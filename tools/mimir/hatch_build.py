"""Hatchling build hook: compile the Vite UI into mimir/ui/dist before packaging.

The built UI is not committed (see .gitignore). `mimir annotate` serves it from
mimir/ui/dist at runtime, so the wheel must carry it. `artifacts` in
pyproject.toml forces the gitignored directory into the wheel.
"""

import os
import shutil
import subprocess

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

_APP_DIR = os.path.join("mimir", "ui", "app")
_DIST_DIR = os.path.join("mimir", "ui", "dist")

_MISSING_BUN = (
  "mimir's build requires `bun` on PATH to compile the annotate UI "
  "(mimir/ui/app -> mimir/ui/dist).\n"
  "Install it with:  curl -fsSL https://bun.sh/install | bash\n"
  "(or `brew install oven-sh/bun/bun`), then re-run the build.\n"
  "Refusing to build a wheel without the UI assets."
)


class MimirUIBuildHook(BuildHookInterface):
  PLUGIN_NAME = "custom"

  def initialize(self, version: str, build_data: dict) -> None:
    if self.target_name not in {"wheel", "sdist"}:
      return
    if os.environ.get("MIMIR_SKIP_UI_BUILD"):
      self.app.display_warning("MIMIR_SKIP_UI_BUILD set; skipping UI build")
      return

    root = self.root
    app_dir = os.path.join(root, _APP_DIR)
    dist_dir = os.path.join(root, _DIST_DIR)

    if not os.path.isdir(app_dir):
      raise RuntimeError(f"UI source directory missing: {app_dir}")

    bun = shutil.which("bun")
    if bun is None:
      raise RuntimeError(_MISSING_BUN)

    self.app.display_info("Building mimir annotate UI with bun...")
    self._run([bun, "install", "--frozen-lockfile"], app_dir)
    self._run([bun, "run", "build"], app_dir)

    index = os.path.join(dist_dir, "index.html")
    if not os.path.isfile(index):
      raise RuntimeError(
        f"UI build finished but {index} is missing; `bun run build` produced no output."
      )

  def _run(self, cmd: list[str], cwd: str) -> None:
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
      raise RuntimeError(
        f"`{' '.join(cmd)}` failed in {cwd} (exit {result.returncode})\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
      )
