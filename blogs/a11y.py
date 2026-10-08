"""Accessibility lint for a built chapter page: axe-core in headless Chromium, light and dark.

    uv run --with playwright a11y.py [url]      # default http://localhost:8010/01-flappy/

Needs the page served (python3 -m http.server 8010 -d dist). Exits 1 if any violation is found.
"""

import sys

from playwright.sync_api import sync_playwright

AXE = "https://cdn.jsdelivr.net/npm/axe-core@4.10.2/axe.min.js"
URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8010/01-flappy/"


def audit(browser, scheme: str) -> list[dict]:
    page = browser.new_page(viewport={"width": 1000, "height": 800}, color_scheme=scheme)
    page.goto(URL)
    page.locator(".cm-editor").first.wait_for()
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
    for scheme in ("light", "dark"):
        violations = audit(browser, scheme)
        report(scheme, violations)
        found += len(violations)
    browser.close()
sys.exit(1 if found else 0)
