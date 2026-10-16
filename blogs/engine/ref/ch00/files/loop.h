// loop.h: one scheduler step as a pure function: the waiting queue + a token budget -> the batch to run.
#pragma once
#include "core.h"
#include "ring.h"

enum : u32 { MAX_BATCH = 64, MAX_REQS = 1024 };

struct Request {
    u32 prompt_len;
    u32 generated;
    u32 max_new;
};

struct Batch {
    u32 ids[MAX_BATCH];
    u32 tokens[MAX_BATCH]; // tokens this step for ids[i]
    u32 n;
};

// Admit requests from the front of `waiting`, in order, while they fit `budget` tokens and MAX_BATCH.
// A request not started yet costs prompt_len tokens (prefill); a started one costs 1 (decode).
// Admitted ids are popped; the first one that doesn't fit ends the step (no skipping ahead).
void sched_step(const Request* reqs, Ring* waiting, u32 budget, Batch* out);
