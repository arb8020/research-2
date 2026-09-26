const std = @import("std");

// xgrammar_shim/xgrammar_c.h + libxgrammar_shim/libxgrammar, built by
// scripts/build_xgrammar.sh into xgrammar_shim/build (see xgrammar_shim/CMakeLists.txt for why
// this is a separate CMake build rather than something Zig compiles directly: xgrammar's own
// C++ core needs its own compiler/build flags, and upstream ships it STATIC-only). Any module
// that imports xgrammar.zig (root_source_file c_api.zig / root.zig) needs both the include path
// (for @cInclude) and the link step (for the actual symbols); tests link it too since root.zig
// pulls in c_api.zig.
fn linkXgrammarShim(b: *std.Build, mod: *std.Build.Module) void {
    const shim_dir = "xgrammar_shim";
    const build_dir = shim_dir ++ "/build";
    mod.addIncludePath(b.path(shim_dir));
    mod.addLibraryPath(b.path(build_dir));
    mod.linkSystemLibrary("xgrammar_shim", .{ .needed = true });
    mod.linkSystemLibrary("xgrammar", .{ .needed = true });
    // rpath so the built artifact finds libxgrammar_shim.{so,dylib} without LD_LIBRARY_PATH /
    // DYLD_LIBRARY_PATH at run time -- both live in xgrammar_shim/build next to each other.
    mod.addRPathSpecial("@loader_path/../../xgrammar_shim/build"); // macOS: relative to zig-out/lib
    mod.addRPathSpecial("$ORIGIN/../../xgrammar_shim/build"); // Linux equivalent
}

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});

    // Library root. link_libc: the xgrammar shim is C++, and the C ABI surface in c_api.zig
    // is built against libc.
    const core_mod = b.addModule("kelpie_core", .{
        .root_source_file = b.path("src/root.zig"),
        .target = target,
        .optimize = optimize,
        .link_libc = true,
    });
    linkXgrammarShim(b, core_mod);

    const lib = b.addLibrary(.{
        .name = "kelpie_core",
        .root_module = core_mod,
        .linkage = .static,
    });
    b.installArtifact(lib);

    // Shared library for the Python ctypes loader (kelpie-engine). `zig build lib`.
    const c_api_mod = b.createModule(.{
        .root_source_file = b.path("src/c_api.zig"),
        .target = target,
        .optimize = optimize,
        .link_libc = true,
    });
    linkXgrammarShim(b, c_api_mod);
    const shared = b.addLibrary(.{
        .name = "kelpie",
        .root_module = c_api_mod,
        .linkage = .dynamic,
    });
    shared.installHeadersDirectory(b.path("include"), "", .{});
    const install_shared = b.addInstallArtifact(shared, .{});
    b.step("lib", "Build libkelpie shared library (zig-out/lib)").dependOn(&install_shared.step);


    // Tests: everything reachable from root.zig. No GPU required.
    const tests = b.addTest(.{
        .root_source_file = b.path("src/root.zig"),
        .target = target,
        .optimize = optimize,
        .link_libc = true,
    });
    linkXgrammarShim(b, tests.root_module);
    const run_tests = b.addRunArtifact(tests);
    run_tests.setCwd(b.path("."));
    b.step("test", "Run library tests").dependOn(&run_tests.step);
}
