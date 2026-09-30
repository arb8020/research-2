Run `kelpie doctor` first (`uv run --frozen kelpie doctor` in kelpie-http; `box doctor` from
anywhere in the checkout runs the same thing). In a fresh worktree, `box setup --local` first.

`box` is the repo's GPU CLI (box/cli.py; from the repo root: `uv run --frozen --project box box`,
alias it): sugar over the box SDK, `--provider modal` by default, kelpie's setup as its default
profile (box/kelpie/):

    box setup --local                        # fresh worktree: xgrammar shim, libkelpie, uv sync --frozen
    box run --gpu H100 [--model ID] [--volume kelpie-a1] -- 'python -m scripts.<proof>'
    box run --detach ... -- <cmd>            # prints an id and returns; use this, not tmux
    box logs <id> -f | box who | box kill <id> | box gc [--yes]

kelpie/scripts/modal_run.py is deprecated (a thin wrapper over box run; old flags still work).

## Testing

scripts/test = zig tests + ruff + imports only; the Python test suite is parked until the
seams are re-cut.
Never run model tests on the laptop.
