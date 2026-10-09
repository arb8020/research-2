"""<nn-fit> remote backend, end to end: the built page in headless Chromium, training on a local Jupyter kernel.

    uv run build_page.py dl/neural-nets.md
    uv run --with playwright --with jupyter_server --with ipykernel python web/embeds/nn-fit/remote_e2e.py

Starts a Jupyter server (torch from this project, CPU) and a static server for dist/, then drives the page. The
page's Connect client doesn't exist on this branch yet, so the test publishes a RemoteRunner itself (JUPYTER_RUNNER
below: a minimal Jupyter kernel client), the same way the Connect client will (web/remote-runner.ts).
Writes screenshots and a video to .evidence/nn-fit-remote/ (gitignored). Exits 1 on the first failed check.
"""

import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from playwright.sync_api import Locator, Page, sync_playwright

BLOGS = Path(__file__).resolve().parents[3]
EVIDENCE = BLOGS / ".evidence" / "nn-fit-remote"
SERVER_START_SECONDS = 60  # jupyter_server's first start (kernel specs, extensions) can take a while
RUN_SECONDS = 2.0  # how long the Stop case lets a remote run train

# A RemoteRunner over a Jupyter kernel: REST to start/interrupt it, its websocket channel to execute code.
JUPYTER_RUNNER = """
async ({ base, token, label }) => {
  const headers = { Authorization: `token ${token}`, "Content-Type": "application/json" };
  const kernel = await (await fetch(`${base}/api/kernels`, { method: "POST", headers, body: JSON.stringify({ name: "python3" }) })).json();
  const ws = new WebSocket(`${base.replace("http", "ws")}/api/kernels/${kernel.id}/channels?token=${token}`);
  await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
  const session = crypto.randomUUID();
  const runs = new Map(); // execute_request msg_id -> { onStdout, resolve, error }
  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    const run = runs.get(msg.parent_header?.msg_id);
    if (!run || msg.channel !== "iopub") return;
    const type = msg.header.msg_type;
    if (type === "stream" && msg.content.name === "stdout") run.onStdout(msg.content.text);
    if (type === "error") run.error = msg.content.traceback.join("\\n").replace(/\\x1b\\[[0-9;]*m/g, "");
    if (type === "status" && msg.content.execution_state === "idle") {
      runs.delete(msg.parent_header.msg_id);
      run.resolve(run.error === null ? { ok: true } : { ok: false, error: run.error });
    }
  };
  const runner = {
    label,
    run(code, onStdout) {
      return new Promise((resolve) => {
        const msg_id = crypto.randomUUID();
        runs.set(msg_id, { onStdout, resolve, error: null });
        ws.send(JSON.stringify({
          header: { msg_id, session, username: "e2e", msg_type: "execute_request", version: "5.3", date: new Date().toISOString() },
          parent_header: {}, metadata: {}, channel: "shell",
          content: { code, silent: false, store_history: false, user_expressions: {}, allow_stdin: false, stop_on_error: true },
        }));
      });
    },
    async interrupt() { await fetch(`${base}/api/kernels/${kernel.id}/interrupt`, { method: "POST", headers }); },
  };
  window.blogsRemoteRunner = runner;
  window.dispatchEvent(new Event("remote-runner-change"));
}
"""

# A runner whose code always fails, as a kernel reports a Python exception.
FAILING_RUNNER = """
() => {
  window.blogsRemoteRunner = {
    label: "failing kernel",
    run: async () => ({ ok: false, error: "Traceback (most recent call last):\\n  ...\\nValueError: config: lr = 99 is outside 0..10" }),
    interrupt: async () => {},
  };
  window.dispatchEvent(new Event("remote-runner-change"));
}
"""

DISCONNECT = "() => { window.blogsRemoteRunner = null; window.dispatchEvent(new Event('remote-runner-change')); }"
STATS = "document.querySelector('nn-fit').stats"


def check(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"FAIL {message}")
    print(f"ok   {message}")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for_http(url: str, proc: subprocess.Popen, seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise SystemExit(f"FAIL server for {url} exited with {proc.returncode}")
        try:
            with urlopen(url, timeout=2):
                return
        except (URLError, ConnectionError):
            time.sleep(0.2)
    raise SystemExit(f"FAIL {url} not up after {seconds} s")


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
    page.wait_for_function(f"{STATS}.steps > 0 && {STATS}.device.startsWith('cpu')", timeout=60_000)
    check(is_disabled(page.locator(nn(page, "fieldset.network"))), "remote run: the network controls are disabled while it trains")
    page.wait_for_timeout(RUN_SECONDS * 1000)
    mid = page.evaluate(STATS)
    page.locator("nn-fit").screenshot(path=EVIDENCE / "wave-remote-running.png")
    page.click(nn(page, "button.train"))  # Stop -> kernel interrupt
    after = stopped(page)
    print(f"  wave: loss {before['loss']:.3g} -> {mid['loss']:.3g} (step {mid['steps']}) -> {after['loss']:.3g} at step {after['steps']} on {after['device']}")
    check(mid["device"] == "cpu · local kernel", f"remote run: reports where it ran ({mid['device']!r})")
    check(after["loss"] < before["loss"] / 10, "remote run: the loss fell by 10x or more")
    check(after["steps"] >= mid["steps"] and after["device"] == mid["device"], "stop: the final state is from the remote run")
    status = page.locator("nn-fit [role=status]").text_content() or ""
    check("Remote run stopped: stopped" in status, f"stop: announced ({status!r})")
    text = page.locator(nn(page, ".usage")).text_content() or ""
    check("on cpu · local kernel" in text, f"readout names the backend ({text!r})")
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


def failure_and_disconnect(page: Page) -> None:
    page.evaluate(FAILING_RUNNER)
    page.click(nn(page, "button.reset"))
    page.select_option(nn(page, "select.backend"), "remote")
    page.click(nn(page, "button.train"))
    stopped(page)
    need = page.locator(nn(page, "p.need")).text_content() or ""
    check("Remote run failed: ValueError: config: lr = 99" in need, f"a failing run says why under the plot ({need!r})")
    check(page.evaluate(STATS)["steps"] == 0, "a failing run leaves the weights alone")
    page.evaluate(DISCONNECT)
    option = page.locator(nn(page, "select.backend option[value=remote]"))
    check(is_disabled(option) and (option.text_content() or "") == "remote (connect first)", "disconnect: remote is offered only when connected")
    check(page.evaluate(STATS)["backend"] == "browser", "disconnect: the widget falls back to the browser")


def drive(page_url: str, jupyter_url: str, token: str) -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(viewport={"width": 900, "height": 1100}, record_video_dir=str(EVIDENCE), record_video_size={"width": 900, "height": 1100})
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(page_url)
        page.locator("nn-fit").scroll_into_view_if_needed()
        option = page.locator(nn(page, "select.backend option[value=remote]"))
        check(is_disabled(option), "no session: remote is disabled")
        page.evaluate(JUPYTER_RUNNER, {"base": jupyter_url, "token": token, "label": "local kernel"})
        check(not is_disabled(option) and option.text_content() == "remote: local kernel", "session published: remote is offered")
        curve_run(page)
        spiral_run(page)
        failure_and_disconnect(page)
        check(errors == [], f"no page errors ({errors})")
        video = page.video
        context.close()
        browser.close()
        if video is not None:
            print(f"  video: {video.path()}")


def main() -> None:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    dist = BLOGS / "dist"
    if not (dist / "neural-nets" / "index.html").exists():
        raise SystemExit("build the page first: uv run build_page.py dl/neural-nets.md")
    token = secrets.token_hex(16)
    jport, sport = free_port(), free_port()
    env = {**os.environ, "JUPYTER_RUNTIME_DIR": str(EVIDENCE / "jupyter-runtime")}  # keep its files out of ~
    jupyter = subprocess.Popen(
        [sys.executable, "-m", "jupyter_server", "--no-browser", f"--port={jport}", f"--IdentityProvider.token={token}",
         "--ServerApp.allow_origin=*", "--ServerApp.disable_check_xsrf=True", f"--ServerApp.root_dir={EVIDENCE}"],
        cwd=BLOGS, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )  # fmt: skip
    static = subprocess.Popen([sys.executable, "-m", "http.server", str(sport), "-d", str(dist)],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # fmt: skip
    try:
        jupyter_url = f"http://127.0.0.1:{jport}"
        wait_for_http(f"{jupyter_url}/api/status?token={token}", jupyter, SERVER_START_SECONDS)
        wait_for_http(f"http://127.0.0.1:{sport}/neural-nets/", static, SERVER_START_SECONDS)
        drive(f"http://127.0.0.1:{sport}/neural-nets/", jupyter_url, token)
    finally:
        for proc in (jupyter, static):
            proc.terminate()
            proc.wait(timeout=20)


if __name__ == "__main__":
    main()
