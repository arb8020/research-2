/* kelpie-core C ABI. Hand-written; mirrors kelpie-core/src/c_api.zig. Additive-only once used. */
#ifndef KELPIE_H
#define KELPIE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct KelpieEngine KelpieEngine; /* opaque: owns request pool + kv pool + scheduler */

enum { KELPIE_GROUP_PER_TOKEN = 0, KELPIE_GROUP_PER_SEQ = 1 };
enum { KELPIE_ORDER_RUNNING_FIRST = 0, KELPIE_ORDER_WAITING_FIRST = 1 };
enum {
    KELPIE_STATE_WAITING = 0,
    KELPIE_STATE_RUNNING = 1,
    KELPIE_STATE_FINISHED_EOS = 2,
    KELPIE_STATE_FINISHED_LENGTH = 3,
    KELPIE_STATE_CANCELLED = 4,
    /* Appended: the request's grammar matcher rejected the sampled token (native-loop grammar
     * support, kelpie_register_grammar + a submit's grammar_key). See request.zig
     * State.grammar_dead_end. */
    KELPIE_STATE_GRAMMAR_DEAD_END = 5
};
enum { KELPIE_SUBMIT_FULL = -1, KELPIE_SUBMIT_TOO_LONG = -2, KELPIE_SUBMIT_BAD_ARGS = -3, KELPIE_SUBMIT_DRAINING = -4, KELPIE_SUBMIT_EXCEEDS_KV_POOL = -5,
       KELPIE_SUBMIT_NOT_EDGE = -6, /* submit/cancel/set/swap on a follower rank (kelpie_register_sync) */
       KELPIE_SUBMIT_BAD_TOP_K = -7 /* kelpie_submit_top_k: top_k > vocab_size */ };

/* TODO(2026-09-10): config_hash / slab_bytes / num_slabs are out-only fields inside an input struct;
 * move them to a KelpieConfigOut filled by kelpie_get_config next time the ABI moves (handoff debt 5). */
typedef struct KelpieConfig {
    uint32_t max_requests;
    uint32_t max_seq_len;
    uint32_t n_groups;
    const uint32_t *group_kinds;       /* [n_groups], KELPIE_GROUP_* */
    const uint32_t *group_block_sizes; /* [n_groups]; ignored for per_seq */
    const uint32_t *group_windows;     /* [n_groups]; per_token: 0 = keep all, W = sliding window of W tokens;
                                        * per_seq: checkpoints kept per request (0 iff stride 0) */
    const uint8_t *group_cacheable;    /* [n_groups]; 0/1, may blocks enter the prefix index */
    uint32_t num_blocks;               /* includes null block 0; num_blocks - 1 are allocatable */
    uint32_t max_batch_tokens;
    uint32_t max_batch_reqs;
    float reserve_ratio;
    uint32_t order; /* KELPIE_ORDER_* */
    uint32_t eos_token;
    uint32_t prefix_cache; /* 0/1: match prompts against cached KV blocks at admission */
    uint64_t config_hash;  /* out only (kelpie_get_config): hash of the live config; ignored by kelpie_create */
    const uint32_t *group_strides; /* [n_groups] per_token: tokens per cache unit (1 = every token);
                                    * per_seq: checkpoint interval S (0 = never); NULL = 1 / 0 */
    uint32_t overlap; /* 0/1: startup-only tier-2 plan/commit protocol choice; not a live knob */
    /* Row width of KelpiePlan.logit_mask: ceil(vocab/32), the model's padded logits width.
     * 0 = grammar support disabled (a submit naming a grammar is refused, logit_mask stays NULL). */
    uint32_t vocab_words;
    /* [n_groups] bytes one page of each group costs, padded to the 4 KB quantum by Python's
     * kelpie_models.groups.choose_block_sizes (docs/slab-lcm-ladder.md). A slab holds
     * floor(slab_bytes / group_bytes_per_page[g]) pages of group g; the tail too small for one
     * more page is slack. NULL = legacy one-tensor-per-group mode: equal pages, one per slab. */
    const uint32_t *group_bytes_per_page;
    uint32_t slab_bytes; /* out only (kelpie_get_config): bytes per slab */
    uint32_t num_slabs;  /* out only (kelpie_get_config): slabs in the pool */
    /* Kmax: the most extra rows a decode-shaped entry may carry after its history row -- rows
     * whose input_ids the caller fills (a drafter's drafts). 0 = none. Sizes the per_seq write
     * units (1 + Kmax per request). Renamed from n_draft, same offset. With max_extra > 0,
     * overlap must be 0. */
    uint32_t max_extra;
    /* The model's vocabulary size: kelpie_commit rejects a kept id >= vocab_size with
     * KELPIE_ERR_TOKEN. 0 = unchecked (KELPIE_NO_TOKEN is always rejected). Appended. */
    uint32_t vocab_size;
} KelpieConfig;

/* Bumped on every NON-additive ABI change; a binding must refuse a library whose
 * kelpie_abi_version() differs. 2: KelpieCommit became {n_entries, stride, tokens, n_tokens,
 * next_extra} (was {n_entries, tokens, n_tokens, drafts, n_drafts}: 40 -> 32 bytes, fields
 * renumbered) and kelpie_commit(const KelpieCommit *) replaced kelpie_commit(sampled, n) and
 * kelpie_commit_payload. The plan/config/event renames (n_drafts -> n_extra etc.) kept offsets. */
/* 3 (docs/design-multigpu.md 2.2): KelpieLaunchFn / KelpieLaunchWaitFn write a KelpieStepOut
 * (n tokens per entry) instead of uint32_t tokens_out[n_reqs]; kelpie_submit_mm_stop gained
 * grammar_key and kelpie_attach_grammar is gone (kelpie_register_grammar); KelpiePlan.digest
 * appended; kelpie_register_sync. Semantics: submit / cancel / set / swap and a poll's release
 * are inbox ops applied at the next step boundary (kelpie_plan, or the loop's). */
#define KELPIE_ABI_VERSION 3u
uint32_t kelpie_abi_version(void);

/* An extra row's input_id: the caller fills it (0 is a real vocab id). */
#define KELPIE_NO_TOKEN 0xFFFFFFFFu
/* Unit 0 of every per_seq group: writable, never read. A write nobody keeps lands here. */
#define KELPIE_UNIT_SCRATCH 0u
/* state_ckpt_row when the step writes no checkpoint. */
#define KELPIE_NO_ROW 0xFFFFFFFFu

/* Live-config knobs (kelpie_set). All tier 0: applied at the step boundary before the next plan. */
enum {
    KELPIE_KNOB_ORDER = 0,            /* u32_value: KELPIE_ORDER_* */
    KELPIE_KNOB_RESERVE_RATIO = 1,    /* f32_value */
    KELPIE_KNOB_MAX_BATCH_TOKENS = 2, /* u32_value, <= the create-time value */
    KELPIE_KNOB_MAX_BATCH_REQS = 3,   /* u32_value, <= the create-time value */
    KELPIE_KNOB_PREFIX_CACHE = 4      /* u32_value: 0/1 */
};

typedef struct KelpieKnob {
    uint32_t kind; /* KELPIE_KNOB_* */
    uint32_t u32_value;
    float f32_value;
} KelpieKnob;

typedef struct KelpieSetResult {
    uint64_t apply_step;  /* the step whose plan applies this knob: exact (the inbox numbers boundaries) */
    uint64_t config_hash; /* hash of the config once everything queued so far has applied */
} KelpieSetResult;

/* Raw pointers into engine-owned buffers. Valid until the next kelpie_plan / kelpie_commit / kelpie_destroy. */
typedef struct KelpiePlan {
    uint32_t n_reqs;
    uint32_t n_tokens;
    uint32_t n_groups;
    const uint32_t *req_ids;            /* [n_reqs] */
    const uint32_t *n_work;             /* [n_reqs] */
    const uint32_t *input_ids;          /* [n_tokens] */
    const uint32_t *positions;          /* [n_tokens] */
    const uint32_t *query_start_loc;    /* [n_reqs + 1] */
    const uint32_t *seq_lens;           /* [n_reqs] */
    const uint32_t *const *slot_mapping;  /* [n_groups][n_tokens] */
    const uint32_t *const *block_tables;  /* [n_groups][n_reqs * max_blocks_per_req[g]] */
    const uint32_t *max_blocks_per_req; /* [n_groups] */
    const float *temperatures;          /* [n_reqs] sampling temperature per planned request */
    const uint64_t *mm_hashes;          /* [n_reqs] multimodal content hash per planned request; 0 = text only */
    const uint32_t *kinds;              /* [n_reqs] KELPIE_KIND_*: what each entry is; never inferred from n_work */
    const uint32_t *n_extra;            /* [n_reqs] extra rows after the entry's n_work history rows (was n_drafts) */
    /* [n_reqs, cfg.vocab_words] int32, one row per planned entry in plan order: bit v of word
     * v/32 set = token v allowed for that entry's next sample. All-ones for an entry with no
     * grammar attached. Filled by kelpie_plan between plan and whatever the caller does next
     * (the forward). NULL iff cfg.vocab_words == 0. */
    const int32_t *logit_mask;
    uint64_t step;
    /* Padded plan (appended: additive ABI). Every array above is bucket-sized; n_reqs/n_tokens
     * say how much of it is real. The core is the only padder -- Python's fill and launch.c
     * copy these arrays verbatim and decide nothing (docs/friction-2026-09-09.md section 1).
     *
     * Pad rows [n_tokens, n_tokens_padded): input_ids 0, positions 0, slot_mapping[g] = the
     * scratch slot (last slot of null block 0; never -1), row_request -1.
     * Pad entries [n_reqs, n_reqs_padded): query_start_loc repeats n_tokens (an empty query),
     * seq_lens 1, block_tables[g] row all zeros (the null block), kinds KELPIE_KIND_PREFILL,
     * n_extra 0, temperatures 1 / top_ks 1 (greedy in the T=0 rule's form, so an all-greedy
     * batch is all-greedy over its padded width), mm_hashes 0, req_ids 0, logit_mask row all ones, seq_start 0,
     * emits 0, per_seq state reading ZERO and writing SCRATCH with ckpt_row KELPIE_NO_ROW.
     * A per_seq group's pad slot_mapping is 0.
     * Every pad is inert by value (docs/model-contract.md section 2). */
    uint32_t n_reqs_padded;
    uint32_t n_tokens_padded;
    const int32_t *row_request; /* [n_tokens_padded] owning request index per row; -1 = pad */
    /* Deterministic program-selection key derived only from this plan (see c_api.zig stepShape()
     * for the exact bit packing: padded_num_tokens bucket idx | padded_num_reqs bucket idx << 8 |
     * has_prefill << 12 | K << 16). A native launch fn may ignore it and recompute the same value
     * from `plan` itself -- Zig and Python must never disagree. mode/dtype/flags
     * (kelpie_models.plan.StepShape) are per-CapturedModel constants fixed at capture time and
     * never travel on this wire (docs/m2-zig-loop.md). */
    uint32_t shape;
    /* The spec-agnostic core API (appended; docs/design-core-option2.md 2.3). Entry r's rows are
     * n_work[r] history rows, then n_extra[r] extra rows (input_ids KELPIE_NO_TOKEN). Tail row j
     * of an entry is its row n_work - 1 + j, j in [0, n_extra]. */
    const uint32_t *seq_start;  /* [n_reqs_padded] tokens already in context; rows start at this position */
    const uint8_t *emits;       /* [n_reqs_padded] 1 iff commit keeps the entry's tokens (not a mid-prefill chunk) */
    uint32_t max_extra;         /* Kmax: state_write rows are 1 + max_extra wide */
    const uint32_t *zero_unit;  /* [n_groups] ZERO(g) of a per_seq group (the always-zero unit); 0 for per_token */
    /* Per group; NULL for a per_token group. Op contract per entry r of a per_seq group:
     *   s = pool[read[r]]; for each row i: update s;
     *   if i is tail row j: pool[write[r * (1 + max_extra) + j]] = s;  if i == ckpt_row[r]: pool[ckpt[r]] = s.
     * write columns past n_extra[r] are KELPIE_UNIT_SCRATCH, as is ckpt when there is none. */
    const uint32_t *const *state_read;     /* [n_groups][n_reqs_padded] */
    const uint32_t *const *state_write;    /* [n_groups][n_reqs_padded * (1 + max_extra)] */
    const uint32_t *const *state_ckpt;     /* [n_groups][n_reqs_padded] */
    const uint32_t *const *state_ckpt_row; /* [n_groups][n_reqs_padded], from the entry's first row */
    /* Wyhash of this plan (scheduling content, the batch applied before it, the previous
     * commit's payload; never logit_mask): equal on every rank that planned the same step. Set
     * for an idle plan too. ABI 3. */
    uint64_t digest;
    /* [n_reqs_padded] sample from the top_k most likely tokens; 0 = the whole vocabulary, 1 =
     * greedy (appended: additive ABI). The caller's top_k (kelpie_submit_top_k), except that the
     * T=0 rule overrides it: a temperature below kelpie_sampling_eps() becomes temperature 1,
     * top_k 1. Pads are 1. */
    const uint32_t *top_ks;
} KelpiePlan;

/* The launch callback's output, owned by the engine, sized at create: tokens
 * [max_batch_reqs * stride], n_tokens and next_extra [max_batch_reqs]. The launch writes every
 * real entry; the loop validates it exactly as kelpie_commit validates a KelpieCommit. */
typedef struct KelpieStepOut {
    uint32_t stride;       /* in: 1 + max_extra */
    uint32_t *tokens;      /* out: [n_reqs, stride] row-major, same rule as KelpieCommit.tokens */
    uint32_t *n_tokens;    /* out: [n_reqs], 1 <= n <= 1 + n_extra[i] */
    uint32_t *next_extra;  /* out: [n_reqs], <= max_extra */
} KelpieStepOut;

/* captured: the CapturedModel this launch runs against (never NULL); shape: see KelpiePlan.shape. */
typedef uint32_t (*KelpieLaunchFn)(void *captured, uint32_t shape, const KelpiePlan *plan, KelpieStepOut *out);
typedef uint32_t (*KelpieLaunchWaitFn)(void *captured, KelpieStepOut *out);

/* Rank sync, called on the stepping thread with no engine lock held. exchange: the edge's `in`
 * reaches every rank's `out` (at most cap bytes); returns the bytes written (> cap = failure).
 * agree: 0 = every rank's digest is equal. Not registered = world 1: nothing is exchanged. */
typedef uint32_t (*KelpieExchangeFn)(void *ctx, const uint8_t *in, uint32_t n_in, uint8_t *out, uint32_t cap);
typedef uint32_t (*KelpieAgreeFn)(void *ctx, uint64_t digest);

enum { KELPIE_KIND_PREFILL = 0, KELPIE_KIND_DECODE = 1 };

/* kelpie_commit. Entry i (plan order) keeps tokens[i * stride .. i * stride + n_tokens[i]) --
 * "tail rows 0..n-1 were valid": the tokens the caller put at extra rows 1..n-1, then the
 * token after tail row n-1 -- cut at the first stop token and at max_new_tokens, and asks for
 * next_extra[i] extra rows on its next decode-shaped entry. A mid-prefill chunk's token is
 * discarded. An idle plan closes with n_entries 0. */
typedef struct KelpieCommit {
    uint32_t n_entries;          /* == plan n_reqs */
    uint32_t stride;             /* >= every n_tokens[i] */
    const uint32_t *tokens;      /* [n_entries * stride], row-major straight from the device; NULL iff n_entries 0 */
    const uint32_t *n_tokens;    /* [n_entries], 1 <= n <= 1 + n_extra[i]; NULL = all 1 */
    const uint32_t *next_extra;  /* [n_entries], <= max_extra; NULL = all 0 */
} KelpieCommit;
/* kelpie_commit status; nothing is applied unless KELPIE_OK. */
enum { KELPIE_OK = 0, KELPIE_ERR_ENTRIES = -1, KELPIE_ERR_COUNT = -2, KELPIE_ERR_GRAMMAR = -3,
       KELPIE_ERR_TOKEN = -4 /* a kept token is KELPIE_NO_TOKEN or >= vocab_size */ };

typedef struct KelpiePoll {
    uint32_t n_new;
    uint8_t finished;
    uint32_t state; /* KELPIE_STATE_* */
} KelpiePoll;

enum { KELPIE_TIMING_PLAN = 0, KELPIE_TIMING_FORWARD = 1, KELPIE_TIMING_COMMIT = 2 };

/* One per plan/commit pair (docs/observability.md). Durations in ns; counts as of plan, n_finished as of commit. */
typedef struct KelpieStepEvent {
    uint64_t step;
    uint64_t t_plan_ns;
    uint64_t t_forward_ns; /* bracketed by the Zig step thread; a by-hand plan/commit caller uses kelpie_timing_* */
    uint64_t t_commit_ns;
    uint32_t n_running;
    uint32_t n_waiting;
    uint32_t n_prefill_reqs;
    uint32_t n_decode_reqs;
    uint32_t n_tokens;
    uint32_t kv_free;
    uint32_t kv_used;
    uint32_t n_admitted;
    uint32_t n_preempted;
    uint32_t n_finished;
    uint32_t n_rejected_full; /* submits that returned KELPIE_SUBMIT_FULL since the previous commit */
    uint32_t prefix_queries;  /* admissions that consulted the prefix cache */
    uint32_t prefix_hits;     /* of those, admissions with n_hit > 0 */
    uint32_t prefix_hit_tokens;
    uint32_t order;           /* KELPIE_ORDER_* */
    uint64_t config_hash;     /* hash of the live config this step planned under */
    bool is_idle;
    uint32_t n_extra_rows; /* extra rows planned over the step's entries (was n_draft_tokens) */
    uint32_t n_extra_kept; /* committed tokens beyond one per entry (was n_accepted_tokens) */
} KelpieStepEvent;

/* One per request; timestamps are ns since kelpie_create (monotonic), 0 = never happened. */
typedef struct KelpieRequestEvent {
    uint64_t t_arrival_ns;
    uint64_t t_first_sched_ns;
    uint64_t t_first_token_ns;
    uint64_t t_last_token_ns;
    uint64_t t_finish_ns;
    uint64_t first_step;
    uint64_t last_step;
    uint32_t request_id;
    uint32_t n_prompt;
    uint32_t n_gen;
    uint32_t max_new;
    uint32_t n_preemptions;
    uint32_t n_chunks;
    uint32_t finish_reason; /* KELPIE_STATE_* */
    uint32_t kv_blocks_peak;
} KelpieRequestEvent;

/* Struct sizes as the core compiled them. The ABI is additive-only, and that is precisely the
 * property a reader cannot verify by eye: a binding that stops short of the struct silently
 * mis-writes every field past the gap rather than failing. Bindings should assert their own
 * sizeof against these at load time. */
size_t kelpie_config_sizeof(void);
size_t kelpie_plan_sizeof(void);

KelpieEngine *kelpie_create(const KelpieConfig *cfg); /* NULL on bad config or OOM */
void kelpie_destroy(KelpieEngine *e);

/* temperature must be finite and >= 0 (else -3). Below kelpie_sampling_eps() it means greedy: the
 * core stores temperature 1, top_k 1 (the T=0 rule); otherwise top_k 0 (the whole vocabulary). */
int64_t kelpie_submit(KelpieEngine *e, const uint32_t *tokens, uint32_t n, uint32_t max_new, float temperature);
float kelpie_sampling_eps(void); /* 1e-6 (sglang's SAMPLING_EPS); read it, never restate it */
/* kelpie_submit with a multimodal content hash (sha256 of the image bytes, truncated; 0 = text only) and the
 * prompt position of the first placeholder token. Echoed in KelpiePlan.mm_hashes per planned entry; the prefix
 * index folds mm_hash into the chain hash of every block from the one containing mm_start on. */
int64_t kelpie_submit_mm(KelpieEngine *e, const uint32_t *tokens, uint32_t n, uint32_t max_new, float temperature,
                         uint64_t mm_hash, uint32_t mm_start);
/* kelpie_submit_mm with a per-request stop token set, checked on commit alongside KelpieConfig.eos_token,
 * and a grammar: grammar_key names a grammar registered with kelpie_register_grammar (0 = none).
 * n_stop must be <= 8 (request.max_stop_tokens); stop_tokens may be any pointer when n_stop == 0.
 * -3 also for an unknown key, vocab_words == 0, or max_extra > 0 (grammar + extra rows is refused).
 * Every submit: the request enters the core at the next step boundary; until then poll reports it
 * waiting with no tokens. All rejections are synchronous and create no op. */
int64_t kelpie_submit_mm_stop(KelpieEngine *e, const uint32_t *tokens, uint32_t n, uint32_t max_new, float temperature,
                              uint64_t mm_hash, uint32_t mm_start, const uint32_t *stop_tokens, uint32_t n_stop,
                              uint64_t grammar_key);
/* kelpie_submit_mm_stop with a top_k (0 = off / whole vocabulary; overridden to 1 by the T=0
 * rule). Same returns, plus KELPIE_SUBMIT_BAD_TOP_K when top_k > KelpieConfig.vocab_size (only
 * checked when vocab_size > 0). A new export, not an appended parameter: additive ABI. */
int64_t kelpie_submit_top_k(KelpieEngine *e, const uint32_t *tokens, uint32_t n, uint32_t max_new, float temperature,
                            uint32_t top_k, uint64_t mm_hash, uint32_t mm_start, const uint32_t *stop_tokens,
                            uint32_t n_stop, uint64_t grammar_key);
/* Queues a cancel: the request finishes cancelled at the next boundary; poll says cancelled from now. */
void kelpie_cancel(KelpieEngine *e, uint32_t req_id);
/* The generation of the request now in req_id (read right after submit); kelpie_cancel_gen with
 * it cancels exactly that request, and is a no-op once the id has been reused. 1 queued, 0 no-op,
 * -6 follower. */
uint32_t kelpie_generation(KelpieEngine *e, uint32_t req_id);
int32_t kelpie_cancel_gen(KelpieEngine *e, uint32_t req_id, uint32_t gen);
/* Registers a compiled grammar (an xgrammar::CompiledGrammar* from the SAME libxgrammar this was
 * linked against; copied) under key != 0. On the edge also queues a grammar_prepare op carrying
 * `source` (<= 64 KiB) ahead of any submit naming the key. Twice = no-op. 0 ok, -1 grammar
 * disabled / bad handle / key 0, -2 full. */
int32_t kelpie_register_grammar(KelpieEngine *e, uint64_t key, void *compiled_grammar_handle,
                                const uint8_t *source, uint32_t n_source);
/* The bucket ladder (kelpie-core/src/buckets.zig): the one owner of how a plan is padded, on
 * both axes. Read it here rather than restating it -- a second copy drifts. Engine-independent. */
uint32_t kelpie_bucket_count(void);
uint32_t kelpie_bucket_at(uint32_t i); /* the i-th bucket, ascending; 0 if i is out of range */

/* One step boundary (drain + exchange + apply the inbox) then the plan, then digest agreement:
 * the loop's boundary, by hand. Returns n_tokens; 0 = idle (only n_reqs, n_tokens, digest written);
 * KELPIE_PLAN_DIVERGED (kelpie_divergence says why; the engine is poisoned);
 * KELPIE_PLAN_STOPPED (the edge's batch said stop). */
uint32_t kelpie_plan(KelpieEngine *e, KelpiePlan *out);
#define KELPIE_PLAN_DIVERGED 0xFFFFFFFFu
#define KELPIE_PLAN_STOPPED 0xFFFFFFFEu
enum { KELPIE_DIVERGED_NONE = 0, KELPIE_DIVERGED_BAD_BATCH = 1, KELPIE_DIVERGED_LAGGED_DIGEST = 2,
       KELPIE_DIVERGED_LAGGED_PAYLOAD = 3, KELPIE_DIVERGED_BOUNDARY = 4, KELPIE_DIVERGED_DIGEST = 5,
       KELPIE_DIVERGED_PAYLOAD = 6 };
uint32_t kelpie_divergence(KelpieEngine *e, uint64_t *step); /* KELPIE_DIVERGED_*; step may be NULL */
uint64_t kelpie_last_digest(KelpieEngine *e); /* the last plan's digest (idle included) */
/* A warm-up plan (c_api.zig kelpie_synthetic_plan): n_reqs real entries of `kind` (KELPIE_KIND_*),
 * each `rows` history rows then `n_extra` extra rows (input_ids KELPIE_NO_TOKEN), padded and keyed
 * (shape) by the same code as a real plan, so its shape is a real plan's for that family and
 * bucket. Real rows are inert by value exactly like pads (scratch slots, null block tables,
 * ZERO/SCRATCH state, temperature 1 / top_k 1, all-ones mask, emits 0, req_id 0); the structure
 * (query_start_loc, row_request, kinds, n_work, n_extra, positions 0.., seq_lens rows + n_extra)
 * is real. Changes no engine state: no step, digest 0, no scheduler/request/kv/inbox change. It
 * writes the plan buffers, so it is refused while a plan is outstanding or the loop runs. Valid
 * until the next kelpie_plan / kelpie_synthetic_plan; never commit it. Limits: n_reqs in
 * [1, live max_batch_reqs], rows >= 1, n_extra <= max_extra, rows + n_extra <= max_seq_len,
 * n_reqs * (rows + n_extra) <= live max_batch_tokens; a decode entry has rows 1 and only a
 * decode entry has extra rows (the shapes a real plan has). */
enum { KELPIE_SYNTH_OK = 0, KELPIE_SYNTH_ERR_BUSY = -1, KELPIE_SYNTH_ERR_KIND = -2,
       KELPIE_SYNTH_ERR_N_REQS = -3, KELPIE_SYNTH_ERR_ROWS = -4, KELPIE_SYNTH_ERR_TOKENS = -5,
       KELPIE_SYNTH_ERR_EXTRA = -6, KELPIE_SYNTH_ERR_SEQ_LEN = -7 };
int32_t kelpie_synthetic_plan(KelpieEngine *e, uint32_t kind, uint32_t n_reqs, uint32_t rows,
                              uint32_t n_extra, KelpiePlan *out);
/* KELPIE_OK or KELPIE_ERR_*; see KelpieCommit. With a sync registered the payload is agreed first
 * (rank 0's wins); a follower may pass NULL. */
int32_t kelpie_commit(KelpieEngine *e, const KelpieCommit *c);
/* Pure: copies unpolled tokens, never frees a slot. The first poll that sees a request finished
 * queues its release (applied at the next boundary; the id is reservable at once). */
uint32_t kelpie_poll(KelpieEngine *e, uint32_t req_id, uint32_t *out, uint32_t cap, KelpiePoll *result);
/* Most slabs a request of n_prompt + max_new tokens holds at once alone; submit returns
 * KELPIE_SUBMIT_EXCEEDS_KV_POOL when this exceeds KelpieConfig.num_slabs. 0 for n_prompt == 0. */
uint32_t kelpie_worst_slabs(KelpieEngine *e, uint32_t n_prompt, uint32_t max_new);
/* 1 = the last plan stalled: work pending, nothing schedulable, nothing in flight, so every later
 * plan is the same until a cancel or knob. Writes the blocked request, its next chunk (0 = budget
 * below the chunk grain) and that chunk's slabs vs free slabs. 0 = no stall, outs untouched. */
int32_t kelpie_stall(KelpieEngine *e, uint32_t *req_id, uint32_t *n_work, uint32_t *need_slabs, uint32_t *free_slabs);

void kelpie_step_event(KelpieEngine *e, KelpieStepEvent *out);                     /* valid after kelpie_commit */
/* Pops the oldest commit record the Zig step thread enqueued: that commit's StepEvent, the
 * req_ids it advanced (plan order) into out_reqs[0..cap], and how many commits were dropped
 * (ring full) since the previous record. Returns the req_id count, -1 empty (nothing popped),
 * -2 cap too small (size out_reqs to max_requests; nothing popped). One record per commit, in
 * order; one step-pipe byte per record. Only the step thread's commits enqueue records. */
int32_t kelpie_next_commit(KelpieEngine *e, KelpieStepEvent *out_event, uint32_t *out_reqs, uint32_t cap, uint32_t *out_n_dropped);
/* Read end of the step-done pipe: the step thread writes one byte per commit record. Block on
 * this (e.g. os.read(fd, 1)) to wake a drain thread, then pop kelpie_next_commit until it
 * returns -1. Owned by the Engine (closed in kelpie_destroy); do not close it. */
int32_t kelpie_step_pipe_fd(KelpieEngine *e);
int32_t kelpie_request_event(KelpieEngine *e, uint32_t req_id, KelpieRequestEvent *out); /* 0 ok, -1 bad id */
int32_t kelpie_timing_start(KelpieEngine *e, uint32_t which); /* KELPIE_TIMING_*; 0 ok, -1 bad value */
int32_t kelpie_timing_stop(KelpieEngine *e, uint32_t which);

/* Queue a live-config change (an inbox op, any thread). 0 ok, -1 bad kind/value, -2 queue full
 * (64 unapplied), -6 follower. `out` may be NULL. */
int32_t kelpie_set(KelpieEngine *e, const KelpieKnob *knob, KelpieSetResult *out);
int32_t kelpie_set_order(KelpieEngine *e, uint32_t order); /* sugar for kelpie_set(KELPIE_KNOB_ORDER); 0 ok, -1 bad value */
void kelpie_get_config(KelpieEngine *e, KelpieConfig *out); /* knob fields + config_hash as last drained */
int32_t kelpie_register_launch(KelpieEngine *e, KelpieLaunchFn launch, void *captured); /* captured != NULL */
int32_t kelpie_register_launch_split(KelpieEngine *e, KelpieLaunchFn launch, KelpieLaunchFn launch_async, KelpieLaunchWaitFn launch_wait, void *captured);
int32_t kelpie_swap_launch(KelpieEngine *e, KelpieLaunchFn launch, void *captured, bool drain); /* an op; -2: swap pending, -6 follower */
/* Registers the rank sync before start_loop (once). edge 1: this rank owns the caller API and its
 * idle loop heartbeats an empty batch every second; 0: a follower, whose loop blocks in exchange.
 * agree may be NULL. Not registered = world 1. 0 ok, -1 bad args / loop running / twice. */
int32_t kelpie_register_sync(KelpieEngine *e, KelpieExchangeFn exchange, KelpieAgreeFn agree, void *ctx, uint32_t edge);
int32_t kelpie_start_loop(KelpieEngine *e);
void kelpie_wake(KelpieEngine *e);
void kelpie_stop_loop(KelpieEngine *e); /* joins */
bool kelpie_loop_alive(KelpieEngine *e); /* true while the step-loop thread is running */
uint64_t kelpie_last_step_ns(KelpieEngine *e); /* clock domain: kelpie_now_ns; 0 before the first step */
uint64_t kelpie_now_ns(KelpieEngine *e); /* same clock domain as every StepEvent/RequestEvent timestamp */

/* ---- ABI layout tripwire (docs/derisk-plan-abi-2026-09-09.md; additive) --------------------
 * kelpie_sizeof/kelpie_offsetof let a caller (e.g. a ctypes/cffi mirror) assert its own struct
 * layout against the real Zig one at import/startup time, instead of trusting hand-copied field
 * lists to stay in sync forever. Ordinals below are hand-copied from kelpie-core/src/abi_ids.zig
 * (`structs` for KELPIE_STRUCT_*, each struct's declaration order for KELPIE_FIELD_*_*) -- that
 * file is the one writer; `zig build test` fails if these ordinals drift from the real structs
 * (abi_ids.zig's "expected_field_order" test). Both functions return 0 for an unrecognized id;
 * 0 is also KelpieCommit's real n_entries offset, so a caller distinguishing "field 0" from
 * "unknown struct/field" must first range-check (kelpie_sizeof(struct_id) != 0, field_id less
 * than the struct's known field count) rather than testing the offset alone. */
enum {
    KELPIE_STRUCT_CONFIG = 0,
    KELPIE_STRUCT_KNOB = 1,
    KELPIE_STRUCT_SET_RESULT = 2,
    KELPIE_STRUCT_PLAN = 3,
    KELPIE_STRUCT_COMMIT = 4,
    KELPIE_STRUCT_POLL = 5,
    KELPIE_STRUCT_STEP_EVENT = 6,
    KELPIE_STRUCT_REQUEST_EVENT = 7,
    KELPIE_STRUCT_STEP_OUT = 8
};

enum {
    KELPIE_FIELD_CONFIG_MAX_REQUESTS = 0,
    KELPIE_FIELD_CONFIG_MAX_SEQ_LEN = 1,
    KELPIE_FIELD_CONFIG_N_GROUPS = 2,
    KELPIE_FIELD_CONFIG_GROUP_KINDS = 3,
    KELPIE_FIELD_CONFIG_GROUP_BLOCK_SIZES = 4,
    KELPIE_FIELD_CONFIG_GROUP_WINDOWS = 5,
    KELPIE_FIELD_CONFIG_GROUP_CACHEABLE = 6,
    KELPIE_FIELD_CONFIG_NUM_BLOCKS = 7,
    KELPIE_FIELD_CONFIG_MAX_BATCH_TOKENS = 8,
    KELPIE_FIELD_CONFIG_MAX_BATCH_REQS = 9,
    KELPIE_FIELD_CONFIG_RESERVE_RATIO = 10,
    KELPIE_FIELD_CONFIG_ORDER = 11,
    KELPIE_FIELD_CONFIG_EOS_TOKEN = 12,
    KELPIE_FIELD_CONFIG_PREFIX_CACHE = 13,
    KELPIE_FIELD_CONFIG_CONFIG_HASH = 14,
    KELPIE_FIELD_CONFIG_GROUP_STRIDES = 15,
    KELPIE_FIELD_CONFIG_OVERLAP = 16,
    KELPIE_FIELD_CONFIG_VOCAB_WORDS = 17,
    KELPIE_FIELD_CONFIG_GROUP_BYTES_PER_PAGE = 18,
    KELPIE_FIELD_CONFIG_SLAB_BYTES = 19,
    KELPIE_FIELD_CONFIG_NUM_SLABS = 20,
    KELPIE_FIELD_CONFIG_MAX_EXTRA = 21,
    KELPIE_FIELD_CONFIG_VOCAB_SIZE = 22
};

enum {
    KELPIE_FIELD_KNOB_KIND = 0,
    KELPIE_FIELD_KNOB_U32_VALUE = 1,
    KELPIE_FIELD_KNOB_F32_VALUE = 2
};

enum {
    KELPIE_FIELD_SET_RESULT_APPLY_STEP = 0,
    KELPIE_FIELD_SET_RESULT_CONFIG_HASH = 1
};

enum {
    KELPIE_FIELD_PLAN_N_REQS = 0,
    KELPIE_FIELD_PLAN_N_TOKENS = 1,
    KELPIE_FIELD_PLAN_N_GROUPS = 2,
    KELPIE_FIELD_PLAN_REQ_IDS = 3,
    KELPIE_FIELD_PLAN_N_WORK = 4,
    KELPIE_FIELD_PLAN_INPUT_IDS = 5,
    KELPIE_FIELD_PLAN_POSITIONS = 6,
    KELPIE_FIELD_PLAN_QUERY_START_LOC = 7,
    KELPIE_FIELD_PLAN_SEQ_LENS = 8,
    KELPIE_FIELD_PLAN_SLOT_MAPPING = 9,
    KELPIE_FIELD_PLAN_BLOCK_TABLES = 10,
    KELPIE_FIELD_PLAN_MAX_BLOCKS_PER_REQ = 11,
    KELPIE_FIELD_PLAN_TEMPERATURES = 12,
    KELPIE_FIELD_PLAN_MM_HASHES = 13,
    KELPIE_FIELD_PLAN_KINDS = 14,
    KELPIE_FIELD_PLAN_N_EXTRA = 15,
    KELPIE_FIELD_PLAN_LOGIT_MASK = 16,
    KELPIE_FIELD_PLAN_STEP = 17,
    KELPIE_FIELD_PLAN_N_REQS_PADDED = 18,
    KELPIE_FIELD_PLAN_N_TOKENS_PADDED = 19,
    KELPIE_FIELD_PLAN_ROW_REQUEST = 20,
    KELPIE_FIELD_PLAN_SHAPE = 21,
    KELPIE_FIELD_PLAN_SEQ_START = 22,
    KELPIE_FIELD_PLAN_EMITS = 23,
    KELPIE_FIELD_PLAN_MAX_EXTRA = 24,
    KELPIE_FIELD_PLAN_ZERO_UNIT = 25,
    KELPIE_FIELD_PLAN_STATE_READ = 26,
    KELPIE_FIELD_PLAN_STATE_WRITE = 27,
    KELPIE_FIELD_PLAN_STATE_CKPT = 28,
    KELPIE_FIELD_PLAN_STATE_CKPT_ROW = 29,
    KELPIE_FIELD_PLAN_DIGEST = 30,
    KELPIE_FIELD_PLAN_TOP_KS = 31
};

enum {
    KELPIE_FIELD_COMMIT_N_ENTRIES = 0,
    KELPIE_FIELD_COMMIT_STRIDE = 1,
    KELPIE_FIELD_COMMIT_TOKENS = 2,
    KELPIE_FIELD_COMMIT_N_TOKENS = 3,
    KELPIE_FIELD_COMMIT_NEXT_EXTRA = 4
};

enum {
    KELPIE_FIELD_POLL_N_NEW = 0,
    KELPIE_FIELD_POLL_FINISHED = 1,
    KELPIE_FIELD_POLL_STATE = 2
};

enum {
    KELPIE_FIELD_STEP_EVENT_STEP = 0,
    KELPIE_FIELD_STEP_EVENT_T_PLAN_NS = 1,
    KELPIE_FIELD_STEP_EVENT_T_FORWARD_NS = 2,
    KELPIE_FIELD_STEP_EVENT_T_COMMIT_NS = 3,
    KELPIE_FIELD_STEP_EVENT_N_RUNNING = 4,
    KELPIE_FIELD_STEP_EVENT_N_WAITING = 5,
    KELPIE_FIELD_STEP_EVENT_N_PREFILL_REQS = 6,
    KELPIE_FIELD_STEP_EVENT_N_DECODE_REQS = 7,
    KELPIE_FIELD_STEP_EVENT_N_TOKENS = 8,
    KELPIE_FIELD_STEP_EVENT_KV_FREE = 9,
    KELPIE_FIELD_STEP_EVENT_KV_USED = 10,
    KELPIE_FIELD_STEP_EVENT_N_ADMITTED = 11,
    KELPIE_FIELD_STEP_EVENT_N_PREEMPTED = 12,
    KELPIE_FIELD_STEP_EVENT_N_FINISHED = 13,
    KELPIE_FIELD_STEP_EVENT_N_REJECTED_FULL = 14,
    KELPIE_FIELD_STEP_EVENT_PREFIX_QUERIES = 15,
    KELPIE_FIELD_STEP_EVENT_PREFIX_HITS = 16,
    KELPIE_FIELD_STEP_EVENT_PREFIX_HIT_TOKENS = 17,
    KELPIE_FIELD_STEP_EVENT_ORDER = 18,
    KELPIE_FIELD_STEP_EVENT_CONFIG_HASH = 19,
    KELPIE_FIELD_STEP_EVENT_IS_IDLE = 20,
    KELPIE_FIELD_STEP_EVENT_N_EXTRA_ROWS = 21,
    KELPIE_FIELD_STEP_EVENT_N_EXTRA_KEPT = 22
};

enum {
    KELPIE_FIELD_REQUEST_EVENT_T_ARRIVAL_NS = 0,
    KELPIE_FIELD_REQUEST_EVENT_T_FIRST_SCHED_NS = 1,
    KELPIE_FIELD_REQUEST_EVENT_T_FIRST_TOKEN_NS = 2,
    KELPIE_FIELD_REQUEST_EVENT_T_LAST_TOKEN_NS = 3,
    KELPIE_FIELD_REQUEST_EVENT_T_FINISH_NS = 4,
    KELPIE_FIELD_REQUEST_EVENT_FIRST_STEP = 5,
    KELPIE_FIELD_REQUEST_EVENT_LAST_STEP = 6,
    KELPIE_FIELD_REQUEST_EVENT_REQUEST_ID = 7,
    KELPIE_FIELD_REQUEST_EVENT_N_PROMPT = 8,
    KELPIE_FIELD_REQUEST_EVENT_N_GEN = 9,
    KELPIE_FIELD_REQUEST_EVENT_MAX_NEW = 10,
    KELPIE_FIELD_REQUEST_EVENT_N_PREEMPTIONS = 11,
    KELPIE_FIELD_REQUEST_EVENT_N_CHUNKS = 12,
    KELPIE_FIELD_REQUEST_EVENT_FINISH_REASON = 13,
    KELPIE_FIELD_REQUEST_EVENT_KV_BLOCKS_PEAK = 14
};

enum {
    KELPIE_FIELD_STEP_OUT_STRIDE = 0,
    KELPIE_FIELD_STEP_OUT_TOKENS = 1,
    KELPIE_FIELD_STEP_OUT_N_TOKENS = 2,
    KELPIE_FIELD_STEP_OUT_NEXT_EXTRA = 3
};

size_t kelpie_sizeof(uint32_t struct_id);                     /* 0 = unrecognized struct_id */
size_t kelpie_offsetof(uint32_t struct_id, uint32_t field_id); /* 0 = unrecognized struct_id/field_id (also a legal offset; range-check first) */

#ifdef __cplusplus
}
#endif
#endif /* KELPIE_H */
