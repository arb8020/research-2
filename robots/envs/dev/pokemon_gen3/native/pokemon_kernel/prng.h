#ifndef POKEMON_KERNEL_PRNG_H
#define POKEMON_KERNEL_PRNG_H

#include <stdint.h>

/* Pinned Showdown's numeric four-word seed selects Gen5RNG. Keep pure PRNG
 * arithmetic here; the battle kernel owns draw labels, trace capacity, and
 * transactional error handling. */
static inline uint32_t pokemon_prng_next_u32(uint16_t seed[4]) {
    uint64_t state = ((uint64_t)seed[0] << 48) |
        ((uint64_t)seed[1] << 32) |
        ((uint64_t)seed[2] << 16) | (uint64_t)seed[3];
    state = state * UINT64_C(0x5D588B656C078965) + UINT64_C(0x269EC3);
    seed[0] = (uint16_t)(state >> 48);
    seed[1] = (uint16_t)(state >> 32);
    seed[2] = (uint16_t)(state >> 16);
    seed[3] = (uint16_t)state;
    return (uint32_t)(state >> 32);
}

static inline uint32_t pokemon_prng_project_below(
    uint32_t raw, uint32_t upper
) {
    return (uint32_t)(((uint64_t)raw * upper) >> 32);
}

#endif
