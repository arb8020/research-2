//! Wide events (docs/observability.md): the core fills these as it runs, Python copies them out.
//! StepEvent is published at commit; RequestEvent lives in the request slot and is complete at finish/cancel.
//! Timestamps are ns since Clock.init (monotonic); durations come from start/stop pairs.

const std = @import("std");
const assert = std.debug.assert;

pub const StepEvent = extern struct {
    step: u64,
    t_plan_ns: u64,
    t_forward_ns: u64,
    t_commit_ns: u64,
    n_running: u32,
    n_waiting: u32,
    n_prefill_reqs: u32,
    n_decode_reqs: u32,
    n_tokens: u32,
    kv_free: u32,
    kv_used: u32,
    n_admitted: u32,
    n_preempted: u32,
    n_finished: u32,
    n_rejected_full: u32,
    /// Prefix cache at admission (admitted requests only): queries, those with a hit, tokens skipped.
    prefix_queries: u32,
    prefix_hits: u32,
    prefix_hit_tokens: u32,
    order: u32,
    /// scheduler.hashConfig of the live Config this step planned under.
    config_hash: u64,
    is_idle: bool,
    /// Extra rows (docs/design-core-option2.md): planned over the step's entries, and kept at
    /// its commit (committed tokens beyond one per entry). Both 0 while max_extra = 0.
    /// Renamed from n_draft_tokens / n_accepted_tokens, same offsets.
    n_extra_rows: u32,
    n_extra_kept: u32,
};

pub const RequestEvent = extern struct {
    t_arrival_ns: u64,
    t_first_sched_ns: u64,
    t_first_token_ns: u64,
    t_last_token_ns: u64,
    t_finish_ns: u64,
    first_step: u64,
    last_step: u64,
    request_id: u32,
    n_prompt: u32,
    n_gen: u32,
    max_new: u32,
    n_preemptions: u32,
    n_chunks: u32,
    finish_reason: u32, // request.State ordinal
    kv_blocks_peak: u32,
};

pub const Timing = enum(u32) { plan, forward, commit };

const n_timings = @typeInfo(Timing).@"enum".fields.len;
const not_started = std.math.maxInt(u64);

/// Fixed storage, one in-flight start per Timing. Unpaired start/stop is a bug and asserts.
pub const Clock = struct {
    origin: std.time.Instant,
    started: [n_timings]u64,

    pub fn init() Clock {
        const c = Clock{ .origin = std.time.Instant.now() catch unreachable, .started = [_]u64{not_started} ** n_timings };
        assert(c.started[0] == not_started);
        return c;
    }
};

pub fn now(c: *const Clock) u64 {
    const t = std.time.Instant.now() catch unreachable;
    return t.since(c.origin);
}

pub fn start(c: *Clock, which: Timing) void {
    const slot = &c.started[@intFromEnum(which)];
    assert(slot.* == not_started);
    slot.* = now(c);
    assert(slot.* != not_started);
}

pub fn stop(c: *Clock, which: Timing) u64 {
    const slot = &c.started[@intFromEnum(which)];
    assert(slot.* != not_started);
    const t = now(c);
    assert(t >= slot.*);
    const elapsed = t - slot.*;
    slot.* = not_started;
    return elapsed;
}

pub fn inFlight(c: *const Clock, which: Timing) bool {
    return c.started[@intFromEnum(which)] != not_started;
}

test "start/stop pairs measure elapsed time" {
    var c = Clock.init();
    try std.testing.expect(!inFlight(&c, .forward));
    start(&c, .forward);
    try std.testing.expect(inFlight(&c, .forward));
    std.time.sleep(1_000_000);
    const d = stop(&c, .forward);
    try std.testing.expect(d >= 1_000_000);
    try std.testing.expect(!inFlight(&c, .forward));
    start(&c, .forward);
    _ = stop(&c, .forward);
}
