"""`kelpie <subcommand> ...`: the one dispatch table. Each entry is `module:function`, imported
only when named, so `kelpie doctor` does not pay for serve's imports. A subcommand's function
takes its own argv; adding one (`bench`, `remote`) is adding a row.

    kelpie serve --model gpt2 --device mps     # also: kelpie --model gpt2 (serve is the default)
    kelpie doctor [--device cuda:A100] [--remote --model openai/gpt-oss-20b]
"""

from __future__ import annotations

import sys
from importlib import import_module

SUBCOMMANDS = {
    "serve": "kelpie_http.sdk.serve:main",
    "build": "kelpie_http.sdk.serve:build_main",
    "cache": "kelpie_http.sdk.serve:cache_main",
    "check": "kelpie_http.sdk.serve:check_main",
    "doctor": "kelpie_http.doctor:main",
}
HELP = ("-h", "--help")
USAGE = """usage: kelpie [SUBCOMMAND] ...   (no subcommand: serve)
    kelpie serve --model gpt2 --device mps
    kelpie doctor [--device cuda:A100] [--remote --model openai/gpt-oss-20b]
    kelpie <subcommand> -h
"""


def main(argv: list[str] | None = None) -> None:
    """Lifecycle verb: whatever the subcommand is (serve runs until interrupted). No leading
    subcommand means serve, so `kelpie --model gpt2` still serves."""
    args = sys.argv[1:] if argv is None else argv
    if args[:1] and args[0] in HELP:
        print(f"{USAGE}\nsubcommands: {', '.join(SUBCOMMANDS)}")
        return
    name, rest = (args[0], args[1:]) if args[:1] and args[0] in SUBCOMMANDS else ("serve", args)
    module, _, function = SUBCOMMANDS[name].partition(":")
    getattr(import_module(module), function)(rest)
