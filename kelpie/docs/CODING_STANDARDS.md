# Coding standards

Binds all three Python packages (`kelpie-engine`, `kelpie-models`, `kelpie-http`) and the Zig in
`kelpie-core`. Distilled from `~/research/docs/code_style` (dune, tiger_style, casey, grug,
parse-don't-validate, matklad).

Docs lie, code is truth. Every rule below carries how it is checked:
`[lint]` a tool fails the build, `[test: path]` a test fails, `[review]` a human/agent must look.
`[lint]` today means `mimir audit` (ruff lint + ruff format + pyright + the `[tool.mimir]`
thresholds in `pyproject.toml`); nothing else is mechanical. A rule tagged `[review]` is one we
have not yet found a way to make fail on its own — turning `[review]` into `[lint]`/`[test]` is
always welcome work.

## Design

1. Write the usage code first: the exact Zig calls and the exact Python calls, before any struct. (casey_worst_api) `[review]`
2. Pin both ends: the lowest primitive we control (CUDA driver API, static buffers) and the caller's ideal loop. (outside_in) `[review]`
3. Static allocation at startup; every queue and loop has a fixed bound. Most load-bearing rule for a KV cache. (tiger_style) `[review]`
4. The scheduler runs on its own tick, not per incoming request. (tiger_style) `[review]`
5. One writer per durable value: exactly one owner mutates block refcounts. (dune) `[review]`
6. Parse at the Python boundary into narrow Zig types; the hot path never re-validates. (parse_dont_validate) `[review]`
7. Messy boundary, sharp interior: FFI marshalling lives in one file. (kingdom_tactics) `[lint: tool.mimir boundaries]`
8. Two assertions per function, split, paired across write and read. (tiger_style) `[review]`
9. Crash on an invariant violation; return an error for an operating condition (oversized prompt). (tiger_style) `[review]`
10. Continuous granularity: `generate()` over `step()` over `allocate_blocks()`; never remove a lower rung. (casey_granularity) `[review]`
11. No `Backend` interface until there are two backends. (semantic_compression) `[review]`
12. The Python-facing API names product actions (`submit` / `cancel`), not mechanism. (telos) `[review]`
13. Lifecycle states are named by cause: `preempted`, `cancelled`, `finished_eos`, `finished_length`. (telos) `[review]`
14. No second queue or thread without a named failure mode. (telos, goedecke) `[review]`
15. Push ifs up, fors down; functions <= 70 lines. (tiger_style) `[lint: tool.mimir max-function-lines/max-nesting/max-cyclomatic]`
16. The Python surface is unbreakable once used: additive only. (goedecke) `[test: kelpie-http/tests/contract/test_contract.py]`

## Names

17. A call site must read as pseudocode. If the reader has to go-to-definition to know what a value
    *is*, the name is wrong. `facts_of(m) -> ModelFacts` failed this: "facts" names nothing, and
    the struct was four unrelated values (decision 4). If a value resists naming, it is probably
    several values. `[review]`
18. A value has one name and one writer. No `CHECKPOINT = MODEL_ID` aliases; a constant that
    duplicates a function's default is a second writer of that default. `[review]`

## Types

19. A struct exists only if its fields honestly travel together through the same call chain (casey).
    Otherwise pass the values separately. `[review]`
20. `Any` in a parameter and `-> None` as a return are anti-patterns by default. Each surviving one
    is justified in a comment at the site. (`check-void-returns` is off in `[tool.mimir]` today —
    turning it on is the encoding.) `[review]`

## Comments

21. Delete decision history from code. It belongs in `docs/decisions.md` and the handoffs, where it
    is dated and can be superseded; in a module it goes stale silently. `[review]`
22. A contract stated in prose becomes an assert or a test. "Must agree with X" is a second writer:
    remove the second writer instead of documenting it. `[review]`

## Structure

23. Prefer moving code into a plugin, hook or extension so the core stays small. Models, kernel
    sets, devices and parallelism are plugins; adding one edits one file and no shared root.
    `[lint: tool.mimir max-dir-entries]` `[test: kelpie-models/tests/test_seam.py]`

## Running the gate

    kelpie doctor        # a fresh worktree needs the xgrammar submodule, the built shim
                         # and zig build lib before anything imports; doctor names the
                         # missing ones and the exact command for each
    mimir audit .        # ruff + pyright + style + structure
    scripts/test         # zig tests + ruff (advisory) + every module imported, one per process
    python scripts/check_serve.py   # the endpoint check: one line per row, non-zero on any miss

`scripts/check_serve.py` is the first CHECK FUNCTION: the rows are data (a model, a device,
requests, expected answers), the runner is the only code, and adding a case means adding a row.
A row's expected may be `SOLO` -- run each request alone and require the batched answers to
match -- which needs no golden string and fails exactly when batching leaks between requests.
