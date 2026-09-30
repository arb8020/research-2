#pragma once

typedef struct Dict Dict;
typedef struct Env Env;
typedef struct Log Log;
typedef struct {
    obs_t *observations;
    float *actions;
    float *rewards;
    float *terminals;
    unsigned char *action_mask;
    int policy;
} Agent;

const char *dict_get_str(Dict *dict, const char *key);
void dict_set(Dict *dict, const char *key, double value);
