Run `kelpie doctor` first (`uv run --frozen kelpie doctor` in kelpie-http, or
`uv run --frozen --project kelpie/kelpie-http kelpie doctor` from the repo root). In a fresh
worktree, `kelpie setup-local` first.

kelpie's dev tooling is `kelpie` subcommands (kelpie_http/dev/); remote runs use the box SDK
(box/sdk.py) on Modal, with kelpie's image, setup and volume (/data) all owned here:

    kelpie setup-local                       # fresh worktree: xgrammar shim, libkelpie, uv sync --frozen
    kelpie remote --gpu H100 [--model ID] [--volume kelpie-a1] [--timeout S] -- 'python -m scripts.<proof>'
    kelpie remote --detach ... -- <cmd>      # prints an id and returns; use this, not tmux
    kelpie gc [--yes]                        # stale build keys / run logs on kelpie-* volumes, local shims

Then `box logs <id> -f | box who | box kill <id>` (`box` = `uv run --frozen --project box box`
from the repo root) follow, list and stop runs.

## Testing

scripts/test = zig tests + ruff + imports only; the Python test suite is parked until the
seams are re-cut. kelpie_http/dev's pure tests run in box's environment, from the repo root:
`PYTHONPATH=kelpie/kelpie-http uv run --frozen --project box --extra dev python -m pytest kelpie/kelpie-http/kelpie_http/dev -q`.
Never run model tests on the laptop.
