"""Drive Connect end to end in headless Chromium; video + screenshots in .evidence/verify_connect/ (gitignored).

    uv run --with playwright verify_connect.py                       # fake gateway (connect_dev.py), started here
    uv run --with playwright verify_connect.py --gateway URL         # a running gateway instead (the real relay);
                                                                     #   token from MODAL_TOKEN_ID / MODAL_TOKEN_SECRET

Builds dl/neural-nets.md and serves dist/ itself. The story (recorded as connect.webm, and .mp4 if ffmpeg is there):
a bad token fails with a reason (not recorded); then paste a token, pick T4, connect with the Details drawer open,
run the nvidia-smi scratch cell, Stop a long cell, reload (the session and its kernel carry over, no new POST),
Disconnect, Sign out. Also: phone width, dark mode, and axe on the connected page with the panel and drawer open.
"""

from __future__ import annotations

import argparse
import functools
import glob
import os
import shutil
import subprocess
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import Browser, BrowserContext, Page, expect, sync_playwright

HERE = Path(__file__).parent
OUT = HERE / ".evidence" / "verify_connect"
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
    posts: list[str] = []
    page.on("request", lambda r: posts.append(r.url) if r.method == "POST" and r.url.rstrip("/").endswith("/sessions") else None)
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
    expect(page.locator(".connect-label")).to_have_text("T4 · <1m")
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
    args = ap.parse_args()

    shutil.rmtree(OUT, ignore_errors=True)
    (OUT / "video").mkdir(parents=True)
    subprocess.run(["uv", "run", "build_page.py", "dl/neural-nets.md"], cwd=HERE, check=True, stdout=subprocess.DEVNULL)
    fake = None if args.gateway else start_fake(args.gateway_port)
    gateway = args.gateway or f"http://localhost:{args.gateway_port}"
    token = (os.environ["MODAL_TOKEN_ID"], os.environ["MODAL_TOKEN_SECRET"]) if args.gateway else FAKE_TOKEN
    server = serve_dist(args.page_port)
    url = f"http://localhost:{args.page_port}/neural-nets/?gateway={gateway}"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=CHROME)
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


if __name__ == "__main__":
    main()
