//! kelpie-core: static-allocation inference engine core.
//!
//! Layout (design-rules.md #7, messy boundary / sharp interior):
//!   xgrammar.zig — the only file that touches a C library via FFI.
//! request.zig / kv_pool.zig / prefix.zig / scheduler.zig — the engine core, no FFI.
//!
//! No CUDA here: kernels come from torch (docs/decisions.md, "Kernels come from torch"), so
//! the core never touches the CUDA driver API and cuda.zig / cuda_smoke.zig / kernels/ went
//! with the old path on 2026-09-10.

pub const request = @import("request.zig");
pub const kv_pool = @import("kv_pool.zig");
pub const prefix = @import("prefix.zig");
pub const events = @import("events.zig");
pub const c_api = @import("c_api.zig");
pub const buckets = @import("buckets.zig");
pub const scheduler = @import("scheduler.zig");
pub const step_loop = @import("step_loop.zig");
pub const trace_test = @import("trace_test.zig");
pub const abi_ids = @import("abi_ids.zig");

test {
    @import("std").testing.refAllDecls(@This());
}
