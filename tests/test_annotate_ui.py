"""Playwright smoke tests for mimir annotate UI.

Verifies that each annotate mode (browse, diff, message) auto-selects
content on load — no blank screen. Requires a built UI in mimir/ui/dist/.

Run: pytest tests/test_annotate_ui.py -v
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import textwrap
import time

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _free_port() -> int:
  with socket.socket() as s:
    s.bind(("127.0.0.1", 0))
    return s.getsockname()[1]


@pytest.fixture()
def mimir_server(request, tmp_path):
  """Start `mimir annotate` as a subprocess, yield (port, proc), kill on exit."""
  mode = request.param  # "browse", "diff", or "message"
  port = _free_port()
  root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

  def _mimir_cmd(argv: list[str]) -> list[str]:
    """Build command to invoke mimir.cli:main with given argv."""
    argv_repr = repr(argv)
    code = f"import sys; sys.argv = {argv_repr}; from mimir.cli import main; main()"
    return [sys.executable, "-c", code]

  if mode == "browse":
    argv = ["mimir", "annotate", "--no-open", "--port", str(port),
            "--root", root, "mimir/cli.py"]
    proc = subprocess.Popen(_mimir_cmd(argv), cwd=root, stderr=subprocess.PIPE)

  elif mode == "diff":
    # Create a small diff to feed via stdin
    diff_text = textwrap.dedent("""\
      diff --git a/foo.py b/foo.py
      --- a/foo.py
      +++ b/foo.py
      @@ -1,3 +1,4 @@
       line1
      +added
       line2
       line3
    """)
    argv = ["mimir", "annotate", "--no-open", "--port", str(port),
            "--root", root, "--diff", "-"]
    proc = subprocess.Popen(_mimir_cmd(argv), cwd=root, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    proc.stdin.write(diff_text.encode())
    proc.stdin.close()

  else:
    pytest.skip("message mode requires active Claude Code session")

  # Wait for server to be ready
  deadline = time.monotonic() + 5
  while time.monotonic() < deadline:
    try:
      with socket.create_connection(("127.0.0.1", port), timeout=0.2):
        break
    except OSError:
      time.sleep(0.1)
  else:
    proc.kill()
    pytest.fail("mimir annotate server did not start")

  yield port, mode
  proc.terminate()
  proc.wait(timeout=5)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

try:
  from playwright.sync_api import sync_playwright
  HAS_PLAYWRIGHT = True
except ImportError:
  HAS_PLAYWRIGHT = False

_SLOW = os.environ.get("RUN_SLOW_TESTS") not in (None, "", "0")

pytestmark = [
  pytest.mark.skipif(not HAS_PLAYWRIGHT, reason="playwright not installed"),
  pytest.mark.skipif(not _SLOW, reason="slow test — set RUN_SLOW_TESTS=1"),
]


def _check_no_empty_state(page) -> None:
  """Assert the 'pick a file' / empty placeholder is NOT showing."""
  empty = page.locator(".empty-state")
  assert empty.count() == 0, f"Empty state still visible: {empty.text_content()}"


@pytest.mark.parametrize("mimir_server", ["browse"], indirect=True)
def test_browse_auto_selects_file(mimir_server):
  """Browse mode with a target path should auto-open the file content."""
  port, _ = mimir_server
  with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    page.goto(f"http://127.0.0.1:{port}?annotate=1&mode=browse")
    # Wait for CodeMirror editor to mount
    page.wait_for_selector(".cm-editor", timeout=8000)
    _check_no_empty_state(page)
    # Verify file header shows the target
    header = page.locator(".file-header").text_content()
    assert "cli.py" in header
    browser.close()


@pytest.mark.parametrize("mimir_server", ["diff"], indirect=True)
def test_diff_auto_shows_content(mimir_server):
  """Diff mode should render diff content immediately, not an empty screen."""
  port, _ = mimir_server
  with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    page.goto(f"http://127.0.0.1:{port}?annotate=1&mode=diff&diff=stdin")
    # Wait for diff content to render
    page.wait_for_selector(".multi-diff-file", timeout=8000)
    _check_no_empty_state(page)
    browser.close()
