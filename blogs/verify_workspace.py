"""Workspace cells end to end: engine/ch00-toy.md in headless Chromium against connect_dev.py (a real local Jupyter).

    uv run --with playwright verify_workspace.py [--slow-mo 250]

Evidence goes to .evidence/verify_workspace/ (gitignored; kept after the run, replaced by the next one): numbered
screenshots, story.log (what each step saw), timings.json, git-log.txt (the restored workspace's history), and the
two Jupyter roots + the persist dir themselves (root1/, root2/, persist/), so the repos can be inspected after.

Phases (the shape a verify-blogs skill can call one by one):
  launch   build the page; serve dist/; start connect_dev.py --root root1 --persist persist
  doctor   g++ / make / git on PATH; the page ships ws.py + ref.bundle; the gateway answers; after Connect the
           workspace is seeded (tag ref/ch00/start) and only the first cell is unlocked
  drive    the story:
             1  ring.cpp with a missing ';' -> Run -> the compiler error streams in; its ring.cpp:L:C link moves the
                ring editor's cursor to line L; nothing committed
             2  fixed -> Run -> pass: commit + tag pass/ch00/ring, the bundle in persist/, loop unlocks
             3  a loop.cpp draft saves to root1/workspace (the save latency); drop the browser's draft copies; reload:
                the editor shows the draft, read back from the workspace
             4  loop.cpp that never returns -> Run; while it runs, a scratch cell runs on the same kernel; Stop kills
                the check (and its check_trace) without committing
             5  loop passes; a budget.py draft (Python cell) is typed but not run
             6  connect_dev restarts with a fresh root (root2) and the same persist dir: a new sandbox. Reconnect: the
                workspace is restored from the bundle (refs identical to root1's); ring/loop show their passing
                versions; the budget draft comes back from the browser's copy and is written to the new workspace
             7  budget passes in the restored workspace
  evidence screenshots, story.log, timings.json, git-log.txt
  cleanup  stop only what this script started (connect_dev, the static server); every process that connect_dev
           started (Jupyter, kernels, check jobs) must be gone afterwards, or the run fails
"""

from __future__ import annotations

import argparse
import functools
import glob
import json
import os
import re
import shutil
import signal
import statistics
import subprocess
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from playwright.sync_api import Page, expect, sync_playwright

import ref

HERE = Path(__file__).parent
OUT = HERE / ".evidence" / "verify_workspace"
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
CHECK_TIMEOUT_MS = 60_000
SAVE_WAIT_S = 10


# ---- small helpers ----

LOG: list[str] = []


def say(text: str) -> None:
    print(f"  {text}", flush=True)
    LOG.append(text)


def shot(page: Page, name: str) -> None:
    page.screenshot(path=OUT / f"{name}.png", full_page=False)


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root / "workspace", capture_output=True, text=True, check=True).stdout


def refs(root: Path) -> str:
    return git(root, "for-each-ref", "--format=%(objectname) %(refname)")


def set_doc(page: Page, cell: str, text: str) -> None:
    """Replace a ws-cell's editor text, as typing would (the cell saves it, debounced)."""
    page.evaluate("([n, s]) => { const v = document.querySelector(`ws-cell[name=${n}]`).view; v.dispatch({changes: {from: 0, to: v.state.doc.length, insert: s}}); }", [cell, text])


def doc(page: Page, cell: str) -> str:
    return page.evaluate("(n) => document.querySelector(`ws-cell[name=${n}]`).view.state.doc.toString()", cell)


def run_cell(page: Page, cell: str) -> tuple[str, str, float]:
    """Click Run; wait for the verdict. Returns (status text, output text, seconds from click to verdict)."""
    cell_el = page.locator(f"ws-cell[name={cell}]")
    cell_el.scroll_into_view_if_needed()
    t0 = time.perf_counter()
    cell_el.locator(".run").click()
    page.wait_for_function("(n) => { const c = document.querySelector(`ws-cell[name=${n}]`); return !c.hasAttribute('data-job') && c.querySelector('.cell-out:is(.pass, .fail)') && !c.querySelector('.cell-status').textContent.startsWith('checking'); }",
                           arg=cell, timeout=CHECK_TIMEOUT_MS)  # fmt: skip
    took = time.perf_counter() - t0
    return cell_el.locator(".cell-status").inner_text(), cell_el.locator(".cell-out").inner_text(), took


def wait_saved(root: Path, file: str, text: str) -> None:
    deadline = time.monotonic() + SAVE_WAIT_S
    while (root / "workspace" / file).read_text() != text:
        assert time.monotonic() < deadline, f"{file} never reached the workspace in {SAVE_WAIT_S}s"
        time.sleep(0.05)


def bundle_note(output: str) -> tuple[float, int]:
    """(KiB, ms) from ws.py's PASS line: 'bundle 8.8 KiB saved in 36 ms'."""
    m = re.search(r"bundle ([\d.]+) KiB saved in (\d+) ms", output)
    assert m, f"no bundle line in the output:\n{output}"
    return float(m[1]), int(m[2])


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
    """connect_dev.py, started by this script and only ever stopped by it. Remembers every process it spawned."""

    def __init__(self, port: int, root: Path, persist: Path) -> None:
        self.port, self.root = port, root
        self.log = (OUT / f"connect_dev-{root.name}.log").open("wb")
        self.proc = subprocess.Popen(["uv", "run", "connect_dev.py", "--port", str(port), "--boot-delay", "0.1", "--root", str(root), "--persist", str(persist)],
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
        """Note every process under connect_dev now (Jupyter, kernels, running checks): cleanup proves they ended."""
        self.seen |= descendants(self.proc.pid)

    def stop(self) -> None:
        self.remember()
        self.proc.send_signal(signal.SIGTERM)  # connect_dev ends every session (stops its Jupyter) on TERM
        self.proc.wait(30)
        deadline = time.monotonic() + 15
        while alive(self.seen) and time.monotonic() < deadline:
            time.sleep(0.2)
        left = alive(self.seen)
        assert not left, f"processes connect_dev ({self.root.name}) started are still running: {left}"
        say(f"cleanup: connect_dev ({self.root.name}) stopped; all {len(self.seen)} processes it started are gone")


# ---- doctor ----


def doctor_toolchain() -> None:
    for tool in ("g++", "make", "git"):
        assert shutil.which(tool), f"{tool} is not on PATH: the workspace checks need it"
    dist = HERE / "dist" / PAGE
    for f in ("index.html", "page.js", "ws.py", "ref.bundle"):
        assert (dist / f).is_file(), f"the built page lacks {f}"
    say("doctor: g++, make, git on PATH; the page ships ws.py + ref.bundle")


def connect(page: Page) -> None:
    page.locator(".connect-pill").click()
    if page.locator("input[name=token-id]").is_visible():
        page.fill("input[name=token-id]", TOKEN[0])
        page.fill("input[name=token-secret]", TOKEN[1])
    page.locator(".connect-go").click()
    page.wait_for_selector("connect-pill[data-phase=connected]", timeout=120_000)
    page.wait_for_function("document.querySelectorAll('ws-cell[data-loaded]').length === 3", timeout=60_000)


def doctor_workspace(page: Page, root: Path) -> None:
    assert "ref/ch00/start" in refs(root), refs(root)
    expect(page.locator("ws-cell[name=ring] .run")).to_be_enabled()
    for cell in ("loop", "budget"):
        expect(page.locator(f"ws-cell[name={cell}] .run")).to_be_disabled()
        expect(page.locator(f"ws-cell[name={cell}] .cell-status")).to_have_text("locked until ring passes")
    say(f"doctor: workspace {page.evaluate('document.documentElement.dataset.workspaceBoot')}; tag ref/ch00/start; ring unlocked, loop + budget locked")


# ---- drive ----


def step_compile_error(page: Page, root: Path, timings: dict[str, Any]) -> None:
    broken = SOLUTION["ring.cpp"].replace(BROKEN_STATEMENT, BROKEN_STATEMENT.replace(";", ""))
    line = SOLUTION["ring.cpp"].split("\n").index(BROKEN_STATEMENT.rstrip("\n")) + 1
    set_doc(page, "ring", broken)
    status, out, took = run_cell(page, "ring")
    timings["check_fail_compile_s"] = round(took, 3)
    assert status.startswith("failed"), status
    assert "error" in out, out
    links = page.locator("ws-cell[name=ring] .cell-out a.out-link")
    locs = [links.nth(i).get_attribute("data-loc") for i in range(links.count())]
    ring_links = [loc for loc in locs if loc and loc.startswith("ring.cpp:")]
    assert ring_links, f"no ring.cpp link in the output; links {locs}\n{out}"
    target = ring_links[0]
    link_line = int(target.split(":")[1])
    assert link_line in (line, line + 1), f"the error points at line {link_line}; the broken statement is line {line}"
    page.locator(f"ws-cell[name=ring] .cell-out a.out-link[data-loc='{target}']").first.click()
    cursor = page.evaluate("() => { const v = document.querySelector('ws-cell[name=ring]').view; const h = v.state.selection.main.head; return {line: v.state.doc.lineAt(h).number, focused: v.hasFocus}; }")
    assert cursor == {"line": link_line, "focused": True}, cursor
    assert "pass/ch00/ring" not in refs(root), "a failed check committed"
    shot(page, "1-compile-error-link")
    say(f"1 compile error: {took:.2f}s to the verdict; link {target} -> ring editor cursor on line {cursor['line']} (focused); nothing committed")


def step_pass(page: Page, root: Path, persist: Path, timings: dict[str, Any], cell: str, file: str) -> None:
    set_doc(page, cell, SOLUTION[file])
    status, out, took = run_cell(page, cell)
    assert status.startswith("passed"), f"{status}\n{out}"
    timings.setdefault("check_pass_s", []).append(round(took, 3))
    kib, ms = bundle_note(out)
    timings.setdefault("bundle_kib", []).append(kib)
    timings.setdefault("bundle_write_ms", []).append(ms)
    assert f"refs/tags/pass/ch00/{cell}" in refs(root)
    assert git(root, "show", f"pass/ch00/{cell}:{file}") == SOLUTION[file], "the tagged commit isn't the checked text"
    assert (persist / "workspace.bundle").is_file()
    shot(page, f"2-pass-{cell}")
    say(f"pass {cell}: {took:.2f}s click -> verdict; tag pass/ch00/{cell} on the checked text; bundle {kib} KiB written in {ms} ms")


def step_reload_from_workspace(page: Page, root: Path, timings: dict[str, Any]) -> None:
    draft = SOLUTION["loop.cpp"].replace("// loop.cpp", "// loop.cpp (a draft, not run yet)")
    set_doc(page, "loop", draft)
    wait_saved(root, "loop.cpp", draft)
    saves = []
    for i in range(5):  # a few more edits for a save-latency sample
        text = draft + f"// edit {i}\n"
        set_doc(page, "loop", text)
        wait_saved(root, "loop.cpp", text)
        page.wait_for_timeout(50)
        saves.append(page.evaluate("document.querySelector('ws-cell[name=loop]').lastSaveMs"))
    set_doc(page, "loop", draft)
    wait_saved(root, "loop.cpp", draft)
    timings["save_ms"] = [round(s, 1) for s in saves]
    page.evaluate("Object.keys(localStorage).filter((k) => k.startsWith('blogs.ws.')).forEach((k) => localStorage.removeItem(k))")
    page.reload()
    page.wait_for_function("document.querySelectorAll('ws-cell[data-loaded]').length === 3", timeout=60_000)
    assert doc(page, "loop") == draft, "after reload the loop editor doesn't show the workspace's draft"
    assert page.get_attribute("ws-cell[name=loop]", "data-loaded") == "workspace"
    expect(page.locator("ws-cell[name=ring] .cell-status")).to_have_text("passed")
    shot(page, "3-reloaded")
    say(f"3 reload: loop draft read back from the workspace (browser copies dropped first); saves {statistics.median(saves):.0f} ms median")


def step_scratch_and_kill(page: Page, root: Path, timings: dict[str, Any]) -> None:
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
    spinning = subprocess.run(["pgrep", "-f", "build/debug/check_trace"], capture_output=True, text=True).stdout.split()
    assert spinning, "the hanging check_trace isn't running"
    shot(page, "4-scratch-during-check")
    cell.scroll_into_view_if_needed()
    expect(cell.locator(".run")).to_have_text("Stop")
    t1 = time.perf_counter()
    cell.locator(".run").click()
    page.wait_for_function("(() => { const c = document.querySelector('ws-cell[name=loop]'); return !c.hasAttribute('data-job') && !c.querySelector('.cell-status').textContent.startsWith('checking'); })()", timeout=10_000)
    kill_s = time.perf_counter() - t1
    status = cell.locator(".cell-status").inner_text()
    assert status.startswith("stopped"), status
    time.sleep(0.3)
    assert not alive({int(p) for p in spinning}), f"check_trace survived Stop: {spinning}"
    assert "pass/ch00/loop" not in refs(root)
    timings["scratch_during_check_s"] = round(scratch_s, 3)
    timings["stop_to_verdict_s"] = round(kill_s, 3)
    shot(page, "4-stopped")
    say(f"4 scratch cell ran in {scratch_s:.2f}s while the loop check spun; Stop -> '{status}' in {kill_s:.2f}s; check_trace gone; nothing committed")


def step_restart(page: Page, old: Gateway, new_root: Path, persist: Path, port: int, timings: dict[str, Any]) -> Gateway:
    budget_draft = SOLUTION["budget.py"]
    set_doc(page, "budget", budget_draft)
    wait_saved(old.root, "budget.py", budget_draft)
    before = refs(old.root)
    old.stop()
    gateway = Gateway(port, new_root, persist)
    page.reload()
    page.wait_for_selector("connect-pill[data-phase=disconnected]", timeout=30_000)
    t0 = time.perf_counter()
    connect(page)
    timings["reconnect_to_loaded_s"] = round(time.perf_counter() - t0, 3)
    boot = page.evaluate("document.documentElement.dataset.workspaceBoot")
    assert boot.startswith("restored "), boot
    timings["restore_ms"] = int(boot.split()[1].removesuffix("ms"))
    after = refs(new_root)
    assert after == before, f"refs differ after restore:\n{before}\n---\n{after}"
    assert doc(page, "ring") == SOLUTION["ring.cpp"]
    assert doc(page, "loop") == SOLUTION["loop.cpp"]
    assert doc(page, "budget") == budget_draft and page.get_attribute("ws-cell[name=budget]", "data-loaded") == "browser"
    wait_saved(new_root, "budget.py", budget_draft)
    for cell in ("ring", "loop"):
        expect(page.locator(f"ws-cell[name={cell}] .cell-status")).to_have_text("passed")
    shot(page, "6-restored")
    say(f"6 new sandbox (fresh root): workspace {boot}; refs identical ({len(after.splitlines())}); ring + loop passing versions; "
        f"budget draft from this browser, written to the new workspace")  # fmt: skip
    return gateway


def drive(page: Page, gateway: Gateway, args: argparse.Namespace, persist: Path, timings: dict[str, Any]) -> Gateway:
    root = gateway.root
    t0 = time.perf_counter()
    connect(page)
    timings["first_connect_to_loaded_s"] = round(time.perf_counter() - t0, 3)
    doctor_workspace(page, root)
    shot(page, "0-connected")
    step_compile_error(page, root, timings)
    step_pass(page, root, persist, timings, "ring", "ring.cpp")
    expect(page.locator("ws-cell[name=loop] .run")).to_be_enabled()
    expect(page.locator("ws-cell[name=budget] .cell-status")).to_have_text("locked until loop passes")
    say("2 loop unlocked; budget now waits for loop")
    step_reload_from_workspace(page, root, timings)
    step_scratch_and_kill(page, root, timings)
    gateway.remember()
    step_pass(page, root, persist, timings, "loop", "loop.cpp")
    gateway = step_restart(page, gateway, OUT / "root2", persist, args.gateway_port, timings)
    step_pass(page, gateway.root, persist, timings, "budget", "budget.py")
    (OUT / "git-log.txt").write_text(git(gateway.root, "log", "--oneline", "--decorate", "--all"))
    say("7 budget (Python) passed in the restored workspace")
    return gateway


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gateway-port", type=int, default=8793)
    ap.add_argument("--page-port", type=int, default=8013)
    ap.add_argument("--slow-mo", type=int, default=0, help="ms between browser actions (a watchable run: 250)")
    args = ap.parse_args()

    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True)
    persist = OUT / "persist"
    print("launch", flush=True)
    subprocess.run(["uv", "run", "build_page.py", str(CHAPTER.relative_to(HERE))], cwd=HERE, check=True, stdout=subprocess.DEVNULL)
    print("doctor", flush=True)
    doctor_toolchain()
    timings: dict[str, Any] = {}
    gateway = Gateway(args.gateway_port, OUT / "root1", persist)
    url = f"http://localhost:{args.page_port}/{PAGE}/?gateway=http://localhost:{args.gateway_port}"
    errors: list[str] = []
    try:
        with static_server(args.page_port), sync_playwright() as p:
            browser = p.chromium.launch(executable_path=CHROME, slow_mo=args.slow_mo)
            page = browser.new_page(viewport={"width": 1100, "height": 900})
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(url)
            expect(page.locator("ws-cell[name=ring] .cell-status")).to_have_text("connect to load your workspace")
            print("drive", flush=True)
            try:
                gateway = drive(page, gateway, args, persist, timings)
            except Exception:
                shot(page, "failed")
                cells = page.evaluate("[...document.querySelectorAll('ws-cell')].map((c) => `${c.getAttribute('name')}: ${c.querySelector('.cell-status').textContent} | ${c.querySelector('.cell-out').textContent.slice(-600)}`)")
                print("FAILED; the cells said:\n  " + "\n  ".join(cells) + f"\npage errors: {errors}", flush=True)
                raise
            browser.close()
    finally:
        print("cleanup", flush=True)
        gateway.stop()
    assert not errors, f"page errors: {errors}"
    print("evidence", flush=True)
    (OUT / "timings.json").write_text(json.dumps(timings, indent=1))
    (OUT / "story.log").write_text("\n".join(LOG) + "\n")
    say(f"timings: {json.dumps(timings)}")
    print(f"ok: {OUT}/ ({', '.join(sorted(p.name for p in OUT.iterdir()))})")


if __name__ == "__main__":
    main()
