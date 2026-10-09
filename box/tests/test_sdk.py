"""The SDK's promises, end to end: real supervisor, real processes. Each test is what a caller
would see, and none names a provider: `pytest --provider modal` runs the same cases on Modal."""

from __future__ import annotations

import contextlib
import json
import shlex
import socket
import ssl
import subprocess
import sys
import textwrap
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from box import sdk
from box.sdk import Ended, Ending, Provider, Running
from box.supervisor import MAX_CEILING_S, MAX_SERVICES
from box.tests import providers

JOB_S = 300  # every test job's max_duration_s: far past any of them, except where a test times one out


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
    with launch(ceiling_s=600) as s:
        job = s.run("echo 'box: cmd exited 0'; exit 3", max_duration_s=JOB_S)
        assert job.wait() == Ending("exited", 3)
        assert output(job) == "box: cmd exited 0\n"


def test_put_then_run_then_get(launch: Callable, tmp_path: Path) -> None:
    src = tmp_path / "src"
    (src / "pkg" / "__pycache__").mkdir(parents=True)
    (src / "pkg" / "a.txt").write_text("a")
    (src / "pkg" / "__pycache__" / "x.pyc").write_text("junk")
    with launch(ceiling_s=600) as s:
        work = f"{s.machine.root}/work"
        s.put(src, work, ignore=("**/__pycache__",))
        job = s.run(f"cd {work} && ls -R . > listing && cp pkg/a.txt out.txt", max_duration_s=JOB_S)
        assert job.wait() == Ending("exited", 0)
        s.get(work, tmp_path / "back")
    assert (tmp_path / "back" / "out.txt").read_text() == "a"
    assert "__pycache__" not in (tmp_path / "back" / "listing").read_text()


def test_a_session_runs_jobs_in_order(launch: Callable) -> None:
    with launch(ceiling_s=600) as s:
        first, second = s.run("echo one", max_duration_s=JOB_S), s.run("echo two", max_duration_s=JOB_S)
        assert (second.wait(), first.wait()) == (Ending("exited", 0), Ending("exited", 0))
        assert first.status().ended_at <= second.status().started_at


def test_crashed_job_still_runs_its_hook(launch: Callable) -> None:
    with launch(ceiling_s=600) as s:
        job = s.run("echo partial > $BOX_JOB_DIR/out; exit 1", max_duration_s=JOB_S, on_exit="echo $BOX_EXIT_CODE $BOX_REASON $(cat out) > hook", hook_budget_s=30)
        assert job.wait() == Ending("exited", 1, hook_exit_code=0)
        assert s.machine.read(f"{job.dir}/hook").decode() == "1 exited partial\n"


def test_terminating_a_machine_mid_hook_ends_the_hook_too(launch: Callable, name: str) -> None:
    if name != "local":
        pytest.skip("reads the hook's heartbeat from this computer's disk")
    s = launch(ceiling_s=600)
    job = s.run("exit 0", max_duration_s=JOB_S, on_exit="while true; do touch $BOX_JOB_DIR/hook-beat; sleep 0.1; done", hook_budget_s=300)
    beat = Path(job.dir) / "hook-beat"
    eventually(lambda: isinstance(job.status(), sdk.Hooking) and beat.exists(), timeout_s=60)
    s.machine.terminate()
    eventually(s.machine.gone)
    last = beat.stat().st_mtime
    time.sleep(0.5)
    assert beat.stat().st_mtime == last, "the hook still runs on a machine that says it is gone"


def test_the_lease_running_out_kills_the_job_in_time_for_its_hook_then_ends_the_box(launch: Callable, provider: Provider, scale: float) -> None:
    s = launch(lease_s=3 * scale, ceiling_s=600)
    job = s.run("sleep 999", max_duration_s=JOB_S, on_exit="echo $BOX_REASON > $BOX_JOB_DIR/hook", hook_budget_s=1 * scale)
    assert job.wait() == Ending("lease", -15, hook_exit_code=0)  # killed hook_budget_s before the lease ends
    assert s.wait() == Ended("lease")
    assert s.machine.read(f"{job.dir}/hook").decode() == "lease\n"  # still readable: the machine lingers while we wait
    s.close()
    assert gone(provider, s)


def test_closing_mid_job_still_runs_its_hook(launch: Callable, provider: Provider) -> None:
    s = launch(ceiling_s=600)
    job = s.run("sleep 999", max_duration_s=JOB_S, on_exit="echo $BOX_REASON", hook_budget_s=30)
    eventually(lambda: isinstance(job.status(), sdk.JobRunning), timeout_s=60)
    s.machine.exec(f"touch {s.machine.root}/stop")  # close() minus its terminate, so the status stays readable
    assert job.wait() == Ending("stopped", -15, hook_exit_code=0)
    s.close()
    assert gone(provider, s)


def test_kill_reaches_grandchildren_and_the_session_goes_on(launch: Callable) -> None:
    with launch(ceiling_s=600) as s:
        job = s.run("sleep 777 & sleep 778; wait", max_duration_s=JOB_S)
        eventually(lambda: isinstance(job.status(), sdk.JobRunning), timeout_s=60)
        job.kill()
        assert job.wait().reason == "killed"
        assert s.machine.exec("pgrep -f 'sleep 77[78]'")[1] == ""
        assert s.run("echo after", max_duration_s=JOB_S).wait() == Ending("exited", 0)


def test_a_vanished_client_ends_nothing_and_its_session_ends_with_its_lease(name: str, provider: Provider, tmp_path: Path, scale: float) -> None:
    client = textwrap.dedent(f"""
        from pathlib import Path
        from box import sdk
        from box.tests import providers
        p = providers.make({name!r}, Path({str(tmp_path / "machines")!r}))
        s = sdk.launch(p, **providers.launch_kw({name!r}), lease_s={6 * scale}, ceiling_s=600)
        s.run("sleep 999", max_duration_s={JOB_S})
        print(s.id, flush=True)
        import time; time.sleep(999)
    """)
    proc = subprocess.Popen([sys.executable, "-c", client], stdout=subprocess.PIPE, text=True)
    session_id = proc.stdout.readline().strip()
    proc.kill()  # SIGKILL: no cleanup, no goodbye
    proc.wait()
    s = sdk.attach(provider, session_id=session_id)
    assert isinstance(s.status(), Running)  # detached: its caller going away ends nothing
    assert s.wait(timeout_s=30 * scale) == Ended("lease")  # the lease does
    eventually(lambda: gone(provider, s), timeout_s=20 * scale)


def test_release_ends_the_session_now_and_the_jobs_hook_still_runs(launch: Callable, provider: Provider, scale: float) -> None:
    s = launch(ceiling_s=600)
    job = s.run("sleep 999", max_duration_s=JOB_S, on_exit="echo $BOX_REASON > $BOX_JOB_DIR/hook", hook_budget_s=30)
    eventually(lambda: isinstance(job.status(), sdk.JobRunning), timeout_s=30 * scale)
    lease = s.release()
    assert lease.until <= time.time()
    assert job.wait() == Ending("released", -15, hook_exit_code=0)
    assert s.wait() == Ended("released")
    assert s.machine.read(f"{job.dir}/hook").decode() == "released\n"
    eventually(lambda: gone(provider, s), timeout_s=60 * scale)


def test_extend_clamps_at_the_ceiling_and_a_shorter_extend_is_a_no_op(launch: Callable) -> None:
    with launch(lease_s=60, ceiling_s=120) as s:
        first = s.status().lease
        assert first.ceiling - first.until == pytest.approx(60, abs=1)
        longest = s.extend(time.time() + 10 * 3600)
        assert longest == sdk.Lease(until=first.ceiling, ceiling=first.ceiling)  # clamped, never past the ceiling
        assert s.extend(time.time() + 30) == longest  # shorter: a no-op that says what the lease is
        assert s.status().lease == longest


def test_keep_holds_a_short_lease_and_releases_on_the_way_out(launch: Callable, scale: float) -> None:
    for raises in (False, True):
        s = launch(lease_s=2 * scale, ceiling_s=600)
        with contextlib.suppress(KeyError), s.keep(every_s=0.5 * scale):
            time.sleep(4 * scale)  # twice the first lease: only the renewals keep it
            assert isinstance(s.status(), Running)
            if raises:
                raise KeyError("the body failed")
        assert s.wait(timeout_s=10 * scale) == Ended("released")
        assert not [t for t in threading.enumerate() if t.name.startswith("box-keep-")]  # the renewer was joined
        s.close()


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_keep_retries_a_dropped_renewal_and_raises_any_other_failure_on_the_way_out(launch: Callable, monkeypatch: pytest.MonkeyPatch, scale: float) -> None:
    with launch(ceiling_s=600) as s:
        extend, calls = s.extend, []

        def renewing(until: float) -> sdk.Lease:
            calls.append(until)
            if len(calls) == 2:
                raise sdk.Dropped("a blip")
            if len(calls) == 3:
                raise RuntimeError("not a blip")
            return extend(until)

        monkeypatch.setattr(s, "extend", renewing)
        with pytest.raises(RuntimeError, match="not a blip"), s.keep(every_s=0.5):
            eventually(lambda: len(calls) >= 3, timeout_s=10 * scale)
        assert len(calls) == 3  # the renewer stopped at the failure
        assert s.wait(timeout_s=10 * scale) == Ended("released")


def test_a_job_past_its_max_duration_times_out_and_its_hook_runs(launch: Callable, scale: float) -> None:
    with launch(ceiling_s=600) as s:
        job = s.run("sleep 999", max_duration_s=1 * scale, on_exit="echo $BOX_REASON > $BOX_JOB_DIR/hook", hook_budget_s=30)
        assert job.wait() == Ending("timeout", -15, hook_exit_code=0)
        assert s.machine.read(f"{job.dir}/hook").decode() == "timeout\n"
        assert s.run("echo after", max_duration_s=JOB_S).wait() == Ending("exited", 0)  # the session goes on
        with pytest.raises(ValueError, match="max_duration_s"):
            s.run("true", max_duration_s=0)


def test_another_process_can_attach_and_read_logs_and_status(launch: Callable, provider: Provider) -> None:
    with launch(ceiling_s=600) as s:
        first = s.run("echo hello; echo oops >&2", max_duration_s=JOB_S)
        first.wait()
        again = sdk.attach(provider, session_id=s.id)
        assert s.machine.id in {m.id for m in provider.list()}
        logs = [(c.stream, c.text) for c in sdk.Job(again, first.id).logs()]  # a job id is all another process needs
    assert ("stdout", "hello\n") in logs and ("stderr", "oops\n") in logs


def test_a_session_has_its_own_id_and_attach_finds_it_by_that(launch: Callable, provider: Provider) -> None:
    with launch(ceiling_s=600) as s, launch(ceiling_s=600) as other:
        assert s.id != s.machine.id
        assert sdk.attach(provider, session_id=s.id).machine.id == s.machine.id
        assert sdk.attach(provider, session_id=other.id).machine.id == other.machine.id
        with pytest.raises(LookupError):
            sdk.attach(provider, session_id="s-000000000000")


def test_labels_are_the_callers_and_box_stamps_only_its_own(launch: Callable, provider: Provider) -> None:
    with launch(ceiling_s=600, labels={"box.user": "reader-7@relay"}) as s:
        assert [m.id for m in provider.list({"box.user": "reader-7@relay"})] == [s.machine.id]
    with pytest.raises(ValueError, match="box's own"):
        launch(ceiling_s=600, labels={sdk.LABEL_SESSION: "s-mine"})


def test_a_session_is_running_until_it_ends_and_then_says_why(launch: Callable) -> None:
    s = launch(ceiling_s=600)
    running = s.status()
    assert isinstance(running, Running)
    assert running.lease.until == running.lease.ceiling  # lease_s defaults to ceiling_s
    assert 0 < running.lease.ceiling - running.started_at <= 600  # counted from create, before the boot
    s.run("sleep 2", max_duration_s=JOB_S)  # wait() starts watching well before the session can end
    s.release()  # ends it now: the job is killed
    assert s.wait() == Ended("released")
    assert s.status() == Ended("released")  # final: the machine is gone, the answer is not
    s.close()


def test_a_closed_session_was_stopped(launch: Callable) -> None:
    with launch(ceiling_s=600) as s:
        s.run("sleep 999", max_duration_s=JOB_S)
    assert s.status() == Ended("stopped")


def test_a_machine_gone_without_a_word_is_machine_lost(launch: Callable) -> None:
    s = launch(ceiling_s=600)
    s.machine.terminate()  # the provider's hard stop: no supervisor gets to write why
    assert s.wait() == Ended("machine_lost")
    s.close()


def test_waiting_on_a_session_is_bounded(launch: Callable) -> None:
    with launch(ceiling_s=600) as s, pytest.raises(TimeoutError):
        s.wait(timeout_s=1)


@pytest.mark.needs("ports")
def test_a_port_declared_at_launch_is_reachable_through_expose(launch: Callable, scale: float) -> None:
    port = free_port()
    with launch(ceiling_s=600, ports=(port,)) as s:
        s.run(f"mkdir -p www && echo hello from the box > www/index.html && exec python3 -m http.server {port} --directory www", max_duration_s=JOB_S)
        endpoint = s.expose(port)
        eventually(lambda: fetch(endpoint) == "hello from the box\n", timeout_s=30 * scale)
        assert endpoint.headers == {}  # declared: the URL alone reaches it (an undeclared port: test_dev)


@pytest.mark.needs("ports")
def test_an_open_connection_to_an_exposed_port_is_not_idle(launch: Callable, scale: float) -> None:
    port, idle_s = free_port(), 3 * scale
    s = launch(ceiling_s=600, idle_timeout_s=idle_s, ports=(port,))
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
        provider, "cd /tmp/w && cat in.txt && mkdir -p out && cp in.txt out/", ceiling_s=600, max_duration_s=JOB_S,
        put=[(str(src), "/tmp/w")], get=[("/tmp/w/out", str(tmp_path / "out"))], **providers.launch_kw(name),
    )  # fmt: skip
    assert ending == Ending("exited", 0)
    assert capsys.readouterr().out == "x"
    assert (tmp_path / "out" / "in.txt").read_text() == "x"


def test_a_hook_budget_that_cannot_fit_is_refused(launch: Callable) -> None:
    with launch(ceiling_s=60) as s, pytest.raises(ValueError, match="does not fit"):
        s.run("true", max_duration_s=JOB_S, on_exit="true", hook_budget_s=300)


def test_following_a_session_that_ends_after_its_job_sees_its_last_line_and_exit(launch: Callable, provider: Provider, scale: float) -> None:
    s = launch(ceiling_s=600, idle_timeout_s=1 * scale)  # as `box run --detach`: idle ends it once the job is done
    job = s.run(f"sleep {1 * scale}; echo last; exit 4", max_duration_s=JOB_S)
    follower = sdk.Job(sdk.attach(provider, session_id=s.id), job.id)
    assert "".join(c.text for c in follower.logs(follow=True)) == "last\n"
    assert follower.wait() == Ending("exited", 4)  # still readable: the machine lingers while we read
    eventually(lambda: gone(provider, s), timeout_s=60)


@pytest.mark.needs("ports")
def test_a_service_runs_beside_the_queue_and_is_not_work_for_idleness(launch: Callable, scale: float) -> None:
    port, idle_s = free_port(), 3 * scale
    s = launch(ceiling_s=600, idle_timeout_s=idle_s, ports=(port,))
    server = s.serve(f"exec python3 -m http.server {port}")
    job = s.run("echo queued after a service", max_duration_s=JOB_S)  # the service never holds the queue up
    assert job.wait() == Ending("exited", 0)
    eventually(lambda: fetch(s.expose(port)) is not None, timeout_s=30 * scale)
    assert isinstance(server.status(), sdk.JobRunning)
    assert s.wait(timeout_s=20 * idle_s) == Ended("idle")  # nobody connected: idle, though the server still ran
    assert server.wait() == Ending("idle", -15)  # killed (SIGTERM) when the session ended
    s.close()


def test_a_service_lives_until_the_lease_ends(launch: Callable, provider: Provider, scale: float) -> None:
    s = launch(lease_s=3 * scale, ceiling_s=600)
    server = s.serve("sleep 999")  # a service has no max duration
    eventually(lambda: isinstance(server.status(), sdk.JobRunning), timeout_s=30 * scale)
    assert s.wait(timeout_s=30 * scale) == Ended("lease")
    assert server.wait() == Ending("lease", -15)
    eventually(lambda: gone(provider, s), timeout_s=60 * scale)


def test_logs_resume_from_byte_offsets(launch: Callable) -> None:
    with launch(ceiling_s=600) as s:
        job = s.run("printf 'héllo\\n'; printf 'oops\\n' >&2", max_duration_s=JOB_S)
        job.wait()
        out = len("hé".encode())
        assert list(job.logs(after=(out, 2))) == [sdk.LogChunk("stdout", "llo\n", (7, 2)), sdk.LogChunk("stderr", "ps\n", (7, 5))]


def test_a_caller_can_name_the_session_before_launch_returns(launch: Callable, provider: Provider) -> None:
    session_id = sdk.new_session_id()
    with launch(ceiling_s=600, session_id=session_id) as s:
        assert s.id == session_id
        assert sdk.attach(provider, session_id=session_id).machine.id == s.machine.id
    with pytest.raises(ValueError, match="new_session_id"):
        launch(ceiling_s=600, session_id="mine")


def test_services_past_the_limit_are_refused_and_the_session_goes_on(launch: Callable, scale: float) -> None:
    with launch(ceiling_s=600) as s:
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
        assert s.run("echo after", max_duration_s=JOB_S).wait() == Ending("exited", 0)


def test_a_character_split_across_reads_is_followed_whole(launch: Callable, scale: float) -> None:
    with launch(ceiling_s=600) as s:
        job = s.run(rf"printf 'caf\xc3'; sleep {2 * scale}; printf '\xa9\n'", max_duration_s=JOB_S)  # é = c3 a9, a read in between
        chunks = list(job.logs(follow=True))
    assert "".join(c.text for c in chunks) == "café\n"
    assert chunks[-1].end == (len("café\n".encode()), 0)


def test_a_session_lists_its_jobs_and_its_services_apart(launch: Callable) -> None:
    with launch(ceiling_s=600) as s:
        server = s.serve("sleep 999")
        job = s.run("echo queued", max_duration_s=JOB_S)
        job.wait()
        assert ([j.id for j in s.jobs()], [j.id for j in s.services()]) == ([job.id], [server.id])


def test_create_returns_before_the_supervisor_is_up_and_launch_is_create_wait_up(name: str, provider: Provider) -> None:
    s = sdk.create(provider, ceiling_s=600, **providers.launch_kw(name))
    assert sdk.attach(provider, session_id=s.id).machine.id == s.machine.id  # it exists, booting or not
    s.wait_up(timeout_s=120)
    assert isinstance(s.status(), Running)
    assert s.run("echo up", max_duration_s=JOB_S).wait() == Ending("exited", 0)
    s.close()
    assert s.status() == Ended("stopped")


def test_close_gives_a_receipt_once_the_supervisor_said_it_ended_and_the_provider_said_the_machine_is_gone(
    launch: Callable, provider: Provider
) -> None:  # fmt: skip
    s = launch(ceiling_s=600)
    s.run("sleep 999", max_duration_s=JOB_S)
    before = time.time()
    receipt = s.close()
    assert (receipt.session_id, receipt.machine_id) == (s.id, s.machine.id)
    assert receipt.ended == Ended("stopped")
    assert receipt.supervisor_confirmed
    assert before < receipt.machine_gone_at <= time.time()
    assert s.machine.gone()
    assert gone(provider, s)
    assert s.status() == Ended("stopped")  # a closed session still answers as before
    assert s.wait() == Ended("stopped")


def test_closing_a_machine_whose_supervisor_was_killed_terminates_it_and_the_receipt_says_so(launch: Callable, provider: Provider) -> None:
    s = launch(ceiling_s=600)
    s.run("sleep 999", max_duration_s=JOB_S)
    providers.kill_supervisor(s.machine)  # no ended.json; on macOS its job lives on (no PDEATHSIG)
    receipt = s.close()
    assert receipt.ended == Ended("machine_lost")
    assert not receipt.supervisor_confirmed
    assert s.machine.gone()  # the job too: terminate() reached it
    assert gone(provider, s)


def test_a_supervisor_that_never_answers_is_terminated_and_its_receipt_is_machine_lost(launch: Callable, scale: float) -> None:
    s = launch(ceiling_s=600)
    providers.freeze_supervisor(s.machine)  # alive, so status() still reads Running: only the bound ends the wait
    t0 = time.monotonic()
    receipt = s.close(timeout_s=2 * scale)
    assert time.monotonic() - t0 >= 2 * scale  # it waited out the bound, then terminated
    assert receipt.ended == Ended("machine_lost")
    assert not receipt.supervisor_confirmed
    assert s.machine.gone()


class NeverGone:
    """A machine whose provider never says it is gone (an API that keeps answering for it)."""

    def __init__(self, inner: sdk.Machine) -> None:
        self.inner = inner

    def gone(self) -> bool:
        return False

    def __getattr__(self, attr: str) -> object:
        return getattr(self.inner, attr)


def test_close_raises_within_its_bound_when_the_provider_never_confirms_the_machine_is_gone(launch: Callable) -> None:
    s = launch(ceiling_s=600)
    real = s.machine
    s.machine = NeverGone(real)
    t0 = time.monotonic()
    with pytest.raises(sdk.NotGone, match="still has it"):
        s.close(gone_timeout_s=2)
    assert time.monotonic() - t0 < 2 + 5  # the bound, plus the stop and terminate before it
    assert s.status() == Ended("stopped")  # the supervisor did end; only the proof is missing
    assert real.gone()


class SlowBoot:
    """A provider whose machines take boot_s to start their entrypoint (as a cloud's do: an
    unpinned Modal L4 took ~6 min), and which notes the backstop (timeout_s) each launch asked for."""

    def __init__(self, inner: Provider, boot_s: float) -> None:
        self.inner, self.boot_s, self.name, self.backstops = inner, boot_s, inner.name, []

    def launch(self, *, entrypoint: list[str], timeout_s: int, **kw: object) -> sdk.Machine:
        self.backstops.append(timeout_s)
        slow = ["bash", "-c", f'sleep {self.boot_s}; exec "$@"', "boot", *entrypoint]
        return self.inner.launch(entrypoint=slow, timeout_s=timeout_s, **kw)

    def __getattr__(self, attr: str) -> object:
        return getattr(self.inner, attr)


def test_the_ceiling_and_the_backstop_count_from_create_not_from_boot(name: str, provider: Provider, scale: float) -> None:
    slow = SlowBoot(provider, boot_s=3 * scale)
    created_at = time.time()
    with sdk.launch(slow, ceiling_s=600, **providers.launch_kw(name)) as s:
        running = s.status()
        assert running.started_at - created_at >= 3 * scale  # it did boot slowly
        assert running.lease.ceiling == pytest.approx(created_at + 600, abs=1)  # yet its ceiling counts from create
        assert int(s.machine.labels[sdk.LABEL_CEILING]) == int(running.lease.ceiling)
        assert slow.backstops == [pytest.approx(running.lease.ceiling - created_at + sdk.BACKSTOP_MARGIN_S, abs=2)]


def test_ceilings_past_48_hours_and_leases_past_the_ceiling_are_refused(provider: Provider, tmp_path: Path) -> None:
    for bad in ({"ceiling_s": MAX_CEILING_S + 1}, {"ceiling_s": 0}, {"lease_s": 601, "ceiling_s": 600}, {"lease_s": 0}):
        with pytest.raises(ValueError, match="lease_s|ceiling_s"):
            sdk.create(provider, **bad)
    assert provider.list() == []  # refused before any machine was made
    now = time.time()  # the supervisor asserts the same of the absolute times it is given (the pair)
    for lease_until, ceiling in ((now + 60, now + MAX_CEILING_S + 1), (now + 120, now + 60)):
        argv = ["--root", str(tmp_path / "root"), "--created-at", repr(now), "--lease-until", repr(lease_until),
                "--ceiling", repr(ceiling), "--host", "h", "--pid", "1", "--session-id", "s-000000000000"]  # fmt: skip
        done = subprocess.run([sys.executable, str(sdk.SUPERVISOR), *argv], capture_output=True, text=True, timeout=30)
        assert done.returncode != 0
        assert "AssertionError" in done.stderr
        assert not (tmp_path / "root").exists()  # before it made anything


def test_a_stream_yields_output_before_its_command_exits(launch: Callable, scale: float) -> None:
    with launch(ceiling_s=600) as s:
        go = f"{s.machine.root}/go"
        cmd = f"echo first; while [ ! -e {go} ]; do sleep 0.05; done; echo second >&2"
        with s.machine.stream(cmd, timeout_s=60 * scale) as stream:
            chunks = iter(stream)
            assert next(chunks) == ("stdout", b"first\n")  # live: the command is still waiting on us
            s.machine.exec(f"touch {go}")
            assert b"".join(data for name, data in chunks if name == "stderr") == b"second\n"
        assert stream.rc == 0


def test_closing_a_stream_kills_its_command(launch: Callable, scale: float) -> None:
    with launch(ceiling_s=600) as s:
        with s.machine.stream("echo $$; exec sleep 999", timeout_s=60 * scale) as stream:
            pid = int(next(iter(stream))[1])
            assert s.machine.exec(f"kill -0 {pid}")[0] == 0  # running
        eventually(lambda: s.machine.exec(f"kill -0 {pid}")[0] != 0, timeout_s=10 * scale)


def test_a_stream_is_bounded_in_time_and_in_silence(launch: Callable, scale: float) -> None:
    with launch(ceiling_s=600) as s:
        with pytest.raises(sdk.Dropped, match="no output"), s.machine.stream("echo hi; exec sleep 999", timeout_s=60 * scale, quiet_s=2 * scale) as stream:
            list(stream)
        with pytest.raises(TimeoutError, match="past"), s.machine.stream("while true; do echo .; sleep 0.2; done", timeout_s=3 * scale) as stream:
            list(stream)


def test_a_follower_that_leaves_and_comes_back_misses_nothing_and_repeats_nothing(launch: Callable, scale: float) -> None:
    with launch(ceiling_s=600) as s:
        go = f"{s.machine.root}/go"
        # é = c3 a9: the first follower leaves between its two bytes
        job = s.run(rf"printf 'caf\xc3'; printf 'e1\n' >&2; while [ ! -e {go} ]; do sleep 0.05; done; printf '\xa9 ok\n'; printf 'e2\n' >&2", max_duration_s=600)
        first = job.logs(follow=True)
        seen = [next(first), next(first)]
        first.close()  # leaves: its stream on the machine is killed
        s.machine.exec(f"touch {go}")
        rest = list(job.logs(after=seen[-1].end, follow=True))
        both = seen + rest
        assert "".join(c.text for c in both if c.stream == "stdout") == "café ok\n"
        assert "".join(c.text for c in both if c.stream == "stderr") == "e1\ne2\n"
        assert both[-1].end == (len("café ok\n".encode()), len("e1\ne2\n"))
        assert [c.end for c in both] == sorted(c.end for c in both)  # the cursor only moves on


def test_a_follower_reconnects_after_a_dropped_stream_and_stops_at_any_other_error(launch: Callable, monkeypatch: pytest.MonkeyPatch) -> None:
    with launch(ceiling_s=600) as s:
        job = s.run("echo one; echo two", max_duration_s=JOB_S)
        job.wait()
        stream = s.machine.stream
        failures: list[BaseException] = [sdk.Dropped("the channel went away")]

        def flaky(cmd: str, **kw: object) -> sdk.Stream:
            if failures:
                raise failures.pop()
            return stream(cmd, **kw)

        monkeypatch.setattr(s.machine, "stream", flaky)
        monkeypatch.setattr(sdk, "FOLLOW_BACKOFF_S", 0.01)
        assert "".join(c.text for c in job.logs(follow=True)) == "one\ntwo\n"
        failures.append(RuntimeError("a bug, not a drop"))
        with pytest.raises(RuntimeError, match="a bug, not a drop"):
            list(job.logs(follow=True))
        assert failures == []


def test_closing_a_stream_reports_a_failed_kill_and_raises_a_kill_bug_after_joining_its_readers(capsys: pytest.CaptureFixture) -> None:
    from box.providers.pump import Pumped

    def waits_for_close(emit: Callable[[str, bytes], None]) -> None:
        time.sleep(0.2)

    for kill_raises, raised in ((ConnectionResetError("the channel went away"), None), (KeyError("a bug"), KeyError)):

        def kill(e: BaseException = kill_raises) -> None:
            raise e

        stream = Pumped([waits_for_close], kill=kill, wait=lambda: 0, timeout_s=10, quiet_s=None, label="test")
        with pytest.raises(raised) if raised else contextlib.nullcontext():
            stream.close()
        assert not [t for t in threading.enumerate() if t.name.startswith("box-stream-test")]  # joined either way
    assert "killing a stream's command failed: ConnectionResetError" in capsys.readouterr().err
