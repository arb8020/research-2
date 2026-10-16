#include <emscripten/emscripten.h>

#include ENV_HEADER

obs_t observations[OBS_SIZE];
float actions[NUM_ATNS];
float rewards[1];
float terminals[1];
Env env = {.agents = {{
    .observations = observations,
    .actions = actions,
    .rewards = rewards,
    .terminals = terminals,
}}};

int main(void) {
    env.rng = emscripten_random() * 4294967295.0;
    Dict kwargs = {0};
    dict_set(&kwargs, "episode_length", 32);
    puf_init(&env, &kwargs);
    puf_reset(&env);
    while (1) {
        puf_render(&env);
        rewards[0] = 0;
        terminals[0] = 0;
        puf_step(&env);
    }
}
