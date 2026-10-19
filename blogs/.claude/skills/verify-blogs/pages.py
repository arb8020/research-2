#!/usr/bin/env python3
"""verify-blogs browser drives that the repo's own harnesses don't cover. `vb drive` calls these; by hand:

    cd blogs && uv run --with playwright python .claude/skills/verify-blogs/pages.py <case> \
        --base http://127.0.0.1:<static port> --gateway http://127.0.0.1:<gateway port> --out <evidence dir> [--path /x/]

cases:
    plan       /00-plan/: title, wip banner, heading ids, no code cells, no Connect, no request to the session
    embeds     /01-flappy/: carousel next/prev + counter, <env-play> on the reference env;
               /neural-nets/: <nn-fit> trains in this browser and its loss falls
    links      /01-flappy/: [[neural-nets#fitting a curve]] hover card (title, heading, live nn-fit), Escape, click
    bad-token  /neural-nets/?gateway=: a token connect_dev.py rejects -> red pill + "failed to start" in the panel
    fixture    --path /vf-page-ok/: excerpt (file:lines, read-only), wip banner, todo note, page-link
Screenshots go to --out; each step prints one line. Exit 1 on the first failed check.
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import sys
from pathlib import Path

from playwright.sync_api import Browser, Page, expect, sync_playwright

CHROME_GLOB = "~/Library/Caches/ms-playwright/chromium-*/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"


def check(ok: bool, what: str) -> None:
    print(f"{'ok  ' if ok else 'FAIL'} {what}", flush=True)
    if not ok:
        sys.exit(1)


def new_page(browser: Browser, errors: list[str]) -> Page:
    page = browser.new_page(viewport={"width": 1000, "height": 900}, device_scale_factor=2)
    page.on("pageerror", lambda e: errors.append(str(e)))
    return page


def plan(browser: Browser, a: argparse.Namespace) -> None:
    errors: list[str] = []
    page = new_page(browser, errors)
    requests: list[str] = []
    page.on("request", lambda r: requests.append(r.url))
    page.goto(f"{a.base}/00-plan/")
    session = page.locator('meta[name="session-url"]').get_attribute("content") or ""
    check(page.locator("h1").inner_text() == "inference engine: curriculum plan", f"h1 {page.locator('h1').inner_text()!r}")
    wip = page.get_by_role("note", name="under construction")
    check(wip.count() == 1 and "plan only. no prose yet" in wip.inner_text(), f"wip banner {wip.inner_text()!r}")
    check(page.locator("h2#chapters").count() == 1, "## chapters has id #chapters")
    h3 = page.locator("h3[id]").count()
    check(h3 >= 5, f"{h3} chapter headings (h3 with ids)")
    check(page.locator("code-cell, scratch-cell, connect-pill, env-play").count() == 0, "no cells, no Connect, no play widget")
    page.wait_for_load_state("networkidle")
    check(not [u for u in requests if u.startswith(session)], f"no request to the session ({session})")
    check(not errors, f"no page errors {errors}")
    wip.screenshot(path=a.out / "plan-wip.png")
    page.screenshot(path=a.out / "plan-page.png", full_page=True)


YOUTUBE = re.compile(r"^https://(www\.)?youtube(-nocookie)?\.com/")


def embeds(browser: Browser, a: argparse.Namespace) -> None:
    errors: list[str] = []
    page = new_page(browser, errors)
    youtube: list[str] = []
    page.on("request", lambda r: youtube.append(r.url) if YOUTUBE.match(r.url) else None)
    page.route(YOUTUBE, lambda route: route.fulfill(body=""))
    page.goto(f"{a.base}/01-flappy/")
    car = page.locator("embed-carousel")
    car.scroll_into_view_if_needed()
    count = car.locator(".carousel-count")
    expect(count).to_have_text(re.compile(r"^1 / \d+$"))
    total = int(count.inner_text().split("/")[1])
    check(total == car.locator(".slide").count() and total >= 2, f"carousel: {total} slides, counter {count.inner_text()!r}")
    car.get_by_role("button", name="Next slide").click()
    expect(count).to_have_text(f"2 / {total}")
    car.get_by_role("button", name="Previous slide").click()
    expect(count).to_have_text(f"1 / {total}")
    check(True, "carousel: Next -> 2, Previous -> 1")
    first = car.locator(".slide").first
    check(not youtube and first.locator("a.facade").count() == 1, f"carousel: nothing loads from YouTube before a click {youtube}")
    first.locator("a.facade").click()
    expect(first.locator("iframe")).to_have_count(1)
    car.get_by_role("button", name="Next slide").click()
    expect(first.locator("iframe")).to_have_count(0)
    check(len(youtube) == 1 and first.locator("a.facade").count() == 1, f"carousel: a click loads the player {youtube}; leaving its slide unloads it")
    car.get_by_role("button", name="Previous slide").click()
    car.screenshot(path=a.out / "carousel.png")

    session = page.locator('meta[name="session-url"]').get_attribute("content") or ""
    reader_wasm = page.request.get(f"{session}/state").json()["wasm"].get("flappy")
    play = page.locator('env-play[cell="flappy"]')
    play.scroll_into_view_if_needed()
    if reader_wasm:
        expect(play.locator(".play-caption")).to_contain_text("playing: your env (latest passing version)")
    src = play.locator("iframe").get_attribute("src") or ""
    caption = play.locator(".play-caption").inner_text()
    if reader_wasm:
        check(src.endswith(re.sub(r"/", "%2F", reader_wasm)), f"env-play (reader's flappy has passed): {caption!r} ({src})")
    else:
        check(src.endswith("js=.%2Fflappy.js") and caption.startswith("playing: reference env"), f"env-play (fresh reader): {caption!r} ({src})")
    page.wait_for_timeout(2000)
    play.screenshot(path=a.out / f"env-play-{'reader' if reader_wasm else 'reference'}.png")

    page.goto(f"{a.base}/neural-nets/")
    nn = page.locator("nn-fit")
    nn.scroll_into_view_if_needed()
    page.wait_for_function("document.querySelector('nn-fit').stats?.loss != null")
    before = page.evaluate("document.querySelector('nn-fit').stats")
    nn.locator("button.train").click()
    page.wait_for_function("document.querySelector('nn-fit').stats.steps >= 200", timeout=30_000)
    nn.locator("button.train").click()
    after = page.evaluate("document.querySelector('nn-fit').stats")
    check(after["loss"] < before["loss"] / 10, f"nn-fit ({before['dataset']}, {before['sizes']}): loss {before['loss']:.3g} -> {after['loss']:.3g} in {after['steps']} steps")
    nn.screenshot(path=a.out / "nn-fit-trained.png")
    check(not errors, f"no page errors {errors}")


def links(browser: Browser, a: argparse.Namespace) -> None:
    errors: list[str] = []
    page = new_page(browser, errors)
    page.goto(f"{a.base}/01-flappy/")
    link = page.locator("page-link > a")
    check(link.count() == 1 and link.get_attribute("href") == "../neural-nets/#fitting-a-curve", f"one page-link -> {link.get_attribute('href')}")
    check(page.evaluate("customElements.get('nn-fit')") is None, "nn-fit not loaded before the card opens")
    page.wait_for_timeout(1500)
    print(f"info focus after load: <{page.evaluate('document.activeElement.tagName').lower()}>", flush=True)
    page.locator("h1").click()
    link.hover()
    card = page.locator(".link-card")
    card.wait_for()
    check(card.locator(".link-card-title").inner_text() == "neural networks", "card title 'neural networks'")
    check(card.locator(".link-card-heading").inner_text() == "fitting a curve", "card heading 'fitting a curve'")
    page.wait_for_function("document.querySelector('.link-card nn-fit')?.stats?.loss != null")
    check(True, "card holds a live nn-fit")
    page.wait_for_timeout(300)
    page.screenshot(path=a.out / "link-card.png")
    focused = page.evaluate("document.activeElement.tagName")
    page.keyboard.press("Escape")
    check(card.count() == 0, f"Escape closes the card (focus was on <{focused.lower()}>)")
    link.click()
    page.wait_for_url("**/neural-nets/#fitting-a-curve")
    check(True, f"click navigates to {page.url}")
    page.screenshot(path=a.out / "link-target.png")
    check(not errors, f"no page errors {errors}")


def bad_token(browser: Browser, a: argparse.Namespace) -> None:
    errors: list[str] = []
    page = new_page(browser, errors)
    page.goto(f"{a.base}/neural-nets/?gateway={a.gateway}")
    expect(page.locator(".connect-label")).to_have_text("Connect")
    page.locator(".connect-pill").click()
    expect(page.locator(".connect-panel")).to_be_visible()
    page.fill("input[name=token-id]", "not-a-modal-token")
    page.fill("input[name=token-secret]", "nope")
    page.screenshot(path=a.out / "bad-token-panel.png")
    page.locator(".connect-go").click()
    page.wait_for_selector("connect-pill[data-failed]", timeout=30_000)
    page.locator(".connect-pill").click()
    failure = page.locator(".connect-failure").inner_text()
    check("failed to start" in failure, f"bad token: {failure!r}")
    page.screenshot(path=a.out / "bad-token-failed.png")
    check(not errors, f"no page errors {errors}")


def fixture(browser: Browser, a: argparse.Namespace) -> None:
    errors: list[str] = []
    page = new_page(browser, errors)
    page.goto(f"{a.base}{a.path}")
    src = page.locator("figure.excerpt .excerpt-src").inner_text()
    check(src == "vendor/pufferlib/pufferenv.h:44–46 · read-only", f"excerpt header {src!r}")
    check(page.locator("figure.excerpt code-view .cm-editor").count() == 1, "excerpt renders as a read-only CodeMirror view")
    check(page.get_by_role("note", name="under construction").inner_text().endswith("verify-blogs fixture banner"), "wip banner")
    check(page.locator(".todo").count() == 1, "<!-- write: --> renders as a todo note")
    check(page.locator("page-link > a").get_attribute("href") == "../neural-nets/#fitting-a-curve", "[[link]] resolved")
    page.screenshot(path=a.out / "fixture-page.png", full_page=True)
    check(not errors, f"no page errors {errors}")


CASES = {"plan": plan, "embeds": embeds, "links": links, "bad-token": bad_token, "fixture": fixture}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("case", choices=sorted(CASES))
    ap.add_argument("--base", required=True, help="the static server, e.g. http://127.0.0.1:<port>")
    ap.add_argument("--gateway", required=True, help="the fake gateway (connect_dev.py)")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--path", default="/vf-page-ok/", help="fixture: the built fixture page")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    found = sorted(glob.glob(os.path.expanduser(CHROME_GLOB)))
    assert found, "no Playwright Chromium: vb setup"
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=found[-1])
        try:
            CASES[a.case](browser, a)
        finally:
            browser.close()


if __name__ == "__main__":
    main()
