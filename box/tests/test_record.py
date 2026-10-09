"""A recorded session (launch(record=store)) is still inspectable after its machine is gone: why it
ended, its jobs, and their output up to the last flush. Same providers as test_sdk.py:
`pytest --provider modal` records into a Modal Volume instead of a directory."""

from __future__ import annotations

import os
import socket
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from box import sdk
from box.sdk import Ended, Ending, Provider, Running
from box.store import Store
from box.supervisor import CHUNK_BYTES, HEARTBEAT_TTL_S
from box.tests import providers
from box.tests.test_sdk import JOB_S, eventually, gone


@pytest.fixture
def store(name: str, provider: Provider, tmp_path: Path) -> Store:
    return providers.make_store(name, tmp_path / "store", provider)


def recorded_output(record: sdk.Record, job_id: str, stream: str = "stdout") -> str:
    return "".join(c.text for c in record.logs(job_id) if c.stream == stream)


def test_a_recorded_session_says_why_it_ended_after_its_machine_is_gone(launch: Callable, provider: Provider, store: Store) -> None:
    with launch(ceiling_s=600, record=store, labels={"box.user": "reader-7@relay"}) as s:
        job = s.run("echo hello; echo oops >&2; exit 3", max_duration_s=JOB_S)
        assert job.wait() == Ending("exited", 3)
    assert gone(provider, s)
    again = sdk.attach(provider, s.id, record=store)  # a fresh process: it never saw the machine
    assert again.status() == Ended("stopped")
    assert again.wait() == Ended("stopped")
    record = sdk.read_record(store, s.id)
    assert (record.ended, record.machine_id, record.labels["box.user"]) == (Ended("stopped"), s.machine.id, "reader-7@relay")
    assert record.jobs() == [job.id]
    assert record.job_status(job.id).ending == Ending("exited", 3)
    assert recorded_output(record, job.id) == "hello\n"
    assert recorded_output(record, job.id, "stderr") == "oops\n"


def test_job_logs_read_on_from_the_record_with_the_same_cursor_once_the_machine_is_gone(launch: Callable, provider: Provider, store: Store) -> None:
    with launch(ceiling_s=600, record=store) as s:
        job = s.run("echo one; echo two >&2; echo three", max_duration_s=JOB_S)
        job.wait()
        first = next(job.logs())  # a reader that saw some of it live
    assert (first.stream, first.text) == ("stdout", "one\nthree\n")
    (again,) = sdk.attach(provider, s.id, record=store).jobs()  # the machine is gone: its record answers
    assert again.id == job.id
    rest = list(again.logs(after=(len("one\n"), 0), follow=True))
    assert [(c.stream, c.text) for c in rest] == [("stdout", "three\n"), ("stderr", "two\n")]
    assert rest[-1].end == (len("one\nthree\n"), len("two\n"))
    assert list(again.logs(after=rest[-1].end)) == []


def test_a_job_env_is_recorded_by_name_never_by_value(launch: Callable, store: Store) -> None:
    with launch(ceiling_s=600, record=store) as s:
        job = s.run("true", max_duration_s=JOB_S, env={"API_KEY": "sekrit-value"})
        job.wait()
    recorded = b"".join(store.get(key) for key in store.list(f"sessions/{s.id}/"))
    assert b"API_KEY" in recorded
    assert b"sekrit-value" not in recorded


def test_a_session_ended_by_its_lease_records_its_end_and_all_its_output(launch: Callable, provider: Provider, store: Store, scale: float) -> None:
    s = launch(lease_s=4 * scale, ceiling_s=600, record=store)
    job = s.run(f"for i in 1 2 3; do echo line $i; sleep {0.5 * scale}; done", max_duration_s=JOB_S)
    eventually(lambda: gone(provider, s), timeout_s=60 * scale)  # nobody here reads its ended.json before it goes
    assert sdk.attach(provider, s.id, record=store).wait(timeout_s=30 * scale) == Ended("lease")
    assert recorded_output(sdk.read_record(store, s.id), job.id) == "line 1\nline 2\nline 3\n"


def test_every_change_of_the_lease_is_audited_in_the_record(launch: Callable, provider: Provider, store: Store, scale: float) -> None:
    s = launch(lease_s=60, ceiling_s=600, record=store)
    for more_s in (120, 180):  # two extends in a row from this process: one entry, n=2
        s.extend(time.time() + more_s)
    s.extend(time.time() + 1)  # shorter: no change, nothing audited
    released = s.release()
    assert s.wait() == Ended("released")
    eventually(lambda: gone(provider, s), timeout_s=60 * scale)
    record = sdk.read_record(store, s.id)
    audit = record.lease_audit()
    assert [(c.op, c.n) for c in audit] == [("create", 1), ("extend", 2), ("release", 1)]
    assert {(c.host, c.pid) for c in audit} == {(socket.gethostname(), os.getpid())}
    assert audit[-1].until == released.until
    assert record.running.lease == released  # the last lease recorded


def test_a_supervisor_killed_without_a_word_is_machine_lost_with_logs_up_to_the_last_flush(
    launch: Callable, provider: Provider, store: Store, scale: float
) -> None:  # fmt: skip
    s = launch(ceiling_s=600, record=store)
    job = s.run("echo before; sleep 999", max_duration_s=JOB_S)
    eventually(lambda: recorded_output(sdk.read_record(store, s.id), job.id) == "before\n", timeout_s=30 * scale)
    providers.kill_supervisor(s.machine)
    killed_at = time.monotonic()
    # its heartbeat is still fresh: status() waits that out (the end may still be landing), never says Running
    assert sdk.attach(provider, s.id, record=store).status() == Ended("machine_lost")
    assert time.monotonic() - killed_at < HEARTBEAT_TTL_S + 5 * scale
    assert s.wait(timeout_s=HEARTBEAT_TTL_S + 30 * scale) == Ended("machine_lost")
    assert time.monotonic() - killed_at < HEARTBEAT_TTL_S + 30 * scale
    s.machine.terminate()  # macOS: the job outlives its supervisor (no PDEATHSIG)
    record = sdk.read_record(store, s.id)
    assert record.ended is None
    assert isinstance(record.running, Running)
    assert record.end(now=time.time()) == Ended("machine_lost")
    assert sdk.attach(provider, s.id, record=store).status() == Ended("machine_lost")
    assert recorded_output(record, job.id) == "before\n"
    s.close()


def test_a_character_split_across_flushes_is_recorded_whole(launch: Callable, store: Store, scale: float) -> None:
    with launch(ceiling_s=600, record=store) as s:
        job = s.run(rf"printf 'caf\xc3'; sleep {3 * scale}; printf '\xa9\n'", max_duration_s=JOB_S)  # é = c3 a9, a flush in between
        job.wait()
    record = sdk.read_record(store, s.id)
    assert recorded_output(record, job.id) == "café\n"
    assert all("\N{REPLACEMENT CHARACTER}" not in c.text for c in record.logs(job.id))


def test_output_past_a_chunk_is_recorded_in_order_and_never_dropped(launch: Callable, store: Store) -> None:
    lines = 3 * CHUNK_BYTES // 8  # "%07d\n": 8 bytes a line; 3 chunks' worth, more than one flush takes
    with launch(ceiling_s=600, record=store) as s:
        job = s.run(f"awk 'BEGIN {{ for (i = 1; i <= {lines}; i++) printf \"%07d\\n\", i }}'", max_duration_s=JOB_S)
        job.wait()
    record = sdk.read_record(store, s.id)
    chunks = list(record.logs(job.id))
    assert len(chunks) >= 3
    recorded = "".join(c.text for c in chunks)
    expected = "".join(f"{i:07d}\n" for i in range(1, lines + 1))
    assert len(recorded) == len(expected)  # a short, readable failure first: no 12 MB diff
    assert recorded == expected
    assert list(record.logs(job.id, after=chunks[0].end)) == chunks[1:]


def test_a_session_never_recorded_is_not_found(provider: Provider, store: Store) -> None:
    with pytest.raises(LookupError):
        sdk.read_record(store, "s-000000000000")
    with pytest.raises(LookupError):
        sdk.attach(provider, "s-000000000000", record=store)
    with pytest.raises(ValueError, match="not a session id"):
        sdk.read_record(store, "../etc")
