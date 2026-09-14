"""Route parity test: Python server ↔ TypeScript frontend.

Extracts API routes defined in annotate.py (and webui.py if present) and
fetch URLs called in api.ts, then asserts they match. Catches the class of
bug where a backend endpoint exists but the frontend doesn't call it, or
vice versa — which surfaces as blank screens or silent 404s.

Inspired by plannotator's tests/parity/route-parity.test.ts.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# Extractors
# ---------------------------------------------------------------------------

def extract_server_routes(path: Path) -> set[str]:
  """Extract url.path == "/api/..." patterns from the Python handler."""
  src = path.read_text()
  routes: set[str] = set()

  # Match: url.path == "/api/..."  or  if url.path == "/api/..."
  for m in re.finditer(r'url\.path\s*==\s*["\'](/api/[^"\']+)["\']', src):
    routes.add(m.group(1))

  # Match: elif url.path == "/api/..." (same regex catches these)
  # Also match string comparisons in do_GET/do_POST methods
  for m in re.finditer(r'["\'](/api/[a-z_/]+)["\']', src):
    routes.add(m.group(1))

  return routes


def extract_frontend_routes(path: Path) -> set[str]:
  """Extract fetch("/api/...") patterns from the TypeScript API client."""
  src = path.read_text()
  routes: set[str] = set()

  # Match: fetch("/api/...") or json("/api/...") or json(`/api/...`)
  for m in re.finditer(r'(?:fetch|json)[(<]\s*["`\'](/api/[a-z_/]+)', src):
    routes.add(m.group(1))

  # Match: template literals like `/api/message?...`
  for m in re.finditer(r'`(/api/[a-z_/]+)', src):
    routes.add(m.group(1))

  return routes


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

ANNOTATE_PY = ROOT / "mimir" / "annotate.py"
API_TS = ROOT / "mimir" / "ui" / "app" / "src" / "api.ts"


def test_frontend_routes_have_backend_handlers():
  """Every route the frontend fetches must exist in the server."""
  server = extract_server_routes(ANNOTATE_PY)
  frontend = extract_frontend_routes(API_TS)

  missing = frontend - server
  assert not missing, (
    f"Frontend calls these routes not handled by the server:\n"
    + "\n".join(f"  - {r}" for r in sorted(missing))
    + "\n\nAdd handlers in mimir/annotate.py or remove dead fetches from api.ts"
  )


def test_backend_routes_are_used_by_frontend():
  """Every API route the server defines should be consumed by the frontend.

  Warns (not fails) for unused routes — some may be used by external tools.
  """
  server = extract_server_routes(ANNOTATE_PY)
  frontend = extract_frontend_routes(API_TS)

  unused = server - frontend
  if unused:
    # Soft warning — print but don't fail
    print(
      f"\nNote: server defines {len(unused)} route(s) not called by api.ts:\n"
      + "\n".join(f"  - {r}" for r in sorted(unused))
      + "\n(These may be used by external tools or tests — not necessarily a bug.)"
    )


def test_extractors_find_real_routes():
  """Sanity check: extractors actually find routes in our files."""
  server = extract_server_routes(ANNOTATE_PY)
  frontend = extract_frontend_routes(API_TS)

  assert len(server) >= 4, f"Expected ≥4 server routes, got {len(server)}: {server}"
  assert len(frontend) >= 4, f"Expected ≥4 frontend routes, got {len(frontend)}: {frontend}"

  # These core routes must always exist on both sides
  for route in ["/api/annotate/target", "/api/annotate/submit", "/api/file", "/api/tree"]:
    assert route in server, f"Server missing core route: {route}"
    assert route in frontend, f"Frontend missing core route: {route}"
