// ring.h: a fixed-capacity FIFO of request ids. The caller owns the storage; nothing here allocates.
#pragma once
#include "core.h"

struct Ring {
    u32* items;
    u32 cap;  // a power of two, so `i & (cap - 1)` is `i % cap`
    u32 head; // next pop; only grows (wrapping at 2^32 is fine: cap divides 2^32)
    u32 tail; // next push
};

void ring_init(Ring* r, u32* storage, u32 cap);
u32 ring_len(const Ring* r);
bool ring_push(Ring* r, u32 id);     // false when full
bool ring_pop(Ring* r, u32* out);    // false when empty
u32 ring_peek(const Ring* r, u32 i); // the i-th waiting id from the front; i < ring_len(r)
