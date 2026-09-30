#include "pokemon_kernel/prng.h"

#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

static void reset(uint16_t seed[4]) {
    const uint16_t initial[4] = {1, 2, 3, 4};
    memcpy(seed, initial, sizeof(initial));
}

static void test_exact_gen5_vectors(void) {
    uint16_t seed[4];
    reset(seed);
    const uint64_t states[] = {
        UINT64_C(0x790684764c73c457),
        UINT64_C(0xe22232e83046a416),
        UINT64_C(0xa9fa25469e6f2171),
        UINT64_C(0x2241436090fb4958),
    };
    const uint32_t raw[] = {
        UINT32_C(2030470262), UINT32_C(3793892072),
        UINT32_C(2851743046), UINT32_C(574702432),
    };
    for (size_t i = 0; i < sizeof(raw) / sizeof(raw[0]); i++) {
        assert(pokemon_prng_next_u32(seed) == raw[i]);
        uint64_t actual = ((uint64_t)seed[0] << 48) |
            ((uint64_t)seed[1] << 32) |
            ((uint64_t)seed[2] << 16) | seed[3];
        assert(actual == states[i]);
    }
}

static void test_replay_and_bounded_projection(void) {
    uint16_t left[4];
    uint16_t right[4];
    reset(left);
    reset(right);
    for (size_t i = 0; i < 100; i++) {
        uint32_t left_raw = pokemon_prng_next_u32(left);
        uint32_t right_raw = pokemon_prng_next_u32(right);
        assert(left_raw == right_raw);
        assert(pokemon_prng_project_below(left_raw, 2) ==
            pokemon_prng_project_below(right_raw, 2));
    }
    assert(memcmp(left, right, sizeof(left)) == 0);
}

static void test_deterministic_distribution_witnesses(void) {
    uint16_t seed[4];
    size_t half_zero = 0;
    size_t chance_217 = 0;
    size_t duplicate_slots[3] = {0};
    reset(seed);
    for (size_t i = 0; i < 100; i++) {
        uint32_t raw = pokemon_prng_next_u32(seed);
        half_zero += pokemon_prng_project_below(raw, 2) == 0;
    }
    assert(half_zero == 54);

    reset(seed);
    for (size_t i = 0; i < 100; i++) {
        uint32_t raw = pokemon_prng_next_u32(seed);
        chance_217 += pokemon_prng_project_below(raw, 256) < 217;
    }
    assert(chance_217 == 85);

    reset(seed);
    size_t five[5] = {0};
    for (size_t i = 0; i < 1000; i++) {
        uint32_t raw = pokemon_prng_next_u32(seed);
        five[pokemon_prng_project_below(raw, 5)]++;
    }
    const size_t expected_five[5] = {201, 188, 201, 212, 198};
    assert(memcmp(five, expected_five, sizeof(five)) == 0);

    reset(seed);
    for (size_t i = 0; i < 100; i++) {
        uint32_t raw = pokemon_prng_next_u32(seed);
        duplicate_slots[pokemon_prng_project_below(raw, 3)]++;
    }
    assert(duplicate_slots[0] + duplicate_slots[1] == 67);
    assert(duplicate_slots[2] == 33);
}

static void test_boundary_denominators_still_advance(void) {
    uint16_t seed[4];
    reset(seed);
    uint16_t before[4];
    memcpy(before, seed, sizeof(before));
    for (size_t i = 0; i < 100; i++) {
        uint32_t raw = pokemon_prng_next_u32(seed);
        assert(pokemon_prng_project_below(raw, 1) == 0);
        assert(pokemon_prng_project_below(raw, 256) < 256);
    }
    assert(memcmp(seed, before, sizeof(seed)) != 0);
}

static void test_chance_and_dense_sampling_projection_identity(void) {
    uint16_t chance_seed[4];
    uint16_t random_seed[4];
    reset(chance_seed);
    reset(random_seed);
    for (size_t i = 0; i < 10; i++) {
        uint32_t chance_raw = pokemon_prng_next_u32(chance_seed);
        uint32_t random_raw = pokemon_prng_next_u32(random_seed);
        assert(chance_raw == random_raw);
        assert((pokemon_prng_project_below(chance_raw, 2) < 1) ==
            (pokemon_prng_project_below(random_raw, 2) == 0));
    }
    assert(memcmp(chance_seed, random_seed, sizeof(chance_seed)) == 0);

    reset(chance_seed);
    reset(random_seed);
    for (size_t i = 0; i < 10; i++) {
        uint32_t chance_raw = pokemon_prng_next_u32(chance_seed);
        uint32_t random_raw = pokemon_prng_next_u32(random_seed);
        assert(chance_raw == random_raw);
        assert((pokemon_prng_project_below(chance_raw, 256) < 217) ==
            (pokemon_prng_project_below(random_raw, 256) < 217));
    }
    assert(memcmp(chance_seed, random_seed, sizeof(chance_seed)) == 0);

    static const uint8_t dense_items[8] = {11, 22, 33, 44, 55, 66, 77, 88};
    reset(chance_seed);
    reset(random_seed);
    for (size_t i = 0; i < 10; i++) {
        uint32_t sample_raw = pokemon_prng_next_u32(chance_seed);
        uint32_t random_raw = pokemon_prng_next_u32(random_seed);
        uint32_t sample_index = pokemon_prng_project_below(sample_raw, 8);
        uint32_t random_index = pokemon_prng_project_below(random_raw, 8);
        assert(dense_items[sample_index] == dense_items[random_index]);
    }
    assert(memcmp(chance_seed, random_seed, sizeof(chance_seed)) == 0);
}

int main(void) {
    test_exact_gen5_vectors();
    test_replay_and_bounded_projection();
    test_deterministic_distribution_witnesses();
    test_boundary_denominators_still_advance();
    test_chance_and_dense_sampling_projection_identity();
    puts("Pokemon Gen5 PRNG tests passed");
    return 0;
}
