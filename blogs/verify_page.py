"""Drive the built page in headless Chromium against a running session; write screenshots/page-builder/.

    uv run session.py rl/01-flappy.md --timeout 20      # in one tmux pane
    python3 -m http.server 8010 -d dist                # in another
    uv run --with playwright verify_page.py

Pastes the hidden C solution into the editor programmatically (testing only).
"""

from __future__ import annotations

import glob
import os
import re
import time
from pathlib import Path
from urllib.request import urlopen

from check import parse
from playwright.sync_api import sync_playwright

HERE = Path(__file__).parent
SHOTS = HERE / "screenshots" / "page-builder"
PAGE = "http://localhost:8010/01-flappy/"
CHROME = sorted(glob.glob(os.path.expanduser(
    "~/Library/Caches/ms-playwright/chromium-*/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing")))[-1]  # fmt: skip
BLOCKS = parse((HERE / "rl" / "01-flappy.md").read_text())
SOLUTION = next(b.source for b in BLOCKS if b.role == "solution" and b.name == "flappy")
STUB = next(b.source for b in BLOCKS if b.role == "cell" and b.name == "flappy")
POLICY = """def init_policy(obs_dim: int, n_actions: int, hidden: int, seed: int) -> dict[str, torch.Tensor]:
    g = torch.Generator().manual_seed(seed)
    w1 = (torch.randn(obs_dim, hidden, generator=g) / obs_dim**0.5).requires_grad_()
    w2 = (torch.randn(hidden, n_actions, generator=g) / hidden**0.5).requires_grad_()
    return {"w1": w1, "b1": torch.zeros(hidden, requires_grad=True), "w2": w2, "b2": torch.zeros(n_actions, requires_grad=True)}


def policy_probs(params: dict[str, torch.Tensor], obs: torch.Tensor) -> torch.Tensor:
    return torch.softmax(torch.tanh(obs @ params["w1"] + params["b1"]) @ params["w2"] + params["b2"], -1)
"""

html = urlopen(PAGE).read().decode()
assert "solution=" not in html and "flappy->tick += 1" not in html and "check=" not in html, "solution or check leaked"
assert not (HERE / ".session" / "01-flappy" / "state.json").exists(), "rm -rf .session first: verify expects a fresh reader"
SHOTS.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=CHROME)
    page = browser.new_page(viewport={"width": 900, "height": 1000}, device_scale_factor=2)
    page.on("pageerror", lambda e: print("  pageerror:", e))
    page.goto(PAGE)
    page.wait_for_selector('code-cell[name="train"] .cm-editor')
    page.wait_for_selector('code-cell[name="policy"].locked')
    page.screenshot(path=SHOTS / "0-page.png", full_page=True)
    print("page: policy locked =", page.locator('code-cell[name="policy"] .run').is_disabled())

    page.locator("env-play").scroll_into_view_if_needed()
    time.sleep(2)
    page.locator("env-play").screenshot(path=SHOTS / "0-play-reference.png")

    def cell(name):
        return page.locator(f'code-cell[name="{name}"]')

    def paste(name, src):
        page.evaluate("([n, s]) => { const v = document.querySelector(`code-cell[name=\"${n}\"]`).view;"
                      " v.dispatch({changes: {from: 0, to: v.state.doc.length, insert: s}}); }", [name, src])  # fmt: skip

    def run(name):
        start = time.perf_counter()
        cell(name).locator(".run").click()
        page.wait_for_selector(f'code-cell[name="{name}"] .cell-out:is(.pass, .fail)', timeout=60_000)
        out = cell(name).locator(".cell-out").inner_text().strip().splitlines()
        print(f"  run {name}: {time.perf_counter() - start:.1f}s -> {out[-2][:110]!r} / {out[-1]}")
        cell(name).locator(".cell-out").scroll_into_view_if_needed()
        return out

    run("flappy")
    cell("flappy").locator(".cell-out").screenshot(path=SHOTS / "1-flappy-stub-fails.png")
    cell("flappy").screenshot(path=SHOTS / "1-flappy-stub-fails-full.png")

    paste("flappy", SOLUTION)
    out = run("flappy")
    assert out[-1] == "PASS"
    cell("flappy").locator(".cell-head").scroll_into_view_if_needed()
    page.screenshot(path=SHOTS / "2-flappy-passes.png")
    cell("flappy").locator(".cell-out").screenshot(path=SHOTS / "2-flappy-passes-output.png")

    page.wait_for_selector('code-cell[name="policy"]:not(.locked)')
    run("policy")
    cell("policy").screenshot(path=SHOTS / "3-policy-unlocked-stub-fails.png")
    paste("policy", POLICY)
    assert run("policy")[-1] == "PASS"
    page.wait_for_selector('code-cell[name="sample"]:not(.locked)')
    cell("policy").screenshot(path=SHOTS / "3-policy-passes.png")
    print("  sample unlocked:", not cell("sample").locator(".run").is_disabled())

    page.wait_for_function("document.querySelector('env-play iframe').src.includes('8787')")
    play = page.locator("env-play")
    play.scroll_into_view_if_needed()
    print("  play widget:", page.locator(".play-caption").inner_text())
    frame = page.frame_locator("env-play iframe")
    frame.locator("canvas").click()
    for key in ("ArrowDown", "ArrowUp", "ArrowDown"):
        page.keyboard.down(key)
        time.sleep(0.1)
        page.keyboard.up(key)
        time.sleep(1.1)
    play.screenshot(path=SHOTS / "4-play-your-env.png")

    paste("flappy", STUB.replace("// write stub here", "volatile int *p = 0;\n    *p = 1;"))
    assert run("flappy")[-1] == "FAIL"
    assert run("policy")[-1] == "PASS", "a failing upstream edit must not propagate"
    cell("flappy").screenshot(path=SHOTS / "5-flappy-segfault.png")

    paste("flappy", STUB.replace("// write stub here", "while (1) {}"))
    assert run("flappy")[-1] == "FAIL"

    page.reload()
    page.wait_for_selector('code-cell[name="sample"]:not(.locked)')
    restored = page.evaluate("document.querySelector('code-cell[name=\"flappy\"]').view.state.doc.toString()")
    print("  after reload: flappy editor restored to last passing =", restored == SOLUTION,
          "| sample unlocked, loss locked =", page.locator('code-cell[name="loss"].locked').count() == 1)
    print("  after reload: play widget =", page.locator(".play-caption").inner_text())
    print("  wasm url:", re.search(r"js=([^&]+)", page.locator("env-play iframe").get_attribute("src"))[1])
    browser.close()
