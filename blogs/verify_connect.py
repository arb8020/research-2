"""Drive Connect end to end in headless Chromium; video + screenshots in .evidence/verify_connect/ (gitignored).

    uv run --with playwright verify_connect.py                       # fake gateway (connect_dev.py), started here
    uv run --with playwright verify_connect.py --gateway URL         # a running gateway instead (the real relay);
                                                                     #   token from MODAL_TOKEN_ID / MODAL_TOKEN_SECRET

Builds dl/neural-nets.md and serves dist/ itself. The story (recorded as connect.webm, and .mp4 if ffmpeg is there):
a bad token fails with a reason (not recorded); then paste a token, pick T4, connect with the Details drawer open,
run the nvidia-smi scratch cell, Stop a long cell, reload (the session and its kernel carry over, no new POST),
Disconnect, Sign out. Also: phone width, dark mode, and axe on the connected page with the panel and drawer open.
Lease (screenshots in .evidence/lease/): a custom session length is capped at 12 h and reaches POST /sessions as lease_s,
the pill counts down, Extend pushes the lease and is clamped at the ceiling, a shorter extend is a no-op (200, lease
unchanged), and (fake only) a run-out lease says so, extending it after is a no-op (200, ended), and extending while
booting is 409. Then: a status without lease_until fails the page with a gateway error (not a guess), and a session
ended from outside the page (POST /end, as another tab or a release would) shows as Disconnected with a reason.
"""

from __future__ import annotations

import argparse
import functools
import glob
import json
import os
import re
import shutil
import subprocess
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from playwright.sync_api import Browser, BrowserContext, Page, Route, expect, sync_playwright

HERE = Path(__file__).parent
OUT = HERE / ".evidence" / "verify_connect"
LEASE_OUT = HERE / ".evidence" / "lease"
CHROME = sorted(glob.glob(os.path.expanduser(
    "~/Library/Caches/ms-playwright/chromium-*/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing")))[-1]  # fmt: skip
AXE = "https://cdn.jsdelivr.net/npm/axe-core@4.10.2/axe.min.js"
FAKE_TOKEN = ("ak-verify-connect-0001", "as-verify-connect-secret")
PID = "import os\nprint('kernel pid', os.getpid())"
LONG = "import time\nfor i in range(600):\n    print(i, flush=True)\n    time.sleep(0.05)"


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, fmt: str, *args: object) -> None:
        pass


def serve_dist(port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), functools.partial(Quiet, directory=str(HERE / "dist")))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def start_fake(port: int) -> subprocess.Popen[bytes]:
    log = (OUT / "connect_dev.log").open("wb")
    proc = subprocess.Popen(["uv", "run", "connect_dev.py", "--port", str(port), "--boot-delay", "0.8"], cwd=HERE, stdout=log, stderr=log)
    for _ in range(240):  # first run installs jupyter_server
        try:
            urlopen(f"http://127.0.0.1:{port}/sessions/none")
        except OSError as e:
            if getattr(e, "code", None) == 404:
                return proc
            time.sleep(0.5)
    proc.kill()
    raise RuntimeError(f"connect_dev.py never answered on :{port} (see {OUT / 'connect_dev.log'})")


def gateway_call(gateway: str, path: str, token: tuple[str, str], method: str = "GET", body: dict[str, Any] | None = None) -> dict[str, Any]:
    headers = {"X-Box-Token": f"{token[0]}:{token[1]}", **({"Content-Type": "application/json"} if body is not None else {})}
    data = None if body is None else json.dumps(body).encode()
    req = Request(f"{gateway}{path}", data=data, method=method, headers=headers)
    with urlopen(req, timeout=10) as r:
        body: dict[str, Any] = json.load(r)
    return body


def paste(page: Page, code: str) -> None:
    page.evaluate("s => { const v = document.querySelector('scratch-cell').view; v.dispatch({changes: {from: 0, to: v.state.doc.length, insert: s}}); }", code)


def run_cell(page: Page, timeout: float = 60_000) -> str:
    page.locator("scratch-cell .run").click()
    page.wait_for_selector("scratch-cell .cell-out:is(.pass, .fail)", timeout=timeout)
    return page.locator("scratch-cell .cell-out").inner_text()


def open_menu(page: Page) -> None:
    page.locator(".connect-pill").click()
    expect(page.locator(".connect-panel")).to_be_visible()


def bad_token(browser: Browser, url: str) -> None:
    """A token the gateway rejects: the pill comes back to Connect with a red dot and the panel says why."""
    context = browser.new_context(viewport={"width": 1000, "height": 800}, device_scale_factor=2)
    page = context.new_page()
    page.goto(url)
    open_menu(page)
    page.fill("input[name=token-id]", "not-a-modal-token")
    page.fill("input[name=token-secret]", "nope")
    page.locator(".connect-go").click()
    page.wait_for_selector("connect-pill[data-failed]", timeout=30_000)
    open_menu(page)
    failure = page.locator(".connect-failure").inner_text()
    assert "failed to start" in failure, failure
    page.screenshot(path=OUT / "0-bad-token.png")
    print(f"  bad token: {failure!r}")
    context.close()


def story(context: BrowserContext, url: str, token: tuple[str, str], gateway: str) -> Page:
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    posts: list[dict[str, Any]] = []
    page.on("request", lambda r: posts.append(r.post_data_json) if r.method == "POST" and r.url.rstrip("/").endswith("/sessions") else None)
    page.goto(url)
    expect(page.locator(".connect-label")).to_have_text("Connect")
    page.locator("scratch-cell").scroll_into_view_if_needed()
    expect(page.locator("scratch-cell .run")).to_be_disabled()
    expect(page.locator("scratch-cell .connect-to-run")).to_be_visible()
    page.screenshot(path=OUT / "1-disconnected.png")

    # "Connect to run" opens the panel; RunPod is there but disabled.
    page.locator("scratch-cell .connect-to-run").click()
    expect(page.locator(".connect-panel")).to_be_visible()
    expect(page.locator("input[value=runpod]")).to_be_disabled()
    assert page.evaluate("document.activeElement.name") == "token-id", "the panel should focus the token field"
    page.fill("input[name=token-id]", token[0])
    page.fill("input[name=token-secret]", token[1])
    page.select_option("select[name=gpu]", "T4")
    page.screenshot(path=OUT / "2-panel.png")
    page.locator(".connect-go").click()
    expect(page.locator(".connect-label")).to_contain_text("connecting…")
    open_menu(page)
    page.locator(".connect-menu .connect-details").click()
    expect(page.locator(".connect-drawer")).to_be_visible()
    page.wait_for_timeout(700)
    page.screenshot(path=OUT / "3-connecting-drawer.png")
    page.wait_for_selector("connect-pill[data-phase=connected]", timeout=600_000)
    assert posts[0]["lease_s"] == 5400, f"default session length should be 90 min, sent {posts[0]!r}"
    expect(page.locator(".connect-label")).to_have_text(re.compile(r"^T4 · 1h (29|30)m left$"))
    page.wait_for_timeout(500)
    page.screenshot(path=OUT / "4-connected-drawer.png")
    steps = page.locator(".drawer-log li").count()
    assert page.locator(".drawer-follow").is_checked(), "follow turned itself off while the log streamed"
    print(f"  connected: pill {page.locator('.connect-label').inner_text()!r}, drawer {steps} lines")
    page.locator(".drawer-close").click()
    expect(page.locator(".connect-drawer")).to_be_hidden()
    assert page.evaluate("document.activeElement.className") == "connect-pill", "closing the drawer returns focus to the pill"

    # nvidia-smi on the session's kernel.
    page.locator("scratch-cell").scroll_into_view_if_needed()
    out = run_cell(page)
    assert "NVIDIA-SMI" in out and "T4" in out, out
    assert page.locator("scratch-cell .cell-out.pass").count() == 1
    print(f"  nvidia-smi: {page.locator('scratch-cell .cell-status').inner_text()!r}, {len(out.splitlines())} lines{' (FAKE)' if 'FAKE' in out else ''}")
    page.locator("scratch-cell").screenshot(path=OUT / "5-nvidia-smi.png")
    page.screenshot(path=OUT / "5-nvidia-smi-page.png")

    paste(page, PID)
    pid = run_cell(page).strip()

    # Stop interrupts a long run.
    paste(page, LONG)
    page.locator("scratch-cell .run").click()
    page.wait_for_function("document.querySelector('scratch-cell .cell-out').textContent.includes('\\n5\\n')", timeout=30_000)
    expect(page.locator("scratch-cell .run")).to_have_text("Stop")
    page.locator("scratch-cell .run").click()
    page.wait_for_selector("scratch-cell .cell-out.fail", timeout=30_000)
    status = page.locator("scratch-cell .cell-status").inner_text()
    assert status.startswith("KeyboardInterrupt ("), status
    print(f"  stop: {status!r}")
    page.locator("scratch-cell").screenshot(path=OUT / "6-stopped.png")

    # Reload: same session, same kernel, no new POST /sessions.
    before = len(posts)
    page.reload()
    page.wait_for_selector("connect-pill[data-phase=connected]", timeout=60_000)
    paste(page, PID)
    again = run_cell(page).strip()
    assert again == pid, f"kernel changed across reload: {pid!r} -> {again!r}"
    assert len(posts) == before == 1, f"POST /sessions sent {len(posts)} times (once expected)"
    stored = page.evaluate("JSON.parse(localStorage.getItem('connect.session'))")
    assert stored["gateway"] == gateway and stored["gpu"] == "T4" and stored["provider"] == "modal", stored
    print(f"  reload: reattached to {stored['session_id']}, same kernel ({again})")
    page.screenshot(path=OUT / "7-after-reload.png")
    assert not errors, errors
    return page


def lease(browser: Browser, url: str, token: tuple[str, str], gateway: str, fake: bool) -> None:
    """Session length: custom 150 min (721 is refused), the countdown, Extend +1 h, then +4 h until clamped at the ceiling."""
    context = browser.new_context(viewport={"width": 1100, "height": 760}, device_scale_factor=2)
    context.add_init_script(f"localStorage.setItem('connect.token.modal', JSON.stringify({{id: '{token[0]}', secret: '{token[1]}'}}))")
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    sid = lease_connect(page, url, token, gateway)
    lease_extend(page, sid, token, gateway)
    lease_shorter(sid, token, gateway)
    if fake:
        gateway_call(gateway, f"/dev/sessions/{sid}/expire", token, method="POST")
        page.wait_for_selector("connect-pill[data-phase=disconnected][data-failed]", timeout=30_000)
        open_menu(page)
        failure = page.locator(".connect-failure").inner_text()
        assert "session length ran out" in failure, failure
        assert gateway_call(gateway, f"/sessions/{sid}", token)["status"]["reason"] == "lease"
        page.screenshot(path=LEASE_OUT / "6-lease-ended.png")
        print(f"  lease ran out: {failure!r}")
        after = gateway_call(gateway, f"/sessions/{sid}/extend", token, method="POST", body={"until": time.time() + 3600})["status"]
        assert after["state"] == "ended" and after["reason"] == "lease", f"extend after the end should be a no-op: {after}"
        print("  extend after the end: 200, still ended (lease)")
        lease_booting(token, gateway)
    else:
        open_menu(page)
        page.locator(".connect-end").click()
        page.wait_for_selector("connect-pill[data-phase=disconnected]")
    assert not errors, errors
    context.close()


def lease_connect(page: Page, url: str, token: tuple[str, str], gateway: str) -> str:
    """The panel's session length: 90 min by default, 721 min refused, custom 150 min sent as lease_s. Returns the session id."""
    creates: list[str] = []
    page.on("request", lambda r: creates.append(r.url) if r.method == "POST" and r.url.rstrip("/").endswith("/sessions") else None)
    page.goto(url)
    open_menu(page)
    expect(page.locator("select[name=length]")).to_have_value("5400")
    expect(page.locator(".connect-ends")).to_contain_text("Ends at")
    page.screenshot(path=LEASE_OUT / "1-panel-default.png")

    # More than 12 h can't be sent: the form refuses 721 minutes.
    page.select_option("select[name=length]", "custom")
    page.fill("input[name=length-min]", "721")
    expect(page.locator(".connect-ends")).to_contain_text("12 h at most")
    page.locator(".connect-go").click()
    page.wait_for_timeout(300)
    assert not creates and page.locator("input[name=length-min]:invalid").count() == 1, "721 min was sent or not flagged"

    page.fill("input[name=length-min]", "150")
    expected = page.evaluate("[0, 60].map(d => new Date((Date.now() / 1000 + 9000 + d) * 1000).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit', hour12: false}))")
    hint = page.locator(".connect-ends").inner_text()
    assert any(f"Ends at {e}" in hint for e in expected), f"end-time hint {hint!r}, expected one of {expected}"
    page.screenshot(path=LEASE_OUT / "2-panel-custom.png")
    with page.expect_request(lambda r: r.method == "POST" and r.url.rstrip("/").endswith("/sessions")) as created:
        page.locator(".connect-go").click()
    sent = created.value.post_data_json
    assert sent["lease_s"] == 9000, sent
    page.wait_for_selector("connect-pill[data-phase=connected]", timeout=600_000)
    expect(page.locator(".connect-label")).to_have_text(re.compile(r"^T4 · 2h (29|30)m left$"))
    sid = page.evaluate("JSON.parse(localStorage.getItem('connect.session')).session_id")
    status = gateway_call(gateway, f"/sessions/{sid}", token)["status"]
    assert round(status["lease_until"] - status["started_at"]) == 9000, status
    print(f"  lease: custom 150 min sent as lease_s=9000, hint {hint!r}, pill {page.locator('.connect-label').inner_text()!r}")
    return str(sid)


def lease_extend(page: Page, sid: str, token: tuple[str, str], gateway: str) -> None:
    """Extend +1 h, then +4 h until the gateway clamps the lease at its ceiling (start + 12 h)."""
    open_menu(page)
    expect(page.locator(".connect-lease")).to_contain_text(re.compile(r"2h (29|30)m left"))
    page.screenshot(path=LEASE_OUT / "3-menu.png")
    page.locator(".connect-extend-open").click()
    page.select_option("select[name=extend-by]", "3600")
    page.screenshot(path=LEASE_OUT / "4-menu-extend.png")
    extends: list[dict[str, Any]] = []

    def extend_once() -> dict[str, Any]:
        with page.expect_response(lambda r: r.request.method == "POST" and r.url.endswith("/extend")) as response:
            page.locator(".connect-extend-go").click()
        assert response.value.ok, response.value.text()
        extends.append(response.value.request.post_data_json)
        expect(page.locator(".connect-extend-result")).to_contain_text("Now ends")
        got: dict[str, Any] = gateway_call(gateway, f"/sessions/{sid}", token)["status"]
        return got

    extended = extend_once()
    assert round(extended["lease_until"] - extended["started_at"]) == 9000 + 3600, extended
    assert abs(extends[0]["until"] - extended["lease_until"]) < 1, (extends, extended)
    expect(page.locator(".connect-label")).to_have_text(re.compile(r"^T4 · 3h (29|30)m left$"))
    expect(page.locator(".connect-lease")).to_contain_text(re.compile(r"3h (29|30)m left"))
    print(f"  extend +1 h: lease now {round((extended['lease_until'] - extended['started_at']) / 60)} min after start")

    # +4 h, +4 h, +4 h: the third asks past the ceiling (start + 12 h) and is clamped to it.
    for _ in range(3):
        if page.locator(".connect-extend").is_hidden():
            page.locator(".connect-extend-open").click()
        page.select_option("select[name=extend-by]", str(4 * 3600))
        clamped = extend_once()
    assert extends[-1]["until"] > clamped["ceiling"], f"the last extend should have asked past the ceiling: {extends[-1]} vs {clamped}"
    assert clamped["lease_until"] == clamped["ceiling"] == clamped["started_at"] + 12 * 3600, clamped
    expect(page.locator(".connect-extend-result")).to_contain_text("the 12 h limit")
    expect(page.locator(".connect-lease")).to_contain_text("at the 12 h limit")
    expect(page.locator(".connect-extend-open")).to_be_disabled()
    expect(page.locator(".connect-label")).to_have_text(re.compile(r"^T4 · 11h (59|60)m left$"))
    page.screenshot(path=LEASE_OUT / "5-menu-at-ceiling.png")
    print(f"  extend clamped: asked {extends[-1]['until'] - clamped['started_at']:.0f} s after start, got the ceiling (43200 s)")
    page.keyboard.press("Escape")


def lease_shorter(sid: str, token: tuple[str, str], gateway: str) -> None:
    """An until before lease_until (here: a minute after the start) never cuts the lease: 200, the status unchanged."""
    before = gateway_call(gateway, f"/sessions/{sid}", token)["status"]
    after = gateway_call(gateway, f"/sessions/{sid}/extend", token, method="POST", body={"until": before["started_at"] + 60})["status"]
    assert after["state"] == "running" and after["lease_until"] == before["lease_until"], f"a shorter extend moved the lease: {before} -> {after}"
    print(f"  shorter extend: 200, lease_until unchanged ({after['lease_until'] - after['started_at']:.0f} s after start)")


def lease_booting(token: tuple[str, str], gateway: str) -> None:
    """(fake) Extend while the session boots: 409, as the relay. Then end it."""
    req = Request(f"{gateway}/sessions", data=json.dumps({"provider": "modal", "token": {"id": token[0], "secret": token[1]}, "gpu": None}).encode(),
                  method="POST", headers={"Content-Type": "application/json"})  # fmt: skip
    with urlopen(req, timeout=10) as r:
        sid = json.load(r)["session_id"]
    try:
        gateway_call(gateway, f"/sessions/{sid}/extend", token, method="POST", body={"until": time.time() + 3600})
        raise AssertionError("extend while booting should be 409")
    except HTTPError as e:
        assert e.code == 409, f"extend while booting: {e.code} {e.read()!r}"
    finally:
        gateway_call(gateway, f"/sessions/{sid}/end", token, method="POST")
    print("  extend while booting: 409")


def ended_elsewhere(browser: Browser, url: str, token: tuple[str, str], gateway: str) -> None:
    """A status without lease_until is a gateway error the page names; a session ended outside the page says so."""
    context = browser.new_context(viewport={"width": 1100, "height": 760}, device_scale_factor=2)
    context.add_init_script(f"localStorage.setItem('connect.token.modal', JSON.stringify({{id: '{token[0]}', secret: '{token[1]}'}}))")
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(url)
    open_menu(page)
    page.locator(".connect-go").click()
    page.wait_for_selector("connect-pill[data-phase=connected]", timeout=600_000)
    sid = page.evaluate("JSON.parse(localStorage.getItem('connect.session')).session_id")

    # Reattach (reload) against a gateway that leaves lease_until out: no guessing from deadline.
    def strip(route: Route) -> None:
        response = route.fetch()
        body = response.json()
        del body["status"]["lease_until"]
        route.fulfill(response=response, json=body)

    pattern = re.compile(rf"/sessions/{re.escape(sid)}$")
    page.route(pattern, strip)
    page.reload()
    page.wait_for_selector("connect-pill[data-phase=disconnected][data-failed]", timeout=30_000)
    open_menu(page)
    failure = page.locator(".connect-failure").inner_text()
    assert "lease_until" in failure and "gateway" in failure, failure
    page.screenshot(path=LEASE_OUT / "7-no-lease-until.png")
    print(f"  status without lease_until: {failure!r}")
    page.unroute(pattern)

    page.reload()  # the session still runs: a real gateway reattaches
    page.wait_for_selector("connect-pill[data-phase=connected]", timeout=60_000)
    gateway_call(gateway, f"/sessions/{sid}/end", token, method="POST")  # as another tab's Disconnect, or a box release
    page.wait_for_selector("connect-pill[data-phase=disconnected][data-failed]", timeout=30_000)
    expect(page.locator(".connect-label")).to_have_text("Connect")
    expect(page.locator(".connect-announce")).to_have_text(re.compile(r"^Disconnected: the session was stopped outside this page"))
    open_menu(page)
    failure = page.locator(".connect-failure").inner_text()
    assert "stopped outside this page" in failure, failure
    page.screenshot(path=LEASE_OUT / "8-stopped-elsewhere.png")
    print(f"  ended outside the page: {failure!r}")
    assert not errors, errors
    context.close()


def wind_down(page: Page) -> None:
    open_menu(page)
    page.screenshot(path=OUT / "8-menu.png")
    page.locator(".connect-end").click()
    page.wait_for_selector("connect-pill[data-phase=disconnected]")
    expect(page.locator("scratch-cell .run")).to_be_disabled()
    assert page.evaluate("localStorage.getItem('connect.session')") is None
    open_menu(page)
    mask = page.locator(".connect-token-mask").inner_text()
    assert "…" in mask and FAKE_TOKEN[1] not in page.content(), mask
    page.screenshot(path=OUT / "9-disconnected-token-saved.png")
    page.locator(".connect-forget").click()
    expect(page.locator("input[name=token-id]")).to_be_visible()
    assert page.evaluate("localStorage.getItem('connect.token.modal')") is None
    print(f"  disconnect + sign out: token was shown as {mask!r}, now forgotten")
    page.keyboard.press("Escape")


def phone_and_dark(browser: Browser, url: str, token: tuple[str, str]) -> None:
    """Connected at phone width (dark): no sideways scroll, pill/panel/drawer fit."""
    context = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=3, is_mobile=True, has_touch=True, color_scheme="dark")
    context.add_init_script(f"localStorage.setItem('connect.token.modal', JSON.stringify({{id: '{token[0]}', secret: '{token[1]}'}}))")
    page = context.new_page()
    page.goto(url)
    page.locator(".connect-pill").click()
    page.screenshot(path=OUT / "phone-panel-dark.png")
    page.locator(".connect-go").click()
    page.wait_for_selector("connect-pill[data-phase=connected]", timeout=600_000)
    page.locator("scratch-cell").scroll_into_view_if_needed()
    run_cell(page)
    overflow = page.evaluate("document.documentElement.scrollWidth - innerWidth")
    assert overflow <= 0, f"phone: page scrolls sideways by {overflow}px"
    page.screenshot(path=OUT / "phone-connected-dark.png")
    page.locator(".connect-pill").click()
    page.screenshot(path=LEASE_OUT / "phone-menu-dark.png")
    page.locator(".connect-menu .connect-details").click()
    page.wait_for_timeout(400)
    page.screenshot(path=OUT / "phone-drawer-dark.png")
    page.keyboard.press("Escape")
    page.locator(".connect-pill").click()
    page.locator(".connect-end").click()
    page.wait_for_selector("connect-pill[data-phase=disconnected]")
    print("  phone (dark): connected, ran, drawer, no sideways scroll")
    context.close()


def axe(browser: Browser, url: str, token: tuple[str, str]) -> None:
    """axe on the connected page: panel (session menu) open, then the drawer with a full log, every theme x scheme."""
    found = 0
    for theme in ("classic", "paper"):
        for scheme in ("light", "dark"):
            context = browser.new_context(viewport={"width": 1000, "height": 800}, color_scheme=scheme)
            context.add_init_script(f"localStorage.setItem('blogs.settings', JSON.stringify({{theme: '{theme}'}}))")
            page = context.new_page()
            page.goto(url)
            page.locator(".connect-pill").click()
            if page.locator("input[name=token-id]").is_visible():
                page.fill("input[name=token-id]", token[0])
                page.fill("input[name=token-secret]", token[1])
            page.locator(".connect-go").click()
            page.wait_for_selector("connect-pill[data-phase=connected]", timeout=600_000)
            page.locator("scratch-cell").scroll_into_view_if_needed()
            run_cell(page)
            page.add_script_tag(url=AXE)
            page.locator(".connect-pill").click()
            menu = page.evaluate("axe.run(document, {resultTypes: ['violations']})")["violations"]
            page.locator(".connect-menu .connect-details").click()
            page.wait_for_timeout(300)
            drawer = page.evaluate("axe.run(document, {resultTypes: ['violations']})")["violations"]
            for where, violations in (("menu", menu), ("drawer", drawer)):
                for v in violations:
                    print(f"  axe {theme} {scheme} {where}: [{v['impact']}] {v['id']}: {v['help']} -> {[n['target'] for n in v['nodes'][:3]]}")
                found += len(violations)
            page.keyboard.press("Escape")
            page.locator(".connect-pill").click()
            page.locator(".connect-end").click()
            page.wait_for_selector("connect-pill[data-phase=disconnected]")
            context.close()
    assert found == 0, f"{found} axe violation type(s) with Connect open"
    print("  axe: connected page with the menu and the drawer open: clean in classic/paper x light/dark")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gateway", help="a running gateway's URL (default: start connect_dev.py)")
    ap.add_argument("--gateway-port", type=int, default=8791)
    ap.add_argument("--page-port", type=int, default=8012)
    ap.add_argument("--slow-mo", type=int, default=0, help="ms between browser actions (a watchable video: 250)")
    args = ap.parse_args()

    shutil.rmtree(OUT, ignore_errors=True)
    shutil.rmtree(LEASE_OUT, ignore_errors=True)
    (OUT / "video").mkdir(parents=True)
    LEASE_OUT.mkdir(parents=True)
    subprocess.run(["uv", "run", "build_page.py", "dl/neural-nets.md"], cwd=HERE, check=True, stdout=subprocess.DEVNULL)
    fake = None if args.gateway else start_fake(args.gateway_port)
    gateway = args.gateway or f"http://localhost:{args.gateway_port}"
    token = (os.environ["MODAL_TOKEN_ID"], os.environ["MODAL_TOKEN_SECRET"]) if args.gateway else FAKE_TOKEN
    server = serve_dist(args.page_port)
    url = f"http://localhost:{args.page_port}/neural-nets/?gateway={gateway}"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=CHROME, slow_mo=args.slow_mo)
            if fake is not None:
                bad_token(browser, url)
            context = browser.new_context(viewport={"width": 1280, "height": 800}, record_video_dir=OUT / "video",
                                          record_video_size={"width": 1280, "height": 800})  # fmt: skip
            page = story(context, url, token, gateway)
            wind_down(page)
            page.wait_for_timeout(800)
            context.close()
            video = page.video
            assert video is not None
            webm = OUT / "connect.webm"
            Path(video.path()).rename(webm)
            lease(browser, url, token, gateway, fake is not None)
            ended_elsewhere(browser, url, token, gateway)
            phone_and_dark(browser, url, token)
            axe(browser, url, token)
            browser.close()
    finally:
        server.shutdown()
        if fake is not None:
            fake.terminate()
            fake.wait(10)
    if shutil.which("ffmpeg"):
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", webm, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", OUT / "connect.mp4"], check=True)
    shutil.rmtree(OUT / "video", ignore_errors=True)
    print(f"ok: {OUT}/ ({', '.join(sorted(p.name for p in OUT.iterdir()))})")
    print(f"ok: {LEASE_OUT}/ ({', '.join(sorted(p.name for p in LEASE_OUT.iterdir()))})")


if __name__ == "__main__":
    main()
