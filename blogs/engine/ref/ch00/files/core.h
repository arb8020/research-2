// core.h: fixed-width types and the always-on ASSERT (cstyle_cpp.md: never <cassert>; NDEBUG must not strip checks).
#pragma once
#include <cstdint>
#include <cstdio>
#include <cstdlib>

typedef uint8_t u8;
typedef uint32_t u32;
typedef uint64_t u64;
typedef int32_t s32;

#define ARRAY_SIZE(a) (sizeof(a) / sizeof((a)[0]))

// file:line first, so the page turns it into a link to the failing line.
#define ASSERT(x)                                                                  \
    do {                                                                           \
        if (!(x)) {                                                                \
            fprintf(stderr, "%s:%d: ASSERT failed: %s\n", __FILE__, __LINE__, #x); \
            abort();                                                               \
        }                                                                          \
    } while (0)
