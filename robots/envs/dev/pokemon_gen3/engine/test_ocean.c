#include <assert.h>
#include <stdio.h>
#include <string.h>

#include "../ocean/pokemon_gen3.h"

struct Dict { int unused; };

const char *dict_get_str(Dict *dict, const char *key) {
    (void)dict;
    (void)key;
    return NULL;
}

void dict_set(Dict *dict, const char *key, double value) {
    (void)dict;
    (void)key;
    (void)value;
}

static Gen3PokemonSet make_set(uint16_t species) {
    Gen3PokemonSet set = {0};
    set.abi_version = GEN3_ABI_VERSION;
    set.struct_size = sizeof(set);
    set.species_id = species;
    set.ability_id = GEN3_ABILITY_STURDY;
    set.level = 100;
    set.gender = 1;
    set.happiness = 255;
    for (size_t stat = 0; stat < 6; stat++) set.stats[stat] = (uint16_t)(200 + species);
    for (size_t move = 0; move < GEN3_MOVE_SLOTS; move++) {
        set.move_ids[move] = (uint16_t)(move + 1);
        set.max_pp[move] = 16;
    }
    return set;
}

static Gen3BattleInit make_init(void) {
    Gen3BattleInit init = {0};
    init.abi_version = GEN3_ABI_VERSION;
    init.struct_size = sizeof(init);
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        init.teams[side].abi_version = GEN3_ABI_VERSION;
        init.teams[side].struct_size = sizeof(init.teams[side]);
        for (size_t slot = 0; slot < GEN3_TEAM_SIZE; slot++) {
            init.teams[side].pokemon[slot] = make_set(
                (uint16_t)(side * GEN3_TEAM_SIZE + slot + 1)
            );
        }
    }
    return init;
}

int main(void) {
    PokemonGen3 env = {0};
    env.num_agents = POKEMON_GEN3_AGENTS;
    env.rng = 42;
    Gen3BattleInit init = make_init();
    assert(pokemon_gen3_configure(&env, &init) == GEN3_OK);

    obs_t observations[POKEMON_GEN3_AGENTS][OBS_SIZE] = {{0}};
    float actions[POKEMON_GEN3_AGENTS] = {0};
    float rewards[POKEMON_GEN3_AGENTS] = {0};
    float terminals[POKEMON_GEN3_AGENTS] = {0};
    unsigned char masks[POKEMON_GEN3_AGENTS][POKEMON_GEN3_ACTIONS] = {{0}};
    for (size_t side = 0; side < POKEMON_GEN3_AGENTS; side++) {
        env.agents[side].observations = observations[side];
        env.agents[side].actions = &actions[side];
        env.agents[side].rewards = &rewards[side];
        env.agents[side].terminals = &terminals[side];
        env.agents[side].action_mask = masks[side];
    }

    puf_reset(&env);
    assert(env.battle != NULL);
    assert(observations[0][3] == pokemon_gen3_ratio(1, GEN3_SPECIES_MAX_ID));
    assert(observations[1][3] == pokemon_gen3_ratio(7, GEN3_SPECIES_MAX_ID));
    for (size_t stat = 0; stat < GEN3_STAT_STAGE_COUNT; stat++) {
        assert(observations[0][11 + stat] == 0.5f);
        assert(observations[1][11 + stat] == 0.5f);
    }
    for (size_t side = 0; side < POKEMON_GEN3_AGENTS; side++) {
        for (size_t action = 0; action < POKEMON_GEN3_ACTIONS; action++) {
            assert(masks[side][action] == 1);
        }
    }

    actions[0] = 4;
    actions[1] = 8;
    puf_step(&env);
    Gen3BattleSnapshot snapshot;
    assert(gen3_battle_snapshot(env.battle, &snapshot) == GEN3_OK);
    assert(snapshot.turn == 2);
    assert(snapshot.pokemon[0][0].set.species_id == 2);
    assert(snapshot.pokemon[1][0].set.species_id == 12);
    assert(observations[0][3] == pokemon_gen3_ratio(2, GEN3_SPECIES_MAX_ID));
    assert(observations[1][3] == pokemon_gen3_ratio(12, GEN3_SPECIES_MAX_ID));
    assert(env.log.episode_length == 1.0f);

    puf_close(&env);
    assert(env.battle == NULL);
    puts("pokemon Gen 3 Ocean adapter tests passed");
    return 0;
}
