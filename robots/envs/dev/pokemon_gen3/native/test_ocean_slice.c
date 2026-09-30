#include <assert.h>
#include <stdio.h>
#include "../ocean/pokemon_slice.h"

struct Dict { int unused; };
const char *dict_get_str(Dict *dict, const char *key) {(void)dict; (void)key; return NULL;}
void dict_set(Dict *dict, const char *key, double value) {(void)dict; (void)key; (void)value;}

int main(void) {
    PokemonSlice env = {0};
    obs_t observations[2][OBS_SIZE] = {{0}};
    float actions[2] = {0}, rewards[2] = {0}, terminals[2] = {0};
    unsigned char masks[2][POKEMON_SLICE_ACTIONS] = {{0}};
    for (size_t side = 0; side < 2; side++) {
        env.agents[side].observations = observations[side];
        env.agents[side].actions = &actions[side];
        env.agents[side].rewards = &rewards[side];
        env.agents[side].terminals = &terminals[side];
        env.agents[side].action_mask = masks[side];
    }
    puf_init(&env, NULL);
    assert(env.agents[0].policy == 0 && env.agents[1].policy == 0);
    PokemonBattleInit configured = pokemon_slice_default_init();
    configured.seed[3] = 9;
    assert(pokemon_slice_configure(&env, &configured) == POKEMON_OK);
    puf_reset(&env);
    PokemonBattle expected;
    assert(pokemon_battle_init(&expected, &configured) == POKEMON_OK);
    assert(memcmp(env.battle.seed, expected.seed, sizeof(expected.seed)) == 0);
    assert(observations[0][3] == pokemon_slice_ratio(POKEMON_GEN3_SPECIES_PERSIAN, UINT16_MAX));
    assert(observations[1][3] == pokemon_slice_ratio(POKEMON_GEN3_SPECIES_BANETTE, UINT16_MAX));
    assert(masks[0][0] == 1 && masks[0][5] == 1);
    actions[0] = 5;
    actions[1] = 0;
    puf_step(&env);
    assert(env.battle.sides[0].active == 1);
    assert(env.battle.sides[1].state[0].pp[0] == 15);
    assert(observations[0][3 + POKEMON_SLICE_POKEMON_OBS + 3] == 1.0f);
    assert(env.log.episode_length == 0.0f);
    assert(env.boundary_reached == 1);

    for (size_t decisions = 0; terminals[0] == 0.0f && decisions < 64; decisions++) {
        for (size_t side = 0; side < 2; side++) {
            actions[side] = 0;
            for (size_t action = 0; action < POKEMON_SLICE_ACTIONS; action++) {
                if (masks[side][action]) {
                    actions[side] = (float)action;
                    break;
                }
            }
        }
        puf_step(&env);
    }
    assert(terminals[0] == 1.0f && terminals[1] == 1.0f);
    assert(rewards[0] + rewards[1] == 0.0f);
    assert(!env.battle.terminal);
    assert(env.battle.turn == 1);
    assert(env.log.n == 1.0f && env.log.episode_length > 0.0f);
    assert(masks[0][0] == 1 && masks[1][0] == 1);
    actions[0] = actions[1] = 0.0f;
    puf_step(&env);
    assert(terminals[0] == 0.0f && terminals[1] == 0.0f);
    assert(rewards[0] == 0.0f && rewards[1] == 0.0f);

    env.battle.terminal = 1;
    env.battle.winner = -1;
    rewards[0] = rewards[1] = 7.0f;
    pokemon_slice_publish(&env);
    assert(terminals[0] == 1.0f && terminals[1] == 1.0f);
    assert(rewards[0] == 0.0f && rewards[1] == 0.0f);
    puf_close(&env);
    puts("Pokemon slice Ocean adapter tests passed");
    return 0;
}
