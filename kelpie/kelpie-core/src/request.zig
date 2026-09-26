//! Pool.init once at startup.
//! acquire/release request slots.
//! advance/appendToken/preempt move a request through its life.

const std = @import("std");
const assert = std.debug.assert;
const events = @import("events.zig");

pub const GroupKind = enum { per_token, per_seq };

/// What a per_token group keeps (docs/cache-groups-ladder.md): `all` grows forever; `window` keeps the last
/// W tokens, entering the prefix index only if cacheable. Drives the prefix hit rule in prefix.zig.
pub const Retention = union(enum) {
    all,
    window: struct { w: u32, cacheable: bool },
};

pub const GroupSpec = struct {
    kind: GroupKind,
    block_size: u32,
    retention: Retention = .all,
    /// per_token: tokens per cache unit (DSV4 compressed KV: one unit every 4 or 128 tokens). A block
    /// holds `block_size` units, so it spans `tokensPerBlock` tokens; unit `j` is written when token
    /// `stride * j + stride - 1` is computed. Window groups are stride 1.
    /// per_seq: the checkpoint interval S. A step whose history rows cross a multiple b of S
    /// writes the state after token b - 1 into a fresh checkpoint unit (the largest such b, at
    /// most one per step); S = 0 means never checkpoint. The per_seq `retention.window.w` is the
    /// number of checkpoints a request keeps (nCheckpoints), not tokens.
    stride: u32 = 1,
};

/// A per_seq checkpoint: unit `id` holds the state after tokens[0..pos), i.e. prefix length
/// `pos` (a multiple of the group's stride).
pub const Ckpt = struct { id: u32, pos: u32 };

/// One request's units in one per_seq group (docs/design-core-option2.md 2.2). `live` holds
/// the state after tokens[0..n_computed); 0 means none yet (a fresh request, or one that just
/// resumed from a prefix-hit checkpoint, which then sits in the ring). `ring[0..n_ring]` are
/// the request's checkpoints, oldest first, each holding one reference.
pub const StateTable = struct { ring: []Ckpt, n_ring: u32, live: u32 };

/// The units the plan in flight names for one request's per_seq group: set by the scheduler
/// at plan (allocState), consumed at commit (keepRows) or by freeBlocks. The model reads
/// `read`, writes the state after tail row j into `write[j]` (write[0] = after the last history
/// row), and the state after row `ckpt_row` into `ckpt.id`. SCRATCH (the null unit 0) marks
/// a write nobody keeps; `write[0] == 0` means nothing is pending.
pub const Pending = struct { read: u32, write: []u32, ckpt: Ckpt, ckpt_row: u32 };

/// ckpt_row when the step writes no checkpoint (its ckpt is SCRATCH): no row matches.
pub const no_row: u32 = std.math.maxInt(u32);

/// Checkpoints a per_seq group keeps per request: its window, 0 when it never checkpoints.
pub fn nCheckpoints(group: GroupSpec) u32 {
    assert(group.kind == .per_seq);
    if (group.stride == 0) return 0;
    const n = window(group);
    assert(n >= 1);
    return n;
}

/// Tokens one block of a per_token group covers: the group's prefix-cache grain.
pub fn tokensPerBlock(group: GroupSpec) u32 {
    assert(group.kind == .per_token);
    assert(group.stride > 0 and group.block_size > 0);
    return group.stride * group.block_size;
}

/// Sliding window of a per_token group, 0 when it keeps everything. Rows older than the last
/// `window` tokens are freed as the request advances; the table keeps its logical row positions
/// with 0 (the null block) in the holes (vLLM SlidingWindowManager).
pub fn window(group: GroupSpec) u32 {
    return switch (group.retention) {
        .all => 0,
        .window => |w| w.w,
    };
}

pub const BlockTable = struct {
    ids: []u32,
    n: u32,
};

pub const Config = struct {
    max_requests: u32,
    max_seq_len: u32,
    groups: []const GroupSpec,
    /// Kmax: the most extra rows (caller-filled, e.g. drafts) a decode-shaped entry may carry
    /// after its history row; 0 = none. Sizes the per_seq write units (1 + Kmax) and the table
    /// rows past max_seq_len an extra row can reach.
    max_extra: u32 = 0,
};

pub const State = enum {
    waiting,
    running,
    finished_eos,
    finished_length,
    cancelled,
    /// Appended (additive-only, see include/kelpie.h): the request's grammar matcher rejected
    /// the sampled token (kelpie-engine/kelpie_engine/core.py's `_accept_grammar_token` / grammar_dead_end
    /// finish reason -- ops.sample emits token 0 for an all-masked mask row rather than a
    /// fallback sample, and this is how that dead end is reported distinctly from
    /// finished_eos/finished_length). c_api.zig's commit path closes the request with this state
    /// when xgrammar_matcher_accept returns false for the token just committed.
    grammar_dead_end,
};

/// A request's sampling, as the sampler reads it. Built only by `samplingParams`, which applies
/// the T=0 rule, so nothing downstream ever sees a temperature of 0.
pub const SamplingParams = struct {
    max_new_tokens: u32,
    temperature: f32,
    /// Sample from the top_k most likely tokens; 0 = the whole vocabulary, 1 = greedy (what
    /// the T=0 rule sets, overriding the caller's top_k).
    top_k: u32,
};

/// Below this a temperature means greedy (sglang's SAMPLING_EPS). The one writer of the value:
/// Python reads it over the ABI (kelpie_sampling_eps), never restates it.
pub const sampling_eps: f32 = 1e-6;

/// A temperature a caller may submit: finite and >= 0. A negative, NaN or infinite one is a
/// caller error; the C boundary refuses it and the inbox parser refuses it on a follower.
pub fn validTemperature(temperature: f32) bool {
    return temperature >= 0 and std.math.isFinite(temperature);
}

/// A top_k a caller may submit: 0 (off) or at most the vocabulary. vocab_size 0 = the engine
/// does not know its vocabulary, so any top_k passes (the sampler clamps to what it has).
pub fn validTopK(top_k: u32, vocab_size: u32) bool {
    return vocab_size == 0 or top_k <= vocab_size;
}

/// The T=0 rule (sglang-jax sampling_params.py:77): a temperature below sampling_eps becomes
/// temperature 1, top_k 1 -- greedy expressed as a sample from one token, so the sampler never
/// divides by 0 and has no greedy branch. It overrides the caller's top_k. Anything else keeps
/// the caller's temperature and top_k (0 = the whole vocabulary). Applied exactly once, here, at
/// the submit every caller passes through; NOT idempotent (the rewritten 1.0 would read as a
/// real temperature), so never re-derive params from params.
pub fn samplingParams(max_new_tokens: u32, temperature: f32, top_k: u32) SamplingParams {
    assert(validTemperature(temperature));
    if (temperature < sampling_eps) return .{ .max_new_tokens = max_new_tokens, .temperature = 1, .top_k = 1 };
    return .{ .max_new_tokens = max_new_tokens, .temperature = temperature, .top_k = top_k };
}

/// Extra end-of-turn ids beyond the scheduler's single `eos_token` (a chat format's stop set,
/// e.g. gpt-oss <|call|>). Fixed capacity: callers with more stop ids than this must reject at
/// their own boundary (kelpie-engine asserts `len(stop_token_ids) <= max_stop_tokens`).
pub const max_stop_tokens = 8;

pub const Sequence = struct {
    tokens: []u32,
    n_prompt: u32,
    n: u32,
    n_computed: u32,
};

pub const Request = struct {
    id: u32,
    state: State,
    params: SamplingParams,
    seq: Sequence,
    /// Per group; a per_seq group's table is empty (its units live in `state`).
    tables: []BlockTable,
    /// Per group; a per_token group's entry is empty (ring of length 0, live 0).
    units: []StateTable,
    /// Per group; see Pending. Only per_seq entries are ever set.
    pending: []Pending,
    n_polled: u32,
    n_preemptions: u32,
    /// Content hash of the request's multimodal inputs (0 = text only). Two prompts with identical
    /// placeholder token ids but different images must never share KV blocks: prefix.zig folds
    /// this into the chain hash of every block from the one containing `mm_start` on (fold with 0
    /// is the identity, so text-only requests hash as before). Python computes it (sha256 of the
    /// image bytes, truncated); the core stores, folds and echoes it.
    mm_hash: u64,
    /// Prompt position of the first placeholder token (meaningful iff mm_hash != 0).
    mm_start: u32,
    /// Extra stop ids for this request (commitEntry checks these alongside the scheduler's
    /// eos_token); stop_tokens[0..n_stop] are the live ones.
    stop_tokens: [max_stop_tokens]u32,
    n_stop: u32,
    /// Filled by the scheduler over the request's life; complete once isFinished (docs/observability.md).
    event: events.RequestEvent,
    /// True between acquire and release. A released slot keeps its last state (for poll) but nothing else is valid.
    owned: bool,
    /// True from plan (schedule) until commit handles the entry. Cancel and poll never release a
    /// planned slot: the plan in flight still names it, so commit does (scheduler.cancel).
    planned: bool,
    /// Membership/reservation in the one not-yet-committed plan ahead of `planned`.
    planned_ahead: bool,
    /// Placeholder occupying the history/input position reserved for the older plan's sampled
    /// token (an entry of the plan in flight that emits: a decode, or a chunk that completes the
    /// prompt).
    pending_token: u32,
    /// Rows of the plan in flight that seq.n_computed already counts (scheduler.reserveAhead,
    /// as vLLM advances num_computed_tokens at schedule time). Nonzero only while an ahead plan
    /// exists; committed rows = seq.n_computed - n_in_flight. The oldest commit zeroes it.
    n_in_flight: u32,
    /// Extra rows the last commit asked for on this request's next decode-shaped entry
    /// (KelpieCommit.next_extra); 0 = none. Every commit rewrites it; finish, cancel and preempt
    /// clear it.
    next_extra: u32,
};

pub fn nWork(seq: *const Sequence) u32 {
    assert(seq.n_computed < seq.n);
    return seq.n - seq.n_computed;
}

pub fn nGenerated(seq: *const Sequence) u32 {
    assert(seq.n_prompt <= seq.n);
    return seq.n - seq.n_prompt;
}

/// Logical table rows of a per_token group a request with n_tokens computed occupies (holes
/// included).
pub fn rowsFor(group: GroupSpec, n_tokens: u32) u32 {
    assert(group.kind == .per_token);
    assert(group.block_size > 0 and group.stride > 0);
    const units = (n_tokens + group.stride - 1) / group.stride;
    return (units + group.block_size - 1) / group.block_size;
}

/// Units a request with n_tokens computed holds in steady state. per_token: rows, capped for a
/// window group at the rows that can cover the last `window` tokens plus the one being
/// written. per_seq: the live unit, the checkpoints the ring keeps, and one write unit per
/// extra row a step may add.
pub fn blocksFor(group: GroupSpec, n_tokens: u32, max_extra: u32) u32 {
    if (group.kind == .per_seq) {
        if (n_tokens == 0) return 0;
        const n_ckpt = if (group.stride == 0) 0 else @min(nCheckpoints(group), n_tokens / group.stride);
        return 1 + n_ckpt + max_extra;
    }
    const rows = rowsFor(group, n_tokens);
    if (window(group) == 0) return rows;
    return @min(rows, windowRows(group, max_extra));
}

/// ceil((W - 1) / block_size) + in-flight rows: the decode-time PLATEAU of a window group
/// (vLLM SlidingWindowSpec.max_admission_blocks_per_request). Two constants live near each
/// other and must not be confused (docs/brief-zig-cache-spike-2-4.md item 3):
///
///   - this one, admission: how many rows a decoding request may hold at once. It includes the
///     row(s) being written, so it carries the `+ ceil((1 + K) / block_size)` in-flight term --
///     with K extra rows a step writes 1 + K tokens, which can straddle a block boundary.
///   - prefix.matchWindow's `ceil((W - 1) / block_size)`, the MATCH rule: how many cached
///     blocks ending at a candidate boundary make it resumable. No in-flight term: nothing is
///     being written during a match.
///
/// `w` here is already W + K: Python folds the lookahead into group_windows[g]
/// (kelpie_models.groups.caches, `Window(window + max_spec_tokens)`), so the retained-token
/// half of K needs nothing from the core.
pub fn windowRows(group: GroupSpec, max_extra: u32) u32 {
    const w = window(group);
    assert(w > 0 and group.stride == 1);
    const in_flight = (1 + max_extra + group.block_size - 1) / group.block_size;
    return (w - 1 + group.block_size - 1) / group.block_size + in_flight;
}

/// First table row still needed once n_computed tokens are in the cache: the next query (at
/// position n_computed) reads keys >= n_computed - window + 1; whole rows below that are gone
/// (vLLM SlidingWindowManager.get_num_skipped_tokens).
pub fn firstLiveRow(group: GroupSpec, n_computed: u32) u32 {
    const w = window(group);
    if (w == 0 or n_computed < w) return 0;
    assert(group.stride == 1);
    return (n_computed - w + 1) / group.block_size;
}

/// Table capacity of a per_token group: rowsFor out to max_seq_len plus the extra rows a last
/// decode entry can carry past it. A per_seq group has no table (StateTable instead).
pub fn capacityRows(group: GroupSpec, max_seq_len: u32, max_extra: u32) u32 {
    return switch (group.kind) {
        .per_token => rowsFor(group, max_seq_len + max_extra),
        .per_seq => 0,
    };
}

fn blocksPerRequest(cfg: Config) u32 {
    assert(cfg.groups.len > 0);
    var total: u32 = 0;
    for (cfg.groups) |group| total += capacityRows(group, cfg.max_seq_len, cfg.max_extra);
    return total;
}

fn checkpointsPerRequest(cfg: Config) u32 {
    var total: u32 = 0;
    for (cfg.groups) |group| {
        if (group.kind == .per_seq) total += nCheckpoints(group);
    }
    return total;
}

fn nSeqGroups(cfg: Config) u32 {
    var n: u32 = 0;
    for (cfg.groups) |group| n += @intFromBool(group.kind == .per_seq);
    return n;
}

/// Tables and state are empty: the caller freed every unit first (scheduler.freeBlocks).
fn resetTables(req: *Request) void {
    assert(req.tables.len > 0);
    for (req.tables) |*table| table.n = 0;
    for (req.units, req.pending) |*st, *pending| {
        assert(st.live == 0 and st.n_ring == 0);
        assert(!isPending(pending));
    }
    assert(req.tables[0].n == 0);
}

/// Does the plan in flight name units of this per_seq group for the request?
pub fn isPending(pending: *const Pending) bool {
    return pending.write.len > 0 and pending.write[0] != 0;
}

/// Leaves a per_seq group with nothing pending (every write SCRATCH, no checkpoint).
pub fn clearPending(pending: *Pending) void {
    pending.read = 0;
    @memset(pending.write, 0);
    pending.ckpt = .{ .id = 0, .pos = 0 };
    pending.ckpt_row = no_row;
}

pub fn advance(seq: *Sequence, n: u32) void {
    assert(n > 0);
    assert(n <= nWork(seq));
    seq.n_computed += n;
    assert(seq.n_computed <= seq.n);
}

/// A token sampled from a partial prefill chunk must be discarded; appending it would land it inside the prompt.
pub fn appendToken(seq: *Sequence, token: u32) void {
    assert(seq.n_computed == seq.n);
    assert(seq.n < seq.tokens.len);
    seq.tokens[seq.n] = token;
    seq.n += 1;
    assert(seq.n_computed == seq.n - 1);
}

/// Appends a token this step already computed, at an extra row the caller vouched for (an
/// accepted draft), so `n_computed` moves with it. (`appendToken` leaves n_computed one behind,
/// because the sampled token's KV is written by the NEXT step; this one's was written by this
/// step.) Its row is already in the tables -- the entry covered 1 + n_extra rows.
pub fn appendComputed(seq: *Sequence, token: u32) void {
    assert(seq.n_computed == seq.n - 1);
    assert(seq.n < seq.tokens.len);
    seq.tokens[seq.n] = token;
    seq.n += 1;
    seq.n_computed += 1;
    assert(seq.n_computed == seq.n - 1);
}

/// History is kept; the whole of it is re-prefilled on readmission.
pub fn preempt(req: *Request) void {
    assert(req.state == .running);
    req.state = .waiting;
    req.seq.n_computed = 0;
    req.next_extra = 0;
    resetTables(req);
    req.n_preemptions += 1;
}

pub fn isFinished(req: *const Request) bool {
    return switch (req.state) {
        .finished_eos, .finished_length, .cancelled, .grammar_dead_end => true,
        .waiting, .running => false,
    };
}

/// Linear scan of the request's stop set (usually 1-3 ids; max_stop_tokens caps it at 8).
pub fn isStopToken(req: *const Request, token: u32) bool {
    for (req.stop_tokens[0..req.n_stop]) |id| {
        if (id == token) return true;
    }
    return false;
}

pub const Pool = struct {
    cfg: Config,
    requests: []Request,
    free_ids: []u32,
    n_free: u32,
    tokens_storage: []u32,
    block_storage: []u32,
    tables_storage: []BlockTable,
    state_storage: []StateTable,
    pending_storage: []Pending,
    ring_storage: []Ckpt,
    write_storage: []u32,

    pub fn init(allocator: std.mem.Allocator, cfg: Config) !Pool {
        assert(cfg.max_requests > 0);
        assert(cfg.max_seq_len > 0);
        const blocks_per_request = blocksPerRequest(cfg);

        const requests = try allocator.alloc(Request, cfg.max_requests);
        errdefer allocator.free(requests);
        const free_ids = try allocator.alloc(u32, cfg.max_requests);
        errdefer allocator.free(free_ids);
        const tokens_per_req = cfg.max_seq_len;
        const tokens_storage = try allocator.alloc(u32, cfg.max_requests * tokens_per_req);
        errdefer allocator.free(tokens_storage);
        const block_storage = try allocator.alloc(u32, cfg.max_requests * blocks_per_request);
        errdefer allocator.free(block_storage);
        const tables_storage = try allocator.alloc(BlockTable, cfg.max_requests * cfg.groups.len);
        errdefer allocator.free(tables_storage);
        const state_storage = try allocator.alloc(StateTable, cfg.max_requests * cfg.groups.len);
        errdefer allocator.free(state_storage);
        const pending_storage = try allocator.alloc(Pending, cfg.max_requests * cfg.groups.len);
        errdefer allocator.free(pending_storage);
        const ring_storage = try allocator.alloc(Ckpt, cfg.max_requests * checkpointsPerRequest(cfg));
        errdefer allocator.free(ring_storage);
        // One write unit per tail row (1 + K) for each per_seq group.
        const write_width = 1 + cfg.max_extra;
        const write_storage = try allocator.alloc(u32, cfg.max_requests * nSeqGroups(cfg) * write_width);
        errdefer allocator.free(write_storage);

        var block_cursor: usize = 0;
        var ring_cursor: usize = 0;
        var write_cursor: usize = 0;
        for (requests, 0..) |*req, i| {
            const id: u32 = @intCast(i);
            const tables = tables_storage[i * cfg.groups.len ..][0..cfg.groups.len];
            for (tables, cfg.groups) |*table, group| {
                const capacity = capacityRows(group, cfg.max_seq_len, cfg.max_extra);
                table.* = .{ .ids = block_storage[block_cursor..][0..capacity], .n = 0 };
                block_cursor += capacity;
            }
            const state = state_storage[i * cfg.groups.len ..][0..cfg.groups.len];
            const pending = pending_storage[i * cfg.groups.len ..][0..cfg.groups.len];
            for (state, pending, cfg.groups) |*st, *pend, group| {
                const n_ring: u32 = if (group.kind == .per_seq) nCheckpoints(group) else 0;
                const n_write: u32 = if (group.kind == .per_seq) write_width else 0;
                st.* = .{ .ring = ring_storage[ring_cursor..][0..n_ring], .n_ring = 0, .live = 0 };
                pend.* = .{ .read = 0, .write = write_storage[write_cursor..][0..n_write], .ckpt = .{ .id = 0, .pos = 0 }, .ckpt_row = no_row };
                clearPending(pend);
                ring_cursor += n_ring;
                write_cursor += n_write;
            }
            req.* = .{
                .id = id,
                .state = .cancelled,
                .params = samplingParams(0, 0, 0),
                .seq = .{
                    .tokens = tokens_storage[i * tokens_per_req ..][0..tokens_per_req],
                    .n_prompt = 0,
                    .n = 0,
                    .n_computed = 0,
                },
                .tables = tables,
                .units = state,
                .pending = pending,
                .n_polled = 0,
                .n_preemptions = 0,
                .mm_hash = 0,
                .mm_start = 0,
                .stop_tokens = std.mem.zeroes([max_stop_tokens]u32),
                .n_stop = 0,
                .event = std.mem.zeroes(events.RequestEvent),
                .owned = false,
                .planned = false,
                .planned_ahead = false,
                .pending_token = 0,
                .n_in_flight = 0,
                .next_extra = 0,
            };
            free_ids[i] = id;
        }
        assert(block_cursor == block_storage.len);
        assert(ring_cursor == ring_storage.len and write_cursor == write_storage.len);
        return .{
            .cfg = cfg,
            .requests = requests,
            .free_ids = free_ids,
            .n_free = cfg.max_requests,
            .tokens_storage = tokens_storage,
            .block_storage = block_storage,
            .tables_storage = tables_storage,
            .state_storage = state_storage,
            .pending_storage = pending_storage,
            .ring_storage = ring_storage,
            .write_storage = write_storage,
        };
    }

    pub fn deinit(pool: *Pool, allocator: std.mem.Allocator) void {
        allocator.free(pool.write_storage);
        allocator.free(pool.ring_storage);
        allocator.free(pool.pending_storage);
        allocator.free(pool.state_storage);
        allocator.free(pool.tables_storage);
        allocator.free(pool.block_storage);
        allocator.free(pool.tokens_storage);
        allocator.free(pool.free_ids);
        allocator.free(pool.requests);
        pool.* = undefined;
    }
};

pub const AcquireError = error{ Full, TooLong };

pub fn acquire(pool: *Pool, prompt: []const u32, params: SamplingParams) AcquireError!*Request {
    return acquireMm(pool, prompt, params, .{ .hash = 0, .start = 0 });
}

/// Multimodal identity of a request, as the prefix index folds it: see Request.mm_hash.
pub const Mm = struct { hash: u64, start: u32 };

pub fn acquireMm(pool: *Pool, prompt: []const u32, params: SamplingParams, mm: Mm) AcquireError!*Request {
    return acquireMmStop(pool, prompt, params, mm, &.{});
}

/// acquireMm with a per-request stop token set (request.Request.stop_tokens); stop_ids.len must
/// be <= max_stop_tokens (the C boundary asserts this before it reaches here).
pub fn acquireMmStop(pool: *Pool, prompt: []const u32, params: SamplingParams, mm: Mm, stop_ids: []const u32) AcquireError!*Request {
    assert(prompt.len > 0);
    assert(stop_ids.len <= max_stop_tokens);
    if (pool.n_free == 0) return error.Full;
    if (prompt.len + params.max_new_tokens > pool.cfg.max_seq_len) return error.TooLong;

    pool.n_free -= 1;
    const req = &pool.requests[pool.free_ids[pool.n_free]];
    fill(req, prompt, params, mm, stop_ids);
    return req;
}

/// acquireMmStop into a slot the caller chose (docs/design-multigpu.md 2.3): the edge reserved
/// `id` when the submit was pushed, and every rank applies the submit op here. The slot must be
/// free -- the reservation guarantees it (an op still in the inbox is the only way a free slot
/// becomes owned), so a taken slot is a bug, not an error.
pub fn acquireAt(pool: *Pool, id: u32, prompt: []const u32, params: SamplingParams, mm: Mm, stop_ids: []const u32) *Request {
    assert(prompt.len > 0);
    assert(stop_ids.len <= max_stop_tokens);
    assert(id < pool.cfg.max_requests);
    assert(prompt.len + params.max_new_tokens <= pool.cfg.max_seq_len);
    // Remove id from the free list, keeping the order of the rest (acquire's LIFO stays LIFO).
    const at = std.mem.indexOfScalar(u32, pool.free_ids[0..pool.n_free], id) orelse unreachable;
    std.mem.copyForwards(u32, pool.free_ids[at .. pool.n_free - 1], pool.free_ids[at + 1 .. pool.n_free]);
    pool.n_free -= 1;
    const req = &pool.requests[id];
    fill(req, prompt, params, mm, stop_ids);
    return req;
}

fn fill(req: *Request, prompt: []const u32, params: SamplingParams, mm: Mm, stop_ids: []const u32) void {
    assert(isFinished(req));
    assert(!req.owned);

    @memcpy(req.seq.tokens[0..prompt.len], prompt);
    req.state = .waiting;
    // Only samplingParams builds params: the T=0 rule has run, so temperature is never below eps.
    assert(params.temperature >= sampling_eps);
    req.params = params;
    req.seq.n_prompt = @intCast(prompt.len);
    req.seq.n = @intCast(prompt.len);
    req.seq.n_computed = 0;
    req.next_extra = 0;
    resetTables(req);
    req.n_polled = 0;
    req.n_preemptions = 0;
    req.mm_hash = mm.hash;
    req.mm_start = mm.start;
    @memcpy(req.stop_tokens[0..stop_ids.len], stop_ids);
    req.n_stop = @intCast(stop_ids.len);
    req.event = std.mem.zeroes(events.RequestEvent);
    req.owned = true;
    assert(!req.planned);

    assert(nWork(&req.seq) == prompt.len);
    assert(req.mm_hash == mm.hash);
}

pub fn release(pool: *Pool, req: *Request) void {
    assert(isFinished(req));
    assert(req.owned);
    assert(!req.planned);
    for (req.tables) |table| assert(table.n == 0);
    for (req.units, req.pending) |st, *pending| assert(st.live == 0 and st.n_ring == 0 and !isPending(pending));
    assert(pool.n_free < pool.cfg.max_requests);
    pool.free_ids[pool.n_free] = req.id;
    pool.n_free += 1;
    req.owned = false;
}

// ---- tests -------------------------------------------------------------------------------

const test_groups = [_]GroupSpec{.{ .kind = .per_token, .block_size = 4 }};
const test_cfg = Config{ .max_requests = 2, .max_seq_len = 32, .groups = &test_groups };

test "acquire and release respect pool bounds" {
    var pool = try Pool.init(std.testing.allocator, test_cfg);
    defer pool.deinit(std.testing.allocator);

    try std.testing.expectError(error.TooLong, acquire(&pool, &.{1}, samplingParams(32, 1.0, 0)));
    const a = try acquire(&pool, &.{1}, samplingParams(1, 1.0, 0));
    _ = try acquire(&pool, &.{1}, samplingParams(1, 1.0, 0));
    try std.testing.expectError(error.Full, acquire(&pool, &.{1}, samplingParams(1, 1.0, 0)));
    a.state = .cancelled;
    release(&pool, a);
    _ = try acquire(&pool, &.{1}, samplingParams(1, 1.0, 0));
}

test "the T=0 rule: below sampling_eps is temperature 1 / top_k 1, overriding the caller top_k" {
    const zero = samplingParams(4, 0, 0);
    try std.testing.expectEqual(@as(f32, 1), zero.temperature);
    try std.testing.expectEqual(@as(u32, 1), zero.top_k);
    try std.testing.expectEqual(@as(u32, 4), zero.max_new_tokens);
    const tiny = samplingParams(4, 1e-7, 0);
    try std.testing.expectEqual(@as(f32, 1), tiny.temperature);
    try std.testing.expectEqual(@as(u32, 1), tiny.top_k);
    const warm = samplingParams(4, 0.7, 0);
    try std.testing.expectEqual(@as(f32, 0.7), warm.temperature);
    try std.testing.expectEqual(@as(u32, 0), warm.top_k);
    const at_eps = samplingParams(4, sampling_eps, 0);
    try std.testing.expectEqual(@as(u32, 0), at_eps.top_k); // eps itself samples (strict <, as sglang)
    // A caller's top_k survives a real temperature and is overridden by the T=0 rule.
    try std.testing.expectEqual(@as(u32, 5), samplingParams(4, 0.7, 5).top_k);
    try std.testing.expectEqual(@as(u32, 1), samplingParams(4, 0, 5).top_k);
    try std.testing.expectEqual(@as(f32, 1), samplingParams(4, 0, 5).temperature);
    try std.testing.expect(validTopK(100, 100) and !validTopK(101, 100) and validTopK(1 << 30, 0));
    try std.testing.expect(!validTemperature(-0.5));
    try std.testing.expect(!validTemperature(std.math.nan(f32)));
    try std.testing.expect(!validTemperature(std.math.inf(f32)));
    try std.testing.expect(validTemperature(0));
}

test "window group: blocksFor plateaus, firstLiveRow slides" {
    const g = GroupSpec{ .kind = .per_token, .block_size = 4, .retention = .{ .window = .{ .w = 8, .cacheable = true } } };
    try std.testing.expectEqual(3, windowRows(g, 0));
    try std.testing.expectEqual(1, blocksFor(g, 4, 0));
    try std.testing.expectEqual(2, blocksFor(g, 8, 0));
    try std.testing.expectEqual(3, blocksFor(g, 9, 0));
    try std.testing.expectEqual(3, blocksFor(g, 100, 0));
    try std.testing.expectEqual(25, rowsFor(g, 100));
    try std.testing.expectEqual(0, firstLiveRow(g, 7));
    try std.testing.expectEqual(0, firstLiveRow(g, 10)); // keys >= 3 needed: row 0 still live
    try std.testing.expectEqual(1, firstLiveRow(g, 11)); // keys >= 4: row 0 gone
    try std.testing.expectEqual(1, firstLiveRow(g, 14));
    try std.testing.expectEqual(2, firstLiveRow(g, 15));
}

test "stride group: a block spans stride * block_size tokens" {
    const g = GroupSpec{ .kind = .per_token, .block_size = 4, .stride = 4 };
    try std.testing.expectEqual(16, tokensPerBlock(g));
    try std.testing.expectEqual(0, rowsFor(g, 0));
    try std.testing.expectEqual(1, rowsFor(g, 1)); // unit 0 exists once its window opens
    try std.testing.expectEqual(1, rowsFor(g, 16));
    try std.testing.expectEqual(2, rowsFor(g, 17));
    try std.testing.expectEqual(7, rowsFor(g, 100)); // ceil(25 units / 4)
    try std.testing.expectEqual(rowsFor(g, 100), blocksFor(g, 100, 0));
    const g128 = GroupSpec{ .kind = .per_token, .block_size = 16, .stride = 128 };
    try std.testing.expectEqual(2, rowsFor(g128, 4096));
}

test "per_token groups get tables, per_seq groups get a checkpoint ring and 1 + K write units" {
    const groups = [_]GroupSpec{
        .{ .kind = .per_token, .block_size = 4 },
        .{ .kind = .per_seq, .block_size = 0, .stride = 0 }, // S = 0: never checkpoint
        .{ .kind = .per_seq, .block_size = 0, .stride = 8, .retention = .{ .window = .{ .w = 3, .cacheable = true } } },
    };
    const cfg = Config{ .max_requests = 2, .max_seq_len = 30, .groups = &groups, .max_extra = 2 };
    var pool = try Pool.init(std.testing.allocator, cfg);
    defer pool.deinit(std.testing.allocator);

    for (pool.requests) |req| {
        try std.testing.expectEqual(3, req.tables.len);
        try std.testing.expectEqual(8, req.tables[0].ids.len); // rowsFor(30 + Kmax)
        try std.testing.expectEqual(0, req.tables[1].ids.len);
        try std.testing.expectEqual(0, req.tables[2].ids.len);
        try std.testing.expectEqual(0, req.units[0].ring.len);
        try std.testing.expectEqual(0, req.units[1].ring.len);
        try std.testing.expectEqual(3, req.units[2].ring.len);
        try std.testing.expectEqual(0, req.pending[0].write.len);
        try std.testing.expectEqual(3, req.pending[1].write.len);
        try std.testing.expect(!isPending(&req.pending[2]));
    }
    try std.testing.expectEqual(16, pool.block_storage.len);
    try std.testing.expectEqual(6, pool.ring_storage.len);
    try std.testing.expectEqual(12, pool.write_storage.len);
}
