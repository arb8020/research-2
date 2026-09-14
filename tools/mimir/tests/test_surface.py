from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from mimir.imports import build_import_graph


class SurfaceTest(unittest.TestCase):
  def setUp(self) -> None:
    self.tempdir = tempfile.TemporaryDirectory()
    self.root = Path(self.tempdir.name)
    files = {
      "workspace/__init__.py": "from . import api\n",
      "workspace/api.py": "from .feature import service\n",
      "workspace/feature/__init__.py": "",
      "workspace/feature/service.py": "import workspace\n",
      "consumer/use.py": "from workspace.feature import service\n",
    }
    for name, source in files.items():
      path = self.root / name
      path.parent.mkdir(parents=True, exist_ok=True)
      path.write_text(source)

  def tearDown(self) -> None:
    self.tempdir.cleanup()

  def test_graph_resolves_packages_relative_imports_and_cycles(self) -> None:
    graph = build_import_graph(str(self.root))

    self.assertEqual(graph.edges["workspace/feature/service.py"], {"workspace/__init__.py"})
    self.assertEqual(graph.edges["workspace/__init__.py"], {"workspace/api.py"})
    self.assertEqual(graph.edges["workspace/api.py"], {"workspace/feature/service.py"})
    self.assertEqual(graph.edges["consumer/use.py"], {"workspace/feature/service.py"})
    self.assertEqual(graph.cycles, [[
      "workspace/__init__.py",
      "workspace/api.py",
      "workspace/feature/service.py",
    ]])

  def test_cli_exposes_filterable_raw_graph_as_json(self) -> None:
    result = subprocess.run(
      [
        sys.executable, "-m", "mimir.cli", "scan", str(self.root),
        "--surface", "--cross", "--from", "consumer", "--json",
      ],
      check=True,
      capture_output=True,
      text=True,
    )

    report = json.loads(result.stdout)
    self.assertEqual(report.keys(), {"surface"})
    self.assertEqual(report["surface"]["edges"], [{
      "from": "consumer/use.py",
      "to": "workspace/feature/service.py",
    }])


if __name__ == "__main__":
  unittest.main()
