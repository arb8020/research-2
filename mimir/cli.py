"""mimir CLI — codebase structural health scanner."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass

from .at import AtReport, parse_target, query_at
from .quests import TurnIn, collect_turn_in
from .scan import FunctionMetrics, scan_dir, scan_file_lengths, structural_erosion

FIELD_THRESHOLD = 7
LONG_FILE_THRESHOLD = 500

# Default thresholds: (warn, alert).
DEFAULT_THRESHOLDS: dict[str, tuple[int, int]] = {
  "nest": (4, 5),
  "stmts": (50, 70),
  "args": (5, 7),
  "cc": (10, 12),
  "branches": (10, 12),
  "returns": (4, 6),
}

ALL_METRICS = list(DEFAULT_THRESHOLDS)

_METRIC_FIELDS = {
  "nest": "max_nesting",
  "stmts": "stmt_count",
  "args": "arg_count",
  "cc": "cyclomatic",
  "branches": "branches",
  "returns": "returns",
}

SECTIONS = ("structure", "heat", "surface", "rot", "todo")


@dataclass(frozen=True)
class EdgeFilter:
  source: str | None
  destination: str | None
  cross_top_level: bool


def _metric_val(m: FunctionMetrics, metric: str) -> int:
  return getattr(m, _METRIC_FIELDS[metric])


def _metric_severity(val: int, thresholds: tuple[int, int]) -> str:
  if val >= thresholds[1]:
    return "alert"
  if val >= thresholds[0]:
    return "warn"
  return "clean"


def _line_severity(
  m: FunctionMetrics,
  thresholds: dict[str, tuple[int, int]],
  only: list[str],
) -> str:
  worst = "clean"
  for k in only:
    sev = _metric_severity(_metric_val(m, k), thresholds[k])
    if sev == "alert":
      return "alert"
    if sev == "warn":
      worst = "warn"
  return worst


def _bad_metrics(
  m: FunctionMetrics,
  thresholds: dict[str, tuple[int, int]],
  only: list[str],
) -> dict[str, int]:
  out = {}
  for k in only:
    v = _metric_val(m, k)
    if v >= thresholds[k][0]:
      out[k] = v
  return out


def _format_fn_line(
  m: FunctionMetrics,
  root: str,
  thresholds: dict[str, tuple[int, int]],
  only: list[str],
) -> str:
  relpath = os.path.relpath(m.file, root)
  bad = _bad_metrics(m, thresholds, only)
  metrics_str = "  ".join(f"{k}={v}" for k, v in bad.items())
  return f"{m.name}  {relpath}:{m.line}  {metrics_str}"


def _active_sections(args: argparse.Namespace) -> set[str]:
  """Which sections to show. If none specified, show all."""
  if args.edge_from or args.edge_to or args.cross:
    return {"surface"}
  explicit = {s for s in SECTIONS if getattr(args, s, False)}
  return explicit if explicit else set(SECTIONS)


def _build_report(
  target: str,
  sections: set[str],
  thresholds: dict[str, tuple[int, int]],
  only: list[str],
  exclude: list[str],
  edge_filter: EdgeFilter,
) -> dict:
  """Build the full report as a dict. Used by both text and JSON output."""
  report: dict = {}

  if "structure" in sections:
    fn_metrics, cls_metrics = scan_dir(target, exclude=exclude)
    file_metrics = scan_file_lengths(target, exclude=exclude)

    long_files = sorted(
      [f for f in file_metrics if f.lines >= LONG_FILE_THRESHOLD],
      key=lambda f: -f.lines,
    )
    wide_classes = sorted(
      [c for c in cls_metrics if c.field_count > FIELD_THRESHOLD],
      key=lambda c: -c.field_count,
    )

    alerts: dict[str, int] = {}
    for k in only:
      _, alert_t = thresholds[k]
      n = sum(1 for m in fn_metrics if _metric_val(m, k) >= alert_t)
      if n > 0:
        alerts[k] = n

    report["structure"] = {
      "functions": {
        "total": len(fn_metrics),
        "alerts": alerts,
        "items": [
          {
            "name": m.name,
            "file": os.path.relpath(m.file, target),
            "line": m.line,
            "nest": m.max_nesting,
            "stmts": m.stmt_count,
            "args": m.arg_count,
            "cc": m.cyclomatic,
            "branches": m.branches,
            "returns": m.returns,
          }
          for m in fn_metrics
        ],
      },
      "erosion": round(structural_erosion(fn_metrics), 2),
      "files": {
        "total": len(file_metrics),
        "long": [
          {"file": os.path.relpath(f.file, target), "lines": f.lines}
          for f in long_files
        ],
      },
      "classes": {
        "total": len(cls_metrics),
        "wide": [
          {"name": c.name, "file": os.path.relpath(c.file, target), "line": c.line, "fields": c.field_count}
          for c in wide_classes
        ],
      },
    }

  if "heat" in sections:
    from .heat import compute_heat
    heat_results = compute_heat(target, exclude=exclude)
    report["heat"] = [
      {"file": h.file, "commits": h.commits, "max_cc": h.max_cc, "rel_heat": h.heat}
      for h in heat_results
    ]

  if "surface" in sections:
    from .imports import build_import_graph
    graph = build_import_graph(target, exclude=exclude)

    HIGH_FAN_OUT = 10
    HIGH_FAN_IN = 15
    DIR_THRESHOLD = 10

    dir_counts: dict[str, int] = {}
    for m in graph.metrics:
      d = os.path.dirname(m.file) or "."
      dir_counts[d] = dir_counts.get(d, 0) + 1

    def matches(path: str, prefix: str | None) -> bool:
      if prefix is None:
        return True
      normalized = prefix.replace("\\", "/").rstrip("/")
      return path == normalized or path.startswith(normalized + "/")

    def top_directory(path: str) -> str:
      directory = path.partition("/")[0]
      return directory if "/" in path else "."

    visible_edges = [
      {"from": source, "to": destination}
      for source, destinations in sorted(graph.edges.items())
      for destination in sorted(destinations)
      if matches(source, edge_filter.source)
      and matches(destination, edge_filter.destination)
      and (
        not edge_filter.cross_top_level
        or top_directory(source) != top_directory(destination)
      )
    ]

    report["surface"] = {
      "edges": visible_edges,
      "cycles": [sorted(c) for c in graph.cycles],
      "high_fan_out": [
        {"file": m.file, "fan_out": m.fan_out}
        for m in sorted(
          [m for m in graph.metrics if m.fan_out >= HIGH_FAN_OUT],
          key=lambda m: -m.fan_out,
        )
      ],
      "high_fan_in": [
        {"file": m.file, "fan_in": m.fan_in}
        for m in sorted(
          [m for m in graph.metrics if m.fan_in >= HIGH_FAN_IN],
          key=lambda m: -m.fan_in,
        )
      ],
      "wide_dirs": [
        {"dir": d, "files": n}
        for d, n in sorted(
          [(d, n) for d, n in dir_counts.items() if n > DIR_THRESHOLD],
          key=lambda x: -x[1],
        )
      ],
    }

  if "rot" in sections:
    from .rot import scan_rot_dir
    rot_findings = scan_rot_dir(target, exclude=exclude)
    rot_by_kind: dict[str, int] = {}
    for f in rot_findings:
      rot_by_kind[f.kind] = rot_by_kind.get(f.kind, 0) + 1
    report["rot"] = {
      "counts": rot_by_kind,
      "items": [
        {"kind": f.kind, "file": os.path.relpath(f.file, target), "line": f.line, "detail": f.detail}
        for f in rot_findings
      ],
    }

  if "todo" in sections:
    from .todo import scan_todo_dir
    todo_findings = scan_todo_dir(target, exclude=exclude)
    todo_by_kind: dict[str, int] = {}
    for f in todo_findings:
      todo_by_kind[f.kind] = todo_by_kind.get(f.kind, 0) + 1
    report["todo"] = {
      "counts": todo_by_kind,
      "items": [
        {"kind": f.kind, "file": os.path.relpath(f.file, target), "line": f.line, "detail": f.detail}
        for f in todo_findings
      ],
    }

  return report


def _print_structure(
  s: dict,
  target: str,
  thresholds: dict[str, tuple[int, int]],
  only: list[str],
  *,
  list_mode: bool,
  only_filter: str | None,
  min_idx: int,
) -> None:
  """Print the structure section of the report."""
  out = sys.stderr
  sev_order = {"clean": 0, "warn": 1, "alert": 2}

  if list_mode:
    fn_metrics = [
      FunctionMetrics(
        file=os.path.join(target, item["file"]),
        name=item["name"], line=item["line"],
        max_nesting=item["nest"], stmt_count=item["stmts"],
        arg_count=item["args"], cyclomatic=item["cc"],
        branches=item["branches"], returns=item["returns"],
      )
      for item in s["functions"]["items"]
    ]
    shown = [
      m for m in fn_metrics
      if sev_order[_line_severity(m, thresholds, only)] >= min_idx
    ]
    shown.sort(key=lambda m: (
      -max(_bad_metrics(m, thresholds, only).values()) if _bad_metrics(m, thresholds, only) else 0,
      m.file, m.line,
    ))
    for m in shown:
      print(_format_fn_line(m, target, thresholds, only))
    if not only_filter:
      for f in s["files"]["long"]:
        print(f"{f['file']}  lines={f['lines']}")
      for c in s["classes"]["wide"]:
        print(f"{c['name']}  {c['file']}:{c['line']}  fields={c['fields']}")

  if not (only_filter and list_mode):
    print("structure", file=out)
    print(f"  functions  {s['functions']['total']}", file=out)
    for k, n in s["functions"]["alerts"].items():
      print(f"    {k}  {n}", file=out)
    print(f"  erosion  {s['erosion']:.2f}", file=out)
    print(f"  files  {s['files']['total']}", file=out)
    if s["files"]["long"]:
      print(f"    long  {len(s['files']['long'])}", file=out)
    print(f"  classes  {s['classes']['total']}", file=out)
    if s["classes"]["wide"]:
      print(f"    wide  {len(s['classes']['wide'])}", file=out)


def _print_heat(heat: list[dict], *, list_mode: bool) -> None:
  """Print the heat section of the report."""
  out = sys.stderr
  if list_mode:
    for h in heat:
      print(f"{h['file']}  commits={h['commits']}  max_cc={h['max_cc']}  rel_heat={h['rel_heat']:.0f}")
  print("heat", file=out)
  for h in heat[:5]:
    print(
      f"  {h['file']}  commits={h['commits']}  max_cc={h['max_cc']}  rel_heat={h['rel_heat']:.0f}",
      file=out,
    )
  if len(heat) > 5:
    print(f"  ... {len(heat) - 5} more", file=out)


def _print_surface(sf: dict, *, list_mode: bool) -> None:
  """Print the surface section of the report."""
  out = sys.stderr
  if list_mode:
    for edge in sf["edges"]:
      print(f"edge  {edge['from']} -> {edge['to']}")
    for m in sf["high_fan_out"]:
      print(f"{m['file']}  fan_out={m['fan_out']}")
    for m in sf["high_fan_in"]:
      print(f"{m['file']}  fan_in={m['fan_in']}")
    for d in sf["wide_dirs"]:
      print(f"{d['dir']}/  files={d['files']}")
    for cycle in sf["cycles"]:
      print(f"cycle  {' -> '.join(cycle)}")
  has_surface = sf["cycles"] or sf["high_fan_out"] or sf["high_fan_in"] or sf["wide_dirs"]
  if has_surface:
    print("surface", file=out)
    if sf["cycles"]:
      print(f"  cycles  {len(sf['cycles'])}", file=out)
    if sf["high_fan_out"]:
      print(f"  high_fan_out  {len(sf['high_fan_out'])}", file=out)
    if sf["high_fan_in"]:
      print(f"  high_fan_in  {len(sf['high_fan_in'])}", file=out)
    if sf["wide_dirs"]:
      print(f"  wide_dirs  {len(sf['wide_dirs'])}", file=out)


def _print_rot(rot: dict, *, list_mode: bool) -> None:
  """Print the rot section of the report."""
  out = sys.stderr
  if list_mode:
    for f in rot["items"]:
      print(f"rot:{f['kind']}  {f['file']}:{f['line']}  {f['detail']}")
  print("rot", file=out)
  for kind, n in sorted(rot["counts"].items()):
    print(f"  {kind}  {n}", file=out)


def _print_todo(todo: dict, *, list_mode: bool) -> None:
  """Print the todo section of the report."""
  out = sys.stderr
  if list_mode:
    for f in todo["items"]:
      print(f"todo:{f['kind']}  {f['file']}:{f['line']}  {f['detail']}")
  print("todo", file=out)
  for kind, n in sorted(todo["counts"].items()):
    print(f"  {kind}  {n}", file=out)


def _print_text(
  report: dict,
  target: str,
  thresholds: dict[str, tuple[int, int]],
  only: list[str],
  args: argparse.Namespace,
) -> None:
  """Render the report as human-readable text."""
  sev_order = {"clean": 0, "warn": 1, "alert": 2}
  min_sev = "alert"
  if args.warn:
    min_sev = "warn"
  if args.all:
    min_sev = "clean"
  min_idx = sev_order[min_sev]

  if "structure" in report:
    _print_structure(
      report["structure"], target, thresholds, only,
      list_mode=args.list, only_filter=args.only, min_idx=min_idx,
    )
  if "heat" in report and report["heat"]:
    _print_heat(report["heat"], list_mode=args.list)
  if "surface" in report:
    _print_surface(report["surface"], list_mode=args.list)
  if "rot" in report and report["rot"]["items"]:
    _print_rot(report["rot"], list_mode=args.list)
  if "todo" in report and report["todo"]["items"]:
    _print_todo(report["todo"], list_mode=args.list)


def cmd_scan(args: argparse.Namespace) -> None:
  target = os.path.abspath(args.target)
  if not os.path.exists(target):
    print(f"error: {target} does not exist", file=sys.stderr)
    sys.exit(1)

  # Build thresholds with any overrides
  thresholds = dict(DEFAULT_THRESHOLDS)
  for k in ALL_METRICS:
    override = getattr(args, k, None)
    if override is not None:
      thresholds[k] = (override, override)

  # Which metrics to check
  only = ALL_METRICS
  if args.only:
    only = [m.strip() for m in args.only.split(",")]
    bad_names = [m for m in only if m not in DEFAULT_THRESHOLDS]
    if bad_names:
      print(f"error: unknown metrics: {', '.join(bad_names)}", file=sys.stderr)
      print(f"available: {', '.join(ALL_METRICS)}", file=sys.stderr)
      sys.exit(1)

  sections = {"structure"} if args.only else _active_sections(args)

  report = _build_report(
    target, sections, thresholds, only, args.exclude,
    EdgeFilter(args.edge_from, args.edge_to, args.cross),
  )

  if args.json:
    print(json.dumps(report, indent=2))
  else:
    _print_text(report, target, thresholds, only, args)


def cmd_quests(args: argparse.Namespace) -> None:
  target = os.path.abspath(args.target)
  if not os.path.exists(target):
    print(f"error: {target} does not exist", file=sys.stderr)
    sys.exit(1)
  if args.at:
    _cmd_at(target, args)
    return
  turn_in = collect_turn_in(target)
  if turn_in is None:
    print(f"error: {target} is not a git repository", file=sys.stderr)
    sys.exit(1)

  if args.json:
    print(json.dumps({"turn_in": asdict(turn_in)}, indent=2))
  else:
    _print_turn_in(turn_in)


def _cmd_at(root: str, args: argparse.Namespace) -> None:
  path, start, end = parse_target(args.at)
  report = query_at(root, path, start, end)
  if report is None:
    print(f"error: {root} is not a git repository", file=sys.stderr)
    sys.exit(1)
  if args.json:
    print(json.dumps({"at": asdict(report)}, indent=2))
    return
  loc = report.file if start is None else (
    f"{report.file}:{start}" if start == end else f"{report.file}:{start}-{end}")
  print(loc)
  if not report.hits:
    print(f"  nobody here ({report.branches_scanned} live branches scanned)")
    return
  for h in report.hits:
    flag = "⚑" if h.worktree else "○"
    rngs = ",".join(f"{a}" if a == b else f"{a}-{b}" for a, b in h.ranges)
    age = f"{h.age_hours:.0f}h" if h.age_hours is not None else "?"
    where = f"  {h.worktree}" if h.worktree else ""
    line = f"  (line {h.line_in_branch} there)" if h.line_in_branch and start is not None else ""
    print(f"  {flag} {h.branch}  touches {rngs}  {age}{where}{line}")
    if h.worktree and h.line_in_branch and start is not None:
      print(f"      $EDITOR {h.worktree}/{report.file} +{h.line_in_branch}")


def _print_turn_in(t: TurnIn) -> None:
  print("turn in")
  if not t.worktrees and not t.branches:
    print("  nothing to turn in ✓")
  if t.worktrees:
    print("  worktrees")
    for w in t.worktrees:
      label = w.branch or f"(detached {w.head})"
      extra = f"  {w.age}  upstream: {w.upstream}" if w.branch else ""
      print(f"    ✓ {w.path}  {label}  {w.verdict}{extra}")
      if w.branch:
        force = "-d" if w.verdict == "merged" else "-D"
        print(f"        git worktree remove {w.path} && git branch {force} {w.branch}")
      else:
        print(f"        git worktree remove {w.path}")
  if t.branches:
    print("  branches")
    for b in t.branches:
      note = "  (reverted on main? re-merging would change it)" if b.reverted else ""
      print(f"    ✓ {b.branch}  {b.verdict}  {b.age}  upstream: {b.upstream}{note}")
    plain = [b.branch for b in t.branches if b.verdict == "merged"]
    forced = [b.branch for b in t.branches if b.verdict != "merged" and not b.reverted]
    if plain:
      print(f"        git branch -d {' '.join(plain)}")
    if forced:
      print(f"        git branch -D {' '.join(forced)}  # content-merged: not ancestors, force needed")
  if t.triage:
    print("  triage  (branch is done, but its worktree has uncommitted changes)")
    for item in t.triage:
      print(f"    ? {item.path}  {item.branch}  {item.verdict}")
      print(f"        git -C {item.path} status   # inspect, then remove or commit")
  for path in t.skipped_dirty:
    print(f"  · skipped (uncommitted changes): {path}")
  print(f"  · live: {t.live_worktrees} worktrees, {t.live_branches} branches vs {t.default_branch}")


def _add_common_args(p: argparse.ArgumentParser) -> None:
  p.add_argument("target", nargs="?", default=".", help="Directory or file to scan")
  p.add_argument(
    "--exclude", "-x", action="append", default=[],
    help="Directories to exclude (relative to target, repeatable)",
  )


def cmd_annotate(args: argparse.Namespace) -> None:
  from .annotate import AnnotateResult, resolve_target, run_annotate

  target = resolve_target(
    paths=args.paths or None,
    diff=args.diff,
    last=args.last,
    root=os.path.abspath(args.root),
  )
  result = run_annotate(
    os.path.abspath(args.root),
    target,
    port=args.port,
    open_browser=not args.no_open,
  )
  if result is None:
    sys.exit(1)
  print(json.dumps(asdict(result)))


def main() -> None:
  parser = argparse.ArgumentParser(prog="mimir", description="Codebase structural health scanner")
  sub = parser.add_subparsers(dest="command")

  scan_p = sub.add_parser(
    "scan",
    help="Codebase health dashboard",
    formatter_class=argparse.RawDescriptionHelpFormatter,
    description="Scan a codebase and report structural health metrics.",
    epilog="""\
sections:
  structure  per-function complexity metrics + file/class counts
  heat       git churn x complexity — files most likely to produce bugs
  surface    import fan-in/fan-out, directory sprawl
  rot        empty functions, dead code
  todo       TODO/FIXME/HACK/XXX comments, NotImplementedError

function metrics (structure):
  nest       max control-flow nesting depth         warn=4  alert=5
  stmts      statement count                        warn=50 alert=70
  args       parameter count                        warn=5  alert=7
  cc         cyclomatic complexity (branch paths)    warn=10 alert=12
  branches   branch point count (if/for/while/match) warn=10 alert=12
  returns    return statement count (early exits)    warn=4  alert=6

aggregate metrics:
  erosion    fraction of complexity mass in high-CC functions.
             mass(f) = CC(f) * sqrt(SLOC(f)), threshold CC > 10.
             human codebases ~0.31, agent-generated ~0.68.
  rel_heat   commits x max cyclomatic complexity per file.
             relative score for ranking — higher = more dangerous.

examples:
  mimir scan                          full dashboard
  mimir scan --heat                   just heat section
  mimir scan --only cc -v             list functions over CC threshold
  mimir scan --only nest --nest=3 -w  nesting violations at custom threshold
  mimir scan --heat --rot             combine sections
""",
  )
  _add_common_args(scan_p)
  scan_p.add_argument("--json", action="store_true", help="Output as JSON")
  scan_p.add_argument("--list", "-v", action="store_true", help="List individual findings")
  scan_p.add_argument("--warn", "-w", action="store_true", help="Include warn-level findings")
  scan_p.add_argument("--all", "-a", action="store_true", help="Show all functions")

  # Section filters
  scan_p.add_argument("--structure", action="store_true", help="Show only structure section")
  scan_p.add_argument("--heat", action="store_true", help="Show only heat section")
  scan_p.add_argument("--surface", action="store_true", help="Show only surface section")
  scan_p.add_argument(
    "--from", dest="edge_from", metavar="PATH",
    help="Only show import edges originating at this file or directory",
  )
  scan_p.add_argument(
    "--to", dest="edge_to", metavar="PATH",
    help="Only show import edges targeting this file or directory",
  )
  scan_p.add_argument(
    "--cross", action="store_true",
    help="Only show import edges crossing top-level directories",
  )
  scan_p.add_argument("--rot", action="store_true", help="Show only rot section")
  scan_p.add_argument("--todo", action="store_true", help="Show only todo section")

  # Metric filters
  scan_p.add_argument(
    "--only", type=str, default=None,
    help="Comma-separated list of metrics (nest,stmts,args,cc,branches,returns)",
  )
  scan_p.add_argument("--nest", type=int, default=None, help="Override nesting threshold")
  scan_p.add_argument("--stmts", type=int, default=None, help="Override statement count threshold")
  scan_p.add_argument("--args", type=int, default=None, help="Override argument count threshold")
  scan_p.add_argument("--cc", type=int, default=None, help="Override cyclomatic complexity threshold")
  scan_p.add_argument("--branches", type=int, default=None, help="Override branch count threshold")
  scan_p.add_argument("--returns", type=int, default=None, help="Override return count threshold")

  quests_p = sub.add_parser(
    "quests", help="Where pending work stands: merged-but-lingering branches and worktrees",
  )
  quests_p.add_argument("target", nargs="?", default=".", help="Git repository root")
  quests_p.add_argument("--json", action="store_true", help="Output JSON")
  quests_p.add_argument(
    "--at", metavar="FILE[:LINE[-LINE]]", default=None,
    help="Sideways blame: which live branches/worktrees touch this file/range")

  ui_p = sub.add_parser("ui", help="Minimal local web surface (design spike)")
  ui_p.add_argument("target", nargs="?", default=".", help="Git repository root")
  ui_p.add_argument("--port", type=int, default=None)
  ui_p.add_argument("--no-open", action="store_true")

  ann_p = sub.add_parser(
    "annotate",
    help="Annotation gate: open files/diffs in browser, collect feedback as JSON",
    description=(
      "Open files or diffs in the browser for annotation. "
      "Blocks until annotations are submitted, then prints structured JSON to stdout."
    ),
  )
  ann_p.add_argument("paths", nargs="*", help="Files or directories to annotate")
  ann_p.add_argument("--diff", metavar="BRANCH", default=None, help="Show diff vs branch")
  ann_p.add_argument("--last", action="store_true", help="Annotate the last agent message")
  ann_p.add_argument("--root", default=".", help="Git repository root")
  ann_p.add_argument("--port", type=int, default=None)
  ann_p.add_argument("--no-open", action="store_true")

  args = parser.parse_args()
  if args.command == "scan":
    cmd_scan(args)
  elif args.command == "quests":
    cmd_quests(args)
  elif args.command == "ui":
    from .webui import serve_ui
    serve_ui(os.path.abspath(args.target), args.port, not args.no_open)
  elif args.command == "annotate":
    cmd_annotate(args)
  else:
    parser.print_help()


if __name__ == "__main__":
  main()
