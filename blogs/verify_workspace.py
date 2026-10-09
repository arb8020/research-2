"""Workspace cells end to end: engine/ch00-toy.md in headless Chromium, through the Connect path (connect_dev.py).

    uv run --with playwright verify_workspace.py                  # sandbox = a local Jupyter (connect_dev --root)
    uv run --with playwright --with modal verify_workspace.py --modal   # sandbox = a Modal CPU sandbox (ws_modal.py)

Evidence goes to .evidence/verify_workspace/ (or verify_workspace-modal/; gitignored, kept until the next run):
numbered screenshots, story.log (what each step saw), timings.json, git-log.txt (the restored workspace's history),
connect_dev logs; locally also the two Jupyter roots and the persist dir (root1/, root2/, persist/).

Phases (the shape a verify-blogs skill can call one by one):
  launch   build the page; serve dist/; start sandbox 1 (local root1, or a Modal sandbox with Jupyter on the relay's
           flags and the persist dir on a Volume) and connect_dev.py in front of it
  doctor   g++ / make / git in the sandbox; the page ships ws.py + ref.bundle; after Connect the workspace is
           seeded (tag ref/ch00/start) and only the first cell is unlocked
  drive    the story:
             1  ring.cpp with a missing ';' -> Run -> the compiler error streams in; its ring.cpp:L:C link moves the
                ring editor's cursor to line L; nothing committed
             2  fixed -> Run -> pass: commit + tag pass/ch00/ring on the checked text, the bundle saved; loop unlocks
             3  a loop.cpp draft saves to the workspace (the save latency); drop the browser's draft copies; reload:
                the editor shows the draft, read back from the workspace
             4  loop.cpp that never returns -> Run; while it runs, a scratch cell runs on the same kernel; Stop kills
                the check (and its check_trace) without committing
             5  loop passes; a budget.py draft (the Python cell) is typed but not run
             6  sandbox 1 and connect_dev stop; sandbox 2 starts fresh with the same persist dir. Reconnect: the
                workspace is restored from the bundle (refs identical to sandbox 1's); ring/loop show their passing
                versions; the budget draft comes back from the browser's copy and is written to the new workspace
             7  budget passes in the restored workspace
  evidence screenshots, story.log, timings.json, git-log.txt
  cleanup  stop only what this script started: connect_dev (every process it spawned must be gone, or the run fails),
           the static server, and on Modal both sandboxes (none of this app's sandboxes may be left; the Volume is
           ephemeral)
"""

from __future__ import annotations

import argparse
import functools
import glob
import json
import os
import re
import shlex
import shutil
import signal
import statistics
import subprocess
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Protocol
from urllib.request import urlopen

from playwright.sync_api import Page, expect, sync_playwright

import ref

HERE = Path(__file__).parent
CHAPTER = HERE / "engine" / "ch00-toy.md"
CH = "ch00"
PAGE = "ch00-toy"
CHROME = sorted(glob.glob(os.path.expanduser(
    "~/Library/Caches/ms-playwright/chromium-*/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing")))[-1]  # fmt: skip
TOKEN = ("ak-verify-workspace-0001", "as-verify-workspace-secret")
SOLUTION = {path: f.data.decode() for path, f in ref.materialize(CH, "solution").items()}
BROKEN_STATEMENT = "    r->tail += 1;\n"  # in ring_push; the broken ring.cpp drops its ';'
HANG = "void sched_step(const Request* reqs, Ring* waiting, u32 budget, Batch* out) {\n"
SCRATCH = "print('scratch ran while the check was running:', 6 * 7)"
CHECK_TIMEOUT_MS = 90_000
SAVE_WAIT_S = 15
CELLS = 3


# ---- the sandbox seam: a local Jupyter root, or a Modal sandbox (ws_modal.ModalBox) ----


class Box(Protocol):
    name: str
    persist: str  # $BLOGS_WS_PERSIST as the sandbox sees it

    def gateway_args(self) -> list[str]: ...
    def sh(self, cmd: str) -> str: ...  # bash -c in the Jupyter root (the kernel's cwd); raises on a non-zero exit
    def close(self) -> None: ...


class LocalBox:
    """connect_dev.py starts Jupyter itself, on this root; the box is just the directories."""

    def __init__(self, name: str, out: Path) -> None:
        self.name = name
        self.root = out / name
        self.persist = str(out / "persist")

    def gateway_args(self) -> list[str]:
        return ["--root", str(self.root), "--persist", self.persist]

    def sh(self, cmd: str) -> str:
        self.root.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(["bash", "-c", cmd], cwd=self.root, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            raise RuntimeError(f"[{self.name}] `{cmd}` exited {proc.returncode}:\n{proc.stdout}{proc.stderr}")
        return proc.stdout

    def close(self) -> None:
        pass  # connect_dev owned its Jupyter; Gateway.stop proved it gone


@dataclass
class Run:
    page: Page
    out: Path
    new_box: Callable[[str], Box]
    gateway_port: int
    timings: dict[str, Any] = field(default_factory=dict)
    log: list[str] = field(default_factory=list)

    def say(self, text: str) -> None:
        print(f"  {text}", flush=True)
        self.log.append(text)

    def shot(self, name: str) -> None:
        self.page.screenshot(path=self.out / f"{name}.png")


# ---- small helpers ----


def git(box: Box, *args: str) -> str:
    return box.sh("git -C workspace " + shlex.join(args))


def refs(box: Box) -> str:
    return git(box, "for-each-ref", "--format=%(objectname) %(refname)")


def wait_saved(box: Box, file: str, text: str) -> None:
    deadline = time.monotonic() + SAVE_WAIT_S
    while box.sh(f"cat workspace/{shlex.quote(file)}") != text:
        assert time.monotonic() < deadline, f"{file} never reached the workspace in {SAVE_WAIT_S}s"
        time.sleep(0.05)


def set_doc(page: Page, cell: str, text: str) -> None:
    """Replace a ws-cell's editor text, as typing would (the cell saves it, debounced)."""
    page.evaluate("([n, s]) => { const v = document.querySelector(`ws-cell[name=${n}]`).view; v.dispatch({changes: {from: 0, to: v.state.doc.length, insert: s}}); }", [cell, text])


def doc(page: Page, cell: str) -> str:
    return page.evaluate("(n) => document.querySelector(`ws-cell[name=${n}]`).view.state.doc.toString()", cell)


DONE = "(n) => { const c = document.querySelector(`ws-cell[name=${n}]`); return !c.hasAttribute('data-job') && c.querySelector('.cell-out:is(.pass, .fail)') && !c.querySelector('.cell-status').textContent.startsWith('checking'); }"


def run_cell(page: Page, cell: str) -> tuple[str, str, float]:
    """Click Run; wait for the verdict. Returns (status text, output text, seconds from click to verdict)."""
    el = page.locator(f"ws-cell[name={cell}]")
    el.scroll_into_view_if_needed()
    t0 = time.perf_counter()
    el.locator(".run").click()
    page.wait_for_function(DONE, arg=cell, timeout=CHECK_TIMEOUT_MS)
    took = time.perf_counter() - t0
    return el.locator(".cell-status").inner_text(), el.locator(".cell-out").inner_text(), took


def bundle_note(output: str) -> tuple[float, int]:
    """(KiB, ms) from ws.py's PASS line: 'bundle 8.8 KiB saved in 36 ms'."""
    m = re.search(r"bundle ([\d.]+) KiB saved in (\d+) ms", output)
    assert m, f"no bundle line in the output:\n{output}"
    return float(m[1]), int(m[2])


def connect(page: Page) -> None:
    page.locator(".connect-pill").click()
    if page.locator("input[name=token-id]").is_visible():
        page.fill("input[name=token-id]", TOKEN[0])
        page.fill("input[name=token-secret]", TOKEN[1])
    page.locator(".connect-go").click()
    page.wait_for_selector("connect-pill[data-phase=connected]", timeout=120_000)
    page.wait_for_function(f"document.querySelectorAll('ws-cell[data-loaded]').length === {CELLS}", timeout=120_000)


# ---- launch / cleanup ----


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, fmt: str, *args: object) -> None:
        pass


@contextmanager
def static_server(port: int) -> Iterator[None]:
    server = ThreadingHTTPServer(("127.0.0.1", port), functools.partial(Quiet, directory=str(HERE / "dist")))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield
    finally:
        server.shutdown()


def descendants(pid: int) -> set[int]:
    rows = subprocess.run(["ps", "-A", "-o", "pid=,ppid="], capture_output=True, text=True, check=True).stdout.split("\n")
    children: dict[int, list[int]] = {}
    for row in rows:
        if row.strip():
            p, pp = (int(x) for x in row.split())
            children.setdefault(pp, []).append(p)
    found: set[int] = set()
    todo = [pid]
    while todo:
        for c in children.get(todo.pop(), []):
            if c not in found:
                found.add(c)
                todo.append(c)
    return found


def alive(pids: set[int]) -> set[int]:
    left = set()
    for p in pids:
        try:
            os.kill(p, 0)
            left.add(p)
        except ProcessLookupError:
            pass
    return left


class Gateway:
    """connect_dev.py in front of one box, started by this script and only stopped by it. Remembers every process
    it spawned (locally: Jupyter, kernels, check jobs) so stop() can prove they all ended."""

    def __init__(self, port: int, box: Box, out: Path) -> None:
        self.box = box
        self.log = (out / f"connect_dev-{box.name}.log").open("wb")
        self.proc = subprocess.Popen(["uv", "run", "connect_dev.py", "--port", str(port), "--boot-delay", "0.1", *box.gateway_args()],
                                     cwd=HERE, stdout=self.log, stderr=self.log)  # fmt: skip
        self.seen: set[int] = set()
        for _ in range(240):  # the first run installs jupyter_server
            try:
                urlopen(f"http://127.0.0.1:{port}/sessions/none")
            except OSError as e:
                if getattr(e, "code", None) == 404:
                    return
                time.sleep(0.5)
        self.proc.kill()
        raise RuntimeError(f"connect_dev.py never answered on :{port} (see {self.log.name})")

    def remember(self) -> None:
        self.seen |= descendants(self.proc.pid)

    def stop(self) -> str:
        self.remember()
        self.proc.send_signal(signal.SIGTERM)  # connect_dev ends every session (stops its Jupyter) on TERM
        self.proc.wait(30)
        deadline = time.monotonic() + 15
        while alive(self.seen) and time.monotonic() < deadline:
            time.sleep(0.2)
        left = alive(self.seen)
        assert not left, f"processes connect_dev ({self.box.name}) started are still running: {left}"
        self.box.close()
        return f"cleanup: connect_dev ({self.box.name}) stopped; all {len(self.seen)} processes it started are gone"


# ---- doctor ----


def doctor_page() -> str:
    dist = HERE / "dist" / PAGE
    for f in ("index.html", "page.js", "ws.py", "ref.bundle"):
        assert (dist / f).is_file(), f"the built page lacks {f}"
    return "doctor: the page ships ws.py + ref.bundle"


def doctor_box(box: Box) -> str:
    versions = box.sh("g++ --version | head -1; make --version | head -1; git --version")
    return f"doctor: {box.name} has the toolchain: {' | '.join(versions.strip().splitlines())}"


def doctor_workspace(run: Run, box: Box) -> None:
    assert "refs/tags/ref/ch00/start" in refs(box), refs(box)
    expect(run.page.locator("ws-cell[name=ring] .run")).to_be_enabled()
    for cell in ("loop", "budget"):
        expect(run.page.locator(f"ws-cell[name={cell}] .run")).to_be_disabled()
        expect(run.page.locator(f"ws-cell[name={cell}] .cell-status")).to_have_text("locked until ring passes")
    run.say(f"doctor: workspace {run.page.evaluate('document.documentElement.dataset.workspaceBoot')}; tag ref/ch00/start; ring unlocked, loop + budget locked")


# ---- drive ----


def step_compile_error(run: Run, box: Box) -> None:
    page = run.page
    broken = SOLUTION["ring.cpp"].replace(BROKEN_STATEMENT, BROKEN_STATEMENT.replace(";", ""))
    line = SOLUTION["ring.cpp"].split("\n").index(BROKEN_STATEMENT.rstrip("\n")) + 1
    set_doc(page, "ring", broken)
    status, out, took = run_cell(page, "ring")
    run.timings["check_fail_compile_s"] = round(took, 3)
    assert status.startswith("failed"), status
    assert "error" in out, out
    links = page.locator("ws-cell[name=ring] .cell-out a.out-link")
    locs = [links.nth(i).get_attribute("data-loc") for i in range(links.count())]
    ring_links = [loc for loc in locs if loc and loc.startswith("ring.cpp:")]
    assert ring_links, f"no ring.cpp link in the output; links {locs}\n{out}"
    target = ring_links[0]
    link_line = int(target.split(":")[1])
    # clang points past the statement (its own line); gcc points at the next token (the next line)
    assert link_line in (line, line + 1), f"the error points at line {link_line}; the broken statement is line {line}"
    page.locator(f"ws-cell[name=ring] .cell-out a.out-link[data-loc='{target}']").first.click()
    cursor = page.evaluate("() => { const v = document.querySelector('ws-cell[name=ring]').view; const h = v.state.selection.main.head; return {line: v.state.doc.lineAt(h).number, focused: v.hasFocus}; }")
    assert cursor == {"line": link_line, "focused": True}, cursor
    assert "pass/ch00/ring" not in refs(box), "a failed check committed"
    run.shot("1-compile-error-link")
    run.say(f"1 compile error: {took:.2f}s to the verdict; link {target} -> ring editor cursor on line {cursor['line']} (focused); nothing committed")


def step_pass(run: Run, box: Box, cell: str, file: str) -> None:
    set_doc(run.page, cell, SOLUTION[file])
    status, out, took = run_cell(run.page, cell)
    assert status.startswith("passed"), f"{status}\n{out}"
    run.timings.setdefault("check_pass_s", []).append(round(took, 3))
    kib, ms = bundle_note(out)
    run.timings.setdefault("bundle_kib", []).append(kib)
    run.timings.setdefault("bundle_write_ms", []).append(ms)
    assert f"refs/tags/pass/ch00/{cell}" in refs(box)
    assert git(box, "show", f"pass/ch00/{cell}:{file}") == SOLUTION[file], "the tagged commit isn't the checked text"
    box.sh(f"test -s {box.persist}/workspace.bundle")
    run.shot(f"2-pass-{cell}")
    run.say(f"pass {cell}: {took:.2f}s click -> verdict; tag pass/ch00/{cell} on the checked text; bundle {kib} KiB saved in {ms} ms")


def step_reload_from_workspace(run: Run, box: Box) -> None:
    page = run.page
    draft = SOLUTION["loop.cpp"].replace("// loop.cpp", "// loop.cpp (a draft, not run yet)")
    set_doc(page, "loop", draft)
    wait_saved(box, "loop.cpp", draft)
    saves = []
    for i in range(5):  # a few more edits for a save-latency sample
        text = draft + f"// edit {i}\n"
        set_doc(page, "loop", text)
        wait_saved(box, "loop.cpp", text)
        page.wait_for_timeout(50)
        saves.append(page.evaluate("document.querySelector('ws-cell[name=loop]').lastSaveMs"))
    set_doc(page, "loop", draft)
    wait_saved(box, "loop.cpp", draft)
    run.timings["save_ms"] = [round(s, 1) for s in saves]
    page.evaluate("Object.keys(localStorage).filter((k) => k.startsWith('blogs.ws.')).forEach((k) => localStorage.removeItem(k))")
    page.reload()
    page.wait_for_function(f"document.querySelectorAll('ws-cell[data-loaded]').length === {CELLS}", timeout=120_000)
    assert doc(page, "loop") == draft, "after reload the loop editor doesn't show the workspace's draft"
    assert page.get_attribute("ws-cell[name=loop]", "data-loaded") == "workspace"
    expect(page.locator("ws-cell[name=ring] .cell-status")).to_have_text("passed")
    run.shot("3-reloaded")
    run.say(f"3 reload: loop draft read back from the workspace (browser copies dropped first); saves {statistics.median(saves):.0f} ms median")


def step_scratch_and_stop(run: Run, box: Box) -> None:
    page = run.page
    hang = SOLUTION["loop.cpp"].replace(HANG, HANG + "    while (budget > 0) {\n    } // never returns\n")
    set_doc(page, "loop", hang)
    cell = page.locator("ws-cell[name=loop]")
    cell.scroll_into_view_if_needed()
    cell.locator(".run").click()
    page.wait_for_function("document.querySelector('ws-cell[name=loop] .cell-out').textContent.includes('check_trace sched.trace')", timeout=CHECK_TIMEOUT_MS)
    page.wait_for_timeout(300)
    assert page.get_attribute("ws-cell[name=loop]", "data-job") is not None
    page.evaluate("(s) => { const v = document.querySelector('scratch-cell').view; v.dispatch({changes: {from: 0, to: v.state.doc.length, insert: s}}); }", SCRATCH)
    page.locator("scratch-cell").scroll_into_view_if_needed()
    t0 = time.perf_counter()
    page.locator("scratch-cell .run").click()
    page.wait_for_selector("scratch-cell .cell-out.pass", timeout=30_000)
    scratch_s = time.perf_counter() - t0
    assert "scratch ran while the check was running: 42" in page.locator("scratch-cell .cell-out").inner_text()
    assert page.get_attribute("ws-cell[name=loop]", "data-job") is not None, "the check ended before the scratch cell ran"
    spinning = box.sh("pgrep -f 'build/debug/check_trac[e] ' || true").split()
    assert spinning, "the hanging check_trace isn't running"
    run.shot("4-scratch-during-check")
    cell.scroll_into_view_if_needed()
    expect(cell.locator(".run")).to_have_text("Stop")
    t1 = time.perf_counter()
    cell.locator(".run").click()
    page.wait_for_function(DONE, arg="loop", timeout=10_000)
    stop_s = time.perf_counter() - t1
    status = cell.locator(".cell-status").inner_text()
    assert status.startswith("stopped"), status
    time.sleep(0.3)
    left = box.sh("pgrep -f 'build/debug/check_trac[e] ' || true").split()
    assert not left, f"check_trace survived Stop: {left}"
    assert "pass/ch00/loop" not in refs(box)
    run.timings["scratch_during_check_s"] = round(scratch_s, 3)
    run.timings["stop_to_verdict_s"] = round(stop_s, 3)
    run.shot("4-stopped")
    run.say(f"4 scratch cell ran in {scratch_s:.2f}s while the loop check spun; Stop -> '{status}' in {stop_s:.2f}s; check_trace gone; nothing committed")


def step_restart(run: Run, old: Gateway) -> Gateway:
    page = run.page
    budget_draft = SOLUTION["budget.py"]
    set_doc(page, "budget", budget_draft)
    wait_saved(old.box, "budget.py", budget_draft)
    before = refs(old.box)
    run.say(old.stop())
    box = run.new_box("sandbox2")
    gateway = Gateway(run.gateway_port, box, run.out)
    page.reload()
    page.wait_for_selector("connect-pill[data-phase=disconnected]", timeout=30_000)
    t0 = time.perf_counter()
    connect(page)
    run.timings["reconnect_to_loaded_s"] = round(time.perf_counter() - t0, 3)
    boot = page.evaluate("document.documentElement.dataset.workspaceBoot")
    assert boot.startswith("restored "), boot
    run.timings["restore_ms"] = int(boot.split()[1].removesuffix("ms"))
    after = refs(box)
    assert after == before, f"refs differ after restore:\n{before}\n---\n{after}"
    assert doc(page, "ring") == SOLUTION["ring.cpp"]
    assert doc(page, "loop") == SOLUTION["loop.cpp"]
    assert doc(page, "budget") == budget_draft
    assert page.get_attribute("ws-cell[name=budget]", "data-loaded") == "browser"
    wait_saved(box, "budget.py", budget_draft)
    for cell in ("ring", "loop"):
        expect(page.locator(f"ws-cell[name={cell}] .cell-status")).to_have_text("passed")
    run.shot("6-restored")
    run.say(f"6 new sandbox ({box.name}): workspace {boot}; refs identical ({len(after.splitlines())}); ring + loop passing versions; "
            f"budget draft from this browser, written to the new workspace")  # fmt: skip
    return gateway


def drive(run: Run, gateway: Gateway) -> Gateway:
    box = gateway.box
    t0 = time.perf_counter()
    connect(run.page)
    run.timings["first_connect_to_loaded_s"] = round(time.perf_counter() - t0, 3)
    doctor_workspace(run, box)
    run.shot("0-connected")
    step_compile_error(run, box)
    step_pass(run, box, "ring", "ring.cpp")
    expect(run.page.locator("ws-cell[name=loop] .run")).to_be_enabled()
    expect(run.page.locator("ws-cell[name=budget] .cell-status")).to_have_text("locked until loop passes")
    run.say("2 loop unlocked; budget now waits for loop")
    step_reload_from_workspace(run, box)
    step_scratch_and_stop(run, box)
    gateway.remember()
    step_pass(run, box, "loop", "loop.cpp")
    gateway = step_restart(run, gateway)
    step_pass(run, gateway.box, "budget", "budget.py")
    (run.out / "git-log.txt").write_text(git(gateway.box, "log", "--oneline", "--decorate", "--all"))
    run.say("7 budget (Python) passed in the restored workspace")
    return gateway


def box_factory(modal: bool, out: Path, origin: str, stack: ExitStack) -> Callable[[str], Box]:
    if not modal:
        return lambda name: LocalBox(name, out)
    import ws_modal  # only with --modal: needs the modal package and a Modal token

    volume = stack.enter_context(ws_modal.modal.Volume.ephemeral())  # deleted when the run ends
    return lambda name: ws_modal.ModalBox(name, volume, origin)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--modal", action="store_true", help="sandboxes on Modal (CPU) instead of local Jupyter roots")
    ap.add_argument("--gateway-port", type=int, default=8793)
    ap.add_argument("--page-port", type=int, default=8013)
    ap.add_argument("--slow-mo", type=int, default=0, help="ms between browser actions (a watchable run: 250)")
    args = ap.parse_args()

    out = HERE / ".evidence" / ("verify_workspace-modal" if args.modal else "verify_workspace")
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    origin = f"http://localhost:{args.page_port}"
    print("launch", flush=True)
    subprocess.run(["uv", "run", "build_page.py", str(CHAPTER.relative_to(HERE))], cwd=HERE, check=True, stdout=subprocess.DEVNULL)
    errors: list[str] = []
    gateway: Gateway | None = None
    with ExitStack() as stack:
        new_box = box_factory(args.modal, out, origin, stack)
        stack.enter_context(static_server(args.page_port))
        p = stack.enter_context(sync_playwright())
        browser = p.chromium.launch(executable_path=CHROME, slow_mo=args.slow_mo)
        page = browser.new_page(viewport={"width": 1100, "height": 900})
        page.on("pageerror", lambda e: errors.append(str(e)))
        run = Run(page, out, new_box, args.gateway_port)
        try:
            box = new_box("sandbox1")
            print("doctor", flush=True)
            run.say(doctor_page())
            run.say(doctor_box(box))
            gateway = Gateway(args.gateway_port, box, out)
            page.goto(f"{origin}/{PAGE}/?gateway=http://localhost:{args.gateway_port}")
            expect(page.locator("ws-cell[name=ring] .cell-status")).to_have_text("connect to load your workspace")
            print("drive", flush=True)
            gateway = drive(run, gateway)
        except Exception:
            run.shot("failed")
            cells = page.evaluate("[...document.querySelectorAll('ws-cell')].map((c) => `${c.getAttribute('name')}: ${c.querySelector('.cell-status').textContent} | ${c.querySelector('.cell-out').textContent.slice(-600)}`)")
            print("FAILED; the cells said:\n  " + "\n  ".join(cells) + f"\npage errors: {errors}", flush=True)
            raise
        finally:
            print("cleanup", flush=True)
            browser.close()
            if gateway is not None:
                run.say(gateway.stop())
            if args.modal:
                import ws_modal

                left = ws_modal.leftovers(kill=True)
                assert left == 0, f"{left} Modal sandbox(es) were still running (now terminated)"
                run.say(f"cleanup: no sandboxes left under Modal app {ws_modal.APP}; the Volume was ephemeral")
    assert not errors, f"page errors: {errors}"
    print("evidence", flush=True)
    (out / "timings.json").write_text(json.dumps(run.timings, indent=1))
    (out / "story.log").write_text("\n".join(run.log) + "\n")
    run.say(f"timings: {json.dumps(run.timings)}")
    print(f"ok: {out}/ ({', '.join(sorted(p.name for p in out.iterdir()))})")


if __name__ == "__main__":
    main()
