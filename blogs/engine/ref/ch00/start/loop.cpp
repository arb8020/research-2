// loop.cpp: your scheduler step (loop.h has the contract).
#include "loop.h"

void sched_step(const Request* reqs, Ring* waiting, u32 budget, Batch* out) {
    out->n = 0;
    // TODO: admit from the front of `waiting` while the next request fits the budget and the batch.
    (void)reqs;
    (void)waiting;
    (void)budget;
}
