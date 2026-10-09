// check_trace: replays a text trace against sched_step. Lines:
//   req <id> <prompt_len> <max_new>      define a request
//   push <id>                            enqueue it
//   step <budget> -> <id>:<tokens> ...   run a step; expect exactly this batch (then requeue it)
//   done <id>                            generated += 1 (decode progress)
// Prints "ok N steps", or the first mismatch as "<trace>:<line>: ..." and exits 1.
#include <cstring>
#include "loop.h"

enum : u32 { RING_CAP = 256, LINE_MAX_BYTES = 1024 };

static Request reqs[MAX_REQS];
static u32 storage[RING_CAP];

// The expected batch after "->" must match got exactly; returns false (after printing why) if not.
static bool expect_batch(const char* trace, int lineno, int steps, char* want, const Batch* got) {
    u32 want_n = 0;
    for (char* tok = strtok(want, " \n"); tok != nullptr; tok = strtok(nullptr, " \n")) {
        unsigned id = 0;
        unsigned t = 0;
        if (sscanf(tok, "%u:%u", &id, &t) != 2) {
            printf("%s:%d: bad batch item '%s'\n", trace, lineno, tok);
            return false;
        }
        if (want_n >= got->n || got->ids[want_n] != id || got->tokens[want_n] != t) {
            printf("%s:%d: step %d: expected %u:%u at position %u, got:", trace, lineno, steps, id, t, want_n);
            for (u32 i = 0; i < got->n; i++) printf(" %u:%u", got->ids[i], got->tokens[i]);
            printf("\n");
            return false;
        }
        want_n += 1;
    }
    if (want_n != got->n) {
        printf("%s:%d: step %d: the batch has %u items, expected %u\n", trace, lineno, steps, got->n, want_n);
        return false;
    }
    return true;
}

int main(int argc, char** argv) {
    if (argc != 2) {
        fprintf(stderr, "usage: check_trace <trace>\n");
        return 2;
    }
    setvbuf(stdout, nullptr, _IOLBF, 0); // line-buffered: the page streams each line as it comes
    const char* trace = argv[1];
    FILE* f = fopen(trace, "r");
    if (f == nullptr) {
        perror(trace);
        return 2;
    }
    Ring waiting;
    ring_init(&waiting, storage, RING_CAP);
    char line[LINE_MAX_BYTES];
    int lineno = 0;
    int steps = 0;
    while (fgets(line, sizeof line, f) != nullptr) {
        lineno += 1;
        unsigned a = 0;
        unsigned b = 0;
        unsigned c = 0;
        if (line[0] == '#' || line[0] == '\n') continue;
        if (sscanf(line, "req %u %u %u", &a, &b, &c) == 3) {
            ASSERT(a < MAX_REQS);
            reqs[a] = Request{b, 0, c};
            continue;
        }
        if (sscanf(line, "push %u", &a) == 1) {
            ASSERT(ring_push(&waiting, a));
            continue;
        }
        if (sscanf(line, "done %u", &a) == 1) {
            reqs[a].generated += 1;
            continue;
        }
        if (sscanf(line, "step %u", &a) == 1) {
            Batch got;
            sched_step(reqs, &waiting, a, &got);
            char* arrow = strstr(line, "->");
            char* want = arrow != nullptr ? arrow + 2 : line + strlen(line);
            if (!expect_batch(trace, lineno, steps, want, &got)) return 1;
            steps += 1;
            for (u32 i = 0; i < got.n; i++) ASSERT(ring_push(&waiting, got.ids[i]));
            continue;
        }
        printf("%s:%d: unknown line: %s", trace, lineno, line);
        return 2;
    }
    fclose(f);
    printf("ok %d steps\n", steps);
    return 0;
}
