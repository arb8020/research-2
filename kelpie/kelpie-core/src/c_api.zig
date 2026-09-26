//! C ABI over request.Pool + kv_pool.Pool + Scheduler. The only file Python touches.
//! Messy boundary, sharp interior (design-rules.md #7): all marshalling lives here.
//! Header: include/kelpie.h (hand-written; keep in sync).

// TODO(2026-09-10): this file is ABI parse + padding + fill + grammar + events (1.3k lines); split
// config.zig (parseConfig) and pad.zig out of it (handoff-2026-09-10 debt 7).
const std = @import("std");
const assert = std.debug.assert;
const request = @import("request.zig");
const kv_pool = @import("kv_pool.zig");
const scheduler = @import("scheduler.zig");
const buckets = @import("buckets.zig");
const events = @import("events.zig");
const step_loop = @import("step_loop.zig");
const xgrammar = @import("xgrammar.zig");
const abi_ids = @import("abi_ids.zig");
const inputs = @import("inputs.zig");

const allocator = std.heap.c_allocator;

/// Records the commit ring holds before the step thread starts dropping (see Engine.ring_*).
/// At ~5000 commits/s (the Zig loop on a small model) this is ~200 ms of drain-thread slack.
pub const commit_ring_capacity: u32 = 1024;

pub const KelpieConfig = extern struct {
    max_requests: u32,
    max_seq_len: u32,
    n_groups: u32,
    group_kinds: [*]const u32, // 0 = per_token, 1 = per_seq
    group_block_sizes: [*]const u32,
    group_windows: [*]const u32, // 0 = keep everything; W = sliding window of W tokens
    group_cacheable: [*]const u8, // 0/1: may the group's blocks enter the prefix index
    num_blocks: u32, // includes null block 0 (kv_pool.null_block); the model allocates [num_blocks] and leaves 0 unused
    max_batch_tokens: u32,
    max_batch_reqs: u32,
    reserve_ratio: f32,
    order: u32, // 0 = running_first, 1 = waiting_first
    eos_token: u32,
    prefix_cache: u32, // 0/1: runtime knob, scheduler.Config.prefix_cache
    config_hash: u64, // out only (kelpie_get_config): scheduler.hashConfig of the live config
    group_strides: ?[*]const u32, // [n_groups] tokens per unit (1 = one unit per token); null = all 1 (appended: additive ABI)
    overlap: u32, // 0/1 startup protocol choice (tier 2; never a live knob)
    // Row width of KelpiePlan.logit_mask: ceil(vocab/32), the model's padded logits width (NOT
    // the tokenizer's -- kelpie-engine/kelpie_engine/grammar.py's compile_json_schema docstring on why).
    // 0 = grammar support disabled: a submit naming a grammar is refused, logit_mask is never
    // filled (appended: additive ABI, mirrors group_strides above).
    vocab_words: u32 = 0,
    /// [n_groups] bytes one page of each group costs, padded to the 4 KB quantum by Python
    /// (kelpie_models.groups.choose_block_sizes, docs/slab-lcm-ladder.md). A slab holds
    /// `floor(slab_bytes / group_bytes_per_page[g])` pages of group g; the tail too small for
    /// one more page is slack. NULL = legacy one-tensor-per-group mode: every group gets an
    /// equal page and pages_per_slab is 1.
    /// (appended: additive ABI, mirrors group_strides above.)
    group_bytes_per_page: ?[*]const u32 = null,
    /// Out only (kelpie_get_config): the slab pool's geometry as the core resolved it.
    slab_bytes: u32 = 0,
    num_slabs: u32 = 0,
    /// Kmax (docs/design-core-option2.md): the most extra rows a decode-shaped entry may carry
    /// after its history row -- rows whose input_ids the caller fills (a drafter's drafts). 0 =
    /// none. Sizes the per_seq write units (1 + Kmax) and the table rows an extra row can reach.
    /// Renamed from n_draft, same offset.
    max_extra: u32 = 0,
    /// The model's vocabulary size: kelpie_commit rejects a kept token id >= vocab_size
    /// (KELPIE_ERR_TOKEN). 0 = unchecked (only KELPIE_NO_TOKEN is rejected). Appended.
    vocab_size: u32 = 0,
};

/// Bumped on every non-additive ABI change; Python refuses a libkelpie whose kelpie_abi_version
/// differs from its own (kelpie_engine._ffi.ABI_VERSION). 2: KelpieCommit {n_entries, stride,
/// tokens, n_tokens, next_extra} replaced {n_entries, tokens, n_tokens, drafts, n_drafts}
/// (40 -> 32 bytes) and kelpie_commit(KelpieCommit*) replaced kelpie_commit(sampled, n) +
/// kelpie_commit_payload. 3 (docs/design-multigpu.md 2.2): LaunchFn/LaunchWaitFn write a
/// KelpieStepOut (n tokens per entry) instead of u32[n_reqs]; kelpie_submit_mm_stop takes a
/// grammar_key and kelpie_attach_grammar is gone (kelpie_register_grammar); KelpiePlan.digest
/// appended; kelpie_register_sync; submit/cancel/set/poll-release are step-boundary inbox ops.
pub const abi_version: u32 = 3;

export fn kelpie_abi_version() u32 {
    return abi_version;
}

/// Tagged live-config change; `kind` selects which value field is read.
pub const KelpieKnob = extern struct {
    kind: u32, // KELPIE_KNOB_*
    u32_value: u32, // order / max_batch_tokens / max_batch_reqs / prefix_cache (0/1)
    f32_value: f32, // reserve_ratio
};

pub const KelpieSetResult = extern struct {
    apply_step: u64, // the step whose plan drains this knob
    config_hash: u64, // hash of the config once everything queued so far has applied
};

pub const KnobKind = enum(u32) { order, reserve_ratio, max_batch_tokens, max_batch_reqs, prefix_cache };

/// Raw pointers into Engine-owned buffers. Valid until the next kelpie_plan/kelpie_commit/kelpie_destroy.
pub const KelpiePlan = extern struct {
    /// Real counts: how many planned entries / rows carry data. Commit is over n_reqs entries.
    n_reqs: u32,
    n_tokens: u32,
    n_groups: u32,
    req_ids: [*]const u32, // [n_reqs]
    n_work: [*]const u32, // [n_reqs]
    input_ids: [*]const u32, // [n_tokens]
    positions: [*]const u32, // [n_tokens]
    query_start_loc: [*]const u32, // [n_reqs + 1]
    seq_lens: [*]const u32, // [n_reqs]
    slot_mapping: [*]const [*]const u32, // [n_groups][n_tokens]
    block_tables: [*]const [*]const u32, // [n_groups][n_reqs * max_blocks_per_req[g]]
    max_blocks_per_req: [*]const u32, // [n_groups]
    temperatures: [*]const f32, // [n_reqs] sampling temperature per planned request
    mm_hashes: [*]const u64, // [n_reqs] multimodal content hash per planned request; 0 = text only (appended: additive ABI)
    kinds: [*]const u32, // [n_reqs] scheduler.Kind ordinal: 0 prefill, 1 decode (appended: additive ABI)
    n_extra: [*]const u32, // [n_reqs] extra rows after the entry's n_work history rows (was n_drafts, same offset)
    // [n_reqs, cfg.vocab_words] int32, one row per planned entry in plan order: bit v of word
    // v/32 set = token v allowed for that entry's next sample. All-ones (0xFFFFFFFF) for an
    // entry with no grammar attached, so the sampler's mask application is never a host
    // conditional (docs/grammar-design.md section 3, superseded doc -- see its header note).
    // Filled by kelpie_plan/fillPlan calling xgrammar_matcher_fill per entry, i.e. between plan
    // and whatever the caller does next (launch_forward). null iff cfg.vocab_words == 0.
    // (appended: additive ABI)
    logit_mask: ?[*]const i32,
    step: u64,
    // ---- padded plan (appended: additive ABI) --------------------------------------------
    // Every array above is bucket-sized: input_ids/positions/slot_mapping[g]/row_request are
    // n_tokens_padded long, req_ids/seq_lens/kinds/n_extra/temperatures/mm_hashes/logit_mask
    // rows are n_reqs_padded long, query_start_loc is n_reqs_padded + 1, block_tables[g] is
    // n_reqs_padded rows. The core is the only padder: Python and launch.c copy what is here
    // and decide nothing (docs/friction-2026-09-09.md 1 -- the fill had two writers and drifted).
    //
    // Pad values, all inert by value (docs/model-contract.md 2): a pad row's input_id and
    // position are 0 and its slot is the scratch slot (last slot of null block 0), so it writes
    // nowhere live; a pad request has an empty query, seq_len 1 on the null block, kind
    // PREFILL, n_extra 0, temperature 1 / top_k 1 (the T=0 rule's greedy form) and an all-ones
    // logit mask.
    n_reqs_padded: u32,
    n_tokens_padded: u32,
    /// [n_tokens_padded] the request index owning each row; -1 for a pad row. A kernel gridding
    /// over rows reads this instead of rebuilding the partition on the host.
    row_request: [*]const i32,
    // Deterministic program-selection key, derived only from this plan (never a Zig-owned
    // counter) -- see stepShape() below for the exact packing. mode/dtype/flags
    // (kelpie_models.plan.StepShape) are per-CapturedModel constants, fixed at capture time, so
    // they never travel on this wire (docs/m2-zig-loop.md).
    shape: u32,
    // ---- spec-agnostic core API (appended; docs/design-core-option2.md 2.3) --------------
    // An entry's rows are n_work history rows then n_extra extra rows (input_ids
    // KELPIE_NO_TOKEN: the caller fills them). Tail row j = row n_work - 1 + j.
    seq_start: [*]const u32, // [n_reqs_padded] tokens already in context; pad 0
    emits: [*]const u8, // [n_reqs_padded] 1 iff commit keeps the entry's tokens; pad 0
    max_extra: u32, // Kmax: state_write rows are 1 + max_extra wide
    zero_unit: [*]const u32, // [n_groups] ZERO(g) of a per_seq group; 0 for a per_token group
    // Per group, NULL for a per_token group (whose rows go through slot_mapping). Pad entries
    // read ZERO and write SCRATCH (unit 0) everywhere, with ckpt_row KELPIE_NO_ROW.
    state_read: [*]const ?[*]const u32, // [n_groups] -> [n_reqs_padded]
    state_write: [*]const ?[*]const u32, // [n_groups] -> [n_reqs_padded * (1 + max_extra)]
    state_ckpt: [*]const ?[*]const u32, // [n_groups] -> [n_reqs_padded]; SCRATCH = none
    state_ckpt_row: [*]const ?[*]const u32, // [n_groups] -> [n_reqs_padded]; KELPIE_NO_ROW = none
    /// Wyhash of this plan's scheduling content, the batch applied before it and the previous
    /// commit's payload (planDigest): equal on every rank that planned the same step. Also set
    /// for an idle plan (whose other fields are not). ABI 3.
    digest: u64,
    /// [n_reqs_padded] per entry: sample from the top_k most likely tokens, 0 = the whole
    /// vocabulary, 1 = greedy. The caller's top_k (kelpie_submit_top_k) unless the T=0 rule
    /// overrode it (request.samplingParams). A pad entry is 1 (with temperature 1), so an
    /// all-greedy batch is all-greedy over its whole padded width. (appended: additive ABI)
    top_ks: [*]const u32,
};

/// request.sampling_eps over the ABI: below it a submitted temperature means greedy. Python
/// reads it (kelpie_engine._ffi) instead of restating it, so the eps has one writer.
export fn kelpie_sampling_eps() f32 {
    return request.sampling_eps;
}

/// The launch callback's output, engine-owned and sized at create (docs/design-multigpu.md
/// 2.2). Entry i keeps tokens[i * stride ..][0..n_tokens[i]] (1 <= n <= 1 + n_extra[i]) and asks
/// for next_extra[i] extra rows next; the launch writes every real entry. The loop validates it
/// exactly as kelpie_commit validates a KelpieCommit (validateCommit).
pub const KelpieStepOut = extern struct {
    stride: u32, // in: 1 + max_extra
    tokens: [*]u32, // [max_batch_reqs * stride]
    n_tokens: [*]u32, // [max_batch_reqs]
    next_extra: [*]u32, // [max_batch_reqs]
};

/// Rank sync (docs/design-multigpu.md 2.2, section 8 B4), called on whatever thread steps --
/// the loop's, or the by-hand caller's -- with no engine lock held. exchange: the edge's `in`
/// goes to every rank's `out` (<= cap bytes); returns the bytes written (> cap = failure).
/// agree: 0 = every rank's digest is equal. Not registered = world 1: nothing is exchanged.
pub const KelpieExchangeFn = *const fn (?*anyopaque, [*]const u8, u32, [*]u8, u32) callconv(.c) u32;
pub const KelpieAgreeFn = *const fn (?*anyopaque, u64) callconv(.c) u32;
const Sync = struct { exchange: KelpieExchangeFn, agree: ?KelpieAgreeFn, ctx: ?*anyopaque, edge: bool };

/// Why a by-hand step refused to continue (kelpie_plan returns plan_diverged; the loop panics).
pub const Divergence = enum(u32) { none = 0, bad_batch, lagged_digest, lagged_payload, boundary, digest, payload };

/// kelpie_plan's return when the step cannot proceed: the batch was malformed, or this rank's
/// plan disagrees with the edge's (kelpie_divergence says which). The engine is poisoned.
pub const plan_diverged: u32 = std.math.maxInt(u32);
/// kelpie_plan's return when the edge's batch said stop.
pub const plan_stopped: u32 = std.math.maxInt(u32) - 1;

/// Per-plan scratch. Every array here is sized to the *bucketed* capacity, because kelpie_plan
/// emits a padded plan: the arrays it publishes are reqsPadded / bucket(n_tokens) long, and
/// the ladder rounds up past max_batch_* when those are not powers of two.
const PlanScratch = struct {
    req_ids: []u32,
    n_work: []u32,
    kinds: []u32,
    n_extra: []u32,
    /// [bucket(max_batch_tokens)] the request index owning each row, -1 for a pad row. Lets a
    /// kernel grid over rows find its request without a host-side partition (the Triton prefill
    /// kernel returns on -1); the one thing a padded plan adds that the unpadded one lacked.
    row_request: []i32,
    slot_mapping_ptrs: [][*]const u32,
    block_table_ptrs: [][*]const u32,
    max_blocks_per_req: []u32,
    /// Per group: plan.state's slices as C pointers, null for a per_token group.
    state_read_ptrs: []?[*]const u32,
    state_write_ptrs: []?[*]const u32,
    state_ckpt_ptrs: []?[*]const u32,
    state_ckpt_row_ptrs: []?[*]const u32,
    // [max_batch_reqs * cfg.vocab_words] int32, row i filled by fillPlan for planned entry i.
    // Empty (len 0) iff cfg.vocab_words == 0 -- KelpiePlan.logit_mask is null in that case, same
    // "feature entirely off" convention as group_strides == null upstream.
    logit_mask: []i32,

    /// Allocates every array, or none: an `errdefer` per field so a failure part-way through
    /// leaves nothing behind. Paired with `deinit`, which is the one writer of how this is freed.
    fn init(scratch: *PlanScratch, cap_reqs: u32, cap_tokens: u32, n_groups: u32, vocab_words: u32) !void {
        scratch.req_ids = try allocator.alloc(u32, cap_reqs);
        errdefer allocator.free(scratch.req_ids);
        scratch.n_work = try allocator.alloc(u32, cap_reqs);
        errdefer allocator.free(scratch.n_work);
        scratch.kinds = try allocator.alloc(u32, cap_reqs);
        errdefer allocator.free(scratch.kinds);
        scratch.n_extra = try allocator.alloc(u32, cap_reqs);
        errdefer allocator.free(scratch.n_extra);
        scratch.row_request = try allocator.alloc(i32, cap_tokens);
        errdefer allocator.free(scratch.row_request);
        scratch.slot_mapping_ptrs = try allocator.alloc([*]const u32, n_groups);
        errdefer allocator.free(scratch.slot_mapping_ptrs);
        scratch.block_table_ptrs = try allocator.alloc([*]const u32, n_groups);
        errdefer allocator.free(scratch.block_table_ptrs);
        scratch.max_blocks_per_req = try allocator.alloc(u32, n_groups);
        errdefer allocator.free(scratch.max_blocks_per_req);
        scratch.state_read_ptrs = try allocator.alloc(?[*]const u32, n_groups);
        errdefer allocator.free(scratch.state_read_ptrs);
        scratch.state_write_ptrs = try allocator.alloc(?[*]const u32, n_groups);
        errdefer allocator.free(scratch.state_write_ptrs);
        scratch.state_ckpt_ptrs = try allocator.alloc(?[*]const u32, n_groups);
        errdefer allocator.free(scratch.state_ckpt_ptrs);
        scratch.state_ckpt_row_ptrs = try allocator.alloc(?[*]const u32, n_groups);
        errdefer allocator.free(scratch.state_ckpt_row_ptrs);
        scratch.logit_mask = try allocator.alloc(i32, cap_reqs * vocab_words);
    }

    fn deinit(scratch: *PlanScratch) void {
        allocator.free(scratch.logit_mask);
        allocator.free(scratch.state_ckpt_row_ptrs);
        allocator.free(scratch.state_ckpt_ptrs);
        allocator.free(scratch.state_write_ptrs);
        allocator.free(scratch.state_read_ptrs);
        allocator.free(scratch.max_blocks_per_req);
        allocator.free(scratch.block_table_ptrs);
        allocator.free(scratch.slot_mapping_ptrs);
        allocator.free(scratch.row_request);
        allocator.free(scratch.n_extra);
        allocator.free(scratch.kinds);
        allocator.free(scratch.n_work);
        allocator.free(scratch.req_ids);
    }
};

/// scheduler.Commit over the C boundary (docs/design-core-option2.md 2.3, section 8 item 2).
/// Entry i (plan order) keeps tokens[i * stride ..][0..n_tokens[i]], 1 <= n_tokens[i] <=
/// 1 + n_extra[i] (null n_tokens = all 1), and asks for next_extra[i] <= max_extra extra rows on
/// its next decode-shaped entry (null = all 0). `tokens` is [n_entries, stride] row-major,
/// straight from the device.
pub const KelpieCommit = extern struct {
    n_entries: u32, // == plan n_reqs
    stride: u32, // >= every n_tokens[i]
    tokens: ?[*]const u32, // [n_entries * stride]; null only when n_entries == 0
    n_tokens: ?[*]const u32, // [n_entries]
    next_extra: ?[*]const u32, // [n_entries]
};

/// kelpie_commit's status. Nothing is applied unless it returns ok.
pub const CommitStatus = enum(i32) { ok = 0, err_entries = -1, err_count = -2, err_grammar = -3, err_token = -4 };

pub const KelpiePoll = extern struct {
    n_new: u32,
    finished: u8, // 0/1
    state: u32, // request.State ordinal: 0 waiting 1 running 2 finished_eos 3 finished_length 4 cancelled 5 grammar_dead_end
};

pub const Engine = struct {
    cfg: KelpieConfig,
    groups: []request.GroupSpec,
    group_kinds: []u32,
    group_block_sizes: []u32,
    group_windows: []u32,
    group_cacheable: []u8,
    group_strides: []u32,
    /// Empty in legacy mode (cfg.group_bytes_per_page NULL).
    group_bytes_per_page: []u32,
    max_blocks_per_req: []u32,
    reqs: request.Pool,
    kv: kv_pool.Pool,
    sched: scheduler.Scheduler,
    // Scratch mirrors of the Plan, laid out the way C wants them.
    plan_scratch: [2]PlanScratch,
    loop: Loop,
    // ns in sched.clock's domain, written by the step thread right after each commit; 0 before
    // the first step. Read by kelpie_last_step_ns (docs/design-compress-step.md: serve's health
    // check needs "did the native loop step recently", the same question Stepper.since_last_step_s
    // answers for the Python rung).
    last_step_ns: u64,
    // The commit ring: one record per commit, in commit order, popped by kelpie_next_commit.
    // A record is that commit's StepEvent plus the req_ids it advanced (plan order). Written
    // under loop.mutex by the step thread (commitOpaque -> enqueueCommit), popped under
    // loop.mutex by the drain thread, so the two never tear. The ring is what makes the step
    // pipe's contract real: one pipe byte is written per record ENQUEUED (never for a dropped
    // one), so the pipe never holds more bytes than the ring holds records, and a drain thread
    // that reads k bytes can pop k records -- not "the latest state" but each commit's own.
    // Full ring (drain thread more than commit_ring_capacity commits behind): the newest
    // record is dropped, its advanced set is carried (carry_advanced, a bitmap over req_ids)
    // into the next record that fits, and that record's n_dropped says how many commits it
    // stands for -- an advanced req_id is reported at least once, a lost StepEvent is counted.
    ring_events: []events.StepEvent, // [commit_ring_capacity]
    ring_advanced: []u32, // [commit_ring_capacity * max_requests]: row i is record i's req_ids
    ring_n_advanced: []u32, // [commit_ring_capacity]
    ring_n_dropped: []u32, // [commit_ring_capacity]
    ring_head: u32, // index of the oldest un-popped record
    ring_len: u32, // records held, <= commit_ring_capacity
    carry_advanced: []u32, // bitmap [ceil(max_requests / 32)] of req_ids advanced by dropped commits
    carry_n_dropped: u32,
    // A pipe the step thread writes one byte to per record enqueued (kelpie_wake's counterpart:
    // this wakes a *drain thread* in Python, not the step thread itself). read_fd is exposed via
    // kelpie_step_pipe_fd for a Python thread to block on with os.read; write_fd is never given
    // out. Non-blocking so a drain thread that falls behind never stalls the step loop; the
    // pipe (>= 16 KiB everywhere we run) outholds the ring, so WouldBlock is not expected, and
    // if it ever happens the record is still in the ring for the next wake to pop.
    pipe_read_fd: i32,
    pipe_write_fd: i32,
    // Per-request grammar matcher, parallel to reqs.requests (index by req_id), the native-loop
    // mirror of kelpie-engine/kelpie_engine/core.py's `self._grammars: dict[int, Matcher]`. null = no
    // grammar attached. Lifetime: attached by kelpie_attach_grammar (after submit -- grammar
    // compilation is async per docs/grammar-design.md section 1, so it can never ride submit's
    // own args the way mm_hash does), destroyed at the same points Python's `_detach` fires:
    // kelpie_poll observing `finished`, kelpie_cancel, and defensively at kelpie_submit/
    // kelpie_submit_mm for a reused slot (stale_grammar_id can otherwise leak across reuse the
    // same way Python's dict.pop(rid, None) guards against). See docs/grammar-design.md's header
    // note: that doc predates the native loop and is superseded by this Engine-owned array for
    // the --native-loop path.
    grammars: []?xgrammar.Matcher,
    // Scratch for commitUnlocked: req_ids of the plan being committed, captured in plan order
    // before scheduler.commit's overlap swap invalidates plan_buf's view of them.
    // [max_batch_reqs].
    commit_req_ids: []u32,
    // ---- step-boundary inputs (docs/design-multigpu.md 2.3, inputs.zig) --------------------
    inbox: inputs.Inbox,
    /// The boundary's batch as this rank drained it (edge) -- [inbox.capWords()].
    batch: []u32,
    /// The agreed batch the exchange wrote (sync only; world 1 applies `batch` itself).
    batch_in: []u32,
    /// The batch the next apply reads: a view of `batch` or `batch_in`.
    batch_view: []const u32,
    /// Core-side generation of each slot's occupant (set when its submit op applies): an op
    /// naming an older generation is stale and applies as a no-op (B2).
    gens: []u32,
    sync: ?Sync,
    /// The last plan's digest, the last applied batch's hash, the last commit's payload hash.
    digest: u64,
    batch_hash: u64,
    prev_payload_hash: u64,
    /// Set once a boundary or agreement fails on a by-hand step; every later step refuses.
    diverged: Divergence,
    diverged_step: u64,
    /// The launch output (KelpieStepOut) and its storage.
    step_out: KelpieStepOut,
    out_tokens: []u32,
    out_n: []u32,
    out_extra: []u32,
    /// Payload agreement buffers (sync only): this rank's payload, and rank 0's.
    payload_mine: []u32,
    payload_agreed: []u32,
    registry: GrammarRegistry,
};

/// Compiled grammars by key (kelpie_register_grammar), owned here. A submit names a key; its
/// op waits at apply until the key is registered on this rank (bounded, then panics: section 8
/// B3). Its own lock + condvar, never loop.mutex. Entries live until kelpie_destroy.
const GrammarRegistry = struct {
    mutex: std.Thread.Mutex = .{},
    registered: std.Thread.Condition = .{},
    keys: [capacity]u64 = undefined,
    grammars: [capacity]xgrammar.CompiledGrammar = undefined,
    n: u32 = 0,

    const capacity = 256;
    const wait_ns: u64 = 30 * std.time.ns_per_s;

    fn find(r: *GrammarRegistry, key: u64) ?xgrammar.CompiledGrammar {
        for (r.keys[0..r.n], r.grammars[0..r.n]) |k, g| if (k == key) return g;
        return null;
    }

    fn has(r: *GrammarRegistry, key: u64) bool {
        r.mutex.lock();
        defer r.mutex.unlock();
        return r.find(key) != null;
    }

    /// Takes ownership of `grammar` unless the key is already registered (then it is destroyed).
    fn put(r: *GrammarRegistry, key: u64, grammar: xgrammar.CompiledGrammar) error{Full}!void {
        r.mutex.lock();
        defer r.mutex.unlock();
        if (r.find(key) != null) {
            xgrammar.compiledGrammarDestroy(grammar);
            return;
        }
        if (r.n == capacity) {
            xgrammar.compiledGrammarDestroy(grammar);
            return error.Full;
        }
        r.keys[r.n] = key;
        r.grammars[r.n] = grammar;
        r.n += 1;
        r.registered.broadcast();
    }

    /// The grammar for key, waiting (bounded) for a registration still on its way.
    fn wait(r: *GrammarRegistry, key: u64) xgrammar.CompiledGrammar {
        r.mutex.lock();
        defer r.mutex.unlock();
        var timer = std.time.Timer.start() catch unreachable;
        while (true) {
            if (r.find(key)) |g| return g;
            const waited = timer.read();
            if (waited >= wait_ns) std.debug.panic("grammar key {x} never registered on this rank ({d} s)", .{ key, wait_ns / std.time.ns_per_s });
            r.registered.timedWait(&r.mutex, wait_ns - waited) catch {};
        }
    }

    fn deinit(r: *GrammarRegistry) void {
        for (r.grammars[0..r.n]) |g| xgrammar.compiledGrammarDestroy(g);
        r.n = 0;
    }
};

/// Size of KelpieConfig / KelpiePlan as the core compiled them. The ABI is additive-only, and
/// "additive" is exactly the property a reader cannot check by eye: a bridge that stops short of
/// the struct does not fail loudly, it silently mis-writes every field past the gap. (That is not
/// hypothetical -- both ctypes bridges missed three appended fields and nothing caught it.) The
/// Python bridges assert `ctypes.sizeof(struct) == this` at import, so a field added on one side
/// only is a startup error naming both numbers, not a wrong answer at runtime.
export fn kelpie_config_sizeof() usize {
    return @sizeOf(KelpieConfig);
}

export fn kelpie_plan_sizeof() usize {
    return @sizeOf(KelpiePlan);
}

export fn kelpie_create(cfg_ptr: ?*const KelpieConfig) ?*Engine {
    const cfg = (cfg_ptr orelse return null).*;
    if (cfg.n_groups == 0 or cfg.max_requests == 0 or cfg.max_seq_len == 0 or cfg.num_blocks < 2) return null;
    if (cfg.max_batch_tokens == 0 or cfg.max_batch_reqs == 0) return null;
    if (cfg.max_batch_tokens > buckets.BUCKETS[buckets.BUCKETS.len - 1]) return null;
    if (cfg.max_batch_reqs > buckets.BUCKETS[buckets.BUCKETS.len - 1]) return null;
    if (cfg.order > 1 or cfg.overlap > 1) return null;
    // An ahead plan is built before the commit that says how many extra rows to plan: overlap
    // would need device-side seq_start/positions (docs/design-core-option2.md 3).
    if (cfg.max_extra > 0 and cfg.overlap != 0) return null;
    return create(cfg) catch null;
}

fn create(cfg: KelpieConfig) !*Engine {
    const e = try allocator.create(Engine);
    errdefer allocator.destroy(e);
    e.cfg = cfg;

    const n_groups = cfg.n_groups;
    e.groups = try allocator.alloc(request.GroupSpec, n_groups);
    errdefer allocator.free(e.groups);
    e.group_kinds = try allocator.alloc(u32, n_groups);
    errdefer allocator.free(e.group_kinds);
    e.group_block_sizes = try allocator.alloc(u32, n_groups);
    errdefer allocator.free(e.group_block_sizes);
    e.group_windows = try allocator.alloc(u32, n_groups);
    errdefer allocator.free(e.group_windows);
    e.group_cacheable = try allocator.alloc(u8, n_groups);
    errdefer allocator.free(e.group_cacheable);
    e.group_strides = try allocator.alloc(u32, n_groups);
    errdefer allocator.free(e.group_strides);
    e.max_blocks_per_req = try allocator.alloc(u32, n_groups);
    errdefer allocator.free(e.max_blocks_per_req);
    for (0..n_groups) |g| {
        const kind = cfg.group_kinds[g];
        if (kind > 1) return error.BadGroupKind;
        e.group_kinds[g] = kind;
        e.group_block_sizes[g] = cfg.group_block_sizes[g];
        e.group_windows[g] = cfg.group_windows[g];
        if (cfg.group_cacheable[g] > 1) return error.BadCacheable;
        e.group_cacheable[g] = cfg.group_cacheable[g];
        // per_token: tokens per unit, default 1. per_seq: the checkpoint interval S, default 0
        // (never checkpoint -- one live unit, which is what per_seq meant before step 4).
        const default_stride: u32 = if (kind == 0) 1 else 0;
        e.group_strides[g] = if (cfg.group_strides) |strides| strides[g] else default_stride;
        e.groups[g] = .{
            .kind = if (kind == 0) .per_token else .per_seq,
            .block_size = cfg.group_block_sizes[g],
            .retention = if (cfg.group_windows[g] == 0) .all else .{
                .window = .{ .w = cfg.group_windows[g], .cacheable = cfg.group_cacheable[g] == 1 },
            },
            .stride = e.group_strides[g],
        };
        if (e.groups[g].kind == .per_token and e.groups[g].block_size == 0) return error.BadBlockSize;
        // A per_seq group's window is the checkpoints a request keeps (request.nCheckpoints),
        // not tokens: >= 1 exactly when it checkpoints (stride S > 0), 0 when it never does.
        if (e.groups[g].kind == .per_seq and (e.groups[g].stride == 0) != (cfg.group_windows[g] == 0)) {
            return error.BadWindow;
        }
        // Overlap plans a decode ahead of the commit that sets the live state it would read.
        if (e.groups[g].kind == .per_seq and cfg.overlap != 0) return error.OverlapPerSeq;
        if (e.groups[g].kind == .per_token and e.groups[g].stride == 0) return error.BadStride;
        // per_token only: a stride-k window group is not modelled (its match rule assumes
        // stride 1). A per_seq group's stride is the CHECKPOINT INTERVAL and its window is
        // checkpoints kept, so stride 16 + window 6 is an ordinary config, not an error.
        if (e.groups[g].kind == .per_token and e.groups[g].stride != 1 and cfg.group_windows[g] != 0) {
            return error.BadStride;
        }
    }
    // Point the stored config at Engine-owned arrays so kelpie_get_config never aliases caller memory.
    e.cfg.group_kinds = e.group_kinds.ptr;
    e.cfg.group_block_sizes = e.group_block_sizes.ptr;
    e.cfg.group_windows = e.group_windows.ptr;
    e.cfg.group_cacheable = e.group_cacheable.ptr;
    e.cfg.group_strides = e.group_strides.ptr;

    e.reqs = try request.Pool.init(allocator, .{
        .max_requests = cfg.max_requests,
        .max_seq_len = cfg.max_seq_len,
        .groups = e.groups,
        .max_extra = cfg.max_extra,
    });
    errdefer e.reqs.deinit(allocator);
    // The kv pool stores a published block's tokens: the most any group puts in one block. A
    // per_seq checkpoint stores its own last S tokens (prefix.insertSeq).
    var max_block_tokens: u32 = 1;
    for (e.groups) |group| {
        const per_block = if (group.kind == .per_token) request.tokensPerBlock(group) else group.stride;
        max_block_tokens = @max(max_block_tokens, per_block);
    }
    // group_bytes_per_page NULL = legacy one-tensor-per-group mode: every group's page is the
    // same size, pages_per_slab is 1, and the pool degenerates to the pre-slab block pool.
    // Non-NULL: slab_bytes is the largest page, and every page must DIVIDE it exactly
    // (ruling 2026-09-10, docs/slab-lcm-ladder.md: kelpie_models.sdk.groups.choose_block_sizes
    // rounds slab_bytes up to a multiple of lcm(k_g * 16) and sets each page to slab_bytes/k_g).
    // num_blocks is then the slab count.
    if (cfg.group_bytes_per_page) |bytes_per_page| {
        var slab_bytes: u32 = 0;
        for (0..n_groups) |g| {
            if (bytes_per_page[g] == 0) return error.BadBytesPerPage;
            slab_bytes = @max(slab_bytes, bytes_per_page[g]);
        }
        e.group_bytes_per_page = try allocator.alloc(u32, n_groups);
        errdefer allocator.free(e.group_bytes_per_page);
        const pool_groups = try allocator.alloc(kv_pool.PoolGroup, n_groups);
        defer allocator.free(pool_groups);
        for (0..n_groups) |g| {
            const page = bytes_per_page[g];
            // Exact tiling, invariant (ii): no slack. A page that does not divide the slab is a
            // Python-side sizing bug, and it is rejected here rather than silently truncated.
            if (slab_bytes % page != 0) return error.BadBytesPerPage;
            e.group_bytes_per_page[g] = page;
            pool_groups[g] = .{ .bytes_per_page = page, .pages_per_slab = slab_bytes / page };
        }
        e.cfg.group_bytes_per_page = e.group_bytes_per_page.ptr;
        e.cfg.slab_bytes = slab_bytes;
        e.cfg.num_slabs = cfg.num_blocks;
        e.kv = try kv_pool.Pool.init(allocator, cfg.num_blocks, slab_bytes, pool_groups, max_block_tokens);
    } else {
        e.group_bytes_per_page = &.{};
        e.cfg.slab_bytes = 0;
        e.cfg.num_slabs = cfg.num_blocks - 1;
        e.kv = try kv_pool.flatInit(allocator, cfg.num_blocks, max_block_tokens, n_groups);
    }
    errdefer e.kv.deinit(allocator);
    e.sched = try scheduler.Scheduler.init(allocator, schedulerConfig(cfg), &e.reqs, &e.kv);
    errdefer e.sched.deinit(allocator);

    const cap_reqs = buckets.bucket(cfg.max_batch_reqs);
    const cap_tokens = buckets.bucket(cfg.max_batch_tokens);
    // n_ready counts the slots fully initialised so far, so the errdefer frees exactly those and
    // no more: a slot whose own init failed already unwound itself.
    var n_ready: usize = 0;
    errdefer for (e.plan_scratch[0..n_ready]) |*scratch| scratch.deinit();
    for (&e.plan_scratch) |*scratch| {
        try scratch.init(cap_reqs, cap_tokens, n_groups, cfg.vocab_words);
        n_ready += 1;
    }
    const stride = 1 + cfg.max_extra;
    e.out_tokens = try allocator.alloc(u32, cfg.max_batch_reqs * stride);
    errdefer allocator.free(e.out_tokens);
    e.out_n = try allocator.alloc(u32, cfg.max_batch_reqs);
    errdefer allocator.free(e.out_n);
    e.out_extra = try allocator.alloc(u32, cfg.max_batch_reqs);
    errdefer allocator.free(e.out_extra);
    @memset(e.out_tokens, 0);
    @memset(e.out_n, 1);
    @memset(e.out_extra, 0);
    e.step_out = .{ .stride = stride, .tokens = e.out_tokens.ptr, .n_tokens = e.out_n.ptr, .next_extra = e.out_extra.ptr };
    e.loop = .{
        .owner = e,
        .boundary_fn = boundaryOpaque,
        .apply_fn = applyOpaque,
        .plan_fn = planOpaque,
        .agree_fn = agreeOpaque,
        .refresh_fn = refreshOpaque,
        .payload_fn = payloadOpaque,
        .commit_fn = commitOpaque,
        .drain_fn = drainOpaque,
        .installed_fn = installedOpaque,
        .forward_begin_fn = forwardBeginOpaque,
        .forward_end_fn = forwardEndOpaque,
        .out = &e.step_out,
        .overlap = cfg.overlap != 0,
    };
    e.last_step_ns = 0;
    try createCommitRing(e, cfg);
    errdefer destroyCommitRing(e);
    const pipe_fds = try std.posix.pipe();
    errdefer {
        std.posix.close(pipe_fds[1]);
        std.posix.close(pipe_fds[0]);
    }
    // Non-blocking write end: a drain thread that falls behind must never stall the step loop
    // (see Engine.pipe_write_fd doc). The read end stays blocking -- Python's drain thread parks
    // in os.read, which is the point.
    const write_flags = try std.posix.fcntl(pipe_fds[1], std.posix.F.GETFL, 0);
    _ = try std.posix.fcntl(pipe_fds[1], std.posix.F.SETFL, write_flags | (1 << @bitOffsetOf(std.posix.O, "NONBLOCK")));
    e.pipe_read_fd = pipe_fds[0];
    e.pipe_write_fd = pipe_fds[1];
    e.grammars = try allocator.alloc(?xgrammar.Matcher, cfg.max_requests);
    errdefer allocator.free(e.grammars);
    @memset(e.grammars, null);
    e.commit_req_ids = try allocator.alloc(u32, cfg.max_batch_reqs);
    errdefer allocator.free(e.commit_req_ids);
    e.inbox = try inputs.Inbox.init(allocator, cfg.max_requests, cfg.max_seq_len, schedulerConfig(cfg));
    errdefer e.inbox.deinit(allocator);
    e.batch = try allocator.alloc(u32, e.inbox.capWords());
    errdefer allocator.free(e.batch);
    e.batch_in = &.{};
    e.batch_view = &.{};
    e.gens = try allocator.alloc(u32, cfg.max_requests);
    errdefer allocator.free(e.gens);
    @memset(e.gens, 0);
    e.sync = null;
    e.digest = 0;
    e.batch_hash = 0;
    e.prev_payload_hash = 0;
    e.diverged = .none;
    e.diverged_step = 0;
    e.payload_mine = &.{};
    e.payload_agreed = &.{};
    e.registry = .{};
    assert(e.groups.len == n_groups);
    return e;
}

/// Storage for the commit ring (Engine.ring_*), all of it at create: no allocation per commit.
fn createCommitRing(e: *Engine, cfg: KelpieConfig) !void {
    assert(cfg.max_requests > 0);
    e.ring_events = try allocator.alloc(events.StepEvent, commit_ring_capacity);
    errdefer allocator.free(e.ring_events);
    e.ring_advanced = try allocator.alloc(u32, commit_ring_capacity * cfg.max_requests);
    errdefer allocator.free(e.ring_advanced);
    e.ring_n_advanced = try allocator.alloc(u32, commit_ring_capacity);
    errdefer allocator.free(e.ring_n_advanced);
    e.ring_n_dropped = try allocator.alloc(u32, commit_ring_capacity);
    errdefer allocator.free(e.ring_n_dropped);
    e.carry_advanced = try allocator.alloc(u32, (cfg.max_requests + 31) / 32);
    @memset(e.carry_advanced, 0);
    e.ring_head = 0;
    e.ring_len = 0;
    e.carry_n_dropped = 0;
    assert(e.carry_advanced.len * 32 >= cfg.max_requests);
}

fn destroyCommitRing(e: *Engine) void {
    allocator.free(e.carry_advanced);
    allocator.free(e.ring_n_dropped);
    allocator.free(e.ring_n_advanced);
    allocator.free(e.ring_advanced);
    allocator.free(e.ring_events);
}

export fn kelpie_destroy(e_opt: ?*Engine) void {
    const e = e_opt orelse return;
    e.loop.stopAndJoin();
    std.posix.close(e.pipe_write_fd);
    std.posix.close(e.pipe_read_fd);
    destroyCommitRing(e);
    for (e.grammars) |maybe_matcher| {
        if (maybe_matcher) |m| xgrammar.matcherDestroy(m);
    }
    e.registry.deinit();
    if (e.payload_agreed.len > 0) allocator.free(e.payload_agreed);
    if (e.payload_mine.len > 0) allocator.free(e.payload_mine);
    if (e.batch_in.len > 0) allocator.free(e.batch_in);
    allocator.free(e.gens);
    allocator.free(e.batch);
    e.inbox.deinit(allocator);
    allocator.free(e.commit_req_ids);
    allocator.free(e.grammars);
    allocator.free(e.out_extra);
    allocator.free(e.out_n);
    allocator.free(e.out_tokens);
    for (&e.plan_scratch) |*scratch| scratch.deinit();
    e.sched.deinit(allocator);
    e.kv.deinit(allocator);
    e.reqs.deinit(allocator);
    allocator.free(e.max_blocks_per_req);
    if (e.group_bytes_per_page.len > 0) allocator.free(e.group_bytes_per_page);
    allocator.free(e.group_strides);
    allocator.free(e.group_cacheable);
    allocator.free(e.group_windows);
    allocator.free(e.group_block_sizes);
    allocator.free(e.group_kinds);
    allocator.free(e.groups);
    allocator.destroy(e);
}

/// Returns the request id, or -1 (Full), -2 (TooLong), -3 (empty prompt / bad args), -4 (Draining),
/// -5 (ExceedsKvPool: worst case above the pool; kelpie_worst_slabs gives the number), -6 (this
/// rank is a follower: only the edge takes submits).
///
/// The request enters the core at the next step boundary (a submit op, docs/design-multigpu.md
/// 2.3); until then poll reports it waiting with no tokens. Every rejection above is decided
/// here and returned synchronously -- a rejected submit never becomes an op (section 8 S1).
export fn kelpie_submit(e: *Engine, tokens: [*]const u32, n: u32, max_new: u32, temperature: f32) i64 {
    return kelpie_submit_mm_stop(e, tokens, n, max_new, temperature, 0, 0, undefined, 0, 0);
}

/// kelpie_submit with a multimodal content hash and the first placeholder position (request.Request.mm_hash /
/// mm_start); same return codes. mm_start must be < n when mm_hash != 0.
export fn kelpie_submit_mm(e: *Engine, tokens: [*]const u32, n: u32, max_new: u32, temperature: f32, mm_hash: u64, mm_start: u32) i64 {
    return kelpie_submit_mm_stop(e, tokens, n, max_new, temperature, mm_hash, mm_start, undefined, 0, 0);
}

pub const submit_not_edge: i64 = -6;

/// kelpie_submit_mm with a per-request stop token set (request.Request.stop_tokens), checked on
/// commit alongside KelpieConfig.eos_token, and a grammar: `grammar_key` names a grammar already
/// registered with kelpie_register_grammar (0 = none). n_stop must be <= request.max_stop_tokens;
/// stop_tokens may be any pointer when n_stop == 0. Same return codes as kelpie_submit, plus -3
/// when n_stop is too large, or the grammar key is unknown, or the engine cannot take a grammar
/// (vocab_words == 0, or max_extra > 0: grammar with extra rows stays refused, design 2.5).
export fn kelpie_submit_mm_stop(e: *Engine, tokens: [*]const u32, n: u32, max_new: u32, temperature: f32, mm_hash: u64, mm_start: u32, stop_tokens: [*]const u32, n_stop: u32, grammar_key: u64) i64 {
    return kelpie_submit_top_k(e, tokens, n, max_new, temperature, 0, mm_hash, mm_start, stop_tokens, n_stop, grammar_key);
}

pub const submit_bad_top_k: i64 = -7;

/// kelpie_submit_mm_stop with a caller top_k (0 = off, the whole vocabulary): a new export
/// rather than an appended parameter, so a binding built against the old signature keeps
/// calling a function whose arity it knows (additive ABI). The T=0 rule overrides top_k: a
/// temperature below kelpie_sampling_eps samples greedily (top_k 1) whatever was asked. Same
/// return codes as kelpie_submit_mm_stop, plus -7 when top_k > KelpieConfig.vocab_size (checked
/// only when vocab_size > 0).
export fn kelpie_submit_top_k(e: *Engine, tokens: [*]const u32, n: u32, max_new: u32, temperature: f32, top_k: u32, mm_hash: u64, mm_start: u32, stop_tokens: [*]const u32, n_stop: u32, grammar_key: u64) i64 {
    if (!isEdge(e)) return submit_not_edge;
    if (!request.validTopK(top_k, e.cfg.vocab_size)) return submit_bad_top_k;
    if (n == 0) return -3;
    if (mm_hash != 0 and mm_start >= n) return -3;
    if (n_stop > request.max_stop_tokens) return -3;
    if (!request.validTemperature(temperature)) return -3; // negative / NaN / inf: a caller error
    if (grammar_key != 0 and (e.cfg.vocab_words == 0 or e.cfg.max_extra > 0 or !e.registry.has(grammar_key))) return -3;
    {
        // The synchronous rejections read the core's live config and service state: the same
        // checks, in the same order, scheduler.submit made on the spot.
        e.loop.mutex.lock();
        defer e.loop.mutex.unlock();
        if (e.sched.state == .draining) return -4;
        const fits = @as(u64, n) + max_new <= e.cfg.max_seq_len;
        if (fits and scheduler.worstSlabs(&e.sched, n, max_new) > e.kv.slabs.len) return -5;
    }
    const id = e.inbox.submit(.{
        .prompt = tokens[0..n],
        .max_new = max_new,
        .temperature = temperature,
        .top_k = top_k,
        .mm = .{ .hash = mm_hash, .start = mm_start },
        .stop = stop_tokens[0..n_stop],
        .grammar_key = grammar_key,
        .t_arrival_ns = events.now(&e.sched.clock),
    }) catch |err| return switch (err) {
        error.Full => -1,
        error.TooLong => -2,
    };
    assert(id < e.cfg.max_requests);
    e.loop.wake();
    return id;
}

/// Registers a compiled grammar under `key` on this rank (an xgrammar::CompiledGrammar* from the
/// SAME libxgrammar this was linked against -- see xgrammar_shim/xgrammar_c.h; the handle is
/// copied, so the caller's stays its own). A submit may then name the key. On the edge this also
/// queues a grammar_prepare op carrying `source` (<= 64 KiB, opaque to the core) ahead of any
/// submit that names the key, so a follower can compile it before that submit applies (section 8
/// B3). Registering a key twice is a no-op. Returns 0 ok, -1 grammar support disabled / bad
/// handle, -2 registry or prepare queue full / source too long.
export fn kelpie_register_grammar(e: *Engine, key: u64, compiled_grammar_handle: ?*anyopaque, source: ?[*]const u8, n_source: u32) i32 {
    if (e.cfg.vocab_words == 0 or key == 0) return -1;
    const grammar = xgrammar.compiledGrammarWrap(compiled_grammar_handle) orelse return -1;
    const known = e.registry.has(key);
    e.registry.put(key, grammar) catch return -2;
    if (known or !isEdge(e)) return 0;
    const bytes: []const u8 = if (source) |ptr| ptr[0..n_source] else &.{};
    e.inbox.prepareGrammar(key, bytes) catch return -2;
    e.loop.wake();
    return 0;
}

/// Destroys and clears any matcher attached to req_id. Called under e.loop.mutex by every op
/// that ends a request's grammar lifetime (a submit into a reused slot, release, cancel) and by
/// kelpie_destroy -- the native-loop mirror of Python core.py's `_detach`.
fn detachGrammarUnlocked(e: *Engine, req_id: u32) void {
    if (e.grammars[req_id]) |m| {
        xgrammar.matcherDestroy(m);
        e.grammars[req_id] = null;
    }
}

/// Queues a cancel of the request now in `req_id`: it finishes `cancelled` at the next step
/// boundary, and poll reports it cancelled from now on. A no-op for an id with no request, one
/// already cancelled, or on a follower.
export fn kelpie_cancel(e: *Engine, req_id: u32) void {
    if (req_id >= e.cfg.max_requests or !isEdge(e)) return;
    if (e.inbox.cancel(req_id, null)) e.loop.wake();
}

/// kelpie_cancel of exactly the request that kelpie_generation named: if the id has been reused
/// since, the cancel is stale and does nothing (section 8 B2). Returns 1 queued, 0 no-op, -6
/// follower.
export fn kelpie_cancel_gen(e: *Engine, req_id: u32, gen: u32) i32 {
    if (!isEdge(e)) return @intCast(submit_not_edge);
    if (req_id >= e.cfg.max_requests) return 0;
    if (!e.inbox.cancel(req_id, gen)) return 0;
    e.loop.wake();
    return 1;
}

/// The generation of the request now holding `req_id` (read it right after submit): the
/// argument kelpie_cancel_gen wants. 0 for an id never used or out of range.
export fn kelpie_generation(e: *Engine, req_id: u32) u32 {
    if (req_id >= e.cfg.max_requests) return 0;
    return e.inbox.generation(req_id);
}

fn isEdge(e: *const Engine) bool {
    return if (e.sync) |sync| sync.edge else true;
}

/// One step boundary by hand, then the next batch: drain + exchange the inbox, apply it, plan,
/// agree -- the same boundary the loop runs (docs/design-multigpu.md 2.3), so a hand loop is a
/// rank like any other. Returns n_tokens; 0 means idle (only n_reqs, n_tokens and digest of
/// `out` are written), plan_diverged when the step cannot proceed (kelpie_divergence says why),
/// plan_stopped when the edge's batch said stop. Every plan must be followed by exactly one
/// commit (kelpie_commit with n == 0 when idle).
export fn kelpie_plan(e: *Engine, out: *KelpiePlan) u32 {
    if (e.diverged != .none) return plan_diverged;
    if (boundaryUnlocked(e, false)) return plan_stopped;
    var n: u32 = undefined;
    {
        e.loop.mutex.lock();
        defer e.loop.mutex.unlock();
        applyBatch(e) catch |err| return divergedAt(e, err);
        n = planUnlocked(e, out, 0);
    }
    agreeUnlocked(e, out.digest) catch |err| return divergedAt(e, err);
    return n;
}

fn divergedAt(e: *Engine, err: DivergenceError) u32 {
    e.diverged = divergenceOf(err);
    e.diverged_step = e.sched.step + @intFromBool(err != error.Digest);
    return plan_diverged;
}

const DivergenceError = error{ BadBatch, LaggedDigest, LaggedPayload, Boundary, Digest, Payload };

fn divergenceOf(err: DivergenceError) Divergence {
    return switch (err) {
        error.BadBatch => .bad_batch,
        error.LaggedDigest => .lagged_digest,
        error.LaggedPayload => .lagged_payload,
        error.Boundary => .boundary,
        error.Digest => .digest,
        error.Payload => .payload,
    };
}

/// Why and at which step a by-hand step stopped (Divergence ordinal; none = 0). The step is
/// the plan the failed boundary or agreement belonged to.
export fn kelpie_divergence(e: *Engine, step: ?*u64) u32 {
    if (step) |ptr| ptr.* = e.diverged_step;
    return @intFromEnum(e.diverged);
}

/// The digest of the last plan (idle plans included); 0 before the first.
export fn kelpie_last_digest(e: *Engine) u64 {
    e.loop.mutex.lock();
    defer e.loop.mutex.unlock();
    return e.digest;
}

/// The unlocked half of a boundary: the edge drains its inbox into `batch`; with a sync
/// registered the exchange replaces it with the edge's batch. -> whether that batch says stop.
/// Runs on the stepping thread with no engine lock held.
fn boundaryUnlocked(e: *Engine, stopping: bool) bool {
    const flags: u32 = if (stopping) inputs.flag_stop else 0;
    const n_mine: u32 = if (isEdge(e)) e.inbox.drain(e.batch, e.digest, e.prev_payload_hash, flags) else 0;
    const sync = e.sync orelse {
        e.batch_view = e.batch[0..n_mine];
        return stopping;
    };
    const mine = std.mem.sliceAsBytes(e.batch[0..n_mine]);
    const cap: u32 = @intCast(e.batch_in.len * 4);
    const got = sync.exchange(sync.ctx, mine.ptr, @intCast(mine.len), std.mem.sliceAsBytes(e.batch_in).ptr, cap);
    // A failed or ragged exchange leaves an empty view, which apply refuses as a bad batch.
    e.batch_view = if (got > cap or got % 4 != 0) &.{} else e.batch_in[0 .. got / 4];
    if (e.batch_view.len < inputs.header_words) return false;
    return inputs.headerOf(e.batch_view).flags & inputs.flag_stop != 0;
}

/// Applies the boundary's batch, in op order (loop.mutex held). Validates the whole batch and
/// the edge's lagged digests first, so a bad batch applies nothing.
fn applyBatch(e: *Engine) DivergenceError!void {
    const words = e.batch_view;
    const limits = inputs.Limits{ .max_requests = e.cfg.max_requests, .max_seq_len = e.cfg.max_seq_len, .max_source_bytes = inputs.max_source_bytes, .vocab_size = e.cfg.vocab_size };
    const header = inputs.validate(words, limits, &e.sched) catch return error.BadBatch;
    if (header.prev_digest != e.digest) return error.LaggedDigest;
    if (header.prev_payload_hash != e.prev_payload_hash) return error.LaggedPayload;
    // The plan after boundary b is step b: what makes KelpieSetResult.apply_step exact (S3).
    if (header.boundary != e.sched.step + 1) return error.Boundary;
    e.batch_hash = inputs.hashOf(words);
    e.sched.live().building.n_rejected_full += header.n_rejected_full;
    var r = inputs.Reader.of(words);
    while (r.next()) |op| switch (op) {
        .submit => |sub| applySubmit(e, sub),
        .cancel => |ref| applyCancel(e, ref),
        .release => |ref| applyRelease(e, ref),
        .knob => |knob| scheduler.applyKnob(&e.sched, knob),
        .swap => |swap| applySwap(e, swap),
        // The edge registered the grammar before it queued this op; a follower compiles from
        // `source` and registers it (rung 1). The submit that needs the key waits for it.
        .grammar_prepare => {},
    };
    // With overlap a cancel may leave the core holding the slot until the in-flight commit.
    if (e.cfg.overlap != 0) e.inbox.reconcile(&e.reqs);
}

fn applySubmit(e: *Engine, sub: inputs.Submit) void {
    const id = sub.id;
    detachGrammarUnlocked(e, id); // reused slot: drop any matcher from its previous occupant
    // The T=0 rule runs here, on every rank, from the wire's raw temperature and top_k.
    const params = request.samplingParams(sub.max_new, sub.temperature, sub.top_k);
    scheduler.submitAt(&e.sched, id, sub.prompt, params, sub.mm, sub.stop, sub.t_arrival_ns);
    e.gens[id] = sub.gen;
    e.inbox.appliedSubmit(id, sub.gen);
    // S2: re-checked against the live config, which a knob in this or an earlier batch may have
    // moved since the edge accepted it. The verdict is a function of core state, so every rank
    // reaches it; the request closes cancelled and keeps its slot until its release.
    if (scheduler.worstSlabs(&e.sched, @intCast(sub.prompt.len), sub.max_new) > e.kv.slabs.len) {
        scheduler.rejectAt(&e.sched, id);
        return;
    }
    if (sub.grammar_key != 0) {
        const grammar = e.registry.wait(sub.grammar_key);
        e.grammars[id] = xgrammar.matcherCreate(grammar) orelse std.debug.panic("xgrammar matcher create failed for key {x}", .{sub.grammar_key});
    }
}

fn applyCancel(e: *Engine, ref: inputs.Ref) void {
    if (e.gens[ref.id] != ref.gen) return; // stale: the slot has a newer occupant (or never had this one)
    const req = &e.reqs.requests[ref.id];
    if (!req.owned) return; // released already
    detachGrammarUnlocked(e, ref.id);
    // Already cancelled: held for the plan in flight (its commit releases it), or closed by an
    // S2 reject at apply, which keeps its slot until a release -- this cancel is that release.
    if (req.state == .cancelled) {
        _ = scheduler.release(&e.sched, ref.id);
        return;
    }
    scheduler.cancel(&e.sched, ref.id);
}

fn applyRelease(e: *Engine, ref: inputs.Ref) void {
    if (e.gens[ref.id] != ref.gen) return;
    const req = &e.reqs.requests[ref.id];
    if (!req.owned) return; // a cancel in the same batch got there first
    // Only a poll that saw it finished queues a release, and a finished request is in no plan.
    assert(request.isFinished(req));
    detachGrammarUnlocked(e, ref.id);
    assert(scheduler.release(&e.sched, ref.id));
}

/// The swap's launch context was registered locally before the op was queued (S6); on a
/// follower it may still be on its way, so wait for it, bounded.
fn applySwap(e: *Engine, swap: inputs.Swap) void {
    var timer = std.time.Timer.start() catch unreachable;
    const reg = while (true) {
        if (e.inbox.takeSwap(swap.epoch)) |reg| break reg;
        if (timer.read() > 30 * std.time.ns_per_s) std.debug.panic("swap epoch {d} never registered on this rank", .{swap.epoch});
        std.time.sleep(std.time.ns_per_ms);
    };
    assert(reg.drain == swap.drain);
    e.loop.setPendingLocked(.{ .launch = @ptrCast(@alignCast(reg.launch)), .captured = reg.captured, .drain = reg.drain, .epoch = reg.epoch });
}

/// The digest agreement for the plan just made (no lock held). World 1: nothing to agree with.
fn agreeUnlocked(e: *Engine, digest: u64) DivergenceError!void {
    const sync = e.sync orelse return;
    const agree = sync.agree orelse return;
    if (agree(sync.ctx, digest) != 0) return error.Digest;
}

/// KelpiePlan.shape: a deterministic function of this plan alone, packed so a native launch fn
/// (or Python's ModelStep.shape_for) can recompute the identical value without a wire struct.
/// Bits: [19:16] max n_extra (K, capped 15) | [15:12] has_prefill (1 bit at 12) |
/// [11:8] padded_num_reqs bucket index | [7:0] padded_num_tokens bucket index (mirrors
/// kelpie_models.plan.StepShape.padded_num_tokens/padded_num_reqs/K; mode/dtype/flags are
/// per-CapturedModel constants and never travel here -- docs/m2-zig-loop.md).
/// `r_pad` is the padded request count (reqsPadded), so the key names the request axis the
/// plan's arrays actually have.
fn stepShape(n_tokens: u32, r_pad: u32, kinds: []const u32, n_extra: []const u32) u32 {
    assert(n_tokens >= kinds.len and kinds.len > 0);
    assert(r_pad >= kinds.len and buckets.bucket(r_pad) == r_pad);
    assert(kinds.len == n_extra.len);
    var max_k: u32 = 0;
    var has_prefill: u32 = 0;
    for (kinds, n_extra) |kind, k| {
        max_k = @max(max_k, k);
        if (kind == @intFromEnum(scheduler.Kind.prefill)) has_prefill = 1;
    }
    const capped_k: u32 = @min(max_k, 15);
    return buckets.bucketIndex(n_tokens) | (buckets.bucketIndex(r_pad) << 8) | (has_prefill << 12) | (capped_k << 16);
}

/// The padded request count. A plan pads each axis to its own bucket, except a DECODE_EXTRA plan
/// (every entry a decode, some carrying extra rows): kelpie_models keys that family by its token
/// bucket alone (sdk/shapes.py), and one captured program per key needs one request axis per
/// key. So its request axis pads to the most entries that token bucket can hold -- an entry with
/// extra rows is >= 2 rows, so n_reqs <= t_pad - 1 -- capped by the plan buffers (`cap`,
/// bucket(max_batch_reqs) at create: fixed for the engine's life, unlike the live knob).
fn reqsPadded(n_reqs: u32, t_pad: u32, cap: u32, kinds: []const u32, n_extra: []const u32) u32 {
    assert(n_reqs > 0 and n_reqs == kinds.len and n_reqs <= cap);
    var decode_only = true;
    var any_extra = false;
    for (kinds, n_extra) |kind, k| {
        if (kind != @intFromEnum(scheduler.Kind.decode)) decode_only = false;
        if (k > 0) any_extra = true;
    }
    if (!(decode_only and any_extra)) return buckets.bucket(n_reqs);
    assert(t_pad >= 2); // one history row and at least one extra row
    const r_pad = @min(buckets.bucket(t_pad - 1), cap);
    assert(r_pad >= buckets.bucket(n_reqs));
    return r_pad;
}

/// Pads the scheduler's plan buffers out to the bucket, in place, and fills row_request.
///
/// The core is the one padder. Everything below the ABI (kelpie_models.plan.plan_step's fill,
/// launch.c's staging table) copies these arrays verbatim, so the two fillers cannot disagree
/// about a pad value the way they did for five days (docs/friction-2026-09-09.md 1).
///
/// Every pad is inert by value, matching docs/model-contract.md 2 exactly:
///   rows    [n_tokens, n_tokens_padded): inertRows, position 0, row_request -1.
///   entries [n_reqs, n_reqs_padded): inertEntries, and an empty query (query_start_loc
///           repeats n_tokens, so q1 - q0 == 0), seq_len 1, kind PREFILL, n_work 0, n_extra 0.
fn padPlan(e: *Engine, scratch: *PlanScratch, p: *const scheduler.Plan, t_pad: u32, r_pad: u32) void {
    const n_tokens = p.n_tokens;
    const n_reqs = p.n_reqs;
    assert(t_pad >= n_tokens and r_pad >= n_reqs);
    assert(t_pad <= p.input_ids.len and r_pad <= p.seq_lens.len);

    inertRows(e, p, n_tokens, t_pad);
    @memset(p.positions[n_tokens..t_pad], 0);
    inertEntries(e, scratch, p, n_reqs, r_pad);
    for (n_reqs..r_pad) |i| {
        // The tail repeats n_tokens, so every pad request's query is empty.
        p.query_start_loc[i + 1] = n_tokens;
        p.seq_lens[i] = 1;
        scratch.n_work[i] = 0;
        scratch.kinds[i] = @intFromEnum(scheduler.Kind.prefill);
        scratch.n_extra[i] = 0;
    }
    // row_request: the owning entry of every real row, -1 for the pad rows.
    for (0..n_reqs) |i| {
        const q0 = p.query_start_loc[i];
        const q1 = p.query_start_loc[i + 1];
        for (q0..q1) |row| scratch.row_request[row] = @intCast(i);
    }
    @memset(scratch.row_request[n_tokens..t_pad], -1);
}

/// The scratch slot of a group: the last slot of null block 0, so a write there lands on
/// storage nothing reads. Never -1 -- no negative slot ever reaches a device. A per_seq group
/// has no slots (its state goes through plan.state): kv_pool.null_block.
fn scratchSlot(group: request.GroupSpec) u32 {
    return if (group.kind == .per_seq) kv_pool.null_block else group.block_size - 1;
}

/// The inert VALUES of rows [from, to): input_id 0 and every group's slot the scratch slot.
/// The one writer of them, for padPlan's pad rows and a synthetic plan's rows alike. Positions
/// and row_request are structure, written by the caller.
fn inertRows(e: *const Engine, p: *const scheduler.Plan, from: u32, to: u32) void {
    assert(from <= to and to <= p.input_ids.len);
    @memset(p.input_ids[from..to], 0);
    for (p.slot_mapping, e.groups) |slots, group| @memset(slots[from..to], scratchSlot(group));
}

/// The inert VALUES of entries [from, to) (docs/design-core-option2.md section 8 item 3): an
/// all-null block table row, seq_start 0, emits 0, temperature 1 / top_k 1 (greedy in the T=0
/// rule's rewritten form, so an all-greedy batch stays all-greedy over its whole padded width),
/// mm_hash 0, req_id 0 (what Python's plan_step used for pads, so sample_key folds the same
/// value), an all-ones logit mask row, and per_seq state reading ZERO and writing SCRATCH with
/// no checkpoint. The one writer of them, for padPlan's pads and a synthetic plan's entries.
/// The query partition, seq_len, kind, n_work and n_extra are structure, written by the caller.
fn inertEntries(e: *const Engine, scratch: *PlanScratch, p: *const scheduler.Plan, from: u32, to: u32) void {
    assert(from <= to and to <= p.seq_lens.len);
    @memset(p.temperatures[from..to], 1);
    @memset(p.top_ks[from..to], 1);
    @memset(p.mm_hashes[from..to], 0);
    @memset(p.seq_start[from..to], 0);
    @memset(p.emits[from..to], 0);
    @memset(scratch.req_ids[from..to], 0);
    for (p.state, p.zero_units) |idx, zero| {
        if (idx.read.len == 0) continue; // per_token
        @memset(idx.read[from..to], zero);
        @memset(idx.write[from * p.write_width .. to * p.write_width], scheduler.scratch_unit);
        @memset(idx.ckpt[from..to], scheduler.scratch_unit);
        @memset(idx.ckpt_row[from..to], request.no_row);
    }
    const width = p.max_blocks_per_req;
    for (p.block_tables) |tables| @memset(tables[from * width .. to * width], kv_pool.null_block);
    const words = e.cfg.vocab_words;
    if (words != 0) @memset(scratch.logit_mask[from * words .. to * words], -1);
}

fn fillPlan(e: *Engine, out: *KelpiePlan, p: *const scheduler.Plan, slot: u32) u32 {
    const scratch = &e.plan_scratch[slot];
    if (p.n_tokens == 0) {
        out.n_reqs = 0;
        out.n_tokens = 0;
        var h = std.hash.Wyhash.init(0);
        hashInts(&h, .{ e.sched.step, @as(u32, 0), e.sched.config_hash, e.batch_hash, e.prev_payload_hash });
        out.digest = h.final();
        e.digest = out.digest;
        return 0;
    }
    assert(p.n_reqs <= e.cfg.max_batch_reqs);
    assert(p.entries.len >= p.n_reqs);
    for (p.entries[0..p.n_reqs], 0..) |entry, i| {
        scratch.req_ids[i] = entry.req_id;
        scratch.n_work[i] = entry.n_work;
        scratch.kinds[i] = @intFromEnum(entry.kind);
        scratch.n_extra[i] = entry.n_extra;
    }
    fillLogitMask(e, scratch, p.entries[0..p.n_reqs]);
    publishPlan(e, out, p, scratch);
    out.digest = planDigest(e, out);
    e.digest = out.digest;
    return p.n_tokens;
}

/// Pads `p` to bucket(n_tokens) x reqsPadded and points `out` at it and at `scratch` (whose
/// real entries the caller filled). The one assembler of a KelpiePlan, for a real plan
/// (fillPlan) and a synthetic one (kelpie_synthetic_plan) alike, so a synthetic plan's pads and
/// `shape` are by construction a real plan's. Leaves out.digest 0: the caller owns the digest.
fn publishPlan(e: *Engine, out: *KelpiePlan, p: *const scheduler.Plan, scratch: *PlanScratch) void {
    assert(p.n_reqs > 0 and p.n_tokens >= p.n_reqs);
    @memset(scratch.max_blocks_per_req, p.max_blocks_per_req);
    for (scratch.slot_mapping_ptrs, p.slot_mapping) |*dst, src| dst.* = src.ptr;
    for (p.state, scratch.state_read_ptrs, scratch.state_write_ptrs, scratch.state_ckpt_ptrs, scratch.state_ckpt_row_ptrs) |idx, *read, *write, *ckpt, *ckpt_row| {
        const is_seq = idx.read.len > 0;
        read.* = if (is_seq) idx.read.ptr else null;
        write.* = if (is_seq) idx.write.ptr else null;
        ckpt.* = if (is_seq) idx.ckpt.ptr else null;
        ckpt_row.* = if (is_seq) idx.ckpt_row.ptr else null;
    }
    for (scratch.block_table_ptrs, p.block_tables) |*dst, src| dst.* = src.ptr;
    // Pad last: the caller wrote the real rows and entries, padPlan the rest.
    const t_pad = buckets.bucket(p.n_tokens);
    const kinds = scratch.kinds[0..p.n_reqs];
    const n_extra = scratch.n_extra[0..p.n_reqs];
    const r_pad = reqsPadded(p.n_reqs, t_pad, @intCast(p.seq_lens.len), kinds, n_extra);
    padPlan(e, scratch, p, t_pad, r_pad);
    out.* = .{
        .n_reqs = p.n_reqs,
        .n_tokens = p.n_tokens,
        .n_reqs_padded = r_pad,
        .n_tokens_padded = t_pad,
        .row_request = scratch.row_request.ptr,
        .n_groups = e.cfg.n_groups,
        .req_ids = scratch.req_ids.ptr,
        .n_work = scratch.n_work.ptr,
        .input_ids = p.input_ids.ptr,
        .positions = p.positions.ptr,
        .query_start_loc = p.query_start_loc.ptr,
        .seq_lens = p.seq_lens.ptr,
        .slot_mapping = scratch.slot_mapping_ptrs.ptr,
        .block_tables = scratch.block_table_ptrs.ptr,
        .max_blocks_per_req = scratch.max_blocks_per_req.ptr,
        .temperatures = p.temperatures.ptr,
        .top_ks = p.top_ks.ptr,
        .mm_hashes = p.mm_hashes.ptr,
        .kinds = scratch.kinds.ptr,
        .n_extra = scratch.n_extra.ptr,
        .logit_mask = if (e.cfg.vocab_words == 0) null else scratch.logit_mask.ptr,
        .step = e.sched.step,
        .shape = stepShape(p.n_tokens, r_pad, kinds, n_extra),
        .seq_start = p.seq_start.ptr,
        .emits = p.emits.ptr,
        .max_extra = e.cfg.max_extra,
        .zero_unit = p.zero_units.ptr,
        .state_read = scratch.state_read_ptrs.ptr,
        .state_write = scratch.state_write_ptrs.ptr,
        .state_ckpt = scratch.state_ckpt_ptrs.ptr,
        .state_ckpt_row = scratch.state_ckpt_row_ptrs.ptr,
        .digest = 0,
    };
}

/// The plan digest (docs/design-multigpu.md 2.3): everything a rank's forward reads from the
/// plan, plus the batch applied before it and the previous payload. O(tokens + used blocks):
/// block tables contribute only each real entry's used prefix (a full max_blocks row can be MBs),
/// and logit_mask is left out (up to 25 KB a row, and rank 0's payload decides the tokens).
fn planDigest(e: *const Engine, out: *const KelpiePlan) u64 {
    var h = std.hash.Wyhash.init(0);
    const r = out.n_reqs_padded;
    const t = out.n_tokens_padded;
    hashInts(&h, .{ out.step, out.shape, out.n_reqs, out.n_tokens, e.sched.config_hash, r, t });
    hashSlice(&h, out.req_ids[0..r]);
    hashSlice(&h, out.n_work[0..r]);
    hashSlice(&h, out.kinds[0..r]);
    hashSlice(&h, out.n_extra[0..r]);
    hashSlice(&h, out.seq_start[0..r]);
    hashSlice(&h, out.emits[0..r]);
    hashSlice(&h, out.seq_lens[0..r]);
    hashSlice(&h, out.query_start_loc[0 .. r + 1]);
    hashSlice(&h, out.temperatures[0..r]);
    hashSlice(&h, out.top_ks[0..r]);
    hashSlice(&h, out.mm_hashes[0..r]);
    hashSlice(&h, out.input_ids[0..t]);
    hashSlice(&h, out.positions[0..t]);
    hashSlice(&h, out.row_request[0..t]);
    const width = 1 + out.max_extra;
    for (e.groups, 0..) |group, g| {
        hashSlice(&h, out.slot_mapping[g][0..t]);
        if (group.kind == .per_seq) {
            hashSlice(&h, out.state_read[g].?[0..r]);
            hashSlice(&h, out.state_write[g].?[0 .. r * width]);
            hashSlice(&h, out.state_ckpt[g].?[0..r]);
            hashSlice(&h, out.state_ckpt_row[g].?[0..r]);
            continue;
        }
        const row_width = out.max_blocks_per_req[g];
        for (0..out.n_reqs) |i| {
            const used = @min(request.rowsFor(group, out.seq_lens[i]), row_width);
            hashSlice(&h, out.block_tables[g][i * row_width ..][0..used]);
        }
    }
    hashInts(&h, .{ e.batch_hash, e.prev_payload_hash });
    return h.final();
}

fn hashSlice(h: *std.hash.Wyhash, items: anytype) void {
    h.update(std.mem.sliceAsBytes(items));
}

fn hashInts(h: *std.hash.Wyhash, ints: anytype) void {
    inline for (ints) |v| {
        const x = v;
        h.update(std.mem.asBytes(&x));
    }
}

/// Fills scratch.logit_mask[i] for every planned entry (one row per entry, cfg.vocab_words
/// wide): all-ones (0xFFFFFFFF, every bit set) for an entry with no grammar attached, or
/// whatever xgrammar_matcher_fill writes otherwise. Mirrors kelpie-engine/kelpie_engine/grammar.py's
/// logit_masks / kelpie-engine/kelpie_engine/core.py's `logit_masks` exactly, including filling
/// unconditionally per entry regardless of Kind (prefill or decode) -- see commitAcceptGrammar's
/// doc comment for why that matches Python's existing (not obviously intentional, but
/// unchanged-here) behavior rather than diverging from it.
/// TODO(grammar-prefill): a mid-prefill-chunk entry's mask is filled and then never consulted
/// (commitEntry discards its sampled token before it would reach commitAcceptGrammar's accept
/// call below), so this is wasted xgrammar work on every prefill step of a grammared request,
/// not a correctness issue. Skipping non-decode, non-prompt-complete entries here would be a
/// real optimization; left as Python already has it for parity, flag if this shows up in
/// profiling.
fn fillLogitMask(e: *Engine, scratch: *PlanScratch, entries: []const scheduler.Entry) void {
    if (e.cfg.vocab_words == 0) return;
    const words = e.cfg.vocab_words;
    for (entries, 0..) |entry, i| {
        const row = scratch.logit_mask[i * words ..][0..words];
        const matcher = e.grammars[entry.req_id] orelse {
            @memset(row, -1); // 0xFFFFFFFF per word: no grammar attached for this entry's request
            continue;
        };
        // Route through fill unconditionally, terminated or not: xgrammar's own
        // FillNextTokenBitmask already writes an EOS-only row for a terminated matcher
        // (docs/grammar-design.md section 2), matching Python's logit_masks, which likewise
        // never special-cases terminated before calling g.fill.
        if (!xgrammar.matcherFill(matcher, row.ptr, @intCast(words))) {
            // fill failed (shim-internal exception, e.g. a length mismatch bug): fail CLOSED
            // (reject every token) rather than silently dropping the grammar constraint for this
            // step -- an all-ones row here would make the request emit ungoverned output with no
            // visible signal. All-zero forces ops.sample's documented dead-end path (token 0,
            // no allowed token), which the accept side below turns into grammar_dead_end -- loud,
            // not silent.
            @memset(row, 0);
        }
    }
}

/// kelpie_synthetic_plan's status. Nothing is written to `out` unless it returns ok.
pub const SyntheticStatus = enum(i32) {
    ok = 0,
    /// A plan is outstanding (planned, not committed) or the native loop is running: both own
    /// the plan buffers a synthetic plan writes.
    err_busy = -1,
    /// kind is not 0/1, or the shape is one no real plan has: a decode entry is exactly one
    /// history row (scheduler.kindOf), and extra rows follow only a decode (scheduler.extraFor).
    err_kind = -2,
    err_n_reqs = -3, // n_reqs == 0 or > the live max_batch_reqs
    err_rows = -4, // rows == 0
    err_tokens = -5, // n_reqs * (rows + n_extra) > the live max_batch_tokens
    err_extra = -6, // n_extra > max_extra
    err_seq_len = -7, // rows + n_extra > max_seq_len
};

/// A warm-up plan: n_reqs real entries of `kind` (0 prefill, 1 decode), each `rows` history rows
/// then `n_extra` extra rows, padded to bucket(n_tokens) x reqsPadded by padPlan and keyed by
/// stepShape -- the functions a real plan goes through, so its `shape` is by construction the
/// key a real plan of that family and bucket carries, and its pads are a real plan's pads.
///
/// Every real row is inert BY VALUE like a pad (inertRows / inertEntries: scratch slots, null
/// block tables, ZERO/SCRATCH state, temperature 1 / top_k 1, all-ones mask, emits 0, req_id
/// 0), but the STRUCTURE is real: query_start_loc partitions the rows per entry, row_request
/// names the entry, positions run 0..rows+n_extra-1 within each entry from seq_start 0,
/// seq_lens are rows + n_extra, and an extra row's input_id is KELPIE_NO_TOKEN (the caller
/// fills it, exactly as in a real plan).
///
/// Changes no engine state: no step, no digest (out.digest is 0 -- a synthetic plan is agreed
/// with nobody), no scheduler/request/kv change, no inbox op. It writes the plan buffers a real
/// plan uses, so it is refused (err_busy) while a plan is outstanding or the loop runs; `out`
/// is valid until the next kelpie_plan / kelpie_synthetic_plan. Never commit it.
export fn kelpie_synthetic_plan(e: *Engine, kind: u32, n_reqs: u32, rows: u32, n_extra: u32, out: *KelpiePlan) i32 {
    e.loop.mutex.lock();
    defer e.loop.mutex.unlock();
    if (loopAliveLocked(e) or e.sched.planned()) return @intFromEnum(SyntheticStatus.err_busy);
    const status = checkSynthetic(e, kind, n_reqs, rows, n_extra);
    if (status != .ok) return @intFromEnum(status);
    const step_before = e.sched.step;
    const digest_before = e.digest;
    // A copy of the live arena's Plan header: its slices alias the arena's buffers (which the
    // next real plan rewrites wholesale), but the scheduler's own n_reqs / n_tokens stay put.
    var p = e.sched.live().plan;
    const scratch = &e.plan_scratch[0]; // kelpie_plan's slot: the by-hand plan's buffers
    fillSynthetic(e, scratch, &p, @enumFromInt(kind), n_reqs, rows, n_extra);
    publishPlan(e, out, &p, scratch);
    assert(out.digest == 0);
    assert(e.sched.step == step_before);
    assert(e.digest == digest_before);
    return @intFromEnum(SyntheticStatus.ok);
}

/// The boundary checks of kelpie_synthetic_plan, against the LIVE batch limits (the ones a
/// real plan is built under right now) and the create-time max_extra / max_seq_len.
fn checkSynthetic(e: *const Engine, kind: u32, n_reqs: u32, rows: u32, n_extra: u32) SyntheticStatus {
    if (kind > @intFromEnum(scheduler.Kind.decode)) return .err_kind;
    const is_decode = kind == @intFromEnum(scheduler.Kind.decode);
    if (is_decode and rows != 1) return .err_kind;
    if (!is_decode and n_extra != 0) return .err_kind;
    if (n_reqs == 0 or n_reqs > e.sched.cfg.max_batch_reqs) return .err_n_reqs;
    if (rows == 0) return .err_rows;
    if (n_extra > e.cfg.max_extra) return .err_extra;
    const per_entry = @as(u64, rows) + n_extra;
    if (per_entry > e.cfg.max_seq_len) return .err_seq_len;
    if (per_entry * n_reqs > e.sched.cfg.max_batch_tokens) return .err_tokens;
    return .ok;
}

/// Writes a synthetic plan's real rows and entries into `p` (header local, buffers the arena's)
/// and `scratch`: the inert values from inertRows / inertEntries, then the structure.
fn fillSynthetic(e: *Engine, scratch: *PlanScratch, p: *scheduler.Plan, kind: scheduler.Kind, n_reqs: u32, rows: u32, n_extra: u32) void {
    const per_entry = rows + n_extra;
    p.n_reqs = n_reqs;
    p.n_tokens = n_reqs * per_entry;
    assert(p.n_tokens <= p.input_ids.len and n_reqs <= p.seq_lens.len);
    inertRows(e, p, 0, p.n_tokens);
    inertEntries(e, scratch, p, 0, n_reqs);
    p.query_start_loc[0] = 0;
    for (0..n_reqs) |i| {
        const start: u32 = @intCast(i * per_entry);
        for (0..per_entry) |j| p.positions[start + j] = @intCast(j);
        // An extra row's input_id is the caller's to fill, as in a real plan (emitEntry).
        @memset(p.input_ids[start + rows ..][0..n_extra], scheduler.no_token);
        p.query_start_loc[i + 1] = start + per_entry;
        p.seq_lens[i] = per_entry;
        scratch.n_work[i] = rows;
        scratch.kinds[i] = @intFromEnum(kind);
        scratch.n_extra[i] = n_extra;
    }
    assert(p.query_start_loc[n_reqs] == p.n_tokens);
}

fn loopAliveLocked(e: *const Engine) bool {
    return e.loop.thread != null and !e.loop.exited;
}

fn planUnlocked(e: *Engine, out: *KelpiePlan, slot: u32) u32 {
    const p = scheduler.plan(&e.sched);
    return fillPlan(e, out, p, slot);
}

/// Applies c to the plan in flight (see KelpieCommit), or nothing and an error status. Every
/// plan must be followed by exactly one commit; an idle plan (n_tokens 0) closes with
/// n_entries 0. With a sync registered the payload is agreed first (section 8 B4): rank 0's
/// wins, so every rank commits identical bytes; a follower may pass NULL (it has no say).
export fn kelpie_commit(e: *Engine, c_ptr: ?*const KelpieCommit) i32 {
    const n_live = blk: {
        e.loop.mutex.lock();
        defer e.loop.mutex.unlock();
        if (!e.sched.planned()) return @intFromEnum(CommitStatus.err_entries); // no plan in flight
        break :blk e.sched.live().plan.n_reqs;
    };
    var c: KelpieCommit = if (c_ptr) |ptr| ptr.* else blk: {
        if (e.sync == null or isEdge(e)) return @intFromEnum(CommitStatus.err_entries);
        break :blk .{ .n_entries = n_live, .stride = e.step_out.stride, .tokens = null, .n_tokens = null, .next_extra = null };
    };
    if (e.sync != null and n_live > 0) {
        // Agree first (no lock): the commit that applies is the edge's, on every rank.
        if (isEdge(e)) {
            const status = checkShape(e, c, n_live);
            if (status != .ok) return @intFromEnum(status);
            stageStepOut(e, c);
        }
        agreePayload(e, n_live) catch return @intFromEnum(CommitStatus.err_count);
        c = stepOutCommit(e, n_live);
    }
    e.loop.mutex.lock();
    defer e.loop.mutex.unlock();
    const status = validateCommit(e, c);
    if (status.status != .ok) return @intFromEnum(status.status);
    commitValidated(e, c);
    return @intFromEnum(CommitStatus.ok);
}

/// The shape checks that must pass before a payload can even be staged: n matches the plan,
/// tokens present, the stride holds every count and fits the engine's StepOut.
fn checkShape(e: *const Engine, c: KelpieCommit, n_live: u32) CommitStatus {
    if (c.n_entries != n_live) return .err_entries;
    if (c.n_entries > 0 and c.tokens == null) return .err_entries;
    if (c.n_entries > 0 and c.stride == 0) return .err_count;
    if (c.n_tokens) |counts| for (counts[0..c.n_entries]) |count| {
        if (count > c.stride or count > e.step_out.stride) return .err_count;
    };
    return .ok;
}

/// Copies a KelpieCommit into the engine's StepOut layout (the one form payload agreement and
/// the loop's commit read). Caller ran checkShape.
fn stageStepOut(e: *Engine, c: KelpieCommit) void {
    const stride = e.step_out.stride;
    for (0..c.n_entries) |i| {
        const count = if (c.n_tokens) |counts| counts[i] else 1;
        e.out_n[i] = count;
        e.out_extra[i] = if (c.next_extra) |extra| extra[i] else 0;
        @memcpy(e.out_tokens[i * stride ..][0..count], c.tokens.?[i * c.stride ..][0..count]);
    }
}

fn stepOutCommit(e: *const Engine, n: u32) KelpieCommit {
    return .{ .n_entries = n, .stride = e.step_out.stride, .tokens = e.out_tokens.ptr, .n_tokens = e.out_n.ptr, .next_extra = e.out_extra.ptr };
}

/// Payload agreement (section 8 B4): this rank's StepOut goes out as [n, then per entry count,
/// next_extra, kept tokens]; rank 0's comes back and overwrites the StepOut. No lock held.
fn agreePayload(e: *Engine, n: u32) DivergenceError!void {
    const sync = e.sync orelse return;
    const stride = e.step_out.stride;
    var pos: usize = 0;
    e.payload_mine[pos] = n;
    pos += 1;
    for (0..n) |i| {
        const count = @min(e.out_n[i], stride); // garbage in stays in bounds; validate refuses it
        e.payload_mine[pos] = count;
        e.payload_mine[pos + 1] = e.out_extra[i];
        pos += 2;
        @memcpy(e.payload_mine[pos..][0..count], e.out_tokens[i * stride ..][0..count]);
        pos += count;
    }
    const mine = std.mem.sliceAsBytes(e.payload_mine[0..pos]);
    const cap: u32 = @intCast(e.payload_agreed.len * 4);
    const got = sync.exchange(sync.ctx, mine.ptr, @intCast(mine.len), std.mem.sliceAsBytes(e.payload_agreed).ptr, cap);
    if (got > cap or got % 4 != 0) return error.Payload;
    const words = e.payload_agreed[0 .. got / 4];
    if (words.len < 1 or words[0] != n) return error.Payload;
    pos = 1;
    for (0..n) |i| {
        if (words.len < pos + 2) return error.Payload;
        const count = words[pos];
        if (count > stride or words.len < pos + 2 + count) return error.Payload;
        e.out_n[i] = count;
        e.out_extra[i] = words[pos + 1];
        pos += 2;
        @memcpy(e.out_tokens[i * stride ..][0..count], words[pos..][0..count]);
        pos += count;
    }
    if (pos != words.len) return error.Payload;
}

pub const CommitCheck = struct { status: CommitStatus, entry: u32 };

/// Every refusal kelpie_commit makes, shared with the loop's commit so the by-hand path and the
/// native loop refuse the same payloads (design 2.3). loop.mutex held. `entry` names the first
/// bad entry (0 for a whole-commit problem).
pub fn validateCommit(e: *Engine, c: KelpieCommit) CommitCheck {
    if (!e.sched.planned()) return .{ .status = .err_entries, .entry = 0 };
    const live = &e.sched.live().plan;
    const n = c.n_entries;
    if (n != live.n_reqs) return .{ .status = .err_entries, .entry = 0 };
    if (n > 0 and c.tokens == null) return .{ .status = .err_entries, .entry = 0 };
    const n_tokens: []const u32 = if (c.n_tokens) |ptr| ptr[0..n] else &.{};
    const next_extra: []const u32 = if (c.next_extra) |ptr| ptr[0..n] else &.{};
    if (n > 0 and c.stride == 0) return .{ .status = .err_count, .entry = 0 };
    for (live.entries[0..n], 0..) |entry, i| {
        const bad = CommitCheck{ .status = .err_count, .entry = @intCast(i) };
        const count: u32 = if (n_tokens.len == 0) 1 else n_tokens[i];
        const extra: u32 = if (next_extra.len == 0) 0 else next_extra[i];
        if (count < 1 or count > 1 + entry.n_extra or count > c.stride) return bad;
        if (extra > e.cfg.max_extra) return bad;
        // Grammar with extra rows stays refused (docs/design-core-option2.md 7.8): the matcher
        // would have to accept and roll back per extra row.
        if (e.grammars[entry.req_id] != null and (count > 1 or extra > 0)) return .{ .status = .err_grammar, .entry = @intCast(i) };
        // A kept token enters the history: never the extra-row placeholder, never out of vocab.
        for (c.tokens.?[i * c.stride ..][0..count]) |token| {
            if (token == scheduler.no_token) return .{ .status = .err_token, .entry = @intCast(i) };
            if (e.cfg.vocab_size != 0 and token >= e.cfg.vocab_size) return .{ .status = .err_token, .entry = @intCast(i) };
        }
    }
    return .{ .status = .ok, .entry = 0 };
}

/// Applies a validated commit and records its payload hash (the next digest folds it in).
fn commitValidated(e: *Engine, c: KelpieCommit) void {
    const n = c.n_entries;
    const tokens: []const u32 = if (c.tokens) |ptr| ptr[0 .. n * c.stride] else &.{};
    const n_tokens: []const u32 = if (c.n_tokens) |ptr| ptr[0..n] else &.{};
    const next_extra: []const u32 = if (c.next_extra) |ptr| ptr[0..n] else &.{};
    e.prev_payload_hash = payloadHash(c);
    commitUnlocked(e, .{ .tokens = tokens, .stride = @max(c.stride, 1), .n_tokens = n_tokens, .next_extra = next_extra });
    if (e.cfg.overlap != 0) e.inbox.reconcile(&e.reqs);
}

/// Stride-independent: per entry its count, next_extra and KEPT tokens only, so a hand loop
/// committing [R, 1] and the loop's [R, 1 + K] StepOut hash the same payload the same.
fn payloadHash(c: KelpieCommit) u64 {
    var h = std.hash.Wyhash.init(0);
    hashInts(&h, .{c.n_entries});
    for (0..c.n_entries) |i| {
        const count: u32 = if (c.n_tokens) |counts| counts[i] else 1;
        const extra: u32 = if (c.next_extra) |extras| extras[i] else 0;
        hashInts(&h, .{ count, extra });
        hashSlice(&h, c.tokens.?[i * c.stride ..][0..count]);
    }
    return h.final();
}

fn commitUnlocked(e: *Engine, c: scheduler.Commit) void {
    // Capture req_ids in plan order BEFORE commit: commit retires the live arena, so
    // e.sched.live() names the *next* plan once commit returns -- same reason
    // kelpie-engine/kelpie_engine/core.py's step() reads batch.req_ids from the `batch` plan() returned,
    // captured before commit().
    const live = &e.sched.live().plan;
    const n = live.n_reqs;
    for (live.entries[0..n], e.commit_req_ids[0..n]) |entry, *dst| dst.* = entry.req_id;
    scheduler.commit(&e.sched, c);
    commitAcceptGrammar(e, e.commit_req_ids[0..n], c.tokens, c.stride);
}

/// Advances every committed entry's grammar matcher by its sampled token (K = 0 sugar: one
/// token per entry, `sampled[i]` for `req_ids[i]`), mirroring kelpie-engine/kelpie_engine/core.py step()'s
/// `for rid, token in zip(batch.req_ids, sampled): ... _accept_grammar_token`. A rejected token
/// (matcherAccept returns false) closes the request as grammar_dead_end via
/// scheduler.markGrammarDeadEnd -- the same "loud, not silent" failure the fillLogitMask
/// fail-closed path above sets up (an all-zero mask row makes ops.sample emit token 0 for a
/// dead-end row rather than a fallback sample; accept then confirms 0 was not actually a valid
/// continuation and closes the request, per request.State.grammar_dead_end's doc comment).
/// Unconditional per entry regardless of Kind, matching Python's own core.py exactly -- see
/// fillLogitMask's TODO on why that includes prefill rows whose token commitEntry discards.
fn commitAcceptGrammar(e: *Engine, req_ids: []const u32, tokens: []const u32, stride: u32) void {
    if (e.cfg.vocab_words == 0) return; // grammar support disabled at create: no matcher can be attached
    assert(tokens.len >= req_ids.len * stride);
    for (req_ids, 0..) |req_id, i| {
        const token = tokens[i * stride]; // a grammared entry keeps exactly one (kelpie_commit)
        const matcher = e.grammars[req_id] orelse continue;
        if (xgrammar.matcherIsTerminated(matcher)) continue; // nothing left to accept
        if (!xgrammar.matcherAccept(matcher, @intCast(token))) {
            scheduler.markGrammarDeadEnd(&e.sched, req_id);
        }
    }
}
fn engineOf(owner: *anyopaque) *Engine {
    return @ptrCast(@alignCast(owner));
}
fn boundaryOpaque(owner: *anyopaque, stopping: bool) bool {
    return boundaryUnlocked(engineOf(owner), stopping);
}
fn applyOpaque(owner: *anyopaque) void {
    const e = engineOf(owner);
    applyBatch(e) catch |err| std.debug.panic("step boundary refused at step {d}: {s} (a bad batch, or this rank diverged from the edge)", .{ e.sched.step + 1, @errorName(err) });
}
fn planOpaque(owner: *anyopaque, out: *KelpiePlan, slot: u32) u32 {
    return planUnlocked(engineOf(owner), out, slot);
}
fn agreeOpaque(owner: *anyopaque, plan: *const KelpiePlan) void {
    const e = engineOf(owner);
    agreeUnlocked(e, plan.digest) catch std.debug.panic("plan digest mismatch at step {d}: this rank's plan differs from another's", .{e.sched.step});
}
fn payloadOpaque(owner: *anyopaque, n: u32) void {
    const e = engineOf(owner);
    agreePayload(e, n) catch std.debug.panic("payload agreement failed at step {d}", .{e.sched.step});
}
fn installedOpaque(owner: *anyopaque, epoch: u64) void {
    engineOf(owner).inbox.swapInstalled(epoch);
}
fn refreshOpaque(owner: *anyopaque, out: *KelpiePlan, slot: u32) void {
    const e = engineOf(owner);
    // commit replaces every reservation sentinel in the canonical Sequence. Refresh the promoted
    // plan's host mirror too; the native launch still performs the stream-ordered D2D scatter,
    // while this keeps the wire plan truthful for diagnostics and non-native split callbacks.
    const live = &e.sched.live().plan;
    for (live.entries[0..live.n_reqs], 0..) |entry, i| {
        if (entry.kind != .decode or entry.n_work != 1) continue;
        const row = live.query_start_loc[i];
        const pos = live.positions[row];
        live.input_ids[row] = e.reqs.requests[entry.req_id].seq.tokens[pos];
    }
    _ = fillPlan(e, out, live, slot);
}
/// The loop's commit: the StepOut the launch filled (rank 0's, after payload agreement),
/// validated exactly as kelpie_commit validates -- a bad payload is a step-fn bug and fails the
/// step, same as a launch that returns non-zero. loop.mutex held.
fn commitOpaque(owner: *anyopaque, n: u32) void {
    const e = engineOf(owner);
    assert(n == e.sched.live().plan.n_reqs);
    const c = stepOutCommit(e, n);
    const check = validateCommit(e, c);
    if (check.status != .ok) std.debug.panic("the step fn returned a payload kelpie_commit refuses: {s} at step {d}, entry {d}", .{ @tagName(check.status), e.sched.step, check.entry });
    commitValidated(e, c);
    e.last_step_ns = events.now(&e.sched.clock);
    // commitUnlocked snapshotted this commit's req_ids (plan order) into commit_req_ids before
    // scheduler.commit's overlap swap could rename plan_buf; that snapshot is exactly the set
    // commitEntry(i) advanced, so it is what the record carries.
    enqueueCommit(e, e.commit_req_ids[0..n]);
}

/// Appends this commit's record (e.sched.event as published by the commit just done, plus the
/// req_ids it advanced) to the ring and writes the drain thread its one byte. A full ring drops
/// the record into the carry instead (see Engine.ring_* doc). Caller holds loop.mutex.
fn enqueueCommit(e: *Engine, req_ids: []const u32) void {
    assert(req_ids.len <= e.cfg.max_batch_reqs);
    assert(e.ring_len <= commit_ring_capacity);
    if (e.ring_len == commit_ring_capacity) {
        for (req_ids) |rid| setCarryBit(e, rid);
        e.carry_n_dropped += 1;
        return;
    }
    const slot = (e.ring_head + e.ring_len) % commit_ring_capacity;
    const row = e.ring_advanced[slot * e.cfg.max_requests ..][0..e.cfg.max_requests];
    var n: u32 = 0;
    for (req_ids) |rid| {
        assert(rid < e.cfg.max_requests);
        row[n] = rid;
        n += 1;
    }
    n = foldCarry(e, row, n);
    e.ring_events[slot] = e.sched.event;
    e.ring_n_advanced[slot] = n;
    e.ring_n_dropped[slot] = e.carry_n_dropped;
    e.carry_n_dropped = 0;
    e.ring_len += 1;
    assert(e.ring_len <= commit_ring_capacity);
    // One byte per record enqueued. WouldBlock is not expected (the pipe outholds the ring) but
    // is harmless: the record stays in the ring and the next wake pops it. Anything else would
    // mean the pipe is broken, which is a bug in this file (Python never closes read_fd).
    _ = std.posix.write(e.pipe_write_fd, &[_]u8{1}) catch |err| switch (err) {
        error.WouldBlock => {},
        else => unreachable,
    };
}

fn setCarryBit(e: *Engine, rid: u32) void {
    assert(rid < e.cfg.max_requests);
    e.carry_advanced[rid / 32] |= @as(u32, 1) << @intCast(rid % 32);
}

/// Appends every carried req_id not already in row[0..n_own] (ascending id order) and clears the
/// carry. Returns the new count; bounded by max_requests because req_ids are unique.
fn foldCarry(e: *Engine, row: []u32, n_own: u32) u32 {
    var n = n_own;
    for (e.carry_advanced, 0..) |*word, w| {
        var bits = word.*;
        while (bits != 0) {
            const bit: u5 = @intCast(@ctz(bits));
            bits &= bits - 1;
            const rid: u32 = @intCast(w * 32 + bit);
            if (!containsReq(row[0..n_own], rid)) {
                row[n] = rid;
                n += 1;
            }
        }
        word.* = 0;
    }
    assert(n <= e.cfg.max_requests);
    assert(n >= n_own);
    return n;
}

fn containsReq(ids: []const u32, rid: u32) bool {
    for (ids) |id| {
        if (id == rid) return true;
    }
    return false;
}

fn forwardBeginOpaque(owner: *anyopaque) void {
    const e: *Engine = @ptrCast(@alignCast(owner));
    scheduler.timingStart(&e.sched, .forward);
}
fn forwardEndOpaque(owner: *anyopaque) void {
    const e: *Engine = @ptrCast(@alignCast(owner));
    scheduler.timingStop(&e.sched, .forward);
}
fn drainOpaque(owner: *anyopaque, entering: bool) bool {
    const e: *Engine = @ptrCast(@alignCast(owner));
    if (entering and e.sched.state == .serving) scheduler.enterDraining(&e.sched);
    if (!scheduler.isDrained(&e.sched)) return false;
    if (!entering) scheduler.leaveDraining(&e.sched);
    return true;
}

pub const Loop = step_loop.State(KelpiePlan, KelpieStepOut);
pub const KelpieLaunchFn = Loop.LaunchFn;
pub const KelpieLaunchAsyncFn = Loop.LaunchAsyncFn;
pub const KelpieLaunchWaitFn = Loop.LaunchWaitFn;
export fn kelpie_register_launch(e: *Engine, launch: ?KelpieLaunchFn, captured: ?*anyopaque) i32 {
    return if (e.loop.register(launch orelse return -1, captured orelse return -1)) 0 else -1;
}
export fn kelpie_register_launch_split(e: *Engine, launch: ?KelpieLaunchFn, launch_async: ?KelpieLaunchAsyncFn, launch_wait: ?KelpieLaunchWaitFn, captured: ?*anyopaque) i32 {
    return if (e.loop.registerSplit(launch orelse return -1, launch_async orelse return -1, launch_wait orelse return -1, captured orelse return -1)) 0 else -1;
}
/// Queues a launch swap: an op that installs (launch, captured) at a step boundary, after the
/// running set drains when `drain`. -2 while an earlier swap is not yet installed; -6 follower.
export fn kelpie_swap_launch(e: *Engine, launch: ?KelpieLaunchFn, captured: ?*anyopaque, drain: bool) i32 {
    if (!isEdge(e)) return @intCast(submit_not_edge);
    const l = launch orelse return -1;
    e.inbox.swapLaunch(@ptrCast(l), captured orelse return -1, drain) catch return -2;
    e.loop.wake();
    return 0;
}

/// Registers the rank sync (docs/design-multigpu.md 2.2): `exchange` carries every boundary's
/// batch and every commit's payload from the edge to every rank, `agree` (may be NULL) checks
/// each plan's digest. `edge` 1 = this rank is the edge (owns submit/cancel/set; its loop sends
/// an empty batch every second when idle so followers never time out), 0 = a follower (its
/// loop blocks in the exchange). Before start_loop, once. Not registered = world 1.
export fn kelpie_register_sync(e: *Engine, exchange: ?KelpieExchangeFn, agree: ?KelpieAgreeFn, ctx: ?*anyopaque, edge: u32) i32 {
    const x = exchange orelse return -1;
    if (edge > 1) return -1;
    e.loop.mutex.lock();
    defer e.loop.mutex.unlock();
    if (e.loop.thread != null or e.sync != null) return -1;
    const payload_words = 1 + @as(usize, e.cfg.max_batch_reqs) * (2 + e.step_out.stride);
    const batch_in = allocator.alloc(u32, e.batch.len) catch return -1;
    const mine = allocator.alloc(u32, payload_words) catch {
        allocator.free(batch_in);
        return -1;
    };
    const agreed = allocator.alloc(u32, payload_words) catch {
        allocator.free(mine);
        allocator.free(batch_in);
        return -1;
    };
    e.batch_in, e.payload_mine, e.payload_agreed = .{ batch_in, mine, agreed };
    e.sync = .{ .exchange = x, .agree = agree, .ctx = ctx, .edge = edge == 1 };
    e.loop.wait_mode = if (edge == 1) .heartbeat else .none;
    return 0;
}
export fn kelpie_start_loop(e: *Engine) i32 {
    e.loop.start() catch return -1;
    return 0;
}
export fn kelpie_wake(e: *Engine) void {
    e.loop.wake();
}
export fn kelpie_stop_loop(e: *Engine) void {
    e.loop.stopAndJoin();
}
/// True while the step-loop thread is running (start_loop called, stop_loop has not yet joined
/// it). Observes the thread itself, not a Python-side bool: see docs/design-rules.md, "no
/// dishonest fallbacks" -- a wedged native thread must read false here, not "probably fine".
export fn kelpie_loop_alive(e: *Engine) bool {
    e.loop.mutex.lock();
    defer e.loop.mutex.unlock();
    return loopAliveLocked(e);
}
/// ns (sched.clock's domain, see kelpie_now_ns) at the last commit the step thread published;
/// 0 before the first step. An idle wake still commits (0 tokens) and still counts as a step,
/// matching kelpie_http.Stepper.since_last_step_s's Python-loop semantics.
export fn kelpie_last_step_ns(e: *Engine) u64 {
    e.loop.mutex.lock();
    defer e.loop.mutex.unlock();
    return e.last_step_ns;
}
/// The current instant in the same clock domain as kelpie_last_step_ns and every StepEvent/
/// RequestEvent timestamp (sched.clock, ns since Engine creation). Exposed so a caller can
/// compute "time since last step" without mixing Zig's clock with its own.
export fn kelpie_now_ns(e: *Engine) u64 {
    return events.now(&e.sched.clock);
}
/// Swaps applied so far. Strictly increasing; a caller that read `e` before kelpie_swap_launch
/// may release the retired launch context once this returns > e (the swap-applied ack).
export fn kelpie_launch_epoch(e: *Engine) u64 {
    return e.loop.appliedEpoch();
}

/// Copies the generated tokens not yet polled. Pure (section 8 B1, 2.1 item 3): it never
/// releases a slot or detaches a grammar. The first poll on the edge that sees a request
/// finished queues its release op, so the slot frees at the next boundary -- and the id is
/// reservable by a submit right away (the release applies first). A request whose submit has
/// not reached a boundary yet reports waiting with no tokens; one with a cancel queued reports
/// cancelled.
export fn kelpie_poll(e: *Engine, req_id: u32, out: [*]u32, cap: u32, result: *KelpiePoll) u32 {
    e.loop.mutex.lock();
    defer e.loop.mutex.unlock();
    if (req_id >= e.cfg.max_requests) {
        result.* = .{ .n_new = 0, .finished = 1, .state = @intFromEnum(request.State.cancelled) };
        return 0;
    }
    const edge = isEdge(e);
    if (edge) switch (e.inbox.pollView(req_id)) {
        .not_applied => {
            result.* = .{ .n_new = 0, .finished = 0, .state = @intFromEnum(request.State.waiting) };
            return 0;
        },
        .cancelled => {
            result.* = .{ .n_new = 0, .finished = 1, .state = @intFromEnum(request.State.cancelled) };
            return 0;
        },
        .core => {},
    };
    const r = scheduler.poll(&e.sched, req_id, out[0..cap]);
    assert(r.n_new <= cap);
    if (r.finished and edge) e.inbox.pollFinished(req_id);
    result.* = .{ .n_new = r.n_new, .finished = @intFromBool(r.finished), .state = @intFromEnum(r.state) };
    return r.n_new;
}

/// Queues a live-config change; it applies at the step boundary before the plan for
/// `out.apply_step` -- exactly that step (the inbox numbers its boundaries, section 8 S3).
/// Returns 0 ok, -1 bad kind/value, -2 queue full (64 unapplied changes), -6 follower.
export fn kelpie_set(e: *Engine, knob_ptr: ?*const KelpieKnob, out: ?*KelpieSetResult) i32 {
    if (!isEdge(e)) return @intCast(submit_not_edge);
    const knob = knobFromC((knob_ptr orelse return -1).*) orelse return -1;
    scheduler.validateKnob(&e.sched, knob) catch return -1;
    const queued = e.inbox.set(knob) catch return -2;
    if (out) |o| o.* = .{ .apply_step = queued.apply_step, .config_hash = queued.config_hash };
    e.loop.wake();
    return 0;
}

/// Sugar for kelpie_set(order): 0 = running_first, 1 = waiting_first. Returns 0 ok, -1 bad value.
export fn kelpie_set_order(e: *Engine, order: u32) i32 {
    if (order > 1) return -1;
    const knob = KelpieKnob{ .kind = @intFromEnum(KnobKind.order), .u32_value = order, .f32_value = 0 };
    return kelpie_set(e, &knob, null);
}

/// Copies the config out: static fields from create, knob fields + hash as the scheduler last drained
/// them (a queued kelpie_set is not visible until its step). Group arrays point at Engine-owned memory.
/// scheduler.worstSlabs: the most slabs a request of this size holds at once alone. Submit
/// returns KELPIE_SUBMIT_EXCEEDS_KV_POOL when this is above KelpieConfig.num_slabs; callers
/// read both to say by how much.
export fn kelpie_worst_slabs(e: *Engine, n_prompt: u32, max_new: u32) u32 {
    e.loop.mutex.lock();
    defer e.loop.mutex.unlock();
    if (n_prompt == 0) return 0;
    return scheduler.worstSlabs(&e.sched, n_prompt, max_new);
}

/// 1 when the last plan stalled (scheduler.Stall: pending work, nothing schedulable, nothing in
/// flight -- every later plan is the same until a cancel or knob), with its fields written to
/// the out pointers; 0 otherwise, outs untouched.
export fn kelpie_stall(e: *Engine, req_id: *u32, n_work: *u32, need_slabs: *u32, free_slabs: *u32) i32 {
    e.loop.mutex.lock();
    defer e.loop.mutex.unlock();
    const stall = e.sched.stall orelse return 0;
    req_id.* = stall.req_id;
    n_work.* = stall.n_work;
    need_slabs.* = stall.need_slabs;
    free_slabs.* = stall.free_slabs;
    return 1;
}

export fn kelpie_get_config(e: *Engine, out: *KelpieConfig) void {
    const live = e.sched.cfg;
    out.* = e.cfg;
    out.max_batch_tokens = live.max_batch_tokens;
    out.max_batch_reqs = live.max_batch_reqs;
    out.reserve_ratio = live.reserve_ratio;
    out.order = @intFromEnum(live.order);
    out.prefix_cache = @intFromBool(live.prefix_cache);
    out.overlap = @intFromBool(live.overlap);
    out.config_hash = e.sched.config_hash;
}

fn knobFromC(k: KelpieKnob) ?scheduler.Knob {
    if (k.kind > @intFromEnum(KnobKind.prefix_cache)) return null;
    return switch (@as(KnobKind, @enumFromInt(k.kind))) {
        .order => if (k.u32_value > 1) null else .{ .order = orderFromU32(k.u32_value) },
        .reserve_ratio => .{ .reserve_ratio = k.f32_value },
        .max_batch_tokens => .{ .max_batch_tokens = k.u32_value },
        .max_batch_reqs => .{ .max_batch_reqs = k.u32_value },
        .prefix_cache => if (k.u32_value > 1) null else .{ .prefix_cache = k.u32_value != 0 },
    };
}

/// The last committed step's event. Valid after kelpie_commit until the next kelpie_commit.
export fn kelpie_step_event(e: *Engine, out: *events.StepEvent) void {
    e.loop.mutex.lock();
    defer e.loop.mutex.unlock();
    out.* = e.sched.event;
}

/// Pops the oldest un-popped commit record (Engine.ring_*): that commit's StepEvent into
/// `out_event`, the req_ids it advanced (plan order; carried ids appended) into
/// `out_reqs[0..cap]`, and into `out_n_dropped` how many commits were dropped (ring full)
/// between the previous record and this one -- 0 in the steady state. Returns the number of
/// advanced req_ids, -1 when the ring is empty (nothing popped, outputs untouched), or -2 when
/// `cap` cannot hold the record (size `out_reqs` to max_requests; nothing popped). Records only
/// come from the Zig step thread's commits (kelpie_commit driven by hand does not enqueue).
export fn kelpie_next_commit(e: *Engine, out_event: *events.StepEvent, out_reqs: [*]u32, cap: u32, out_n_dropped: *u32) i32 {
    e.loop.mutex.lock();
    defer e.loop.mutex.unlock();
    if (e.ring_len == 0) return -1;
    const slot = e.ring_head;
    const n = e.ring_n_advanced[slot];
    if (n > cap) return -2;
    const row = e.ring_advanced[slot * e.cfg.max_requests ..][0..n];
    @memcpy(out_reqs[0..n], row);
    out_event.* = e.ring_events[slot];
    out_n_dropped.* = e.ring_n_dropped[slot];
    e.ring_head = (slot + 1) % commit_ring_capacity;
    e.ring_len -= 1;
    assert(e.ring_len < commit_ring_capacity);
    return @intCast(n);
}

/// The read end of the step-done pipe (see Engine.pipe_read_fd): the step thread writes one byte
/// per commit record enqueued. A Python drain thread blocks in os.read(fd, 1) on this, then pops
/// kelpie_next_commit until it returns -1. The fd is owned by the Engine (closed in
/// kelpie_destroy) -- the caller must not close it.
export fn kelpie_step_pipe_fd(e: *Engine) i32 {
    return e.pipe_read_fd;
}

/// The request's event; complete at the poll that observes finish, or right after kelpie_cancel.
/// The slot is reused by a later submit, so read it then. Returns -1 on a bad id.
export fn kelpie_request_event(e: *Engine, req_id: u32, out: *events.RequestEvent) i32 {
    e.loop.mutex.lock();
    defer e.loop.mutex.unlock();
    if (req_id >= e.cfg.max_requests) return -1;
    out.* = e.reqs.requests[req_id].event;
    return 0;
}

/// which: 0 plan, 1 forward, 2 commit. plan/commit bracket themselves in the core, and the Zig
/// step thread brackets the forward itself (step_loop forward_begin_fn/forward_end_fn), so a
/// caller driving the loop must NOT bracket it again (unpaired/double starts assert). Only a
/// caller stepping by hand through kelpie_plan / kelpie_commit brackets the forward here.
/// Returns -1 on a bad value.
export fn kelpie_timing_start(e: *Engine, which: u32) i32 {
    scheduler.timingStart(&e.sched, timingFromU32(which) orelse return -1);
    return 0;
}

export fn kelpie_timing_stop(e: *Engine, which: u32) i32 {
    scheduler.timingStop(&e.sched, timingFromU32(which) orelse return -1);
    return 0;
}

/// Layout tripwire (docs/derisk-plan-abi-2026-09-09.md): sizeof for one of the KELPIE_STRUCT_*
/// ids in kelpie.h. 0 for an unrecognized struct_id -- chosen over SIZE_MAX because every
/// struct this table carries is non-zero-sized in practice (each has at least one u32 field),
/// so 0 can never collide with a real answer, and a C caller's likely first move ("is this
/// zero?") produces the right verdict without needing a SIZE_MAX/(size_t)-1 comparison.
export fn kelpie_sizeof(struct_id: u32) usize {
    return abi_ids.sizeOf(struct_id);
}

/// Layout tripwire counterpart: offsetof for (KELPIE_STRUCT_* id, KELPIE_FIELD_<STRUCT>_* id).
/// 0 for an unrecognized struct_id OR field_id -- same reasoning as kelpie_sizeof; note 0 is
/// also a legal *answer* here (a struct's first field is always at offset 0), so a caller that
/// must distinguish "field 0" from "unknown" should first confirm struct_id/field_id are in
/// range (kelpie_sizeof(struct_id) != 0 and field_id < the struct's known field count).
export fn kelpie_offsetof(struct_id: u32, field_id: u32) usize {
    return abi_ids.offsetOf(struct_id, field_id);
}

fn timingFromU32(which: u32) ?events.Timing {
    if (which > @intFromEnum(events.Timing.commit)) return null;
    return @enumFromInt(which);
}

fn schedulerConfig(cfg: KelpieConfig) scheduler.Config {
    return .{
        .max_batch_tokens = cfg.max_batch_tokens,
        .max_batch_reqs = cfg.max_batch_reqs,
        .reserve_ratio = cfg.reserve_ratio,
        .order = orderFromU32(cfg.order),
        .eos_token = cfg.eos_token,
        .prefix_cache = cfg.prefix_cache != 0,
        .overlap = cfg.overlap != 0,
    };
}

fn orderFromU32(order: u32) scheduler.Order {
    assert(order <= 1);
    return if (order == 0) .running_first else .waiting_first;
}

comptime {
    // The header hard-codes these ordinals; fail the build if request.State is reordered.
    assert(@intFromEnum(request.State.waiting) == 0);
    assert(@intFromEnum(request.State.running) == 1);
    assert(@intFromEnum(request.State.finished_eos) == 2);
    assert(@intFromEnum(request.State.finished_length) == 3);
    assert(@intFromEnum(request.State.cancelled) == 4);
    assert(@intFromEnum(request.State.grammar_dead_end) == 5);
    assert(@intFromEnum(scheduler.Order.running_first) == 0);
    assert(@intFromEnum(scheduler.Order.waiting_first) == 1);
    assert(@intFromEnum(scheduler.Kind.prefill) == 0);
    assert(@intFromEnum(scheduler.Kind.decode) == 1);
    assert(@intFromEnum(events.Timing.plan) == 0);
    assert(@intFromEnum(events.Timing.forward) == 1);
    assert(@intFromEnum(events.Timing.commit) == 2);
    assert(@intFromEnum(KnobKind.order) == 0);
    assert(@intFromEnum(KnobKind.reserve_ratio) == 1);
    assert(@intFromEnum(KnobKind.max_batch_tokens) == 2);
    assert(@intFromEnum(KnobKind.max_batch_reqs) == 3);
    assert(@intFromEnum(KnobKind.prefix_cache) == 4);
}

// ---- grammar tests (kelpie_attach_grammar / KelpiePlan.logit_mask / commitAcceptGrammar) -----

/// The native loop's commit by hand: fill the StepOut as a launch would (one token each), then
/// commitOpaque, which validates it exactly as kelpie_commit does.
fn loopCommit(e: *Engine, tokens: []const u32) void {
    for (tokens, 0..) |token, i| {
        e.out_tokens[i * e.step_out.stride] = token;
        e.out_n[i] = 1;
        e.out_extra[i] = 0;
    }
    commitOpaque(e, @intCast(tokens.len));
}

/// One token per entry (stride 1), no extra rows asked for; an empty slice closes an idle plan.
fn commitTokens(e: *Engine, tokens: []const u32) i32 {
    const c = KelpieCommit{ .n_entries = @intCast(tokens.len), .stride = 1, .tokens = if (tokens.len == 0) null else tokens.ptr, .n_tokens = null, .next_extra = null };
    return kelpie_commit(e, &c);
}

fn testConfig(vocab_words: u32) KelpieConfig {
    return .{
        .max_requests = 4,
        .max_seq_len = 32,
        .n_groups = 1,
        .group_kinds = &[_]u32{0},
        .group_block_sizes = &[_]u32{4},
        .group_windows = &[_]u32{0},
        .group_cacheable = &[_]u8{1},
        .num_blocks = 64,
        .max_batch_tokens = 16,
        .max_batch_reqs = 4,
        .reserve_ratio = 0,
        .order = 0,
        .eos_token = 9, // matches xgrammar_test_compiled_grammar_create's stop_token_ids = {9}
        .prefix_cache = 0,
        .config_hash = 0,
        .group_strides = null,
        .overlap = 0,
        .vocab_words = vocab_words,
        .vocab_size = 100,
    };
}

test "grammar: register, submit by key, end to end through fillPlan and commitAcceptGrammar" {
    const words: u32 = @intCast(xgrammar.testVocabWords());
    var cfg = testConfig(words);
    const e = kelpie_create(&cfg) orelse return error.CreateFailed;
    defer kelpie_destroy(e);

    const grammar = xgrammar.testCompiledGrammarCreate() orelse return error.GrammarCompileFailed;
    // kelpie_register_grammar copies the grammar; the caller's handle is independent afterwards
    // (mirrors compiled_grammar_wrap's doc comment).
    defer xgrammar.compiledGrammarDestroy(grammar);
    const source = "{\"type\": \"object\"}";
    try std.testing.expectEqual(@as(i32, 0), kelpie_register_grammar(e, 77, @ptrCast(grammar), source, source.len));
    try std.testing.expectEqual(@as(i32, 0), kelpie_register_grammar(e, 77, @ptrCast(grammar), source, source.len)); // again: no-op
    const prompt = [_]u32{1};
    const rid = kelpie_submit_mm_stop(e, &prompt, 1, 8, 0, 0, 0, undefined, 0, 77);
    try std.testing.expect(rid >= 0);

    var plan_out: KelpiePlan = undefined;
    const n = kelpie_plan(e, &plan_out); // the boundary applies grammar_prepare, then the submit
    try std.testing.expect(n > 0);
    try std.testing.expectEqual(@as(u32, 1), plan_out.n_reqs);
    try std.testing.expect(plan_out.logit_mask != null);
    try std.testing.expect(e.grammars[@intCast(rid)] != null);

    // "{" (token 0) must be allowed as the grammar's first token; row 0 is this single entry's.
    const row = plan_out.logit_mask.?[0..words];
    try std.testing.expect((row[0] & 1) != 0);

    // Commit "{" (accepted) -- the request stays running, the matcher advances.
    const open_brace: u32 = @intCast(xgrammar.test_token_open_brace);
    try std.testing.expectEqual(@as(i32, 0), commitTokens(e, &.{open_brace}));
    try std.testing.expect(e.reqs.requests[@intCast(rid)].state == .running);

    // Then "true" (token 6), not a valid continuation right after "{": grammar_dead_end.
    try std.testing.expect(kelpie_plan(e, &plan_out) > 0);
    const true_token: u32 = @intCast(xgrammar.test_token_true);
    try std.testing.expectEqual(@as(i32, 0), commitTokens(e, &.{true_token}));
    try std.testing.expect(e.reqs.requests[@intCast(rid)].state == .grammar_dead_end);

    // poll reports the terminal state; it is pure, so the matcher lives until the release op
    // applies at the next boundary, which also frees the slot.
    var poll_out: [8]u32 = undefined;
    var poll_result: KelpiePoll = undefined;
    _ = kelpie_poll(e, @intCast(rid), &poll_out, poll_out.len, &poll_result);
    try std.testing.expectEqual(@as(u8, 1), poll_result.finished);
    try std.testing.expectEqual(@intFromEnum(request.State.grammar_dead_end), poll_result.state);
    try std.testing.expect(e.grammars[@intCast(rid)] != null);
    try std.testing.expectEqual(@as(u32, 0), kelpie_plan(e, &plan_out));
    try std.testing.expectEqual(@as(i32, 0), commitTokens(e, &.{}));
    try std.testing.expect(e.grammars[@intCast(rid)] == null);
    try std.testing.expect(!e.reqs.requests[@intCast(rid)].owned);
}

test "grammar: refused without support, for an unknown key, and with extra rows" {
    const grammar = xgrammar.testCompiledGrammarCreate() orelse return error.GrammarCompileFailed;
    defer xgrammar.compiledGrammarDestroy(grammar);
    const prompt = [_]u32{1};

    var cfg = testConfig(0); // grammar support disabled
    const e = kelpie_create(&cfg) orelse return error.CreateFailed;
    defer kelpie_destroy(e);
    try std.testing.expectEqual(@as(i32, -1), kelpie_register_grammar(e, 5, @ptrCast(grammar), null, 0));
    try std.testing.expectEqual(@as(i64, -3), kelpie_submit_mm_stop(e, &prompt, 1, 8, 0, 0, 0, undefined, 0, 5));

    var cfg2 = testConfig(@intCast(xgrammar.testVocabWords()));
    const e2 = kelpie_create(&cfg2) orelse return error.CreateFailed;
    defer kelpie_destroy(e2);
    try std.testing.expectEqual(@as(i64, -3), kelpie_submit_mm_stop(e2, &prompt, 1, 8, 0, 0, 0, undefined, 0, 5)); // never registered
    try std.testing.expectEqual(@as(i32, -1), kelpie_register_grammar(e2, 0, @ptrCast(grammar), null, 0)); // key 0 = none

    var cfg3 = testConfig(@intCast(xgrammar.testVocabWords()));
    cfg3.max_extra = 2;
    const e3 = kelpie_create(&cfg3) orelse return error.CreateFailed;
    defer kelpie_destroy(e3);
    try std.testing.expectEqual(@as(i32, 0), kelpie_register_grammar(e3, 5, @ptrCast(grammar), null, 0));
    try std.testing.expectEqual(@as(i64, -3), kelpie_submit_mm_stop(e3, &prompt, 1, 8, 0, 0, 0, undefined, 0, 5));
}

// ---- commit ring tests (kelpie_next_commit / enqueueCommit) --------------------------------

fn popRecord(e: *Engine, out_reqs: []u32, out_dropped: *u32) !struct { n: i32, event: events.StepEvent } {
    var event: events.StepEvent = undefined;
    const n = kelpie_next_commit(e, &event, out_reqs.ptr, @intCast(out_reqs.len), out_dropped);
    return .{ .n = n, .event = event };
}

test "commit ring: one record per commit; a full ring carries advanced ids and counts drops" {
    var cfg = testConfig(0);
    const e = kelpie_create(&cfg) orelse return error.CreateFailed;
    defer kelpie_destroy(e);
    var reqs: [4]u32 = undefined;
    var dropped: u32 = 0;
    var plan_out: KelpiePlan = undefined;
    const token = [_]u32{5};

    // Empty ring: nothing to pop.
    try std.testing.expectEqual(@as(i32, -1), (try popRecord(e, &reqs, &dropped)).n);

    // One real commit -> exactly one record naming the request it advanced.
    const prompt = [_]u32{1};
    const rid: u32 = @intCast(kelpie_submit(e, &prompt, 1, 8, 0));
    try std.testing.expect(kelpie_plan(e, &plan_out) > 0);
    loopCommit(e, &token);
    const first = try popRecord(e, &reqs, &dropped);
    try std.testing.expectEqual(@as(i32, 1), first.n);
    try std.testing.expectEqual(rid, reqs[0]);
    try std.testing.expectEqual(@as(u32, 0), dropped);
    try std.testing.expectEqual(@as(u64, 1), first.event.step);
    try std.testing.expect(!first.event.is_idle);
    try std.testing.expectEqual(@as(i32, -1), (try popRecord(e, &reqs, &dropped)).n);

    // Fill the ring with idle commits (the request is cancelled, so plan() is idle).
    kelpie_cancel(e, rid);
    for (0..commit_ring_capacity) |_| {
        try std.testing.expectEqual(@as(u32, 0), kelpie_plan(e, &plan_out));
        loopCommit(e, &.{});
    }
    try std.testing.expectEqual(commit_ring_capacity, e.ring_len);

    // Full: a real commit is dropped, its req_id carried, the drop counted.
    const rid2: u32 = @intCast(kelpie_submit(e, &prompt, 1, 8, 0)); // may reuse rid's slot
    try std.testing.expect(kelpie_plan(e, &plan_out) > 0);
    loopCommit(e, &token);
    try std.testing.expectEqual(commit_ring_capacity, e.ring_len);
    try std.testing.expectEqual(@as(u32, 1), e.carry_n_dropped);
    try std.testing.expect(e.carry_advanced[rid2 / 32] != 0);

    // Pop one (idle, no drops before it), then the next real commit folds the carry in once.
    const idle = try popRecord(e, &reqs, &dropped);
    try std.testing.expectEqual(@as(i32, 0), idle.n);
    try std.testing.expect(idle.event.is_idle);
    try std.testing.expectEqual(@as(u32, 0), dropped);
    try std.testing.expect(kelpie_plan(e, &plan_out) > 0);
    loopCommit(e, &token);
    try std.testing.expectEqual(@as(u32, 0), e.carry_n_dropped);
    try std.testing.expectEqual(@as(u32, 0), e.carry_advanced[rid2 / 32]);

    // Drain: capacity - 1 idle records, then the folded one (rid2 once, 1 drop), then empty.
    for (0..commit_ring_capacity - 1) |_| {
        try std.testing.expectEqual(@as(i32, 0), (try popRecord(e, &reqs, &dropped)).n);
        try std.testing.expectEqual(@as(u32, 0), dropped);
    }
    // -2: the caller's buffer cannot hold the record; nothing is popped.
    try std.testing.expectEqual(@as(i32, -2), (try popRecord(e, reqs[0..0], &dropped)).n);
    const folded = try popRecord(e, &reqs, &dropped);
    try std.testing.expectEqual(@as(i32, 1), folded.n);
    try std.testing.expectEqual(rid2, reqs[0]);
    try std.testing.expectEqual(@as(u32, 1), dropped);
    try std.testing.expect(!folded.event.is_idle);
    try std.testing.expectEqual(@as(i32, -1), (try popRecord(e, &reqs, &dropped)).n);
    try std.testing.expectEqual(@as(u32, 0), e.ring_len);
}

test "kelpie_plan emits a bucket-padded plan whose pad rows and pad entries are inert" {
    // max_batch_reqs = 3 is deliberately not a power of two: the ladder pads 3 entries up to 4,
    // past the configured maximum. That write is only in bounds because the plan buffers are
    // allocated at bucket(max_batch_*) (scheduler.allocPlan), which is what this pins down.
    var cfg = testConfig(0);
    cfg.max_batch_reqs = 3;
    cfg.max_batch_tokens = 12;
    const e = kelpie_create(&cfg) orelse return error.CreateFailed;
    defer kelpie_destroy(e);

    // Two prompts of 3 tokens: 6 real rows over 2 entries -> padded to 8 rows and 2 entries.
    const prompt = [_]u32{ 1, 2, 3 };
    try std.testing.expect(kelpie_submit(e, &prompt, prompt.len, 4, 0) >= 0);
    try std.testing.expect(kelpie_submit(e, &prompt, prompt.len, 4, 0) >= 0);

    var plan: KelpiePlan = undefined;
    const n = kelpie_plan(e, &plan);
    try std.testing.expectEqual(@as(u32, 6), n);
    try std.testing.expectEqual(@as(u32, 6), plan.n_tokens);
    try std.testing.expectEqual(@as(u32, 2), plan.n_reqs);
    // The padded counts are the buckets of the real ones, from the one ladder.
    try std.testing.expectEqual(buckets.bucket(6), plan.n_tokens_padded);
    try std.testing.expectEqual(buckets.bucket(2), plan.n_reqs_padded);
    try std.testing.expectEqual(@as(u32, 8), plan.n_tokens_padded);
    try std.testing.expectEqual(@as(u32, 2), plan.n_reqs_padded);

    // Pad rows: id and position 0, slot = the scratch slot (never negative), row_request -1.
    const scratch_slot = cfg.group_block_sizes[0] - 1;
    for (plan.n_tokens..plan.n_tokens_padded) |i| {
        try std.testing.expectEqual(@as(u32, 0), plan.input_ids[i]);
        try std.testing.expectEqual(@as(u32, 0), plan.positions[i]);
        try std.testing.expectEqual(scratch_slot, plan.slot_mapping[0][i]);
        try std.testing.expectEqual(@as(i32, -1), plan.row_request[i]);
    }
    // Real rows: row_request names the owning entry, and it agrees with query_start_loc.
    for (0..plan.n_reqs) |r| {
        const q0 = plan.query_start_loc[r];
        const q1 = plan.query_start_loc[r + 1];
        try std.testing.expect(q1 > q0);
        for (q0..q1) |row| try std.testing.expectEqual(@as(i32, @intCast(r)), plan.row_request[row]);
    }
    // The tail of query_start_loc repeats n_tokens, so every pad entry's query is empty.
    for (plan.n_reqs..plan.n_reqs_padded) |r| {
        try std.testing.expectEqual(plan.n_tokens, plan.query_start_loc[r + 1]);
        try std.testing.expectEqual(plan.query_start_loc[r], plan.query_start_loc[r + 1]);
        try std.testing.expectEqual(@as(u32, 1), plan.seq_lens[r]);
        try std.testing.expectEqual(@as(u32, 0), plan.req_ids[r]);
        try std.testing.expectEqual(@as(f32, 1), plan.temperatures[r]);
        try std.testing.expectEqual(@as(u32, 1), plan.top_ks[r]);
        try std.testing.expectEqual(@as(u64, 0), plan.mm_hashes[r]);
        try std.testing.expectEqual(@intFromEnum(scheduler.Kind.prefill), plan.kinds[r]);
        try std.testing.expectEqual(@as(u32, 0), plan.n_extra[r]);
        try std.testing.expectEqual(@as(u32, 0), plan.seq_start[r]);
        try std.testing.expectEqual(@as(u8, 0), plan.emits[r]);
        // The whole block-table row is the null block.
        const width = plan.max_blocks_per_req[0];
        for (0..width) |b| try std.testing.expectEqual(kv_pool.null_block, plan.block_tables[0][r * width + b]);
    }
}

test "the T=0 rule reaches the plan: top_ks per real entry, pads greedy, negative refused" {
    var cfg = testConfig(0);
    cfg.max_batch_reqs = 3; // three real entries pad to four
    const e = kelpie_create(&cfg) orelse return error.CreateFailed;
    defer kelpie_destroy(e);
    const prompt = [_]u32{ 1, 2 };
    try std.testing.expectEqual(@as(i64, -3), kelpie_submit(e, &prompt, prompt.len, 4, -0.5));
    try std.testing.expectEqual(@as(i64, -3), kelpie_submit(e, &prompt, prompt.len, 4, std.math.nan(f32)));
    const temps = [_]f32{ 0, 1e-7, 0.7 };
    for (temps) |t| try std.testing.expect(kelpie_submit(e, &prompt, prompt.len, 4, t) >= 0);
    var plan: KelpiePlan = undefined;
    try std.testing.expect(kelpie_plan(e, &plan) > 0);
    try std.testing.expectEqual(@as(u32, 3), plan.n_reqs);
    try std.testing.expectEqual(@as(u32, 4), plan.n_reqs_padded);
    // Plan order is not submit order in general; key each entry by its request's own params.
    for (0..plan.n_reqs) |r| {
        const params = e.reqs.requests[plan.req_ids[r]].params;
        try std.testing.expectEqual(params.temperature, plan.temperatures[r]);
        try std.testing.expectEqual(params.top_k, plan.top_ks[r]);
    }
    var greedy: u32 = 0;
    for (0..plan.n_reqs) |r| {
        if (plan.top_ks[r] == 1) {
            try std.testing.expectEqual(@as(f32, 1), plan.temperatures[r]);
            greedy += 1;
        } else {
            try std.testing.expectEqual(@as(u32, 0), plan.top_ks[r]);
            try std.testing.expectEqual(@as(f32, 0.7), plan.temperatures[r]);
        }
    }
    try std.testing.expectEqual(@as(u32, 2), greedy); // T = 0 and T = 1e-7
    try std.testing.expectEqual(@as(f32, 1), plan.temperatures[3]); // the pad entry
    try std.testing.expectEqual(@as(u32, 1), plan.top_ks[3]);
}

test "a caller top_k reaches the plan, the T=0 rule overrides it, above vocab_size is refused" {
    var cfg = testConfig(0); // vocab_size 100
    const e = kelpie_create(&cfg) orelse return error.CreateFailed;
    defer kelpie_destroy(e);
    const prompt = [_]u32{ 1, 2 };
    try std.testing.expectEqual(submit_bad_top_k, kelpie_submit_top_k(e, &prompt, prompt.len, 4, 0.7, 101, 0, 0, undefined, 0, 0));
    const warm = kelpie_submit_top_k(e, &prompt, prompt.len, 4, 0.7, 5, 0, 0, undefined, 0, 0);
    const cold = kelpie_submit_top_k(e, &prompt, prompt.len, 4, 0, 5, 0, 0, undefined, 0, 0);
    const edge = kelpie_submit_top_k(e, &prompt, prompt.len, 4, 0.7, 100, 0, 0, undefined, 0, 0); // == vocab_size
    try std.testing.expect(warm >= 0 and cold >= 0 and edge >= 0);
    var plan: KelpiePlan = undefined;
    try std.testing.expect(kelpie_plan(e, &plan) > 0);
    try std.testing.expectEqual(@as(u32, 3), plan.n_reqs);
    for (0..plan.n_reqs) |r| {
        const id: i64 = plan.req_ids[r];
        const want_k: u32 = if (id == warm) 5 else if (id == cold) 1 else 100;
        const want_t: f32 = if (id == cold) 1 else 0.7;
        try std.testing.expectEqual(want_k, plan.top_ks[r]);
        try std.testing.expectEqual(want_t, plan.temperatures[r]);
    }
}

test "a follower replaying the edge's batches applies the same caller top_k" {
    var cfg = testConfig(0);
    const e = kelpie_create(&cfg) orelse return error.CreateFailed;
    defer kelpie_destroy(e);
    var rec = Recording{};
    defer rec.deinit();
    try std.testing.expectEqual(@as(i32, 0), kelpie_register_sync(e, Recording.exchange, Recording.agree, &rec, 1));
    const prompt = [_]u32{ 1, 2, 3 };
    const id = kelpie_submit_top_k(e, &prompt, prompt.len, 2, 0.7, 5, 0, 0, undefined, 0, 0);
    try std.testing.expect(id >= 0);
    var plan: KelpiePlan = undefined;
    for (0..3) |_| {
        const n = kelpie_plan(e, &plan);
        if (n > 0) try std.testing.expectEqual(@as(u32, 5), plan.top_ks[0]);
        const tokens = [_]u32{7};
        try std.testing.expectEqual(@as(i32, 0), commitTokens(e, if (n == 0) &.{} else &tokens));
    }
    _ = boundaryUnlocked(e, true);
    const f = kelpie_create(&cfg) orelse return error.CreateFailed;
    defer kelpie_destroy(f);
    var replay = Replay{ .msgs = rec.msgs.items, .digests = rec.digests.items };
    try std.testing.expectEqual(@as(i32, 0), kelpie_register_sync(f, Replay.exchange, Replay.agree, &replay, 0));
    try std.testing.expectEqual(@as(u32, 3), replayByHand(f));
    try std.testing.expectEqual(@as(u32, 0), replay.mismatches);
    try std.testing.expectEqual(@as(u32, 5), f.reqs.requests[@intCast(id)].params.top_k);
}

test "the plan digest covers top_ks" {
    // Flip one top_k in place and re-digest the same plan: nothing else moved (the batch hash
    // already differs between two engines submitting T=0 and T=1, so that would prove nothing).
    var cfg = testConfig(0);
    const e = kelpie_create(&cfg) orelse return error.CreateFailed;
    defer kelpie_destroy(e);
    const prompt = [_]u32{ 1, 2 };
    try std.testing.expect(kelpie_submit(e, &prompt, prompt.len, 4, 0) >= 0);
    var plan: KelpiePlan = undefined;
    try std.testing.expect(kelpie_plan(e, &plan) > 0);
    try std.testing.expectEqual(plan.digest, planDigest(e, &plan));
    const top_ks = e.sched.live().plan.top_ks;
    try std.testing.expectEqual(@intFromPtr(plan.top_ks), @intFromPtr(top_ks.ptr));
    top_ks[0] = 0;
    try std.testing.expect(plan.digest != planDigest(e, &plan));
    top_ks[0] = 1;
    try std.testing.expectEqual(plan.digest, planDigest(e, &plan));
}

// ---- kelpie_synthetic_plan -------------------------------------------------------------------

const synth_prefill: u32 = @intFromEnum(scheduler.Kind.prefill);
const synth_decode: u32 = @intFromEnum(scheduler.Kind.decode);

fn synthOk(e: *Engine, kind: u32, n_reqs: u32, rows: u32, n_extra: u32, out: *KelpiePlan) !void {
    try std.testing.expectEqual(@intFromEnum(SyntheticStatus.ok), kelpie_synthetic_plan(e, kind, n_reqs, rows, n_extra, out));
}

/// Every row of `plan` (real and pad) writes the scratch slot; every entry is inert by value.
fn expectInert(cfg: KelpieConfig, plan: *const KelpiePlan) !void {
    for (0..plan.n_groups) |g| {
        const scratch_slot = if (cfg.group_kinds[g] == 1) kv_pool.null_block else cfg.group_block_sizes[g] - 1;
        for (0..plan.n_tokens_padded) |i| try std.testing.expectEqual(scratch_slot, plan.slot_mapping[g][i]);
        const width = plan.max_blocks_per_req[g];
        for (0..plan.n_reqs_padded * width) |b| try std.testing.expectEqual(kv_pool.null_block, plan.block_tables[g][b]);
    }
    for (0..plan.n_reqs_padded) |r| {
        try std.testing.expectEqual(@as(u32, 0), plan.req_ids[r]);
        try std.testing.expectEqual(@as(f32, 1), plan.temperatures[r]);
        try std.testing.expectEqual(@as(u32, 1), plan.top_ks[r]);
        try std.testing.expectEqual(@as(u64, 0), plan.mm_hashes[r]);
        try std.testing.expectEqual(@as(u32, 0), plan.seq_start[r]);
        try std.testing.expectEqual(@as(u8, 0), plan.emits[r]);
    }
    try std.testing.expectEqual(@as(u64, 0), plan.digest);
}

/// The real structure: entry r owns rows [r * per, (r + 1) * per), positions 0..per-1, history
/// rows input_id 0 and extra rows NO_TOKEN.
fn expectStructure(plan: *const KelpiePlan, kind: u32, rows: u32, n_extra: u32) !void {
    const per = rows + n_extra;
    try std.testing.expectEqual(plan.n_reqs * per, plan.n_tokens);
    for (0..plan.n_reqs) |r| {
        try std.testing.expectEqual(@as(u32, @intCast(r)) * per, plan.query_start_loc[r]);
        try std.testing.expectEqual(kind, plan.kinds[r]);
        try std.testing.expectEqual(rows, plan.n_work[r]);
        try std.testing.expectEqual(n_extra, plan.n_extra[r]);
        try std.testing.expectEqual(per, plan.seq_lens[r]);
        for (0..per) |j| {
            const row = r * per + j;
            try std.testing.expectEqual(@as(i32, @intCast(r)), plan.row_request[row]);
            try std.testing.expectEqual(@as(u32, @intCast(j)), plan.positions[row]);
            const want: u32 = if (j < rows) 0 else scheduler.no_token;
            try std.testing.expectEqual(want, plan.input_ids[row]);
        }
    }
    try std.testing.expectEqual(plan.n_tokens, plan.query_start_loc[plan.n_reqs]);
    for (plan.n_tokens..plan.n_tokens_padded) |i| try std.testing.expectEqual(@as(i32, -1), plan.row_request[i]);
    for (plan.n_reqs..plan.n_reqs_padded) |r| {
        try std.testing.expectEqual(plan.n_tokens, plan.query_start_loc[r + 1]);
        try std.testing.expectEqual(@as(u32, 1), plan.seq_lens[r]);
        try std.testing.expectEqual(synth_prefill, plan.kinds[r]);
    }
}

test "synthetic decode plan: 3 entries pad to 4 and carry a real 3-entry decode plan's shape" {
    var cfg = testConfig(2);
    cfg.max_batch_reqs = 3; // three pad to four
    const e = kelpie_create(&cfg) orelse return error.CreateFailed;
    defer kelpie_destroy(e);

    var synth: KelpiePlan = undefined;
    try synthOk(e, synth_decode, 3, 1, 0, &synth);
    try std.testing.expectEqual(@as(u32, 3), synth.n_reqs);
    try std.testing.expectEqual(@as(u32, 4), synth.n_reqs_padded);
    try std.testing.expectEqual(buckets.bucket(3), synth.n_tokens_padded);
    try expectInert(cfg, &synth);
    try expectStructure(&synth, synth_decode, 1, 0);
    for (0..synth.n_reqs_padded * cfg.vocab_words) |w| try std.testing.expectEqual(@as(i32, -1), synth.logit_mask.?[w]);
    const synth_shape = synth.shape;
    const kinds = [_]u32{synth_decode} ** 3;
    const n_extra = [_]u32{0} ** 3;
    try std.testing.expectEqual(stepShape(3, 4, &kinds, &n_extra), synth_shape);

    // A real decode plan of three entries: prefill three prompts, commit, plan again.
    const prompt = [_]u32{ 1, 2 };
    for (0..3) |_| try std.testing.expect(kelpie_submit(e, &prompt, prompt.len, 4, 0) >= 0);
    var plan: KelpiePlan = undefined;
    try std.testing.expect(kelpie_plan(e, &plan) > 0);
    try std.testing.expectEqual(@as(i32, 0), commitTokens(e, &.{ 5, 5, 5 }));
    try std.testing.expectEqual(@as(u32, 3), kelpie_plan(e, &plan));
    for (0..3) |r| try std.testing.expectEqual(synth_decode, plan.kinds[r]);
    try std.testing.expectEqual(synth_shape, plan.shape);
    try std.testing.expectEqual(@as(i32, 0), commitTokens(e, &.{ 5, 5, 5 }));
}

test "synthetic prefill plan: 1 entry of 16 rows" {
    var cfg = testConfig(0);
    const e = kelpie_create(&cfg) orelse return error.CreateFailed;
    defer kelpie_destroy(e);
    var synth: KelpiePlan = undefined;
    try synthOk(e, synth_prefill, 1, 16, 0, &synth);
    try std.testing.expectEqual(@as(u32, 16), synth.n_tokens);
    try std.testing.expectEqual(buckets.bucket(16), synth.n_tokens_padded);
    try std.testing.expectEqual(buckets.bucket(1), synth.n_reqs_padded);
    try std.testing.expect(synth.logit_mask == null);
    try expectInert(cfg, &synth);
    try expectStructure(&synth, synth_prefill, 16, 0);
    const kinds = [_]u32{synth_prefill};
    const n_extra = [_]u32{0};
    try std.testing.expectEqual(stepShape(16, 1, &kinds, &n_extra), synth.shape);
}

test "synthetic decode plan with extra rows: NO_TOKEN extra rows, per_seq state ZERO/SCRATCH" {
    var cfg = testConfig(0);
    cfg.n_groups = 2;
    cfg.group_kinds = &[_]u32{ 0, 1 }; // per_token, per_seq
    cfg.group_block_sizes = &[_]u32{ 16, 0 };
    cfg.group_windows = &[_]u32{ 0, 6 };
    cfg.group_cacheable = &[_]u8{ 1, 1 };
    cfg.group_strides = &[_]u32{ 1, 16 };
    cfg.max_extra = 4;
    cfg.max_batch_reqs = 3;
    cfg.max_batch_tokens = 48;
    const e = kelpie_create(&cfg) orelse return error.CreateFailed;
    defer kelpie_destroy(e);
    var synth: KelpiePlan = undefined;
    try synthOk(e, synth_decode, 3, 1, 2, &synth);
    try expectInert(cfg, &synth);
    try expectStructure(&synth, synth_decode, 1, 2);
    const zero = synth.zero_unit[1];
    const width = 1 + cfg.max_extra;
    for (0..synth.n_reqs_padded) |r| {
        try std.testing.expectEqual(zero, synth.state_read[1].?[r]);
        for (0..width) |j| try std.testing.expectEqual(scheduler.scratch_unit, synth.state_write[1].?[r * width + j]);
        try std.testing.expectEqual(scheduler.scratch_unit, synth.state_ckpt[1].?[r]);
        try std.testing.expectEqual(request.no_row, synth.state_ckpt_row[1].?[r]);
    }
    const kinds = [_]u32{synth_decode} ** 3;
    const n_extra = [_]u32{2} ** 3;
    try std.testing.expectEqual(stepShape(9, 4, &kinds, &n_extra), synth.shape);
    try std.testing.expectEqual(@as(u32, 2), (synth.shape >> 16) & 0xF);
}

test "a decode_extra plan pads its request axis to what its token bucket can hold" {
    // Kmax = 3, 4 request slots. One request drafting: 4 rows -> token bucket 4, whose most
    // entries is bucket(4 - 1) = 4, so the plan carries 3 pad entries a plain decode of one
    // request would not; the synthetic plan of the same key has the same request axis and shape.
    var cfg = testConfig(0);
    cfg.max_extra = 3;
    const e = kelpie_create(&cfg) orelse return error.CreateFailed;
    defer kelpie_destroy(e);
    var synth: KelpiePlan = undefined;
    try synthOk(e, synth_decode, 1, 1, 3, &synth);
    try std.testing.expectEqual(@as(u32, 4), synth.n_reqs_padded);
    const synth_shape = synth.shape;
    try synthOk(e, synth_decode, 1, 1, 0, &synth); // no extra rows: a plain decode, 1 slot
    try std.testing.expectEqual(@as(u32, 1), synth.n_reqs_padded);

    const prompt = [_]u32{ 1, 2, 3 };
    try std.testing.expect(kelpie_submit(e, &prompt, prompt.len, 8, 0) >= 0);
    var plan: KelpiePlan = undefined;
    try std.testing.expectEqual(@as(u32, 3), kelpie_plan(e, &plan));
    try std.testing.expectEqual(@as(u32, 1), plan.n_reqs_padded); // a prefill pads by its own count
    const t0 = [_]u32{ 40, 0, 0, 0 };
    const c0 = KelpieCommit{ .n_entries = 1, .stride = 4, .tokens = &t0, .n_tokens = null, .next_extra = &[_]u32{3} };
    try std.testing.expectEqual(@as(i32, 0), kelpie_commit(e, &c0));
    try std.testing.expectEqual(@as(u32, 4), kelpie_plan(e, &plan));
    try std.testing.expectEqual(@as(u32, 3), plan.n_extra[0]);
    try std.testing.expectEqual(@as(u32, 4), plan.n_reqs_padded);
    try std.testing.expectEqual(synth_shape, plan.shape);
    for (1..4) |r| {
        try std.testing.expectEqual(@as(u32, 1), plan.seq_lens[r]);
        try std.testing.expectEqual(@as(u32, 0), plan.n_extra[r]);
        try std.testing.expectEqual(plan.n_tokens, plan.query_start_loc[r + 1]);
    }
    const t1 = [_]u32{ 50, 0, 0, 0 };
    const c1 = KelpieCommit{ .n_entries = 1, .stride = 4, .tokens = &t1, .n_tokens = null, .next_extra = &[_]u32{0} };
    try std.testing.expectEqual(@as(i32, 0), kelpie_commit(e, &c1));
}

test "synthetic plans change nothing: a follower that never ran them agrees on every digest" {
    // The edge interleaves synthetic plans with its steps; a follower replays only the edge's
    // batches and payloads (no synthetic plans) and must reproduce every digest. Two separate
    // engines would not do: a submit stamps its arrival time into the batch, so their batch
    // hashes differ anyway.
    var cfg = testConfig(0);
    const e = kelpie_create(&cfg) orelse return error.CreateFailed;
    defer kelpie_destroy(e);
    var rec = Recording{};
    defer rec.deinit();
    try std.testing.expectEqual(@as(i32, 0), kelpie_register_sync(e, Recording.exchange, Recording.agree, &rec, 1));
    const prompt = [_]u32{ 1, 2, 3 };
    try std.testing.expect(kelpie_submit(e, &prompt, prompt.len, 3, 0) >= 0);
    var synth: KelpiePlan = undefined;
    var plan: KelpiePlan = undefined;
    for (0..4) |_| {
        const step = e.sched.step;
        const digest = kelpie_last_digest(e);
        try synthOk(e, synth_prefill, 2, 8, 0, &synth);
        try synthOk(e, synth_decode, 4, 1, 0, &synth);
        try std.testing.expectEqual(step, e.sched.step);
        try std.testing.expectEqual(digest, kelpie_last_digest(e));
        try std.testing.expect(!e.sched.planned());
        const n = kelpie_plan(e, &plan);
        const tokens = [_]u32{7};
        try std.testing.expectEqual(@as(i32, 0), commitTokens(e, if (n == 0) &.{} else &tokens));
    }
    _ = boundaryUnlocked(e, true); // the edge's stop batch

    const f = kelpie_create(&cfg) orelse return error.CreateFailed;
    defer kelpie_destroy(f);
    var replay = Replay{ .msgs = rec.msgs.items, .digests = rec.digests.items };
    try std.testing.expectEqual(@as(i32, 0), kelpie_register_sync(f, Replay.exchange, Replay.agree, &replay, 0));
    try std.testing.expectEqual(@as(u32, 4), replayByHand(f));
    try std.testing.expectEqual(@as(u32, 0), replay.mismatches);
    try std.testing.expectEqual(rec.digests.items.len, replay.next_digest);
    try std.testing.expectEqual(e.digest, f.digest);
}

test "synthetic plan refusals: outstanding plan, and every boundary limit" {
    var cfg = testConfig(0); // max_batch_reqs 4, max_batch_tokens 16, max_seq_len 32, max_extra 0
    const e = kelpie_create(&cfg) orelse return error.CreateFailed;
    defer kelpie_destroy(e);
    var out: KelpiePlan = undefined;
    const S = SyntheticStatus;
    const cases = [_]struct { kind: u32, n_reqs: u32, rows: u32, n_extra: u32, want: S }{
        .{ .kind = 2, .n_reqs = 1, .rows = 1, .n_extra = 0, .want = .err_kind },
        .{ .kind = synth_decode, .n_reqs = 1, .rows = 2, .n_extra = 0, .want = .err_kind },
        .{ .kind = synth_prefill, .n_reqs = 1, .rows = 1, .n_extra = 1, .want = .err_kind },
        .{ .kind = synth_prefill, .n_reqs = 0, .rows = 1, .n_extra = 0, .want = .err_n_reqs },
        .{ .kind = synth_prefill, .n_reqs = 5, .rows = 1, .n_extra = 0, .want = .err_n_reqs },
        .{ .kind = synth_prefill, .n_reqs = 1, .rows = 0, .n_extra = 0, .want = .err_rows },
        .{ .kind = synth_decode, .n_reqs = 1, .rows = 1, .n_extra = 1, .want = .err_extra },
        .{ .kind = synth_prefill, .n_reqs = 1, .rows = 33, .n_extra = 0, .want = .err_seq_len },
        .{ .kind = synth_prefill, .n_reqs = 2, .rows = 9, .n_extra = 0, .want = .err_tokens },
    };
    for (cases) |c| try std.testing.expectEqual(@intFromEnum(c.want), kelpie_synthetic_plan(e, c.kind, c.n_reqs, c.rows, c.n_extra, &out));

    // An outstanding plan -- idle ones included -- owns the buffers until its commit.
    var plan: KelpiePlan = undefined;
    try std.testing.expectEqual(@as(u32, 0), kelpie_plan(e, &plan));
    try std.testing.expectEqual(@intFromEnum(S.err_busy), kelpie_synthetic_plan(e, synth_prefill, 1, 1, 0, &out));
    try std.testing.expectEqual(@as(i32, 0), commitTokens(e, &.{}));
    const prompt = [_]u32{ 1, 2 };
    try std.testing.expect(kelpie_submit(e, &prompt, prompt.len, 2, 0) >= 0);
    try std.testing.expect(kelpie_plan(e, &plan) > 0);
    try std.testing.expectEqual(@intFromEnum(S.err_busy), kelpie_synthetic_plan(e, synth_prefill, 1, 1, 0, &out));
    try std.testing.expectEqual(@as(i32, 0), commitTokens(e, &.{4}));
    try synthOk(e, synth_prefill, 1, 1, 0, &out);
}

test "a plan padded past max_batch_reqs stays in bounds for every ladder step" {
    // Every non-power-of-two request maximum pads up past itself; none may write out of bounds.
    for ([_]u32{ 1, 2, 3, 5, 6, 7 }) |max_reqs| {
        var cfg = testConfig(0);
        cfg.max_requests = 8;
        cfg.max_batch_reqs = max_reqs;
        cfg.max_batch_tokens = 16;
        const e = kelpie_create(&cfg) orelse return error.CreateFailed;
        defer kelpie_destroy(e);
        const prompt = [_]u32{1};
        for (0..max_reqs) |_| try std.testing.expect(kelpie_submit(e, &prompt, 1, 4, 0) >= 0);
        var plan: KelpiePlan = undefined;
        try std.testing.expect(kelpie_plan(e, &plan) > 0);
        try std.testing.expectEqual(buckets.bucket(plan.n_reqs), plan.n_reqs_padded);
        try std.testing.expect(plan.n_reqs_padded >= plan.n_reqs);
        // Touch every padded entry: out-of-bounds shows up here under the test allocator.
        var total: u64 = 0;
        for (0..plan.n_reqs_padded) |r| total += plan.seq_lens[r];
        for (0..plan.n_tokens_padded) |i| total +%= plan.input_ids[i];
        try std.testing.expect(total > 0);
    }
}

test "per_seq group with a checkpoint interval and a window is accepted" {
    // The trace harness builds GroupSpecs directly, so it cannot reach these checks -- this is
    // the only place the config validation itself is exercised. A per_seq group's `stride` is
    // the checkpoint interval S and its `window` is checkpoints kept, so S = 16 with window 6
    // is an ordinary recurrent config, not a stride-k window group.
    var cfg = testConfig(0);
    cfg.n_groups = 2;
    cfg.group_kinds = &[_]u32{ 0, 1 }; // per_token, per_seq
    cfg.group_block_sizes = &[_]u32{ 16, 0 };
    cfg.group_windows = &[_]u32{ 0, 6 }; // checkpoints kept
    cfg.group_cacheable = &[_]u8{ 1, 1 };
    cfg.group_strides = &[_]u32{ 1, 16 }; // per_seq stride = checkpoint interval S
    cfg.max_extra = 4;
    cfg.max_batch_reqs = 3; // pads to 4 entries
    cfg.max_batch_tokens = 48;

    const e = kelpie_create(&cfg) orelse return error.CreateFailed;
    defer kelpie_destroy(e);
    var out: KelpieConfig = undefined;
    kelpie_get_config(e, &out);
    try std.testing.expectEqual(@as(u32, 2), out.n_groups);
    try std.testing.expectEqual(@as(u32, 16), out.group_strides.?[1]);
    try std.testing.expectEqual(@as(u32, 6), out.group_windows[1]);
    try std.testing.expectEqual(@as(u32, 4), out.max_extra);

    // The per_seq state crosses the ABI: per_token groups have no state arrays; real entries
    // read ZERO on a fresh start and write a fresh unit; pads read ZERO and write SCRATCH.
    // A 16-token prompt checkpoints after row 15, stored from its own 16 tokens.
    const prompt = [_]u32{1} ** 16;
    for (0..3) |_| try std.testing.expect(kelpie_submit(e, &prompt, prompt.len, 4, 0) >= 0);
    var plan: KelpiePlan = undefined;
    try std.testing.expect(kelpie_plan(e, &plan) > 0);
    try std.testing.expectEqual(@as(u32, 3), plan.n_reqs);
    try std.testing.expectEqual(@as(u32, 4), plan.n_reqs_padded);
    try std.testing.expectEqual(@as(u32, 4), plan.max_extra);
    try std.testing.expect(plan.state_read[0] == null and plan.state_write[0] == null);
    const zero = plan.zero_unit[1];
    try std.testing.expect(zero != scheduler.scratch_unit);
    try std.testing.expectEqual(@as(u32, 0), plan.zero_unit[0]);
    const read = plan.state_read[1].?;
    const write = plan.state_write[1].?;
    try std.testing.expectEqual(zero, read[0]);
    try std.testing.expect(write[0] != scheduler.scratch_unit and write[0] != zero);
    for (1..5) |j| try std.testing.expectEqual(scheduler.scratch_unit, write[j]);
    try std.testing.expect(plan.state_ckpt[1].?[0] != scheduler.scratch_unit);
    try std.testing.expectEqual(@as(u32, 15), plan.state_ckpt_row[1].?[0]);
    try std.testing.expectEqual(zero, read[3]); // the pad entry
    for (15..20) |j| try std.testing.expectEqual(scheduler.scratch_unit, write[j]);
    try std.testing.expectEqual(scheduler.scratch_unit, plan.state_ckpt[1].?[3]);
    try std.testing.expectEqual(request.no_row, plan.state_ckpt_row[1].?[3]);
    for (plan.n_tokens..plan.n_tokens_padded) |i| try std.testing.expectEqual(@as(u32, 0), plan.slot_mapping[1][i]);
    try std.testing.expectEqual(@as(i32, 0), commitTokens(e, &.{ 5, 5, 5 }));
}

test "config validation rejects what it should: bad windows and stride-k window groups" {
    // A per_token stride-k group with a window is still rejected (its match rule assumes
    // stride 1); a per_seq window needs a checkpoint interval and vice versa; overlap is
    // refused with a per_seq group.
    var stride_window = testConfig(0);
    stride_window.group_windows = &[_]u32{8};
    stride_window.group_strides = &[_]u32{4};
    try std.testing.expectEqual(@as(?*Engine, null), kelpie_create(&stride_window));

    var seq_no_stride = testConfig(0);
    seq_no_stride.group_kinds = &[_]u32{1};
    seq_no_stride.group_windows = &[_]u32{2};
    seq_no_stride.group_strides = &[_]u32{0}; // window without a checkpoint interval
    try std.testing.expectEqual(@as(?*Engine, null), kelpie_create(&seq_no_stride));

    var seq_no_window = testConfig(0);
    seq_no_window.group_kinds = &[_]u32{1};
    seq_no_window.group_windows = &[_]u32{0}; // checkpoints with nowhere to keep them
    seq_no_window.group_strides = &[_]u32{16};
    try std.testing.expectEqual(@as(?*Engine, null), kelpie_create(&seq_no_window));

    var seq_window_one = testConfig(0);
    seq_window_one.group_kinds = &[_]u32{1};
    seq_window_one.group_windows = &[_]u32{1}; // one checkpoint: fine
    seq_window_one.group_strides = &[_]u32{16};
    const e = kelpie_create(&seq_window_one) orelse return error.CreateFailed;
    kelpie_destroy(e);

    var seq_overlap = seq_window_one;
    seq_overlap.overlap = 1;
    try std.testing.expectEqual(@as(?*Engine, null), kelpie_create(&seq_overlap));
}

test "extra rows round trip: next_extra plans them, n_tokens keeps them, bad commits apply nothing" {
    // Kmax = 3. The prefill commit asks for 3 extra rows; the next plan's decode entry is 1
    // history row + 3 extra rows [t0, NO, NO, NO] at consecutive positions, kind decode, n_extra
    // 3. The caller puts drafts there; committing n = 2 [50, 60] says extra row 1 (50) was valid,
    // then 60 is the next token.
    var cfg = testConfig(0);
    cfg.max_extra = 3;
    var with_overlap = cfg;
    with_overlap.overlap = 1;
    try std.testing.expectEqual(@as(?*Engine, null), kelpie_create(&with_overlap));
    const e = kelpie_create(&cfg) orelse return error.CreateFailed;
    defer kelpie_destroy(e);
    const prompt = [_]u32{ 1, 2, 3, 4, 5 };
    const rid = kelpie_submit(e, &prompt, prompt.len, 8, 0);
    try std.testing.expect(rid >= 0);

    var plan: KelpiePlan = undefined;
    try std.testing.expectEqual(@as(u32, 5), kelpie_plan(e, &plan));
    try std.testing.expectEqual(@as(u32, 0), plan.n_extra[0]);
    try std.testing.expectEqual(@as(u32, 0), plan.seq_start[0]);
    try std.testing.expectEqual(@as(u8, 1), plan.emits[0]);
    // A prefill may not keep more than one token, nor ask for more than Kmax: nothing applies.
    const t0 = [_]u32{ 40, 0, 0, 0 };
    var bad = KelpieCommit{ .n_entries = 1, .stride = 4, .tokens = &t0, .n_tokens = &[_]u32{2}, .next_extra = null };
    try std.testing.expectEqual(@as(i32, -2), kelpie_commit(e, &bad));
    bad.n_tokens = null;
    bad.next_extra = &[_]u32{4};
    try std.testing.expectEqual(@as(i32, -2), kelpie_commit(e, &bad));
    bad.n_entries = 2;
    try std.testing.expectEqual(@as(i32, -1), kelpie_commit(e, &bad));
    const t_no = [_]u32{ scheduler.no_token, 0, 0, 0 };
    const bad_token = KelpieCommit{ .n_entries = 1, .stride = 4, .tokens = &t_no, .n_tokens = null, .next_extra = null };
    try std.testing.expectEqual(@as(i32, -4), kelpie_commit(e, &bad_token));
    const t_big = [_]u32{ 1000, 0, 0, 0 }; // testConfig's vocab_size is 100
    const big_token = KelpieCommit{ .n_entries = 1, .stride = 4, .tokens = &t_big, .n_tokens = null, .next_extra = null };
    try std.testing.expectEqual(@as(i32, -4), kelpie_commit(e, &big_token));
    try std.testing.expectEqual(abi_version, kelpie_abi_version());
    var c0 = KelpieCommit{ .n_entries = 1, .stride = 4, .tokens = &t0, .n_tokens = null, .next_extra = &[_]u32{3} };
    try std.testing.expectEqual(@as(i32, 0), kelpie_commit(e, &c0));

    try std.testing.expectEqual(@as(u32, 4), kelpie_plan(e, &plan));
    try std.testing.expectEqual(@as(u32, 1), plan.n_reqs);
    try std.testing.expectEqual(@intFromEnum(scheduler.Kind.decode), plan.kinds[0]);
    try std.testing.expectEqual(@as(u32, 1), plan.n_work[0]);
    try std.testing.expectEqual(@as(u32, 3), plan.n_extra[0]);
    try std.testing.expectEqual(@as(u32, 5), plan.seq_start[0]);
    const no = scheduler.no_token;
    try std.testing.expectEqualSlices(u32, &[_]u32{ 40, no, no, no }, plan.input_ids[0..4]);
    try std.testing.expectEqualSlices(u32, &[_]u32{ 5, 6, 7, 8 }, plan.positions[0..4]);
    try std.testing.expectEqual(@as(u32, 9), plan.seq_lens[0]);
    // Rows exist for every extra row (positions < 9, block 4 -> 3 rows) and no further: the
    // drafter's noise block IS these rows.
    for (0..3) |b| try std.testing.expect(plan.block_tables[0][b] != kv_pool.null_block);
    try std.testing.expectEqual(kv_pool.null_block, plan.block_tables[0][3]);

    const t1 = [_]u32{ 50, 60, 0, 0 };
    var c1 = KelpieCommit{ .n_entries = 1, .stride = 4, .tokens = &t1, .n_tokens = &[_]u32{5}, .next_extra = &[_]u32{3} };
    try std.testing.expectEqual(@as(i32, -2), kelpie_commit(e, &c1)); // n above 1 + n_extra
    c1.n_tokens = &[_]u32{2};
    try std.testing.expectEqual(@as(i32, 0), kelpie_commit(e, &c1));

    // History is now prompt + [40, 50, 60]; the next entry is [60, NO, NO, NO] from position 7.
    try std.testing.expectEqual(@as(u32, 4), kelpie_plan(e, &plan));
    try std.testing.expectEqualSlices(u32, &[_]u32{ 60, no, no, no }, plan.input_ids[0..4]);
    try std.testing.expectEqualSlices(u32, &[_]u32{ 7, 8, 9, 10 }, plan.positions[0..4]);

    // max_new = 8 caps a commit: 3 generated so far, so a 4-token commit keeps 4 (7 total) and
    // the next one keeps one token, finishing the request at exactly 8, never past it.
    const t2 = [_]u32{ 70, 71, 72, 80 };
    const c2 = KelpieCommit{ .n_entries = 1, .stride = 4, .tokens = &t2, .n_tokens = &[_]u32{4}, .next_extra = &[_]u32{3} };
    try std.testing.expectEqual(@as(i32, 0), kelpie_commit(e, &c2));
    try std.testing.expectEqual(@as(u32, 4), kelpie_plan(e, &plan));
    const t3 = [_]u32{ 70, 71, 72, 90 };
    const c3 = KelpieCommit{ .n_entries = 1, .stride = 4, .tokens = &t3, .n_tokens = &[_]u32{4}, .next_extra = &[_]u32{3} };
    try std.testing.expectEqual(@as(i32, 0), kelpie_commit(e, &c3));
    var out: [16]u32 = undefined;
    var poll: KelpiePoll = undefined;
    const n_out = kelpie_poll(e, @intCast(rid), &out, out.len, &poll);
    try std.testing.expectEqual(@as(u32, 8), n_out);
    try std.testing.expectEqualSlices(u32, &[_]u32{ 40, 50, 60, 70, 71, 72, 80, 70 }, out[0..8]);
    try std.testing.expectEqual(@as(u8, 1), poll.finished);
}

test "submit rejects a request above the pool, and a stalled plan is reported" {
    var cfg = testConfig(0);
    cfg.num_blocks = 5; // 4 usable blocks of 4 tokens
    const e = kelpie_create(&cfg) orelse return error.CreateFailed;
    defer kelpie_destroy(e);
    var got: KelpieConfig = undefined;
    kelpie_get_config(e, &got);
    try std.testing.expectEqual(@as(u32, 4), got.num_slabs);

    const prompt = [_]u32{1} ** 8;
    try std.testing.expectEqual(@as(u32, 5), kelpie_worst_slabs(e, 8, 12));
    try std.testing.expectEqual(@as(i64, -5), kelpie_submit(e, &prompt, 8, 12, 0));
    try std.testing.expectEqual(@as(u32, 4), kelpie_worst_slabs(e, 8, 9));
    const rid = kelpie_submit(e, &prompt, 8, 9, 0);
    try std.testing.expect(rid >= 0);

    // A budget below the block grain: A's next chunk is 0 tokens, forever.
    const knob = KelpieKnob{ .kind = @intFromEnum(KnobKind.max_batch_tokens), .u32_value = 2, .f32_value = 0 };
    try std.testing.expectEqual(@as(i32, 0), kelpie_set(e, &knob, null));
    var out: KelpiePlan = undefined;
    try std.testing.expectEqual(@as(u32, 0), kelpie_plan(e, &out));
    try std.testing.expectEqual(@as(i32, 0), commitTokens(e, &.{}));
    var req_id: u32 = 0;
    var n_work: u32 = 1;
    var need: u32 = 1;
    var free: u32 = 0;
    try std.testing.expectEqual(@as(i32, 1), kelpie_stall(e, &req_id, &n_work, &need, &free));
    try std.testing.expectEqual(@as(u32, @intCast(rid)), req_id);
    try std.testing.expectEqual(@as(u32, 0), n_work);
    try std.testing.expectEqual(@as(u32, 4), free);

    kelpie_cancel(e, @intCast(rid));
    try std.testing.expectEqual(@as(u32, 0), kelpie_plan(e, &out));
    try std.testing.expectEqual(@as(i32, 0), commitTokens(e, &.{}));
    try std.testing.expectEqual(@as(i32, 0), kelpie_stall(e, &req_id, &n_work, &need, &free));
}

// ---- step-boundary inputs: determinism, replay, ledger (docs/design-multigpu.md 2.3, section 8)

/// Test sync: an edge-side recorder. Every exchanged message (boundary batches and commit
/// payloads, in call order) and every agreed digest is kept, and the exchange is the identity --
/// world 1 with a tap on the seam.
const Recording = struct {
    mutex: std.Thread.Mutex = .{},
    msgs: std.ArrayListUnmanaged([]u8) = .{},
    digests: std.ArrayListUnmanaged(u64) = .{},

    fn deinit(r: *Recording) void {
        for (r.msgs.items) |m| std.testing.allocator.free(m);
        r.msgs.deinit(std.testing.allocator);
        r.digests.deinit(std.testing.allocator);
    }

    fn exchange(ctx: ?*anyopaque, in: [*]const u8, n_in: u32, out: [*]u8, cap: u32) callconv(.c) u32 {
        const r: *Recording = @ptrCast(@alignCast(ctx.?));
        r.mutex.lock();
        defer r.mutex.unlock();
        r.msgs.append(std.testing.allocator, std.testing.allocator.dupe(u8, in[0..n_in]) catch unreachable) catch unreachable;
        assert(n_in <= cap);
        @memcpy(out[0..n_in], in[0..n_in]);
        return n_in;
    }

    fn agree(ctx: ?*anyopaque, digest: u64) callconv(.c) u32 {
        const r: *Recording = @ptrCast(@alignCast(ctx.?));
        r.mutex.lock();
        defer r.mutex.unlock();
        r.digests.append(std.testing.allocator, digest) catch unreachable;
        return 0;
    }
};

/// Test sync: a follower fed a recording. The exchange hands back the edge's messages in order;
/// agree compares each digest with the edge's and counts the first mismatch.
const Replay = struct {
    msgs: []const []const u8,
    digests: []const u64,
    next_msg: usize = 0,
    next_digest: usize = 0,
    mismatches: u32 = 0,

    fn exchange(ctx: ?*anyopaque, _: [*]const u8, _: u32, out: [*]u8, cap: u32) callconv(.c) u32 {
        const r: *Replay = @ptrCast(@alignCast(ctx.?));
        assert(r.next_msg < r.msgs.len); // the recording ends with the edge's stop batch
        const msg = r.msgs[r.next_msg];
        r.next_msg += 1;
        assert(msg.len <= cap);
        @memcpy(out[0..msg.len], msg);
        return @intCast(msg.len);
    }

    fn agree(ctx: ?*anyopaque, digest: u64) callconv(.c) u32 {
        const r: *Replay = @ptrCast(@alignCast(ctx.?));
        assert(r.next_digest < r.digests.len);
        const want = r.digests[r.next_digest];
        r.next_digest += 1;
        if (digest == want) return 0;
        r.mismatches += 1;
        return 1;
    }
};

/// A follower stepping by hand: plan, then commit whatever payload the edge agreed. Returns the
/// number of plans made, stopping at the edge's stop batch or at a divergence.
fn replayByHand(f: *Engine) u32 {
    var plan: KelpiePlan = undefined;
    var n_plans: u32 = 0;
    while (true) {
        const n = kelpie_plan(f, &plan);
        if (n == plan_stopped or n == plan_diverged) return n_plans;
        n_plans += 1;
        const status = if (n == 0) commitTokens(f, &.{}) else kelpie_commit(f, null);
        assert(status == 0);
    }
}

fn raceConfig(max_extra: u32, overlap: u32) KelpieConfig {
    var cfg = testConfig(0);
    cfg.max_requests = 8;
    cfg.max_seq_len = 64;
    cfg.num_blocks = 40; // small enough to preempt
    cfg.max_batch_tokens = 16;
    cfg.max_batch_reqs = 4;
    cfg.max_extra = max_extra;
    cfg.overlap = overlap;
    cfg.prefix_cache = 1;
    return cfg;
}

/// The fake model: a deterministic PRNG step fn. Keeps 1..1+n_extra tokens per entry (ids below
/// the vocab, eos sometimes), asks for 0 or Kmax extra rows next.
const FakeModel = struct {
    rng: std.Random.DefaultPrng,
    max_extra: u32,
    launches: std.atomic.Value(u32) = .init(0),

    fn fill(m: *FakeModel, plan: *const KelpiePlan, out: *KelpieStepOut) void {
        const random = m.rng.random();
        for (0..plan.n_reqs) |i| {
            const n = 1 + random.uintAtMost(u32, plan.n_extra[i]);
            out.n_tokens[i] = n;
            out.next_extra[i] = if (random.boolean()) m.max_extra else 0;
            for (0..n) |j| out.tokens[i * out.stride + j] = random.uintLessThan(u32, 12);
        }
        _ = m.launches.fetchAdd(1, .monotonic);
    }

    fn launch(ctx: *anyopaque, _: u32, plan: *const KelpiePlan, out: *KelpieStepOut) callconv(.c) u32 {
        const m: *FakeModel = @ptrCast(@alignCast(ctx));
        m.fill(plan, out);
        return 0;
    }

    fn launchWait(_: *anyopaque, _: *KelpieStepOut) callconv(.c) u32 {
        return 0;
    }
};

/// Callers racing the loop: submits (random prompts from shared stems), cancels (sometimes a
/// stale generation), polls that release, knobs. Every id it was handed is polled to the end.
const Driver = struct {
    e: *Engine,
    seed: u64,
    n_submits: u32,
    /// Longest prompt, overlap or not: max_batch_tokens knobs of 8..16 chunk the longer ones.
    max_prompt: u32 = 30,
    submitted: std.atomic.Value(u32) = .init(0),

    fn submitter(d: *Driver) void {
        var rng = std.Random.DefaultPrng.init(d.seed);
        const random = rng.random();
        var stem: [40]u32 = undefined;
        for (&stem, 0..) |*t, i| t.* = 20 + @as(u32, @intCast(i % 30));
        var done: u32 = 0;
        while (done < d.n_submits) {
            const n_prompt = 1 + random.uintLessThan(u32, d.max_prompt);
            var prompt: [40]u32 = stem;
            if (random.boolean()) for (prompt[0..n_prompt]) |*t| {
                t.* = 10 + random.uintLessThan(u32, 80);
            };
            const max_new = random.uintLessThan(u32, 20);
            const rid = kelpie_submit(d.e, &prompt, n_prompt, max_new, 0);
            if (rid == -1) { // Full: wait for a release
                std.Thread.yield() catch {};
                continue;
            }
            assert(rid >= 0);
            done += 1;
            _ = d.submitted.fetchAdd(1, .release);
            if (random.uintLessThan(u32, 8) == 0) kelpie_cancel(d.e, @intCast(rid));
            if (random.uintLessThan(u32, 16) == 0) {
                const gen = kelpie_generation(d.e, @intCast(rid));
                _ = kelpie_cancel_gen(d.e, @intCast(rid), gen -% 1); // stale: a no-op
            }
            if (random.uintLessThan(u32, 10) == 0) {
                const knob = KelpieKnob{ .kind = @intFromEnum(KnobKind.max_batch_tokens), .u32_value = 8 + random.uintLessThan(u32, 9), .f32_value = 0 };
                assert(kelpie_set(d.e, &knob, null) == 0);
            }
            if (random.uintLessThan(u32, 4) == 0) std.time.sleep(50 * std.time.ns_per_us);
        }
    }

    /// Polls every id until nothing live is left (releases happen here). Stops once every submit
    /// is in and every id reads finished.
    fn poller(d: *Driver) void {
        var out: [64]u32 = undefined;
        var result: KelpiePoll = undefined;
        while (true) {
            // Read before the pass: a submit counted here has its id reserved already, so the
            // pass sees it (read after, the last submit could land in an id this pass had just
            // seen free, and the poller would leave it unpolled).
            const submitted = d.submitted.load(.acquire);
            var all_done = true;
            for (0..d.e.cfg.max_requests) |id| {
                _ = kelpie_poll(d.e, @intCast(id), &out, out.len, &result);
                if (result.finished == 0) all_done = false;
            }
            if (all_done and submitted == d.n_submits) {
                // One more boundary applies the releases the last polls queued.
                kelpie_wake(d.e);
                return;
            }
            std.Thread.yield() catch {};
        }
    }
};

fn quiescent(e: *Engine) !void {
    e.loop.mutex.lock();
    defer e.loop.mutex.unlock();
    for (e.reqs.requests) |req| try std.testing.expect(!req.owned);
    for (e.inbox.slots) |slot| try std.testing.expectEqual(inputs.SlotState.free, slot.state);
    try std.testing.expectEqual(e.cfg.max_requests, e.inbox.n_free);
    try std.testing.expectEqual(e.cfg.max_requests, e.reqs.n_free);
}

/// Waits for the loop to go idle with every request released: all ids free in the core.
fn waitQuiescent(e: *Engine) void {
    var tries: u32 = 0;
    while (true) : (tries += 1) {
        {
            e.loop.mutex.lock();
            defer e.loop.mutex.unlock();
            if (e.reqs.n_free == e.cfg.max_requests and e.inbox.n_ops == 0) return;
            if (tries == 2000) for (e.reqs.requests, e.inbox.slots, 0..) |req, slot, id| {
                std.debug.print("DEBUG id={d} owned={} state={s} planned={} ahead={} gen={d} ledger={s} lgen={d} cq={} n={d} nc={d} polled={d}\n", .{ id, req.owned, @tagName(req.state), req.planned, req.planned_ahead, e.gens[id], @tagName(slot.state), slot.gen, slot.cancel_queued, req.seq.n, req.seq.n_computed, req.n_polled });
            };
        }
        kelpie_wake(e);
        std.time.sleep(std.time.ns_per_ms);
    }
}

fn raceAndReplay(max_extra: u32, overlap: u32, seed: u64) !void {
    var cfg = raceConfig(max_extra, overlap);
    const e = kelpie_create(&cfg) orelse return error.CreateFailed;
    defer kelpie_destroy(e);
    var rec = Recording{};
    defer rec.deinit();
    try std.testing.expectEqual(@as(i32, 0), kelpie_register_sync(e, Recording.exchange, Recording.agree, &rec, 1));
    var model = FakeModel{ .rng = .init(seed), .max_extra = max_extra };
    if (overlap != 0) {
        try std.testing.expectEqual(@as(i32, 0), kelpie_register_launch_split(e, FakeModel.launch, FakeModel.launch, FakeModel.launchWait, &model));
    } else {
        try std.testing.expectEqual(@as(i32, 0), kelpie_register_launch(e, FakeModel.launch, &model));
    }
    try std.testing.expectEqual(@as(i32, 0), kelpie_start_loop(e));

    var driver = Driver{ .e = e, .seed = seed ^ 0x9E37, .n_submits = 60 };
    const t_submit = try std.Thread.spawn(.{}, Driver.submitter, .{&driver});
    const t_poll = try std.Thread.spawn(.{}, Driver.poller, .{&driver});
    t_submit.join();
    t_poll.join();
    waitQuiescent(e);
    kelpie_stop_loop(e); // the edge sends its stop batch: the recording's last message
    try quiescent(e);
    try std.testing.expect(model.launches.load(.monotonic) > 20);
    try std.testing.expect(rec.digests.items.len > 20);

    // A fresh follower replays the recording and must reproduce every digest: by hand, or as a
    // loop of its own (the overlap loop cannot be stepped by hand).
    var cfg_f = cfg;
    const f = kelpie_create(&cfg_f) orelse return error.CreateFailed;
    defer kelpie_destroy(f);
    var replay = Replay{ .msgs = rec.msgs.items, .digests = rec.digests.items };
    try std.testing.expectEqual(@as(i32, 0), kelpie_register_sync(f, Replay.exchange, Replay.agree, &replay, 0));
    if (overlap != 0) {
        var follower_model = FakeModel{ .rng = .init(seed +% 1), .max_extra = max_extra }; // its payloads lose to the edge's
        try std.testing.expectEqual(@as(i32, 0), kelpie_register_launch_split(f, FakeModel.launch, FakeModel.launch, FakeModel.launchWait, &follower_model));
        try std.testing.expectEqual(@as(i32, 0), kelpie_start_loop(f));
        f.loop.thread.?.join(); // returns at the stop batch
        f.loop.thread = null;
    } else {
        _ = replayByHand(f);
    }
    try std.testing.expectEqual(@as(u32, 0), replay.mismatches);
    try std.testing.expectEqual(rec.digests.items.len, replay.next_digest);
    try std.testing.expectEqual(rec.msgs.items.len, replay.next_msg);
    try std.testing.expectEqual(e.digest, f.digest);
    try quiescent(f);
}

test "inbox race: callers race the native loop; a by-hand follower replays every digest" {
    try raceAndReplay(3, 0, 1);
    try raceAndReplay(0, 0, 2);
}

test "overlap + inbox: ops land between launch_async and plan N+1; a follower loop replays it" {
    try raceAndReplay(0, 1, 3);
    try raceAndReplay(0, 1, 4);
}

/// A scripted by-hand edge: submits, a cancel in flight, a knob, polls that release, a reused id.
fn scriptedEdge(e: *Engine) !void {
    var plan: KelpiePlan = undefined;
    const a = [_]u32{ 1, 2, 3, 4, 5 };
    const b = [_]u32{ 1, 2, 3, 6 };
    const ra = kelpie_submit(e, &a, a.len, 6, 0);
    const rb = kelpie_submit(e, &b, b.len, 3, 0);
    try std.testing.expect(ra >= 0 and rb >= 0);
    var out: [16]u32 = undefined;
    var poll: KelpiePoll = undefined;
    var step: u32 = 0;
    while (step < 30) : (step += 1) {
        const n = kelpie_plan(e, &plan);
        if (step == 2) {
            const knob = KelpieKnob{ .kind = @intFromEnum(KnobKind.order), .u32_value = 1, .f32_value = 0 };
            try std.testing.expectEqual(@as(i32, 0), kelpie_set(e, &knob, null));
            kelpie_cancel(e, @intCast(rb)); // between plan and commit: applies at the next boundary
        }
        if (step == 4) _ = kelpie_submit(e, &b, b.len, 2, 0); // may reuse rb's id
        if (n == 0) {
            try std.testing.expectEqual(@as(i32, 0), commitTokens(e, &.{}));
        } else {
            var tokens: [8]u32 = undefined;
            for (tokens[0..plan.n_reqs], 0..) |*t, i| t.* = 30 + @as(u32, @intCast(i + step));
            try std.testing.expectEqual(@as(i32, 0), commitTokens(e, tokens[0..plan.n_reqs]));
        }
        for (0..e.cfg.max_requests) |id| _ = kelpie_poll(e, @intCast(id), &out, out.len, &poll);
    }
    _ = boundaryUnlocked(e, true); // the edge's stop batch (the loop sends it on close)
}

test "replay with one dropped op fails the digest at exactly that op's step, for every op" {
    var cfg = testConfig(0);
    const e = kelpie_create(&cfg) orelse return error.CreateFailed;
    defer kelpie_destroy(e);
    var rec = Recording{};
    defer rec.deinit();
    try std.testing.expectEqual(@as(i32, 0), kelpie_register_sync(e, Recording.exchange, Recording.agree, &rec, 1));
    try scriptedEdge(e);

    // Unmodified: every digest matches, to the stop batch.
    {
        const f = kelpie_create(&cfg) orelse return error.CreateFailed;
        defer kelpie_destroy(f);
        var replay = Replay{ .msgs = rec.msgs.items, .digests = rec.digests.items };
        try std.testing.expectEqual(@as(i32, 0), kelpie_register_sync(f, Replay.exchange, Replay.agree, &replay, 0));
        try std.testing.expectEqual(@as(u32, 30), replayByHand(f));
        try std.testing.expectEqual(@as(u32, 0), replay.mismatches);
        try std.testing.expectEqual(@as(u32, 0), kelpie_divergence(f, null));
    }

    // Each batch message with ops, each op dropped in turn: the follower fails at that batch's
    // boundary -- the plan right after it -- and not a step earlier.
    var n_cases: u32 = 0;
    var msgs = try std.testing.allocator.alloc([]const u8, rec.msgs.items.len);
    defer std.testing.allocator.free(msgs);
    var scratch = try std.testing.allocator.alloc(u32, e.batch.len);
    defer std.testing.allocator.free(scratch);
    for (rec.msgs.items, 0..) |msg, m| {
        if (msg.len < inputs.header_words * 4 or msg.len % 4 != 0) continue;
        const words = std.mem.bytesAsSlice(u32, @as([]align(4) const u8, @alignCast(msg)));
        const header = inputs.headerOf(words);
        if (header.version != inputs.wire_version or header.n_words * 4 + inputs.header_words * 4 != msg.len) continue; // a payload, not a batch
        for (0..header.n_ops) |drop| {
            const n = inputs.dropOp(words, @intCast(drop), scratch);
            @memcpy(msgs, rec.msgs.items);
            msgs[m] = std.mem.sliceAsBytes(scratch[0..n]);
            const f = kelpie_create(&cfg) orelse return error.CreateFailed;
            defer kelpie_destroy(f);
            var replay = Replay{ .msgs = msgs, .digests = rec.digests.items };
            try std.testing.expectEqual(@as(i32, 0), kelpie_register_sync(f, Replay.exchange, Replay.agree, &replay, 0));
            const n_plans = replayByHand(f);
            var step: u64 = 0;
            try std.testing.expectEqual(@intFromEnum(Divergence.digest), kelpie_divergence(f, &step));
            try std.testing.expectEqual(header.boundary, step);
            try std.testing.expectEqual(header.boundary, n_plans + 1); // every plan before it agreed
            n_cases += 1;
        }
    }
    try std.testing.expect(n_cases >= 6); // submits, a cancel, a knob, releases, a resubmit
}

test "stale cancel after id reuse is a no-op, at the API and at apply" {
    var cfg = testConfig(0);
    cfg.max_requests = 1; // one slot: the second submit must reuse the first's id
    const e = kelpie_create(&cfg) orelse return error.CreateFailed;
    defer kelpie_destroy(e);
    var plan: KelpiePlan = undefined;
    var out: [16]u32 = undefined;
    var poll: KelpiePoll = undefined;
    const prompt = [_]u32{ 1, 2 };
    const a = kelpie_submit(e, &prompt, prompt.len, 1, 0);
    try std.testing.expect(a >= 0);
    const gen_a = kelpie_generation(e, @intCast(a));
    try std.testing.expect(kelpie_plan(e, &plan) > 0);
    try std.testing.expectEqual(@as(i32, 0), commitTokens(e, &.{5}));
    _ = kelpie_poll(e, @intCast(a), &out, out.len, &poll);
    try std.testing.expectEqual(@as(u8, 1), poll.finished); // release queued; the id is free now
    const b = kelpie_submit(e, &prompt, prompt.len, 3, 0);
    try std.testing.expectEqual(a, b);
    const gen_b = kelpie_generation(e, @intCast(b));
    try std.testing.expect(gen_b != gen_a);
    try std.testing.expectEqual(@as(i32, 0), kelpie_cancel_gen(e, @intCast(b), gen_a)); // stale
    try std.testing.expect(kelpie_plan(e, &plan) > 0); // release(a) then submit(b) apply, in order
    try std.testing.expectEqual(@as(u32, 1), plan.n_reqs);
    // At apply: an op naming the old generation does nothing to the new occupant.
    {
        e.loop.mutex.lock();
        defer e.loop.mutex.unlock();
        applyCancel(e, .{ .id = @intCast(b), .gen = gen_a });
        applyRelease(e, .{ .id = @intCast(b), .gen = gen_a });
        try std.testing.expect(e.reqs.requests[@intCast(b)].state == .running);
    }
    try std.testing.expectEqual(@as(i32, 0), commitTokens(e, &.{6}));
    for (0..2) |_| {
        try std.testing.expect(kelpie_plan(e, &plan) > 0);
        try std.testing.expectEqual(@as(i32, 0), commitTokens(e, &.{7}));
    }
    _ = kelpie_poll(e, @intCast(b), &out, out.len, &poll);
    try std.testing.expectEqual(@as(u8, 1), poll.finished);
    try std.testing.expectEqual(@intFromEnum(request.State.finished_length), poll.state);
    try std.testing.expectEqualSlices(u32, &.{ 6, 7, 7 }, out[0..3]);
}

/// Every submit op in the recorded batches (the payload messages are skipped), in order.
fn recordedSubmits(rec: *const Recording, out: []inputs.Ref) usize {
    var n: usize = 0;
    for (rec.msgs.items) |msg| {
        if (msg.len < inputs.header_words * 4 or msg.len % 4 != 0) continue;
        const words = std.mem.bytesAsSlice(u32, @as([]align(4) const u8, @alignCast(msg)));
        const header = inputs.headerOf(words);
        if (header.version != inputs.wire_version or header.n_words * 4 + inputs.header_words * 4 != msg.len) continue;
        var r = inputs.Reader.of(words);
        while (r.next()) |op| switch (op) {
            .submit => |sub| {
                out[n] = .{ .id = sub.id, .gen = sub.gen };
                n += 1;
            },
            else => {},
        };
    }
    return n;
}

test "a submit cancelled before its boundary never reaches the core: no op, and the id's next occupant is the only one replay sees" {
    // B2 (54d28a7): the cancel drops the queued submit op and frees the id at once. The caller
    // saw an occupant (an id, a generation, a poll that reads cancelled with no tokens) that no
    // rank ever applies, so a replay oracle must key occupants by (id, generation), not count them.
    var cfg = testConfig(0);
    cfg.max_requests = 1; // the resubmit must reuse the id
    const e = kelpie_create(&cfg) orelse return error.CreateFailed;
    defer kelpie_destroy(e);
    var rec = Recording{};
    defer rec.deinit();
    try std.testing.expectEqual(@as(i32, 0), kelpie_register_sync(e, Recording.exchange, Recording.agree, &rec, 1));
    var plan: KelpiePlan = undefined;
    var out: [16]u32 = undefined;
    var poll: KelpiePoll = undefined;
    const prompt = [_]u32{ 1, 2, 3 };

    const a = kelpie_submit(e, &prompt, prompt.len, 2, 0);
    try std.testing.expect(a >= 0);
    const gen_a = kelpie_generation(e, @intCast(a));
    kelpie_cancel(e, @intCast(a)); // before any boundary: the op is dropped
    try std.testing.expectEqual(@as(u32, 0), e.inbox.n_ops);
    _ = kelpie_poll(e, @intCast(a), &out, out.len, &poll);
    try std.testing.expectEqual(@as(u32, 0), poll.n_new);
    try std.testing.expectEqual(@as(u8, 1), poll.finished);
    try std.testing.expectEqual(@intFromEnum(request.State.cancelled), poll.state);

    const b = kelpie_submit(e, &prompt, prompt.len, 2, 0);
    try std.testing.expectEqual(a, b);
    const gen_b = kelpie_generation(e, @intCast(b));
    try std.testing.expect(gen_b != gen_a);
    var got: [2]u32 = undefined;
    var n_got: usize = 0;
    for (0..2) |i| {
        try std.testing.expect(kelpie_plan(e, &plan) > 0);
        try std.testing.expectEqual(@as(i32, 0), commitTokens(e, &.{@intCast(40 + i)}));
        _ = kelpie_poll(e, @intCast(b), &out, out.len, &poll);
        @memcpy(got[n_got..][0..poll.n_new], out[0..poll.n_new]);
        n_got += poll.n_new;
    }
    try std.testing.expectEqual(@as(u8, 1), poll.finished);
    try std.testing.expectEqualSlices(u32, &.{ 40, 41 }, got[0..n_got]);
    _ = boundaryUnlocked(e, true); // the edge's stop batch

    // The recording names B's generation only: A never existed for any rank.
    var subs: [4]inputs.Ref = undefined;
    const n_subs = recordedSubmits(&rec, &subs);
    try std.testing.expectEqual(@as(usize, 1), n_subs);
    try std.testing.expectEqual(inputs.Ref{ .id = @intCast(b), .gen = gen_b }, subs[0]);

    // And a by-hand follower agrees with the edge on every digest.
    const f = kelpie_create(&cfg) orelse return error.CreateFailed;
    defer kelpie_destroy(f);
    var replay = Replay{ .msgs = rec.msgs.items, .digests = rec.digests.items };
    try std.testing.expectEqual(@as(i32, 0), kelpie_register_sync(f, Replay.exchange, Replay.agree, &replay, 0));
    _ = replayByHand(f);
    try std.testing.expectEqual(@as(u32, 0), replay.mismatches);
    try std.testing.expectEqual(rec.digests.items.len, replay.next_digest);
}

test "poll between submit and boundary: waiting, no tokens -- also for a reused id" {
    var cfg = testConfig(0);
    cfg.max_requests = 1;
    const e = kelpie_create(&cfg) orelse return error.CreateFailed;
    defer kelpie_destroy(e);
    var plan: KelpiePlan = undefined;
    var out: [16]u32 = undefined;
    var poll: KelpiePoll = undefined;
    const prompt = [_]u32{ 1, 2 };
    const a = kelpie_submit(e, &prompt, prompt.len, 1, 0);
    try std.testing.expectEqual(@as(u32, 0), kelpie_poll(e, @intCast(a), &out, out.len, &poll));
    try std.testing.expectEqual(@as(u8, 0), poll.finished);
    try std.testing.expectEqual(@intFromEnum(request.State.waiting), poll.state);
    try std.testing.expect(!e.reqs.requests[@intCast(a)].owned); // nothing in the core yet
    try std.testing.expect(kelpie_plan(e, &plan) > 0);
    try std.testing.expectEqual(@as(i32, 0), commitTokens(e, &.{5}));
    try std.testing.expectEqual(@as(u32, 1), kelpie_poll(e, @intCast(a), &out, out.len, &poll));
    try std.testing.expectEqual(@as(u8, 1), poll.finished);
    // The id is reused before the release applies: poll sees the new request, not a's finish.
    const b = kelpie_submit(e, &prompt, prompt.len, 1, 0);
    try std.testing.expectEqual(a, b);
    try std.testing.expectEqual(@as(u32, 0), kelpie_poll(e, @intCast(b), &out, out.len, &poll));
    try std.testing.expectEqual(@as(u8, 0), poll.finished);
    try std.testing.expect(e.reqs.requests[@intCast(a)].owned); // a still holds the slot in the core
    // A second submit: Full, synchronously (the pool's one id is reserved), and no op for it.
    try std.testing.expectEqual(@as(i64, -1), kelpie_submit(e, &prompt, prompt.len, 1, 0));
    try std.testing.expect(kelpie_plan(e, &plan) > 0);
    try std.testing.expectEqual(@as(u32, 1), e.sched.live().building.n_rejected_full);
    try std.testing.expectEqual(@as(i32, 0), commitTokens(e, &.{6}));
    try std.testing.expectEqual(@as(u32, 1), e.sched.event.n_rejected_full);
    // Cancel reports cancelled at once, before any boundary.
    const c_prompt = [_]u32{3};
    _ = kelpie_poll(e, @intCast(b), &out, out.len, &poll); // b finished: release queued
    const c = kelpie_submit(e, &c_prompt, 1, 4, 0);
    try std.testing.expect(c >= 0);
    kelpie_cancel(e, @intCast(c));
    _ = kelpie_poll(e, @intCast(c), &out, out.len, &poll);
    try std.testing.expectEqual(@as(u8, 1), poll.finished);
    try std.testing.expectEqual(@intFromEnum(request.State.cancelled), poll.state);
    try std.testing.expectEqual(@as(u32, 0), kelpie_plan(e, &plan)); // release b, submit c, cancel c: idle
    try std.testing.expectEqual(@as(i32, 0), commitTokens(e, &.{}));
    try quiescent(e);
}

test "a drain in progress rejects submits synchronously (-4); a queued submit waits it out" {
    var cfg = testConfig(0);
    const e = kelpie_create(&cfg) orelse return error.CreateFailed;
    defer kelpie_destroy(e);
    const prompt = [_]u32{ 1, 2 };
    try std.testing.expect(kelpie_submit(e, &prompt, prompt.len, 2, 0) >= 0);
    {
        e.loop.mutex.lock();
        defer e.loop.mutex.unlock();
        scheduler.enterDraining(&e.sched);
    }
    try std.testing.expectEqual(@as(i64, -4), kelpie_submit(e, &prompt, prompt.len, 2, 0));
    var plan: KelpiePlan = undefined;
    try std.testing.expectEqual(@as(u32, 0), kelpie_plan(e, &plan)); // applied, but draining admits no one
    try std.testing.expectEqual(@as(i32, 0), commitTokens(e, &.{}));
    try std.testing.expectEqual(@as(u32, 1), e.sched.n_waiting);
    {
        e.loop.mutex.lock();
        defer e.loop.mutex.unlock();
        scheduler.leaveDraining(&e.sched);
    }
    try std.testing.expect(kelpie_plan(e, &plan) > 0);
    try std.testing.expectEqual(@as(i32, 0), commitTokens(e, &.{3}));
}

test "S2: a submit the live config no longer fits closes cancelled at apply, slot kept" {
    // The edge accepted it against the config it saw; a knob ahead of it in the same batch (or
    // an earlier one) can move worstSlabs (it depends on max_batch_tokens through the chunking of
    // a window group). The verdict at apply reads only core state, so every rank reaches it.
    var cfg = testConfig(0);
    cfg.num_blocks = 5; // 4 slabs of 4 tokens
    const e = kelpie_create(&cfg) orelse return error.CreateFailed;
    defer kelpie_destroy(e);
    e.loop.mutex.lock();
    defer e.loop.mutex.unlock();
    const big = [_]u32{1} ** 20;
    try std.testing.expect(scheduler.worstSlabs(&e.sched, big.len, 12) > e.kv.slabs.len);
    applySubmit(e, .{ .id = 2, .gen = 9, .max_new = 12, .temperature = 0, .top_k = 0, .mm = .{ .hash = 0, .start = 0 }, .grammar_key = 0, .t_arrival_ns = 0, .stop = &.{}, .prompt = &big });
    try std.testing.expect(e.reqs.requests[2].owned);
    try std.testing.expect(e.reqs.requests[2].state == .cancelled);
    try std.testing.expectEqual(@as(u32, 0), e.sched.n_waiting);
    try std.testing.expectEqual(@as(u32, 9), e.gens[2]);
    // A cancel of the rejected request is its release (it used to be a no-op: a leaked slot).
    applyCancel(e, .{ .id = 2, .gen = 9 });
    try std.testing.expect(!e.reqs.requests[2].owned);
}

test "apply_step is exact: the knob's hash shows up at exactly that step, by hand and in the loop" {
    var cfg = testConfig(0);
    const e = kelpie_create(&cfg) orelse return error.CreateFailed;
    defer kelpie_destroy(e);
    var plan: KelpiePlan = undefined;
    var event: events.StepEvent = undefined;
    const h0 = e.sched.config_hash;
    for (0..3) |_| {
        _ = kelpie_plan(e, &plan);
        try std.testing.expectEqual(@as(i32, 0), commitTokens(e, &.{}));
    }
    // Set between steps, and between a plan and its commit: both name the next boundary.
    var knob = KelpieKnob{ .kind = @intFromEnum(KnobKind.order), .u32_value = 1, .f32_value = 0 };
    var set: KelpieSetResult = undefined;
    try std.testing.expectEqual(@as(i32, 0), kelpie_set(e, &knob, &set));
    try std.testing.expectEqual(@as(u64, 4), set.apply_step);
    _ = kelpie_plan(e, &plan); // step 4
    knob = .{ .kind = @intFromEnum(KnobKind.reserve_ratio), .u32_value = 0, .f32_value = 0.5 };
    var set2: KelpieSetResult = undefined;
    try std.testing.expectEqual(@as(i32, 0), kelpie_set(e, &knob, &set2));
    try std.testing.expectEqual(@as(u64, 5), set2.apply_step);
    try std.testing.expectEqual(@as(i32, 0), commitTokens(e, &.{}));
    kelpie_step_event(e, &event);
    try std.testing.expectEqual(@as(u64, 4), event.step);
    try std.testing.expect(event.config_hash != h0);
    try std.testing.expect(event.config_hash != set2.config_hash);
    _ = kelpie_plan(e, &plan); // step 5
    try std.testing.expectEqual(@as(i32, 0), commitTokens(e, &.{}));
    kelpie_step_event(e, &event);
    try std.testing.expectEqual(set2.config_hash, event.config_hash);

    // The loop: each set's apply_step is the step whose commit record first carries its hash.
    var model = FakeModel{ .rng = .init(7), .max_extra = 0 };
    try std.testing.expectEqual(@as(i32, 0), kelpie_register_launch(e, FakeModel.launch, &model));
    try std.testing.expectEqual(@as(i32, 0), kelpie_start_loop(e));
    defer kelpie_stop_loop(e);
    var reqs: [4]u32 = undefined;
    var dropped: u32 = 0;
    while (kelpie_next_commit(e, &event, &reqs, reqs.len, &dropped) >= 0) {} // drain the start
    var prev_hash = set2.config_hash;
    for (0..20) |i| {
        knob = .{ .kind = @intFromEnum(KnobKind.max_batch_tokens), .u32_value = 8 + @as(u32, @intCast(i % 5)), .f32_value = 0 };
        try std.testing.expectEqual(@as(i32, 0), kelpie_set(e, &knob, &set));
        const prompt = [_]u32{ 1, 2, 3 };
        if (i % 3 == 0) _ = kelpie_submit(e, &prompt, prompt.len, 2, 0);
        while (true) {
            if (kelpie_next_commit(e, &event, &reqs, reqs.len, &dropped) < 0) {
                std.Thread.yield() catch {};
                continue;
            }
            if (event.step < set.apply_step) {
                try std.testing.expectEqual(prev_hash, event.config_hash);
                continue;
            }
            try std.testing.expectEqual(set.apply_step, event.step);
            try std.testing.expectEqual(set.config_hash, event.config_hash);
            prev_hash = event.config_hash;
            break;
        }
    }
}

test "validateCommit parity: the loop's StepOut path refuses exactly what kelpie_commit refuses" {
    var cfg = testConfig(0);
    cfg.max_extra = 3;
    const e = kelpie_create(&cfg) orelse return error.CreateFailed;
    defer kelpie_destroy(e);
    const prompt = [_]u32{ 1, 2, 3, 4, 5 };
    _ = kelpie_submit(e, &prompt, prompt.len, 8, 0);
    var plan: KelpiePlan = undefined;
    try std.testing.expect(kelpie_plan(e, &plan) > 0);
    try std.testing.expectEqual(@as(i32, 0), kelpie_commit(e, &.{ .n_entries = 1, .stride = 4, .tokens = &[_]u32{ 40, 0, 0, 0 }, .n_tokens = null, .next_extra = &[_]u32{3} }));
    try std.testing.expect(kelpie_plan(e, &plan) > 0); // decode entry with 3 extra rows
    const no = scheduler.no_token;
    const Case = struct { tokens: [4]u32, n: u32, extra: u32 };
    const cases = [_]Case{
        .{ .tokens = .{ 1, 2, 3, 4 }, .n = 5, .extra = 0 }, // n above 1 + n_extra
        .{ .tokens = .{ 1, 2, 3, 4 }, .n = 0, .extra = 0 }, // n 0
        .{ .tokens = .{ 1, 2, 3, 4 }, .n = 2, .extra = 4 }, // next_extra above Kmax
        .{ .tokens = .{ 1, no, 3, 4 }, .n = 2, .extra = 0 }, // a kept NO_TOKEN
        .{ .tokens = .{ 1, 200, 3, 4 }, .n = 2, .extra = 0 }, // a kept id >= vocab
        .{ .tokens = .{ 1, 2, 3, no }, .n = 3, .extra = 3 }, // ok: the NO_TOKEN is not kept
    };
    for (cases) |case| {
        const c = KelpieCommit{ .n_entries = 1, .stride = 4, .tokens = &case.tokens, .n_tokens = &[_]u32{case.n}, .next_extra = &[_]u32{case.extra} };
        e.out_n[0] = case.n;
        e.out_extra[0] = case.extra;
        @memcpy(e.out_tokens[0..4], &case.tokens);
        const via_loop = blk: {
            e.loop.mutex.lock();
            defer e.loop.mutex.unlock();
            break :blk validateCommit(e, stepOutCommit(e, 1)).status;
        };
        const via_commit = kelpie_commit(e, &c);
        try std.testing.expectEqual(@intFromEnum(via_loop), via_commit);
        if (via_commit == 0) break; // applied; nothing after it is in flight
    }
    try std.testing.expect(!e.sched.planned()); // the last case was valid and applied
}
