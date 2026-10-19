"""Workspace cells end to end: engine/ch00-toy.md and engine/ch01-forward.md in headless Chromium, through the
Connect path (connect_dev.py). Ports are free ones picked at start (never the author's 8790 / 8012).

    uv run --with playwright verify_workspace.py [--page ch00|ch01|all]   # sandbox = a local Jupyter (connect_dev --root)
    uv run --with playwright --with modal verify_workspace.py --modal --page ch00   # ch00 on a Modal CPU sandbox

Checks run the real check core (blogs/assay, shipped as _blogs/assay/). Locally connect_dev.py runs under assay's uv
env (`uv run --project assay python connect_dev.py`), so the kernel, workspace.py and run_checks have torch etc.

Evidence goes to .evidence/verify_workspace/<page>/ (or verify_workspace-modal/; gitignored, kept until the next run):
numbered screenshots, story.log (what each step saw), timings.json, git-log.txt (the workspace's history),
connect_dev logs; locally also the Jupyter roots and the persist dir (root1/, root2/, persist/).

Phases (the shape a verify-blogs skill can call one by one):
  launch   build the page; serve dist/; start sandbox 1 (local root1, or a Modal sandbox with Jupyter on the relay's
           flags and the persist dir on a Volume) and connect_dev.py in front of it
  doctor   g++ / make / git in the sandbox; the page ships _blogs/ (workspace.py, assay/, MANIFEST.sha256) +
           ref.bundle; after Connect the workspace is seeded (tag ref/<chapter>/start) and every cell can run
  drive    the ch00 story (C++ + Python, whole-file cells, the legacy plain-text check output):
             1  ring.cpp with a missing ';' -> Run -> the compiler error streams in; its ring.cpp:L:C link moves the
                ring editor's cursor to line L; nothing committed
             2  fixed -> Run -> pass: commit + tag pass/ch00/ring on the checked text, the bundle saved
             3  a loop.cpp draft saves to the workspace (the save latency); drop the browser's draft copies; reload:
                the editor shows the draft, read back from the workspace
             4  loop.cpp that never returns -> Run; while it runs, a scratch cell runs on the same kernel; Stop kills
                the check (and its check_trace) without committing
             5  loop passes; a budget.py draft (the Python cell) is typed but not run
             6  sandbox 1 and connect_dev stop; sandbox 2 starts fresh with the same persist dir. Reconnect: the
                workspace is restored from the bundle (refs identical to sandbox 1's); ring/loop show their passing
                versions; the budget draft comes back from the browser's copy and is written to the new workspace
             7  budget passes in the restored workspace
           the ch01 story (one gpt2.py, seven region cells over one shared doc, the real check core on real GPT-2):
             0  stop any running assay warm process, so the first check pays its start (the "cold" timing)
             1  before Connect: edit the linear region in its cell; the gelu cell's view of gpt2.py shows the same
                edit at once; Run linear while disconnected -> "waiting for sandbox"; Connect (slow boot) -> the
                queued run starts once the workspace is up and passes on the edit made before Connect: tag
                pass/ch01/linear on exactly that text, the bundle saved
             2  edit gelu in the gelu cell; undo (Mod-z) from the attention cell undoes it everywhere (one history
                per file), redo restores it; exact erf GELU typed in -> Run gelu -> FAIL rows reading
                "allclose: |out - fp64 truth| up to Xx the tolerance" (err/tol > 1 at fp32; fp16/bf16 miss it by
                design), nothing committed; tanh restored -> PASS, every row err/tol < 1 (fp32 + bf16 cases +
                coverage; fp16 a visible SKIP on CPU, rows on a GPU)
             3  a syntax error planted in the forward region; Run layer_norm -> BLOCKED with gpt2.py:L (forward); the
                link puts the cursor on line L in the forward cell (the one whose region holds it); nothing committed
             4  syntax fixed; Run forward with attention still a stub -> FAIL "NotImplementedError: self_attention:
                ..." whose link names the stub's raise line (attention region)
             5  the block region's start marker deleted: the block cell says so (nothing to highlight); Run block still
                checks (a verdict, no crash); marker restored
             6  attention without its / sqrt(H) -> FAIL with numbers; fixed -> PASS; Run block and forward -> PASS
                on real GPT-2 (forward: per-position KL max < 1e-7) + bf16 a visible SKIP (no bf16 model checks on
                CPU, the capability table)
             7  the check store made unreadable -> Run -> "not run (infrastructure)", HEAD unchanged
             8  a trusted file in _blogs/ tampered -> Run refused (HEAD unchanged); MANIFEST.sha256 itself rewritten
                to match -> refused (the page's sha256 differs); reload re-uploads _blogs/ -> Run passes again
             9  reload: the shared doc comes back from the workspace with every edit; passed cells say so
            10  timings: layer_norm and forward with the warm process stopped (cold) then running (warm), store warm
            11  sandbox 1 stops; this browser's draft is replaced by one built on a commit the restored sandbox never
                had (another device's); sandbox 2 restores from the bundle -> every gpt2.py cell shows the conflict
                banner and the sandbox's text; "Use this browser's draft" puts it in (saved to the workspace); Run
                generate passes (24 greedy tokens = HF's)
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
import socket
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
BROKEN_STATEMENT = "    r->tail += 1;\n"
TOL_FAIL = "allclose: |out - fp64 truth| up to "
HANG = "void sched_step(const Request* reqs, Ring* waiting, u32 budget, Batch* out) {\n"
SCRATCH = "print('scratch ran while the check was running:', 6 * 7)"
CHECK_TIMEOUT_MS = 180_000
SAVE_WAIT_S = 15
CELLS = 3


class Box(Protocol):
    name: str
    persist: str

    def gateway_args(self) -> list[str]: ...
    def sh(self, cmd: str) -> str: ...
    def close(self) -> None: ...


class LocalBox:
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
        pass


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

    def shot(self, name: str, cell: str | None = None) -> None:
        if cell is None:
            self.page.screenshot(path=self.out / f"{name}.png")
        else:
            self.page.locator(f"ws-cell[name={cell}]").screenshot(path=self.out / f"{name}.png")


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
    page.evaluate("([n, s]) => { const v = document.querySelector(`ws-cell[name=${n}]`).view; v.dispatch({changes: {from: 0, to: v.state.doc.length, insert: s}}); }", [cell, text])


def doc(page: Page, cell: str) -> str:
    return page.evaluate("(n) => document.querySelector(`ws-cell[name=${n}]`).view.state.doc.toString()", cell)


DONE = "(n) => { const c = document.querySelector(`ws-cell[name=${n}]`); return !c.hasAttribute('data-job') && c.querySelector('.cell-out:is(.pass, .fail)') && !c.querySelector('.cell-status').textContent.startsWith('checking'); }"


def run_cell(page: Page, cell: str) -> tuple[str, str, float]:
    el = page.locator(f"ws-cell[name={cell}]")
    el.scroll_into_view_if_needed()
    t0 = time.perf_counter()
    el.locator(".run").click()
    page.wait_for_function(DONE, arg=cell, timeout=CHECK_TIMEOUT_MS)
    took = time.perf_counter() - t0
    return el.locator(".cell-status").inner_text(), el.locator(".cell-out").inner_text(), took


def bundle_note(output: str) -> tuple[float, int]:
    m = re.search(r"bundle ([\d.]+) KiB saved in (\d+) ms", output)
    assert m, f"no bundle line in the output:\n{output}"
    return float(m[1]), int(m[2])


def connect(page: Page, cells: int = CELLS) -> None:
    if page.locator(".connect-panel").is_hidden():
        page.locator(".connect-pill").click()
    if page.locator("input[name=token-id]").is_visible():
        page.fill("input[name=token-id]", TOKEN[0])
        page.fill("input[name=token-secret]", TOKEN[1])
    page.locator(".connect-go").click()
    page.wait_for_selector("connect-pill[data-phase=connected]", timeout=120_000)
    page.wait_for_function(f"document.querySelectorAll('ws-cell[data-loaded]').length === {cells}", timeout=120_000)


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
    def __init__(self, port: int, box: Box, out: Path, boot_delay: float = 0.1) -> None:
        self.box = box
        self.log = (out / f"connect_dev-{box.name}.log").open("wb")
        self.proc = subprocess.Popen(["uv", "run", "--project", "assay", "python", "connect_dev.py", "--port", str(port), "--boot-delay", str(boot_delay), *box.gateway_args()],
                                     cwd=HERE, stdout=self.log, stderr=self.log)  # fmt: skip
        self.seen: set[int] = set()
        for _ in range(240):
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
        self.proc.send_signal(signal.SIGTERM)
        self.proc.wait(30)
        deadline = time.monotonic() + 15
        while alive(self.seen) and time.monotonic() < deadline:
            time.sleep(0.2)
        left = alive(self.seen)
        assert not left, f"processes connect_dev ({self.box.name}) started are still running: {left}"
        self.box.close()
        return f"cleanup: connect_dev ({self.box.name}) stopped; all {len(self.seen)} processes it started are gone"


def doctor_page(name: str) -> str:
    dist = HERE / "dist" / name
    for f in ("index.html", "page.js", "_blogs/workspace.py", "_blogs/assay/cli.py", "_blogs/MANIFEST.sha256", "ref.bundle"):
        assert (dist / f).is_file(), f"the built page lacks {f}"
    listed = sorted(line.split("  ")[1] for line in (dist / "_blogs/MANIFEST.sha256").read_text().splitlines())
    assert all(f == "workspace.py" or (f.startswith("assay/") and f.endswith(".py")) for f in listed), listed
    return f"doctor: {name} ships _blogs/ (workspace.py + {len(listed) - 1} assay/*.py, all in MANIFEST.sha256) + ref.bundle"


def doctor_box(box: Box) -> str:
    versions = box.sh("g++ --version | head -1; make --version | head -1; git --version")
    return f"doctor: {box.name} has the toolchain: {' | '.join(versions.strip().splitlines())}"


def doctor_workspace(run: Run, box: Box) -> None:
    assert "refs/tags/ref/ch00/start" in refs(box), refs(box)
    for cell in ("ring", "loop", "budget"):
        expect(run.page.locator(f"ws-cell[name={cell}] .run")).to_be_enabled()
        expect(run.page.locator(f"ws-cell[name={cell}] .cell-status")).to_have_text("not passed yet")
    run.say(f"doctor: workspace {run.page.evaluate('document.documentElement.dataset.workspaceBoot')}; tag ref/ch00/start; every cell runnable (no gating)")


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
    for i in range(5):
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
    spinning = box.sh("pgrep -f 'assay-ch00-build-[0-9a-f]*/check_trac[e] ' || true").split()
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
    left = box.sh("pgrep -f 'assay-ch00-build-[0-9a-f]*/check_trac[e] ' || true").split()
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
    import ws_modal

    volume = stack.enter_context(ws_modal.modal.Volume.ephemeral())
    return lambda name: ws_modal.ModalBox(name, volume, origin)


CH1 = "ch01"
PAGE1 = "ch01-forward"
CHAPTER1 = HERE / "engine" / "ch01-forward.md"
SOL1 = ref.materialize(CH1, "solution")["gpt2.py"].data.decode()
CELLS1 = 7
SLOW_BOOT_S = 1.5


def region_text(text: str, name: str) -> str:
    m = re.search(rf"# region: {name}\n.*?# endregion", text, re.DOTALL)
    assert m, f"no region {name} in the text"
    return m[0]


def replace_in_view(page: Page, cell: str, old: str, new: str) -> None:
    page.evaluate("""([n, a, b]) => { const v = document.querySelector(`ws-cell[name=${n}]`).view; const i = v.state.doc.toString().indexOf(a);
                     if (i < 0) throw new Error(`not in ${n}'s view: ${a.slice(0, 60)}`);
                     v.dispatch({changes: {from: i, to: i + a.length, insert: b}, userEvent: "input.type"}); }""", [cell, old, new])  # fmt: skip


def put_region(page: Page, cell: str, name: str, text: str) -> None:
    replace_in_view(page, cell, region_text(doc(page, cell), name), region_text(text, name))


def line_of(text: str, needle: str) -> int:
    return next(i for i, line in enumerate(text.split("\n"), start=1) if needle in line)


def scrolled_to_region(page: Page, cell: str) -> None:
    page.wait_for_function("""(n) => { const v = document.querySelector(`ws-cell[name=${n}]`).view; const d = v.state.doc;
        let start = 0; for (let i = 1; i <= d.lines; i++) if (d.line(i).text.trim() === `# region: ${n}`) { start = i; break; }
        const s = v.scrollDOM, top = d.lineAt(v.lineBlockAtHeight(s.scrollTop + 1).from).number;
        const atEnd = s.scrollTop + s.clientHeight >= s.scrollHeight - 2;
        const bottom = d.lineAt(v.lineBlockAtHeight(s.scrollTop + s.clientHeight - 2).from).number;
        return start > 0 && ((top >= start - 1 && top <= start) || (atEnd && top <= start && start <= bottom)); }""",
                          arg=cell, timeout=5_000)  # fmt: skip


def head(box: Box) -> str:
    return git(box, "rev-parse", "HEAD").strip()


def check_log(page: Page, cell: str) -> str:
    return page.locator(f"ws-cell[name={cell}] .check-log").inner_text()


def record(run: Run, label: str, cell: str, took: float | None) -> None:
    log = check_log(run.page, cell)
    done = re.findall(r"done in ([\d.]+)s", log)
    run.timings.setdefault("checks", []).append({
        "check": label, "click_to_verdict_s": None if took is None else round(took, 2),
        "worker_s": float(done[-1]) if done else None,
        "warm_process": "cold (started it)" if "starting the warm check process" in log else "warm (forked)"})


def rows(page: Page, cell: str) -> list[dict[str, str]]:
    return page.evaluate("""(n) => [...document.querySelectorAll(`ws-cell[name=${n}] tr.verdict`)].map((tr) => {
        const td = tr.querySelectorAll('td'); return {outcome: tr.dataset.outcome, case: td[0].textContent,
        dtype: td[1].textContent, metric: td[4].textContent, notes: td[5].textContent}; })""", cell)  # fmt: skip


def metric_value(row: dict[str, str], label: str) -> float:
    assert row["metric"].startswith(label + " "), row
    return float(row["metric"].removeprefix(label + " "))


def stop_warm(box: Box) -> str:
    return box.sh(f"PYTHONPATH=_blogs {shlex.quote(ref.assay_python())} -B -c 'from assay.core import stop_warm; print(stop_warm())'").strip()


def ch01_before_connect(run: Run, gateway: Gateway) -> None:
    page, box = run.page, gateway.box
    expect(page.locator("ws-cell[name=linear] .cell-status")).to_have_text("not connected: edits are kept in this browser")
    put_region(page, "linear", "linear", SOL1)
    want = region_text(SOL1, "linear")
    assert want in doc(page, "gelu"), "the gelu cell's view of gpt2.py doesn't show the edit made in the linear cell"
    stored = page.evaluate("JSON.parse(localStorage.getItem('blogs.ws.v1.ch01.gpt2.py')).text")
    assert want in stored, "the edit isn't in the browser's draft"
    run.shot("1-edited-before-connect")
    page.locator("ws-cell[name=linear] .run").click()
    expect(page.locator("ws-cell[name=linear] .cell-status")).to_have_text("waiting for sandbox: connect to run")
    expect(page.locator(".connect-panel")).to_be_visible()
    t0 = time.perf_counter()
    page.fill("input[name=token-id]", TOKEN[0])
    page.fill("input[name=token-secret]", TOKEN[1])
    page.locator(".connect-go").click()
    page.wait_for_function("document.querySelector('ws-cell[name=linear] .cell-status').textContent.startsWith('waiting for sandbox (')", timeout=30_000)
    waiting = page.locator("ws-cell[name=linear] .cell-status").inner_text()
    put_region(page, "layer_norm", "layer_norm", SOL1)
    run.shot("1-connecting-queued")
    page.wait_for_function(DONE, arg="linear", timeout=CHECK_TIMEOUT_MS)
    page.wait_for_function(f"document.querySelectorAll('ws-cell[data-loaded]').length === {CELLS1}", timeout=120_000)
    took = time.perf_counter() - t0
    status = page.locator("ws-cell[name=linear] .cell-status").inner_text()
    assert status.startswith("passed"), f"{status}\n{page.locator('ws-cell[name=linear] .cell-out').inner_text()}"
    assert "refs/tags/pass/ch01/linear" in refs(box)
    assert region_text(git(box, "show", "pass/ch01/linear:gpt2.py"), "linear") == want, "the tagged commit lacks the pre-Connect edit"
    box.sh(f"test -s {box.persist}/workspace.bundle")
    run.timings["connect_click_to_queued_pass_s"] = round(took, 3)
    record(run, "linear (queued at Connect; cold process, cold store)", "linear", None)
    scrolled_to_region(page, "generate")
    run.shot("1-queued-run-passed")
    assert region_text(box.sh("cat workspace/gpt2.py"), "layer_norm") == region_text(SOL1, "layer_norm"), "the edit made while connecting was lost"
    run.say(f"1 linear edited before Connect (mirrored into the gelu cell, kept in localStorage); Run queued while disconnected; "
            f"while connecting the cell said '{waiting}' and layer_norm was edited; "
            f"Connect -> workspace {page.evaluate('document.documentElement.dataset.workspaceBoot')} -> the queued run passed "
            f"{took:.2f}s after clicking Connect (worker {run.timings['checks'][-1]['worker_s']}s, "
            f"{run.timings['checks'][-1]['warm_process']}); tag pass/ch01/linear holds the pre-Connect edit; bundle saved")  # fmt: skip


GELU_TANH = "(1 + torch.tanh(inner_TF))"
GELU_ERF = "(1 + torch.erf(x_TF / math.sqrt(2)))"


def ch01_gelu(run: Run, box: Box) -> None:
    page = run.page
    stub = region_text(doc(page, "gelu"), "gelu")
    put_region(page, "gelu", "gelu", SOL1)
    assert region_text(doc(page, "attention"), "gelu") == region_text(SOL1, "gelu"), "the attention view doesn't mirror gelu's edit"
    page.locator("ws-cell[name=attention] .cm-content").click()
    page.keyboard.press("ControlOrMeta+z")
    for cell in ("gelu", "attention", "generate"):
        assert region_text(doc(page, cell), "gelu") == stub, f"undo from the attention cell didn't undo gelu's edit in {cell}"
    page.keyboard.press("ControlOrMeta+Shift+z")
    for cell in ("gelu", "attention"):
        assert region_text(doc(page, cell), "gelu") == region_text(SOL1, "gelu"), f"redo didn't restore the gelu edit in {cell}"
    replace_in_view(page, "gelu", GELU_TANH, GELU_ERF)
    before = head(box)
    status, _, took = run_cell(page, "gelu")
    record(run, "gelu, exact-GELU bug (warm process, cold store)", "gelu", took)
    assert status.startswith("failed"), status
    bad = [r for r in rows(page, "gelu") if r["outcome"] == "fail"]
    assert bad and bad[0]["notes"].startswith(TOL_FAIL), bad[:1]
    assert {r["dtype"] for r in bad} == {"fp32"}, "exact GELU is under fp16/bf16's tolerance: only fp32 rows catch it"
    worst = max(metric_value(r, "err/tol") for r in bad)
    assert worst > 1 and "(gelu)" in bad[0]["notes"], bad[0]
    assert head(box) == before and "pass/ch01/gelu" not in refs(box), "a failing check committed"
    run.shot("2-gelu-planted-bug", "gelu")
    run.say(f"2 gelu edited in its cell, mirrored into attention's view; Mod-z in the attention cell undid it everywhere, Mod-Shift-z "
            f"redid it; then exact erf GELU typed in -> Run -> '{status}' in {took:.2f}s: {len(bad)} failing rows, e.g. "
            f"'{bad[0]['case']} {bad[0]['dtype']}: {bad[0]['notes']}' ({bad[0]['metric']}; worst {worst:.3g}x its tolerance); nothing committed")  # fmt: skip
    replace_in_view(page, "gelu", GELU_ERF, GELU_TANH)
    status, _, took = run_cell(page, "gelu")
    record(run, "gelu, fixed (warm process, cold store)", "gelu", took)
    assert status.startswith("passed"), status
    got = [r for r in rows(page, "gelu") if r["outcome"] != "skip"]
    assert got and all(r["outcome"] == "pass" for r in got), got
    ratios = [metric_value(r, "err/tol") for r in got if r["metric"].startswith("err/tol")]
    assert ratios and max(ratios) < 1, ratios
    assert any(r["case"].endswith("coverage") for r in got), "no coverage row"
    assert page.locator("ws-cell[name=gelu] .check-summary").inner_text().startswith("PASS")
    run.shot("2-gelu-pass", "gelu")
    run.say(f"2 tanh GELU restored -> Run -> '{status}' in {took:.2f}s: {len(got)} rows PASS ({len(ratios)} cases, "
            f"{'+'.join(sorted({r['dtype'] for r in got} - {'*'}))}, err at most {max(ratios):.3g}x its tolerance; + coverage)")  # fmt: skip


def ch01_blocked(run: Run, box: Box) -> None:
    page = run.page
    put_region(page, "layer_norm", "layer_norm", SOL1)
    stub_line = 'raise NotImplementedError("forward: write this in the forward cell")'
    replace_in_view(page, "forward", stub_line, "oops = (  # a syntax error, planted\n    " + stub_line)
    bad = line_of(doc(page, "forward"), "oops = (")
    before = head(box)
    status, out, took = run_cell(page, "layer_norm")
    record(run, "layer_norm, syntax error elsewhere (blocked)", "layer_norm", took)
    assert status.startswith("blocked"), f"{status}\n{out}"
    row = page.locator("ws-cell[name=layer_norm] tr.verdict.blocked")
    expect(row).to_have_count(1)
    link = row.locator("a.where")
    assert link.get_attribute("data-loc") == f"gpt2.py:{bad}:1", link.get_attribute("data-loc")
    assert "(forward)" in link.inner_text(), link.inner_text()
    notes = next(r["notes"] for r in rows(page, "layer_norm") if r["outcome"] == "blocked")
    link.click()
    cursor = page.evaluate("() => { const v = document.querySelector('ws-cell[name=forward]').view; return {line: v.state.doc.lineAt(v.state.selection.main.head).number, focused: v.hasFocus}; }")
    assert cursor == {"line": bad, "focused": True}, cursor
    assert head(box) == before and "pass/ch01/layer_norm" not in refs(box), "a blocked check committed"
    run.shot("3-blocked-jump")
    run.say(f"3 syntax error planted in forward (line {bad}); Run layer_norm -> '{status}': '{notes}'; the link put the forward cell's "
            f"cursor on line {bad} (focused); nothing committed")  # fmt: skip
    replace_in_view(page, "forward", "oops = (  # a syntax error, planted\n    ", "")


def ch01_fail_at_stub(run: Run, box: Box) -> None:
    page = run.page
    put_region(page, "forward", "forward", SOL1)
    put_region(page, "block", "block", SOL1)
    status, out, took = run_cell(page, "forward")
    record(run, "forward, attention still a stub (raises; first forward: computes HF's fp64 truth)", "forward", took)
    assert status.startswith("failed"), f"{status}\n{out}"
    text = doc(page, "attention")
    stub_raise_line = line_of(text, '"self_attention: write this in the attention cell"') - 1
    assert text.split("\n")[stub_raise_line - 1].strip() == "raise NotImplementedError(", text.split("\n")[stub_raise_line - 1]
    fail = page.locator("ws-cell[name=forward] tr.verdict.fail").first
    loc = fail.locator("a.where").get_attribute("data-loc")
    assert loc == f"gpt2.py:{stub_raise_line}:1", (loc, stub_raise_line)
    assert "(attention)" in fail.locator("a.where").inner_text()
    notes = rows(page, "forward")
    first = next(r for r in notes if r["outcome"] == "fail")["notes"]
    assert "NotImplementedError: self_attention: write this in the attention cell" in first, first
    run.say(f"4 Run forward with attention still a stub -> '{status}': '{first}' (any order: forward runs block runs the "
            f"stub; the link names the raise, line {stub_raise_line}, in the attention region)")  # fmt: skip


def ch01_missing_marker(run: Run, box: Box) -> None:
    page = run.page
    replace_in_view(page, "block", "# region: block\n", "")
    note = page.locator("ws-cell[name=block] .cell-note")
    expect(note).to_be_visible()
    expect(note).to_contain_text('no "# region: block"')
    status, out, took = run_cell(page, "block")
    record(run, "block, attention still a stub (raises; first block: computes HF's fp64 truth)", "block", took)
    assert status.startswith("failed") and page.locator("ws-cell[name=block] tr.verdict.fail").count() >= 1, f"{status}\n{out}"
    run.shot("5-missing-marker")
    replace_in_view(page, "block", "def mlp(", "# region: block\ndef mlp(")
    expect(note).to_be_hidden()
    run.say(f"5 block's start marker deleted: the cell says so (no highlight, view stays where it was); Run block "
            f"still checked ('{status}'); marker restored, note gone")  # fmt: skip


NO_SCALE = "    scores_NTS = scores_NTS / math.sqrt(H)\n"


def ch01_attention_and_model(run: Run, box: Box) -> None:
    page = run.page
    put_region(page, "attention", "attention", SOL1.replace(NO_SCALE, ""))
    status, _, took = run_cell(page, "attention")
    record(run, "attention, scale missing (warm process, cold store)", "attention", took)
    assert status.startswith("failed"), status
    bad = [r for r in rows(page, "attention") if r["outcome"] == "fail"]
    assert bad and bad[0]["notes"].startswith(TOL_FAIL), bad[:1]
    assert "pass/ch01/attention" not in refs(box)
    run.shot("6-attention-no-scale", "attention")
    run.say(f"6 attention without / sqrt(H) -> '{status}' in {took:.2f}s: {len(bad)} failing rows, e.g. "
            f"'{bad[0]['case']} {bad[0]['dtype']}: {bad[0]['notes']}' ({bad[0]['metric']})")  # fmt: skip
    put_region(page, "attention", "attention", SOL1)
    status, _, took = run_cell(page, "attention")
    record(run, "attention, fixed (warm process, cold store)", "attention", took)
    assert status.startswith("passed"), status
    run.say(f"6 attention fixed -> '{status}' in {took:.2f}s ({len(rows(page, 'attention'))} rows)")
    for cell, label in (("block", "err/tol"), ("forward", "KL max")):
        status, _, took = run_cell(page, cell)
        record(run, f"{cell}, correct (warm process; HF's truth cached by the stub run above)", cell, took)
        assert status.startswith("passed"), f"{status}\n{page.locator(f'ws-cell[name={cell}] .cell-out').inner_text()[-2000:]}"
        got = rows(page, cell)
        passing = [r for r in got if r["outcome"] == "pass"]
        skip = [r for r in got if r["outcome"] == "skip"]
        assert passing and len(skip) == 1 and skip[0]["dtype"] == "bf16", got
        assert "checked on a bf16 GPU" in skip[0]["notes"], skip[0]
        values = [metric_value(r, label) for r in passing]
        if cell == "forward":
            assert max(values) < 1e-7, values
        skip_row = page.locator(f"ws-cell[name={cell}] tr.verdict.skip")
        assert skip_row.evaluate("(r) => getComputedStyle(r).fontStyle") == "italic", "SKIP isn't styled apart"
        run.shot(f"6-{cell}-pass-skip", cell)
        run.say(f"6 Run {cell} -> '{status}' in {took:.2f}s: {len(passing)} fp32 rows PASS ({label} at most {max(values):.3g}); "
                f"bf16 a visible SKIP (italic): '{skip[0]['notes']}'")  # fmt: skip


def ch01_infra(run: Run, box: Box) -> None:
    page = run.page
    store = f"{box.persist}/cache/assay"
    mode = box.sh(f"stat -f %Lp {shlex.quote(store)} 2>/dev/null || stat -c %a {shlex.quote(store)}").strip()
    box.sh(f"chmod 000 {shlex.quote(store)}")
    before = head(box)
    try:
        status, out, _ = run_cell(page, "linear")
    finally:
        box.sh(f"chmod {mode} {shlex.quote(store)}")
    assert status.startswith("not run (infrastructure)"), f"{status}\n{out}"
    assert head(box) == before
    run.say(f"7 check store unreadable (chmod 000 {store}) -> Run linear -> '{status[:120]}'; HEAD unchanged; store restored")


def ch01_tamper(run: Run, box: Box) -> None:
    page = run.page
    before = head(box)
    box.sh("echo '# tampered' >> _blogs/assay/cli.py")
    status, _, _ = run_cell(page, "linear")
    assert status.startswith("not run (infrastructure): the trusted code in _blogs/ differs from MANIFEST.sha256: assay/cli.py changed"), status
    run.shot("8-tampered")
    box.sh("python3 - <<'PY'\nimport hashlib, pathlib\nm = pathlib.Path('_blogs/MANIFEST.sha256')\n"
           "lines = [l.split('  ') for l in m.read_text().splitlines()]\n"
           "m.write_text(''.join(f\"{hashlib.sha256(pathlib.Path('_blogs', p).read_bytes()).hexdigest()}  {p}\\n\" for _, p in lines))\nPY")  # fmt: skip
    status2, _, _ = run_cell(page, "linear")
    assert status2.startswith("not run (infrastructure): _blogs/MANIFEST.sha256 is not the page's"), status2
    assert head(box) == before
    page.reload()
    page.wait_for_function(f"document.querySelectorAll('ws-cell[data-loaded]').length === {CELLS1}", timeout=120_000)
    status3, _, _ = run_cell(page, "linear")
    assert status3.startswith("passed"), status3
    run.say(f"8 tampered assay/cli.py -> '{status[:90]}…'; manifest rewritten to match -> '{status2[:80]}…'; "
            f"HEAD unchanged; reload re-uploaded _blogs/ -> Run linear '{status3}'")  # fmt: skip


def ch01_reload(run: Run, box: Box) -> None:
    page = run.page
    text = doc(page, "linear")
    wait_saved(box, "gpt2.py", text)
    page.reload()
    page.wait_for_function(f"document.querySelectorAll('ws-cell[data-loaded]').length === {CELLS1}", timeout=120_000)
    for cell in ("linear", "generate"):
        assert doc(page, cell) == text, f"{cell} after reload differs from the workspace's draft"
    for cell in ("linear", "gelu", "attention", "block", "forward"):
        expect(page.locator(f"ws-cell[name={cell}] .cell-status")).to_contain_text("passed")
    run.shot("9-reloaded")
    statuses = {c: page.locator(f"ws-cell[name={c}] .cell-status").inner_text() for c in ("linear", "gelu", "layer_norm", "forward")}
    run.say(f"9 reload: every view shows the workspace's gpt2.py with all edits; {statuses}")


def ch01_timings(run: Run, box: Box) -> None:
    page = run.page
    for cell in ("layer_norm", "forward"):
        run.say(f"10 stop the warm process: {stop_warm(box)}")
        for label in ("cold process, warm store", "warm process, warm store"):
            status, _, took = run_cell(page, cell)
            assert status.startswith("passed"), status
            record(run, f"{cell} ({label})", cell, took)
            last = run.timings["checks"][-1]
            run.say(f"10 {cell} ({label}): {took:.2f}s click -> verdict, worker {last['worker_s']}s, {last['warm_process']}")


def ch01_conflict(run: Run, old: Gateway) -> Gateway:
    page = run.page
    run.say(old.stop())
    page.evaluate("(t) => localStorage.setItem('blogs.ws.v1.ch01.gpt2.py', JSON.stringify({text: t, acked: true, base: '0000000'}))", SOL1)
    box = run.new_box("sandbox2")
    gateway = Gateway(run.gateway_port, box, run.out)
    page.reload()
    page.wait_for_selector("connect-pill[data-phase=disconnected]", timeout=30_000)
    assert doc(page, "linear") == SOL1, "before Connect the editors should show this browser's draft"
    connect(page, CELLS1)
    boot = page.evaluate("document.documentElement.dataset.workspaceBoot")
    assert boot.startswith("restored "), boot
    in_workspace = box.sh("cat workspace/gpt2.py")
    for cell in ("linear", "generate"):
        expect(page.locator(f"ws-cell[name={cell}] .cell-conflict")).to_be_visible()
    assert doc(page, "linear") == in_workspace, "with a conflict the editor should show the sandbox's passing code"
    scrolled_to_region(page, "gelu")
    run.shot("11-conflict")
    page.locator("ws-cell[name=generate] .use-browser").click()
    assert doc(page, "linear") == SOL1
    wait_saved(box, "gpt2.py", SOL1)
    expect(page.locator("ws-cell[name=linear] .cell-conflict")).to_be_hidden()
    status, _, took = run_cell(page, "generate")
    record(run, "generate, correct (new sandbox; cold store for generate)", "generate", took)
    assert status.startswith("passed"), status
    got = rows(page, "generate")
    assert [r["outcome"] for r in got] == ["pass"] and got[0]["metric"] == "tokens 24", got
    run.shot("11-resolved-generate-passed")
    run.say(f"11 new sandbox ({boot}); a draft built on another commit -> conflict banner on every gpt2.py cell, editor shows "
            f"the sandbox's passing code; 'Use this browser's draft' -> saved to the workspace; Run generate '{status}' in "
            f"{took:.2f}s ({got[0]['case']}: {got[0]['metric']}, HF's greedy tokens exactly)")  # fmt: skip
    return gateway


def drive_ch01(run: Run, gateway: Gateway) -> Gateway:
    run.say(f"0 before the story, stop any running warm process: {stop_warm(gateway.box)}")
    ch01_before_connect(run, gateway)
    assert "refs/tags/ref/ch01/start" in refs(gateway.box)
    assert "ring.cpp" not in gateway.box.sh("ls workspace"), "ch00's toy files leaked into ch01's tree"
    ch01_gelu(run, gateway.box)
    ch01_blocked(run, gateway.box)
    ch01_fail_at_stub(run, gateway.box)
    ch01_missing_marker(run, gateway.box)
    ch01_attention_and_model(run, gateway.box)
    ch01_infra(run, gateway.box)
    ch01_tamper(run, gateway.box)
    ch01_reload(run, gateway.box)
    ch01_timings(run, gateway.box)
    gateway.remember()
    gateway = ch01_conflict(run, gateway)
    (run.out / "git-log.txt").write_text(git(gateway.box, "log", "--oneline", "--decorate", "--all"))
    run.say(f"cleanup: stop the warm process the checks started: {stop_warm(gateway.box)}")
    return gateway


@dataclass(frozen=True)
class Story:
    chapter: Path
    page: str
    boot_delay: float
    pre_connect_cell: str
    drive: Callable[[Run, Gateway], Gateway]


STORIES = {"ch00": Story(CHAPTER, PAGE, 0.1, "ring", drive), "ch01": Story(CHAPTER1, PAGE1, SLOW_BOOT_S, "linear", drive_ch01)}


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def run_story(name: str, story: Story, args: argparse.Namespace, out: Path, browser: Any, origin: str) -> None:
    out.mkdir(parents=True)
    errors: list[str] = []
    gateway: Gateway | None = None
    print(f"== {name}: launch", flush=True)
    with ExitStack() as stack:
        new_box = box_factory(args.modal, out, origin, stack)
        context = browser.new_context(viewport={"width": 1100, "height": 900})
        page = context.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        run = Run(page, out, new_box, args.gateway_port)
        try:
            box = new_box("sandbox1")
            print(f"== {name}: doctor", flush=True)
            run.say(doctor_page(story.page))
            run.say(doctor_box(box))
            gateway = Gateway(args.gateway_port, box, out, story.boot_delay)
            page.goto(f"{origin}/{story.page}/?gateway=http://localhost:{args.gateway_port}")
            expect(page.locator(f"ws-cell[name={story.pre_connect_cell}] .cell-status")).to_have_text("not connected: edits are kept in this browser")
            print(f"== {name}: drive", flush=True)
            gateway = story.drive(run, gateway)
        except Exception:
            run.shot("failed")
            cells = page.evaluate("[...document.querySelectorAll('ws-cell')].map((c) => `${c.getAttribute('name')}: ${c.querySelector('.cell-status').textContent} | ${c.querySelector('.cell-out').textContent.slice(-600)}`)")
            print("FAILED; the cells said:\n  " + "\n  ".join(cells) + f"\npage errors: {errors}", flush=True)
            raise
        finally:
            print(f"== {name}: cleanup", flush=True)
            context.close()
            if gateway is not None:
                run.say(gateway.stop())
            if args.modal:
                import ws_modal

                left = ws_modal.leftovers(kill=True)
                assert left == 0, f"{left} Modal sandbox(es) were still running (now terminated)"
                run.say(f"cleanup: no sandboxes left under Modal app {ws_modal.APP}; the Volume was ephemeral")
    assert not errors, f"page errors: {errors}"
    (out / "timings.json").write_text(json.dumps(run.timings, indent=1))
    (out / "story.log").write_text("\n".join(run.log) + "\n")
    run.say(f"timings: {json.dumps(run.timings)}")
    print(f"ok {name}: {out}/ ({', '.join(sorted(p.name for p in out.iterdir()))})", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--modal", action="store_true", help="sandboxes on Modal (CPU) instead of local Jupyter roots (ch00 only)")
    ap.add_argument("--page", choices=("ch00", "ch01", "all"), default="all")
    ap.add_argument("--gateway-port", type=int, default=0, help="default: a free port")
    ap.add_argument("--page-port", type=int, default=0, help="default: a free port")
    ap.add_argument("--slow-mo", type=int, default=0, help="ms between browser actions (a watchable run: 250)")
    args = ap.parse_args()
    names = ["ch00", "ch01"] if args.page == "all" else [args.page]
    assert not (args.modal and "ch01" in names), "--modal drives ch00 only (pass --page ch00)"
    args.gateway_port = args.gateway_port or free_port()
    args.page_port = args.page_port or free_port()
    assert {args.gateway_port, args.page_port}.isdisjoint({8790, 8795, 8012, 8015, 8010, 8787, 8060}), "those ports are the author's"

    root = HERE / ".evidence" / ("verify_workspace-modal" if args.modal else "verify_workspace")
    shutil.rmtree(root, ignore_errors=True)
    origin = f"http://localhost:{args.page_port}"
    print(f"build (page :{args.page_port}, gateway :{args.gateway_port})", flush=True)
    subprocess.run(["uv", "run", "build_page.py", *(str(STORIES[n].chapter.relative_to(HERE)) for n in names)], cwd=HERE, check=True, stdout=subprocess.DEVNULL)
    with ExitStack() as stack:
        stack.enter_context(static_server(args.page_port))
        p = stack.enter_context(sync_playwright())
        browser = p.chromium.launch(executable_path=CHROME, slow_mo=args.slow_mo)
        stack.callback(browser.close)
        for name in names:
            run_story(name, STORIES[name], args, root / name, browser, origin)
    print(f"ok: {root}/")


if __name__ == "__main__":
    main()
