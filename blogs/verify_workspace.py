from __future__ import annotations

import json
import re

from playwright.sync_api import Browser, Page, expect

import ref
from replay import HERE, OUT, TOKEN, Replay, check
from verify_connect import go, replayed

SOLUTION = {path: f.data.decode() for path, f in ref.materialize("ch00", "solution").items()}
SOL1 = ref.materialize("ch01", "solution")["gpt2.py"].data.decode()
BROKEN_STATEMENT = "    r->tail += 1;\n"
HANG = "void sched_step(const Request* reqs, Ring* waiting, u32 budget, Batch* out) {\n"
SCRATCH = "print('scratch ran while the check was running:', 6 * 7)"
CELLS = 3
DONE = "(n) => { const c = document.querySelector(`ws-cell[name=${n}]`); return !c.hasAttribute('data-job') && c.querySelector('.cell-out:is(.pass, .fail)') && !c.querySelector('.cell-status').textContent.startsWith('checking'); }"
LOADED = "(n) => document.querySelectorAll('ws-cell[data-loaded]').length === n"


def set_doc(page: Page, cell: str, text: str) -> None:
    page.evaluate("([n, s]) => { const v = document.querySelector(`ws-cell[name=${n}]`).view; v.dispatch({changes: {from: 0, to: v.state.doc.length, insert: s}}); }", [cell, text])


def doc(page: Page, cell: str) -> str:
    return page.evaluate("(n) => document.querySelector(`ws-cell[name=${n}]`).view.state.doc.toString()", cell)


def replace_in_view(page: Page, cell: str, old: str, new: str) -> None:
    page.evaluate("""([n, a, b]) => { const v = document.querySelector(`ws-cell[name=${n}]`).view; const i = v.state.doc.toString().indexOf(a);
                     if (i < 0) throw new Error(`not in ${n}'s view: ${a.slice(0, 60)}`);
                     v.dispatch({changes: {from: i, to: i + a.length, insert: b}, userEvent: "input.type"}); }""", [cell, old, new])  # fmt: skip


def region(text: str, name: str) -> str:
    m = re.search(rf"# region: {name}\n.*?# endregion", text, re.DOTALL)
    assert m, f"no region {name} in the text"
    return m[0]


def run_cell(page: Page, cell: str, text: str | None = None) -> tuple[str, str]:
    if text is not None:
        set_doc(page, cell, text)
    el = page.locator(f"ws-cell[name={cell}]")
    el.scroll_into_view_if_needed()
    el.locator(".run").click()
    page.wait_for_function(DONE, arg=cell, timeout=180_000)
    return el.locator(".cell-status").inner_text(), el.locator(".cell-out").inner_text()


def queued_run(page: Page, token: tuple[str, str]) -> None:
    expect(page.locator("ws-cell[name=ring] .cell-status")).to_have_text("not connected: edits are kept in this browser")
    line = SOLUTION["ring.cpp"].split("\n").index(BROKEN_STATEMENT.rstrip("\n")) + 1
    set_doc(page, "ring", SOLUTION["ring.cpp"].replace(BROKEN_STATEMENT, BROKEN_STATEMENT.replace(";", "")))
    page.locator("ws-cell[name=ring] .run").click()
    expect(page.locator("ws-cell[name=ring] .cell-status")).to_have_text("waiting for sandbox: connect to run")
    expect(page.locator(".connect-panel")).to_be_visible()
    go(page, token)
    page.wait_for_function(LOADED, arg=CELLS, timeout=120_000)
    page.wait_for_function(DONE, arg="ring", timeout=180_000)
    status = page.locator("ws-cell[name=ring] .cell-status").inner_text()
    links = [loc for loc in page.locator("ws-cell[name=ring] .cell-out a.out-link").evaluate_all("(as) => as.map((a) => a.dataset.loc)") if loc.startswith("ring.cpp:")]
    check(status.startswith("failed") and links and int(links[0].split(":")[1]) in (line, line + 1), f"a Run queued before Connect ran once connected: {status!r}, links {links}")
    page.locator(f"ws-cell[name=ring] .cell-out a.out-link[data-loc='{links[0]}']").first.click()
    cursor = page.evaluate("() => { const v = document.querySelector('ws-cell[name=ring]').view; return {line: v.state.doc.lineAt(v.state.selection.main.head).number, focused: v.hasFocus}; }")
    check(cursor == {"line": int(links[0].split(":")[1]), "focused": True}, f"the compile error's link puts the ring cursor on its line ({cursor})")


def cells(page: Page) -> None:
    status, out = run_cell(page, "ring", SOLUTION["ring.cpp"])
    check(status.startswith("passed") and "bundle" in out, f"ring passes: {status!r}")
    draft = SOLUTION["loop.cpp"].replace("// loop.cpp", "// loop.cpp (a draft, not run yet)")
    set_doc(page, "loop", draft)
    page.wait_for_function("document.querySelector('ws-cell[name=loop]').lastSaveMs !== undefined", timeout=15_000)
    page.wait_for_timeout(1000)
    page.evaluate("Object.keys(localStorage).filter((k) => k.startsWith('blogs.ws.')).forEach((k) => localStorage.removeItem(k))")
    page.reload()
    page.wait_for_function(LOADED, arg=CELLS, timeout=120_000)
    check(doc(page, "loop") == draft and page.get_attribute("ws-cell[name=loop]", "data-loaded") == "workspace", "reload: the loop draft comes back from the workspace")
    expect(page.locator("ws-cell[name=ring] .cell-status")).to_have_text("passed")
    set_doc(page, "loop", SOLUTION["loop.cpp"].replace(HANG, HANG + "    while (budget > 0) {\n    } // never returns\n"))
    page.locator("ws-cell[name=loop] .run").click()
    page.wait_for_function("document.querySelector('ws-cell[name=loop] .cell-out').textContent.includes('check_trace sched.trace')", timeout=60_000)
    page.evaluate("(s) => { const v = document.querySelector('scratch-cell').view; v.dispatch({changes: {from: 0, to: v.state.doc.length, insert: s}}); }", SCRATCH)
    page.locator("scratch-cell .run").click()
    page.wait_for_selector("scratch-cell .cell-out.pass", timeout=30_000)
    check("while the check was running: 42" in page.locator("scratch-cell .cell-out").inner_text() and page.get_attribute("ws-cell[name=loop]", "data-job") is not None,
          "a scratch cell runs while a check spins")  # fmt: skip
    expect(page.locator("ws-cell[name=loop] .run")).to_have_text("Stop")
    page.locator("ws-cell[name=loop] .run").click()
    page.wait_for_function(DONE, arg="loop", timeout=10_000)
    check(page.locator("ws-cell[name=loop] .cell-status").inner_text().startswith("stopped"), "Stop ends the spinning check")
    status, _ = run_cell(page, "budget", SOLUTION["budget.py"])
    check(status.startswith("passed"), f"budget (Python) passes: {status!r}")
    page.screenshot(path=OUT / "workspace.png")


def ch00(page: Page, stub: Replay) -> None:
    queued_run(page, TOKEN)
    cells(page)


def ch01(page: Page, stub: Replay) -> None:
    expect(page.locator("ws-cell[name=linear] .cell-status")).to_have_text("not connected: edits are kept in this browser")
    stub_gelu = region(doc(page, "gelu"), "gelu")
    replace_in_view(page, "gelu", stub_gelu, region(SOL1, "gelu"))
    check(region(doc(page, "attention"), "gelu") == region(SOL1, "gelu"), "an edit in one region cell shows in every view of gpt2.py")
    stored = page.wait_for_function("Object.entries(localStorage).find(([k]) => k.startsWith('blogs.ws.') && k.endsWith('.ch01.gpt2.py'))?.[1]").json_value()
    stored = json.loads(stored)["text"]
    page.locator("ws-cell[name=attention] .cm-content").click()
    page.keyboard.press("ControlOrMeta+z")
    undone = all(region(doc(page, c), "gelu") == stub_gelu for c in ("gelu", "attention", "generate"))
    page.keyboard.press("ControlOrMeta+Shift+z")
    check(region(SOL1, "gelu") in stored and undone and region(doc(page, "gelu"), "gelu") == region(SOL1, "gelu"), "kept in localStorage; undo/redo from another cell applies everywhere")
    replace_in_view(page, "block", "# region: block\n", "")
    expect(page.locator("ws-cell[name=block] .cell-note")).to_contain_text('no "# region: block"')
    replace_in_view(page, "block", "def mlp(", "# region: block\ndef mlp(")
    expect(page.locator("ws-cell[name=block] .cell-note")).to_be_hidden()
    page.locator("ws-cell[name=linear] .run").click()
    expect(page.locator("ws-cell[name=linear] .cell-status")).to_have_text("waiting for sandbox: connect to run")
    check(page.locator(".connect-panel").is_visible(), "a missing region marker is noted; Run while disconnected waits and opens Connect")


def fast(browser: Browser, base: str) -> None:
    dist = HERE / "dist" / "ch00-toy"
    listed = [line.split("  ")[1] for line in (dist / "_blogs/MANIFEST.sha256").read_text().splitlines()]
    check(all((dist / f).is_file() for f in ("index.html", "ref.bundle", "_blogs/workspace.py")) and all(f == "workspace.py" or f.startswith("assay/") for f in listed),
          f"ch00-toy ships _blogs/ ({len(listed)} files in MANIFEST.sha256) + ref.bundle")  # fmt: skip
    replayed(browser, base, ch00, "workspace", kernel=("workspace",))
    replayed(browser, base, ch01, "ch01")


if __name__ == "__main__":
    import replay

    replay.alone(fast, "workspace", "ch01")
