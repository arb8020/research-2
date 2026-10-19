from __future__ import annotations

import glob
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import urlopen

from playwright.sync_api import Browser, Locator, sync_playwright

from check import parse

HERE = Path(__file__).parent
SHOTS = HERE / ".evidence" / "verify_page"
PAGE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8010/01-flappy/"
NEURAL_NETS = urljoin(PAGE, "../neural-nets/")
CHROME = sorted(glob.glob(os.path.expanduser(
    "~/Library/Caches/ms-playwright/chromium-*/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing")))[-1]  # fmt: skip
BLOCKS = parse((HERE / "rl" / "01-flappy.md").read_text())
SOLUTION = next(b.source for b in BLOCKS if b.role == "solution" and b.name == "flappy")
STUB = next(b.source for b in BLOCKS if b.role == "cell" and b.name == "flappy")
INJECT = "// increment env by a tick"
PAST_LINK_CARD_GRACE_MS = 300
assert INJECT in STUB, "verify_page injects crash/hang code at a stub comment that is gone"
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
SESSION = re.search(r'<meta name="session-url" content="([^"]+)">', html)[1]
assert not (HERE / ".session" / "01-flappy" / "state.json").exists(), "rm -rf .session first: verify expects a fresh reader"
SHOTS.mkdir(parents=True, exist_ok=True)


def nn_fit_and_wip(browser: Browser, scheme: str) -> None:
    page = browser.new_page(viewport={"width": 900, "height": 1000}, device_scale_factor=2, color_scheme=scheme)
    page.on("pageerror", lambda e: print("  pageerror:", e))
    page.goto(NEURAL_NETS)
    wip = page.locator(".wip")
    assert wip.count() == 1 and wip.is_visible(), "the wip banner is missing"
    assert "still working on" in wip.inner_text(), wip.inner_text()
    nn = page.locator("nn-fit")
    nn.scroll_into_view_if_needed()
    before = page.evaluate("document.querySelector('nn-fit').stats")
    assert before["dataset"] == "wave" and before["sizes"] == [1, 12, 12, 1], before
    assert before["steps"] == 0 and before["loss"] is not None, before
    nn.locator("button.train").click()
    page.wait_for_function("document.querySelector('nn-fit').stats.steps >= 200", timeout=20_000)
    nn.locator("button.train").click()
    after = page.evaluate("document.querySelector('nn-fit').stats")
    assert after["loss"] < before["loss"] / 10, f"loss {before['loss']} -> {after['loss']} after {after['steps']} steps"
    print(f"  nn-fit ({scheme}): {before['sizes']} loss {before['loss']:.3g} -> {after['loss']:.3g} after {after['steps']} steps")
    page.locator(".wip").scroll_into_view_if_needed()
    wip.screenshot(path=SHOTS / f"nn-fit-wip-banner-{scheme}.png")
    nn.screenshot(path=SHOTS / f"nn-fit-widget-{scheme}.png")
    page.evaluate("document.querySelector('.wip').scrollIntoView({block: 'start'})")
    page.screenshot(path=SHOTS / f"nn-fit-section-{scheme}.png")
    page.close()


def link_preview(browser: Browser, scheme: str) -> None:
    page = browser.new_page(viewport={"width": 900, "height": 900}, device_scale_factor=2, color_scheme=scheme)
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(PAGE)
    assert page.evaluate("customElements.get('nn-fit')") is None, "nn-fit should load only when a card first needs it"
    link = page.locator("page-link > a")
    assert link.count() == 1 and link.get_attribute("href") == "../neural-nets/#fitting-a-curve", link.get_attribute("href")
    page.evaluate("scrollBy(0, document.querySelector('page-link').getBoundingClientRect().top - 120)")

    grace = page.evaluate("""async () => {
        const host = document.querySelector('page-link');
        host.dispatchEvent(new PointerEvent('pointerenter', {pointerType: 'mouse'}));
        const card = document.querySelector('.link-card');
        const hit = () => { const r = card.getBoundingClientRect(); return card.contains(document.elementFromPoint(r.left + r.width / 2, r.top + 20)); };
        const early = hit();
        await new Promise((ok) => setTimeout(ok, 350));
        const late = hit();
        host.dispatchEvent(new PointerEvent('pointerleave', {pointerType: 'mouse'}));
        await new Promise((ok) => setTimeout(ok, 450));
        return {early, late, closed: document.querySelector('.link-card') === null};
    }""")
    assert grace == {"early": False, "late": True, "closed": True}, grace

    link.hover()
    card = page.locator(".link-card")
    card.wait_for()
    assert card.locator(".link-card-title").inner_text() == "neural networks", card.locator(".link-card-title").inner_text()
    assert card.locator(".link-card-heading").inner_text() == "fitting a curve"
    page.wait_for_function("document.querySelector('.link-card nn-fit')?.stats?.loss != null")
    stats = page.evaluate("document.querySelector('.link-card nn-fit').stats")
    assert stats["dataset"] == "wave" and stats["sizes"] == [1, 12, 12, 1], stats
    page.wait_for_timeout(PAST_LINK_CARD_GRACE_MS)
    page.screenshot(path=SHOTS / f"link-card-{scheme}.png")
    card.screenshot(path=SHOTS / f"link-card-only-{scheme}.png")
    box = card.bounding_box()
    link_box = link.bounding_box()
    assert box is not None and link_box is not None
    assert box["y"] > link_box["y"] and box["width"] <= 430, (box, link_box)
    overflow = page.evaluate("document.documentElement.scrollWidth - innerWidth")
    assert overflow <= 0, f"the page scrolls sideways by {overflow}px with the card open"
    nn_box = card.locator("nn-fit").bounding_box()
    assert nn_box is not None and nn_box["x"] + nn_box["width"] <= box["x"] + box["width"], (nn_box, box)
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + 40)
    card.locator("nn-fit button.train").click()
    page.wait_for_function("document.querySelector('.link-card nn-fit').stats.steps >= 50", timeout=20_000)
    card.locator("nn-fit button.train").click()
    print(f"  link card ({scheme}): {box['width']:.0f}x{box['height']:.0f}px, nn-fit {nn_box['width']:.0f}px wide,"
          f" trained {page.evaluate('document.querySelector(\'.link-card nn-fit\').stats.steps')} steps in the card")
    card.screenshot(path=SHOTS / f"link-card-trained-{scheme}.png")
    page.keyboard.press("Escape")
    assert card.count() == 0, "Escape should close the card"

    page.mouse.move(5, 5)
    page.evaluate("document.activeElement.blur()")
    link.focus()
    card.wait_for()
    page.keyboard.press("Escape")
    assert card.count() == 0 and page.evaluate("document.activeElement === document.querySelector('page-link > a')")

    link.click()
    page.wait_for_url("**/neural-nets/#fitting-a-curve")
    top = page.evaluate("document.getElementById('fitting-a-curve').getBoundingClientRect().top")
    assert 0 <= top < 200, f"#fitting-a-curve is at y={top}, not at the top of the view"
    page.screenshot(path=SHOTS / f"link-target-{scheme}.png")
    assert not errors, errors
    print(f"  link click ({scheme}): {page.url}, heading at y={top:.0f}")
    page.close()


def link_on_touch(browser: Browser) -> None:
    context = browser.new_context(viewport={"width": 390, "height": 800}, is_mobile=True, has_touch=True)
    page = context.new_page()
    page.goto(PAGE)
    assert page.evaluate("matchMedia('(pointer: coarse)').matches"), "the touch emulation isn't coarse"
    page.locator("page-link > a").tap()
    page.wait_for_url("**/neural-nets/#fitting-a-curve")
    print("  link on touch: tap navigated, no card")
    context.close()


with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=CHROME)
    page = browser.new_page(viewport={"width": 900, "height": 1000}, device_scale_factor=2)
    page.on("pageerror", lambda e: print("  pageerror:", e))
    page.goto(PAGE)
    page.wait_for_selector('code-cell[name="train"] .cm-editor')
    page.wait_for_selector('code-cell[name="policy"].locked')
    page.screenshot(path=SHOTS / "0-page.png", full_page=True)
    print("page: policy locked =", page.locator('code-cell[name="policy"] .run').is_disabled())

    for scheme in ("light", "dark"):
        nn_fit_and_wip(browser, scheme)
        link_preview(browser, scheme)
    link_on_touch(browser)

    page.locator("env-play").scroll_into_view_if_needed()
    time.sleep(2)
    page.locator("env-play").screenshot(path=SHOTS / "0-play-reference.png")

    def cell(name: str) -> Locator:
        return page.locator(f'code-cell[name="{name}"]')

    def paste(name: str, src: str) -> None:
        page.evaluate("([n, s]) => { const v = document.querySelector(`code-cell[name=\"${n}\"]`).view;"
                      " v.dispatch({changes: {from: 0, to: v.state.doc.length, insert: s}}); }", [name, src])  # fmt: skip

    def run(name: str) -> bool:
        start = time.perf_counter()
        cell(name).locator(".run").click()
        page.wait_for_selector(f'code-cell[name="{name}"] .cell-out:is(.pass, .fail)', timeout=60_000)
        passed = cell(name).locator(".cell-out.pass").count() == 1
        status = cell(name).locator(".cell-status").inner_text()
        print(f"  run {name}: {time.perf_counter() - start:.1f}s -> {'PASS' if passed else 'FAIL'} | status: {status[:110]!r}")
        cell(name).locator(".cell-out").scroll_into_view_if_needed()
        return passed

    assert not run("flappy")
    cell("flappy").locator(".cell-out").screenshot(path=SHOTS / "1-flappy-stub-fails.png")
    cell("flappy").screenshot(path=SHOTS / "1-flappy-stub-fails-full.png")

    paste("flappy", SOLUTION)
    assert run("flappy")
    cell("flappy").locator(".cell-head").scroll_into_view_if_needed()
    page.screenshot(path=SHOTS / "2-flappy-passes.png")
    cell("flappy").locator(".cell-out").screenshot(path=SHOTS / "2-flappy-passes-output.png")

    page.wait_for_selector('code-cell[name="policy"]:not(.locked)')
    assert not run("policy")
    cell("policy").screenshot(path=SHOTS / "3-policy-unlocked-stub-fails.png")
    paste("policy", POLICY)
    assert run("policy")
    page.wait_for_selector('code-cell[name="sample"]:not(.locked)')
    cell("policy").screenshot(path=SHOTS / "3-policy-passes.png")
    print("  sample unlocked:", not cell("sample").locator(".run").is_disabled())

    page.wait_for_function("s => document.querySelector('env-play iframe').src.includes(encodeURIComponent(s))", arg=SESSION)
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

    paste("flappy", STUB.replace(INJECT, "volatile int *p = 0;\n    *p = 1;"))
    assert not run("flappy")
    assert run("policy"), "a failing upstream edit must not propagate"
    cell("flappy").screenshot(path=SHOTS / "5-flappy-segfault.png")

    paste("flappy", STUB.replace(INJECT, "while (1) {}"))
    assert not run("flappy")

    page.reload()
    page.wait_for_selector('code-cell[name="sample"]:not(.locked)')
    restored = page.evaluate("document.querySelector('code-cell[name=\"flappy\"]').view.state.doc.toString()")
    print("  after reload: flappy editor restored to last passing =", restored == SOLUTION,
          "| sample unlocked, loss locked =", page.locator('code-cell[name="loss"].locked').count() == 1)
    print("  after reload: play widget =", page.locator(".play-caption").inner_text())
    print("  wasm url:", re.search(r"js=([^&]+)", page.locator("env-play iframe").get_attribute("src"))[1])
    browser.close()
