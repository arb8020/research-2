"""The primitives a dev workflow is built from, end to end: names, pty streams, the two expose routes
and the proxy, idleness from ROOT/activity, the shell escape hatch, and git sync. Like test_sdk, no
test names a provider: `pytest --provider modal` runs them on Modal CPU boxes."""

from __future__ import annotations

import concurrent.futures
import http.client
import hashlib
import os
import shlex
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from box import gitsync, sdk
from box.proxy import Proxy
from box.sdk import Ended, Ending, Provider, Running
from box.tests import providers

JOB_S = 300
PORTS = range(8880, 8890)  # the ports these tests listen on, here and on the machine
HASH = 'python3 -c "import hashlib,sys; print(hashlib.sha1(open(sys.argv[1],\'rb\').read()).hexdigest())"'


def test_port() -> int:
    """A port in PORTS nothing on this computer listens on (the local provider shares its network)."""
    for port in PORTS:
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise AssertionError(f"every port in {PORTS} is taken")


test_port.__test__ = False  # a helper, not a test


@pytest.fixture
def dev(provider: Provider, name: str) -> Iterator[Callable[..., sdk.Session]]:
    """launch(**kw) on an image with git (Session.sync), every session closed after the test."""
    launched: list[sdk.Session] = []

    def launch(**kw: object) -> sdk.Session:
        s = sdk.launch(provider, **(providers.launch_kw(name) | ({} if name in ("local", "colab-fake") else {"image": providers.DEV_IMAGE}) | kw))
        launched.append(s)
        return s

    yield launch
    for s in launched:
        if not isinstance(s.status(), Ended) or s.machine.id in {m.id for m in provider.list()}:
            s.close()


def unique(request: pytest.FixtureRequest, tag: str) -> str:
    """A name no other test run uses (names are per provider, so per Modal workspace)."""
    return f"t-{tag}-{os.getpid()}-{abs(hash(request.node.name)) % 10**6}"


def remote(s: sdk.Session, cmd: str) -> str:
    rc, out, err = s.machine.exec(cmd)
    assert rc == 0, f"`{cmd}` exited {rc}: {err}"
    return out.strip()


def eventually(predicate: Callable[[], bool], timeout_s: float = 10.0) -> None:
    give_up = time.monotonic() + timeout_s
    while not predicate():
        assert time.monotonic() < give_up, "timed out"
        time.sleep(0.2)


# ---- names ----


def test_attach_finds_a_session_by_its_name_from_another_process(dev: Callable, provider: Provider, name: str, tmp_path: Path, request: pytest.FixtureRequest) -> None:
    box_name = unique(request, "named")
    s = dev(ceiling_s=600, name=box_name)
    assert s.name == box_name
    assert sdk.attach(provider, name=box_name).id == s.id
    with pytest.raises(LookupError):
        sdk.attach(provider, name=unique(request, "nobody"))
    again, created = sdk.find_or_create(provider, box_name, ceiling_s=600)
    assert (again.id, created) == (s.id, False)
    with pytest.raises(sdk.NameTaken):
        sdk.create(provider, name=box_name, ceiling_s=600, **providers.launch_kw(name))
    client = (f"from pathlib import Path; from box import sdk; from box.tests import providers; "
              f"p = providers.make({name!r}, Path({str(tmp_path / 'machines')!r})); print(sdk.attach(p, name={box_name!r}).id); p.close()")  # fmt: skip
    assert subprocess.run([sys.executable, "-c", client], capture_output=True, text=True, check=True, timeout=120).stdout.strip() == s.id


def test_attach_takes_exactly_one_handle_and_a_name_every_provider_takes(provider: Provider) -> None:
    with pytest.raises(ValueError, match="exactly one"):
        sdk.attach(provider)
    with pytest.raises(ValueError, match="exactly one"):
        sdk.attach(provider, session_id="s-000000000000", name="x")
    for bad in ("", "has space", "-leading", "x" * 64, "a/b"):
        with pytest.raises(ValueError, match="name"):
            sdk.create(provider, name=bad)


@pytest.mark.needs("unique-names")
def test_racing_creates_of_one_name_get_one_session(dev: Callable, provider: Provider, name: str, request: pytest.FixtureRequest) -> None:
    """Every caller races find_or_create at once: the provider refuses all creates but one (NameTaken),
    and each loser finds the winner's session."""
    box_name, callers = unique(request, "race"), 4
    go = threading.Barrier(callers)

    def race() -> tuple[sdk.Session, bool]:
        go.wait()
        return sdk.find_or_create(provider, box_name, ceiling_s=600, **providers.launch_kw(name))

    with concurrent.futures.ThreadPoolExecutor(callers) as pool:  # owned: leaving joins every caller
        results = [f.result() for f in [pool.submit(race) for _ in range(callers)]]
    winners = [s for s, created in results if created]
    try:
        assert len(winners) == 1, [(s.id, created) for s, created in results]
        assert {s.id for s, _ in results} == {winners[0].id}
        assert [m.labels[sdk.LABEL_NAME] for m in provider.list({sdk.LABEL_NAME: box_name})] == [box_name]
    finally:
        for s in {s.id: s for s, _ in results}.values():
            s.close()


# ---- streams ----


@pytest.mark.needs("pty")
def test_a_pty_stream_merges_its_output_and_gives_its_exit_code(dev: Callable, scale: float) -> None:
    s = dev(ceiling_s=600)
    with s.stream("echo out; echo err >&2; test -t 0 && echo tty; exit 7", pty=True, timeout_s=30 * scale) as stream:
        seen = list(stream)
    text = b"".join(data for _, data in seen).decode()
    assert {n for n, _ in seen} == {"stdout"}  # a terminal: one stream, as on a laptop's
    assert "out" in text and "err" in text and "tty" in text
    assert stream.rc == 7
    with s.stream("echo plain", timeout_s=30 * scale) as plain, pytest.raises(ValueError, match="not a pty"):
        plain.send(b"x")


@pytest.mark.needs("pty")
def test_ctrl_c_reaches_a_pty_command(dev: Callable, scale: float) -> None:
    s = dev(ceiling_s=600)
    with s.stream("trap 'echo got-int; exit 130' INT; echo ready; sleep 60 & wait", pty=True, timeout_s=30 * scale) as stream:
        chunks, seen = iter(stream), b""
        while b"ready" not in seen:
            seen += next(chunks)[1]
        sent = time.monotonic()
        stream.send(b"\x03")
        seen += b"".join(data for _, data in chunks)
    assert b"got-int" in seen
    assert stream.rc == 130
    assert time.monotonic() - sent < 10 * scale


@pytest.mark.needs("pty")
def test_a_pty_stream_ends_at_its_bound(dev: Callable, scale: float) -> None:
    s = dev(ceiling_s=600)
    bound = 3 * scale
    started = time.monotonic()
    with pytest.raises(TimeoutError, match="past"), s.stream("echo $$; exec sleep 999", pty=True, timeout_s=bound) as stream:
        pid = int(next(iter(stream))[1].strip())
        list(stream)
    assert bound <= time.monotonic() - started < bound + 15 * scale
    eventually(lambda: s.machine.exec(f"kill -0 {pid}")[0] != 0, timeout_s=10 * scale)  # killed at its bound
    with pytest.raises(ValueError, match="ceiling"):
        s.stream("true", timeout_s=10**6)  # never past the session's ceiling


# ---- ports ----

# Answers GET with the X-Box-Test header it got, then three server-sent events GAP s apart.
SSE_SERVER = """
import sys, time
from http.server import BaseHTTPRequestHandler, HTTPServer
class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def do_GET(self):
        self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.send_header("Transfer-Encoding", "chunked"); self.end_headers()
        for i, data in enumerate([f"seen: {self.headers.get('X-Box-Test')}\\n".encode()] + [f"data: {i}\\n\\n".encode() for i in range(3)]):
            self.wfile.write(b"%x\\r\\n%s\\r\\n" % (len(data), data)); self.wfile.flush(); time.sleep(float(sys.argv[2]) if i else 0)
        self.wfile.write(b"0\\r\\n\\r\\n")
    def log_message(self, *a): pass
HTTPServer(("0.0.0.0", int(sys.argv[1])), H).serve_forever()
"""


def serve_sse(s: sdk.Session, port: int, gap_s: float) -> sdk.Job:
    """SSE_SERVER as a service (not work for idleness), once it listens."""
    s.machine.write(f"{s.machine.root}/sse.py", SSE_SERVER.encode())
    job = s.serve(f"exec python3 {s.machine.root}/sse.py {port} {gap_s}")
    eventually(lambda: s.machine.exec(f"python3 -c 'import socket; socket.create_connection((\"127.0.0.1\", {port}), 1)'")[0] == 0, timeout_s=60)
    return job


def get(url: str, headers: dict[str, str], timeout_s: float) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout_s) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


@pytest.mark.needs("undeclared-ports")
def test_an_undeclared_port_is_exposed_through_the_providers_gated_route(dev: Callable, name: str, scale: float) -> None:
    port = test_port()
    s = dev(ceiling_s=600)
    serve_sse(s, port, 0.0)
    endpoint = s.expose(port)  # not declared at create
    if name == "modal":  # the connect token: a bearer header, and nothing without it
        assert set(endpoint.headers) == {"Authorization"} and endpoint.headers["Authorization"].startswith("Bearer ")
        eventually(lambda: get(endpoint.url + "/", endpoint.headers, 30)[0] == 200, timeout_s=30 * scale)
        assert get(endpoint.url + "/", {}, 30)[0] in (401, 403)
    else:  # the local provider: this computer's own port, nothing to gate
        assert endpoint.headers == {}
    status, body = get(endpoint.url + "/", endpoint.headers, 30 * scale)
    assert (status, body.splitlines()[0]) == (200, b"seen: None")


@pytest.mark.needs("undeclared-ports")
def test_the_proxy_adds_the_endpoints_headers_and_streams(dev: Callable, scale: float) -> None:
    port, gap = test_port(), 1.0 * scale
    s = dev(ceiling_s=600)
    serve_sse(s, port, gap)
    exposed = s.expose(port)
    endpoint = sdk.Endpoint(exposed.url, {**exposed.headers, "X-Box-Test": "added-by-the-proxy"})
    with Proxy(endpoint, port=test_port()) as proxy:
        with urllib.request.urlopen(proxy.url + "/events", timeout=30 * scale) as resp:  # no headers of ours
            seen = resp.readline()
            started = time.monotonic()
            first = resp.readline()
            first_at = time.monotonic() - started
            rest = resp.read()
    assert seen == b"seen: added-by-the-proxy\n"
    assert first == b"data: 0\n"
    assert rest == b"\ndata: 1\n\ndata: 2\n\n"
    assert first_at < gap  # it came before the server finished: streamed, not buffered
    assert not [t for t in threading.enumerate() if t.name.startswith("box-proxy")]  # every thread joined


# ---- idle ----


@pytest.mark.needs("pty")
@pytest.mark.needs("undeclared-ports")
def test_a_pty_stream_and_a_proxy_in_use_keep_a_session_from_going_idle(dev: Callable, scale: float) -> None:
    idle_s = 3 * scale
    s = dev(ceiling_s=600, idle_timeout_s=idle_s)
    with s.stream(f"sleep {2.5 * idle_s}", pty=True) as stream:  # no job, no declared port: only its keepalive
        assert list(stream) == [] and stream.rc == 0
    assert isinstance(s.status(), Running)
    port = test_port()
    serve_sse(s, port, 0.8 * idle_s)  # a service: not work; one request through the proxy lasts 2.4 idle timeouts
    with s.proxy(port, local_port=test_port()) as proxy, urllib.request.urlopen(proxy.url + "/", timeout=30 * scale) as resp:
        assert resp.read().count(b"data:") == 3
    assert isinstance(s.status(), Running)
    assert s.wait(timeout_s=10 * idle_s) == Ended("idle")  # then nothing uses it


def test_a_log_follow_does_not_keep_a_session_from_going_idle(dev: Callable, scale: float) -> None:
    idle_s = 3 * scale
    s = dev(ceiling_s=600, idle_timeout_s=idle_s)
    ticker = s.serve("while true; do echo tick; sleep 0.5; done")  # a service: output, but not work
    stop, ticks = threading.Event(), []

    def follow() -> None:
        for chunk in ticker.logs(follow=True, stop=stop):
            ticks.append(chunk)

    follower = threading.Thread(target=follow, name="test-follower", daemon=False)
    follower.start()
    try:
        assert s.wait(timeout_s=10 * idle_s) == Ended("idle")  # followed all along: reading is not use
    finally:
        stop.set()
        follower.join(timeout=30 * scale)
        assert not follower.is_alive()
    assert ticks, "the follow saw nothing: it was not following"


# ---- shell ----


@pytest.mark.needs("shell")
def test_shell_argv_gives_a_shell_in_cwd_that_keeps_the_session_used(dev: Callable, name: str) -> None:
    if name != "local":
        pytest.skip("runs the argv with a pipe for its terminal; `modal shell` wants a real one")
    s = dev(ceiling_s=600, idle_timeout_s=8)
    remote(s, f"mkdir -p {s.machine.work}/here")
    before = float(remote(s, f"stat -f %m {s.machine.root}/activity || stat -c %Y {s.machine.root}/activity"))
    time.sleep(1.1)
    done = subprocess.run(s.shell_argv(cwd=f"{s.machine.work}/here"), input="pwd; exit 3\n", capture_output=True, text=True, timeout=60)
    assert done.returncode == 3, done.stderr
    assert done.stdout.strip().endswith("/work/here")
    after = float(remote(s, f"stat -f %m {s.machine.root}/activity || stat -c %Y {s.machine.root}/activity"))
    assert after > before  # the keepalive touched ROOT/activity while the shell ran


# ---- sync ----


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, timeout=60).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A git repo with a text file, a 200 kB binary, an executable and a symlink, committed."""
    root = tmp_path / "repo"
    (root / "pkg").mkdir(parents=True)
    git(root, "init", "-q", "-b", "main")
    (root / "pkg" / "a.txt").write_text("a\n")
    (root / "pkg" / "b.txt").write_text("b\n")
    (root / "blob.bin").write_bytes(os.urandom(200_000))
    (root / "run.sh").write_text("#!/bin/sh\necho ran\n")
    (root / "run.sh").chmod(0o755)
    (root / "link").symlink_to("pkg/a.txt")
    git(root, "add", "-A")
    git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init")
    return root


def sha1(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()


def test_sync_sends_adds_edits_deletes_modes_and_symlinks_and_then_nothing(dev: Callable, repo: Path) -> None:
    s = dev(ceiling_s=600)
    seed = s.sync(repo)
    t = seed.path
    assert t == f"{s.machine.work}/repo"
    assert remote(s, f"cat {t}/pkg/a.txt {t}/pkg/b.txt") == "a\nb"
    assert remote(s, f"{HASH} {t}/blob.bin") == sha1(repo / "blob.bin")
    assert remote(s, f"{t}/run.sh") == "ran"
    assert remote(s, f"readlink {t}/link") == "pkg/a.txt"

    (repo / "pkg" / "a.txt").write_text("a edited\n")  # not committed: the worktree as it is on disk
    (repo / "pkg" / "b.txt").unlink()
    (repo / "pkg" / "new.txt").write_text("new\n")  # untracked, under paths
    (repo / "stray.txt").write_text("stray\n")  # untracked, outside paths: stays home
    edit = s.sync(repo, paths=("pkg",))
    assert remote(s, f"cat {t}/pkg/a.txt {t}/pkg/new.txt") == "a edited\nnew"
    assert remote(s, f"ls {t}/pkg").split() == ["a.txt", "new.txt"]
    assert remote(s, f"test -e {t}/pkg/b.txt || echo deleted; test -e {t}/stray.txt || echo stayed-home") == "deleted\nstayed-home"
    assert 0 < edit.pack_bytes < seed.pack_bytes / 20, (edit.pack_bytes, seed.pack_bytes)  # the blob is not resent

    again = s.sync(repo, paths=("pkg",))
    assert (again.commit, again.pack_bytes) == (edit.commit, 0)  # nothing changed: nothing sent


def test_files_made_on_the_box_survive_a_sync(dev: Callable, repo: Path) -> None:
    s = dev(ceiling_s=600)
    t = s.sync(repo).path
    remote(s, f"mkdir -p {t}/runs && echo result > {t}/runs/out.txt")
    (repo / "pkg" / "a.txt").write_text("a2\n")
    s.sync(repo)
    assert remote(s, f"cat {t}/runs/out.txt {t}/pkg/a.txt") == "result\na2"


def test_a_tracked_file_changed_on_the_box_refuses_the_sync_unless_forced(dev: Callable, repo: Path) -> None:
    s = dev(ceiling_s=600)
    t = s.sync(repo).path
    remote(s, f"echo box-edit > {t}/pkg/a.txt")
    (repo / "pkg" / "b.txt").write_text("b2\n")
    with pytest.raises(gitsync.Drift, match="pkg/a.txt"):
        s.sync(repo)
    assert remote(s, f"cat {t}/pkg/a.txt {t}/pkg/b.txt") == "box-edit\nb"  # refused whole: nothing applied
    s.sync(repo, force=True)
    assert remote(s, f"cat {t}/pkg/a.txt {t}/pkg/b.txt") == "a\nb2"
    assert remote(s, f"git -C {t} status --porcelain --untracked-files=no") == ""  # git works on the box


def test_two_worktrees_share_one_box_and_its_object_store(dev: Callable, repo: Path, tmp_path: Path) -> None:
    other = tmp_path / "other-wt"
    git(repo, "worktree", "add", "-q", "--detach", str(other))
    (other / "pkg" / "a.txt").write_text("other\n")
    s = dev(ceiling_s=600)
    first, second = s.sync(repo), s.sync(other)
    assert (first.path, second.path) == (f"{s.machine.work}/repo", f"{s.machine.work}/other-wt")
    assert remote(s, f"cat {first.path}/pkg/a.txt {second.path}/pkg/a.txt") == "a\nother"
    assert second.pack_bytes < first.pack_bytes / 20  # the blob was already on the box, from the first
    assert remote(s, f"ls -d {s.machine.work}/*/.git | wc -l") == "2"


def test_a_sync_is_use_and_a_run_sees_the_synced_code(dev: Callable, repo: Path, scale: float) -> None:
    s = dev(ceiling_s=600, idle_timeout_s=3 * scale)
    deadline = time.monotonic() + 2.5 * 3 * scale  # past the idle timeout, only syncs in between
    while time.monotonic() < deadline:
        s.sync(repo)
        time.sleep(scale)
    assert isinstance(s.status(), Running)
    job = s.run(f"cd {shlex.quote(s.machine.work)}/repo && cat pkg/a.txt", max_duration_s=JOB_S)
    assert job.wait() == Ending("exited", 0)
    assert "".join(c.text for c in job.logs()) == "a\n"


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_the_proxy_serves_on_after_its_session_is_gone_but_not_after_a_bug_in_marking_it_used(capsys: pytest.CaptureFixture) -> None:
    import http.server

    class Ok(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *args: object) -> None:
            pass

    upstream = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Ok)
    threading.Thread(target=upstream.serve_forever, daemon=True).start()
    endpoint = sdk.Endpoint(f"http://127.0.0.1:{upstream.server_address[1]}")
    try:
        for failure, served in ((sdk.Gone("the machine is gone"), True), (KeyError("a bug"), False)):

            def on_use(e: BaseException = failure) -> None:
                raise e

            with Proxy(endpoint, on_use=on_use, every_s=3600) as proxy:
                try:
                    with urllib.request.urlopen(proxy.url + "/", timeout=10) as r:
                        got = r.read() == b"ok"
                except (urllib.error.URLError, ConnectionError, http.client.RemoteDisconnected):
                    got = False
                assert got is served, failure
                assert proxy._inflight == 0
    finally:
        upstream.shutdown()
        upstream.server_close()
    assert "marking the session used failed: Gone" in capsys.readouterr().err
