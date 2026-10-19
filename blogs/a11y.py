import argparse
import sys
from urllib.error import URLError
from urllib.request import urlopen

from playwright.sync_api import Browser, sync_playwright

AXE = "https://cdn.jsdelivr.net/npm/axe-core@4.10.2/axe.min.js"
SERVE = "python3 -m http.server 8010 -d dist"
_ap = argparse.ArgumentParser(
    description="Accessibility lint for a built chapter page: axe-core in headless Chromium, every theme x light/dark, "
                "and again with the first [[link]]'s preview card open. Exits 1 on any violation.",
    epilog=f"needs the page served: {SERVE}")
_ap.add_argument("url", nargs="?", default="http://localhost:8010/01-flappy/")
URL = _ap.parse_args().url
try:
    urlopen(URL)
except URLError as e:
    sys.exit(f"nothing at {URL} ({e.reason}); serve dist/ first: {SERVE}")


def audit(browser: Browser, theme: str, scheme: str, card: bool) -> list[dict]:
    page = browser.new_page(viewport={"width": 1000, "height": 800}, color_scheme=scheme)
    page.add_init_script(f"localStorage.setItem('blogs.settings', JSON.stringify({{theme: '{theme}'}}))")
    page.goto(URL)
    page.wait_for_function("[...document.querySelectorAll('code-cell, code-view')].every((e) => e.querySelector('.cm-editor'))")
    if card:
        page.locator("page-link > a").first.hover()
        page.locator(".link-card").wait_for()
    page.wait_for_timeout(1000)
    page.add_script_tag(url=AXE)
    result = page.evaluate("axe.run(document, {resultTypes: ['violations']})")
    page.close()
    return result["violations"]


def report(scheme: str, violations: list[dict]) -> None:
    print(f"\n== {scheme}: {len(violations)} violation type(s)")
    for v in violations:
        print(f"  [{v['impact']}] {v['id']}: {v['help']} ({len(v['nodes'])} node(s))")
        for node in v["nodes"][:4]:
            target = " ".join(node["target"]) if isinstance(node["target"][0], str) else str(node["target"])
            detail = node.get("any", [{}])[0].get("message", "") if node.get("any") else ""
            print(f"      {target[:70]:70}  {detail[:110]}")
        if len(v["nodes"]) > 4:
            print(f"      ... {len(v['nodes']) - 4} more")


with sync_playwright() as p:
    browser = p.chromium.launch()
    found = 0
    probe = browser.new_page()
    probe.goto(URL)
    cards = (False, True) if probe.locator("page-link").count() else (False,)
    probe.close()
    for theme in ("classic", "paper"):
        for scheme in ("light", "dark"):
            for card in cards:
                violations = audit(browser, theme, scheme, card)
                report(f"{theme} {scheme}{' (link card open)' if card else ''}", violations)
                found += len(violations)
    browser.close()
sys.exit(1 if found else 0)
