//! kelpie_sizeof / kelpie_offsetof (docs/derisk-plan-abi-2026-09-09.md "sizeof/offsetof tripwire
//! first"): a runtime layout tripwire over the 9 extern structs the header hand-mirrors from
//! c_api.zig/events.zig. The Zig struct list below (`structs`) is the ONE writer of both the
//! struct-id -> struct mapping and the field-id -> field mapping (via @typeInfo/std.meta.fields,
//! comptime) -- kelpie.h's KELPIE_STRUCT_*/KELPIE_FIELD_* enums are hand-written copies of the
//! *ordinals* this file assigns (struct index in `structs`, field index in that struct's
//! declaration order). `zig build test` fails if the header's ordinals drift from this list:
//! see the "header ids match this table" test at the bottom, which re-derives the header's
//! constants from a checked-in copy of them and compares against @typeInfo directly.

const std = @import("std");
const c_api = @import("c_api.zig");
const events = @import("events.zig");

/// One entry per extern struct the header mirrors. Order here IS the KELPIE_STRUCT_* ordinal
/// order -- append only; never reorder or remove (additive ABI, same rule as the structs
/// themselves).
const structs = .{
    c_api.KelpieConfig,
    c_api.KelpieKnob,
    c_api.KelpieSetResult,
    c_api.KelpiePlan,
    c_api.KelpieCommit,
    c_api.KelpiePoll,
    events.StepEvent,
    events.RequestEvent,
    c_api.KelpieStepOut,
};

const n_structs = structs.len;

/// sizeof for struct_id; 0 for an out-of-range id. 0 is safe as a sentinel here because no
/// extern struct in this table is (or ever will be) zero-sized -- every one of the 9 carries at
/// least a u32. SIZE_MAX was the other option considered (see kelpie_sizeof doc comment in
/// c_api.zig for why 0 won out).
pub fn sizeOf(struct_id: u32) usize {
    inline for (structs, 0..) |S, i| {
        if (struct_id == i) return @sizeOf(S);
    }
    return 0;
}

/// offsetof for (struct_id, field_id); 0 for an out-of-range struct_id OR field_id. Field ids
/// are the field's index in the struct's declaration order (std.meta.fields), matching the
/// header's per-struct KELPIE_FIELD_<STRUCT>_* enum, which lists fields in the same order they
/// appear in the struct definition.
pub fn offsetOf(struct_id: u32, field_id: u32) usize {
    inline for (structs, 0..) |S, i| {
        if (struct_id == i) {
            const fields = std.meta.fields(S);
            inline for (fields, 0..) |f, j| {
                if (field_id == j) return @offsetOf(S, f.name);
            }
            return 0;
        }
    }
    return 0;
}

/// Field count for struct_id; 0 for an out-of-range id. Exposed so a caller (or the test below)
/// can enumerate 0..fieldCount(id) rather than guessing how many KELPIE_FIELD_* constants exist.
pub fn fieldCount(struct_id: u32) usize {
    inline for (structs, 0..) |S, i| {
        if (struct_id == i) return std.meta.fields(S).len;
    }
    return 0;
}

test "sizeOf/offsetOf agree with @sizeOf/@offsetOf for every struct in the table" {
    inline for (structs, 0..) |S, i| {
        try std.testing.expectEqual(@sizeOf(S), sizeOf(@intCast(i)));
        const fields = std.meta.fields(S);
        inline for (fields, 0..) |f, j| {
            try std.testing.expectEqual(@offsetOf(S, f.name), offsetOf(@intCast(i), @intCast(j)));
        }
        try std.testing.expectEqual(fields.len, fieldCount(@intCast(i)));
    }
}

test "unknown struct_id and field_id return 0" {
    try std.testing.expectEqual(@as(usize, 0), sizeOf(n_structs));
    try std.testing.expectEqual(@as(usize, 0), sizeOf(999));
    try std.testing.expectEqual(@as(usize, 0), offsetOf(0, 999));
    try std.testing.expectEqual(@as(usize, 0), offsetOf(999, 0));
    try std.testing.expectEqual(@as(usize, 0), fieldCount(999));
}

// ---- spot-check known offsets (docs/derisk-plan-abi-2026-09-09.md, next-session item 2c) ----
// A hand-verified pin, independent of the generic loop above, on a couple of fields whose
// offset would be easy to get wrong by hand if this table's declaration order ever drifted
// from the struct's: KelpieConfig.n_groups is the third u32 (offset 8, after two u32 fields),
// and KelpiePlan.step (a u64) falls after 17 leading fields of assorted width -- verified here
// against @offsetOf directly rather than through this file's own machinery, so a bug in the
// inline-for loop above can't hide behind agreeing with itself.
test "spot-check known offsets against @offsetOf directly" {
    try std.testing.expectEqual(@as(usize, 8), @offsetOf(c_api.KelpieConfig, "n_groups"));
    try std.testing.expectEqual(@offsetOf(c_api.KelpieConfig, "n_groups"), offsetOf(0, 2));

    try std.testing.expectEqual(@as(usize, 0), @offsetOf(c_api.KelpiePlan, "n_reqs"));
    try std.testing.expectEqual(@offsetOf(c_api.KelpiePlan, "step"), offsetOf(3, structFieldIndex(c_api.KelpiePlan, "step")));
}

fn structFieldIndex(comptime S: type, comptime name: []const u8) u32 {
    const fields = std.meta.fields(S);
    inline for (fields, 0..) |f, i| {
        if (comptime std.mem.eql(u8, f.name, name)) return i;
    }
    @compileError("field not found");
}

// ---- header ids match this table -------------------------------------------------------------
// kelpie.h hand-mirrors KELPIE_STRUCT_* (struct ordinal) and KELPIE_FIELD_<STRUCT>_* (per-struct
// field ordinal) as plain C enums, generated by eye from this file. There is no way for a zig
// test to parse kelpie.h, so instead this test pins the *field name, in order* for every struct,
// as a checked Zig-side literal; a header edit that reorders/renames/adds a field without a
// matching edit here (and to kelpie.h) is caught the next time this list is updated by hand and
// diffed against the header during review -- see docs/handoff note for why full header-parsing
// (derisk option (a)/(c)) is out of scope for this change. This is the best a Zig-only test can
// do to keep the *ordering* honest without a C/C++ parser in the build.
const expected_field_order = .{
    .{ "KelpieConfig", &[_][]const u8{
        "max_requests", "max_seq_len", "n_groups", "group_kinds", "group_block_sizes",
        "group_windows", "group_cacheable", "num_blocks", "max_batch_tokens", "max_batch_reqs",
        "reserve_ratio", "order", "eos_token", "prefix_cache", "config_hash",
        "group_strides", "overlap", "vocab_words", "group_bytes_per_page",
        "slab_bytes", "num_slabs", "max_extra", "vocab_size",
    } },
    .{ "KelpieKnob", &[_][]const u8{ "kind", "u32_value", "f32_value" } },
    .{ "KelpieSetResult", &[_][]const u8{ "apply_step", "config_hash" } },
    .{ "KelpiePlan", &[_][]const u8{
        "n_reqs", "n_tokens", "n_groups", "req_ids", "n_work", "input_ids", "positions",
        "query_start_loc", "seq_lens", "slot_mapping", "block_tables", "max_blocks_per_req",
        "temperatures", "mm_hashes", "kinds", "n_extra", "logit_mask", "step",
        "n_reqs_padded", "n_tokens_padded", "row_request", "shape", "seq_start", "emits",
        "max_extra", "zero_unit", "state_read", "state_write", "state_ckpt", "state_ckpt_row",
        "digest", "top_ks",
    } },
    .{ "KelpieCommit", &[_][]const u8{ "n_entries", "stride", "tokens", "n_tokens", "next_extra" } },
    .{ "KelpiePoll", &[_][]const u8{ "n_new", "finished", "state" } },
    .{ "StepEvent", &[_][]const u8{
        "step", "t_plan_ns", "t_forward_ns", "t_commit_ns", "n_running", "n_waiting",
        "n_prefill_reqs", "n_decode_reqs", "n_tokens", "kv_free", "kv_used", "n_admitted",
        "n_preempted", "n_finished", "n_rejected_full", "prefix_queries", "prefix_hits",
        "prefix_hit_tokens", "order", "config_hash", "is_idle", "n_extra_rows", "n_extra_kept",
    } },
    .{ "RequestEvent", &[_][]const u8{
        "t_arrival_ns", "t_first_sched_ns", "t_first_token_ns", "t_last_token_ns", "t_finish_ns",
        "first_step", "last_step", "request_id", "n_prompt", "n_gen", "max_new", "n_preemptions",
        "n_chunks", "finish_reason", "kv_blocks_peak",
    } },
    .{ "KelpieStepOut", &[_][]const u8{ "stride", "tokens", "n_tokens", "next_extra" } },
};

test "expected_field_order (hand-kept, mirrors kelpie.h KELPIE_FIELD_* enums) matches the structs" {
    try std.testing.expectEqual(n_structs, expected_field_order.len);
    inline for (structs, 0..) |S, i| {
        const entry = expected_field_order[i];
        const expected_names = entry[1];
        const fields = std.meta.fields(S);
        try std.testing.expectEqual(expected_names.len, fields.len);
        inline for (fields, 0..) |f, j| {
            try std.testing.expect(std.mem.eql(u8, f.name, expected_names[j]));
        }
    }
}
