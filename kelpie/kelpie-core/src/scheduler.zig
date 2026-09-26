//! One step = plan (build the batch, allocate its KV blocks) then commit (apply the sampled tokens).
//! Python runs the forward between the two. submit/cancel/poll are the product-facing edges.

const std = @import("std");
const assert = std.debug.assert;
const request = @import("request.zig");
const kv_pool = @import("kv_pool.zig");
const prefix = @import("prefix.zig");
const events = @import("events.zig");
const buckets = @import("buckets.zig");

pub const Order = enum { running_first, waiting_first };
pub const ServiceState = enum { serving, draining };
/// ExceedsKvPool: the request's worst case (worstSlabs) is more slabs than the pool has, so it
/// could never finish even alone; admitting it would end in a stall.
pub const SubmitError = request.AcquireError || error{ Draining, ExceedsKvPool };

pub const Config = struct {
    max_batch_tokens: u32,
    max_batch_reqs: u32,
    reserve_ratio: f32,
    order: Order,
    eos_token: u32,
    /// Runtime knob: match prompts against cached blocks at admission and publish full blocks after commit.
    prefix_cache: bool = true,
    /// Startup protocol choice (tier 2): permit exactly one plan ahead of the oldest commit.
    overlap: bool = false,
};

/// docs/design-rules.md "Config tiers": 0 live (read each step) / 1 recapture / 2 drain+realloc / 3 program.
pub const Tier = enum(u8) { live, recapture, realloc, program };

/// A live-config change. It travels as an inbox op (c_api.zig, inputs.zig) and applyKnob runs it at
/// the step boundary before a plan, so a knob takes effect at exactly one step boundary. Every
/// field's tier is a comptime tag (`tier`); all are live today.
pub const Knob = union(enum) {
    order: Order,
    reserve_ratio: f32,
    max_batch_tokens: u32,
    max_batch_reqs: u32,
    prefix_cache: bool,

    pub fn tier(comptime tag: std.meta.Tag(Knob)) Tier {
        return switch (tag) {
            .order, .reserve_ratio, .prefix_cache => .live,
            // Changing the token budget moves the bucket ladder (recapture) once programs are compiled;
            // there are none yet, so it is live for now.
            .max_batch_tokens => .live,
            .max_batch_reqs => .live,
        };
    }
};

pub const KnobError = error{Invalid};

/// What a planned chunk is. Decided in `schedule` by position, never by n_work: a one-token prompt's
/// first chunk and a chunked prefill's one-token tail are prefills (docs/spec-decode-design.md 7.1).
pub const Kind = enum(u32) { prefill, decode };

/// One planned entry (docs/design-core-option2.md 2.1): `n_work` history rows (tokens the core
/// owns, at [seq_start, seq_start + n_work)) then `n_extra` extra rows right after them, whose
/// input_ids are no_token -- the caller fills them. Tail row j is row n_work - 1 + j,
/// j in [0, n_extra]. Extra rows only ever follow a decode-shaped history row (extraFor).
pub const Entry = struct { req_id: u32, n_work: u32, n_extra: u32, kind: Kind };

/// What a commit applies, per plan entry i in plan order (docs/design-core-option2.md 2.3,
/// section 8 item 2): the entry keeps tokens[i * stride ..][0..n_tokens[i]] -- "tail rows
/// 0..n-1 were valid": the tokens at extra rows 1..n-1 (which the caller put there), then the
/// token after tail row n-1 -- and asks for next_extra[i] extra rows on its next decode-shaped
/// entry. Empty n_tokens = all 1; empty next_extra = all 0.
pub const Commit = struct {
    tokens: []const u32,
    stride: u32,
    n_tokens: []const u32,
    next_extra: []const u32,
};

/// input_ids of an extra row: the caller fills it. Not 0, which is a real vocab id.
pub const no_token: u32 = std.math.maxInt(u32);

/// Static buffers sized in init; valid from plan until the next plan. Decode entries come first.
pub const Plan = struct {
    n_reqs: u32,
    n_tokens: u32,
    max_blocks_per_req: u32,
    entries: []Entry,
    input_ids: []u32,
    positions: []u32,
    query_start_loc: []u32,
    seq_lens: []u32,
    temperatures: []f32,
    /// Per entry: the request's top_k (request.SamplingParams.top_k): 1 = greedy, 0 = whole vocab.
    top_ks: []u32,
    /// Per entry: the request's multimodal content hash (0 = text only). Lets Python locate which
    /// planned entries carry embedding overrides without a side channel keyed on req_id alone.
    mm_hashes: []u64,
    slot_mapping: [][]u32,
    block_tables: [][]u32,
    /// Per entry: tokens already in context when the step runs (n_computed at plan). The
    /// entry's rows sit at positions seq_start, seq_start + 1, ...; 0 = no prior context.
    seq_start: []u32,
    /// Per entry: 1 iff the chunk reaches the end of the history, so commit keeps its tokens
    /// (a partial prefill chunk's sample is discarded).
    emits: []u8,
    /// Per group: the per_seq state indices of every entry (Pending, as the model sees it);
    /// empty slices for a per_token group, whose rows go through slot_mapping instead.
    state: []StateIdx,
    /// Columns per entry of state[g].write: one per tail row, 1 + Kmax (request.Config.max_extra).
    write_width: u32,
    /// Per group: ZERO(g), the always-zero unit a fresh request reads; 0 for a per_token group.
    zero_units: []const u32,
};

/// One per_seq group's indices for a plan, entry-major (docs/design-core-option2.md 2.2):
/// read[i] the unit holding the state before the entry's first row; write[i * write_width + j]
/// where the state after tail row j goes (j = 0: after the last history row; SCRATCH past the
/// entry's extra rows); ckpt[i] where the state after row ckpt_row[i] goes (SCRATCH and
/// request.no_row when the step writes no checkpoint). ckpt_row counts from the entry's first
/// row.
pub const StateIdx = struct { read: []u32, write: []u32, ckpt: []u32, ckpt_row: []u32 };

/// SCRATCH: unit 0 of every per_seq group (kv_pool.null_block). Writable, never read: a write
/// nobody keeps lands here.
pub const scratch_unit: u32 = kv_pool.null_block;

/// One plan buffer and everything that belongs to it. These five moved together through five
/// `std.mem.swap` calls before, except `slots`/`tables`, which did not -- so after an odd number of
/// swaps `plan.slot_mapping` pointed into the *other* arena's storage. Bundling them makes that
/// unrepresentable: a plan and the memory it points at are one value with one owner.
pub const PlanArena = struct {
    plan: Plan,
    /// Entries as `schedule` appends them, before `emitPlan` orders them decode-first into `plan`.
    sched: []Entry,
    /// Accumulates from the end of one commit to the end of the next; published in `publishStep`.
    building: events.StepEvent,
    /// Backing storage for plan.slot_mapping / plan.block_tables / plan.state (per-group
    /// slices into these).
    slots: []u32,
    tables: []u32,
    state_buf: []u32,
};

/// A plan that scheduled nothing although work is pending, with no plan in flight and nobody
/// preempted: nothing inside the scheduler will change before the next plan, so the next plan is
/// the same, forever (only a cancel or a knob can help). `req_id` is the request that could not
/// go -- the first runner, else the waiting head -- with its next chunk and that chunk's slabs.
/// n_work == 0 means the budget is below the chunk grain.
pub const Stall = struct { req_id: u32, n_work: u32, need_slabs: u32, free_slabs: u32 };

pub const PollResult = struct { n_new: u32, finished: bool, state: request.State };

pub const Scheduler = struct {
    cfg: Config,
    reqs: *request.Pool,
    kv: *kv_pool.Pool,
    running: []u32,
    n_running: u32,
    /// Index into running where the next planRunning starts: a runner skipped for lack of batch
    /// room (max_batch_reqs / max_batch_tokens below the runner count) goes first next step.
    rr: u32,
    /// Scratch: this step's runners in visit order (running rotated by rr).
    order: []u32,
    waiting: []u32,
    waiting_head: u32,
    n_waiting: u32,
    n_sched: u32,
    /// The two plan buffers. Everything that belongs to one plan lives in one arena, so promoting
    /// a plan is an index change, never a field-by-field swap (which silently left `slot_storage`
    /// paired with the *other* arena's `Plan` -- see PlanArena).
    arenas: [2]PlanArena,
    /// The arena holding the oldest uncommitted plan. `live()`.
    cur: u1,
    /// Plans planned but not yet committed: 0, 1, or 2. Replaces the three booleans
    /// (`planned` = n_outstanding > 0, `has_ahead` = n_outstanding == 2). The arena `plan` is
    /// currently filling is `build()`; `building_ahead` is `n_outstanding == 1` inside plan().
    n_outstanding: u2,
    /// True only for the duration of a plan() call that is building the second (ahead) plan.
    building_ahead: bool,
    clock: events.Clock,
    step: u64,
    /// wyhash over the live cfg, recomputed by applyKnob and published in every StepEvent.
    config_hash: u64,
    event: events.StepEvent,
    state: ServiceState,
    /// Set by every plan not built ahead; see Stall.
    stall: ?Stall,
    /// Per group: ZERO(g) for a per_seq group, allocated at init and held forever (never a
    /// write target, so it stays as the model zeroed it); 0 for a per_token group.
    zero_units: []u32,

    pub fn init(allocator: std.mem.Allocator, cfg: Config, reqs: *request.Pool, kv: *kv_pool.Pool) !Scheduler {
        assert(cfg.max_batch_tokens > 0);
        assert(cfg.max_batch_reqs > 0);
        const n_reqs = reqs.cfg.max_requests;
        const running = try allocator.alloc(u32, n_reqs);
        errdefer allocator.free(running);
        const waiting = try allocator.alloc(u32, n_reqs);
        errdefer allocator.free(waiting);
        const order = try allocator.alloc(u32, n_reqs);
        errdefer allocator.free(order);
        const groups = reqs.cfg.groups;
        const zero_units = try allocator.alloc(u32, groups.len);
        errdefer allocator.free(zero_units);
        for (groups, zero_units, 0..) |group, *zero, g| {
            zero.* = kv_pool.null_block;
            if (group.kind == .per_seq) kv_pool.allocate(kv, @intCast(g), zero[0..1]);
            // Overlap reserves a placeholder decode row ahead of the commit that fills the live
            // state it would read; per_seq state has no such placeholder.
            assert(!(group.kind == .per_seq and cfg.overlap));
        }
        var s = Scheduler{
            .cfg = cfg,
            .reqs = reqs,
            .kv = kv,
            .running = running,
            .n_running = 0,
            .rr = 0,
            .order = order,
            .waiting = waiting,
            .waiting_head = 0,
            .n_waiting = 0,
            .n_sched = 0,
            .arenas = undefined,
            .cur = 0,
            .n_outstanding = 0,
            .building_ahead = false,
            .clock = events.Clock.init(),
            .step = 0,
            .config_hash = hashConfig(&cfg),
            .event = std.mem.zeroes(events.StepEvent),
            .state = .serving,
            .stall = null,
            .zero_units = zero_units,
        };
        s.event.config_hash = s.config_hash; // so "changed" on the first step means a real set
        try initPlan(&s, allocator);
        assert(s.live().plan.slot_mapping.len == reqs.cfg.groups.len);
        return s;
    }

    /// The arena holding the oldest uncommitted plan: what `commit` applies to and what every
    /// external reader (`c_api.zig`) means by "the plan".
    pub fn live(s: *Scheduler) *PlanArena {
        return &s.arenas[s.cur];
    }

    /// The arena `plan` is filling right now. The same as `live()` unless we are building ahead,
    /// in which case it is the other one.
    fn build(s: *Scheduler) *PlanArena {
        return &s.arenas[s.cur ^ @intFromBool(s.building_ahead)];
    }

    /// The second, not-yet-live plan, or null when there is none. Public for the trace tests,
    /// which assert on both plans separately.
    pub fn ahead(s: *Scheduler) ?*PlanArena {
        if (s.n_outstanding < 2) return null;
        return &s.arenas[s.cur ^ 1];
    }

    /// A plan has been handed out and not yet committed.
    pub fn planned(s: *const Scheduler) bool {
        return s.n_outstanding > 0;
    }

    pub fn deinit(s: *Scheduler, allocator: std.mem.Allocator) void {
        for (&s.arenas) |*a| freeArena(allocator, a);
        allocator.free(s.zero_units);
        allocator.free(s.waiting);
        allocator.free(s.order);
        allocator.free(s.running);
        s.* = undefined;
    }
};

pub fn submit(s: *Scheduler, prompt: []const u32, params: request.SamplingParams) SubmitError!u32 {
    return submitMm(s, prompt, params, .{ .hash = 0, .start = 0 });
}

/// submit with a multimodal content hash; see request.Request.mm_hash.
pub fn submitMm(s: *Scheduler, prompt: []const u32, params: request.SamplingParams, mm: request.Mm) SubmitError!u32 {
    return submitMmStop(s, prompt, params, mm, &.{});
}

/// submitMm with a per-request stop token set; see request.Request.stop_tokens.
pub fn submitMmStop(s: *Scheduler, prompt: []const u32, params: request.SamplingParams, mm: request.Mm, stop_ids: []const u32) SubmitError!u32 {
    assert(prompt.len > 0);
    if (s.state == .draining) return error.Draining;
    // TooLong (acquire) is checked first: worstSlabs only means something within max_seq_len.
    const n_total = prompt.len + params.max_new_tokens;
    if (n_total <= s.reqs.cfg.max_seq_len and worstSlabs(s, @intCast(prompt.len), params.max_new_tokens) > s.kv.slabs.len) {
        return error.ExceedsKvPool;
    }
    const req = request.acquireMmStop(s.reqs, prompt, params, mm, stop_ids) catch |err| {
        if (err == error.Full) s.live().building.n_rejected_full += 1;
        return err;
    };
    req.event.request_id = req.id;
    req.event.t_arrival_ns = events.now(&s.clock);
    req.event.max_new = params.max_new_tokens;
    pushBackWaiting(s, req.id);
    assert(req.state == .waiting);
    return req.id;
}

/// A submit op applied at a step boundary (docs/design-multigpu.md 2.3): the edge already chose
/// `id` and stamped the arrival, and every rank lands the request in exactly that slot. No
/// Draining check -- planWaiting refuses admission while draining, so an op queued before a
/// drain simply waits -- and no Full (the reservation guarantees the slot). The caller re-checks
/// TooLong / ExceedsKvPool against the live config (c_api.zig applySubmit, section 8 S2).
pub fn submitAt(s: *Scheduler, id: u32, prompt: []const u32, params: request.SamplingParams, mm: request.Mm, stop_ids: []const u32, t_arrival_ns: u64) void {
    assert(prompt.len > 0);
    const req = request.acquireAt(s.reqs, id, prompt, params, mm, stop_ids);
    assert(req.id == id);
    req.event.request_id = req.id;
    req.event.t_arrival_ns = t_arrival_ns;
    req.event.max_new = params.max_new_tokens;
    pushBackWaiting(s, req.id);
    assert(req.state == .waiting);
}

/// A submit op that no longer fits the live config when it applies (docs/design-multigpu.md
/// section 8 S2): it closes cancelled at once -- on every rank, since the verdict reads only core
/// state -- and keeps its slot until the edge's release op, like any finished request.
pub fn rejectAt(s: *Scheduler, id: u32) void {
    const req = &s.reqs.requests[id];
    assert(req.owned and req.state == .waiting and !req.planned and !req.planned_ahead);
    removeWaiting(s, id);
    close(s, req, .cancelled);
    assert(request.isFinished(req));
}

pub fn enterDraining(s: *Scheduler) void {
    assert(s.state == .serving);
    assert(s.n_running <= s.reqs.cfg.max_requests);
    s.state = .draining;
}

pub fn leaveDraining(s: *Scheduler) void {
    assert(s.state == .draining and isDrained(s));
    s.state = .serving;
}

pub fn isDrained(s: *const Scheduler) bool {
    assert(s.n_running <= s.reqs.cfg.max_requests);
    return s.n_running == 0;
}

/// Frees blocks and releases the slot right away; unpolled tokens are dropped. A later poll on the
/// id reports finished+cancelled (unless the slot has been reacquired by a new submit).
/// A request that finished but was never polled is still owned: cancel releases it too (the HTTP
/// layer cancels on client disconnect without knowing whether the last step finished it).
/// Exception: a request named by the plan in flight keeps its slot until commit (so a submit in
/// between cannot land in a slot the plan still refers to); poll reports it cancelled meanwhile.
/// Cancelling twice is not allowed here; the C boundary makes it a no-op.
pub fn cancel(s: *Scheduler, req_id: u32) void {
    const req = &s.reqs.requests[req_id];
    assert(req.owned);
    switch (req.state) {
        .waiting => removeWaiting(s, req_id),
        .running => if (!req.planned_ahead) freeBlocks(s, req),
        .finished_eos, .finished_length, .grammar_dead_end => assert(req.tables[0].n == 0),
        .cancelled => unreachable,
    }
    close(s, req, .cancelled);
    compactRunning(s);
    if (req.planned_ahead) return; // oldest commit unwinds both plans' rows once
    assert(req.tables[0].n == 0);
    if (req.planned) return; // commit releases it
    request.release(s.reqs, req);
    assert(!req.owned);
}

/// Applies a knob to the live config at a step boundary (the only caller is the boundary: c_api's
/// inbox apply, or the trace harness's `set` right before its next plan). The value was validated
/// when it was queued (validateKnob reads only init-time sizes, so any thread may call it).
pub fn applyKnob(s: *Scheduler, knob: Knob) void {
    assert(!s.building_ahead);
    setField(&s.cfg, knob);
    s.config_hash = hashConfig(&s.cfg);
    assert(s.cfg.max_batch_tokens <= s.arenas[0].plan.input_ids.len);
    assert(s.cfg.max_batch_reqs <= s.arenas[0].sched.len);
}

pub fn hashConfig(cfg: *const Config) u64 {
    // Field by field: the struct has padding bytes, which would make the hash depend on garbage.
    var h = std.hash.Wyhash.init(0);
    inline for (@typeInfo(Config).@"struct".fields) |f| h.update(std.mem.asBytes(&@field(cfg, f.name)));
    return h.final();
}

/// Invalid: a value the static buffers cannot hold (max_batch_tokens / max_batch_reqs above the
/// init-time size) or out of range. Reads only init-time sizes: safe from any thread.
pub fn validateKnob(s: *const Scheduler, knob: Knob) KnobError!void {
    switch (knob) {
        .max_batch_tokens => |v| if (v == 0 or v > s.arenas[0].plan.input_ids.len) return error.Invalid,
        .max_batch_reqs => |v| if (v == 0 or v > s.arenas[0].sched.len) return error.Invalid,
        .reserve_ratio => |v| if (!(v >= 0)) return error.Invalid,
        .order, .prefix_cache => {},
    }
}

/// Writes one knob into a Config (the live one at the boundary, or the edge's pending copy).
pub fn setField(cfg: *Config, knob: Knob) void {
    switch (knob) {
        .order => |v| cfg.order = v,
        .reserve_ratio => |v| cfg.reserve_ratio = v,
        .max_batch_tokens => |v| cfg.max_batch_tokens = v,
        .max_batch_reqs => |v| cfg.max_batch_reqs = v,
        .prefix_cache => |v| cfg.prefix_cache = v,
    }
}

pub fn plan(s: *Scheduler) *const Plan {
    // Building ahead means a plan is already outstanding: fill the *other* arena and leave the
    // live one untouched. `build()` follows `building_ahead`, so no buffer is ever swapped.
    const build_ahead = s.planned();
    assert(!build_ahead or (s.cfg.overlap and s.n_outstanding == 1));
    if (build_ahead) {
        reserveAhead(s);
        s.building_ahead = true;
    }
    defer if (build_ahead) {
        s.building_ahead = false;
    };
    timingStart(s, .plan);
    s.step += 1;
    s.n_sched = 0;
    const n_preempted_before = s.build().building.n_preempted;
    var budget = s.cfg.max_batch_tokens;
    switch (s.cfg.order) {
        .running_first => {
            const preempted = planRunning(s, &budget, s.n_running);
            if (!preempted and s.state == .serving) planWaiting(s, &budget);
        },
        .waiting_first => {
            const n_old = s.n_running;
            if (s.state == .serving) planWaiting(s, &budget);
            _ = planRunning(s, &budget, n_old);
        },
    }
    emitPlan(s);
    recordPlan(s);
    // An ahead plan may come up empty while the one in flight still holds what it needs.
    const preempted = s.build().building.n_preempted != n_preempted_before;
    s.stall = if (build_ahead) null else stallOf(s, preempted);
    const built = s.build();
    assert(built.plan.n_reqs == s.n_sched);
    timingStop(s, .plan);
    s.n_outstanding += 1;
    assert(s.n_outstanding <= 2);
    return &built.plan;
}

/// Stall when this plan (none in flight) scheduled nothing, preempted nobody, and work is
/// pending: a runner, or a waiting request while serving (draining admits no one on purpose).
/// Then nothing changes before the next plan, which therefore does the same.
fn stallOf(s: *const Scheduler, preempted: bool) ?Stall {
    assert(s.n_outstanding == 0);
    if (s.n_sched > 0 or preempted) return null;
    const waiting_blocked = s.n_waiting > 0 and s.state == .serving;
    if (s.n_running == 0 and !waiting_blocked) return null;
    const id = if (s.n_running > 0) s.running[0] else s.waiting[s.waiting_head];
    const req = &s.reqs.requests[id];
    const n_work = chunkFor(s, &req.seq, s.cfg.max_batch_tokens);
    const need = if (n_work == 0) 0 else slabsNeeded(s, req, n_work, extraFor(s, req, n_work, s.cfg.max_batch_tokens));
    return .{ .req_id = id, .n_work = n_work, .need_slabs = need, .free_slabs = kv_pool.nFreeSlabs(s.kv) };
}

/// Before N+1 is built, count every row of N (the plan in flight) as computed, so N+1 plans from
/// committed + in flight and never plans an in-flight row again. An entry that emits (a decode,
/// or a chunk that completes the prompt or a re-prefill) also reserves the history position of
/// the token N will sample, with a placeholder commit(N) overwrites. This is how the reference
/// engines do it: vLLM v1 advances num_computed_tokens at schedule time
/// (Scheduler._update_after_schedule) and adds an output placeholder only for a non-chunk
/// (AsyncScheduler._update_after_schedule); SGLang's overlap loop moves chunked_req.prefix_indices
/// past the in-flight chunk before planning the next (Scheduler.get_next_batch_to_run).
fn reserveAhead(s: *Scheduler) void {
    assert(s.n_outstanding == 1 and !s.building_ahead);
    const p = &s.live().plan;
    for (p.entries[0..p.n_reqs], 0..) |entry, i| {
        const req = &s.reqs.requests[entry.req_id];
        if (req.state != .running) continue; // cancelled in flight: never planned again
        const seq = &req.seq;
        // Nothing was counted yet, and the entry still starts where plan N put it.
        assert(!req.planned_ahead and req.n_in_flight == 0);
        assert(seq.n_computed == p.seq_start[i]);
        // Overlap and extra rows are exclusive (c_api refuses the config; extraFor never plans
        // them ahead), so the entry's rows are exactly its n_work history rows.
        assert(entry.n_extra == 0);
        assert(seq.n_computed + entry.n_work <= seq.n);
        const emits = seq.n_computed + entry.n_work == seq.n;
        assert(emits == (p.emits[i] == 1));
        seq.n_computed += entry.n_work;
        req.n_in_flight = entry.n_work;
        if (emits) {
            assert(seq.n < seq.tokens.len);
            req.pending_token = std.math.maxInt(u32);
            seq.tokens[seq.n] = req.pending_token;
            seq.n += 1;
        }
        req.planned_ahead = true;
    }
}

/// The invariant overlap rests on: a row is never planned twice while in flight, and positions
/// derive from committed + in-flight counts. `req` is being emitted into the ahead plan (N+1).
/// If plan N names it, N's rows [seq_start, seq_start + n_work) are counted in n_computed, so
/// N+1 starts exactly where N ends; otherwise nothing of it is in flight.
fn assertNotInFlight(s: *Scheduler, req: *const request.Request) void {
    assert(s.building_ahead);
    const live = &s.live().plan;
    for (live.entries[0..live.n_reqs], 0..) |entry, i| {
        if (entry.req_id != req.id) continue;
        assert(req.n_in_flight == entry.n_work);
        assert(req.seq.n_computed - req.n_in_flight == live.seq_start[i]);
        assert(req.seq.n_computed == live.seq_start[i] + entry.n_work);
        return;
    }
    assert(req.n_in_flight == 0);
}

/// Applies c to the plan in flight, entry by entry (entries[i] <- row i of c). A partial prefill
/// chunk's token is discarded; an emitting entry appends what it keeps and advances past it.
/// The C boundary validates c (kelpie_commit returns an error); here a bad commit is a bug.
pub fn commit(s: *Scheduler, c: Commit) void {
    assert(s.planned());
    timingStart(s, .commit);
    const p = &s.live().plan;
    assert(c.n_tokens.len == p.n_reqs or c.n_tokens.len == 0);
    assert(c.next_extra.len == p.n_reqs or c.next_extra.len == 0);
    assert(c.stride >= 1 and c.tokens.len >= p.n_reqs * c.stride);
    for (p.entries[0..p.n_reqs], 0..) |entry, i| {
        const n_tokens: u32 = if (c.n_tokens.len == 0) 1 else c.n_tokens[i];
        const next_extra: u32 = if (c.next_extra.len == 0) 0 else c.next_extra[i];
        assert(n_tokens >= 1 and n_tokens <= 1 + entry.n_extra and n_tokens <= c.stride);
        assert(next_extra <= s.reqs.cfg.max_extra);
        commitEntry(s, entry, c.tokens[i * c.stride ..][0..n_tokens], next_extra);
    }
    compactRunning(s);
    timingStop(s, .commit);
    publishStep(s);
    // The oldest plan is done. Retiring it is one index step: the ahead plan, if any, becomes live.
    s.n_outstanding -= 1;
    if (s.n_outstanding > 0) {
        s.cur ^= 1;
        // Every entry of the promoted plan is now the plan in flight. commitEntry already moved a
        // request that was in both plans (planned = aheadContains); one admitted by the ahead
        // plan itself was only planned_ahead, and its commit asserted `planned` (a submit landing
        // while a plan was in flight under overlap). Found by the overlap + inbox race test.
        const promoted = &s.live().plan;
        for (promoted.entries[0..promoted.n_reqs]) |entry| {
            const req = &s.reqs.requests[entry.req_id];
            req.planned = true;
            req.planned_ahead = false;
        }
    }
}

/// One entry of a commit: a prefill chunk advances by n_work and yields its token only once the
/// prompt is complete; an emitting entry keeps `tokens` up to the first stop token and within
/// max_new_tokens (nCommitted, room). A proposer may draft PAST an eos -- the core must not append
/// those, advance n_computed over them, or let keepRows pick a live state from after the request
/// ended.
fn nCommitted(s: *const Scheduler, req: *const request.Request, tokens: []const u32) u32 {
    assert(tokens.len >= 1);
    for (tokens, 1..) |tok, n| {
        if (tok == s.cfg.eos_token or request.isStopToken(req, tok)) return @intCast(n);
    }
    return @intCast(tokens.len);
}

fn commitEntry(s: *Scheduler, entry: Entry, tokens: []const u32, next_extra: u32) void {
    // `tokens` = the tokens at extra rows 1..n-1 (drafts the caller vouches for), then the
    // token after tail row n-1; the request advances by tokens.len (fewer at a stop token or
    // max_new). commit() already bounded it by 1 + entry.n_extra.
    assert(tokens.len >= 1 and tokens.len <= 1 + entry.n_extra);
    assert(next_extra <= s.reqs.cfg.max_extra);
    const req = &s.reqs.requests[entry.req_id];
    assert(req.planned and req.owned);
    const reserved = req.pending_token == std.math.maxInt(u32);
    // reserveAhead already counted this entry's rows (it ran iff an ahead plan was built).
    const n_in_flight = req.n_in_flight;
    assert(n_in_flight == 0 or n_in_flight == entry.n_work);
    assert(!reserved or n_in_flight > 0);
    req.n_in_flight = 0;
    req.planned = false;
    if (req.state == .cancelled) { // cancelled between plan and commit: its slot was held for us
        if (n_in_flight > 0) { // unwind what reserveAhead counted
            if (reserved) req.seq.n -= 1;
            req.seq.n_computed -= n_in_flight;
            req.pending_token = 0;
        }
        // cancel() left the blocks to us when an ahead plan named the request (planned_ahead):
        // this commit frees both plans' rows once. That includes a request only the ahead plan
        // named, which reaches here from the promoted plan. Otherwise cancel() freed them already.
        freeBlocks(s, req);
        strikeAhead(s, req.id);
        req.planned_ahead = false;
        request.release(s.reqs, req);
        return;
    }
    assert(req.state == .running);
    if (entry.kind == .decode) assert(entry.n_work == 1);
    if (reserved) {
        assert(entry.n_extra == 0);
        req.seq.tokens[req.seq.n - 1] = tokens[0];
        req.pending_token = 0;
    } else if (n_in_flight == 0) request.advance(&req.seq, entry.n_work); // the history rows; kept extra rows are appended below
    const emits = reserved or req.seq.n_computed == req.seq.n;
    // How many of `tokens` the request keeps: up to the first stop token (a proposer may draft
    // past an eos; none of that may enter the history, advance n_computed or pick the live
    // state) and never past max_new_tokens (spec decode must not change the output length).
    // A reserved entry already counted its placeholder in n; max_new_tokens == 0 still
    // generates one token, as K = 0 always did. A partial prefill chunk keeps nothing but its
    // history rows (kept 1 = tail row 0).
    const room = @max(1, (req.params.max_new_tokens + @intFromBool(reserved)) -| request.nGenerated(&req.seq));
    const kept: u32 = if (emits) @min(nCommitted(s, req, tokens), room) else 1;
    assert(kept >= 1 and kept <= tokens.len);
    keepRows(s, req, entry, kept);
    if (s.cfg.prefix_cache) publishFull(s, req);
    if (!emits) { // partial prefill chunk: its token is discarded
        req.next_extra = next_extra;
        req.planned = aheadContains(s, req.id);
        req.planned_ahead = false;
        return;
    }
    const token = tokens[kept - 1];
    const t = events.now(&s.clock);
    // max_seq_len bounds the history (acquire checked prompt + max_new against it, and room caps
    // kept at max_new), so the kept tokens always fit (section 8 item 10).
    assert(kept <= s.reqs.cfg.max_seq_len - req.seq.n + @intFromBool(reserved));
    // Every kept token but the last was computed by this step (its row was one of this entry's
    // extra rows); the last one's KV comes next step. appendToken then appendComputed leaves
    // exactly that state: n_computed == n - 1. With no extra rows, kept == 1.
    if (!reserved) request.appendToken(&req.seq, tokens[0]);
    for (tokens[1..kept]) |tok| request.appendComputed(&req.seq, tok);
    s.live().building.n_extra_kept += kept - 1;
    if (request.nGenerated(&req.seq) == 1) req.event.t_first_token_ns = t;
    req.event.t_last_token_ns = t;
    if (token == s.cfg.eos_token or request.isStopToken(req, token)) {
        finish(s, req, .finished_eos);
    } else if (request.nGenerated(&req.seq) >= req.params.max_new_tokens) {
        finish(s, req, .finished_length);
    }
    req.next_extra = if (request.isFinished(req)) 0 else next_extra;
    if (request.isFinished(req)) {
        strikeAhead(s, req.id);
        req.planned = false;
    } else {
        req.planned = aheadContains(s, req.id);
    }
    req.planned_ahead = false;
}

fn aheadContains(s: *Scheduler, id: u32) bool {
    const a = s.ahead() orelse return false;
    for (a.plan.entries[0..a.plan.n_reqs]) |entry| if (entry.req_id == id) return true;
    return false;
}

fn strikeAhead(s: *Scheduler, id: u32) void {
    const ap = &(s.ahead() orelse return).plan;
    var dst: u32 = 0;
    var token_dst: u32 = 0;
    for (ap.entries[0..ap.n_reqs], 0..) |entry, src| {
        if (entry.req_id == id) continue;
        ap.entries[dst] = entry;
        const start = ap.query_start_loc[src];
        const end = ap.query_start_loc[src + 1];
        const n = end - start;
        std.mem.copyForwards(u32, ap.input_ids[token_dst..][0..n], ap.input_ids[start..end]);
        std.mem.copyForwards(u32, ap.positions[token_dst..][0..n], ap.positions[start..end]);
        for (ap.slot_mapping) |slots| std.mem.copyForwards(u32, slots[token_dst..][0..n], slots[start..end]);
        for (ap.block_tables) |tables| {
            const width = ap.max_blocks_per_req;
            std.mem.copyForwards(u32, tables[dst * width ..][0..width], tables[@as(u32, @intCast(src)) * width ..][0..width]);
        }
        ap.seq_lens[dst] = ap.seq_lens[src];
        ap.seq_start[dst] = ap.seq_start[src];
        ap.emits[dst] = ap.emits[src];
        for (ap.state) |idx| assert(idx.read.len == 0); // overlap runs per_token groups only
        ap.temperatures[dst] = ap.temperatures[src];
        ap.top_ks[dst] = ap.top_ks[src];
        ap.mm_hashes[dst] = ap.mm_hashes[src];
        ap.query_start_loc[dst] = token_dst;
        token_dst += n;
        dst += 1;
    }
    ap.n_reqs = dst;
    ap.n_tokens = token_dst;
    ap.query_start_loc[dst] = token_dst;
}

/// The forward runs outside the core; the caller brackets it with .forward. plan/commit bracket themselves.
pub fn timingStart(s: *Scheduler, which: events.Timing) void {
    events.start(&s.clock, which);
}

pub fn timingStop(s: *Scheduler, which: events.Timing) void {
    const elapsed = events.stop(&s.clock, which);
    switch (which) {
        .plan => s.build().building.t_plan_ns = elapsed,
        .forward => s.live().building.t_forward_ns = elapsed,
        .commit => s.live().building.t_commit_ns = elapsed,
    }
}

/// Copies generated tokens not yet polled. Pure apart from the request's own poll cursor: it never
/// releases the slot (docs/design-multigpu.md 2.1 item 3). The caller releases a finished request
/// with `release` -- c_api queues a release op when a poll first observes finished; the trace
/// harness releases right after the poll.
/// An unowned slot (cancelled, or already released) reports finished+cancelled with no tokens.
/// A planned-then-cancelled request reports cancelled but keeps its slot until commit (see cancel).
///
/// Overlap: reserveAhead has already appended N+1's placeholder (maxInt(u32)) at tokens[n-1] and
/// advanced seq.n; commit(N) overwrites it in place. That sentinel is not a generated token, so
/// poll must stop short of it -- otherwise a caller polling between reserveAhead and the matching
/// commit reads the placeholder AND advances n_polled past it, losing the real token forever.
pub fn poll(s: *Scheduler, req_id: u32, out: []u32) PollResult {
    const req = &s.reqs.requests[req_id];
    if (!req.owned) return .{ .n_new = 0, .finished = true, .state = .cancelled };
    const seq = &req.seq;
    const start = seq.n_prompt + req.n_polled;
    const end = seq.n - @intFromBool(req.pending_token == std.math.maxInt(u32));
    assert(start <= end);
    const n_new = end - start;
    assert(n_new <= out.len);
    @memcpy(out[0..n_new], seq.tokens[start..end]);
    req.n_polled += n_new;
    return .{ .n_new = n_new, .finished = request.isFinished(req), .state = req.state };
}

/// Frees a finished request's slot (poll's old side effect, now its own verb). A no-op when the
/// slot is not owned, not finished, or still named by a plan in flight (a cancelled request the
/// in-flight plan holds: its commit releases it). Returns whether the slot was released.
pub fn release(s: *Scheduler, req_id: u32) bool {
    const req = &s.reqs.requests[req_id];
    if (!req.owned or !request.isFinished(req) or req.planned or req.planned_ahead) return false;
    request.release(s.reqs, req);
    assert(!req.owned);
    return true;
}

/// Waiting request ids in queue order (front to back), written into `out`. Returns the count.
/// Read-only query over the waiting ring: callers (e.g. the trace harness's `expect waiting`)
/// get ids, never ring indices, so the ring's layout stays private to the scheduler.
pub fn waitingIds(s: *const Scheduler, out: []u32) usize {
    assert(s.n_waiting <= s.waiting.len);
    for (out[0..s.n_waiting], 0..) |*slot, i| slot.* = waitingSlot(s, @intCast(i)).*;
    for (out[0..s.n_waiting]) |id| assert(s.reqs.requests[id].owned);
    return s.n_waiting;
}

// ---- planning ----------------------------------------------------------------------------

/// Runners are running[0..n_unplanned]; anything after was admitted this step. Returns whether anyone was preempted.
/// Visited from `rr` on, wrapping. A runner that finds no batch room (the request cap is reached or
/// the token budget is spent: max_batch_reqs / max_batch_tokens set below the runner count) is
/// skipped, keeps its blocks, and goes first next step (round-robin; docs/design-rules.md "Live
/// config"); everyone after it is skipped too. Victim: the last still-unplanned runner in visit
/// order, which is the youngest runner whenever nobody was skipped last step.
fn planRunning(s: *Scheduler, budget: *u32, n_unplanned: u32) bool {
    assert(n_unplanned <= s.n_running);
    const order = s.order[0..n_unplanned];
    const start = if (n_unplanned == 0) 0 else s.rr % n_unplanned;
    for (order, 0..) |*slot, k| slot.* = s.running[(start + k) % n_unplanned];
    s.rr = 0;
    var n_old = n_unplanned;
    var preempted = false;
    var i: u32 = 0;
    while (i < n_old) : (i += 1) {
        const req = &s.reqs.requests[order[i]];
        assert(req.state == .running);
        if (budget.* == 0 or s.n_sched == s.cfg.max_batch_reqs) {
            s.rr = indexOfRunning(s, req.id);
            return preempted;
        }
        slideOut(s, req);
        const n_work = chunkFor(s, &req.seq, budget.*);
        if (n_work == 0) continue;
        var n_extra = extraFor(s, req, n_work, budget.*);
        // Extra rows are optional: drop them before taking anyone's memory (a lone request would
        // otherwise preempt itself, re-prefill, and do it again forever).
        if (n_extra > 0 and slabsNeeded(s, req, n_work, n_extra) > kv_pool.nFreeSlabs(s.kv)) n_extra = 0;
        while (slabsNeeded(s, req, n_work, n_extra) > kv_pool.nFreeSlabs(s.kv)) {
            if (s.building_ahead) {
                s.rr = indexOfRunning(s, req.id);
                return preempted;
            }
            preempted = true;
            n_old -= 1;
            preemptRunning(s, indexOfRunning(s, order[n_old]));
            if (n_old == i) return true;
        }
        schedule(s, req, n_work, n_extra);
        budget.* -= n_work + n_extra;
    }
    return preempted;
}

fn indexOfRunning(s: *const Scheduler, id: u32) u32 {
    for (s.running[0..s.n_running], 0..) |rid, i| {
        if (rid == id) return @intCast(i);
    }
    unreachable;
}

fn planWaiting(s: *Scheduler, budget: *u32) void {
    while (s.n_waiting > 0 and budget.* > 0 and s.n_running < s.cfg.max_batch_reqs) {
        const req = &s.reqs.requests[s.waiting[s.waiting_head]];
        assert(req.state == .waiting);
        assert(req.seq.n_computed == 0);
        const n_hit = if (s.cfg.prefix_cache) claimPrefix(s, req) else 0;
        const n_work = chunkFor(s, &req.seq, budget.*);
        // An admitted request's first entry never has extra rows (a recompute or prefill,
        // section 8 item 1), and acquire and preempt cleared what it had asked for.
        assert(req.next_extra == 0);
        // The reserve keeps room for runners' decode. With none running there is no one to keep
        // it for, and submit already checked the request fits alone: waiting on it would stall.
        const reserve = if (s.n_running == 0) 0 else reserveSlabs(s, req);
        if (n_work == 0 or slabsNeeded(s, req, n_work, 0) + reserve > kv_pool.nFreeSlabs(s.kv)) {
            // Not admitted this tick: give the hit blocks back; the next tick re-matches.
            freeBlocks(s, req);
            req.seq.n_computed = 0;
            break;
        }
        _ = popFrontWaiting(s);
        const b = &s.build().building;
        b.prefix_queries += @intFromBool(s.cfg.prefix_cache);
        b.prefix_hits += @intFromBool(n_hit > 0);
        b.prefix_hit_tokens += n_hit;
        req.state = .running;
        s.running[s.n_running] = req.id;
        s.n_running += 1;
        b.n_admitted += 1;
        if (req.event.first_step == 0) {
            req.event.first_step = s.step;
            req.event.t_first_sched_ns = events.now(&s.clock);
        }
        schedule(s, req, n_work, 0);
        budget.* -= n_work;
    }
    assert(s.n_running <= s.reqs.cfg.max_requests);
}

/// Longest prefix cached in every group (min over groups; docs/kv-groups.md), at most n - 1 tokens,
/// floored to the lcm of the groups' block grains so every group resumes on a whole block
/// (docs/cache-groups-ladder.md Q3: stride-128 at block 16 makes the DSV4 grain 2048).
/// Hit blocks are referenced and become the head of each table; n_computed skips past them.
/// A preempted request matches its own history here, so re-prefill is mostly free.
fn claimPrefix(s: *Scheduler, req: *request.Request) u32 {
    assert(req.seq.n_computed == 0);
    for (req.tables) |table| assert(table.n == 0);
    const tokens = req.seq.tokens[0..req.seq.n];
    const n_hit = hitFixpoint(s, req, tokens);
    assert(n_hit < req.seq.n);
    // A per-group match may have found a longer run than the final (floored, cross-group) n_hit --
    // stride/window groups scan independently -- so re-derive each table's live rows at n_hit itself
    // rather than trusting table.n / table.ids past the point every group agreed on. A window
    // group's rows below firstLiveRow(n_hit) were never the target run (or belong to a longer one
    // this group alone supported) and must not be touched: they are holes here, exactly as slideOut
    // would leave them for a request that had been running all along.
    for (s.reqs.cfg.groups, req.tables, 0..) |group, *table, g| {
        // A per_seq hit is the checkpoint at exactly n_hit. It enters this request's ring with a
        // reference of its own (the ring releases it on slide-out or finish); `live` stays 0,
        // so the first step reads the checkpoint and writes a fresh unit (allocState) -- the
        // shared checkpoint is never written.
        if (group.kind == .per_seq) {
            const st = &req.units[g];
            assert(st.live == 0 and st.n_ring == 0);
            if (n_hit == 0) continue;
            var hit: [1]u32 = undefined;
            const m = prefix.matchUpTo(s.kv, @intCast(g), group, tokens, &hit, mmOf(req), n_hit);
            assert(m.n_hit == n_hit and hit[0] != kv_pool.null_block);
            kv_pool.touch(s.kv, @intCast(g), hit[0]);
            st.ring[0] = .{ .id = hit[0], .pos = n_hit };
            st.n_ring = 1;
            continue;
        }
        const first_live = request.firstLiveRow(group, n_hit);
        const want = request.rowsFor(group, n_hit); // logical rows, not blocksFor's admission plateau
        assert(first_live <= want);
        for (table.ids[0..first_live]) |*id| id.* = kv_pool.null_block;
        for (table.ids[first_live..want]) |id| kv_pool.touch(s.kv, @intCast(g), id);
        table.n = want;
    }
    req.seq.n_computed = n_hit;
    assert(request.nWork(&req.seq) > 0);
    return n_hit;
}

/// The cross-group hit length: the largest `t` every group supports at once
/// (docs/cache-groups-ladder.md Q3, vLLM HybridKVCacheCoordinator.find_longest_cache_hit).
///
/// One pass of `min` over independent scans is NOT this. A closed group (all, stride-k) is
/// prefix-closed, so its answer at a shorter cap is just the truncation; a window or per_seq
/// group is not, and its longest resumable boundary <= cap is not monotone in the same way --
/// capping for one group can move another group's answer. So: take the min, re-ask everyone
/// capped at it, repeat until nothing shrinks. Each round strictly decreases n_hit or stops,
/// and n_hit is floored to the grain each round, so it terminates in at most n_groups rounds
/// (each round at least one group's answer becomes binding and stays so).
fn hitFixpoint(s: *Scheduler, req: *request.Request, tokens: []const u32) u32 {
    const groups = s.reqs.cfg.groups;
    const grain = hitGrain(groups);
    var cap: u32 = @intCast(tokens.len - 1); // the last token is never matched
    cap = cap / grain * grain;
    var round: u32 = 0;
    while (round <= groups.len) : (round += 1) {
        var next = cap;
        for (groups, req.tables, 0..) |group, table, g| {
            var seq_hit: [1]u32 = undefined; // a per_seq group has no table; claimPrefix re-matches
            const into = if (group.kind == .per_seq) seq_hit[0..] else table.ids;
            const hit = prefix.matchUpTo(s.kv, @intCast(g), group, tokens, into, mmOf(req), cap).n_hit;
            next = @min(next, hit);
        }
        next = next / grain * grain;
        assert(next <= cap);
        if (next == cap) return cap;
        cap = next;
    }
    // Monotone decrease over a finite grid cannot outlast one round per group.
    unreachable;
}

/// lcm over per_token groups of tokensPerBlock: the only resume points every table can express.
fn hitGrain(groups: []const request.GroupSpec) u32 {
    var grain: u32 = 1;
    for (groups) |group| {
        // A checkpointing per_seq group can only resume at a multiple of its interval, so it
        // joins the lcm exactly like a stride-k per_token group (Q3 "floor to lcm_g(u_g)").
        const u = switch (group.kind) {
            .per_token => request.tokensPerBlock(group),
            .per_seq => if (group.stride == 0) continue else group.stride,
        };
        grain = grain / std.math.gcd(grain, u) * u;
    }
    assert(grain >= 1);
    return grain;
}

fn mmOf(req: *const request.Request) request.Mm {
    return .{ .hash = req.mm_hash, .start = req.mm_start };
}

fn publishFull(s: *Scheduler, req: *request.Request) void {
    const computed = req.seq.tokens[0..req.seq.n_computed];
    for (s.reqs.cfg.groups, req.tables, req.units, 0..) |group, table, st, g| {
        switch (group.kind) {
            .per_token => prefix.insert(s.kv, @intCast(g), group, computed, table.ids[0..table.n], mmOf(req)),
            .per_seq => prefix.insertSeq(s.kv, @intCast(g), group, computed, st.ring[0..st.n_ring], mmOf(req)),
        }
    }
}

/// A partial chunk ends on a block boundary of the first per_token group (its tokensPerBlock:
/// stride-aware); the chunk that finishes the prompt may not. per_seq groups never force
/// alignment (a chunk crossing checkpoint boundaries checkpoints the largest one). Compress
/// rings (docs/cache-groups-ladder.md) carry partial units across chunks, so no alignment to a
/// stride is required of the scheduler.
fn chunkFor(s: *const Scheduler, seq: *const request.Sequence, budget: u32) u32 {
    return chunkAt(s, seq.n_computed, request.nWork(seq), budget);
}

/// chunkFor on bare numbers, so worstSlabs can lay out a request's chunks before it exists.
fn chunkAt(s: *const Scheduler, n_computed: u32, remaining: u32, budget: u32) u32 {
    assert(budget > 0 and remaining > 0);
    const n_work = @min(remaining, budget);
    if (n_work == remaining) return n_work;
    const grain = chunkGrain(s.reqs.cfg.groups) orelse return n_work;
    const end = (n_computed + n_work) / grain * grain;
    assert(end >= n_computed);
    return end - n_computed;
}

/// The first per_token group's tokensPerBlock; null when every group is per_seq.
fn chunkGrain(groups: []const request.GroupSpec) ?u32 {
    for (groups) |group| {
        if (group.kind == .per_token) return request.tokensPerBlock(group);
    }
    return null;
}

/// New rows this chunk adds, in *slabs* off the free list (docs/kv-groups.md Q4:
/// `slabs = sum_g ceil((need_g - held_g) / pages_per_slab_g)`, minus what the group's partial
/// slabs already hold). Slid-out rows were freed already (slideOut), so a window group in steady
/// decode needs ~0. With pages_per_slab == 1 everywhere this is the old page count exactly.
fn slabsNeeded(s: *const Scheduler, req: *const request.Request, n_work: u32, n_extra: u32) u32 {
    assert(n_work > 0);
    // Must match what `schedule` will allocate, including the extra rows. A table can already
    // be LONGER than this: extra rows that were not kept leave rows the next step's rowsFor does
    // not ask for, and those are the request's to reuse, not a debt.
    var need: u32 = 0;
    for (s.reqs.cfg.groups, req.tables, req.units, 0..) |group, table, st, g| {
        if (group.kind == .per_seq) {
            // Once scheduled, the step's units are allocated: nothing more is needed.
            if (request.isPending(&req.pending[g])) continue;
            need += kv_pool.slabsFor(s.kv, @intCast(g), newUnits(group, &st, req.seq.n_computed, n_work, n_extra));
            continue;
        }
        const want = rowsWithExtra(group, req.seq.n_computed + n_work, n_extra);
        if (want <= table.n) continue;
        need += kv_pool.slabsFor(s.kv, @intCast(g), want - table.n);
    }
    return need;
}

/// Fresh units allocState takes for one per_seq group: write[0] unless the live unit is
/// updated in place, one per draft row, and a checkpoint if the history rows cross a boundary.
fn newUnits(group: request.GroupSpec, st: *const request.StateTable, seq_start: u32, n_hist: u32, n_extra: u32) u32 {
    assert(group.kind == .per_seq);
    const ckpt: u32 = @intFromBool(checkpointIn(group, seq_start, n_hist) != null);
    return @as(u32, @intFromBool(st.live == 0)) + n_extra + ckpt;
}

/// The checkpoint a step whose history rows are [seq_start, seq_start + n_hist) writes: the
/// largest multiple b of the stride with seq_start < b <= seq_start + n_hist (the state after
/// row b - 1), or null. Never a boundary inside draft rows: those may be rejected.
fn checkpointIn(group: request.GroupSpec, seq_start: u32, n_hist: u32) ?u32 {
    assert(group.kind == .per_seq);
    if (group.stride == 0) return null;
    const b = (seq_start + n_hist) / group.stride * group.stride;
    return if (b > seq_start) b else null;
}

/// Decode reserve per group, in slabs; a window group never reserves past its plateau.
fn reserveSlabs(s: *const Scheduler, req: *const request.Request) u32 {
    assert(s.cfg.reserve_ratio >= 0);
    const max_new: f32 = @floatFromInt(req.params.max_new_tokens);
    const n_tokens: u32 = @intFromFloat(@ceil(s.cfg.reserve_ratio * max_new));
    var total: u32 = 0;
    for (s.reqs.cfg.groups, 0..) |group, g| {
        const need = request.blocksFor(group, n_tokens, s.reqs.cfg.max_extra);
        total += kv_pool.slabsFor(s.kv, @intCast(g), need);
    }
    return total;
}

/// The most slabs a request of n_prompt + max_new tokens holds at once if it runs alone to
/// max_new, over every step it can take: each chunk of a from-scratch prefill of its whole
/// history (a preempted request re-prefills everything, so this covers the prompt's own chunks)
/// and each decode step. Summed over groups at the same step, since that is what must be free
/// together. Nothing the scheduler does needs fewer, so a request above the pool can never finish.
/// Not modelled: pages stranded in a partly freed slab (window / per_seq groups with
/// pages_per_slab > 1) and budgets changed after submit; the stall check in plan reports those.
pub fn worstSlabs(s: *const Scheduler, n_prompt: u32, max_new: u32) u32 {
    assert(n_prompt > 0);
    // Tokens whose KV is ever computed: the last sampled token never is.
    const n_end = n_prompt + @max(max_new, 1) - 1;
    var worst: u32 = 0;
    var n_c: u32 = 0;
    while (n_c < n_end) {
        const n_work = chunkAt(s, n_c, n_end - n_c, s.cfg.max_batch_tokens);
        if (n_work == 0) break; // budget below the grain: never runs; the stall check says so
        worst = @max(worst, slabsAt(s, n_c, n_work, 0));
        n_c += n_work;
    }
    // Decode from the prompt's end. Per residue mod the grain a window group's rows repeat and
    // every other group only grows, so the last grain positions hold the peak. Without extra
    // rows: planRunning drops them rather than wait or preempt, so a lone request never needs them.
    const period = hitGrain(s.reqs.cfg.groups);
    n_c = @max(n_prompt, n_end -| period);
    while (n_c < n_end) : (n_c += 1) worst = @max(worst, slabsAt(s, n_c, 1, 0));
    return worst;
}

/// Slabs a lone request holds while computing [n_computed, n_computed + n_work) with n_extra
/// extra rows: rows up to the chunk's end minus a window group's slid-out holes, per group, each
/// group rounded up to whole slabs (a slab belongs to one group).
fn slabsAt(s: *const Scheduler, n_computed: u32, n_work: u32, n_extra: u32) u32 {
    var total: u32 = 0;
    for (s.reqs.cfg.groups, s.kv.groups) |group, pool_group| {
        if (group.kind == .per_seq) {
            // ZERO, the live unit (or fresh write[0]), the ring so far, this step's
            // checkpoint and one write unit per extra row.
            const n_ring = if (group.stride == 0) 0 else @min(request.nCheckpoints(group), n_computed / group.stride);
            const ckpt: u32 = @intFromBool(checkpointIn(group, n_computed, n_work) != null);
            const units = 1 + 1 + n_ring + ckpt + n_extra;
            total += (units + pool_group.pages_per_slab - 1) / pool_group.pages_per_slab;
            continue;
        }
        const rows = rowsWithExtra(group, n_computed + n_work, n_extra);
        const holes = if (group.kind == .per_token) request.firstLiveRow(group, n_computed) else 0;
        assert(holes <= rows);
        total += (rows - holes + pool_group.pages_per_slab - 1) / pool_group.pages_per_slab;
    }
    return total;
}

/// Free the rows of every window group that the next query can no longer see; the row keeps its
/// position and reads 0 (null block) from here on. Runs before need is computed, so the freed
/// blocks pay for this step's new ones.
fn slideOut(s: *Scheduler, req: *request.Request) void {
    for (s.reqs.cfg.groups, req.tables, 0..) |group, *table, g| {
        // A per_seq group's checkpoints slide at commit (keepRows), not here.
        if (group.kind == .per_seq) continue;
        if (request.window(group) == 0) continue;
        const first_live = request.firstLiveRow(group, req.seq.n_computed);
        assert(first_live <= table.n);
        for (table.ids[0..first_live]) |*id| {
            if (id.* == kv_pool.null_block) continue;
            kv_pool.free(s.kv, @intCast(g), id[0..1]);
            id.* = kv_pool.null_block;
        }
    }
}

/// `n_work` history rows (1 for a decode row), then `n_extra` extra rows (extraFor).
fn schedule(s: *Scheduler, req: *request.Request, n_work: u32, n_extra: u32) void {
    assert(s.n_sched < s.cfg.max_batch_reqs);
    assert(n_extra == 0 or isDecodeShaped(&req.seq, n_work));
    assert(n_extra == 0 or n_extra == req.next_extra);
    const kind = kindOf(&req.seq, n_work);
    // The step writes KV for every extra row, so the rows must exist before it runs -- even
    // though only the kept ones survive the commit. The rest are handed back by the next step's
    // rowsFor, which is below table.n once rows are not kept.
    for (s.reqs.cfg.groups, req.tables, 0..) |group, *table, g| {
        if (group.kind == .per_seq) continue;
        const want = rowsWithExtra(group, req.seq.n_computed + n_work, n_extra);
        if (want <= table.n) continue;
        kv_pool.allocate(s.kv, @intCast(g), table.ids[table.n..want]);
        table.n = want;
    }
    allocState(s, req, n_work, n_extra);
    s.build().sched[s.n_sched] = .{ .req_id = req.id, .n_work = n_work, .n_extra = n_extra, .kind = kind };
    s.n_sched += 1;
    if (s.building_ahead) {
        // No assert here, unlike the `planned` arm below, and both halves of that are deliberate:
        //   - req.planned may already be true: this request is named in the outstanding plan N as
        //     well as the N+1 being built. That is the ordinary overlap case, not a double-plan.
        //   - req.planned_ahead may ALSO already be true: reserveAhead stamps decode entries as
        //     reserved before N+1 is built, and a request can then be scheduled into N+1 on its
        //     own (the reference calls this out -- reservation is one path into `ahead`, not the
        //     only one). Setting it again is idempotent; asserting it false fails on real traces.
        req.planned_ahead = true;
    } else {
        assert(!req.planned);
        req.planned = true;
    }
    req.event.n_chunks += 1;
    req.event.kv_blocks_peak = @max(req.event.kv_blocks_peak, blocksHeld(req));
    assert(slabsNeeded(s, req, n_work, n_extra) == 0);
}

/// Every per_seq group's units for the step being scheduled (docs/design-core-option2.md 2.2
/// `allocState`, section 8 items 3, 5, 6). The history rows are [seq_start, seq_start + n_hist),
/// then n_extra draft rows.
///   read     = live if set; else the ring checkpoint at exactly seq_start (a prefix hit); else ZERO.
///   write[0] = live, updated in place (live is private: checkpoints are separate units), else
///              fresh. write[1..n_extra] fresh; write past n_extra SCRATCH, explicitly.
///   ckpt     = fresh at the largest stride boundary in the history rows (checkpointIn), else
///              SCRATCH with ckpt_row = no_row. At most one per step.
/// No copies anywhere: rollback, a fresh start, a prefix hit and a recompute are index values.
fn allocState(s: *Scheduler, req: *request.Request, n_hist: u32, n_extra: u32) void {
    const seq_start = req.seq.n_computed;
    for (s.reqs.cfg.groups, req.units, req.pending, s.zero_units, 0..) |group, *st, *pending, zero, g_usize| {
        if (group.kind != .per_seq) continue;
        const g: u32 = @intCast(g_usize);
        assert(!request.isPending(pending));
        assert(1 + n_extra <= pending.write.len);
        const n_free_before = kv_pool.nFree(s.kv, g);
        const n_new = newUnits(group, st, seq_start, n_hist, n_extra);
        pending.read = readUnit(st, zero, seq_start);
        if (st.live != kv_pool.null_block) {
            pending.write[0] = st.live;
        } else kv_pool.allocate(s.kv, g, pending.write[0..1]);
        kv_pool.allocate(s.kv, g, pending.write[1 .. 1 + n_extra]);
        @memset(pending.write[1 + n_extra ..], scratch_unit);
        if (checkpointIn(group, seq_start, n_hist)) |b| {
            var ckpt: [1]u32 = undefined;
            kv_pool.allocate(s.kv, g, &ckpt);
            pending.ckpt = .{ .id = ckpt[0], .pos = b };
            pending.ckpt_row = b - 1 - seq_start;
            assert(pending.ckpt_row < n_hist);
        } else {
            pending.ckpt = .{ .id = scratch_unit, .pos = 0 };
            pending.ckpt_row = request.no_row;
        }
        for (pending.write) |id| assert(id != zero);
        assert(pending.ckpt.id != zero and pending.read != scratch_unit);
        // slabsNeeded asked newUnits; this is what was actually taken.
        assert(n_free_before - kv_pool.nFree(s.kv, g) == n_new);
        assert(request.isPending(pending));
    }
}

/// The unit holding the state after tokens[0..seq_start): live, else the ring checkpoint at
/// exactly seq_start (only right after a prefix hit), else ZERO (nothing computed yet).
fn readUnit(st: *const request.StateTable, zero: u32, seq_start: u32) u32 {
    if (st.live != kv_pool.null_block) return st.live;
    if (seq_start == 0) return zero;
    assert(st.n_ring > 0);
    const newest = st.ring[st.n_ring - 1];
    assert(newest.pos == seq_start);
    return newest.id;
}

/// Commit side of allocState, per per_seq group: tail rows 0..kept-1 were valid, so
/// live := write[kept - 1] and every other write unit is freed (write[0] is the old live unit
/// when it was updated in place: dropped too unless kept == 1). The checkpoint always enters the
/// ring -- it lies on a history row, and every history row commits -- and the ring's oldest
/// entry slides out when full. Invariant after: live holds the state after
/// tokens[0..n_computed).
fn keepRows(s: *Scheduler, req: *request.Request, entry: Entry, kept: u32) void {
    assert(kept >= 1 and kept <= 1 + entry.n_extra);
    for (s.reqs.cfg.groups, req.units, req.pending, 0..) |group, *st, *pending, g_usize| {
        if (group.kind != .per_seq) continue;
        const g: u32 = @intCast(g_usize);
        assert(request.isPending(pending));
        const writes = pending.write[0 .. 1 + entry.n_extra];
        for (writes, 0..) |id, j| {
            assert(id != scratch_unit);
            if (j != kept - 1) kv_pool.free(s.kv, g, &.{id});
        }
        st.live = writes[kept - 1];
        if (pending.ckpt.id != scratch_unit) {
            assert(pending.ckpt.pos <= req.seq.n_computed);
            pushRing(s, g, st, pending.ckpt);
        }
        request.clearPending(pending);
        assert(st.live != kv_pool.null_block);
    }
}

/// Appends a checkpoint (its reference moves into the ring); a full ring releases its oldest.
fn pushRing(s: *Scheduler, g: u32, st: *request.StateTable, ckpt: request.Ckpt) void {
    assert(st.ring.len > 0);
    if (st.n_ring > 0) assert(st.ring[st.n_ring - 1].pos < ckpt.pos);
    if (st.n_ring == st.ring.len) {
        kv_pool.free(s.kv, g, &.{st.ring[0].id});
        std.mem.copyForwards(request.Ckpt, st.ring[0 .. st.n_ring - 1], st.ring[1..st.n_ring]);
        st.n_ring -= 1;
    }
    st.ring[st.n_ring] = ckpt;
    st.n_ring += 1;
}

/// Drops every unit a request holds in its per_seq groups: pending writes and checkpoint (the
/// plan in flight's, when a cancel lands before its commit), live, then the ring oldest first,
/// so the newest checkpoint -- the most useful prefix -- is the last to be reused.
fn freeState(s: *Scheduler, req: *request.Request, g: u32) void {
    const st = &req.units[g];
    const pending = &req.pending[g];
    if (request.isPending(pending)) {
        for (pending.write) |id| {
            if (id != scratch_unit and id != st.live) kv_pool.free(s.kv, g, &.{id});
        }
        if (pending.ckpt.id != scratch_unit) kv_pool.free(s.kv, g, &.{pending.ckpt.id});
        request.clearPending(pending);
    }
    if (st.live != kv_pool.null_block) kv_pool.free(s.kv, g, &.{st.live});
    st.live = kv_pool.null_block;
    for (st.ring[0..st.n_ring]) |ckpt| kv_pool.free(s.kv, g, &.{ckpt.id});
    st.n_ring = 0;
}

/// Rows a per_token group needs for positions < n_end + n_extra: the extra rows are more
/// positions in the same block arithmetic. No reach term: whatever the caller does with the
/// extra rows (a drafter's noise block) happens on exactly these rows.
fn rowsWithExtra(group: request.GroupSpec, n_end: u32, n_extra: u32) u32 {
    assert(group.kind == .per_token);
    return request.rowsFor(group, n_end + n_extra);
}

/// Extra rows a chunk carries: what the last commit asked for (req.next_extra), all or nothing
/// (section 8 item 1: a partial draft block is wrong, not smaller). Only on a decode-shaped
/// chunk, and only when the budget has room for all 1 + n_extra rows (a runner short of room
/// degrades to plain decode rather than being skipped). Never on an ahead plan: overlap and
/// extra rows are exclusive.
fn extraFor(s: *const Scheduler, req: *const request.Request, n_work: u32, budget: u32) u32 {
    assert(req.next_extra <= s.reqs.cfg.max_extra);
    if (req.next_extra == 0 or s.building_ahead or !isDecodeShaped(&req.seq, n_work)) return 0;
    if (n_work + req.next_extra > budget) return 0;
    return req.next_extra;
}

/// The chunk is the newest token of a request whose prompt is done: one history row at the end
/// of the history.
fn isDecodeShaped(seq: *const request.Sequence, n_work: u32) bool {
    return n_work == 1 and seq.n_computed >= seq.n_prompt and seq.n_computed + n_work == seq.n;
}

/// Decode iff the chunk is exactly the newest token of a request whose prompt is fully computed.
/// Everything else is a prefill: a first chunk of any length (a one-token prompt included), a
/// chunked prefill's one-token tail, and a re-prefill of generated history after preemption.
fn kindOf(seq: *const request.Sequence, n_work: u32) Kind {
    assert(n_work > 0 and n_work <= request.nWork(seq));
    const prompt_done = seq.n_computed >= seq.n_prompt;
    const at_end = seq.n_computed + n_work == seq.n;
    return if (prompt_done and at_end and n_work == 1) .decode else .prefill;
}

fn blocksHeld(req: *const request.Request) u32 {
    var n: u32 = 0;
    for (req.tables) |table| n += table.n;
    for (req.units, req.pending) |st, *pending| {
        n += st.n_ring + @intFromBool(st.live != kv_pool.null_block);
        if (!request.isPending(pending)) continue;
        for (pending.write) |id| n += @intFromBool(id != scratch_unit and id != st.live);
        n += @intFromBool(pending.ckpt.id != scratch_unit);
    }
    return n;
}

fn preemptRunning(s: *Scheduler, idx: u32) void {
    assert(idx < s.n_running);
    const req = &s.reqs.requests[s.running[idx]];
    freeBlocks(s, req);
    request.preempt(req);
    s.build().building.n_preempted += 1;
    removeRunning(s, idx);
    pushFrontWaiting(s, req.id);
    assert(req.state == .waiting);
}

fn emitPlan(s: *Scheduler) void {
    const a = s.build();
    const p = &a.plan;
    p.n_reqs = 0;
    p.n_tokens = 0;
    p.query_start_loc[0] = 0;
    for ([_]Kind{ .decode, .prefill }) |want| {
        for (a.sched[0..s.n_sched]) |entry| {
            if (entry.kind == want) emitEntry(s, entry);
        }
    }
    assert(p.n_reqs == s.n_sched);
    assert(p.query_start_loc[p.n_reqs] == p.n_tokens);
}

fn emitEntry(s: *Scheduler, entry: Entry) void {
    const p = &s.build().plan;
    const req = &s.reqs.requests[entry.req_id];
    const seq = &req.seq;
    if (s.building_ahead) assertNotInFlight(s, req) else assert(req.n_in_flight == 0);
    const i = p.n_reqs;
    const start = p.n_tokens;
    assert(start + entry.n_work + entry.n_extra <= p.input_ids.len);
    p.entries[i] = entry;
    const n_rows = entry.n_work + entry.n_extra;
    for (0..n_rows) |j| {
        const pos = seq.n_computed + @as(u32, @intCast(j));
        p.input_ids[start + j] = if (j < entry.n_work) seq.tokens[pos] else no_token;
        p.positions[start + j] = pos;
        for (s.reqs.cfg.groups, req.tables, 0..) |group, table, g| {
            // per_seq rows have no slot: their state goes through p.state (below).
            p.slot_mapping[g][start + j] = if (group.kind == .per_seq) kv_pool.null_block else slotFor(group, table, pos);
        }
    }
    for (s.reqs.cfg.groups, req.pending, p.state) |group, pending, idx| {
        if (group.kind != .per_seq) continue;
        assert(pending.write.len == p.write_width);
        idx.read[i] = pending.read;
        @memcpy(idx.write[i * p.write_width ..][0..p.write_width], pending.write);
        idx.ckpt[i] = pending.ckpt.id;
        idx.ckpt_row[i] = pending.ckpt_row;
    }
    p.seq_start[i] = seq.n_computed;
    p.emits[i] = @intFromBool(seq.n_computed + entry.n_work == seq.n);
    for (req.tables, 0..) |table, g| {
        const row = p.block_tables[g][i * p.max_blocks_per_req ..][0..p.max_blocks_per_req];
        @memset(row, 0);
        @memcpy(row[0..table.n], table.ids[0..table.n]);
    }
    p.seq_lens[i] = seq.n_computed + n_rows;
    p.temperatures[i] = req.params.temperature;
    p.top_ks[i] = req.params.top_k;
    p.mm_hashes[i] = req.mm_hash;
    p.n_tokens += n_rows;
    p.query_start_loc[i + 1] = p.n_tokens;
    p.n_reqs += 1;
    assert(p.n_reqs <= p.entries.len);
}

fn slotFor(group: request.GroupSpec, table: request.BlockTable, pos: u32) u32 {
    assert(group.kind == .per_token);
    // Unit pos / stride: for a stride-k group the slot names the compressed unit the token
    // belongs to (the model writes it when the unit's last token is computed).
    const unit = pos / group.stride;
    const b = unit / group.block_size;
    assert(b < table.n);
    assert(table.ids[b] != kv_pool.null_block); // a written row is never slid out
    return table.ids[b] * group.block_size + unit % group.block_size;
}

// ---- events ------------------------------------------------------------------------------

fn recordPlan(s: *Scheduler) void {
    const a = s.build();
    const p = &a.plan;
    const b = &a.building;
    b.step = s.step;
    b.n_running = s.n_running;
    b.n_waiting = s.n_waiting;
    b.n_tokens = p.n_tokens;
    b.is_idle = p.n_tokens == 0;
    b.order = @intFromEnum(s.cfg.order);
    b.config_hash = s.config_hash;
    // Slab-denominated (docs/kv-groups.md "The slab model"); with pages_per_slab == 1 for every
    // group these are the page counts they were before.
    b.kv_free = kv_pool.nFreeSlabs(s.kv);
    b.kv_used = @as(u32, @intCast(s.kv.slabs.len)) - b.kv_free;
    for (p.entries[0..p.n_reqs]) |entry| {
        switch (entry.kind) {
            .decode => b.n_decode_reqs += 1,
            .prefill => b.n_prefill_reqs += 1,
        }
        b.n_extra_rows += entry.n_extra;
    }
    assert(b.n_decode_reqs + b.n_prefill_reqs == p.n_reqs);
}

fn publishStep(s: *Scheduler) void {
    const b = &s.live().building;
    assert(b.step > 0 and b.step <= s.step);
    s.event = b.*;
    b.* = std.mem.zeroes(events.StepEvent);
    assert(s.event.step <= s.step);
}

// ---- lifecycle ---------------------------------------------------------------------------

/// Closes a request as grammar_dead_end: its matcher rejected the token this commit just
/// appended (c_api.zig's commit path, right after scheduler.commit returns -- see
/// request.State.grammar_dead_end's doc comment). Unlike `cancel`, this always runs after
/// commit() has fully resolved the entry (planned/planned_ahead are already false, blocks
/// already freed if the request finished by EOS/length in the same commit), so there is no
/// in-flight-plan case to special-case: a request still `running` here is exactly the state
/// `finish` handles, just with a state neither `finished_eos` nor `finished_length` describes.
/// A no-op if the request already finished this same commit (EOS/length raced the dead end;
/// keep whichever the scheduler recorded first) or is no longer owned (already released).
///
/// Runs strictly after scheduler.commit() returns (c_api.zig's commitUnlocked calls
/// commitAcceptGrammar, which calls this, only after scheduler.commit has already run its own
/// compactRunning()). That earlier compactRunning
/// still saw this request as `.running` (this function is what changes that), so s.running[]
/// still names it: without a second compactRunning() here, the next plan() calls planRunning()
/// on a req_id whose state is grammar_dead_end, not running, tripping planRunning's own
/// `assert(req.state == .running)` (a real, previously-unexercised crash -- c_api.zig's own
/// grammar test never calls kelpie_plan again after observing grammar_dead_end, so it never
/// hit this). compactRunning is safe to call unconditionally like `cancel` does, even though
/// this function may run several times per commit (once per dead-ended entry in
/// commitAcceptGrammar's loop) -- it is idempotent, just O(n_running) per call.
pub fn markGrammarDeadEnd(s: *Scheduler, req_id: u32) void {
    const req = &s.reqs.requests[req_id];
    if (!req.owned or request.isFinished(req)) return;
    assert(req.state == .running and !req.planned and !req.planned_ahead);
    freeBlocks(s, req);
    s.live().building.n_finished += 1;
    close(s, req, .grammar_dead_end);
    compactRunning(s);
}

fn finish(s: *Scheduler, req: *request.Request, state: request.State) void {
    assert(req.state == .running);
    assert(state == .finished_eos or state == .finished_length);
    freeBlocks(s, req);
    s.live().building.n_finished += 1;
    close(s, req, state);
}

/// The one writer of the terminal state and the RequestEvent's summary fields (finish and cancel).
/// Cancelling a request that already finished keeps the event it finished with.
fn close(s: *Scheduler, req: *request.Request, state: request.State) void {
    assert(request.isFinished(req) or req.event.t_finish_ns == 0);
    const finished_before = request.isFinished(req);
    req.state = state;
    req.next_extra = 0;
    if (finished_before) return;
    req.event.t_finish_ns = events.now(&s.clock);
    req.event.last_step = s.step;
    req.event.n_prompt = req.seq.n_prompt;
    req.event.n_gen = request.nGenerated(&req.seq);
    req.event.n_preemptions = req.n_preemptions;
    req.event.finish_reason = @intFromEnum(state);
    assert(request.isFinished(req));
}

/// Blocks shared with another request stay allocated; the rest keep their hashes on the free list.
/// Holes (null block, slid out of a window) are skipped: they were freed when they slid.
fn freeBlocks(s: *Scheduler, req: *request.Request) void {
    const n_free_before = kv_pool.nFreeSlabs(s.kv);
    var n_released: u32 = 0;
    var g = req.tables.len;
    while (g > 0) {
        g -= 1;
        if (s.reqs.cfg.groups[g].kind == .per_seq) {
            n_released += blocksHeldSeq(req, @intCast(g));
            freeState(s, req, @intCast(g));
            continue;
        }
        const table = &req.tables[g];
        var i = table.n;
        while (i > 0) {
            i -= 1;
            if (table.ids[i] == kv_pool.null_block) continue;
            prefix.release(s.kv, @intCast(g), table.ids[i .. i + 1]);
            n_released += 1;
        }
        table.n = 0;
    }
    assert(kv_pool.nFreeSlabs(s.kv) <= n_free_before + n_released);
}

/// Units one per_seq group holds for the request (freeBlocks' accounting).
fn blocksHeldSeq(req: *const request.Request, g: u32) u32 {
    const st = req.units[g];
    var n: u32 = st.n_ring + @intFromBool(st.live != kv_pool.null_block);
    const pending = &req.pending[g];
    if (request.isPending(pending)) {
        for (pending.write) |id| n += @intFromBool(id != scratch_unit and id != st.live);
        n += @intFromBool(pending.ckpt.id != scratch_unit);
    }
    return n;
}

fn compactRunning(s: *Scheduler) void {
    const n_before = s.n_running;
    var n: u32 = 0;
    for (s.running[0..s.n_running]) |id| {
        if (s.reqs.requests[id].state != .running) continue;
        s.running[n] = id;
        n += 1;
    }
    s.n_running = n;
    assert(n <= n_before);
}

fn removeRunning(s: *Scheduler, idx: u32) void {
    assert(idx < s.n_running);
    std.mem.copyForwards(u32, s.running[idx .. s.n_running - 1], s.running[idx + 1 .. s.n_running]);
    s.n_running -= 1;
}

// ---- waiting ring ------------------------------------------------------------------------

fn waitingSlot(s: *const Scheduler, i: u32) *u32 {
    assert(i < s.waiting.len);
    return &s.waiting[(s.waiting_head + i) % @as(u32, @intCast(s.waiting.len))];
}

fn pushBackWaiting(s: *Scheduler, id: u32) void {
    assert(s.n_waiting < s.waiting.len);
    waitingSlot(s, s.n_waiting).* = id;
    s.n_waiting += 1;
}

fn pushFrontWaiting(s: *Scheduler, id: u32) void {
    assert(s.n_waiting < s.waiting.len);
    const cap: u32 = @intCast(s.waiting.len);
    s.waiting_head = (s.waiting_head + cap - 1) % cap;
    s.waiting[s.waiting_head] = id;
    s.n_waiting += 1;
}

fn popFrontWaiting(s: *Scheduler) u32 {
    assert(s.n_waiting > 0);
    const id = s.waiting[s.waiting_head];
    s.waiting_head = (s.waiting_head + 1) % @as(u32, @intCast(s.waiting.len));
    s.n_waiting -= 1;
    return id;
}

fn removeWaiting(s: *Scheduler, id: u32) void {
    assert(s.n_waiting > 0);
    var i: u32 = 0;
    while (waitingSlot(s, i).* != id) : (i += 1) assert(i + 1 < s.n_waiting);
    while (i + 1 < s.n_waiting) : (i += 1) waitingSlot(s, i).* = waitingSlot(s, i + 1).*;
    s.n_waiting -= 1;
}

// ---- init --------------------------------------------------------------------------------

fn initPlan(s: *Scheduler, allocator: std.mem.Allocator) !void {
    const cfg = s.cfg;
    const groups = s.reqs.cfg.groups;
    // At least 1 so a model of per_seq groups only still has a (null-filled) table column.
    var max_blocks: u32 = 1;
    for (groups) |group| max_blocks = @max(max_blocks, request.capacityRows(group, s.reqs.cfg.max_seq_len, s.reqs.cfg.max_extra));

    // Both arenas come from the one allocator, so "how a plan buffer is sized" has a single
    // writer (it grew a second one silently once already -- docs/friction-2026-09-09.md 1).
    var n_ready: usize = 0;
    errdefer for (s.arenas[0..n_ready]) |*a| freeArena(allocator, a);
    for (&s.arenas) |*a| {
        a.* = try allocArena(allocator, cfg, groups, max_blocks, 1 + s.reqs.cfg.max_extra, s.zero_units);
        n_ready += 1;
    }
    assert(s.live().plan.block_tables.len == groups.len);
}

fn allocArena(allocator: std.mem.Allocator, cfg: Config, groups: []const request.GroupSpec, max_blocks: u32, write_width: u32, zero_units: []const u32) !PlanArena {
    const sched = try allocator.alloc(Entry, cfg.max_batch_reqs);
    errdefer allocator.free(sched);
    const p = try allocPlan(allocator, cfg, groups, max_blocks, write_width, zero_units);
    return .{
        .plan = p.plan,
        .sched = sched,
        .building = std.mem.zeroes(events.StepEvent),
        .slots = p.slots,
        .tables = p.tables,
        .state_buf = p.state_buf,
    };
}

fn freeArena(allocator: std.mem.Allocator, a: *PlanArena) void {
    freePlan(allocator, &a.plan, a.slots, a.tables, a.state_buf);
    allocator.free(a.sched);
}

const AllocatedPlan = struct { plan: Plan, slots: []u32, tables: []u32, state_buf: []u32 };

/// Plan buffers are sized to the *bucketed* capacity, not the raw maxima: kelpie_plan emits a
/// padded plan (arrays bucket(n_tokens) / bucket(n_reqs) long) and the ladder rounds up past
/// max_batch_* whenever those are not themselves powers of two (max_batch_reqs = 3 pads to 4).
/// The pad region must be in bounds for every reachable plan, so it is allocated up front.
fn allocPlan(allocator: std.mem.Allocator, cfg: Config, groups: []const request.GroupSpec, max_blocks: u32, write_width: u32, zero_units: []const u32) !AllocatedPlan {
    const cap_tokens = buckets.bucket(cfg.max_batch_tokens);
    const cap_reqs = buckets.bucket(cfg.max_batch_reqs);
    const entries = try allocator.alloc(Entry, cap_reqs);
    errdefer allocator.free(entries);
    const input_ids = try allocator.alloc(u32, cap_tokens);
    errdefer allocator.free(input_ids);
    const positions = try allocator.alloc(u32, cap_tokens);
    errdefer allocator.free(positions);
    const query_start_loc = try allocator.alloc(u32, cap_reqs + 1);
    errdefer allocator.free(query_start_loc);
    const seq_lens = try allocator.alloc(u32, cap_reqs);
    errdefer allocator.free(seq_lens);
    const temperatures = try allocator.alloc(f32, cap_reqs);
    errdefer allocator.free(temperatures);
    const top_ks = try allocator.alloc(u32, cap_reqs);
    errdefer allocator.free(top_ks);
    const mm_hashes = try allocator.alloc(u64, cap_reqs);
    errdefer allocator.free(mm_hashes);
    const slots = try allocator.alloc(u32, groups.len * cap_tokens);
    errdefer allocator.free(slots);
    const tables = try allocator.alloc(u32, groups.len * cap_reqs * max_blocks);
    errdefer allocator.free(tables);
    const slot_mapping = try allocator.alloc([]u32, groups.len);
    errdefer allocator.free(slot_mapping);
    const block_tables = try allocator.alloc([]u32, groups.len);
    errdefer allocator.free(block_tables);
    for (slot_mapping, block_tables, 0..) |*sm, *bt, g| {
        sm.* = slots[g * cap_tokens ..][0..cap_tokens];
        const row_len = cap_reqs * max_blocks;
        bt.* = tables[g * row_len ..][0..row_len];
    }
    const seq_start = try allocator.alloc(u32, cap_reqs);
    errdefer allocator.free(seq_start);
    const emits = try allocator.alloc(u8, cap_reqs);
    errdefer allocator.free(emits);
    var n_seq_groups: u32 = 0;
    for (groups) |group| n_seq_groups += @intFromBool(group.kind == .per_seq);
    // Per per_seq group: read, ckpt, ckpt_row (one each per entry) and write_width writes.
    const per_group = cap_reqs * (3 + write_width);
    const state_buf = try allocator.alloc(u32, n_seq_groups * per_group);
    errdefer allocator.free(state_buf);
    const state = try allocator.alloc(StateIdx, groups.len);
    errdefer allocator.free(state);
    var cursor: usize = 0;
    for (state, groups) |*idx, group| {
        if (group.kind != .per_seq) {
            idx.* = .{ .read = &.{}, .write = &.{}, .ckpt = &.{}, .ckpt_row = &.{} };
            continue;
        }
        const buf = state_buf[cursor..][0..per_group];
        idx.* = .{
            .read = buf[0..cap_reqs],
            .ckpt = buf[cap_reqs..][0..cap_reqs],
            .ckpt_row = buf[2 * cap_reqs ..][0..cap_reqs],
            .write = buf[3 * cap_reqs ..][0 .. cap_reqs * write_width],
        };
        cursor += per_group;
    }
    assert(cursor == state_buf.len);
    return .{ .plan = .{ .n_reqs = 0, .n_tokens = 0, .max_blocks_per_req = max_blocks, .entries = entries, .input_ids = input_ids, .positions = positions, .query_start_loc = query_start_loc, .seq_lens = seq_lens, .temperatures = temperatures, .top_ks = top_ks, .mm_hashes = mm_hashes, .slot_mapping = slot_mapping, .block_tables = block_tables, .seq_start = seq_start, .emits = emits, .state = state, .write_width = write_width, .zero_units = zero_units }, .slots = slots, .tables = tables, .state_buf = state_buf };
}

fn freePlan(allocator: std.mem.Allocator, p: *Plan, slots: []u32, tables: []u32, state_buf: []u32) void {
    allocator.free(p.state);
    allocator.free(state_buf);
    allocator.free(p.emits);
    allocator.free(p.seq_start);
    allocator.free(p.block_tables);
    allocator.free(p.slot_mapping);
    allocator.free(tables);
    allocator.free(slots);
    allocator.free(p.mm_hashes);
    allocator.free(p.top_ks);
    allocator.free(p.temperatures);
    allocator.free(p.seq_lens);
    allocator.free(p.query_start_loc);
    allocator.free(p.positions);
    allocator.free(p.input_ids);
    allocator.free(p.entries);
}
