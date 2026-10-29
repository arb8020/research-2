#pragma once

#include <assert.h>
#include <stdint.h>
#include <string.h>

#include "../native/gen3_rules.h"
#include "../native/gen3_slice_data.h"
#include "../native/pokemon.h"
#include "../native/singles2.h"

typedef float obs_t;
#include "pufferenv.h"

#define POKEMON_SLICE_AGENTS 2
#define POKEMON_SLICE_ACTIONS 10
#define POKEMON_SLICE_POKEMON_OBS 13
#define OBS_SIZE (3 + POKEMON_SIDES * POKEMON_TEAM_CAPACITY * POKEMON_SLICE_POKEMON_OBS)
#define ACT_SIZES {POKEMON_SLICE_ACTIONS}
#define NUM_ATNS 1

typedef struct Log Log;
struct Log { float episode_return; float episode_length; float score; float perf; float n; };

struct Env {
    Log log;
    int num_agents;
    unsigned int rng;
    Agent agents[POKEMON_SLICE_AGENTS];
    int tag;
    int boundary_reached;
    uint32_t episode;
    PokemonBattleInit initial;
    PokemonBattle battle;
};
typedef Env PokemonSlice;

static PokemonSet pokemon_slice_set(
    uint16_t species, uint16_t move, uint16_t hp, uint16_t attack,
    uint16_t defense, uint16_t special_attack, uint16_t special_defense,
    uint16_t speed
) {
    return (PokemonSet){.species_id = species, .move_ids = {move, 0, 0, 0},
        .stats = {hp, attack, defense, special_attack, special_defense, speed},
        .level = 100, .gender = POKEMON_GENDER_MALE};
}

static PokemonBattleInit pokemon_slice_default_init(void) {
    PokemonBattleInit init = {0};
    init.bundle = &POKEMON_GEN3_OU_BUNDLE;
    init.team_sizes[0] = init.team_sizes[1] = 2;
    for (size_t word = 0; word < 4; word++) init.seed[word] = (uint16_t)(word + 1);
    init.teams[0].members[0] = pokemon_slice_set(POKEMON_GEN3_SPECIES_PERSIAN,
        POKEMON_GEN3_MOVE_QUICKATTACK, 300, 200, 150, 150, 150, 300);
    init.teams[0].members[1] = pokemon_slice_set(POKEMON_GEN3_SPECIES_ALAKAZAM,
        POKEMON_GEN3_MOVE_THIEF, 250, 100, 100, 350, 200, 320);
    init.teams[1].members[0] = pokemon_slice_set(POKEMON_GEN3_SPECIES_BANETTE,
        POKEMON_GEN3_MOVE_THIEF, 50, 150, 100, 100, 100, 100);
    init.teams[1].members[1] = pokemon_slice_set(POKEMON_GEN3_SPECIES_MACHOP,
        POKEMON_GEN3_MOVE_STRENGTH, 50, 100, 80, 50, 50, 80);
    return init;
}

static int pokemon_slice_configure(PokemonSlice *env, const PokemonBattleInit *init) {
    if (env == NULL || init == NULL) return POKEMON_INVALID_ARGUMENT;
    PokemonBattle validation;
    int result = pokemon_battle_init(&validation, init);
    if (result == POKEMON_OK) env->initial = *init;
    return result;
}

static uint32_t pokemon_slice_mix_seed(uint32_t value) {
    value ^= value >> 16;
    value *= UINT32_C(0x7feb352d);
    value ^= value >> 15;
    value *= UINT32_C(0x846ca68b);
    return value ^ (value >> 16);
}

static void pokemon_slice_reset_episode(PokemonSlice *env, int advance_seed) {
    PokemonBattleInit init = env->initial;
    if (advance_seed) {
        uint32_t value = env->rng + UINT32_C(0x9e3779b9) * ++env->episode;
        for (size_t word = 0; word < 4; word++) {
            value = pokemon_slice_mix_seed(value + (uint32_t)word);
            init.seed[word] = (uint16_t)value;
        }
    }
    assert(pokemon_battle_init(&env->battle, &init) == POKEMON_OK);
    env->boundary_reached = 0;
}

static float pokemon_slice_ratio(uint32_t value, uint32_t maximum) {
    return maximum == 0 ? 0.0f : (float)value / (float)maximum;
}

static void pokemon_slice_encode_member(obs_t *out, const PokemonSide *side, size_t slot) {
    const PokemonSet *set = &side->sets[slot];
    const PokemonMutable *state = &side->state[slot];
    size_t index = 0;
    out[index++] = pokemon_slice_ratio(set->species_id, UINT16_MAX);
    out[index++] = pokemon_slice_ratio(state->hp, set->stats[0]);
    out[index++] = (float)state->fainted;
    out[index++] = (float)(side->active == slot);
    out[index++] = pokemon_slice_ratio(set->happiness, 255);
    for (size_t move = 0; move < POKEMON_MOVE_CAPACITY; move++) {
        out[index++] = pokemon_slice_ratio(state->move_ids[move], UINT16_MAX);
        out[index++] = pokemon_slice_ratio(state->pp[move], UINT8_MAX);
    }
    assert(index == POKEMON_SLICE_POKEMON_OBS);
}

static void pokemon_slice_publish(PokemonSlice *env) {
    const PokemonBattle *battle = &env->battle;
    PokemonRequest request = pokemon_battle_request(battle);
    for (size_t viewer = 0; viewer < POKEMON_SIDES; viewer++) {
        Agent *agent = &env->agents[viewer];
        size_t index = 0;
        agent->observations[index++] = pokemon_slice_ratio(battle->turn, UINT32_MAX);
        agent->observations[index++] = pokemon_slice_ratio(
            request.kind[viewer], POKEMON_REQUEST_TERMINAL);
        agent->observations[index++] = (float)battle->terminal;
        for (size_t relative = 0; relative < POKEMON_SIDES; relative++) {
            size_t side = relative == 0 ? viewer : 1u - viewer;
            for (size_t slot = 0; slot < POKEMON_TEAM_CAPACITY; slot++) {
                pokemon_slice_encode_member(&agent->observations[index],
                    &battle->sides[side], slot);
                index += POKEMON_SLICE_POKEMON_OBS;
            }
        }
        assert(index == OBS_SIZE);
        memset(agent->action_mask, 0, POKEMON_SLICE_ACTIONS);
        for (size_t move = 0; move < POKEMON_MOVE_CAPACITY; move++)
            agent->action_mask[move] =
                (uint8_t)((request.legal_moves[viewer] >> move) & 1u);
        for (size_t slot = 0; slot < POKEMON_TEAM_CAPACITY; slot++)
            agent->action_mask[POKEMON_MOVE_CAPACITY + slot] =
                (uint8_t)((request.legal_switches[viewer] >> slot) & 1u);
        if (battle->terminal) {
            agent->terminals[0] = 1.0f;
            agent->rewards[0] = battle->winner < 0 ? 0.0f :
                (battle->winner == (int8_t)viewer ? 1.0f : -1.0f);
        }
    }
}

static PokemonChoice pokemon_slice_choice(const PokemonRequest *request, size_t side, float raw) {
    if (request->kind[side] == POKEMON_REQUEST_WAIT)
        return (PokemonChoice){POKEMON_CHOICE_NONE, 0};
    int action = (int)raw;
    assert(raw == (float)action && action >= 0 && action < POKEMON_SLICE_ACTIONS);
    if ((unsigned int)action < POKEMON_MOVE_CAPACITY)
        return (PokemonChoice){POKEMON_CHOICE_MOVE, (uint8_t)action};
    return (PokemonChoice){POKEMON_CHOICE_SWITCH,
        (uint8_t)(action - POKEMON_MOVE_CAPACITY)};
}

void puf_init(PokemonSlice *env, Dict *kwargs) {
    (void)kwargs;
    assert(env != NULL);
    env->num_agents = POKEMON_SLICE_AGENTS;
    for (size_t side = 0; side < POKEMON_SIDES; side++) env->agents[side].policy = 0;
    PokemonBattleInit init = pokemon_slice_default_init();
    assert(pokemon_slice_configure(env, &init) == POKEMON_OK);
}

void puf_reset(PokemonSlice *env) {
    env->episode = 0;
    pokemon_slice_reset_episode(env, 0);
    env->log = (Log){0};
    for (size_t side = 0; side < POKEMON_SIDES; side++) {
        env->agents[side].rewards[0] = 0.0f;
        env->agents[side].terminals[0] = 0.0f;
    }
    pokemon_slice_publish(env);
}

void puf_step(PokemonSlice *env) {
    PokemonRequest request = pokemon_battle_request(&env->battle);
    PokemonChoice choices[POKEMON_SIDES];
    for (size_t side = 0; side < POKEMON_SIDES; side++) {
        env->agents[side].rewards[0] = 0.0f;
        env->agents[side].terminals[0] = 0.0f;
        choices[side] = pokemon_slice_choice(&request, side, env->agents[side].actions[0]);
    }
    assert(pokemon_battle_step(&env->battle, choices) == POKEMON_OK);
    env->boundary_reached++;
    if (!env->battle.terminal) {
        pokemon_slice_publish(env);
        return;
    }
    int8_t winner = env->battle.winner;
    float rewards[POKEMON_SIDES];
    for (size_t side = 0; side < POKEMON_SIDES; side++)
        rewards[side] = winner < 0 ? 0.0f :
            (winner == (int8_t)side ? 1.0f : -1.0f);
    env->log.episode_return += rewards[0];
    env->log.episode_length += (float)env->boundary_reached;
    env->log.score += rewards[0];
    env->log.perf += (rewards[0] + 1.0f) * 0.5f;
    env->log.n += 1.0f;
    pokemon_slice_reset_episode(env, 1);
    pokemon_slice_publish(env);
    for (size_t side = 0; side < POKEMON_SIDES; side++) {
        env->agents[side].rewards[0] = rewards[side];
        env->agents[side].terminals[0] = 1.0f;
    }
}

void puf_log(Log *log, Dict *out) {
    dict_set(out, "episode_return", log->episode_return);
    dict_set(out, "episode_length", log->episode_length);
    dict_set(out, "score", log->score);
    dict_set(out, "perf", log->perf);
    dict_set(out, "n", log->n);
}
void puf_render(PokemonSlice *env) { (void)env; }
void puf_close(PokemonSlice *env) { (void)env; }
