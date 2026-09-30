#define _POSIX_C_SOURCE 200809L
#include <assert.h>
#include <inttypes.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#if defined(__APPLE__)
#include <mach/mach.h>
#elif defined(__linux__)
#include <unistd.h>
#endif
#ifdef GEN3_VERIFY_TRACE
#error "performance benchmark must be built with tracing disabled"
#endif
#include "../../ocean/pokemon_slice.h"

enum { ENV_COUNT = 1024, WARMUP_SWEEPS = 64, MEASURED_REPETITIONS = 5,
    SWEEPS_PER_REPETITION = 256, SCALAR_STEPS = 4096 };

struct Dict { int unused; };
const char *dict_get_str(Dict *dict, const char *key) {
    (void)dict; (void)key; return NULL;
}
void dict_set(Dict *dict, const char *key, double value) {
    (void)dict; (void)key; (void)value;
}

typedef struct Buffers {
    obs_t observations[POKEMON_SLICE_AGENTS][OBS_SIZE];
    float actions[POKEMON_SLICE_AGENTS];
    float rewards[POKEMON_SLICE_AGENTS];
    float terminals[POKEMON_SLICE_AGENTS];
    unsigned char masks[POKEMON_SLICE_AGENTS][POKEMON_SLICE_ACTIONS];
} Buffers;

static uint64_t mix64(uint64_t value) {
    value ^= value >> 30;
    value *= UINT64_C(0xbf58476d1ce4e5b9);
    value ^= value >> 27;
    value *= UINT64_C(0x94d049bb133111eb);
    return value ^ (value >> 31);
}

static uint64_t hash_bytes(uint64_t hash, const void *data, size_t size) {
    const unsigned char *bytes = data;
    for (size_t index = 0; index < size; index++) {
        hash ^= bytes[index];
        hash *= UINT64_C(1099511628211);
    }
    return hash;
}

static double monotonic_seconds(void) {
    struct timespec value;
    assert(clock_gettime(CLOCK_MONOTONIC, &value) == 0);
    return (double)value.tv_sec + (double)value.tv_nsec / 1000000000.0;
}

static size_t resident_bytes(void) {
#if defined(__APPLE__)
    mach_task_basic_info_data_t info;
    mach_msg_type_number_t count = MACH_TASK_BASIC_INFO_COUNT;
    assert(task_info(mach_task_self(), MACH_TASK_BASIC_INFO,
        (task_info_t)&info, &count) == KERN_SUCCESS);
    return (size_t)info.resident_size;
#elif defined(__linux__)
    FILE *file = fopen("/proc/self/statm", "r");
    unsigned long total_pages = 0, resident_pages = 0;
    assert(file != NULL);
    assert(fscanf(file, "%lu %lu", &total_pages, &resident_pages) == 2);
    (void)total_pages;
    fclose(file);
    long page_size = sysconf(_SC_PAGESIZE);
    assert(page_size > 0);
    return (size_t)resident_pages * (size_t)page_size;
#else
    return 0;
#endif
}

static void bind(PokemonSlice *env, Buffers *buffers) {
    memset(env, 0, sizeof(*env));
    for (size_t side = 0; side < POKEMON_SLICE_AGENTS; side++) {
        env->agents[side].observations = buffers->observations[side];
        env->agents[side].actions = &buffers->actions[side];
        env->agents[side].rewards = &buffers->rewards[side];
        env->agents[side].terminals = &buffers->terminals[side];
        env->agents[side].action_mask = buffers->masks[side];
    }
    puf_init(env, NULL);
}

static void configure(PokemonSlice *env, size_t index) {
    PokemonBattleInit init = pokemon_slice_default_init();
    uint64_t seed = mix64(UINT64_C(0x706f6b656d6f6e) + index);
    for (size_t word = 0; word < 4; word++) {
        init.seed[word] = (uint16_t)seed;
        seed = mix64(seed + word + 1);
    }
    assert(pokemon_slice_configure(env, &init) == POKEMON_OK);
    puf_reset(env);
}

static uint8_t policy_rank(size_t env, size_t side, uint64_t step) {
    uint64_t key = UINT64_C(0x9e3779b97f4a7c15) * (env + 1);
    key ^= UINT64_C(0xd1b54a32d192ed03) * (side + 1);
    key ^= UINT64_C(0x94d049bb133111eb) * (step + 1);
    return (uint8_t)mix64(key);
}

static float choose_legal(const unsigned char *mask, uint8_t rank) {
    unsigned int count = 0;
    for (size_t action = 0; action < POKEMON_SLICE_ACTIONS; action++)
        count += mask[action] != 0;
    if (count == 0) return 0.0f;
    unsigned int wanted = (unsigned int)rank % count;
    for (size_t action = 0; action < POKEMON_SLICE_ACTIONS; action++)
        if (mask[action] && wanted-- == 0) return (float)action;
    assert(0 && "legal action rank must resolve");
    return 0.0f;
}

static uint64_t digest_outputs(uint64_t digest, const PokemonSlice *env,
        const Buffers *buffers) {
    digest = hash_bytes(digest, &env->log, sizeof(env->log));
    for (size_t side = 0; side < POKEMON_SLICE_AGENTS; side++) {
        digest = hash_bytes(digest, buffers->observations[side],
            sizeof(buffers->observations[side]));
        digest = hash_bytes(digest, buffers->masks[side],
            sizeof(buffers->masks[side]));
        digest = hash_bytes(digest, &buffers->rewards[side], sizeof(float));
        digest = hash_bytes(digest, &buffers->terminals[side], sizeof(float));
    }
    return digest;
}

static uint64_t step_one(PokemonSlice *env, Buffers *buffers, size_t index,
        uint64_t step, uint64_t digest) {
    for (size_t side = 0; side < POKEMON_SLICE_AGENTS; side++)
        buffers->actions[side] = choose_legal(buffers->masks[side],
            policy_rank(index, side, step));
    puf_step(env);
    digest = digest_outputs(digest, env, buffers);
    if (buffers->terminals[0] != 0.0f) puf_reset(env);
    return digest;
}

static uint64_t run_probe(void) {
    PokemonSlice env;
    Buffers buffers = {0};
    bind(&env, &buffers);
    configure(&env, 0);
    uint64_t digest = UINT64_C(1469598103934665603);
    for (uint64_t step = 0; step < 64; step++)
        digest = step_one(&env, &buffers, 0, step, digest);
    puf_close(&env);
    return digest;
}

static int compare_double(const void *left, const void *right) {
    double a = *(const double *)left, b = *(const double *)right;
    return (a > b) - (a < b);
}

static double percentile(double *values, size_t count, double fraction) {
    qsort(values, count, sizeof(*values), compare_double);
    size_t index = (size_t)ceil(fraction * (double)count);
    if (index == 0) index = 1;
    return values[index - 1];
}

int main(void) {
    uint64_t probe = run_probe();
    assert(probe == run_probe());

    PokemonSlice scalar;
    Buffers scalar_buffers = {0};
    bind(&scalar, &scalar_buffers);
    configure(&scalar, 0);
    uint64_t scalar_digest = UINT64_C(1469598103934665603);
    double scalar_start = monotonic_seconds();
    for (uint64_t step = 0; step < SCALAR_STEPS; step++)
        scalar_digest = step_one(&scalar, &scalar_buffers, 0, step, scalar_digest);
    double scalar_rate = SCALAR_STEPS / (monotonic_seconds() - scalar_start);
    puf_close(&scalar);

    PokemonSlice *envs = calloc(ENV_COUNT, sizeof(*envs));
    Buffers *buffers = calloc(ENV_COUNT, sizeof(*buffers));
    assert(envs != NULL && buffers != NULL);
    memset(envs, 0xa5, ENV_COUNT * sizeof(*envs));
    memset(buffers, 0xa5, ENV_COUNT * sizeof(*buffers));
    size_t baseline_rss = resident_bytes();
    for (size_t env = 0; env < ENV_COUNT; env++) {
        bind(&envs[env], &buffers[env]);
        configure(&envs[env], env);
    }
    size_t initialized_rss = resident_bytes(), peak_rss = initialized_rss;
    uint64_t digest = UINT64_C(1469598103934665603), step = 0;
    for (; step < WARMUP_SWEEPS; step++)
        for (size_t env = 0; env < ENV_COUNT; env++)
            digest = step_one(&envs[env], &buffers[env], env, step, digest);

    double rates[MEASURED_REPETITIONS];
    double latencies[MEASURED_REPETITIONS * SWEEPS_PER_REPETITION];
    size_t latency_count = 0;
    for (size_t repetition = 0; repetition < MEASURED_REPETITIONS; repetition++) {
        double repetition_start = monotonic_seconds();
        for (size_t sweep = 0; sweep < SWEEPS_PER_REPETITION; sweep++, step++) {
            double start = monotonic_seconds();
            for (size_t env = 0; env < ENV_COUNT; env++)
                digest = step_one(&envs[env], &buffers[env], env, step, digest);
            latencies[latency_count++] = (monotonic_seconds() - start) * 1000.0;
            size_t rss = resident_bytes();
            if (rss > peak_rss) peak_rss = rss;
        }
        rates[repetition] = (double)(ENV_COUNT * SWEEPS_PER_REPETITION) /
            (monotonic_seconds() - repetition_start);
    }

    double sorted_rates[MEASURED_REPETITIONS];
    memcpy(sorted_rates, rates, sizeof(rates));
    double median_rate = percentile(sorted_rates, MEASURED_REPETITIONS, 0.5);
    double p99_latency = percentile(latencies, latency_count, 0.99);
    size_t incremental_rss = peak_rss > baseline_rss ? peak_rss - baseline_rss : 0;

    printf("{\n");
    printf("  \"workload\": \"native-gen3ou-default-2v2-hot-path\",\n");
    printf("  \"env_count\": %d,\n", ENV_COUNT);
    printf("  \"scalar_boundaries_per_second\": %.3f,\n", scalar_rate);
    printf("  \"batch_rates_boundaries_per_second\": [");
    for (size_t index = 0; index < MEASURED_REPETITIONS; index++)
        printf("%s%.3f", index == 0 ? "" : ", ", rates[index]);
    printf("],\n");
    printf("  \"batch_median_boundaries_per_second\": %.3f,\n", median_rate);
    printf("  \"batch_p99_sweep_latency_ms\": %.6f,\n", p99_latency);
    printf("  \"deterministic_digest\": \"%016" PRIx64 "\",\n", digest);
    printf("  \"self_check_digest\": \"%016" PRIx64 "\",\n", probe);
    printf("  \"scalar_digest\": \"%016" PRIx64 "\",\n", scalar_digest);
    printf("  \"sizeof_pokemon_slice_bytes\": %zu,\n", sizeof(PokemonSlice));
    printf("  \"sizeof_pokemon_battle_bytes\": %zu,\n", sizeof(PokemonBattle));
    printf("  \"sizeof_battle_init_bytes\": %zu,\n", sizeof(PokemonBattleInit));
    printf("  \"sizeof_battle_view_bytes\": %zu,\n", sizeof(PokemonBattleView));
    printf("  \"verifier_buffers_per_env_bytes\": %zu,\n", sizeof(Buffers));
    printf("  \"exact_env_and_io_bytes\": %zu,\n", sizeof(PokemonSlice) + sizeof(Buffers));
    printf("  \"rss_baseline_bytes\": %zu,\n", baseline_rss);
    printf("  \"rss_peak_bytes\": %zu,\n", peak_rss);
    printf("  \"incremental_rss_per_env_bytes\": %.3f\n",
        (double)incremental_rss / ENV_COUNT);
    printf("}\n");

    for (size_t env = 0; env < ENV_COUNT; env++) puf_close(&envs[env]);
    free(buffers);
    free(envs);
    return 0;
}
