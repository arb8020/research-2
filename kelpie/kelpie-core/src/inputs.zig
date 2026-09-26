//! Step-boundary inputs (docs/design-multigpu.md 2.3 + section 8): the inbox callers write to,
//! the one wire format a boundary drains it into, and the decoder every rank applies from.
//!
//!   caller thread (edge)       step thread, every boundary
//!   submit / cancel / set  ->  Inbox.drain -> bytes -> [exchange] -> validate -> apply (c_api.zig)
//!   poll (first finish)    ->  release op
//!
//! The inbox has its own mutex and never takes loop.mutex; the step thread takes loop.mutex
//! first and the inbox mutex second (lock order: loop -> inbox), never the other way round.
//! World 1 runs exactly this path: the edge is the only rank and the exchange is the identity.
//!
//! The Inbox is edge state. It owns the id LEDGER: which request ids are free, reserved by a
//! submit op not yet applied, or live in the core -- the edge's view, which lets submit pick an id
//! synchronously (and return Full synchronously, section 8 S1) without reading core state that the
//! step thread is mutating. Every op names (id, gen): gen is bumped each time an id is reserved,
//! so an op aimed at an earlier occupant of the slot is a no-op when it applies (B2).
//!
//! Everything on the wire is little-endian u32 words; the batch is word-aligned end to end.

const std = @import("std");
const assert = std.debug.assert;
const request = @import("request.zig");
const scheduler = @import("scheduler.zig");

/// 2: the submit op carries top_k (its last fixed word).
pub const wire_version: u32 = 2;
/// Header.flags: the edge is closing; every rank's loop returns at this boundary.
pub const flag_stop: u32 = 1;

/// The first 12 words of every batch. `boundary` numbers the drains (1-based): the plan right
/// after boundary b is step b, which is what makes KelpieSetResult.apply_step exact (S3).
/// prev_digest / prev_payload_hash are the edge's: a follower compares them with its own (the
/// free, one-step-lagged divergence check).
pub const Header = extern struct {
    version: u32,
    n_ops: u32,
    n_words: u32, // body words after the header
    flags: u32,
    boundary: u64,
    prev_digest: u64,
    prev_payload_hash: u64,
    n_rejected_full: u32, // edge submits that returned Full since the previous boundary (StepEvent)
    reserved: u32 = 0,
};
pub const header_words: u32 = @sizeOf(Header) / 4;
comptime {
    assert(@sizeOf(Header) == 48);
}

pub const Kind = enum(u32) { submit = 1, cancel = 2, release = 3, knob = 4, swap = 5, grammar_prepare = 6 };

/// Words before the variable parts of each op.
const submit_fixed: u32 = 15;
const ref_words: u32 = 3;
const knob_words: u32 = 4;
const swap_words: u32 = 4;
const prepare_fixed: u32 = 4;

pub const Ref = struct { id: u32, gen: u32 };

pub const Submit = struct {
    id: u32,
    gen: u32,
    max_new: u32,
    temperature: f32,
    top_k: u32,
    mm: request.Mm,
    grammar_key: u64,
    t_arrival_ns: u64,
    stop: []const u32,
    prompt: []const u32,
};

pub const Swap = struct { epoch: u64, drain: bool };
pub const GrammarPrepare = struct { key: u64, source: []const u8 };

/// One decoded op; slices point into the batch.
pub const Op = union(Kind) {
    submit: Submit,
    cancel: Ref,
    release: Ref,
    knob: scheduler.Knob,
    swap: Swap,
    grammar_prepare: GrammarPrepare,
};

pub const ParseError = error{ Truncated, BadVersion, BadKind, BadLength, BadValue, TrailingWords };

/// What a well-formed batch may contain on this engine. A follower must reject anything its own
/// storage cannot hold, before applying any op (validate runs over the whole batch first).
pub const Limits = struct {
    max_requests: u32,
    max_seq_len: u32,
    max_source_bytes: u32,
    /// KelpieConfig.vocab_size: a submit's top_k must not exceed it (0 = unchecked).
    vocab_size: u32,
};

/// Validates the whole batch and returns its header. After this, `Reader.next` cannot fail.
pub fn validate(words: []const u32, limits: Limits, sched: *const scheduler.Scheduler) ParseError!Header {
    if (words.len < header_words) return error.Truncated;
    const header = headerOf(words);
    if (header.version != wire_version) return error.BadVersion;
    if (header.n_words != words.len - header_words) return error.BadLength;
    var r = Reader{ .words = words[header_words..], .left = header.n_ops };
    while (try r.nextChecked(limits)) |op| {
        switch (op) {
            .knob => |k| scheduler.validateKnob(sched, k) catch return error.BadValue,
            else => {},
        }
    }
    if (r.pos != r.words.len) return error.TrailingWords;
    return header;
}

pub fn headerOf(words: []const u32) Header {
    assert(words.len >= header_words);
    var h: Header = undefined;
    @memcpy(std.mem.asBytes(&h), std.mem.sliceAsBytes(words[0..header_words]));
    return h;
}

/// Ops in batch order. Construct only over a batch `validate` accepted.
pub const Reader = struct {
    words: []const u32,
    pos: usize = 0,
    left: u32,

    pub fn of(words: []const u32) Reader {
        const header = headerOf(words);
        return .{ .words = words[header_words..], .left = header.n_ops };
    }

    pub fn next(r: *Reader) ?Op {
        const unchecked = Limits{ .max_requests = std.math.maxInt(u32), .max_seq_len = std.math.maxInt(u32), .max_source_bytes = std.math.maxInt(u32), .vocab_size = 0 };
        return r.nextChecked(unchecked) catch unreachable; // validate() accepted this batch
    }

    fn take(r: *Reader, n: usize) ParseError![]const u32 {
        if (r.words.len - r.pos < n) return error.Truncated;
        defer r.pos += n;
        return r.words[r.pos..][0..n];
    }

    fn nextChecked(r: *Reader, limits: Limits) ParseError!?Op {
        if (r.left == 0) return null;
        r.left -= 1;
        const kind_word = (try r.take(1))[0];
        const kind = std.meta.intToEnum(Kind, kind_word) catch return error.BadKind;
        switch (kind) {
            .submit => {
                const w = try r.take(submit_fixed - 1);
                const id, const gen, const n_prompt, const max_new = .{ w[0], w[1], w[2], w[3] };
                const n_stop = w[8];
                if (id >= limits.max_requests) return error.BadValue;
                if (n_prompt == 0 or n_stop > request.max_stop_tokens) return error.BadLength;
                if (@as(u64, n_prompt) + max_new > limits.max_seq_len) return error.BadLength;
                const mm = request.Mm{ .hash = u64Of(w[5], w[6]), .start = w[7] };
                if (mm.hash != 0 and mm.start >= n_prompt) return error.BadValue;
                const temperature: f32 = @bitCast(w[4]);
                if (!request.validTemperature(temperature)) return error.BadValue;
                const top_k = w[13];
                if (!request.validTopK(top_k, limits.vocab_size)) return error.BadValue;
                const stop = try r.take(n_stop);
                const prompt = try r.take(n_prompt);
                return .{ .submit = .{
                    .id = id,
                    .gen = gen,
                    .max_new = max_new,
                    .temperature = temperature,
                    .top_k = top_k,
                    .mm = mm,
                    .grammar_key = u64Of(w[9], w[10]),
                    .t_arrival_ns = u64Of(w[11], w[12]),
                    .stop = stop,
                    .prompt = prompt,
                } };
            },
            .cancel, .release => {
                const w = try r.take(ref_words - 1);
                if (w[0] >= limits.max_requests) return error.BadValue;
                const ref = Ref{ .id = w[0], .gen = w[1] };
                return if (kind == .cancel) .{ .cancel = ref } else .{ .release = ref };
            },
            .knob => {
                const w = try r.take(knob_words - 1);
                return .{ .knob = knobOf(w[0], w[1], @bitCast(w[2])) orelse return error.BadValue };
            },
            .swap => {
                const w = try r.take(swap_words - 1);
                if (w[2] > 1) return error.BadValue;
                return .{ .swap = .{ .epoch = u64Of(w[0], w[1]), .drain = w[2] == 1 } };
            },
            .grammar_prepare => {
                const w = try r.take(prepare_fixed - 1);
                const n_source = w[2];
                if (n_source > limits.max_source_bytes) return error.BadLength;
                const body = try r.take((n_source + 3) / 4);
                return .{ .grammar_prepare = .{ .key = u64Of(w[0], w[1]), .source = std.mem.sliceAsBytes(body)[0..n_source] } };
            },
        }
    }
};

/// The wire's knob encoding: (kind ordinal, u32 value, f32 value), the same triple KelpieKnob
/// carries. null for an out-of-range kind or value.
pub fn knobOf(kind: u32, u32_value: u32, f32_value: f32) ?scheduler.Knob {
    const Tag = std.meta.Tag(scheduler.Knob);
    const tag = std.meta.intToEnum(Tag, kind) catch return null;
    return switch (tag) {
        .order => if (u32_value > 1) null else .{ .order = if (u32_value == 0) .running_first else .waiting_first },
        .reserve_ratio => .{ .reserve_ratio = f32_value },
        .max_batch_tokens => .{ .max_batch_tokens = u32_value },
        .max_batch_reqs => .{ .max_batch_reqs = u32_value },
        .prefix_cache => if (u32_value > 1) null else .{ .prefix_cache = u32_value != 0 },
    };
}

fn knobWords(knob: scheduler.Knob) [3]u32 {
    const kind: u32 = @intFromEnum(std.meta.activeTag(knob));
    return switch (knob) {
        .order => |v| .{ kind, @intFromEnum(v), 0 },
        .reserve_ratio => |v| .{ kind, 0, @bitCast(v) },
        .max_batch_tokens, .max_batch_reqs => |v| .{ kind, v, 0 },
        .prefix_cache => |v| .{ kind, @intFromBool(v), 0 },
    };
}

fn u64Of(lo: u32, hi: u32) u64 {
    return @as(u64, hi) << 32 | lo;
}
fn lo32(v: u64) u32 {
    return @truncate(v);
}
fn hi32(v: u64) u32 {
    return @truncate(v >> 32);
}

/// Wyhash of a batch's bytes: what the plan digest folds in as "the batch applied before it".
pub fn hashOf(words: []const u32) u64 {
    return std.hash.Wyhash.hash(0, std.mem.sliceAsBytes(words));
}

// ---- the inbox (edge side) -------------------------------------------------------------------

/// The ledger's view of one request id.
///   free      reservable: nobody holds it, or a queued op releases it before anything queued
///             after it can use it (FIFO: S1's "no release lag")
///   reserved  a submit op for (id, gen) is queued and not yet applied
///   live      the core holds (id, gen)
pub const SlotState = enum(u8) { free, reserved, live };
pub const Slot = struct {
    gen: u32 = 0,
    state: SlotState = .free,
    /// A cancel for (id, gen) is queued: poll reports cancelled from now on, as a cancel did
    /// when it mutated the core on the spot.
    cancel_queued: bool = false,
};

const PendingSubmit = struct {
    id: u32,
    gen: u32,
    n_prompt: u32,
    max_new: u32,
    temperature: f32,
    top_k: u32,
    mm: request.Mm,
    grammar_key: u64,
    t_arrival_ns: u64,
    n_stop: u32,
    stop: [request.max_stop_tokens]u32,
};
const Pending = union(Kind) {
    submit: PendingSubmit,
    cancel: Ref,
    release: Ref,
    knob: scheduler.Knob,
    swap: Swap,
    grammar_prepare: struct { key: u64, n_source: u32, index: u32 },
};

pub const knob_capacity = 64;
pub const prepare_capacity = 8;
pub const max_source_bytes: u32 = 64 * 1024;

/// A launch context registered for a swap epoch before the swap op is pushed (S6). The loop
/// installs it when the op applies. Opaque here: c_api.zig owns the types.
pub const SwapReg = struct { epoch: u64, launch: *const anyopaque, captured: *anyopaque, drain: bool };

pub const Inbox = struct {
    mutex: std.Thread.Mutex = .{},
    max_requests: u32,
    max_seq_len: u32,
    /// With overlap a boundary can find the cancelled request still named by the plan in flight,
    /// and scheduler.cancel then holds its slot until that commit: the ledger cannot count the
    /// slot free when the cancel is pushed, only once the core has released it (reconcile).
    overlap: bool,
    ops: []Pending,
    n_ops: u32,
    slots: []Slot,
    /// Reservable ids, LIFO -- the same order request.Pool's free list hands them out, so ids
    /// at world 1 are what they were before the inbox existed.
    free: []u32,
    n_free: u32,
    /// [max_requests * max_seq_len]: the prompt of a queued submit, at id * max_seq_len.
    staging: []u32,
    sources: [][max_source_bytes]u8,
    n_prepare: u32,
    /// The config once every queued knob has applied (KelpieSetResult.config_hash).
    pending_cfg: scheduler.Config,
    n_knobs: u32,
    /// Boundaries drained so far. An op pushed now applies at boundary `boundary + 1`.
    boundary: u64,
    n_rejected_full: u32,
    swap: ?SwapReg,
    swap_epoch: u64,

    pub fn init(allocator: std.mem.Allocator, max_requests: u32, max_seq_len: u32, cfg: scheduler.Config) !Inbox {
        assert(max_requests > 0 and max_seq_len > 0);
        // Every op an inbox can hold at once: a submit per id, a cancel and a release per id,
        // the knobs, the grammar prepares and one swap.
        const cap_ops = 3 * max_requests + knob_capacity + prepare_capacity + 1;
        const ops = try allocator.alloc(Pending, cap_ops);
        errdefer allocator.free(ops);
        const slots = try allocator.alloc(Slot, max_requests);
        errdefer allocator.free(slots);
        const free = try allocator.alloc(u32, max_requests);
        errdefer allocator.free(free);
        const staging = try allocator.alloc(u32, @as(usize, max_requests) * max_seq_len);
        errdefer allocator.free(staging);
        const sources = try allocator.alloc([max_source_bytes]u8, prepare_capacity);
        @memset(slots, .{});
        for (free, 0..) |*id, i| id.* = @intCast(i);
        return .{
            .max_requests = max_requests,
            .max_seq_len = max_seq_len,
            .overlap = cfg.overlap,
            .ops = ops,
            .n_ops = 0,
            .slots = slots,
            .free = free,
            .n_free = max_requests,
            .staging = staging,
            .sources = sources,
            .n_prepare = 0,
            .pending_cfg = cfg,
            .n_knobs = 0,
            .boundary = 0,
            .n_rejected_full = 0,
            .swap = null,
            .swap_epoch = 0,
        };
    }

    pub fn deinit(ib: *Inbox, allocator: std.mem.Allocator) void {
        allocator.free(ib.sources);
        allocator.free(ib.staging);
        allocator.free(ib.free);
        allocator.free(ib.slots);
        allocator.free(ib.ops);
        ib.* = undefined;
    }

    /// Worst-case batch size in words: every op the inbox can hold, every staged prompt.
    pub fn capWords(ib: *const Inbox) usize {
        const per_id = submit_fixed + request.max_stop_tokens + 2 * ref_words;
        return header_words + @as(usize, ib.max_requests) * (per_id + ib.max_seq_len) +
            knob_capacity * knob_words + prepare_capacity * (prepare_fixed + max_source_bytes / 4) + swap_words;
    }

    fn push(ib: *Inbox, op: Pending) void {
        assert(ib.n_ops < ib.ops.len); // sized for the worst case in init
        ib.ops[ib.n_ops] = op;
        ib.n_ops += 1;
    }

    pub const SubmitArgs = struct {
        prompt: []const u32,
        max_new: u32,
        temperature: f32,
        top_k: u32,
        mm: request.Mm,
        stop: []const u32,
        grammar_key: u64,
        t_arrival_ns: u64,
    };

    /// Reserves an id, stages the prompt and queues the submit op. The caller has already
    /// refused TooLong / ExceedsKvPool / Draining (those never create an op, S1).
    /// Full before TooLong, as request.acquire checks them.
    pub fn submit(ib: *Inbox, args: SubmitArgs) error{ Full, TooLong }!u32 {
        ib.mutex.lock();
        defer ib.mutex.unlock();
        assert(args.prompt.len > 0);
        assert(args.stop.len <= request.max_stop_tokens);
        if (ib.n_free == 0) {
            ib.n_rejected_full += 1;
            return error.Full;
        }
        if (args.prompt.len + @as(u64, args.max_new) > ib.max_seq_len) return error.TooLong;
        ib.n_free -= 1;
        const id = ib.free[ib.n_free];
        const slot = &ib.slots[id];
        assert(slot.state == .free);
        slot.* = .{ .gen = slot.gen +% 1, .state = .reserved, .cancel_queued = false };
        @memcpy(ib.staging[@as(usize, id) * ib.max_seq_len ..][0..args.prompt.len], args.prompt);
        var p = PendingSubmit{
            .id = id,
            .gen = slot.gen,
            .n_prompt = @intCast(args.prompt.len),
            .max_new = args.max_new,
            .temperature = args.temperature,
            .top_k = args.top_k,
            .mm = args.mm,
            .grammar_key = args.grammar_key,
            .t_arrival_ns = args.t_arrival_ns,
            .n_stop = @intCast(args.stop.len),
            .stop = undefined,
        };
        @memcpy(p.stop[0..args.stop.len], args.stop);
        ib.push(.{ .submit = p });
        return id;
    }

    /// The generation the ledger holds for `id`: a caller that records it at submit can cancel
    /// exactly that request later (cancelGen), and a cancel after the id is reused is a no-op.
    pub fn generation(ib: *Inbox, id: u32) u32 {
        ib.mutex.lock();
        defer ib.mutex.unlock();
        return ib.slots[id].gen;
    }

    /// Queues a cancel of (id, gen), gen = the current occupant when null. A no-op for a free id,
    /// a stale gen, or a cancel already queued. Returns whether an op was queued.
    pub fn cancel(ib: *Inbox, id: u32, gen: ?u32) bool {
        ib.mutex.lock();
        defer ib.mutex.unlock();
        const slot = &ib.slots[id];
        if (gen) |g| if (g != slot.gen) return false;
        if (slot.state == .free or slot.cancel_queued) return false;
        slot.cancel_queued = true;
        if (slot.state == .reserved and ib.dropSubmit(id, slot.gen)) {
            // Its submit is still queued: drop the op itself (B2: the reservation is cancelled).
            // Nothing reaches the core, so the id is free at once, and a burst of submit + cancel
            // pairs between two boundaries never grows the inbox. (Drained but not yet applied:
            // the cancel op below follows the submit, FIFO.)
            ib.freeLocked(id);
            return true;
        }
        ib.push(.{ .cancel = .{ .id = id, .gen = slot.gen } });
        // Without overlap nothing is planned at a boundary, so the cancel releases the slot the
        // moment it applies: anything queued after it may have the id (S1: no release lag).
        if (!ib.overlap) ib.freeLocked(id);
        return true;
    }

    /// What poll may report for `id` before looking at the core (B1).
    pub const View = enum { core, not_applied, cancelled };
    pub fn pollView(ib: *Inbox, id: u32) View {
        ib.mutex.lock();
        defer ib.mutex.unlock();
        const slot = ib.slots[id];
        if (slot.cancel_queued) return .cancelled;
        if (slot.state == .reserved) return .not_applied;
        return .core;
    }

    /// A poll saw (id)'s current occupant finished: queue its release, once. Only for a live id
    /// (a reserved one has nothing in the core yet; a free one is released or being released).
    pub fn pollFinished(ib: *Inbox, id: u32) void {
        ib.mutex.lock();
        defer ib.mutex.unlock();
        const slot = &ib.slots[id];
        if (slot.state != .live or slot.cancel_queued) return;
        ib.push(.{ .release = .{ .id = id, .gen = slot.gen } });
        ib.freeLocked(id);
    }

    /// Removes the queued submit for (id, gen); false when it was drained already.
    fn dropSubmit(ib: *Inbox, id: u32, gen: u32) bool {
        for (ib.ops[0..ib.n_ops], 0..) |op, i| switch (op) {
            .submit => |p| if (p.id == id and p.gen == gen) {
                std.mem.copyForwards(Pending, ib.ops[i .. ib.n_ops - 1], ib.ops[i + 1 .. ib.n_ops]);
                ib.n_ops -= 1;
                return true;
            },
            else => {},
        };
        return false;
    }

    fn freeLocked(ib: *Inbox, id: u32) void {
        const slot = &ib.slots[id];
        assert(slot.state != .free);
        slot.state = .free;
        assert(ib.n_free < ib.max_requests);
        ib.free[ib.n_free] = id;
        ib.n_free += 1;
    }

    /// Queues a knob. -> the boundary (= step) that applies it, and the config hash once
    /// everything queued so far has applied.
    pub fn set(ib: *Inbox, knob: scheduler.Knob) error{Full}!struct { apply_step: u64, config_hash: u64 } {
        ib.mutex.lock();
        defer ib.mutex.unlock();
        if (ib.n_knobs == knob_capacity) return error.Full;
        ib.n_knobs += 1;
        ib.push(.{ .knob = knob });
        scheduler.setField(&ib.pending_cfg, knob);
        return .{ .apply_step = ib.boundary + 1, .config_hash = scheduler.hashConfig(&ib.pending_cfg) };
    }

    /// Registers the launch context for the next epoch and queues the swap op (S6: the context
    /// exists locally before the op does). error.Pending while an earlier swap has not been
    /// installed (swapInstalled).
    pub fn swapLaunch(ib: *Inbox, launch: *const anyopaque, captured: *anyopaque, drain_first: bool) error{Pending}!void {
        ib.mutex.lock();
        defer ib.mutex.unlock();
        if (ib.swap != null) return error.Pending;
        ib.swap_epoch += 1;
        ib.swap = .{ .epoch = ib.swap_epoch, .launch = launch, .captured = captured, .drain = drain_first };
        ib.push(.{ .swap = .{ .epoch = ib.swap_epoch, .drain = drain_first } });
    }

    /// The registration for `epoch`, taken (the loop now holds it as its pending swap).
    pub fn takeSwap(ib: *Inbox, epoch: u64) ?SwapReg {
        ib.mutex.lock();
        defer ib.mutex.unlock();
        const reg = ib.swap orelse return null;
        if (reg.epoch != epoch) return null;
        return reg;
    }

    /// The loop installed the swap: a new one may be queued.
    pub fn swapInstalled(ib: *Inbox, epoch: u64) void {
        ib.mutex.lock();
        defer ib.mutex.unlock();
        if (ib.swap) |reg| if (reg.epoch == epoch) {
            ib.swap = null;
        };
    }

    pub fn prepareGrammar(ib: *Inbox, key: u64, source: []const u8) error{ Full, TooLong }!void {
        ib.mutex.lock();
        defer ib.mutex.unlock();
        if (source.len > max_source_bytes) return error.TooLong;
        if (ib.n_prepare == prepare_capacity) return error.Full;
        const index = ib.n_prepare;
        ib.n_prepare += 1;
        @memcpy(ib.sources[index][0..source.len], source);
        ib.push(.{ .grammar_prepare = .{ .key = key, .n_source = @intCast(source.len), .index = index } });
    }

    /// Encodes every queued op into `out` (header first) and empties the inbox: one boundary.
    /// Returns the batch length in words.
    pub fn drain(ib: *Inbox, out: []u32, prev_digest: u64, prev_payload_hash: u64, flags: u32) u32 {
        ib.mutex.lock();
        defer ib.mutex.unlock();
        assert(out.len >= ib.capWords());
        var w = Writer{ .out = out, .pos = header_words };
        for (ib.ops[0..ib.n_ops]) |op| switch (op) {
            .submit => |p| {
                w.put(&.{ @intFromEnum(Kind.submit), p.id, p.gen, p.n_prompt, p.max_new, @bitCast(p.temperature), lo32(p.mm.hash), hi32(p.mm.hash), p.mm.start, p.n_stop, lo32(p.grammar_key), hi32(p.grammar_key), lo32(p.t_arrival_ns), hi32(p.t_arrival_ns), p.top_k });
                w.put(p.stop[0..p.n_stop]);
                w.put(ib.staging[@as(usize, p.id) * ib.max_seq_len ..][0..p.n_prompt]);
            },
            .cancel => |ref| w.put(&.{ @intFromEnum(Kind.cancel), ref.id, ref.gen }),
            .release => |ref| w.put(&.{ @intFromEnum(Kind.release), ref.id, ref.gen }),
            .knob => |knob| {
                w.put(&.{@intFromEnum(Kind.knob)});
                w.put(&knobWords(knob));
            },
            .swap => |s| w.put(&.{ @intFromEnum(Kind.swap), lo32(s.epoch), hi32(s.epoch), @intFromBool(s.drain) }),
            .grammar_prepare => |g| {
                w.put(&.{ @intFromEnum(Kind.grammar_prepare), lo32(g.key), hi32(g.key), g.n_source });
                const n_words = (g.n_source + 3) / 4;
                const dst = std.mem.sliceAsBytes(out[w.pos..][0..n_words]);
                @memset(dst, 0);
                @memcpy(dst[0..g.n_source], ib.sources[g.index][0..g.n_source]);
                w.pos += n_words;
            },
        };
        ib.boundary += 1;
        const header = Header{
            .version = wire_version,
            .n_ops = ib.n_ops,
            .n_words = @intCast(w.pos - header_words),
            .flags = flags,
            .boundary = ib.boundary,
            .prev_digest = prev_digest,
            .prev_payload_hash = prev_payload_hash,
            .n_rejected_full = ib.n_rejected_full,
        };
        @memcpy(std.mem.sliceAsBytes(out[0..header_words]), std.mem.asBytes(&header));
        ib.n_ops = 0;
        ib.n_knobs = 0;
        ib.n_prepare = 0;
        ib.n_rejected_full = 0;
        return @intCast(w.pos);
    }

    /// The submit for (id, gen) applied: the core holds it now. Stale when the ledger moved on
    /// (the request was cancelled before it applied and the id reserved again).
    pub fn appliedSubmit(ib: *Inbox, id: u32, gen: u32) void {
        ib.mutex.lock();
        defer ib.mutex.unlock();
        const slot = &ib.slots[id];
        if (slot.gen == gen and slot.state == .reserved) slot.state = .live;
    }

    /// Frees every live id the core no longer owns -- with overlap, a cancel whose release the
    /// core deferred to a commit. Called by the step thread with loop.mutex held.
    pub fn reconcile(ib: *Inbox, reqs: *const request.Pool) void {
        ib.mutex.lock();
        defer ib.mutex.unlock();
        for (ib.slots, 0..) |slot, id| {
            if (slot.state == .live and !reqs.requests[id].owned) ib.freeLocked(@intCast(id));
        }
    }
};

const Writer = struct {
    out: []u32,
    pos: usize,
    fn put(w: *Writer, words: []const u32) void {
        @memcpy(w.out[w.pos..][0..words.len], words);
        w.pos += words.len;
    }
};

/// Rewrites `words` (a valid batch) without op `drop` into `out`: the dropped-op replay test's
/// mutation. Returns the new length in words.
pub fn dropOp(words: []const u32, drop: u32, out: []u32) u32 {
    const header = headerOf(words);
    assert(drop < header.n_ops);
    var r = Reader.of(words);
    var pos: usize = header_words;
    var i: u32 = 0;
    var start: usize = r.pos;
    while (r.next()) |_| : (i += 1) {
        const op_words = words[header_words + start .. header_words + r.pos];
        if (i != drop) {
            @memcpy(out[pos..][0..op_words.len], op_words);
            pos += op_words.len;
        }
        start = r.pos;
    }
    var h = header;
    h.n_ops -= 1;
    h.n_words = @intCast(pos - header_words);
    @memcpy(std.mem.sliceAsBytes(out[0..header_words]), std.mem.asBytes(&h));
    return @intCast(pos);
}

// ---- tests -----------------------------------------------------------------------------------

const test_cfg = scheduler.Config{ .max_batch_tokens = 16, .max_batch_reqs = 4, .reserve_ratio = 0, .order = .running_first, .eos_token = 99 };

test "every op round-trips through drain -> validate -> Reader in push order" {
    const allocator = std.testing.allocator;
    const groups = [_]request.GroupSpec{.{ .kind = .per_token, .block_size = 4 }};
    var reqs = try request.Pool.init(allocator, .{ .max_requests = 4, .max_seq_len = 32, .groups = &groups });
    defer reqs.deinit(allocator);
    const kv_pool = @import("kv_pool.zig");
    var kv = try kv_pool.flatInit(allocator, 16, 4, 1);
    defer kv.deinit(allocator);
    var sched = try scheduler.Scheduler.init(allocator, test_cfg, &reqs, &kv);
    defer sched.deinit(allocator);

    var ib = try Inbox.init(allocator, 4, 32, test_cfg);
    defer ib.deinit(allocator);
    const out = try allocator.alloc(u32, ib.capWords());
    defer allocator.free(out);

    const id = try ib.submit(.{ .prompt = &.{ 5, 6, 7 }, .max_new = 4, .temperature = 0.5, .top_k = 7, .mm = .{ .hash = 0x1_0000_0002, .start = 1 }, .stop = &.{42}, .grammar_key = 0xAB_0000_00CD, .t_arrival_ns = 123 });
    try std.testing.expectEqual(@as(u32, 3), id); // LIFO from the top, like request.Pool
    const set = try ib.set(.{ .order = .waiting_first });
    try std.testing.expectEqual(@as(u64, 1), set.apply_step);
    ib.appliedSubmit(id, ib.slots[id].gen); // as if applied: a cancel of a live id is an op
    try std.testing.expect(ib.cancel(id, null));
    try std.testing.expect(!ib.cancel(id, null)); // already queued
    try ib.prepareGrammar(7, "{\"type\":1}");
    const n = ib.drain(out, 11, 22, 0);
    const words = out[0..n];

    const limits = Limits{ .max_requests = 4, .max_seq_len = 32, .max_source_bytes = max_source_bytes, .vocab_size = 100 };
    const header = try validate(words, limits, &sched);
    try std.testing.expectEqual(@as(u32, 4), header.n_ops);
    try std.testing.expectEqual(@as(u64, 1), header.boundary);
    try std.testing.expectEqual(@as(u64, 11), header.prev_digest);
    var r = Reader.of(words);
    const s = r.next().?.submit;
    try std.testing.expectEqual(id, s.id);
    try std.testing.expectEqualSlices(u32, &.{ 5, 6, 7 }, s.prompt);
    try std.testing.expectEqualSlices(u32, &.{42}, s.stop);
    try std.testing.expectEqual(@as(u64, 0x1_0000_0002), s.mm.hash);
    try std.testing.expectEqual(@as(u64, 0xAB_0000_00CD), s.grammar_key);
    try std.testing.expectEqual(@as(f32, 0.5), s.temperature);
    try std.testing.expectEqual(@as(u32, 7), s.top_k);
    try std.testing.expectEqual(scheduler.Order.waiting_first, r.next().?.knob.order);
    try std.testing.expectEqual(id, r.next().?.cancel.id);
    try std.testing.expectEqualStrings("{\"type\":1}", r.next().?.grammar_prepare.source);
    try std.testing.expect(r.next() == null);

    // Drop the knob (op 1): the rest survive, still valid.
    const dropped = try allocator.alloc(u32, n);
    defer allocator.free(dropped);
    const m = dropOp(words, 1, dropped);
    try std.testing.expectEqual(@as(u32, 3), (try validate(dropped[0..m], limits, &sched)).n_ops);

    // A drained inbox encodes an empty batch; boundaries keep counting.
    const empty = ib.drain(out, 0, 0, flag_stop);
    try std.testing.expectEqual(header_words, empty);
    try std.testing.expectEqual(@as(u64, 2), (try validate(out[0..empty], limits, &sched)).boundary);
}

test "validate refuses what this engine cannot hold, before any op applies" {
    const allocator = std.testing.allocator;
    const groups = [_]request.GroupSpec{.{ .kind = .per_token, .block_size = 4 }};
    var reqs = try request.Pool.init(allocator, .{ .max_requests = 4, .max_seq_len = 32, .groups = &groups });
    defer reqs.deinit(allocator);
    const kv_pool = @import("kv_pool.zig");
    var kv = try kv_pool.flatInit(allocator, 16, 4, 1);
    defer kv.deinit(allocator);
    var sched = try scheduler.Scheduler.init(allocator, test_cfg, &reqs, &kv);
    defer sched.deinit(allocator);
    var ib = try Inbox.init(allocator, 4, 32, test_cfg);
    defer ib.deinit(allocator);
    const out = try allocator.alloc(u32, ib.capWords());
    defer allocator.free(out);
    _ = try ib.submit(.{ .prompt = &.{ 1, 2 }, .max_new = 4, .temperature = 0, .top_k = 5, .mm = .{ .hash = 0, .start = 0 }, .stop = &.{}, .grammar_key = 0, .t_arrival_ns = 0 });
    const n = ib.drain(out, 0, 0, 0);
    const limits = Limits{ .max_requests = 4, .max_seq_len = 32, .max_source_bytes = 0, .vocab_size = 8 };
    _ = try validate(out[0..n], limits, &sched);
    // A negative temperature on the wire (a bad edge): refused here, before applySubmit's T=0
    // rule would assert on it. Word 5 of the submit op, after its kind word.
    const t_word = header_words + 5;
    const good = out[t_word];
    out[t_word] = @bitCast(@as(f32, -1));
    try std.testing.expectError(error.BadValue, validate(out[0..n], limits, &sched));
    out[t_word] = good;
    // A top_k above this rank's vocabulary (5 > 4) is refused the same way; unchecked at 0.
    try std.testing.expectError(error.BadValue, validate(out[0..n], .{ .max_requests = 4, .max_seq_len = 32, .max_source_bytes = 0, .vocab_size = 4 }, &sched));
    _ = try validate(out[0..n], .{ .max_requests = 4, .max_seq_len = 32, .max_source_bytes = 0, .vocab_size = 0 }, &sched);
    try std.testing.expectError(error.BadValue, validate(out[0..n], .{ .max_requests = 2, .max_seq_len = 32, .max_source_bytes = 0, .vocab_size = 8 }, &sched));
    try std.testing.expectError(error.BadLength, validate(out[0..n], .{ .max_requests = 4, .max_seq_len = 5, .max_source_bytes = 0, .vocab_size = 8 }, &sched));
    try std.testing.expectError(error.BadLength, validate(out[0 .. n - 1], limits, &sched));
    out[0] = 99;
    try std.testing.expectError(error.BadVersion, validate(out[0..n], limits, &sched));
    // A knob the follower's buffers cannot hold.
    const set = try ib.set(.{ .max_batch_tokens = 1000 });
    _ = set;
    const m = ib.drain(out, 0, 0, 0);
    try std.testing.expectError(error.BadValue, validate(out[0..m], limits, &sched));
}

test "ledger: Full is synchronous, a finished+polled or cancelled id is reservable at once, gens move" {
    const allocator = std.testing.allocator;
    var ib = try Inbox.init(allocator, 2, 8, test_cfg);
    defer ib.deinit(allocator);
    const args = Inbox.SubmitArgs{ .prompt = &.{1}, .max_new = 1, .temperature = 0, .top_k = 0, .mm = .{ .hash = 0, .start = 0 }, .stop = &.{}, .grammar_key = 0, .t_arrival_ns = 0 };
    const a = try ib.submit(args);
    const b = try ib.submit(args);
    try std.testing.expectError(error.Full, ib.submit(args));
    try std.testing.expectEqual(@as(u32, 1), ib.n_rejected_full);
    try std.testing.expectEqual(Inbox.View.not_applied, ib.pollView(a));
    ib.appliedSubmit(a, ib.slots[a].gen);
    ib.appliedSubmit(b, ib.slots[b].gen);
    try std.testing.expectEqual(Inbox.View.core, ib.pollView(a));
    // a finished and was polled: its release is queued, and the id is reservable right away.
    ib.pollFinished(a);
    ib.pollFinished(a); // once
    const gen_a = ib.slots[a].gen;
    const c = try ib.submit(args);
    try std.testing.expectEqual(a, c);
    try std.testing.expectEqual(gen_a +% 1, ib.slots[c].gen);
    // A stale cancel (the old gen) queues nothing.
    try std.testing.expect(!ib.cancel(c, gen_a));
    // Cancel b: reservable at once (no overlap), poll says cancelled until the id is reused.
    try std.testing.expect(ib.cancel(b, null));
    try std.testing.expectEqual(Inbox.View.cancelled, ib.pollView(b));
    const d = try ib.submit(args);
    try std.testing.expectEqual(b, d);
    try std.testing.expectEqual(Inbox.View.not_applied, ib.pollView(d));
    try std.testing.expectEqual(@as(u32, 6), ib.n_ops); // submit a, b, release a, submit c, cancel b, submit d
    // Cancelling a not-yet-applied submit drops its op: a burst of submit + cancel pairs between
    // two boundaries leaves the inbox where it was (the review's overflow repro).
    for (0..10_000) |_| {
        try std.testing.expect(ib.cancel(d, null));
        try std.testing.expectEqual(d, try ib.submit(args));
    }
    try std.testing.expectEqual(@as(u32, 6), ib.n_ops);
}
