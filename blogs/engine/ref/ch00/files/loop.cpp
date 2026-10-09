// loop.cpp: your scheduler step (loop.h has the contract).
#include "loop.h"

void sched_step(const Request* reqs, Ring* waiting, u32 budget, Batch* out) {
    out->n = 0;
    u32 used = 0;
    while (ring_len(waiting) > 0 && out->n < MAX_BATCH) {
        u32 id = ring_peek(waiting, 0);
        ASSERT(id < MAX_REQS);
        const Request* r = &reqs[id];
        u32 cost = r->generated == 0 ? r->prompt_len : 1;
        if (used + cost > budget) break;
        u32 popped = 0;
        bool ok = ring_pop(waiting, &popped);
        ASSERT(ok);
        ASSERT(popped == id);
        out->ids[out->n] = id;
        out->tokens[out->n] = cost;
        out->n += 1;
        used += cost;
    }
    ASSERT(used <= budget);
}
