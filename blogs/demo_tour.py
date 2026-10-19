"""The morning demo: one continuous, real-time recording of the reader path on a real Modal T4.

    MODAL_TOKEN_ID=... MODAL_TOKEN_SECRET=... uv run --with playwright demo_tour.py --gateway http://localhost:8796

Needs a running gateway (the relay, box/gateway/relay.py). Builds dl/neural-nets.md, serves dist/ on a free port, and
records one 1280x800 video with a caption naming each step: Connect a T4 (Details drawer open while it boots), run the
nvidia-smi scratch cell, train <nn-fit>'s default wave on the GPU and Stop, train the grokking dataset until test
accuracy passes 95%, Disconnect. Writes to .evidence/demo-tour/ (gitignored): tour.webm, tour.mp4, tour-fast.mp4
(sped up), contact.png (a frame sheet). The helpers come from verify_connect.py and nn-fit/remote_e2e.py.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

from playwright.sync_api import Page, expect, sync_playwright

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE / "web" / "embeds" / "nn-fit"))
from remote_e2e import GPU_DEVICE, STATS, free_port, nn, slider, stopped  # noqa: E402  # isort: skip
from verify_connect import CHROME, open_menu, run_cell, serve_dist  # noqa: E402

OUT = HERE / ".evidence" / "demo-tour"
CONNECT_SECONDS = 600
GROK_SECONDS = 180
TIME_BUDGET_60S_STOP = "6"
BUDGET_OFF = "7"
SPEEDUP = 2.5
CONTACT_FRAMES = 8

OVERLAY = """
(text) => {
  let el = document.getElementById('demo-caption');
  if (!el) {
    el = document.createElement('div');
    el.id = 'demo-caption';
    Object.assign(el.style, {position: 'fixed', left: '16px', bottom: '16px', zIndex: 2147483647, padding: '6px 12px',
      font: '600 15px/1.3 system-ui, sans-serif', color: '#fff', background: 'rgba(20,20,28,.82)', borderRadius: '6px',
      pointerEvents: 'none', boxShadow: '0 2px 8px rgba(0,0,0,.25)'});
    document.body.appendChild(el);
    const style = document.createElement('style');
    style.textContent = 'input[name=token-id] { -webkit-text-security: disc; }';
    document.head.appendChild(style);
  }
  el.textContent = text;
}
"""


def caption(page: Page, text: str) -> None:
    page.evaluate(OVERLAY, text)
    print(f"  {text}")


def stats(page: Page) -> dict:
    return page.evaluate(STATS)


def tour(page: Page, token: tuple[str, str]) -> str:
    session_id = connect(page, token)
    nvidia_smi(page)
    wave(page)
    grok(page)
    disconnect(page)
    return session_id


def connect(page: Page, token: tuple[str, str]) -> str:
    caption(page, "The reader path: dl/neural-nets, nothing connected")
    expect(page.locator(".connect-label")).to_have_text("Connect")
    page.wait_for_timeout(2500)

    caption(page, "1. Connect a GPU: paste a Modal token, pick T4")
    open_menu(page)
    page.locator("input[name=token-id]").type(token[0], delay=15)
    page.locator("input[name=token-secret]").type(token[1], delay=15)
    page.select_option("select[name=gpu]", "T4")
    page.wait_for_timeout(1200)
    page.locator(".connect-go").click()
    expect(page.locator(".connect-label")).to_contain_text("connecting…")

    caption(page, "2. Booting a Modal T4: live boot log in the Details drawer")
    open_menu(page)
    page.locator(".connect-menu .connect-details").click()
    expect(page.locator(".connect-drawer")).to_be_visible()
    t0 = time.monotonic()
    page.wait_for_selector("connect-pill[data-phase=connected]", timeout=CONNECT_SECONDS * 1000)
    print(f"    connected in {time.monotonic() - t0:.0f} s: pill {page.locator('.connect-label').inner_text()!r}")
    caption(page, "2. Connected: ● T4")
    page.wait_for_timeout(2500)
    page.locator(".drawer-close").click()
    expect(page.locator(".connect-drawer")).to_be_hidden()
    session_id = page.evaluate("JSON.parse(localStorage.getItem('connect.session')).session_id")
    page.wait_for_timeout(1000)
    return session_id


def nvidia_smi(page: Page) -> None:
    caption(page, "3. !nvidia-smi in a scratch cell, on the connected GPU")
    page.locator("scratch-cell").scroll_into_view_if_needed()
    page.wait_for_timeout(1200)
    out = run_cell(page)
    assert "NVIDIA-SMI" in out and "Tesla T4" in out, out
    page.locator("scratch-cell .cell-out").scroll_into_view_if_needed()
    page.wait_for_timeout(5000)


def wave(page: Page) -> None:
    caption(page, "4. nn-fit: Run on remote, train the wave on the T4")
    page.locator("nn-fit").scroll_into_view_if_needed()
    page.wait_for_timeout(1200)
    slider(page, "step-budget", BUDGET_OFF)
    page.select_option(nn(page, "select.backend"), "remote")
    page.click(nn(page, "button.train"))
    page.wait_for_function(f"{STATS}.steps > 0 && {STATS}.device === {GPU_DEVICE!r}", timeout=60_000)
    page.wait_for_timeout(4000)
    usage = page.locator(nn(page, ".usage")).text_content() or ""
    assert f"on {GPU_DEVICE}" in usage, usage
    caption(page, "4. Stop: the weights come back to the page")
    if stats(page)["training"]:
        page.click(nn(page, "button.train"))
    end = stopped(page)
    print(f"    wave: {end['steps']} steps, loss {end['loss']:.3g} on {end['device']}")
    page.wait_for_timeout(2500)


def grok(page: Page) -> None:
    caption(page, "5. Grokking: a + b mod 113, a 1-layer transformer, trained until test accuracy passes 95%")
    page.select_option(nn(page, "select.dataset"), "grok")
    slider(page, "step-budget", BUDGET_OFF)
    slider(page, "time-budget", TIME_BUDGET_60S_STOP)
    page.locator("nn-fit").scroll_into_view_if_needed()
    page.wait_for_timeout(1500)
    page.click(nn(page, "button.train"))
    page.wait_for_function(f"{STATS}.grok.grokked !== null", timeout=GROK_SECONDS * 1000)
    g = stats(page)
    print(f"    grok: test past 95% at step {g['grok']['grokked']['step']} ({g['grok']['grokked']['seconds']:.1f} s) on {g['device']}")
    caption(page, f"5. Grokked: test accuracy past 95% at step {g['grok']['grokked']['step']} ({g['grok']['grokked']['seconds']:.0f} s on the T4)")
    page.wait_for_timeout(4000)
    if stats(page)["training"]:
        page.click(nn(page, "button.train"))
    stopped(page)
    page.wait_for_timeout(2000)


def disconnect(page: Page) -> None:
    caption(page, "6. Disconnect: the T4 shuts down")
    page.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")
    page.wait_for_timeout(1000)
    open_menu(page)
    page.wait_for_timeout(1000)
    page.locator(".connect-end").click()
    page.wait_for_selector("connect-pill[data-phase=disconnected]", timeout=60_000)
    page.wait_for_timeout(2500)


def session_status(gateway: str, session_id: str, token: tuple[str, str]) -> str:
    req = Request(f"{gateway}/sessions/{session_id}", headers={"X-Box-Token": f"{token[0]}:{token[1]}"})
    with urlopen(req, timeout=60) as r:
        return json.dumps(json.load(r).get("status"))


def end_left_session(page: Page, gateway: str, token: tuple[str, str]) -> None:
    stored = page.evaluate("localStorage.getItem('connect.session')")
    if stored is None:
        return
    session_id = json.loads(stored)["session_id"]
    req = Request(f"{gateway}/sessions/{session_id}/end", method="POST", headers={"X-Box-Token": f"{token[0]}:{token[1]}"})
    with urlopen(req, timeout=60) as r:
        print(f"  tour failed: ended session {session_id} ({r.status})")


def ffmpeg(*args: object) -> None:
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *map(str, args)], check=True)


def duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         check=True, capture_output=True, text=True).stdout  # fmt: skip
    return float(out)


def encode(webm: Path) -> None:
    mp4 = OUT / "tour.mp4"
    x264 = ("-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart")
    ffmpeg("-i", webm, *x264, mp4)
    ffmpeg("-i", webm, "-vf", f"setpts=PTS/{SPEEDUP}", "-an", *x264, OUT / "tour-fast.mp4")
    seconds = duration(mp4)
    every = seconds / CONTACT_FRAMES
    ffmpeg("-i", mp4, "-vf", f"fps=1/{every:.3f},scale=640:-1,tile=4x2:padding=4:color=white", "-frames:v", "1", OUT / "contact.png")
    print(f"  video {seconds:.0f} s (fast {seconds / SPEEDUP:.0f} s), contact sheet every {every:.0f} s")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gateway", required=True, help="a running gateway's URL (the relay)")
    ap.add_argument("--slow-mo", type=int, default=200, help="ms between browser actions")
    args = ap.parse_args()
    gateway = args.gateway.rstrip("/")
    token = (os.environ["MODAL_TOKEN_ID"], os.environ["MODAL_TOKEN_SECRET"])

    shutil.rmtree(OUT, ignore_errors=True)
    (OUT / "video").mkdir(parents=True)
    subprocess.run(["uv", "run", "build_page.py", "dl/neural-nets.md"], cwd=HERE, check=True, stdout=subprocess.DEVNULL)
    port = free_port()
    server = serve_dist(port)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=CHROME, slow_mo=args.slow_mo)
            context = browser.new_context(viewport={"width": 1280, "height": 800}, record_video_dir=OUT / "video",
                                          record_video_size={"width": 1280, "height": 800})  # fmt: skip
            page = context.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://localhost:{port}/neural-nets/?gateway={gateway}")
            try:
                session_id = tour(page, token)
            except BaseException:
                end_left_session(page, gateway, token)
                raise
            finally:
                video = page.video
                context.close()
                browser.close()
            assert video is not None
            webm = OUT / "tour.webm"
            Path(video.path()).rename(webm)
            assert not errors, errors
    finally:
        server.shutdown()
        shutil.rmtree(OUT / "video", ignore_errors=True)
    print(f"  session {session_id}: {session_status(gateway, session_id, token)}")
    encode(webm)
    print(f"ok: {OUT}/ ({', '.join(sorted(p.name for p in OUT.iterdir()))})")


if __name__ == "__main__":
    main()
