"""Toggle + shared-journal behavior for `mimir papercut` / `mimir breadcrumb`."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from mimir import journal

REPO = Path(__file__).resolve().parent.parent


def run_cli(
  *args: str, cwd: Path, env_extra: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
  env = {k: v for k, v in os.environ.items() if not k.startswith("MIMIR_")}
  env["PYTHONPATH"] = str(REPO)
  env.update(env_extra or {})
  return subprocess.run(
    [sys.executable, "-m", "mimir.cli", *args],
    cwd=cwd, env=env, capture_output=True, text=True,
  )


class JournalToggleTest(unittest.TestCase):
  def setUp(self) -> None:
    self.tempdir = tempfile.TemporaryDirectory()
    self.root = Path(self.tempdir.name).resolve()
    subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
    self.pyproject = self.root / "pyproject.toml"
    self.pyproject.write_text("[project]\nname = \"demo\"\n")

  def tearDown(self) -> None:
    self.tempdir.cleanup()

  def enable(self, *keys: str) -> None:
    body = "".join(f"{k} = true\n" for k in keys)
    self.pyproject.write_text(f"[project]\nname = \"demo\"\n\n[tool.mimir]\n{body}")

  # --- (a) default off ---

  def test_default_off_exits_nonzero_with_howto(self) -> None:
    for cmd, key in (("breadcrumb", "breadcrumb"), ("papercut", "papercut")):
      with self.subTest(cmd=cmd):
        r = run_cli(cmd, "hello", cwd=self.root)
        self.assertEqual(r.returncode, 1)
        self.assertIn(f"`{key} = true`", r.stderr)
        self.assertIn("[tool.mimir]", r.stderr)
        self.assertIn(str(self.pyproject), r.stderr)
        self.assertFalse((self.root / "BREADCRUMBS.md").exists())
        self.assertFalse((self.root / "PAPERCUTS.md").exists())

  def test_list_and_path_are_gated_too(self) -> None:
    for cmd in ("breadcrumb", "papercut"):
      for flag in ("--list", "--path"):
        with self.subTest(cmd=cmd, flag=flag):
          r = run_cli(cmd, flag, cwd=self.root)
          self.assertEqual(r.returncode, 1)
          self.assertIn("disabled", r.stderr)

  def test_explicit_false_stays_off(self) -> None:
    self.pyproject.write_text(
      "[project]\nname = \"demo\"\n\n[tool.mimir]\nbreadcrumb = false\n"
    )
    r = run_cli("breadcrumb", "hi", cwd=self.root)
    self.assertEqual(r.returncode, 1)

  # --- (b) pyproject on ---

  def test_pyproject_enables(self) -> None:
    self.enable("breadcrumb", "papercut")

    r = run_cli("breadcrumb", "-a", "tester", "shipped it", cwd=self.root)
    self.assertEqual(r.returncode, 0, r.stderr)
    text = (self.root / "BREADCRUMBS.md").read_text()
    self.assertTrue(text.startswith("# Breadcrumbs\n\n"))
    self.assertIn("[tester] shipped it", text)

    r = run_cli("papercut", "-m", "opus", "slow startup", cwd=self.root)
    self.assertEqual(r.returncode, 0, r.stderr)
    self.assertIn("slow startup", (self.root / "PAPERCUTS.md").read_text())

  def test_one_toggle_does_not_enable_the_other(self) -> None:
    self.enable("breadcrumb")
    self.assertEqual(run_cli("breadcrumb", "ok", cwd=self.root).returncode, 0)
    self.assertEqual(run_cli("papercut", "ok", cwd=self.root).returncode, 1)

  # --- (c) env override ---

  def test_env_enables_without_pyproject(self) -> None:
    r = run_cli("breadcrumb", "-a", "env", "via env", cwd=self.root,
                env_extra={"MIMIR_BREADCRUMB": "1"})
    self.assertEqual(r.returncode, 0, r.stderr)
    self.assertIn("via env", (self.root / "BREADCRUMBS.md").read_text())

    r = run_cli("papercut", "via env", cwd=self.root,
                env_extra={"MIMIR_PAPERCUT": "true"})
    self.assertEqual(r.returncode, 0, r.stderr)

  def test_env_off_beats_pyproject_on(self) -> None:
    self.enable("breadcrumb")
    r = run_cli("breadcrumb", "nope", cwd=self.root,
                env_extra={"MIMIR_BREADCRUMB": "0"})
    self.assertEqual(r.returncode, 1)

  # --- (d) existing append/list behavior ---

  def test_append_then_list_roundtrip(self) -> None:
    self.enable("breadcrumb", "papercut")

    self.assertIn("(no breadcrumbs yet)", run_cli("breadcrumb", "--list", cwd=self.root).stdout)
    self.assertIn("(no papercuts yet)", run_cli("papercut", "--list", cwd=self.root).stdout)

    run_cli("breadcrumb", "-a", "a1", "first", cwd=self.root)
    run_cli("breadcrumb", "-a", "a2", "second", cwd=self.root)
    out = run_cli("breadcrumb", "--list", cwd=self.root).stdout
    self.assertIn("[a1] first", out)
    self.assertIn("[a2] second", out)
    self.assertEqual(out.count("# Breadcrumbs"), 1)

    p = run_cli("breadcrumb", "--path", cwd=self.root).stdout.strip()
    self.assertEqual(Path(p).resolve(), self.root / "BREADCRUMBS.md")

  def test_empty_message_still_errors(self) -> None:
    self.enable("breadcrumb")
    r = run_cli("breadcrumb", cwd=self.root)
    self.assertEqual(r.returncode, 1)
    self.assertIn("no message provided", r.stderr)

  def test_file_override_is_honored(self) -> None:
    self.enable("papercut")
    target = self.root / "notes" / "PC.md"
    target.parent.mkdir()
    r = run_cli("papercut", "-f", str(target), "custom path", cwd=self.root)
    self.assertEqual(r.returncode, 0, r.stderr)
    self.assertIn("custom path", target.read_text())


class JournalModuleTest(unittest.TestCase):
  """The shared module is what both wrappers delegate to."""

  def test_wrappers_share_one_implementation(self) -> None:
    from mimir import breadcrumb, papercut

    self.assertIs(breadcrumb.SPEC, journal.BREADCRUMB)
    self.assertIs(papercut.SPEC, journal.PAPERCUT)
    self.assertIs(breadcrumb.repo_root, papercut.repo_root)
    self.assertIs(breadcrumb.repo_root, journal.repo_root)

  def test_specs_are_distinct_and_default_off(self) -> None:
    with tempfile.TemporaryDirectory() as d:
      for spec, fname in ((journal.BREADCRUMB, "BREADCRUMBS.md"),
                          (journal.PAPERCUT, "PAPERCUTS.md")):
        self.assertEqual(journal.resolve_path(spec, str(Path(d) / fname)).name, fname)
        self.assertFalse(journal.is_enabled(spec, d))


if __name__ == "__main__":
  unittest.main()
