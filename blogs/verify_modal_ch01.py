"""The ch01 page on a real Modal T4 through box's relay: headless Chromium, the reader's path end to end.

    # 1. the relay (box at 42c05b12), in its own terminal; the reader's token goes in the page, not here
    git archive 42c05b12 box pyproject.toml observe | tar -x -C /tmp/box-42c05b12   # from the research-2 checkout
    cd /tmp/box-42c05b12/box && uv sync --extra dev
    uv run python -m box.gateway.relay --port 8791 \\
        --image "$BLOGS/engine/kernel.Dockerfile" --volume /ws=blogs-ws
    # 2. this script (from blogs/): token from ~/.modal.toml [arb8020], typed into the Connect form
    uv run --with playwright verify_modal_ch01.py --relay http://localhost:8791

Story (every step through the page; no shell in the sandbox):
  1  before Connect: the solution's linear region typed into the linear cell; Run queued
  2  Connect on T4 (the first connect builds the image: minutes) -> the queued linear run passes on cuda
     (fp32 + fp16 rows; bf16 a visible SKIP: sm_75 has no bf16 hardware)
  3  gelu: exact erf GELU typed in -> FAIL (fp32 rows only, readable notes); tanh restored -> PASS
  4  layer_norm, attention, block, forward with the reference solution -> PASS (forward: per-position KL gate)
  5  reload: the page reattaches to the same sandbox; cells keep their state
  6  Disconnect (ends the sandbox), Connect again: a new sandbox restores the workspace from the Volume; passed
     cells say so
  7  Disconnect. The script never leaves a session it started: it ends it on any failure too.
Evidence: .evidence/modal-ch01/ (screenshots, story.log, timings.json, each cell's check log).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

import verify_workspace as vw

OUT = vw.HERE / ".evidence" / "modal-ch01"
CONNECT_TIMEOUT_MS = 15 * 60_000
vw.CHECK_TIMEOUT_MS = 10 * 60_000


@dataclass(frozen=True)
class Secret:
    value: str = field(repr=False)

    def __str__(self) -> str:
        return "[secret]"


def token(profile: str) -> tuple[str, Secret]:
    cfg = tomllib.loads((Path.home() / ".modal.toml").read_text())[profile]
    return cfg["token_id"], Secret(cfg["token_secret"])


LOADED = (f"document.querySelectorAll('ws-cell[data-loaded]').length === {vw.CELLS1} && [...document.querySelectorAll("
          "'ws-cell .cell-status')].every((e) => !e.textContent.startsWith('loading'))")


class Story:
    def __init__(self, page: Page, tok: tuple[str, Secret]) -> None:
        self.page, self.tok = page, tok
        self.log: list[str] = []
        self.timings: dict[str, object] = {}

    def say(self, text: str) -> None:
        print(f"  {text}", flush=True)
        self.log.append(text)

    def shot(self, name: str, cell: str | None = None) -> None:
        target = self.page.locator(f"ws-cell[name={cell}]") if cell else self.page
        target.screenshot(path=OUT / f"{name}.png")

    def keep_log(self, name: str, cell: str) -> None:
        (OUT / f"{name}.log").write_text(vw.check_log(self.page, cell) + "\n---- output ----\n"
                                         + self.page.locator(f"ws-cell[name={cell}] .cell-out").inner_text())

    def connect(self, label: str) -> float:
        page = self.page
        if page.locator(".connect-panel").is_hidden():
            page.locator(".connect-pill").click()
        if page.locator("input[name=token-id]").is_visible():
            page.fill("input[name=token-id]", self.tok[0])
            page.fill("input[name=token-secret]", self.tok[1].value)
        page.select_option("select[name=gpu]", "T4")
        t0 = time.perf_counter()
        page.locator(".connect-go").click()
        page.wait_for_selector("connect-pill[data-phase=connected]", timeout=CONNECT_TIMEOUT_MS)
        took = time.perf_counter() - t0
        page.wait_for_function(LOADED, timeout=120_000)
        self.timings[f"connect_{label}_s"] = round(took, 1)
        return took

    def disconnect(self) -> None:
        page = self.page
        if page.locator("connect-pill[data-phase=disconnected]").count():
            return
        if page.locator(".connect-panel").is_hidden():
            page.locator(".connect-pill").click()
        page.locator(".connect-end").click()
        page.wait_for_selector("connect-pill[data-phase=disconnected]", timeout=120_000)

    def check(self, cell: str, label: str) -> tuple[str, list[dict[str, str]], float]:
        status, _, took = vw.run_cell(self.page, cell)
        self.timings.setdefault("checks", []).append({"check": label, "click_to_verdict_s": round(took, 2)})
        self.keep_log(f"{len(self.timings['checks']):02d}-{cell}", cell)
        return status, vw.rows(self.page, cell), took


def passes(rows: list[dict[str, str]], cell: str) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    ran = [r for r in rows if r["outcome"] != "skip"]
    skips = [r for r in rows if r["outcome"] == "skip"]
    assert ran and all(r["outcome"] == "pass" for r in ran), (cell, [r for r in ran if r["outcome"] != "pass"][:3])
    return ran, skips


def drive(s: Story) -> None:
    page = s.page
    vw.put_region(page, "linear", "linear", vw.SOL1)
    page.locator("ws-cell[name=linear] .run").click()
    s.shot("1-edited-queued")
    s.say("1 linear region typed before Connect; Run queued")
    took = s.connect("first")
    s.say(f"2 Connect -> connected in {took:.1f}s (T4)")
    t0 = time.perf_counter()
    page.wait_for_function(vw.DONE, arg="linear", timeout=vw.CHECK_TIMEOUT_MS)
    s.timings.setdefault("checks", []).append({"check": "linear (queued at Connect; warm process cold)",
                                              "after_connected_s": round(time.perf_counter() - t0, 2)})
    s.keep_log("01-linear", "linear")
    status = page.locator("ws-cell[name=linear] .cell-status").inner_text()
    rows = vw.rows(page, "linear")
    log = vw.check_log(page, "linear")
    assert status.startswith("passed"), f"{status}\n{log[-3000:]}"
    ran, skips = passes(rows, "linear")
    assert "'device': 'cuda'" in log and "'chip': 'sm_75'" in log, log[-2000:]
    assert {r["dtype"] for r in ran} >= {"fp32", "fp16"}, rows
    assert [r["dtype"] for r in skips] == ["bf16"] and "sm_75 has no bf16 hardware" in skips[0]["notes"], skips
    s.shot("2-linear-pass", "linear")
    s.say(f"2 queued linear -> '{status}': {len(ran)} rows PASS on cuda sm_75 (dtypes {sorted({r['dtype'] for r in ran})}, "
          f"worst {max(vw.metric_value(r, 'err/tol') for r in ran if r['metric'].startswith('err/tol')):.3g}x tolerance); "
          f"bf16 SKIP: {skips[0]['notes'][:80]}…")
    vw.put_region(page, "gelu", "gelu", vw.SOL1)
    vw.replace_in_view(page, "gelu", vw.GELU_TANH, vw.GELU_ERF)
    status, rows, took = s.check("gelu", "gelu, exact-GELU bug")
    bad = [r for r in rows if r["outcome"] == "fail"]
    assert status.startswith("failed") and bad and bad[0]["notes"].startswith(vw.TOL_FAIL), (status, rows[:3])
    assert {r["dtype"] for r in bad} == {"fp32"}, bad
    s.shot("3-gelu-planted-bug", "gelu")
    s.say(f"3 exact GELU -> '{status}' in {took:.1f}s: {len(bad)} fp32 rows FAIL, e.g. '{bad[0]['case']}: {bad[0]['notes'][:160]}'")
    vw.replace_in_view(page, "gelu", vw.GELU_ERF, vw.GELU_TANH)
    status, rows, took = s.check("gelu", "gelu, fixed")
    ran, skips = passes(rows, "gelu")
    s.shot("3-gelu-pass", "gelu")
    s.say(f"3 tanh restored -> '{status}' in {took:.1f}s ({len(ran)} rows PASS, {len(skips)} SKIP)")
    for cell in ("layer_norm", "attention", "block", "forward"):
        vw.put_region(page, cell, cell, vw.SOL1)
        status, rows, took = s.check(cell, f"{cell}, solution")
        assert status.startswith("passed"), (cell, status, rows[:3], vw.check_log(page, cell)[-2000:])
        ran, skips = passes(rows, cell)
        label = "KL max" if cell == "forward" else "err/tol"
        worst = max(vw.metric_value(r, label) for r in ran if r["metric"].startswith(label))
        if cell == "forward":
            assert worst < 1e-7, worst
        s.shot(f"4-{cell}-pass", cell)
        s.say(f"4 {cell} -> '{status}' in {took:.1f}s: {len(ran)} rows PASS ({label} at most {worst:.3g}); "
              f"skips: {[r['dtype'] for r in skips]}")
    t0 = time.perf_counter()
    page.reload()
    page.wait_for_selector("connect-pill[data-phase=connected]", timeout=120_000)
    page.wait_for_function(LOADED, timeout=120_000)
    s.timings["reload_reattach_s"] = round(time.perf_counter() - t0, 1)
    states = {c: page.locator(f"ws-cell[name={c}] .cell-status").inner_text() for c in ("linear", "gelu", "forward")}
    assert all(v.startswith("passed") for v in states.values()), states
    s.say(f"5 reload -> reattached in {s.timings['reload_reattach_s']}s; {states}")
    s.disconnect()
    took = s.connect("warm")
    states = {c: page.locator(f"ws-cell[name={c}] .cell-status").inner_text() for c in ("linear", "gelu", "layer_norm", "attention", "block", "forward")}
    assert all(v.startswith("passed") for v in states.values()), states
    assert vw.region_text(vw.doc(page, "gelu"), "gelu") == vw.region_text(vw.SOL1, "gelu")
    s.shot("6-restored")
    s.say(f"6 Disconnect + Connect (new sandbox, warm image) in {took:.1f}s: workspace restored from the Volume; {states}")
    status, rows, took = s.check("linear", "linear, new sandbox (warm process cold, store on the Volume)")
    assert status.startswith("passed"), status
    s.say(f"6 linear in the new sandbox -> '{status}' in {took:.1f}s")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--relay", required=True, help="the relay's URL, e.g. http://localhost:8791")
    ap.add_argument("--profile", default="arb8020", help="~/.modal.toml profile whose token the page is given")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    port = vw.free_port()
    subprocess.run(["uv", "run", "build_page.py", str(vw.CHAPTER1.relative_to(vw.HERE))], cwd=vw.HERE, check=True,
                   stdout=subprocess.DEVNULL)
    errors: list[str] = []
    with vw.static_server(port), sync_playwright() as p:
        browser = p.chromium.launch(executable_path=vw.CHROME)
        page = browser.new_context(viewport={"width": 1100, "height": 900}).new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        s = Story(page, token(args.profile))
        t0 = time.perf_counter()
        page.goto(f"http://localhost:{port}/{vw.PAGE1}/?gateway={args.relay}")
        try:
            drive(s)
        except Exception:
            s.shot("failed")
            raise
        finally:
            try:
                s.disconnect()
                s.say("7 Disconnect: session ended")
            finally:
                s.timings["story_s"] = round(time.perf_counter() - t0, 1)
                (OUT / "timings.json").write_text(json.dumps(s.timings, indent=1))
                (OUT / "story.log").write_text("\n".join(s.log) + "\n")
                browser.close()
    assert not errors, errors
    print(f"ok: {OUT}/ timings {json.dumps(s.timings)}")


if __name__ == "__main__":
    os.chdir(vw.HERE)
    main()
