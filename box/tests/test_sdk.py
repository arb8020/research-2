"""The SDK's promises, end to end: real supervisor, real processes. Each test is what a caller
would see, and none names a provider: `pytest --provider modal` runs the same cases on Modal."""

from __future__ import annotations

import subprocess
import sys
import textwrap
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from box import sdk
from box.sdk import Ending, Provider
from box.tests import providers


# TODO(handoff): the live suites are slow because every test rents its own machine (modal ~128 s on
# CPU; runpod: minutes, pods boot in 1-2 min). Plan: local stays the inner loop, live is a merge
# gate; run live with pytest -n (each test owns its machine); share one machine across the tests
# that don't end their session. The runpod suite has not been seen green on the current sdk.
@pytest.fixture
def name(request: pytest.FixtureRequest) -> str:
    return request.config.getoption("--provider")


@pytest.fixture
def provider(name: str, tmp_path: Path) -> Provider:
    return providers.make(name, tmp_path / "machines")


@pytest.fixture
def scale(name: str) -> float:
    return providers.SCALE[name]


@pytest.fixture
def launch(provider: Provider, name: str) -> Callable[..., sdk.Session]:
    return lambda **kw: sdk.launch(provider, **providers.launch_kw(name), **kw)


def output(job: sdk.Job) -> str:
    return "".join(text for stream, text in job.logs() if stream == "stdout")


def gone(provider: Provider, s: sdk.Session) -> bool:
    return s.machine.id not in {m.id for m in provider.list()}


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
    assert s.ended() == "deadline"  # still readable: the machine lingers while its holder heartbeats
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
        logs = list(sdk.Job(again, first.id).logs())  # a job id is all another process needs
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
    assert "".join(t for _, t in follower.logs(follow=True)) == "last\n"
    assert follower.wait() == Ending("exited", 4)  # still readable: the machine lingers while we read
    eventually(lambda: gone(provider, s), timeout_s=60)
