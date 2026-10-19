from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import Browser, Locator, Page

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from replay import OUT, Replay, check  # noqa: E402
from verify_connect import connected, replayed  # noqa: E402

STATS = "document.querySelector('nn-fit').stats"
CPU = "cpu (remote)"
GPU_DEVICE = "cuda · Tesla T4"
RUN_MS = 1000
GROK_FIRST_STEPS = 50
TIME_BUDGET_5S, TIME_BUDGET_60S, STEP_BUDGET_1000, BUDGET_OFF = "2", "6", "1", "7"


def nn(part: str) -> str:
    return f"nn-fit >> {part}"


def is_disabled(locator: Locator) -> bool:
    return locator.evaluate("(el) => el.disabled")


def slider(page: Page, cls: str, stop: str) -> None:
    page.locator(nn(f"input.{cls}")).evaluate(f"(el) => {{ el.value = '{stop}'; el.dispatchEvent(new Event('input')); }}")


def stopped(page: Page) -> dict:
    page.wait_for_function(f"!{STATS}.training", timeout=180_000)
    return page.evaluate(STATS)


def status(page: Page) -> str:
    return page.locator("nn-fit [role=status]").text_content() or ""


def curve_stop(page: Page, device: str) -> None:
    before = page.evaluate(STATS)
    page.select_option(nn("select.backend"), "remote")
    page.click(nn("button.train"))
    page.wait_for_function(f"{STATS}.steps > 0 && {STATS}.device === {device!r}", timeout=60_000)
    check(is_disabled(page.locator(nn("fieldset.network"))), f"remote run on {device}: the network controls are disabled while it trains")
    page.wait_for_timeout(RUN_MS)
    page.click(nn("button.train"))
    after = stopped(page)
    check(after["loss"] < before["loss"] / 10 and "Remote run stopped: stopped" in status(page), f"Stop: the remote loss fell 10x ({before['loss']:.3g} -> {after['loss']:.3g}), announced")
    check(f"on {device}" in (page.locator(nn(".usage")).text_content() or ""), "the readout names the backend")
    page.select_option(nn("select.backend"), "browser")
    page.click(nn("button.train"))
    page.wait_for_function(f"{STATS}.steps >= {after['steps'] + 200}", timeout=30_000)
    page.click(nn("button.train"))
    cont = page.evaluate(STATS)
    check(cont["device"] == "this browser" and cont["loss"] < before["loss"] / 10, f"the browser continues from the remote weights (loss {cont['loss']:.3g})")


def spiral(page: Page) -> None:
    page.select_option(nn("select.dataset"), "spiral")
    page.click(nn("button.reset"))
    slider(page, "step-budget", STEP_BUDGET_1000)
    page.select_option(nn("select.backend"), "remote")
    page.click(nn("button.train"))
    end = stopped(page)
    check(end["steps"] == 1000 and end["accuracy"] > 0.9 and "step budget used up" in status(page), f"spiral: the step budget stops it at 1000, train accuracy {end['accuracy']:.1%}")
    slider(page, "step-budget", BUDGET_OFF)


def grok(page: Page, device: str, gpu: bool) -> None:
    page.select_option(nn("select.dataset"), "grok")
    check(page.locator(nn("fieldset.network")).is_hidden() and is_disabled(page.locator(nn("select.backend"))), "grok: remote only, no network controls")
    page.click(nn("button.train"))
    page.wait_for_function(f"{STATS}.steps >= {GROK_FIRST_STEPS} && {STATS}.device === {device!r}", timeout=120_000)
    page.click(nn("button.train"))
    first = stopped(page)
    check("Remote run stopped: stopped" in status(page) and first["grok"]["points"] > 10, f"grok: Stop at step {first['steps']}, {first['grok']['points']} points plotted")
    slider(page, "time-budget", TIME_BUDGET_60S if gpu else TIME_BUDGET_5S)
    page.click(nn("button.train"))
    end = page.wait_for_function(f"!{STATS}.training && {STATS}.steps > {first['steps']} && {STATS}", timeout=180_000).json_value()
    check("time budget used up" in status(page) and end["grok"]["run"] == first["grok"]["run"], f"grok: Train continued the same run to {end['steps']} steps; the time budget ended it")
    if gpu:
        check(end["grok"]["grokked"] is not None, f"grok: test accuracy passed 95% ({end['grok']['grokked']})")
    slider(page, "time-budget", BUDGET_OFF)
    page.select_option(nn("select.dataset"), "spiral")
    page.locator("nn-fit").screenshot(path=OUT / "grok.png")


def runs(page: Page, gpu: str | None) -> None:
    device = GPU_DEVICE if gpu == "T4" else CPU
    page.locator("nn-fit").scroll_into_view_if_needed()
    curve_stop(page, device)
    spiral(page)
    grok(page, device, gpu is not None)


def disconnect_mid_run(page: Page) -> None:
    page.select_option(nn("select.dataset"), "wave")
    page.click(nn("button.reset"))
    page.click(nn("button.train"))
    page.wait_for_function(f"{STATS}.steps > 0", timeout=60_000)
    page.locator(".connect-pill").click()
    page.locator(".connect-end").click()
    end = stopped(page)
    need = page.locator(nn("p.need")).text_content() or ""
    check(need.startswith("Remote run failed: ") and end["steps"] == 0 and end["device"] == "this browser", f"disconnect mid-run: the run fails, says why ({need!r}), weights untouched")
    option = page.locator(nn("select.backend option[value=remote]"))
    check(is_disabled(option) and option.text_content() == "remote (Connect first)", "disconnected: remote offered only when connected")


def nn_fit(page: Page, stub: Replay) -> None:
    option, grok_option = page.locator(nn("select.backend option[value=remote]")), page.locator(nn("select.dataset option[value=grok]"))
    check(is_disabled(option) and is_disabled(grok_option) and "Connect first" in (grok_option.text_content() or ""), "not connected: remote and grokking disabled, with a hint")
    connected(page)
    check(not is_disabled(option) and not is_disabled(grok_option), "connected: remote and grokking offered")
    runs(page, None)
    disconnect_mid_run(page)


def fast(browser: Browser, base: str) -> None:
    replayed(browser, base, nn_fit, kernel=("nn-fit",))


if __name__ == "__main__":
    import replay

    replay.alone(fast, "connect")
