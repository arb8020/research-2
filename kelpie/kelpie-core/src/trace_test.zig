//! Trace test harness for scheduler.zig. Trace format: see traces/*.txt. Every expectation is a
//! string compare so failures show both sides. num_blocks counts the null block 0, so
//! `expect free` starts at num_blocks - 1.

const std = @import("std");
const request = @import("request.zig");
const kv_pool = @import("kv_pool.zig");
const events = @import("events.zig");
const scheduler = @import("scheduler.zig");
const Order = scheduler.Order;
const Config = scheduler.Config;
const Scheduler = scheduler.Scheduler;
const Knob = scheduler.Knob;
const Tier = scheduler.Tier;
const submit = scheduler.submit;
const submitMm = scheduler.submitMm;
const cancel = scheduler.cancel;
const validateKnob = scheduler.validateKnob;
const applyKnob = scheduler.applyKnob;
const plan = scheduler.plan;
const commit = scheduler.commit;
const poll = scheduler.poll;
const enterDraining = scheduler.enterDraining;
const leaveDraining = scheduler.leaveDraining;
const isDrained = scheduler.isDrained;
const waitingIds = scheduler.waitingIds;

const TraceError = error{ TraceFailed, NoSpaceLeft } || std.mem.Allocator.Error || std.fmt.ParseIntError || std.fmt.ParseFloatError;

const Trace = struct {
    allocator: std.mem.Allocator,
    path: []const u8,
    line_no: usize,
    groups: [max_groups]request.GroupSpec,
    /// Pages of each group that fit in one slab (`/P` in the groups= spec); 1 = flat pool.
    pages_per_slab: [max_groups]u32,
    /// Kmax from the config line (`max_extra=`); bounds `kept=` and `next=`.
    max_extra: u32,
    n_groups: usize,
    reqs: ?request.Pool,
    kv: ?kv_pool.Pool,
    sched: ?Scheduler,
    names: [max_names]?[]const u8,
    ids: [max_names]u32,
    /// config_hash of the step before the last one, for `expect config_hash changed|unchanged`.
    prev_hash: u64,
    /// Tokens for the plan in flight (`plan [tokens=..]` ... `commit`); `step` is both at once.
    sampled: [64]u32,
    /// Tokens committed per entry (`kept=A:2`): tail rows 0..n-1 valid; only 1 while Kmax = 0.
    kept: [64]u32,
    /// Extra rows each entry asks for next (`next=A:0`); default Kmax, as a drafter would.
    next: [64]u32,
    ahead_sampled: [64]u32,
    ahead_kept: [64]u32,
    ahead_next: [64]u32,
    launch_ctx: u8,
    last_launch_ctx: ?u8,
    pending_swap: ?struct { ctx: u8, drain: bool },
    last_submit_draining: bool,
    /// The last plan stalled and no `expect stall` has looked at it yet. A plan, or the end of
    /// the trace, fails while this is set: every stall a trace reaches must be one it expects.
    stall_unchecked: bool,
    /// `set` knobs not yet applied: the harness's stand-in for the inbox (c_api.zig), applied
    /// in order right before the next plan -- the step boundary.
    knobs: [64]Knob,
    n_knobs: usize,

    const max_names = 16;
    const max_groups = 4;
    const max_commit_tokens = 256;

    fn deinit(t: *Trace) void {
        if (t.sched) |*s| s.deinit(t.allocator);
        if (t.kv) |*kv| kv.deinit(t.allocator);
        if (t.reqs) |*reqs| reqs.deinit(t.allocator);
    }
};

fn runTrace(allocator: std.mem.Allocator, path: []const u8, text: []const u8) TraceError!void {
    var t = Trace{
        .allocator = allocator,
        .path = path,
        .line_no = 0,
        .groups = undefined,
        .pages_per_slab = [_]u32{1} ** Trace.max_groups,
        .max_extra = 0,
        .n_groups = 1,
        .reqs = null,
        .kv = null,
        .sched = null,
        .names = [_]?[]const u8{null} ** Trace.max_names,
        .ids = undefined,
        .prev_hash = 0,
        .sampled = undefined,
        .kept = undefined,
        .next = undefined,
        .ahead_sampled = undefined,
        .ahead_kept = undefined,
        .ahead_next = undefined,
        .launch_ctx = 'A',
        .last_launch_ctx = null,
        .pending_swap = null,
        .last_submit_draining = false,
        .stall_unchecked = false,
        .knobs = undefined,
        .n_knobs = 0,
    };
    defer t.deinit();
    var lines = std.mem.splitScalar(u8, text, '\n');
    while (lines.next()) |raw| {
        t.line_no += 1;
        const line = std.mem.trim(u8, raw[0 .. std.mem.indexOfScalar(u8, raw, '#') orelse raw.len], " \t\r");
        if (line.len == 0) continue;
        try runLine(&t, line);
    }
    if (t.stall_unchecked) return fail(&t, "the last plan stalled; the trace never expected it", .{});
}

fn runLine(t: *Trace, line: []const u8) TraceError!void {
    var words = std.mem.tokenizeScalar(u8, line, ' ');
    const cmd = words.next().?;
    if (std.mem.eql(u8, cmd, "config")) return cmdConfig(t, &words);
    if (t.sched == null) return fail(t, "config must come first", .{});
    if (std.mem.eql(u8, cmd, "submit")) return cmdSubmit(t, &words);
    if (std.mem.eql(u8, cmd, "step")) return cmdStep(t, &words);
    if (std.mem.eql(u8, cmd, "plan")) return cmdPlan(t, &words);
    if (std.mem.eql(u8, cmd, "commit")) return cmdCommit(t);
    if (std.mem.eql(u8, cmd, "cancel")) return cmdCancel(t, words.next().?);
    if (std.mem.eql(u8, cmd, "set")) return cmdSet(t, &words);
    if (std.mem.eql(u8, cmd, "swap")) return cmdSwap(t, &words);
    if (std.mem.eql(u8, cmd, "stop_loop")) return;
    if (std.mem.eql(u8, cmd, "expect")) return cmdExpect(t, &words);
    return fail(t, "unknown command '{s}'", .{cmd});
}

// TODO(2026-09-10): build the config through c_api parseConfig instead of constructing GroupSpecs here;
// the harness bypassing parseConfig hid the per_seq BadStride bug (handoff-2026-09-10 debt 1).
fn cmdConfig(t: *Trace, words: *std.mem.TokenIterator(u8, .scalar)) TraceError!void {
    if (t.sched != null) return fail(t, "config given twice", .{});
    // Traces default to prefix_cache=0 so the older traces keep documenting the plain scheduler.
    var cfg = Config{ .max_batch_tokens = 8, .max_batch_reqs = 4, .reserve_ratio = 0, .order = .running_first, .eos_token = 99, .prefix_cache = false, .overlap = false };
    var block_size: u32 = 4;
    var num_blocks: u32 = 8;
    var max_requests: u32 = 8;
    var max_seq_len: u32 = 64;
    var groups_spec: []const u8 = "full";
    while (words.next()) |word| {
        const eq = std.mem.indexOfScalar(u8, word, '=') orelse return fail(t, "bad config '{s}'", .{word});
        const key = word[0..eq];
        const val = word[eq + 1 ..];
        if (std.mem.eql(u8, key, "max_batch_tokens")) {
            cfg.max_batch_tokens = try std.fmt.parseInt(u32, val, 10);
        } else if (std.mem.eql(u8, key, "max_batch_reqs")) {
            cfg.max_batch_reqs = try std.fmt.parseInt(u32, val, 10);
        } else if (std.mem.eql(u8, key, "reserve_ratio")) {
            cfg.reserve_ratio = try std.fmt.parseFloat(f32, val);
        } else if (std.mem.eql(u8, key, "eos")) {
            cfg.eos_token = try std.fmt.parseInt(u32, val, 10);
        } else if (std.mem.eql(u8, key, "order")) {
            cfg.order = std.meta.stringToEnum(Order, val) orelse return fail(t, "bad order '{s}'", .{val});
        } else if (std.mem.eql(u8, key, "block_size")) {
            block_size = try std.fmt.parseInt(u32, val, 10);
        } else if (std.mem.eql(u8, key, "max_extra")) {
            t.max_extra = try std.fmt.parseInt(u32, val, 10);
        } else if (std.mem.eql(u8, key, "num_blocks")) {
            num_blocks = try std.fmt.parseInt(u32, val, 10);
        } else if (std.mem.eql(u8, key, "max_requests")) {
            max_requests = try std.fmt.parseInt(u32, val, 10);
        } else if (std.mem.eql(u8, key, "max_seq_len")) {
            max_seq_len = try std.fmt.parseInt(u32, val, 10);
        } else if (std.mem.eql(u8, key, "prefix_cache")) {
            cfg.prefix_cache = (try std.fmt.parseInt(u32, val, 10)) != 0;
        } else if (std.mem.eql(u8, key, "groups")) {
            groups_spec = val;
        } else if (std.mem.eql(u8, key, "overlap")) {
            cfg.overlap = (try std.fmt.parseInt(u32, val, 10)) != 0;
        } else return fail(t, "unknown config key '{s}'", .{key});
    }
    try parseGroups(t, groups_spec, block_size);
    t.reqs = try request.Pool.init(t.allocator, .{
        .max_requests = max_requests,
        .max_seq_len = max_seq_len,
        .groups = t.groups[0..t.n_groups],
        .max_extra = t.max_extra,
    });
    var max_tokens_per_block: u32 = block_size;
    for (t.groups[0..t.n_groups]) |g| {
        // A per_seq checkpoint stores its own S tokens (prefix.insertSeq), a per_token block
        // its tokensPerBlock.
        const per_group = if (g.kind == .per_seq) g.stride else request.tokensPerBlock(g);
        max_tokens_per_block = @max(max_tokens_per_block, per_group);
    }
    // A group's `/P` suffix says how many of its pages fit in a slab; the slab is the largest
    // page. With every P == 1 this is the degenerate flat pool and num_blocks counts pages as it
    // always did, so every pre-slab trace is unchanged.
    var slab_pages: u32 = 1;
    for (t.pages_per_slab[0..t.n_groups]) |p| slab_pages = @max(slab_pages, p);
    if (slab_pages == 1) {
        t.kv = try kv_pool.flatInit(t.allocator, num_blocks, max_tokens_per_block, @intCast(t.n_groups));
    } else {
        const page_unit: u32 = 4096;
        const slab_bytes = slab_pages * page_unit;
        var pool_groups: [Trace.max_groups]kv_pool.PoolGroup = undefined;
        for (t.pages_per_slab[0..t.n_groups], 0..) |p, g| {
            if (slab_pages % p != 0) return fail(t, "pages_per_slab {d} must divide {d}", .{ p, slab_pages });
            pool_groups[g] = .{ .bytes_per_page = slab_bytes / p, .pages_per_slab = p };
        }
        t.kv = try kv_pool.Pool.init(t.allocator, num_blocks, slab_bytes, pool_groups[0..t.n_groups], max_tokens_per_block);
    }
    t.sched = try Scheduler.init(t.allocator, cfg, &t.reqs.?, &t.kv.?);
}

/// groups=full,window8,window8nc,stride4: comma-separated per_token groups; each defaults to the
/// config's block_size, and a `:N` suffix (`stride4:32`) gives that group its own block size.
/// A further `/P` suffix (`full:16/4`) gives the group P pages per slab -- the slab pool carving
/// (docs/slab-lcm-ladder.md): the slab is the largest page, and a group whose page is P times
/// smaller fits P of them in one slab. Default 1 for every group (the degenerate flat pool).
/// windowN sets window=N (suffix `nc`: not cacheable), strideK sets stride=K.
/// `stateS` is a per_seq (recurrent) group checkpointing every S tokens, S = 0 never; its `:C`
/// suffix is the checkpoints each request keeps (the per_seq window, default 1), not a block size.
fn parseGroups(t: *Trace, spec: []const u8, block_size: u32) TraceError!void {
    var it = std.mem.tokenizeScalar(u8, spec, ',');
    t.n_groups = 0;
    while (it.next()) |entry| {
        if (t.n_groups == Trace.max_groups) return fail(t, "too many groups", .{});
        var word = entry;
        var bs = block_size;
        var pps: u32 = 1;
        if (std.mem.indexOfScalar(u8, word, '/')) |slash| {
            pps = try std.fmt.parseInt(u32, word[slash + 1 ..], 10);
            if (pps == 0) return fail(t, "pages_per_slab must be >= 1", .{});
            word = word[0..slash];
        }
        if (std.mem.indexOfScalar(u8, word, ':')) |colon| {
            bs = try std.fmt.parseInt(u32, word[colon + 1 ..], 10);
            word = word[0..colon];
        }
        t.pages_per_slab[t.n_groups] = pps;
        var g = request.GroupSpec{ .kind = .per_token, .block_size = bs };
        if (std.mem.startsWith(u8, word, "state")) {
            // stateS[:C]: per_seq, checkpoint interval S, C checkpoints kept (default 1; none
            // when S = 0).
            const strideS = try std.fmt.parseInt(u32, word["state".len..], 10);
            g = .{ .kind = .per_seq, .block_size = 0, .stride = strideS };
            const n_ckpt: u32 = if (bs != block_size) bs else 1;
            if (strideS != 0) g.retention = .{ .window = .{ .w = n_ckpt, .cacheable = true } };
        } else if (std.mem.startsWith(u8, word, "window")) {
            const cacheable = !std.mem.endsWith(u8, word, "nc");
            const digits = word["window".len .. word.len - @as(usize, if (cacheable) 0 else 2)];
            const w = try std.fmt.parseInt(u32, digits, 10);
            g.retention = .{ .window = .{ .w = w, .cacheable = cacheable } };
        } else if (std.mem.startsWith(u8, word, "stride")) {
            g.stride = try std.fmt.parseInt(u32, word["stride".len..], 10);
        } else if (!std.mem.eql(u8, word, "full")) return fail(t, "bad group '{s}'", .{word});
        t.groups[t.n_groups] = g;
        t.n_groups += 1;
    }
    if (t.n_groups == 0) return fail(t, "groups= needs at least one group", .{});
}

/// The id is released by cancel and may be reacquired by the next submit, so the name dies with it.
fn cmdCancel(t: *Trace, name: []const u8) TraceError!void {
    cancel(&t.sched.?, try lookup(t, name));
    forget(t, name);
}

fn cmdSubmit(t: *Trace, words: *std.mem.TokenIterator(u8, .scalar)) TraceError!void {
    const name = words.next() orelse return fail(t, "submit needs a name", .{});
    var n_prompt: u32 = 0;
    var max_new: u32 = 0;
    var base: u32 = 1000;
    var mm = request.Mm{ .hash = 0, .start = 0 };
    var expect_err: ?[]const u8 = null;
    while (words.next()) |word| {
        if (std.mem.startsWith(u8, word, "prompt=")) n_prompt = try std.fmt.parseInt(u32, word["prompt=".len..], 10);
        if (std.mem.startsWith(u8, word, "max_new=")) max_new = try std.fmt.parseInt(u32, word["max_new=".len..], 10);
        if (std.mem.startsWith(u8, word, "base=")) base = try std.fmt.parseInt(u32, word["base=".len..], 10);
        if (std.mem.startsWith(u8, word, "mm=")) mm.hash = try std.fmt.parseInt(u64, word["mm=".len..], 10);
        if (std.mem.startsWith(u8, word, "mm_start=")) mm.start = try std.fmt.parseInt(u32, word["mm_start=".len..], 10);
        if (std.mem.startsWith(u8, word, "fails=")) expect_err = word["fails=".len..];
    }
    // Prompt tokens are base+i, so two submits with the same base share a prefix.
    var prompt: [256]u32 = undefined;
    for (prompt[0..n_prompt], 0..) |*token, i| token.* = base + @as(u32, @intCast(i));
    t.last_submit_draining = false;
    const id = submitMm(&t.sched.?, prompt[0..n_prompt], request.samplingParams(max_new, 1.0, 0), mm) catch |err| {
        t.last_submit_draining = err == error.Draining;
        if (expect_err != null and std.mem.eql(u8, expect_err.?, @errorName(err))) return;
        return fail(t, "submit {s}: {s}", .{ name, @errorName(err) });
    };
    if (expect_err) |e| return fail(t, "submit {s}: expected {s}, got id {d}", .{ name, e, id });
    for (&t.names, &t.ids) |*slot, *slot_id| {
        if (slot.* != null) continue;
        slot.* = name;
        slot_id.* = id;
        return;
    }
    return fail(t, "too many names", .{});
}

fn cmdSwap(t: *Trace, words: *std.mem.TokenIterator(u8, .scalar)) TraceError!void {
    var drain = false;
    var expect_pending = false;
    while (words.next()) |word| {
        if (std.mem.eql(u8, word, "drain=0")) drain = false else if (std.mem.eql(u8, word, "drain=1")) drain = true else if (std.mem.eql(u8, word, "fails=SwapPending")) expect_pending = true else return fail(t, "bad swap arg '{s}'", .{word});
    }
    if (t.pending_swap != null) {
        if (expect_pending) return;
        return fail(t, "swap: SwapPending", .{});
    }
    if (expect_pending) return fail(t, "swap: expected SwapPending", .{});
    const next: u8 = if (t.launch_ctx == 'A') 'B' else 'A';
    t.pending_swap = .{ .ctx = next, .drain = drain };
}

fn applyTraceSwapBoundary(t: *Trace) void {
    const pending = t.pending_swap orelse return;
    const s = &t.sched.?;
    if (!pending.drain) {
        t.launch_ctx = pending.ctx;
        t.pending_swap = null;
        return;
    }
    if (s.state == .serving) enterDraining(s);
    if (!isDrained(s)) return;
    t.launch_ctx = pending.ctx;
    t.pending_swap = null;
    leaveDraining(s);
}

/// `set order=waiting_first reserve_ratio=0.5`: queued now, applied at the start of the next step.
fn cmdSet(t: *Trace, words: *std.mem.TokenIterator(u8, .scalar)) TraceError!void {
    while (words.next()) |word| {
        const eq = std.mem.indexOfScalar(u8, word, '=') orelse return fail(t, "bad set '{s}'", .{word});
        const knob = try parseKnob(t, word[0..eq], word[eq + 1 ..]);
        validateKnob(&t.sched.?, knob) catch |err| return fail(t, "set {s}: {s}", .{ word, @errorName(err) });
        if (t.n_knobs == t.knobs.len) return fail(t, "set {s}: too many queued knobs", .{word});
        t.knobs[t.n_knobs] = knob;
        t.n_knobs += 1;
    }
}

/// The boundary: every queued knob applies, in order, right before the plan.
fn applyTraceKnobs(t: *Trace) void {
    for (t.knobs[0..t.n_knobs]) |knob| applyKnob(&t.sched.?, knob);
    t.n_knobs = 0;
}

fn parseKnob(t: *Trace, key: []const u8, val: []const u8) TraceError!Knob {
    if (std.mem.eql(u8, key, "order")) {
        return .{ .order = std.meta.stringToEnum(Order, val) orelse return fail(t, "bad order '{s}'", .{val}) };
    } else if (std.mem.eql(u8, key, "reserve_ratio")) {
        return .{ .reserve_ratio = try std.fmt.parseFloat(f32, val) };
    } else if (std.mem.eql(u8, key, "max_batch_tokens")) {
        return .{ .max_batch_tokens = try std.fmt.parseInt(u32, val, 10) };
    } else if (std.mem.eql(u8, key, "max_batch_reqs")) {
        return .{ .max_batch_reqs = try std.fmt.parseInt(u32, val, 10) };
    } else if (std.mem.eql(u8, key, "prefix_cache")) {
        return .{ .prefix_cache = (try std.fmt.parseInt(u32, val, 10)) != 0 };
    }
    return fail(t, "unknown knob '{s}'", .{key});
}

fn cmdStep(t: *Trace, words: *std.mem.TokenIterator(u8, .scalar)) TraceError!void {
    try cmdPlan(t, words);
    try cmdCommit(t);
}

/// `plan [tokens=A:7,B:8] [kept=A:2] [next=A:0]`: per entry, the first token committed (default 1;
/// an entry keeping n commits tok, tok+1, .., tok+n-1), how many tokens it keeps (default 1;
/// anything else fails while max_extra = 0), and the extra rows it asks for next (default
/// max_extra) -- kept for the matching `commit`.
fn cmdPlan(t: *Trace, words: *std.mem.TokenIterator(u8, .scalar)) TraceError!void {
    const s = &t.sched.?;
    const is_ahead = s.planned();
    if (is_ahead and (!s.cfg.overlap or s.ahead() != null)) return fail(t, "plan while a plan is in flight", .{});
    if (t.stall_unchecked) return fail(t, "the previous plan stalled; no `expect stall` checked it", .{});
    applyTraceSwapBoundary(t);
    applyTraceKnobs(t);
    t.prev_hash = s.event.config_hash;
    const p = plan(s);
    t.stall_unchecked = s.stall != null;
    if (p.n_reqs > 0) t.last_launch_ctx = t.launch_ctx;
    const sampled = if (is_ahead) &t.ahead_sampled else &t.sampled;
    const kept = if (is_ahead) &t.ahead_kept else &t.kept;
    const next = if (is_ahead) &t.ahead_next else &t.next;
    @memset(sampled[0..p.n_reqs], 1);
    @memset(kept[0..p.n_reqs], 1);
    @memset(next[0..p.n_reqs], t.max_extra);
    while (words.next()) |word| {
        const eq = std.mem.indexOfScalar(u8, word, '=') orelse return fail(t, "bad step arg '{s}'", .{word});
        const key = word[0..eq];
        const into = if (std.mem.eql(u8, key, "tokens")) sampled else if (std.mem.eql(u8, key, "kept")) kept else if (std.mem.eql(u8, key, "next")) next else return fail(t, "bad step arg '{s}'", .{word});
        var pairs = std.mem.tokenizeScalar(u8, word[eq + 1 ..], ',');
        while (pairs.next()) |pair| {
            const colon = std.mem.indexOfScalar(u8, pair, ':') orelse return fail(t, "bad {s} pair '{s}'", .{ key, pair });
            const id = try lookup(t, pair[0..colon]);
            const value = try std.fmt.parseInt(u32, pair[colon + 1 ..], 10);
            if (std.mem.eql(u8, key, "kept") and value != 1 and t.max_extra == 0) {
                return fail(t, "kept={d}: only 1 while max_extra = 0", .{value});
            }
            if (std.mem.eql(u8, key, "kept") and value > 1 + t.max_extra) {
                return fail(t, "kept={d} exceeds 1 + max_extra ({d})", .{ value, 1 + t.max_extra });
            }
            if (std.mem.eql(u8, key, "next") and value > t.max_extra) {
                return fail(t, "next={d} exceeds max_extra ({d})", .{ value, t.max_extra });
            }
            for (p.entries[0..p.n_reqs], 0..) |entry, i| {
                if (entry.req_id == id) into[i] = value;
            }
        }
    }
}

fn cmdCommit(t: *Trace) TraceError!void {
    const s = &t.sched.?;
    if (!s.planned()) return fail(t, "commit without a plan", .{});
    const n = s.live().plan.n_reqs;
    // Row i of the [n, stride] token matrix: tok, tok+1, ... for the kept[i] tokens it keeps.
    const stride = 1 + t.max_extra;
    var rows: [Trace.max_commit_tokens]u32 = undefined;
    if (n * stride > rows.len) return fail(t, "too many tokens for the trace harness", .{});
    for (t.sampled[0..n], 0..) |tok, i| {
        for (0..stride) |j| rows[i * stride + j] = tok + @as(u32, @intCast(j));
    }
    // An entry may keep at most 1 + its own n_extra.
    for (s.live().plan.entries[0..n], t.kept[0..n]) |entry, n_kept| {
        if (n_kept > 1 + entry.n_extra) return fail(t, "kept={d} but the entry has {d} extra rows", .{ n_kept, entry.n_extra });
    }
    commit(s, .{ .tokens = rows[0 .. n * stride], .stride = stride, .n_tokens = t.kept[0..n], .next_extra = t.next[0..n] });
    if (s.planned()) {
        t.sampled = t.ahead_sampled;
        t.kept = t.ahead_kept;
        t.next = t.ahead_next;
    }
    applyTraceSwapBoundary(t);
}

const ExpectSubject = enum {
    batch,
    ahead_batch,
    free,
    running,
    waiting,
    table,
    finished,
    reserved,
    n_computed,
    polled,
    prefix,
    blocks,
    event,
    config_hash,
    state,
    launch_ctx,
    submit,
    stall,
    units,
    idx,
    rows,
    ahead_rows,
};

/// `A:5` for 5 history rows; `A:1+3` for 1 history row and 3 extra rows.
fn expectBatch(t: *Trace, w: anytype, entries: []const scheduler.Entry) TraceError!void {
    for (entries, 0..) |entry, i| {
        try w.print("{s}{s}:{d}", .{ if (i == 0) "" else " ", nameOf(t, entry.req_id), entry.n_work });
        if (entry.n_extra > 0) try w.print("+{d}", .{entry.n_extra});
    }
}

/// `expect rows A [40@8,-@9,-@10]`: A's rows in the plan in flight, input_id@position; `-` is
/// no_token (an extra row the caller fills, or a reserved placeholder). `expect ahead_rows`
/// reads the ahead plan instead.
fn expectRows(t: *Trace, p: *const scheduler.Plan, words: *std.mem.TokenIterator(u8, .scalar), w: anytype) TraceError!void {
    const name = words.next() orelse return fail(t, "expect rows needs a name", .{});
    const id = try lookup(t, name);
    const i = for (p.entries[0..p.n_reqs], 0..) |entry, i| {
        if (entry.req_id == id) break i;
    } else return fail(t, "expect rows: {s} is not in the plan", .{name});
    try w.writeAll("[");
    for (p.query_start_loc[i]..p.query_start_loc[i + 1], 0..) |row, j| {
        if (j > 0) try w.writeAll(",");
        if (p.input_ids[row] == scheduler.no_token) try w.writeAll("-") else try w.print("{d}", .{p.input_ids[row]});
        try w.print("@{d}", .{p.positions[row]});
    }
    try w.writeAll("]");
}

fn expectFree(s: *Scheduler, w: anytype) TraceError!void {
    try w.print("{d}", .{kv_pool.nFreeSlabs(s.kv)});
}

fn expectRunning(t: *Trace, s: *Scheduler, w: anytype) TraceError!void {
    for (s.running[0..s.n_running], 0..) |id, i| try w.print("{s}{s}", .{ if (i == 0) "" else " ", nameOf(t, id) });
}

fn expectWaiting(t: *Trace, s: *Scheduler, w: anytype) TraceError!void {
    var ids: [64]u32 = undefined;
    const n = waitingIds(s, &ids);
    for (ids[0..n], 0..) |id, i| try w.print("{s}{s}", .{ if (i == 0) "" else " ", nameOf(t, id) });
}

/// `expect table A g=1 [0,0,5,6]`: group g's logical rows, 0 = slid-out hole.
fn expectTable(t: *Trace, s: *Scheduler, words: *std.mem.TokenIterator(u8, .scalar), w: anytype) TraceError!void {
    const name = words.next() orelse return fail(t, "expect table needs a name", .{});
    const gword = words.next() orelse return fail(t, "expect table needs g=N", .{});
    const g = try std.fmt.parseInt(usize, gword["g=".len..], 10);
    const req = &s.reqs.requests[try lookup(t, name)];
    const table = req.tables[g];
    try w.writeAll("[");
    for (table.ids[0..table.n], 0..) |id, i| try w.print("{s}{d}", .{ if (i == 0) "" else ",", id });
    try w.writeAll("]");
}

fn expectFinished(t: *Trace, s: *Scheduler, words: *std.mem.TokenIterator(u8, .scalar), w: anytype) TraceError!void {
    const name = words.next() orelse return fail(t, "expect finished needs a name", .{});
    const req = &s.reqs.requests[try lookup(t, name)];
    try w.print("reason={s}", .{@tagName(req.state)});
}

fn expectReserved(t: *Trace, s: *Scheduler, words: *std.mem.TokenIterator(u8, .scalar), w: anytype) TraceError!void {
    const name = words.next() orelse return fail(t, "expect reserved needs a name", .{});
    try w.writeAll(if (s.reqs.requests[try lookup(t, name)].pending_token == std.math.maxInt(u32)) "true" else "false");
}

fn expectNComputed(t: *Trace, s: *Scheduler, words: *std.mem.TokenIterator(u8, .scalar), w: anytype) TraceError!void {
    const name = words.next() orelse return fail(t, "expect n_computed needs a name", .{});
    try w.print("{d}", .{s.reqs.requests[try lookup(t, name)].seq.n_computed});
}

fn expectPolled(t: *Trace, words: *std.mem.TokenIterator(u8, .scalar), w: anytype) TraceError!void {
    const name = words.next() orelse return fail(t, "expect polled needs a name", .{});
    try writePolled(t, w, name);
}

fn expectPrefix(s: *Scheduler, w: anytype) TraceError!void {
    const ev = s.event;
    try w.print("queries={d} hits={d} tokens={d}", .{ ev.prefix_queries, ev.prefix_hits, ev.prefix_hit_tokens }); // last committed step
}

fn expectBlocks(t: *Trace, s: *Scheduler, words: *std.mem.TokenIterator(u8, .scalar), w: anytype) TraceError!void {
    const name = words.next() orelse return fail(t, "expect blocks needs a name", .{});
    const req = &s.reqs.requests[try lookup(t, name)];
    for (req.tables[0].ids[0..req.tables[0].n], 0..) |id, i| try w.print("{s}{d}", .{ if (i == 0) "" else " ", id });
}

fn expectConfigHash(t: *Trace, s: *Scheduler, w: anytype) TraceError!void {
    const changed = s.event.config_hash != t.prev_hash;
    try w.writeAll(if (changed) "changed" else "unchanged");
}

fn expectState(s: *Scheduler, w: anytype) TraceError!void {
    try w.writeAll(@tagName(s.state));
}

fn expectLaunchCtx(t: *Trace, w: anytype) TraceError!void {
    if (t.last_launch_ctx) |ctx| try w.writeByte(ctx) else try w.writeAll("none");
}

fn expectSubmit(t: *Trace, w: anytype) TraceError!void {
    try w.writeAll(if (t.last_submit_draining) "rejected draining" else "accepted");
}

/// `expect stall none` or `expect stall A n_work=16 need=4 free=3`: the last plan's Stall.
fn expectStall(t: *Trace, s: *Scheduler, w: anytype) TraceError!void {
    t.stall_unchecked = false;
    const stall = s.stall orelse return w.writeAll("none");
    try w.print("{s} n_work={d} need={d} free={d}", .{ nameOf(t, stall.req_id), stall.n_work, stall.need_slabs, stall.free_slabs });
}

/// `expect units A g=1 live=5 ring=[3@16,7@32]`: a per_seq group's units between steps
/// (live 0 = none) and its checkpoints as id@pos, oldest first.
fn expectUnits(t: *Trace, s: *Scheduler, words: *std.mem.TokenIterator(u8, .scalar), w: anytype) TraceError!void {
    const name = words.next() orelse return fail(t, "expect units needs a name", .{});
    const g = try parseGroupWord(t, words);
    if (t.groups[g].kind != .per_seq) return fail(t, "expect units: group {d} is not per_seq", .{g});
    const st = s.reqs.requests[try lookup(t, name)].units[g];
    try w.print("live={d} ring=[", .{st.live});
    for (st.ring[0..st.n_ring], 0..) |ckpt, i| try w.print("{s}{d}@{d}", .{ if (i == 0) "" else ",", ckpt.id, ckpt.pos });
    try w.writeAll("]");
}

/// `expect idx A g=1 start=16 read=Z write=[5,0] ckpt=6@row15`: what the plan in flight tells the
/// model for A's entry in per_seq group g. read=Z is ZERO(g); 0 is SCRATCH; ckpt=- is none.
fn expectIdx(t: *Trace, s: *Scheduler, words: *std.mem.TokenIterator(u8, .scalar), w: anytype) TraceError!void {
    const name = words.next() orelse return fail(t, "expect idx needs a name", .{});
    const g = try parseGroupWord(t, words);
    if (t.groups[g].kind != .per_seq) return fail(t, "expect idx: group {d} is not per_seq", .{g});
    const id = try lookup(t, name);
    const p = &s.live().plan;
    const i = for (p.entries[0..p.n_reqs], 0..) |entry, i| {
        if (entry.req_id == id) break i;
    } else return fail(t, "expect idx: {s} is not in the plan", .{name});
    const idx = p.state[g];
    try w.print("start={d} read=", .{p.seq_start[i]});
    if (idx.read[i] == p.zero_units[g]) try w.writeAll("Z") else try w.print("{d}", .{idx.read[i]});
    try w.writeAll(" write=[");
    for (idx.write[i * p.write_width ..][0..p.write_width], 0..) |unit, j| try w.print("{s}{d}", .{ if (j == 0) "" else ",", unit });
    try w.writeAll("]");
    if (idx.ckpt[i] == scheduler.scratch_unit) {
        if (idx.ckpt_row[i] != request.no_row) return fail(t, "expect idx: SCRATCH ckpt with row {d}", .{idx.ckpt_row[i]});
        try w.writeAll(" ckpt=-");
    } else try w.print(" ckpt={d}@row{d}", .{ idx.ckpt[i], idx.ckpt_row[i] });
}

fn parseGroupWord(t: *Trace, words: *std.mem.TokenIterator(u8, .scalar)) TraceError!usize {
    const gword = words.next() orelse return fail(t, "expected g=N", .{});
    if (!std.mem.startsWith(u8, gword, "g=")) return fail(t, "expected g=N, got '{s}'", .{gword});
    const g = try std.fmt.parseInt(usize, gword["g=".len..], 10);
    if (g >= t.n_groups) return fail(t, "g={d}: only {d} groups", .{ g, t.n_groups });
    return g;
}

fn cmdExpect(t: *Trace, words: *std.mem.TokenIterator(u8, .scalar)) TraceError!void {
    const s = &t.sched.?;
    const what = words.next() orelse return fail(t, "expect needs a subject", .{});
    const subject = std.meta.stringToEnum(ExpectSubject, what) orelse return fail(t, "unknown expect '{s}'", .{what});
    var buf: [512]u8 = undefined;
    var fbs = std.io.fixedBufferStream(&buf);
    const w = fbs.writer();
    switch (subject) {
        .batch => blk: {
            const p = &s.live().plan;
            break :blk try expectBatch(t, w, p.entries[0..p.n_reqs]);
        },
        .ahead_batch => blk: {
            const a = s.ahead() orelse break :blk try expectBatch(t, w, &.{});
            break :blk try expectBatch(t, w, a.plan.entries[0..a.plan.n_reqs]);
        },
        .free => try expectFree(s, w),
        .running => try expectRunning(t, s, w),
        .waiting => try expectWaiting(t, s, w),
        .table => try expectTable(t, s, words, w),
        .finished => try expectFinished(t, s, words, w),
        .reserved => try expectReserved(t, s, words, w),
        .n_computed => try expectNComputed(t, s, words, w),
        .polled => try expectPolled(t, words, w),
        .prefix => try expectPrefix(s, w),
        .blocks => try expectBlocks(t, s, words, w),
        .event => return expectEvent(t, words),
        .config_hash => try expectConfigHash(t, s, w),
        .state => try expectState(s, w),
        .launch_ctx => try expectLaunchCtx(t, w),
        .submit => try expectSubmit(t, w),
        .stall => try expectStall(t, s, w),
        .units => try expectUnits(t, s, words, w),
        .idx => try expectIdx(t, s, words, w),
        .rows => try expectRows(t, &s.live().plan, words, w),
        .ahead_rows => {
            const a = s.ahead() orelse return fail(t, "expect ahead_rows: no ahead plan", .{});
            try expectRows(t, &a.plan, words, w);
        },
    }
    try compareRest(t, what, words, fbs.getWritten());
}

/// `expect event n_admitted=1 n_preempted=0`: each key names a StepEvent field of the last committed step.
fn expectEvent(t: *Trace, words: *std.mem.TokenIterator(u8, .scalar)) TraceError!void {
    const ev = t.sched.?.event;
    var buf: [512]u8 = undefined;
    var fbs = std.io.fixedBufferStream(&buf);
    var rest = words.*;
    var first = true;
    while (words.next()) |word| : (first = false) {
        const eq = std.mem.indexOfScalar(u8, word, '=') orelse return fail(t, "bad event key '{s}'", .{word});
        const key = word[0..eq];
        var known = false;
        inline for (@typeInfo(events.StepEvent).@"struct".fields) |f| {
            if (std.mem.eql(u8, f.name, key)) {
                known = true;
                try fbs.writer().print("{s}{s}={}", .{ if (first) "" else " ", key, @field(ev, f.name) });
            }
        }
        if (!known) return fail(t, "unknown event field '{s}'", .{key});
    }
    try compareRest(t, "event", &rest, fbs.getWritten());
}

fn writePolled(t: *Trace, w: anytype, name: []const u8) TraceError!void {
    const s = &t.sched.?;
    const id = try lookup(t, name);
    var out: [64]u32 = undefined;
    const result = poll(s, id, &out);
    try w.writeAll("[");
    for (out[0..result.n_new], 0..) |token, i| try w.print("{s}{d}", .{ if (i == 0) "" else ",", token });
    try w.writeAll("]");
    // poll is pure; the edge queues a release op when a poll first sees finished, and the
    // harness applies it at once (no other op can be queued between the two here).
    if (result.finished) {
        _ = scheduler.release(s, id);
        forget(t, name);
    }
}

fn compareRest(t: *Trace, what: []const u8, words: *std.mem.TokenIterator(u8, .scalar), actual: []const u8) TraceError!void {
    var buf: [512]u8 = undefined;
    var fbs = std.io.fixedBufferStream(&buf);
    var first = true;
    while (words.next()) |word| : (first = false) {
        try fbs.writer().print("{s}{s}", .{ if (first) "" else " ", word });
    }
    const expected = fbs.getWritten();
    if (std.mem.eql(u8, expected, actual)) return;
    return fail(t, "expect {s}\n  expected: {s}\n  actual:   {s}", .{ what, expected, actual });
}

fn fail(t: *Trace, comptime fmt: []const u8, args: anytype) TraceError {
    std.debug.print("\n{s}:{d}: " ++ fmt ++ "\n", .{ t.path, t.line_no } ++ args);
    return error.TraceFailed;
}

fn lookup(t: *Trace, name: []const u8) TraceError!u32 {
    for (t.names, t.ids) |slot, id| {
        if (slot != null and std.mem.eql(u8, slot.?, name)) return id;
    }
    return fail(t, "unknown request '{s}'", .{name});
}

fn nameOf(t: *const Trace, id: u32) []const u8 {
    for (t.names, t.ids) |slot, slot_id| {
        if (slot != null and slot_id == id) return slot.?;
    }
    return "?";
}

fn forget(t: *Trace, name: []const u8) void {
    for (&t.names) |*slot| {
        if (slot.* != null and std.mem.eql(u8, slot.*.?, name)) slot.* = null;
    }
}

test "inline smoke trace" {
    try runTrace(std.testing.allocator, "<inline>",
        \\config max_batch_tokens=8 max_batch_reqs=4 block_size=4 num_blocks=8 reserve_ratio=0 order=running_first eos=99
        \\submit A prompt=5 max_new=3
        \\step tokens=A:7
        \\  expect batch A:5
        \\  expect free 5
        \\  expect event step=1 n_admitted=1 n_prefill_reqs=1 n_decode_reqs=0 n_tokens=5 kv_used=2 is_idle=false
        \\step
        \\  expect batch A:1
        \\step
        \\expect finished A reason=finished_length
        \\expect polled A [7,1,1]
    );
}

test "kept= other than 1 fails the trace while max_extra = 0" {
    try std.testing.expectError(error.TraceFailed, runTrace(std.testing.allocator, "<inline>",
        \\config max_batch_tokens=8 max_batch_reqs=4 block_size=4 num_blocks=8
        \\submit A prompt=5 max_new=3
        \\step kept=A:2
    ));
}

/// K = 0 sugar for the unit tests below: one sampled token per entry.
fn commitSampled(s: *Scheduler, sampled: []const u32) void {
    commit(s, .{ .tokens = sampled, .stride = 1, .n_tokens = &.{}, .next_extra = &.{} });
}

test "mm_hash round-trips from submit to the plan entry" {
    const allocator = std.testing.allocator;
    const groups = [_]request.GroupSpec{.{ .kind = .per_token, .block_size = 4 }};
    var reqs = try request.Pool.init(allocator, .{ .max_requests = 2, .max_seq_len = 16, .groups = &groups });
    defer reqs.deinit(allocator);
    var kv = try kv_pool.flatInit(allocator, 16, 4, @intCast(groups.len));
    defer kv.deinit(allocator);
    var s = try Scheduler.init(allocator, .{ .max_batch_tokens = 16, .max_batch_reqs = 2, .reserve_ratio = 0, .order = .running_first, .eos_token = 99 }, &reqs, &kv);
    defer s.deinit(allocator);

    // Identical placeholder ids, different image content: the hash is the only thing telling them apart.
    const prompt = [_]u32{ 7, 7, 7 };
    const a = try submitMm(&s, &prompt, request.samplingParams(1, 0, 0), .{ .hash = 0xDEADBEEF_CAFEF00D, .start = 0 });
    const b = try submit(&s, &prompt, request.samplingParams(1, 0, 0));
    const p = plan(&s);
    try std.testing.expectEqual(2, p.n_reqs);
    for (p.entries[0..p.n_reqs], p.mm_hashes[0..p.n_reqs]) |entry, h| {
        if (entry.req_id == a) try std.testing.expectEqual(0xDEADBEEF_CAFEF00D, h);
        if (entry.req_id == b) try std.testing.expectEqual(0, h);
    }
    commitSampled(&s, &.{ 1, 1 });
}

test "a stop token finishes the request as finished_eos, same as the scheduler's eos_token" {
    const allocator = std.testing.allocator;
    const groups = [_]request.GroupSpec{.{ .kind = .per_token, .block_size = 4 }};
    var reqs = try request.Pool.init(allocator, .{ .max_requests = 2, .max_seq_len = 16, .groups = &groups });
    defer reqs.deinit(allocator);
    var kv = try kv_pool.flatInit(allocator, 16, 4, @intCast(groups.len));
    defer kv.deinit(allocator);
    // eos_token = 99 so it can never fire on its own; only the request's own stop set (42) can.
    var s = try Scheduler.init(allocator, .{ .max_batch_tokens = 16, .max_batch_reqs = 2, .reserve_ratio = 0, .order = .running_first, .eos_token = 99 }, &reqs, &kv);
    defer s.deinit(allocator);

    const prompt = [_]u32{ 1, 2, 3 };
    const stop_ids = [_]u32{ 42, 43 };
    const rid = try scheduler.submitMmStop(&s, &prompt, request.samplingParams(10, 0, 0), .{ .hash = 0, .start = 0 }, &stop_ids);

    // Prefill: any non-stop token, request stays running.
    _ = plan(&s);
    commitSampled(&s, &.{7});
    try std.testing.expectEqual(request.State.running, reqs.requests[rid].state);

    // Decode: sample the stop token (42, not the scheduler's eos_token 99). The request must
    // finish as finished_eos, exactly like hitting the scheduler-wide eos_token would.
    _ = plan(&s);
    commitSampled(&s, &.{42});
    try std.testing.expectEqual(request.State.finished_eos, reqs.requests[rid].state);

    // Finished: the next plan must not schedule it again.
    const p = plan(&s);
    try std.testing.expectEqual(0, p.n_reqs);
    commitSampled(&s, &.{});
}

test "every knob is tier 0 (live) today" {
    inline for (@typeInfo(std.meta.Tag(Knob)).@"enum".fields) |f| {
        try std.testing.expectEqual(Tier.live, Knob.tier(@field(std.meta.Tag(Knob), f.name)));
    }
    try std.testing.expectEqual(@as(u8, 0), @intFromEnum(Tier.live));
}

test "validateKnob rejects values the static buffers cannot hold; applyKnob rehashes" {
    // The queue itself (bounded at 64, apply_step exact) is the inbox's: c_api.zig tests it.
    const allocator = std.testing.allocator;
    const groups = [_]request.GroupSpec{.{ .kind = .per_token, .block_size = 4 }};
    var reqs = try request.Pool.init(allocator, .{ .max_requests = 8, .max_seq_len = 64, .groups = &groups });
    defer reqs.deinit(allocator);
    var kv = try kv_pool.flatInit(allocator, 16, 4, @intCast(groups.len));
    defer kv.deinit(allocator);
    const cfg = Config{ .max_batch_tokens = 8, .max_batch_reqs = 4, .reserve_ratio = 0, .order = .running_first, .eos_token = 99 };
    var s = try Scheduler.init(allocator, cfg, &reqs, &kv);
    defer s.deinit(allocator);
    try std.testing.expectError(error.Invalid, validateKnob(&s, .{ .max_batch_tokens = 9 }));
    try std.testing.expectError(error.Invalid, validateKnob(&s, .{ .max_batch_reqs = 0 }));
    try std.testing.expectError(error.Invalid, validateKnob(&s, .{ .reserve_ratio = -1 }));
    try validateKnob(&s, .{ .max_batch_tokens = 4 });
    const h0 = s.config_hash;
    applyKnob(&s, .{ .order = .running_first }); // the value it already has: same hash
    try std.testing.expectEqual(h0, s.config_hash);
    applyKnob(&s, .{ .max_batch_tokens = 4 });
    try std.testing.expect(s.config_hash != h0);
    try std.testing.expectEqual(@as(u32, 4), s.cfg.max_batch_tokens);
    _ = plan(&s);
    commitSampled(&s, &.{});
    try std.testing.expectEqual(s.config_hash, s.event.config_hash);
}

test "trace files" {
    const allocator = std.testing.allocator;
    var dir = try std.fs.cwd().openDir("traces", .{ .iterate = true });
    defer dir.close();
    var n_traces: u32 = 0;
    var it = dir.iterate();
    while (try it.next()) |entry| {
        if (!std.mem.endsWith(u8, entry.name, ".txt") or entry.name[0] == '.') continue;
        const text = try dir.readFileAlloc(allocator, entry.name, 1 << 20);
        defer allocator.free(text);
        var path_buf: [256]u8 = undefined;
        const path = try std.fmt.bufPrint(&path_buf, "traces/{s}", .{entry.name});
        try runTrace(allocator, path, text);
        n_traces += 1;
    }
    try std.testing.expect(n_traces >= 28);
}
