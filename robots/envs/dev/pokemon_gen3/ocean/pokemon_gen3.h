#pragma once

#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "../engine/gen3_abi.h"
#include "../engine/data_gen3.h"

typedef float obs_t;
#include "pufferenv.h"

#define POKEMON_GEN3_AGENTS 2
#define POKEMON_GEN3_ACTIONS 9
#define POKEMON_GEN3_POKEMON_OBS 30
#define OBS_SIZE (3 + GEN3_SIDE_COUNT * GEN3_TEAM_SIZE * POKEMON_GEN3_POKEMON_OBS)
#define ACT_SIZES {POKEMON_GEN3_ACTIONS}
#define NUM_ATNS 1

typedef struct Log Log;
struct Log {
    float episode_return;
    float episode_length;
    float n;
};

struct Env {
    Log log;
    int num_agents;
    unsigned int rng;
    Agent agents[POKEMON_GEN3_AGENTS];
    int tag;
    int boundary_reached;

    Gen3BattleInit initial;
    Gen3Battle *battle;
    uint32_t episode;
};

typedef Env PokemonGen3;

static float pokemon_gen3_ratio(uint32_t value, uint32_t maximum) {
    assert(maximum > 0);
    return (float)value / (float)maximum;
}

static void pokemon_gen3_encode_pokemon(
    obs_t *out, const Gen3PokemonSnapshot *pokemon, int active
) {
    const Gen3PokemonSet *set = &pokemon->set;
    size_t index = 0;
    out[index++] = pokemon_gen3_ratio(set->species_id, GEN3_SPECIES_MAX_ID);
    out[index++] = pokemon_gen3_ratio(set->item_id, GEN3_ITEM_MAX_ID);
    out[index++] = pokemon_gen3_ratio(set->ability_id, GEN3_ABILITY_MAX_ID);
    out[index++] = pokemon_gen3_ratio(pokemon->hp, set->stats[0]);
    out[index++] = pokemon_gen3_ratio(pokemon->status, 7);
    out[index++] = pokemon_gen3_ratio(pokemon->protect_counter, 8);
    out[index++] = pokemon_gen3_ratio(pokemon->toxic_counter, 15);
    out[index++] = (float)pokemon->leech_seeded;
    for (size_t stat = 0; stat < GEN3_STAT_STAGE_COUNT; stat++) {
        assert(pokemon->stat_stages[stat] >= -6 && pokemon->stat_stages[stat] <= 6);
        out[index++] = (float)(pokemon->stat_stages[stat] + 6) / 12.0f;
    }
    out[index++] = (float)active;
    out[index++] = pokemon_gen3_ratio(set->level, 100);
    out[index++] = pokemon_gen3_ratio(set->gender, 2);
    for (size_t stat = 0; stat < 6; stat++) {
        out[index++] = pokemon_gen3_ratio(set->stats[stat], UINT16_MAX);
    }
    for (size_t move = 0; move < GEN3_MOVE_SLOTS; move++) {
        out[index++] = pokemon_gen3_ratio(set->move_ids[move], GEN3_MOVE_MAX_ID);
        out[index++] = set->max_pp[move] == 0 ? 0.0f :
            pokemon_gen3_ratio(pokemon->pp[move], set->max_pp[move]);
    }
    assert(index == POKEMON_GEN3_POKEMON_OBS);
}

static void pokemon_gen3_publish(PokemonGen3 *env) {
    Gen3BattleSnapshot snapshot;
    int result = gen3_battle_snapshot(env->battle, &snapshot);
    assert(result == GEN3_OK);
    for (size_t viewer = 0; viewer < GEN3_SIDE_COUNT; viewer++) {
        obs_t *obs = env->agents[viewer].observations;
        assert(obs != NULL);
        size_t index = 0;
        obs[index++] = pokemon_gen3_ratio(snapshot.turn, UINT32_MAX);
        obs[index++] = pokemon_gen3_ratio(snapshot.spikes[viewer], 3);
        obs[index++] = pokemon_gen3_ratio(snapshot.spikes[1 - viewer], 3);
        for (size_t relative_side = 0; relative_side < GEN3_SIDE_COUNT; relative_side++) {
            size_t side = relative_side == 0 ? viewer : 1 - viewer;
            for (size_t slot = 0; slot < GEN3_TEAM_SIZE; slot++) {
                pokemon_gen3_encode_pokemon(
                    &obs[index], &snapshot.pokemon[side][slot], slot == 0
                );
                index += POKEMON_GEN3_POKEMON_OBS;
            }
        }
        assert(index == OBS_SIZE);

        uint16_t mask = 0;
        result = gen3_battle_legal_actions(env->battle, (uint8_t)viewer, &mask);
        assert(result == GEN3_OK);
        assert(env->agents[viewer].action_mask != NULL);
        for (size_t action = 0; action < POKEMON_GEN3_ACTIONS; action++) {
            env->agents[viewer].action_mask[action] = (uint8_t)((mask >> action) & 1u);
        }
        if (snapshot.done) {
            env->agents[viewer].terminals[0] = 1.0f;
            env->agents[viewer].rewards[0] =
                snapshot.winner_side == (int8_t)viewer ? 1.0f : -1.0f;
        }
    }
}

/* Testable configuration boundary. The caller retains no storage ownership. */
static int pokemon_gen3_configure(PokemonGen3 *env, const Gen3BattleInit *initial) {
    if (env == NULL || initial == NULL) return GEN3_INVALID_ARGUMENT;
    Gen3Battle *validation = NULL;
    int result = gen3_battle_create(initial, &validation, NULL, 0);
    if (result != GEN3_OK) return result;
    gen3_battle_destroy(validation);
    memcpy(&env->initial, initial, sizeof(env->initial));
    return GEN3_OK;
}

void puf_init(PokemonGen3 *env, Dict *kwargs) {
    assert(env != NULL);
    env->num_agents = POKEMON_GEN3_AGENTS;
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        env->agents[side].policy = (int)side;
        env->agents[side].action_mask = NULL;
    }
    const char *path = dict_get_str(kwargs, "battle_init_path");
    if (path == NULL || path[0] == '\0') {
        fprintf(stderr, "missing required battle_init_path\n");
        abort();
    }
    FILE *file = fopen(path, "rb");
    if (file == NULL) {
        fprintf(stderr, "cannot open normalized Gen 3 battle init: %s\n", path);
        abort();
    }
    Gen3BattleInit initial;
    size_t count = fread(&initial, sizeof(initial), 1, file);
    int trailing = fgetc(file);
    fclose(file);
    if (count != 1 || trailing != EOF || pokemon_gen3_configure(env, &initial) != GEN3_OK) {
        fprintf(stderr, "invalid normalized Gen 3 battle init: %s\n", path);
        abort();
    }
}

void puf_reset(PokemonGen3 *env) {
    gen3_battle_destroy(env->battle);
    env->battle = NULL;
    Gen3BattleInit initial = env->initial;
    uint32_t value = env->rng + UINT32_C(0x9E3779B9) * ++env->episode;
    for (size_t word = 0; word < 4; word++) {
        value ^= value >> 16;
        value *= UINT32_C(0x7FEB352D);
        value ^= value >> 15;
        value *= UINT32_C(0x846CA68B);
        value ^= value >> 16;
        initial.seed[word] = (uint16_t)value;
        value += UINT32_C(0x9E3779B9);
    }
    int result = gen3_battle_create(&initial, &env->battle, NULL, 0);
    assert(result == GEN3_OK);
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        env->agents[side].rewards[0] = 0.0f;
        env->agents[side].terminals[0] = 0.0f;
    }
    pokemon_gen3_publish(env);
}

void puf_step(PokemonGen3 *env) {
    int8_t actions[GEN3_SIDE_COUNT];
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t legal = 0;
        int result = gen3_battle_legal_actions(env->battle, (uint8_t)side, &legal);
        assert(result == GEN3_OK);
        if (legal == 0) {
            actions[side] = -1;
            env->agents[side].rewards[0] = 0.0f;
            env->agents[side].terminals[0] = 0.0f;
            continue;
        }
        float raw = env->agents[side].actions[0];
        int action = (int)raw;
        if (raw != (float)action || action < 0 || action >= POKEMON_GEN3_ACTIONS) {
            fprintf(stderr, "invalid Gen 3 action for side %zu: %.9g\n", side, raw);
            abort();
        }
        actions[side] = (int8_t)action;
        env->agents[side].rewards[0] = 0.0f;
        env->agents[side].terminals[0] = 0.0f;
    }
    int result = gen3_battle_turn(env->battle, actions[0], actions[1]);
    if (result != GEN3_OK) {
        fprintf(stderr, "Gen 3 engine rejected decision boundary (%d): %d, %d\n",
            result, actions[0], actions[1]);
        abort();
    }
    env->log.episode_length += 1.0f;
    pokemon_gen3_publish(env);
}

void puf_log(Log *log, Dict *out) {
    dict_set(out, "episode_return", log->episode_return);
    dict_set(out, "episode_length", log->episode_length);
    dict_set(out, "n", log->n);
}

void puf_render(PokemonGen3 *env) {
    (void)env;
}

void puf_close(PokemonGen3 *env) {
    gen3_battle_destroy(env->battle);
    env->battle = NULL;
}
