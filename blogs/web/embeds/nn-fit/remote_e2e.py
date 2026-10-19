"""<nn-fit> remote backend, end to end: the built page in headless Chromium, Connect to a local fake gateway
(connect_dev.py, its kernel a local Jupyter with torch, CPU), then train <nn-fit> remotely on it.

    uv run --with playwright python web/embeds/nn-fit/remote_e2e.py
    uv run --with playwright python web/embeds/nn-fit/remote_e2e.py --gateway http://localhost:8790   # a running
        gateway instead (the real relay, box/examples/notebook-gateway/relay.py); token from MODAL_TOKEN_ID / MODAL_TOKEN_SECRET; T4

Cases: a curve run with Stop, a spiral run to its step budget, the grokking dataset (Stop, then continue: on a
real GPU until test accuracy passes 95%, on the fake gateway's CPU for 1000 steps), a disconnect mid-run.
--case grok runs only the grokking case.

Builds dl/neural-nets.md, starts connect_dev.py (with torch added to its env, so the kernel can import it) and a
static server for dist/, then drives the page through the real Connect UI and kernel client (web/connect/).
Writes screenshots and a video to .evidence/nn-fit-remote/ (gitignored). Exits 1 on the first failed check.
"""

import argparse
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from playwright.sync_api import Locator, Page, sync_playwright

BLOGS = Path(__file__).resolve().parents[3]
EVIDENCE = BLOGS / ".evidence" / "nn-fit-remote"
SERVER_START_SECONDS = 120  # connect_dev.py's first start installs jupyter_server (+ torch from uv's cache)
CONNECT_SECONDS = 120  # the fake boot, then a local Jupyter Server and kernel
RUN_SECONDS = 2.0  # how long the Stop case lets a remote run train
FAKE_TOKEN = ("ak-nn-fit-remote-e2e", "as-nn-fit-remote-e2e")  # connect_dev.py boots any id starting "ak-"
STATS = "document.querySelector('nn-fit').stats"
FAKE_DEVICE = "cpu (remote)"  # connect_dev.py's kernel: torch on this computer's CPU
GPU_DEVICE = "cuda · Tesla T4"  # a real gateway: a Modal T4
GATEWAY_CONNECT_SECONDS = 600  # a real gateway: a workspace's first connect builds the image (~90 s seen)
GROK_FIRST_STEPS = 300  # the grokking case trains this far, stops, then continues
GROK_FAKE_STEPS = 1000  # the fake gateway (CPU, ~40 steps/s) trains this far: fits, doesn't grok
GROK_TIME_BUDGET = "6"  # slider stop 6 = 60 s: a T4 groks in ~20-30 s (test accuracy past 95%)


class Run:
    """What differs between the fake gateway and a real one: the token, how long Connect takes, where it trains."""

    token: tuple[str, str] = FAKE_TOKEN
    connect_seconds: float = CONNECT_SECONDS
    device: str = FAKE_DEVICE


def check(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"FAIL {message}")
    print(f"ok   {message}")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for_http(url: str, proc: subprocess.Popen, seconds: float) -> None:
    """Until `url` answers at all (an HTTP error status counts: the server is up)."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise SystemExit(f"FAIL server for {url} exited with {proc.returncode}")
        try:
            with urlopen(url, timeout=2):
                return
        except HTTPError:
            return
        except (URLError, ConnectionError):
            time.sleep(0.2)
    raise SystemExit(f"FAIL {url} not up after {seconds} s")


def connect(page: Page) -> None:
    """Connect through the header pill, as a reader would: token, GPU, go; wait for the kernel."""
    page.locator(".connect-pill").click()
    page.fill("input[name=token-id]", Run.token[0])
    page.fill("input[name=token-secret]", Run.token[1])
    page.select_option("select[name=gpu]", "T4")
    page.locator(".connect-go").click()
    page.wait_for_selector("connect-pill[data-phase=connected]", timeout=Run.connect_seconds * 1000)
    page.keyboard.press("Escape")


def is_disabled(locator: Locator) -> bool:
    return locator.evaluate("(el) => el.disabled")  # Locator.is_disabled() sees neither a disabled <option> nor <fieldset>


def nn(page: Page, part: str) -> str:
    return f"nn-fit >> {part}"


def stopped(page: Page) -> dict:
    page.wait_for_function(f"!{STATS}.training", timeout=30_000)
    return page.evaluate(STATS)


def curve_run(page: Page) -> None:
    """The default widget (wave, 1-12-12-1): Stop mid-run keeps the remote's weights; the browser continues them."""
    before = page.evaluate(STATS)
    page.select_option(nn(page, "select.backend"), "remote")
    page.click(nn(page, "button.train"))
    page.wait_for_function(f"{STATS}.steps > 0 && {STATS}.device === {Run.device!r}", timeout=60_000)
    check(is_disabled(page.locator(nn(page, "fieldset.network"))), "remote run: the network controls are disabled while it trains")
    page.wait_for_timeout(RUN_SECONDS * 1000)
    mid = page.evaluate(STATS)
    page.locator("nn-fit").screenshot(path=EVIDENCE / "wave-remote-running.png")
    page.click(nn(page, "button.train"))  # Stop -> kernel interrupt
    after = stopped(page)
    print(f"  wave: loss {before['loss']:.3g} -> {mid['loss']:.3g} (step {mid['steps']}) -> {after['loss']:.3g} at step {after['steps']} on {after['device']}")
    check(mid["device"] == Run.device, f"remote run: reports where it ran ({mid['device']!r})")
    check(after["loss"] < before["loss"] / 10, "remote run: the loss fell by 10x or more")
    check(after["steps"] >= mid["steps"] and after["device"] == mid["device"], "stop: the final state is from the remote run")
    status = page.locator("nn-fit [role=status]").text_content() or ""
    check("Remote run stopped: stopped" in status, f"stop: announced ({status!r})")
    text = page.locator(nn(page, ".usage")).text_content() or ""
    check(f"on {Run.device}" in text, f"readout names the backend ({text!r})")
    page.locator("nn-fit").screenshot(path=EVIDENCE / "wave-remote-stopped.png")

    # Back in the browser, training continues from the remote's weights (not from scratch).
    page.select_option(nn(page, "select.backend"), "browser")
    page.click(nn(page, "button.train"))
    page.wait_for_function(f"{STATS}.steps >= {after['steps'] + 200}", timeout=30_000)
    page.click(nn(page, "button.train"))
    cont = page.evaluate(STATS)
    check(cont["device"] == "this browser" and cont["loss"] < before["loss"] / 10,
          f"browser continues from the remote weights: step {cont['steps']}, loss {cont['loss']:.3g}")


def spiral_run(page: Page) -> None:
    """The spiral with a step budget: the run ends by itself; the heatmap comes from the remote's predictions."""
    page.select_option(nn(page, "select.dataset"), "spiral")
    page.click(nn(page, "button.reset"))
    page.locator(nn(page, "input.step-budget")).evaluate("(el) => { el.value = '1'; el.dispatchEvent(new Event('input')); }")  # 1000 steps
    page.select_option(nn(page, "select.backend"), "remote")
    page.click(nn(page, "button.train"))
    page.wait_for_function(f"{STATS}.steps > 0", timeout=60_000)
    page.locator("nn-fit").screenshot(path=EVIDENCE / "spiral-remote-running.png")
    end = stopped(page)
    print(f"  spiral: {end['steps']} steps, loss {end['loss']:.3g}, train {end['accuracy']:.1%}, held-out {end['heldOutAccuracy']:.1%} on {end['device']}")
    check(end["steps"] == 1000, "spiral: the step budget stopped the remote run at 1000 steps")
    check(end["accuracy"] > 0.9, "spiral: train accuracy above 90% (browser evaluation of the remote's final weights)")
    status = page.locator("nn-fit [role=status]").text_content() or ""
    check("step budget used up" in status, f"spiral: announced ({status!r})")
    page.locator("nn-fit").screenshot(path=EVIDENCE / "spiral-remote-done.png")


def slider(page: Page, cls: str, stop: str) -> None:
    page.locator(nn(page, f"input.{cls}")).evaluate(f"(el) => {{ el.value = '{stop}'; el.dispatchEvent(new Event('input')); }}")


def grok_run(page: Page, gpu: bool) -> None:
    """Grokking (remote only): Stop keeps the run on the kernel, Train continues it; on a GPU it groks."""
    page.select_option(nn(page, "select.dataset"), "grok")
    slider(page, "step-budget", "7")  # off (the spiral case set 1000 steps)
    slider(page, "time-budget", "7")
    check(page.locator(nn(page, "fieldset.network")).is_hidden(), "grok: the MLP's network controls are hidden")
    check(is_disabled(page.locator(nn(page, "select.backend"))) and page.locator(nn(page, "select.backend")).input_value() == "remote",
          "grok: runs remotely, and only there")  # fmt: skip
    page.click(nn(page, "button.train"))
    page.wait_for_function(f"{STATS}.steps >= {GROK_FIRST_STEPS} && {STATS}.device === {Run.device!r}", timeout=120_000)
    page.click(nn(page, "button.train"))  # Stop
    first = stopped(page)
    print(f"  grok: stopped at step {first['steps']}: train {first['accuracy']:.1%}, test {first['heldOutAccuracy']:.1%} on {first['device']}")
    status = page.locator("nn-fit [role=status]").text_content() or ""
    check("Remote run stopped: stopped" in status, f"grok stop: announced ({status!r})")
    check(first["grok"]["points"] > 10 and first["steps"] >= GROK_FIRST_STEPS, f"grok: {first['grok']['points']} points plotted")
    page.locator("nn-fit").screenshot(path=EVIDENCE / "grok-stopped.png")

    if gpu:
        slider(page, "time-budget", GROK_TIME_BUDGET)
    else:
        slider(page, "step-budget", "1")  # 1000 steps
    page.click(nn(page, "button.train"))  # continues the same run
    page.wait_for_function(f"{STATS}.training && {STATS}.steps > {first['steps']}", timeout=60_000)
    end = page.wait_for_function(f"!{STATS}.training && {STATS}", timeout=180_000).json_value()
    g = end["grok"]
    print(f"  grok: {end['steps']} steps in {end['seconds']:.1f} s ({end['steps'] / end['seconds']:.0f} steps/s): train {end['accuracy']:.1%}, "
          f"test {end['heldOutAccuracy']:.1%}; test past 95% at {g['grokked']}")  # fmt: skip
    status = page.locator("nn-fit [role=status]").text_content() or ""
    budget = "time budget used up" if gpu else "step budget used up"
    check(f"Remote run stopped: {budget}" in status, f"grok: the budget ended it, not a failure ({status!r})")  # a 60 s run outlives 2 keepalives
    check(g["run"] == first["grok"]["run"] and end["steps"] > first["steps"], "grok: Train continued the stopped run (same run, more steps)")
    check(end["accuracy"] == 1.0, "grok: fits every training pair")
    if gpu:
        check(g["grokked"] is not None, f"grok: test accuracy passed 95% (at step {g['grokked'] and g['grokked']['step']})")
    else:
        check(end["steps"] == GROK_FAKE_STEPS, f"grok: the step budget stopped it at {GROK_FAKE_STEPS}")
    text = page.locator(nn(page, ".usage")).text_content() or ""
    check(f"on {Run.device}" in text, f"grok readout names the backend ({text!r})")
    page.locator("nn-fit").screenshot(path=EVIDENCE / "grok-done.png")
    # Back to where the next case expects the widget: spiral, budgets off.
    slider(page, "time-budget", "7")
    slider(page, "step-budget", "7")
    page.select_option(nn(page, "select.dataset"), "spiral")


def disconnect_mid_run(page: Page) -> None:
    """Disconnect while a remote run trains: the run fails with the reason, the weights stay, remote goes away."""
    page.click(nn(page, "button.reset"))
    page.locator(nn(page, "input.step-budget")).evaluate("(el) => { el.value = '7'; el.dispatchEvent(new Event('input')); }")  # off
    page.click(nn(page, "button.train"))
    page.wait_for_function(f"{STATS}.steps > 0", timeout=60_000)
    page.locator(".connect-pill").click()
    page.locator(".connect-end").click()
    end = stopped(page)
    need = page.locator(nn(page, "p.need")).text_content() or ""
    # The reason depends on which goes first, the page's detach or the gateway's kernel: "disconnected" or
    # "the connection to the kernel dropped".
    check(need.startswith("Remote run failed: ") and len(need) > len("Remote run failed: "), f"disconnect mid-run: the run fails and says why ({need!r})")
    check(end["steps"] == 0 and end["device"] == "this browser", "disconnect mid-run: the weights are left as they were")
    option = page.locator(nn(page, "select.backend option[value=remote]"))
    check(is_disabled(option) and (option.text_content() or "") == "remote (Connect first)", "disconnected: remote is offered only when connected")
    # The kernel can drop before the gateway has answered POST /end (a real one closes the machine first, ~2 s):
    # the fallback follows the session's phase, so wait for it rather than sample it.
    page.wait_for_function(f"{STATS}.backend === 'browser'", timeout=30_000)
    check(page.evaluate(STATS)["backend"] == "browser", "disconnected: the widget falls back to the browser")
    page.locator("nn-fit").screenshot(path=EVIDENCE / "disconnected-mid-run.png")


def drive(page_url: str, case: str) -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(viewport={"width": 900, "height": 1100}, record_video_dir=str(EVIDENCE / "video"),
                                      record_video_size={"width": 900, "height": 1100})  # fmt: skip
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(page_url)
        option = page.locator(nn(page, "select.backend option[value=remote]"))
        grok_option = page.locator(nn(page, "select.dataset option[value=grok]"))
        check(is_disabled(option), "not connected: remote is disabled")
        check(is_disabled(grok_option) and "Connect first" in (grok_option.text_content() or ""), "not connected: grokking is disabled, with a hint")
        connect(page)
        page.locator("nn-fit").scroll_into_view_if_needed()
        check(not is_disabled(option) and not is_disabled(grok_option), "connected: remote and grokking are offered")
        if case == "all":
            curve_run(page)
            spiral_run(page)
        grok_run(page, Run.device == GPU_DEVICE)
        if case == "all":
            disconnect_mid_run(page)
        else:
            page.locator(".connect-pill").click()
            page.locator(".connect-end").click()
        check(errors == [], f"no page errors ({errors})")
        video = page.video
        assert video is not None
        context.close()  # finishes the video file
        recorded = Path(video.path())
        browser.close()
    webm = EVIDENCE / "nn-fit-remote.webm"
    recorded.rename(webm)
    recorded.parent.rmdir()
    if shutil.which("ffmpeg"):
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", webm, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                        EVIDENCE / "nn-fit-remote.mp4"], check=True)  # fmt: skip
    print(f"ok: {EVIDENCE}/ ({', '.join(sorted(p.name for p in EVIDENCE.iterdir()))})")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gateway", help="a running gateway's URL (default: start connect_dev.py)")
    ap.add_argument("--case", choices=("all", "grok"), default="all", help="grok: only the grokking case")
    args = ap.parse_args()
    shutil.rmtree(EVIDENCE, ignore_errors=True)
    EVIDENCE.mkdir(parents=True)
    subprocess.run(["uv", "run", "build_page.py", "dl/neural-nets.md"], cwd=BLOGS, check=True, stdout=subprocess.DEVNULL)
    sport = free_port()
    procs = []
    if args.gateway:
        Run.token, Run.connect_seconds, Run.device = (os.environ["MODAL_TOKEN_ID"], os.environ["MODAL_TOKEN_SECRET"]), GATEWAY_CONNECT_SECONDS, GPU_DEVICE
        gateway_url = args.gateway.rstrip("/")
    else:
        gport = free_port()
        log = (EVIDENCE / "connect_dev.log").open("wb")
        procs.append(subprocess.Popen(["uv", "run", "--with", "torch", "connect_dev.py", "--port", str(gport), "--boot-delay", "0.2"],
                                      cwd=BLOGS, stdout=log, stderr=log))  # fmt: skip
        gateway_url = f"http://127.0.0.1:{gport}"
    static = subprocess.Popen([sys.executable, "-m", "http.server", str(sport), "-d", str(BLOGS / "dist")],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # fmt: skip
    procs.append(static)
    try:
        if not args.gateway:
            wait_for_http(f"{gateway_url}/sessions/none", procs[0], SERVER_START_SECONDS)
        wait_for_http(f"http://127.0.0.1:{sport}/neural-nets/", static, SERVER_START_SECONDS)
        drive(f"http://127.0.0.1:{sport}/neural-nets/?gateway={gateway_url}", args.case)
    finally:
        for proc in procs:
            proc.terminate()
            proc.wait(timeout=20)


if __name__ == "__main__":
    main()
