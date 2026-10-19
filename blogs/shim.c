#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include ENV_HEADER

#define VEC_LOG_CAP_TOO_SMALL (-1)

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

static unsigned int env_rng(unsigned int seed, int i) {
    uint64_t z = ((uint64_t)seed << 32 | (uint32_t)i) + 0x9E3779B97F4A7C15ull;
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ull;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBull;
    return (unsigned int)(z ^ (z >> 31));
}

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
            return VEC_LOG_CAP_TOO_SMALL;
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
