"""mimir CLI — codebase structural health scanner."""

from __future__ import annotations

import argparse
import os
import sys

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
  explicit = {s for s in SECTIONS if getattr(args, s, False)}
  return explicit if explicit else set(SECTIONS)


def cmd_scan(args: argparse.Namespace) -> None:
  target = os.path.abspath(args.target)
  if not os.path.exists(target):
    print(f"error: {target} does not exist", file=sys.stderr)
    sys.exit(1)

  out = sys.stderr

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

  # --only implies --structure (only show the filtered function metrics)
  if args.only:
    sections = {"structure"}
  else:
    sections = _active_sections(args)

  # Filter severity
  min_sev = "alert"
  if args.warn:
    min_sev = "warn"
  if args.all:
    min_sev = "clean"
  sev_order = {"clean": 0, "warn": 1, "alert": 2}
  min_idx = sev_order[min_sev]

  # -- structure --
  if "structure" in sections:
    fn_metrics, cls_metrics = scan_dir(target, exclude=args.exclude)
    file_metrics = scan_file_lengths(target, exclude=args.exclude)

    shown_fns = [
      m for m in fn_metrics
      if sev_order[_line_severity(m, thresholds, only)] >= min_idx
    ]
    shown_fns.sort(key=lambda m: (
      -max(_bad_metrics(m, thresholds, only).values()) if _bad_metrics(m, thresholds, only) else 0,
      m.file, m.line,
    ))

    long_files = sorted(
      [f for f in file_metrics if f.lines >= LONG_FILE_THRESHOLD],
      key=lambda f: -f.lines,
    )
    wide_classes = sorted(
      [c for c in cls_metrics if c.field_count > FIELD_THRESHOLD],
      key=lambda c: -c.field_count,
    )

    if args.list:
      for m in shown_fns:
        print(_format_fn_line(m, target, thresholds, only))
      if not args.only:
        for f in long_files:
          print(f"{os.path.relpath(f.file, target)}  lines={f.lines}")
        for c in wide_classes:
          print(f"{c.name}  {os.path.relpath(c.file, target)}:{c.line}  fields={c.field_count}")

    def fn_alert_count(metric: str) -> int:
      _, alert_t = thresholds[metric]
      return sum(1 for m in fn_metrics if _metric_val(m, metric) >= alert_t)

    if not (args.only and args.list):
      erosion = structural_erosion(fn_metrics)

      print("structure", file=out)
      print(f"  functions  {len(fn_metrics)}", file=out)
      for k in only:
        n = fn_alert_count(k)
        if n > 0:
          print(f"    {k}  {n}", file=out)
      print(f"  erosion  {erosion:.2f}", file=out)
      print(f"  files  {len(file_metrics)}", file=out)
      if long_files:
        print(f"    long  {len(long_files)}", file=out)
      print(f"  classes  {len(cls_metrics)}", file=out)
      if wide_classes:
        print(f"    wide  {len(wide_classes)}", file=out)

  # -- heat --
  if "heat" in sections:
    from .heat import compute_heat
    heat_results = compute_heat(target, exclude=args.exclude)

    if args.list:
      for h in heat_results:
        print(f"{h.file}  commits={h.commits}  max_cc={h.max_cc}  rel_heat={h.heat:.0f}")

    if heat_results:
      print("heat", file=out)
      for h in heat_results[:5]:
        print(
          f"  {h.file}  commits={h.commits}  max_cc={h.max_cc}  rel_heat={h.heat:.0f}",
          file=out,
        )
      if len(heat_results) > 5:
        print(f"  ... {len(heat_results) - 5} more", file=out)

  # -- surface --
  if "surface" in sections:
    from .imports import scan_imports
    import_metrics = scan_imports(target, exclude=args.exclude)

    HIGH_FAN_OUT = 10
    HIGH_FAN_IN = 15
    high_fan_out = sorted(
      [m for m in import_metrics if m.fan_out >= HIGH_FAN_OUT],
      key=lambda m: -m.fan_out,
    )
    high_fan_in = sorted(
      [m for m in import_metrics if m.fan_in >= HIGH_FAN_IN],
      key=lambda m: -m.fan_in,
    )

    # Directory sprawl
    DIR_THRESHOLD = 10
    dir_counts: dict[str, int] = {}
    for m in import_metrics:
      d = os.path.dirname(m.file) or "."
      dir_counts[d] = dir_counts.get(d, 0) + 1
    wide_dirs = sorted(
      [(d, n) for d, n in dir_counts.items() if n > DIR_THRESHOLD],
      key=lambda x: -x[1],
    )

    if args.list:
      for m in high_fan_out:
        print(f"{m.file}  fan_out={m.fan_out}")
      for m in high_fan_in:
        print(f"{m.file}  fan_in={m.fan_in}")
      for d, n in wide_dirs:
        print(f"{d}/  files={n}")

    if high_fan_out or high_fan_in or wide_dirs:
      print("surface", file=out)
      if high_fan_out:
        print(f"  high_fan_out  {len(high_fan_out)}", file=out)
      if high_fan_in:
        print(f"  high_fan_in  {len(high_fan_in)}", file=out)
      if wide_dirs:
        print(f"  wide_dirs  {len(wide_dirs)}", file=out)

  # -- rot --
  if "rot" in sections:
    from .rot import scan_rot_dir
    rot_findings = scan_rot_dir(target, exclude=args.exclude)

    rot_by_kind: dict[str, int] = {}
    for f in rot_findings:
      rot_by_kind[f.kind] = rot_by_kind.get(f.kind, 0) + 1

    if args.list:
      for f in rot_findings:
        print(f"rot:{f.kind}  {os.path.relpath(f.file, target)}:{f.line}  {f.detail}")

    if rot_findings:
      print("rot", file=out)
      for kind in sorted(rot_by_kind):
        print(f"  {kind}  {rot_by_kind[kind]}", file=out)

  # -- todo --
  if "todo" in sections:
    from .todo import scan_todo_dir
    todo_findings = scan_todo_dir(target, exclude=args.exclude)

    todo_by_kind: dict[str, int] = {}
    for f in todo_findings:
      todo_by_kind[f.kind] = todo_by_kind.get(f.kind, 0) + 1

    if args.list:
      for f in todo_findings:
        print(f"todo:{f.kind}  {os.path.relpath(f.file, target)}:{f.line}  {f.detail}")

    if todo_findings:
      print("todo", file=out)
      for kind in sorted(todo_by_kind):
        print(f"  {kind}  {todo_by_kind[kind]}", file=out)


def _add_common_args(p: argparse.ArgumentParser) -> None:
  p.add_argument("target", nargs="?", default=".", help="Directory or file to scan")
  p.add_argument(
    "--exclude", "-x", action="append", default=[],
    help="Directories to exclude (relative to target, repeatable)",
  )


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
  scan_p.add_argument("--list", "-v", action="store_true", help="List individual findings")
  scan_p.add_argument("--warn", "-w", action="store_true", help="Include warn-level findings")
  scan_p.add_argument("--all", "-a", action="store_true", help="Show all functions")

  # Section filters
  scan_p.add_argument("--structure", action="store_true", help="Show only structure section")
  scan_p.add_argument("--heat", action="store_true", help="Show only heat section")
  scan_p.add_argument("--surface", action="store_true", help="Show only surface section")
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

  args = parser.parse_args()
  if args.command == "scan":
    cmd_scan(args)
  else:
    parser.print_help()


if __name__ == "__main__":
  main()
