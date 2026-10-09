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
    (void)r; // TODO: how many ids are waiting?
    return 0;
}

bool ring_push(Ring* r, u32 id) {
    (void)r; // TODO: false when full; otherwise store id at the tail
    (void)id;
    return false;
}

bool ring_pop(Ring* r, u32* out) {
    (void)r; // TODO: false when empty; otherwise take the id at the head
    (void)out;
    return false;
}

u32 ring_peek(const Ring* r, u32 i) {
    (void)r; // TODO: the i-th waiting id, without removing it
    (void)i;
    return 0;
}
