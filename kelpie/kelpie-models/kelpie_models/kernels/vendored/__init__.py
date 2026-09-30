"""Vendored kernel sources, one directory per backend's toolchain. These files are the upstream
code as pulled in; nothing here imports at package-import time and nothing here is an op.

An op file's `@<op>.register(...)` adapter imports the one function it wraps, lazily, inside the
adapter body -- so a machine without triton/jax/neuronxcc can still import every op.
"""
