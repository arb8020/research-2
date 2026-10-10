"""create(setup=): a repo's setup runs once, is snapshotted, and later sessions boot from it with the
code synced on top (box/setup_cache.py). Like test_dev, no test names a provider: on local a
snapshot is a copy of the work dir; `pytest --provider modal` uses Modal's filesystem snapshots."""

from __future__ import annotations

import dataclasses
import secrets
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from box import sdk
from box.sdk import Ended, Provider
from box.setup_cache import CACHE_PREFIX, SetupSpec, Snapshotter, lookup, setup_key
from box.store import Store
from box.tests import providers
from box.tests.test_dev import git, remote
from box.tests.test_dev import repo as repo  # noqa: PLC0414 (the fixture, re-exported for pytest)

SECRET = "BOX_TEST_SECRET"
# The setup marks each run in the worktree (untracked, so a sync leaves it be) and writes the names
# of its env; resume does the same. Idempotent, as a setup must be: appending a line is harmless.
SETUP = "set -eu\necho ran >> .setup-runs\nenv | cut -d= -f1 | sort > .setup-env\n"
RESUME = "set -eu\nenv | cut -d= -f1 | sort > .resume-env\n"


@pytest.fixture
def store(name: str, provider: Provider, tmp_path: Path) -> Store:
    if why := providers.CANNOT.get(name, {}).get("record"):
        pytest.skip(why)
    return providers.make_store(name, tmp_path / "store", provider)


@pytest.fixture
def spec(repo: Path) -> SetupSpec:
    """repo with .box/setup, .box/resume and a lockfile whose bytes are new each test: a key no
    other test (or earlier run, in a shared Modal workspace) has cached."""
    (repo / ".box").mkdir()
    (repo / ".box" / "setup").write_text(SETUP)
    (repo / ".box" / "resume").write_text(RESUME)
    (repo / "deps.lock").write_text(f"pinned {secrets.token_hex(8)}\n")
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "setup")
    return SetupSpec(repo=repo, lockfiles=("deps.lock",), resume=".box/resume")


@pytest.fixture
def create(provider: Provider, name: str) -> Iterator[Callable[..., sdk.Session]]:
    """create(setup=...) on an image with git, every session closed after the test."""
    made: list[sdk.Session] = []

    def make(**kw: object) -> sdk.Session:
        image = {} if name in ("local", "colab-fake") else {"image": providers.DEV_IMAGE}
        s = sdk.create(provider, **(providers.launch_kw(name) | image | {"ceiling_s": 600} | kw))
        made.append(s)
        return s

    yield make
    for s in made:
        if not isinstance(s.status(), Ended):
            s.close()


def setup_runs(s: sdk.Session) -> int:
    return len(remote(s, f"cat {s.machine.work}/repo/.setup-runs").split())


def test_a_miss_runs_the_setup_snapshots_it_and_remembers_the_key(create: Callable, spec: SetupSpec, store: Store, provider: Provider) -> None:
    assert isinstance(provider, Snapshotter)
    s = create(record=store, setup=spec)
    assert setup_runs(s) == 1
    prepared = sdk.read_record(store, s.id).setup()
    assert prepared is not None
    assert (prepared.hit, prepared.setup_job is not None, prepared.resume_job is not None) == (False, True, True)
    cached = lookup(store, prepared.key, now=time.time(), max_age_s=spec.max_age_s)
    assert cached is not None
    assert (cached.image, cached.built_by) == (prepared.image, s.id)
    assert cached.commit == sdk.read_record(store, s.id).syncs()[0]["commit"]  # the code the setup ran against
    assert {j.id for j in s.jobs()} == {prepared.setup_job, prepared.resume_job}  # job ids order by the second, not within one


def test_a_hit_boots_from_the_snapshot_and_runs_no_setup(create: Callable, spec: SetupSpec, store: Store) -> None:
    first = create(record=store, setup=spec)
    built = sdk.read_record(store, first.id).setup()
    s = create(record=store, setup=spec)
    prepared = sdk.read_record(store, s.id).setup()
    assert prepared is not None and built is not None
    assert (prepared.hit, prepared.key, prepared.image, prepared.setup_job) == (True, built.key, built.image, None)
    assert setup_runs(s) == 1  # the one line is the snapshot's, from first's setup
    assert [j.id for j in s.jobs()] == [prepared.resume_job]  # resume runs every boot
    assert remote(s, f"test -e {s.machine.root}/ended.json || echo fresh") == "fresh"  # first's supervisor files were cleared
    assert remote(s, f"ls {s.machine.root}/jobs").split() == [prepared.resume_job]


@pytest.mark.parametrize("edit", ["deps.lock", ".box/setup"])
def test_changing_a_lockfile_or_the_setup_is_a_miss(create: Callable, spec: SetupSpec, store: Store, edit: str) -> None:
    first = create(record=store, setup=spec)
    with (spec.repo / edit).open("a") as f:
        f.write("\n# changed\n")  # on disk, not committed: the key is what a sync would send
    s = create(record=store, setup=spec)
    prepared = sdk.read_record(store, s.id).setup()
    assert prepared is not None
    assert prepared.hit is False
    assert prepared.key != sdk.read_record(store, first.id).setup().key  # type: ignore[union-attr]
    assert setup_runs(s) == 1  # booted from the base: a fresh machine, set up once


def test_an_expired_snapshot_is_a_miss(create: Callable, spec: SetupSpec, store: Store) -> None:
    short = dataclasses.replace(spec, max_age_s=0.5)
    create(record=store, setup=short)
    time.sleep(1.0)
    s = create(record=store, setup=short)
    assert sdk.read_record(store, s.id).setup().hit is False  # type: ignore[union-attr]


def test_rebuild_is_a_miss_and_replaces_the_snapshot(create: Callable, spec: SetupSpec, store: Store) -> None:
    first = create(record=store, setup=spec)
    s = create(record=store, setup=dataclasses.replace(spec, rebuild=True))
    prepared, built = sdk.read_record(store, s.id).setup(), sdk.read_record(store, first.id).setup()
    assert prepared is not None and built is not None
    assert (prepared.hit, prepared.key) == (False, built.key)
    assert prepared.image != built.image
    cached = lookup(store, prepared.key, now=time.time(), max_age_s=spec.max_age_s)
    assert cached is not None and cached.image == prepared.image  # the next hit boots the rebuilt one


def test_the_setup_gets_none_of_the_sessions_env_and_resume_gets_all_of_it(create: Callable, spec: SetupSpec, store: Store) -> None:
    s = create(record=store, setup=spec, env={SECRET: "hunter2", "BOX_TEST_TOKEN": "t0k"})
    t = f"{s.machine.work}/repo"
    setup_env, resume_env = remote(s, f"cat {t}/.setup-env").split(), remote(s, f"cat {t}/.resume-env").split()
    assert SECRET not in setup_env and "BOX_TEST_TOKEN" not in setup_env
    assert {SECRET, "BOX_TEST_TOKEN"} <= set(resume_env)
    assert "PATH" in setup_env  # the image's own env is kept: only the session's is dropped


def test_a_sync_after_a_hit_sends_only_the_diff(create: Callable, spec: SetupSpec, store: Store) -> None:
    first = create(record=store, setup=spec)
    full = sdk.read_record(store, first.id).syncs()[0]["pack_bytes"]
    (spec.repo / "pkg" / "a.txt").write_text("edited after the setup\n")
    s = create(record=store, setup=spec)
    (synced,) = sdk.read_record(store, s.id).syncs()
    assert sdk.read_record(store, s.id).setup().hit is True  # type: ignore[union-attr]
    assert 0 < synced["pack_bytes"] < full / 20, (synced["pack_bytes"], full)  # the 200 kB blob came with the snapshot
    assert remote(s, f"cat {s.machine.work}/repo/pkg/a.txt") == "edited after the setup"
    again = s.sync(spec.repo)
    assert again.pack_bytes == 0


def test_syncs_and_jobs_record_their_commits(create: Callable, spec: SetupSpec, store: Store) -> None:
    s = create(record=store, setup=spec)
    (spec.repo / "pkg" / "a.txt").write_text("v2\n")
    v2 = s.sync(spec.repo)
    job = s.run(f"cat {v2.path}/pkg/a.txt", max_duration_s=300)
    job.wait()
    s.close()
    record = sdk.read_record(store, s.id)
    syncs = record.syncs()
    assert [x["commit"] for x in syncs][-1] == v2.commit
    assert len(syncs) == 2 and syncs[0]["commit"] != v2.commit
    assert record.job_code(record.setup().setup_job) == {"repo": syncs[0]["commit"]}  # type: ignore[union-attr, arg-type]
    assert record.job_code(job.id) == {"repo": v2.commit}
    assert git(spec.repo, "show", f"{v2.commit}:pkg/a.txt") == "v2"  # the commit answers what code ran, here


def test_a_failed_setup_closes_the_session_and_caches_nothing(create: Callable, spec: SetupSpec, store: Store, provider: Provider, name: str) -> None:
    (spec.repo / ".box" / "setup").write_text("echo building; echo broke >&2; exit 7\n")
    with pytest.raises(sdk.SetupFailed, match="exit 7") as raised:
        create(record=store, setup=spec)
    assert "broke" in str(raised.value)
    key = setup_key(spec, provider=provider.name, image=None if name == "local" else providers.DEV_IMAGE)
    assert store.list(f"{CACHE_PREFIX}/{key}") == []
    session_id = str(raised.value).split(":", 1)[0]
    assert sdk.read_record(store, session_id).receipt() is not None  # closed: ended, and the provider said it is gone


class NoSnapshots:
    """A provider without the snapshot capability (RunPod, Colab today): every boot runs the setup."""

    def __init__(self, inner: Provider) -> None:
        self.inner = inner
        self.name = inner.name

    def launch(self, **kw: object) -> sdk.Machine:
        return self.inner.launch(**kw)

    def get(self, machine_id: str) -> sdk.Machine:
        return self.inner.get(machine_id)

    def list(self, labels: dict[str, str] | None = None) -> list[sdk.Machine]:
        return self.inner.list(labels)

    def close(self) -> None:
        self.inner.close()


class StaysListed(NoSnapshots):
    """A provider whose machines terminate but which says it still has them (one that may bill on)."""

    def launch(self, **kw: object) -> sdk.Machine:
        machine = self.inner.launch(**kw)

        def gone() -> bool:
            raise sdk.NotGone(f"{machine.id}: its provider still has it")

        setattr(machine, "gone", gone)  # noqa: B010
        return machine


def test_a_machine_that_will_not_go_after_a_failed_setup_is_raised_not_swallowed(provider: Provider, name: str, spec: SetupSpec) -> None:
    (spec.repo / ".box" / "setup").write_text("exit 7\n")
    kw = providers.launch_kw(name) | ({} if name == "local" else {"image": providers.DEV_IMAGE})
    with pytest.raises(sdk.NotGone, match="still has it") as raised:
        sdk.create(StaysListed(provider), ceiling_s=600, setup=spec, **kw)
    assert isinstance(raised.value.__context__, sdk.SetupFailed)  # the setup's own failure rides along


def test_without_snapshots_every_boot_runs_the_setup(provider: Provider, name: str, spec: SetupSpec, store: Store) -> None:
    plain = NoSnapshots(provider)
    assert not isinstance(plain, Snapshotter)
    kw = providers.launch_kw(name) | ({} if name == "local" else {"image": providers.DEV_IMAGE})
    for _ in range(2):
        with sdk.create(plain, ceiling_s=600, record=store, setup=spec, **kw) as s:
            assert setup_runs(s) == 1
            prepared = sdk.read_record(store, s.id).setup()
            assert prepared is not None
            assert (prepared.hit, prepared.image) == (False, None)
    assert store.list(f"{CACHE_PREFIX}/") == []  # nothing to remember


def test_wait_up_waits_for_this_sessions_supervisor_not_a_snapshots(create: Callable, spec: SetupSpec, store: Store) -> None:
    """A snapshot holds the snapshotted session's ROOT/up until the boot clears it: seen live on
    Modal, a wait_up that took it for its own, then a Booting session."""
    s = create(record=store, setup=spec)
    up = f"{s.machine.root}/up"
    assert remote(s, f"cat {up}") == s.id
    remote(s, f"echo s-0123456789ab > {up}")  # another session's, as a snapshot has it
    with pytest.raises(TimeoutError):
        s.wait_up(1.0)
    remote(s, f"echo {s.id} > {up}")
    s.wait_up(1.0)
