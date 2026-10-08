#include <stdlib.h>
#include <emscripten/emscripten.h>

#include ENV_HEADER

static obs_t observations[OBS_SIZE];
static float actions[NUM_ATNS];
static float rewards[1];
static float terminals[1];

int main(void) {
    Env* env = calloc(1, sizeof(Env));
    env->agents[0].observations = observations;
    env->agents[0].actions = actions;
    env->agents[0].rewards = rewards;
    env->agents[0].terminals = terminals;
    env->rng = (unsigned int)(emscripten_random() * 4294967295.0);
    Dict kwargs = {0};
    dict_set(&kwargs, "episode_length", 32);
    puf_init(env, &kwargs);
    puf_reset(env);
    while (1) {
        puf_render(env);
        rewards[0] = 0;
        terminals[0] = 0;
        puf_step(env);
    }
    return 0;
}
