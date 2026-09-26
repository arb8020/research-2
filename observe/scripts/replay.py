"""Replay a finished run into a new file, one line at a time, so the dashboard
sees it arrive live.

Usage:
    python -m observe.scripts.replay runs/long-run.jsonl runs/replay.jsonl
    python -m observe.scripts.replay runs/long-run.jsonl runs/replay.jsonl --delay 0.1
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path

DEFAULT_DELAY_S = 0.020


def replay(
    source: Path,
    target: Path,
    *,
    delay_s: float = DEFAULT_DELAY_S,
    truncate: bool = True,
) -> Iterator[int]:
    """Append source's lines to target with delay_s between them.

    Yields the 1-based count after each line, so a caller can report progress.
    Each line is flushed and fsync-free-but-flushed so a Range poller sees it.
    """
    assert delay_s >= 0.0, f"delay must be non-negative, got {delay_s}"
    if not source.is_file():
        raise FileNotFoundError(f"source run not found: {source}")

    lines = [line for line in source.read_text().splitlines() if line.strip()]
    target.parent.mkdir(parents=True, exist_ok=True)
    mode = "w" if truncate else "a"
    with target.open(mode) as fh:
        for i, line in enumerate(lines, start=1):
            fh.write(line + "\n")
            fh.flush()
            yield i
            if delay_s:
                time.sleep(delay_s)


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    parser.add_argument(
        "--delay", type=float, default=DEFAULT_DELAY_S, help="Seconds between lines"
    )
    parser.add_argument("--append", action="store_true", help="Append instead of truncating")
    args = parser.parse_args(argv)

    progress = replay(args.source, args.target, delay_s=args.delay, truncate=not args.append)
    total = max(progress, default=0)
    print(f"replayed {total} lines -> {args.target}")


if __name__ == "__main__":
    main()
