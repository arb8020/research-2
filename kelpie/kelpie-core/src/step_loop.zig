const std = @import("std");
const assert = std.debug.assert;

/// One owner for planning, launch selection, and commit. All storage is supplied at init.
///
/// Every step is the same sequence at every world size (docs/design-multigpu.md 2.3):
///
///   boundary_fn   [no lock]  drain the inbox + exchange the batch (world 1: identity)
///   apply_fn      [lock]     apply the batch's ops (a swap op makes `pending`)
///   plan_fn       [lock]     plan + digest
///   agree_fn      [no lock]  digest agreement (world 1: nothing)
///   launch        [no lock]  the step fn fills Out
///   payload_fn    [no lock]  payload agreement: rank 0's Out wins (world 1: nothing)
///   commit_fn     [lock]     validate + commit + commit ring
///
/// Under overlap the boundary for plan N+1 runs between launch_async(N) and launch_wait(N), so
/// ops pushed during forward N apply before plan N+1, exactly one boundary per plan.
pub fn State(comptime Plan: type, comptime Out: type) type {
    return struct {
        const Self = @This();
        /// (captured, shape, plan, out) -> status (0 ok). `shape` is Plan.shape: a
        /// deterministic packing of the plan (see c_api.zig stepShape()) the plugin may ignore
        /// and recompute from `plan` itself; the two must never disagree. `out` is owner-owned
        /// (KelpieStepOut) and must be filled for every real entry.
        pub const LaunchFn = *const fn (*anyopaque, u32, *const Plan, *Out) callconv(.c) u32;
        pub const LaunchAsyncFn = LaunchFn;
        pub const LaunchWaitFn = *const fn (*anyopaque, *Out) callconv(.c) u32;
        /// -> true when the batch says stop (the edge closed). `stopping`: this rank is the edge
        /// and is closing, so the batch it sends carries the stop flag.
        pub const BoundaryFn = *const fn (*anyopaque, bool) bool;
        pub const ApplyFn = *const fn (*anyopaque) void;
        pub const PlanFn = *const fn (*anyopaque, *Plan, u32) u32;
        pub const AgreeFn = *const fn (*anyopaque, *const Plan) void;
        pub const RefreshFn = *const fn (*anyopaque, *Plan, u32) void;
        pub const PayloadFn = *const fn (*anyopaque, u32) void;
        pub const CommitFn = *const fn (*anyopaque, u32) void;
        pub const DrainFn = *const fn (*anyopaque, bool) bool;
        /// A swap registered for `epoch` was installed (the owner may take the next one).
        pub const InstalledFn = *const fn (*anyopaque, u64) void;
        /// Called on the step thread right before the forward is launched / right after it
        /// has returned its tokens (after launch_wait under overlap), with the mutex NOT held.
        /// The loop owns the forward now, so the loop is what brackets it: the owner turns these
        /// into the StepEvent's t_forward_ns (c_api.zig forwardBeginOpaque/forwardEndOpaque).
        pub const ForwardMarkFn = *const fn (*anyopaque) void;

        /// How the loop waits between steps. `wake`: until kelpie_wake (world 1). `heartbeat`:
        /// a rank-0 edge with a sync registered also steps (an empty batch) every second, so
        /// followers blocked in the exchange never hit a collective timeout. `none`: a follower
        /// blocks in the exchange itself.
        pub const WaitMode = enum { wake, heartbeat, none };
        const heartbeat_ns: u64 = std.time.ns_per_s;

        pub const Pending = struct { launch: LaunchFn, captured: *anyopaque, drain: bool, epoch: u64 };

        mutex: std.Thread.Mutex = .{},
        condition: std.Thread.Condition = .{},
        thread: ?std.Thread = null,
        /// run() returned (a stop, or the edge's stop batch) and the thread is not joined yet.
        exited: bool = false,
        stop: bool = false,
        wake_pending: bool = false,
        launch: ?LaunchFn = null,
        launch_async: ?LaunchAsyncFn = null,
        launch_wait: ?LaunchWaitFn = null,
        captured: ?*anyopaque = null,
        pending: ?Pending = null,
        /// Bumped once each time a pending swap actually takes effect at a step boundary. The
        /// owner of the retired CapturedModel frees it only after observing a higher epoch, so
        /// no launch can still be reading storage that Python has released.
        epoch: u64 = 0,
        owner: *anyopaque,
        boundary_fn: BoundaryFn,
        apply_fn: ApplyFn,
        plan_fn: PlanFn,
        agree_fn: AgreeFn,
        refresh_fn: RefreshFn,
        payload_fn: PayloadFn,
        commit_fn: CommitFn,
        drain_fn: DrainFn,
        installed_fn: InstalledFn,
        forward_begin_fn: ForwardMarkFn,
        forward_end_fn: ForwardMarkFn,
        out: *Out,
        overlap: bool = false,
        wait_mode: WaitMode = .wake,

        pub fn register(self: *Self, launch: LaunchFn, captured: *anyopaque) bool {
            self.mutex.lock();
            defer self.mutex.unlock();
            if (self.thread != null or self.launch != null) return false;
            self.launch, self.captured = .{ launch, captured };
            return true;
        }

        pub fn registerSplit(self: *Self, launch: LaunchFn, launch_async: LaunchAsyncFn, launch_wait: LaunchWaitFn, captured: *anyopaque) bool {
            if (!self.register(launch, captured)) return false;
            self.launch_async = launch_async;
            self.launch_wait = launch_wait;
            return true;
        }

        /// A swap op applied (apply_fn, mutex held): the loop installs it at this and every
        /// later boundary until it can (a draining swap waits for the running set to empty).
        pub fn setPendingLocked(self: *Self, pending: Pending) void {
            assert(self.pending == null); // the owner queues one swap at a time
            self.pending = pending;
        }

        pub fn start(self: *Self) !void {
            self.mutex.lock();
            defer self.mutex.unlock();
            if (self.thread != null or self.launch == null) return error.BadState;
            self.stop = false;
            self.exited = false;
            self.wake_pending = true;
            self.thread = try std.Thread.spawn(.{}, runAndMark, .{self});
        }

        pub fn wake(self: *Self) void {
            self.mutex.lock();
            defer self.mutex.unlock();
            self.wake_pending = true;
            self.condition.signal();
        }

        pub fn stopAndJoin(self: *Self) void {
            self.mutex.lock();
            const thread = self.thread orelse {
                self.mutex.unlock();
                return;
            };
            self.stop = true;
            self.condition.signal();
            self.mutex.unlock();
            thread.join();
            self.mutex.lock();
            self.thread = null;
            self.mutex.unlock();
        }

        /// Reads the swap-applied acknowledgement. `epoch` only ever increases; a caller that
        /// saw `e` before swap() may free the retired launch context once it observes > e.
        pub fn appliedEpoch(self: *Self) u64 {
            self.mutex.lock();
            defer self.mutex.unlock();
            return self.epoch;
        }

        fn applySwapAtBoundary(self: *Self) void {
            const pending = self.pending orelse return;
            if (!pending.drain) {
                self.apply(pending);
                return;
            }
            if (!self.drain_fn(self.owner, true)) return;
            self.apply(pending);
            assert(self.drain_fn(self.owner, false));
        }

        /// The one place a swap takes effect: install the new pair and publish the epoch, so
        /// "swap applied" and "epoch bumped" can never disagree.
        fn apply(self: *Self, pending: Pending) void {
            self.launch, self.captured = .{ pending.launch, pending.captured };
            self.pending = null;
            self.epoch += 1;
            self.installed_fn(self.owner, pending.epoch);
        }

        /// Wait for work (mutex held on entry and exit). -> false when stopping.
        fn waitForWork(self: *Self) bool {
            switch (self.wait_mode) {
                .wake => while (!self.stop and !self.wake_pending) self.condition.wait(&self.mutex),
                .heartbeat => if (!self.stop and !self.wake_pending) {
                    self.condition.timedWait(&self.mutex, heartbeat_ns) catch {};
                },
                .none => {},
            }
            // A follower stops only when the edge's batch says so; stop_loop on a follower is
            // honoured at its next boundary (boundary_fn reads it through `stopping`).
            if (self.stop and self.wait_mode != .none) return false;
            self.wake_pending = false;
            return true;
        }

        /// The boundary before a plan: drain + exchange with no lock, then apply + plan under
        /// it. Returns n_tokens (0 idle), or null when the batch said stop. Mutex NOT held on
        /// entry; held on a non-null return.
        fn boundaryAndPlan(self: *Self, plan: *Plan, slot: u32) ?u32 {
            if (self.boundary_fn(self.owner, false)) return null;
            self.mutex.lock();
            self.apply_fn(self.owner);
            self.applySwapAtBoundary();
            return self.plan_fn(self.owner, plan, slot);
        }

        fn runAndMark(self: *Self) void {
            self.run();
            self.mutex.lock();
            defer self.mutex.unlock();
            self.exited = true;
        }

        fn run(self: *Self) void {
            var plans: [2]Plan = undefined;
            var current: u32 = 0;
            var have_plan = false;
            while (true) {
                self.mutex.lock();
                // A heartbeat edge with a plan ahead in flight finishes it first: its followers
                // are at the same point and expect the ahead plan's launch, not a boundary.
                if (!self.waitForWork() and !(have_plan and self.wait_mode == .heartbeat)) {
                    self.mutex.unlock();
                    // The edge of a synced world tells its followers (world 1: no one to tell).
                    if (self.wait_mode == .heartbeat) _ = self.boundary_fn(self.owner, true);
                    return;
                }
                const ahead = have_plan;
                var n_tokens: u32 = undefined;
                if (have_plan) {
                    n_tokens = plans[current].n_tokens;
                } else {
                    self.mutex.unlock();
                    n_tokens = self.boundaryAndPlan(&plans[current], current) orelse return;
                }
                have_plan = false;
                if (n_tokens == 0) {
                    self.commit_fn(self.owner, 0);
                    self.applySwapAtBoundary();
                    self.mutex.unlock();
                    if (!ahead) self.agree_fn(self.owner, &plans[current]);
                    continue;
                }
                const plan = &plans[current];
                const launch, const captured = .{ self.launch.?, self.captured.? };
                const step = plan.step;
                const shape = plan.shape;
                const n_reqs = plan.n_reqs;
                self.mutex.unlock();
                if (!ahead) self.agree_fn(self.owner, plan); // an ahead plan agreed after its refresh
                if (self.overlap) {
                    const launch_async = self.launch_async orelse std.debug.panic("overlap requires split launch", .{});
                    const launch_wait = self.launch_wait orelse std.debug.panic("overlap requires split launch", .{});
                    self.forward_begin_fn(self.owner);
                    var status = launch_async(captured, shape, plan, self.out);
                    if (status != 0) std.debug.panic("launch_async failed: status={d} step={d} shape={d} n_reqs={d}", .{ status, step, shape, n_reqs });
                    // The overlap window: the boundary for N+1, then plan N+1 on the host while
                    // the GPU runs N's forward. N+1's decode rows hold reservation sentinels,
                    // since the tokens that belong there are exactly what N's commit produces.
                    const next: u32 = current ^ 1;
                    _ = self.boundaryAndPlan(&plans[next], next) orelse std.debug.panic("stop inside an overlap window", .{}); // n_tokens is restated by refresh below
                    self.mutex.unlock();
                    status = launch_wait(captured, self.out);
                    if (status != 0) std.debug.panic("launch_wait failed: status={d} step={d} shape={d} n_reqs={d}", .{ status, step, shape, n_reqs });
                    self.forward_end_fn(self.owner);
                    self.payload_fn(self.owner, n_reqs);
                    self.mutex.lock();
                    // Order matters: commit(N) replaces every sentinel in the canonical Sequence,
                    // and only then can refresh mirror the real tokens into the promoted plan.
                    self.commit_fn(self.owner, n_reqs);
                    self.refresh_fn(self.owner, &plans[next], next);
                    current = next;
                    have_plan = true;
                    self.applySwapAtBoundary();
                    self.wake_pending = true;
                    self.mutex.unlock();
                    // The promoted plan's digest is final only now (refresh): agree on it here,
                    // before the next iteration launches (or idles on) it.
                    self.agree_fn(self.owner, &plans[current]);
                    continue;
                }
                self.forward_begin_fn(self.owner);
                const status = launch(captured, shape, plan, self.out);
                if (status != 0) std.debug.panic("launch failed: status={d} step={d} shape={d} n_reqs={d}", .{ status, step, shape, n_reqs });
                self.forward_end_fn(self.owner);
                self.payload_fn(self.owner, n_reqs);
                self.mutex.lock();
                self.commit_fn(self.owner, n_reqs);
                self.applySwapAtBoundary();
                self.wake_pending = true;
                self.mutex.unlock();
            }
        }
    };
}

const OrderPlan = struct { n_tokens: u32, n_reqs: u32, step: u64, shape: u32 };
const OrderOut = struct { token: u32 = 0 };
const OrderOwner = struct {
    events: [32]u8 = undefined,
    n_events: usize = 0,
    plans: u32 = 0,
    commits: std.atomic.Value(u32) = .init(0),

    fn push(self: *OrderOwner, event: u8) void {
        if (self.n_events == self.events.len) return;
        self.events[self.n_events] = event;
        self.n_events += 1;
    }
};

fn orderOwner(ctx: *anyopaque) *OrderOwner {
    return @ptrCast(@alignCast(ctx));
}
fn orderBoundary(ctx: *anyopaque, _: bool) bool {
    orderOwner(ctx).push('b');
    return false;
}
fn orderApply(_: *anyopaque) void {}
fn orderPlan(ctx: *anyopaque, out: *OrderPlan, _: u32) u32 {
    const owner = orderOwner(ctx);
    owner.push('p');
    owner.plans += 1;
    out.* = .{ .n_tokens = 1, .n_reqs = 1, .step = owner.plans, .shape = 1 };
    return 1;
}
fn orderAgree(ctx: *anyopaque, _: *const OrderPlan) void {
    orderOwner(ctx).push('g');
}
fn orderRefresh(ctx: *anyopaque, _: *OrderPlan, _: u32) void {
    orderOwner(ctx).push('r');
}
fn orderPayload(ctx: *anyopaque, _: u32) void {
    orderOwner(ctx).push('x');
}
fn orderCommit(ctx: *anyopaque, _: u32) void {
    const owner = orderOwner(ctx);
    owner.push('c');
    _ = owner.commits.fetchAdd(1, .release);
}
fn orderDrain(_: *anyopaque, _: bool) bool {
    return true;
}
fn orderInstalled(_: *anyopaque, _: u64) void {}
fn orderForwardBegin(ctx: *anyopaque) void {
    orderOwner(ctx).push('[');
}
fn orderForwardEnd(ctx: *anyopaque) void {
    orderOwner(ctx).push(']');
}
fn orderLaunch(_: *anyopaque, _: u32, _: *const OrderPlan, _: *OrderOut) callconv(.c) u32 {
    return 0;
}
fn orderAsync(ctx: *anyopaque, _: u32, _: *const OrderPlan, _: *OrderOut) callconv(.c) u32 {
    orderOwner(ctx).push('a');
    return 0;
}
fn orderWait(ctx: *anyopaque, _: *OrderOut) callconv(.c) u32 {
    orderOwner(ctx).push('w');
    return 0;
}

fn orderState(owner: *OrderOwner, out: *OrderOut, overlap: bool) State(OrderPlan, OrderOut) {
    return .{
        .owner = owner,
        .boundary_fn = orderBoundary,
        .apply_fn = orderApply,
        .plan_fn = orderPlan,
        .agree_fn = orderAgree,
        .refresh_fn = orderRefresh,
        .payload_fn = orderPayload,
        .commit_fn = orderCommit,
        .drain_fn = orderDrain,
        .installed_fn = orderInstalled,
        .forward_begin_fn = orderForwardBegin,
        .forward_end_fn = orderForwardEnd,
        .out = out,
        .overlap = overlap,
    };
}

test "one boundary per plan: boundary, plan, agree, launch, payload, commit" {
    var owner = OrderOwner{};
    var out = OrderOut{};
    var state = orderState(&owner, &out, false);
    try std.testing.expect(state.register(orderLaunch, &owner));
    try state.start();
    while (owner.commits.load(.acquire) < 2) std.Thread.yield() catch {};
    state.stopAndJoin();
    try std.testing.expectEqualStrings("bpg[]xcbpg[]xc", owner.events[0..14]);
}

test "overlap: the boundary and plan N+1 run between async and wait, then N commits and N+1 agrees" {
    var owner = OrderOwner{};
    var out = OrderOut{};
    var state = orderState(&owner, &out, true);
    try std.testing.expect(state.registerSplit(orderLaunch, orderAsync, orderWait, &owner));
    try state.start();
    while (owner.commits.load(.acquire) < 2) std.Thread.yield() catch {};
    state.stopAndJoin();
    // Plan N+1's boundary (b) and plan (p) land inside the forward window [ .. ]; N+1 agrees (g)
    // after refresh (r), once, and its launch then needs no boundary of its own.
    try std.testing.expectEqualStrings("bpg[abpw]xcrg[abpw]xcrg", owner.events[0..23]);
}
