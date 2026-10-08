// Generic ctypes-facing vectorizer over one PufferLib 5.0 CPU env.
// Compiled once per env: clang -DENV_HEADER=\"breakout/breakout.h\" ... -shared.
//
// Buffers are caller-owned (Python passes torch data_ptrs). Env i, agent 0 owns
// obs[i*OBS_SIZE..], actions[i*NUM_ATNS..], rewards[i], terminals[i].
// Contract mirrors pufferl.cu (env_setup / vec_log / worker loop):
//   - env->rng is set before puf_init (pufferl uses rng = env index; we mix in a seed).
//   - rewards/terminals are zeroed before every puf_step (envs may only write them
//     on events, e.g. breakout's destroy_brick does `rewards += points`).
//   - envs auto-reset inside puf_step; obs is post-reset on terminal steps.
//   - Log is a flat struct of floats; vec_log sums over envs, clears, divides by n.

#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include ENV_HEADER

_Static_assert(sizeof(obs_t) == sizeof(float), "shim expects float32 obs (PRECISION_FLOAT)");
_Static_assert(sizeof(Log) % sizeof(float) == 0, "Log must be a flat struct of floats");
_Static_assert(NUM_ATNS == 1, "shim supports one action head");

static const int act_sizes[] = ACT_SIZES;

typedef struct {
    int num_envs;
    Env* envs;
    float* rewards;
    float* terminals;
    unsigned char* action_mask;
} Vec;

int vec_obs_size(void) { return OBS_SIZE; }
int vec_num_atns(void) { return NUM_ATNS; }
int vec_num_actions(void) { return act_sizes[0]; }

// splitmix64 finalizer: distinct, decorrelated rand_r states per (seed, env).
static unsigned int env_rng(unsigned int seed, int i) {
    uint64_t z = ((uint64_t)seed << 32 | (uint32_t)i) + 0x9E3779B97F4A7C15ull;
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ull;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBull;
    return (unsigned int)(z ^ (z >> 31));
}

// kwargs: "key=value;key=value". Values use upstream's ini parser (numbers,
// 1_000 separators, lists, strings).
static void parse_kwargs(Dict* out, const char* kwargs) {
    char* buf = dict_strdup(kwargs);
    for (char* tok = strtok(buf, ";"); tok; tok = strtok(NULL, ";")) {
        char* eq = strchr(tok, '=');
        assert(eq && "kwargs entries must be key=value");
        *eq = 0;
        puf_ini_set(out, puf_ini_trim(tok), puf_ini_trim(eq + 1));
    }
    free(buf);
}

void* vec_create(int num_envs, const char* kwargs, unsigned int seed,
        float* obs, float* actions, float* rewards, float* terminals) {
    Dict dict = {0};
    parse_kwargs(&dict, kwargs);

    Vec* vec = (Vec*)calloc(1, sizeof(Vec));
    vec->num_envs = num_envs;
    vec->envs = (Env*)calloc(num_envs, sizeof(Env));
    vec->rewards = rewards;
    vec->terminals = terminals;
    vec->action_mask = (unsigned char*)malloc((size_t)num_envs * act_sizes[0]);
    memset(vec->action_mask, 1, (size_t)num_envs * act_sizes[0]);

    // OpenMP would go here and in vec_reset/vec_step: `#pragma omp parallel for`.
    for (int i = 0; i < num_envs; i++) {
        Env* env = &vec->envs[i];
        env->rng = env_rng(seed, i);
        puf_init(env, &dict);
        if (env->num_agents != 1) {
            fprintf(stderr, "shim: env reports num_agents=%d; only 1 is supported\n",
                env->num_agents);
            abort();
        }
        Agent* a = &env->agents[0];
        a->observations = obs + (size_t)i * OBS_SIZE;
        a->actions = actions + (size_t)i * NUM_ATNS;
        a->rewards = rewards + i;
        a->terminals = terminals + i;
        a->action_mask = vec->action_mask + (size_t)i * act_sizes[0];
    }
    dict_clear(&dict);
    return vec;
}

void vec_reset(void* handle, unsigned int seed) {
    Vec* vec = (Vec*)handle;
    memset(vec->rewards, 0, vec->num_envs * sizeof(float));
    memset(vec->terminals, 0, vec->num_envs * sizeof(float));
    for (int i = 0; i < vec->num_envs; i++) {
        vec->envs[i].rng = env_rng(seed, i);
        puf_reset(&vec->envs[i]);
    }
}

void vec_step(void* handle) {
    Vec* vec = (Vec*)handle;
    memset(vec->rewards, 0, vec->num_envs * sizeof(float));
    memset(vec->terminals, 0, vec->num_envs * sizeof(float));
    for (int i = 0; i < vec->num_envs; i++) {
        puf_step(&vec->envs[i]);
    }
}

// Writes "key=value\n" lines (episode means over all finished episodes since the
// last call, plus n = episode count) into out, then clears env logs. Returns bytes
// written, or -1 (logs kept) if cap is too small.
int vec_log(void* handle, char* out, int cap) {
    Vec* vec = (Vec*)handle;
    const int nf = sizeof(Log) / sizeof(float);
    Log sum = {0};
    float* acc = (float*)&sum;
    for (int i = 0; i < vec->num_envs; i++) {
        float* el = (float*)&vec->envs[i].log;
        for (int j = 0; j < nf; j++) {
            acc[j] += el[j];
        }
    }
    float n = sum.n;
    Dict dict = {0};
    if (n > 0.0f) {
        for (int j = 0; j < nf; j++) {
            acc[j] /= n;
        }
        puf_log(&sum, &dict);
    }
    dict_set(&dict, "n", n);
    int len = 0;
    for (int i = 0; i < dict.size; i++) {
        int w = snprintf(out + len, cap - len, "%s=%.17g\n",
            dict.items[i].key, dict.items[i].value);
        if (w < 0 || w >= cap - len) {
            dict_clear(&dict);
            return -1;
        }
        len += w;
    }
    dict_clear(&dict);
    for (int i = 0; i < vec->num_envs; i++) {
        memset(&vec->envs[i].log, 0, sizeof(Log));
    }
    return len;
}

void vec_close(void* handle) {
    Vec* vec = (Vec*)handle;
    for (int i = 0; i < vec->num_envs; i++) {
        puf_close(&vec->envs[i]);
    }
    free(vec->action_mask);
    free(vec->envs);
    free(vec);
}
