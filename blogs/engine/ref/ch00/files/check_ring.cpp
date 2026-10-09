// check_ring: the ring's contract, case by case. CHECK counts failures instead of aborting, so one run lists
// every broken case (cstyle_cpp.md "Testing"); exit 1 if any failed.
#include "ring.h"

static int failed = 0;

#define CHECK(x)                                                    \
    do {                                                            \
        if (!(x)) {                                                 \
            printf("%s:%d: CHECK failed: %s\n", __FILE__, __LINE__, #x); \
            failed += 1;                                            \
        }                                                           \
    } while (0)

enum : u32 { CAP = 4 };

static void fifo_order() {
    u32 storage[CAP];
    Ring r;
    ring_init(&r, storage, CAP);
    CHECK(ring_len(&r) == 0);
    CHECK(ring_push(&r, 7));
    CHECK(ring_push(&r, 8));
    CHECK(ring_len(&r) == 2);
    CHECK(ring_peek(&r, 0) == 7);
    CHECK(ring_peek(&r, 1) == 8);
    u32 out = 0;
    CHECK(ring_pop(&r, &out));
    CHECK(out == 7);
    CHECK(ring_len(&r) == 1);
}

static void full_and_empty() {
    u32 storage[CAP];
    Ring r;
    ring_init(&r, storage, CAP);
    u32 out = 99;
    CHECK(!ring_pop(&r, &out));
    CHECK(out == 99); // an empty pop leaves *out alone
    for (u32 i = 0; i < CAP; i++) CHECK(ring_push(&r, i));
    CHECK(!ring_push(&r, 100));
    CHECK(ring_len(&r) == CAP);
}

static void wraps_around() {
    u32 storage[CAP];
    Ring r;
    ring_init(&r, storage, CAP);
    u32 out = 0;
    for (u32 i = 0; i < 10 * CAP; i++) {
        CHECK(ring_push(&r, i));
        CHECK(ring_push(&r, i + 1000));
        CHECK(ring_pop(&r, &out));
        CHECK(out == i);
        CHECK(ring_pop(&r, &out));
        CHECK(out == i + 1000);
    }
    CHECK(ring_len(&r) == 0);
}

static void counters_wrap_at_2_32() {
    u32 storage[CAP];
    Ring r;
    ring_init(&r, storage, CAP);
    r.head = 0xFFFFFFFEu;
    r.tail = 0xFFFFFFFEu;
    for (u32 i = 0; i < CAP; i++) CHECK(ring_push(&r, i));
    CHECK(ring_len(&r) == CAP);
    CHECK(ring_peek(&r, 3) == 3);
}

int main() {
    setvbuf(stdout, nullptr, _IOLBF, 0); // line-buffered: the page streams each line as it comes
    fifo_order();
    full_and_empty();
    wraps_around();
    counters_wrap_at_2_32();
    if (failed > 0) {
        printf("%d check(s) failed\n", failed);
        return 1;
    }
    printf("ok ring\n");
    return 0;
}
