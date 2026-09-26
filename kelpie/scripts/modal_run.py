"""DEPRECATED: use `box run` (box/cli.py). This file keeps the old flags working for scripts and
agents that still call it; it is a thin wrapper and holds no logic of its own.

    PYTHONPATH=. uv run --no-project --with modal --with requests python kelpie/scripts/modal_run.py \\
        --gpu A100-80GB --model openai/gpt-oss-20b -- 'python -c "import torch; print(torch.cuda.get_device_name())"'

is now

    uv run --frozen --project box box run --gpu A100-80GB --volume kelpie-data \\
        --model openai/gpt-oss-20b -- 'python -c "import torch; print(torch.cuda.get_device_name())"'

Same image contents, mounts, volume layout, streamed output and exit status. Defaults kept:
--gpu A100-80GB, --volume kelpie-data (box run defaults to kelpie-a1). What changed underneath:
setup runs inside the box as its job (box/kelpie/inside.py), so a run whose caller dies ends
with its command instead of idling until its timeout; --log-file gets the job's spans after the
run. Setup's lines and the job's spans now print with the command's output, and the spans
are named box.run / box.inside* (not modal_run*). The words after `--` are joined with spaces and run by bash, as before: quote a command that
has its own quotes or `;` as one argument.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from box.cli import add_run_args, make_provider, make_recipe, run

KELPIE = Path(__file__).resolve().parent.parent


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_run_args(ap, gpu="A100-80GB", volume="kelpie-data")
    args = ap.parse_args()
    args.profile, args.image = "kelpie", None
    return run(make_provider("modal"), make_recipe(args, KELPIE), args, detach=False)


if __name__ == "__main__":
    sys.exit(main())
