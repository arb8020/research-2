# Slab sizing across the ladder (option A + exact tiling, measured 2026-09-10)

Ruling of 2026-09-10 (user), replacing the LCM rule of 2026-09-09 and the "LCM slabs not earned"
call of 09-06. LCM does not survive the ladder: a recurrent group's page is 77 MB (Qwen3-Next) to
449 MB (Kimi-K3) because it sums a state blob over 36-69 layers, while the full-attention page is
~400 KB, and `lcm` of two numbers that far apart is their product over a tiny gcd (147 MB, 2.5 GB).
DSV4 was worse: four near-coprime padded pages, 22 GB. The measurements are kept at the bottom.

## The rule

The slack rule of earlier on 2026-09-10 was itself replaced, later the same day, by the ruling
below; both it and the LCM measurements are kept at the bottom for the record.

**Ruling of 2026-09-10 (user), Jenga's two invariants:**

- **(i) Each group numbers its own pages.** `pageId = slab * pages_per_slab[g] + index + 1`.
  Ids are GROUP-LOCAL: an id means nothing without the group that issued it, and the same number
  in two groups is different memory. Block tables are per group already, so every caller has `g`
  in hand. Page 0 stays the null page of every group.
- **(ii) A slab is tiled exactly.** `pages_per_slab[g] * bytes_per_page[g] == slab_bytes`, with
  no slack. The Zig assert is back to `==`.

Exact tiling is satisfiable -- which the 09-10 slack ruling had concluded it was not -- because
the page is allowed to grow to fit rather than the slab being forced to a common multiple:

1. `slab0` is the largest RAW page over the chosen block sizes.
2. `k_g = floor(slab0 / raw page_g)`: how many of group g's pages a slab holds.
3. `slab_bytes` is `slab0` rounded UP to a multiple of `lcm_g(k_g * 16)`, so every `k_g` divides
   it and every resulting page stays 16-byte aligned.
4. `bytes_per_page[g] = slab_bytes / k_g`, exact by construction and `>=` the raw page.

So the old SLACK becomes per-page PADDING, which is what the 25% guard already measured. Per-group
`block_size` is still searched over [8, 64] (per_seq groups hold one unit per page, block 1), the
block size minimising step 4's padding wins, and among candidates within one percentage point the
SMALLEST block size wins, because prefix-cache grain matters more than the last percent. The
winning slab is the smallest candidate whose padding clears 25% for every group; `ValueError`
names the group and the number when nothing clears it.

Measured on the ladder (the table below): the step-3 rounding grows `slab0` by at most **0.17%**
and worst per-page padding is **8.21%**, both far inside the guards. `SlabPlan.__post_init__`
asserts the exact-tiling identity for every group, so a plan that does not tile cannot be built.

### Why ids had to become group-local, and what it uncovered

Sharing one id space across groups meant the per-page arrays (`blocks`, `tokens`, and the hash
table) were indexed by a raw page id. With group-local ids they are indexed by `base[g] + id`
instead -- each group gets its own stretch, and the null page is slot 0 for everyone.

Making that change surfaced a REAL BUG that had been invisible: the prefix chain hash had no
group in it and the hash table is shared, so a window or per_seq group's `lookup` could find --
and resume on -- ANOTHER group's page. Two traces were encoding that aliasing as expected
behaviour (`prefix_fixpoint.txt`, where the window group resumed on the full group's ids 1,2;
`per_seq_state_prefix_hit.txt`, where the state group's "checkpoint" was the full group's page 2
rather than its own page 4). `prefix.groupSeed(g)` now roots each group's chain in its own index,
so the key spaces cannot collide; `groupSeed(0) == 0`, so a single-group model's hashes and every
trace of one are byte-identical.

Fixing that also exposed `matchSeq` breaking at the first chunk it could not find. A per_seq group
keeps only its newest `n_snapshots` units, so chunk 0's unit is normally already recycled and the
scan died immediately -- it had only ever "worked" by finding another group's page. The chain hash
is pure (fixed by the tokens, not by whether a unit survived), so the walk now continues past an
absent chunk and keeps the newest one it does find, which is the right-to-left scan for the newest
cached checkpoint its own docstring always described.

## The table

Block size searched over [8, 64]; bf16, TP=1, no spec. Raw page is `block_size * sum(member
bytes_per_unit)`; the padded page is `slab_bytes / pages_per_slab`, which the group tiles exactly.
"rounding" is how much step 3 grew `slab0` for that model.

| model | slab_bytes | group | block | raw page | padded page | pages/slab | padding | rounding |
|---|---|---|---|---|---|---|---|---|
| gpt2 | 294,912 (0.28 MB) | F | 8 | 294,912 | 294,912 | 1 | 0.00% | 0.00% |
| Qwen3-0.6B | 917,504 (0.88 MB) | F | 8 | 917,504 | 917,504 | 1 | 0.00% | 0.00% |
| gpt-oss-20b | 196,608 (0.19 MB) | W128 | 8 | 196,608 | 196,608 | 1 | 0.00% | 0.00% |
|  |  | F | 8 | 196,608 | 196,608 | 1 | 0.00% | 0.00% |
| GLM-5.2 | 771,072 (0.74 MB) | F | 8 | 771,072 | 771,072 | 1 | 0.00% | 0.00% |
| Qwen3-Next-80B | 77,266,944 (73.69 MB) | F | 8 | 196,608 | 196,608 | 393 | 0.00% | 0.00% |
|  |  | per_seq s0 | 1 | 77,266,944 | 77,266,944 | 1 | 0.00% | 0.00% |
| Kimi-K3 | 449,381,184 (428.56 MB) | F | 17 | 470,016 | 470,064 | 956 | 0.01% | 0.00% |
|  |  | per_seq s0 | 1 | 449,372,160 | 449,381,184 | 1 | 0.00% | 0.00% |
| DeepSeek-V4-Flash | 3,294,720 (3.14 MB) | W128 (nc) | 8 | 205,568 | 205,920 | 16 | 0.17% | 0.17% |
|  |  | C128 | 8 | 102,784 | 102,960 | 32 | 0.17% | 0.17% |
|  |  | per_seq s128 | 1 | 3,289,088 | 3,294,720 | 1 | 0.17% | 0.17% |
|  |  | C4 | 8 | 126,016 | 126,720 | 26 | 0.56% | 0.17% |
|  |  | per_seq s4 | 1 | 504,064 | 549,120 | 6 | 8.21% | 0.17% |

Worst padding on the ladder is 8.21% (DSV4's stride-4 compressor ring, whose fixed 504,064 B page
is the one that fits a slab least evenly) and worst rounding 0.17%, both well inside the guards.
No model needs a STOP. Every row tiles its slab exactly: `padded page * pages/slab == slab_bytes`.

The two big slabs are the two recurrent models, and there the slab is exactly the R page: a slab
holds one sequence's recurrent state, and the F group carves 393 (Qwen3-Next) or 2031 (K3) pages out
of a slab of the same size. That is the shape the pool was built for -- one arena, one LRU, no
static partition between F and R.

DeepSeek-V4-Flash has **five** groups, not the four of the earlier "As built" note: the CSA/HCA
compressor rings are per_seq groups at `stride = ratio` now (step 5), and stride is part of the
group key, so the stride-4 and stride-128 rings no longer merge. See docs/cache-groups-ladder.md.

## Superseded: slack, and the LCM measurements

The intermediate rule (option A + slack) let `pages_per_slab[g] = floor(slab_bytes / page)` leave
a tail too small for one more page, on the grounds that DSV4's two near-coprime per_seq pages made
exact tiling unsatisfiable. It is unsatisfiable only if the PAGE is held fixed and the SLAB has to
absorb the mismatch; growing each page to `slab_bytes / k_g` instead costs 8.21% on that one group
and nothing anywhere else, and buys back the invariant that a page id maps to memory by
multiplication alone -- which is what makes the Python-side `as_strided` arena views possible.

For the record, `slab_bytes = lcm_g(padded page_g)` at block 16, which is what sent this back for a
ruling: gpt-oss-20b 384 KB, GLM-5.2 1.43 MB, Qwen3-Next 147.4 MB, Kimi-K3 2.51 GB, DeepSeek-V4-Flash
21.96 GB. Pad-to-max is not the fallback either: it would inflate Qwen3-Next's F page from 393 KB to
77 MB, a 196x blow-up strictly worse than a static partition. Option A avoids both by letting a slab
hold many pages of a small group.

## Open: K (max_spec_tokens) has no way into the core

Step 7 of docs/brief-slab-pool-recurrent.md asked for spec-sized rings and windows "without an
ABI change", baking K into existing per-group fields at config time. It does not fit, and step 8
(draft plumbing) plus step 4's rule (d) (reserve K+1 units, commit keeps `accepted`) are blocked
behind the same gap:

- `group_windows[g] = W + K` is unrecoverable: the core receives only the sum and never learns W
  (a window group) or the 2 (a per_seq group) on its own. Both are model-side numbers.
- Three ladder models -- gpt2, Qwen3-0.6B, GLM-5.2 -- have no window group and no checkpointing
  per_seq group, so there is no field carrying K for them at all.
- `group_windows` is also the live-retention number `slideOut` / `firstLiveRow` / `windowRows`
  free rows by; overloading it to mean W+K silently changes that arithmetic.
- `max_seq_len` would size token storage correctly (`request.Pool` already does
  `max_seq_len + n_draft`) but corrupts the `TooLong` admission bound, which must stay
  `prompt + max_new <= max_seq_len`.

K is one number per engine, not per group. The field needed is `KelpieConfig.n_draft` (u32,
appended, default 0) feeding `request.Config.n_draft`, which already exists and is already read
by `request.Pool.init` and `scheduler.commitEntry` -- the same additive-ABI shape
`group_strides`, `vocab_words` and `group_bytes_per_page` already use.

## Owed: roll()-based check rows

`kelpie_models/sdk/checks/recurrent_batching.py` proves batched == single-request on a
self-contained `TinyRecurrent` (one recurrent layer over a per_seq page view) rather than on
`roll(Qwen3-Next config)` and `roll(gpt-oss-20b config)` as step 5 asked. The two rolled models
were not reachable at the time: `qwen3_next.py` is unported and raises at first use, and
`gpt_oss.py` sits in the ports branch's migration path.

**Owed after the ports branch merges**: the same `check_batched_equals_single` driven by
`roll(Qwen3-Next config)` with the reference `chunk_gated_delta_rule` as the op's default body,
and by `roll(gpt-oss-20b config)` for F + W128 across slabs, over prefill -> decode -> a prefix
hit -> K = 4 drafts (all four now exist in the core).
