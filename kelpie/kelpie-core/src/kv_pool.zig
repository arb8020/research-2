//! One slab pool for every cache group (Jenga arXiv:2503.18292, TokenSpeed `block_pool.h`,
//! docs/kv-groups.md "The slab model"). Cache memory is `num_slabs` slabs of `slab_bytes`; a
//! cache group `g` carves pages of `bytes_per_page[g]` out of a slab it owns, so a slab holds
//! `pages_per_slab[g]` pages of that group. A slab is tiled EXACTLY:
//! `pages_per_slab[g] * bytes_per_page[g] == slab_bytes`, no slack (ruling 2026-09-10,
//! docs/slab-lcm-ladder.md) -- Python rounds slab_bytes up to a multiple of lcm(k_g) * 16 and
//! pads each page to `slab_bytes / k_g`, so the old slack becomes per-page padding.
//!
//! A slab belongs to at most one group at a time. The free list is a list of *slabs* (LRU: head is
//! the oldest, tail the most recently released). `allocate(g, into)` carves pages from group g's
//! partial slab, taking a fresh slab off the LRU head when it runs out; taking a slab off the head
//! evicts it, dropping the prefix-hash of every page in it (mass hash drop, not page-LRU +
//! compaction). `free(g, ids)` returns pages to their slab; a slab whose last page is returned goes
//! back on the LRU tail, keeping the hashes of the pages in it -- so a freed-but-not-yet-reused slab
//! is still hittable, exactly as a freed block was before.
//!
//! Page ids are GROUP-LOCAL (Jenga invariant (i), ruling 2026-09-10): group g numbers its own
//! pages `slab * pages_per_slab[g] + index + 1`, so an id means nothing without the group that
//! issued it. Block tables are per group already, so every caller has g in hand. Id 0 is the null
//! page of EVERY group (docs/kv-groups.md): never handed out, never carved; models point pad slots
//! and holes at it. Because ids collide across groups, the shared per-page arrays (`blocks`,
//! `tokens`, and the hash table) are indexed by `base[g] + id`, where `base[g]` is group g's
//! stretch of the id space; `null_block` maps to slot 0 for every group.
//! With equal page sizes (one group, or groups of equal bytes) every `pages_per_slab` is 1, the
//! packing is `slab + 1`, and the pool degenerates exactly to the pre-slab block pool.
//!
//! Pages are refcounted and content-addressed: publish gives a page a hash (prefix.zig computes it),
//! lookup finds a page by hash, touch takes a reference, free drops one. The hash table is open
//! addressing over page ids, sized 2 * n_pages at init; never allocates after. A published page also
//! stores its token ids ([n_pages][block_size], static) so a hash hit is verified against the actual
//! content (vLLM/nano-vllm style): a hash collision can never serve the wrong KV.

const std = @import("std");
const assert = std.debug.assert;

pub const none = std.math.maxInt(u32);
pub const null_block: u32 = 0;

/// What one cache group costs per page. A slab is tiled exactly:
/// `pages_per_slab * bytes_per_page == slab_bytes` (ruling 2026-09-10, docs/slab-lcm-ladder.md).
/// Python computes both and the pool checks the identity.
pub const PoolGroup = struct { bytes_per_page: u32, pages_per_slab: u32 };

/// hash 0 = unpublished. n_tokens = tokens stored when published (the prefix matcher's partial-block guard).
pub const Block = struct { ref_count: u32, hash: u64, n_tokens: u32 };

/// A slab is either free (on the LRU list, `owner == none` or a stale owner with n_used == 0) or
/// owned by one group. `n_used` counts referenced pages; `n_carved` counts pages handed out of it
/// since it was taken (the carve cursor). A slab is on the free list iff `n_used == 0`.
pub const Slab = struct {
    owner: u32,
    n_used: u32,
    n_carved: u32,
    prev: u32,
    next: u32,
    /// Next partial slab of the same owner; `none` at the end of the owner's partial list.
    next_partial: u32,
    on_free_list: bool,
};

pub const Pool = struct {
    blocks: []Block,
    slabs: []Slab,
    /// Per group: the head of its list of partially-carved slabs, or `none`.
    partial: []u32,
    /// Per group: pages still carvable from its partial list. Cached because admission asks for
    /// it once per group per attempt; `nPartial` walks the list only in the debug assert.
    n_partial: []u32,
    groups: []PoolGroup,
    /// Start of each group's stretch of the shared per-page arrays; ids are group-local, so
    /// page `id` of group `g` is slot `base[g] + id`. base[0] == 1 (slot 0 is the null page,
    /// shared by every group).
    base: []u32,
    slab_bytes: u32,
    /// LRU list of free slabs: head is evicted first, a released slab goes on the tail.
    head: u32,
    tail: u32,
    n_free_slabs: u32,
    /// Open-addressing table of page ids keyed by blocks[id].hash; `none` = empty slot.
    hash_to_block: []u32,
    /// Token ids of published pages, block_size per page; blocks[id].n_tokens of them are valid.
    tokens: []u32,
    block_size: u32,

    /// num_slabs slabs of slab_bytes; groups[g] says what one page of group g costs.
    /// block_size: the most tokens any group stores per page (bounds the stored token ids).
    pub fn init(
        allocator: std.mem.Allocator,
        num_slabs: u32,
        slab_bytes: u32,
        groups: []const PoolGroup,
        block_size: u32,
    ) !Pool {
        assert(num_slabs >= 1);
        assert(slab_bytes > 0);
        assert(groups.len > 0);
        assert(block_size > 0);
        // Ids are group-local, so each group gets its own stretch of the shared per-page arrays,
        // starting after the one null-page slot every group shares.
        const base = try allocator.alloc(u32, groups.len);
        errdefer allocator.free(base);
        var n_pages: u64 = 1; // slot 0 is the null page, shared by every group
        for (groups, 0..) |group, g| {
            assert(group.bytes_per_page > 0);
            assert(group.pages_per_slab > 0);
            // Exact tiling: no slack (ruling 2026-09-10, docs/slab-lcm-ladder.md).
            assert(group.pages_per_slab * group.bytes_per_page == slab_bytes);
            // base[g] + id for id in 1..=num_slabs*pps, so the stretch starts one below its first id.
            base[g] = @intCast(n_pages - 1);
            n_pages += @as(u64, num_slabs) * group.pages_per_slab;
            assert(n_pages < none);
        }

        const blocks = try allocator.alloc(Block, @intCast(n_pages));
        errdefer allocator.free(blocks);
        const slabs = try allocator.alloc(Slab, num_slabs);
        errdefer allocator.free(slabs);
        const partial = try allocator.alloc(u32, groups.len);
        errdefer allocator.free(partial);
        const n_partial = try allocator.alloc(u32, groups.len);
        errdefer allocator.free(n_partial);
        const groups_copy = try allocator.alloc(PoolGroup, groups.len);
        errdefer allocator.free(groups_copy);
        const hash_to_block = try allocator.alloc(u32, 2 * @as(usize, @intCast(n_pages)));
        errdefer allocator.free(hash_to_block);
        const tokens = try allocator.alloc(u32, @as(usize, @intCast(n_pages)) * block_size);
        errdefer allocator.free(tokens);

        @memcpy(groups_copy, groups);
        @memset(partial, none);
        @memset(n_partial, 0);
        @memset(hash_to_block, none);
        for (blocks) |*block| block.* = .{ .ref_count = 0, .hash = 0, .n_tokens = 0 };
        // The null page holds a permanent reference so it can never be carved or freed.
        blocks[null_block].ref_count = 1;
        for (slabs, 0..) |*slab, i| {
            const id: u32 = @intCast(i);
            slab.* = .{
                .owner = none,
                .n_used = 0,
                .n_carved = 0,
                .prev = if (id == 0) none else id - 1,
                .next = if (id + 1 == num_slabs) none else id + 1,
                .next_partial = none,
                .on_free_list = true,
            };
        }
        return .{
            .blocks = blocks,
            .slabs = slabs,
            .partial = partial,
            .n_partial = n_partial,
            .groups = groups_copy,
            .base = base,
            .slab_bytes = slab_bytes,
            .head = 0,
            .tail = num_slabs - 1,
            .n_free_slabs = num_slabs,
            .hash_to_block = hash_to_block,
            .tokens = tokens,
            .block_size = block_size,
        };
    }

    pub fn deinit(pool: *Pool, allocator: std.mem.Allocator) void {
        allocator.free(pool.tokens);
        allocator.free(pool.hash_to_block);
        allocator.free(pool.base);
        allocator.free(pool.groups);
        allocator.free(pool.n_partial);
        allocator.free(pool.partial);
        allocator.free(pool.slabs);
        allocator.free(pool.blocks);
        pool.* = undefined;
    }
};

// ---- page id packing ---------------------------------------------------------------------

/// Group-local: id `slab * pages_per_slab[g] + index + 1` (ruling 2026-09-10). An id is
/// meaningless without the group that issued it; every caller has g in hand because block
/// tables are per group.
pub fn pageId(pool: *const Pool, g: u32, slab: u32, index: u32) u32 {
    assert(g < pool.groups.len);
    assert(slab < pool.slabs.len);
    assert(index < pool.groups[g].pages_per_slab);
    return slab * pool.groups[g].pages_per_slab + index + 1;
}

pub fn slabOf(pool: *const Pool, g: u32, id: u32) u32 {
    assert(g < pool.groups.len);
    assert(id != null_block);
    return (id - 1) / pool.groups[g].pages_per_slab;
}

pub fn indexIn(pool: *const Pool, g: u32, id: u32) u32 {
    assert(g < pool.groups.len);
    assert(id != null_block);
    return (id - 1) % pool.groups[g].pages_per_slab;
}

/// Slot of group g's page `id` in the shared per-page arrays (`blocks`, `tokens`, hash table).
/// The null page is slot 0 for every group.
pub fn pageSlot(pool: *const Pool, g: u32, id: u32) u32 {
    assert(g < pool.groups.len);
    if (id == null_block) return null_block;
    assert(id <= @as(u32, @intCast(pool.slabs.len)) * pool.groups[g].pages_per_slab);
    return pool.base[g] + id;
}

// ---- capacity ----------------------------------------------------------------------------

/// Free slabs: what admission budgets against (`slabsFor`).
pub fn nFreeSlabs(pool: *const Pool) u32 {
    if (pool.n_free_slabs == 0) assert(pool.head == none);
    return pool.n_free_slabs;
}

/// Pages of group g still carvable without taking a fresh slab: what its partial list holds.
/// O(1); `walkPartial` is the same number the slow way, asserted in the invariant checker.
pub fn nPartial(pool: *const Pool, g: u32) u32 {
    return pool.n_partial[g];
}

fn walkPartial(pool: *const Pool, g: u32) u32 {
    var total: u32 = 0;
    var slab = pool.partial[g];
    var n_seen: usize = 0;
    while (slab != none) : (slab = pool.slabs[slab].next_partial) {
        assert(n_seen <= pool.slabs.len);
        n_seen += 1;
        total += pool.groups[g].pages_per_slab - pool.slabs[slab].n_carved;
    }
    return total;
}

/// Slabs `allocate(g, n)` would have to take off the free list.
pub fn slabsFor(pool: *const Pool, g: u32, n_pages: u32) u32 {
    const have = nPartial(pool, g);
    if (n_pages <= have) return 0;
    const pps = pool.groups[g].pages_per_slab;
    return (n_pages - have + pps - 1) / pps;
}

/// Total free capacity in pages of group g: its partials plus every free slab carved for g.
/// The old `nFree`: with pages_per_slab == 1 for every group this is exactly the free page count.
pub fn nFree(pool: *const Pool, g: u32) u32 {
    return nPartial(pool, g) + pool.n_free_slabs * pool.groups[g].pages_per_slab;
}

// ---- allocate / free ---------------------------------------------------------------------

/// Fresh pages of group g, carved from its partial slabs, taking (and evicting) LRU slabs as needed.
pub fn allocate(pool: *Pool, g: u32, into: []u32) void {
    assert(g < pool.groups.len);
    assert(into.len <= nFree(pool, g));
    const pps = pool.groups[g].pages_per_slab;
    for (into) |*slot| {
        var slab = pool.partial[g];
        if (slab == none) slab = takeSlab(pool, g);
        const s = &pool.slabs[slab];
        assert(s.owner == g);
        assert(s.n_carved < pps);
        const id = pageId(pool, g, slab, s.n_carved);
        s.n_carved += 1;
        s.n_used += 1;
        assert(pool.n_partial[g] > 0);
        pool.n_partial[g] -= 1;
        const block = &pool.blocks[pageSlot(pool, g, id)];
        assert(block.ref_count == 0);
        if (block.hash != 0) tableRemove(pool, pageSlot(pool, g, id));
        block.hash = 0;
        block.n_tokens = 0;
        block.ref_count = 1;
        if (s.n_carved == pps) {
            // Fully carved: off the partial list. Its remaining room is 0, so n_partial is unchanged.
            pool.partial[g] = s.next_partial;
            s.next_partial = none;
        }
        slot.* = id;
    }
}

/// Drops one reference per id; a slab whose last referenced page goes lands on the free tail,
/// keeping its pages' hashes so they stay hittable until it is taken again.
pub fn free(pool: *Pool, g: u32, ids: []const u32) void {
    assert(g < pool.groups.len);
    for (ids) |id| {
        assert(id != null_block);
        const block = &pool.blocks[pageSlot(pool, g, id)];
        assert(block.ref_count > 0);
        block.ref_count -= 1;
        if (block.ref_count != 0) continue;
        const slab = slabOf(pool, g, id);
        const s = &pool.slabs[slab];
        assert(s.owner == g);
        assert(s.n_used > 0);
        s.n_used -= 1;
        if (s.n_used == 0) releaseSlab(pool, g, slab);
    }
}

/// Takes a reference on an existing page (a prefix hit). Resurrects the page's slab off the free
/// list if that slab had been fully released.
pub fn touch(pool: *Pool, g: u32, id: u32) void {
    assert(id != null_block);
    const block = &pool.blocks[pageSlot(pool, g, id)];
    const s = &pool.slabs[slabOf(pool, g, id)];
    if (block.ref_count == 0) {
        if (s.n_used == 0) resurrectSlab(pool, slabOf(pool, g, id));
        s.n_used += 1;
    }
    block.ref_count += 1;
    assert(s.n_used > 0 and !s.on_free_list);
}

/// The page of group g carrying `hash`, as a group-local id, or null. The hash table is shared
/// across groups (it stores slots), so a hit in another group's stretch is not a hit here.
pub fn lookup(pool: *const Pool, g: u32, hash: u64) ?u32 {
    assert(hash != 0);
    const found = tableFind(pool, hash) orelse return null;
    const s = pool.hash_to_block[found];
    assert(pool.blocks[s].hash == hash);
    const lo = pool.base[g];
    const hi = lo + @as(u32, @intCast(pool.slabs.len)) * pool.groups[g].pages_per_slab;
    if (s <= lo or s > hi) return null; // another group's page
    return s - lo;
}

/// Gives a referenced, unpublished page its content hash and the tokens behind it. If another page
/// already carries the hash (two requests computed the same block in one step) the table keeps the
/// first; this page keeps the hash so chains through it still work, but it is not findable.
pub fn publish(pool: *Pool, g: u32, id: u32, hash: u64, tokens: []const u32) void {
    assert(hash != 0);
    assert(id != null_block);
    assert(tokens.len > 0 and tokens.len <= pool.block_size);
    const s = pageSlot(pool, g, id);
    const block = &pool.blocks[s];
    assert(block.ref_count > 0);
    assert(block.hash == 0);
    block.hash = hash;
    block.n_tokens = @intCast(tokens.len);
    @memcpy(pool.tokens[s * pool.block_size ..][0..tokens.len], tokens);
    if (tableFind(pool, hash) == null) tableInsert(pool, s);
    // The hash is findable, but not necessarily as THIS page: a duplicate publisher (two requests
    // computing the same block in one step, or another group whose content hashes the same) keeps
    // the entry the table already had. So assert the table has the hash, not that `lookup` in this
    // group returns `id` -- with group-local ids the standing entry may be another group's.
    assert(tableFind(pool, hash) != null);
    assert(std.mem.eql(u32, blockTokens(pool, g, id), tokens));
}

/// The tokens a published page holds (empty for an unpublished one).
pub fn blockTokens(pool: *const Pool, g: u32, id: u32) []const u32 {
    const s = pageSlot(pool, g, id);
    const block = pool.blocks[s];
    assert(block.n_tokens <= pool.block_size);
    if (block.hash == 0) assert(block.n_tokens == 0);
    return pool.tokens[s * pool.block_size ..][0..block.n_tokens];
}

// ---- slab list ---------------------------------------------------------------------------

/// Pops the LRU head, evicts it (mass hash drop of every page in it) and binds it to group g.
fn takeSlab(pool: *Pool, g: u32) u32 {
    const slab = pool.head;
    assert(slab != none);
    const s = &pool.slabs[slab];
    assert(s.n_used == 0);
    unlinkFree(pool, slab);
    // Mass hash drop: every page of the slab's previous owner is gone.
    if (s.owner != none) {
        const old_pps = pool.groups[s.owner].pages_per_slab;
        var i: u32 = 0;
        while (i < old_pps) : (i += 1) {
            const sl = pageSlot(pool, s.owner, pageId(pool, s.owner, slab, i));
            assert(pool.blocks[sl].ref_count == 0);
            if (pool.blocks[sl].hash != 0) tableRemove(pool, sl);
            pool.blocks[sl].hash = 0;
            pool.blocks[sl].n_tokens = 0;
        }
    }
    s.owner = g;
    s.n_carved = 0;
    pushPartial(pool, g, slab);
    assert(pool.groups[g].pages_per_slab > 0);
    return slab;
}

/// Last page of a slab freed: off the owner's partial list, onto the free LRU tail with its
/// hashes intact (still hittable until it is taken again).
fn releaseSlab(pool: *Pool, g: u32, slab: u32) void {
    const s = &pool.slabs[slab];
    assert(s.n_used == 0);
    assert(!s.on_free_list);
    unlinkPartial(pool, g, slab);
    pushTail(pool, slab);
}

/// A hit on a page of a fully-released slab: back off the free list, onto the owner's partial list
/// (its carve cursor is preserved, so already-carved pages are not handed out twice).
/// It goes on the TAIL, so `allocate` keeps carving the slab it was already carving and fills the
/// most-occupied slab first (TokenSpeed `planLocations`) instead of scattering across slabs.
fn resurrectSlab(pool: *Pool, slab: u32) void {
    const s = &pool.slabs[slab];
    assert(s.on_free_list);
    assert(s.owner != none);
    unlinkFree(pool, slab);
    if (s.n_carved < pool.groups[s.owner].pages_per_slab) pushPartialTail(pool, s.owner, slab);
}

/// A freshly taken slab is carved from first: it goes on the head.
fn pushPartial(pool: *Pool, g: u32, slab: u32) void {
    const s = &pool.slabs[slab];
    assert(s.next_partial == none);
    s.next_partial = pool.partial[g];
    pool.partial[g] = slab;
    pool.n_partial[g] += pool.groups[g].pages_per_slab - s.n_carved;
}

fn pushPartialTail(pool: *Pool, g: u32, slab: u32) void {
    const s = &pool.slabs[slab];
    assert(s.next_partial == none);
    pool.n_partial[g] += pool.groups[g].pages_per_slab - s.n_carved;
    if (pool.partial[g] == none) {
        pool.partial[g] = slab;
        return;
    }
    var cur = pool.partial[g];
    var n_seen: usize = 0;
    while (pool.slabs[cur].next_partial != none) : (cur = pool.slabs[cur].next_partial) {
        assert(n_seen <= pool.slabs.len);
        n_seen += 1;
    }
    pool.slabs[cur].next_partial = slab;
}

fn unlinkPartial(pool: *Pool, g: u32, slab: u32) void {
    const room = pool.groups[g].pages_per_slab - pool.slabs[slab].n_carved;
    var cur = pool.partial[g];
    if (cur == slab) {
        pool.partial[g] = pool.slabs[slab].next_partial;
        pool.slabs[slab].next_partial = none;
        assert(pool.n_partial[g] >= room);
        pool.n_partial[g] -= room;
        return;
    }
    var n_seen: u32 = 0;
    while (cur != none) : (cur = pool.slabs[cur].next_partial) {
        assert(n_seen <= pool.slabs.len);
        n_seen += 1;
        if (pool.slabs[cur].next_partial != slab) continue;
        pool.slabs[cur].next_partial = pool.slabs[slab].next_partial;
        pool.slabs[slab].next_partial = none;
        assert(pool.n_partial[g] >= room);
        pool.n_partial[g] -= room;
        return;
    }
    // Not on the partial list: the slab was fully carved (allocate popped it off).
    assert(pool.slabs[slab].next_partial == none);
}

fn unlinkFree(pool: *Pool, slab: u32) void {
    const s = &pool.slabs[slab];
    assert(s.on_free_list);
    assert(pool.n_free_slabs > 0);
    if (s.prev == none) pool.head = s.next else pool.slabs[s.prev].next = s.next;
    if (s.next == none) pool.tail = s.prev else pool.slabs[s.next].prev = s.prev;
    s.prev = none;
    s.next = none;
    s.on_free_list = false;
    pool.n_free_slabs -= 1;
    assert((pool.head == none) == (pool.n_free_slabs == 0));
}

fn pushTail(pool: *Pool, slab: u32) void {
    const s = &pool.slabs[slab];
    assert(!s.on_free_list);
    assert(s.n_used == 0);
    s.prev = pool.tail;
    s.next = none;
    if (pool.tail == none) pool.head = slab else pool.slabs[pool.tail].next = slab;
    pool.tail = slab;
    s.on_free_list = true;
    pool.n_free_slabs += 1;
}

// ---- hash table --------------------------------------------------------------------------

fn tableHome(pool: *const Pool, hash: u64) u32 {
    return @intCast(hash % pool.hash_to_block.len);
}

fn tableFind(pool: *const Pool, hash: u64) ?u32 {
    assert(hash != 0);
    const cap: u32 = @intCast(pool.hash_to_block.len);
    var slot = tableHome(pool, hash);
    var n_probed: u32 = 0;
    while (pool.hash_to_block[slot] != none) : (slot = (slot + 1) % cap) {
        assert(n_probed < cap);
        n_probed += 1;
        if (pool.blocks[pool.hash_to_block[slot]].hash == hash) return slot;
    }
    return null;
}

/// `s` is a SLOT (base[g] + id), not a group-local id: the table is shared across groups.
fn tableInsert(pool: *Pool, s: u32) void {
    const hash = pool.blocks[s].hash;
    assert(hash != 0);
    assert(tableFind(pool, hash) == null);
    const cap: u32 = @intCast(pool.hash_to_block.len);
    var at = tableHome(pool, hash);
    while (pool.hash_to_block[at] != none) at = (at + 1) % cap;
    pool.hash_to_block[at] = s;
    assert(pool.hash_to_block[tableFind(pool, hash).?] == s);
}

/// Removes id if the table points at it (a duplicate publisher is not in the table). Linear-probing
/// deletion by backward shift: entries after the hole move up unless their home lies past the hole.
fn tableRemove(pool: *Pool, s: u32) void {
    const hash = pool.blocks[s].hash;
    assert(hash != 0);
    const found = tableFind(pool, hash) orelse return;
    if (pool.hash_to_block[found] != s) return;
    const cap: u32 = @intCast(pool.hash_to_block.len);
    var hole = found;
    pool.hash_to_block[hole] = none;
    var j = hole;
    while (true) {
        j = (j + 1) % cap;
        const other = pool.hash_to_block[j];
        if (other == none) break;
        const home = tableHome(pool, pool.blocks[other].hash);
        const stays = if (hole <= j) (hole < home and home <= j) else (hole < home or home <= j);
        if (stays) continue;
        pool.hash_to_block[hole] = other;
        pool.hash_to_block[j] = none;
        hole = j;
    }
    assert(tableFind(pool, hash) == null or pool.hash_to_block[tableFind(pool, hash).?] != s);
}

// ---- tests -------------------------------------------------------------------------------

// ---- tests helper (also used by prefix.zig tests) ----------------------------------------

/// One group of equal-sized pages: the degenerate (pages_per_slab == 1) pool the pre-slab code used.
/// num_blocks counts the null page, so it makes num_blocks - 1 slabs of one page each.
pub fn flatInit(allocator: std.mem.Allocator, num_blocks: u32, block_size: u32, n_groups: u32) !Pool {
    assert(num_blocks >= 2);
    assert(n_groups > 0 and n_groups <= max_flat_groups);
    var groups: [max_flat_groups]PoolGroup = undefined;
    for (groups[0..n_groups]) |*group| group.* = .{ .bytes_per_page = 4096, .pages_per_slab = 1 };
    return Pool.init(allocator, num_blocks - 1, 4096, groups[0..n_groups], block_size);
}

const max_flat_groups = 8;

fn assertFreeListLinked(pool: *const Pool) void {
    assert(pool.blocks[null_block].ref_count == 1);
    if (pool.head == none) assert(pool.tail == none);
    if (pool.tail == none) assert(pool.head == none);

    var n_free: u32 = 0;
    for (pool.slabs) |slab| {
        assert((slab.n_used == 0) == slab.on_free_list or slab.n_used > 0);
        if (slab.on_free_list) {
            assert(slab.n_used == 0);
            n_free += 1;
        }
    }
    assert(n_free == pool.n_free_slabs);

    var n_forward: u32 = 0;
    var prev: u32 = none;
    var id = pool.head;
    while (id != none) : (id = pool.slabs[id].next) {
        assert(n_forward < pool.n_free_slabs);
        assert(pool.slabs[id].on_free_list);
        assert(pool.slabs[id].prev == prev);
        prev = id;
        n_forward += 1;
    }
    assert(n_forward == pool.n_free_slabs);
    assert(prev == pool.tail);

    var n_backward: u32 = 0;
    var next: u32 = none;
    id = pool.tail;
    while (id != none) : (id = pool.slabs[id].prev) {
        assert(n_backward < pool.n_free_slabs);
        assert(pool.slabs[id].next == next);
        next = id;
        n_backward += 1;
    }
    assert(n_backward == pool.n_free_slabs);
    assert(next == pool.head);

    // Every slab's n_used equals the referenced pages in it.
    for (pool.slabs, 0..) |slab, i| {
        if (slab.owner == none) {
            assert(slab.n_used == 0);
            continue;
        }
        var counted: u32 = 0;
        var j: u32 = 0;
        while (j < pool.groups[slab.owner].pages_per_slab) : (j += 1) {
            const page = pageId(pool, slab.owner, @intCast(i), j);
            if (pool.blocks[pageSlot(pool, slab.owner, page)].ref_count > 0) counted += 1;
        }
        assert(counted == slab.n_used);
    }

    for (pool.groups, 0..) |_, g| assert(pool.n_partial[g] == walkPartial(pool, @intCast(g)));

    var n_entries: u32 = 0;
    for (pool.hash_to_block) |entry| {
        if (entry == none) continue;
        const hash = pool.blocks[entry].hash;
        assert(hash != 0);
        // The table is shared across groups and stores SLOTS, so this checks the table itself
        // (tableFind), not the group-local `lookup` that maps a slot back to one group's id.
        assert(pool.hash_to_block[tableFind(pool, hash).?] == entry);
        n_entries += 1;
    }
    assert(n_entries < pool.blocks.len);
}

test "block 0 is never handed out" {
    var pool = try flatInit(std.testing.allocator, 5, 4, 1);
    defer pool.deinit(std.testing.allocator);
    try std.testing.expectEqual(4, nFree(&pool, 0));
    var ids: [4]u32 = undefined;
    allocate(&pool, 0, &ids);
    try std.testing.expectEqualSlices(u32, &.{ 1, 2, 3, 4 }, &ids);
    try std.testing.expectEqual(0, nFree(&pool, 0));
}

test "freed-first is reused first" {
    var pool = try flatInit(std.testing.allocator, 5, 4, 1);
    defer pool.deinit(std.testing.allocator);

    var ids: [4]u32 = undefined;
    allocate(&pool, 0, &ids);
    try std.testing.expectEqualSlices(u32, &.{ 1, 2, 3, 4 }, &ids);

    free(&pool, 0, &.{3});
    free(&pool, 0, &.{1});
    free(&pool, 0, &.{4});
    var reused: [3]u32 = undefined;
    allocate(&pool, 0, &reused);
    try std.testing.expectEqualSlices(u32, &.{ 3, 1, 4 }, &reused);
}

test "free order controls reuse order" {
    const cases = [_]struct { freed: []const u32, reused: []const u32 }{
        .{ .freed = &.{ 1, 2, 3, 4 }, .reused = &.{ 1, 2 } },
        .{ .freed = &.{ 4, 3, 2, 1 }, .reused = &.{ 4, 3 } },
        .{ .freed = &.{ 2, 4, 1, 3 }, .reused = &.{ 2, 4 } },
    };
    for (cases) |case| {
        var pool = try flatInit(std.testing.allocator, 5, 4, 1);
        defer pool.deinit(std.testing.allocator);
        var ids: [4]u32 = undefined;
        allocate(&pool, 0, &ids);
        free(&pool, 0, case.freed);
        var reused: [2]u32 = undefined;
        allocate(&pool, 0, &reused);
        try std.testing.expectEqualSlices(u32, case.reused, &reused);
    }
}

test "nFree accounting across allocate and free" {
    var pool = try flatInit(std.testing.allocator, 9, 4, 1); // 8 usable
    defer pool.deinit(std.testing.allocator);
    try std.testing.expectEqual(8, nFree(&pool, 0));

    var a: [3]u32 = undefined;
    allocate(&pool, 0, &a);
    try std.testing.expectEqual(5, nFree(&pool, 0));
    var b: [5]u32 = undefined;
    allocate(&pool, 0, &b);
    try std.testing.expectEqual(0, nFree(&pool, 0));
    free(&pool, 0, a[0..2]);
    try std.testing.expectEqual(2, nFree(&pool, 0));
    free(&pool, 0, &b);
    try std.testing.expectEqual(7, nFree(&pool, 0));
    free(&pool, 0, a[2..3]);
    try std.testing.expectEqual(8, nFree(&pool, 0));
    allocate(&pool, 0, &[_]u32{});
    try std.testing.expectEqual(8, nFree(&pool, 0));
}

test "invariants hold across a randomized sequence" {
    const num_blocks = 16;
    var pool = try flatInit(std.testing.allocator, num_blocks + 1, 4, 1);
    defer pool.deinit(std.testing.allocator);

    var prng = std.Random.DefaultPrng.init(0x5eed);
    const random = prng.random();
    var held: [num_blocks]u32 = undefined;
    var n_held: u32 = 0;
    var scratch: [num_blocks]u32 = undefined;

    for (0..2000) |_| {
        const do_allocate = random.boolean();
        if (do_allocate and nFree(&pool, 0) > 0) {
            const n = random.intRangeAtMost(u32, 1, nFree(&pool, 0));
            allocate(&pool, 0, scratch[0..n]);
            @memcpy(held[n_held..][0..n], scratch[0..n]);
            n_held += n;
        } else if (n_held > 0) {
            const n = random.intRangeAtMost(u32, 1, n_held);
            random.shuffle(u32, held[0..n_held]);
            free(&pool, 0, held[n_held - n .. n_held]);
            n_held -= n;
        }
        assertFreeListLinked(&pool);
        try std.testing.expectEqual(num_blocks, nFree(&pool, 0) + n_held);
    }
}

test "touch resurrects a freed block and free drops references" {
    var pool = try flatInit(std.testing.allocator, 5, 4, 1);
    defer pool.deinit(std.testing.allocator);
    var ids: [2]u32 = undefined;
    allocate(&pool, 0, &ids);
    publish(&pool, 0, ids[0], 0xabc, &.{ 1, 2, 3, 4 });
    free(&pool, 0, &ids);
    try std.testing.expectEqual(4, nFree(&pool, 0));
    try std.testing.expectEqual(ids[0], lookup(&pool, 0, 0xabc).?);
    try std.testing.expectEqualSlices(u32, &.{ 1, 2, 3, 4 }, blockTokens(&pool, 0, ids[0]));

    touch(&pool, 0, ids[0]); // resurrected from the middle of the free list
    try std.testing.expectEqual(3, nFree(&pool, 0));
    touch(&pool, 0, ids[0]); // second holder
    assertFreeListLinked(&pool);
    free(&pool, 0, ids[0..1]);
    try std.testing.expectEqual(3, nFree(&pool, 0));
    free(&pool, 0, ids[0..1]);
    try std.testing.expectEqual(4, nFree(&pool, 0));
    try std.testing.expectEqual(ids[0], lookup(&pool, 0, 0xabc).?);

    // Popping it off the free list forgets the hash.
    var fresh: [4]u32 = undefined;
    allocate(&pool, 0, &fresh);
    try std.testing.expectEqual(null, lookup(&pool, 0, 0xabc));
    try std.testing.expectEqual(0, blockTokens(&pool, 0, ids[0]).len);
    assertFreeListLinked(&pool);
}

test "duplicate publish keeps the first block findable" {
    var pool = try flatInit(std.testing.allocator, 3, 4, 1);
    defer pool.deinit(std.testing.allocator);
    var ids: [2]u32 = undefined;
    allocate(&pool, 0, &ids);
    publish(&pool, 0, ids[0], 7, &.{ 1, 2 });
    publish(&pool, 0, ids[1], 7, &.{ 1, 2 });
    try std.testing.expectEqual(ids[0], lookup(&pool, 0, 7).?);
    free(&pool, 0, ids[0..1]);
    var fresh: [1]u32 = undefined;
    allocate(&pool, 0, &fresh);
    try std.testing.expectEqual(ids[0], fresh[0]);
    try std.testing.expectEqual(null, lookup(&pool, 0, 7));
    assertFreeListLinked(&pool);
}

test "hash table invariants hold across a randomized publish/touch/free sequence" {
    const num_blocks = 16;
    var pool = try flatInit(std.testing.allocator, num_blocks + 1, 4, 1);
    defer pool.deinit(std.testing.allocator);
    var prng = std.Random.DefaultPrng.init(0xcafe);
    const random = prng.random();
    var refs: [num_blocks + 1]u32 = [_]u32{0} ** (num_blocks + 1);

    for (0..4000) |_| {
        switch (random.intRangeAtMost(u8, 0, 3)) {
            0 => if (nFree(&pool, 0) > 0) {
                var id: [1]u32 = undefined;
                allocate(&pool, 0, &id);
                refs[id[0]] += 1;
            },
            1 => {
                const id = random.intRangeAtMost(u32, 1, num_blocks);
                if (refs[id] > 0 and pool.blocks[pageSlot(&pool, 0, id)].hash == 0) {
                    // Small hash space so duplicates and collisions in the table happen.
                    publish(&pool, 0, id, random.intRangeAtMost(u64, 1, 6), &.{ 9, 9, 9, 9 });
                }
            },
            2 => {
                const hash = random.intRangeAtMost(u64, 1, 6);
                if (lookup(&pool, 0, hash)) |id| {
                    touch(&pool, 0, id);
                    refs[id] += 1;
                }
            },
            3 => {
                const id = random.intRangeAtMost(u32, 1, num_blocks);
                if (refs[id] > 0) {
                    free(&pool, 0, &.{id});
                    refs[id] -= 1;
                }
            },
            else => unreachable,
        }
        assertFreeListLinked(&pool);
        for (pool.blocks[1..], refs[1..]) |block, r| try std.testing.expectEqual(r, block.ref_count);
    }
}

// ---- slab carving ------------------------------------------------------------------------

test "a group with many pages per slab carves within one slab before taking another" {
    // Group 0: 1 KB pages, 4 per slab. Group 1: 4 KB pages, 1 per slab. slab_bytes = 4 KB.
    const groups = [_]PoolGroup{
        .{ .bytes_per_page = 1024, .pages_per_slab = 4 },
        .{ .bytes_per_page = 4096, .pages_per_slab = 1 },
    };
    var pool = try Pool.init(std.testing.allocator, 3, 4096, &groups, 4);
    defer pool.deinit(std.testing.allocator);
    try std.testing.expectEqual(3, nFreeSlabs(&pool));
    try std.testing.expectEqual(12, nFree(&pool, 0));
    try std.testing.expectEqual(3, nFree(&pool, 1));

    var a: [4]u32 = undefined;
    allocate(&pool, 0, &a);
    // Slab 0 (LRU head), pages 0..3: group 0 numbers its own pages, pages_per_slab 4 -> ids 1..4.
    try std.testing.expectEqualSlices(u32, &.{ 1, 2, 3, 4 }, &a);
    try std.testing.expectEqual(2, nFreeSlabs(&pool));
    try std.testing.expectEqual(2, nFree(&pool, 1));

    var b: [1]u32 = undefined;
    allocate(&pool, 1, &b);
    // Ids are GROUP-LOCAL (ruling 2026-09-10): group 1 has pages_per_slab 1, so slab 1 page 0
    // is its id 2 -- not 5, which is what the old shared max_pages_per_slab packing gave.
    try std.testing.expectEqualSlices(u32, &.{2}, &b);
    try std.testing.expectEqual(1, nFreeSlabs(&pool));
    assertFreeListLinked(&pool);

    // Freeing all four pages of slab 0 returns the whole slab.
    free(&pool, 0, a[0..3]);
    try std.testing.expectEqual(1, nFreeSlabs(&pool));
    free(&pool, 0, a[3..4]);
    try std.testing.expectEqual(2, nFreeSlabs(&pool));
    assertFreeListLinked(&pool);
}

test "slabsFor budgets partial slabs before fresh ones" {
    const groups = [_]PoolGroup{.{ .bytes_per_page = 1024, .pages_per_slab = 4 }};
    var pool = try Pool.init(std.testing.allocator, 4, 4096, &groups, 4);
    defer pool.deinit(std.testing.allocator);
    try std.testing.expectEqual(0, slabsFor(&pool, 0, 0));
    try std.testing.expectEqual(1, slabsFor(&pool, 0, 1));
    try std.testing.expectEqual(1, slabsFor(&pool, 0, 4));
    try std.testing.expectEqual(2, slabsFor(&pool, 0, 5));

    var a: [2]u32 = undefined;
    allocate(&pool, 0, &a); // slab 0 half carved: 2 pages left in the partial
    try std.testing.expectEqual(2, nPartial(&pool, 0));
    try std.testing.expectEqual(0, slabsFor(&pool, 0, 2));
    try std.testing.expectEqual(1, slabsFor(&pool, 0, 3));
    try std.testing.expectEqual(1, slabsFor(&pool, 0, 6));
    try std.testing.expectEqual(2, slabsFor(&pool, 0, 7));
    assertFreeListLinked(&pool);
}

test "taking a slab drops the hashes of every page in it" {
    const groups = [_]PoolGroup{.{ .bytes_per_page = 1024, .pages_per_slab = 4 }};
    var pool = try Pool.init(std.testing.allocator, 2, 4096, &groups, 4);
    defer pool.deinit(std.testing.allocator);

    var a: [4]u32 = undefined;
    allocate(&pool, 0, &a);
    for (a, 1..) |id, h| publish(&pool, 0, id, @intCast(h), &.{ 1, 2, 3, 4 });
    free(&pool, 0, &a); // slab 0 back on the free tail, all four still hittable
    for (1..5) |h| try std.testing.expect(lookup(&pool, 0, @intCast(h)) != null);

    var b: [4]u32 = undefined;
    allocate(&pool, 0, &b); // takes slab 1 (LRU head), slab 0 untouched
    for (1..5) |h| try std.testing.expect(lookup(&pool, 0, @intCast(h)) != null);
    var c: [1]u32 = undefined;
    allocate(&pool, 0, &c); // takes slab 0: mass hash drop
    for (1..5) |h| try std.testing.expectEqual(null, lookup(&pool, 0, @intCast(h)));
    assertFreeListLinked(&pool);
}

test "touch resurrects a released slab and keeps its carve cursor" {
    const groups = [_]PoolGroup{.{ .bytes_per_page = 1024, .pages_per_slab = 4 }};
    var pool = try Pool.init(std.testing.allocator, 2, 4096, &groups, 4);
    defer pool.deinit(std.testing.allocator);

    var a: [2]u32 = undefined;
    allocate(&pool, 0, &a); // slab 0, pages 0 and 1
    publish(&pool, 0, a[0], 0xaa, &.{ 1, 2, 3, 4 });
    free(&pool, 0, &a);
    try std.testing.expectEqual(2, nFreeSlabs(&pool));

    touch(&pool, 0, a[0]);
    try std.testing.expectEqual(1, nFreeSlabs(&pool));
    // The carve cursor survived: the next page out of slab 0 is index 2, not index 0.
    var b: [1]u32 = undefined;
    allocate(&pool, 0, &b);
    try std.testing.expectEqual(pageId(&pool, 0, 0, 2), b[0]);
    try std.testing.expectEqual(a[0], lookup(&pool, 0, 0xaa).?);
    assertFreeListLinked(&pool);
}

test "a slab is tiled exactly: pages_per_slab * bytes_per_page == slab_bytes" {
    // Ruling 2026-09-10 (docs/slab-lcm-ladder.md): slack is gone. Python rounds slab_bytes up to
    // a multiple of lcm(k_g) * 16 and pads each page to slab_bytes / k_g, so a slab divides
    // exactly. Here: a 9 KB slab with a 3 KB page fits exactly 3, no tail.
    const groups = [_]PoolGroup{.{ .bytes_per_page = 3072, .pages_per_slab = 3 }};
    var pool = try Pool.init(std.testing.allocator, 2, 9216, &groups, 4);
    defer pool.deinit(std.testing.allocator);
    try std.testing.expectEqual(6, nFree(&pool, 0)); // 2 slabs * 3 pages

    var a: [4]u32 = undefined;
    allocate(&pool, 0, &a);
    // Slab 0 gives 3 pages, then slab 1 opens: group-local ids 1,2,3 then 4.
    try std.testing.expectEqualSlices(u32, &.{ 1, 2, 3, 4 }, &a);
    try std.testing.expectEqual(0, nFreeSlabs(&pool));
    try std.testing.expectEqual(2, nPartial(&pool, 0)); // slab 1 has 2 pages left
    assertFreeListLinked(&pool);
}

test "group-local ids: two groups reuse the same numbers for different pages" {
    // Invariant (i) of the ruling: an id means nothing without its group. Group 0 (4 pages per
    // slab) and group 1 (1 page per slab) both hand out id 1, for different memory.
    const groups = [_]PoolGroup{
        .{ .bytes_per_page = 1024, .pages_per_slab = 4 },
        .{ .bytes_per_page = 4096, .pages_per_slab = 1 },
    };
    var pool = try Pool.init(std.testing.allocator, 3, 4096, &groups, 4);
    defer pool.deinit(std.testing.allocator);

    var a: [1]u32 = undefined;
    var b: [1]u32 = undefined;
    allocate(&pool, 0, &a);
    allocate(&pool, 1, &b);
    try std.testing.expectEqual(1, a[0]);
    // Group 1 takes a fresh slab (slab 0 is group 0's), and with pages_per_slab 1 its own
    // numbering makes that slab 1's page 0 the id 2.
    try std.testing.expectEqual(2, b[0]);
    // The point of group-local ids: the same NUMBER in two groups is two different pages.
    try std.testing.expect(pageSlot(&pool, 0, 1) != pageSlot(&pool, 1, 1));

    // They publish under different hashes and neither lookup crosses into the other's group.
    publish(&pool, 0, a[0], 0x11, &.{ 1, 2, 3, 4 });
    publish(&pool, 1, b[0], 0x22, &.{ 5, 6, 7, 8 });
    try std.testing.expectEqual(a[0], lookup(&pool, 0, 0x11).?);
    try std.testing.expectEqual(b[0], lookup(&pool, 1, 0x22).?);
    // Group 0 must NOT find group 1's page, and vice versa.
    try std.testing.expect(lookup(&pool, 0, 0x22) == null);
    try std.testing.expect(lookup(&pool, 1, 0x11) == null);
    try std.testing.expectEqualSlices(u32, &.{ 1, 2, 3, 4 }, blockTokens(&pool, 0, a[0]));
    try std.testing.expectEqualSlices(u32, &.{ 5, 6, 7, 8 }, blockTokens(&pool, 1, b[0]));
    assertFreeListLinked(&pool);
}

test "a resurrected slab goes on the partial tail: the most-occupied slab fills first" {
    // Two slabs of 4 pages. Carve 2 out of slab 0, free them (slab 0 released), then take slab 1
    // and carve 1 page out of it. Touching a page of slab 0 resurrects it; because it lands on the
    // TAIL, the next allocate keeps filling slab 1 (3 pages left, 1 used) rather than jumping back
    // to slab 0 (TokenSpeed planLocations: fill the most-occupied partial first).
    const groups = [_]PoolGroup{.{ .bytes_per_page = 1024, .pages_per_slab = 4 }};
    var pool2 = try Pool.init(std.testing.allocator, 2, 4096, &groups, 4);
    defer pool2.deinit(std.testing.allocator);
    var c: [2]u32 = undefined;
    allocate(&pool2, 0, &c); // slab 0 pages 0,1
    publish(&pool2, 0, c[0], 0xbb, &.{ 5, 6, 7, 8 });
    free(&pool2, 0, &c); // slab 0 on the free tail, behind slab 1
    var d: [1]u32 = undefined;
    allocate(&pool2, 0, &d); // LRU head is slab 1 (never used): carve page 0 of slab 1
    try std.testing.expectEqual(pageId(&pool2, 0, 1, 0), d[0]);
    try std.testing.expectEqual(3, nPartial(&pool2, 0)); // slab 1 has 3 left

    touch(&pool2, 0, c[0]); // resurrects slab 0 onto the partial TAIL
    try std.testing.expectEqual(5, nPartial(&pool2, 0)); // + slab 0's 2 remaining
    var e: [1]u32 = undefined;
    allocate(&pool2, 0, &e);
    // Head of the partial list is still slab 1: the most-occupied slab keeps filling.
    try std.testing.expectEqual(pageId(&pool2, 0, 1, 1), e[0]);
    assertFreeListLinked(&pool2);
}

test "invariants hold across a randomized two-group sequence" {
    const groups = [_]PoolGroup{
        .{ .bytes_per_page = 1024, .pages_per_slab = 4 },
        .{ .bytes_per_page = 2048, .pages_per_slab = 2 },
    };
    var pool = try Pool.init(std.testing.allocator, 8, 4096, &groups, 4);
    defer pool.deinit(std.testing.allocator);

    var prng = std.Random.DefaultPrng.init(0xf00d);
    const random = prng.random();
    var held: [2][64]u32 = undefined;
    var n_held: [2]u32 = .{ 0, 0 };
    var scratch: [8]u32 = undefined;

    for (0..4000) |_| {
        const g = random.intRangeAtMost(u32, 0, 1);
        if (random.boolean()) {
            const room = @min(@as(u32, 8), nFree(&pool, g));
            if (room > 0 and n_held[g] + room <= 64) {
                const n = random.intRangeAtMost(u32, 1, room);
                allocate(&pool, g, scratch[0..n]);
                @memcpy(held[g][n_held[g]..][0..n], scratch[0..n]);
                n_held[g] += n;
            }
        } else if (n_held[g] > 0) {
            const n = random.intRangeAtMost(u32, 1, n_held[g]);
            random.shuffle(u32, held[g][0..n_held[g]]);
            free(&pool, g, held[g][n_held[g] - n .. n_held[g]]);
            n_held[g] -= n;
        }
        assertFreeListLinked(&pool);
        // No page of memory is held by both groups. Ids are group-local now (ruling 2026-09-10),
        // so the same NUMBER in two groups is two different pages; compare SLOTS, which are the
        // pool-wide identity, and separately assert the two groups never share a slab.
        for (held[0][0..n_held[0]]) |id0| {
            for (held[1][0..n_held[1]]) |id1| {
                try std.testing.expect(pageSlot(&pool, 0, id0) != pageSlot(&pool, 1, id1));
                try std.testing.expect(slabOf(&pool, 0, id0) != slabOf(&pool, 1, id1));
            }
        }
    }
}
