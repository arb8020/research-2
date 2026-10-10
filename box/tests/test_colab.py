"""What is particular to the Colab provider, on a fake Colab account (tests/fake_colab.py). The SDK's
own promises run on it too: `pytest --provider colab-fake`."""

from __future__ import annotations

import io
import json
import re
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from box import sdk
from box.providers import colab as colab_provider
from box.providers.colab import Colab, ColabMachine
from box.sdk import Ending, Gone
from box.store import DirStore
from box.tests.fake_colab import FakeBackend, FakeRuntime


@pytest.fixture
def backend(tmp_path: Path) -> FakeBackend:
    return FakeBackend(tmp_path / "account")


@pytest.fixture
def log() -> io.StringIO:
    return io.StringIO()


@pytest.fixture
def colab(backend: FakeBackend, log: io.StringIO) -> Iterator[Callable[..., Colab]]:
    made: list[Colab] = []

    def make(**kw: object) -> Colab:
        made.append(Colab(backend, log=log, **kw))
        return made[-1]

    yield make
    for c in made:
        c.close()


def eventually(predicate: Callable[[], bool], timeout_s: float = 20.0) -> None:
    give_up = time.monotonic() + timeout_s
    while not predicate():
        assert time.monotonic() < give_up, "timed out"
        time.sleep(0.2)


def entrypoint(seconds: float) -> list[str]:
    return ["bash", "-c", f"mkdir -p $BOX_ROOT && touch $BOX_ROOT/lease && sleep {seconds}"]


def raw_launch(c: Colab, timeout_s: int, **kw: object) -> ColabMachine:
    """Provider.launch itself, as create() calls it, with a supervisor that only sleeps."""
    args = {"gpu": "T4", "image": None, "entrypoint": entrypoint(999), "env": {}, "labels": {"box.by": "box"}, "ports": [], "mounts": []}
    return c.launch(**{**args, **kw}, timeout_s=timeout_s)


@pytest.mark.parametrize(
    ("gpu", "accelerator"),
    [(None, "NONE"), ("T4", "T4"), ("l4", "L4"), ("A100-40GB", "A100"), ("H100", "H100"), ("RTX-PRO-6000", "G4"),
     ("TPU-v5e-1", "V5E1"), ("TPU-v6e-1", "V6E1"), ("T4:1", "T4")],
)  # fmt: skip
def test_canonical_names_map_to_colab_accelerators(gpu: str | None, accelerator: str) -> None:
    assert colab_provider.colab_accelerator(gpu) == accelerator


@pytest.mark.parametrize(
    ("gpu", "error"),
    [("A100-80GB", "Colab does not rent 'A100-80GB'; it rents T4, L4, A100-40GB"), ("T4:2", "one accelerator"), ("K80", "unknown GPU")],
)
def test_what_colab_does_not_rent_is_refused_by_name(gpu: str, error: str) -> None:
    with pytest.raises((ValueError, KeyError), match=re.escape(error)):
        colab_provider.colab_accelerator(gpu)


def test_variant_follows_the_accelerator() -> None:
    assert [colab_provider.variant(a) for a in ("NONE", "T4", "V6E1")] == ["DEFAULT", "GPU", "TPU"]


def test_an_image_is_refused_before_anything_is_rented(colab: Callable, backend: FakeBackend) -> None:
    with pytest.raises(ValueError, match="Colab runs its own image"):
        sdk.launch(colab(), ceiling_s=600, image="python:3.13-slim")
    assert backend.assignments() == []


def test_ports_and_a_record_are_refused_before_anything_is_rented(colab: Callable, backend: FakeBackend, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no ports.*terms forbid web services"):
        sdk.launch(colab(), ceiling_s=600, ports=(8888,))
    with pytest.raises(ValueError, match="no volumes.*no durable record"):
        sdk.launch(colab(), ceiling_s=600, record=DirStore(tmp_path / "store"))
    assert backend.assignments() == []


def test_expose_is_refused(colab: Callable) -> None:
    with sdk.launch(colab(), ceiling_s=600) as s, pytest.raises(ValueError, match="cannot expose port 8888.*terms forbid"):
        s.expose(8888)


def test_a_pty_and_a_shell_are_refused_and_a_plain_stream_still_works(colab: Callable) -> None:
    with sdk.launch(colab(), ceiling_s=600) as s:
        with pytest.raises(ValueError, match="no pty: a kernel cell takes no stdin"):
            s.stream("bash", pty=True)
        with pytest.raises(ValueError, match="no shell"):
            s.shell()
        with s.stream("echo plain", timeout_s=60) as stream:
            assert b"".join(data for _, data in stream) == b"plain\n"


def test_a_ceiling_past_colabs_max_runtime_is_refused_not_clamped(colab: Callable, backend: FakeBackend) -> None:
    """The backstop is the ceiling + BACKSTOP_MARGIN_S; Colab ends a runtime at its max. A ceiling
    whose backstop fits is launched as asked; one past it is refused before anything is rented."""
    c = colab(max_runtime_s=3600)
    most_s = 3600 - sdk.BACKSTOP_MARGIN_S
    with pytest.raises(ValueError, match=r"ceiling of 0\.84 h is refused: Colab ends a runtime after 1 h.*at most 0\.83 h.*Not clamped"):
        sdk.create(c, ceiling_s=most_s + 30)
    assert backend.assignments() == []
    with sdk.launch(c, ceiling_s=most_s - 30) as s:
        running = s.status()
        assert isinstance(running, sdk.Running)
        assert running.lease.ceiling - time.time() > most_s - 90  # the ceiling asked for, not a shorter one


def test_no_compute_units_is_refused_unless_allowed(colab: Callable, backend: FakeBackend, log: io.StringIO) -> None:
    backend.configure(compute_units=0.0)
    with pytest.raises(RuntimeError, match="no compute units.*BOX_COLAB_ALLOW_FREE=1"):
        sdk.launch(colab(), ceiling_s=600)
    assert backend.assignments() == []
    with sdk.launch(colab(allow_free=True), ceiling_s=600) as s:
        assert s.run("echo free").wait() == Ending("exited", 0)
    assert "no compute units; going ahead because allow_free is set" in log.getvalue()


def test_exec_is_bash_with_its_exit_code_and_both_streams(colab: Callable) -> None:
    with sdk.launch(colab(), ceiling_s=600) as s:
        assert s.machine.exec("echo out; echo err >&2; exit 7") == (7, "out\n", "err\n")
        assert s.machine.exec("printf '\\x1ebox-exec\\x1e{}'")[1] == "\x1ebox-exec\x1e{}"  # the marker in output is just output


def test_a_stream_pushes_output_while_its_command_runs_and_exec_is_not_held_up(colab: Callable) -> None:
    """A stream's cell runs in a kernel of its own: its first chunk arrives while the command still
    waits on us, and execs go on meanwhile (in the exec kernel). Bytes come through exact."""
    with sdk.launch(colab(), ceiling_s=600) as s:
        go = f"{s.machine.root}/go"
        cmd = f"printf 'one\\n\\x1e\\xff'; while [ ! -e {go} ]; do sleep 0.05; done; echo two >&2; exit 5"
        t0 = time.monotonic()
        with s.machine.stream(cmd, timeout_s=60) as stream:
            chunks = iter(stream)
            assert next(chunks) == ("stdout", b"one\n\x1e\xff")
            assert s.machine.exec("echo meanwhile") == (0, "meanwhile\n", "")
            s.machine.exec(f"touch {go}")
            assert list(chunks) == [("stderr", b"two\n")]
        assert stream.rc == 5
        assert time.monotonic() - t0 < 30


def test_closing_a_stream_kills_its_command_and_shuts_its_kernel_down(colab: Callable, backend: FakeBackend) -> None:
    with sdk.launch(colab(), ceiling_s=600) as s:
        kernels = len(_vm_state(backend, s.machine.id)["kernels"])
        with s.machine.stream("echo $$; exec sleep 999", timeout_s=60) as stream:
            pid = int(next(iter(stream))[1])
            assert len(_vm_state(backend, s.machine.id)["kernels"]) == kernels + 1
        assert s.machine.exec(f"kill -0 {pid}")[0] != 0  # dead by the time close() returns
        assert len(_vm_state(backend, s.machine.id)["kernels"]) == kernels


def test_a_stream_on_a_runtime_that_goes_away_is_gone(colab: Callable, backend: FakeBackend) -> None:
    s = sdk.launch(colab(), ceiling_s=600)
    with s.machine.stream("echo up; exec sleep 999", timeout_s=60) as stream:
        chunks = iter(stream)
        assert next(chunks) == ("stdout", b"up\n")
        backend.unassign(s.machine.id)  # Colab takes the VM back
        with pytest.raises(Gone):
            list(chunks)


def test_an_exec_result_too_big_for_iopub_comes_back_as_a_file(colab: Callable) -> None:
    with sdk.launch(colab(), ceiling_s=600) as s:
        rc, out, _ = s.machine.exec(f"head -c {colab_provider.INLINE_MAX} /dev/zero | tr '\\0' x")
        assert (rc, len(out), set(out)) == (0, colab_provider.INLINE_MAX, {"x"})
        assert s.machine.exec("ls /tmp | grep -c '^box-exec-' || true")[1].strip() in ("0", "")  # cleaned up


def test_write_makes_parents_and_files_round_trip_as_bytes(colab: Callable) -> None:
    data = bytes(range(256)) * 10
    with sdk.launch(colab(), ceiling_s=600) as s:
        path = f"{s.machine.root}/deep/er/blob.bin"
        s.machine.write(path, data)
        assert s.machine.read(path) == data
        with pytest.raises(FileNotFoundError):
            s.machine.read(f"{s.machine.root}/nope")


def test_closing_unassigns_the_runtime_and_gone_says_so(colab: Callable, backend: FakeBackend) -> None:
    s = sdk.launch(colab(), ceiling_s=600)
    assert [a.endpoint for a in backend.assignments()] == [s.machine.id]
    assert not s.machine.gone()
    receipt = s.close()
    assert receipt.ended == sdk.Ended("stopped")
    assert backend.assignments() == []
    assert s.machine.gone()
    with pytest.raises(Gone):
        s.machine.exec("true")
    s.machine.terminate()  # idempotent


def test_gone_after_terminate(colab: Callable) -> None:
    machine = raw_launch(colab(), timeout_s=600)
    assert not machine.gone()
    machine.terminate()
    assert machine.gone()


def test_a_session_that_ends_by_itself_unassigns_its_runtime_from_inside(colab: Callable, backend: FakeBackend) -> None:
    """No client terminates it: the supervisor ends (released) and BOOT calls the runtime's own
    unassign, as google.colab.runtime.unassign() does."""
    s = sdk.launch(colab(), ceiling_s=600)
    s.release()
    eventually(lambda: backend.assignments() == [])
    assert s.machine.gone()
    assert "supervisor exited 0" in (Path(s.machine.root) / "shutdown.log").read_text()


def test_the_backstop_unassigns_a_runtime_whose_supervisor_never_ends(colab: Callable, backend: FakeBackend) -> None:
    machine = raw_launch(colab(), timeout_s=2)
    assert [a.endpoint for a in backend.assignments()] == [machine.id]
    eventually(lambda: backend.assignments() == [])


def test_a_runtime_that_cannot_end_itself_is_refused_and_released(colab: Callable, backend: FakeBackend) -> None:
    backend.configure(tbe=False)
    with pytest.raises(RuntimeError, match="no TBE_RUNTIME_ADDR"):
        sdk.launch(colab(), ceiling_s=600)
    assert backend.assignments() == []


def test_list_and_get_see_only_runtimes_box_launched(colab: Callable, backend: FakeBackend) -> None:
    mine = colab()
    foreign = backend.assign_foreign("L4")  # a notebook of yours: no box labels on it
    with sdk.launch(mine, ceiling_s=600, gpu="T4", labels={"box.cmd": "x"}) as s:
        assert [(m.id, m.labels["box.cmd"]) for m in mine.list()] == [(s.machine.id, "x")]
        assert [m.id for m in mine.list({sdk.LABEL_SESSION: s.id})] == [s.machine.id]
        assert mine.list({sdk.LABEL_SESSION: "s-000000000000"}) == []
        assert mine.get(s.machine.id).labels == s.machine.labels
        with pytest.raises(LookupError, match="not launched by box"):
            mine.get(foreign.endpoint)
        with pytest.raises(LookupError, match="no runtime"):
            mine.get("fake-t4-000000")
        assert sdk.attach(mine, session_id=s.id).machine.exec("echo again")[1] == "again\n"
    backend.unassign(foreign.endpoint)


def test_an_expiring_proxy_token_is_refreshed_from_the_account(colab: Callable, backend: FakeBackend) -> None:
    backend.configure(token_ttl_s=colab_provider.REFRESH_MARGIN_S + 1.5)
    with sdk.launch(colab(), ceiling_s=600) as s:
        assert isinstance(s.machine, ColabMachine)
        first = s.machine._assignment.token
        time.sleep(2)  # now within REFRESH_MARGIN_S of expiry
        assert s.machine.exec("echo still")[1] == "still\n"
        assert s.machine._assignment.token != first


def test_a_vanished_exec_kernel_is_replaced_and_recorded(colab: Callable) -> None:
    with sdk.launch(colab(), ceiling_s=600) as s:
        m = s.machine
        runtime = m._shared()
        assert isinstance(runtime, FakeRuntime)
        old = m._exec_kernel
        runtime.kill_kernel(old)
        assert m.exec("echo back") == (0, "back\n", "")
        assert m._exec_kernel != old
        assert m.colab.get(m.id)._exec_kernel == m._exec_kernel  # another process finds the new one


def test_a_failing_exec_cell_is_an_error_not_an_exit_code() -> None:
    with pytest.raises(RuntimeError, match="exec cell failed.*NameError: boom"):
        colab_provider.parse_exec([{"output_type": "error", "ename": "NameError", "evalue": "boom"}], "true")
    with pytest.raises(RuntimeError, match="printed 0 results"):
        colab_provider.parse_exec([{"output_type": "stream", "name": "stdout", "text": "chatter\n"}], "true")


def test_stream_frames_survive_any_split_and_refuse_what_is_not_a_frame() -> None:
    text = f"{colab_provider.MARK}oaGk=\n{colab_provider.MARK}r0\n"
    for cut in range(len(text)):
        frames = colab_provider.Frames("x")
        assert frames.feed(text[:cut]) + frames.feed(text[cut:]) == [("o", "aGk="), ("r", "0")]
        frames.end()
    with pytest.raises(RuntimeError, match="non-frame"):
        colab_provider.Frames("x").feed("chatter\n")
    frames = colab_provider.Frames("x")
    frames.feed(f"{colab_provider.MARK}oaG")
    with pytest.raises(RuntimeError, match="mid-frame"):
        frames.end()


def _vm_state(backend: FakeBackend, endpoint: str) -> dict:
    return json.loads((backend.vm(endpoint) / "state.json").read_text())
