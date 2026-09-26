"""Check functions: run a model on the laptop CPU with random weights and assert a property.

Not pytest, not fixtures -- a `check_*` is a plain function that raises on failure and prints a
line on success, so it can be run from a REPL, a script, or a box job. The first one
(`check_batched_equals_single`) is the recurrent rung's: batched step outputs must equal the same
requests run one at a time (docs/brief-slab-pool-recurrent.md step 5).
"""
