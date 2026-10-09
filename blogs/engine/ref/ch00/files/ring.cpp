// ring.cpp: your ring. head and tail count pushes and pops forever; the slot is the count masked by cap - 1.
#include "ring.h"

void ring_init(Ring* r, u32* storage, u32 cap) {
    ASSERT(storage != nullptr);
    ASSERT(cap > 0);
    ASSERT((cap & (cap - 1)) == 0);
    r->items = storage;
    r->cap = cap;
    r->head = 0;
    r->tail = 0;
}

u32 ring_len(const Ring* r) {
    u32 len = r->tail - r->head;
    ASSERT(len <= r->cap);
    return len;
}

bool ring_push(Ring* r, u32 id) {
    if (ring_len(r) == r->cap) return false;
    r->items[r->tail & (r->cap - 1)] = id;
    r->tail += 1;
    return true;
}

bool ring_pop(Ring* r, u32* out) {
    if (ring_len(r) == 0) return false;
    *out = r->items[r->head & (r->cap - 1)];
    r->head += 1;
    return true;
}

u32 ring_peek(const Ring* r, u32 i) {
    ASSERT(i < ring_len(r));
    return r->items[(r->head + i) & (r->cap - 1)];
}
