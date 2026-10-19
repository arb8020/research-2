from __future__ import annotations

import re
import time
from collections.abc import Callable
from typing import Any

from playwright.sync_api import Browser, Page, expect

from replay import DEFAULT_LIMITS, OUT, TOKEN, Replay, check, page_url

PID = "import os\nprint('kernel pid', os.getpid())"
LONG = "import time\nfor i in range(600):\n    print(i, flush=True)\n    time.sleep(0.05)"
REASONS = [("stopped", "the session was stopped outside this page"), ("lease", "the session length ran out"), ("idle", "the session was idle too long"),
           ("boot_failed", "the machine failed to start"), ("machine_lost", "the machine went away")]  # fmt: skip
AXE = "https://cdn.jsdelivr.net/npm/axe-core@4.10.2/axe.min.js"


def left(until: float) -> str:
    minutes = int((until - time.time()) // 60)
    shown = ["<1m" if m < 1 else f"{m}m" if m < 60 else f"{m // 60}h {m % 60:02d}m" for m in (minutes, minutes - 1)]
    return "(" + "|".join(map(re.escape, shown)) + ")"


def open_menu(page: Page) -> None:
    if page.locator(".connect-panel").is_hidden():
        page.locator(".connect-pill").click()
    expect(page.locator(".connect-panel")).to_be_visible()


def go(page: Page, token: tuple[str, str]) -> None:
    open_menu(page)
    if page.locator("input[name=token-id]").is_visible():
        page.fill("input[name=token-id]", token[0])
        page.fill("input[name=token-secret]", token[1])
    page.locator(".connect-go").click()


def connected(page: Page, token: tuple[str, str] = TOKEN) -> None:
    go(page, token)
    page.wait_for_selector("connect-pill[data-phase=connected]", timeout=120_000)
    page.keyboard.press("Escape")


def paste(page: Page, code: str) -> None:
    page.evaluate("s => { const v = document.querySelector('scratch-cell').view; v.dispatch({changes: {from: 0, to: v.state.doc.length, insert: s}}); }", code)


def run_cell(page: Page, code: str | None = None) -> str:
    if code is not None:
        paste(page, code)
    page.locator("scratch-cell").scroll_into_view_if_needed()
    page.locator("scratch-cell .run").click()
    page.wait_for_selector("scratch-cell .cell-out:is(.pass, .fail)", timeout=60_000)
    return page.locator("scratch-cell .cell-out").inner_text()


def failure(page: Page) -> str:
    page.wait_for_selector("connect-pill[data-phase=disconnected][data-failed]", timeout=60_000)
    open_menu(page)
    return page.locator(".connect-failure").inner_text()


def nvidia_smi(page: Page, gpu: str) -> None:
    out = run_cell(page, "!nvidia-smi")
    check("NVIDIA-SMI" in out and gpu in out, f"nvidia-smi on the session's {gpu}")


def scratch(page: Page) -> None:
    pid = run_cell(page, PID).strip()
    check(pid.startswith("kernel pid"), f"a scratch cell runs on the session's kernel ({pid})")
    paste(page, LONG)
    page.locator("scratch-cell .run").click()
    page.wait_for_function("document.querySelector('scratch-cell .cell-out').textContent.includes('\\n5\\n')", timeout=30_000)
    expect(page.locator("scratch-cell .run")).to_have_text("Stop")
    page.locator("scratch-cell .run").click()
    page.wait_for_selector("scratch-cell .cell-out.fail", timeout=30_000)
    check(page.locator("scratch-cell .cell-status").inner_text().startswith("KeyboardInterrupt ("), "Stop interrupts a running cell: KeyboardInterrupt")
    posts: list[str] = []
    page.on("request", lambda r: posts.append(r.url) if r.method == "POST" and r.url.endswith("/sessions") else None)
    page.reload()
    page.wait_for_selector("connect-pill[data-phase=connected]", timeout=60_000)
    check(run_cell(page, PID).strip() == pid and not posts, "reload reattaches to the same session and kernel, no new POST /sessions")


def extend(page: Page, seconds: int) -> str:
    open_menu(page)
    if page.locator(".connect-extend").is_hidden():
        page.locator(".connect-extend-open").click()
    page.select_option("select[name=extend-by]", str(seconds))
    page.locator(".connect-extend-go").click()
    result = page.locator(".connect-extend-result")
    expect(result).to_have_text(re.compile(r"^Now ends [^…]+$"))
    if seconds == 0:
        expect(page.locator(".connect-extend-open")).to_be_disabled()
        check("limit" in result.inner_text(), f"extend to the limit: {result.inner_text()!r}, Extend… disabled")
    page.keyboard.press("Escape")
    return result.inner_text()


def runout(page: Page) -> None:
    text = failure(page)
    check("session length ran out" in text, f"a run-out lease says so: {text!r}")


def replayed(browser: Browser, base: str, body: Callable[[Page, Replay], None], page_name: str = "connect", **kw: Any) -> None:
    context = browser.new_context(**{"viewport": {"width": 1100, "height": 800}, **kw.pop("context", {})})
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    stub = Replay(page, **kw)
    page.goto(page_url(base, page_name))
    body(page, stub)
    check(not errors and not stub.errors, f"no page or replay errors ({errors + stub.errors})")
    context.close()


def story(page: Page, stub: Replay) -> None:
    expect(page.locator(".connect-label")).to_have_text("Connect")
    expect(page.locator("scratch-cell .run")).to_be_disabled()
    page.locator("scratch-cell .connect-to-run").click()
    expect(page.locator("input[value=runpod]")).to_be_disabled()
    check(page.evaluate("document.activeElement.name") == "token-id", "Connect to run opens the panel, focus on the token")
    go(page, TOKEN)
    page.locator(".connect-pill").click()
    page.locator(".connect-menu .connect-details").click()
    page.wait_for_selector("connect-pill[data-phase=connected]", timeout=30_000)
    expect(page.locator(".connect-label")).to_have_text(re.compile(rf"^CPU · {left(stub.session.latest['lease_until'])} left$"))
    check(page.locator(".drawer-log li").count() > 5 and page.locator(".drawer-follow").is_checked(), "the drawer streamed the boot, following")
    page.locator(".drawer-close").click()
    check(page.evaluate("document.activeElement.className") == "connect-pill", "closing the drawer returns focus to the pill")
    page.screenshot(path=OUT / "connected.png")
    scratch(page)
    check(len(stub.posts) == 1 and stub.posts[0]["lease_s"] == 5400, f"one POST /sessions, the default 90 min ({stub.posts})")
    open_menu(page)
    page.locator(".connect-end").click()
    page.wait_for_selector("connect-pill[data-phase=disconnected]")
    check(page.evaluate("localStorage.getItem('connect.session')") is None, "Disconnect forgets the session")
    open_menu(page)
    mask = page.locator(".connect-token-mask").inner_text()
    page.locator(".connect-forget").click()
    check("…" in mask and page.evaluate("localStorage.getItem('connect.token.modal')") is None, f"the token showed masked ({mask!r}); Sign out forgets it")


def lease(page: Page, stub: Replay) -> None:
    open_menu(page)
    expect(page.locator("select[name=length]")).to_have_value("5400")
    page.select_option("select[name=length]", "custom")
    page.fill("input[name=length-min]", "721")
    expect(page.locator(".connect-ends")).to_contain_text("12 h at most")
    page.locator(".connect-go").click()
    check(not stub.posts and page.locator("input[name=length-min]:invalid").count() == 1, "721 min is refused by the form")
    page.fill("input[name=length-min]", "150")
    expect(page.locator(".connect-ends")).to_contain_text("Ends at")
    connected(page)
    check(stub.posts[0]["lease_s"] == 9000, "custom 150 min reaches POST /sessions as lease_s 9000")
    before = stub.session.latest["lease_until"]
    shown = extend(page, 1800)
    check(abs(stub.extends[0]["until"] - max(before, time.time()) - 1800) < 5 and time.strftime("%H:%M", time.localtime(stub.session.latest["lease_until"])) in shown,
          f"+30 min asks lease_until + 30 min and shows the granted end ({shown!r})")  # fmt: skip
    expect(page.locator(".connect-label")).to_have_text(re.compile(rf"^CPU · {left(stub.session.latest['lease_until'])} left$"))
    shown = extend(page, 0)
    check(shown.endswith("the 12 h limit.") and stub.extends[1]["until"] == stub.session.latest["ceiling"], "to the limit asks for the ceiling; the text names the gateway's 12 h")
    stub.release()
    runout(page)


def reasons(page: Page, stub: Replay) -> None:
    for reason, text in REASONS:
        connected(page)
        stub.session.push({**stub.session.latest, "state": "ended", "reason": reason})
        got = failure(page)
        check(text in got, f"ended ({reason}) -> {got!r}")
        page.keyboard.press("Escape")


def no_lease_until(page: Page, stub: Replay) -> None:
    connected(page)
    tokens = []

    def strip(body: dict) -> dict:
        tokens.append(body["status"]["kernel"]["token"])
        return {**body, "status": {k: v for k, v in body["status"].items() if k != "lease_until"}}

    stub.on_get = strip
    page.reload()
    text = failure(page)
    check("lease_until" in text and "[redacted]" in text and tokens and all(t not in text for t in tokens), f"a status without lease_until is a gateway error, token redacted: {text[:90]!r}")


def bad_token(page: Page, stub: Replay) -> None:
    go(page, ("not-a-modal-token", "nope"))
    text = failure(page)
    check("failed to start" in text, f"a token the gateway rejects: {text!r}")


def phone(page: Page, stub: Replay) -> None:
    connected(page)
    run_cell(page, PID)
    check(page.evaluate("document.documentElement.scrollWidth - innerWidth") <= 0, "phone, dark: connected and ran, no sideways scroll")
    page.locator(".connect-pill").click()
    page.locator(".connect-menu .connect-details").click()
    page.screenshot(path=OUT / "phone-drawer-dark.png")


def axe(page: Page, stub: Replay) -> None:
    connected(page)
    run_cell(page, PID)
    page.add_script_tag(url=AXE)
    page.locator(".connect-pill").click()
    found = page.evaluate("axe.run(document, {resultTypes: ['violations']})")["violations"]
    page.locator(".connect-menu .connect-details").click()
    found += page.evaluate("axe.run(document, {resultTypes: ['violations']})")["violations"]
    check(not found, f"axe: menu and drawer open, {page.evaluate('document.documentElement.dataset.theme')}: {[v['id'] for v in found]}")


def fast(browser: Browser, base: str) -> None:
    replayed(browser, base, bad_token, sessions=["bad-token"])
    replayed(browser, base, story, limits=DEFAULT_LIMITS)
    replayed(browser, base, lease, limits=DEFAULT_LIMITS)
    replayed(browser, base, reasons)
    replayed(browser, base, no_lease_until)
    replayed(browser, base, phone, context={"viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True, "color_scheme": "dark"})
    for theme in ("classic", "paper"):
        for scheme in ("light", "dark"):
            replayed(browser, base, axe, context={"color_scheme": scheme, "storage_state": {"cookies": [], "origins": [
                {"origin": base, "localStorage": [{"name": "blogs.settings", "value": f'{{"theme": "{theme}"}}'}]}]}})  # fmt: skip


if __name__ == "__main__":
    import replay

    replay.alone(fast, "connect")
