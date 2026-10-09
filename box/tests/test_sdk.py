"""The SDK's promises, end to end: real supervisor, real processes. Each test is what a caller
would see, and none names a provider: `pytest --provider modal` runs the same cases on Modal."""

from __future__ import annotations

import json
import shlex
import socket
import ssl
import subprocess
import sys
import textwrap
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from box import sdk
from box.sdk import Ended, Ending, Provider, Running
from box.supervisor import MAX_SERVICES
from box.tests import providers


# TODO(handoff): the live suites are slow because every test rents its own machine (modal ~128 s on
# CPU; runpod: minutes, pods boot in 1-2 min). Plan: local stays the inner loop, live is a merge
# gate; run live with pytest -n (each test owns its machine); share one machine across the tests
# that don't end their session. The runpod suite has not been seen green on the current sdk.
def output(job: sdk.Job) -> str:
    return "".join(c.text for c in job.logs() if c.stream == "stdout")


def gone(provider: Provider, s: sdk.Session) -> bool:
    return s.machine.id not in {m.id for m in provider.list()}


def free_port() -> int:
    """A port nothing on this computer listens on (the local provider shares its network)."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def fetch(endpoint: sdk.Endpoint) -> str | None:
    """GET endpoint's root; None until something answers 200 there."""
    try:
        with urllib.request.urlopen(urllib.request.Request(endpoint.url + "/", headers=endpoint.headers), timeout=10) as r:
            return r.read().decode()
    except (urllib.error.URLError, ConnectionError, TimeoutError):
        return None


def connect(endpoint: sdk.Endpoint) -> socket.socket:
    """A TCP connection to endpoint (TLS for https) that has sent a request and stays open."""
    url = urlsplit(endpoint.url)
    raw = socket.create_connection((url.hostname, url.port or (443 if url.scheme == "https" else 80)), timeout=10)
    conn = ssl.create_default_context().wrap_socket(raw, server_hostname=url.hostname) if url.scheme == "https" else raw
    conn.sendall(f"GET / HTTP/1.1\r\nHost: {url.hostname}\r\n\r\n".encode())
    return conn


# Accepts connections on PORT and holds them open (never answers) for LIFE s: a client that stays.
HOLD = """
import socket, time
s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("0.0.0.0", {port})); s.listen(); s.settimeout(1)
held, end = [], time.time() + {life}
while time.time() < end:
    try: held.append(s.accept()[0])
    except TimeoutError: pass
"""


def eventually(predicate: Callable[[], bool], timeout_s: float = 10.0) -> None:
    give_up = time.monotonic() + timeout_s
    while not predicate():
        assert time.monotonic() < give_up, "timed out"
        time.sleep(0.2)


def test_exit_code_comes_from_the_process_not_its_output(launch: Callable) -> None:
    with launch(deadline_s=600) as s:
        job = s.run("echo 'box: cmd exited 0'; exit 3")
        assert job.wait() == Ending("exited", 3)
        assert output(job) == "box: cmd exited 0\n"


def test_put_then_run_then_get(launch: Callable, tmp_path: Path) -> None:
    src = tmp_path / "src"
    (src / "pkg" / "__pycache__").mkdir(parents=True)
    (src / "pkg" / "a.txt").write_text("a")
    (src / "pkg" / "__pycache__" / "x.pyc").write_text("junk")
    with launch(deadline_s=600) as s:
        work = f"{s.machine.root}/work"
        s.put(src, work, ignore=("**/__pycache__",))
        job = s.run(f"cd {work} && ls -R . > listing && cp pkg/a.txt out.txt")
        assert job.wait() == Ending("exited", 0)
        s.get(work, tmp_path / "back")
    assert (tmp_path / "back" / "out.txt").read_text() == "a"
    assert "__pycache__" not in (tmp_path / "back" / "listing").read_text()


def test_a_session_runs_jobs_in_order(launch: Callable) -> None:
    with launch(deadline_s=600) as s:
        first, second = s.run("echo one"), s.run("echo two")
        assert (second.wait(), first.wait()) == (Ending("exited", 0), Ending("exited", 0))
        assert first.status()["ended"] <= second.status()["started"]


def test_crashed_job_still_runs_its_hook(launch: Callable) -> None:
    with launch(deadline_s=600) as s:
        job = s.run("echo partial > $BOX_JOB_DIR/out; exit 1", on_exit="echo $BOX_EXIT_CODE $BOX_REASON $(cat out) > hook", hook_budget_s=30)
        assert job.wait() == Ending("exited", 1, hook_exit_code=0)
        assert s.machine.read(f"{job.dir}/hook").decode() == "1 exited partial\n"


def test_deadline_kills_the_job_in_time_for_its_hook_then_ends_the_box(launch: Callable, provider: Provider, scale: float) -> None:
    s = launch(deadline_s=int(3 * scale))
    job = s.run("sleep 999", on_exit="echo $BOX_REASON > $BOX_JOB_DIR/hook", hook_budget_s=1 * scale)
    assert job.wait() == Ending("deadline", -15, hook_exit_code=0)
    assert s.status() == Ended("deadline")  # still readable: the machine lingers while its holder heartbeats
    assert s.machine.read(f"{job.dir}/hook").decode() == "deadline\n"
    s.close()
    assert gone(provider, s)


def test_closing_mid_job_still_runs_its_hook(launch: Callable, provider: Provider) -> None:
    s = launch(deadline_s=600)
    job = s.run("sleep 999", on_exit="echo $BOX_REASON", hook_budget_s=30)
    eventually(lambda: (job.status() or {}).get("state") == "running", timeout_s=60)
    s._stop_holding()
    s.machine.exec(f"touch {s.machine.root}/stop")  # close() minus its terminate, so the status stays readable
    assert job.wait() == Ending("stopped", -15, hook_exit_code=0)
    s.close()
    assert gone(provider, s)


def test_kill_reaches_grandchildren_and_the_session_goes_on(launch: Callable) -> None:
    with launch(deadline_s=600) as s:
        job = s.run("sleep 777 & sleep 778; wait")
        eventually(lambda: (job.status() or {}).get("state") == "running", timeout_s=60)
        job.kill()
        assert job.wait().reason == "killed"
        assert s.machine.exec("pgrep -f 'sleep 77[78]'")[1] == ""
        assert s.run("echo after").wait() == Ending("exited", 0)


def test_a_vanished_client_loses_the_lease_and_the_box_ends(name: str, provider: Provider, tmp_path: Path, scale: float) -> None:
    client = textwrap.dedent(f"""
        from pathlib import Path
        from box import sdk
        from box.tests import providers
        p = providers.make({name!r}, Path({str(tmp_path / "machines")!r}))
        s = sdk.launch(p, **providers.launch_kw({name!r}), deadline_s=600, lease_ttl_s={2 * scale})
        s.run("sleep 999")
        print(s.id, flush=True)
        import time; time.sleep(999)
    """)
    proc = subprocess.Popen([sys.executable, "-c", client], stdout=subprocess.PIPE, text=True)
    session_id = proc.stdout.readline().strip()
    proc.kill()  # SIGKILL: no cleanup, no goodbye
    s = sdk.attach(provider, session_id)
    eventually(lambda: gone(provider, s), timeout_s=20 * scale)


def test_released_session_finishes_its_job_then_ends_itself(launch: Callable, provider: Provider, scale: float) -> None:
    s = launch(deadline_s=600, lease_ttl_s=2 * scale)
    job = s.run(f"sleep {2 * scale}; echo done", on_exit="echo saved")
    s.release()  # this process stops heartbeating; the lease no longer applies
    assert job.wait() == Ending("exited", 0, hook_exit_code=0)
    eventually(lambda: gone(provider, s), timeout_s=10 * scale)


def test_another_process_can_attach_and_read_logs_and_status(launch: Callable, provider: Provider) -> None:
    with launch(deadline_s=600) as s:
        first = s.run("echo hello; echo oops >&2")
        first.wait()
        again = sdk.attach(provider, s.id)
        assert s.machine.id in {m.id for m in provider.list()}
        logs = [(c.stream, c.text) for c in sdk.Job(again, first.id).logs()]  # a job id is all another process needs
    assert ("stdout", "hello\n") in logs and ("stderr", "oops\n") in logs


def test_a_session_has_its_own_id_and_attach_finds_it_by_that(launch: Callable, provider: Provider) -> None:
    with launch(deadline_s=600) as s, launch(deadline_s=600) as other:
        assert s.id != s.machine.id
        assert sdk.attach(provider, s.id).machine.id == s.machine.id
        assert sdk.attach(provider, other.id).machine.id == other.machine.id
        with pytest.raises(LookupError):
            sdk.attach(provider, "s-000000000000")


def test_labels_are_the_callers_and_box_stamps_only_its_own(launch: Callable, provider: Provider) -> None:
    with launch(deadline_s=600, labels={"box.user": "reader-7@relay"}) as s:
        assert [m.id for m in provider.list({"box.user": "reader-7@relay"})] == [s.machine.id]
    with pytest.raises(ValueError, match="box's own"):
        launch(deadline_s=600, labels={sdk.LABEL_SESSION: "s-mine"})


def test_a_session_is_running_until_it_ends_and_then_says_why(launch: Callable) -> None:
    s = launch(deadline_s=600)
    running = s.status()
    assert isinstance(running, Running)
    assert running.deadline_at - running.started_at == 600
    s.run("sleep 2")  # wait() starts watching well before the session can end
    s.release()  # ends itself once no job is left
    assert s.wait() == Ended("released")
    assert s.status() == Ended("released")  # final: the machine is gone, the answer is not
    s.close()


def test_a_closed_session_was_stopped(launch: Callable) -> None:
    with launch(deadline_s=600) as s:
        s.run("sleep 999")
    assert s.status() == Ended("stopped")


def test_a_machine_gone_without_a_word_is_machine_lost(launch: Callable) -> None:
    s = launch(deadline_s=600)
    s.machine.terminate()  # the provider's hard stop: no supervisor gets to write why
    assert s.wait() == Ended("machine_lost")
    s.close()


def test_waiting_on_a_session_is_bounded(launch: Callable) -> None:
    with launch(deadline_s=600) as s, pytest.raises(TimeoutError):
        s.wait(timeout_s=1)


def test_a_port_declared_at_launch_is_reachable_through_expose(launch: Callable, scale: float) -> None:
    port = free_port()
    with launch(deadline_s=600, ports=(port,)) as s:
        s.run(f"mkdir -p www && echo hello from the box > www/index.html && exec python3 -m http.server {port} --directory www")
        endpoint = s.expose(port)
        eventually(lambda: fetch(endpoint) == "hello from the box\n", timeout_s=30 * scale)
        with pytest.raises(ValueError, match="not declared"):
            s.expose(port + 1)


def test_an_open_connection_to_an_exposed_port_is_not_idle(launch: Callable, scale: float) -> None:
    port, idle_s = free_port(), 3 * scale
    s = launch(deadline_s=600, idle_timeout_s=idle_s, ports=(port,))
    hold = HOLD.format(port=port, life=int(10 * idle_s))
    s.machine.exec(f"nohup python3 -c {shlex.quote(hold)} >/dev/null 2>&1 &")  # not a job: a job is never idle
    eventually(lambda: s.machine.exec(f"python3 -c 'import socket; socket.create_connection((\"127.0.0.1\", {port}), 1)'")[0] == 0)
    conn = connect(s.expose(port))
    time.sleep(2 * idle_s)  # no job all along: only the connection keeps it from idling
    assert isinstance(s.status(), Running)
    conn.close()
    assert s.wait(timeout_s=10 * idle_s) == Ended("idle")
    s.close()


def test_run_job_is_launch_put_run_get_close(name: str, provider: Provider, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "in.txt").write_text("x")
    ending = sdk.run_job(
        provider, "cd /tmp/w && cat in.txt && mkdir -p out && cp in.txt out/", deadline_s=600,
        put=[(str(src), "/tmp/w")], get=[("/tmp/w/out", str(tmp_path / "out"))], **providers.launch_kw(name),
    )  # fmt: skip
    assert ending == Ending("exited", 0)
    assert capsys.readouterr().out == "x"
    assert (tmp_path / "out" / "in.txt").read_text() == "x"


def test_a_hook_budget_that_cannot_fit_is_refused(launch: Callable) -> None:
    with launch(deadline_s=60) as s, pytest.raises(ValueError, match="does not fit"):
        s.run("true", on_exit="true", hook_budget_s=300)


def test_following_a_released_session_sees_its_last_line_and_exit(launch: Callable, provider: Provider, scale: float) -> None:
    s = launch(deadline_s=600)
    job = s.run(f"sleep {1 * scale}; echo last; exit 4")
    s.release()  # detached: the machine ends itself right after the job
    follower = sdk.Job(sdk.attach(provider, s.id), job.id)
    assert "".join(c.text for c in follower.logs(follow=True)) == "last\n"
    assert follower.wait() == Ending("exited", 4)  # still readable: the machine lingers while we read
    eventually(lambda: gone(provider, s), timeout_s=60)


def test_a_service_runs_beside_the_queue_and_is_not_work_for_idleness(launch: Callable, scale: float) -> None:
    port, idle_s = free_port(), 3 * scale
    s = launch(deadline_s=600, idle_timeout_s=idle_s, ports=(port,))
    server = s.serve(f"exec python3 -m http.server {port}")
    job = s.run("echo queued after a service")  # the service never holds the queue up
    assert job.wait() == Ending("exited", 0)
    eventually(lambda: fetch(s.expose(port)) is not None, timeout_s=30 * scale)
    assert (server.status() or {}).get("state") == "running"
    assert s.wait(timeout_s=20 * idle_s) == Ended("idle")  # nobody connected: idle, though the server still ran
    assert server.wait() == Ending("idle", -15)  # killed (SIGTERM) when the session ended
    s.close()


def test_a_released_session_lives_while_its_service_does(launch: Callable, provider: Provider, scale: float) -> None:
    s = launch(deadline_s=600, lease_ttl_s=2 * scale)
    server = s.serve("sleep 999")
    eventually(lambda: (server.status() or {}).get("state") == "running", timeout_s=30 * scale)
    s.release()
    time.sleep(3 * scale)  # past the lease TTL: released, and a service is something left
    assert isinstance(s.status(), Running)
    server.kill()
    assert server.wait().reason == "killed"
    eventually(lambda: gone(provider, s), timeout_s=20 * scale)  # nothing left: ends as released


def test_logs_resume_from_byte_offsets(launch: Callable) -> None:
    with launch(deadline_s=600) as s:
        job = s.run("printf 'héllo\\n'; printf 'oops\\n' >&2")
        job.wait()
        out = len("hé".encode())
        assert list(job.logs(after=(out, 2))) == [sdk.LogChunk("stdout", "llo\n", (7, 2)), sdk.LogChunk("stderr", "ps\n", (7, 5))]


def test_a_caller_can_name_the_session_before_launch_returns(launch: Callable, provider: Provider) -> None:
    session_id = sdk.new_session_id()
    with launch(deadline_s=600, session_id=session_id) as s:
        assert s.id == session_id
        assert sdk.attach(provider, session_id).machine.id == s.machine.id
    with pytest.raises(ValueError, match="new_session_id"):
        launch(deadline_s=600, session_id="mine")


def test_services_past_the_limit_are_refused_and_the_session_goes_on(launch: Callable, scale: float) -> None:
    with launch(deadline_s=600) as s:
        for _ in range(MAX_SERVICES):
            s.serve("sleep 999")
        with pytest.raises(ValueError, match="services"):
            s.serve("sleep 999")
        # a second client racing the first gets past that check: the supervisor refuses the spec, and lives
        extra = sdk.Job(s, "9999999999-extra", "services")
        s.machine.write(f"{s.machine.root}/services/{extra.id}.spec.tmp", json.dumps({"cmd": "sleep 999"}).encode())
        s.machine.exec(f"mkdir -p {extra.dir} && mv {s.machine.root}/services/{extra.id}.spec.tmp {extra.dir}/spec.json")
        assert extra.wait() == Ending("refused", None)
        assert isinstance(s.status(), Running)
        assert s.run("echo after").wait() == Ending("exited", 0)


def test_a_character_split_across_reads_is_followed_whole(launch: Callable, scale: float) -> None:
    with launch(deadline_s=600) as s:
        job = s.run(rf"printf 'caf\xc3'; sleep {2 * scale}; printf '\xa9\n'")  # é = c3 a9, a read in between
        chunks = list(job.logs(follow=True))
    assert "".join(c.text for c in chunks) == "café\n"
    assert chunks[-1].end == (len("café\n".encode()), 0)


def test_a_session_lists_its_jobs_and_its_services_apart(launch: Callable) -> None:
    with launch(deadline_s=600) as s:
        server = s.serve("sleep 999")
        job = s.run("echo queued")
        job.wait()
        assert ([j.id for j in s.jobs()], [j.id for j in s.services()]) == ([job.id], [server.id])
