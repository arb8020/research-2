#!/usr/bin/env python3
"""Warm the HF hub cache from scripts/hf-models.txt (docs/audit-tests.md 4.4).

    uv run scripts/hf_warm.py [--dry-run] [--list PATH]

Remote runs use HF_HUB_OFFLINE=1, so every hub artifact a test reads has to be in
~/.cache/huggingface before the run; this is the one place that knows the list.  Run it on the
remote host before the suites; on a Mac the same command warms the laptop.  A miss is never an
error here: no network, a gated repo without a token, a repo renamed on the hub -- each prints
one line and the rest of the list still runs, and the tests report the gap as a `needs hf:<repo>`
skip.  --dry-run prints, per row, what would be fetched
and whether the cache already has it.

Needs kelpie-models' environment (huggingface_hub, and kelpie_models.sdk.hf for the `@layers=N`
rows); plain `uv run scripts/hf_warm.py` re-executes itself under `uv run --project
kelpie-models` when it is not already there.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LIST = ROOT / "scripts" / "hf-models.txt"
KINDS = ("config", "tokenizer", "weights")

# What each kind pulls (huggingface_hub fnmatch, `*` crosses `/`) and the file whose presence
# in the cache means the row is already warm.  `model*.safetensors`, not `*.safetensors`:
# gpt-oss-20b ships a second full copy under original/.
SMALL = ("*.json", "*.jinja", "*.py", "*.model", "*.txt", "*.tiktoken")
PATTERNS: dict[str, tuple[str, ...]] = {
    "config": ("config.json",),
    "tokenizer": SMALL,
    "weights": (*SMALL, "model*.safetensors"),
}
# Subtrees no test reads: format duplicates (gpt2's onnx/, gpt-oss-20b's original/ and metal/)
# and DeepSeek-V3.2's reference inference/ + assets/.  Its encoding/*.py IS read
# (test_render_parity), so this is a deny list, not "top level only".
IGNORE = ("onnx/*", "original/*", "metal/*", "inference/*", "assets/*")
PROBE: dict[str, tuple[str, ...]] = {
    "config": ("config.json",),
    "tokenizer": ("config.json", "tokenizer_config.json"),
    "weights": ("config.json", "tokenizer_config.json", "model.safetensors|model.safetensors.index.json"),
}


def in_models_env() -> bool:
    try:
        import huggingface_hub  # noqa: F401
        import kelpie_models.sdk.hf  # noqa: F401
    except ImportError:
        return False
    return True


def reexec_under_kelpie_models() -> int:
    cmd = ["uv", "run", "--project", str(ROOT / "kelpie-models"), "python", __file__, *sys.argv[1:]]
    print(f"hf_warm: not in kelpie-models' env; re-running as: {' '.join(cmd[:5])} ...", file=sys.stderr)
    env = {**os.environ, "UV_CACHE_DIR": os.environ.get("UV_CACHE_DIR", "/tmp/kelpie-uv-cache")}
    return subprocess.call(cmd, env=env)


def parse_list(path: Path) -> list[tuple[str, str]]:
    """[(repo, kind)], `#` comments and blank lines dropped; a malformed line is an error (the
    list is checked in, so that is a code failure, not a cache miss)."""
    rows: list[tuple[str, str]] = []
    for n, raw in enumerate(path.read_text().splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 2 or parts[1] not in KINDS:
            sys.exit(f"{path}:{n}: expected `<repo> <{'|'.join(KINDS)}>`, got {raw!r}")
        rows.append((parts[0], parts[1]))
    assert rows, path
    return rows


def split_layers(repo: str) -> tuple[str, int | None]:
    if "@layers=" in repo:
        base, n = repo.split("@layers=", 1)
        return base, int(n)
    return repo, None


def cached(repo: str, kind: str) -> list[str]:
    """The probe files this row still lacks in the local cache ([] = warm)."""
    from huggingface_hub import try_to_load_from_cache

    base, n = split_layers(repo)
    if n is not None:
        from kelpie_models.sdk.hf import TRUNCATED_ROOT

        d = TRUNCATED_ROOT / f"{base.replace('/', '--')}--layers-{n}"
        return [str(d / f) for f in ("config.json", "model.safetensors") if not (d / f).exists()]
    missing = []
    for alt in PROBE[kind]:
        if not any(isinstance(try_to_load_from_cache(base, f), str) for f in alt.split("|")):
            missing.append(alt)
    return missing


def n_files(repo: str) -> int:
    """Files in the repo's cached snapshots (0 when never fetched): the before/after of a warm."""
    from huggingface_hub.constants import HF_HUB_CACHE

    d = Path(HF_HUB_CACHE) / f"models--{repo.replace('/', '--')}" / "snapshots"
    return sum(len(fs) for _, _, fs in os.walk(d)) if d.is_dir() else 0


def warm(repo: str, kind: str) -> int:
    """snapshot_download the row's patterns (it fetches only what the cache lacks, so a warm
    row costs one revision lookup); for `@layers=N`, the small files plus the truncated
    checkpoint kelpie_models.sdk.hf builds (its own cache under TRUNCATED_ROOT).  -> new files."""
    from huggingface_hub import snapshot_download

    base, n = split_layers(repo)
    patterns = PATTERNS["tokenizer" if n is not None else kind]
    before = n_files(base)
    snapshot_download(base, allow_patterns=list(patterns), ignore_patterns=list(IGNORE))
    if n is not None:
        from kelpie_models.sdk.hf import resolve_truncated

        resolve_truncated(base, n)
    return n_files(base) - before


def why_skipped(e: Exception) -> str | None:
    """A one-line reason when the failure is the environment, not the code; None re-raises."""
    from huggingface_hub import errors as hf_errors

    if isinstance(e, hf_errors.OfflineModeIsEnabled):
        return "HF_HUB_OFFLINE=1 (unset it to warm)"
    if isinstance(e, hf_errors.GatedRepoError):
        return "gated repo, no token (huggingface-cli login)"
    if isinstance(e, hf_errors.RepositoryNotFoundError):
        return "repo not found on the hub (renamed? private?)"
    if isinstance(e, hf_errors.LocalEntryNotFoundError | ConnectionError | OSError):
        return f"no hub access: {type(e).__name__}: {str(e).splitlines()[0][:120]}"
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="print the plan and the cache state, fetch nothing")
    ap.add_argument("--list", type=Path, default=DEFAULT_LIST)
    args = ap.parse_args()
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")  # one line per row, not a tqdm bar
    if not in_models_env():
        return reexec_under_kelpie_models()

    rows = parse_list(args.list)
    from huggingface_hub.constants import HF_HUB_CACHE

    print(f"hf_warm: {len(rows)} rows from {args.list} (cache: {HF_HUB_CACHE})")
    if os.environ.get("HF_HUB_OFFLINE") == "1" and not args.dry_run:
        print("hf_warm: skipped -- HF_HUB_OFFLINE=1 in this environment; nothing can be fetched")
        return 0
    warmed = missed = seen = 0
    for repo, kind in rows:
        seen += 1
        lacking = cached(repo, kind)
        state = "cached" if not lacking else f"missing {', '.join(lacking)}"
        if args.dry_run:
            pats = "truncated checkpoint + " + " ".join(SMALL) if "@layers=" in repo else " ".join(PATTERNS[kind])
            print(f"  {repo:44s} {kind:9s} {state}  <- {pats}")
            continue
        # Always ask the hub, even when the probe files are cached: the probe is a lower bound
        # (one host had DeepSeek-V3.2's tokenizer but not its encoding/*.py), the download is a no-op
        # for files already present.
        try:
            new = warm(repo, kind)
        except Exception as e:  # noqa: BLE001 -- a warm miss must not fail setup
            reason = why_skipped(e)
            if reason is None:
                raise
            print(f"  {repo:44s} {kind:9s} SKIPPED: {reason}")
            missed += 1
            if "no hub access" in reason:
                print("hf_warm: no hub access from this machine; warm where the network is and stop here")
                break
            continue
        if new == 0 and not lacking:
            print(f"  {repo:44s} {kind:9s} cached")
            continue
        warmed += 1
        print(f"  {repo:44s} {kind:9s} warmed (+{new} files; {state} before)")
    if not args.dry_run:
        tail = f", {len(rows) - seen} not attempted" if seen < len(rows) else ""
        print(f"hf_warm: done -- {warmed} warmed, {missed} skipped, {seen - warmed - missed} already cached{tail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
