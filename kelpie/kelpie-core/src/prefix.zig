//! Prefix cache: a hash chain over full blocks (docs/design-rules.md, "Prefix cache").
//! match finds the longest cached prefix of a token sequence; insert publishes blocks that became full;
//! release drops a request's blocks. The scheduler sees block ids and token counts, never hashes.
//!
//! hash(block_i) = wyhash(seed = hash(block_{i-1}) ^ fold_i, tokens of block i); hash(block_-1) = 0.
//! fold_i = mm.hash for every block from the one containing mm.start on (image content mixed into the
//! chain: identical placeholder ids with different pixels never hit), 0 otherwise. Text-only requests
//! carry mm.hash == 0, which folds as the identity, so their hashes are unchanged.
//! Only full blocks are hashed, and the last token of a sequence is never matched: its logits are the
//! reason the request runs, so at least one token is always computed.
//! A block of a stride-k group covers `tokensPerBlock = k * block_size` tokens: the chain hashes that
//! many tokens per block and a hit is a multiple of it (docs/cache-groups-ladder.md Q3, "grain u").

const std = @import("std");
const assert = std.debug.assert;
const request = @import("request.zig");
const kv_pool = @import("kv_pool.zig");

pub const Match = struct { n_hit: u32, ids: []u32 };

pub const Mm = request.Mm;
pub const text_only = Mm{ .hash = 0, .start = 0 };

/// Pure: fills into[0..n_hit / block_size] with the hit block ids, oldest first, takes no references.
/// The hit rule depends on the group's retention: `all` is prefix-closed (stop at the first miss);
/// `window(W)` is not closed (see matchWindow). A not-cacheable window never hits: recomputing the
/// last W tokens from an empty ring cannot reproduce their hidden states (cache-groups-ladder.md
/// "As built (derisk/dsv4)", correcting Q3's `hit_g(t) = t - W`), so it is not modelled here at all.
pub fn match(pool: *const kv_pool.Pool, g: u32, group: request.GroupSpec, tokens: []const u32, into: []u32, mm: Mm) Match {
    return matchUpTo(pool, g, group, tokens, into, mm, std.math.maxInt(u32));
}

/// `match` capped at `cap` tokens: the longest hit this group supports that is <= cap. The
/// cross-group fixpoint (scheduler.claimPrefix) needs this because a window or per_seq group's
/// answer depends on WHERE it is asked -- shortening the candidate for one group can make
/// another group's run resumable (or not), so one pass of `min` over independent scans is not
/// a fixed point (docs/cache-groups-ladder.md Q3, vLLM HybridKVCacheCoordinator).
pub fn matchUpTo(pool: *const kv_pool.Pool, g: u32, group: request.GroupSpec, tokens: []const u32, into: []u32, mm: Mm, cap: u32) Match {
    assert(tokens.len > 0);
    if (cap == 0) return .{ .n_hit = 0, .ids = into[0..0] };
    // Rule (c): a checkpointing per_seq group hashes its checkpoint units like a stride-S page,
    // so a boundary at t is a hit for exactly t tokens. S = 0 never checkpoints and never hits
    // (docs/cache-groups-ladder.md Q3, "per_seq, stride 0").
    if (group.kind == .per_seq) {
        if (group.stride == 0 or !seqCacheable(group)) return .{ .n_hit = 0, .ids = into[0..0] };
        return matchSeq(pool, g, group, tokens, into, mm, cap);
    }
    switch (group.retention) {
        .all => return matchAll(pool, g, group, tokens, into, mm, cap),
        .window => |w| {
            if (!w.cacheable) return .{ .n_hit = 0, .ids = into[0..0] };
            return matchWindow(pool, g, group, w.w, tokens, into, mm, cap);
        },
    }
}

fn matchAll(pool: *const kv_pool.Pool, g: u32, group: request.GroupSpec, tokens: []const u32, into: []u32, mm: Mm, cap: u32) Match {
    const bs = request.tokensPerBlock(group);
    const n_full: u32 = @min(@as(u32, @intCast((tokens.len - 1) / bs)), cap / bs);
    assert(n_full <= into.len);
    var prev: u64 = groupSeed(g);
    var n_hit_blocks: u32 = 0;
    while (n_hit_blocks < n_full) : (n_hit_blocks += 1) {
        const block_tokens = tokens[n_hit_blocks * bs ..][0..bs];
        const hash = hashBlock(seed(prev, mm, n_hit_blocks, bs), block_tokens);
        const id = kv_pool.lookup(pool, g, hash) orelse break;
        // Collision guard: the stored tokens must be exactly this block's (a chain hash equal by accident
        // would otherwise serve another prompt's KV).
        if (!std.mem.eql(u32, kv_pool.blockTokens(pool, g, id), block_tokens)) break;
        into[n_hit_blocks] = id;
        prev = hash;
    }
    assert(n_hit_blocks * bs < tokens.len);
    return .{ .n_hit = n_hit_blocks * bs, .ids = into[0..n_hit_blocks] };
}

/// A cacheable window group is not prefix-closed: a boundary `t` (a multiple of `bs`) is resumable
/// iff the `ceil((W-1)/bs)` blocks covering `[t-W, t)` are all present (vLLM SlidingWindowManager,
/// TokenSpeed SwaMatcher). Blocks older than the window may be missing without invalidating a hit,
/// so this scans candidate boundaries right to left, largest first, and for each recomputes the
/// pure chain hash from block 0 (no lookups: those blocks are only needed for their hash value, not
/// their presence) up to the window's first block, then looks up just the blocks in the window.
fn matchWindow(pool: *const kv_pool.Pool, g: u32, group: request.GroupSpec, w: u32, tokens: []const u32, into: []u32, mm: Mm, cap: u32) Match {
    assert(w > 0);
    const bs = request.tokensPerBlock(group);
    const n_full: u32 = @min(@as(u32, @intCast((tokens.len - 1) / bs)), cap / bs);
    assert(n_full <= into.len);
    // Q3: the run ending at t must cover ceil((W-1)/bs) blocks -- no "+1 in-flight" term, unlike
    // windowRows (that one sizes the decode-time plateau, which includes the row being written).
    const window_blocks = (w - 1 + bs - 1) / bs;
    var t_blocks = n_full;
    while (t_blocks > 0) : (t_blocks -= 1) {
        const first = t_blocks -| window_blocks;
        if (windowRunHits(pool, g, group, first, t_blocks, tokens, into, mm)) {
            // `first` here equals firstLiveRow(t_blocks * bs) (checked by construction: both floor
            // n_hit - W + 1 to bs), so rows [0, first) are exactly the rows a resumed request's own
            // slideOut would free -- report only the live rows, never the un-filled prefix below them.
            return .{ .n_hit = t_blocks * bs, .ids = into[first..t_blocks] };
        }
    }
    return .{ .n_hit = 0, .ids = into[0..0] };
}

/// Chain-hashes blocks [0, first) purely (for context only, never looked up), then blocks
/// [first, t_blocks) must each be present and content-verified. On success fills into[first..t_blocks].
fn windowRunHits(pool: *const kv_pool.Pool, g: u32, group: request.GroupSpec, first: u32, t_blocks: u32, tokens: []const u32, into: []u32, mm: Mm) bool {
    assert(first <= t_blocks);
    const bs = request.tokensPerBlock(group);
    var prev: u64 = groupSeed(g);
    var b: u32 = 0;
    while (b < t_blocks) : (b += 1) {
        const block_tokens = tokens[b * bs ..][0..bs];
        const hash = hashBlock(seed(prev, mm, b, bs), block_tokens);
        if (b >= first) {
            const id = kv_pool.lookup(pool, g, hash) orelse return false;
            if (!std.mem.eql(u32, kv_pool.blockTokens(pool, g, id), block_tokens)) return false;
            into[b] = id;
        }
        prev = hash;
    }
    return true;
}

/// Publishes every full block of tokens (the computed prefix) that has no hash yet. Published blocks form
/// a prefix of ids (hits come published, fresh blocks are published here in order), so the scan starts
/// from the last published block and the per-step cost is the number of newly full blocks. A
/// not-cacheable window group never publishes (see match); a cacheable one publishes only its live
/// rows (holes below firstLiveRow are gone, so their chain hash is recomputed purely, never read
/// back from a block that no longer exists -- see insertWindow).
pub fn insert(pool: *kv_pool.Pool, g: u32, group: request.GroupSpec, tokens: []const u32, ids: []const u32, mm: Mm) void {
    assert(group.kind == .per_token);
    switch (group.retention) {
        .all => {},
        .window => |w| {
            if (!w.cacheable) return;
            return insertWindow(pool, g, group, tokens, ids, mm);
        },
    }
    const bs = request.tokensPerBlock(group);
    const n_full: u32 = @intCast(tokens.len / bs);
    assert(n_full <= ids.len);
    var first = n_full;
    while (first > 0 and pool.blocks[kv_pool.pageSlot(pool, g, ids[first - 1])].hash == 0) first -= 1;
    var prev: u64 = if (first == 0) groupSeed(g) else pool.blocks[kv_pool.pageSlot(pool, g, ids[first - 1])].hash;
    for (first..n_full) |b| {
        prev = hashBlock(seed(prev, mm, @intCast(b), bs), tokens[b * bs ..][0..bs]);
        kv_pool.publish(pool, g, ids[b], prev, tokens[b * bs ..][0..bs]);
    }
    for (ids[0..n_full]) |id| assert(pool.blocks[kv_pool.pageSlot(pool, g, id)].hash != 0);
}

/// Publishes only a cacheable window group's live rows (>= firstLiveRow(tokens.len)): holes below
/// that no longer exist and must not be read or published, but the pure chain hash still walks
/// through them (their content is fixed by `tokens`, independent of whether the row survived) so the
/// first live block's `prev` matches what matchWindow recomputes.
fn insertWindow(pool: *kv_pool.Pool, g: u32, group: request.GroupSpec, tokens: []const u32, ids: []const u32, mm: Mm) void {
    const bs = request.tokensPerBlock(group);
    const n_full: u32 = @intCast(tokens.len / bs);
    assert(n_full <= ids.len);
    const first_live = request.firstLiveRow(group, @intCast(tokens.len));
    assert(first_live <= n_full);
    var prev: u64 = groupSeed(g);
    var b: u32 = 0;
    while (b < n_full) : (b += 1) {
        const block_tokens = tokens[b * bs ..][0..bs];
        const hash = hashBlock(seed(prev, mm, b, bs), block_tokens);
        if (b >= first_live and pool.blocks[kv_pool.pageSlot(pool, g, ids[b])].hash == 0) kv_pool.publish(pool, g, ids[b], hash, block_tokens);
        prev = hash;
    }
    for (ids[first_live..n_full]) |id| assert(pool.blocks[kv_pool.pageSlot(pool, g, id)].hash != 0);
}

/// Last block freed first, so the LRU free list reuses the tail of a sequence last.
fn seqCacheable(group: request.GroupSpec) bool {
    return switch (group.retention) {
        .all => false, // a per_seq group with no window keeps one unit: nothing to share
        .window => |w| w.cacheable,
    };
}

/// A per_seq checkpoint at token boundary `t` (a multiple of S) hits for exactly `t` tokens.
/// Scan right to left for the newest cached checkpoint (vLLM MambaManager.find_longest_cache_hit).
/// Only the checkpoint is returned: the caller gets a FRESH live unit on top of it (claimPrefix).
///
/// The key is the same chain hash a stride-S per_token group would build over the same tokens
/// (`seqHash`), so a checkpoint stores only its own S tokens, not the whole prefix -- the chain
/// carries the history, exactly as matchAll's does.
fn matchSeq(pool: *const kv_pool.Pool, g: u32, group: request.GroupSpec, tokens: []const u32, into: []u32, mm: Mm, cap: u32) Match {
    const s = group.stride;
    assert(s > 0);
    // The last token is never matched: its logits are why the request runs.
    const n_ck: u32 = @min(@as(u32, @intCast((tokens.len - 1) / s)), cap / s);
    var prev: u64 = groupSeed(g);
    var best: u32 = 0;
    var best_id: u32 = kv_pool.null_block;
    var i: u32 = 0;
    while (i < n_ck) : (i += 1) {
        const chunk = tokens[i * s ..][0..s];
        const hash = hashBlock(seed(prev, mm, i, s), chunk);
        prev = hash;
        // Keep walking past a chunk that is NOT in the table. The chain hash is PURE -- it is
        // fixed by the tokens, not by whether a unit survived -- so an absent chunk still gives
        // the next one its correct `prev`, exactly as insertWindow walks through slid-out holes.
        // A per_seq group keeps only its newest `n_snapshots` units, so chunk 0's unit is
        // normally already recycled: breaking here made a hit impossible whenever the group kept
        // fewer units than the prompt has chunks. (Until 2026-09-10 this looked like it worked
        // because the hash table was shared across groups and the lookup was silently finding
        // ANOTHER group's page -- see prefix_fixpoint.txt.) This is the right-to-left scan for
        // the newest cached checkpoint the docstring describes.
        const id = kv_pool.lookup(pool, g, hash) orelse continue;
        if (!std.mem.eql(u32, kv_pool.blockTokens(pool, g, id), chunk)) continue;
        best = (i + 1) * s;
        best_id = id;
    }
    if (best == 0) return .{ .n_hit = 0, .ids = into[0..0] };
    into[0] = best_id;
    return .{ .n_hit = best, .ids = into[0..1] };
}

/// Publishes a request's checkpoints: every ring entry not yet hashed gets the chain hash of
/// tokens[0..pos) -- the same key matchSeq recomputes -- and stores its own last S tokens. The
/// ring says which unit holds which prefix length (explicit (id, pos), no positional inference
/// from the table). A prefix-hit checkpoint is already published and is skipped. `tokens` is the
/// computed history; every checkpoint lies within it.
pub fn insertSeq(pool: *kv_pool.Pool, g: u32, group: request.GroupSpec, tokens: []const u32, ring: []const request.Ckpt, mm: Mm) void {
    assert(group.kind == .per_seq);
    if (group.stride == 0 or !seqCacheable(group)) return;
    const s = group.stride;
    for (ring) |ckpt| {
        assert(ckpt.id != kv_pool.null_block);
        assert(ckpt.pos > 0 and ckpt.pos % s == 0 and ckpt.pos <= tokens.len);
        if (pool.blocks[kv_pool.pageSlot(pool, g, ckpt.id)].hash != 0) continue;
        var prev: u64 = groupSeed(g);
        var i: u32 = 0;
        while (i < ckpt.pos / s) : (i += 1) prev = hashBlock(seed(prev, mm, i, s), tokens[i * s ..][0..s]);
        kv_pool.publish(pool, g, ckpt.id, prev, tokens[ckpt.pos - s .. ckpt.pos]);
    }
}

pub fn release(pool: *kv_pool.Pool, g: u32, ids: []u32) void {
    std.mem.reverse(u32, ids);
    kv_pool.free(pool, g, ids);
}

/// Chain seed for block `b`: the previous hash, with mm.hash folded in once the block reaches mm.start.
/// mm.hash == 0 folds as the identity (x ^ 0 == x), so text-only chains are unchanged.
pub fn seed(prev: u64, mm: Mm, b: u32, block_size: u32) u64 {
    assert(block_size > 0);
    const contains_image = (b + 1) * block_size > mm.start;
    const fold: u64 = if (mm.hash != 0 and contains_image) mm.hash else 0;
    return prev ^ fold;
}

/// The chain's group-0 seed. The hash table is shared across groups, so two groups over the SAME
/// tokens must not hash the same: with group-local ids (ruling 2026-09-10) a shared entry would
/// hand one group the other's page id, which now names different memory. Folding g into the root
/// of each group's chain gives every group its own key space. g == 0 keeps the old value, so a
/// single-group model's hashes -- and every trace of one -- are byte-identical.
pub fn groupSeed(g: u32) u64 {
    return if (g == 0) 0 else std.hash.Wyhash.hash(0x9e3779b97f4a7c15, std.mem.asBytes(&g));
}

pub fn hashBlock(prev: u64, tokens: []const u32) u64 {
    const h = std.hash.Wyhash.hash(prev, std.mem.sliceAsBytes(tokens));
    return if (h == 0) 1 else h;
}

// ---- tests -------------------------------------------------------------------------------

const group4 = request.GroupSpec{ .kind = .per_token, .block_size = 4 };

test "match walks the chain and never matches the last token" {
    var pool = try kv_pool.flatInit(std.testing.allocator, 9, 4, 1);
    defer pool.deinit(std.testing.allocator);
    const tokens = [_]u32{ 1, 2, 3, 4, 5, 6, 7, 8, 9, 10 };
    var ids: [3]u32 = undefined;
    kv_pool.allocate(&pool, 0, &ids);
    insert(&pool, 0, group4, tokens[0..10], &ids, text_only); // publishes blocks 0 and 1; block 2 is partial

    var out: [3]u32 = undefined;
    try std.testing.expectEqual(8, match(&pool, 0, group4, &tokens, &out, text_only).n_hit);
    try std.testing.expectEqual(8, match(&pool, 0, group4, tokens[0..9], &out, text_only).n_hit);
    try std.testing.expectEqual(4, match(&pool, 0, group4, tokens[0..8], &out, text_only).n_hit); // token 8 must be computed
    try std.testing.expectEqualSlices(u32, ids[0..1], match(&pool, 0, group4, tokens[0..8], &out, text_only).ids);
    try std.testing.expectEqual(0, match(&pool, 0, group4, tokens[0..4], &out, text_only).n_hit);
    const diverged = [_]u32{ 1, 2, 3, 4, 5, 0, 7, 8, 9 };
    try std.testing.expectEqual(4, match(&pool, 0, group4, &diverged, &out, text_only).n_hit);
    const other = [_]u32{ 0, 2, 3, 4, 5, 6, 7, 8, 9 };
    try std.testing.expectEqual(0, match(&pool, 0, group4, &other, &out, text_only).n_hit); // chain: block 1 depends on block 0
}

test "collision guard rejects a block whose hash matches but whose tokens differ" {
    const tokens = [_]u32{ 1, 2, 3, 4, 5 };
    const impostors = [_][]const u32{ &.{ 1, 2, 3 }, &.{ 1, 2, 3, 9 }, &.{ 9, 2, 3, 4 } };
    for (impostors) |impostor| {
        var pool = try kv_pool.flatInit(std.testing.allocator, 4, 4, 1);
        defer pool.deinit(std.testing.allocator);
        var ids: [1]u32 = undefined;
        kv_pool.allocate(&pool, 0, &ids);
        // Published under the first full block's chain hash but with other content: a colliding publisher.
        kv_pool.publish(&pool, 0, ids[0], hashBlock(0, tokens[0..4]), impostor);
        var out: [1]u32 = undefined;
        try std.testing.expectEqual(0, match(&pool, 0, group4, &tokens, &out, text_only).n_hit);
    }
}

test "per_seq groups never hit; a cacheable window group hits by content, not by group identity" {
    var pool = try kv_pool.flatInit(std.testing.allocator, 4, 4, 1);
    defer pool.deinit(std.testing.allocator);
    const tokens = [_]u32{ 1, 2, 3, 4, 5, 6, 7, 8, 9 };
    var ids: [2]u32 = undefined;
    kv_pool.allocate(&pool, 0, &ids);
    insert(&pool, 0, group4, &tokens, &ids, text_only);
    var out: [2]u32 = undefined;
    // Same block_size/stride as group4, so the chain hashes coincide: a cacheable window group
    // legitimately hits blocks an `all` group published (matchWindow, item 1).
    const windowed = request.GroupSpec{ .kind = .per_token, .block_size = 4, .retention = .{ .window = .{ .w = 4, .cacheable = true } } };
    try std.testing.expectEqual(8, match(&pool, 0, windowed, &tokens, &out, text_only).n_hit);
    const per_seq = request.GroupSpec{ .kind = .per_seq, .block_size = 0, .stride = 0 };
    try std.testing.expectEqual(0, match(&pool, 0, per_seq, &tokens, &out, text_only).n_hit);
}

test "stride group: a block hashes stride * block_size tokens; hits are multiples of that grain" {
    // 2 units per block, stride 3: one block = 6 tokens. 13 tokens: blocks 0 and 1 full, block 2 partial.
    const g = request.GroupSpec{ .kind = .per_token, .block_size = 2, .stride = 3 };
    var pool = try kv_pool.flatInit(std.testing.allocator, 9, 6, 1);
    defer pool.deinit(std.testing.allocator);
    const tokens = [_]u32{ 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13 };
    var ids: [3]u32 = undefined;
    kv_pool.allocate(&pool, 0, &ids);
    insert(&pool, 0, g, &tokens, &ids, text_only);
    try std.testing.expectEqualSlices(u32, tokens[6..12], kv_pool.blockTokens(&pool, 0, ids[1]));
    try std.testing.expectEqual(0, pool.blocks[ids[2]].hash);
    var out: [3]u32 = undefined;
    try std.testing.expectEqual(12, match(&pool, 0, g, &tokens, &out, text_only).n_hit);
    try std.testing.expectEqual(6, match(&pool, 0, g, tokens[0..12], &out, text_only).n_hit); // token 12 must be computed
    try std.testing.expectEqual(6, match(&pool, 0, g, tokens[0..9], &out, text_only).n_hit); // 9 is not a grain multiple
    try std.testing.expectEqual(0, match(&pool, 0, g, tokens[0..5], &out, text_only).n_hit);
    // A stride-1 group over the same tokens hashes different blocks: the grain is part of the chain.
    const g1 = request.GroupSpec{ .kind = .per_token, .block_size = 6 };
    try std.testing.expectEqual(12, match(&pool, 0, g1, &tokens, &out, text_only).n_hit); // same 6-token grain, same hashes
}

test "window group that is not cacheable never hits and never publishes" {
    var pool = try kv_pool.flatInit(std.testing.allocator, 4, 4, 1);
    defer pool.deinit(std.testing.allocator);
    const tokens = [_]u32{ 1, 2, 3, 4, 5, 6, 7, 8, 9 };
    var ids: [2]u32 = undefined;
    kv_pool.allocate(&pool, 0, &ids);
    const ring = request.GroupSpec{ .kind = .per_token, .block_size = 4, .retention = .{ .window = .{ .w = 4, .cacheable = false } } };
    insert(&pool, 0, ring, &tokens, &ids, text_only);
    for (ids) |id| try std.testing.expectEqual(0, pool.blocks[id].hash);
    var out: [2]u32 = undefined;
    try std.testing.expectEqual(0, match(&pool, 0, ring, &tokens, &out, text_only).n_hit);
}

test "insert after a hit publishes only the new blocks" {
    var pool = try kv_pool.flatInit(std.testing.allocator, 9, 4, 1);
    defer pool.deinit(std.testing.allocator);
    const tokens = [_]u32{ 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12 };
    var a: [2]u32 = undefined;
    kv_pool.allocate(&pool, 0, &a);
    insert(&pool, 0, group4, tokens[0..8], &a, text_only);
    release(&pool, 0, &a);

    var b: [3]u32 = undefined;
    const m = match(&pool, 0, group4, &tokens, &b, text_only);
    try std.testing.expectEqual(8, m.n_hit);
    for (m.ids) |id| kv_pool.touch(&pool, 0, id);
    kv_pool.allocate(&pool, 0, b[2..3]);
    insert(&pool, 0, group4, &tokens, &b, text_only);
    var out: [3]u32 = undefined;
    try std.testing.expectEqual(12, match(&pool, 0, group4, &(tokens ++ [_]u32{13}), &out, text_only).n_hit);
    try std.testing.expectEqualSlices(u32, &b, out[0..3]);
}

test "mm fold: same placeholders differ by image; text blocks before the image still shared; 0 is identity" {
    var pool = try kv_pool.flatInit(std.testing.allocator, 9, 4, 1);
    defer pool.deinit(std.testing.allocator);
    const tokens = [_]u32{ 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13 }; // placeholders from position 8 on
    const img_a = Mm{ .hash = 0xA11CE, .start = 8 };
    const img_b = Mm{ .hash = 0xB0B, .start = 8 };
    var ids: [3]u32 = undefined;
    kv_pool.allocate(&pool, 0, &ids);
    insert(&pool, 0, group4, &tokens, &ids, img_a);
    var out: [3]u32 = undefined;
    try std.testing.expectEqual(12, match(&pool, 0, group4, &tokens, &out, img_a).n_hit); // same image: full hit
    try std.testing.expectEqual(8, match(&pool, 0, group4, &tokens, &out, img_b).n_hit); // other image: text blocks only
    try std.testing.expectEqual(8, match(&pool, 0, group4, &tokens, &out, text_only).n_hit); // text-only shares the text prefix
    // Blocks 0 and 1 hold no placeholder: their hashes equal the text-only chain (identity fold).
    try std.testing.expectEqual(hashBlock(0, tokens[0..4]), pool.blocks[ids[0]].hash);
    try std.testing.expectEqual(seed(7, text_only, 0, 4), 7);
    try std.testing.expect(pool.blocks[ids[2]].hash != hashBlock(pool.blocks[ids[1]].hash, tokens[8..12]));
}

test "cacheable window scan: right-to-left run of ceil((W-1)/block) blocks ending at t; older evicted blocks don't matter" {
    // W=8, block_size=4: window_blocks = ceil(7/4) = 2. Publish incrementally at n_computed=12,20
    // (as the scheduler does after each chunk), so every block up to firstLiveRow(n_computed) at
    // the time of its own publish is live -- exactly the real insert/match contract. Match against
    // a 20-token sequence: the last token is never claimed (matchAll's rule, shared here), so the
    // max full boundary is block 4 (t=16, tokens 16-19 form the never-matched partial tail).
    var pool = try kv_pool.flatInit(std.testing.allocator, 9, 4, 1);
    defer pool.deinit(std.testing.allocator);
    const window8 = request.GroupSpec{ .kind = .per_token, .block_size = 4, .retention = .{ .window = .{ .w = 8, .cacheable = true } } };
    const tokens = [_]u32{ 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20 };
    var ids: [5]u32 = undefined;
    kv_pool.allocate(&pool, 0, &ids);
    insert(&pool, 0, window8, tokens[0..12], ids[0..3], text_only); // firstLiveRow(12)=1: blocks 0,1,2 all still live, all published
    insert(&pool, 0, window8, tokens[0..16], ids[0..4], text_only); // firstLiveRow(16)=2: blocks 2,3 published; 0,1 already were
    insert(&pool, 0, window8, &tokens, &ids, text_only); // firstLiveRow(20)=3: block 4 published (partial: only 4 tokens, tokens.len=20 makes it full)

    var out: [5]u32 = undefined;
    // Everything published and live: the run ending at the max full boundary (block 4, t=16) hits.
    try std.testing.expectEqual(16, match(&pool, 0, window8, &tokens, &out, text_only).n_hit);

    // Evict block 3 (tokens 12-15) directly from the pool, simulating it having slid out and been
    // reused. The run ending at t=16 needs blocks {2,3}; block 3 is gone, so t=16 misses. The scan
    // must step left to t=12 (blocks {1,2}), which is still fully present, and hit there.
    pool.blocks[ids[3]].hash = 0;
    var out2: [5]u32 = undefined;
    const m2 = match(&pool, 0, window8, &tokens, &out2, text_only);
    try std.testing.expectEqual(12, m2.n_hit);
    // The run only covers live rows [first, t_blocks) = [1, 3): row 0 (slid out at this boundary,
    // per firstLiveRow) is never part of Match.ids.
    try std.testing.expectEqualSlices(u32, &.{ ids[1], ids[2] }, m2.ids);
}

test "cacheable window scan finds nothing once every candidate run is broken" {
    var pool = try kv_pool.flatInit(std.testing.allocator, 9, 4, 1);
    defer pool.deinit(std.testing.allocator);
    const window8 = request.GroupSpec{ .kind = .per_token, .block_size = 4, .retention = .{ .window = .{ .w = 8, .cacheable = true } } };
    const tokens = [_]u32{ 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12 };
    var ids: [3]u32 = undefined;
    kv_pool.allocate(&pool, 0, &ids);
    insert(&pool, 0, window8, &tokens, &ids, text_only);
    // Break the middle block: no 2-block run anywhere can be complete.
    pool.blocks[ids[1]].hash = 0;
    var out: [3]u32 = undefined;
    try std.testing.expectEqual(0, match(&pool, 0, window8, &tokens, &out, text_only).n_hit);
}

test "a window group's hit is not monotone in the cap: why the cross-group loop is a fixpoint" {
    // W = 8, block 4 -> a resumable boundary needs the ceil(7/4) = 2 blocks ending at it.
    // Publish blocks 0,1,3,4 and leave block 2 missing (evicted while a request ran).
    //   asked at the full length: t = 5 needs blocks {3,4} -> hit at 20 tokens
    //   asked capped at 12:       t = 3 needs {1,2} -> miss; t = 2 needs {0,1} -> hit at 8
    // So capping 20 -> 12 moves this group's answer to 8, BELOW the cap. A single pass of
    // `min` over independently-scanned groups would report 12 -- a boundary this group cannot
    // resume from. That is the whole reason claimPrefix iterates to a fixed point.
    // Exactly 5 usable pages, so freeing one makes it the LRU head and the next allocate
    // takes it back -- a real eviction, not a fresh page from a roomy pool.
    var pool = try kv_pool.flatInit(std.testing.allocator, 6, 4, 1);
    defer pool.deinit(std.testing.allocator);
    const w8 = request.GroupSpec{
        .kind = .per_token,
        .block_size = 4,
        .retention = .{ .window = .{ .w = 8, .cacheable = true } },
    };
    var tokens: [24]u32 = undefined;
    for (&tokens, 0..) |*tok, i| tok.* = @intCast(100 + i);

    // Publish all five blocks of a 20-token prefix by hand. (`insertWindow` deliberately
    // publishes only a request's LIVE rows, so it cannot produce a fully-populated history --
    // but a history like this one accumulates across several requests' live windows.)
    var ids: [5]u32 = undefined;
    kv_pool.allocate(&pool, 0, &ids);
    {
        var prev: u64 = groupSeed(0);
        for (ids, 0..) |id, b| {
            const chunk = tokens[b * 4 ..][0..4];
            const hash = hashBlock(seed(prev, text_only, @intCast(b), 4), chunk);
            kv_pool.publish(&pool, 0, id, hash, chunk);
            prev = hash;
        }
    }
    // Drop block 2's hash: free it and pop it straight back off the LRU head. Blocks 0,1,3,4
    // stay referenced, so the head is block 2 and nothing else moves.
    kv_pool.free(&pool, 0, ids[2..3]);
    var stolen: [1]u32 = undefined;
    kv_pool.allocate(&pool, 0, &stolen);
    try std.testing.expectEqual(ids[2], stolen[0]);

    var out: [8]u32 = undefined;
    try std.testing.expectEqual(20, matchUpTo(&pool, 0, w8, &tokens, &out, text_only, 24).n_hit);
    try std.testing.expectEqual(8, matchUpTo(&pool, 0, w8, &tokens, &out, text_only, 12).n_hit);
    // The fixpoint's own step: capped at its previous answer, it is stable.
    try std.testing.expectEqual(8, matchUpTo(&pool, 0, w8, &tokens, &out, text_only, 8).n_hit);
}
