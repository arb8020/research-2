//! The bucket ladder: the one owner of how a plan's shape is rounded up.
//!
//! Both axes (tokens and requests) use the same powers-of-two ladder. Every other reader --
//! the padded KelpiePlan the scheduler emits, KelpiePlan.shape's packing (c_api.zig stepShape),
//! kelpie._ffi.BUCKETS, kelpie_models.plan.BUCKETS -- reads it from here through
//! kelpie_bucket_count / kelpie_bucket_at rather than restating it. Python must never keep a
//! second ladder: a value with two writers drifts (docs/friction-2026-09-09.md section 1).

const std = @import("std");
const assert = std.debug.assert;

pub const BUCKETS = [_]u32{ 1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096, 8192 };

/// The smallest bucket >= n. Asserts n > 0 and n <= the largest bucket.
pub fn bucket(n: u32) u32 {
    assert(n > 0);
    for (BUCKETS) |b| {
        if (b >= n) return b;
    }
    unreachable; // callers bound n by max_batch_tokens/reqs, both checked <= 8192 at create
}

/// The index of the smallest bucket >= n; what travels in KelpiePlan.shape (not the value).
pub fn bucketIndex(n: u32) u32 {
    assert(n > 0);
    for (BUCKETS, 0..) |b, i| {
        if (b >= n) return @intCast(i);
    }
    unreachable;
}

/// The ladder over the C ABI, so Python has no second copy.
export fn kelpie_bucket_count() u32 {
    return BUCKETS.len;
}

export fn kelpie_bucket_at(i: u32) u32 {
    return if (i < BUCKETS.len) BUCKETS[i] else 0;
}

test "bucket rounds up to the next power of two" {
    try std.testing.expectEqual(@as(u32, 1), bucket(1));
    try std.testing.expectEqual(@as(u32, 4), bucket(3));
    try std.testing.expectEqual(@as(u32, 4), bucket(4));
    try std.testing.expectEqual(@as(u32, 8), bucket(5));
    try std.testing.expectEqual(@as(u32, 8192), bucket(8192));
}

test "bucketIndex agrees with bucket" {
    for (BUCKETS, 0..) |b, i| {
        try std.testing.expectEqual(@as(u32, @intCast(i)), bucketIndex(b));
        try std.testing.expectEqual(b, bucket(b));
    }
    try std.testing.expectEqual(bucket(3), BUCKETS[bucketIndex(3)]);
}

test "the exported ladder is the ladder" {
    try std.testing.expectEqual(@as(u32, BUCKETS.len), kelpie_bucket_count());
    for (BUCKETS, 0..) |b, i| try std.testing.expectEqual(b, kelpie_bucket_at(@intCast(i)));
    try std.testing.expectEqual(@as(u32, 0), kelpie_bucket_at(BUCKETS.len));
}
