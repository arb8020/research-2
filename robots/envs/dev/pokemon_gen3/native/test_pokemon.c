#include "gen3_rules.h"
#include "gen3_slice_data.h"
#include "pokemon.h"
#include "singles2.h"
#include "test_plugin.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>

static PokemonSet make_set(
    uint16_t species, uint16_t move, uint16_t hp, uint16_t attack,
    uint16_t defense, uint16_t special_attack, uint16_t special_defense,
    uint16_t speed
) {
    PokemonSet set = {
        .species_id = species,
        .move_ids = {move, 0, 0, 0},
        .stats = {hp, attack, defense, special_attack, special_defense, speed},
        .level = 100,
        .gender = POKEMON_GENDER_MALE,
    };
    return set;
}

static PokemonBattleInit battle_init(void) {
    PokemonBattleInit init = {
        .bundle = &POKEMON_GEN3_OU_BUNDLE,
        .team_sizes = {2, 2},
        .seed = {1, 2, 3, 4},
    };
    init.teams[0].members[0] = make_set(
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_QUICKATTACK,
        300, 200, 150, 150, 150, 300
    );
    init.teams[0].members[1] = make_set(
        POKEMON_GEN3_SPECIES_ALAKAZAM, POKEMON_GEN3_MOVE_THIEF,
        250, 100, 100, 350, 200, 320
    );
    init.teams[1].members[0] = make_set(
        POKEMON_GEN3_SPECIES_BANETTE, POKEMON_GEN3_MOVE_THIEF,
        50, 150, 100, 100, 100, 100
    );
    init.teams[1].members[1] = make_set(
        POKEMON_GEN3_SPECIES_MACHOP, POKEMON_GEN3_MOVE_STRENGTH,
        50, 100, 80, 50, 50, 80
    );
    return init;
}

static PokemonChoice move(uint8_t slot) {
    return (PokemonChoice){POKEMON_CHOICE_MOVE, slot};
}

static PokemonChoice switch_to(uint8_t slot) {
    return (PokemonChoice){POKEMON_CHOICE_SWITCH, slot};
}

static PokemonChoice wait_choice(void) {
    return (PokemonChoice){POKEMON_CHOICE_NONE, 0};
}

static void test_replace_base_move(
    PokemonBattle *battle, size_t side, size_t team_slot, size_t move_slot,
    uint16_t move_id, uint8_t pp
) {
    const PokemonMoveData *move = NULL;
    for (size_t i = 0; i < battle->data->move_count; i++) {
        if (battle->data->moves[i].id == move_id) {
            move = &battle->data->moves[i];
            break;
        }
    }
    assert(move != NULL && pp <= move->pp);
    PokemonMutable *state = &battle->sides[side].state[team_slot];
    state->move_ids[move_slot] = move_id;
    state->pp[move_slot] = pp;
    state->max_pp[move_slot] = move->pp;
    state->base_move_ids[move_slot] = move_id;
    state->base_pp[move_slot] = pp;
    state->base_max_pp[move_slot] = move->pp;
    state->temporary_move_slots &= (uint8_t)~(1u << move_slot);
}

static void test_set_base_backed_pp(
    PokemonBattle *battle, size_t side, size_t team_slot, size_t move_slot,
    uint8_t pp
) {
    PokemonMutable *state = &battle->sides[side].state[team_slot];
    assert((state->temporary_move_slots & (1u << move_slot)) == 0);
    assert(pp <= state->max_pp[move_slot]);
    state->pp[move_slot] = pp;
    state->base_pp[move_slot] = pp;
}

static PokemonMoveData TEST_MOVE = {
    .id = 1,
    .type = 0,
    .category = POKEMON_CATEGORY_PHYSICAL,
    .power = 50,
    .accuracy = {POKEMON_ACCURACY_PERCENT, 100},
    .priority = 0,
    .raw_pp = 10,
    .pp = 16,
    .target = POKEMON_TARGET_NORMAL,
    .damage_formula = POKEMON_DAMAGE_STANDARD,
    .critical_stage = 1,
};

/* Synthetic handler-program tests intentionally replace the resolved handler
 * table. Remove the delegated-move capability coherently so those fixtures do
 * not construct a mixed plugin bundle. */
static void remove_move_call_capability(
    PokemonData *data, PokemonMoveData moves[POKEMON_GEN3_MOVE_COUNT]
) {
    assert(data->move_count == POKEMON_GEN3_MOVE_COUNT);
    memcpy(moves, data->moves,
        POKEMON_GEN3_MOVE_COUNT * sizeof(PokemonMoveData));
    for (size_t i = 0; i < POKEMON_GEN3_MOVE_COUNT; i++) {
        moves[i].call_pool_id = 0;
    }
    data->moves = moves;
    data->move_call_pools = NULL;
    data->move_call_pool_count = 0;
    data->move_call_pool_candidates = NULL;
    data->move_call_pool_candidate_count = 0;
    data->constructed_hit_templates = NULL;
    data->constructed_hit_template_count = 0;
    data->move_pre_use_programs = NULL;
    data->move_pre_use_program_count = 0;
}

static PokemonBattleInit condition_init(
    uint16_t species0, uint16_t move0, uint16_t species1, uint16_t move1
);
static size_t draw_label_count(
    const PokemonBattle *battle, PokemonDrawLabel label);
static size_t handler_event_count(
    const PokemonBattle *battle, PokemonEventId event);
static size_t event_kind_count(
    const PokemonBattle *battle, PokemonEventKind kind);
static size_t handler_id_count(
    const PokemonBattle *battle, uint16_t handler_id);
static int accuracy_protect_owned_state_equal(
    const PokemonBattle *left, const PokemonBattle *right);
static void assert_invalid_resolved_data_is_atomic(
    PokemonBattleInit init, const PokemonData *invalid_data);
static int test_volatile_index(
    const PokemonMutable *state, PokemonVolatileKind kind
) {
    for (size_t i = 0; i < state->volatile_count; i++) {
        if (state->volatiles[i].kind == kind) return (int)i;
    }
    return -1;
}

static void test_perish_song_generated_lifecycle(void) {
    PokemonChoice perish[POKEMON_SIDES] = {move(0), move(0)};
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_PERISHSONG,
        POKEMON_GEN3_SPECIES_BANETTE, POKEMON_GEN3_MOVE_PERISHSONG);
    init.team_sizes[0] = 1;
    init.team_sizes[1] = 1;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);

    /* The field callback admits both actives independently. The same-turn
     * residual decrements the generated duration-four descriptor to three. */
    assert(pokemon_battle_step(&battle, perish) == POKEMON_OK);
    for (size_t side = 0; side < POKEMON_SIDES; side++) {
        int index = test_volatile_index(
            &battle.sides[side].state[0], POKEMON_VOLATILE_COUNTDOWN_FAINT);
        assert(index >= 0);
        const PokemonVolatileState *condition =
            &battle.sides[side].state[0].volatiles[index];
        assert(condition->duration == 3);
        assert(condition->descriptor_id ==
            POKEMON_GEN3_CONDITION_VOLATILE_PERISHSONG);
        assert(condition->source_effect.kind == POKEMON_SOURCE_EFFECT_MOVE);
        assert(condition->source_effect.id == POKEMON_GEN3_MOVE_PERISHSONG);
    }
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 0);

    /* Reapplying when every active already has the volatile fails as a field
     * callback and, critically, does not restart either countdown. */
    assert(pokemon_battle_step(&battle, perish) == POKEMON_OK);
    for (size_t side = 0; side < POKEMON_SIDES; side++) {
        int index = test_volatile_index(
            &battle.sides[side].state[0], POKEMON_VOLATILE_COUNTDOWN_FAINT);
        assert(index >= 0);
        assert(battle.sides[side].state[0].volatiles[index].duration == 2);
    }
    assert(pokemon_battle_step(&battle, perish) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, perish) == POKEMON_OK);
    assert(battle.terminal);
    assert(battle.winner == -1);
    assert(battle.sides[0].state[0].fainted);
    assert(battle.sides[1].state[0].fainted);
    assert(handler_id_count(
        &battle, POKEMON_GEN3_HANDLER_PERISH_SONG_END) == 2);
    assert(pokemon_battle_check_invariants(&battle));

    /* Switching clears only the outgoing holder's volatile. Its peer keeps
     * counting down and requests replacement after expiry. */
    init = condition_init(
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_PERISHSONG,
        POKEMON_GEN3_SPECIES_BANETTE, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[0].members[1] = make_set(
        POKEMON_GEN3_SPECIES_ALAKAZAM, POKEMON_GEN3_MOVE_SPLASH,
        250, 100, 100, 350, 200, 320);
    init.teams[1].members[1] = make_set(
        POKEMON_GEN3_SPECIES_MACHOP, POKEMON_GEN3_MOVE_SPLASH,
        250, 100, 100, 100, 100, 80);
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    PokemonChoice install[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_step(&battle, install) == POKEMON_OK);
    PokemonChoice leave[POKEMON_SIDES] = {switch_to(1), move(0)};
    assert(pokemon_battle_step(&battle, leave) == POKEMON_OK);
    assert(test_volatile_index(
        &battle.sides[0].state[0], POKEMON_VOLATILE_COUNTDOWN_FAINT) < 0);
    assert(test_volatile_index(
        &battle.sides[0].state[1], POKEMON_VOLATILE_COUNTDOWN_FAINT) < 0);
    PokemonChoice splashes[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_step(&battle, splashes) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, splashes) == POKEMON_OK);
    assert(!battle.terminal);
    assert(battle.sides[1].state[0].fainted);
    assert(battle.request.kind[1] == POKEMON_REQUEST_SWITCH);
    assert(battle.request.kind[0] == POKEMON_REQUEST_WAIT);
    assert(pokemon_battle_check_invariants(&battle));

    /* Soundproof is banned by the pinned Gen 3 OU format, so its upstream
     * regression cannot be a legal differential case.  A constructed plugin
     * nevertheless proves the generic field callback honors an ability-owned
     * TryHit cancellation independently for each active. */
    enum { TEST_SOUNDPROOF = 62500, TEST_PERISH_FIELD = 62501,
        TEST_SOUNDPROOF_TRY_HIT = 62502 };
    PokemonAbilityData soundproof = {
        .id = TEST_SOUNDPROOF, .handler_offset = 1, .handler_count = 1,
    };
    PokemonHandlerOp programs[] = {
        {POKEMON_HANDLER_OP_APPLY_VOLATILE_TO_ADMITTED_ACTIVES,
            POKEMON_VOLATILE_COUNTDOWN_FAINT},
        {POKEMON_HANDLER_OP_RETURN_NULL, 0},
    };
    PokemonHandlerDescriptor handlers[] = {
        {
            .event = POKEMON_HANDLER_EVENT_MOVE_HIT_FIELD_CALLBACK,
            .id = TEST_PERISH_FIELD,
            .source_kind = POKEMON_HANDLER_SOURCE_MOVE,
            .source_id = POKEMON_GEN3_MOVE_PERISHSONG,
            .program_offset = 0, .program_count = 1,
            .scope = POKEMON_HANDLER_SCOPE_FIELD,
            .route = POKEMON_HANDLER_ROUTE_MOVE_SELF,
            .raw_hook = "synthetic.perishsong.onHitField",
        },
        {
            .event = POKEMON_HANDLER_EVENT_TRY_HIT,
            .id = TEST_SOUNDPROOF_TRY_HIT,
            .source_kind = POKEMON_HANDLER_SOURCE_ABILITY,
            .source_id = TEST_SOUNDPROOF,
            .program_offset = 1, .program_count = 1,
            .scope = POKEMON_HANDLER_SCOPE_TARGET,
            .route = POKEMON_HANDLER_ROUTE_OWNER,
            .raw_hook = "synthetic.soundproof.onTryHit",
        },
    };
    PokemonOwnerBindingIndex soundproof_binding = {
        .owner_kind = POKEMON_OWNER_ABILITY, .owner_id = TEST_SOUNDPROOF,
        .event = POKEMON_HANDLER_EVENT_TRY_HIT,
        .scope = POKEMON_HANDLER_SCOPE_TARGET,
        .route = POKEMON_HANDLER_ROUTE_OWNER,
        .binding_offset = 1, .binding_count = 1,
    };
    PokemonData data = POKEMON_GEN3_SLICE_DATA;
    PokemonMoveData moves[data.move_count];
    remove_move_call_capability(&data, moves);
    data.abilities = &soundproof; data.ability_count = 1;
    data.handlers = handlers; data.handler_count = 2;
    data.handler_programs = programs; data.handler_program_count = 2;
    data.owner_binding_index = &soundproof_binding;
    data.owner_binding_index_count = 1;
    PokemonResolvedBundle bundle = POKEMON_GEN3_OU_BUNDLE;
    PokemonFormatPolicy policy = *bundle.policy;
    policy.status_clauses = NULL;
    policy.status_clause_count = 0;
    bundle.policy = &policy;
    bundle.data = &data;
    init = condition_init(
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_PERISHSONG,
        POKEMON_GEN3_SPECIES_BANETTE, POKEMON_GEN3_MOVE_SPLASH);
    init.bundle = &bundle;
    init.team_sizes[0] = 1;
    init.team_sizes[1] = 1;
    init.teams[1].members[0].ability_id = TEST_SOUNDPROOF;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, install) == POKEMON_OK);
    assert(test_volatile_index(
        &battle.sides[0].state[0], POKEMON_VOLATILE_COUNTDOWN_FAINT) >= 0);
    assert(test_volatile_index(
        &battle.sides[1].state[0], POKEMON_VOLATILE_COUNTDOWN_FAINT) < 0);
    assert(event_kind_count(&battle, POKEMON_EVENT_IMMUNE) == 1);
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 0);
    assert(pokemon_battle_check_invariants(&battle));
}

static void test_generic_item_mutation_family(void) {
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};

    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_ALAKAZAM, POKEMON_GEN3_MOVE_THIEF,
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[1].members[0].item_id = POKEMON_GEN3_ITEM_BLACKBELT;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    uint16_t source_generation = battle.sides[0].state[0].item_generation;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].item_id == POKEMON_GEN3_ITEM_BLACKBELT);
    assert(battle.sides[0].state[0].item_generation == source_generation + 1);
    assert(battle.sides[0].state[0].item_effect_order != 0);
    assert(battle.sides[0].state[0].pending_staleness ==
        POKEMON_STALENESS_INTERNAL);
    assert(battle.sides[1].state[0].item_id == 0);
    assert(battle.sides[1].state[0].pending_staleness ==
        POKEMON_STALENESS_NONE);
    assert(battle.sides[1].state[0].last_item_id == 0);

    init = condition_init(
        POKEMON_GEN3_SPECIES_ALAKAZAM, POKEMON_GEN3_MOVE_COVET,
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[1].members[0].item_id = POKEMON_GEN3_ITEM_MAIL;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].item_id == POKEMON_GEN3_ITEM_MAIL);
    assert(battle.sides[0].state[0].pending_staleness ==
        POKEMON_STALENESS_INTERNAL);
    assert(battle.sides[1].state[0].item_id == 0);

    init = condition_init(
        POKEMON_GEN3_SPECIES_ALAKAZAM, POKEMON_GEN3_MOVE_KNOCKOFF,
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[1].members[0].item_id = POKEMON_GEN3_ITEM_BLACKBELT;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    uint16_t target_generation = battle.sides[1].state[0].item_generation;
    uint16_t target_order = battle.sides[1].state[0].item_effect_order;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].state[0].item_id == 0);
    assert(battle.sides[1].state[0].item_knocked_off == 1);
    assert(battle.sides[1].state[0].last_item_id == 0);
    /* Pinned Gen 3's direct Knock Off override deliberately leaves the old
     * installation object intact until switching replaces it. */
    assert(battle.sides[1].state[0].item_generation == target_generation);
    assert(battle.sides[1].state[0].item_effect_order == target_order);

    init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_STICKYHOLD;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].state[0].item_id == POKEMON_GEN3_ITEM_BLACKBELT);
    assert(battle.sides[1].state[0].item_knocked_off == 0);

    init = condition_init(
        POKEMON_GEN3_SPECIES_ALAKAZAM, POKEMON_GEN3_MOVE_RECYCLE,
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SPLASH);
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    battle.sides[0].state[0].last_item_id = POKEMON_GEN3_ITEM_ORANBERRY;
    source_generation = battle.sides[0].state[0].item_generation;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].item_id == POKEMON_GEN3_ITEM_ORANBERRY);
    assert(battle.sides[0].state[0].last_item_id == 0);
    assert(battle.sides[0].state[0].item_generation == source_generation + 1);
}

static void test_trick_item_swap_family(void) {
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_ALAKAZAM, POKEMON_GEN3_MOVE_TRICK,
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[0].members[0].item_id = POKEMON_GEN3_ITEM_ORANBERRY;
    init.teams[1].members[0].item_id = POKEMON_GEN3_ITEM_BLACKBELT;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    uint16_t source_generation = battle.sides[0].state[0].item_generation;
    uint16_t target_generation = battle.sides[1].state[0].item_generation;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].item_id == POKEMON_GEN3_ITEM_BLACKBELT);
    assert(battle.sides[1].state[0].item_id == POKEMON_GEN3_ITEM_ORANBERRY);
    assert(battle.sides[0].state[0].item_generation == source_generation + 2);
    assert(battle.sides[1].state[0].item_generation == target_generation + 2);
    assert(battle.sides[0].state[0].item_effect_order != 0);
    assert(battle.sides[1].state[0].item_effect_order != 0);

    /* Callback-free items are still executable identities. Generic item
     * transactions must be able to observe and move every legal identity
     * without manufacturing an item-specific handler. */
    const uint16_t passive_items[] = {
        POKEMON_GEN3_ITEM_MASTERBALL, POKEMON_GEN3_ITEM_ULTRABALL,
        POKEMON_GEN3_ITEM_GREATBALL, POKEMON_GEN3_ITEM_POKEBALL,
        POKEMON_GEN3_ITEM_NETBALL, POKEMON_GEN3_ITEM_DIVEBALL,
        POKEMON_GEN3_ITEM_NESTBALL, POKEMON_GEN3_ITEM_REPEATBALL,
        POKEMON_GEN3_ITEM_TIMERBALL, POKEMON_GEN3_ITEM_LUXURYBALL,
        POKEMON_GEN3_ITEM_PREMIERBALL, POKEMON_GEN3_ITEM_SUNSTONE,
        POKEMON_GEN3_ITEM_MOONSTONE, POKEMON_GEN3_ITEM_FIRESTONE,
        POKEMON_GEN3_ITEM_THUNDERSTONE, POKEMON_GEN3_ITEM_WATERSTONE,
        POKEMON_GEN3_ITEM_LEAFSTONE, POKEMON_GEN3_ITEM_ROOTFOSSIL,
        POKEMON_GEN3_ITEM_CLAWFOSSIL, POKEMON_GEN3_ITEM_HELIXFOSSIL,
        POKEMON_GEN3_ITEM_DOMEFOSSIL, POKEMON_GEN3_ITEM_OLDAMBER,
        POKEMON_GEN3_ITEM_DRAGONSCALE, POKEMON_GEN3_ITEM_UPGRADE,
        POKEMON_GEN3_ITEM_FRIENDBALL,
    };
    for (size_t i = 0; i < sizeof(passive_items) / sizeof(passive_items[0]); i++) {
        init.teams[0].members[0].item_id = POKEMON_GEN3_ITEM_ORANBERRY;
        init.teams[1].members[0].item_id = passive_items[i];
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        source_generation = battle.sides[0].state[0].item_generation;
        target_generation = battle.sides[1].state[0].item_generation;
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        assert(battle.sides[0].state[0].item_id == passive_items[i]);
        assert(battle.sides[1].state[0].item_id == POKEMON_GEN3_ITEM_ORANBERRY);
        assert(battle.sides[0].state[0].item_generation == source_generation + 2);
        assert(battle.sides[1].state[0].item_generation == target_generation + 2);
        assert(battle.sides[0].state[0].item_effect_order != 0);
        assert(battle.sides[1].state[0].item_effect_order != 0);
    }

    /* Either empty holder still forms a valid transfer; two empty holders do
     * not fabricate an installation. */
    init.teams[0].members[0].item_id = 0;
    init.teams[1].members[0].item_id = POKEMON_GEN3_ITEM_BLACKBELT;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].item_id == POKEMON_GEN3_ITEM_BLACKBELT);
    assert(battle.sides[1].state[0].item_id == 0);
    init.teams[1].members[0].item_id = 0;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].item_id == 0);
    assert(battle.sides[1].state[0].item_id == 0);

    /* Sticky Hold is move-owned TryImmunity after accuracy and before Hit. */
    init.teams[0].members[0].item_id = POKEMON_GEN3_ITEM_ORANBERRY;
    init.teams[1].members[0].item_id = POKEMON_GEN3_ITEM_BLACKBELT;
    init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_STICKYHOLD;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].item_id == POKEMON_GEN3_ITEM_ORANBERRY);
    assert(battle.sides[1].state[0].item_id == POKEMON_GEN3_ITEM_BLACKBELT);
    assert(battle.draws[0].label == POKEMON_DRAW_ACCURACY);
    assert(battle.draws[1].label == POKEMON_DRAW_END_TURN);

    /* Mail rejects Trick. If the first take already succeeded, Showdown's
     * failure rollback restores only that raw ID, not its old installation. */
    init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_LIMBER;
    init.teams[0].members[0].item_id = POKEMON_GEN3_ITEM_MAIL;
    target_generation = 0;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    target_generation = battle.sides[1].state[0].item_generation;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].item_id == POKEMON_GEN3_ITEM_MAIL);
    assert(battle.sides[1].state[0].item_id == POKEMON_GEN3_ITEM_BLACKBELT);
    assert(battle.sides[1].state[0].item_generation == target_generation + 1);
    assert(battle.sides[1].state[0].item_effect_order == 0);

    /* The Gen 3 knocked-off marker blocks either side's take and Protect
     * prevents the Hit program from running. */
    init.teams[0].members[0].item_id = POKEMON_GEN3_ITEM_ORANBERRY;
    init.teams[1].members[0].item_id = POKEMON_GEN3_ITEM_BLACKBELT;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    battle.sides[0].state[0].item_knocked_off = 1;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].item_id == POKEMON_GEN3_ITEM_ORANBERRY);
    assert(battle.sides[1].state[0].item_id == POKEMON_GEN3_ITEM_BLACKBELT);
    init.teams[1].members[0].move_ids[0] = POKEMON_GEN3_MOVE_PROTECT;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].item_id == POKEMON_GEN3_ITEM_ORANBERRY);
    assert(battle.sides[1].state[0].item_id == POKEMON_GEN3_ITEM_BLACKBELT);
}

static void test_generated_direct_half_heal_family(void) {
    static const uint16_t moves[] = {
        POKEMON_GEN3_MOVE_RECOVER, POKEMON_GEN3_MOVE_MILKDRINK,
        POKEMON_GEN3_MOVE_SLACKOFF, POKEMON_GEN3_MOVE_SOFTBOILED,
    };
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    for (size_t i = 0; i < sizeof(moves) / sizeof(moves[0]); i++) {
        PokemonBattleInit init = condition_init(
            POKEMON_GEN3_SPECIES_ALAKAZAM, moves[i],
            POKEMON_GEN3_SPECIES_KINGLER, POKEMON_GEN3_MOVE_SPLASH);
        init.teams[0].members[0].stats[0] = 301;
        init.initial_hp[0][0] = 100;
        PokemonBattle battle;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        uint8_t pp = battle.sides[0].state[0].pp[0];
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        assert(battle.sides[0].state[0].hp == 250);
        assert(battle.sides[0].state[0].pp[0] == (uint8_t)(pp - 1));
        assert(battle.effect_trace_count == 1);
        const PokemonEffectTrace *trace = &battle.effect_traces[0];
        assert(trace->kind == POKEMON_EFFECT_HEAL_FRACTION);
        assert(trace->result == POKEMON_EFFECT_APPLIED);
        assert(trace->damage_basis == 301 && trace->requested == 150);
        assert(trace->value == 150 && trace->before == 100 && trace->after == 250);
        assert(trace->numerator == 1 && trace->denominator == 2);
        size_t heals = 0;
        for (size_t event = 0; event < battle.event_count; event++) {
            if (battle.events[event].kind == POKEMON_EVENT_HEAL) {
                heals++;
                assert(battle.events[event].amount == 150);
            }
        }
        assert(heals == 1);

        init.initial_hp[0][0] = 300;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        assert(battle.sides[0].state[0].hp == 301);
        assert(battle.effect_traces[0].requested == 150);
        assert(battle.effect_traces[0].value == 1);

        init.initial_hp[0][0] = 301;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        pp = battle.sides[0].state[0].pp[0];
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        assert(battle.sides[0].state[0].hp == 301);
        assert(battle.sides[0].state[0].pp[0] == (uint8_t)(pp - 1));
        assert(battle.effect_traces[0].result == POKEMON_EFFECT_FAILED);
        heals = 0;
        for (size_t event = 0; event < battle.event_count; event++) {
            heals += battle.events[event].kind == POKEMON_EVENT_HEAL;
        }
        assert(heals == 0);
    }
}

static void test_generated_weather_recovery_family(void) {
    static const uint16_t moves[] = {
        POKEMON_GEN3_MOVE_MOONLIGHT, POKEMON_GEN3_MOVE_MORNINGSUN,
        POKEMON_GEN3_MOVE_SYNTHESIS,
    };
    static const PokemonWeatherKind weather[] = {
        POKEMON_WEATHER_NONE, POKEMON_WEATHER_SUN, POKEMON_WEATHER_RAIN,
        POKEMON_WEATHER_SANDSTORM, POKEMON_WEATHER_HAIL,
    };
    static const uint16_t requested[] = {150, 200, 75, 75, 75};
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    for (size_t m = 0; m < sizeof(moves) / sizeof(moves[0]); m++) {
        for (size_t w = 0; w < sizeof(weather) / sizeof(weather[0]); w++) {
            PokemonBattleInit init = condition_init(
                POKEMON_GEN3_SPECIES_SMEARGLE, moves[m],
                POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SPLASH);
            init.teams[0].members[0].stats[0] = 301;
            init.initial_hp[0][0] = 50;
            PokemonBattle battle;
            assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
            if (weather[w] != POKEMON_WEATHER_NONE) {
                battle.field.weather = (PokemonWeatherState){
                    .kind = weather[w],
                    .descriptor_id = battle.generation->condition_descriptor(
                        POKEMON_OWNER_FIELD, weather[w]),
                    .duration = 5, .source_side = 1, .source_slot = 0,
                    .state_generation = 1,
                };
            }
            assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
            assert(battle.effect_trace_count >= 1);
            const PokemonEffectTrace *trace = &battle.effect_traces[0];
            assert(trace->kind == POKEMON_EFFECT_HEAL_WEATHER_FRACTION);
            assert(trace->requested == requested[w] && trace->value == requested[w]);
            assert(trace->before == 50 && trace->after == 50 + requested[w]);
            assert(trace->damage_basis == 301);
        }
    }
}

static uint16_t weather_ball_damage(
    PokemonWeatherKind weather, uint16_t suppressing_ability,
    PokemonVolatileKind gate
) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_WEATHERBALL,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_FLY);
    init.teams[0].members[0].stats[1] = 80;
    init.teams[0].members[0].stats[3] = 240;
    init.teams[0].members[0].stats[5] = 200;
    init.teams[1].members[0].stats[0] = 700;
    init.teams[1].members[0].stats[2] = 180;
    init.teams[1].members[0].stats[4] = 180;
    init.teams[1].members[0].stats[5] = 50;
    init.teams[1].members[0].ability_id = suppressing_ability;
    PokemonBattle battle;
    int init_result = pokemon_battle_init(&battle, &init);
    assert(init_result == POKEMON_OK);
    if (weather != POKEMON_WEATHER_NONE) {
        battle.field.weather = (PokemonWeatherState){
            .kind = weather,
            .descriptor_id = battle.generation->condition_descriptor(
                POKEMON_OWNER_FIELD, weather),
            .duration = 5, .source_side = 0, .source_slot = 0,
            .state_generation = 1,
        };
    }
    PokemonMutable *target = &battle.sides[1].state[0];
    if (gate == POKEMON_VOLATILE_PROTECT) {
        target->volatiles[target->volatile_count++] = (PokemonVolatileState){
            .kind = gate,
            .descriptor_id = POKEMON_GEN3_CONDITION_VOLATILE_PROTECT,
            .duration = 1, .state_generation = 1,
            .effect_order = ++battle.next_holder_effect_order,
        };
    } else if (gate == POKEMON_VOLATILE_SUBSTITUTE) {
        target->volatiles[target->volatile_count++] = (PokemonVolatileState){
            .kind = gate,
            .descriptor_id = POKEMON_GEN3_CONDITION_VOLATILE_SUBSTITUTE,
            .state_generation = 1,
            .effect_order = ++battle.next_holder_effect_order,
            .payload.substitute.hp = 200,
        };
    }
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    size_t modify_type = 0, modify_move = 0;
    for (size_t i = 0; i < battle.handler_count; i++) {
        modify_type += battle.handlers[i].handler.descriptor.id ==
            POKEMON_GEN3_HANDLER_WEATHER_BALL_MODIFY_TYPE;
        modify_move += battle.handlers[i].handler.descriptor.id ==
            POKEMON_GEN3_HANDLER_WEATHER_BALL_MODIFY_MOVE;
    }
    assert(modify_type == 0 && modify_move == 1);
    if (gate == POKEMON_VOLATILE_PROTECT) {
        assert(target->hp == battle.sides[1].sets[0].stats[0]);
        return 0;
    }
    for (size_t i = 0; i < battle.event_count; i++) {
        if (battle.events[i].kind == POKEMON_EVENT_DAMAGE &&
            battle.events[i].move_id == POKEMON_GEN3_MOVE_WEATHERBALL) {
            return battle.events[i].amount;
        }
    }
    for (size_t i = 0; i < battle.hit_trace_count; i++) {
        if (battle.hit_traces[i].move_id == POKEMON_GEN3_MOVE_WEATHERBALL &&
            battle.hit_traces[i].kind == POKEMON_HIT_SUBSTITUTE) {
            return battle.hit_traces[i].damage;
        }
    }
    assert(0 && "Weather Ball must produce a damage-bearing hit trace");
    return 0;
}

static void test_weather_ball_active_frame_mutation(void) {
    uint16_t clear = weather_ball_damage(POKEMON_WEATHER_NONE, 0, 0);
    uint16_t sand = weather_ball_damage(POKEMON_WEATHER_SANDSTORM, 0, 0);
    uint16_t hail = weather_ball_damage(POKEMON_WEATHER_HAIL, 0, 0);
    uint16_t rain = weather_ball_damage(POKEMON_WEATHER_RAIN, 0, 0);
    uint16_t sun = weather_ball_damage(POKEMON_WEATHER_SUN, 0, 0);
    assert(clear != 0 && sand > clear && hail > clear && rain > clear && sun > clear);
    assert(weather_ball_damage(
        POKEMON_WEATHER_RAIN, POKEMON_GEN3_ABILITY_CLOUDNINE, 0) == clear);
    assert(weather_ball_damage(
        POKEMON_WEATHER_SUN, 0, POKEMON_VOLATILE_PROTECT) == 0);
    assert(weather_ball_damage(
        POKEMON_WEATHER_HAIL, 0, POKEMON_VOLATILE_SUBSTITUTE) != 0);

    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_WEATHERBALL,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[0].members[0].stats[5] = 200;
    init.teams[1].members[0].stats[0] = 700;
    init.teams[1].members[0].stats[5] = 50;
    init.initial_status[1][0] = POKEMON_STATUS_FREEZE;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    battle.field.weather = (PokemonWeatherState){
        .kind = POKEMON_WEATHER_SUN,
        .descriptor_id = battle.generation->condition_descriptor(
            POKEMON_OWNER_FIELD, POKEMON_WEATHER_SUN),
        .duration = 5, .source_side = 0, .source_slot = 0,
        .state_generation = 1,
    };
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].state[0].status.kind == POKEMON_STATUS_FREEZE);
}

static void test_conversion_2_resolved_last_move_response(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_AGGRON, POKEMON_GEN3_MOVE_CONVERSION2,
        POKEMON_GEN3_SPECIES_CHARIZARD, POKEMON_GEN3_MOVE_DRAGONRAGE);
    init.teams[0].members[0].move_ids[1] = POKEMON_GEN3_MOVE_SPLASH;
    init.teams[1].members[0].move_ids[1] = POKEMON_GEN3_MOVE_SPLASH;
    init.teams[0].members[0].stats[5] = 200;
    init.teams[1].members[0].stats[5] = 100;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);

    /* Conversion 2 runs before the foe has any invoked-move history. It
     * fails without consuming the selection draw or changing source types. */
    PokemonChoice no_history[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_step(&battle, no_history) == POKEMON_OK);
    assert(draw_label_count(
        &battle, POKEMON_DRAW_TYPE_RESPONSE_SELECTION) == 0);
    assert(battle.sides[0].state[0].effective_type_count == 2);

    /* Reinitialize, let Dragon Rage become the target's canonical resolved
     * last-used move, then answer it. Steel is the sole standard Gen 3 type
     * resistant to Dragon, and Showdown samples even a singleton list. */
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    PokemonChoice establish[POKEMON_SIDES] = {move(1), move(0)};
    assert(pokemon_battle_step(&battle, establish) == POKEMON_OK);
    const PokemonLastUsedMove *history =
        &battle.sides[1].state[0].last_move_used;
    assert(history->present);
    assert(history->move_id == POKEMON_GEN3_MOVE_DRAGONRAGE);
    assert(history->resolved_type == POKEMON_GEN3_TYPE_DRAGON);
    /* Gen 3 does not exclude a response merely because the source already
     * has that type: Aggron is currently Steel/Rock and Steel remains the
     * singleton legal response. */
    assert(battle.sides[0].state[0].effective_types[0] ==
        POKEMON_GEN3_TYPE_STEEL);
    PokemonChoice respond[POKEMON_SIDES] = {move(0), move(1)};
    assert(pokemon_battle_step(&battle, respond) == POKEMON_OK);
    assert(draw_label_count(
        &battle, POKEMON_DRAW_TYPE_RESPONSE_SELECTION) == 1);
    const PokemonDraw *selection = NULL;
    for (size_t i = 0; i < battle.draw_count; i++) {
        if (battle.draws[i].label == POKEMON_DRAW_TYPE_RESPONSE_SELECTION) {
            selection = &battle.draws[i];
        }
    }
    assert(selection != NULL && selection->upper_bound == 1 &&
        selection->result == 0);
    const PokemonMutable *source = &battle.sides[0].state[0];
    assert(source->effective_type_count == 1);
    assert(source->effective_types[0] == POKEMON_GEN3_TYPE_STEEL);
    assert(source->last_move_used.present);
    assert(source->last_move_used.move_id == POKEMON_GEN3_MOVE_CONVERSION2);
    assert(pokemon_battle_check_invariants(&battle));

    /* Struggle remains canonically typeless; the generation policy identifies
     * it by catalog identity and responds as if Normal. */
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    battle.sides[1].state[0].last_move_used = (PokemonLastUsedMove){
        .present = 1,
        .move_id = POKEMON_GEN3_MOVE_STRUGGLE,
        .resolved_type = POKEMON_GEN3_TYPE_TYPELESS,
    };
    assert(pokemon_battle_check_invariants(&battle));
    PokemonChoice struggle_response[POKEMON_SIDES] = {move(0), move(1)};
    assert(pokemon_battle_step(&battle, struggle_response) == POKEMON_OK);
    selection = NULL;
    for (size_t i = 0; i < battle.draw_count; i++) {
        if (battle.draws[i].label == POKEMON_DRAW_TYPE_RESPONSE_SELECTION) {
            selection = &battle.draws[i];
        }
    }
    assert(selection != NULL && selection->upper_bound == 3);
    assert(pokemon_battle_check_invariants(&battle));
}

static void test_current_move_slot_type_overlays(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_ALAKAZAM, POKEMON_GEN3_MOVE_CAMOUFLAGE,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SPLASH);
    init.team_sizes[0] = 2;
    init.teams[0].members[1] = init.teams[0].members[0];
    init.teams[0].members[1].species_id = POKEMON_GEN3_SPECIES_ALAKAZAM;
    init.teams[0].members[1].move_ids[0] = POKEMON_GEN3_MOVE_SPLASH;
    init.teams[0].members[0].stats[5] = 300;
    init.teams[1].members[0].stats[5] = 100;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].effective_type_count == 1);
    assert(battle.sides[0].state[0].effective_types[0] ==
        POKEMON_GEN3_TYPE_NORMAL);
    assert(draw_label_count(&battle, POKEMON_DRAW_MOVE_TYPE_SELECTION) == 0);
    PokemonChoice switch_choices[POKEMON_SIDES] = {switch_to(1), move(0)};
    assert(pokemon_battle_step(&battle, switch_choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].effective_type_count == 1);
    assert(battle.sides[0].state[0].effective_types[0] ==
        POKEMON_GEN3_TYPE_PSYCHIC);
    assert(pokemon_battle_check_invariants(&battle));

    init = condition_init(
        POKEMON_GEN3_SPECIES_ALAKAZAM, POKEMON_GEN3_MOVE_CONVERSION,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[0].members[0].move_ids[1] = POKEMON_GEN3_MOVE_FLAMETHROWER;
    init.teams[0].members[0].move_ids[2] = POKEMON_GEN3_MOVE_FIREPUNCH;
    init.teams[0].members[0].move_ids[3] = POKEMON_GEN3_MOVE_PSYCHIC;
    init.teams[0].members[0].stats[5] = 300;
    init.teams[1].members[0].stats[5] = 100;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    const PokemonDraw *selection = NULL;
    for (size_t i = 0; i < battle.draw_count; i++) {
        if (battle.draws[i].label == POKEMON_DRAW_MOVE_TYPE_SELECTION) {
            selection = &battle.draws[i];
        }
    }
    assert(selection != NULL && selection->upper_bound == 3);
    assert(battle.sides[0].state[0].effective_type_count == 1);
    assert(battle.sides[0].state[0].effective_types[0] ==
            POKEMON_GEN3_TYPE_NORMAL ||
        battle.sides[0].state[0].effective_types[0] ==
            POKEMON_GEN3_TYPE_FIRE);
    assert(pokemon_battle_check_invariants(&battle));

    /* A Normal holder whose only current slot is Conversion has no candidate
     * and therefore fails before owning a selection draw. */
    init = condition_init(
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_CONVERSION,
        POKEMON_GEN3_SPECIES_ALAKAZAM, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[0].members[0].stats[5] = 300;
    init.teams[1].members[0].stats[5] = 100;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(draw_label_count(&battle, POKEMON_DRAW_MOVE_TYPE_SELECTION) == 0);
    assert(battle.sides[0].state[0].effective_type_count == 1);
    assert(battle.sides[0].state[0].effective_types[0] ==
        POKEMON_GEN3_TYPE_NORMAL);
    assert(pokemon_battle_check_invariants(&battle));
}

static void test_focus_punch_prepared_action_lifecycle(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_BRELOOM, POKEMON_GEN3_MOVE_FOCUSPUNCH,
        POKEMON_GEN3_SPECIES_VENUSAUR, POKEMON_GEN3_MOVE_TACKLE);
    init.teams[0].members[0].stats[5] = 100;
    init.teams[1].members[0].stats[0] = 1000;
    init.teams[1].members[0].stats[5] = 300;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    uint16_t target_hp = battle.sides[1].state[0].hp;
    uint8_t before_pp = battle.sides[0].state[0].pp[0];
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].pp[0] == before_pp - 1);
    assert(battle.sides[1].state[0].hp == target_hp);
    assert(handler_id_count(
        &battle, POKEMON_GEN3_HANDLER_FOCUS_PUNCH_START) == 1);
    assert(handler_id_count(
        &battle, POKEMON_GEN3_HANDLER_FOCUS_PUNCH_HIT) == 1);
    assert(handler_id_count(
        &battle, POKEMON_GEN3_HANDLER_FOCUS_PUNCH_TRY) == 1);
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 1);
    assert(draw_label_count(&battle, POKEMON_DRAW_CRITICAL) == 1);
    assert(draw_label_count(&battle, POKEMON_DRAW_DAMAGE_ROLL) == 1);
    assert(test_volatile_index(
        &battle.sides[0].state[0], POKEMON_VOLATILE_PREPARED_ACTION) < 0);
    assert(pokemon_battle_check_invariants(&battle));

    /* A status hit reaches the holder-wide Hit boundary but does not mark the
     * prepared action. Focus Punch then owns its ordinary hit draws. */
    init.teams[1].members[0].move_ids[0] = POKEMON_GEN3_MOVE_GROWL;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    target_hp = battle.sides[1].state[0].hp;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].state[0].hp < target_hp);
    assert(handler_id_count(
        &battle, POKEMON_GEN3_HANDLER_FOCUS_PUNCH_HIT) == 1);
    assert(handler_id_count(
        &battle, POKEMON_GEN3_HANDLER_FOCUS_PUNCH_TRY) == 1);
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 2);
    assert(draw_label_count(&battle, POKEMON_DRAW_CRITICAL) == 1);
    assert(draw_label_count(&battle, POKEMON_DRAW_DAMAGE_ROLL) == 1);
    assert(test_volatile_index(
        &battle.sides[0].state[0], POKEMON_VOLATILE_PREPARED_ACTION) < 0);
    assert(pokemon_battle_check_invariants(&battle));
}

static void test_faint_response_condition_family(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_DESTINYBOND,
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_SPLASH);
    init.team_sizes[0] = 1;
    init.team_sizes[1] = 1;
    init.teams[0].members[0].move_ids[1] = POKEMON_GEN3_MOVE_SPLASH;
    init.teams[1].members[0].move_ids[1] = POKEMON_GEN3_MOVE_QUICKATTACK;
    init.teams[0].members[0].stats[5] = 50;
    init.teams[1].members[0].stats[5] = 100;
    init.initial_hp[0][0] = 1;
    PokemonChoice setup[POKEMON_SIDES] = {move(0), move(0)};
    PokemonChoice ko[POKEMON_SIDES] = {move(1), move(1)};
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, setup) == POKEMON_OK);
    assert(test_volatile_index(&battle.sides[0].state[0],
        POKEMON_VOLATILE_SOURCE_FAINT_RESPONSE) >= 0);
    assert(pokemon_battle_step(&battle, ko) == POKEMON_OK);
    assert(battle.sides[0].state[0].fainted);
    assert(battle.sides[1].state[0].fainted);
    assert(battle.terminal && battle.winner == -1);
    assert(handler_id_count(
        &battle, POKEMON_GEN3_HANDLER_DESTINY_BOND_FAINT) == 1);
    assert(event_kind_count(&battle, POKEMON_EVENT_FAINT) == 2);
    assert(pokemon_battle_check_invariants(&battle));

    init.teams[0].members[0].move_ids[0] = POKEMON_GEN3_MOVE_GRUDGE;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, setup) == POKEMON_OK);
    assert(test_volatile_index(&battle.sides[0].state[0],
        POKEMON_VOLATILE_SOURCE_PP_ZERO_RESPONSE) >= 0);
    assert(battle.sides[1].state[0].pp[1] != 0);
    assert(pokemon_battle_step(&battle, ko) == POKEMON_OK);
    assert(battle.sides[0].state[0].fainted);
    assert(!battle.sides[1].state[0].fainted);
    assert(battle.sides[1].state[0].pp[1] == 0);
    assert(handler_id_count(&battle, POKEMON_GEN3_HANDLER_GRUDGE_FAINT) == 1);
    assert(event_kind_count(&battle, POKEMON_EVENT_FAINT) == 1);
    assert(pokemon_battle_check_invariants(&battle));
}

static PokemonBattle thunder_battle(PokemonWeatherKind weather, uint16_t ability,
    uint16_t seed0, PokemonVolatileKind gate) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_THUNDER,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[0].members[0].stats[5] = 200;
    init.teams[1].members[0].stats[0] = 700;
    init.teams[1].members[0].stats[5] = 50;
    init.teams[1].members[0].ability_id = ability;
    init.seed[0] = seed0;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    if (weather != POKEMON_WEATHER_NONE) battle.field.weather = (PokemonWeatherState){
        .kind = weather,
        .descriptor_id = battle.generation->condition_descriptor(
            POKEMON_OWNER_FIELD, weather),
        .duration = 5, .source_side = 0, .source_slot = 0,
        .state_generation = 1,
    };
    if (gate != 0) {
        PokemonMutable *target = &battle.sides[1].state[0];
        target->volatiles[target->volatile_count++] = (PokemonVolatileState){
            .kind = gate,
            .descriptor_id = gate == POKEMON_VOLATILE_PROTECT ?
                POKEMON_GEN3_CONDITION_VOLATILE_PROTECT :
                POKEMON_GEN3_CONDITION_VOLATILE_SUBSTITUTE,
            .duration = gate == POKEMON_VOLATILE_PROTECT ? 1 : 0,
            .state_generation = 1,
            .effect_order = ++battle.next_holder_effect_order,
            .payload.substitute.hp = gate == POKEMON_VOLATILE_SUBSTITUTE ? 200 : 0,
        };
    }
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    size_t modify = 0;
    for (size_t i = 0; i < battle.handler_count; i++) modify +=
        battle.handlers[i].handler.descriptor.id ==
            POKEMON_GEN3_HANDLER_THUNDER_MODIFY_MOVE;
    assert(modify == 1);
    return battle;
}

static void test_thunder_weather_accuracy_pipeline(void) {
    static const PokemonWeatherKind weather[] = {
        POKEMON_WEATHER_NONE, POKEMON_WEATHER_SANDSTORM,
        POKEMON_WEATHER_HAIL, POKEMON_WEATHER_RAIN, POKEMON_WEATHER_SUN,
    };
    for (size_t i = 0; i < sizeof(weather) / sizeof(weather[0]); i++) {
        PokemonBattle battle = thunder_battle(weather[i], 0, 1, 0);
        assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) ==
            (weather[i] == POKEMON_WEATHER_RAIN ? 0 : 1));
    }
    PokemonBattle suppressed = thunder_battle(
        POKEMON_WEATHER_RAIN, POKEMON_GEN3_ABILITY_CLOUDNINE, 1, 0);
    assert(draw_label_count(&suppressed, POKEMON_DRAW_ACCURACY) == 1);

    uint8_t saw_hit = 0, saw_miss = 0, saw_secondary = 0, saw_no_secondary = 0;
    for (uint16_t seed = 1; seed < 1000 &&
         !(saw_hit && saw_miss && saw_secondary && saw_no_secondary); seed++) {
        PokemonBattle battle = thunder_battle(POKEMON_WEATHER_NONE, 0, seed, 0);
        uint8_t missed = 0;
        for (size_t i = 0; i < battle.event_count; i++) missed |=
            battle.events[i].kind == POKEMON_EVENT_MISS;
        saw_miss |= missed;
        saw_hit |= !missed;
        if (!missed) {
            uint8_t paralyzed = battle.sides[1].state[0].status.kind ==
                POKEMON_STATUS_PARALYSIS;
            saw_secondary |= paralyzed;
            saw_no_secondary |= !paralyzed;
        }
    }
    assert(saw_hit && saw_miss && saw_secondary && saw_no_secondary);
    PokemonBattle protected = thunder_battle(
        POKEMON_WEATHER_RAIN, 0, 1, POKEMON_VOLATILE_PROTECT);
    assert(protected.sides[1].state[0].hp == 700);
    assert(draw_label_count(&protected, POKEMON_DRAW_SECONDARY) == 0);
    PokemonBattle substituted = thunder_battle(
        POKEMON_WEATHER_RAIN, 0, 1, POKEMON_VOLATILE_SUBSTITUTE);
    assert(substituted.sides[1].state[0].hp == 700);
    assert(draw_label_count(&substituted, POKEMON_DRAW_SECONDARY) == 1);
    assert(substituted.sides[1].state[0].status.kind == POKEMON_STATUS_NONE);
}

static PokemonBattle solar_beam_battle(
    PokemonWeatherKind weather, uint16_t ability
) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_SOLARBEAM,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[0].members[0].stats[3] = 60;
    init.teams[0].members[0].stats[5] = 200;
    init.teams[1].members[0].stats[0] = 700;
    init.teams[1].members[0].stats[4] = 500;
    init.teams[1].members[0].stats[5] = 50;
    init.teams[1].members[0].ability_id = ability;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    if (weather != POKEMON_WEATHER_NONE) battle.field.weather = (PokemonWeatherState){
        .kind = weather,
        .descriptor_id = battle.generation->condition_descriptor(
            POKEMON_OWNER_FIELD, weather),
        .duration = 5, .source_side = 0, .source_slot = 0,
        .state_generation = 1,
    };
    return battle;
}

static void test_solar_beam_two_turn_lifecycle(void) {
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    PokemonBattle clear = solar_beam_battle(POKEMON_WEATHER_NONE, 0);
    uint8_t pp = clear.sides[0].state[0].pp[0];
    uint16_t hp = clear.sides[1].state[0].hp;
    int solar_status = pokemon_battle_step(&clear, choices);
    assert(solar_status == POKEMON_OK);
    assert(clear.sides[0].state[0].pp[0] == pp - 1);
    assert(clear.sides[1].state[0].hp == hp);
    assert(test_volatile_index(&clear.sides[0].state[0],
        POKEMON_VOLATILE_TWO_TURN_MOVE) >= 0);
    assert(test_volatile_index(&clear.sides[0].state[0],
        POKEMON_VOLATILE_TWO_TURN_MARKER) >= 0);
    int marker = test_volatile_index(&clear.sides[0].state[0],
        POKEMON_VOLATILE_TWO_TURN_MARKER);
    int lock = test_volatile_index(&clear.sides[0].state[0],
        POKEMON_VOLATILE_TWO_TURN_MOVE);
    assert(clear.sides[0].state[0].volatiles[marker].descriptor_id ==
        POKEMON_GEN3_CONDITION_VOLATILE_SOLARBEAM);
    assert(clear.sides[0].state[0].volatiles[marker].payload.two_turn.move_id ==
        POKEMON_GEN3_MOVE_SOLARBEAM);
    assert(clear.sides[0].state[0].volatiles[marker].payload.two_turn.target_side == 1);
    assert(clear.sides[0].state[0].volatiles[marker].payload.two_turn.target_slot == 0);
    PokemonBattle malformed = clear;
    malformed.sides[0].state[0].volatiles[marker].descriptor_id =
        POKEMON_GEN3_CONDITION_VOLATILE_TWOTURNMOVE;
    assert(!pokemon_battle_check_invariants(&malformed));
    malformed = clear;
    malformed.sides[0].state[0].volatiles[marker].payload.two_turn.target_side =
        POKEMON_SIDES;
    assert(!pokemon_battle_check_invariants(&malformed));
    malformed = clear;
    malformed.sides[0].state[0].volatiles[lock].descriptor_id = 0;
    assert(!pokemon_battle_check_invariants(&malformed));
    assert(clear.request.legal_moves[0] == 1 && clear.request.legal_switches[0] == 0);
    assert(draw_label_count(&clear, POKEMON_DRAW_ACCURACY) == 0);
    assert(draw_label_count(&clear, POKEMON_DRAW_CRITICAL) == 0);
    assert(draw_label_count(&clear, POKEMON_DRAW_DAMAGE_ROLL) == 0);
    solar_status = pokemon_battle_step(&clear, choices);
    assert(solar_status == POKEMON_OK);
    assert(clear.sides[0].state[0].pp[0] == pp - 1);
    assert(clear.sides[1].state[0].hp < hp);
    assert(test_volatile_index(&clear.sides[0].state[0],
        POKEMON_VOLATILE_TWO_TURN_MOVE) < 0);
    assert(test_volatile_index(&clear.sides[0].state[0],
        POKEMON_VOLATILE_TWO_TURN_MARKER) < 0);

    PokemonBattle sun = solar_beam_battle(POKEMON_WEATHER_SUN, 0);
    hp = sun.sides[1].state[0].hp;
    assert(pokemon_battle_step(&sun, choices) == POKEMON_OK);
    assert(sun.sides[1].state[0].hp < hp);
    assert(test_volatile_index(&sun.sides[0].state[0],
        POKEMON_VOLATILE_TWO_TURN_MOVE) < 0);

    PokemonBattle changed = solar_beam_battle(POKEMON_WEATHER_NONE, 0);
    assert(pokemon_battle_step(&changed, choices) == POKEMON_OK);
    changed.field.weather.kind = POKEMON_WEATHER_RAIN;
    changed.field.weather.descriptor_id = changed.generation->condition_descriptor(
        POKEMON_OWNER_FIELD, POKEMON_WEATHER_RAIN);
    changed.field.weather.duration = 4;
    changed.field.weather.state_generation = 1;
    assert(pokemon_battle_step(&changed, choices) == POKEMON_OK);

    PokemonBattle suppressed = solar_beam_battle(
        POKEMON_WEATHER_SUN, POKEMON_GEN3_ABILITY_CLOUDNINE);
    assert(pokemon_battle_step(&suppressed, choices) == POKEMON_OK);
    assert(test_volatile_index(&suppressed.sides[0].state[0],
        POKEMON_VOLATILE_TWO_TURN_MOVE) >= 0);

    PokemonBattle interrupted = solar_beam_battle(POKEMON_WEATHER_NONE, 0);
    pp = interrupted.sides[0].state[0].pp[0];
    assert(pokemon_battle_step(&interrupted, choices) == POKEMON_OK);
    interrupted.sides[0].state[0].status = (PokemonStatusState){
        .kind = POKEMON_STATUS_SLEEP,
        .descriptor_id = POKEMON_GEN3_CONDITION_STATUS_SLP,
        .state_generation = 1, .effect_order = ++interrupted.next_holder_effect_order,
        .state.sleep = {.time = 2, .skipped_time = 0},
    };
    assert(pokemon_battle_step(&interrupted, choices) == POKEMON_OK);
    assert(interrupted.sides[0].state[0].pp[0] == pp - 1);
    assert(test_volatile_index(&interrupted.sides[0].state[0],
        POKEMON_VOLATILE_TWO_TURN_MOVE) < 0);
    assert(test_volatile_index(&interrupted.sides[0].state[0],
        POKEMON_VOLATILE_TWO_TURN_MARKER) < 0);
    assert(interrupted.request.legal_moves[0] == 1);

    PokemonBattle fainted = solar_beam_battle(POKEMON_WEATHER_NONE, 0);
    assert(pokemon_battle_step(&fainted, choices) == POKEMON_OK);
    uint16_t applied = 0;
    assert(pokemon_apply_direct_damage(&fainted, &(PokemonDirectDamageRequest){
        .source = {POKEMON_ENTITY_POKEMON, 1, 0},
        .target = {POKEMON_ENTITY_POKEMON, 0, 0},
        .source_effect = {POKEMON_SOURCE_EFFECT_MOVE, POKEMON_GEN3_MOVE_SPLASH},
        .amount = fainted.sides[0].state[0].hp,
    }, &applied) == POKEMON_OK);
    assert(fainted.sides[0].state[0].fainted);
    assert(fainted.sides[0].state[0].volatile_count == 0);

    PokemonBattle full = solar_beam_battle(POKEMON_WEATHER_NONE, 0);
    PokemonMutable *full_state = &full.sides[0].state[0];
    static const PokemonVolatileKind occupied[] = {
        POKEMON_VOLATILE_PROTECT, POKEMON_VOLATILE_MAGIC_COAT,
        POKEMON_VOLATILE_SNATCH,
    };
    static const uint16_t occupied_descriptors[] = {
        POKEMON_GEN3_CONDITION_VOLATILE_PROTECT,
        POKEMON_GEN3_CONDITION_VOLATILE_MAGICCOAT,
        POKEMON_GEN3_CONDITION_VOLATILE_SNATCH,
    };
    for (size_t i = 0; i < 3; i++) full_state->volatiles[full_state->volatile_count++] =
        (PokemonVolatileState){.kind = occupied[i],
            .descriptor_id = occupied_descriptors[i], .duration = 1,
            .state_generation = 1, .effect_order = ++full.next_holder_effect_order};
    assert(pokemon_battle_check_invariants(&full));
    PokemonBattle before_full = full;
    assert(pokemon_battle_step(&full, choices) == POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&full, &before_full, sizeof(full)) == 0);
}

static void test_generated_two_turn_descriptor_rotation(void) {
    static const uint16_t moves[] = {
        POKEMON_GEN3_MOVE_BOUNCE, POKEMON_GEN3_MOVE_DIG,
        POKEMON_GEN3_MOVE_DIVE, POKEMON_GEN3_MOVE_RAZORWIND,
        POKEMON_GEN3_MOVE_SKULLBASH, POKEMON_GEN3_MOVE_SKYATTACK,
    };
    static const uint16_t markers[] = {
        POKEMON_GEN3_CONDITION_VOLATILE_BOUNCE,
        POKEMON_GEN3_CONDITION_VOLATILE_DIG,
        POKEMON_GEN3_CONDITION_VOLATILE_DIVE,
        POKEMON_GEN3_CONDITION_VOLATILE_RAZORWIND,
        POKEMON_GEN3_CONDITION_VOLATILE_SKULLBASH,
        POKEMON_GEN3_CONDITION_VOLATILE_SKYATTACK,
    };
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    for (size_t i = 0; i < sizeof(moves) / sizeof(moves[0]); i++) {
        PokemonBattleInit init = condition_init(
            POKEMON_GEN3_SPECIES_SMEARGLE, moves[i],
            POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SPLASH);
        init.teams[0].members[0].ability_id = POKEMON_GEN3_ABILITY_OWNTEMPO;
        init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_NATURALCURE;
        init.teams[0].members[0].stats[5] = 200;
        init.teams[1].members[0].stats[0] = 700;
        PokemonBattle battle;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        uint8_t pp = battle.sides[0].state[0].pp[0];
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        assert(battle.sides[0].state[0].pp[0] == (uint8_t)(pp - 1));
        int marker = test_volatile_index(
            &battle.sides[0].state[0], POKEMON_VOLATILE_TWO_TURN_MARKER);
        assert(marker >= 0);
        assert(battle.sides[0].state[0].volatiles[marker].descriptor_id ==
            markers[i]);
        assert(battle.sides[0].state[0].volatiles[marker]
            .payload.two_turn.move_id == moves[i]);
        assert(battle.request.legal_moves[0] == 1);
        assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 0);
        assert(battle.sides[0].state[0].boosts[POKEMON_STAT_DEF] ==
            (moves[i] == POKEMON_GEN3_MOVE_SKULLBASH ? 1 : 0));
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        assert(battle.sides[0].state[0].pp[0] == (uint8_t)(pp - 1));
        assert(test_volatile_index(&battle.sides[0].state[0],
            POKEMON_VOLATILE_TWO_TURN_MOVE) < 0);
        assert(test_volatile_index(&battle.sides[0].state[0],
            POKEMON_VOLATILE_TWO_TURN_MARKER) < 0);
        assert(battle.sides[0].state[0].boosts[POKEMON_STAT_DEF] ==
            (moves[i] == POKEMON_GEN3_MOVE_SKULLBASH ? 1 : 0));
        assert(pokemon_battle_check_invariants(&battle));
    }
}

static void test_fly_two_turn_invulnerability_family(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_FLY,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_STRENGTH);
    init.teams[0].members[0].ability_id = POKEMON_GEN3_ABILITY_OWNTEMPO;
    init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_NATURALCURE;
    init.teams[0].members[0].stats[5] = 200;
    init.teams[1].members[0].stats[0] = 700;
    init.teams[1].members[0].stats[2] = 500;
    init.teams[1].members[0].stats[5] = 100;
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    PokemonBattle battle;
    assert(POKEMON_GEN3_SLICE_DATA.handlers[
        POKEMON_GEN3_HANDLER_FLY_INVULNERABILITY - 1].id ==
        POKEMON_GEN3_HANDLER_FLY_INVULNERABILITY);
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    uint16_t source_hp = battle.sides[0].state[0].hp;
    uint16_t target_hp = battle.sides[1].state[0].hp;
    uint8_t pp = battle.sides[0].state[0].pp[0];
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.last_queue.values[0].side == 0);
    int marker = test_volatile_index(
        &battle.sides[0].state[0], POKEMON_VOLATILE_TWO_TURN_MARKER);
    assert(marker >= 0);
    assert(battle.sides[0].state[0].volatiles[marker].descriptor_id ==
        POKEMON_GEN3_CONDITION_VOLATILE_FLY);
    size_t invulnerability_handlers = 0;
    for (size_t i = 0; i < battle.handler_count; i++) {
        invulnerability_handlers += battle.handlers[i].handler.descriptor.event ==
            POKEMON_HANDLER_EVENT_INVULNERABILITY;
    }
    assert(invulnerability_handlers == 1);
    assert(battle.sides[0].state[0].hp == source_hp);
    assert(battle.sides[1].state[0].hp == target_hp);
    assert(battle.sides[0].state[0].pp[0] == pp - 1);
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 0);
    assert(battle.request.forced_move_id[0] == POKEMON_GEN3_MOVE_FLY);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(test_volatile_index(
        &battle.sides[0].state[0], POKEMON_VOLATILE_TWO_TURN_MARKER) < 0);
    assert(test_volatile_index(
        &battle.sides[0].state[0], POKEMON_VOLATILE_TWO_TURN_MOVE) < 0);

    /* Thunder's generated semantic bypass reaches accuracy while airborne. */
    init.teams[1].members[0].move_ids[0] = POKEMON_GEN3_MOVE_THUNDER;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 1);
    assert(pokemon_battle_check_invariants(&battle));
}

static void test_lock_on_source_bound_accuracy_and_invulnerability(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_LOCKON,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_FLY);
    init.teams[0].members[0].move_ids[1] = POKEMON_GEN3_MOVE_TOXIC;
    init.teams[0].members[0].stats[5] = 200;
    init.teams[1].members[0].stats[5] = 100;
    init.teams[1].members[0].stats[0] = 700;
    PokemonBattle battle;
    PokemonChoice setup[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, setup) == POKEMON_OK);
    int lock_on = test_volatile_index(
        &battle.sides[0].state[0], POKEMON_VOLATILE_LOCK_ON);
    assert(lock_on >= 0);
    const PokemonVolatileState *state =
        &battle.sides[0].state[0].volatiles[lock_on];
    assert(state->descriptor_id == POKEMON_GEN3_CONDITION_VOLATILE_LOCKON);
    assert(state->duration == 1);
    assert(state->source.kind == POKEMON_ENTITY_POKEMON);
    assert(state->source.side == 1 && state->source.slot == 0);
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 1);

    PokemonChoice follow_up[POKEMON_SIDES] = {move(1), move(0)};
    assert(pokemon_battle_step(&battle, follow_up) == POKEMON_OK);
    assert(battle.sides[1].state[0].status.kind == POKEMON_STATUS_TOXIC);
    /* Fly's release owns the only accuracy draw; Toxic's numeric check is
     * suppressed by the source-bound condition. */
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 1);
    assert(test_volatile_index(
        &battle.sides[0].state[0], POKEMON_VOLATILE_LOCK_ON) < 0);
    assert(pokemon_battle_check_invariants(&battle));

    init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_MINDREADER,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[0].members[0].stats[5] = 200;
    init.teams[1].members[0].stats[5] = 100;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, setup) == POKEMON_OK);
    assert(test_volatile_index(
        &battle.sides[0].state[0], POKEMON_VOLATILE_LOCK_ON) >= 0);
    /* Accuracy runs before move-owned TryHit; the existing source-bound
     * condition makes the duplicate setup always-hit before TryHit rejects. */
    assert(pokemon_battle_step(&battle, setup) == POKEMON_OK);
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 0);
    assert(pokemon_battle_check_invariants(&battle));

}

static void test_semi_invulnerable_descriptor_masks_and_validation(void) {
    static const struct {
        uint16_t move_id;
        uint8_t hit;
        uint8_t doubled;
    } cases[] = {
        {POKEMON_GEN3_MOVE_GUST, POKEMON_SEMI_INVULNERABLE_AIRBORNE,
            POKEMON_SEMI_INVULNERABLE_AIRBORNE},
        {POKEMON_GEN3_MOVE_TWISTER, POKEMON_SEMI_INVULNERABLE_AIRBORNE,
            POKEMON_SEMI_INVULNERABLE_AIRBORNE},
        {POKEMON_GEN3_MOVE_SKYUPPERCUT, POKEMON_SEMI_INVULNERABLE_AIRBORNE, 0},
        {POKEMON_GEN3_MOVE_THUNDER, POKEMON_SEMI_INVULNERABLE_AIRBORNE, 0},
        {POKEMON_GEN3_MOVE_EARTHQUAKE, POKEMON_SEMI_INVULNERABLE_UNDERGROUND,
            POKEMON_SEMI_INVULNERABLE_UNDERGROUND},
        {POKEMON_GEN3_MOVE_SURF, POKEMON_SEMI_INVULNERABLE_UNDERWATER,
            POKEMON_SEMI_INVULNERABLE_UNDERWATER},
        {POKEMON_GEN3_MOVE_WHIRLPOOL, POKEMON_SEMI_INVULNERABLE_UNDERWATER,
            POKEMON_SEMI_INVULNERABLE_UNDERWATER},
        {POKEMON_GEN3_MOVE_STRENGTH, 0, 0},
    };
    size_t strength_index = SIZE_MAX;
    for (size_t expected = 0; expected < sizeof(cases) / sizeof(cases[0]);
         expected++) {
        const PokemonMoveData *found = NULL;
        for (size_t i = 0; i < POKEMON_GEN3_SLICE_DATA.move_count; i++) {
            if (POKEMON_GEN3_SLICE_DATA.moves[i].id == cases[expected].move_id) {
                found = &POKEMON_GEN3_SLICE_DATA.moves[i];
                if (cases[expected].move_id == POKEMON_GEN3_MOVE_STRENGTH) {
                    strength_index = i;
                }
                break;
            }
        }
        assert(found != NULL);
        assert(found->semi_invulnerable_hit_mask == cases[expected].hit);
        assert(found->semi_invulnerable_double_mask == cases[expected].doubled);
    }
    assert(strength_index != SIZE_MAX);

    PokemonMoveData malformed_moves[POKEMON_GEN3_MOVE_COUNT];
    memcpy(malformed_moves, POKEMON_GEN3_SLICE_DATA.moves,
        sizeof(malformed_moves));
    PokemonData malformed_data = POKEMON_GEN3_SLICE_DATA;
    malformed_data.moves = malformed_moves;
    PokemonResolvedBundle malformed_bundle = POKEMON_GEN3_OU_BUNDLE;
    malformed_bundle.data = &malformed_data;
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_STRENGTH,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SPLASH);
    init.bundle = &malformed_bundle;
    PokemonBattle untouched;
    memset(&untouched, 0xa5, sizeof(untouched));
    PokemonBattle before = untouched;
    malformed_moves[strength_index].semi_invulnerable_hit_mask = UINT8_C(0x80);
    assert(pokemon_battle_init(&untouched, &init) ==
        POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&untouched, &before, sizeof(untouched)) == 0);
    malformed_moves[strength_index].semi_invulnerable_hit_mask = 0;
    malformed_moves[strength_index].semi_invulnerable_double_mask =
        POKEMON_SEMI_INVULNERABLE_AIRBORNE;
    assert(pokemon_battle_init(&untouched, &init) ==
        POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&untouched, &before, sizeof(untouched)) == 0);
}

static PokemonBattleInit locked_move_init(uint16_t move_id) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, move_id,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[0].members[0].stats[3] = 60;
    init.teams[0].members[0].stats[5] = 200;
    init.teams[1].members[0].stats[0] = 700;
    init.teams[1].members[0].stats[4] = 500;
    init.teams[1].members[0].stats[5] = 50;
    return init;
}

static void test_uproar_global_status_and_lock_lifecycle(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_UPROAR,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SPLASH);
    init.initial_status[1][0] = POKEMON_STATUS_NONE;
    init.teams[0].members[0].stats[0] = 500;
    init.teams[1].members[0].stats[0] = 1000;
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    uint8_t applied = 0;
    assert(pokemon_set_status(
        &battle, (PokemonEntityRef){POKEMON_ENTITY_POKEMON, 1, 0},
        POKEMON_STATUS_SLEEP,
        (PokemonEntityRef){POKEMON_ENTITY_POKEMON, 0, 0},
        (PokemonSourceEffectRef){POKEMON_SOURCE_EFFECT_MOVE,
            POKEMON_GEN3_MOVE_SPORE}, 1, &applied) == POKEMON_OK);
    assert(applied);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);

    /* Move-owned TryHit runs only after ordinary hit admission. It wakes the
     * opposing active, then the self effect owns exactly one duration draw. */
    assert(battle.sides[1].state[0].status.kind == POKEMON_STATUS_NONE);
    assert(battle.effect_trace_count >= 1);
    assert(battle.effect_traces[0].kind == POKEMON_EFFECT_CURE_STATUS);
    assert(battle.effect_traces[0].move_id == POKEMON_GEN3_MOVE_UPROAR);
    assert(battle.effect_traces[0].source_side == 0);
    assert(battle.effect_traces[0].target_side == 1);
    assert(battle.effect_traces[0].before == POKEMON_STATUS_SLEEP);
    assert(draw_label_count(&battle, POKEMON_DRAW_UPROAR_DURATION) == 1);
    int uproar = test_volatile_index(
        &battle.sides[0].state[0], POKEMON_VOLATILE_UPROAR);
    assert(uproar >= 0);
    assert(battle.sides[0].state[0].volatiles[uproar].duration >= 1);
    assert(battle.sides[0].state[0].volatiles[uproar].duration <= 4);
    assert(battle.sides[0].state[0].volatiles[uproar].descriptor_id ==
        POKEMON_GEN3_CONDITION_VOLATILE_UPROAR);
    assert(battle.sides[0].state[0].volatiles[uproar].source_effect.kind ==
        POKEMON_SOURCE_EFFECT_MOVE);
    assert(battle.sides[0].state[0].volatiles[uproar].source_effect.id ==
        POKEMON_GEN3_MOVE_UPROAR);
    assert(battle.request.forced_move_id[0] == POKEMON_GEN3_MOVE_UPROAR);

    /* Natural duration expiry owns End dispatch. Restarting the self
     * volatile on the locked hit does not replace the existing duration. */
    PokemonBattle expiry = battle;
    int expiry_uproar = test_volatile_index(
        &expiry.sides[0].state[0], POKEMON_VOLATILE_UPROAR);
    assert(expiry_uproar >= 0);
    expiry.sides[0].state[0].volatiles[expiry_uproar].duration = 1;
    size_t natural_ends = handler_id_count(
        &expiry, POKEMON_GEN3_HANDLER_UPROAR_END);
    assert(pokemon_battle_step(&expiry, choices) == POKEMON_OK);
    assert(test_volatile_index(
        &expiry.sides[0].state[0], POKEMON_VOLATILE_UPROAR) < 0);
    assert(handler_id_count(&expiry, POKEMON_GEN3_HANDLER_UPROAR_END) ==
        natural_ends + 1);

    /* The condition-owned ANY listener rejects sleep before mutation and
     * before sleep-duration PRNG, while unrelated statuses pass unchanged. */
    size_t sleep_draws = draw_label_count(&battle, POKEMON_DRAW_SLEEP_DURATION);
    applied = 1;
    assert(pokemon_set_status(
        &battle, (PokemonEntityRef){POKEMON_ENTITY_POKEMON, 1, 0},
        POKEMON_STATUS_SLEEP,
        (PokemonEntityRef){POKEMON_ENTITY_POKEMON, 0, 0},
        (PokemonSourceEffectRef){POKEMON_SOURCE_EFFECT_MOVE,
            POKEMON_GEN3_MOVE_SPORE}, 1, &applied) == POKEMON_OK);
    assert(!applied);
    assert(battle.sides[1].state[0].status.kind == POKEMON_STATUS_NONE);
    assert(draw_label_count(&battle, POKEMON_DRAW_SLEEP_DURATION) == sleep_draws);
    assert(handler_id_count(&battle, POKEMON_GEN3_HANDLER_UPROAR_SET_STATUS) == 1);

    applied = 1;
    assert(pokemon_set_status(
        &battle, (PokemonEntityRef){POKEMON_ENTITY_POKEMON, 0, 0},
        POKEMON_STATUS_SLEEP,
        (PokemonEntityRef){POKEMON_ENTITY_POKEMON, 1, 0},
        (PokemonSourceEffectRef){POKEMON_SOURCE_EFFECT_MOVE,
            POKEMON_GEN3_MOVE_SPORE}, 1, &applied) == POKEMON_OK);
    assert(!applied);
    assert(battle.sides[0].state[0].status.kind == POKEMON_STATUS_NONE);
    assert(draw_label_count(&battle, POKEMON_DRAW_SLEEP_DURATION) == sleep_draws);

    assert(pokemon_set_status(
        &battle, (PokemonEntityRef){POKEMON_ENTITY_POKEMON, 1, 0},
        POKEMON_STATUS_POISON,
        (PokemonEntityRef){POKEMON_ENTITY_POKEMON, 0, 0},
        (PokemonSourceEffectRef){POKEMON_SOURCE_EFFECT_MOVE,
            POKEMON_GEN3_MOVE_POISONPOWDER}, 1, &applied) == POKEMON_OK);
    assert(applied);
    assert(battle.sides[1].state[0].status.kind == POKEMON_STATUS_POISON);

    /* The inherited residual fallback is unreachable through legal choices,
     * but remains a generated condition program: a constructed Struggle last
     * move silently releases the lock without dispatching End. */
    battle.sides[0].state[0].last_move_id = POKEMON_GEN3_MOVE_STRUGGLE;
    size_t traces_before = battle.condition_trace_count;
    size_t ends_before = handler_id_count(
        &battle, POKEMON_GEN3_HANDLER_UPROAR_END);
    PokemonEventFrame residual;
    assert(pokemon_run_event(&battle, &(PokemonEventInput){
        .event = POKEMON_HANDLER_EVENT_RESIDUAL,
        .source = {POKEMON_ENTITY_POKEMON, 0, 0},
        .target_side = 0, .target_slot = 0,
        .source_effect = {POKEMON_SOURCE_EFFECT_CONDITION,
            POKEMON_GEN3_CONDITION_VOLATILE_UPROAR},
        .relay = {.kind = POKEMON_RELAY_UNDEFINED},
    }, &residual) == POKEMON_OK);
    assert(test_volatile_index(
        &battle.sides[0].state[0], POKEMON_VOLATILE_UPROAR) < 0);
    assert(handler_id_count(&battle, POKEMON_GEN3_HANDLER_UPROAR_END) ==
        ends_before);
    assert(battle.condition_trace_count == traces_before + 1);
    assert(battle.condition_traces[traces_before].operation ==
        POKEMON_CONDITION_REMOVE);
    assert(battle.condition_traces[traces_before].reason ==
        POKEMON_CONDITION_REASON_HANDLER);

    /* Protect cancels before the move-owned wake/install callback. */
    init.initial_status[1][0] = POKEMON_STATUS_NONE;
    init.teams[1].members[0].move_ids[0] = POKEMON_GEN3_MOVE_PROTECT;
    init.teams[1].members[0].stats[5] = 400;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(test_volatile_index(
        &battle.sides[0].state[0], POKEMON_VOLATILE_UPROAR) < 0);
    assert(draw_label_count(&battle, POKEMON_DRAW_UPROAR_DURATION) == 0);
    assert(pokemon_battle_check_invariants(&battle));

    /* The move-owned TryHit program clears every living active in canonical
     * side order. This constructed state is unreachable through an ordinary
     * selected action because sleep's BeforeMove gate would stop the user. */
    init.teams[1].members[0].move_ids[0] = POKEMON_GEN3_MOVE_SPLASH;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    size_t sleep_before = battle.condition_trace_count;
    for (size_t side = 0; side < POKEMON_SIDES; side++) {
        applied = 0;
        assert(pokemon_set_status(
            &battle, (PokemonEntityRef){POKEMON_ENTITY_POKEMON,
                (uint8_t)side, 0}, POKEMON_STATUS_SLEEP,
            (PokemonEntityRef){POKEMON_ENTITY_POKEMON,
                (uint8_t)(1u - side), 0},
            (PokemonSourceEffectRef){POKEMON_SOURCE_EFFECT_MOVE,
                POKEMON_GEN3_MOVE_SPORE}, 1, &applied) == POKEMON_OK);
        assert(applied);
    }
    const PokemonMoveData *uproar_move = NULL;
    for (size_t i = 0; i < battle.data->move_count; i++) {
        if (battle.data->moves[i].id == POKEMON_GEN3_MOVE_UPROAR) {
            uproar_move = &battle.data->moves[i];
            break;
        }
    }
    assert(uproar_move != NULL);
    size_t effects_before = battle.effect_trace_count;
    PokemonEventFrame try_hit;
    assert(pokemon_run_event(&battle, &(PokemonEventInput){
        .event = POKEMON_HANDLER_EVENT_TRY_HIT,
        .source = {POKEMON_ENTITY_POKEMON, 0, 0},
        .target_side = 1, .target_slot = 0,
        .source_effect = {POKEMON_SOURCE_EFFECT_MOVE,
            POKEMON_GEN3_MOVE_UPROAR},
        .relay = {.kind = POKEMON_RELAY_BOOLEAN, .value.boolean = 1},
        .context_kind = POKEMON_EVENT_CONTEXT_MOVE,
        .context.move = {.move = uproar_move},
        .include_move_self = 1,
    }, &try_hit) == POKEMON_OK);
    assert(battle.sides[0].state[0].status.kind == POKEMON_STATUS_NONE);
    assert(battle.sides[1].state[0].status.kind == POKEMON_STATUS_NONE);
    assert(battle.condition_trace_count == sleep_before + 4);
    assert(battle.condition_traces[sleep_before + 2].operation ==
        POKEMON_CONDITION_REMOVE);
    assert(battle.condition_traces[sleep_before + 2].side == 0);
    assert(battle.condition_traces[sleep_before + 3].operation ==
        POKEMON_CONDITION_REMOVE);
    assert(battle.condition_traces[sleep_before + 3].side == 1);
    assert(battle.effect_trace_count == effects_before + 2);
    assert(battle.effect_traces[effects_before].kind ==
        POKEMON_EFFECT_CURE_STATUS);
    assert(battle.effect_traces[effects_before].target_side == 0);
    assert(battle.effect_traces[effects_before + 1].kind ==
        POKEMON_EFFECT_CURE_STATUS);
    assert(battle.effect_traces[effects_before + 1].target_side == 1);

    /* The generated wake opcode is admitted only for a move-owned source-
     * scoped TryHit handler and a nonempty valid status mask. Bundle
     * rejection is transactional and consumes no PRNG. */
    PokemonHandlerOp invalid_programs[
        POKEMON_GEN3_SLICE_DATA.handler_program_count];
    memcpy(invalid_programs, POKEMON_GEN3_SLICE_DATA.handler_programs,
        sizeof(invalid_programs));
    uint8_t found_uproar_try_hit = 0;
    for (size_t i = 0; i < POKEMON_GEN3_SLICE_DATA.handler_count; i++) {
        const PokemonHandlerDescriptor *descriptor =
            &POKEMON_GEN3_SLICE_DATA.handlers[i];
        if (descriptor->id != POKEMON_GEN3_HANDLER_UPROAR_TRY_HIT) continue;
        invalid_programs[descriptor->program_offset].argument = UINT32_C(1) << 31;
        found_uproar_try_hit = 1;
    }
    assert(found_uproar_try_hit);
    PokemonData invalid_data = POKEMON_GEN3_SLICE_DATA;
    invalid_data.handler_programs = invalid_programs;
    PokemonResolvedBundle invalid_bundle = POKEMON_GEN3_OU_BUNDLE;
    invalid_bundle.data = &invalid_data;
    init.bundle = &invalid_bundle;
    PokemonBattle untouched;
    memset(&untouched, 0x5a, sizeof(untouched));
    PokemonBattle before = untouched;
    assert(pokemon_battle_init(&untouched, &init) ==
        POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&untouched, &before, sizeof(untouched)) == 0);
}

static void test_delayed_slot_condition_family(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_ALAKAZAM, POKEMON_GEN3_MOVE_FUTURESIGHT,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[0].members[0].move_ids[1] = POKEMON_GEN3_MOVE_DOOMDESIRE;
    init.teams[1].members[0].stats[0] = 1000;
    init.teams[1].members[0].stats[2] = 300;
    init.teams[1].members[0].stats[4] = 300;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].slot_condition_count[0] == 1);
    const PokemonSlotConditionState *future =
        &battle.sides[1].slot_conditions[0][0];
    assert(future->descriptor_id == POKEMON_GEN3_CONDITION_SLOT_FUTUREMOVE);
    assert(future->semantic_kind == POKEMON_SLOT_CONDITION_FUTURE_MOVE);
    assert(future->duration == 2);
    assert(future->payload.delayed_move.move_id ==
        POKEMON_GEN3_MOVE_FUTURESIGHT);
    assert(future->payload.delayed_move.fixed_damage > 0);
    assert(draw_label_count(&battle, POKEMON_DRAW_DAMAGE_ROLL) == 1);
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 0);
    assert(pokemon_battle_check_invariants(&battle));

    /* Future Sight and Doom Desire share one slot key. Rejection happens
     * before damage snapshotting, so the rejected cast owns no PRNG draw. */
    choices[0] = move(1);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].slot_condition_count[0] == 1);
    assert(battle.sides[1].slot_conditions[0][0].duration == 1);
    assert(battle.sides[1].slot_conditions[0][0].payload.delayed_move.move_id ==
        POKEMON_GEN3_MOVE_FUTURESIGHT);
    assert(draw_label_count(&battle, POKEMON_DRAW_DAMAGE_ROLL) == 0);
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 0);

    choices[0] = move(0);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].slot_condition_count[0] == 0);
    assert(draw_label_count(&battle, POKEMON_DRAW_DAMAGE_ROLL) == 0);
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 1);
    assert(pokemon_battle_check_invariants(&battle));

    init = condition_init(
        POKEMON_GEN3_SPECIES_VAPOREON, POKEMON_GEN3_MOVE_WISH,
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[0].members[1] = make_set(
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SPLASH,
        700, 100, 100, 100, 100, 50);
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    battle.sides[0].state[1].hp = 100;
    choices[0] = move(0);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].slot_condition_count[0] == 1);
    assert(battle.sides[0].slot_conditions[0][0].duration == 1);
    assert(draw_label_count(&battle, POKEMON_DRAW_DAMAGE_ROLL) == 0);
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 0);

    choices[0] = switch_to(1);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].active == 1);
    assert(battle.sides[0].state[1].hp == 450);
    assert(battle.sides[0].slot_condition_count[0] == 0);
    assert(draw_label_count(&battle, POKEMON_DRAW_DAMAGE_ROLL) == 0);
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 0);
    assert(pokemon_battle_check_invariants(&battle));

    /* A lethal delayed hit owns its faint drain even though it runs outside
     * the ordinary move-action drain point. */
    init = condition_init(
        POKEMON_GEN3_SPECIES_ALAKAZAM, POKEMON_GEN3_MOVE_FUTURESIGHT,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_AROMATHERAPY);
    init.team_sizes[0] = 1;
    init.team_sizes[1] = 1;
    init.teams[0].members[0].move_ids[1] = POKEMON_GEN3_MOVE_SPLASH;
    choices[0] = move(0);
    choices[1] = move(0);
    uint16_t delayed_hit_tail = 0;
    for (uint16_t tail = 1; tail < 2048 && delayed_hit_tail == 0; tail++) {
        init.seed[3] = tail;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        battle.sides[1].state[0].hp = 1;
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        choices[0] = move(1);
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        if (battle.terminal) delayed_hit_tail = tail;
        choices[0] = move(0);
    }
    assert(delayed_hit_tail != 0);
    assert(battle.terminal);
    assert(battle.winner == 0);
    assert(battle.sides[1].state[0].fainted);
    assert(battle.sides[1].state[0].last_attacked_by.present);
    assert(battle.sides[1].state[0].last_attacked_by.move_id ==
        POKEMON_GEN3_MOVE_FUTURESIGHT);
    assert(battle.sides[1].slot_condition_count[0] == 0);
    assert(pokemon_battle_check_invariants(&battle));

    /* With a bench, the same damage owner projects and accepts forced
     * replacement without rebuilding the already-completed residual queue. */
    init.teams[1].members[1] = make_set(
        POKEMON_GEN3_SPECIES_SNORLAX, POKEMON_GEN3_MOVE_PROTECT,
        461, 256, 166, 166, 256, 96);
    init.team_sizes[1] = 2;
    init.seed[3] = delayed_hit_tail;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    battle.sides[1].state[0].hp = 1;
    choices[0] = move(0);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    choices[0] = move(1);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(!battle.terminal);
    assert(battle.request.kind[1] == POKEMON_REQUEST_SWITCH);
    assert(battle.turn_suspended == POKEMON_TURN_SUSPENDED_AFTER_RESIDUAL);
    PokemonChoice replacement[POKEMON_SIDES] = {
        wait_choice(), switch_to(1),
    };
    assert(pokemon_battle_step(&battle, replacement) == POKEMON_OK);
    assert(battle.sides[1].active == 1);
    assert(battle.turn_suspended == POKEMON_TURN_NOT_SUSPENDED);
    assert(battle.sides[1].state[0].last_attacked_by.present);
    assert(battle.request.kind[0] == POKEMON_REQUEST_MOVE);
    assert(battle.request.kind[1] == POKEMON_REQUEST_MOVE);
    assert(pokemon_battle_check_invariants(&battle));
}

static void test_color_change_effective_type_product(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_WINGATTACK,
        POKEMON_GEN3_SPECIES_KECLEON, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[0].members[0].move_ids[1] = POKEMON_GEN3_MOVE_EARTHQUAKE;
    init.teams[0].members[0].move_ids[2] = POKEMON_GEN3_MOVE_SPLASH;
    init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_COLORCHANGE;
    init.teams[1].members[0].stats[0] = 500;
    init.teams[1].members[0].stats[2] = 300;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    PokemonMutable *kecleon = &battle.sides[1].state[0];
    assert(kecleon->effective_type_count == 1);
    assert(kecleon->effective_types[0] == POKEMON_GEN3_TYPE_NORMAL);

    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(kecleon->effective_type_count == 1);
    assert(kecleon->effective_types[0] == POKEMON_GEN3_TYPE_FLYING);
    uint16_t hp = kecleon->hp;
    choices[0] = move(1);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(kecleon->hp == hp);
    assert(kecleon->effective_types[0] == POKEMON_GEN3_TYPE_FLYING);

    choices[0] = move(2);
    choices[1] = switch_to(1);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    choices[1] = switch_to(0);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(kecleon->effective_type_count == 1);
    assert(kecleon->effective_types[0] == POKEMON_GEN3_TYPE_NORMAL);
}

static void test_locked_move_action_lock_and_fatigue(void) {
    static const uint16_t moves[] = {
        POKEMON_GEN3_MOVE_OUTRAGE, POKEMON_GEN3_MOVE_PETALDANCE,
        POKEMON_GEN3_MOVE_THRASH,
    };
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    for (size_t move_index = 0;
         move_index < sizeof(moves) / sizeof(moves[0]); move_index++) {
        PokemonBattle duration_cases[2];
        uint8_t found[2] = {0, 0};
        for (uint16_t seed = 1; seed != 0 && (!found[0] || !found[1]); seed++) {
            PokemonBattleInit init = locked_move_init(moves[move_index]);
            init.seed[0] = seed;
            PokemonBattle candidate;
            assert(pokemon_battle_init(&candidate, &init) == POKEMON_OK);
            uint8_t initial_pp = candidate.sides[0].state[0].pp[0];
            int step_status = pokemon_battle_step(&candidate, choices);
            if (step_status != POKEMON_OK) fprintf(stderr,
                "locked move %u seed %u status %d\n", moves[move_index], seed,
                step_status);
            assert(step_status == POKEMON_OK);
            int lock_index = test_volatile_index(
                &candidate.sides[0].state[0], POKEMON_VOLATILE_LOCKED_MOVE);
            assert(lock_index >= 0);
            PokemonVolatileState *lock =
                &candidate.sides[0].state[0].volatiles[lock_index];
            assert(lock->payload.locked_move.move_id == moves[move_index]);
            assert(lock->duration == 1);
            assert(lock->payload.locked_move.true_duration == 1 ||
                lock->payload.locked_move.true_duration == 2);
            size_t duration_slot = lock->payload.locked_move.true_duration - 1;
            if (!found[duration_slot]) {
                duration_cases[duration_slot] = candidate;
                found[duration_slot] = initial_pp;
            }
        }
        assert(found[0] && found[1]);
        for (size_t duration_slot = 0; duration_slot < 2; duration_slot++) {
            PokemonBattle battle = duration_cases[duration_slot];
            assert(draw_label_count(
                &battle, POKEMON_DRAW_LOCKED_MOVE_DURATION) == 1);
            assert(battle.request.legal_moves[0] == 1);
            assert(battle.request.legal_switches[0] == 0);
            assert(battle.sides[0].state[0].pp[0] ==
                (uint8_t)(found[duration_slot] - 1));
            assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
            assert(battle.sides[0].state[0].pp[0] ==
                (uint8_t)(found[duration_slot] - 1));
            int lock_index = test_volatile_index(
                &battle.sides[0].state[0], POKEMON_VOLATILE_LOCKED_MOVE);
            if (duration_slot == 0) {
                assert(lock_index < 0);
                assert(test_volatile_index(
                    &battle.sides[0].state[0], POKEMON_VOLATILE_CONFUSION) >= 0);
                assert(draw_label_count(
                    &battle, POKEMON_DRAW_CONFUSION_DURATION) == 1);
            } else {
                assert(lock_index >= 0);
                assert(battle.sides[0].state[0].volatiles[lock_index]
                    .payload.locked_move.true_duration == 1);
                assert(battle.request.legal_moves[0] == 1);
                assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
                assert(test_volatile_index(
                    &battle.sides[0].state[0], POKEMON_VOLATILE_LOCKED_MOVE) < 0);
                assert(test_volatile_index(
                    &battle.sides[0].state[0], POKEMON_VOLATILE_CONFUSION) >= 0);
                assert(battle.sides[0].state[0].pp[0] ==
                    (uint8_t)(found[duration_slot] - 1));
            }
        }
    }

    /* A sleeping holder is released by Residual without running End and
     * therefore without fatigue confusion or a confusion-duration draw. */
    PokemonBattleInit init = locked_move_init(POKEMON_GEN3_MOVE_OUTRAGE);
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    PokemonMutable *holder = &battle.sides[0].state[0];
    holder->volatiles[0] = (PokemonVolatileState){
        .kind = POKEMON_VOLATILE_LOCKED_MOVE,
        .descriptor_id = POKEMON_GEN3_CONDITION_VOLATILE_LOCKEDMOVE,
        .duration = 2, .state_generation = 1,
        .effect_order = ++battle.next_holder_effect_order,
        .source = {POKEMON_ENTITY_POKEMON, 0, 0},
        .source_effect = {POKEMON_SOURCE_EFFECT_MOVE,
            POKEMON_GEN3_MOVE_OUTRAGE},
        .payload.locked_move = {POKEMON_GEN3_MOVE_OUTRAGE, 3},
    };
    holder->volatile_count = 1;
    holder->status = (PokemonStatusState){
        .kind = POKEMON_STATUS_SLEEP,
        .descriptor_id = POKEMON_GEN3_CONDITION_STATUS_SLP,
        .state_generation = 1,
        .effect_order = ++battle.next_holder_effect_order,
        .state.sleep = {.time = 2},
    };
    battle.request.legal_moves[0] = 1;
    battle.request.legal_switches[0] = 0;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(test_volatile_index(holder, POKEMON_VOLATILE_LOCKED_MOVE) < 0);
    assert(test_volatile_index(holder, POKEMON_VOLATILE_CONFUSION) < 0);
    assert(draw_label_count(&battle, POKEMON_DRAW_CONFUSION_DURATION) == 0);

    /* Failed initial applications never create the self lock. */
    init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_THRASH,
        POKEMON_GEN3_SPECIES_GENGAR, POKEMON_GEN3_MOVE_SPLASH);
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(test_volatile_index(&battle.sides[0].state[0],
        POKEMON_VOLATILE_LOCKED_MOVE) < 0);

    init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_OUTRAGE,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_PROTECT);
    init.teams[0].members[0].stats[5] = 100;
    init.teams[1].members[0].stats[5] = 300;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(test_volatile_index(&battle.sides[0].state[0],
        POKEMON_VOLATILE_LOCKED_MOVE) < 0);

    /* A successful KO installs the lock before replacement is requested. */
    init = locked_move_init(POKEMON_GEN3_MOVE_OUTRAGE);
    init.initial_hp[1][0] = 1;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.request.kind[1] == POKEMON_REQUEST_SWITCH);
    assert(test_volatile_index(&battle.sides[0].state[0],
        POKEMON_VOLATILE_LOCKED_MOVE) >= 0);

    /* Ordinary switch and faint cleanup erase the condition without End. */
    holder = &battle.sides[0].state[0];
    uint8_t confusion_draws = (uint8_t)draw_label_count(
        &battle, POKEMON_DRAW_CONFUSION_DURATION);
    battle.request.kind[0] = POKEMON_REQUEST_SWITCH;
    battle.request.kind[1] = POKEMON_REQUEST_WAIT;
    battle.request.required_sides = 1;
    battle.request.legal_moves[0] = 0;
    battle.request.legal_switches[0] = 2;
    PokemonChoice switch_choices[POKEMON_SIDES] = {switch_to(1), wait_choice()};
    assert(pokemon_battle_step(&battle, switch_choices) == POKEMON_OK);
    assert(test_volatile_index(holder, POKEMON_VOLATILE_LOCKED_MOVE) < 0);
    assert(draw_label_count(&battle, POKEMON_DRAW_CONFUSION_DURATION) == 0 ||
        confusion_draws != 0);

    init = locked_move_init(POKEMON_GEN3_MOVE_OUTRAGE);
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    holder = &battle.sides[0].state[0];
    holder->volatiles[0] = (PokemonVolatileState){
        .kind = POKEMON_VOLATILE_LOCKED_MOVE,
        .descriptor_id = POKEMON_GEN3_CONDITION_VOLATILE_LOCKEDMOVE,
        .duration = 1, .state_generation = 1,
        .effect_order = ++battle.next_holder_effect_order,
        .source = {POKEMON_ENTITY_POKEMON, 0, 0},
        .source_effect = {POKEMON_SOURCE_EFFECT_MOVE,
            POKEMON_GEN3_MOVE_OUTRAGE},
        .payload.locked_move = {POKEMON_GEN3_MOVE_OUTRAGE, 1},
    };
    holder->volatile_count = 1;
    uint16_t applied = 0;
    assert(pokemon_apply_direct_damage(&battle, &(PokemonDirectDamageRequest){
        .source = {POKEMON_ENTITY_POKEMON, 1, 0},
        .target = {POKEMON_ENTITY_POKEMON, 0, 0},
        .source_effect = {POKEMON_SOURCE_EFFECT_MOVE, POKEMON_GEN3_MOVE_STRENGTH},
        .amount = holder->hp,
    }, &applied) == POKEMON_OK);
    assert(holder->fainted && holder->volatile_count == 0);
    assert(draw_label_count(&battle, POKEMON_DRAW_CONFUSION_DURATION) == 0);
}

static void test_move_invocation_stack_foundation(void) {
    PokemonBattleInit init = battle_init();
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    uint8_t left_pp = battle.sides[0].state[0].pp[0];
    uint8_t right_pp = battle.sides[1].state[0].pp[0];
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.move_frame_depth == 0);
    assert(battle.move_invocation_count == 2);
    for (size_t i = 0; i < battle.move_invocation_count; i++) {
        const PokemonMoveInvocationTrace *trace = &battle.move_invocations[i];
        assert(trace->invocation.entry == POKEMON_MOVE_ENTRY_SELECTED);
        assert(trace->invocation.invocation_id != 0);
        assert(trace->invocation.parent_invocation_id == 0);
        assert(trace->invocation.source_effect.kind == POKEMON_SOURCE_EFFECT_NONE);
        assert(trace->resolved_target.kind == POKEMON_ENTITY_POKEMON);
        assert(trace->resolved_target.side != trace->invocation.user.side);
        assert(trace->result == POKEMON_OK);
    }
    assert(battle.move_invocations[0].invocation.invocation_id !=
        battle.move_invocations[1].invocation.invocation_id);
    assert(battle.sides[0].state[0].pp[0] == (uint8_t)(left_pp - 1));
    assert(battle.sides[1].state[0].pp[0] == (uint8_t)(right_pp - 1));

    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    battle.move_frame_depth = POKEMON_MOVE_FRAME_CAPACITY;
    PokemonBattle before = battle;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_CAPACITY_EXCEEDED);
    assert(memcmp(&battle, &before, sizeof(battle)) == 0);
}

static void test_magic_coat_reflects_through_called_move_entry(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_ALAKAZAM, POKEMON_GEN3_MOVE_MAGICCOAT,
        POKEMON_GEN3_SPECIES_KINGLER, POKEMON_GEN3_MOVE_TICKLE);
    init.teams[0].members[0].stats[5] = 50;
    init.teams[1].members[0].stats[5] = 200;
    PokemonBattle left;
    PokemonBattle right;
    assert(pokemon_battle_init(&left, &init) == POKEMON_OK);
    assert(pokemon_battle_init(&right, &init) == POKEMON_OK);
    uint8_t magic_pp = left.sides[0].state[0].pp[0];
    uint8_t tickle_pp = left.sides[1].state[0].pp[0];
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_step(&left, choices) == POKEMON_OK);
    assert(pokemon_battle_step(&right, choices) == POKEMON_OK);
    assert(memcmp(left.seed, right.seed, sizeof(left.seed)) == 0);
    assert(left.move_invocation_count == right.move_invocation_count);
    assert(accuracy_protect_owned_state_equal(&left, &right));
    assert(left.sides[0].state[0].boosts[POKEMON_STAT_ATK] == 0);
    assert(left.sides[0].state[0].boosts[POKEMON_STAT_DEF] == 0);
    assert(left.sides[1].state[0].boosts[POKEMON_STAT_ATK] == -1);
    assert(left.sides[1].state[0].boosts[POKEMON_STAT_DEF] == -1);
    assert(memcmp(left.sides[0].state[0].boosts,
        right.sides[0].state[0].boosts,
        sizeof(left.sides[0].state[0].boosts)) == 0);
    assert(memcmp(left.sides[1].state[0].boosts,
        right.sides[1].state[0].boosts,
        sizeof(left.sides[1].state[0].boosts)) == 0);
    assert(left.sides[0].state[0].pp[0] == (uint8_t)(magic_pp - 1));
    assert(left.sides[1].state[0].pp[0] == (uint8_t)(tickle_pp - 1));
    assert(left.move_invocation_count == 3);
    assert(left.move_invocations[0].invocation.entry == POKEMON_MOVE_ENTRY_SELECTED);
    assert(left.move_invocations[1].invocation.entry == POKEMON_MOVE_ENTRY_SELECTED);
    assert(left.move_invocations[2].invocation.entry == POKEMON_MOVE_ENTRY_CALLED);
    assert(left.move_invocations[2].invocation.parent_invocation_id ==
        left.move_invocations[1].invocation.invocation_id);
    assert(left.move_invocations[2].invocation.has_bounced == 1);
    assert(left.move_invocations[2].invocation.source_effect.kind ==
        POKEMON_SOURCE_EFFECT_CONDITION);
    assert(left.move_invocations[2].invocation.source_effect.id ==
        POKEMON_GEN3_CONDITION_VOLATILE_MAGICCOAT);
    assert(left.move_invocations[2].resolved_target.side == 1);
    assert(left.move_frame_depth == 0);
    assert(left.sides[0].state[0].volatile_count == 0);
    assert(left.handler_count == 1);
    assert(left.handlers[0].handler.descriptor.id == POKEMON_GEN3_HANDLER_MAGIC_COAT);
    assert(left.event_frames[0].cancellation == POKEMON_EVENT_CANCEL_NULL);
    assert(left.event_frames[1].cancellation == POKEMON_EVENT_CANCEL_NONE);
    assert(left.event_frames[1].source_effect.kind ==
        POKEMON_SOURCE_EFFECT_CONDITION);
    assert(left.event_frames[1].source_effect.id ==
        POKEMON_GEN3_CONDITION_VOLATILE_MAGICCOAT);

    /* A second installed reflector observes the reflected child, but the
     * invocation-local bounced bit prevents a second re-entry. */
    assert(pokemon_battle_init(&left, &init) == POKEMON_OK);
    left.sides[1].state[0].volatiles[0] = (PokemonVolatileState){
        .kind = POKEMON_VOLATILE_MAGIC_COAT,
        .descriptor_id = POKEMON_GEN3_CONDITION_VOLATILE_MAGICCOAT,
        .duration = 1, .state_generation = 1,
        .effect_order = ++left.next_holder_effect_order,
    };
    left.sides[1].state[0].volatile_count = 1;
    assert(pokemon_battle_check_invariants(&left));
    assert(pokemon_battle_step(&left, choices) == POKEMON_OK);
    assert(left.move_invocation_count == 3);
    assert(left.handler_count == 2);
    assert(left.sides[1].state[0].boosts[POKEMON_STAT_ATK] == -1);
    assert(left.sides[1].state[0].boosts[POKEMON_STAT_DEF] == -1);
}

static void test_mirror_move_provenance_and_called_move_entry(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SKARMORY, POKEMON_GEN3_MOVE_MIRRORMOVE,
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_GROWL);
    init.teams[0].members[0].stats[5] = 50;
    init.teams[1].members[0].stats[5] = 300;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    uint8_t mirror_pp = battle.sides[0].state[0].pp[0];
    uint8_t growl_pp = battle.sides[1].state[0].pp[0];
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].boosts[POKEMON_STAT_ATK] == -1);
    assert(battle.sides[1].state[0].boosts[POKEMON_STAT_ATK] == -1);
    assert(battle.sides[0].state[0].pp[0] == (uint8_t)(mirror_pp - 1));
    assert(battle.sides[1].state[0].pp[0] == (uint8_t)(growl_pp - 1));
    assert(battle.sides[0].state[0].last_move_id ==
        POKEMON_GEN3_MOVE_MIRRORMOVE);
    assert(battle.sides[1].state[0].last_move_id == POKEMON_GEN3_MOVE_GROWL);
    assert(battle.sides[0].state[0].last_attacked_by.present);
    assert(battle.sides[0].state[0].last_attacked_by.move_id ==
        POKEMON_GEN3_MOVE_GROWL);
    assert(battle.sides[0].state[0].last_attacked_by.source.side == 1);
    assert(!battle.sides[0].state[0].last_attacked_by.this_turn);
    assert(battle.move_invocation_count == 3);
    assert(battle.move_invocations[2].invocation.entry ==
        POKEMON_MOVE_ENTRY_CALLED);
    assert(battle.move_invocations[2].invocation.move_id ==
        POKEMON_GEN3_MOVE_GROWL);
    assert(battle.move_invocations[2].invocation.source_effect.kind ==
        POKEMON_SOURCE_EFFECT_MOVE);
    assert(battle.move_invocations[2].invocation.source_effect.id ==
        POKEMON_GEN3_MOVE_MIRRORMOVE);
    assert(battle.move_invocations[2].invocation.parent_invocation_id ==
        battle.move_invocations[1].invocation.invocation_id);

    /* No attackedBy record is an ordinary failed move, not a guessed call. */
    init = condition_init(
        POKEMON_GEN3_SPECIES_SKARMORY, POKEMON_GEN3_MOVE_MIRRORMOVE,
        POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[0].members[0].stats[5] = 300;
    init.teams[1].members[0].stats[5] = 50;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.move_invocation_count == 2);
    assert(battle.sides[0].state[0].last_attacked_by.present == 0);

    /* The record survives a turn, but not loss of the source's current move. */
    init = condition_init(
        POKEMON_GEN3_SPECIES_SKARMORY, POKEMON_GEN3_MOVE_MIRRORMOVE,
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_GROWL);
    init.teams[0].members[0].stats[5] = 50;
    init.teams[1].members[0].stats[5] = 300;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    test_replace_base_move(
        &battle, 1, 0, 0, POKEMON_GEN3_MOVE_SPLASH, 64);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.move_invocation_count == 2);
    assert(pokemon_battle_check_invariants(&battle));
}

static void test_substitute_family(void) {
    PokemonBattleInit init = battle_init();
    init.teams[0].members[0] = make_set(
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SUBSTITUTE,
        301, 200, 150, 150, 150, 300);
    init.teams[1].members[0] = make_set(
        POKEMON_GEN3_SPECIES_MACHOP, POKEMON_GEN3_MOVE_SPLASH,
        300, 200, 150, 150, 150, 100);
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    PokemonChoice choices[2] = {move(0), move(0)};
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    PokemonMutable *holder = &battle.sides[0].state[0];
    assert(holder->hp == 226);
    int sub = -1;
    for (size_t i = 0; i < holder->volatile_count; i++) {
        if (holder->volatiles[i].kind == POKEMON_VOLATILE_SUBSTITUTE) sub = (int)i;
    }
    assert(sub >= 0 && holder->volatiles[sub].payload.substitute.hp == 75);
    assert(pokemon_battle_check_invariants(&battle));

    /* Duplicate creation neither pays HP nor refreshes the payload. */
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(holder->hp == 226);
    assert(holder->volatiles[sub].payload.substitute.hp == 75);
    assert(battle.event_count >= 1);
    assert(battle.events[0].kind == POKEMON_EVENT_MOVE);
    assert(battle.events[0].target_side == 0);

    /* A foe primary boost operation is consumed before mutation. */
    test_replace_base_move(
        &battle, 1, 0, 0, POKEMON_GEN3_MOVE_GROWL, 64);
    choices[0] = move(0);
    choices[1] = move(0);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(holder->boosts[POKEMON_STAT_ATK] == 0);

    /* Damage is capped to remaining Substitute HP and never spills. */
    test_replace_base_move(
        &battle, 0, 0, 0, POKEMON_GEN3_MOVE_SPLASH, 64);
    test_replace_base_move(
        &battle, 1, 0, 0, POKEMON_GEN3_MOVE_STRENGTH, 24);
    uint16_t real_hp = holder->hp;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(holder->hp == real_hp);
    assert(battle.hit_trace_count >= 1);
    assert(battle.hit_traces[battle.hit_trace_count - 1].kind ==
        POKEMON_HIT_SUBSTITUTE);
    assert(battle.hit_traces[battle.hit_trace_count - 1].after_sub_damage_dispatched == 1);
    sub = -1;
    int broken = -1;
    for (size_t i = 0; i < holder->volatile_count; i++) {
        if (holder->volatiles[i].kind == POKEMON_VOLATILE_SUBSTITUTE) sub = (int)i;
        if (holder->volatiles[i].kind == POKEMON_VOLATILE_SUBSTITUTE_BROKEN) broken = (int)i;
    }
    assert(sub < 0);
    assert(broken >= 0);
    assert(holder->volatiles[broken].payload.substitute_broken.breaking_move_id ==
        POKEMON_GEN3_MOVE_STRENGTH);
    assert(pokemon_battle_check_invariants(&battle));

    /* Ordinary switching clears both live and inert marker volatiles. */
    choices[0] = switch_to(1);
    choices[1] = move(0);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].volatile_count == 0);

    /* Exact-cost HP is an honest failure boundary. */
    init.initial_hp[0][0] = 75;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    choices[0] = move(0);
    choices[1] = move(0);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].hp == 75);
    assert(battle.sides[0].state[0].volatile_count == 0);
    assert(battle.event_count >= 1);
    assert(battle.events[0].kind == POKEMON_EVENT_MOVE);
    assert(battle.events[0].target_side == 0);

    /* Below-cost and max-HP-one users are rejected without mutation. */
    init.initial_hp[0][0] = 74;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].hp == 74);
    assert(battle.sides[0].state[0].volatile_count == 0);
    init.teams[0].members[0].stats[0] = 1;
    init.initial_hp[0][0] = 1;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].hp == 1);
    assert(battle.sides[0].state[0].volatile_count == 0);

    /* Creation removes partial trapping at the move-effect boundary. */
    init.teams[0].members[0].stats[0] = 301;
    init.initial_hp[0][0] = 0;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    holder = &battle.sides[0].state[0];
    holder->volatiles[0] = (PokemonVolatileState){
        .kind = POKEMON_VOLATILE_PARTIALLY_TRAPPED,
        .descriptor_id = POKEMON_GEN3_CONDITION_VOLATILE_PARTIALLYTRAPPED,
        .duration = 3, .state_generation = 1,
        .effect_order = ++battle.next_holder_effect_order,
    };
    holder->volatile_count = 1;
    assert(pokemon_battle_check_invariants(&battle));
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(holder->volatile_count == 1);
    assert(holder->volatiles[0].kind == POKEMON_VOLATILE_SUBSTITUTE);

    /* Switching also clears a live Substitute, not only its inert marker. */
    choices[0] = switch_to(1);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].volatile_count == 0);

    /* A full, valid volatile set makes creation fail transactionally. */
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    holder = &battle.sides[0].state[0];
    holder->volatiles[0] = (PokemonVolatileState){
        .kind = POKEMON_VOLATILE_PROTECT,
        .descriptor_id = POKEMON_GEN3_CONDITION_VOLATILE_PROTECT,
        .duration = 1, .state_generation = 1,
        .effect_order = ++battle.next_holder_effect_order,
    };
    holder->volatiles[1] = (PokemonVolatileState){
        .kind = POKEMON_VOLATILE_STALL,
        .descriptor_id = POKEMON_GEN3_CONDITION_VOLATILE_STALL,
        .duration = 1, .counter = 2, .state_generation = 1,
        .effect_order = ++battle.next_holder_effect_order,
    };
    holder->volatiles[2] = (PokemonVolatileState){
        .kind = POKEMON_VOLATILE_SUBSTITUTE_BROKEN,
        .descriptor_id = POKEMON_GEN3_CONDITION_VOLATILE_SUBSTITUTEBROKEN,
        .state_generation = 1,
        .effect_order = ++battle.next_holder_effect_order,
        .payload.substitute_broken = {
            .breaking_move_id = POKEMON_GEN3_MOVE_STRENGTH,
        },
    };
    holder->volatiles[3] = (PokemonVolatileState){
        .kind = POKEMON_VOLATILE_PARTIALLY_TRAPPED,
        .descriptor_id = POKEMON_GEN3_CONDITION_VOLATILE_PARTIALLYTRAPPED,
        .duration = 3, .state_generation = 1,
        .effect_order = ++battle.next_holder_effect_order,
    };
    holder->volatile_count = POKEMON_VOLATILE_CAPACITY;
    assert(pokemon_battle_check_invariants(&battle));
    PokemonBattle before = battle;
    choices[0] = move(0);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_CAPACITY_EXCEEDED);
    assert(memcmp(&battle, &before, sizeof(battle)) == 0);

    /* Recoil fainting clears both live and inert Substitute-family state. */
    init.teams[0].members[0].move_ids[1] = POKEMON_GEN3_MOVE_DOUBLEEDGE;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    choices[0] = move(0);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    holder = &battle.sides[0].state[0];
    assert(holder->volatile_count == 1);
    holder->hp = 1;
    choices[0] = move(1);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(holder->fainted == 1);
    assert(holder->volatile_count == 0);
}

static void test_substitute_blocks_primary_status_family(void) {
    static const uint16_t moves[] = {
        POKEMON_GEN3_MOVE_HYPNOSIS,
        POKEMON_GEN3_MOVE_TOXIC,
        POKEMON_GEN3_MOVE_POISONGAS,
        POKEMON_GEN3_MOVE_THUNDERWAVE,
        POKEMON_GEN3_MOVE_WILLOWISP,
    };
    for (size_t index = 0; index < sizeof(moves) / sizeof(moves[0]); index++) {
        PokemonBattleInit init = battle_init();
        memset(init.seed, 0, sizeof(init.seed));
        init.teams[0].members[0] = make_set(
            POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SUBSTITUTE,
            301, 200, 150, 150, 150, 300);
        init.teams[0].members[0].move_ids[1] = POKEMON_GEN3_MOVE_SPLASH;
        init.teams[1].members[0] = make_set(
            POKEMON_GEN3_SPECIES_MACHOP, moves[index],
            300, 200, 150, 150, 150, 100);
        PokemonBattle battle;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        PokemonMutable *target = &battle.sides[0].state[0];
        assert(target->volatile_count == 1);
        assert(target->volatiles[0].kind == POKEMON_VOLATILE_SUBSTITUTE);
        uint16_t substitute_hp = target->volatiles[0].payload.substitute.hp;

        choices[0] = move(1);
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        assert(target->status.kind == POKEMON_STATUS_NONE);
        assert(target->volatile_count == 1);
        assert(target->volatiles[0].kind == POKEMON_VOLATILE_SUBSTITUTE);
        assert(target->volatiles[0].payload.substitute.hp == substitute_hp);
        assert(handler_id_count(&battle,
            POKEMON_GEN3_HANDLER_SUBSTITUTE_TRY_PRIMARY_HIT) >= 1);
        assert(draw_label_count(&battle, POKEMON_DRAW_SLEEP_DURATION) == 0);
        assert(pokemon_battle_check_invariants(&battle));
    }
}

static const PokemonSpeciesData TEST_SPECIES[] = {
    {1, {0, 0}, 1, 100},
    {2, {0, 0}, 1, 100},
};

static uint8_t TEST_TYPE_CHART[] = {4};

static PokemonBattleInit mechanic_init(uint16_t seed_tail) {
    static PokemonData data;
    static PokemonGeneration generation;
    static PokemonFormatPolicy policy;
    static PokemonResolvedBundle bundle;
    data = (PokemonData){
        .plugin_fingerprint = POKEMON_GEN3_PLUGIN_FINGERPRINT,
        .capability_version = POKEMON_KERNEL_PLUGIN_ABI_VERSION,
        .capabilities = POKEMON_CAP_GEN3,
        .generation = 3,
        .species = TEST_SPECIES,
        .species_count = 2,
        .moves = &TEST_MOVE,
        .move_count = 1,
        .event_specs = POKEMON_GEN3_SLICE_DATA.event_specs,
        .event_spec_count = POKEMON_GEN3_SLICE_DATA.event_spec_count,
        .weather_policies = POKEMON_GEN3_SLICE_DATA.weather_policies,
        .weather_policy_count = POKEMON_GEN3_SLICE_DATA.weather_policy_count,
        .condition_catalog = POKEMON_GEN3_SLICE_DATA.condition_catalog,
        .condition_catalog_count =
            POKEMON_GEN3_SLICE_DATA.condition_catalog_count,
        .slot_condition_policies =
            POKEMON_GEN3_SLICE_DATA.slot_condition_policies,
        .slot_condition_policy_count =
            POKEMON_GEN3_SLICE_DATA.slot_condition_policy_count,
        .type_chart = TEST_TYPE_CHART,
        .type_count = 1,
    };
    generation = POKEMON_GEN3_RULES;
    generation.fallback_move_id = TEST_MOVE.id;
    generation.choice_control_policies = NULL;
    generation.choice_control_policy_count = 0;
    bundle = POKEMON_GEN3_OU_BUNDLE;
    policy = *bundle.policy;
    policy.status_clauses = NULL;
    policy.status_clause_count = 0;
    bundle.data = &data;
    bundle.rules = &generation;
    bundle.policy = &policy;
    PokemonBattleInit init = {
        .bundle = &bundle,
        .team_sizes = {2, 2},
        .seed = {1, 2, 3, seed_tail},
    };
    for (size_t side = 0; side < POKEMON_SIDES; side++) {
        for (size_t slot = 0; slot < 2; slot++) {
            init.teams[side].members[slot] = make_set(
                (uint16_t)(side + 1), 1, 500, 100, 100, 100, 100,
                (uint16_t)(side == 0 ? 200 : 100)
            );
        }
    }
    return init;
}

static void test_typed_synthetic_self_hit_damage(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_TACKLE,
        POKEMON_GEN3_SPECIES_BANETTE, POKEMON_GEN3_MOVE_SPLASH);
    PokemonMoveData synthetic = TEST_MOVE;
    synthetic.id = 0;
    synthetic.power = 40;
    PokemonDamageRequest request = {
        .mode = POKEMON_DAMAGE_MODE_SYNTHETIC_SELF_HIT,
        .source = {POKEMON_ENTITY_POKEMON, 0, 0},
        .target = {POKEMON_ENTITY_POKEMON, 0, 0},
        .move = &synthetic,
        .critical = 1,
    };
    PokemonBattle ordinary;
    assert(pokemon_battle_init(&ordinary, &init) == POKEMON_OK);
    size_t draw_start = ordinary.draw_count;
    size_t stage_start = ordinary.damage_stage_count;
    PokemonCalculatedDamage baseline;
    assert(pokemon_calculate_damage(&ordinary, &request, &baseline) == POKEMON_OK);
    assert(baseline.damage > 0 && baseline.critical == 0);
    assert(ordinary.draw_count == draw_start + 1);
    assert(ordinary.draws[draw_start].label == POKEMON_DRAW_DAMAGE_ROLL);
    assert(ordinary.damage_stage_count == stage_start);
    assert(ordinary.sides[0].state[0].hp ==
        ordinary.sides[0].sets[0].stats[0]);

    PokemonBattle burned;
    assert(pokemon_battle_init(&burned, &init) == POKEMON_OK);
    burned.sides[0].state[0].status.kind = POKEMON_STATUS_BURN;
    PokemonCalculatedDamage reduced;
    assert(pokemon_calculate_damage(&burned, &request, &reduced) == POKEMON_OK);
    assert(reduced.damage == baseline.damage);
    assert(reduced.damage_roll == baseline.damage_roll);
    assert(burned.damage_stage_count == stage_start);

    PokemonBattle guts;
    init.teams[0].members[0].ability_id = POKEMON_GEN3_ABILITY_GUTS;
    assert(pokemon_battle_init(&guts, &init) == POKEMON_OK);
    guts.sides[0].state[0].status.kind = POKEMON_STATUS_BURN;
    PokemonCalculatedDamage boosted;
    assert(pokemon_calculate_damage(&guts, &request, &boosted) == POKEMON_OK);
    assert(boosted.damage == baseline.damage);
    assert(boosted.damage_roll == baseline.damage_roll);
    assert(guts.damage_stage_count == stage_start);

    PokemonBattle huge_power;
    init.teams[0].members[0].ability_id = POKEMON_GEN3_ABILITY_HUGEPOWER;
    assert(pokemon_battle_init(&huge_power, &init) == POKEMON_OK);
    PokemonCalculatedDamage ability_ignored;
    assert(pokemon_calculate_damage(
        &huge_power, &request, &ability_ignored) == POKEMON_OK);
    assert(ability_ignored.damage == baseline.damage);
    assert(ability_ignored.damage_roll == baseline.damage_roll);

    PokemonBattle type_item;
    init.teams[0].members[0].ability_id = 0;
    init.teams[0].members[0].item_id = POKEMON_GEN3_ITEM_SILKSCARF;
    assert(pokemon_battle_init(&type_item, &init) == POKEMON_OK);
    PokemonCalculatedDamage item_ignored;
    assert(pokemon_calculate_damage(
        &type_item, &request, &item_ignored) == POKEMON_OK);
    assert(item_ignored.damage == baseline.damage);
    assert(item_ignored.damage_roll == baseline.damage_roll);

    PokemonBattle before = guts;
    request.target.side = POKEMON_SIDES;
    assert(pokemon_calculate_damage(&guts, &request, &boosted) ==
        POKEMON_INVALID_ARGUMENT);
    assert(memcmp(&guts, &before, sizeof(guts)) == 0);

    request.target.side = 0;
    guts.damage_stage_count = POKEMON_DAMAGE_STAGE_CAPACITY;
    assert(pokemon_calculate_damage(&guts, &request, &boosted) == POKEMON_OK);
    assert(guts.damage_stage_count == POKEMON_DAMAGE_STAGE_CAPACITY);

    PokemonBattle damaged;
    init = condition_init(
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_TACKLE,
        POKEMON_GEN3_SPECIES_BANETTE, POKEMON_GEN3_MOVE_SPLASH);
    assert(pokemon_battle_init(&damaged, &init) == POKEMON_OK);
    damaged.sides[0].state[0].hp = 1;
    PokemonDirectDamageRequest direct = {
        .source = {POKEMON_ENTITY_POKEMON, 0, 0},
        .target = {POKEMON_ENTITY_POKEMON, 0, 0},
        .source_effect = {POKEMON_SOURCE_EFFECT_CONDITION, 1},
        .amount = 20,
    };
    uint16_t applied = 0;
    size_t event_start = damaged.event_count;
    assert(pokemon_apply_direct_damage(&damaged, &direct, &applied) == POKEMON_OK);
    assert(applied == 1 && damaged.sides[0].state[0].hp == 0);
    assert(damaged.sides[0].state[0].fainted);
    assert(damaged.events[event_start].kind == POKEMON_EVENT_DAMAGE);
    assert(damaged.events[event_start].move_id == 0);
    assert(damaged.events[event_start + 1].kind == POKEMON_EVENT_FAINT);

    assert(pokemon_battle_init(&damaged, &init) == POKEMON_OK);
    damaged.sides[0].state[0].hp = 1;
    damaged.event_count = POKEMON_EVENT_CAPACITY - 1;
    before = damaged;
    assert(pokemon_apply_direct_damage(&damaged, &direct, &applied) ==
        POKEMON_CAPACITY_EXCEEDED);
    assert(memcmp(&damaged, &before, sizeof(damaged)) == 0);
}

static void test_confusion_primary_lifecycle_and_own_tempo(void) {
    static const uint16_t moves[] = {
        POKEMON_GEN3_MOVE_CONFUSERAY, POKEMON_GEN3_MOVE_SUPERSONIC,
        POKEMON_GEN3_MOVE_SWEETKISS,
    };
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    for (size_t move_index = 0; move_index < 3; move_index++) {
        PokemonBattleInit init = condition_init(
            POKEMON_GEN3_SPECIES_GENGAR, moves[move_index],
            POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SPLASH);
        PokemonBattle battle;
        uint8_t installed = 0;
        for (uint16_t tail = 1; tail < 256 && !installed; tail++) {
            init.seed[3] = tail;
            assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
            assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
            installed = test_volatile_index(
                &battle.sides[1].state[0], POKEMON_VOLATILE_CONFUSION) >= 0;
        }
        assert(installed);
        int index = test_volatile_index(
            &battle.sides[1].state[0], POKEMON_VOLATILE_CONFUSION);
        assert(index >= 0);
        uint8_t time = battle.sides[1].state[0].volatiles[index].payload.confusion.time;
        assert(time >= 1 && time <= 4);
        assert(draw_label_count(&battle, POKEMON_DRAW_CONFUSION_DURATION) == 1);
    }

    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_GENGAR, POKEMON_GEN3_MOVE_CONFUSERAY,
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_OWNTEMPO;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(test_volatile_index(
        &battle.sides[1].state[0], POKEMON_VOLATILE_CONFUSION) < 0);
    assert(draw_label_count(&battle, POKEMON_DRAW_CONFUSION_DURATION) == 0);

    /* A prevented selected action owns the action and damage rolls, changes
     * real HP, and consumes neither PP nor lastMove. */
    init = condition_init(
        POKEMON_GEN3_SPECIES_GENGAR, POKEMON_GEN3_MOVE_CONFUSERAY,
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SPLASH);
    uint8_t self_hit = 0;
    uint16_t self_hit_tail = 0;
    for (uint16_t tail = 1; tail < 512 && !self_hit; tail++) {
        init.seed[3] = tail;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        uint16_t hp = battle.sides[1].state[0].hp;
        uint8_t pp = battle.sides[1].state[0].pp[0];
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        self_hit = battle.sides[1].state[0].hp < hp;
        if (self_hit) {
            self_hit_tail = tail;
            assert(draw_label_count(&battle, POKEMON_DRAW_CONFUSION_ACTION) == 1);
            assert(draw_label_count(&battle, POKEMON_DRAW_DAMAGE_ROLL) == 1);
            assert(battle.sides[1].state[0].pp[0] == pp);
            assert(battle.sides[1].state[0].last_move_id == 0);
        }
    }
    assert(self_hit);

    /* Reuse the proven self-hit seed with a one-HP holder: it faints before
     * its selected move and requests replacement. */
    init.seed[3] = self_hit_tail;
    init.initial_hp[1][0] = 1;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    uint8_t fainted_pp = battle.sides[1].state[0].pp[0];
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].state[0].fainted);
    assert(battle.request.kind[1] == POKEMON_REQUEST_SWITCH);
    assert(battle.sides[1].state[0].pp[0] == fainted_pp);

    /* A two-turn Start duration decrements to one on the installation turn,
     * then expires through End and permits the next selected move. */
    init.initial_hp[1][0] = 0;
    uint8_t found_two = 0;
    for (uint16_t tail = 1; tail < 512 && !found_two; tail++) {
        init.seed[3] = tail;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        for (size_t trace = 0; trace < battle.condition_trace_count; trace++) {
            const PokemonConditionTrace *entry = &battle.condition_traces[trace];
            found_two |= entry->condition_id == POKEMON_VOLATILE_CONFUSION &&
                entry->operation == POKEMON_CONDITION_ADD &&
                entry->duration_after == 2;
        }
    }
    assert(found_two);
    uint8_t pp_before_expiry = battle.sides[1].state[0].pp[0];
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(test_volatile_index(&battle.sides[1].state[0],
        POKEMON_VOLATILE_CONFUSION) < 0);
    assert(battle.sides[1].state[0].pp[0] == (uint8_t)(pp_before_expiry - 1));

    /* Ordinary switch clears the payload without running End. */
    init.seed[3] = 1;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    PokemonChoice switches[POKEMON_SIDES] = {switch_to(1), switch_to(1)};
    assert(pokemon_battle_step(&battle, switches) == POKEMON_OK);
    assert(test_volatile_index(&battle.sides[1].state[0],
        POKEMON_VOLATILE_CONFUSION) < 0);

    /* Update cures an already-installed confusion through the generated
     * Own Tempo callback, independently of TryAddVolatile. */
    init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_OWNTEMPO;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    PokemonMutable *holder = &battle.sides[1].state[0];
    holder->volatiles[holder->volatile_count++] = (PokemonVolatileState){
        .kind = POKEMON_VOLATILE_CONFUSION,
        .descriptor_id = POKEMON_GEN3_CONDITION_VOLATILE_CONFUSION,
        .state_generation = 1,
        .effect_order = ++battle.next_holder_effect_order,
        .payload.confusion.time = 3,
    };
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(test_volatile_index(holder, POKEMON_VOLATILE_CONFUSION) < 0);
}

static void test_flatter_ordered_primary_effects(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_GENGAR, POKEMON_GEN3_MOVE_FLATTER,
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SPLASH);
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    PokemonBattle battle;
    uint8_t installed = 0;
    for (uint16_t tail = 1; tail < 256 && !installed; tail++) {
        init.seed[3] = tail;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        installed = test_volatile_index(&battle.sides[1].state[0],
            POKEMON_VOLATILE_CONFUSION) >= 0;
    }
    assert(installed);
    assert(battle.sides[1].state[0].boosts[POKEMON_STAT_SPA] == 1);
    assert(battle.effect_trace_count >= 1);
    assert(battle.effect_traces[0].kind == POKEMON_EFFECT_BOOST);
    assert(draw_label_count(&battle, POKEMON_DRAW_CONFUSION_DURATION) == 1);

    /* Own Tempo cancels only the volatile transaction; the earlier positive
     * target boost remains committed. */
    init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_OWNTEMPO;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].state[0].boosts[POKEMON_STAT_SPA] == 1);
    assert(test_volatile_index(&battle.sides[1].state[0],
        POKEMON_VOLATILE_CONFUSION) < 0);
    assert(draw_label_count(&battle, POKEMON_DRAW_CONFUSION_DURATION) == 0);

    /* Failure at the boost cap does not suppress the following independent
     * volatile operation. */
    init.teams[1].members[0].ability_id = 0;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    battle.sides[1].state[0].boosts[POKEMON_STAT_SPA] = 6;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].state[0].boosts[POKEMON_STAT_SPA] == 6);
    assert(test_volatile_index(&battle.sides[1].state[0],
        POKEMON_VOLATILE_CONFUSION) >= 0);

    /* Swagger is the same ordered product over Attack +2 and confusion.  It
     * remains executable for legal delegated entry even though direct team
     * submission is banned by the Gen 3 OU format manifest. */
    const PokemonMoveData *swagger = NULL;
    for (size_t index = 0; index < POKEMON_GEN3_SLICE_DATA.move_count; index++) {
        if (POKEMON_GEN3_SLICE_DATA.moves[index].id == POKEMON_GEN3_MOVE_SWAGGER)
            swagger = &POKEMON_GEN3_SLICE_DATA.moves[index];
    }
    assert(swagger != NULL);
    assert(swagger->accuracy.kind == POKEMON_ACCURACY_PERCENT);
    assert(swagger->accuracy.percent == 90);
    assert(swagger->effect_count == 2);
    const PokemonEffectOp *swagger_effects =
        &POKEMON_GEN3_SLICE_DATA.effects[swagger->effect_offset];
    assert(swagger_effects[0].kind == POKEMON_EFFECT_BOOST);
    assert(swagger_effects[0].argument == POKEMON_STAT_ATK);
    assert(swagger_effects[0].amount == 2);
    assert(swagger_effects[1].kind == POKEMON_EFFECT_ADD_VOLATILE);
    assert(swagger_effects[1].argument == POKEMON_VOLATILE_CONFUSION);

    init = condition_init(
        POKEMON_GEN3_SPECIES_GENGAR, POKEMON_GEN3_MOVE_SWAGGER,
        POKEMON_GEN3_SPECIES_MACHOP, POKEMON_GEN3_MOVE_SPLASH);
    installed = 0;
    for (uint16_t tail = 1; tail < 256 && !installed; tail++) {
        init.seed[3] = tail;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        installed = test_volatile_index(&battle.sides[1].state[0],
            POKEMON_VOLATILE_CONFUSION) >= 0;
    }
    assert(installed);
    assert(battle.sides[1].state[0].boosts[POKEMON_STAT_ATK] == 2);

    /* A capped boost is an independent failed operation and does not roll
     * back or suppress the following volatile transaction. */
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    battle.sides[1].state[0].boosts[POKEMON_STAT_ATK] = 6;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].state[0].boosts[POKEMON_STAT_ATK] == 6);
    assert(test_volatile_index(&battle.sides[1].state[0],
        POKEMON_VOLATILE_CONFUSION) >= 0);

}

static void test_teeter_dance_target_iteration(void) {
    const PokemonMoveData *descriptor = NULL;
    for (size_t i = 0; i < POKEMON_GEN3_SLICE_DATA.move_count; i++) {
        if (POKEMON_GEN3_SLICE_DATA.moves[i].id ==
            POKEMON_GEN3_MOVE_TEETERDANCE) {
            descriptor = &POKEMON_GEN3_SLICE_DATA.moves[i];
            break;
        }
    }
    assert(descriptor != NULL);
    assert(descriptor->target == POKEMON_TARGET_ALL_ADJACENT);
    assert(descriptor->effect_count == 1);

    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_TEETERDANCE,
        POKEMON_GEN3_SPECIES_MACHOP, POKEMON_GEN3_MOVE_SPLASH);
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    PokemonBattle battle;
    uint8_t installed = 0;
    for (uint16_t tail = 1; tail < 256 && !installed; tail++) {
        init.seed[3] = tail;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        installed = test_volatile_index(&battle.sides[1].state[0],
            POKEMON_VOLATILE_CONFUSION) >= 0;
    }
    assert(installed);
    assert(test_volatile_index(&battle.sides[0].state[0],
        POKEMON_VOLATILE_CONFUSION) < 0);
    assert(draw_label_count(&battle, POKEMON_DRAW_CONFUSION_DURATION) == 1);

    init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_OWNTEMPO;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(test_volatile_index(&battle.sides[1].state[0],
        POKEMON_VOLATILE_CONFUSION) < 0);
    assert(draw_label_count(&battle, POKEMON_DRAW_CONFUSION_DURATION) == 0);

    /* The topology abstraction is wider than singles, but the present state
     * representation owns only one active slot per side and rejects a wider
     * format instead of collapsing its targets. */
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    battle.format.active_per_side = 2;
    assert(pokemon_battle_step(&battle, choices) ==
        POKEMON_INVALID_CONFIGURATION);
}

static void test_snatch_reenters_active_move_as_handler_owner(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_ALAKAZAM, POKEMON_GEN3_MOVE_SNATCH,
        POKEMON_GEN3_SPECIES_KINGLER, POKEMON_GEN3_MOVE_HOWL);
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    uint8_t snatch_pp = battle.sides[0].state[0].pp[0];
    uint8_t howl_pp = battle.sides[1].state[0].pp[0];
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].boosts[POKEMON_STAT_ATK] == 1);
    assert(battle.sides[1].state[0].boosts[POKEMON_STAT_ATK] == 0);
    assert(battle.sides[0].state[0].pp[0] == (uint8_t)(snatch_pp - 1));
    assert(battle.sides[1].state[0].pp[0] == (uint8_t)(howl_pp - 1));
    assert(battle.sides[0].state[0].volatile_count == 0);
    assert(battle.move_invocation_count == 3);
    assert(battle.move_invocations[2].invocation.entry == POKEMON_MOVE_ENTRY_CALLED);
    assert(battle.move_invocations[2].invocation.user.side == 0);
    assert(battle.move_invocations[2].invocation.source_effect.kind ==
        POKEMON_SOURCE_EFFECT_CONDITION);
    assert(battle.move_invocations[2].invocation.source_effect.id ==
        POKEMON_GEN3_CONDITION_VOLATILE_SNATCH);
    assert(battle.move_invocations[2].invocation.parent_invocation_id ==
        battle.move_invocations[1].invocation.invocation_id);
    assert(battle.move_invocations[2].invocation.invocation_id !=
        battle.move_invocations[1].invocation.invocation_id);
    assert(battle.move_invocations[2].resolved_target.side == 0);
    assert(battle.move_invocations[2].result == POKEMON_OK);
    assert(battle.handlers[0].handler.descriptor.id == POKEMON_GEN3_HANDLER_SNATCH);
    assert(battle.handlers[0].handler.descriptor.scope == POKEMON_HANDLER_SCOPE_ANY);
    assert(battle.handlers[0].handler.holder_side == 0);
    assert(battle.handlers[0].handler.owner.side == 0);
    assert(battle.handlers[0].handler.owner.effect_id ==
        POKEMON_GEN3_CONDITION_VOLATILE_SNATCH);
    assert(battle.event_frames[0].event == POKEMON_HANDLER_EVENT_PREPARE_HIT);
    assert(battle.event_frames[0].cancellation == POKEMON_EVENT_CANCEL_NULL);
    assert(battle.event_frames[0].cancelling_owner.side == 0);
    assert(battle.condition_trace_count == 2); /* install, trigger removal */
    assert(pokemon_battle_check_invariants(&battle));

    /* Pressure belongs to the immediately stolen-from user and charges the
     * Snatch installation's originating slot, not the called move. */
    init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_PRESSURE;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    snatch_pp = battle.sides[0].state[0].pp[0];
    howl_pp = battle.sides[1].state[0].pp[0];
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].pp[0] == (uint8_t)(snatch_pp - 2));
    assert(battle.sides[1].state[0].pp[0] == (uint8_t)(howl_pp - 1));

    /* Each child rediscovers the remaining installations. Fastest removes
     * first; the slowest remaining holder is therefore the final executor. */
    init = condition_init(
        POKEMON_GEN3_SPECIES_ALAKAZAM, POKEMON_GEN3_MOVE_HOWL,
        POKEMON_GEN3_SPECIES_KINGLER, POKEMON_GEN3_MOVE_SPLASH);
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    for (size_t side = 0; side < POKEMON_SIDES; side++) {
        PokemonMutable *state = &battle.sides[side].state[0];
        state->volatiles[0] = (PokemonVolatileState){
            .kind = POKEMON_VOLATILE_SNATCH,
            .descriptor_id = POKEMON_GEN3_CONDITION_VOLATILE_SNATCH,
            .duration = 1, .state_generation = 1,
            .effect_order = ++battle.next_holder_effect_order,
            .source = {POKEMON_ENTITY_POKEMON, (uint8_t)side, 0},
            .source_effect = {POKEMON_SOURCE_EFFECT_MOVE,
                POKEMON_GEN3_MOVE_SNATCH},
        };
        state->volatile_count = 1;
    }
    assert(pokemon_battle_check_invariants(&battle));
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].boosts[POKEMON_STAT_ATK] == 0);
    assert(battle.sides[1].state[0].boosts[POKEMON_STAT_ATK] == 1);
    assert(battle.sides[0].state[0].volatile_count == 0);
    assert(battle.sides[1].state[0].volatile_count == 0);
    assert(battle.move_invocation_count == 4);
    assert(battle.move_invocations[2].invocation.user.side == 1);

    /* A multi-stat move is stolen as one called invocation, not decomposed
     * into per-stat special cases. */
    init = condition_init(
        POKEMON_GEN3_SPECIES_ALAKAZAM, POKEMON_GEN3_MOVE_SNATCH,
        POKEMON_GEN3_SPECIES_KINGLER, POKEMON_GEN3_MOVE_CALMMIND);
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].boosts[POKEMON_STAT_SPA] == 1);
    assert(battle.sides[0].state[0].boosts[POKEMON_STAT_SPD] == 1);
    assert(battle.sides[1].state[0].boosts[POKEMON_STAT_SPA] == 0);
    assert(battle.sides[1].state[0].boosts[POKEMON_STAT_SPD] == 0);
    assert(battle.move_invocation_count == 3);

    /* An ineligible move observes but does not consume Snatch; duration-one
     * residual expiry removes it later in the same turn. */
    init = condition_init(
        POKEMON_GEN3_SPECIES_ALAKAZAM, POKEMON_GEN3_MOVE_SNATCH,
        POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_SPLASH);
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.move_invocation_count == 2);
    assert(battle.sides[0].state[0].volatile_count == 0);
    assert(battle.condition_trace_count == 3); /* add, residual execute, remove */
    assert(battle.condition_traces[0].operation == POKEMON_CONDITION_ADD);
    assert(battle.condition_traces[1].operation == POKEMON_CONDITION_UPDATE);
    assert(battle.condition_traces[1].reason == POKEMON_CONDITION_REASON_EXPIRY);
    assert(battle.condition_traces[2].operation == POKEMON_CONDITION_REMOVE);

    /* Reapplying an already installed Snatch neither duplicates nor refreshes
     * it; the original installation expires normally. */
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    battle.sides[0].state[0].volatiles[0] = (PokemonVolatileState){
        .kind = POKEMON_VOLATILE_SNATCH,
        .descriptor_id = POKEMON_GEN3_CONDITION_VOLATILE_SNATCH,
        .duration = 1, .state_generation = 1,
        .effect_order = ++battle.next_holder_effect_order,
        .source = {POKEMON_ENTITY_POKEMON, 0, 0},
        .source_effect = {POKEMON_SOURCE_EFFECT_MOVE, POKEMON_GEN3_MOVE_SNATCH},
    };
    battle.sides[0].state[0].volatile_count = 1;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].volatile_count == 0);
    assert(battle.condition_trace_count == 2); /* residual execute, remove */
    assert(battle.condition_traces[0].operation == POKEMON_CONDITION_UPDATE);
    assert(battle.condition_traces[0].reason == POKEMON_CONDITION_REASON_EXPIRY);
    assert(battle.condition_traces[1].operation == POKEMON_CONDITION_REMOVE);

    /* Equal ordinary handler keys own one labeled ordering draw per event
     * discovery. Snatch re-enters PrepareHit once, so the two installations
     * produce two draws, and replay preserves both exactly. */
    init = condition_init(
        POKEMON_GEN3_SPECIES_ALAKAZAM, POKEMON_GEN3_MOVE_HOWL,
        POKEMON_GEN3_SPECIES_KINGLER, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[0].members[0].stats[5] = 200;
    init.teams[1].members[0].stats[5] = 200;
    PokemonBattle replay;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_init(&replay, &init) == POKEMON_OK);
    for (size_t side = 0; side < POKEMON_SIDES; side++) {
        PokemonVolatileState installed = {
            .kind = POKEMON_VOLATILE_SNATCH,
            .descriptor_id = POKEMON_GEN3_CONDITION_VOLATILE_SNATCH,
            .duration = 1, .state_generation = 1,
            .source = {POKEMON_ENTITY_POKEMON, (uint8_t)side, 0},
            .source_effect = {POKEMON_SOURCE_EFFECT_MOVE, POKEMON_GEN3_MOVE_SNATCH},
        };
        installed.effect_order = 7; /* exact tie is verifier-injected */
        battle.sides[side].state[0].volatiles[0] = installed;
        replay.sides[side].state[0].volatiles[0] = installed;
        battle.sides[side].state[0].volatile_count = 1;
        replay.sides[side].state[0].volatile_count = 1;
    }
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(pokemon_battle_step(&replay, choices) == POKEMON_OK);
    assert(memcmp(battle.seed, replay.seed, sizeof(battle.seed)) == 0);
    assert(battle.draw_count == replay.draw_count);
    assert(memcmp(battle.draws, replay.draws,
        battle.draw_count * sizeof(battle.draws[0])) == 0);
    assert(battle.handler_count == replay.handler_count);
    assert(battle.move_invocation_count == replay.move_invocation_count);
    for (size_t side = 0; side < POKEMON_SIDES; side++) {
        assert(memcmp(battle.sides[side].state[0].boosts,
            replay.sides[side].state[0].boosts,
            sizeof(battle.sides[side].state[0].boosts)) == 0);
    }
    size_t ordering_draws = 0;
    for (size_t i = 0; i < battle.draw_count; i++) {
        if (battle.draws[i].label == POKEMON_DRAW_EVENT_HANDLER_ORDER &&
            battle.draws[i].context_event_id == POKEMON_HANDLER_EVENT_PREPARE_HIT) {
            ordering_draws++;
        }
    }
    assert(ordering_draws == 2);
    assert(battle.sides[0].state[0].boosts[POKEMON_STAT_ATK] == 0);
    assert(battle.sides[1].state[0].boosts[POKEMON_STAT_ATK] == 1);

    /* Nested frame exhaustion rolls the entire public step back, including
     * the owner removal, PP deductions, traces, and PRNG state. */
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    battle.sides[1].state[0].volatiles[0] = (PokemonVolatileState){
        .kind = POKEMON_VOLATILE_SNATCH,
        .descriptor_id = POKEMON_GEN3_CONDITION_VOLATILE_SNATCH,
        .duration = 1, .state_generation = 1,
        .effect_order = ++battle.next_holder_effect_order,
        .source = {POKEMON_ENTITY_POKEMON, 1, 0},
        .source_effect = {POKEMON_SOURCE_EFFECT_MOVE, POKEMON_GEN3_MOVE_SNATCH},
    };
    battle.sides[1].state[0].volatile_count = 1;
    battle.move_frame_depth = POKEMON_MOVE_FRAME_CAPACITY - 1;
    PokemonBattle before_overflow = battle;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_CAPACITY_EXCEEDED);
    assert(memcmp(&battle, &before_overflow, sizeof(battle)) == 0);

    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    battle.sides[1].state[0].volatiles[0] = (PokemonVolatileState){
        .kind = POKEMON_VOLATILE_SNATCH,
        .descriptor_id = POKEMON_GEN3_CONDITION_VOLATILE_SNATCH,
        .duration = 1, .state_generation = 1,
        .effect_order = ++battle.next_holder_effect_order,
        .source = {POKEMON_ENTITY_POKEMON, 1, 0},
        .source_effect = {POKEMON_SOURCE_EFFECT_MOVE, POKEMON_GEN3_MOVE_SNATCH},
    };
    battle.sides[1].state[0].volatile_count = 1;
    battle.event_depth = POKEMON_EVENT_FRAME_CAPACITY - 1;
    before_overflow = battle;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_CAPACITY_EXCEEDED);
    assert(memcmp(&battle, &before_overflow, sizeof(battle)) == 0);

    /* Installation into a full, otherwise valid volatile product fails
     * atomically before any partial Snatch state survives. */
    init = condition_init(
        POKEMON_GEN3_SPECIES_ALAKAZAM, POKEMON_GEN3_MOVE_SNATCH,
        POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_SPLASH);
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    PokemonMutable *full = &battle.sides[0].state[0];
    full->volatiles[0] = (PokemonVolatileState){
        .kind = POKEMON_VOLATILE_PROTECT,
        .descriptor_id = POKEMON_GEN3_CONDITION_VOLATILE_PROTECT,
        .duration = 1, .state_generation = 1,
        .effect_order = ++battle.next_holder_effect_order,
    };
    full->volatiles[1] = (PokemonVolatileState){
        .kind = POKEMON_VOLATILE_STALL,
        .descriptor_id = POKEMON_GEN3_CONDITION_VOLATILE_STALL,
        .duration = 1, .counter = 2, .state_generation = 1,
        .effect_order = ++battle.next_holder_effect_order,
    };
    full->volatiles[2] = (PokemonVolatileState){
        .kind = POKEMON_VOLATILE_SUBSTITUTE_BROKEN,
        .descriptor_id = POKEMON_GEN3_CONDITION_VOLATILE_SUBSTITUTEBROKEN,
        .state_generation = 1,
        .effect_order = ++battle.next_holder_effect_order,
        .payload.substitute_broken = {.breaking_move_id = POKEMON_GEN3_MOVE_HOWL},
    };
    full->volatiles[3] = (PokemonVolatileState){
        .kind = POKEMON_VOLATILE_PARTIALLY_TRAPPED,
        .descriptor_id = POKEMON_GEN3_CONDITION_VOLATILE_PARTIALLYTRAPPED,
        .duration = 3, .state_generation = 1,
        .effect_order = ++battle.next_holder_effect_order,
    };
    full->volatile_count = POKEMON_VOLATILE_CAPACITY;
    assert(pokemon_battle_check_invariants(&battle));
    before_overflow = battle;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_CAPACITY_EXCEEDED);
    assert(memcmp(&battle, &before_overflow, sizeof(battle)) == 0);
}

static size_t pressure_deduct_handler_count(const PokemonBattle *battle) {
    size_t count = 0;
    for (size_t i = 0; i < battle->handler_count; i++) {
        count += battle->handlers[i].handler.descriptor.id ==
            POKEMON_GEN3_HANDLER_PRESSURE_DEDUCT_PP;
    }
    return count;
}

static void test_pressure_generic_pp_deduction_stage(void) {
    PokemonChoice attack[POKEMON_SIDES] = {move(0), move(0)};
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_STARMIE, POKEMON_GEN3_MOVE_SURF,
        POKEMON_GEN3_SPECIES_DUSCLOPS, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_PRESSURE;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    uint8_t initial_pp = battle.sides[0].state[0].pp[0];
    assert(pokemon_battle_step(&battle, attack) == POKEMON_OK);
    assert(battle.sides[0].state[0].pp[0] == (uint8_t)(initial_pp - 2));
    assert(pressure_deduct_handler_count(&battle) == 1);

    /* Self-targeting a Pressure holder is not opposing-target Pressure. */
    init = condition_init(
        POKEMON_GEN3_SPECIES_DUSCLOPS, POKEMON_GEN3_MOVE_HOWL,
        POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[0].members[0].ability_id = POKEMON_GEN3_ABILITY_PRESSURE;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    initial_pp = battle.sides[0].state[0].pp[0];
    assert(pokemon_battle_step(&battle, attack) == POKEMON_OK);
    assert(battle.sides[0].state[0].pp[0] == (uint8_t)(initial_pp - 1));
    assert(pressure_deduct_handler_count(&battle) == 1);

    /* Deduction precedes both natural immunity and Protect. */
    init = condition_init(
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_EARTHQUAKE,
        POKEMON_GEN3_SPECIES_ARTICUNO, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_PRESSURE;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    initial_pp = battle.sides[0].state[0].pp[0];
    uint16_t target_hp = battle.sides[1].state[0].hp;
    assert(pokemon_battle_step(&battle, attack) == POKEMON_OK);
    assert(battle.sides[0].state[0].pp[0] == (uint8_t)(initial_pp - 2));
    assert(battle.sides[1].state[0].hp == target_hp);

    init = condition_init(
        POKEMON_GEN3_SPECIES_STARMIE, POKEMON_GEN3_MOVE_SURF,
        POKEMON_GEN3_SPECIES_DUSCLOPS, POKEMON_GEN3_MOVE_PROTECT);
    init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_PRESSURE;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    initial_pp = battle.sides[0].state[0].pp[0];
    target_hp = battle.sides[1].state[0].hp;
    assert(pokemon_battle_step(&battle, attack) == POKEMON_OK);
    assert(battle.sides[0].state[0].pp[0] == (uint8_t)(initial_pp - 2));
    assert(battle.sides[1].state[0].hp == target_hp);

    /* A foe-side target such as Spikes discovers the opposing active holder. */
    init = condition_init(
        POKEMON_GEN3_SPECIES_SKARMORY, POKEMON_GEN3_MOVE_SPIKES,
        POKEMON_GEN3_SPECIES_DUSCLOPS, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_PRESSURE;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    initial_pp = battle.sides[0].state[0].pp[0];
    assert(pokemon_battle_step(&battle, attack) == POKEMON_OK);
    assert(battle.sides[0].state[0].pp[0] == (uint8_t)(initial_pp - 2));
    assert(battle.sides[1].condition_count == 1);
    assert(battle.sides[1].conditions[0].kind == POKEMON_SIDE_CONDITION_SPIKES);

    /* Target discovery occurs after faster switches resolve. */
    PokemonChoice switch_target[POKEMON_SIDES] = {move(0), switch_to(1)};
    init = condition_init(
        POKEMON_GEN3_SPECIES_STARMIE, POKEMON_GEN3_MOVE_SURF,
        POKEMON_GEN3_SPECIES_DUSCLOPS, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_PRESSURE;
    init.teams[1].members[1].ability_id = 0;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    initial_pp = battle.sides[0].state[0].pp[0];
    assert(pokemon_battle_step(&battle, switch_target) == POKEMON_OK);
    assert(battle.sides[0].state[0].pp[0] == (uint8_t)(initial_pp - 1));

    init.teams[1].members[0].ability_id = 0;
    init.teams[1].members[1].ability_id = POKEMON_GEN3_ABILITY_PRESSURE;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    initial_pp = battle.sides[0].state[0].pp[0];
    assert(pokemon_battle_step(&battle, switch_target) == POKEMON_OK);
    assert(battle.sides[0].state[0].pp[0] == (uint8_t)(initial_pp - 2));

    /* A forced locked continuation does not own a second PP deduction. */
    init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_OUTRAGE,
        POKEMON_GEN3_SPECIES_DUSCLOPS, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_PRESSURE;
    init.teams[1].members[0].stats[0] = 1000;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    initial_pp = battle.sides[0].state[0].pp[0];
    assert(pokemon_battle_step(&battle, attack) == POKEMON_OK);
    assert(battle.sides[0].state[0].pp[0] == (uint8_t)(initial_pp - 2));
    uint8_t after_selected = battle.sides[0].state[0].pp[0];
    assert(pokemon_battle_step(&battle, attack) == POKEMON_OK);
    assert(battle.sides[0].state[0].pp[0] == after_selected);
    assert(pokemon_battle_check_invariants(&battle));
}

static void test_gen3_rule_plugin_boundaries(void) {
    PokemonDamageFormulaOutput output;
    POKEMON_GEN3_RULES.resolve_damage_formula(
        &(PokemonDamageFormulaInput){
            .formula = POKEMON_DAMAGE_FIXED_LEVEL, .level = 73,
            .hp = 1, .max_hp = 1,
        },
        &output
    );
    assert(output.fixed_damage == 73);
    assert(output.resolved_power == 0);
    static const struct { uint16_t hp; uint8_t ratio; uint16_t power; } cases[] = {
        {301, 48, 20}, {207, 33, 20}, {206, 32, 40},
        {107, 17, 40}, {106, 16, 80}, {63, 10, 80},
        {62, 9, 100}, {32, 5, 100}, {31, 4, 150},
        {13, 2, 150}, {12, 1, 200},
    };
    for (size_t i = 0; i < sizeof(cases) / sizeof(cases[0]); i++) {
        POKEMON_GEN3_RULES.resolve_damage_formula(
            &(PokemonDamageFormulaInput){
                .formula = POKEMON_DAMAGE_HP_BRACKET,
                .hp = cases[i].hp, .max_hp = 301,
            },
            &output
        );
        assert(output.ratio == cases[i].ratio);
        assert(output.resolved_power == cases[i].power);
    }
    assert(POKEMON_GEN3_RULES.residual_damage(
        POKEMON_RESIDUAL_FORMULA_SAND, 401, 0) == 25);
    assert(POKEMON_GEN3_RULES.residual_damage(
        POKEMON_RESIDUAL_FORMULA_BURN, 401, 0) == 50);
    assert(POKEMON_GEN3_RULES.residual_damage(
        POKEMON_RESIDUAL_FORMULA_TOXIC, 401, 15) == 375);
    assert(POKEMON_GEN3_RULES.residual_damage(
        POKEMON_RESIDUAL_FORMULA_BURN, 1, 0) == 1);
    assert(POKEMON_GEN3_RULES.condition_rule_count == 61);
    assert(POKEMON_GEN3_RULES.stages != NULL);
    for (int stage = -6; stage <= 6; stage++) {
        uint32_t ordinary_expected = stage < 0 ?
            101u * 2u / (uint32_t)(2 - stage) :
            101u * (uint32_t)(2 + stage) / 2u;
        uint32_t accuracy_expected = stage < 0 ?
            101u * 3u / (uint32_t)(3 - stage) :
            101u * (uint32_t)(3 + stage) / 3u;
        assert(pokemon_apply_stage_ratio(
            POKEMON_GEN3_RULES.stages, 101, (int8_t)stage, 0) ==
            ordinary_expected);
        assert(pokemon_apply_stage_ratio(
            POKEMON_GEN3_RULES.stages, 101, (int8_t)stage, 1) ==
            accuracy_expected);
    }
    static const struct {
        PokemonRuleConditionKind kind;
        uint8_t duration;
        uint8_t order;
        uint8_t sub_order;
    } condition_cases[] = {
        {POKEMON_RULE_CONDITION_TOXIC, 0, 10, 6},
        {POKEMON_RULE_CONDITION_BURN, 0, 10, 6},
        {POKEMON_RULE_CONDITION_POISON, 0, 10, 6},
        {POKEMON_RULE_CONDITION_PROTECT, 1, 0, 2},
        {POKEMON_RULE_CONDITION_STALL, 2, 0, 2},
        {POKEMON_RULE_CONDITION_REFLECT, 5, 1, 4},
        {POKEMON_RULE_CONDITION_SANDSTORM, 5, 8, 5},
        {POKEMON_RULE_CONDITION_HAIL, 5, 8, 5},
        {POKEMON_RULE_CONDITION_RAIN, 5, 8, 5},
        {POKEMON_RULE_CONDITION_SUN, 5, 8, 5},
        {POKEMON_RULE_CONDITION_FLINCH, 1, 0, 2},
        {POKEMON_RULE_CONDITION_FOCUS_ENERGY, 0, 0, 0},
        {POKEMON_RULE_CONDITION_LIGHT_SCREEN, 5, 2, 4},
        {POKEMON_RULE_CONDITION_MIST, 5, 3, 4},
        {POKEMON_RULE_CONDITION_SAFEGUARD, 5, 4, 4},
        {POKEMON_RULE_CONDITION_YAWN, 2, 10, 19},
        {POKEMON_RULE_CONDITION_SPIKES, 0, 0, 0},
        {POKEMON_RULE_CONDITION_MUST_RECHARGE, 2, 0, 2},
        {POKEMON_RULE_CONDITION_MUD_SPORT, 0, 0, 0},
        {POKEMON_RULE_CONDITION_WATER_SPORT, 0, 0, 0},
        {POKEMON_RULE_CONDITION_ENDURE, 1, 0, 2},
        {POKEMON_RULE_CONDITION_LOCK_ON, 2, 0, 2},
        {POKEMON_RULE_CONDITION_RETALIATION_PHYSICAL, 1, 0, 2},
        {POKEMON_RULE_CONDITION_RETALIATION_SPECIAL, 1, 0, 2},
        {POKEMON_RULE_CONDITION_INGRAIN, 0, 10, 1},
        {POKEMON_RULE_CONDITION_QUEUED_MOVE_INTERCEPT, 1, 0, 2},
        {POKEMON_RULE_CONDITION_CHARGE, 0, 0, 0},
        {POKEMON_RULE_CONDITION_LEECH_SEED, 0, 10, 5},
        {POKEMON_RULE_CONDITION_FLASH_FIRE, 0, 0, 0},
    };
    for (size_t i = 0; i < sizeof(condition_cases) / sizeof(condition_cases[0]); i++) {
        const PokemonConditionRule *rule = NULL;
        for (size_t j = 0; j < POKEMON_GEN3_RULES.condition_rule_count; j++) {
            if (POKEMON_GEN3_RULES.condition_rules[j].kind ==
                    condition_cases[i].kind) {
                rule = &POKEMON_GEN3_RULES.condition_rules[j];
                break;
            }
        }
        assert(rule != NULL);
        assert(rule->lifecycle_duration.maximum == condition_cases[i].duration);
        assert(rule->lifecycle_duration.minimum == condition_cases[i].duration);
        assert(rule->lifecycle_duration.kind ==
            (condition_cases[i].duration == 0 ?
                POKEMON_CONDITION_DURATION_NONE :
                POKEMON_CONDITION_DURATION_FIXED));
        assert(rule->residual_order == condition_cases[i].order);
        assert(rule->residual_sub_order == condition_cases[i].sub_order);
    }
    assert(POKEMON_GEN3_RULES.stall.initial_denominator == 2);
    assert(POKEMON_GEN3_RULES.stall.multiplier == 2);
    assert(POKEMON_GEN3_RULES.stall.denominator_cap == 8);

    assert(POKEMON_GEN3_OU_BUNDLE.manifest == &POKEMON_GEN3_OU_FORMAT);
    assert(POKEMON_GEN3_OU_BUNDLE.runtime_format == &POKEMON_SINGLES_6_FORMAT);
    assert(POKEMON_GEN3_OU_BUNDLE.policy == &POKEMON_GEN3_OU_POLICY);
    PokemonGeneration wrong_generation = POKEMON_GEN3_RULES;
    wrong_generation.generation = 4;
    PokemonBattleInit init = battle_init();
    PokemonResolvedBundle invalid_bundle = *init.bundle;
    invalid_bundle.rules = &wrong_generation;
    init.bundle = &invalid_bundle;
    PokemonBattle untouched;
    memset(&untouched, 0x5a, sizeof(untouched));
    PokemonBattle before = untouched;
    assert(pokemon_battle_init(&untouched, &init) == POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&untouched, &before, sizeof(untouched)) == 0);

    /* Stalling guards are an explicit plugin capability, not an enum range.
     * Reject both a descriptor that has lost that capability and a bundle
     * whose shared stall lifecycle cannot be executed by the fixed-duration
     * kernel operation. */
    PokemonConditionRule malformed_stalling_rules[
        POKEMON_GEN3_RULES.condition_rule_count];
    memcpy(malformed_stalling_rules, POKEMON_GEN3_RULES.condition_rules,
        sizeof(malformed_stalling_rules));
    malformed_stalling_rules[POKEMON_RULE_CONDITION_PROTECT - 1]
        .flags &= (uint8_t)~POKEMON_CONDITION_RULE_STALLING_GUARD;
    PokemonGeneration malformed_stalling_generation = POKEMON_GEN3_RULES;
    malformed_stalling_generation.condition_rules = malformed_stalling_rules;
    init = condition_init(
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_PROTECT,
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_TACKLE);
    invalid_bundle = *init.bundle;
    invalid_bundle.rules = &malformed_stalling_generation;
    init.bundle = &invalid_bundle;
    before = untouched;
    assert(pokemon_battle_init(&untouched, &init) ==
        POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&untouched, &before, sizeof(untouched)) == 0);

    memcpy(malformed_stalling_rules, POKEMON_GEN3_RULES.condition_rules,
        sizeof(malformed_stalling_rules));
    malformed_stalling_rules[POKEMON_RULE_CONDITION_STALL - 1]
        .lifecycle_duration = (PokemonConditionDuration){
            POKEMON_CONDITION_DURATION_UNIFORM, 1, 2};
    malformed_stalling_rules[POKEMON_RULE_CONDITION_STALL - 1]
        .duration_draw_label = POKEMON_DRAW_DISABLE_DURATION;
    malformed_stalling_generation = POKEMON_GEN3_RULES;
    malformed_stalling_generation.condition_rules = malformed_stalling_rules;
    invalid_bundle = *init.bundle;
    invalid_bundle.rules = &malformed_stalling_generation;
    init.bundle = &invalid_bundle;
    before = untouched;
    assert(pokemon_battle_init(&untouched, &init) ==
        POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&untouched, &before, sizeof(untouched)) == 0);

    PokemonFormatPolicy wrong_policy = POKEMON_GEN3_OU_POLICY;
    wrong_policy.generation = 4;
    init = battle_init();
    invalid_bundle = *init.bundle;
    invalid_bundle.policy = &wrong_policy;
    init.bundle = &invalid_bundle;
    assert(pokemon_battle_init(&untouched, &init) == POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&untouched, &before, sizeof(untouched)) == 0);

    PokemonFormatManifest equivalent_but_unbound_manifest = POKEMON_GEN3_OU_FORMAT;
    wrong_policy = POKEMON_GEN3_OU_POLICY;
    wrong_policy.manifest = &equivalent_but_unbound_manifest;
    init = battle_init();
    invalid_bundle = *init.bundle;
    invalid_bundle.policy = &wrong_policy;
    init.bundle = &invalid_bundle;
    assert(pokemon_battle_init(&untouched, &init) == POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&untouched, &before, sizeof(untouched)) == 0);

    PokemonData wrong_data = POKEMON_GEN3_SLICE_DATA;
    wrong_data.generation = 4;
    init = battle_init();
    invalid_bundle = *init.bundle;
    invalid_bundle.data = &wrong_data;
    init.bundle = &invalid_bundle;
    assert(pokemon_battle_init(&untouched, &init) == POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&untouched, &before, sizeof(untouched)) == 0);

    PokemonGeneration incomplete = POKEMON_GEN3_RULES;
    incomplete.resolve_damage_formula = NULL;
    init = battle_init();
    invalid_bundle = *init.bundle;
    invalid_bundle.rules = &incomplete;
    init.bundle = &invalid_bundle;
    assert(pokemon_battle_init(&untouched, &init) == POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&untouched, &before, sizeof(untouched)) == 0);

    PokemonConditionRule malformed_link_rules[
        POKEMON_GEN3_RULES.condition_rule_count];
    memcpy(malformed_link_rules, POKEMON_GEN3_RULES.condition_rules,
        sizeof(malformed_link_rules));
    size_t trapped_rule = 0;
    while (trapped_rule < POKEMON_GEN3_RULES.condition_rule_count &&
        malformed_link_rules[trapped_rule].kind !=
            POKEMON_RULE_CONDITION_TRAPPED) trapped_rule++;
    assert(trapped_rule < POKEMON_GEN3_RULES.condition_rule_count);
    malformed_link_rules[trapped_rule].source_linked_kind =
        POKEMON_VOLATILE_ATTRACT;
    incomplete = POKEMON_GEN3_RULES;
    incomplete.condition_rules = malformed_link_rules;
    init = battle_init();
    invalid_bundle = *init.bundle;
    invalid_bundle.rules = &incomplete;
    init.bundle = &invalid_bundle;
    before = untouched;
    assert(pokemon_battle_init(&untouched, &init) ==
        POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&untouched, &before, sizeof(untouched)) == 0);

    incomplete = POKEMON_GEN3_RULES;
    incomplete.fallback_move_id = UINT16_MAX;
    init = battle_init();
    invalid_bundle = *init.bundle;
    invalid_bundle.rules = &incomplete;
    init.bundle = &invalid_bundle;
    assert(pokemon_battle_init(&untouched, &init) == POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&untouched, &before, sizeof(untouched)) == 0);

    PokemonConditionRule duplicate_rules[
        POKEMON_GEN3_RULES.condition_rule_count];
    memcpy(duplicate_rules, POKEMON_GEN3_RULES.condition_rules,
        sizeof(duplicate_rules));
    duplicate_rules[5].kind = duplicate_rules[4].kind;
    incomplete = POKEMON_GEN3_RULES;
    incomplete.condition_rules = duplicate_rules;
    invalid_bundle.rules = &incomplete;
    assert(pokemon_battle_init(&untouched, &init) == POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&untouched, &before, sizeof(untouched)) == 0);

    PokemonConditionRule duplicate_descriptor[
        POKEMON_GEN3_RULES.condition_rule_count];
    memcpy(duplicate_descriptor, POKEMON_GEN3_RULES.condition_rules,
        sizeof(duplicate_descriptor));
    duplicate_descriptor[5].descriptor_id = duplicate_descriptor[4].descriptor_id;
    incomplete = POKEMON_GEN3_RULES;
    incomplete.condition_rules = duplicate_descriptor;
    invalid_bundle.rules = &incomplete;
    assert(pokemon_battle_init(&untouched, &init) == POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&untouched, &before, sizeof(untouched)) == 0);

    incomplete = POKEMON_GEN3_RULES;
    /* Remove the complete parameterized ramp family, not merely one of its
     * additional descriptor rows. */
    incomplete.condition_rule_count -= 4;
    invalid_bundle.rules = &incomplete;
    assert(pokemon_battle_init(&untouched, &init) == POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&untouched, &before, sizeof(untouched)) == 0);

    const PokemonConditionDuration invalid_durations[] = {
        {(PokemonConditionDurationKind)99, 0, 0},
        {POKEMON_CONDITION_DURATION_NONE, 1, 1},
        {POKEMON_CONDITION_DURATION_FIXED, 0, 0},
        {POKEMON_CONDITION_DURATION_FIXED, 1, 2},
        {POKEMON_CONDITION_DURATION_UNIFORM, 2, 2},
        {POKEMON_CONDITION_DURATION_UNIFORM, 3, 2},
    };
    for (size_t i = 0;
         i < sizeof(invalid_durations) / sizeof(invalid_durations[0]); i++) {
        PokemonConditionRule invalid_duration_rules[
            POKEMON_GEN3_RULES.condition_rule_count];
        memcpy(invalid_duration_rules, POKEMON_GEN3_RULES.condition_rules,
            sizeof(invalid_duration_rules));
        invalid_duration_rules[POKEMON_RULE_CONDITION_REFLECT - 1]
            .lifecycle_duration = invalid_durations[i];
        incomplete = POKEMON_GEN3_RULES;
        incomplete.condition_rules = invalid_duration_rules;
        init = battle_init();
        invalid_bundle = *init.bundle;
        invalid_bundle.rules = &incomplete;
        init.bundle = &invalid_bundle;
        before = untouched;
        assert(pokemon_battle_init(&untouched, &init) ==
            POKEMON_INVALID_CONFIGURATION);
        assert(memcmp(&untouched, &before, sizeof(untouched)) == 0);
    }

    PokemonConditionRule extended_rules[
        POKEMON_GEN3_RULES.condition_rule_count + 1];
    memcpy(extended_rules, POKEMON_GEN3_RULES.condition_rules,
        sizeof(POKEMON_GEN3_RULES.condition_rules[0]) *
        POKEMON_GEN3_RULES.condition_rule_count);
    extended_rules[POKEMON_GEN3_RULES.condition_rule_count] =
        (PokemonConditionRule){
            .kind = (PokemonRuleConditionKind)100, .descriptor_id = UINT16_MAX,
        };
    incomplete = POKEMON_GEN3_RULES;
    incomplete.condition_rules = extended_rules;
    incomplete.condition_rule_count++;
    invalid_bundle.rules = &incomplete;
    assert(pokemon_battle_init(&untouched, &init) == POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&untouched, &before, sizeof(untouched)) == 0);

    PokemonMoveData malformed_moves[POKEMON_GEN3_MOVE_COUNT];
    memcpy(malformed_moves, POKEMON_GEN3_SLICE_DATA.moves,
        sizeof(malformed_moves));
    uint16_t selected_move = init.teams[0].members[0].move_ids[0];
    size_t selected_index = 0;
    while (malformed_moves[selected_index].id != selected_move) selected_index++;
    malformed_moves[selected_index].weather_policy[POKEMON_WEATHER_NONE] =
        (PokemonWeatherMovePolicy){
            .flags = POKEMON_WEATHER_MOVE_POWER, .power_q12 = 0,
        };
    PokemonData malformed_data = POKEMON_GEN3_SLICE_DATA;
    malformed_data.moves = malformed_moves;
    init = battle_init();
    invalid_bundle = *init.bundle;
    invalid_bundle.data = &malformed_data;
    init.bundle = &invalid_bundle;
    before = untouched;
    assert(pokemon_battle_init(&untouched, &init) == POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&untouched, &before, sizeof(untouched)) == 0);
}

static void test_initial_request_and_atomic_rejection(void) {
    PokemonBattleInit init = battle_init();
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(battle.turn == 1);
    assert(battle.request.kind[0] == POKEMON_REQUEST_MOVE);
    assert(battle.request.kind[1] == POKEMON_REQUEST_MOVE);
    assert(battle.request.legal_moves[0] == 1);
    assert(battle.request.legal_switches[0] == 2);
    assert(battle.event_count == 2);
    assert(battle.phase == POKEMON_PHASE_AWAITING_CHOICES);
    assert(battle.last_queue.count == 0);
    PokemonBattle before = battle;
    PokemonChoice illegal[POKEMON_SIDES] = {move(1), move(0)};
    assert(pokemon_battle_step(&battle, illegal) == POKEMON_ILLEGAL_CHOICE);
    assert(memcmp(&battle, &before, sizeof(battle)) == 0);
}

static void test_empty_pp_projects_and_executes_struggle(void) {
    PokemonMoveData moves[POKEMON_GEN3_MOVE_COUNT];
    memcpy(moves, POKEMON_GEN3_SLICE_DATA.moves, sizeof(moves));
    for (size_t i = 0; i < POKEMON_GEN3_MOVE_COUNT; i++) {
        if (moves[i].id == POKEMON_GEN3_MOVE_QUICKATTACK) {
            moves[i].raw_pp = 1;
            moves[i].pp = 1;
            moves[i].no_pp_boosts = 1;
        }
    }
    PokemonData data = POKEMON_GEN3_SLICE_DATA;
    data.moves = moves;
    PokemonResolvedBundle bundle = POKEMON_GEN3_OU_BUNDLE;
    PokemonFormatPolicy policy = *bundle.policy;
    policy.status_clauses = NULL;
    policy.status_clause_count = 0;
    bundle.policy = &policy;
    bundle.data = &data;
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_QUICKATTACK,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SPLASH);
    init.bundle = &bundle;
    init.teams[0].members[0].ability_id = POKEMON_GEN3_ABILITY_ROCKHEAD;
    init.teams[0].members[0].stats[0] = 500;
    init.teams[1].members[0].stats[0] = 500;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].pp[0] == 0);
    assert(battle.request.legal_moves[0] == 1);
    assert(battle.request.forced_move_id[0] == POKEMON_GEN3_MOVE_STRUGGLE);
    uint16_t hp = battle.sides[0].state[0].hp;
    uint16_t target_hp = battle.sides[1].state[0].hp;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.last_queue.values[0].side == 0);
    assert(battle.last_queue.values[0].selected_move_id ==
        POKEMON_GEN3_MOVE_STRUGGLE);
    assert(battle.last_queue.values[0].move_choice_kind ==
        POKEMON_MOVE_CHOICE_FALLBACK);
    assert(battle.sides[0].state[0].pp[0] == 0);
    assert(battle.sides[0].state[0].last_move_id == POKEMON_GEN3_MOVE_STRUGGLE);
    uint16_t actual_damage = (uint16_t)(
        target_hp - battle.sides[1].state[0].hp);
    uint16_t recoil = (uint16_t)(hp - battle.sides[0].state[0].hp);
    assert(actual_damage > 0);
    assert(recoil == (actual_damage / 4u == 0 ? 1u : actual_damage / 4u));
    assert(battle.immunity_count == 0);
    uint8_t found_accuracy = 0;
    for (size_t i = 0; i < battle.draw_count; i++) {
        found_accuracy |= battle.draws[i].label == POKEMON_DRAW_ACCURACY;
    }
    assert(found_accuracy);
    uint8_t found_typeless = 0;
    uint8_t found_rock_head = 0;
    for (size_t i = 0; i < battle.handler_count; i++) {
        const PokemonHandlerInvocation *handler = &battle.handlers[i];
        found_typeless |= handler->invoked &&
            handler->handler.descriptor.event ==
                POKEMON_HANDLER_EVENT_MODIFY_MOVE &&
            handler->handler.descriptor.source_kind ==
                POKEMON_HANDLER_SOURCE_MOVE &&
            handler->handler.descriptor.source_id == POKEMON_GEN3_MOVE_STRUGGLE;
        found_rock_head |= handler->handler.descriptor.id ==
            POKEMON_GEN3_HANDLER_ROCK_HEAD;
    }
    assert(found_typeless);
    assert(!found_rock_head);
    assert(pokemon_battle_check_invariants(&battle));
}

static void test_explicit_move_slot_and_no_fallback(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_QUICKATTACK,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[0].members[0].move_ids[1] = POKEMON_GEN3_MOVE_SPLASH;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(battle.request.kind[0] == POKEMON_REQUEST_MOVE);
    assert(battle.request.legal_moves[0] == 0x03);
    assert(battle.request.forced_move_id[0] == 0);
    uint8_t first_pp = battle.sides[0].state[0].pp[0];
    uint8_t second_pp = battle.sides[0].state[0].pp[1];
    uint16_t target_hp = battle.sides[1].state[0].hp;
    PokemonChoice choices[POKEMON_SIDES] = {move(1), move(0)};
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].pp[0] == first_pp);
    assert(battle.sides[0].state[0].pp[1] == (uint8_t)(second_pp - 1));
    assert(battle.sides[0].state[0].last_move_id == POKEMON_GEN3_MOVE_SPLASH);
    assert(battle.sides[1].state[0].hp == target_hp);
    for (size_t i = 0; i < battle.last_queue.count; i++) {
        if (battle.last_queue.values[i].side != 0) continue;
        assert(battle.last_queue.values[i].selected_move_id ==
            POKEMON_GEN3_MOVE_SPLASH);
        assert(battle.last_queue.values[i].move_choice_kind ==
            POKEMON_MOVE_CHOICE_SELECTED_SLOT);
    }
    assert(pokemon_battle_check_invariants(&battle));
}

static void test_move_choice_reducer_composition(void) {
    PokemonMoveChoiceSlot slots[POKEMON_MOVE_CAPACITY] = {
        {10, 10, POKEMON_CATEGORY_PHYSICAL},
        {20, 10, POKEMON_CATEGORY_STATUS},
        {30, 0, POKEMON_CATEGORY_SPECIAL},
        {40, 10, POKEMON_CATEGORY_STATUS},
    };
    PokemonMoveRestriction restrictions[] = {
        {.kind = POKEMON_MOVE_RESTRICTION_DISABLE_EQUAL, .move_id = 40},
        {.kind = POKEMON_MOVE_RESTRICTION_DISABLE_CATEGORY,
            .category = POKEMON_CATEGORY_STATUS},
    };
    PokemonMoveChoiceSet set;
    assert(pokemon_reduce_move_choices(
        slots, POKEMON_MOVE_CAPACITY, 0, 99,
        restrictions, 2, &set) == POKEMON_OK);
    assert(set.kind == POKEMON_MOVE_CHOICE_SET_SELECTABLE);
    assert(set.legal_slot_mask == 1);

    restrictions[0] = (PokemonMoveRestriction){
        .kind = POKEMON_MOVE_RESTRICTION_DISABLE_UNEQUAL, .move_id = 30,
    };
    assert(pokemon_reduce_move_choices(
        slots, POKEMON_MOVE_CAPACITY, 0, 99,
        restrictions, 1, &set) == POKEMON_OK);
    assert(set.kind == POKEMON_MOVE_CHOICE_SET_FALLBACK);
    assert(set.synthetic_move_id == 99);

    assert(pokemon_reduce_move_choices(
        slots, POKEMON_MOVE_CAPACITY, 30, 99,
        restrictions, 1, &set) == POKEMON_OK);
    assert(set.kind == POKEMON_MOVE_CHOICE_SET_HARD_LOCK);
    assert(set.synthetic_move_id == 30);

    restrictions[0] = (PokemonMoveRestriction){
        .kind = POKEMON_MOVE_RESTRICTION_DISABLE_LAST_NONFALLBACK,
        .move_id = 10, .fallback_move_id = 99,
    };
    assert(pokemon_reduce_move_choices(
        slots, POKEMON_MOVE_CAPACITY, 0, 99,
        restrictions, 1, &set) == POKEMON_OK);
    assert(set.legal_slot_mask == ((1u << 1) | (1u << 3)));
    PokemonMoveChoiceSet before = set;
    restrictions[0].kind = (PokemonMoveRestrictionKind)99;
    assert(pokemon_reduce_move_choices(
        slots, POKEMON_MOVE_CAPACITY, 0, 99,
        restrictions, 1, &set) == POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&set, &before, sizeof(set)) == 0);

    PokemonChoiceControlPolicy policies[] = {
        {.owner_descriptor_id = 1,
         .request_op = POKEMON_CHOICE_REQUEST_DISABLE_STORED_MOVE,
         .action_op = POKEMON_CHOICE_ACTION_REJECT_STORED_MOVE,
         .request_handler_id = 900, .action_handler_id = 901,
         .action_priority = 7},
        {.owner_descriptor_id = 2,
         .request_op = POKEMON_CHOICE_REQUEST_DISABLE_CATEGORY,
         .action_op = POKEMON_CHOICE_ACTION_REJECT_CATEGORY,
         .request_handler_id = 902, .action_handler_id = 903,
         .category = POKEMON_CATEGORY_STATUS},
    };
    assert(pokemon_validate_choice_control_policies(policies, 2));
    policies[1].owner_descriptor_id = 1;
    assert(!pokemon_validate_choice_control_policies(policies, 2));
    policies[1].owner_descriptor_id = 2;
    policies[1].category = 0;
    assert(!pokemon_validate_choice_control_policies(policies, 2));
    policies[1].category = POKEMON_CATEGORY_STATUS;
    policies[0].residual_op =
        POKEMON_CHOICE_RESIDUAL_END_IF_STORED_MOVE_UNUSABLE;
    assert(!pokemon_validate_choice_control_policies(policies, 2));
    policies[0].residual_handler_id = 904;
    assert(pokemon_validate_choice_control_policies(policies, 2));
    policies[0].residual_op = POKEMON_CHOICE_RESIDUAL_NONE;
    assert(!pokemon_validate_choice_control_policies(policies, 2));

    policies[0] = (PokemonChoiceControlPolicy){
        .owner_descriptor_id = 1,
        .action_op = POKEMON_CHOICE_ACTION_OVERRIDE_WITH_STORED_MOVE,
        .action_handler_id = 901,
    };
    policies[1] = (PokemonChoiceControlPolicy){
        .owner_descriptor_id = 2,
        .action_op = POKEMON_CHOICE_ACTION_REJECT_CATEGORY,
        .action_handler_id = 903,
        .category = POKEMON_CATEGORY_STATUS,
    };
    PokemonVolatileState volatiles[] = {
        {.descriptor_id = 1, .effect_order = 1,
         .payload.choice_control = {.stored_move_id = 20}},
        {.descriptor_id = 2, .effect_order = 2},
    };
    PokemonChoiceActionDecision decision;
    assert(pokemon_apply_choice_action_stage(
        policies, 2, volatiles, 2, slots, 10,
        POKEMON_CHOICE_ACTION_STAGE_OVERRIDE, &decision) == POKEMON_OK);
    assert(decision.allowed && decision.executed_move_id == 20);
    assert(pokemon_apply_choice_action_stage(
        policies, 2, volatiles, 2, slots, decision.executed_move_id,
        POKEMON_CHOICE_ACTION_STAGE_GUARD, &decision) == POKEMON_OK);
    assert(!decision.allowed && decision.executed_move_id == 20);
}

static void test_switch_choice_reducer(void) {
    uint8_t legal = 0x16;
    PokemonSwitchRestriction restriction = {
        .kind = POKEMON_SWITCH_RESTRICTION_DISALLOW_ALL,
    };
    assert(pokemon_reduce_switch_choices(
        legal, POKEMON_SWITCH_CHOICE_VOLUNTARY,
        NULL, 0, &legal) == POKEMON_OK && legal == 0x16);
    assert(pokemon_reduce_switch_choices(
        legal, POKEMON_SWITCH_CHOICE_VOLUNTARY,
        &restriction, 1, &legal) == POKEMON_OK && legal == 0);
    assert(pokemon_reduce_switch_choices(
        0x16, POKEMON_SWITCH_CHOICE_FORCED_REPLACEMENT,
        &restriction, 1, &legal) == POKEMON_OK && legal == 0x16);

    restriction.hidden = 1;
    assert(pokemon_reduce_switch_choices(
        0x16, POKEMON_SWITCH_CHOICE_VOLUNTARY,
        &restriction, 1, &legal) == POKEMON_OK && legal == 0);
    assert(pokemon_reduce_switch_choices(
        0x16, POKEMON_SWITCH_CHOICE_FORCED_REPLACEMENT,
        &restriction, 1, &legal) == POKEMON_OK && legal == 0x16);

    PokemonSwitchRestriction storage[1] = {0};
    PokemonSwitchRestrictionBuffer buffer = {
        .values = storage, .capacity = 1,
    };
    assert(pokemon_append_switch_restriction(
        &buffer, restriction) == POKEMON_OK && buffer.count == 1);
    assert(pokemon_append_switch_restriction(
        &buffer, restriction) == POKEMON_CAPACITY_EXCEEDED);
    assert(buffer.count == 1 &&
        storage[0].kind == POKEMON_SWITCH_RESTRICTION_DISALLOW_ALL &&
        storage[0].hidden == 1);
}

static void test_transactional_choice_attempt(void) {
    PokemonSwitchRestriction trapped = {
        .kind = POKEMON_SWITCH_RESTRICTION_DISALLOW_ALL,
        .hidden = 1,
    };
    PokemonSwitchChoiceRequest request;
    assert(pokemon_make_switch_choice_request(
        0x06, POKEMON_SWITCH_CHOICE_VOLUNTARY, &trapped, 1,
        POKEMON_TRAP_DISCLOSURE_MAYBE, &request) == POKEMON_OK);
    assert(request.candidate_mask == 0x06 && request.definitive_mask == 0);

    PokemonChoiceAttemptState state = {
        .request_kind = POKEMON_REQUEST_MOVE,
        .legal_move_mask = 0x01,
        .switches = request,
    };
    PokemonChoiceAttemptOutcome outcome;
    assert(pokemon_attempt_choice(
        &state, switch_to(1), &outcome) == POKEMON_OK);
    assert(outcome == POKEMON_CHOICE_ATTEMPT_REJECTED_HIDDEN_TRAP);
    assert(state.switches.trap_disclosure == POKEMON_TRAP_DISCLOSURE_KNOWN);
    assert(state.switches.updated && !state.has_choice && !state.cant_undo);
    assert(pokemon_attempt_choice(&state, move(0), &outcome) == POKEMON_OK);
    assert(outcome == POKEMON_CHOICE_ATTEMPT_ACCEPTED);

    assert(pokemon_make_switch_choice_request(
        0x06, POKEMON_SWITCH_CHOICE_VOLUNTARY, NULL, 0,
        POKEMON_TRAP_DISCLOSURE_MAYBE, &request) == POKEMON_OK);
    state = (PokemonChoiceAttemptState){
        .request_kind = POKEMON_REQUEST_MOVE,
        .legal_move_mask = 0x01,
        .switches = request,
    };
    assert(pokemon_attempt_choice(
        &state, switch_to(1), &outcome) == POKEMON_OK);
    assert(outcome == POKEMON_CHOICE_ATTEMPT_ACCEPTED && state.cant_undo);
    PokemonChoiceAttemptState committed = state;
    assert(pokemon_attempt_choice(&state, move(0), &outcome) == POKEMON_OK);
    assert(outcome == POKEMON_CHOICE_ATTEMPT_REJECTED_CANT_UNDO);
    assert(memcmp(&state, &committed, sizeof(state)) == 0);

    assert(pokemon_make_switch_choice_request(
        0x06, POKEMON_SWITCH_CHOICE_FORCED_REPLACEMENT, &trapped, 1,
        POKEMON_TRAP_DISCLOSURE_NONE, &request) == POKEMON_OK);
    assert(request.definitive_mask == request.candidate_mask);
    state = (PokemonChoiceAttemptState){
        .request_kind = POKEMON_REQUEST_SWITCH,
        .switches = request,
    };
    assert(pokemon_attempt_choice(
        &state, switch_to(2), &outcome) == POKEMON_OK);
    assert(outcome == POKEMON_CHOICE_ATTEMPT_ACCEPTED && !state.cant_undo);
}

static void test_request_choice_kind_matrix(void) {
    PokemonSwitchChoiceRequest forced;
    assert(pokemon_make_switch_choice_request(
        0x06, POKEMON_SWITCH_CHOICE_FORCED_REPLACEMENT, NULL, 0,
        POKEMON_TRAP_DISCLOSURE_NONE, &forced) == POKEMON_OK);
    PokemonChoiceAttemptState switch_request = {
        .request_kind = POKEMON_REQUEST_SWITCH,
        .switches = forced,
    };
    PokemonChoiceAttemptOutcome outcome;
    PokemonChoiceAttemptState trial = switch_request;
    assert(pokemon_attempt_choice(&trial, switch_to(1), &outcome) == POKEMON_OK);
    assert(outcome == POKEMON_CHOICE_ATTEMPT_ACCEPTED);
    const PokemonChoice invalid_switch_choices[] = {
        {POKEMON_CHOICE_MOVE, 0},
        {POKEMON_CHOICE_NONE, 0},
        {(PokemonChoiceKind)99, 0},
    };
    for (size_t i = 0; i < sizeof(invalid_switch_choices) /
            sizeof(invalid_switch_choices[0]); i++) {
        trial = switch_request;
        assert(pokemon_attempt_choice(
            &trial, invalid_switch_choices[i], &outcome) ==
            POKEMON_ILLEGAL_CHOICE);
        assert(memcmp(&trial, &switch_request, sizeof(trial)) == 0);
    }

    PokemonSwitchChoiceRequest voluntary;
    assert(pokemon_make_switch_choice_request(
        0x06, POKEMON_SWITCH_CHOICE_VOLUNTARY, NULL, 0,
        POKEMON_TRAP_DISCLOSURE_NONE, &voluntary) == POKEMON_OK);
    PokemonChoiceAttemptState move_request = {
        .request_kind = POKEMON_REQUEST_MOVE,
        .legal_move_mask = 0x05,
        .switches = voluntary,
    };
    trial = move_request;
    assert(pokemon_attempt_choice(&trial, move(2), &outcome) == POKEMON_OK);
    assert(outcome == POKEMON_CHOICE_ATTEMPT_ACCEPTED);
    trial = move_request;
    assert(pokemon_attempt_choice(&trial, switch_to(2), &outcome) == POKEMON_OK);
    assert(outcome == POKEMON_CHOICE_ATTEMPT_ACCEPTED);
    const PokemonChoice invalid_move_choices[] = {
        {POKEMON_CHOICE_NONE, 0},
        {POKEMON_CHOICE_MOVE, 1},
        {(PokemonChoiceKind)99, 0},
    };
    for (size_t i = 0; i < sizeof(invalid_move_choices) /
            sizeof(invalid_move_choices[0]); i++) {
        trial = move_request;
        assert(pokemon_attempt_choice(
            &trial, invalid_move_choices[i], &outcome) ==
            POKEMON_ILLEGAL_CHOICE);
        assert(memcmp(&trial, &move_request, sizeof(trial)) == 0);
    }
}

static void test_disabled_selection_does_not_force_fallback(void) {
    PokemonMoveChoiceSlot slots[POKEMON_MOVE_CAPACITY] = {
        {POKEMON_GEN3_MOVE_POUND, 10, POKEMON_CATEGORY_PHYSICAL},
        {POKEMON_GEN3_MOVE_SPLASH, 10, POKEMON_CATEGORY_STATUS},
    };
    PokemonMoveRestriction disabled = {
        .kind = POKEMON_MOVE_RESTRICTION_DISABLE_EQUAL,
        .move_id = POKEMON_GEN3_MOVE_POUND,
    };
    PokemonMoveChoiceSet choices;
    assert(pokemon_reduce_move_choices(
        slots, POKEMON_MOVE_CAPACITY, 0, POKEMON_GEN3_MOVE_STRUGGLE,
        &disabled, 1, &choices) == POKEMON_OK);
    assert(choices.kind == POKEMON_MOVE_CHOICE_SET_SELECTABLE);
    assert(choices.legal_slot_mask == 0x02);
    assert(choices.synthetic_move_id == 0);

    PokemonChoiceAttemptState request = {
        .request_kind = POKEMON_REQUEST_MOVE,
        .legal_move_mask = choices.legal_slot_mask,
    };
    PokemonChoiceAttemptState trial = request;
    PokemonChoiceAttemptOutcome outcome;
    assert(pokemon_attempt_choice(&trial, move(0), &outcome) ==
        POKEMON_ILLEGAL_CHOICE);
    assert(memcmp(&trial, &request, sizeof(trial)) == 0);
    assert(pokemon_attempt_choice(&trial, move(1), &outcome) == POKEMON_OK);
    assert(outcome == POKEMON_CHOICE_ATTEMPT_ACCEPTED);
}

static void test_hidden_trap_rejection_updates_only_request(void) {
    PokemonBattleInit init = {
        .bundle = &POKEMON_GEN3_OU_BUNDLE,
        .team_sizes = {1, 2},
        .seed = {1, 2, 3, 4},
    };
    init.teams[0].members[0] = make_set(
        POKEMON_GEN3_SPECIES_DIGLETT, POKEMON_GEN3_MOVE_SCRATCH,
        161, 146, 86, 106, 126, 226);
    init.teams[0].members[0].ability_id = POKEMON_GEN3_ABILITY_ARENATRAP;
    init.teams[1].members[0] = make_set(
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_TACKLE,
        271, 176, 156, 166, 166, 266);
    init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_LIMBER;
    init.teams[1].members[1] = make_set(
        POKEMON_GEN3_SPECIES_VAPOREON, POKEMON_GEN3_MOVE_TACKLE,
        401, 166, 156, 256, 226, 166);
    init.teams[1].members[1].ability_id = POKEMON_GEN3_ABILITY_WATERABSORB;

    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(battle.request.legal_switches[1] == 2);
    assert(battle.request.switch_choices[1].candidate_mask == 2);
    assert(battle.request.switch_choices[1].definitive_mask == 0);
    assert(battle.request.switch_choices[1].trap_disclosure ==
        POKEMON_TRAP_DISCLOSURE_MAYBE);
    uint16_t seed_before[4];
    memcpy(seed_before, battle.seed, sizeof(seed_before));
    uint32_t turn_before = battle.turn;
    uint16_t hp_before[2] = {
        battle.sides[0].state[0].hp, battle.sides[1].state[0].hp,
    };
    PokemonChoice rejected[POKEMON_SIDES] = {move(0), switch_to(1)};
    assert(pokemon_battle_step(&battle, rejected) == POKEMON_ILLEGAL_CHOICE);
    assert(battle.turn == turn_before);
    assert(memcmp(seed_before, battle.seed, sizeof(seed_before)) == 0);
    assert(battle.sides[0].state[0].hp == hp_before[0]);
    assert(battle.sides[1].state[0].hp == hp_before[1]);
    assert(battle.request.legal_switches[1] == 0);
    assert(battle.request.switch_choices[1].trap_disclosure ==
        POKEMON_TRAP_DISCLOSURE_KNOWN);
    assert(battle.request.switch_choices[1].updated);

    PokemonChoice retry[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_step(&battle, retry) == POKEMON_OK);
    assert(battle.turn == turn_before + 1);
    assert(pokemon_battle_check_invariants(&battle));
}

static void test_choice_override_changes_execution_not_queue_priority(void) {
    PokemonChoiceControlPolicy policy = {
        .owner_descriptor_id = POKEMON_GEN3_CONDITION_VOLATILE_FOCUSENERGY,
        .request_op = POKEMON_CHOICE_REQUEST_DISABLE_CATEGORY,
        .action_op = POKEMON_CHOICE_ACTION_OVERRIDE_WITH_STORED_MOVE,
        .category = POKEMON_CATEGORY_STATUS,
        .request_handler_id = 902,
        .action_handler_id = 901,
    };
    PokemonGeneration generation = POKEMON_GEN3_RULES;
    generation.choice_control_policies = &policy;
    generation.choice_control_policy_count = 1;
    PokemonResolvedBundle bundle = POKEMON_GEN3_OU_BUNDLE;
    bundle.rules = &generation;
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_QUICKATTACK,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SPLASH);
    init.bundle = &bundle;
    init.teams[0].members[0].move_ids[1] = POKEMON_GEN3_MOVE_THIEF;
    init.teams[0].members[0].move_ids[2] = POKEMON_GEN3_MOVE_SPLASH;
    init.teams[1].members[0].stats[0] = 500;
    init.teams[1].members[0].stats[2] = 300;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    PokemonMutable *holder = &battle.sides[0].state[0];
    holder->volatiles[0] = (PokemonVolatileState){
        .kind = POKEMON_VOLATILE_FOCUS_ENERGY,
        .descriptor_id = POKEMON_GEN3_CONDITION_VOLATILE_FOCUSENERGY,
        .state_generation = 1,
        .effect_order = ++battle.next_holder_effect_order,
        .payload.choice_control = {.stored_move_id = POKEMON_GEN3_MOVE_THIEF},
    };
    holder->volatile_count = 1;
    uint8_t quick_attack_pp = holder->pp[0];
    uint8_t thief_pp = holder->pp[1];
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.last_queue.values[0].selected_move_id ==
        POKEMON_GEN3_MOVE_QUICKATTACK);
    assert(holder->last_move_id == POKEMON_GEN3_MOVE_THIEF);
    assert(holder->pp[0] == quick_attack_pp);
    assert(holder->pp[1] == (uint8_t)(thief_pp - 1));
    assert(battle.request.legal_moves[0] == ((1u << 0) | (1u << 1)));

    policy.action_op = POKEMON_CHOICE_ACTION_REJECT_CATEGORY;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    holder = &battle.sides[0].state[0];
    holder->volatiles[0] = (PokemonVolatileState){
        .kind = POKEMON_VOLATILE_FOCUS_ENERGY,
        .descriptor_id = POKEMON_GEN3_CONDITION_VOLATILE_FOCUSENERGY,
        .state_generation = 1,
        .effect_order = ++battle.next_holder_effect_order,
    };
    holder->volatile_count = 1;
    uint8_t splash_pp = holder->pp[2];
    choices[0] = move(2);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(holder->pp[2] == splash_pp);
    assert(holder->last_move_id == 0);
    assert(battle.request.legal_moves[0] == ((1u << 0) | (1u << 1)));
    uint8_t found_guard = 0;
    for (size_t i = 0; i < battle.handler_count; i++) {
        found_guard |= battle.handlers[i].handler.descriptor.id == 901 &&
            battle.handlers[i].result == POKEMON_HANDLER_PREVENT;
    }
    assert(found_guard);
}

static void test_imprison_foe_scoped_choice_lifecycle(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_IMPRISON,
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[0].members[0].move_ids[1] = POKEMON_GEN3_MOVE_SPLASH;
    init.teams[1].members[0].move_ids[1] = POKEMON_GEN3_MOVE_POUND;
    init.teams[0].members[0].stats[5] = 200;
    init.teams[1].members[0].stats[5] = 100;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    uint8_t splash_pp = battle.sides[1].state[0].pp[0];
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(test_volatile_index(
        &battle.sides[0].state[0], POKEMON_VOLATILE_IMPRISON) >= 0);
    assert(battle.sides[1].state[0].pp[0] == splash_pp);
    assert(battle.sides[1].state[0].last_move_id == 0);
    assert(battle.request.legal_moves[1] == (1u << 1));
    uint8_t found_request = 0, found_guard = 0;
    for (size_t i = 0; i < battle.handler_count; i++) {
        const PokemonHandlerInvocation *handler = &battle.handlers[i];
        found_request |= handler->handler.descriptor.id ==
            POKEMON_GEN3_HANDLER_IMPRISON_DISABLE_MOVE;
        found_guard |= handler->handler.descriptor.id ==
                POKEMON_GEN3_HANDLER_IMPRISON_BEFORE_MOVE &&
            handler->result == POKEMON_HANDLER_PREVENT;
    }
    assert(found_request && found_guard);
    assert(pokemon_battle_check_invariants(&battle));

    PokemonBattleInit no_shared = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_IMPRISON,
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_POUND);
    assert(pokemon_battle_init(&battle, &no_shared) == POKEMON_OK);
    uint8_t imprison_pp = battle.sides[0].state[0].pp[0];
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(test_volatile_index(
        &battle.sides[0].state[0], POKEMON_VOLATILE_IMPRISON) < 0);
    assert(battle.sides[0].state[0].pp[0] == (uint8_t)(imprison_pp - 1));
    assert(pokemon_battle_check_invariants(&battle));

    PokemonHandlerOp programs[POKEMON_GEN3_SLICE_DATA.handler_program_count];
    memcpy(programs, POKEMON_GEN3_SLICE_DATA.handler_programs,
        sizeof(programs));
    uint8_t found_try_hit = 0;
    for (size_t i = 0; i < POKEMON_GEN3_SLICE_DATA.handler_count; i++) {
        const PokemonHandlerDescriptor *descriptor =
            &POKEMON_GEN3_SLICE_DATA.handlers[i];
        if (descriptor->id != POKEMON_GEN3_HANDLER_IMPRISON_TRY_HIT) continue;
        programs[descriptor->program_offset].argument = 1;
        found_try_hit = 1;
    }
    assert(found_try_hit);
    PokemonData invalid_data = POKEMON_GEN3_SLICE_DATA;
    invalid_data.handler_programs = programs;
    PokemonBattleInit invalid_init = init;
    PokemonResolvedBundle invalid_bundle = POKEMON_GEN3_OU_BUNDLE;
    invalid_bundle.data = &invalid_data;
    invalid_init.bundle = &invalid_bundle;
    assert(pokemon_battle_init(&battle, &invalid_init) == POKEMON_OK);
    PokemonBattle before = battle;
    assert(pokemon_battle_step(&battle, choices) ==
        POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&battle, &before, sizeof(battle)) == 0);
}

static void test_taunt_choice_control_lifecycle(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_TAUNT,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[0].members[0].move_ids[1] = POKEMON_GEN3_MOVE_SPLASH;
    init.teams[0].members[0].stats[0] = 500;
    init.teams[1].members[0].stats[0] = 500;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    uint8_t splash_pp = battle.sides[1].state[0].pp[0];
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    int taunt = test_volatile_index(
        &battle.sides[1].state[0], POKEMON_VOLATILE_TAUNT);
    assert(taunt >= 0);
    assert(battle.sides[1].state[0].volatiles[taunt].duration == 1);
    assert(battle.sides[1].state[0].pp[0] == splash_pp);
    assert(battle.sides[1].state[0].last_move_id == 0);
    assert(battle.request.legal_moves[1] == 1);
    assert(battle.request.forced_move_id[1] == POKEMON_GEN3_MOVE_STRUGGLE);
    uint8_t found_guard = 0, found_request = 0;
    for (size_t i = 0; i < battle.handler_count; i++) {
        const PokemonHandlerInvocation *handler = &battle.handlers[i];
        found_guard |= handler->handler.descriptor.event ==
                POKEMON_HANDLER_EVENT_BEFORE_MOVE &&
            handler->handler.descriptor.source_id ==
                POKEMON_GEN3_CONDITION_VOLATILE_TAUNT &&
            handler->result == POKEMON_HANDLER_PREVENT;
        found_request |= handler->handler.descriptor.event ==
                POKEMON_HANDLER_EVENT_DISABLE_MOVE &&
            handler->handler.descriptor.source_id ==
                POKEMON_GEN3_CONDITION_VOLATILE_TAUNT;
    }
    assert(found_guard && found_request);

    choices[0] = move(1);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(test_volatile_index(
        &battle.sides[1].state[0], POKEMON_VOLATILE_TAUNT) < 0);
    assert(battle.sides[1].state[0].last_move_id == POKEMON_GEN3_MOVE_STRUGGLE);
    assert(battle.sides[1].state[0].pp[0] == splash_pp);
    assert(battle.request.forced_move_id[1] == 0);
    assert(battle.request.legal_moves[1] == 1);
    assert(pokemon_battle_check_invariants(&battle));
}

static void test_torment_request_time_cycle(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_TORMENT,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[0].members[0].move_ids[1] = POKEMON_GEN3_MOVE_SPLASH;
    init.teams[0].members[0].stats[0] = 500;
    init.teams[1].members[0].stats[0] = 500;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    uint8_t splash_pp = battle.sides[1].state[0].pp[0];
    PokemonChoice choices[POKEMON_SIDES] = {move(1), move(0)};

    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].state[0].last_move_id == POKEMON_GEN3_MOVE_SPLASH);
    assert(battle.sides[1].state[0].pp[0] == (uint8_t)(splash_pp - 1));

    choices[0] = move(0);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    int torment = test_volatile_index(
        &battle.sides[1].state[0], POKEMON_VOLATILE_TORMENT);
    assert(torment >= 0);
    assert(battle.sides[1].state[0].volatiles[torment].duration == 0);
    /* Torment has no execution guard: the slower action was already queued
     * and therefore executes once before the next request is restricted. */
    assert(battle.sides[1].state[0].pp[0] == (uint8_t)(splash_pp - 2));
    assert(battle.request.forced_move_id[1] == POKEMON_GEN3_MOVE_STRUGGLE);

    choices[0] = move(1);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].state[0].last_move_id == POKEMON_GEN3_MOVE_STRUGGLE);
    assert(battle.sides[1].state[0].pp[0] == (uint8_t)(splash_pp - 2));
    assert(battle.request.forced_move_id[1] == 0);
    assert(battle.request.legal_moves[1] == 1);

    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].state[0].last_move_id == POKEMON_GEN3_MOVE_SPLASH);
    assert(battle.sides[1].state[0].pp[0] == (uint8_t)(splash_pp - 3));
    assert(battle.request.forced_move_id[1] == POKEMON_GEN3_MOVE_STRUGGLE);
    assert(test_volatile_index(
        &battle.sides[1].state[0], POKEMON_VOLATILE_TORMENT) >= 0);
    assert(pokemon_battle_check_invariants(&battle));
}

static void test_disable_atomic_start_and_queued_guard(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_DISABLE,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_POUND);
    init.teams[0].members[0].move_ids[1] = POKEMON_GEN3_MOVE_SPLASH;
    init.teams[1].members[0].move_ids[1] = POKEMON_GEN3_MOVE_SPLASH;
    init.teams[0].members[0].stats[0] = 500;
    init.teams[1].members[0].stats[0] = 500;
    PokemonBattle battle;
    uint8_t pound_pp = 0;
    PokemonChoice choices[POKEMON_SIDES] = {move(1), move(0)};
    uint8_t proved_early_admission = 0;
    for (uint16_t tail = 1; tail < 2048 && !proved_early_admission; tail++) {
        init.seed[3] = tail;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        choices[0] = move(0);
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        for (size_t i = 0; i < battle.draw_count; i++) {
            if (battle.draws[i].label == POKEMON_DRAW_ACCURACY &&
                battle.draws[i].result < 55) proved_early_admission = 1;
        }
        if (proved_early_admission) {
            assert(test_volatile_index(
                &battle.sides[1].state[0], POKEMON_VOLATILE_DISABLE) < 0);
            assert(draw_label_count(
                &battle, POKEMON_DRAW_DISABLE_DURATION) == 0);
            uint8_t found_move_try_hit = 0;
            for (size_t i = 0; i < battle.handler_count; i++) {
                const PokemonHandlerInvocation *handler = &battle.handlers[i];
                found_move_try_hit |= handler->handler.descriptor.id ==
                        POKEMON_GEN3_HANDLER_DISABLE_TRY_HIT &&
                    handler->handler.descriptor.source_kind ==
                        POKEMON_HANDLER_SOURCE_MOVE &&
                    handler->handler.descriptor.route ==
                        POKEMON_HANDLER_ROUTE_MOVE_SELF &&
                    handler->handler.descriptor.event ==
                        POKEMON_HANDLER_EVENT_TRY_HIT &&
                    handler->result == POKEMON_HANDLER_PREVENT;
            }
            assert(found_move_try_hit);
        }
    }
    assert(proved_early_admission);

    /* Start revalidates PP after TryHit. A last move which became unusable
     * still consumes the condition-owned duration draw and invokes Start, but
     * commits neither owner state nor Add evidence. The provisional holder
     * identity advances effect order and is deliberately not rewound. */
    uint8_t proved_start_rollback = 0;
    for (uint16_t tail = 1; tail < 2048 && !proved_start_rollback; tail++) {
        init.seed[3] = tail;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        choices[0] = move(1);
        choices[1] = move(0);
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        test_set_base_backed_pp(&battle, 1, 0, 0, 0);
        uint16_t effect_order_before = battle.next_holder_effect_order;
        choices[0] = move(0);
        choices[1] = move(1);
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        if (draw_label_count(&battle, POKEMON_DRAW_DISABLE_DURATION) == 0) {
            continue;
        }
        proved_start_rollback = 1;
        assert(test_volatile_index(
            &battle.sides[1].state[0], POKEMON_VOLATILE_DISABLE) < 0);
        assert(battle.next_holder_effect_order ==
            (uint16_t)(effect_order_before + 1u));
        uint8_t found_rejected_start = 0;
        for (size_t i = 0; i < battle.handler_count; i++) {
            const PokemonHandlerInvocation *handler = &battle.handlers[i];
            found_rejected_start |= handler->handler.descriptor.event ==
                    POKEMON_HANDLER_EVENT_START &&
                handler->handler.descriptor.source_id ==
                    POKEMON_GEN3_CONDITION_VOLATILE_DISABLE &&
                handler->result == POKEMON_HANDLER_PREVENT;
        }
        assert(found_rejected_start);
        for (size_t i = 0; i < battle.condition_trace_count; i++) {
            assert(!(battle.condition_traces[i].operation ==
                    POKEMON_CONDITION_ADD &&
                battle.condition_traces[i].condition_id ==
                    POKEMON_VOLATILE_DISABLE));
        }
    }
    assert(proved_start_rollback);
    init.teams[1].members[0].move_ids[1] = 0;
    choices[1] = move(0);

    int disable = -1;
    for (uint16_t tail = 1; tail < 2048 && disable < 0; tail++) {
        init.seed[3] = tail;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        pound_pp = battle.sides[1].state[0].pp[0];
        choices[0] = move(1);
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        assert(battle.sides[1].state[0].last_move_id ==
            POKEMON_GEN3_MOVE_POUND);
        choices[0] = move(0);
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        disable = test_volatile_index(
            &battle.sides[1].state[0], POKEMON_VOLATILE_DISABLE);
    }
    assert(disable >= 0);
    const PokemonVolatileState *owner =
        &battle.sides[1].state[0].volatiles[disable];
    assert(owner->payload.choice_control.stored_move_id ==
        POKEMON_GEN3_MOVE_POUND);
    assert(owner->duration >= 1 && owner->duration <= 4);
    assert(draw_label_count(&battle, POKEMON_DRAW_DISABLE_DURATION) == 1);
    /* Disable owns an execution guard, unlike Torment. The slower queued
     * Pound is rejected before PP deduction, then the request falls back. */
    assert(battle.sides[1].state[0].pp[0] == (uint8_t)(pound_pp - 1));
    assert(battle.request.forced_move_id[1] == POKEMON_GEN3_MOVE_STRUGGLE);
    uint8_t found_start = 0, found_guard = 0, found_request = 0;
    for (size_t i = 0; i < battle.handler_count; i++) {
        const PokemonHandlerInvocation *handler = &battle.handlers[i];
        if (handler->handler.descriptor.source_id !=
                POKEMON_GEN3_CONDITION_VOLATILE_DISABLE) continue;
        found_start |= handler->handler.descriptor.event ==
            POKEMON_HANDLER_EVENT_START;
        found_guard |= handler->handler.descriptor.event ==
                POKEMON_HANDLER_EVENT_BEFORE_MOVE &&
            handler->result == POKEMON_HANDLER_PREVENT;
        found_request |= handler->handler.descriptor.event ==
            POKEMON_HANDLER_EVENT_DISABLE_MOVE;
    }
    assert(found_start && found_guard && found_request);
    assert(pokemon_battle_check_invariants(&battle));
}

static void test_encore_choice_control_lifecycle(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_ALAKAZAM, POKEMON_GEN3_MOVE_ENCORE,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_RECOVER);
    init.teams[0].members[0].move_ids[1] = POKEMON_GEN3_MOVE_SPLASH;
    init.teams[1].members[0].move_ids[1] = POKEMON_GEN3_MOVE_SPLASH;
    init.teams[0].members[0].stats[0] = 500;
    init.teams[1].members[0].stats[0] = 500;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    uint8_t recover_pp = battle.sides[1].state[0].pp[0];
    uint8_t splash_pp = battle.sides[1].state[0].pp[1];
    PokemonChoice choices[POKEMON_SIDES] = {move(1), move(0)};
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);

    /* A faster Encore captures the previous move before the target's queued
     * choice executes. OverrideAction changes execution, not queue ordering:
     * the selected Splash spends no PP and Recover executes a second time. */
    choices[0] = move(0);
    choices[1] = move(1);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    int encore = test_volatile_index(
        &battle.sides[1].state[0], POKEMON_VOLATILE_ENCORE);
    assert(encore >= 0);
    const PokemonVolatileState *owner =
        &battle.sides[1].state[0].volatiles[encore];
    assert(owner->payload.choice_control.stored_move_id ==
        POKEMON_GEN3_MOVE_RECOVER);
    assert(owner->duration >= 2 && owner->duration <= 5);
    assert(battle.sides[1].state[0].pp[0] == (uint8_t)(recover_pp - 2));
    assert(battle.sides[1].state[0].pp[1] == splash_pp);
    assert(battle.request.legal_moves[1] == 1u);
    assert(draw_label_count(&battle, POKEMON_DRAW_ENCORE_DURATION) == 1);
    uint8_t found_start = 0, found_override = 0, found_request = 0;
    for (size_t i = 0; i < battle.handler_count; i++) {
        const PokemonHandlerInvocation *handler = &battle.handlers[i];
        if (handler->handler.descriptor.source_id !=
                POKEMON_GEN3_CONDITION_VOLATILE_ENCORE) continue;
        found_start |= handler->handler.descriptor.event ==
            POKEMON_HANDLER_EVENT_START;
        found_override |= handler->handler.descriptor.event ==
            POKEMON_HANDLER_EVENT_OVERRIDE_ACTION;
        found_request |= handler->handler.descriptor.event ==
            POKEMON_HANDLER_EVENT_DISABLE_MOVE;
    }
    assert(found_start && found_override && found_request);
    assert(pokemon_battle_check_invariants(&battle));

    /* Residual owns the zero-PP early end. It invokes Encore's End handler,
     * removes the exact volatile instance, and restores the ordinary request. */
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    choices[0] = move(1);
    choices[1] = move(0);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    test_set_base_backed_pp(&battle, 1, 0, 0, 1);
    choices[0] = move(0);
    choices[1] = move(1);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].state[0].pp[0] == 0);
    assert(test_volatile_index(
        &battle.sides[1].state[0], POKEMON_VOLATILE_ENCORE) < 0);
    assert(battle.request.legal_moves[1] == 2u);
    uint8_t found_residual = 0, found_end = 0, found_remove = 0;
    for (size_t i = 0; i < battle.handler_count; i++) {
        const PokemonHandlerInvocation *handler = &battle.handlers[i];
        if (handler->handler.descriptor.source_id !=
                POKEMON_GEN3_CONDITION_VOLATILE_ENCORE) continue;
        found_residual |= handler->handler.descriptor.event ==
            POKEMON_HANDLER_EVENT_RESIDUAL;
        found_end |= handler->handler.descriptor.event ==
            POKEMON_HANDLER_EVENT_END;
    }
    for (size_t i = 0; i < battle.condition_trace_count; i++) {
        found_remove |= battle.condition_traces[i].condition_id ==
                POKEMON_VOLATILE_ENCORE &&
            battle.condition_traces[i].operation == POKEMON_CONDITION_REMOVE;
    }
    assert(found_residual && found_end && found_remove);
    assert(pokemon_battle_check_invariants(&battle));

    /* A slower Encore starts after the target acted. Gen 3 adds one turn
     * before the same-turn residual decrement, leaving the sampled duration. */
    init.teams[0].members[0].stats[5] = 100;
    init.teams[1].members[0].stats[5] = 300;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    choices[0] = move(1);
    choices[1] = move(0);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    choices[0] = move(0);
    choices[1] = move(0);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    encore = test_volatile_index(
        &battle.sides[1].state[0], POKEMON_VOLATILE_ENCORE);
    assert(encore >= 0);
    uint8_t sampled_duration = 0;
    for (size_t i = 0; i < battle.draw_count; i++) {
        if (battle.draws[i].label == POKEMON_DRAW_ENCORE_DURATION) {
            sampled_duration = (uint8_t)battle.draws[i].result;
        }
    }
    assert(sampled_duration >= 3 && sampled_duration <= 6);
    assert(battle.sides[1].state[0].volatiles[encore].duration ==
        sampled_duration);
    assert(pokemon_battle_check_invariants(&battle));
}

static void test_choice_control_start_policies(void) {
    PokemonChoiceControlStart start = {0};
    PokemonChoiceControlPolicy disable = {
        .owner_descriptor_id = 77,
        .start_op = POKEMON_CHOICE_START_CAPTURE_LAST_USABLE_MOVE,
        .start_duration_op =
            POKEMON_CHOICE_START_DURATION_INCREMENT_IF_ALREADY_MOVED,
    };
    assert(pokemon_prepare_choice_control_start(
        &disable, 20, POKEMON_MOVE_SLOT_PRESENT_WITH_PP, 0, 1, 5, &start) ==
        POKEMON_OK);
    assert(start.admitted && start.stored_move_id == 20 && start.duration == 5);
    assert(pokemon_prepare_choice_control_start(
        &disable, 20, POKEMON_MOVE_SLOT_PRESENT_ZERO_PP, 1, 0, 3, &start) ==
        POKEMON_OK);
    assert(!start.admitted && start.stored_move_id == 0 && start.duration == 3);
    assert(pokemon_prepare_choice_control_start(
        &disable, 20, POKEMON_MOVE_SLOT_ABSENT, 1, 0, 3, &start) ==
        POKEMON_OK);
    assert(start.admitted && start.stored_move_id == 20);

    PokemonChoiceControlPolicy encore = {
        .owner_descriptor_id = 78,
        .start_op =
            POKEMON_CHOICE_START_CAPTURE_LAST_ENCORE_ELIGIBLE_MOVE,
        .start_duration_op =
            POKEMON_CHOICE_START_DURATION_INCREMENT_IF_ALREADY_MOVED,
    };
    assert(pokemon_prepare_choice_control_start(
        &encore, 20, POKEMON_MOVE_SLOT_PRESENT_WITH_PP, 1, 1, 3, &start) ==
        POKEMON_OK);
    assert(start.admitted && start.stored_move_id == 20 && start.duration == 3);
    assert(pokemon_prepare_choice_control_start(
        &encore, 20, POKEMON_MOVE_SLOT_PRESENT_WITH_PP, 1, 0, 6, &start) ==
        POKEMON_OK);
    assert(start.admitted && start.duration == 7);
    assert(pokemon_prepare_choice_control_start(
        &encore, 20, POKEMON_MOVE_SLOT_PRESENT_WITH_PP, 0, 0, 4, &start) ==
        POKEMON_OK);
    assert(!start.admitted && start.stored_move_id == 0 && start.duration == 4);
    assert(pokemon_prepare_choice_control_start(
        &encore, 20, POKEMON_MOVE_SLOT_ABSENT, 1, 0, 4, &start) ==
        POKEMON_OK);
    assert(!start.admitted);
}

static void test_choice_band_choice_lock_lifecycle(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_TACKLE,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[0].members[0].move_ids[1] = POKEMON_GEN3_MOVE_HOWL;
    init.teams[0].members[0].item_id = POKEMON_GEN3_ITEM_CHOICEBAND;
    init.teams[0].members[0].stats[0] = 500;
    init.teams[1].members[0].stats[0] = 1000;
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);

    PokemonMutable *holder = &battle.sides[0].state[0];
    int lock = test_volatile_index(holder, POKEMON_VOLATILE_CHOICE_LOCK);
    assert(lock >= 0);
    assert(holder->volatiles[lock].duration == 0);
    assert(holder->volatiles[lock].payload.choice_control.stored_move_id ==
        POKEMON_GEN3_MOVE_TACKLE);
    assert(battle.request.legal_moves[0] == 1u);
    assert(battle.request.legal_switches[0] != 0);
    uint8_t found_choice_band_modifier = 0;
    for (size_t i = 0; i < battle.modifier_count; i++) {
        found_choice_band_modifier |=
            battle.modifiers[i].handler.descriptor.id ==
                POKEMON_GEN3_HANDLER_CHOICE_BAND_MODIFY_ATK &&
            battle.modifiers[i].modifier_after_q12 == 6144;
    }
    assert(found_choice_band_modifier);
    assert(handler_event_count(
        &battle, POKEMON_HANDLER_EVENT_AFTER_MOVE) == 1);
    assert(handler_event_count(
        &battle, POKEMON_HANDLER_EVENT_DISABLE_MOVE) == 1);
    assert(handler_event_count(
        &battle, POKEMON_HANDLER_EVENT_BEFORE_MOVE) == 0);

    /* Generic switch cleanup owns the volatile lifetime.  Returning the same
     * holder exposes both move slots again. */
    choices[0] = switch_to(1);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(test_volatile_index(
        &battle.sides[0].state[0], POKEMON_VOLATILE_CHOICE_LOCK) < 0);
    choices[0] = switch_to(0);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.request.legal_moves[0] == 3u);
    assert(pokemon_battle_check_invariants(&battle));

    /* DisableMove removes the exact stale owner when the required held item
     * is gone.  This is the shared item-loss boundary used by Knock Off. */
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    choices[0] = move(0);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    holder = &battle.sides[0].state[0];
    assert(test_volatile_index(holder, POKEMON_VOLATILE_CHOICE_LOCK) >= 0);
    holder->item_id = 0;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(test_volatile_index(holder, POKEMON_VOLATILE_CHOICE_LOCK) < 0);
    assert(battle.request.legal_moves[0] == 3u);
    assert(pokemon_battle_check_invariants(&battle));

    /* A plugin cannot name a required held item outside its own immutable
     * data bundle.  Bundle rejection precedes state construction and draws. */
    PokemonGeneration rules = POKEMON_GEN3_RULES;
    PokemonChoiceControlPolicy policies[8];
    assert(rules.choice_control_policy_count ==
        sizeof(policies) / sizeof(policies[0]));
    memcpy(policies, rules.choice_control_policies, sizeof(policies));
    size_t choice_lock_policy = SIZE_MAX;
    for (size_t i = 0; i < rules.choice_control_policy_count; i++) {
        if (policies[i].owner_descriptor_id ==
                POKEMON_GEN3_CONDITION_VOLATILE_CHOICELOCK) {
            choice_lock_policy = i;
        }
    }
    assert(choice_lock_policy != SIZE_MAX);
    policies[choice_lock_policy].required_held_item_id = UINT16_MAX;
    rules.choice_control_policies = policies;
    PokemonResolvedBundle invalid_bundle = POKEMON_GEN3_OU_BUNDLE;
    invalid_bundle.rules = &rules;
    PokemonBattleInit invalid_init = init;
    invalid_init.bundle = &invalid_bundle;
    PokemonBattle rejected;
    memset(&rejected, 0xa5, sizeof(rejected));
    PokemonBattle rejected_before = rejected;
    assert(pokemon_battle_init(&rejected, &invalid_init) ==
        POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&rejected, &rejected_before, sizeof(rejected)) == 0);
}

static void test_choice_control_residual_ends_exact_unusable_owner(void) {
    assert(POKEMON_GEN3_RULES.choice_control_policy_count == 8);
    assert(POKEMON_GEN3_RULES.condition_rule_count == 61);
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_POUND,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[0].members[0].move_ids[1] = POKEMON_GEN3_MOVE_SPLASH;
    init.teams[0].members[0].stats[0] = 500;
    init.teams[1].members[0].stats[0] = 500;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    PokemonMutable *holder = &battle.sides[0].state[0];
    holder->pp[0] = 2;
    holder->volatiles[0] = (PokemonVolatileState){
        .kind = POKEMON_VOLATILE_ENCORE,
        .descriptor_id = POKEMON_GEN3_CONDITION_VOLATILE_ENCORE,
        .duration = 3,
        .state_generation = 9,
        .effect_order = ++battle.next_holder_effect_order,
        .source = {POKEMON_ENTITY_POKEMON, 1, 0},
        .source_effect = {POKEMON_SOURCE_EFFECT_MOVE,
            POKEMON_GEN3_MOVE_ENCORE},
        .payload.choice_control = {.stored_move_id = POKEMON_GEN3_MOVE_POUND},
    };
    holder->volatile_count = 1;

    PokemonChoice choices[POKEMON_SIDES] = {move(1), move(0)};
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(holder->last_move_id == POKEMON_GEN3_MOVE_POUND);
    assert(holder->pp[0] == 1);
    int owner = test_volatile_index(holder, POKEMON_VOLATILE_ENCORE);
    assert(owner >= 0 && holder->volatiles[owner].duration == 2);
    assert(battle.request.legal_moves[0] == 1);

    choices[0] = move(0);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(holder->pp[0] == 0);
    assert(test_volatile_index(holder, POKEMON_VOLATILE_ENCORE) < 0);
    assert(battle.request.legal_moves[0] == (1u << 1));
    uint8_t found_residual = 0, found_end = 0, found_remove = 0;
    for (size_t i = 0; i < battle.handler_count; i++) {
        const PokemonHandlerInvocation *invocation = &battle.handlers[i];
        if (invocation->handler.descriptor.source_id !=
                POKEMON_GEN3_CONDITION_VOLATILE_ENCORE) continue;
        found_residual |= invocation->handler.descriptor.event ==
                POKEMON_HANDLER_EVENT_RESIDUAL &&
            invocation->handler.descriptor.order == 10 &&
            invocation->handler.descriptor.sub_order == 14;
        found_end |= invocation->handler.descriptor.event ==
            POKEMON_HANDLER_EVENT_END;
    }
    for (size_t i = 0; i < battle.condition_trace_count; i++) {
        const PokemonConditionTrace *trace = &battle.condition_traces[i];
        found_remove |= trace->scope == POKEMON_CONDITION_SCOPE_VOLATILE &&
            trace->condition_id == POKEMON_VOLATILE_ENCORE &&
            trace->operation == POKEMON_CONDITION_REMOVE &&
            trace->reason == POKEMON_CONDITION_REASON_HANDLER &&
            trace->has_duration_before && trace->duration_before == 1 &&
            !trace->has_duration_after;
    }
    assert(found_residual && found_end && found_remove);
    assert(pokemon_battle_check_invariants(&battle));
}

static void test_generated_inert_ability_inventory(void) {
    static const uint16_t abilities[] = {
        POKEMON_GEN3_ABILITY_LIMBER,
        POKEMON_GEN3_ABILITY_SYNCHRONIZE,
        POKEMON_GEN3_ABILITY_INSOMNIA,
        POKEMON_GEN3_ABILITY_GUTS,
        POKEMON_GEN3_ABILITY_OVERGROW,
        POKEMON_GEN3_ABILITY_BLAZE,
        POKEMON_GEN3_ABILITY_ROCKHEAD,
        POKEMON_GEN3_ABILITY_NATURALCURE,
        POKEMON_GEN3_ABILITY_ILLUMINATE,
        POKEMON_GEN3_ABILITY_PICKUP,
        POKEMON_GEN3_ABILITY_RUNAWAY,
        POKEMON_GEN3_ABILITY_STENCH,
        POKEMON_GEN3_ABILITY_LIGHTNINGROD,
    };
    for (size_t i = 0; i < sizeof(abilities) / sizeof(abilities[0]); i++) {
        PokemonBattleInit init = battle_init();
        init.teams[0].members[0].ability_id = abilities[i];
        PokemonBattle battle;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        assert(battle.handler_count == 0);
    }
    PokemonBattleInit init = battle_init();
    init.teams[0].members[0].ability_id = UINT16_MAX;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_INVALID_CONFIGURATION);
}

static void test_complete_identity_catalog_maps_executable_support(void) {
    const PokemonData *data = &POKEMON_GEN3_SLICE_DATA;
    assert(data->species_catalog_count == POKEMON_GEN3_SPECIES_CATALOG_COUNT);
    assert(data->move_catalog_count == POKEMON_GEN3_MOVE_CATALOG_COUNT);
    assert(data->ability_catalog_count == POKEMON_GEN3_ABILITY_CATALOG_COUNT);
    assert(data->item_catalog_count == POKEMON_GEN3_ITEM_CATALOG_COUNT);
    assert(data->condition_catalog_count == POKEMON_GEN3_CONDITION_CATALOG_COUNT);
    assert(strcmp(pokemon_species_identity(data, 1)->id, "abra") == 0);
    assert(strcmp(pokemon_species_identity(
        data, POKEMON_GEN3_SPECIES_CATALOG_COUNT)->id, "zubat") == 0);
    assert(strcmp(pokemon_move_identity(data, 1)->id, "absorb") == 0);
    assert(strcmp(pokemon_move_identity(
        data, POKEMON_GEN3_MOVE_CATALOG_COUNT)->id, "zapcannon") == 0);
    assert(strcmp(pokemon_ability_identity(data, 1)->id, "arenatrap") == 0);
    assert(strcmp(pokemon_item_identity(data, 1)->id, "aguavberry") == 0);
    assert(strcmp(pokemon_condition_identity(data, 1)->id, "brn") == 0);
    assert(strcmp(pokemon_condition_identity(
        data, POKEMON_GEN3_CONDITION_CATALOG_COUNT)->id, "wish") == 0);
    assert(strcmp(pokemon_condition_identity(
        data, POKEMON_GEN3_CONDITION_VOLATILE_TRAPPER)->id, "trapper") == 0);
    assert(strcmp(pokemon_condition_identity(
        data, POKEMON_GEN3_CONDITION_SLOT_WISH)->id, "wish") == 0);
    assert(pokemon_condition_identity(
        data, POKEMON_GEN3_CONDITION_STATUS_BRN)->domain ==
        POKEMON_CONDITION_DOMAIN_STATUS);
    assert(pokemon_condition_identity(
        data, POKEMON_GEN3_CONDITION_STATUS_BRN)->semantic_kind ==
        POKEMON_STATUS_BURN);
    assert(pokemon_condition_identity(
        data, POKEMON_GEN3_CONDITION_VOLATILE_PROTECT)->semantic_kind ==
        POKEMON_VOLATILE_PROTECT);
    assert(pokemon_condition_identity(
        data, POKEMON_GEN3_CONDITION_VOLATILE_TWOTURNMOVE)->semantic_kind ==
        POKEMON_VOLATILE_TWO_TURN_MOVE);
    assert(pokemon_condition_identity(
        data, POKEMON_GEN3_CONDITION_SLOT_WISH)->domain ==
        POKEMON_CONDITION_DOMAIN_SLOT);
    assert(pokemon_condition_identity(
        data, POKEMON_GEN3_CONDITION_SLOT_WISH)->semantic_kind ==
        POKEMON_SLOT_CONDITION_WISH);
    assert(pokemon_condition_identity(
        data, POKEMON_GEN3_CONDITION_SLOT_FUTUREMOVE)->domain ==
        POKEMON_CONDITION_DOMAIN_SLOT);
    assert(pokemon_condition_identity(
        data, POKEMON_GEN3_CONDITION_SLOT_FUTUREMOVE)->semantic_kind ==
        POKEMON_SLOT_CONDITION_FUTURE_MOVE);
    assert(pokemon_species_identity(data, 0) == NULL);
    assert(pokemon_move_identity(data, POKEMON_GEN3_MOVE_CATALOG_COUNT + 1) == NULL);
    assert(pokemon_condition_identity(data, 0) == NULL);
    assert(pokemon_condition_identity(
        data, POKEMON_GEN3_CONDITION_CATALOG_COUNT + 1) == NULL);

    size_t executable_species = 0;
    size_t executable_moves = 0;
    size_t executable_abilities = 0;
    size_t executable_items = 0;
    size_t executable_conditions = 0;
    const PokemonSpeciesIdentity *abra = pokemon_species_identity(data, 1);
    assert(abra->executable_id != 0);
    assert(abra->type_count == 1 && abra->types[0] == POKEMON_GEN3_TYPE_PSYCHIC);
    assert(abra->base_stats[0] == 25 && abra->base_stats[3] == 105);
    for (size_t i = 0; i < data->condition_catalog_count; i++) {
        const PokemonConditionIdentity *identity = &data->condition_catalog[i];
        assert(identity->catalog_id == i + 1);
        assert(identity->id != NULL && identity->name != NULL);
        executable_conditions += identity->semantic_kind != 0;
    }
    assert(executable_conditions == 73);
    for (size_t i = 0; i < data->species_catalog_count; i++) {
        const PokemonSpeciesIdentity *identity = &data->species_catalog[i];
        assert(identity->catalog_id == i + 1);
        assert(identity->id != NULL && identity->name != NULL);
        assert(identity->executable_id > 0);
        assert(identity->executable_id <= data->species_count);
        assert(data->species[identity->executable_id - 1].id ==
            identity->executable_id);
        executable_species += identity->executable_id != 0;
    }
    const PokemonMoveIdentity *curse = NULL;
    const PokemonMoveIdentity *quick_attack = NULL;
    for (size_t i = 0; i < data->move_catalog_count; i++) {
        const PokemonMoveIdentity *identity = &data->move_catalog[i];
        assert(identity->catalog_id == i + 1);
        executable_moves += identity->executable_id != 0;
        if (strcmp(identity->id, "curse") == 0) curse = identity;
        if (strcmp(identity->id, "quickattack") == 0) quick_attack = identity;
    }
    assert(curse != NULL && curse->type == POKEMON_GEN3_TYPE_TYPELESS);
    assert(curse->executable_id == POKEMON_GEN3_MOVE_CURSE);
    assert(quick_attack != NULL &&
        quick_attack->executable_id == POKEMON_GEN3_MOVE_QUICKATTACK);
    for (size_t i = 0; i < data->ability_catalog_count; i++) {
        executable_abilities += data->ability_catalog[i].executable_id != 0;
    }
    for (size_t i = 0; i < data->item_catalog_count; i++) {
        executable_items += data->item_catalog[i].executable_id != 0;
    }
    assert(executable_species == data->species_count);
    assert(executable_species == POKEMON_GEN3_SPECIES_CATALOG_COUNT);
    /* Runtime closure now catalogs simulator-forced Struggle. Recharge is an
     * action sentinel rather than a Dex move and remains catalog-free. */
    assert(executable_moves + 1 == data->move_count);
    assert(executable_abilities == data->ability_count);
    assert(executable_items == data->item_count);

    const PokemonSpeciesIdentity *shedinja = NULL;
    for (size_t i = 0; i < data->species_catalog_count; i++) {
        if (strcmp(data->species_catalog[i].id, "shedinja") == 0) {
            shedinja = &data->species_catalog[i];
            break;
        }
    }
    assert(shedinja != NULL && shedinja->max_hp_override == 1);
}

static uint16_t catalog_species_id(const char *id) {
    for (size_t i = 0; i < POKEMON_GEN3_SLICE_DATA.species_catalog_count; i++) {
        if (strcmp(POKEMON_GEN3_SLICE_DATA.species_catalog[i].id, id) == 0) {
            return (uint16_t)(i + 1);
        }
    }
    assert(0);
    return 0;
}

static uint16_t catalog_move_id(const char *id) {
    for (size_t i = 0; i < POKEMON_GEN3_SLICE_DATA.move_catalog_count; i++) {
        if (strcmp(POKEMON_GEN3_SLICE_DATA.move_catalog[i].id, id) == 0) {
            return (uint16_t)(i + 1);
        }
    }
    assert(0);
    return 0;
}

static PokemonCatalogSet catalog_set(const char *species, const char *move_id) {
    PokemonCatalogSet set = {
        .species_catalog_id = catalog_species_id(species),
        .move_catalog_ids = {0, 0, 0, 0},
        .level = 100,
    };
    set.move_catalog_ids[0] = catalog_move_id(move_id);
    return set;
}

static void test_gen3_ou_format_manifest_and_bounded_legality(void) {
    const PokemonData *data = &POKEMON_GEN3_SLICE_DATA;
    const PokemonFormatManifest *format = &POKEMON_GEN3_OU_FORMAT;
    assert(strcmp(format->id, "gen3ou") == 0);
    assert(format->game_type == POKEMON_GAME_TYPE_SINGLES);
    assert(format->min_team_size == 1 && format->max_team_size == 6);
    assert(format->max_move_count == 4);
    assert(format->min_level == 1 && format->max_level == 100);
    assert(format->default_level == 100 && format->ev_limit_enabled && format->ev_limit == 510);
    assert(format->rule_count == 42);
    assert(POKEMON_GEN3_OU_POLICY.voluntary_switch_order ==
        POKEMON_VOLUNTARY_SWITCH_ORDER_SPEED);
    assert(POKEMON_GEN3_OU_POLICY.protocol.report_hp_percentages == 1);
    assert(POKEMON_GEN3_OU_POLICY.protocol.allow_uncommitted_choice_cancel == 1);
    assert(POKEMON_GEN3_OU_POLICY.protocol.hide_beat_up_party_identity == 1);

    uint8_t saw_switch_order = 0;
    uint8_t saw_cancel = 0;
    uint8_t saw_hp_percentage = 0;
    uint8_t saw_beat_up_identity = 0;
    for (size_t rule = 0; rule < format->rule_count; rule++) {
        const PokemonFormatRule *entry = &format->rules[rule];
        if (strcmp(entry->id, "switchpriorityclausemod") == 0) {
            assert(entry->kind == POKEMON_FORMAT_RULE_ASSERTION);
            saw_switch_order = 1;
        } else if (strcmp(entry->id, "cancelmod") == 0) {
            assert(entry->kind == POKEMON_FORMAT_RULE_REQUEST_PROTOCOL);
            saw_cancel = 1;
        } else if (strcmp(entry->id, "hppercentagemod") == 0) {
            assert(entry->kind == POKEMON_FORMAT_RULE_PRESENTATION);
            saw_hp_percentage = 1;
        } else if (strcmp(entry->id, "beatupnicknamesmod") == 0) {
            assert(entry->kind == POKEMON_FORMAT_RULE_PRESENTATION);
            saw_beat_up_identity = 1;
        }
    }
    assert(saw_switch_order && saw_cancel && saw_hp_percentage &&
        saw_beat_up_identity);

    PokemonBattleInit policy_init = battle_init();
    PokemonResolvedBundle policy_bundle = *policy_init.bundle;
    PokemonFormatPolicy invalid_policy = POKEMON_GEN3_OU_POLICY;
    policy_bundle.policy = &invalid_policy;
    policy_init.bundle = &policy_bundle;
    PokemonBattle policy_battle;
    memset(&policy_battle, 0x5a, sizeof(policy_battle));
    PokemonBattle policy_before = policy_battle;
    invalid_policy.voluntary_switch_order = POKEMON_VOLUNTARY_SWITCH_ORDER_NONE;
    assert(pokemon_battle_init(&policy_battle, &policy_init) ==
        POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&policy_battle, &policy_before, sizeof(policy_battle)) == 0);
    invalid_policy = POKEMON_GEN3_OU_POLICY;
    invalid_policy.protocol.report_hp_percentages = 2;
    assert(pokemon_battle_init(&policy_battle, &policy_init) ==
        POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&policy_battle, &policy_before, sizeof(policy_battle)) == 0);

    PokemonCatalogTeam team = {0};
    team.members[0] = catalog_set("abra", "absorb");
    PokemonValidationResult result = pokemon_validate_catalog_team(
        format, data, &team, 1);
    assert(result.decision == POKEMON_VALIDATION_ACCEPTED_BOUNDED);
    assert(result.unsupported_rule_count != 0);

    result = pokemon_validate_catalog_team(format, data, &team, 0);
    assert(result.decision == POKEMON_VALIDATION_REJECTED);
    assert(result.reason == POKEMON_VALIDATION_TEAM_SIZE);
    team.members[0].level = 0;
    result = pokemon_validate_catalog_team(format, data, &team, 1);
    assert(result.reason == POKEMON_VALIDATION_LEVEL);
    team.members[0].level = 100;
    team.members[0].move_catalog_ids[0] = 0;
    result = pokemon_validate_catalog_team(format, data, &team, 1);
    assert(result.reason == POKEMON_VALIDATION_MOVE_COUNT);
    team.members[0] = catalog_set("abra", "absorb");
    team.members[0].species_catalog_id = 999;
    result = pokemon_validate_catalog_team(format, data, &team, 1);
    assert(result.reason == POKEMON_VALIDATION_UNKNOWN_DESCRIPTOR);

    team.members[0] = catalog_set("abra", "absorb");
    team.members[1] = catalog_set("abra", "tackle");
    result = pokemon_validate_catalog_team(format, data, &team, 2);
    assert(result.reason == POKEMON_VALIDATION_SPECIES_CLAUSE);

    uint8_t unsupported_admission = 0;
    for (size_t rule = 0; rule < format->rule_count; rule++) {
        if (strcmp(format->rules[rule].id, "-pokemontag:uber") == 0 ||
            strcmp(format->rules[rule].id, "-ability:soundproof") == 0 ||
            strcmp(format->rules[rule].id, "-item:brightpowder") == 0) {
            assert(format->rules[rule].kind ==
                POKEMON_FORMAT_RULE_UNSUPPORTED_ADMISSION_UNIVERSE);
            unsupported_admission++;
        }
    }
    assert(unsupported_admission == 3);

    team.members[0] = catalog_set("abra", "swagger");
    result = pokemon_validate_catalog_team(format, data, &team, 1);
    assert(result.reason == POKEMON_VALIDATION_BANNED);

    team.members[0] = catalog_set("smeargle", "ingrain");
    result = pokemon_validate_catalog_team(format, data, &team, 1);
    assert(result.reason == POKEMON_VALIDATION_COMPLEX_BAN);
    team.members[0] = catalog_set("abra", "batonpass");
    team.members[0].move_catalog_ids[1] = catalog_move_id("meanlook");
    result = pokemon_validate_catalog_team(format, data, &team, 1);
    assert(result.reason == POKEMON_VALIDATION_COMPLEX_BAN);

    team.members[0] = catalog_set("abra", "batonpass");
    team.members[0].move_catalog_ids[1] = catalog_move_id("block");
    result = pokemon_validate_catalog_team(format, data, &team, 1);
    assert(result.reason == POKEMON_VALIDATION_COMPLEX_BAN);

    team.members[0] = catalog_set("abra", "batonpass");
    team.members[0].move_catalog_ids[1] = catalog_move_id("spiderweb");
    result = pokemon_validate_catalog_team(format, data, &team, 1);
    assert(result.reason == POKEMON_VALIDATION_COMPLEX_BAN);
}

static void test_priority_immunity_and_prng_staging(void) {
    const PokemonMoveData *extreme_speed = NULL;
    const PokemonMoveData *flail = NULL;
    const PokemonMoveData *hyper_voice = NULL;
    const PokemonMoveData *vital_throw = NULL;
    for (size_t i = 0; i < POKEMON_GEN3_SLICE_DATA.move_count; i++) {
        if (POKEMON_GEN3_SLICE_DATA.moves[i].id ==
                POKEMON_GEN3_MOVE_EXTREMESPEED) {
            extreme_speed = &POKEMON_GEN3_SLICE_DATA.moves[i];
        }
        if (POKEMON_GEN3_SLICE_DATA.moves[i].id == POKEMON_GEN3_MOVE_FLAIL)
            flail = &POKEMON_GEN3_SLICE_DATA.moves[i];
        if (POKEMON_GEN3_SLICE_DATA.moves[i].id == POKEMON_GEN3_MOVE_HYPERVOICE)
            hyper_voice = &POKEMON_GEN3_SLICE_DATA.moves[i];
        if (POKEMON_GEN3_SLICE_DATA.moves[i].id == POKEMON_GEN3_MOVE_VITALTHROW)
            vital_throw = &POKEMON_GEN3_SLICE_DATA.moves[i];
    }
    assert(extreme_speed != NULL);
    assert(extreme_speed->priority == 1);
    assert(extreme_speed->power == 80);
    assert(extreme_speed->effect_count == 0);
    assert(flail != NULL && flail->damage_formula == POKEMON_DAMAGE_HP_BRACKET);
    assert(hyper_voice != NULL && hyper_voice->power == 90 &&
        hyper_voice->target == POKEMON_TARGET_ALL_ADJACENT_FOES &&
        hyper_voice->effect_count == 0);
    assert(vital_throw != NULL && vital_throw->power == 70 &&
        vital_throw->priority == -1 &&
        vital_throw->accuracy.kind == POKEMON_ACCURACY_ALWAYS &&
        vital_throw->effect_count == 0);
    PokemonBattleInit init = battle_init();
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.turn == 2);
    assert(battle.sides[0].state[0].pp[0] == 47);
    assert(battle.sides[1].state[0].pp[0] == 15);
    assert(battle.events[0].kind == POKEMON_EVENT_MOVE);
    assert(battle.events[0].side == 0);
    assert(battle.events[1].kind == POKEMON_EVENT_IMMUNE);
    assert(battle.events[2].kind == POKEMON_EVENT_MOVE);
    assert(battle.events[2].side == 1);
    assert(battle.events[3].kind == POKEMON_EVENT_DAMAGE);
    assert(battle.queue.count == 0);
    assert(battle.last_queue.count == 2);
    assert(battle.last_queue.values[0].kind == POKEMON_ACTION_MOVE);
    assert(battle.last_queue.values[0].side == 0);
    assert(battle.last_queue.values[0].selected_move_id ==
        POKEMON_GEN3_MOVE_QUICKATTACK);
    assert(battle.last_queue.values[1].side == 1);
    assert(battle.last_queue.values[1].selected_move_id ==
        POKEMON_GEN3_MOVE_THIEF);
    assert(battle.phase == POKEMON_PHASE_AWAITING_CHOICES);
    PokemonBattleView view;
    pokemon_battle_view(&battle, &view);
    assert(memcmp(&view.last_queue, &battle.last_queue, sizeof(view.last_queue)) == 0);
    assert(view.phase == battle.phase);
    assert(battle.draw_count == 5);
    assert(battle.draws[0].label == POKEMON_DRAW_ACCURACY);
    assert(battle.draws[1].label == POKEMON_DRAW_ACCURACY);
    assert(battle.draws[2].label == POKEMON_DRAW_CRITICAL);
    assert(battle.draws[3].label == POKEMON_DRAW_DAMAGE_ROLL);
    assert(battle.draws[4].label == POKEMON_DRAW_END_TURN);
}

static void test_switch_faint_replacement_and_terminal(void) {
    PokemonBattleInit init = battle_init();
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);

    choices[0] = switch_to(1);
    choices[1] = move(0);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].active == 1);
    assert(battle.events[0].kind == POKEMON_EVENT_SWITCH);
    assert(battle.events[1].kind == POKEMON_EVENT_MOVE);
    assert(battle.turn == 3);

    choices[0] = move(0);
    choices[1] = move(0);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.turn == 3);
    assert(battle.sides[1].state[0].fainted);
    assert(battle.request.kind[0] == POKEMON_REQUEST_WAIT);
    assert(battle.request.kind[1] == POKEMON_REQUEST_SWITCH);
    assert(battle.queue.count == 0);
    assert(battle.last_queue.count == 2);
    assert(battle.last_queue.values[0].side == 0);
    assert(battle.last_queue.values[1].side == 1);
    assert(battle.phase == POKEMON_PHASE_FORCED_REPLACEMENT);

    choices[0] = wait_choice();
    choices[1] = switch_to(1);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.turn == 4);
    assert(battle.sides[1].active == 1);
    assert(battle.last_queue.count == 1);
    assert(battle.last_queue.values[0].kind == POKEMON_ACTION_SWITCH);
    assert(battle.last_queue.values[0].side == 1);
    assert(battle.last_queue.values[0].order == 3);
    assert(battle.phase == POKEMON_PHASE_AWAITING_CHOICES);

    choices[0] = move(0);
    choices[1] = move(0);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.terminal);
    assert(battle.winner == 0);
    assert(battle.turn == 4);
    assert(battle.request.kind[0] == POKEMON_REQUEST_TERMINAL);
    assert(battle.request.kind[1] == POKEMON_REQUEST_TERMINAL);
    assert(battle.request.required_sides == 0);
    assert(battle.events[battle.event_count - 1].kind == POKEMON_EVENT_WIN);
    assert(battle.last_queue.count == 2);
    assert(battle.phase == POKEMON_PHASE_TERMINAL);
}

static void test_mutable_party_order_permutation(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SPLASH,
        POKEMON_GEN3_SPECIES_BANETTE, POKEMON_GEN3_MOVE_SPLASH);
    init.team_sizes[0] = 3;
    init.teams[0].members[1] = make_set(
        POKEMON_GEN3_SPECIES_ALAKAZAM, POKEMON_GEN3_MOVE_SPLASH,
        250, 100, 100, 350, 200, 320);
    init.teams[0].members[2] = make_set(
        POKEMON_GEN3_SPECIES_SNORLAX, POKEMON_GEN3_MOVE_SPLASH,
        500, 250, 200, 150, 250, 100);
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    const uint8_t initial[3] = {0, 1, 2};
    assert(memcmp(battle.sides[0].party_order, initial, sizeof(initial)) == 0);

    PokemonChoice choices[POKEMON_SIDES] = {switch_to(1), move(0)};
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    const uint8_t first[3] = {1, 0, 2};
    assert(memcmp(battle.sides[0].party_order, first, sizeof(first)) == 0);
    choices[0] = switch_to(2);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    const uint8_t second[3] = {2, 0, 1};
    assert(memcmp(battle.sides[0].party_order, second, sizeof(second)) == 0);
    choices[0] = switch_to(0);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    const uint8_t third[3] = {0, 2, 1};
    assert(memcmp(battle.sides[0].party_order, third, sizeof(third)) == 0);
    assert(battle.sides[0].active == battle.sides[0].party_order[0]);
    assert(pokemon_battle_check_invariants(&battle));

    battle.sides[0].party_order[2] = battle.sides[0].party_order[1];
    assert(!pokemon_battle_check_invariants(&battle));
}

static void test_deterministic_replay(void) {
    PokemonBattleInit init = battle_init();
    PokemonBattle left;
    PokemonBattle right;
    assert(pokemon_battle_init(&left, &init) == POKEMON_OK);
    assert(pokemon_battle_init(&right, &init) == POKEMON_OK);
    const PokemonChoice script[][POKEMON_SIDES] = {
        {{POKEMON_CHOICE_MOVE, 0}, {POKEMON_CHOICE_MOVE, 0}},
        {{POKEMON_CHOICE_SWITCH, 1}, {POKEMON_CHOICE_MOVE, 0}},
        {{POKEMON_CHOICE_MOVE, 0}, {POKEMON_CHOICE_MOVE, 0}},
        {{POKEMON_CHOICE_NONE, 0}, {POKEMON_CHOICE_SWITCH, 1}},
        {{POKEMON_CHOICE_MOVE, 0}, {POKEMON_CHOICE_MOVE, 0}},
    };
    for (size_t i = 0; i < sizeof(script) / sizeof(script[0]); i++) {
        assert(pokemon_battle_step(&left, script[i]) == POKEMON_OK);
        assert(pokemon_battle_step(&right, script[i]) == POKEMON_OK);
        PokemonBattleView left_view;
        PokemonBattleView right_view;
        pokemon_battle_view(&left, &left_view);
        pokemon_battle_view(&right, &right_view);
        assert(memcmp(left_view.seed, right_view.seed,
            sizeof(left_view.seed)) == 0);
        assert(left_view.turn == right_view.turn);
        assert(left_view.phase == right_view.phase);
        assert(left_view.terminal == right_view.terminal);
        assert(left_view.winner == right_view.winner);
        assert(left_view.event_count == right_view.event_count);
        assert(left_view.draw_count == right_view.draw_count);
        assert(left_view.handler_count == right_view.handler_count);
        for (size_t side = 0; side < POKEMON_SIDES; side++) {
            assert(left_view.sides[side].active == right_view.sides[side].active);
            for (size_t slot = 0; slot < left_view.team_sizes[side]; slot++) {
                const PokemonMutable *l = &left_view.sides[side].state[slot];
                const PokemonMutable *r = &right_view.sides[side].state[slot];
                assert(l->hp == r->hp && l->fainted == r->fainted);
                assert(l->status.kind == r->status.kind);
                assert(l->volatile_count == r->volatile_count);
                assert(l->ability_id == r->ability_id && l->item_id == r->item_id);
                assert(l->last_move_id == r->last_move_id);
                assert(memcmp(l->pp, r->pp, sizeof(l->pp)) == 0);
                assert(memcmp(l->boosts, r->boosts, sizeof(l->boosts)) == 0);
            }
        }
    }
}

static void test_unspecified_gender_is_resolved_at_team_construction(void) {
    PokemonBattleInit init = battle_init();
    init.teams[0].members[1].gender = POKEMON_GENDER_UNSPECIFIED;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(init.teams[0].members[1].gender == POKEMON_GENDER_UNSPECIFIED);
    assert(battle.draw_count == 2);
    assert(battle.draws[0].label == POKEMON_DRAW_TEAM_GENDER);
    assert(battle.draws[0].upper_bound == 2);
    assert(battle.sides[0].sets[1].gender ==
        (battle.draws[0].result == 0 ?
            POKEMON_GENDER_MALE : POKEMON_GENDER_FEMALE));
    assert(battle.draws[1].label == POKEMON_DRAW_END_TURN);
    assert(pokemon_battle_check_invariants(&battle));

    init = battle_init();
    init.teams[0].members[0].gender = (PokemonGender)99;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_INVALID_CONFIGURATION);
}

static void test_miss_stops_later_hit_draws(void) {
    TEST_MOVE.accuracy = (PokemonAccuracy){POKEMON_ACCURACY_PERCENT, 1};
    PokemonBattleInit init = mechanic_init(4);
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.event_count == 4);
    assert(battle.events[1].kind == POKEMON_EVENT_MISS);
    assert(battle.events[3].kind == POKEMON_EVENT_MISS);
    assert(battle.draw_count == 3);
    assert(battle.draws[0].label == POKEMON_DRAW_ACCURACY);
    assert(battle.draws[1].label == POKEMON_DRAW_ACCURACY);
    assert(battle.draws[2].label == POKEMON_DRAW_END_TURN);
    TEST_MOVE.accuracy = (PokemonAccuracy){POKEMON_ACCURACY_PERCENT, 100};
}

static void test_singles_target_algebra(void) {
    static const struct {
        PokemonMoveTarget mode;
        PokemonResolvedTarget resolved;
        PokemonTargetCapability capability;
        int8_t target_loc;
    } cases[] = {
        {POKEMON_TARGET_ADJACENT_ALLY, POKEMON_RESOLVED_TARGET_NONE,
            POKEMON_TARGET_SUPPORTED, 0},
        {POKEMON_TARGET_ALL, POKEMON_RESOLVED_TARGET_FIELD,
            POKEMON_TARGET_SUPPORTED, 0},
        {POKEMON_TARGET_ALL_ADJACENT, POKEMON_RESOLVED_TARGET_FOE,
            POKEMON_TARGET_SUPPORTED, 1},
        {POKEMON_TARGET_ALL_ADJACENT_FOES, POKEMON_RESOLVED_TARGET_FOE,
            POKEMON_TARGET_SUPPORTED, 1},
        {POKEMON_TARGET_ALLY_SIDE, POKEMON_RESOLVED_TARGET_USER_SIDE,
            POKEMON_TARGET_SUPPORTED, 0},
        {POKEMON_TARGET_ALLY_TEAM, POKEMON_RESOLVED_TARGET_USER_TEAM,
            POKEMON_TARGET_SUPPORTED, 0},
        {POKEMON_TARGET_ANY, POKEMON_RESOLVED_TARGET_FOE,
            POKEMON_TARGET_SUPPORTED, 1},
        {POKEMON_TARGET_FOE_SIDE, POKEMON_RESOLVED_TARGET_FOE_SIDE,
            POKEMON_TARGET_SUPPORTED, 0},
        {POKEMON_TARGET_NORMAL, POKEMON_RESOLVED_TARGET_FOE,
            POKEMON_TARGET_SUPPORTED, 1},
        {POKEMON_TARGET_RANDOM_NORMAL, POKEMON_RESOLVED_TARGET_FOE,
            POKEMON_TARGET_SUPPORTED, 1},
        {POKEMON_TARGET_SCRIPTED, POKEMON_RESOLVED_TARGET_FOE,
            POKEMON_TARGET_SUPPORTED, 1},
        {POKEMON_TARGET_SELF, POKEMON_RESOLVED_TARGET_USER,
            POKEMON_TARGET_SUPPORTED, -1},
    };
    assert(POKEMON_SINGLES_2_FORMAT.target_rule_count ==
        sizeof(cases) / sizeof(cases[0]));
    for (size_t i = 0; i < sizeof(cases) / sizeof(cases[0]); i++) {
        PokemonTargetRule resolved = {0};
        int supported = pokemon_resolve_move_target(
            &POKEMON_SINGLES_2_FORMAT, cases[i].mode, &resolved);
        assert(resolved.mode == cases[i].mode);
        assert(resolved.resolved == cases[i].resolved);
        assert(resolved.capability == cases[i].capability);
        assert(resolved.target_loc == cases[i].target_loc);
        assert(supported == (cases[i].capability == POKEMON_TARGET_SUPPORTED));
    }

    PokemonMoveTarget saved = TEST_MOVE.target;
    TEST_MOVE.target = POKEMON_TARGET_SCRIPTED;
    PokemonBattle battle;
    PokemonBattleInit init = mechanic_init(4);
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);

    PokemonCategory saved_category = TEST_MOVE.category;
    uint8_t saved_power = TEST_MOVE.power;
    TEST_MOVE.category = POKEMON_CATEGORY_STATUS;
    TEST_MOVE.power = 0;
    TEST_MOVE.target = POKEMON_TARGET_ADJACENT_ALLY;
    init = mechanic_init(4);
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    uint16_t hp_before[2] = {
        battle.sides[0].state[0].hp, battle.sides[1].state[0].hp,
    };
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].pp[0] == 15);
    assert(battle.sides[1].state[0].pp[0] == 15);
    assert(battle.sides[0].state[0].hp == hp_before[0]);
    assert(battle.sides[1].state[0].hp == hp_before[1]);
    assert(battle.event_count == 2);
    assert(battle.events[0].kind == POKEMON_EVENT_MOVE);
    assert(battle.events[0].target_side == UINT8_MAX);
    assert(battle.events[1].kind == POKEMON_EVENT_MOVE);
    assert(battle.events[1].target_side == UINT8_MAX);
    assert(battle.draw_count == 1);
    assert(battle.draws[0].label == POKEMON_DRAW_END_TURN);
    assert(battle.last_queue.count == 2);
    for (size_t i = 0; i < battle.last_queue.count; i++) {
        assert(battle.last_queue.values[i].target_mode ==
            POKEMON_TARGET_ADJACENT_ALLY);
        assert(battle.last_queue.values[i].resolved_target ==
            POKEMON_RESOLVED_TARGET_NONE);
        assert(battle.last_queue.values[i].target_loc == 0);
    }

    const PokemonMoveData *wing_attack = NULL;
    for (size_t i = 0; i < POKEMON_GEN3_SLICE_DATA.move_count; i++) {
        if (POKEMON_GEN3_SLICE_DATA.moves[i].id ==
            POKEMON_GEN3_MOVE_WINGATTACK) {
            wing_attack = &POKEMON_GEN3_SLICE_DATA.moves[i];
        }
    }
    assert(wing_attack != NULL && wing_attack->target == POKEMON_TARGET_ANY);
    PokemonTargetRule wing_target;
    assert(pokemon_resolve_move_target(
        &POKEMON_SINGLES_1_FORMAT, wing_attack->target, &wing_target));
    assert(wing_target.resolved == POKEMON_RESOLVED_TARGET_FOE);
    assert(wing_target.target_loc == 1);

    /* randomNormal is a choice-legality mode, not an extra source of
     * randomness in singles. The sole foe uses the ordinary foe pipeline. */
    TEST_MOVE.category = saved_category;
    TEST_MOVE.power = saved_power;
    TEST_MOVE.target = POKEMON_TARGET_NORMAL;
    PokemonBattle normal;
    init = mechanic_init(9);
    assert(pokemon_battle_init(&normal, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&normal, choices) == POKEMON_OK);

    TEST_MOVE.target = POKEMON_TARGET_RANDOM_NORMAL;
    PokemonBattle random_normal;
    init = mechanic_init(9);
    assert(pokemon_battle_init(&random_normal, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&random_normal, choices) == POKEMON_OK);
    assert(random_normal.last_queue.count == 2);
    for (size_t i = 0; i < random_normal.last_queue.count; i++) {
        assert(random_normal.last_queue.values[i].target_mode ==
            POKEMON_TARGET_RANDOM_NORMAL);
        assert(random_normal.last_queue.values[i].resolved_target ==
            POKEMON_RESOLVED_TARGET_FOE);
        assert(random_normal.last_queue.values[i].target_loc == 1);
    }
    assert(random_normal.draw_count == normal.draw_count);
    assert(memcmp(random_normal.draws, normal.draws,
        normal.draw_count * sizeof(normal.draws[0])) == 0);
    assert(random_normal.event_count == normal.event_count);
    assert(memcmp(random_normal.events, normal.events,
        normal.event_count * sizeof(normal.events[0])) == 0);
    assert(accuracy_protect_owned_state_equal(&random_normal, &normal));

    TEST_MOVE.category = saved_category;
    TEST_MOVE.power = saved_power;
    TEST_MOVE.target = saved;
}

static void test_critical_and_exact_damage_roll(void) {
    PokemonBattleInit init = mechanic_init(6);
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.draws[0].label == POKEMON_DRAW_ACCURACY);
    assert(battle.draws[1].label == POKEMON_DRAW_CRITICAL);
    assert(battle.draws[1].result == 0);
    assert(battle.draws[2].label == POKEMON_DRAW_DAMAGE_ROLL);
    assert(battle.draws[2].result == 8);
    /* Base 44 * crit * STAB = 132, followed by the 92% damage roll. */
    assert(battle.events[1].kind == POKEMON_EVENT_DAMAGE);
    assert(battle.events[1].amount == 121);
}

static void test_high_critical_stage_pipeline(void) {
    static const uint16_t ids[] = {
        POKEMON_GEN3_MOVE_LEAFBLADE, POKEMON_GEN3_MOVE_CRABHAMMER,
        POKEMON_GEN3_MOVE_AIRCUTTER, POKEMON_GEN3_MOVE_KARATECHOP,
        POKEMON_GEN3_MOVE_AEROBLAST, POKEMON_GEN3_MOVE_BLAZEKICK,
        POKEMON_GEN3_MOVE_CROSSCHOP, POKEMON_GEN3_MOVE_POISONTAIL,
        POKEMON_GEN3_MOVE_RAZORLEAF, POKEMON_GEN3_MOVE_SLASH,
    };
    for (size_t wanted = 0; wanted < sizeof(ids) / sizeof(ids[0]); wanted++) {
        const PokemonMoveData *found = NULL;
        for (size_t i = 0; i < POKEMON_GEN3_SLICE_DATA.move_count; i++) {
            if (POKEMON_GEN3_SLICE_DATA.moves[i].id == ids[wanted]) {
                found = &POKEMON_GEN3_SLICE_DATA.moves[i];
                break;
            }
        }
        assert(found != NULL && found->critical_stage == 2);
    }
    static const uint8_t denominators[] = {0, 16, 8, 4, 3, 2};
    for (uint32_t stage = 0; stage <= 7; stage++) {
        uint8_t numerator = 99;
        uint8_t denominator = 99;
        POKEMON_GEN3_RULES.critical_chance(
            stage, &numerator, &denominator);
        uint32_t clamped = stage > 5 ? 5 : stage;
        assert(numerator == (clamped == 0 ? 0 : 1));
        assert(denominator == denominators[clamped]);
    }
    uint8_t saved_stage = TEST_MOVE.critical_stage;
    TEST_MOVE.critical_stage = 2;
    PokemonBattleInit init = mechanic_init(6);
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.draws[1].label == POKEMON_DRAW_CRITICAL);
    assert(battle.draws[1].upper_bound == 8);
    assert(battle.draws[1].result == 0);
    TEST_MOVE.critical_stage = saved_stage;

    uint8_t saw_ratio = 0;
    uint8_t saw_cancel = 0;
    for (size_t i = 0; i < POKEMON_GEN3_SLICE_DATA.event_spec_count; i++) {
        const PokemonEventSpec *spec = &POKEMON_GEN3_SLICE_DATA.event_specs[i];
        if (spec->id == POKEMON_HANDLER_EVENT_MODIFY_CRIT_RATIO) {
            saw_ratio = spec->supported &&
                spec->algebra == POKEMON_EVENT_ALGEBRA_NUMERIC_OR_CANCEL;
        }
        if (spec->id == POKEMON_HANDLER_EVENT_CRITICAL_HIT) {
            saw_cancel = spec->supported &&
                spec->algebra == POKEMON_EVENT_ALGEBRA_BOOLEAN_OR_NULL;
        }
    }
    assert(saw_ratio && saw_cancel);
}

static void test_speed_tie_has_one_owned_draw(void) {
    PokemonBattleInit init = mechanic_init(7);
    init.teams[1].members[0].stats[5] = 200;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.draws[0].label == POKEMON_DRAW_QUEUE_TIE);
    uint8_t expected_first_side = battle.draws[0].result == 0 ? 0 : 1;
    assert(battle.last_queue.count == 2);
    assert(battle.last_queue.values[0].side == expected_first_side);
    assert(battle.events[0].kind == POKEMON_EVENT_MOVE);
    assert(battle.events[0].side == expected_first_side);
}

static void test_generic_pre_turn_action_and_four_action_sort(void) {
    PokemonMoveData moves[POKEMON_GEN3_MOVE_COUNT];
    memcpy(moves, POKEMON_GEN3_SLICE_DATA.moves, sizeof(moves));
    size_t splash_index = 0;
    while (moves[splash_index].id != POKEMON_GEN3_MOVE_SPLASH) splash_index++;
    moves[splash_index].pre_turn_condition_descriptor =
        POKEMON_GEN3_CONDITION_VOLATILE_PROTECT;
    PokemonData data = POKEMON_GEN3_SLICE_DATA;
    data.moves = moves;
    PokemonResolvedBundle bundle = POKEMON_GEN3_OU_BUNDLE;
    bundle.data = &data;
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_SPLASH,
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_SPLASH);
    init.bundle = &bundle;
    init.teams[0].members[0].stats[5] = 100;
    init.teams[1].members[0].stats[5] = 100;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.last_queue.count == 2);
    assert(battle.last_queue.values[0].kind == POKEMON_ACTION_MOVE);
    assert(battle.last_queue.values[1].kind == POKEMON_ACTION_MOVE);
    assert(draw_label_count(&battle, POKEMON_DRAW_QUEUE_TIE) == 2);
    size_t installed = 0;
    for (size_t i = 0; i < battle.condition_trace_count; i++) {
        const PokemonConditionTrace *trace = &battle.condition_traces[i];
        installed += trace->scope == POKEMON_CONDITION_SCOPE_VOLATILE &&
            trace->operation == POKEMON_CONDITION_ADD &&
            trace->condition_id == POKEMON_VOLATILE_PROTECT;
    }
    assert(installed == 2);
    assert(test_volatile_index(
        &battle.sides[0].state[battle.sides[0].active],
        POKEMON_VOLATILE_PROTECT) < 0);
    assert(test_volatile_index(
        &battle.sides[1].state[battle.sides[1].active],
        POKEMON_VOLATILE_PROTECT) < 0);

    moves[splash_index].pre_turn_condition_descriptor = UINT16_MAX;
    PokemonBattle untouched;
    memset(&untouched, 0xA5, sizeof(untouched));
    PokemonBattle before = untouched;
    assert(pokemon_battle_init(&untouched, &init) ==
        POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&untouched, &before, sizeof(untouched)) == 0);
}

static void test_staged_speed_orders_actions_before_tie_draw(void) {
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    PokemonBattleInit init = mechanic_init(91);
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    battle.sides[0].state[0].boosts[POKEMON_STAT_SPE] = -1;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.last_queue.values[0].side == 0);
    assert(battle.last_queue.values[0].speed == 133);
    assert(battle.last_queue.values[1].speed == 100);
    assert(battle.draws[0].label != POKEMON_DRAW_QUEUE_TIE);

    init = mechanic_init(92);
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    battle.sides[0].state[0].boosts[POKEMON_STAT_SPE] = -2;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.last_queue.values[0].speed == 100);
    assert(battle.last_queue.values[1].speed == 100);
    assert(battle.draws[0].label == POKEMON_DRAW_QUEUE_TIE);
}

static uint16_t find_accuracy_seed(uint32_t wanted) {
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    for (uint32_t seed = 0; seed <= UINT16_MAX; seed++) {
        PokemonBattleInit init = mechanic_init((uint16_t)seed);
        PokemonBattle battle;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        battle.sides[1].state[0].boosts[POKEMON_STAT_EVASION] = 1;
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        for (size_t i = 0; i < battle.draw_count; i++) {
            if (battle.draws[i].label == POKEMON_DRAW_ACCURACY) {
                if (battle.draws[i].result == wanted) return (uint16_t)seed;
                break;
            }
        }
    }
    assert(0 && "accuracy seed exists");
    return 0;
}

static void test_shared_fractional_accuracy_and_always_hit(void) {
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    PokemonAccuracy saved_accuracy = TEST_MOVE.accuracy;
    PokemonCategory saved_category = TEST_MOVE.category;
    uint8_t saved_power = TEST_MOVE.power;
    TEST_MOVE.accuracy = (PokemonAccuracy){POKEMON_ACCURACY_PERCENT, 85};
    /* +1 evasion gives an exact 63.75% threshold: 63 hits, 64 misses. */
    uint16_t hit_seed = find_accuracy_seed(63);
    uint16_t miss_seed = find_accuracy_seed(64);
    for (size_t kind = 0; kind < 2; kind++) {
        TEST_MOVE.category = kind == 0 ? POKEMON_CATEGORY_PHYSICAL :
            POKEMON_CATEGORY_STATUS;
        TEST_MOVE.power = kind == 0 ? 50 : 0;
        PokemonBattleInit init = mechanic_init(hit_seed);
        PokemonBattle battle;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        battle.sides[1].state[0].boosts[POKEMON_STAT_EVASION] = 1;
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        assert(battle.draws[0].label == POKEMON_DRAW_ACCURACY);
        assert(battle.draws[0].result == 63);
        assert(battle.events[1].kind != POKEMON_EVENT_MISS);

        init = mechanic_init(miss_seed);
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        battle.sides[1].state[0].boosts[POKEMON_STAT_EVASION] = 1;
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        assert(battle.draws[0].result == 64);
        assert(battle.events[1].kind == POKEMON_EVENT_MISS);
    }

    TEST_MOVE.ignore_evasion = 1;
    PokemonBattleInit ignored = mechanic_init(miss_seed);
    PokemonBattle ignored_battle;
    assert(pokemon_battle_init(&ignored_battle, &ignored) == POKEMON_OK);
    ignored_battle.sides[1].state[0].boosts[POKEMON_STAT_EVASION] = 1;
    assert(pokemon_battle_step(&ignored_battle, choices) == POKEMON_OK);
    assert(ignored_battle.draws[0].result == 64);
    assert(ignored_battle.events[1].kind != POKEMON_EVENT_MISS);
    TEST_MOVE.ignore_evasion = 0;

    PokemonBattleInit accuracy_ignored = mechanic_init(miss_seed);
    assert(pokemon_battle_init(&ignored_battle, &accuracy_ignored) == POKEMON_OK);
    ignored_battle.sides[0].state[0].boosts[POKEMON_STAT_ACCURACY] = -1;
    assert(pokemon_battle_step(&ignored_battle, choices) == POKEMON_OK);
    assert(ignored_battle.events[1].kind == POKEMON_EVENT_MISS);
    TEST_MOVE.ignore_accuracy = 1;
    accuracy_ignored = mechanic_init(miss_seed);
    assert(pokemon_battle_init(&ignored_battle, &accuracy_ignored) == POKEMON_OK);
    ignored_battle.sides[0].state[0].boosts[POKEMON_STAT_ACCURACY] = -1;
    assert(pokemon_battle_step(&ignored_battle, choices) == POKEMON_OK);
    assert(ignored_battle.events[1].kind != POKEMON_EVENT_MISS);
    TEST_MOVE.ignore_accuracy = 0;

    TEST_MOVE.category = POKEMON_CATEGORY_PHYSICAL;
    TEST_MOVE.power = 50;
    TEST_MOVE.accuracy = (PokemonAccuracy){POKEMON_ACCURACY_ALWAYS, 0};
    PokemonBattleInit init = mechanic_init(93);
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    battle.sides[0].state[0].boosts[POKEMON_STAT_ACCURACY] = -6;
    battle.sides[1].state[0].boosts[POKEMON_STAT_EVASION] = 6;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    for (size_t i = 0; i < battle.draw_count; i++) {
        assert(battle.draws[i].label != POKEMON_DRAW_ACCURACY);
    }

    TEST_MOVE.accuracy = (PokemonAccuracy){POKEMON_ACCURACY_PERCENT, 0};
    init = mechanic_init(93);
    memset(&battle, 0xA5, sizeof(battle));
    PokemonBattle before = battle;
    assert(pokemon_battle_init(&battle, &init) ==
        POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&battle, &before, sizeof(battle)) == 0);

    TEST_MOVE.accuracy = (PokemonAccuracy){0, 0};
    init = mechanic_init(93);
    memset(&battle, 0x5A, sizeof(battle));
    before = battle;
    assert(pokemon_battle_init(&battle, &init) ==
        POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&battle, &before, sizeof(battle)) == 0);

    TEST_MOVE.accuracy = saved_accuracy;
    TEST_MOVE.category = saved_category;
    TEST_MOVE.power = saved_power;
}

static void test_unsupported_stage_handler_fails_closed_when_installed(void) {
    PokemonBattleInit init = mechanic_init(94);
    PokemonData data = *init.bundle->data;
    PokemonResolvedBundle bundle = *init.bundle;
    static const PokemonHandlerOp invalid_program = {
        .opcode = POKEMON_HANDLER_OP_RETURN_FALSE,
    };
    static const PokemonHandlerDescriptor handler = {
        .event = POKEMON_HANDLER_EVENT_MODIFY_BOOST,
        .id = 900,
        .source_kind = POKEMON_HANDLER_SOURCE_CONDITION,
        .source_id = POKEMON_GEN3_CONDITION_STATUS_PAR,
        .scope = POKEMON_HANDLER_SCOPE_TARGET,
        .route = POKEMON_HANDLER_ROUTE_OWNER,
        .program_count = 1,
        .raw_hook = "onModifyBoost",
    };
    static const PokemonOwnerBindingIndex index = {
        .owner_kind = POKEMON_OWNER_STATUS,
        .owner_id = POKEMON_GEN3_CONDITION_STATUS_PAR,
        .event = POKEMON_HANDLER_EVENT_MODIFY_BOOST,
        .scope = POKEMON_HANDLER_SCOPE_TARGET,
        .route = POKEMON_HANDLER_ROUTE_OWNER,
        .binding_offset = 0,
        .binding_count = 1,
    };
    data.handlers = &handler;
    data.handler_count = 1;
    data.handler_programs = &invalid_program;
    data.handler_program_count = 1;
    data.owner_binding_index = &index;
    data.owner_binding_index_count = 1;
    bundle.data = &data;
    init.bundle = &bundle;
    init.initial_status[0][0] = POKEMON_STATUS_PARALYSIS;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) ==
        POKEMON_INVALID_CONFIGURATION);
}

static PokemonBattleInit immunity_init(
    uint16_t move_id, uint16_t defender_species, uint16_t defender_ability
) {
    PokemonBattleInit init = battle_init();
    init.teams[0].members[0] = make_set(
        POKEMON_GEN3_SPECIES_PERSIAN, move_id, 500, 200, 200, 200, 200, 300
    );
    init.teams[1].members[0] = make_set(
        defender_species, move_id, 500, 100, 200, 100, 200, 100
    );
    init.teams[1].members[0].ability_id = defender_ability;
    return init;
}

static void test_ground_immunity_causes_are_not_handlers(void) {
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    PokemonBattle battle;

    PokemonBattleInit init = immunity_init(
        POKEMON_GEN3_MOVE_EARTHQUAKE, POKEMON_GEN3_SPECIES_MACHOP, 0
    );
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.immunities[0].cause == POKEMON_IMMUNITY_NONE);
    assert(battle.handler_count == 0);
    assert(battle.events[1].kind == POKEMON_EVENT_DAMAGE);

    init = immunity_init(
        POKEMON_GEN3_MOVE_EARTHQUAKE, POKEMON_GEN3_SPECIES_CHARIZARD, 0
    );
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.immunities[0].cause == POKEMON_IMMUNITY_NATURAL_TYPE);
    assert(battle.handler_count == 0);
    assert(battle.events[1].kind == POKEMON_EVENT_IMMUNE);
    assert(battle.events[1].immunity_cause == POKEMON_IMMUNITY_NATURAL_TYPE);

    init = immunity_init(
        POKEMON_GEN3_MOVE_EARTHQUAKE, POKEMON_GEN3_SPECIES_GENGAR,
        POKEMON_GEN3_ABILITY_LEVITATE
    );
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.immunities[0].cause == POKEMON_IMMUNITY_LEVITATE);
    assert(battle.immunities[0].effect_id == POKEMON_GEN3_ABILITY_LEVITATE);
    assert(battle.handler_count == 0);
    assert(battle.events[1].immunity_cause == POKEMON_IMMUNITY_LEVITATE);
}

static void test_foresight_generic_immunity_and_boost_staging(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_FORESIGHT,
        POKEMON_GEN3_SPECIES_DUSCLOPS, POKEMON_GEN3_MOVE_CALMMIND);
    init.teams[0].members[0].move_ids[1] = POKEMON_GEN3_MOVE_TACKLE;
    init.teams[0].members[0].move_ids[2] = POKEMON_GEN3_MOVE_SPLASH;
    init.teams[1].members[1] = make_set(
        POKEMON_GEN3_SPECIES_BANETTE, POKEMON_GEN3_MOVE_SPLASH,
        300, 100, 100, 100, 100, 80);
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);

    PokemonChoice install[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_step(&battle, install) == POKEMON_OK);
    assert(test_volatile_index(
        &battle.sides[1].state[0], POKEMON_VOLATILE_FORESIGHT) >= 0);
    uint16_t hp = battle.sides[1].state[0].hp;
    PokemonChoice admitted[POKEMON_SIDES] = {move(1), move(0)};
    assert(pokemon_battle_step(&battle, admitted) == POKEMON_OK);
    assert(battle.sides[1].state[0].hp < hp);
    assert(handler_id_count(
        &battle, POKEMON_GEN3_HANDLER_FORESIGHT_NEGATE_IMMUNITY) == 2);
    assert(handler_id_count(
        &battle, POKEMON_GEN3_HANDLER_FORESIGHT_MODIFY_BOOST) == 4);

    PokemonChoice cleanup[POKEMON_SIDES] = {wait_choice(), switch_to(1)};
    assert(pokemon_battle_step(&battle, cleanup) == POKEMON_OK);
    assert(battle.sides[1].active == 1);
    assert(test_volatile_index(
        &battle.sides[1].state[0], POKEMON_VOLATILE_FORESIGHT) < 0);
}

static void test_foresight_positive_and_negative_evasion_product(void) {
    PokemonChoice install[POKEMON_SIDES] = {move(0), move(0)};
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_FORESIGHT,
        POKEMON_GEN3_SPECIES_DUSCLOPS, POKEMON_GEN3_MOVE_SPLASH);
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, install) == POKEMON_OK);
    assert(test_volatile_index(
        &battle.sides[1].state[0], POKEMON_VOLATILE_FORESIGHT) >= 0);
    size_t modify_boost_before = handler_id_count(
        &battle, POKEMON_GEN3_HANDLER_FORESIGHT_MODIFY_BOOST);

    PokemonBoostTable boosts = {0};
    boosts.present[POKEMON_STAT_EVASION] = 1;
    boosts.delta[POKEMON_STAT_EVASION] = 6;
    PokemonEventFrame frame;
    assert(pokemon_run_event(&battle, &(PokemonEventInput){
        .event = POKEMON_HANDLER_EVENT_MODIFY_BOOST,
        .source = {POKEMON_ENTITY_POKEMON, 1, 0},
        .target_side = 1, .target_slot = 0,
        .relay = {.kind = POKEMON_RELAY_BOOST_TABLE, .value.boosts = boosts},
    }, &frame) == POKEMON_OK);
    assert(frame.relay.kind == POKEMON_RELAY_BOOST_TABLE);
    assert(frame.relay.value.boosts.present[POKEMON_STAT_EVASION]);
    assert(frame.relay.value.boosts.delta[POKEMON_STAT_EVASION] == 0);

    boosts.delta[POKEMON_STAT_EVASION] = -6;
    assert(pokemon_run_event(&battle, &(PokemonEventInput){
        .event = POKEMON_HANDLER_EVENT_MODIFY_BOOST,
        .source = {POKEMON_ENTITY_POKEMON, 1, 0},
        .target_side = 1, .target_slot = 0,
        .relay = {.kind = POKEMON_RELAY_BOOST_TABLE, .value.boosts = boosts},
    }, &frame) == POKEMON_OK);
    assert(frame.relay.value.boosts.present[POKEMON_STAT_EVASION]);
    assert(frame.relay.value.boosts.delta[POKEMON_STAT_EVASION] == -6);
    assert(handler_id_count(
        &battle, POKEMON_GEN3_HANDLER_FORESIGHT_MODIFY_BOOST) ==
        modify_boost_before + 2);
    assert(pokemon_battle_check_invariants(&battle));
}

static void test_water_absorb_is_a_scoped_try_hit_handler(void) {
    PokemonBattleInit init = immunity_init(
        POKEMON_GEN3_MOVE_SURF, POKEMON_GEN3_SPECIES_VAPOREON,
        POKEMON_GEN3_ABILITY_WATERABSORB
    );
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    /* runImmunity found no immunity; Water Absorb cancels later at TryHit. */
    assert(battle.immunities[0].cause == POKEMON_IMMUNITY_NONE);
    assert(battle.immunities[0].effect_id == 0);
    assert(battle.handler_count == 1);
    assert(battle.handlers[0].handler.descriptor.event == POKEMON_HANDLER_EVENT_TRY_HIT);
    assert(battle.handlers[0].handler.descriptor.id == POKEMON_GEN3_HANDLER_WATER_ABSORB);
    assert(battle.handlers[0].handler.holder_side == 1);
    assert(battle.handlers[0].handler.holder_slot == 0);
    assert(battle.handlers[0].invoked == 1);
    assert(battle.handlers[0].result == POKEMON_HANDLER_IMMUNE);
    assert(battle.events[1].kind == POKEMON_EVENT_IMMUNE);
    assert(battle.events[1].immunity_cause == POKEMON_IMMUNITY_HANDLER);
    assert(battle.events[1].handler_id == POKEMON_GEN3_HANDLER_WATER_ABSORB);
    PokemonBattleView view;
    pokemon_battle_view(&battle, &view);
    assert(view.handler_count == battle.handler_count);
    assert(view.immunity_count == battle.immunity_count);
    assert(memcmp(view.handlers, battle.handlers, sizeof(view.handlers)) == 0);
    assert(memcmp(view.immunities, battle.immunities, sizeof(view.immunities)) == 0);

    init = immunity_init(
        POKEMON_GEN3_MOVE_EARTHQUAKE, POKEMON_GEN3_SPECIES_VAPOREON,
        POKEMON_GEN3_ABILITY_WATERABSORB
    );
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.immunities[0].cause == POKEMON_IMMUNITY_NONE);
    assert(battle.handler_count == 1);
    assert(battle.handlers[0].invoked == 1);
    assert(battle.handlers[0].result == POKEMON_HANDLER_CONTINUE);
    assert(battle.events[1].kind == POKEMON_EVENT_DAMAGE);
}

static void test_volt_absorb_generated_interception(void) {
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_RAIKOU, POKEMON_GEN3_MOVE_THUNDERBOLT,
        POKEMON_GEN3_SPECIES_LANTURN, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_VOLTABSORB;
    init.teams[1].members[0].stats[0] = 401;
    init.initial_hp[1][0] = 201;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].state[0].hp == 301);
    assert(event_kind_count(&battle, POKEMON_EVENT_HEAL) == 1);
    assert(event_kind_count(&battle, POKEMON_EVENT_IMMUNE) == 0);
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 1);
    assert(draw_label_count(&battle, POKEMON_DRAW_CRITICAL) == 0);
    assert(draw_label_count(&battle, POKEMON_DRAW_DAMAGE_ROLL) == 0);
    assert(battle.handlers[0].handler.descriptor.id ==
        POKEMON_GEN3_HANDLER_VOLT_ABSORB);

    init.initial_hp[1][0] = 401;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].state[0].hp == 401);
    assert(event_kind_count(&battle, POKEMON_EVENT_HEAL) == 0);
    assert(event_kind_count(&battle, POKEMON_EVENT_IMMUNE) == 1);
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 1);

    init = condition_init(
        POKEMON_GEN3_SPECIES_LANTURN, POKEMON_GEN3_MOVE_THUNDERWAVE,
        POKEMON_GEN3_SPECIES_LANTURN, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_VOLTABSORB;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].state[0].status.kind == POKEMON_STATUS_PARALYSIS);
    assert(battle.handlers[0].handler.descriptor.id ==
        POKEMON_GEN3_HANDLER_VOLT_ABSORB);
    assert(battle.handlers[0].result == POKEMON_HANDLER_CONTINUE);
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 1);

}

static void test_event_interpreter_contract_and_water_absorb_heal(void) {
    assert(POKEMON_GEN3_SLICE_DATA.event_spec_count == 75);
    size_t supported = 0;
    const PokemonEventSpec *lock_move = NULL;
    const PokemonEventSpec *restart = NULL;
    const PokemonEventSpec *try_move = NULL;
    const PokemonEventSpec *move_aborted = NULL;
    const PokemonEventSpec *move_fail = NULL;
    const PokemonEventSpec *base_power = NULL;
    const PokemonEventSpec *modify_spd = NULL;
    const PokemonEventSpec *modify_boost = NULL;
    for (size_t i = 0; i < POKEMON_GEN3_SLICE_DATA.event_spec_count; i++) {
        const PokemonEventSpec *spec = &POKEMON_GEN3_SLICE_DATA.event_specs[i];
        assert(spec->id == i + 1);
        assert(spec->name != NULL && spec->name[0] != '\0');
        assert(spec->algebra >= POKEMON_EVENT_ALGEBRA_NUMERIC_OR_CANCEL &&
            spec->algebra <= POKEMON_EVENT_ALGEBRA_MUTABLE_BOOST_TABLE);
        supported += spec->supported;
        if (spec->id == POKEMON_HANDLER_EVENT_LOCK_MOVE) lock_move = spec;
        if (spec->id == POKEMON_HANDLER_EVENT_RESTART) restart = spec;
        if (spec->id == POKEMON_HANDLER_EVENT_TRY_MOVE) try_move = spec;
        if (spec->id == POKEMON_HANDLER_EVENT_MOVE_ABORTED) move_aborted = spec;
        if (spec->id == POKEMON_HANDLER_EVENT_MOVE_FAIL) move_fail = spec;
        if (spec->id == POKEMON_HANDLER_EVENT_BASE_POWER) base_power = spec;
        if (spec->id == POKEMON_HANDLER_EVENT_MODIFY_SPD) modify_spd = spec;
        if (spec->id == POKEMON_HANDLER_EVENT_MODIFY_BOOST) modify_boost = spec;
    }
    assert(supported == 64);
    assert(move_fail != NULL && move_fail->supported &&
        move_fail->algebra == POKEMON_EVENT_ALGEBRA_VOID_NOTIFICATION);
    assert(modify_boost != NULL && modify_boost->supported &&
        modify_boost->algebra ==
            POKEMON_EVENT_ALGEBRA_MUTABLE_BOOST_TABLE);
    assert(modify_spd != NULL && modify_spd->supported &&
        strcmp(modify_spd->name, "ModifySpD") == 0 &&
        modify_spd->algebra == POKEMON_EVENT_ALGEBRA_NUMERIC_OR_CANCEL);
    assert(lock_move != NULL && lock_move->supported &&
        strcmp(lock_move->name, "LockMove") == 0 &&
        lock_move->algebra == POKEMON_EVENT_ALGEBRA_SELECTOR_REPLACEMENT);
    assert(restart != NULL && restart->supported &&
        strcmp(restart->name, "Restart") == 0 &&
        restart->algebra == POKEMON_EVENT_ALGEBRA_VOID_NOTIFICATION);
    assert(try_move != NULL && try_move->supported &&
        strcmp(try_move->name, "TryMove") == 0 &&
        try_move->algebra == POKEMON_EVENT_ALGEBRA_BOOLEAN_OR_NULL);
    assert(move_aborted != NULL && move_aborted->supported &&
        strcmp(move_aborted->name, "MoveAborted") == 0 &&
        move_aborted->algebra == POKEMON_EVENT_ALGEBRA_VOID_NOTIFICATION);
    assert(base_power != NULL && base_power->supported &&
        strcmp(base_power->name, "BasePower") == 0 &&
        base_power->algebra == POKEMON_EVENT_ALGEBRA_NUMERIC_OR_CANCEL);

    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_STARMIE, POKEMON_GEN3_MOVE_SURF,
        POKEMON_GEN3_SPECIES_VAPOREON, POKEMON_GEN3_MOVE_TACKLE
    );
    init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_WATERABSORB;
    init.teams[1].members[0].stats[0] = 401;
    init.initial_hp[1][0] = 201;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].state[0].hp == 301);
    int saw_heal = 0;
    int saw_immune = 0;
    for (size_t i = 0; i < battle.event_count; i++) {
        saw_heal += battle.events[i].kind == POKEMON_EVENT_HEAL &&
            battle.events[i].side == 1 && battle.events[i].amount == 100;
        saw_immune += battle.events[i].kind == POKEMON_EVENT_IMMUNE;
    }
    assert(saw_heal == 1 && saw_immune == 0);
    assert(battle.event_depth == 0);

    PokemonEventFrame frame;
    uint16_t hp_before_self_event = battle.sides[1].state[0].hp;
    assert(pokemon_run_event(&battle, &(PokemonEventInput){
        .event = POKEMON_HANDLER_EVENT_TRY_HIT,
        .source = {POKEMON_ENTITY_POKEMON, 1, 0},
        .target_side = 1, .target_slot = 0,
        .source_effect = {POKEMON_SOURCE_EFFECT_MOVE, POKEMON_GEN3_MOVE_SURF},
        .relay = {.kind = POKEMON_RELAY_BOOLEAN, .value.boolean = 1},
        .context_kind = POKEMON_EVENT_CONTEXT_MOVE,
        .context.move = {.move = &POKEMON_GEN3_SLICE_DATA.moves[7]},
    }, &frame) == POKEMON_OK);
    assert(frame.source.kind == POKEMON_ENTITY_POKEMON);
    assert(frame.source.side == 1 && frame.source.slot == 0);
    assert(frame.target.kind == POKEMON_ENTITY_POKEMON);
    assert(frame.target.side == 1 && frame.target.slot == 0);
    assert(frame.source_effect.kind == POKEMON_SOURCE_EFFECT_MOVE);
    assert(frame.source_effect.id == POKEMON_GEN3_MOVE_SURF);
    assert(frame.cancellation == POKEMON_EVENT_CANCEL_NONE);
    assert(battle.sides[1].state[0].hp == hp_before_self_event);

    PokemonEventInput absorb_input = {
        .event = POKEMON_HANDLER_EVENT_TRY_HIT,
        .source = {POKEMON_ENTITY_POKEMON, 0, 0},
        .target_side = 1, .target_slot = 0,
        .source_effect = {POKEMON_SOURCE_EFFECT_MOVE,
            POKEMON_GEN3_MOVE_SURF},
        .relay = {.kind = POKEMON_RELAY_BOOLEAN, .value.boolean = 1},
        .context_kind = POKEMON_EVENT_CONTEXT_MOVE,
        .context.move = {.move = &POKEMON_GEN3_SLICE_DATA.moves[7]},
    };
    assert(pokemon_run_event(&battle, &absorb_input, &frame) == POKEMON_OK);
    assert(frame.cancellation == POKEMON_EVENT_CANCEL_NULL);
    assert(frame.cancellation_emits_immunity == 0);
    assert(battle.sides[1].state[0].hp == 401);
    assert(pokemon_run_event(&battle, &absorb_input, &frame) == POKEMON_OK);
    assert(frame.cancellation == POKEMON_EVENT_CANCEL_NULL);
    assert(frame.cancellation_emits_immunity == 1);
    assert(battle.sides[1].state[0].hp == 401);

    PokemonBattle before = battle;
    assert(pokemon_run_event(&battle, &(PokemonEventInput){
        .event = POKEMON_HANDLER_EVENT_TRY_HIT,
        .target_side = 1, .target_slot = 0,
        .relay = {.kind = POKEMON_RELAY_U32, .value.u32 = 1},
        .context_kind = POKEMON_EVENT_CONTEXT_MOVE,
        .context.move = {.move = &POKEMON_GEN3_SLICE_DATA.moves[7]},
    }, &frame) == POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&battle, &before, sizeof(battle)) == 0);

    init = condition_init(
        POKEMON_GEN3_SPECIES_MAROWAK, POKEMON_GEN3_MOVE_DOUBLEEDGE,
        POKEMON_GEN3_SPECIES_VAPOREON, POKEMON_GEN3_MOVE_TACKLE
    );
    init.teams[0].members[0].ability_id = POKEMON_GEN3_ABILITY_ROCKHEAD;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_run_event(&battle, &(PokemonEventInput){
        .event = POKEMON_HANDLER_EVENT_DAMAGE,
        .target_side = 0, .target_slot = 0,
        .relay = {.kind = POKEMON_RELAY_U32, .value.u32 = 10},
        .context_kind = POKEMON_EVENT_CONTEXT_DAMAGE,
        .context.damage = {
            .kind = POKEMON_DAMAGE_RELATIVE_RECOIL,
            .source_move_id = POKEMON_GEN3_MOVE_DOUBLEEDGE,
            .preventable = 0,
        },
    }, &frame) == POKEMON_OK);
    assert(frame.cancellation == POKEMON_EVENT_CANCEL_NONE);
    assert(frame.relay.kind == POKEMON_RELAY_U32);
    assert(frame.relay.value.u32 == 10);
    assert(battle.event_depth == 0);

    assert(pokemon_run_event(&battle, &(PokemonEventInput){
        .event = POKEMON_HANDLER_EVENT_DAMAGE,
        .target_side = 0, .target_slot = 0,
        .relay = {.kind = POKEMON_RELAY_U32, .value.u32 = 10},
        .context_kind = POKEMON_EVENT_CONTEXT_DAMAGE,
        .context.damage = {
            .kind = POKEMON_DAMAGE_RELATIVE_RECOIL,
            .source_move_id = POKEMON_GEN3_MOVE_DOUBLEEDGE,
            .preventable = 1,
        },
    }, &frame) == POKEMON_OK);
    assert(frame.cancellation == POKEMON_EVENT_CANCEL_NULL);
    assert(frame.cancelling_owner.kind == POKEMON_OWNER_ABILITY);
    assert(frame.cancelling_owner.effect_id == POKEMON_GEN3_ABILITY_ROCKHEAD);
    assert(frame.cancelling_handler_id == POKEMON_GEN3_HANDLER_ROCK_HEAD);
    assert(battle.event_depth == 0);
}

static void test_weighted_active_move_power_distribution(void) {
    static const uint16_t seeds[][4] = {
        {2, 2, 3, 4}, {17, 2, 3, 4}, {6, 2, 3, 4},
        {25, 2, 3, 4}, {74, 2, 3, 4}, {134, 2, 3, 4},
        {164, 2, 3, 4},
    };
    static const uint16_t powers[] = {10, 30, 50, 70, 90, 110, 150};
    static const uint16_t messages[] = {4, 5, 6, 7, 8, 9, 10};
    const PokemonMoveData *magnitude = NULL;
    for (size_t i = 0; i < POKEMON_GEN3_SLICE_DATA.move_count; i++) {
        if (POKEMON_GEN3_SLICE_DATA.moves[i].id ==
                POKEMON_GEN3_MOVE_MAGNITUDE) {
            magnitude = &POKEMON_GEN3_SLICE_DATA.moves[i];
            break;
        }
    }
    const PokemonHandlerDescriptor *descriptor = NULL;
    size_t descriptor_index = 0;
    for (size_t i = 0; i < POKEMON_GEN3_SLICE_DATA.handler_count; i++) {
        const PokemonHandlerDescriptor *candidate =
            &POKEMON_GEN3_SLICE_DATA.handlers[i];
        if (candidate->event == POKEMON_HANDLER_EVENT_MODIFY_MOVE &&
            candidate->source_kind == POKEMON_HANDLER_SOURCE_MOVE &&
            candidate->source_id == POKEMON_GEN3_MOVE_MAGNITUDE) {
            descriptor = candidate;
            descriptor_index = i;
            break;
        }
    }
    assert(magnitude != NULL && descriptor != NULL);
    assert(POKEMON_GEN3_SLICE_DATA.weighted_move_distribution_count == 2);
    for (size_t sample = 0; sample < 7; sample++) {
        PokemonBattleInit init = condition_init(
            POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_MAGNITUDE,
            POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SPLASH);
        PokemonBattle battle;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        memcpy(battle.seed, seeds[sample], sizeof(battle.seed));
        battle.move_frame_depth = 1;
        battle.move_frames[0] = (PokemonActiveMoveFrame){
            .invocation = {.move_id = POKEMON_GEN3_MOVE_MAGNITUDE},
            .base_power = 0,
        };
        size_t draw_start = battle.draw_count;
        PokemonEventFrame result;
        assert(pokemon_run_event(&battle, &(PokemonEventInput){
            .event = POKEMON_HANDLER_EVENT_MODIFY_MOVE,
            .source = {POKEMON_ENTITY_POKEMON, 0, 0},
            .target_side = 1, .target_slot = 0,
            .source_effect = {POKEMON_SOURCE_EFFECT_MOVE,
                POKEMON_GEN3_MOVE_MAGNITUDE},
            .relay = {.kind = POKEMON_RELAY_UNDEFINED},
            .context_kind = POKEMON_EVENT_CONTEXT_MOVE,
            .context.move = {.move = magnitude},
            .has_only_handler = 1,
            .only_handler = {
                .descriptor = *descriptor,
                .binding_index = (uint16_t)descriptor_index,
                .owner = {POKEMON_OWNER_MOVE, 0, 0,
                    POKEMON_GEN3_MOVE_MAGNITUDE, 1},
                .holder_side = 0, .holder_slot = 0,
            },
        }, &result) == POKEMON_OK);
        assert(battle.draw_count == draw_start + 1);
        assert(battle.draws[draw_start].label ==
            POKEMON_DRAW_MOVE_POWER_DISTRIBUTION);
        assert(battle.draws[draw_start].upper_bound == 100);
        assert(battle.move_frames[0].base_power == powers[sample]);
        assert(battle.move_frames[0].has_message_value);
        assert(battle.move_frames[0].message_value == messages[sample]);
    }

    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_MAGNITUDE,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SPLASH);
    PokemonData invalid_data = POKEMON_GEN3_SLICE_DATA;
    PokemonWeightedMoveOutcome invalid_outcome = {
        .weight = 0,
        .kind = POKEMON_WEIGHTED_MOVE_OUTCOME_DAMAGE,
        .value.damage = {.power = 10, .message_value = 4},
    };
    invalid_data.weighted_move_outcomes = &invalid_outcome;
    invalid_data.weighted_move_outcome_count = 1;
    PokemonWeightedMoveOutcomeDistribution invalid_distribution = {
        .id = 1, .outcome_offset = 0, .outcome_count = 1,
        .draw_label = POKEMON_DRAW_MOVE_POWER_DISTRIBUTION,
    };
    invalid_data.weighted_move_distributions = &invalid_distribution;
    invalid_data.weighted_move_distribution_count = 1;
    PokemonResolvedBundle invalid_bundle = *init.bundle;
    invalid_bundle.data = &invalid_data;
    init.bundle = &invalid_bundle;
    PokemonBattle untouched;
    memset(&untouched, 0x5a, sizeof(untouched));
    PokemonBattle before = untouched;
    assert(pokemon_battle_init(&untouched, &init) ==
        POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&untouched, &before, sizeof(untouched)) == 0);
}

static void test_weighted_move_resolution_outcomes(void) {
    const PokemonMoveData *present = NULL;
    for (size_t i = 0; i < POKEMON_GEN3_SLICE_DATA.move_count; i++) {
        if (POKEMON_GEN3_SLICE_DATA.moves[i].id == POKEMON_GEN3_MOVE_PRESENT) {
            present = &POKEMON_GEN3_SLICE_DATA.moves[i];
            break;
        }
    }
    assert(present != NULL && present->power == 0);
    assert(present->accuracy.kind == POKEMON_ACCURACY_PERCENT);
    assert(present->accuracy.percent == 90);

    const PokemonWeightedMoveOutcomeDistribution *distribution = NULL;
    for (size_t i = 0;
         i < POKEMON_GEN3_SLICE_DATA.weighted_move_distribution_count; i++) {
        const PokemonWeightedMoveOutcomeDistribution *candidate =
            &POKEMON_GEN3_SLICE_DATA.weighted_move_distributions[i];
        if (candidate->id == 2) distribution = candidate;
    }
    assert(distribution != NULL && distribution->outcome_count == 4);
    assert(distribution->draw_label ==
        POKEMON_DRAW_MOVE_RESOLUTION_DISTRIBUTION);
    const PokemonWeightedMoveOutcome *outcomes =
        &POKEMON_GEN3_SLICE_DATA.weighted_move_outcomes[
            distribution->outcome_offset];
    assert(outcomes[0].weight == 2 && outcomes[0].kind ==
        POKEMON_WEIGHTED_MOVE_OUTCOME_TARGET_MAX_HP_HEAL);
    assert(outcomes[0].value.heal.numerator == 1 &&
        outcomes[0].value.heal.denominator == 4);
    static const uint16_t expected_power[] = {40, 80, 120};
    static const uint16_t expected_weight[] = {4, 3, 1};
    for (size_t i = 0; i < 3; i++) {
        assert(outcomes[i + 1].kind ==
            POKEMON_WEIGHTED_MOVE_OUTCOME_DAMAGE);
        assert(outcomes[i + 1].weight == expected_weight[i]);
        assert(outcomes[i + 1].value.damage.power == expected_power[i]);
    }

    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_PRESENT,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[0].members[0].ability_id = POKEMON_GEN3_ABILITY_OWNTEMPO;
    init.teams[1].members[0].stats[0] = 400;
    init.initial_hp[1][0] = 200;
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    uint8_t saw_bucket[4] = {0};
    for (uint16_t tail = 1; tail < 4096; tail++) {
        PokemonBattle battle;
        init.seed[3] = tail;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        const PokemonDraw *variant = NULL;
        for (size_t i = 0; i < battle.draw_count; i++) {
            if (battle.draws[i].label ==
                    POKEMON_DRAW_MOVE_RESOLUTION_DISTRIBUTION) {
                variant = &battle.draws[i];
                break;
            }
        }
        assert(variant != NULL && variant->upper_bound == 10);
        size_t bucket = variant->result < 2 ? 0 :
            variant->result < 6 ? 1 : variant->result < 9 ? 2 : 3;
        if (saw_bucket[bucket]) continue;
        if (draw_label_count(&battle, POKEMON_DRAW_ACCURACY) != 1) continue;
        if (bucket == 0) {
            assert(battle.sides[1].state[0].hp == 300);
            assert(draw_label_count(&battle, POKEMON_DRAW_CRITICAL) == 0);
            assert(draw_label_count(&battle, POKEMON_DRAW_DAMAGE_ROLL) == 0);
        } else {
            if (battle.sides[1].state[0].hp == 200) continue;
            assert(battle.sides[1].state[0].hp < 200);
            assert(draw_label_count(&battle, POKEMON_DRAW_CRITICAL) == 1);
            assert(draw_label_count(&battle, POKEMON_DRAW_DAMAGE_ROLL) == 1);
        }
        saw_bucket[bucket] = 1;
        if (saw_bucket[0] && saw_bucket[1] && saw_bucket[2] && saw_bucket[3]) {
            break;
        }
    }
    assert(saw_bucket[0] && saw_bucket[1] && saw_bucket[2] && saw_bucket[3]);

    PokemonData invalid_data = POKEMON_GEN3_SLICE_DATA;
    PokemonWeightedMoveOutcome copied_outcomes[11];
    PokemonWeightedMoveOutcomeDistribution copied_distributions[2];
    assert(invalid_data.weighted_move_outcome_count == 11);
    assert(invalid_data.weighted_move_distribution_count == 2);
    memcpy(copied_outcomes, invalid_data.weighted_move_outcomes,
        sizeof(copied_outcomes));
    memcpy(copied_distributions, invalid_data.weighted_move_distributions,
        sizeof(copied_distributions));
    invalid_data.weighted_move_outcomes = copied_outcomes;
    invalid_data.weighted_move_distributions = copied_distributions;
    PokemonResolvedBundle invalid_bundle = *init.bundle;
    invalid_bundle.data = &invalid_data;
    init.bundle = &invalid_bundle;
    PokemonBattle untouched;
    memset(&untouched, 0x5a, sizeof(untouched));
    PokemonBattle before = untouched;
    copied_outcomes[7].value.heal.denominator = 0;
    assert(pokemon_battle_init(&untouched, &init) ==
        POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&untouched, &before, sizeof(untouched)) == 0);
    copied_outcomes[7] = POKEMON_GEN3_SLICE_DATA.weighted_move_outcomes[7];
    copied_outcomes[7].kind = (PokemonWeightedMoveOutcomeKind)UINT8_MAX;
    assert(pokemon_battle_init(&untouched, &init) ==
        POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&untouched, &before, sizeof(untouched)) == 0);
    copied_outcomes[7] = POKEMON_GEN3_SLICE_DATA.weighted_move_outcomes[7];
    copied_distributions[1].draw_label = POKEMON_DRAW_ACCURACY;
    assert(pokemon_battle_init(&untouched, &init) ==
        POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&untouched, &before, sizeof(untouched)) == 0);
}

static void test_boost_table_event_contract(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_VAPOREON, POKEMON_GEN3_MOVE_TACKLE,
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_TACKLE);
    init.teams[0].members[0].ability_id = POKEMON_GEN3_ABILITY_WATERABSORB;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);

    PokemonBoostTable input = {0};
    input.present[POKEMON_STAT_ATK] = 1;
    input.delta[POKEMON_STAT_ATK] = -1;
    input.present[POKEMON_STAT_DEF] = 1;
    input.delta[POKEMON_STAT_DEF] = -1;
    PokemonEventFrame frame;
    assert(pokemon_run_event(&battle, &(PokemonEventInput){
        .event = POKEMON_HANDLER_EVENT_CHANGE_BOOST,
        .source = {POKEMON_ENTITY_POKEMON, 1, 0},
        .target_side = 0, .target_slot = 0,
        .source_effect = {POKEMON_SOURCE_EFFECT_MOVE, POKEMON_GEN3_MOVE_TACKLE},
        .relay = {.kind = POKEMON_RELAY_BOOST_TABLE, .value.boosts = input},
    }, &frame) == POKEMON_OK);
    assert(frame.executed_count == 0);
    assert(frame.relay.kind == POKEMON_RELAY_BOOST_TABLE);
    assert(memcmp(&frame.relay.value.boosts, &input, sizeof(input)) == 0);

    PokemonData data = POKEMON_GEN3_SLICE_DATA;
    PokemonMoveData moves[data.move_count];
    memcpy(moves, data.moves, sizeof(moves));
    for (size_t i = 0; i < data.move_count; i++) moves[i].call_pool_id = 0;
    data.moves = moves;
    PokemonHandlerOp program = {
        POKEMON_HANDLER_OP_DROP_BOOST_STAT, POKEMON_STAT_ATK};
    PokemonHandlerDescriptor handler = {
        .event = POKEMON_HANDLER_EVENT_TRY_BOOST,
        .id = 100,
        .source_kind = POKEMON_HANDLER_SOURCE_ABILITY,
        .source_id = POKEMON_GEN3_ABILITY_WATERABSORB,
        .program_offset = 0, .program_count = 1,
        .scope = POKEMON_HANDLER_SCOPE_TARGET,
        .route = POKEMON_HANDLER_ROUTE_OWNER,
    };
    PokemonOwnerBindingIndex index = {
        .owner_kind = POKEMON_OWNER_ABILITY,
        .owner_id = POKEMON_GEN3_ABILITY_WATERABSORB,
        .event = POKEMON_HANDLER_EVENT_TRY_BOOST,
        .scope = POKEMON_HANDLER_SCOPE_TARGET,
        .route = POKEMON_HANDLER_ROUTE_OWNER,
        .binding_offset = 0, .binding_count = 1,
    };
    data.handlers = &handler;
    data.handler_count = 1;
    data.handler_programs = &program;
    data.handler_program_count = 1;
    data.owner_binding_index = &index;
    data.owner_binding_index_count = 1;
    data.move_call_pools = NULL; data.move_call_pool_count = 0;
    data.move_call_pool_candidates = NULL;
    data.move_call_pool_candidate_count = 0;
    data.constructed_hit_templates = NULL;
    data.constructed_hit_template_count = 0;
    data.move_pre_use_programs = NULL;
    data.move_pre_use_program_count = 0;
    PokemonResolvedBundle bundle = *init.bundle;
    PokemonFormatPolicy policy = *bundle.policy;
    policy.status_clauses = NULL;
    policy.status_clause_count = 0;
    bundle.policy = &policy;
    bundle.data = &data;
    init.bundle = &bundle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_run_event(&battle, &(PokemonEventInput){
        .event = POKEMON_HANDLER_EVENT_TRY_BOOST,
        .source = {POKEMON_ENTITY_POKEMON, 1, 0},
        .target_side = 0, .target_slot = 0,
        .source_effect = {POKEMON_SOURCE_EFFECT_MOVE, POKEMON_GEN3_MOVE_TACKLE},
        .relay = {.kind = POKEMON_RELAY_BOOST_TABLE, .value.boosts = input},
    }, &frame) == POKEMON_OK);
    assert(frame.executed_count == 1);
    assert(frame.relay.kind == POKEMON_RELAY_BOOST_TABLE);
    assert(!frame.relay.value.boosts.present[POKEMON_STAT_ATK]);
    assert(frame.relay.value.boosts.delta[POKEMON_STAT_ATK] == 0);
    assert(frame.relay.value.boosts.present[POKEMON_STAT_DEF]);
    assert(frame.relay.value.boosts.delta[POKEMON_STAT_DEF] == -1);

    PokemonBattle before = battle;
    assert(pokemon_run_event(&battle, &(PokemonEventInput){
        .event = POKEMON_HANDLER_EVENT_TRY_BOOST,
        .source = {POKEMON_ENTITY_POKEMON, 1, 0},
        .target_side = 0, .target_slot = 0,
        .relay = {.kind = POKEMON_RELAY_BOOLEAN, .value.boolean = 1},
    }, &frame) == POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&battle, &before, sizeof(battle)) == 0);
}

static PokemonEventFrame run_try_boost(
    PokemonBattle *battle, PokemonEntityRef source, PokemonBoostTable boosts
) {
    PokemonEventFrame frame;
    assert(pokemon_run_event(battle, &(PokemonEventInput){
        .event = POKEMON_HANDLER_EVENT_TRY_BOOST,
        .source = source,
        .target_side = 0, .target_slot = 0,
        .source_effect = {POKEMON_SOURCE_EFFECT_MOVE, POKEMON_GEN3_MOVE_GROWL},
        .relay = {.kind = POKEMON_RELAY_BOOST_TABLE, .value.boosts = boosts},
    }, &frame) == POKEMON_OK);
    return frame;
}

static void test_negative_boost_filter_programs(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SKARMORY, POKEMON_GEN3_MOVE_SPLASH,
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_GROWL);
    PokemonBattle battle;
    PokemonBoostTable mixed = {0};
    mixed.present[POKEMON_STAT_ATK] = 1;
    mixed.delta[POKEMON_STAT_ATK] = -1;
    mixed.present[POKEMON_STAT_DEF] = 1;
    mixed.delta[POKEMON_STAT_DEF] = -2;
    mixed.present[POKEMON_STAT_SPA] = 1;
    mixed.delta[POKEMON_STAT_SPA] = 1;
    mixed.present[POKEMON_STAT_SPD] = 1; /* Present zero is preserved. */

    init.teams[0].members[0].ability_id = POKEMON_GEN3_ABILITY_CLEARBODY;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    uint8_t draw_count_before = battle.draw_count;
    PokemonEventFrame frame = run_try_boost(
        &battle, (PokemonEntityRef){POKEMON_ENTITY_POKEMON, 1, 0}, mixed);
    assert(!frame.relay.value.boosts.present[POKEMON_STAT_ATK]);
    assert(!frame.relay.value.boosts.present[POKEMON_STAT_DEF]);
    assert(frame.relay.value.boosts.present[POKEMON_STAT_SPA]);
    assert(frame.relay.value.boosts.delta[POKEMON_STAT_SPA] == 1);
    assert(frame.relay.value.boosts.present[POKEMON_STAT_SPD]);
    assert(frame.relay.value.boosts.delta[POKEMON_STAT_SPD] == 0);
    assert(frame.executed_count == 1 && frame.skipped_count == 0);
    assert(battle.handler_count == 1);
    assert(battle.draw_count == draw_count_before);
    assert(battle.handlers[0].handler.owner.kind == POKEMON_OWNER_ABILITY);
    assert(battle.handlers[0].handler.owner.effect_id ==
        POKEMON_GEN3_ABILITY_CLEARBODY);
    assert(battle.handlers[0].handler.descriptor.scope ==
        POKEMON_HANDLER_SCOPE_TARGET);
    assert(battle.handlers[0].handler.holder_side == 0);

    /* NONE is not self and is filtered. Explicit source == target bypasses. */
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    frame = run_try_boost(&battle, (PokemonEntityRef){0}, mixed);
    assert(!frame.relay.value.boosts.present[POKEMON_STAT_ATK]);
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    frame = run_try_boost(
        &battle, (PokemonEntityRef){POKEMON_ENTITY_POKEMON, 0, 0}, mixed);
    assert(frame.relay.value.boosts.present[POKEMON_STAT_ATK]);
    assert(frame.relay.value.boosts.delta[POKEMON_STAT_ATK] == -1);

    init.teams[0].members[0].ability_id = POKEMON_GEN3_ABILITY_WHITESMOKE;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    frame = run_try_boost(
        &battle, (PokemonEntityRef){POKEMON_ENTITY_POKEMON, 1, 0}, mixed);
    assert(!frame.relay.value.boosts.present[POKEMON_STAT_ATK]);
    assert(!frame.relay.value.boosts.present[POKEMON_STAT_DEF]);
    assert(frame.relay.value.boosts.present[POKEMON_STAT_SPA]);

    init.teams[0].members[0].ability_id = POKEMON_GEN3_ABILITY_HYPERCUTTER;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    frame = run_try_boost(
        &battle, (PokemonEntityRef){POKEMON_ENTITY_POKEMON, 1, 0}, mixed);
    assert(!frame.relay.value.boosts.present[POKEMON_STAT_ATK]);
    assert(frame.relay.value.boosts.present[POKEMON_STAT_DEF]);
    assert(frame.relay.value.boosts.delta[POKEMON_STAT_DEF] == -2);
    assert(frame.relay.value.boosts.present[POKEMON_STAT_SPA]);

    init.teams[0].members[0].ability_id = POKEMON_GEN3_ABILITY_KEENEYE;
    mixed.present[POKEMON_STAT_ACCURACY] = 1;
    mixed.delta[POKEMON_STAT_ACCURACY] = -1;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    frame = run_try_boost(
        &battle, (PokemonEntityRef){POKEMON_ENTITY_POKEMON, 1, 0}, mixed);
    assert(!frame.relay.value.boosts.present[POKEMON_STAT_ACCURACY]);
    assert(frame.relay.value.boosts.present[POKEMON_STAT_DEF]);

    /* The same generic program is side-owned for Mist. It filters all
     * externally sourced negatives, preserves nonnegative entries, and its
     * source/target guard admits self drops. */
    init.teams[0].members[0].ability_id = POKEMON_GEN3_ABILITY_WATERABSORB;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    battle.sides[0].conditions[0] = (PokemonSideConditionState){
        .kind = POKEMON_SIDE_CONDITION_MIST,
        .descriptor_id = POKEMON_GEN3_CONDITION_SIDE_MIST,
        .duration = 5, .state_generation = 1,
        .effect_order = ++battle.next_holder_effect_order,
    };
    battle.sides[0].condition_count = 1;
    assert(pokemon_battle_check_invariants(&battle));
    frame = run_try_boost(
        &battle, (PokemonEntityRef){POKEMON_ENTITY_POKEMON, 1, 0}, mixed);
    assert(!frame.relay.value.boosts.present[POKEMON_STAT_ATK]);
    assert(!frame.relay.value.boosts.present[POKEMON_STAT_DEF]);
    assert(!frame.relay.value.boosts.present[POKEMON_STAT_ACCURACY]);
    assert(frame.relay.value.boosts.present[POKEMON_STAT_SPA]);
    assert(frame.relay.value.boosts.present[POKEMON_STAT_SPD]);
    assert(frame.executed_count == 1 && frame.skipped_count == 0);
    assert(battle.handlers[battle.handler_count - 1].handler.owner.kind ==
        POKEMON_OWNER_SIDE);
    assert(battle.handlers[battle.handler_count - 1].handler.owner.effect_id ==
        POKEMON_GEN3_CONDITION_SIDE_MIST);
    frame = run_try_boost(
        &battle, (PokemonEntityRef){POKEMON_ENTITY_POKEMON, 0, 0}, mixed);
    assert(frame.relay.value.boosts.present[POKEMON_STAT_ATK]);
    assert(frame.relay.value.boosts.delta[POKEMON_STAT_ATK] == -1);
    assert(frame.relay.value.boosts.present[POKEMON_STAT_DEF]);
    assert(frame.relay.value.boosts.delta[POKEMON_STAT_DEF] == -2);

    /* Invalid stat arguments are rejected by the public transactional event
     * boundary without consuming traces or mutating canonical state. */
    PokemonData data = POKEMON_GEN3_SLICE_DATA;
    PokemonMoveData synthetic_moves[POKEMON_GEN3_MOVE_COUNT];
    remove_move_call_capability(&data, synthetic_moves);
    PokemonHandlerOp invalid_program = {
        POKEMON_HANDLER_OP_DROP_NEGATIVE_BOOST_STAT, POKEMON_STAT_COUNT};
    PokemonHandlerDescriptor invalid_handler = {
        .event = POKEMON_HANDLER_EVENT_TRY_BOOST, .id = 500,
        .source_kind = POKEMON_HANDLER_SOURCE_ABILITY,
        .source_id = POKEMON_GEN3_ABILITY_KEENEYE,
        .program_offset = 0, .program_count = 1,
        .scope = POKEMON_HANDLER_SCOPE_TARGET,
        .route = POKEMON_HANDLER_ROUTE_OWNER,
    };
    PokemonOwnerBindingIndex invalid_index = {
        .owner_kind = POKEMON_OWNER_ABILITY,
        .owner_id = POKEMON_GEN3_ABILITY_KEENEYE,
        .event = POKEMON_HANDLER_EVENT_TRY_BOOST,
        .scope = POKEMON_HANDLER_SCOPE_TARGET,
        .route = POKEMON_HANDLER_ROUTE_OWNER,
        .binding_offset = 0, .binding_count = 1,
    };
    data.handlers = &invalid_handler; data.handler_count = 1;
    data.handler_programs = &invalid_program; data.handler_program_count = 1;
    data.owner_binding_index = &invalid_index;
    data.owner_binding_index_count = 1;
    PokemonResolvedBundle bundle = *init.bundle;
    PokemonFormatPolicy policy = *bundle.policy;
    policy.status_clauses = NULL;
    policy.status_clause_count = 0;
    bundle.policy = &policy;
    bundle.data = &data;
    init.bundle = &bundle;
    init.teams[0].members[0].ability_id = POKEMON_GEN3_ABILITY_KEENEYE;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    PokemonBattle before = battle;
    assert(pokemon_run_event(&battle, &(PokemonEventInput){
        .event = POKEMON_HANDLER_EVENT_TRY_BOOST,
        .source = {POKEMON_ENTITY_POKEMON, 1, 0},
        .target_side = 0, .target_slot = 0,
        .relay = {.kind = POKEMON_RELAY_BOOST_TABLE, .value.boosts = mixed},
    }, &frame) == POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&battle, &before, sizeof(battle)) == 0);
}

static void test_event_handler_tie_ordering(void) {
    PokemonData data = POKEMON_GEN3_SLICE_DATA;
    PokemonMoveData synthetic_moves[POKEMON_GEN3_MOVE_COUNT];
    remove_move_call_capability(&data, synthetic_moves);
    PokemonEventSpec event_specs[data.event_spec_count];
    memcpy(event_specs, data.event_specs, sizeof(event_specs));
    event_specs[1].supported = 1;
    data.event_specs = event_specs;
    PokemonAbilityData abilities[data.ability_count];
    memcpy(abilities, data.abilities, sizeof(abilities));
    PokemonHandlerDescriptor handlers[3];
    PokemonOwnerBindingIndex owner_index[2] = {{
        .owner_kind = POKEMON_OWNER_ABILITY,
        .owner_id = POKEMON_GEN3_ABILITY_WATERABSORB,
        .event = POKEMON_HANDLER_EVENT_MODIFY_ATK,
        .scope = POKEMON_HANDLER_SCOPE_TARGET,
        .route = POKEMON_HANDLER_ROUTE_OWNER,
        .binding_offset = 0, .binding_count = 3}};
    data.owner_binding_index = owner_index;
    data.owner_binding_index_count = 1;
    PokemonHandlerOp programs[3] = {
        {POKEMON_HANDLER_OP_RETURN_UNDEFINED, 0},
        {POKEMON_HANDLER_OP_RETURN_UNDEFINED, 0},
        {POKEMON_HANDLER_OP_RETURN_UNDEFINED, 0},
    };
    for (size_t i = 0; i < 3; i++) {
        handlers[i] = (PokemonHandlerDescriptor){
            .event = POKEMON_HANDLER_EVENT_MODIFY_ATK,
            .id = (PokemonHandlerId)(i + 1),
            .source_kind = POKEMON_HANDLER_SOURCE_ABILITY,
            .source_id = POKEMON_GEN3_ABILITY_WATERABSORB,
            .program_offset = (uint16_t)i, .program_count = 1,
        };
    }
    for (size_t i = 0; i < data.ability_count; i++) {
        if (abilities[i].id == POKEMON_GEN3_ABILITY_WATERABSORB) {
            abilities[i].handler_offset = 0;
            abilities[i].handler_count = 3;
        }
    }
    data.abilities = abilities;
    data.handlers = handlers; data.handler_count = 3;
    data.handler_programs = programs; data.handler_program_count = 3;
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_VAPOREON, POKEMON_GEN3_MOVE_TACKLE,
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_TACKLE);
    PokemonResolvedBundle bundle = *init.bundle;
    PokemonFormatPolicy policy = *bundle.policy;
    policy.status_clauses = NULL;
    policy.status_clause_count = 0;
    bundle.policy = &policy;
    bundle.data = &data;
    init.bundle = &bundle;
    init.teams[0].members[0].ability_id = POKEMON_GEN3_ABILITY_WATERABSORB;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    size_t before_draws = battle.draw_count;
    PokemonEventFrame frame;
    assert(pokemon_run_event(&battle, &(PokemonEventInput){
        .event = POKEMON_HANDLER_EVENT_MODIFY_ATK,
        .source = {POKEMON_ENTITY_POKEMON, 0, 0},
        .target_side = 0, .target_slot = 0,
        .source_effect = {POKEMON_SOURCE_EFFECT_MOVE, POKEMON_GEN3_MOVE_TACKLE},
        .relay = {.kind = POKEMON_RELAY_U32, .value.u32 = 100},
        .context_kind = POKEMON_EVENT_CONTEXT_MOVE,
        .context.move = {.move = &data.moves[0]},
    }, &frame) == POKEMON_OK);
    assert(battle.draw_count == before_draws + 2);
    assert(battle.draws[before_draws].label == POKEMON_DRAW_EVENT_HANDLER_ORDER);
    assert(battle.draws[before_draws].context_event_id == POKEMON_HANDLER_EVENT_MODIFY_ATK);
    assert(battle.draws[before_draws].upper_bound == 3);
    assert(battle.draws[before_draws + 1].upper_bound == 2);
    PokemonBattle ordinary = battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_run_event(&battle, &(PokemonEventInput){
        .event = POKEMON_HANDLER_EVENT_MODIFY_ATK,
        .source = {POKEMON_ENTITY_POKEMON, 0, 0},
        .target_side = 0, .target_slot = 0,
        .source_effect = {POKEMON_SOURCE_EFFECT_MOVE, POKEMON_GEN3_MOVE_TACKLE},
        .relay = {.kind = POKEMON_RELAY_U32, .value.u32 = 100},
        .context_kind = POKEMON_EVENT_CONTEXT_MOVE,
        .context.move = {.move = &data.moves[0]},
    }, &frame) == POKEMON_OK);
    assert(memcmp(battle.seed, ordinary.seed, sizeof(battle.seed)) == 0);
    assert(battle.handler_count == ordinary.handler_count);
    for (size_t i = 0; i < battle.handler_count; i++) {
        assert(battle.handlers[i].handler.descriptor.id ==
            ordinary.handlers[i].handler.descriptor.id);
    }

    for (size_t i = 0; i < 3; i++) handlers[i].event = POKEMON_HANDLER_EVENT_TRY_HIT;
    owner_index[0].event = POKEMON_HANDLER_EVENT_TRY_HIT;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    before_draws = battle.draw_count;
    assert(pokemon_run_event(&battle, &(PokemonEventInput){
        .event = POKEMON_HANDLER_EVENT_TRY_HIT,
        .source = {POKEMON_ENTITY_POKEMON, 1, 0},
        .target_side = 0, .target_slot = 0,
        .source_effect = {POKEMON_SOURCE_EFFECT_MOVE, POKEMON_GEN3_MOVE_TACKLE},
        .relay = {.kind = POKEMON_RELAY_BOOLEAN, .value.boolean = 1},
        .context_kind = POKEMON_EVENT_CONTEXT_MOVE,
        .context.move = {.move = &data.moves[0]},
    }, &frame) == POKEMON_OK);
    assert(battle.draw_count == before_draws);
    assert(battle.handlers[0].handler.descriptor.id == 1);
    assert(battle.handlers[1].handler.descriptor.id == 2);
    assert(battle.handlers[2].handler.descriptor.id == 3);

    handlers[0].event = POKEMON_HANDLER_EVENT_MODIFY_ATK;
    owner_index[0].event = POKEMON_HANDLER_EVENT_MODIFY_ATK;
    handlers[0].program_offset = 0; handlers[0].program_count = 1;
    handlers[1].event = 2;
    handlers[1].program_offset = 1; handlers[1].program_count = 1;
    programs[0] = (PokemonHandlerOp){POKEMON_HANDLER_OP_NEST_EVENT,
        2};
    programs[1] = (PokemonHandlerOp){POKEMON_HANDLER_OP_RETURN_UNDEFINED, 0};
    for (size_t i = 0; i < data.ability_count; i++) {
        if (abilities[i].id == POKEMON_GEN3_ABILITY_WATERABSORB) {
            abilities[i].handler_count = 2;
        }
    }
    data.handler_count = 2; data.handler_program_count = 2;
    owner_index[0].binding_count = 1;
    owner_index[1] = owner_index[0];
    owner_index[1].event = 2;
    owner_index[1].binding_offset = 1;
    data.owner_binding_index_count = 2;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_run_event(&battle, &(PokemonEventInput){
        .event = POKEMON_HANDLER_EVENT_MODIFY_ATK,
        .source = {POKEMON_ENTITY_POKEMON, 0, 0},
        .target_side = 0, .target_slot = 0,
        .source_effect = {POKEMON_SOURCE_EFFECT_MOVE, POKEMON_GEN3_MOVE_TACKLE},
        .relay = {.kind = POKEMON_RELAY_U32, .value.u32 = 77},
        .context_kind = POKEMON_EVENT_CONTEXT_MOVE,
        .context.move = {.move = &data.moves[0]},
    }, &frame) == POKEMON_OK);
    assert(frame.depth == 0 && frame.relay.value.u32 == 77);
    assert(battle.event_frames[1].depth == 1);
    assert(battle.event_frames[1].event == 2);
    assert(battle.event_depth == 0);

    programs[1] = (PokemonHandlerOp){POKEMON_HANDLER_OP_NEST_EVENT,
        2};
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    PokemonBattle before_nested_failure = battle;
    assert(pokemon_run_event(&battle, &(PokemonEventInput){
        .event = POKEMON_HANDLER_EVENT_MODIFY_ATK,
        .source = {POKEMON_ENTITY_POKEMON, 0, 0},
        .target_side = 0, .target_slot = 0,
        .source_effect = {POKEMON_SOURCE_EFFECT_MOVE, POKEMON_GEN3_MOVE_TACKLE},
        .relay = {.kind = POKEMON_RELAY_U32, .value.u32 = 77},
        .context_kind = POKEMON_EVENT_CONTEXT_MOVE,
        .context.move = {.move = &data.moves[0]},
    }, &frame) == POKEMON_CAPACITY_EXCEEDED);
    assert(memcmp(&battle, &before_nested_failure, sizeof(battle)) == 0);

}

static void test_event_discovery_d1_scopes(void) {
    PokemonData data = POKEMON_GEN3_SLICE_DATA;
    PokemonMoveData synthetic_moves[POKEMON_GEN3_MOVE_COUNT];
    remove_move_call_capability(&data, synthetic_moves);
    PokemonEventSpec specs[data.event_spec_count];
    memcpy(specs, data.event_specs, sizeof(specs));
    specs[1].supported = 1; /* AfterHit: void notification. */
    data.event_specs = specs;
    PokemonAbilityData abilities[data.ability_count];
    memcpy(abilities, data.abilities, sizeof(abilities));
    for (size_t i = 0; i < data.ability_count; i++) {
        if (abilities[i].id == POKEMON_GEN3_ABILITY_WATERABSORB) {
            abilities[i].handler_offset = 0; abilities[i].handler_count = 4;
        }
    }
    data.abilities = abilities;
    PokemonHandlerOp programs[4];
    PokemonHandlerDescriptor handlers[4];
    PokemonOwnerBindingIndex index[4];
    const PokemonHandlerScope scopes[4] = {
        POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_SCOPE_SOURCE,
        POKEMON_HANDLER_SCOPE_FOE, POKEMON_HANDLER_SCOPE_ANY,
    };
    const int16_t orders[4] = {1, 4, 3, 2};
    for (size_t i = 0; i < 4; i++) {
        programs[i] = (PokemonHandlerOp){POKEMON_HANDLER_OP_RETURN_UNDEFINED, 0};
        handlers[i] = (PokemonHandlerDescriptor){
            .event = 2, .id = (PokemonHandlerId)(i + 1),
            .source_kind = POKEMON_HANDLER_SOURCE_ABILITY,
            .source_id = POKEMON_GEN3_ABILITY_WATERABSORB,
            .order = orders[i], .program_offset = (uint16_t)i,
            .program_count = 1, .scope = scopes[i],
            .route = POKEMON_HANDLER_ROUTE_OWNER, .raw_hook = "synthetic",
        };
        index[i] = (PokemonOwnerBindingIndex){
            .owner_kind = POKEMON_OWNER_ABILITY,
            .owner_id = POKEMON_GEN3_ABILITY_WATERABSORB,
            .event = 2, .scope = scopes[i],
            .route = POKEMON_HANDLER_ROUTE_OWNER,
            .binding_offset = (uint16_t)i, .binding_count = 1,
        };
    }
    data.handlers = handlers; data.handler_count = 4;
    data.handler_programs = programs; data.handler_program_count = 4;
    data.owner_binding_index = index; data.owner_binding_index_count = 4;
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_VAPOREON, POKEMON_GEN3_MOVE_TACKLE,
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_TACKLE);
    PokemonResolvedBundle bundle = *init.bundle;
    PokemonFormatPolicy policy = *bundle.policy;
    policy.status_clauses = NULL;
    policy.status_clause_count = 0;
    bundle.policy = &policy;
    bundle.data = &data;
    init.bundle = &bundle;
    init.teams[0].members[0].ability_id = POKEMON_GEN3_ABILITY_WATERABSORB;
    init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_WATERABSORB;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    size_t draws_before = battle.draw_count;
    PokemonEventFrame frame;
    assert(pokemon_run_event(&battle, &(PokemonEventInput){
        .event = 2, .source = {POKEMON_ENTITY_POKEMON, 1, 0},
        .target_side = 0, .target_slot = 0,
        .relay = {.kind = POKEMON_RELAY_UNDEFINED},
        .context_kind = POKEMON_EVENT_CONTEXT_MOVE,
        .context.move = {.move = &data.moves[0]},
    }, &frame) == POKEMON_OK);
    assert(battle.handler_count == 5); /* ANY once per distinct holder. */
    const uint16_t ids[5] = {1, 4, 4, 3, 2};
    const uint8_t sides[5] = {0, 0, 1, 1, 1};
    for (size_t i = 0; i < 5; i++) {
        assert(battle.handlers[i].handler.descriptor.id == ids[i]);
        assert(battle.handlers[i].handler.owner.side == sides[i]);
        assert(battle.handlers[i].handler.effect_order ==
            battle.sides[sides[i]].state[0].ability_effect_order);
    }
    assert(battle.draw_count == draws_before);
    assert(frame.executed_count == 5 && frame.skipped_count == 0);
}

static void test_event_discovery_d2_installed_conditions(void) {
    PokemonData data = POKEMON_GEN3_SLICE_DATA;
    PokemonMoveData synthetic_moves[POKEMON_GEN3_MOVE_COUNT];
    remove_move_call_capability(&data, synthetic_moves);
    PokemonEventSpec specs[data.event_spec_count];
    memcpy(specs, data.event_specs, sizeof(specs));
    specs[1].supported = 1; /* AfterHit: void notification. */
    data.event_specs = specs;

    PokemonHandlerOp program = {
        POKEMON_HANDLER_OP_RETURN_UNDEFINED, 0,
    };
    PokemonHandlerDescriptor handlers[5];
    PokemonOwnerBindingIndex index[5];
    const PokemonOwnerKind owner_kinds[5] = {
        POKEMON_OWNER_STATUS, POKEMON_OWNER_VOLATILE,
        POKEMON_OWNER_VOLATILE, POKEMON_OWNER_ABILITY, POKEMON_OWNER_ITEM,
    };
    const uint16_t owner_ids[5] = {
        POKEMON_GEN3_CONDITION_STATUS_BRN,
        POKEMON_GEN3_CONDITION_VOLATILE_PROTECT,
        POKEMON_GEN3_CONDITION_VOLATILE_STALL, POKEMON_GEN3_ABILITY_GUTS,
        POKEMON_GEN3_ITEM_BLACKBELT,
    };
    const int8_t sub_orders[5] = {0, 2, 2, 7, 8};
    for (size_t i = 0; i < 5; i++) {
        handlers[i] = (PokemonHandlerDescriptor){
            .event = 2, .id = (PokemonHandlerId)(i + 1),
            .source_kind = i < 3 ? POKEMON_HANDLER_SOURCE_CONDITION :
                (i == 3 ? POKEMON_HANDLER_SOURCE_ABILITY :
                    POKEMON_HANDLER_SOURCE_ITEM),
            .source_id = owner_ids[i], .order = (int16_t)(i + 1),
            .sub_order = sub_orders[i], .program_offset = 0,
            .program_count = 1, .scope = POKEMON_HANDLER_SCOPE_TARGET,
            .route = POKEMON_HANDLER_ROUTE_OWNER, .raw_hook = "synthetic",
        };
        index[i] = (PokemonOwnerBindingIndex){
            .owner_kind = owner_kinds[i], .owner_id = owner_ids[i],
            .event = 2, .scope = POKEMON_HANDLER_SCOPE_TARGET,
            .route = POKEMON_HANDLER_ROUTE_OWNER,
            .binding_offset = (uint16_t)i, .binding_count = 1,
        };
    }
    data.handlers = handlers;
    data.handler_count = 5;
    data.handler_programs = &program;
    data.handler_program_count = 1;
    data.owner_binding_index = index;
    data.owner_binding_index_count = 5;

    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_MACHOP, POKEMON_GEN3_MOVE_TACKLE,
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_TACKLE);
    PokemonResolvedBundle bundle = *init.bundle;
    PokemonFormatPolicy policy = *bundle.policy;
    policy.status_clauses = NULL;
    policy.status_clause_count = 0;
    bundle.policy = &policy;
    bundle.data = &data;
    init.bundle = &bundle;
    init.teams[0].members[0].ability_id = POKEMON_GEN3_ABILITY_GUTS;
    init.teams[0].members[0].item_id = POKEMON_GEN3_ITEM_BLACKBELT;
    init.initial_status[0][0] = POKEMON_STATUS_BURN;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    PokemonMutable *holder = &battle.sides[0].state[0];
    holder->volatiles[0] = (PokemonVolatileState){
        .kind = POKEMON_VOLATILE_PROTECT, .duration = 1,
        .descriptor_id = POKEMON_GEN3_CONDITION_VOLATILE_PROTECT,
        .state_generation = 11,
        .effect_order = ++battle.next_holder_effect_order,
    };
    holder->volatiles[1] = (PokemonVolatileState){
        .kind = POKEMON_VOLATILE_STALL, .duration = 1, .counter = 2,
        .descriptor_id = POKEMON_GEN3_CONDITION_VOLATILE_STALL,
        .state_generation = 12,
        .effect_order = ++battle.next_holder_effect_order,
    };
    holder->volatile_count = 2;
    assert(pokemon_battle_check_invariants(&battle));
    const uint16_t generations[5] = {
        holder->status.state_generation, 11, 12,
        holder->ability_generation, holder->item_generation,
    };
    const uint16_t effect_orders[5] = {
        holder->status.effect_order, holder->volatiles[0].effect_order,
        holder->volatiles[1].effect_order, holder->ability_effect_order,
        holder->item_effect_order,
    };
    size_t draws_before = battle.draw_count;
    PokemonEventFrame frame;
    assert(pokemon_run_event(&battle, &(PokemonEventInput){
        .event = 2, .source = {POKEMON_ENTITY_POKEMON, 1, 0},
        .target_side = 0, .target_slot = 0,
        .relay = {.kind = POKEMON_RELAY_UNDEFINED},
        .context_kind = POKEMON_EVENT_CONTEXT_MOVE,
        .context.move = {.move = &data.moves[0]},
    }, &frame) == POKEMON_OK);
    assert(battle.handler_count == 5);
    assert(frame.executed_count == 5 && frame.skipped_count == 0);
    for (size_t i = 0; i < 5; i++) {
        const PokemonHandlerRef *ref = &battle.handlers[i].handler;
        assert(ref->descriptor.id == i + 1);
        assert(ref->owner.kind == owner_kinds[i]);
        assert(ref->owner.effect_id == owner_ids[i]);
        assert(ref->owner.state_generation == generations[i]);
        assert(ref->descriptor.sub_order == sub_orders[i]);
        assert(ref->effect_order == effect_orders[i]);
    }
    assert(battle.draw_count == draws_before);
}

static void test_event_discovery_d3_side_and_weather(void) {
    PokemonData data = POKEMON_GEN3_SLICE_DATA;
    PokemonMoveData synthetic_moves[POKEMON_GEN3_MOVE_COUNT];
    remove_move_call_capability(&data, synthetic_moves);
    PokemonEventSpec specs[data.event_spec_count];
    memcpy(specs, data.event_specs, sizeof(specs));
    specs[1].supported = 1; /* AfterHit: void notification. */
    data.event_specs = specs;
    PokemonHandlerOp programs[3];
    PokemonHandlerDescriptor handlers[3];
    PokemonOwnerBindingIndex index[3];
    const PokemonOwnerKind kinds[3] = {
        POKEMON_OWNER_SIDE, POKEMON_OWNER_SIDE, POKEMON_OWNER_FIELD,
    };
    const uint16_t owner_ids[3] = {
        POKEMON_GEN3_CONDITION_SIDE_REFLECT,
        POKEMON_GEN3_CONDITION_SIDE_REFLECT,
        POKEMON_GEN3_CONDITION_WEATHER_SANDSTORM,
    };
    const PokemonHandlerScope scopes[3] = {
        POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_SCOPE_FOE,
        POKEMON_HANDLER_SCOPE_TARGET,
    };
    for (size_t i = 0; i < 3; i++) {
        programs[i] = (PokemonHandlerOp){POKEMON_HANDLER_OP_RETURN_UNDEFINED, 0};
        handlers[i] = (PokemonHandlerDescriptor){
            .event = 2, .id = (PokemonHandlerId)(i + 1),
            .source_kind = POKEMON_HANDLER_SOURCE_CONDITION,
            .source_id = owner_ids[i], .order = (int16_t)(i + 1),
            .sub_order = i < 2 ? 4 : 5,
            .program_offset = (uint16_t)i, .program_count = 1,
            .scope = scopes[i], .route = POKEMON_HANDLER_ROUTE_OWNER,
            .raw_hook = "synthetic",
        };
        index[i] = (PokemonOwnerBindingIndex){
            .owner_kind = kinds[i], .owner_id = owner_ids[i], .event = 2,
            .scope = scopes[i], .route = POKEMON_HANDLER_ROUTE_OWNER,
            .binding_offset = (uint16_t)i, .binding_count = 1,
        };
    }
    data.handlers = handlers; data.handler_count = 3;
    data.handler_programs = programs; data.handler_program_count = 3;
    data.owner_binding_index = index; data.owner_binding_index_count = 3;
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_VAPOREON, POKEMON_GEN3_MOVE_TACKLE,
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_TACKLE);
    PokemonResolvedBundle bundle = *init.bundle;
    PokemonFormatPolicy policy = *bundle.policy;
    policy.status_clauses = NULL;
    policy.status_clause_count = 0;
    bundle.policy = &policy;
    bundle.data = &data; init.bundle = &bundle;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    battle.sides[0].conditions[0] = (PokemonSideConditionState){
        .kind = POKEMON_SIDE_CONDITION_REFLECT,
        .descriptor_id = POKEMON_GEN3_CONDITION_SIDE_REFLECT,
        .duration = 5, .state_generation = 1, .effect_order = 5,
    };
    battle.sides[0].condition_count = 1;
    battle.sides[1].conditions[0] = (PokemonSideConditionState){
        .kind = POKEMON_SIDE_CONDITION_REFLECT,
        .descriptor_id = POKEMON_GEN3_CONDITION_SIDE_REFLECT,
        .duration = 5, .state_generation = 1, .effect_order = 6,
    };
    battle.sides[1].condition_count = 1;
    battle.field.weather = (PokemonWeatherState){
        .kind = POKEMON_WEATHER_SANDSTORM,
        .descriptor_id = POKEMON_GEN3_CONDITION_WEATHER_SANDSTORM,
        .duration = 5, .source_side = 0, .source_slot = 0,
        .state_generation = 1, .effect_order = 0,
    };
    size_t draws_before = battle.draw_count;
    PokemonEventFrame frame;
    assert(pokemon_run_event(&battle, &(PokemonEventInput){
        .event = 2, .source = {POKEMON_ENTITY_POKEMON, 1, 0},
        .target_side = 0, .target_slot = 0,
        .relay = {.kind = POKEMON_RELAY_UNDEFINED},
        .context_kind = POKEMON_EVENT_CONTEXT_MOVE,
        .context.move = {.move = &data.moves[0]},
    }, &frame) == POKEMON_OK);
    assert(frame.executed_count == 3 && frame.skipped_count == 0);
    assert(battle.draw_count == draws_before);
    const PokemonOwnerKind expected_kinds[3] = {
        POKEMON_OWNER_SIDE, POKEMON_OWNER_SIDE, POKEMON_OWNER_FIELD,
    };
    const uint8_t expected_sides[3] = {0, 1, 0};
    const uint16_t expected_effect_orders[3] = {5, 6, 0};
    for (size_t i = 0; i < 3; i++) {
        const PokemonHandlerRef *ref = &battle.handlers[i].handler;
        assert(ref->descriptor.id == i + 1);
        assert(ref->owner.kind == expected_kinds[i]);
        assert(ref->owner.side == expected_sides[i]);
        assert(ref->effect_order == expected_effect_orders[i] && ref->speed == 0);
        assert(ref->descriptor.sub_order == (i < 2 ? 4 : 5));
    }
}

static void test_holder_installation_lifecycle(void) {
    PokemonBattleInit init = battle_init();
    init.teams[0].members[0].item_id = POKEMON_GEN3_ITEM_BLACKBELT;
    init.teams[0].members[1].item_id = POKEMON_GEN3_ITEM_MYSTICWATER;
    /* This lifecycle test isolates switching; the default opposing Thief is
     * now a real item-transfer move. */
    init.teams[1].members[0].move_ids[0] = POKEMON_GEN3_MOVE_SPLASH;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(battle.sides[0].state[0].ability_effect_order == 0);
    assert(battle.sides[0].state[0].item_effect_order != 0);
    assert(battle.sides[0].state[1].ability_effect_order == 0);
    assert(battle.sides[0].state[1].item_effect_order == 0);
    uint16_t incoming_ability_generation =
        battle.sides[0].state[1].ability_generation;
    uint16_t incoming_item_generation = battle.sides[0].state[1].item_generation;
    battle.sides[0].state[0].ability_id = POKEMON_GEN3_ABILITY_GUTS;
    uint16_t effect_order_before = battle.next_holder_effect_order;
    PokemonChoice choices[POKEMON_SIDES] = {switch_to(1), move(0)};
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].ability_id ==
        init.teams[0].members[0].ability_id);
    assert(battle.sides[0].state[0].item_id == POKEMON_GEN3_ITEM_BLACKBELT);
    assert(battle.sides[0].state[1].ability_generation ==
        incoming_ability_generation + 1);
    assert(battle.sides[0].state[1].item_generation == incoming_item_generation + 1);
    assert(battle.sides[0].state[1].ability_effect_order == 0);
    assert(battle.sides[0].state[1].item_effect_order != 0);
    assert(battle.sides[0].state[1].item_id == POKEMON_GEN3_ITEM_MYSTICWATER);
    assert(battle.next_holder_effect_order == effect_order_before + 1);
}

static void test_natural_immunity_wins_after_accuracy_consumption(void) {
    TEST_MOVE.accuracy = (PokemonAccuracy){POKEMON_ACCURACY_PERCENT, 1};
    TEST_TYPE_CHART[0] = 0;
    PokemonBattleInit init = mechanic_init(4);
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.events[1].kind == POKEMON_EVENT_IMMUNE);
    assert(battle.events[1].immunity_cause == POKEMON_IMMUNITY_NATURAL_TYPE);
    assert(battle.draws[0].label == POKEMON_DRAW_ACCURACY);
    assert(battle.draws[0].result >= TEST_MOVE.accuracy.percent);
    assert(battle.draw_count == 3);
    assert(battle.handler_count == 0);
    TEST_TYPE_CHART[0] = 4;
    TEST_MOVE.accuracy = (PokemonAccuracy){POKEMON_ACCURACY_PERCENT, 100};
}

static void install_protect_for_test(PokemonBattle *battle, size_t side) {
    PokemonMutable *holder = &battle->sides[side].state[
        battle->sides[side].active];
    assert(holder->volatile_count == 0);
    holder->volatiles[0] = (PokemonVolatileState){
        .kind = POKEMON_VOLATILE_PROTECT,
        .duration = 1,
        .descriptor_id = POKEMON_GEN3_CONDITION_VOLATILE_PROTECT,
        .state_generation = 1,
        .effect_order = ++battle->next_holder_effect_order,
    };
    holder->volatile_count = 1;
    assert(pokemon_battle_check_invariants(battle));
}

static size_t draw_label_count(
    const PokemonBattle *battle, PokemonDrawLabel label
) {
    size_t count = 0;
    for (size_t i = 0; i < battle->draw_count; i++) {
        if (battle->draws[i].label == label) count++;
    }
    return count;
}

static size_t handler_event_count(
    const PokemonBattle *battle, PokemonEventId event
) {
    size_t count = 0;
    for (size_t i = 0; i < battle->handler_count; i++) {
        if (battle->handlers[i].handler.descriptor.event == event) count++;
    }
    return count;
}

static size_t event_kind_count(
    const PokemonBattle *battle, PokemonEventKind kind
) {
    size_t count = 0;
    for (size_t i = 0; i < battle->event_count; i++) {
        if (battle->events[i].kind == kind) count++;
    }
    return count;
}

static size_t handler_id_count(
    const PokemonBattle *battle, uint16_t handler_id
) {
    size_t count = 0;
    for (size_t i = 0; i < battle->handler_count; i++) {
        if (battle->handlers[i].handler.descriptor.id == handler_id) count++;
    }
    return count;
}

static int accuracy_protect_owned_state_equal(
    const PokemonBattle *left, const PokemonBattle *right
) {
    if (left->turn != right->turn || left->phase != right->phase ||
        left->semantic_sequence != right->semantic_sequence ||
        memcmp(left->seed, right->seed, sizeof(left->seed)) != 0) return 0;
    for (size_t side = 0; side < POKEMON_SIDES; side++) {
        if (left->sides[side].active != right->sides[side].active) return 0;
        size_t slot = left->sides[side].active;
        if (left->sides[side].state[slot].hp != right->sides[side].state[slot].hp ||
            left->sides[side].state[slot].status.kind !=
                right->sides[side].state[slot].status.kind ||
            memcmp(left->sides[side].state[slot].pp,
            right->sides[side].state[slot].pp,
            sizeof(left->sides[side].state[slot].pp)) != 0) return 0;
    }
    return 1;
}

static void assert_accuracy_protect_replay_equal(
    const PokemonBattle *left, const PokemonBattle *right
) {
    assert(accuracy_protect_owned_state_equal(left, right));
    assert(left->draw_count == right->draw_count);
    for (size_t i = 0; i < left->draw_count; i++) {
        assert(left->draws[i].label == right->draws[i].label);
        assert(left->draws[i].context_event_id == right->draws[i].context_event_id);
        assert(left->draws[i].semantic_sequence == right->draws[i].semantic_sequence);
        assert(left->draws[i].upper_bound == right->draws[i].upper_bound);
        assert(left->draws[i].raw == right->draws[i].raw);
        assert(left->draws[i].result == right->draws[i].result);
    }
    assert(left->event_count == right->event_count);
    for (size_t i = 0; i < left->event_count; i++) {
        assert(left->events[i].kind == right->events[i].kind);
        assert(left->events[i].side == right->events[i].side);
        assert(left->events[i].target_side == right->events[i].target_side);
        assert(left->events[i].slot == right->events[i].slot);
        assert(left->events[i].move_id == right->events[i].move_id);
        assert(left->events[i].amount == right->events[i].amount);
        assert(left->events[i].hp == right->events[i].hp);
        assert(left->events[i].immunity_cause == right->events[i].immunity_cause);
        assert(left->events[i].handler_id == right->events[i].handler_id);
    }
    assert(left->handler_count == right->handler_count);
    for (size_t i = 0; i < left->handler_count; i++) {
        assert(left->handlers[i].handler.descriptor.id ==
            right->handlers[i].handler.descriptor.id);
        assert(left->handlers[i].handler.owner.kind ==
            right->handlers[i].handler.owner.kind);
        assert(left->handlers[i].handler.holder_side ==
            right->handlers[i].handler.holder_side);
        assert(left->handlers[i].handler.holder_slot ==
            right->handlers[i].handler.holder_slot);
        assert(left->handlers[i].semantic_sequence ==
            right->handlers[i].semantic_sequence);
        assert(left->handlers[i].invoked == right->handlers[i].invoked);
        assert(left->handlers[i].result == right->handlers[i].result);
    }
}

static void test_gen3_accuracy_precedes_protect_try_hit(void) {
    static const uint16_t moves[] = {
        POKEMON_GEN3_MOVE_TOXIC,   /* numeric 85, status */
        POKEMON_GEN3_MOVE_STRENGTH, /* numeric 100, damaging */
    };
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    uint16_t accuracy_hit_seed = find_accuracy_seed(63);
    for (size_t i = 0; i < sizeof(moves) / sizeof(moves[0]); i++) {
        PokemonBattleInit init = condition_init(
            POKEMON_GEN3_SPECIES_PERSIAN, moves[i],
            POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SPLASH);
        init.seed[3] = accuracy_hit_seed;
        PokemonBattle protected_a, protected_b, unprotected;
        assert(pokemon_battle_init(&protected_a, &init) == POKEMON_OK);
        assert(pokemon_battle_init(&protected_b, &init) == POKEMON_OK);
        assert(pokemon_battle_init(&unprotected, &init) == POKEMON_OK);
        install_protect_for_test(&protected_a, 1);
        install_protect_for_test(&protected_b, 1);
        uint16_t hp_before = protected_a.sides[1].state[0].hp;
        assert(pokemon_battle_step(&protected_a, choices) == POKEMON_OK);
        assert(pokemon_battle_step(&protected_b, choices) == POKEMON_OK);
        assert_accuracy_protect_replay_equal(&protected_a, &protected_b);
        PokemonBattle divergent = protected_b;
        divergent.sides[1].state[divergent.sides[1].active].hp--;
        assert(!accuracy_protect_owned_state_equal(&protected_a, &divergent));
        assert(draw_label_count(&protected_a, POKEMON_DRAW_ACCURACY) == 1);
        assert(protected_a.sides[1].state[0].hp == hp_before);
        assert(protected_a.sides[1].state[0].status.kind == POKEMON_STATUS_NONE);
        /* The opposing self-targeting status action also discovers the
         * installed target-owned TryHit handler and lets its predicate skip. */
        assert(protected_a.handler_count == 2);
        assert(protected_a.handlers[0].handler.descriptor.id ==
            POKEMON_GEN3_HANDLER_PROTECT);
		assert(protected_a.handlers[1].handler.descriptor.id ==
			POKEMON_GEN3_HANDLER_PROTECT);
        assert(protected_a.handlers[0].handler.descriptor.priority == 3);
        assert(protected_a.handlers[0].handler.owner.kind ==
            POKEMON_OWNER_VOLATILE);
        assert(protected_a.events[1].kind == POKEMON_EVENT_BLOCK);

        assert(pokemon_battle_step(&unprotected, choices) == POKEMON_OK);
        assert(draw_label_count(&unprotected, POKEMON_DRAW_ACCURACY) == 1);

        PokemonData invalid_data = *init.bundle->data;
        PokemonHandlerDescriptor invalid_handlers[
            POKEMON_GEN3_HANDLER_DESCRIPTOR_COUNT];
        assert(invalid_data.handler_count <=
            sizeof(invalid_handlers) / sizeof(invalid_handlers[0]));
        memcpy(invalid_handlers, invalid_data.handlers,
            invalid_data.handler_count * sizeof(invalid_handlers[0]));
        uint8_t found_protect = 0;
        for (size_t handler = 0; handler < invalid_data.handler_count; handler++) {
            if (invalid_handlers[handler].id == POKEMON_GEN3_HANDLER_PROTECT) {
                invalid_handlers[handler].program_count = UINT8_MAX;
                found_protect = 1;
            }
        }
        assert(found_protect);
        invalid_data.handlers = invalid_handlers;
        PokemonResolvedBundle invalid_bundle = *init.bundle;
        invalid_bundle.data = &invalid_data;
        init.bundle = &invalid_bundle;
        PokemonBattle before = protected_a;
        assert(pokemon_battle_init(&protected_a, &init) ==
            POKEMON_INVALID_CONFIGURATION);
        assert(memcmp(&protected_a, &before, sizeof(protected_a)) == 0);
    }
}

static void assert_bone_rush_precedence(
    uint16_t defender_species, uint16_t defender_ability,
    PokemonImmunityCause expected_cause, PokemonEventKind expected_event
) {
    PokemonBattleInit init = immunity_init(
        POKEMON_GEN3_MOVE_BONERUSH, defender_species, defender_ability
    );
    init.teams[0].members[0].species_id = POKEMON_GEN3_SPECIES_MAROWAK;
    init.teams[1].members[0].move_ids[0] = POKEMON_GEN3_MOVE_SPLASH;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.immunities[0].cause == expected_cause);
    assert(battle.events[1].kind == expected_event);
    assert(battle.handler_count == 0);
    size_t accuracy_draws = 0;
    for (size_t i = 0; i < battle.draw_count; i++) {
        if (battle.draws[i].label == POKEMON_DRAW_ACCURACY) accuracy_draws++;
    }
    if (expected_cause == POKEMON_IMMUNITY_NONE) {
        assert(accuracy_draws == 1);
        assert(battle.draws[0].label == POKEMON_DRAW_ACCURACY);
        assert(battle.draws[0].result >= 80);
    } else {
        assert(accuracy_draws == 1);
    }
}

static void test_bone_rush_immunity_and_accuracy_precedence(void) {
    assert_bone_rush_precedence(
        POKEMON_GEN3_SPECIES_PERSIAN, 0,
        POKEMON_IMMUNITY_NONE, POKEMON_EVENT_MISS
    );
    assert_bone_rush_precedence(
        POKEMON_GEN3_SPECIES_CHARIZARD, 0,
        POKEMON_IMMUNITY_NATURAL_TYPE, POKEMON_EVENT_IMMUNE
    );
    assert_bone_rush_precedence(
        POKEMON_GEN3_SPECIES_GENGAR, POKEMON_GEN3_ABILITY_LEVITATE,
        POKEMON_IMMUNITY_LEVITATE, POKEMON_EVENT_IMMUNE
    );
}

static void test_handler_order_and_capacity_failure(void) {
    PokemonHandlerRef slower = {
        .descriptor = {
            .event = POKEMON_HANDLER_EVENT_TRY_HIT,
            .id = POKEMON_GEN3_HANDLER_WATER_ABSORB,
            .source_kind = POKEMON_HANDLER_SOURCE_ABILITY,
            .source_id = 10,
            .priority = 1,
        },
        .speed = 100,
        .effect_order = 2,
    };
    PokemonHandlerRef faster = slower;
    faster.speed = 200;
    assert(pokemon_compare_handler_refs(&faster, &slower) < 0);
    faster.descriptor.priority = 0;
    assert(pokemon_compare_handler_refs(&slower, &faster) < 0);
    faster.descriptor.priority = 1;
    faster.descriptor.order = 1;
    assert(pokemon_compare_handler_refs(&faster, &slower) < 0);
    PokemonHandlerRef unordered[2] = {slower, faster};
    pokemon_order_handler_refs(unordered, 2);
    assert(unordered[0].descriptor.order == 1);
    assert(unordered[1].descriptor.order == 0);

    static PokemonHandlerDescriptor too_many[POKEMON_HANDLER_CAPACITY + 1];
    static PokemonAbilityData ability;
    for (size_t i = 0; i < POKEMON_HANDLER_CAPACITY + 1; i++) {
        too_many[i] = (PokemonHandlerDescriptor){
            .event = POKEMON_HANDLER_EVENT_TRY_HIT,
            .id = POKEMON_GEN3_HANDLER_WATER_ABSORB,
            .source_kind = POKEMON_HANDLER_SOURCE_ABILITY,
            .source_id = 99,
        };
    }
    ability = (PokemonAbilityData){99, 0, POKEMON_HANDLER_CAPACITY + 1, 0, 0, 0, 0, 0, 0};
    PokemonBattleInit init = mechanic_init(7);
    PokemonData data = *init.bundle->data;
    data.abilities = &ability;
    data.ability_count = 1;
    data.handlers = too_many;
    data.handler_count = POKEMON_HANDLER_CAPACITY + 1;
    PokemonOwnerBindingIndex owner_index = {
        .owner_kind = POKEMON_OWNER_ABILITY, .owner_id = 99,
        .event = POKEMON_HANDLER_EVENT_TRY_HIT,
        .scope = POKEMON_HANDLER_SCOPE_TARGET,
        .route = POKEMON_HANDLER_ROUTE_OWNER,
        .binding_offset = 0, .binding_count = POKEMON_HANDLER_CAPACITY + 1};
    data.owner_binding_index = &owner_index;
    data.owner_binding_index_count = 1;
    PokemonResolvedBundle bundle = *init.bundle;
    PokemonFormatPolicy policy = *bundle.policy;
    policy.status_clauses = NULL;
    policy.status_clause_count = 0;
    bundle.policy = &policy;
    bundle.data = &data;
    init.bundle = &bundle;
    init.teams[1].members[0].ability_id = 99;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    PokemonBattle before = battle;
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_step(&battle, choices) == POKEMON_CAPACITY_EXCEEDED);
    assert(memcmp(&battle, &before, sizeof(battle)) == 0);

    battle = before;
    for (size_t i = 0; i < POKEMON_HANDLER_CAPACITY; i++) {
        battle.handlers[i] = (PokemonHandlerInvocation){
            .handler = {
                .descriptor = {.event = POKEMON_HANDLER_EVENT_UPDATE},
                .holder_side = 0, .holder_slot = 0,
            },
            .semantic_sequence = (uint32_t)(i + 1),
            .invoked = 1,
            .result = POKEMON_HANDLER_CONTINUE,
        };
    }
    battle.handler_count = POKEMON_HANDLER_CAPACITY - 1;
    battle.semantic_sequence = POKEMON_HANDLER_CAPACITY - 1;
    assert(pokemon_battle_check_invariants(&battle));
    battle.handler_count = POKEMON_HANDLER_CAPACITY;
    battle.semantic_sequence = POKEMON_HANDLER_CAPACITY;
    assert(pokemon_battle_check_invariants(&battle));
    battle.handler_count = POKEMON_HANDLER_CAPACITY + 1;
    assert(!pokemon_battle_check_invariants(&battle));
    battle = before;
    battle.immunity_count = POKEMON_IMMUNITY_CAPACITY + 1;
    assert(!pokemon_battle_check_invariants(&battle));
}

static PokemonBattleInit modifier_init(
    uint16_t ability, uint16_t item, PokemonStatus status
) {
    PokemonBattleInit init = battle_init();
    init.teams[0].members[0] = make_set(
        POKEMON_GEN3_SPECIES_MACHOP, POKEMON_GEN3_MOVE_MACHPUNCH,
        500, 100, 100, 100, 100, 100
    );
    init.teams[0].members[0].ability_id = ability;
    init.teams[0].members[0].item_id = item;
    init.initial_status[0][0] = (uint8_t)status;
    init.teams[1].members[0] = make_set(
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SCRATCH,
        500, 100, 100, 100, 100, 200
    );
    return init;
}

static uint16_t first_damage(const PokemonBattle *battle) {
    for (size_t i = 0; i < battle->event_count; i++) {
        if (battle->events[i].kind == POKEMON_EVENT_DAMAGE) {
            return battle->events[i].amount;
        }
    }
    assert(0);
    return 0;
}

static uint16_t run_modifier_case(
    uint16_t ability, uint16_t item, PokemonStatus status,
    PokemonBattle *battle
) {
    PokemonBattleInit init = modifier_init(ability, item, status);
    assert(pokemon_battle_init(battle, &init) == POKEMON_OK);
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_step(battle, choices) == POKEMON_OK);
    return first_damage(battle);
}

static void test_modify_atk_relay_and_burn_stage(void) {
    PokemonBattle plain;
    PokemonBattle burned;
    PokemonBattle guts;
    PokemonBattle belt;
    PokemonBattle combined;
    uint16_t plain_damage = run_modifier_case(
        POKEMON_GEN3_ABILITY_ROCKHEAD, 0, POKEMON_STATUS_NONE, &plain
    );
    uint16_t burned_damage = run_modifier_case(
        POKEMON_GEN3_ABILITY_ROCKHEAD, 0, POKEMON_STATUS_BURN, &burned
    );
    uint16_t guts_damage = run_modifier_case(
        POKEMON_GEN3_ABILITY_GUTS, 0, POKEMON_STATUS_BURN, &guts
    );
    uint16_t belt_damage = run_modifier_case(
        POKEMON_GEN3_ABILITY_ROCKHEAD, POKEMON_GEN3_ITEM_BLACKBELT,
        POKEMON_STATUS_NONE, &belt
    );
    uint16_t combined_damage = run_modifier_case(
        POKEMON_GEN3_ABILITY_GUTS, POKEMON_GEN3_ITEM_BLACKBELT,
        POKEMON_STATUS_BURN, &combined
    );
    assert(burned_damage < plain_damage);
    assert(belt_damage > plain_damage);
    assert(guts_damage > belt_damage);
    assert(combined_damage > guts_damage);

    /* A relay event has a result even when discovery finds no handlers. */
    assert(plain.modifier_count == 0);
    assert(plain.relay_result_count == 2);
    assert(plain.relay_results[0].event == POKEMON_HANDLER_EVENT_MODIFY_ATK);
    assert(plain.relay_results[0].holder_side == 0);
    assert(plain.relay_results[0].holder_slot == 0);
    assert(plain.relay_results[0].input == 100);
    assert(plain.relay_results[0].modifier_q12 == 4096);
    assert(plain.relay_results[0].output == 100);
    assert(plain.relay_results[0].semantic_sequence == 1);
    assert(plain.damage_stages[0].semantic_sequence == 2);
    assert(plain.relay_results[1].semantic_sequence == 3);
    /* The defender's Rock Head callback is discovered for ordinary Damage
     * and declines it through its generated recoil-kind guard. */
    assert(plain.handler_count == 1);
    assert(plain.handlers[0].handler.descriptor.id ==
        POKEMON_GEN3_HANDLER_ROCK_HEAD);
    assert(plain.handlers[0].handler.descriptor.event ==
        POKEMON_HANDLER_EVENT_DAMAGE);
    assert(plain.handlers[0].handler.holder_side == 0);
    assert(plain.handlers[0].semantic_sequence == 5);
    assert(plain.handlers[0].invoked);
    assert(plain.handlers[0].result == POKEMON_HANDLER_CONTINUE);
    assert(plain.damage_stages[1].semantic_sequence == 4);
    assert(plain.semantic_sequence == 5);

    assert(guts.modifier_count == 1);
    assert(guts.modifiers[0].handler.descriptor.id == POKEMON_GEN3_HANDLER_GUTS);
    assert(guts.modifiers[0].modifier_before_q12 == 4096);
    assert(guts.modifiers[0].modifier_q12 == 6144);
    assert(guts.modifiers[0].modifier_after_q12 == 6144);
    assert(guts.modifiers[0].input == 100);
    assert(guts.modifiers[0].output == 150);
    assert(guts.damage_stages[0].reason == POKEMON_BURN_GUTS);
    assert(!guts.damage_stages[0].applied);

    assert(combined.modifier_count == 2);
    assert(combined.modifiers[0].handler.descriptor.id == POKEMON_GEN3_HANDLER_GUTS);
    assert(combined.modifiers[1].handler.descriptor.id == POKEMON_GEN3_HANDLER_BLACK_BELT);
    assert(combined.modifiers[1].modifier_before_q12 == 6144);
    assert(combined.modifiers[1].modifier_q12 == 4505);
    assert(combined.modifiers[1].modifier_after_q12 == 6758);
    assert(combined.modifiers[1].output == 165);
    assert(combined.modifiers[0].semantic_sequence == 1);
    assert(combined.modifiers[1].semantic_sequence == 2);
    assert(combined.relay_result_count == 2);
    assert(combined.relay_results[0].input == 100);
    assert(combined.relay_results[0].modifier_q12 == 6758);
    assert(combined.relay_results[0].output == 165);
    assert(combined.relay_results[0].semantic_sequence == 3);
    assert(combined.damage_stages[0].semantic_sequence == 4);
    assert(combined.relay_results[1].semantic_sequence == 5);
    assert(combined.damage_stages[1].semantic_sequence == 6);
    assert(combined.semantic_sequence == 8);
    assert(combined.residual_count == 1);
    assert(combined.residuals[0].condition_id == POKEMON_STATUS_BURN);
    assert(combined.residuals[0].semantic_sequence == 7);
    assert(burned.damage_stages[0].reason == POKEMON_BURN_APPLIED);
    assert(burned.damage_stages[0].applied);
    assert(burned.damage_stages[0].output < burned.damage_stages[0].input);

    PokemonBattleView view;
    pokemon_battle_view(&combined, &view);
    assert(view.modifier_count == combined.modifier_count);
    assert(view.relay_result_count == combined.relay_result_count);
    assert(view.damage_stage_count == combined.damage_stage_count);
    assert(view.semantic_sequence == combined.semantic_sequence);
    assert(memcmp(view.modifiers, combined.modifiers, sizeof(view.modifiers)) == 0);
    assert(memcmp(view.relay_results, combined.relay_results,
        sizeof(view.relay_results)) == 0);
    assert(memcmp(view.damage_stages, combined.damage_stages,
        sizeof(view.damage_stages)) == 0);
}

static const PokemonMoveData *generated_move(uint16_t id) {
    for (size_t i = 0; i < POKEMON_GEN3_SLICE_DATA.move_count; i++) {
        if (POKEMON_GEN3_SLICE_DATA.moves[i].id == id) {
            return &POKEMON_GEN3_SLICE_DATA.moves[i];
        }
    }
    assert(0 && "generated move exists");
    return NULL;
}

static PokemonEventFrame run_scalar_event(
    PokemonBattle *battle, PokemonEventId event, const PokemonMoveData *move_data,
    PokemonRelay relay
) {
    PokemonEventFrame frame;
    int status = pokemon_run_event(battle, &(PokemonEventInput){
        .event = event,
        .source = {POKEMON_ENTITY_POKEMON, 0, 0},
        .target_side = event == POKEMON_HANDLER_EVENT_MODIFY_ACCURACY ? 1 : 0,
        .target_slot = 0,
        .context_kind = POKEMON_EVENT_CONTEXT_MOVE,
        .context.move = {.move = move_data},
        .relay = relay,
    }, &frame);
    assert(status == POKEMON_OK);
    return frame;
}

static void test_guts_major_status_evidence_rotation(void) {
    static const PokemonStatus statuses[] = {
        POKEMON_STATUS_BURN, POKEMON_STATUS_POISON, POKEMON_STATUS_TOXIC,
        POKEMON_STATUS_PARALYSIS, POKEMON_STATUS_FREEZE, POKEMON_STATUS_SLEEP,
    };
    const PokemonMoveData *physical = generated_move(POKEMON_GEN3_MOVE_MACHPUNCH);
    const PokemonMoveData *special = generated_move(POKEMON_GEN3_MOVE_EMBER);
    for (size_t i = 0; i < sizeof(statuses) / sizeof(statuses[0]); i++) {
        PokemonBattleInit init = modifier_init(
            POKEMON_GEN3_ABILITY_GUTS, 0, statuses[i]);
        if (statuses[i] == POKEMON_STATUS_SLEEP) {
            init.initial_sleep_time[0][0] = 2;
        }
        PokemonBattle battle;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        PokemonEventFrame attack = run_scalar_event(
            &battle, POKEMON_HANDLER_EVENT_MODIFY_ATK, physical,
            (PokemonRelay){.kind = POKEMON_RELAY_U32, .value.u32 = 100});
        assert(attack.relay.value.u32 == 150);
        assert(battle.modifier_count == 1);
        assert(battle.modifiers[0].handler.descriptor.id ==
            POKEMON_GEN3_HANDLER_GUTS);
        assert(battle.modifiers[0].modifier_before_q12 == 4096);
        assert(battle.modifiers[0].modifier_after_q12 == 6144);
        PokemonEventFrame special_attack = run_scalar_event(
            &battle, POKEMON_HANDLER_EVENT_MODIFY_SPA, special,
            (PokemonRelay){.kind = POKEMON_RELAY_U32, .value.u32 = 100});
        assert(special_attack.relay.value.u32 == 100);
        assert(battle.modifier_count == 1);
    }

    PokemonBattleInit init = modifier_init(
        POKEMON_GEN3_ABILITY_GUTS, POKEMON_GEN3_ITEM_BLACKBELT,
        POKEMON_STATUS_POISON);
    PokemonBattle combined;
    assert(pokemon_battle_init(&combined, &init) == POKEMON_OK);
    PokemonEventFrame attack = run_scalar_event(
        &combined, POKEMON_HANDLER_EVENT_MODIFY_ATK, physical,
        (PokemonRelay){.kind = POKEMON_RELAY_U32, .value.u32 = 100});
    assert(attack.relay.value.u32 == 165);
    assert(combined.modifier_count == 2);
    assert(combined.modifiers[0].handler.descriptor.id ==
        POKEMON_GEN3_HANDLER_GUTS);
    assert(combined.modifiers[1].handler.descriptor.id ==
        POKEMON_GEN3_HANDLER_BLACK_BELT);
    assert(combined.modifiers[1].modifier_before_q12 == 6144);
    assert(combined.modifiers[1].modifier_after_q12 == 6758);
}

static void test_generated_scalar_owner_handlers(void) {
    const PokemonMoveData *strength = generated_move(POKEMON_GEN3_MOVE_STRENGTH);
    const PokemonMoveData *supersonic = generated_move(POKEMON_GEN3_MOVE_SUPERSONIC);
    PokemonBattle battle;
    PokemonEventFrame frame;

    const PokemonStatus statuses[] = {
        POKEMON_STATUS_BURN, POKEMON_STATUS_PARALYSIS, POKEMON_STATUS_POISON,
        POKEMON_STATUS_TOXIC, POKEMON_STATUS_SLEEP, POKEMON_STATUS_FREEZE,
    };
    for (size_t i = 0; i < sizeof(statuses) / sizeof(statuses[0]); i++) {
        PokemonBattleInit init = modifier_init(
            POKEMON_GEN3_ABILITY_GUTS, 0, POKEMON_STATUS_NONE);
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        battle.sides[0].state[0].status.kind = statuses[i];
        frame = run_scalar_event(&battle, POKEMON_HANDLER_EVENT_MODIFY_ATK,
            strength, (PokemonRelay){.kind = POKEMON_RELAY_U32,
                .value.u32 = 101});
        assert(frame.relay.value.u32 == 151);
        assert(frame.modifier_q12 == 6144);
    }

    const uint16_t doubles[] = {
        POKEMON_GEN3_ABILITY_HUGEPOWER, POKEMON_GEN3_ABILITY_PUREPOWER,
    };
    for (size_t i = 0; i < sizeof(doubles) / sizeof(doubles[0]); i++) {
        PokemonBattleInit init = modifier_init(
            doubles[i], 0, POKEMON_STATUS_NONE);
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        frame = run_scalar_event(&battle, POKEMON_HANDLER_EVENT_MODIFY_ATK,
            strength, (PokemonRelay){.kind = POKEMON_RELAY_U32,
                .value.u32 = 101});
        assert(frame.relay.value.u32 == 202);
        assert(frame.modifier_q12 == 8192);
    }

    /* Hustle returns a rounded relay immediately.  The later item callback
     * chains onto that 151, yielding 166 rather than the all-chained 167. */
    PokemonBattleInit hustle = modifier_init(
        POKEMON_GEN3_ABILITY_HUSTLE, POKEMON_GEN3_ITEM_SILKSCARF,
        POKEMON_STATUS_NONE);
    assert(pokemon_battle_init(&battle, &hustle) == POKEMON_OK);
    frame = run_scalar_event(&battle, POKEMON_HANDLER_EVENT_MODIFY_ATK,
        strength, (PokemonRelay){.kind = POKEMON_RELAY_U32, .value.u32 = 101});
    assert(frame.relay.value.u32 == 166);
    assert(frame.modifier_q12 == 4505);
    assert(battle.modifier_count == 2);
    assert(battle.modifiers[0].handler.descriptor.id ==
        POKEMON_GEN3_HANDLER_HUSTLE_ATTACK);
    assert(battle.modifiers[0].input == 101);
    assert(battle.modifiers[1].handler.descriptor.id ==
        POKEMON_GEN3_HANDLER_SILKSCARF);
    assert(battle.modifiers[1].input == 151);

    PokemonBattleInit eyes = modifier_init(
        POKEMON_GEN3_ABILITY_COMPOUNDEYES, 0, POKEMON_STATUS_NONE);
    assert(pokemon_battle_init(&battle, &eyes) == POKEMON_OK);
    frame = run_scalar_event(&battle, POKEMON_HANDLER_EVENT_MODIFY_ACCURACY,
        supersonic, (PokemonRelay){.kind = POKEMON_RELAY_NUMBER,
            .value.number = 55});
    assert(frame.relay.value.number == 71);
    assert(frame.modifier_q12 == 5324);
    frame = run_scalar_event(&battle, POKEMON_HANDLER_EVENT_MODIFY_ACCURACY,
        supersonic, (PokemonRelay){.kind = POKEMON_RELAY_NUMBER,
            .value.number = 75});
    /* Resolved Gen 3 inherits the Gen 4 floating 1.3 callback, which truncates
     * to Q12 5324 and produces 97. Current-generation source uses 5325/4096. */
    assert(frame.relay.value.number == 97);
    assert(frame.modifier_q12 == 5324);
    /* Showdown only applies an accumulated modifier to integral numeric
     * relays; the callback still runs and records its Q12 state. */
    frame = run_scalar_event(&battle, POKEMON_HANDLER_EVENT_MODIFY_ACCURACY,
        supersonic, (PokemonRelay){.kind = POKEMON_RELAY_NUMBER,
            .value.number = 63.75});
    assert(frame.relay.value.number == 63.75);
    assert(frame.modifier_q12 == 5324);
    frame = run_scalar_event(&battle, POKEMON_HANDLER_EVENT_MODIFY_ACCURACY,
        supersonic, (PokemonRelay){.kind = POKEMON_RELAY_BOOLEAN,
            .value.boolean = 1});
    assert(frame.relay.kind == POKEMON_RELAY_BOOLEAN &&
        frame.relay.value.boolean == 1 && frame.modifier_q12 == 4096);

    PokemonBattleInit club = modifier_init(
        POKEMON_GEN3_ABILITY_ROCKHEAD, POKEMON_GEN3_ITEM_THICKCLUB,
        POKEMON_STATUS_NONE);
    club.teams[0].members[0].species_id = POKEMON_GEN3_SPECIES_MAROWAK;
    assert(pokemon_battle_init(&battle, &club) == POKEMON_OK);
    frame = run_scalar_event(&battle, POKEMON_HANDLER_EVENT_MODIFY_ATK,
        strength, (PokemonRelay){.kind = POKEMON_RELAY_U32, .value.u32 = 101});
    assert(frame.relay.value.u32 == 202);
    club.teams[0].members[0].species_id = POKEMON_GEN3_SPECIES_PERSIAN;
    assert(pokemon_battle_init(&battle, &club) == POKEMON_OK);
    frame = run_scalar_event(&battle, POKEMON_HANDLER_EVENT_MODIFY_ATK,
        strength, (PokemonRelay){.kind = POKEMON_RELAY_U32, .value.u32 = 101});
    assert(frame.relay.value.u32 == 101);
}

static void test_relational_active_ability_modifier(void) {
    const PokemonMoveData *surf = generated_move(POKEMON_GEN3_MOVE_SURF);
    PokemonBattle battle;
    PokemonEventFrame frame;

    PokemonBattleInit init = modifier_init(
        POKEMON_GEN3_ABILITY_PLUS, 0, POKEMON_STATUS_NONE);
    init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_MINUS;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    frame = run_scalar_event(&battle, POKEMON_HANDLER_EVENT_MODIFY_SPA,
        surf, (PokemonRelay){.kind = POKEMON_RELAY_U32, .value.u32 = 100});
    assert(frame.relay.value.u32 == 150 && frame.modifier_q12 == 6144);
    assert(battle.modifier_count == 1);
    assert(battle.modifiers[0].handler.descriptor.id ==
        POKEMON_GEN3_HANDLER_PLUS_MODIFY_SPA);

    init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_PLUS;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    frame = run_scalar_event(&battle, POKEMON_HANDLER_EVENT_MODIFY_SPA,
        surf, (PokemonRelay){.kind = POKEMON_RELAY_U32, .value.u32 = 100});
    assert(frame.relay.value.u32 == 100 && frame.modifier_q12 == 4096);

    init.teams[0].members[0].ability_id = POKEMON_GEN3_ABILITY_MINUS;
    init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_PLUS;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    frame = run_scalar_event(&battle, POKEMON_HANDLER_EVENT_MODIFY_SPA,
        surf, (PokemonRelay){.kind = POKEMON_RELAY_U32, .value.u32 = 101});
    assert(frame.relay.value.u32 == 151 && frame.modifier_q12 == 6144);
    battle.sides[1].state[0].hp = 0;
    battle.sides[1].state[0].fainted = 1;
    battle.modifier_count = 0;
    battle.relay_result_count = 0;
    frame = run_scalar_event(&battle, POKEMON_HANDLER_EVENT_MODIFY_SPA,
        surf, (PokemonRelay){.kind = POKEMON_RELAY_U32, .value.u32 = 101});
    assert(frame.relay.value.u32 == 101 && frame.modifier_q12 == 4096);
}

static void test_generated_species_stat_item_handlers(void) {
    const PokemonMoveData *surf = generated_move(POKEMON_GEN3_MOVE_SURF);
    PokemonBattle battle;
    PokemonEventFrame frame;

    PokemonBattleInit init = modifier_init(
        POKEMON_GEN3_ABILITY_SHELLARMOR, POKEMON_GEN3_ITEM_DEEPSEATOOTH,
        POKEMON_STATUS_NONE);
    init.teams[0].members[0].species_id = POKEMON_GEN3_SPECIES_CLAMPERL;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    frame = run_scalar_event(&battle, POKEMON_HANDLER_EVENT_MODIFY_SPA, surf,
        (PokemonRelay){.kind = POKEMON_RELAY_U32, .value.u32 = 101});
    assert(frame.relay.value.u32 == 202 && frame.modifier_q12 == 8192);
    assert(battle.modifier_count == 1);
    assert(battle.modifiers[0].handler.descriptor.id ==
        POKEMON_GEN3_HANDLER_DEEP_SEA_TOOTH_SPA);

    init.teams[0].members[0].species_id = POKEMON_GEN3_SPECIES_VAPOREON;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    frame = run_scalar_event(&battle, POKEMON_HANDLER_EVENT_MODIFY_SPA, surf,
        (PokemonRelay){.kind = POKEMON_RELAY_U32, .value.u32 = 101});
    assert(frame.relay.value.u32 == 101 && frame.modifier_q12 == 4096);

    init.teams[0].members[0].species_id = POKEMON_GEN3_SPECIES_CLAMPERL;
    init.teams[0].members[0].item_id = POKEMON_GEN3_ITEM_DEEPSEASCALE;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    frame = run_scalar_event(&battle, POKEMON_HANDLER_EVENT_MODIFY_SPD, surf,
        (PokemonRelay){.kind = POKEMON_RELAY_U32, .value.u32 = 101});
    assert(frame.relay.value.u32 == 202 && frame.modifier_q12 == 8192);
    assert(battle.modifiers[0].handler.descriptor.id ==
        POKEMON_GEN3_HANDLER_DEEP_SEA_SCALE_SPD);

    init.teams[0].members[0].species_id = POKEMON_GEN3_SPECIES_PIKACHU;
    init.teams[0].members[0].item_id = POKEMON_GEN3_ITEM_LIGHTBALL;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    frame = run_scalar_event(&battle, POKEMON_HANDLER_EVENT_MODIFY_SPA, surf,
        (PokemonRelay){.kind = POKEMON_RELAY_U32, .value.u32 = 101});
    assert(frame.relay.value.u32 == 202 && frame.modifier_q12 == 8192);

    init.teams[0].members[0].species_id = POKEMON_GEN3_SPECIES_PERSIAN;
    init.teams[0].members[0].item_id = POKEMON_GEN3_ITEM_MACHOBRACE;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    frame = run_scalar_event(&battle, POKEMON_HANDLER_EVENT_MODIFY_SPE, surf,
        (PokemonRelay){.kind = POKEMON_RELAY_U32, .value.u32 = 101});
    assert(frame.relay.value.u32 == 50 && frame.modifier_q12 == 2048);

    init = modifier_init(
        POKEMON_GEN3_ABILITY_LIMBER, POKEMON_GEN3_ITEM_METALPOWDER,
        POKEMON_STATUS_NONE);
    init.teams[0].members[0].species_id = POKEMON_GEN3_SPECIES_DITTO;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    frame = run_scalar_event(&battle, POKEMON_HANDLER_EVENT_MODIFY_DEF, surf,
        (PokemonRelay){.kind = POKEMON_RELAY_U32, .value.u32 = 101});
    assert(frame.relay.value.u32 == 202 && frame.modifier_q12 == 8192);
    assert(battle.modifier_count == 1);
    assert(battle.modifiers[0].handler.descriptor.id ==
        POKEMON_GEN3_HANDLER_METAL_POWDER_MODIFY_DEF);
    assert(battle.modifiers[0].handler.descriptor.priority == 2);

    init.teams[0].members[0].species_id = POKEMON_GEN3_SPECIES_PERSIAN;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    frame = run_scalar_event(&battle, POKEMON_HANDLER_EVENT_MODIFY_DEF, surf,
        (PokemonRelay){.kind = POKEMON_RELAY_U32, .value.u32 = 101});
    assert(frame.relay.value.u32 == 101 && frame.modifier_q12 == 4096);

    /* The resolved OU bundle retains both observable Soul Dew callbacks, but
     * specializes their Lati-only positive branches to undefined. */
    init.teams[0].members[0].species_id = POKEMON_GEN3_SPECIES_SMEARGLE;
    init.teams[0].members[0].item_id = POKEMON_GEN3_ITEM_SOULDEW;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    frame = run_scalar_event(&battle, POKEMON_HANDLER_EVENT_MODIFY_SPA, surf,
        (PokemonRelay){.kind = POKEMON_RELAY_U32, .value.u32 = 101});
    assert(frame.relay.value.u32 == 101 && frame.modifier_q12 == 4096);
    assert(battle.modifier_count == 1);
    assert(battle.modifiers[0].handler.descriptor.id ==
        POKEMON_GEN3_HANDLER_SOUL_DEW_SPA);
    assert(battle.modifiers[0].handler.descriptor.modifier_q12 == 6144);
    frame = run_scalar_event(&battle, POKEMON_HANDLER_EVENT_MODIFY_SPD, surf,
        (PokemonRelay){.kind = POKEMON_RELAY_U32, .value.u32 = 101});
    assert(frame.relay.value.u32 == 101 && frame.modifier_q12 == 4096);
    assert(battle.modifier_count == 2);
    assert(battle.modifiers[1].handler.descriptor.id ==
        POKEMON_GEN3_HANDLER_SOUL_DEW_SPD);

    /* Critical stage suppression does not suppress the later item-owned SpD
     * event.  This proves the real special-damage staging boundary. */
    PokemonBattleInit damage_init = condition_init(
        POKEMON_GEN3_SPECIES_VAPOREON, POKEMON_GEN3_MOVE_SURF,
        POKEMON_GEN3_SPECIES_CLAMPERL, POKEMON_GEN3_MOVE_SPLASH);
    damage_init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_SHELLARMOR;
    damage_init.teams[1].members[0].item_id = POKEMON_GEN3_ITEM_DEEPSEASCALE;
    damage_init.teams[1].members[0].stats[4] = 101;
    assert(pokemon_battle_init(&battle, &damage_init) == POKEMON_OK);
    battle.sides[1].state[0].boosts[POKEMON_STAT_SPD] = 6;
    PokemonDamageRequest request = {
        .mode = POKEMON_DAMAGE_MODE_ORDINARY_MOVE,
        .source = {POKEMON_ENTITY_POKEMON, 0, 0},
        .target = {POKEMON_ENTITY_POKEMON, 1, 0},
        .move = surf, .critical = 1,
    };
    PokemonCalculatedDamage damage;
    assert(pokemon_calculate_damage(&battle, &request, &damage) == POKEMON_OK);
    const PokemonRelayResult *spd_result = NULL;
    for (size_t i = 0; i < battle.relay_result_count; i++) {
        if (battle.relay_results[i].event == POKEMON_HANDLER_EVENT_MODIFY_SPD) {
            spd_result = &battle.relay_results[i];
        }
    }
    assert(spd_result != NULL);
    assert(spd_result->input == 101 && spd_result->output == 202);
    assert(pokemon_battle_check_invariants(&battle));
}

static void test_starter_ability_base_power_family(void) {
    static const struct {
        uint16_t ability;
        uint8_t type;
        uint16_t handler;
    } cases[] = {
        {POKEMON_GEN3_ABILITY_BLAZE, POKEMON_GEN3_TYPE_FIRE,
            POKEMON_GEN3_HANDLER_BLAZE_BASE_POWER},
        {POKEMON_GEN3_ABILITY_OVERGROW, POKEMON_GEN3_TYPE_GRASS,
            POKEMON_GEN3_HANDLER_OVERGROW_BASE_POWER},
        {POKEMON_GEN3_ABILITY_SWARM, POKEMON_GEN3_TYPE_BUG,
            POKEMON_GEN3_HANDLER_SWARM_BASE_POWER},
        {POKEMON_GEN3_ABILITY_TORRENT, POKEMON_GEN3_TYPE_WATER,
            POKEMON_GEN3_HANDLER_TORRENT_BASE_POWER},
    };

    for (size_t i = 0; i < sizeof(cases) / sizeof(cases[0]); i++) {
        PokemonBattleInit init = modifier_init(
            cases[i].ability, 0, POKEMON_STATUS_NONE);
        PokemonMoveData matching = {
            .id = POKEMON_GEN3_MOVE_TACKLE,
            .type = cases[i].type,
            .category = POKEMON_CATEGORY_PHYSICAL,
        };
        PokemonBattle battle;
        PokemonEventFrame frame;

        /* modifier_init gives the holder 500 max HP, so the exact integer
         * one-third boundary is 166. */
        init.initial_hp[0][0] = 166;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        frame = run_scalar_event(&battle, POKEMON_HANDLER_EVENT_BASE_POWER,
            &matching, (PokemonRelay){.kind = POKEMON_RELAY_U32,
                .value.u32 = 101});
        assert(frame.relay.value.u32 == 151);
        assert(frame.modifier_q12 == 6144);
        assert(frame.executed_count == 1 && frame.skipped_count == 0);
        assert(battle.modifier_count == 1);
        assert(battle.modifiers[0].handler.descriptor.id == cases[i].handler);
        assert(battle.modifiers[0].input == 101);
        assert(battle.modifiers[0].output == 151);

        init.initial_hp[0][0] = 167;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        frame = run_scalar_event(&battle, POKEMON_HANDLER_EVENT_BASE_POWER,
            &matching, (PokemonRelay){.kind = POKEMON_RELAY_U32,
                .value.u32 = 101});
        assert(frame.relay.value.u32 == 101);
        assert(frame.modifier_q12 == 4096);
        assert(frame.executed_count == 1 && frame.skipped_count == 0);
        assert(battle.modifier_count == 1);
        assert(battle.modifiers[0].modifier_q12 == 4096);

        init.initial_hp[0][0] = 166;
        matching.type = cases[i].type == POKEMON_GEN3_TYPE_NORMAL ?
            POKEMON_GEN3_TYPE_FIRE : POKEMON_GEN3_TYPE_NORMAL;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        frame = run_scalar_event(&battle, POKEMON_HANDLER_EVENT_BASE_POWER,
            &matching, (PokemonRelay){.kind = POKEMON_RELAY_U32,
                .value.u32 = 101});
        assert(frame.relay.value.u32 == 101);
        assert(frame.modifier_q12 == 4096);
        assert(frame.executed_count == 1 && frame.skipped_count == 0);
        assert(battle.modifier_count == 1);
        assert(battle.modifiers[0].modifier_q12 == 4096);
    }
}

static void test_sport_ambient_base_power_family(void) {
    static const struct {
        uint16_t move_id;
        PokemonVolatileKind volatile_kind;
        uint8_t affected_type;
        uint16_t handler_id;
    } cases[] = {
        {POKEMON_GEN3_MOVE_MUDSPORT, POKEMON_VOLATILE_MUD_SPORT,
            POKEMON_GEN3_TYPE_ELECTRIC,
            POKEMON_GEN3_HANDLER_MUD_SPORT_ANY_BASE_POWER},
        {POKEMON_GEN3_MOVE_WATERSPORT, POKEMON_VOLATILE_WATER_SPORT,
            POKEMON_GEN3_TYPE_FIRE,
            POKEMON_GEN3_HANDLER_WATER_SPORT_ANY_BASE_POWER},
    };
    const PokemonChoice moves[POKEMON_SIDES] = {move(0), move(0)};

    for (size_t i = 0; i < sizeof(cases) / sizeof(cases[0]); i++) {
        PokemonBattleInit init = condition_init(
            POKEMON_GEN3_SPECIES_SMEARGLE, cases[i].move_id,
            POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_SPLASH);
        PokemonBattle battle;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        assert(pokemon_battle_step(&battle, moves) == POKEMON_OK);
        assert(test_volatile_index(&battle.sides[0].state[0],
            cases[i].volatile_kind) >= 0);

        PokemonMoveData affected = {
            .id = POKEMON_GEN3_MOVE_TACKLE,
            .type = cases[i].affected_type,
            .category = POKEMON_CATEGORY_SPECIAL,
        };
        PokemonEventFrame frame = run_scalar_event(&battle,
            POKEMON_HANDLER_EVENT_BASE_POWER, &affected,
            (PokemonRelay){.kind = POKEMON_RELAY_U32, .value.u32 = 101});
        assert(frame.relay.value.u32 == 50 && frame.modifier_q12 == 2048);
        assert(frame.executed_count == 1 && frame.skipped_count == 0);
        assert(battle.modifiers[battle.modifier_count - 1]
            .handler.descriptor.id == cases[i].handler_id);

        affected.type = POKEMON_GEN3_TYPE_NORMAL;
        frame = run_scalar_event(&battle, POKEMON_HANDLER_EVENT_BASE_POWER,
            &affected,
            (PokemonRelay){.kind = POKEMON_RELAY_U32, .value.u32 = 101});
        assert(frame.relay.value.u32 == 101 && frame.modifier_q12 == 4096);
        assert(frame.executed_count == 1 && frame.skipped_count == 0);

        PokemonChoice switch_out[POKEMON_SIDES] = {switch_to(1), move(0)};
        assert(pokemon_battle_step(&battle, switch_out) == POKEMON_OK);
        assert(test_volatile_index(&battle.sides[0].state[0],
            cases[i].volatile_kind) < 0);
    }

    /* Any-scope discovery includes an opposing holder. */
    PokemonBattleInit opposing = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_SPLASH,
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_MUDSPORT);
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &opposing) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, moves) == POKEMON_OK);
    PokemonMoveData electric = {
        .id = POKEMON_GEN3_MOVE_TACKLE,
        .type = POKEMON_GEN3_TYPE_ELECTRIC,
        .category = POKEMON_CATEGORY_SPECIAL,
    };
    PokemonEventFrame frame = run_scalar_event(&battle,
        POKEMON_HANDLER_EVENT_BASE_POWER, &electric,
        (PokemonRelay){.kind = POKEMON_RELAY_U32, .value.u32 = 101});
    assert(frame.relay.value.u32 == 50 && frame.executed_count == 1);

    /* Independent holders compose through the ordinary modifier relay. */
    PokemonBattleInit doubled = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_MUDSPORT,
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_MUDSPORT);
    assert(pokemon_battle_init(&battle, &doubled) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, moves) == POKEMON_OK);
    frame = run_scalar_event(&battle, POKEMON_HANDLER_EVENT_BASE_POWER,
        &electric,
        (PokemonRelay){.kind = POKEMON_RELAY_U32, .value.u32 = 101});
    assert(frame.relay.value.u32 == 25 && frame.modifier_q12 == 1024);
    assert(frame.executed_count == 2 && frame.skipped_count == 0);
    assert(pokemon_battle_check_invariants(&battle));
}

static void test_holder_status_mask_base_power_predicate(void) {
    enum { TEST_FACADE_HANDLER = 65000 };
    static const PokemonHandlerOp program[] = {
        {POKEMON_HANDLER_OP_GUARD_HOLDER_STATUS_MASK,
            (UINT32_C(1) << POKEMON_STATUS_BURN) |
            (UINT32_C(1) << POKEMON_STATUS_TOXIC) |
            (UINT32_C(1) << POKEMON_STATUS_PARALYSIS) |
            (UINT32_C(1) << POKEMON_STATUS_POISON) |
            (UINT32_C(1) << POKEMON_STATUS_FREEZE)},
        {POKEMON_HANDLER_OP_CHAIN_Q12, 8192},
    };
    static const PokemonHandlerDescriptor handler = {
        .event = POKEMON_HANDLER_EVENT_BASE_POWER,
        .id = TEST_FACADE_HANDLER,
        .source_kind = POKEMON_HANDLER_SOURCE_MOVE,
        .source_id = POKEMON_GEN3_MOVE_STRENGTH,
        .program_offset = 0,
        .program_count = 2,
        .scope = POKEMON_HANDLER_SCOPE_SOURCE,
        .route = POKEMON_HANDLER_ROUTE_MOVE_SELF,
        .raw_hook = "onBasePower",
    };
    const PokemonStatus statuses[] = {
        POKEMON_STATUS_NONE, POKEMON_STATUS_BURN, POKEMON_STATUS_TOXIC,
        POKEMON_STATUS_PARALYSIS, POKEMON_STATUS_POISON, POKEMON_STATUS_SLEEP,
        POKEMON_STATUS_FREEZE,
    };
    for (size_t i = 0; i < sizeof(statuses) / sizeof(statuses[0]); i++) {
        PokemonBattleInit init = modifier_init(
            POKEMON_GEN3_ABILITY_ROCKHEAD, 0, POKEMON_STATUS_NONE);
        PokemonData data = *init.bundle->data;
        PokemonMoveData synthetic_moves[POKEMON_GEN3_MOVE_COUNT];
        remove_move_call_capability(&data, synthetic_moves);
        data.handlers = &handler;
        data.handler_count = 1;
        data.handler_programs = program;
        data.handler_program_count = 2;
        PokemonResolvedBundle bundle = *init.bundle;
        PokemonFormatPolicy policy = *bundle.policy;
        policy.status_clauses = NULL;
        policy.status_clause_count = 0;
        bundle.policy = &policy;
        bundle.data = &data;
        init.bundle = &bundle;
        PokemonBattle battle;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        battle.sides[0].state[0].status.kind = statuses[i];
        PokemonEventFrame frame;
        assert(pokemon_run_event(&battle, &(PokemonEventInput){
            .event = POKEMON_HANDLER_EVENT_BASE_POWER,
            .source = {POKEMON_ENTITY_POKEMON, 0, 0},
            .target_side = 1, .target_slot = 0,
            .context_kind = POKEMON_EVENT_CONTEXT_MOVE,
            .context.move = {
                .move = generated_move(POKEMON_GEN3_MOVE_STRENGTH)},
            .relay = {.kind = POKEMON_RELAY_U32, .value.u32 = 70},
            .include_move_self = 1,
        }, &frame) == POKEMON_OK);
        const int applies = statuses[i] != POKEMON_STATUS_NONE &&
            statuses[i] != POKEMON_STATUS_SLEEP;
        assert(frame.relay.value.u32 == (uint32_t)(applies ? 140 : 70));
        assert(frame.modifier_q12 == (uint16_t)(applies ? 8192 : 4096));
        assert(frame.executed_count == 1 && frame.skipped_count == 0);
        assert(battle.modifier_count == 1);
        assert(battle.modifiers[0].handler.descriptor.id ==
            TEST_FACADE_HANDLER);
    }

    PokemonHandlerOp invalid_program[] = {
        {POKEMON_HANDLER_OP_GUARD_HOLDER_STATUS_MASK, 0},
        {POKEMON_HANDLER_OP_CHAIN_Q12, 8192},
    };
    PokemonBattleInit init = modifier_init(
        POKEMON_GEN3_ABILITY_ROCKHEAD, 0, POKEMON_STATUS_NONE);
    PokemonData data = *init.bundle->data;
    PokemonMoveData synthetic_moves[POKEMON_GEN3_MOVE_COUNT];
    remove_move_call_capability(&data, synthetic_moves);
    data.handlers = &handler;
    data.handler_count = 1;
    data.handler_programs = invalid_program;
    data.handler_program_count = 2;
    PokemonResolvedBundle bundle = *init.bundle;
    PokemonFormatPolicy policy = *bundle.policy;
    policy.status_clauses = NULL;
    policy.status_clause_count = 0;
    bundle.policy = &policy;
    bundle.data = &data;
    init.bundle = &bundle;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    battle.sides[0].state[0].status.kind = POKEMON_STATUS_BURN;
    PokemonBattle before = battle;
    PokemonEventFrame frame;
    assert(pokemon_run_event(&battle, &(PokemonEventInput){
        .event = POKEMON_HANDLER_EVENT_BASE_POWER,
        .source = {POKEMON_ENTITY_POKEMON, 0, 0},
        .target_side = 0, .target_slot = 0,
        .context_kind = POKEMON_EVENT_CONTEXT_MOVE,
        .context.move = {.move = generated_move(POKEMON_GEN3_MOVE_STRENGTH)},
        .relay = {.kind = POKEMON_RELAY_U32, .value.u32 = 70},
        .include_move_self = 1,
    }, &frame) == POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&battle, &before, sizeof(battle)) == 0);
}

static void test_recent_damage_from_resolved_target_base_power_guard(void) {
    const PokemonData *generated = &POKEMON_GEN3_SLICE_DATA;
    size_t handler_index = SIZE_MAX;
    for (size_t i = 0; i < generated->handler_count; i++) {
        if (generated->handlers[i].id ==
                POKEMON_GEN3_HANDLER_REVENGE_BASE_POWER) {
            handler_index = i;
            break;
        }
    }
    assert(handler_index != SIZE_MAX);
    const PokemonHandlerDescriptor *handler =
        &generated->handlers[handler_index];
    assert(handler->event == POKEMON_HANDLER_EVENT_BASE_POWER);
    assert(handler->source_kind == POKEMON_HANDLER_SOURCE_MOVE);
    assert(handler->source_id == POKEMON_GEN3_MOVE_REVENGE);
    assert(handler->scope == POKEMON_HANDLER_SCOPE_SOURCE);
    assert(handler->route == POKEMON_HANDLER_ROUTE_MOVE_SELF);
    assert(handler->program_count == 2);
    assert(generated->handler_programs[handler->program_offset].opcode ==
        POKEMON_HANDLER_OP_GUARD_HOLDER_ATTACKED_BY_TARGET_THIS_TURN);
    assert(generated->handler_programs[handler->program_offset].argument == 0);
    assert(generated->handler_programs[handler->program_offset + 1].opcode ==
        POKEMON_HANDLER_OP_MULTIPLY_RELAY_U32);
    assert(generated->handler_programs[handler->program_offset + 1].argument ==
        2);

    const PokemonAttackRecord cases[] = {
        {0},
        {{POKEMON_ENTITY_POKEMON, 1, 0}, POKEMON_GEN3_MOVE_TACKLE,
            0, 1, 1, 1},
        {{POKEMON_ENTITY_POKEMON, 1, 0}, POKEMON_GEN3_MOVE_TACKLE,
            20, 1, 0, 1},
        {{POKEMON_ENTITY_POKEMON, 1, 1}, POKEMON_GEN3_MOVE_TACKLE,
            20, 1, 1, 1},
        {{POKEMON_ENTITY_POKEMON, 1, 0}, POKEMON_GEN3_MOVE_TACKLE,
            20, 0, 1, 1},
        {{POKEMON_ENTITY_POKEMON, 1, 0}, POKEMON_GEN3_MOVE_DRAGONRAGE,
            40, 1, 1, 1},
    };
    for (size_t i = 0; i < sizeof(cases) / sizeof(cases[0]); i++) {
        PokemonBattleInit init = condition_init(
            POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_REVENGE,
            POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_SPLASH);
        PokemonBattle battle;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        battle.sides[0].state[0].last_attacked_by = cases[i];
        battle.move_frame_depth = 1;
        battle.move_frames[0] = (PokemonActiveMoveFrame){
            .invocation = {
                .move_id = POKEMON_GEN3_MOVE_REVENGE,
                .user = {POKEMON_ENTITY_POKEMON, 0, 0},
            },
            .resolved_target = {POKEMON_ENTITY_POKEMON, 1, 0},
        };
        PokemonEventFrame frame;
        assert(pokemon_run_event(&battle, &(PokemonEventInput){
            .event = POKEMON_HANDLER_EVENT_BASE_POWER,
            .source = {POKEMON_ENTITY_POKEMON, 0, 0},
            .target_side = 0, .target_slot = 0,
            .context_kind = POKEMON_EVENT_CONTEXT_MOVE,
            .context.move = {.move = generated_move(POKEMON_GEN3_MOVE_REVENGE)},
            .relay = {.kind = POKEMON_RELAY_U32, .value.u32 = 60},
            .include_move_self = 1,
        }, &frame) == POKEMON_OK);
        const int doubles = i == sizeof(cases) / sizeof(cases[0]) - 1;
        assert(frame.relay.value.u32 == (uint32_t)(doubles ? 120 : 60));
        assert(frame.modifier_q12 == 4096);
        assert(frame.executed_count == 1 && frame.skipped_count == 0);
        assert(battle.modifier_count == 1);
        assert(battle.modifiers[0].handler.descriptor.id ==
            POKEMON_GEN3_HANDLER_REVENGE_BASE_POWER);
        battle.move_frame_depth = 0;
        assert(pokemon_battle_check_invariants(&battle));
    }

    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_REVENGE,
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_SPLASH);
    PokemonHandlerOp programs[generated->handler_program_count];
    memcpy(programs, generated->handler_programs, sizeof(programs));
    programs[handler->program_offset].argument = 1;
    PokemonData invalid_data = *generated;
    invalid_data.handler_programs = programs;
    assert_invalid_resolved_data_is_atomic(init, &invalid_data);

    memcpy(programs, generated->handler_programs, sizeof(programs));
    programs[handler->program_offset + 1].argument = 1;
    invalid_data = *generated;
    invalid_data.handler_programs = programs;
    assert_invalid_resolved_data_is_atomic(init, &invalid_data);

    PokemonHandlerDescriptor handlers[generated->handler_count];
    memcpy(handlers, generated->handlers, sizeof(handlers));
    handlers[handler_index].event = POKEMON_HANDLER_EVENT_MODIFY_ATK;
    invalid_data = *generated;
    invalid_data.handlers = handlers;
    assert_invalid_resolved_data_is_atomic(init, &invalid_data);

    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    battle.move_frame_depth = 1;
    battle.move_frames[0] = (PokemonActiveMoveFrame){
        .invocation = {
            .move_id = POKEMON_GEN3_MOVE_REVENGE,
            .user = {POKEMON_ENTITY_POKEMON, 1, 0},
        },
        .resolved_target = {POKEMON_ENTITY_POKEMON, 1, 0},
    };
    PokemonBattle before = battle;
    PokemonEventFrame frame;
    assert(pokemon_run_event(&battle, &(PokemonEventInput){
        .event = POKEMON_HANDLER_EVENT_BASE_POWER,
        .source = {POKEMON_ENTITY_POKEMON, 0, 0},
        .target_side = 0, .target_slot = 0,
        .context_kind = POKEMON_EVENT_CONTEXT_MOVE,
        .context.move = {.move = generated_move(POKEMON_GEN3_MOVE_REVENGE)},
        .relay = {.kind = POKEMON_RELAY_U32, .value.u32 = 60},
        .include_move_self = 1,
    }, &frame) == POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&battle, &before, sizeof(battle)) == 0);
}

static void test_dream_eater_move_immunity_is_deferred_after_accuracy(void) {
    const PokemonData *generated = &POKEMON_GEN3_SLICE_DATA;
    const PokemonHandlerDescriptor *handler = NULL;
    for (size_t i = 0; i < generated->handler_count; i++) {
        if (generated->handlers[i].id ==
                POKEMON_GEN3_HANDLER_DREAM_EATER_TRY_IMMUNITY) {
            handler = &generated->handlers[i];
            break;
        }
    }
    assert(handler != NULL);
    assert(handler->event == POKEMON_HANDLER_EVENT_TRY_IMMUNITY);
    assert(handler->source_kind == POKEMON_HANDLER_SOURCE_MOVE);
    assert(handler->source_id == POKEMON_GEN3_MOVE_DREAMEATER);
    assert(handler->scope == POKEMON_HANDLER_SCOPE_TARGET);
    assert(handler->route == POKEMON_HANDLER_ROUTE_MOVE_SELF);
    assert(handler->program_count == 2);
    assert(generated->handler_programs[handler->program_offset].opcode ==
        POKEMON_HANDLER_OP_REQUIRE_HOLDER_STATUS_MASK);
    assert(generated->handler_programs[handler->program_offset].argument ==
        (UINT32_C(1) << POKEMON_STATUS_SLEEP));
    assert(generated->handler_programs[handler->program_offset + 1].opcode ==
        POKEMON_HANDLER_OP_REQUIRE_HOLDER_WITHOUT_VOLATILE_KIND);
    assert(generated->handler_programs[handler->program_offset + 1].argument ==
        POKEMON_VOLATILE_SUBSTITUTE);

    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_DREAMEATER,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[0].members[0].stats[5] = 500;
    init.initial_hp[0][0] = 50;
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    PokemonBattle battle;

    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    uint16_t target_hp = battle.sides[1].state[0].hp;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].state[0].hp == target_hp);
    assert(battle.sides[0].state[0].hp == 50);
    assert(handler_id_count(&battle,
        POKEMON_GEN3_HANDLER_DREAM_EATER_TRY_IMMUNITY) == 1);
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 1);
    assert(draw_label_count(&battle, POKEMON_DRAW_CRITICAL) == 0);
    assert(draw_label_count(&battle, POKEMON_DRAW_DAMAGE_ROLL) == 0);

    init.initial_status[1][0] = POKEMON_STATUS_SLEEP;
    init.initial_sleep_time[1][0] = 3;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    target_hp = battle.sides[1].state[0].hp;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].state[0].hp < target_hp);
    assert(battle.sides[0].state[0].hp > 50);
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 1);
    assert(draw_label_count(&battle, POKEMON_DRAW_CRITICAL) == 1);
    assert(draw_label_count(&battle, POKEMON_DRAW_DAMAGE_ROLL) == 1);

    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    PokemonMutable *target = &battle.sides[1].state[0];
    target->volatiles[target->volatile_count++] = (PokemonVolatileState){
        .kind = POKEMON_VOLATILE_SUBSTITUTE,
        .descriptor_id = POKEMON_GEN3_CONDITION_VOLATILE_SUBSTITUTE,
        .state_generation = 1,
        .effect_order = ++battle.next_holder_effect_order,
        .payload.substitute.hp = 1,
    };
    target_hp = target->hp;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(target->hp == target_hp);
    assert(target->volatiles[0].payload.substitute.hp == 1);
    assert(battle.sides[0].state[0].hp == 50);
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 1);
    assert(draw_label_count(&battle, POKEMON_DRAW_CRITICAL) == 0);
    assert(draw_label_count(&battle, POKEMON_DRAW_DAMAGE_ROLL) == 0);

    PokemonHandlerOp programs[generated->handler_program_count];
    memcpy(programs, generated->handler_programs, sizeof(programs));
    programs[handler->program_offset + 1].argument = POKEMON_VOLATILE_NONE;
    PokemonData invalid_data = *generated;
    invalid_data.handler_programs = programs;
    assert_invalid_resolved_data_is_atomic(init, &invalid_data);
}

static void test_refresh_move_hit_callback_boundary(void) {
    const uint32_t curable =
        (UINT32_C(1) << POKEMON_STATUS_BURN) |
        (UINT32_C(1) << POKEMON_STATUS_TOXIC) |
        (UINT32_C(1) << POKEMON_STATUS_PARALYSIS) |
        (UINT32_C(1) << POKEMON_STATUS_POISON);
    const PokemonStatus statuses[] = {
        POKEMON_STATUS_NONE, POKEMON_STATUS_SLEEP, POKEMON_STATUS_FREEZE,
        POKEMON_STATUS_BURN, POKEMON_STATUS_PARALYSIS,
        POKEMON_STATUS_POISON, POKEMON_STATUS_TOXIC,
    };
    for (size_t i = 0; i < sizeof(statuses) / sizeof(statuses[0]); i++) {
        PokemonBattleInit init = condition_init(
            POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_REFRESH,
            POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_SPLASH);
        PokemonBattle battle;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        PokemonStatusState *status = &battle.sides[0].state[0].status;
        status->kind = statuses[i];
        if (statuses[i] != POKEMON_STATUS_NONE) {
            status->descriptor_id = battle.generation->condition_descriptor(
                POKEMON_OWNER_STATUS, statuses[i]);
            status->state_generation = 1;
            status->effect_order = 1;
            if (statuses[i] == POKEMON_STATUS_SLEEP) {
                status->state.sleep.time = 1;
            }
        }
        uint8_t draws_before = battle.draw_count;
        PokemonEventFrame frame;
        assert(pokemon_run_event(&battle, &(PokemonEventInput){
            .event = POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK,
            .source = {POKEMON_ENTITY_POKEMON, 0, 0},
            .target_side = 0, .target_slot = 0,
            .source_effect = {POKEMON_SOURCE_EFFECT_MOVE,
                POKEMON_GEN3_MOVE_REFRESH},
            .relay = {.kind = POKEMON_RELAY_BOOLEAN, .value.boolean = 1},
            .context_kind = POKEMON_EVENT_CONTEXT_MOVE,
            .context.move = {.move = generated_move(POKEMON_GEN3_MOVE_REFRESH)},
            .include_move_self = 1,
        }, &frame) == POKEMON_OK);
        const int succeeds = statuses[i] != POKEMON_STATUS_NONE &&
            (curable & (UINT32_C(1) << statuses[i])) != 0;
        assert(frame.relay.kind == POKEMON_RELAY_BOOLEAN);
        assert(frame.relay.value.boolean == succeeds);
        assert(frame.cancellation == (succeeds ? POKEMON_EVENT_CANCEL_NONE :
            POKEMON_EVENT_CANCEL_FALSE));
        assert(battle.sides[0].state[0].status.kind ==
            (succeeds ? POKEMON_STATUS_NONE : statuses[i]));
        assert(battle.condition_trace_count == (uint8_t)succeeds);
        assert(battle.effect_trace_count == (uint8_t)succeeds);
        if (succeeds) {
            const PokemonEffectTrace *effect = &battle.effect_traces[0];
            assert(effect->kind == POKEMON_EFFECT_CURE_STATUS);
            assert(effect->phase == POKEMON_EFFECT_PHASE_PRIMARY);
            assert(effect->result == POKEMON_EFFECT_APPLIED);
            assert(effect->move_id == POKEMON_GEN3_MOVE_REFRESH);
            assert(effect->source_side == 0 && effect->source_slot == 0);
            assert(effect->target_side == 0 && effect->target_slot == 0);
            assert(effect->before == (int16_t)statuses[i]);
            assert(effect->after == POKEMON_STATUS_NONE);
        }
        assert(battle.draw_count == draws_before);
        assert(battle.handler_count == 1);
        assert(battle.handlers[0].handler.descriptor.id ==
            POKEMON_GEN3_HANDLER_REFRESH_HIT);
        assert(pokemon_battle_check_invariants(&battle));
    }

    for (size_t status_case = 0; status_case < 2; status_case++) {
        PokemonBattleInit init = condition_init(
            POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_REFRESH,
            POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_SPLASH);
        init.initial_status[0][0] = status_case ?
            POKEMON_STATUS_BURN : POKEMON_STATUS_NONE;
        PokemonBattle battle;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        size_t own_move = SIZE_MAX;
        for (size_t i = 0; i < battle.event_count; i++) {
            if (battle.events[i].kind == POKEMON_EVENT_MOVE &&
                battle.events[i].side == 0) own_move = i;
        }
        assert(own_move != SIZE_MAX);
        assert(battle.events[own_move].target_side ==
            (status_case ? 0 : UINT8_MAX));
        assert(battle.sides[0].state[0].status.kind == POKEMON_STATUS_NONE);
        assert(battle.condition_trace_count == (status_case ? 1 : 0));
        assert(pokemon_battle_check_invariants(&battle));
    }
}

static void test_thick_fat_source_base_power(void) {
    PokemonBattleInit init = modifier_init(
        POKEMON_GEN3_ABILITY_ROCKHEAD, 0, POKEMON_STATUS_NONE);
    init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_THICKFAT;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);

    PokemonMoveData active = {
        .id = POKEMON_GEN3_MOVE_WEATHERBALL,
        .type = POKEMON_GEN3_TYPE_FIRE,
        .category = POKEMON_CATEGORY_SPECIAL,
    };
    PokemonEventInput input = {
        .event = POKEMON_HANDLER_EVENT_BASE_POWER,
        .source = {POKEMON_ENTITY_POKEMON, 0, 0},
        /* BasePower is rooted at the attacker; onSourceBasePower discovers
         * the defender through the FOE scope. */
        .target_side = 0, .target_slot = 0,
        .context_kind = POKEMON_EVENT_CONTEXT_MOVE,
        .context.move = {.move = &active},
        .relay = {.kind = POKEMON_RELAY_U32, .value.u32 = 95},
    };
    PokemonEventFrame frame;
    assert(pokemon_run_event(&battle, &input, &frame) == POKEMON_OK);
    assert(frame.relay.value.u32 == 47);
    assert(frame.modifier_q12 == 2048);
    assert(frame.executed_count == 1);
    assert(battle.modifier_count == 1);
    assert(battle.modifiers[0].handler.descriptor.id ==
        POKEMON_GEN3_HANDLER_THICK_FAT);
    assert(battle.modifiers[0].handler.descriptor.priority == 1);

    active.type = POKEMON_GEN3_TYPE_ICE;
    input.relay.value.u32 = 95;
    assert(pokemon_run_event(&battle, &input, &frame) == POKEMON_OK);
    assert(frame.relay.value.u32 == 47 && frame.modifier_q12 == 2048);

    active.type = POKEMON_GEN3_TYPE_WATER;
    input.relay.value.u32 = 95;
    assert(pokemon_run_event(&battle, &input, &frame) == POKEMON_OK);
    assert(frame.relay.value.u32 == 95 && frame.modifier_q12 == 4096);
    assert(pokemon_battle_check_invariants(&battle));
}

static void test_marvel_scale_modify_defense_staging(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SNORLAX, POKEMON_GEN3_MOVE_EXPLOSION,
        POKEMON_GEN3_SPECIES_MILOTIC, POKEMON_GEN3_MOVE_SURF);
    init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_MARVELSCALE;
    init.teams[1].members[0].stats[2] = 101;
    init.initial_status[1][0] = POKEMON_STATUS_PARALYSIS;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);

    PokemonEventFrame frame;
    assert(pokemon_run_event(&battle, &(PokemonEventInput){
        .event = POKEMON_HANDLER_EVENT_MODIFY_DEF,
        .source = {POKEMON_ENTITY_POKEMON, 0, 0},
        .target_side = 1, .target_slot = 0,
        .source_effect = {POKEMON_SOURCE_EFFECT_MOVE,
            POKEMON_GEN3_MOVE_EXPLOSION},
        .relay = {.kind = POKEMON_RELAY_U32, .value.u32 = 101},
        .context_kind = POKEMON_EVENT_CONTEXT_MOVE,
        .context.move = {.move = generated_move(POKEMON_GEN3_MOVE_EXPLOSION)},
    }, &frame) == POKEMON_OK);
    assert(frame.relay.value.u32 == 151 && frame.modifier_q12 == 6144);
    assert(battle.modifier_count == 1);
    assert(battle.modifiers[0].handler.descriptor.id ==
        POKEMON_GEN3_HANDLER_MARVEL_SCALE);
    assert(battle.modifiers[0].handler.descriptor.priority == 6);

    init.initial_status[1][0] = POKEMON_STATUS_NONE;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_run_event(&battle, &(PokemonEventInput){
        .event = POKEMON_HANDLER_EVENT_MODIFY_DEF,
        .source = {POKEMON_ENTITY_POKEMON, 0, 0},
        .target_side = 1, .target_slot = 0,
        .source_effect = {POKEMON_SOURCE_EFFECT_MOVE,
            POKEMON_GEN3_MOVE_EXPLOSION},
        .relay = {.kind = POKEMON_RELAY_U32, .value.u32 = 101},
        .context_kind = POKEMON_EVENT_CONTEXT_MOVE,
        .context.move = {.move = generated_move(POKEMON_GEN3_MOVE_EXPLOSION)},
    }, &frame) == POKEMON_OK);
    assert(frame.relay.value.u32 == 101 && frame.modifier_q12 == 4096);

    init.initial_status[1][0] = POKEMON_STATUS_PARALYSIS;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    battle.sides[1].state[0].boosts[POKEMON_STAT_DEF] = 6;
    PokemonDamageRequest request = {
        .mode = POKEMON_DAMAGE_MODE_ORDINARY_MOVE,
        .source = {POKEMON_ENTITY_POKEMON, 0, 0},
        .target = {POKEMON_ENTITY_POKEMON, 1, 0},
        .move = generated_move(POKEMON_GEN3_MOVE_EXPLOSION),
        .critical = 1,
    };
    PokemonCalculatedDamage modified;
    assert(pokemon_calculate_damage(&battle, &request, &modified) == POKEMON_OK);
    const PokemonRelayResult *defense_result = NULL;
    for (size_t i = 0; i < battle.relay_result_count; i++) {
        if (battle.relay_results[i].event == POKEMON_HANDLER_EVENT_MODIFY_DEF) {
            defense_result = &battle.relay_results[i];
        }
    }
    assert(defense_result != NULL);
    assert(defense_result->input == 101 && defense_result->output == 151);

    PokemonMoveData ordinary = *request.move;
    ordinary.defense_policy = POKEMON_DEFENSE_POLICY_STANDARD;
    PokemonBattleInit control_init = init;
    control_init.teams[1].members[0].ability_id = 0;
    control_init.teams[1].members[0].stats[2] = 75;
    PokemonBattle control;
    assert(pokemon_battle_init(&control, &control_init) == POKEMON_OK);
    request.move = &ordinary;
    PokemonCalculatedDamage control_damage;
    assert(pokemon_calculate_damage(&control, &request, &control_damage) ==
        POKEMON_OK);
    assert(modified.damage == control_damage.damage);

    request.move = &ordinary;
    request.critical = 0;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    battle.sides[1].state[0].boosts[POKEMON_STAT_DEF] = 1;
    assert(pokemon_calculate_damage(&battle, &request, &modified) == POKEMON_OK);
    defense_result = NULL;
    for (size_t i = 0; i < battle.relay_result_count; i++) {
        if (battle.relay_results[i].event == POKEMON_HANDLER_EVENT_MODIFY_DEF) {
            defense_result = &battle.relay_results[i];
        }
    }
    assert(defense_result != NULL);
    assert(defense_result->input == 151 && defense_result->output == 226);
    assert(pokemon_battle_check_invariants(&battle));
}

static void test_leftovers_residual_healing(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_SPLASH,
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[0].members[0].item_id = POKEMON_GEN3_ITEM_LEFTOVERS;
    init.teams[0].members[0].stats[0] = 500;
    init.initial_hp[0][0] = 470;
    PokemonBattle battle;
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};

    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].hp == 500);
    assert(battle.handler_count == 1);
    assert(battle.handlers[0].handler.descriptor.id ==
        POKEMON_GEN3_HANDLER_LEFTOVERS_RESIDUAL);
    assert(battle.handlers[0].handler.descriptor.order == 10);
    assert(battle.handlers[0].handler.descriptor.sub_order == 4);
    size_t heal_count = 0;
    for (size_t i = 0; i < battle.event_count; i++) {
        if (battle.events[i].kind != POKEMON_EVENT_HEAL) continue;
        heal_count++;
        assert(battle.events[i].amount == 30);
    }
    assert(heal_count == 1);

    init.initial_hp[0][0] = 500;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].hp == 500);
    assert(battle.handler_count == 1);
    heal_count = 0;
    for (size_t i = 0; i < battle.event_count; i++) {
        heal_count += battle.events[i].kind == POKEMON_EVENT_HEAL;
    }
    assert(heal_count == 0);

    init.teams[0].members[0].stats[0] = 15;
    init.initial_hp[0][0] = 14;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].hp == 15);
    heal_count = 0;
    for (size_t i = 0; i < battle.event_count; i++) {
        if (battle.events[i].kind != POKEMON_EVENT_HEAL) continue;
        heal_count++;
        assert(battle.events[i].amount == 1);
    }
    assert(heal_count == 1);
}

static void test_natural_cure_switch_out(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_STARMIE, POKEMON_GEN3_MOVE_SPLASH,
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_SPLASH);
    init.team_sizes[0] = 2;
    init.teams[0].members[0].ability_id = POKEMON_GEN3_ABILITY_NATURALCURE;
    init.teams[0].members[1] = make_set(
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SPLASH,
        651, 56, 56, 186, 306, 146);
    init.initial_status[0][0] = POKEMON_STATUS_BURN;
    PokemonBattle battle;
    PokemonChoice choices[POKEMON_SIDES] = {switch_to(1), move(0)};

    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].active == 1);
    assert(battle.sides[0].state[0].status.kind == POKEMON_STATUS_NONE);
    assert(battle.handler_count >= 1);
    assert(battle.handlers[0].handler.descriptor.id ==
        POKEMON_GEN3_HANDLER_NATURAL_CURE_SWITCH_OUT);
    assert(battle.condition_trace_count >= 1);
    assert(battle.condition_traces[0].scope == POKEMON_CONDITION_SCOPE_STATUS);
    assert(battle.condition_traces[0].operation == POKEMON_CONDITION_REMOVE);
    assert(battle.condition_traces[0].reason == POKEMON_CONDITION_REASON_HANDLER);

    init.initial_status[0][0] = POKEMON_STATUS_NONE;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.handlers[0].handler.descriptor.id ==
        POKEMON_GEN3_HANDLER_NATURAL_CURE_SWITCH_OUT);
    assert(battle.condition_trace_count == 0);
}

static void test_generated_ordinary_attack_family(void) {
    static const struct {
        uint16_t id;
        uint8_t type;
        PokemonCategory category;
        uint8_t power;
        uint8_t accuracy;
        uint8_t pp;
        PokemonMoveTarget target;
    } cases[] = {
        {POKEMON_GEN3_MOVE_CUT, POKEMON_GEN3_TYPE_NORMAL, POKEMON_CATEGORY_PHYSICAL, 50, 95, 48, POKEMON_TARGET_NORMAL},
        {POKEMON_GEN3_MOVE_DRAGONCLAW, POKEMON_GEN3_TYPE_DRAGON, POKEMON_CATEGORY_SPECIAL, 80, 100, 24, POKEMON_TARGET_NORMAL},
        {POKEMON_GEN3_MOVE_DRILLPECK, POKEMON_GEN3_TYPE_FLYING, POKEMON_CATEGORY_PHYSICAL, 80, 100, 32, POKEMON_TARGET_ANY},
        {POKEMON_GEN3_MOVE_EGGBOMB, POKEMON_GEN3_TYPE_NORMAL, POKEMON_CATEGORY_PHYSICAL, 100, 75, 16, POKEMON_TARGET_NORMAL},
        {POKEMON_GEN3_MOVE_HORNATTACK, POKEMON_GEN3_TYPE_NORMAL, POKEMON_CATEGORY_PHYSICAL, 65, 100, 40, POKEMON_TARGET_NORMAL},
        {POKEMON_GEN3_MOVE_HYDROPUMP, POKEMON_GEN3_TYPE_WATER, POKEMON_CATEGORY_SPECIAL, 120, 80, 8, POKEMON_TARGET_NORMAL},
        {POKEMON_GEN3_MOVE_MEGAHORN, POKEMON_GEN3_TYPE_BUG, POKEMON_CATEGORY_PHYSICAL, 120, 85, 16, POKEMON_TARGET_NORMAL},
        {POKEMON_GEN3_MOVE_MEGAKICK, POKEMON_GEN3_TYPE_NORMAL, POKEMON_CATEGORY_PHYSICAL, 120, 75, 8, POKEMON_TARGET_NORMAL},
        {POKEMON_GEN3_MOVE_PECK, POKEMON_GEN3_TYPE_FLYING, POKEMON_CATEGORY_PHYSICAL, 35, 100, 56, POKEMON_TARGET_ANY},
        {POKEMON_GEN3_MOVE_POUND, POKEMON_GEN3_TYPE_NORMAL, POKEMON_CATEGORY_PHYSICAL, 40, 100, 56, POKEMON_TARGET_NORMAL},
        {POKEMON_GEN3_MOVE_PAYDAY, POKEMON_GEN3_TYPE_NORMAL, POKEMON_CATEGORY_PHYSICAL, 40, 100, 32, POKEMON_TARGET_NORMAL},
        {POKEMON_GEN3_MOVE_ROCKTHROW, POKEMON_GEN3_TYPE_ROCK, POKEMON_CATEGORY_PHYSICAL, 50, 90, 24, POKEMON_TARGET_NORMAL},
        {POKEMON_GEN3_MOVE_SLAM, POKEMON_GEN3_TYPE_NORMAL, POKEMON_CATEGORY_PHYSICAL, 80, 75, 32, POKEMON_TARGET_NORMAL},
        {POKEMON_GEN3_MOVE_VINEWHIP, POKEMON_GEN3_TYPE_GRASS, POKEMON_CATEGORY_SPECIAL, 35, 100, 16, POKEMON_TARGET_NORMAL},
        {POKEMON_GEN3_MOVE_VISEGRIP, POKEMON_GEN3_TYPE_NORMAL, POKEMON_CATEGORY_PHYSICAL, 55, 100, 48, POKEMON_TARGET_NORMAL},
        {POKEMON_GEN3_MOVE_WATERFALL, POKEMON_GEN3_TYPE_WATER, POKEMON_CATEGORY_SPECIAL, 80, 100, 24, POKEMON_TARGET_NORMAL},
        {POKEMON_GEN3_MOVE_WATERGUN, POKEMON_GEN3_TYPE_WATER, POKEMON_CATEGORY_SPECIAL, 40, 100, 40, POKEMON_TARGET_NORMAL},
    };
    assert(sizeof(cases) / sizeof(cases[0]) == 17);
    for (size_t i = 0; i < sizeof(cases) / sizeof(cases[0]); i++) {
        const PokemonMoveData *move_data = NULL;
        for (size_t j = 0; j < POKEMON_GEN3_SLICE_DATA.move_count; j++) {
            if (POKEMON_GEN3_SLICE_DATA.moves[j].id == cases[i].id) {
                move_data = &POKEMON_GEN3_SLICE_DATA.moves[j];
                break;
            }
        }
        assert(move_data != NULL);
        assert(move_data->type == cases[i].type);
        assert(move_data->category == cases[i].category);
        assert(move_data->power == cases[i].power);
        assert(move_data->accuracy.kind == POKEMON_ACCURACY_PERCENT &&
            move_data->accuracy.percent == cases[i].accuracy);
        assert(move_data->priority == 0 && move_data->pp == cases[i].pp);
        assert(move_data->target == cases[i].target && move_data->flags != 0);
        assert(move_data->effect_count == 0);
        assert(move_data->multihit_min == 0 && move_data->multihit_max == 0);
        assert(move_data->damage_formula == POKEMON_DAMAGE_STANDARD);
    }
}

static void test_generated_type_boost_item_family(void) {
    static const struct {
        uint16_t item;
        PokemonEventId event;
        uint8_t type;
    } cases[] = {
        {POKEMON_GEN3_ITEM_HARDSTONE, POKEMON_HANDLER_EVENT_MODIFY_ATK, POKEMON_GEN3_TYPE_ROCK},
        {POKEMON_GEN3_ITEM_METALCOAT, POKEMON_HANDLER_EVENT_MODIFY_ATK, POKEMON_GEN3_TYPE_STEEL},
        {POKEMON_GEN3_ITEM_POISONBARB, POKEMON_HANDLER_EVENT_MODIFY_ATK, POKEMON_GEN3_TYPE_POISON},
        {POKEMON_GEN3_ITEM_SHARPBEAK, POKEMON_HANDLER_EVENT_MODIFY_ATK, POKEMON_GEN3_TYPE_FLYING},
        {POKEMON_GEN3_ITEM_SILKSCARF, POKEMON_HANDLER_EVENT_MODIFY_ATK, POKEMON_GEN3_TYPE_NORMAL},
        {POKEMON_GEN3_ITEM_SILVERPOWDER, POKEMON_HANDLER_EVENT_MODIFY_ATK, POKEMON_GEN3_TYPE_BUG},
        {POKEMON_GEN3_ITEM_SOFTSAND, POKEMON_HANDLER_EVENT_MODIFY_ATK, POKEMON_GEN3_TYPE_GROUND},
        {POKEMON_GEN3_ITEM_SPELLTAG, POKEMON_HANDLER_EVENT_MODIFY_ATK, POKEMON_GEN3_TYPE_GHOST},
        {POKEMON_GEN3_ITEM_BLACKGLASSES, POKEMON_HANDLER_EVENT_MODIFY_SPA, POKEMON_GEN3_TYPE_DARK},
        {POKEMON_GEN3_ITEM_CHARCOAL, POKEMON_HANDLER_EVENT_MODIFY_SPA, POKEMON_GEN3_TYPE_FIRE},
        {POKEMON_GEN3_ITEM_DRAGONFANG, POKEMON_HANDLER_EVENT_MODIFY_SPA, POKEMON_GEN3_TYPE_DRAGON},
        {POKEMON_GEN3_ITEM_MAGNET, POKEMON_HANDLER_EVENT_MODIFY_SPA, POKEMON_GEN3_TYPE_ELECTRIC},
        {POKEMON_GEN3_ITEM_MIRACLESEED, POKEMON_HANDLER_EVENT_MODIFY_SPA, POKEMON_GEN3_TYPE_GRASS},
        {POKEMON_GEN3_ITEM_MYSTICWATER, POKEMON_HANDLER_EVENT_MODIFY_SPA, POKEMON_GEN3_TYPE_WATER},
        {POKEMON_GEN3_ITEM_NEVERMELTICE, POKEMON_HANDLER_EVENT_MODIFY_SPA, POKEMON_GEN3_TYPE_ICE},
        {POKEMON_GEN3_ITEM_SEAINCENSE, POKEMON_HANDLER_EVENT_MODIFY_SPA, POKEMON_GEN3_TYPE_WATER},
        {POKEMON_GEN3_ITEM_TWISTEDSPOON, POKEMON_HANDLER_EVENT_MODIFY_SPA, POKEMON_GEN3_TYPE_PSYCHIC},
    };
    for (size_t i = 0; i < sizeof(cases) / sizeof(cases[0]); i++) {
        PokemonBattleInit init = modifier_init(
            POKEMON_GEN3_ABILITY_ROCKHEAD, cases[i].item, POKEMON_STATUS_NONE);
        PokemonBattle battle;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        PokemonMoveData matching = {.id = POKEMON_GEN3_MOVE_TACKLE,
            .type = cases[i].type, .category = POKEMON_CATEGORY_PHYSICAL};
        PokemonEventFrame frame;
        assert(pokemon_run_event(&battle, &(PokemonEventInput){
            .event = cases[i].event,
            .source = {POKEMON_ENTITY_POKEMON, 0, 0},
            .target_side = 0, .target_slot = 0,
            .context_kind = POKEMON_EVENT_CONTEXT_MOVE,
            .context.move = {.move = &matching},
            .relay = {.kind = POKEMON_RELAY_U32, .value.u32 = 100},
        }, &frame) == POKEMON_OK);
        uint32_t expected_modifier = cases[i].item == POKEMON_GEN3_ITEM_SEAINCENSE ?
            4300 : 4505;
        uint32_t expected_output = cases[i].item == POKEMON_GEN3_ITEM_SEAINCENSE ?
            105 : 110;
        assert(frame.relay.value.u32 == expected_output);
        assert(frame.modifier_q12 == expected_modifier);
        assert(frame.executed_count == 1 && frame.skipped_count == 0);
        assert(battle.modifier_count == 1);
        assert(battle.modifiers[0].handler.owner.effect_id == cases[i].item);
        assert(battle.sides[0].state[0].item_id == cases[i].item);

        matching.type = cases[i].type == POKEMON_GEN3_TYPE_NORMAL ?
            POKEMON_GEN3_TYPE_FIRE : POKEMON_GEN3_TYPE_NORMAL;
        assert(pokemon_run_event(&battle, &(PokemonEventInput){
            .event = cases[i].event,
            .source = {POKEMON_ENTITY_POKEMON, 0, 0},
            .target_side = 0, .target_slot = 0,
            .context_kind = POKEMON_EVENT_CONTEXT_MOVE,
            .context.move = {.move = &matching},
            .relay = {.kind = POKEMON_RELAY_U32, .value.u32 = 100},
        }, &frame) == POKEMON_OK);
        assert(frame.relay.value.u32 == 100);
        assert(frame.modifier_q12 == 4096);
        assert(frame.executed_count == 1 && frame.skipped_count == 0);
    }

    /* Damage-category staging is observable: physical and special moves use
     * distinct Showdown events, while the same Q12 family owns rounding. */
    PokemonBattle plain_physical, boosted_physical, plain_special, boosted_special;
    uint16_t plain_physical_damage = run_modifier_case(
        POKEMON_GEN3_ABILITY_ROCKHEAD, 0, POKEMON_STATUS_NONE, &plain_physical);
    uint16_t boosted_physical_damage = run_modifier_case(
        POKEMON_GEN3_ABILITY_ROCKHEAD, POKEMON_GEN3_ITEM_BLACKBELT,
        POKEMON_STATUS_NONE, &boosted_physical);
    assert(boosted_physical_damage > plain_physical_damage);
    assert(boosted_physical.relay_results[0].event == POKEMON_HANDLER_EVENT_MODIFY_ATK);

    PokemonBattleInit special_init = condition_init(
        POKEMON_GEN3_SPECIES_VAPOREON, POKEMON_GEN3_MOVE_SURF,
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SPLASH);
    special_init.teams[0].members[0].ability_id = POKEMON_GEN3_ABILITY_ROCKHEAD;
    special_init.teams[1].members[0].stats[0] = 1000;
    special_init.teams[1].members[0].stats[4] = 400;
    assert(pokemon_battle_init(&plain_special, &special_init) == POKEMON_OK);
    special_init.teams[0].members[0].item_id = POKEMON_GEN3_ITEM_MYSTICWATER;
    assert(pokemon_battle_init(&boosted_special, &special_init) == POKEMON_OK);
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_step(&plain_special, choices) == POKEMON_OK);
    assert(pokemon_battle_step(&boosted_special, choices) == POKEMON_OK);
    assert(first_damage(&boosted_special) > first_damage(&plain_special));
    assert(boosted_special.relay_results[0].event == POKEMON_HANDLER_EVENT_MODIFY_SPA);
    assert(boosted_special.modifiers[0].modifier_q12 == 4505);
}

static void test_modifier_capacity_failure_is_atomic(void) {
    static PokemonHandlerDescriptor too_many[POKEMON_MODIFIER_CAPACITY + 1];
    static PokemonAbilityData ability;
    for (size_t i = 0; i < POKEMON_MODIFIER_CAPACITY + 1; i++) {
        too_many[i] = (PokemonHandlerDescriptor){
            .event = POKEMON_HANDLER_EVENT_MODIFY_ATK,
            .id = POKEMON_GEN3_HANDLER_GUTS,
            .source_kind = POKEMON_HANDLER_SOURCE_ABILITY,
            .source_id = 99,
            .modifier_q12 = 4096,
        };
    }
    ability = (PokemonAbilityData){99, 0, POKEMON_MODIFIER_CAPACITY + 1, 0, 0, 0, 0, 0, 0};
    PokemonBattleInit init = modifier_init(0, 0, POKEMON_STATUS_NONE);
    PokemonData data = *init.bundle->data;
    PokemonMoveData synthetic_moves[POKEMON_GEN3_MOVE_COUNT];
    remove_move_call_capability(&data, synthetic_moves);
    data.abilities = &ability;
    data.ability_count = 1;
    data.handlers = too_many;
    data.handler_count = POKEMON_MODIFIER_CAPACITY + 1;
    PokemonOwnerBindingIndex owner_index = {
        .owner_kind = POKEMON_OWNER_ABILITY, .owner_id = 99,
        .event = POKEMON_HANDLER_EVENT_MODIFY_ATK,
        .scope = POKEMON_HANDLER_SCOPE_TARGET,
        .route = POKEMON_HANDLER_ROUTE_OWNER,
        .binding_offset = 0, .binding_count = POKEMON_MODIFIER_CAPACITY + 1};
    data.owner_binding_index = &owner_index;
    data.owner_binding_index_count = 1;
    PokemonResolvedBundle bundle = *init.bundle;
    PokemonFormatPolicy policy = *bundle.policy;
    policy.status_clauses = NULL;
    policy.status_clause_count = 0;
    bundle.policy = &policy;
    bundle.data = &data;
    init.bundle = &bundle;
    init.teams[0].members[0].ability_id = 99;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    PokemonBattle before = battle;
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_step(&battle, choices) == POKEMON_CAPACITY_EXCEEDED);
    assert(memcmp(&battle, &before, sizeof(battle)) == 0);

    battle = before;
    battle.relay_result_count = POKEMON_RELAY_RESULT_CAPACITY + 1;
    assert(!pokemon_battle_check_invariants(&battle));
}

static PokemonBattleInit condition_init(
    uint16_t left_species, uint16_t left_move,
    uint16_t right_species, uint16_t right_move
) {
    PokemonBattleInit init = battle_init();
    init.teams[0].members[0].species_id = left_species;
    init.teams[0].members[0].move_ids[0] = left_move;
    init.teams[0].members[0].stats[5] = 300;
    init.teams[1].members[0].species_id = right_species;
    init.teams[1].members[0].move_ids[0] = right_move;
    init.teams[1].members[0].stats[5] = 100;
    return init;
}

static void test_generic_queued_move_interception(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_PURSUIT,
        POKEMON_GEN3_SPECIES_ALAKAZAM, POKEMON_GEN3_MOVE_SPLASH);
    init.team_sizes[0] = 1;
    init.team_sizes[1] = 2;
    init.teams[1].members[1] = make_set(
        POKEMON_GEN3_SPECIES_MACHOP, POKEMON_GEN3_MOVE_SPLASH,
        200, 100, 100, 100, 100, 80);
    PokemonChoice switching[POKEMON_SIDES] = {move(0), switch_to(1)};
    PokemonChoice staying[POKEMON_SIDES] = {move(0), move(0)};
    PokemonBattle battle;

    /* The targeted pre-turn condition claims the exact queued move and runs
     * it from the post-BeforeMove boundary. Switch intent owns both Pursuit
     * policies: doubled power and always-hit accuracy. */
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    uint16_t old_hp = battle.sides[1].state[0].hp;
    assert(battle.sides[0].state[0].pp[0] == 32);
    assert(pokemon_battle_step(&battle, switching) == POKEMON_OK);
    assert(battle.sides[1].active == 1);
    assert(battle.sides[1].state[0].hp < old_hp);
    assert(battle.sides[0].state[0].pp[0] == 31);
    assert(battle.sides[0].state[0].last_move_id == POKEMON_GEN3_MOVE_PURSUIT);
    assert(battle.sides[0].state[0].active_move_actions == 1);
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 0);
    assert(handler_event_count(
        &battle, POKEMON_HANDLER_EVENT_BEFORE_SWITCH_OUT) == 1);
    assert(battle.move_invocation_count == 1);
    assert(battle.move_invocations[0].invocation.target_switching == 1);

    /* Without switch intent, the same descriptor follows the ordinary move
     * path and consumes its accuracy draw. */
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, staying) == POKEMON_OK);
    assert(battle.sides[1].active == 0);
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 1);
    assert(handler_event_count(
        &battle, POKEMON_HANDLER_EVENT_BEFORE_SWITCH_OUT) == 0);
    assert(battle.move_invocations[0].invocation.target_switching == 0);

    /* Gen 3's interception callback directly invokes useMove after the
     * ordinary BeforeMove gate has already run. Paralysis therefore cannot
     * add a second immobilization draw. Pressure still owns its normal PP
     * deduction in the invoked move. */
    init.initial_status[0][0] = POKEMON_STATUS_PARALYSIS;
    init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_PRESSURE;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    old_hp = battle.sides[1].state[0].hp;
    assert(pokemon_battle_step(&battle, switching) == POKEMON_OK);
    assert(battle.sides[1].state[0].hp < old_hp);
    assert(battle.sides[0].state[0].pp[0] == 30);
    assert(draw_label_count(&battle, POKEMON_DRAW_PARALYSIS) == 0);
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 0);

    /* Sleep and freeze suppress pre-turn registration, so the switch is not
     * intercepted and the selected move remains unspent. */
    const uint8_t blocked[] = {POKEMON_STATUS_SLEEP, POKEMON_STATUS_FREEZE};
    for (size_t i = 0; i < sizeof(blocked) / sizeof(blocked[0]); i++) {
        init.initial_status[0][0] = blocked[i];
        init.initial_sleep_time[0][0] = blocked[i] == POKEMON_STATUS_SLEEP ? 3 : 0;
        init.teams[1].members[0].ability_id = 0;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        old_hp = battle.sides[1].state[0].hp;
        assert(pokemon_battle_step(&battle, switching) == POKEMON_OK);
        assert(battle.sides[1].active == 1);
        assert(battle.sides[1].state[0].hp == old_hp);
        assert(battle.sides[0].state[0].pp[0] == 32);
        assert(handler_event_count(
            &battle, POKEMON_HANDLER_EVENT_BEFORE_SWITCH_OUT) == 0);
    }

    /* A lethal interception does not manufacture a forced replacement. It
     * drains the faint, then continues the exact switch chosen this turn. */
    init.initial_status[0][0] = POKEMON_STATUS_NONE;
    init.teams[1].members[0].stats[0] = 1;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, switching) == POKEMON_OK);
    assert(battle.sides[1].state[0].fainted);
    assert(battle.sides[1].active == 1);
    size_t faint_at = SIZE_MAX;
    size_t switch_at = SIZE_MAX;
    for (size_t i = 0; i < battle.event_count; i++) {
        if (battle.events[i].kind == POKEMON_EVENT_FAINT &&
            battle.events[i].side == 1 && battle.events[i].slot == 0) {
            faint_at = i;
        }
        if (battle.events[i].kind == POKEMON_EVENT_SWITCH &&
            battle.events[i].side == 1 && battle.events[i].slot == 1) {
            switch_at = i;
        }
    }
    assert(faint_at != SIZE_MAX);
    assert(switch_at != SIZE_MAX);
    assert(faint_at < switch_at);
}

static void test_generic_forced_drag_transaction(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_ROAR,
        POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_WHIRLWIND);
    init.team_sizes[0] = 1;
    init.team_sizes[1] = 3;
    init.teams[1].members[1] = make_set(
        POKEMON_GEN3_SPECIES_MACHOP, POKEMON_GEN3_MOVE_SPLASH,
        200, 100, 100, 100, 100, 80);
    init.teams[1].members[2] = make_set(
        POKEMON_GEN3_SPECIES_ALAKAZAM, POKEMON_GEN3_MOVE_SPLASH,
        200, 100, 100, 100, 100, 90);
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    uint8_t old_active = battle.sides[1].active;
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].active != old_active);
    assert(battle.sides[1].active == 1 || battle.sides[1].active == 2);
    assert(draw_label_count(&battle, POKEMON_DRAW_FORCED_SWITCH_TARGET) == 1);
    assert(handler_event_count(&battle, POKEMON_HANDLER_EVENT_DRAG_OUT) == 0);
    /* The displaced member's queued Whirlwind must not be reinterpreted as
     * the incoming member's move. */
    assert(battle.sides[1].state[old_active].pp[0] == 32);
    assert(battle.sides[1].state[battle.sides[1].active].pp[0] == 64);
    uint8_t saw_drag_switch = 0;
    for (size_t i = 0; i < battle.event_count; i++) {
        if (battle.events[i].kind == POKEMON_EVENT_SWITCH &&
            battle.events[i].side == 1 &&
            battle.events[i].switch_cause == POKEMON_SWITCH_CAUSE_DRAG) {
            saw_drag_switch = 1;
        }
    }
    assert(saw_drag_switch);

    /* Showdown's sample consumes one draw even for a singleton candidate. */
    init.team_sizes[1] = 2;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].active == 1);
    assert(draw_label_count(&battle, POKEMON_DRAW_FORCED_SWITCH_TARGET) == 1);

    /* No eligible bench: forceSwitch never enters DragOut and owns no draw. */
    init.teams[1].members[0].move_ids[0] = POKEMON_GEN3_MOVE_SPLASH;
    init.team_sizes[1] = 1;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].active == 0);
    assert(draw_label_count(&battle, POKEMON_DRAW_FORCED_SWITCH_TARGET) == 0);
    assert(event_kind_count(&battle, POKEMON_EVENT_BLOCK) == 1);
    assert(battle.effect_trace_count == 1);
    assert(battle.effect_traces[0].kind == POKEMON_EFFECT_FORCE_SWITCH);
    assert(battle.effect_traces[0].result == POKEMON_EFFECT_FAILED);
    uint8_t saw_failed_roar = 0;
    for (size_t i = 0; i < battle.event_count; i++) {
        if (battle.events[i].kind == POKEMON_EVENT_MOVE &&
            battle.events[i].move_id == POKEMON_GEN3_MOVE_ROAR) {
            assert(battle.events[i].target_side == UINT8_MAX);
            saw_failed_roar = 1;
        }
    }
    assert(saw_failed_roar);

    /* A miss never reaches either DragOut gate or selection. */
    init.team_sizes[1] = 3;
    uint8_t observed_miss = 0;
    for (uint16_t tail = 1; tail < 256 && !observed_miss; tail++) {
        init.seed[3] = tail;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        battle.sides[0].state[0].boosts[POKEMON_STAT_ACCURACY] = -6;
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        observed_miss = event_kind_count(&battle, POKEMON_EVENT_MISS) != 0;
        if (observed_miss) {
            assert(battle.sides[1].active == 0);
            assert(draw_label_count(
                &battle, POKEMON_DRAW_FORCED_SWITCH_TARGET) == 0);
            assert(handler_event_count(
                &battle, POKEMON_HANDLER_EVENT_DRAG_OUT) == 0);
        }
    }
    assert(observed_miss);

    /* Ordered DragOut handlers are ordinary generated owner handlers. A
     * later null result cancels displacement without consuming selection
     * PRNG, and leaves the target's queued action intact. */
    enum { TEST_ABILITY = 62400, TEST_HIGH = 62401, TEST_CANCEL = 62402 };
    PokemonAbilityData ability = {
        .id = TEST_ABILITY, .handler_offset = 0, .handler_count = 2,
    };
    PokemonHandlerOp programs[] = {
        {POKEMON_HANDLER_OP_RETURN_TRUE, 0},
        {POKEMON_HANDLER_OP_RETURN_NULL, 0},
    };
    PokemonHandlerDescriptor handlers[] = {
        {
            .event = POKEMON_HANDLER_EVENT_DRAG_OUT, .id = TEST_HIGH,
            .source_kind = POKEMON_HANDLER_SOURCE_ABILITY,
            .source_id = TEST_ABILITY, .priority = 2,
            .program_offset = 0, .program_count = 1,
            .scope = POKEMON_HANDLER_SCOPE_TARGET,
            .route = POKEMON_HANDLER_ROUTE_OWNER, .raw_hook = "synthetic.high",
        },
        {
            .event = POKEMON_HANDLER_EVENT_DRAG_OUT, .id = TEST_CANCEL,
            .source_kind = POKEMON_HANDLER_SOURCE_ABILITY,
            .source_id = TEST_ABILITY, .priority = 1,
            .program_offset = 1, .program_count = 1,
            .scope = POKEMON_HANDLER_SCOPE_TARGET,
            .route = POKEMON_HANDLER_ROUTE_OWNER, .raw_hook = "synthetic.cancel",
        },
    };
    PokemonOwnerBindingIndex binding = {
        .owner_kind = POKEMON_OWNER_ABILITY, .owner_id = TEST_ABILITY,
        .event = POKEMON_HANDLER_EVENT_DRAG_OUT,
        .scope = POKEMON_HANDLER_SCOPE_TARGET,
        .route = POKEMON_HANDLER_ROUTE_OWNER,
        .binding_offset = 0, .binding_count = 2,
    };
    PokemonData data = POKEMON_GEN3_SLICE_DATA;
    PokemonMoveData moves[data.move_count];
    memcpy(moves, data.moves, sizeof(moves));
    for (size_t move_index = 0; move_index < data.move_count; move_index++) {
        moves[move_index].call_pool_id = 0;
    }
    data.moves = moves;
    data.abilities = &ability; data.ability_count = 1;
    data.handlers = handlers; data.handler_count = 2;
    data.handler_programs = programs; data.handler_program_count = 2;
    data.owner_binding_index = &binding; data.owner_binding_index_count = 1;
    data.move_call_pools = NULL; data.move_call_pool_count = 0;
    data.move_call_pool_candidates = NULL;
    data.move_call_pool_candidate_count = 0;
    data.constructed_hit_templates = NULL;
    data.constructed_hit_template_count = 0;
    data.move_pre_use_programs = NULL;
    data.move_pre_use_program_count = 0;
    PokemonResolvedBundle bundle = POKEMON_GEN3_OU_BUNDLE;
    PokemonFormatPolicy policy = *bundle.policy;
    policy.status_clauses = NULL;
    policy.status_clause_count = 0;
    bundle.policy = &policy;
    bundle.data = &data;
    init.team_sizes[1] = 3;
    init.teams[1].members[0].move_ids[0] = POKEMON_GEN3_MOVE_WHIRLWIND;
    init.bundle = &bundle;
    init.teams[1].members[0].ability_id = TEST_ABILITY;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].active == 0);
    assert(draw_label_count(&battle, POKEMON_DRAW_FORCED_SWITCH_TARGET) == 0);
    assert(handler_event_count(&battle, POKEMON_HANDLER_EVENT_DRAG_OUT) == 2);
    assert(event_kind_count(&battle, POKEMON_EVENT_BLOCK) == 2);
    assert(battle.handlers[0].handler.descriptor.id == TEST_HIGH);
    assert(battle.handlers[1].handler.descriptor.id == TEST_CANCEL);
    assert(battle.sides[1].state[0].pp[0] == 31);
}

static void test_generated_drag_blockers(void) {
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};

    /* Ingrain is installed through the ordinary primary-effect path before
     * Roar's negative-priority action. Its DragOut handler cancels before the
     * forced-switch candidate draw, TrapPokemon removes voluntary switches,
     * and its resolved Gen 3 residual heals baseMaxhp / 16. */
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_CRADILY, POKEMON_GEN3_MOVE_INGRAIN,
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_ROAR);
    init.team_sizes[0] = 2;
    init.team_sizes[1] = 1;
    init.teams[0].members[0].ability_id = POKEMON_GEN3_ABILITY_ROCKHEAD;
    init.teams[0].members[0].stats[0] = 320;
    init.initial_hp[0][0] = 200;
    init.teams[0].members[1] = make_set(
        POKEMON_GEN3_SPECIES_MACHOP, POKEMON_GEN3_MOVE_SPLASH,
        200, 100, 100, 100, 100, 80);
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].active == 0);
    assert(test_volatile_index(
        &battle.sides[0].state[0], POKEMON_VOLATILE_INGRAIN) >= 0);
    assert(battle.sides[0].state[0].hp == 220);
    assert(battle.request.legal_switches[0] == 0);
    assert(draw_label_count(&battle, POKEMON_DRAW_FORCED_SWITCH_TARGET) == 0);
    uint8_t saw_ingrain_drag = 0;
    uint8_t saw_ingrain_start = 0;
    uint8_t saw_ingrain_residual = 0;
    uint8_t saw_ingrain_trap = 0;
    for (size_t i = 0; i < battle.handler_count; i++) {
        uint16_t id = battle.handlers[i].handler.descriptor.id;
        saw_ingrain_drag |= id == POKEMON_GEN3_HANDLER_INGRAIN_DRAG_OUT;
        saw_ingrain_start |= id == POKEMON_GEN3_HANDLER_INGRAIN_START;
        saw_ingrain_residual |= id == POKEMON_GEN3_HANDLER_INGRAIN_RESIDUAL;
        saw_ingrain_trap |= id == POKEMON_GEN3_HANDLER_INGRAIN_TRAP_POKEMON;
    }
    assert(saw_ingrain_drag && saw_ingrain_start &&
        saw_ingrain_residual && saw_ingrain_trap);
    assert(pokemon_battle_check_invariants(&battle));

    /* Suction Cups is the higher-priority ability-owned DragOut veto. It
     * cancels before selection and does not require a volatile or move-ID
     * branch in generic control flow. */
    init = condition_init(
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_ROAR,
        POKEMON_GEN3_SPECIES_CRADILY, POKEMON_GEN3_MOVE_SPLASH);
    init.team_sizes[0] = 1;
    init.team_sizes[1] = 2;
    init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_SUCTIONCUPS;
    init.teams[1].members[1] = make_set(
        POKEMON_GEN3_SPECIES_MACHOP, POKEMON_GEN3_MOVE_SPLASH,
        200, 100, 100, 100, 100, 80);
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].active == 0);
    assert(draw_label_count(&battle, POKEMON_DRAW_FORCED_SWITCH_TARGET) == 0);
    assert(handler_event_count(&battle, POKEMON_HANDLER_EVENT_DRAG_OUT) == 1);
    assert(battle.handlers[0].handler.descriptor.id ==
        POKEMON_GEN3_HANDLER_SUCTION_CUPS_DRAG_OUT);
    assert(pokemon_battle_check_invariants(&battle));
}

static void test_confusion_damaging_secondaries_and_shield_dust(void) {
    static const uint16_t moves[] = {
        POKEMON_GEN3_MOVE_CONFUSION, POKEMON_GEN3_MOVE_PSYBEAM,
        POKEMON_GEN3_MOVE_SIGNALBEAM, POKEMON_GEN3_MOVE_DIZZYPUNCH,
        POKEMON_GEN3_MOVE_WATERPULSE, POKEMON_GEN3_MOVE_DYNAMICPUNCH,
    };
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    for (size_t i = 0; i < sizeof(moves) / sizeof(moves[0]); i++) {
        PokemonBattleInit init = condition_init(
            POKEMON_GEN3_SPECIES_GENGAR, moves[i],
            POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SPLASH);
        init.teams[1].members[0].stats[0] = 500;
        init.teams[1].members[0].stats[2] = 300;
        init.teams[1].members[0].stats[4] = 300;
        uint8_t installed = 0;
        for (uint16_t tail = 1; tail < 2048 && !installed; tail++) {
            init.seed[3] = tail;
            PokemonBattle battle;
            assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
            assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
            installed = test_volatile_index(
                &battle.sides[1].state[0], POKEMON_VOLATILE_CONFUSION) >= 0;
            if (installed) {
                assert(draw_label_count(&battle, POKEMON_DRAW_SECONDARY) == 1);
                assert(draw_label_count(
                    &battle, POKEMON_DRAW_CONFUSION_DURATION) == 1);
            }
        }
        assert(installed);
    }

    /* Shield Dust filters the target secondary before even a nominally 100%
     * secondary owns its chance draw. */
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_GENGAR, POKEMON_GEN3_MOVE_DYNAMICPUNCH,
        POKEMON_GEN3_SPECIES_DUSTOX, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_SHIELDDUST;
    init.teams[1].members[0].stats[0] = 500;
    init.teams[1].members[0].stats[2] = 300;
    init.teams[1].members[0].stats[4] = 300;
    uint8_t observed_filter = 0;
    for (uint16_t tail = 1; tail < 2048 && !observed_filter; tail++) {
        init.seed[3] = tail;
        PokemonBattle battle;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        for (size_t handler = 0; handler < battle.handler_count; handler++) {
            observed_filter |= battle.handlers[handler].handler.descriptor.id ==
                POKEMON_GEN3_HANDLER_SHIELD_DUST_MODIFY_SECONDARIES;
        }
        if (observed_filter) {
            assert(draw_label_count(&battle, POKEMON_DRAW_SECONDARY) == 0);
            assert(draw_label_count(
                &battle, POKEMON_DRAW_CONFUSION_DURATION) == 0);
            assert(test_volatile_index(&battle.sides[1].state[0],
                POKEMON_VOLATILE_CONFUSION) < 0);
        }
    }
    assert(observed_filter);

    /* Own Tempo is later: chance is consumed, TryAddVolatile cancels, and
     * duration/Start never occur. */
    init = condition_init(
        POKEMON_GEN3_SPECIES_GENGAR, POKEMON_GEN3_MOVE_CONFUSION,
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_OWNTEMPO;
    init.teams[1].members[0].stats[0] = 500;
    init.teams[1].members[0].stats[2] = 300;
    init.teams[1].members[0].stats[4] = 300;
    uint8_t observed_cancel = 0;
    for (uint16_t tail = 1; tail < 2048 && !observed_cancel; tail++) {
        init.seed[3] = tail;
        PokemonBattle battle;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        for (size_t handler = 0; handler < battle.handler_count; handler++) {
            observed_cancel |= battle.handlers[handler].handler.descriptor.id ==
                POKEMON_GEN3_HANDLER_OWN_TEMPO_TRY_ADD_VOLATILE;
        }
        if (observed_cancel) {
            assert(draw_label_count(&battle, POKEMON_DRAW_SECONDARY) == 1);
            assert(draw_label_count(
                &battle, POKEMON_DRAW_CONFUSION_DURATION) == 0);
            assert(test_volatile_index(&battle.sides[1].state[0],
                POKEMON_VOLATILE_CONFUSION) < 0);
        }
    }
    assert(observed_cancel);
}

static void test_flinch_secondary_family_and_inner_focus(void) {
    static const uint16_t moves[] = {
        POKEMON_GEN3_MOVE_ASTONISH, POKEMON_GEN3_MOVE_EXTRASENSORY,
        POKEMON_GEN3_MOVE_NEEDLEARM, POKEMON_GEN3_MOVE_BONECLUB,
        POKEMON_GEN3_MOVE_HYPERFANG, POKEMON_GEN3_MOVE_ROLLINGKICK,
        POKEMON_GEN3_MOVE_BITE, POKEMON_GEN3_MOVE_HEADBUTT,
        POKEMON_GEN3_MOVE_ROCKSLIDE, POKEMON_GEN3_MOVE_STOMP,
        POKEMON_GEN3_MOVE_TWISTER,
    };
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    for (size_t move_index = 0;
         move_index < sizeof(moves) / sizeof(moves[0]); move_index++) {
        PokemonBattleInit init = condition_init(
            POKEMON_GEN3_SPECIES_SMEARGLE, moves[move_index],
            POKEMON_GEN3_SPECIES_GOLEM, POKEMON_GEN3_MOVE_SPLASH);
        init.initial_status[1][0] = POKEMON_STATUS_PARALYSIS;
        init.teams[1].members[0].stats[0] = 5000;
        init.teams[1].members[0].stats[2] = 1000;
        uint8_t observed = 0;
        for (uint16_t tail = 1; tail < 4096 && !observed; tail++) {
            init.seed[3] = tail;
            PokemonBattle battle;
            assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
            assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
            for (size_t handler = 0; handler < battle.handler_count; handler++) {
                observed |= battle.handlers[handler].handler.descriptor.id ==
                    POKEMON_GEN3_HANDLER_FLINCH_BEFORE_MOVE;
            }
            if (!observed) continue;
            assert(draw_label_count(&battle, POKEMON_DRAW_SECONDARY) == 1);
            /* Flinch priority 8 cancels before paralysis priority 1 can own a
             * draw.  Duration one then expires during this turn's Residual. */
            assert(draw_label_count(&battle, POKEMON_DRAW_PARALYSIS) == 0);
            assert(battle.sides[1].state[0].last_move_id == 0);
            assert(test_volatile_index(&battle.sides[1].state[0],
                POKEMON_VOLATILE_FLINCH) < 0);
            uint8_t added = 0, removed = 0;
            for (size_t trace = 0; trace < battle.condition_trace_count; trace++) {
                const PokemonConditionTrace *condition =
                    &battle.condition_traces[trace];
                if (condition->scope != POKEMON_CONDITION_SCOPE_VOLATILE ||
                    condition->condition_id != POKEMON_VOLATILE_FLINCH) continue;
                added |= condition->operation == POKEMON_CONDITION_ADD;
                removed |= condition->operation == POKEMON_CONDITION_REMOVE;
            }
            assert(added && removed);
        }
        assert(observed);
    }

    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_BITE,
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_INNERFOCUS;
    init.teams[1].members[0].stats[0] = 5000;
    init.teams[1].members[0].stats[2] = 1000;
    uint8_t prevented = 0;
    for (uint16_t tail = 1; tail < 4096 && !prevented; tail++) {
        init.seed[3] = tail;
        PokemonBattle battle;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        for (size_t handler = 0; handler < battle.handler_count; handler++) {
            prevented |= battle.handlers[handler].handler.descriptor.id ==
                POKEMON_GEN3_HANDLER_INNER_FOCUS_TRY_ADD_VOLATILE;
        }
        if (!prevented) continue;
        assert(draw_label_count(&battle, POKEMON_DRAW_SECONDARY) == 1);
        assert(test_volatile_index(&battle.sides[1].state[0],
            POKEMON_VOLATILE_FLINCH) < 0);
        assert(battle.sides[1].state[0].last_move_id ==
            POKEMON_GEN3_MOVE_SPLASH);
    }
    assert(prevented);
}

static void test_fake_out_selected_action_counter(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_FAKEOUT,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[1].members[0].stats[0] = 5000;
    init.teams[1].members[0].stats[2] = 1000;
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(battle.sides[0].state[0].active_move_actions == 0);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].active_move_actions == 1);
    assert(draw_label_count(&battle, POKEMON_DRAW_SECONDARY) == 1);
    uint16_t after_first = battle.sides[1].state[0].hp;
    assert(after_first < battle.sides[1].sets[0].stats[0]);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].active_move_actions == 2);
    assert(battle.sides[1].state[0].hp == after_first);
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 0);
    assert(draw_label_count(&battle, POKEMON_DRAW_SECONDARY) == 0);

    /* A selected action increments before BeforeMove. A flinch-aborted first
     * attempt therefore consumes Fake Out eligibility without consuming PP. */
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    PokemonMutable *user = &battle.sides[0].state[0];
    user->volatiles[user->volatile_count++] = (PokemonVolatileState){
        .kind = POKEMON_VOLATILE_FLINCH,
        .descriptor_id = POKEMON_GEN3_CONDITION_VOLATILE_FLINCH,
        .state_generation = 1,
        .effect_order = ++battle.next_holder_effect_order,
        .duration = 1,
    };
    uint8_t pp = user->pp[0];
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(user->active_move_actions == 1 && user->pp[0] == pp);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(user->active_move_actions == 2 && user->pp[0] == (uint8_t)(pp - 1));
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 0);
}

static void test_follow_me_singles_try_rejection(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_FOLLOWME,
        POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_SPLASH);
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    uint8_t pp = battle.sides[0].state[0].pp[0];
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].pp[0] == (uint8_t)(pp - 1));
    assert(battle.sides[0].state[0].last_move_id == POKEMON_GEN3_MOVE_FOLLOWME);
    assert(battle.hit_trace_count == 0);
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 0);
    assert(battle.handler_count >= 1);
    uint8_t found_try = 0;
    for (size_t i = 0; i < battle.handler_count; i++) {
        found_try |= battle.handlers[i].handler.descriptor.id ==
            POKEMON_GEN3_HANDLER_FOLLOW_ME_TRY;
    }
    assert(found_try);
    for (size_t i = 0; i < battle.condition_trace_count; i++) {
        assert(battle.condition_traces[i].condition_id !=
            POKEMON_GEN3_CONDITION_SLOT_FOLLOWME);
    }
    assert(pokemon_battle_check_invariants(&battle));
}

static void test_declarative_move_try_rejection(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_TELEPORT,
        POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_SPLASH);
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    uint8_t pp = battle.sides[0].state[0].pp[0];
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].pp[0] == (uint8_t)(pp - 1));
    assert(battle.sides[0].state[0].last_move_id == POKEMON_GEN3_MOVE_TELEPORT);
    assert(battle.sides[0].active == 0);
    assert(battle.hit_trace_count == 0);
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 0);
    uint8_t found_try = 0;
    for (size_t i = 0; i < battle.handler_count; i++) {
        found_try |= battle.handlers[i].handler.descriptor.id ==
            POKEMON_GEN3_HANDLER_TELEPORT_TRY;
    }
    assert(found_try);
    assert(pokemon_battle_check_invariants(&battle));
}

static uint16_t target_move_damage(const PokemonBattle *battle) {
    uint16_t total = 0;
    for (size_t i = 0; i < battle->event_count; i++) {
        if (battle->events[i].kind == POKEMON_EVENT_DAMAGE &&
            battle->events[i].side == 1) {
            total = (uint16_t)(total + battle->events[i].amount);
        }
    }
    return total;
}

static void test_happiness_base_power_policies(void) {
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_RETURN,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SOFTBOILED);
    init.teams[1].members[0].stats[0] = 5000;
    init.teams[0].members[0].stats[1] = 1000;
    init.teams[1].members[0].stats[2] = 100;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(battle.sides[0].sets[0].happiness == 255);
    assert(battle.sides[0].sets[0].happiness_specified == 1);

    init.teams[0].members[0].happiness_specified = 1;
    init.teams[0].members[0].happiness = 0;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    uint16_t return_zero = target_move_damage(&battle);

    init.teams[0].members[0].move_ids[0] = POKEMON_GEN3_MOVE_FRUSTRATION;
    init.teams[0].members[0].happiness = 255;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(target_move_damage(&battle) == return_zero);

    init.teams[0].members[0].move_ids[0] = POKEMON_GEN3_MOVE_RETURN;
    init.teams[0].members[0].happiness = 128;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    uint16_t return_midpoint = target_move_damage(&battle);
    init.teams[0].members[0].move_ids[0] = POKEMON_GEN3_MOVE_FRUSTRATION;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(return_midpoint > target_move_damage(&battle));

    init.teams[0].members[0].happiness_specified = 2;
    PokemonBattle untouched;
    memset(&untouched, 0xa5, sizeof(untouched));
    PokemonBattle before = untouched;
    assert(pokemon_battle_init(&untouched, &init) ==
        POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&untouched, &before, sizeof(untouched)) == 0);
}

static void test_personal_move_profile_hidden_power(void) {
    static const struct {
        uint8_t ivs[6];
        uint8_t type;
        PokemonCategory category;
        uint8_t power;
    } vectors[] = {
        {{28, 28, 28, 28, 28, 28}, POKEMON_GEN3_TYPE_FIGHTING,
            POKEMON_CATEGORY_PHYSICAL, 30},
        {{30, 30, 30, 30, 30, 30}, POKEMON_GEN3_TYPE_FIGHTING,
            POKEMON_CATEGORY_PHYSICAL, 70},
        {{29, 29, 29, 29, 29, 29}, POKEMON_GEN3_TYPE_DARK,
            POKEMON_CATEGORY_SPECIAL, 30},
        {{31, 31, 31, 31, 31, 31}, POKEMON_GEN3_TYPE_DARK,
            POKEMON_CATEGORY_SPECIAL, 70},
        {{30, 30, 30, 31, 30, 30}, POKEMON_GEN3_TYPE_GROUND,
            POKEMON_CATEGORY_PHYSICAL, 70},
        {{30, 30, 30, 31, 31, 30}, POKEMON_GEN3_TYPE_ELECTRIC,
            POKEMON_CATEGORY_SPECIAL, 70},
    };
    for (size_t i = 0; i < sizeof(vectors) / sizeof(vectors[0]); i++) {
        PokemonPersonalMoveProfile profile = {0};
        assert(POKEMON_GEN3_RULES.resolve_personal_move_profile(
            1, vectors[i].ivs, &profile) == POKEMON_OK);
        assert(profile.kind == 1 && profile.type == vectors[i].type);
        assert(profile.category == vectors[i].category);
        assert(profile.power == vectors[i].power);
    }

    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_HIDDENPOWER,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SOFTBOILED);
    init.teams[0].members[0].stats[1] = 1000;
    init.teams[0].members[0].stats[3] = 1000;
    init.teams[1].members[0].stats[0] = 5000;
    init.teams[1].members[0].stats[2] = 200;
    init.teams[1].members[0].stats[4] = 200;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    const PokemonPersonalMoveProfile *profile =
        &battle.sides[0].state[0].personal_move_profile;
    assert(profile->kind == 1 && profile->type == POKEMON_GEN3_TYPE_DARK);
    assert(profile->category == POKEMON_CATEGORY_SPECIAL && profile->power == 70);
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    uint8_t saw_modify = 0;
    for (size_t i = 0; i < battle.handler_count; i++) {
        saw_modify |= battle.handlers[i].handler.descriptor.id ==
            POKEMON_GEN3_HANDLER_HIDDEN_POWER_MODIFY_MOVE;
    }
    assert(saw_modify && target_move_damage(&battle) > 0);

    /* The constructed move still enters the ordinary immunity boundary,
     * which removes the target before accuracy, critical, or damage draws. */
    init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_HIDDENPOWER,
        POKEMON_GEN3_SPECIES_GOLEM, POKEMON_GEN3_MOVE_SPLASH);
    static const uint8_t electric_ivs[6] = {30, 30, 30, 31, 31, 30};
    memcpy(init.teams[0].members[0].ivs, electric_ivs, sizeof(electric_ivs));
    init.teams[0].members[0].ivs_specified = 1;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(battle.sides[0].state[0].personal_move_profile.type ==
        POKEMON_GEN3_TYPE_ELECTRIC);
    uint16_t hp = battle.sides[1].state[0].hp;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].state[0].hp == hp);
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 1);
    assert(draw_label_count(&battle, POKEMON_DRAW_CRITICAL) == 0);
    assert(draw_label_count(&battle, POKEMON_DRAW_DAMAGE_ROLL) == 0);

    init.teams[0].members[0].ivs[0] = 32;
    PokemonBattle untouched;
    memset(&untouched, 0xa5, sizeof(untouched));
    PokemonBattle before = untouched;
    assert(pokemon_battle_init(&untouched, &init) ==
        POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&untouched, &before, sizeof(untouched)) == 0);
}

static void test_kings_rock_appended_secondary_pipeline(void) {
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_TACKLE,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SOFTBOILED);
    init.teams[0].members[0].item_id = POKEMON_GEN3_ITEM_KINGSROCK;
    init.teams[1].members[0].stats[0] = 5000;
    init.teams[1].members[0].stats[2] = 1000;
    init.seed[0] = 313;
    init.seed[1] = 197;
    init.seed[2] = 83;
    PokemonBattle battle;
    uint8_t saw_item_handler = 0, saw_flinch = 0;
    for (uint16_t tail = 1; tail < 4096 && !saw_flinch; tail++) {
        init.seed[3] = tail;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        if (draw_label_count(&battle, POKEMON_DRAW_SECONDARY) != 1) continue;
        for (size_t i = 0; i < battle.handler_count; i++) {
            uint16_t id = battle.handlers[i].handler.descriptor.id;
            saw_item_handler |=
                id == POKEMON_GEN3_HANDLER_KINGS_ROCK_MODIFY_MOVE;
            saw_flinch |= id == POKEMON_GEN3_HANDLER_FLINCH_BEFORE_MOVE;
        }
    }
    assert(saw_item_handler && saw_flinch);

    /* A failed appended secondary still owns exactly one labeled draw. */
    uint8_t saw_failed_roll = 0;
    for (uint16_t tail = 1; tail < 4096 && !saw_failed_roll; tail++) {
        init.seed[3] = tail;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        if (draw_label_count(&battle, POKEMON_DRAW_SECONDARY) != 1) continue;
        saw_flinch = 0;
        for (size_t i = 0; i < battle.handler_count; i++) {
            saw_flinch |= battle.handlers[i].handler.descriptor.id ==
                POKEMON_GEN3_HANDLER_FLINCH_BEFORE_MOVE;
        }
        saw_failed_roll = !saw_flinch;
    }
    assert(saw_failed_roll);

    /* ModifySecondaries removes the item-appended effect before its owner can
     * consume a draw. */
    init.teams[1].members[0].species_id = POKEMON_GEN3_SPECIES_DUSTOX;
    init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_SHIELDDUST;
    init.teams[1].members[0].move_ids[0] = POKEMON_GEN3_MOVE_MOONLIGHT;
    init.seed[3] = 14;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(draw_label_count(&battle, POKEMON_DRAW_SECONDARY) == 0);

    /* Appended secondaries live on the active move frame, so a multihit move
     * resolves them once per connected hit rather than once per action. */
    init.teams[1].members[0].species_id = POKEMON_GEN3_SPECIES_BLISSEY;
    init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_NATURALCURE;
    init.teams[1].members[0].move_ids[0] = POKEMON_GEN3_MOVE_SOFTBOILED;
    init.teams[0].members[0].move_ids[0] = POKEMON_GEN3_MOVE_ARMTHRUST;
    init.seed[3] = 1;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(draw_label_count(&battle, POKEMON_DRAW_MULTIHIT_COUNT) == 1);
    assert(draw_label_count(&battle, POKEMON_DRAW_SECONDARY) == 3);
    saw_flinch = 0;
    for (size_t i = 0; i < battle.handler_count; i++) {
        saw_flinch |= battle.handlers[i].handler.descriptor.id ==
            POKEMON_GEN3_HANDLER_FLINCH_BEFORE_MOVE;
    }
    assert(saw_flinch);

    /* King's Rock priority -1 appends before Serene Grace priority -2.  This
     * seed's secondary roll is 18: it succeeds only after the generated
     * ability policy doubles the appended chance from 10 to 20. */
    init.teams[0].members[0].species_id = POKEMON_GEN3_SPECIES_JIRACHI;
    init.teams[0].members[0].ability_id = POKEMON_GEN3_ABILITY_SERENEGRACE;
    init.teams[0].members[0].move_ids[0] = POKEMON_GEN3_MOVE_AERIALACE;
    init.seed[3] = 4;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(draw_label_count(&battle, POKEMON_DRAW_SECONDARY) == 1);
    saw_flinch = 0;
    for (size_t i = 0; i < battle.handler_count; i++) {
        saw_flinch |= battle.handlers[i].handler.descriptor.id ==
            POKEMON_GEN3_HANDLER_FLINCH_BEFORE_MOVE;
    }
    assert(saw_flinch);
}

static void test_shell_bell_actual_move_damage_transaction(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_TACKLE,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SOFTBOILED);
    init.teams[0].members[0].item_id = POKEMON_GEN3_ITEM_SHELLBELL;
    init.teams[0].members[0].stats[0] = 301;
    init.initial_hp[0][0] = 100;
    init.teams[1].members[0].stats[0] = 5000;
    init.teams[1].members[0].stats[2] = 1000;
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    uint16_t dealt = 0;
    for (size_t i = 0; i < battle.event_count; i++) {
        if (battle.events[i].kind == POKEMON_EVENT_DAMAGE &&
            battle.events[i].side == 1 &&
            battle.events[i].move_id == POKEMON_GEN3_MOVE_TACKLE) {
            dealt = (uint16_t)(dealt + battle.events[i].amount);
        }
    }
    assert(dealt != 0);
    uint16_t expected = (uint16_t)(dealt / 8u);
    if (expected == 0) expected = 1;
    assert(battle.sides[0].state[0].hp == (uint16_t)(100 + expected));

    /* Damage absorbed by Substitute is not move.totalDamage and cannot heal. */
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    PokemonMutable *target = &battle.sides[1].state[0];
    target->volatiles[target->volatile_count++] = (PokemonVolatileState){
        .kind = POKEMON_VOLATILE_SUBSTITUTE,
        .descriptor_id = POKEMON_GEN3_CONDITION_VOLATILE_SUBSTITUTE,
        .state_generation = 1,
        .effect_order = ++battle.next_holder_effect_order,
        .payload.substitute.hp = 200,
    };
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].hp == 100);

    /* A multihit invocation aggregates real damage and heals once. */
    init.teams[0].members[0].move_ids[0] = POKEMON_GEN3_MOVE_ARMTHRUST;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    dealt = 0;
    size_t heals = 0;
    for (size_t i = 0; i < battle.event_count; i++) {
        if (battle.events[i].kind == POKEMON_EVENT_DAMAGE &&
            battle.events[i].side == 1 &&
            battle.events[i].move_id == POKEMON_GEN3_MOVE_ARMTHRUST) {
            dealt = (uint16_t)(dealt + battle.events[i].amount);
        }
        heals += battle.events[i].kind == POKEMON_EVENT_HEAL &&
            battle.events[i].side == 0;
    }
    expected = (uint16_t)(dealt / 8u);
    if (expected == 0 && dealt != 0) expected = 1;
    assert(dealt != 0 && heals == 1);
    assert(battle.sides[0].state[0].hp == (uint16_t)(100 + expected));

    /* Overkill contributes only the target's remaining real HP. */
    init.teams[0].members[0].move_ids[0] = POKEMON_GEN3_MOVE_TACKLE;
    init.initial_hp[1][0] = 1;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].hp == 101);

    /* A full holder still runs the transaction but emits no dishonest heal. */
    init.initial_hp[1][0] = 0;
    init.initial_hp[0][0] = 301;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    heals = 0;
    for (size_t i = 0; i < battle.event_count; i++) {
        heals += battle.events[i].kind == POKEMON_EVENT_HEAL &&
            battle.events[i].side == 0;
    }
    assert(heals == 0 && battle.sides[0].state[0].hp == 301);

    /* Recoil resolves before this event; a fainted holder cannot be revived. */
    init.teams[0].members[0].move_ids[0] = POKEMON_GEN3_MOVE_DOUBLEEDGE;
    init.initial_hp[0][0] = 1;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    heals = 0;
    for (size_t i = 0; i < battle.event_count; i++) {
        heals += battle.events[i].kind == POKEMON_EVENT_HEAL &&
            battle.events[i].side == 0;
    }
    assert(heals == 0 && battle.sides[0].state[0].hp == 0);
}

static void test_toxic_lifecycle_and_immunity(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_GENGAR, POKEMON_GEN3_MOVE_TOXIC,
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_TACKLE
    );
    PokemonBattle battle;
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    int applied = 0;
    for (uint16_t tail = 1; tail < 64 && !applied; tail++) {
        init.seed[3] = tail;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        applied = battle.sides[1].state[0].status.kind == POKEMON_STATUS_TOXIC;
    }
    assert(applied);
    uint16_t maximum_hp = battle.sides[1].sets[0].stats[0];
    assert(battle.sides[1].state[0].status.kind == POKEMON_STATUS_TOXIC);
    assert(battle.sides[1].state[0].status.state.toxic.stage == 1);
    assert(battle.sides[1].state[0].hp == maximum_hp - maximum_hp / 16u);
    assert(battle.residual_count == 1);
    assert(battle.residuals[0].order == 10);

    init = condition_init(
        POKEMON_GEN3_SPECIES_GENGAR, POKEMON_GEN3_MOVE_TOXIC,
        POKEMON_GEN3_SPECIES_VENUSAUR, POKEMON_GEN3_MOVE_TACKLE
    );
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].state[0].status.kind == POKEMON_STATUS_NONE);
}

static void test_generated_status_residual_policy_family(void) {
    const PokemonData *data = &POKEMON_GEN3_SLICE_DATA;
    assert(data->status_residual_policy_count == 3);
    const struct {
        uint16_t descriptor_id;
        PokemonStatus status;
        PokemonResidualFormula formula;
        PokemonStatusResidualStatePolicy state_policy;
    } expected[] = {
        {POKEMON_GEN3_CONDITION_STATUS_BRN, POKEMON_STATUS_BURN,
            POKEMON_RESIDUAL_FORMULA_BURN, POKEMON_STATUS_RESIDUAL_STATELESS},
        {POKEMON_GEN3_CONDITION_STATUS_PSN, POKEMON_STATUS_POISON,
            POKEMON_RESIDUAL_FORMULA_POISON, POKEMON_STATUS_RESIDUAL_TICK},
        {POKEMON_GEN3_CONDITION_STATUS_TOX, POKEMON_STATUS_TOXIC,
            POKEMON_RESIDUAL_FORMULA_TOXIC,
            POKEMON_STATUS_RESIDUAL_ESCALATE},
    };
    for (size_t i = 0; i < sizeof(expected) / sizeof(expected[0]); i++) {
        const PokemonStatusResidualPolicy *policy =
            &data->status_residual_policies[i];
        assert(policy->descriptor_id == expected[i].descriptor_id);
        assert(policy->status == expected[i].status);
        assert(policy->formula == expected[i].formula);
        assert(policy->state_policy == expected[i].state_policy);
    }

    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    const PokemonStatus ordinary[] = {
        POKEMON_STATUS_BURN, POKEMON_STATUS_POISON,
    };
    for (size_t i = 0; i < sizeof(ordinary) / sizeof(ordinary[0]); i++) {
        PokemonBattleInit init = condition_init(
            POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_SPLASH,
            POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_SPLASH);
        init.teams[0].members[0].stats[0] = 301;
        init.initial_status[0][0] = ordinary[i];
        PokemonBattle battle;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        assert(battle.sides[0].state[0].hp == 301 - 301 / 8);
        assert(battle.residual_count == 1);
        assert(battle.residuals[0].order == 10);
        assert(battle.residuals[0].sub_order == 6);
        assert(battle.residuals[0].condition_id == ordinary[i]);
    }

    PokemonBattleInit toxic = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_SPLASH,
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_SPLASH);
    toxic.teams[0].members[0].stats[0] = 401;
    toxic.initial_status[0][0] = POKEMON_STATUS_TOXIC;
    toxic.initial_toxic_stage[0][0] = 15;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &toxic) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].status.state.toxic.stage == 1);
    assert(battle.sides[0].state[0].hp == 401 - 401 / 16);
    battle.sides[0].state[0].status.state.toxic.stage = 15;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].status.state.toxic.stage == 15);
    assert(battle.sides[0].state[0].hp == 1);

    PokemonStatusResidualPolicy malformed_policies[3];
    memcpy(malformed_policies, data->status_residual_policies,
        sizeof(malformed_policies));
    malformed_policies[1].descriptor_id = malformed_policies[0].descriptor_id;
    PokemonData malformed_data = *data;
    malformed_data.status_residual_policies = malformed_policies;
    PokemonResolvedBundle malformed_bundle = *toxic.bundle;
    malformed_bundle.data = &malformed_data;
    toxic.bundle = &malformed_bundle;
    PokemonBattle before;
    memset(&before, 0xa5, sizeof(before));
    battle = before;
    assert(pokemon_battle_init(&battle, &toxic) ==
        POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&battle, &before, sizeof(battle)) == 0);
}

static void test_sandstorm_duration_and_residual_order(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_MAROWAK, POKEMON_GEN3_MOVE_SANDSTORM,
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_TACKLE
    );
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    uint16_t left_hp = battle.sides[0].state[0].hp;
    uint16_t right_hp = battle.sides[1].state[0].hp;
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.field.weather.kind == POKEMON_WEATHER_SANDSTORM);
    assert(battle.field.weather.state_generation == 1);
    assert(battle.field.weather.effect_order == 0);
    assert(battle.field.weather.duration == 4);
    assert(battle.sides[0].state[0].hp < left_hp); /* Tackle, but no sand. */
    assert(battle.sides[1].state[0].hp == right_hp - right_hp / 16u);
    assert(battle.residuals[0].kind == POKEMON_RESIDUAL_WEATHER);
    assert(battle.residuals[0].order == 8);
    assert(battle.residuals[0].weather_event_dispatched);
    uint16_t hp_after_first = battle.sides[1].state[0].hp;
    for (size_t turn = 0; turn < 3; turn++) {
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    }
    assert(battle.field.weather.kind == POKEMON_WEATHER_SANDSTORM);
    assert(battle.field.weather.duration == 1);
    assert(battle.sides[1].state[0].hp ==
        hp_after_first - 3u * (right_hp / 16u));
    uint16_t hp_before_expiry = battle.sides[1].state[0].hp;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.field.weather.kind == POKEMON_WEATHER_NONE);
    assert(battle.field.weather.state_generation == 0);
    assert(battle.field.weather.effect_order == 0);
    assert(battle.sides[1].state[0].hp == hp_before_expiry);

    /* A field weather event damages every active before draining its faint
     * batch. Do not interleave the first faint with the second target's
     * damage. */
    init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_SANDSTORM,
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SPLASH);
    init.initial_hp[0][0] = 1;
    init.initial_hp[1][0] = 1;
    init.initial_status[0][0] = POKEMON_STATUS_TOXIC;
    init.initial_status[1][0] = POKEMON_STATUS_TOXIC;
    init.initial_toxic_stage[0][0] = 1;
    init.initial_toxic_stage[1][0] = 1;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    uint8_t left_toxic_stage =
        battle.sides[0].state[0].status.state.toxic.stage;
    uint8_t right_toxic_stage =
        battle.sides[1].state[0].status.state.toxic.stage;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    size_t damage_count = 0;
    size_t faint_count = 0;
    size_t last_damage = 0;
    size_t first_faint = SIZE_MAX;
    for (size_t i = 0; i < battle.event_count; i++) {
        if (battle.events[i].kind == POKEMON_EVENT_DAMAGE) {
            damage_count++;
            last_damage = i;
        } else if (battle.events[i].kind == POKEMON_EVENT_FAINT) {
            faint_count++;
            if (first_faint == SIZE_MAX) first_faint = i;
        }
    }
    assert(damage_count == 2);
    assert(faint_count == 2);
    assert(last_damage < first_faint);
    assert(battle.sides[0].state[0].status.state.toxic.stage ==
        left_toxic_stage);
    assert(battle.sides[1].state[0].status.state.toxic.stage ==
        right_toxic_stage);
}

static void test_generic_weather_install_replace_and_expire(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_STARMIE, POKEMON_GEN3_MOVE_RAINDANCE,
        POKEMON_GEN3_SPECIES_SKARMORY, POKEMON_GEN3_MOVE_SPLASH
    );
    init.teams[0].members[0].move_ids[1] = POKEMON_GEN3_MOVE_SUNNYDAY;
    init.teams[0].members[0].move_ids[2] = POKEMON_GEN3_MOVE_HAIL;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.field.weather.kind == POKEMON_WEATHER_RAIN);
    assert(battle.field.weather.duration == 4);
    uint16_t rain_generation = battle.field.weather.state_generation;

    choices[0] = move(1);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.field.weather.kind == POKEMON_WEATHER_SUN);
    assert(battle.field.weather.duration == 4);
    assert(battle.field.weather.state_generation > rain_generation);

    choices[0] = move(2);
    uint16_t foe_hp = battle.sides[1].state[0].hp;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.field.weather.kind == POKEMON_WEATHER_HAIL);
    assert(battle.sides[1].state[0].hp == foe_hp - foe_hp / 16u);
    choices[0] = move(0);
    for (size_t turn = 0; turn < 5; turn++) {
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    }
    /* Rain replaces Hail on the first loop iteration, then a repeated Rain
     * fails without refreshing its original five-turn lifetime. */
    assert(battle.field.weather.kind == POKEMON_WEATHER_NONE);
}

static uint16_t weather_surf_damage(
    PokemonWeatherKind weather, uint32_t expected_modifier
) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_STARMIE, POKEMON_GEN3_MOVE_SURF,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SPLASH);
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    battle.field.weather = (PokemonWeatherState){
        .kind = weather,
        .descriptor_id = battle.generation->condition_descriptor(
            POKEMON_OWNER_FIELD, weather),
        .duration = 5, .source_side = 0, .source_slot = 0,
        .state_generation = 1,
    };
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.modifier_count == 1);
    assert(battle.modifiers[0].handler.descriptor.event ==
        POKEMON_HANDLER_EVENT_WEATHER_MODIFY_DAMAGE);
    assert(battle.modifiers[0].modifier_q12 == expected_modifier);
    uint16_t weather_result = 0;
    for (size_t i = 0; i < battle.relay_result_count; i++) {
        if (battle.relay_results[i].event ==
                POKEMON_HANDLER_EVENT_WEATHER_MODIFY_DAMAGE) {
            weather_result = (uint16_t)battle.relay_results[i].output;
        }
    }
    assert(weather_result != 0);
    return weather_result;
}

static void test_weather_modify_damage_event_and_gen3_stage(void) {
    assert(POKEMON_GEN3_RULES.weather_damage_stage ==
        POKEMON_WEATHER_DAMAGE_BEFORE_FINAL_BASE_OFFSET);
    uint16_t rain = weather_surf_damage(POKEMON_WEATHER_RAIN, 6144);
    uint16_t sun = weather_surf_damage(POKEMON_WEATHER_SUN, 2048);
    assert(rain > sun);
}

static void test_cloud_nine_suppresses_effective_not_stored_weather(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_STARMIE, POKEMON_GEN3_MOVE_SURF,
        POKEMON_GEN3_SPECIES_GOLDUCK, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_CLOUDNINE;
    init.teams[1].members[0].stats[0] = 301;
    init.teams[1].members[0].stats[1] = 200;
    init.teams[1].members[0].stats[2] = 192;
    init.teams[1].members[0].stats[3] = 226;
    init.teams[1].members[0].stats[4] = 196;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    battle.field.weather = (PokemonWeatherState){
        .kind = POKEMON_WEATHER_RAIN,
        .descriptor_id = battle.generation->condition_descriptor(
            POKEMON_OWNER_FIELD, POKEMON_WEATHER_RAIN),
        .duration = 5, .source_side = 0, .source_slot = 0,
        .state_generation = 1,
    };
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.field.weather.kind == POKEMON_WEATHER_RAIN);
    assert(battle.field.weather.duration == 4);
    assert(battle.residual_count == 1);
    assert(!battle.residuals[0].weather_event_dispatched);
    assert(battle.modifier_count == 1);
    assert(battle.modifiers[0].handler.descriptor.event ==
        POKEMON_HANDLER_EVENT_WEATHER_MODIFY_DAMAGE);
    assert(battle.modifiers[0].invoked == 0);
    assert(battle.modifiers[0].modifier_q12 == 4096);
    assert(battle.modifiers[0].modifier_before_q12 == 4096);
    assert(battle.modifiers[0].modifier_after_q12 == 4096);
}

static void test_weather_status_immunity_is_generated_and_suppressible(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SPLASH,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SPLASH);
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    battle.field.weather = (PokemonWeatherState){
        .kind = POKEMON_WEATHER_SUN,
        .descriptor_id = battle.generation->condition_descriptor(
            POKEMON_OWNER_FIELD, POKEMON_WEATHER_SUN),
        .duration = 5, .state_generation = 1,
    };
    PokemonEntityRef target = {POKEMON_ENTITY_POKEMON, 1, 0};
    PokemonEntityRef source = {POKEMON_ENTITY_POKEMON, 0, 0};
    PokemonSourceEffectRef effect = {
        POKEMON_SOURCE_EFFECT_MOVE, POKEMON_GEN3_MOVE_ICEBEAM};
    uint8_t applied = 99;
    assert(pokemon_set_status(
        &battle, target, POKEMON_STATUS_FREEZE, source, effect,
        1, &applied) == POKEMON_OK);
    assert(!applied);

    init.teams[0].members[0].ability_id = POKEMON_GEN3_ABILITY_CLOUDNINE;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    battle.field.weather = (PokemonWeatherState){
        .kind = POKEMON_WEATHER_SUN,
        .descriptor_id = battle.generation->condition_descriptor(
            POKEMON_OWNER_FIELD, POKEMON_WEATHER_SUN),
        .duration = 5, .state_generation = 1,
    };
    assert(pokemon_set_status(
        &battle, target, POKEMON_STATUS_FREEZE, source, effect,
        1, &applied) == POKEMON_OK);
    assert(applied);
    assert(battle.field.weather.kind == POKEMON_WEATHER_SUN);
    assert(battle.field.weather.duration == 5);

    PokemonWeatherPolicy policies[4];
    memcpy(policies, POKEMON_GEN3_SLICE_DATA.weather_policies,
        sizeof(policies));
    for (size_t i = 0; i < 4; i++) {
        if (policies[i].kind == POKEMON_WEATHER_SUN) {
            policies[i].blocked_status_mask = 0;
        }
    }
    PokemonData data = POKEMON_GEN3_SLICE_DATA;
    data.weather_policies = policies;
    PokemonResolvedBundle bundle = POKEMON_GEN3_OU_BUNDLE;
    bundle.data = &data;
    init = condition_init(
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SPLASH,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SPLASH);
    init.bundle = &bundle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    battle.field.weather = (PokemonWeatherState){
        .kind = POKEMON_WEATHER_SUN,
        .descriptor_id = battle.generation->condition_descriptor(
            POKEMON_OWNER_FIELD, POKEMON_WEATHER_SUN),
        .duration = 5, .state_generation = 1,
    };
    assert(pokemon_set_status(
        &battle, target, POKEMON_STATUS_FREEZE, source, effect,
        1, &applied) == POKEMON_OK);
    assert(applied);

    policies[1].kind = policies[0].kind;
    PokemonBattle untouched;
    memset(&untouched, 0xa5, sizeof(untouched));
    PokemonBattle before = untouched;
    assert(pokemon_battle_init(&untouched, &init) ==
        POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&untouched, &before, sizeof(untouched)) == 0);
    policies[1].kind = POKEMON_WEATHER_HAIL;
    policies[1].blocked_status_mask = UINT32_C(1) << 31;
    assert(pokemon_battle_init(&untouched, &init) ==
        POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&untouched, &before, sizeof(untouched)) == 0);
    policies[1].blocked_status_mask = 0;
    policies[1].descriptor_id = policies[0].descriptor_id;
    assert(pokemon_battle_init(&untouched, &init) ==
        POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&untouched, &before, sizeof(untouched)) == 0);
    policies[1].descriptor_id = 0;
    assert(pokemon_battle_init(&untouched, &init) ==
        POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&untouched, &before, sizeof(untouched)) == 0);
}

static void test_toxic_switch_reset_and_residual_faint(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_GENGAR, POKEMON_GEN3_MOVE_THIEF,
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_TACKLE
    );
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    battle.sides[1].state[1].status.kind = POKEMON_STATUS_TOXIC;
    battle.sides[1].state[1].status.descriptor_id =
        POKEMON_GEN3_CONDITION_STATUS_TOX;
    battle.sides[1].state[1].status.state.toxic.stage = 7;
    battle.sides[1].state[1].status.state_generation = 1;
    battle.sides[1].state[1].status.effect_order =
        ++battle.next_holder_effect_order;
    PokemonChoice choices[POKEMON_SIDES] = {move(0), switch_to(1)};
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].active == 1);
    assert(battle.sides[1].state[1].status.state.toxic.stage == 1);

    init = condition_init(
        POKEMON_GEN3_SPECIES_GENGAR, POKEMON_GEN3_MOVE_TOXIC,
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_TACKLE
    );
    init.teams[1].members[0].stats[0] = 1;
    int found = 0;
    for (uint16_t tail = 1; tail < 64 && !found; tail++) {
        init.seed[3] = tail;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        choices[0] = move(0);
        choices[1] = move(0);
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        found = battle.request.kind[1] == POKEMON_REQUEST_SWITCH;
    }
    assert(found);
    assert(battle.phase == POKEMON_PHASE_FORCED_REPLACEMENT);
    assert(battle.sides[1].state[0].fainted);
    uint32_t suspended_turn = battle.turn;
    choices[0] = wait_choice();
    choices[1] = switch_to(1);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.turn == suspended_turn + 1);
}

static void test_protect_stall_and_expiry(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_PROTECT,
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_TACKLE
    );
    PokemonBattle battle;
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    int found_chain = 0;
    for (uint16_t tail = 1; tail < 4096 && !found_chain; tail++) {
        init.seed[3] = tail;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        uint16_t hp = battle.sides[0].state[0].hp;
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        assert(battle.sides[0].state[0].hp == hp);
        assert(battle.sides[0].state[0].volatile_count == 1);
        assert(battle.sides[0].state[0].volatiles[0].kind ==
            POKEMON_VOLATILE_STALL);
        assert(battle.sides[0].state[0].volatiles[0].counter == 2);
        int chain = 1;
        for (size_t repeat = 0; repeat < 3 && chain; repeat++) {
            assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
            int saw_stall = 0;
            uint32_t expected_upper = repeat == 0 ? 2u :
                (repeat == 1 ? 4u : 8u);
            for (size_t i = 0; i < battle.draw_count; i++) {
                if (battle.draws[i].label == POKEMON_DRAW_STALL_SUCCESS) {
                    saw_stall = 1;
                    assert(battle.draws[i].upper_bound == expected_upper);
                    chain = battle.draws[i].result == 0;
                }
            }
            assert(saw_stall);
            if (!chain) {
                assert(test_volatile_index(
                    &battle.sides[0].state[0], POKEMON_VOLATILE_STALL) < 0);
                int saw_stall_removal = 0;
                for (size_t i = 0; i < battle.condition_trace_count; i++) {
                    const PokemonConditionTrace *trace =
                        &battle.condition_traces[i];
                    saw_stall_removal |=
                        trace->scope == POKEMON_CONDITION_SCOPE_VOLATILE &&
                        trace->condition_id == POKEMON_VOLATILE_STALL &&
                        trace->operation == POKEMON_CONDITION_REMOVE;
                }
                assert(saw_stall_removal);
            }
        }
        found_chain = chain;
    }
    assert(found_chain);
    int found_stall = 0;
    for (size_t i = 0; i < battle.sides[0].state[0].volatile_count; i++) {
        if (battle.sides[0].state[0].volatiles[i].kind == POKEMON_VOLATILE_STALL) {
            found_stall = 1;
            assert(battle.sides[0].state[0].volatiles[i].counter == 8);
            assert(battle.sides[0].state[0].volatiles[i].duration == 1);
        }
    }
    assert(found_stall);
}

static void test_generic_stalling_guard_and_endure_damage_relay(void) {
    /* Endure and Detect execute through the same stalling operation. Endure
     * acts first by descriptor priority; final-action Detect fails before a
     * stall draw or condition mutation, matching queue.willAct(). */
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_DETECT,
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_ENDURE);
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(test_volatile_index(
        &battle.sides[0].state[0], POKEMON_VOLATILE_STALL) < 0);
    int stall = test_volatile_index(
        &battle.sides[1].state[0], POKEMON_VOLATILE_STALL);
    assert(stall >= 0);
    assert(battle.sides[1].state[0].volatiles[stall].counter == 2);
    assert(draw_label_count(&battle, POKEMON_DRAW_STALL_SUCCESS) == 0);

    /* The guard expires at Residual, but its condition-owned Damage relay has
     * already clamped lethal ordinary Move damage to current HP minus one. */
    init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_ENDURE,
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_STRENGTH);
    init.teams[0].members[0].stats[0] = 20;
    init.teams[0].members[0].stats[2] = 1;
    init.teams[1].members[0].stats[1] = 500;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].hp == 1);
    assert(test_volatile_index(
        &battle.sides[0].state[0], POKEMON_VOLATILE_ENDURE) < 0);
    int saw_endure_damage = 0;
    for (size_t i = 0; i < battle.handler_count; i++) {
        if (battle.handlers[i].handler.descriptor.id ==
                POKEMON_GEN3_HANDLER_ENDURE_DAMAGE) {
            saw_endure_damage = 1;
            assert(battle.handlers[i].invoked);
        }
    }
    assert(saw_endure_damage);
    assert(pokemon_battle_check_invariants(&battle));
}

static void test_reflect_duration_and_damage_handler(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_ALAKAZAM, POKEMON_GEN3_MOVE_REFLECT,
        POKEMON_GEN3_SPECIES_MACHOP, POKEMON_GEN3_MOVE_STRENGTH
    );
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].condition_count == 1);
    assert(battle.sides[0].conditions[0].kind == POKEMON_SIDE_CONDITION_REFLECT);
    assert(battle.sides[0].conditions[0].duration == 4);
    int found = 0;
    for (size_t i = 0; i < battle.modifier_count; i++) {
        const PokemonModifierInvocation *modifier = &battle.modifiers[i];
        if (modifier->handler.descriptor.id !=
                POKEMON_GEN3_HANDLER_REFLECT_MODIFY_DAMAGE_PHASE1) continue;
        found = 1;
        assert(modifier->invoked);
        assert(modifier->modifier_before_q12 == 4096);
        assert(modifier->modifier_after_q12 == 2048);
        assert(modifier->output < modifier->input);
    }
    assert(found);
    choices[0] = switch_to(1);
    choices[1] = move(0);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].condition_count == 1);
    assert(battle.sides[0].conditions[0].duration == 3);
}

static void test_light_screen_uses_generic_side_condition_lifecycle(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_ALAKAZAM, POKEMON_GEN3_MOVE_LIGHTSCREEN,
        POKEMON_GEN3_SPECIES_VAPOREON, POKEMON_GEN3_MOVE_SURF
    );
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].condition_count == 1);
    assert(battle.sides[0].conditions[0].kind ==
        POKEMON_SIDE_CONDITION_SPECIAL_SCREEN);
    assert(battle.sides[0].conditions[0].descriptor_id ==
        POKEMON_GEN3_CONDITION_SIDE_LIGHTSCREEN);
    assert(battle.sides[0].conditions[0].duration == 4);
    int saw_applied_screen = 0;
    for (size_t i = 0; i < battle.modifier_count; i++) {
        const PokemonModifierInvocation *modifier = &battle.modifiers[i];
        if (modifier->handler.descriptor.id !=
                POKEMON_GEN3_HANDLER_LIGHT_SCREEN_MODIFY_DAMAGE_PHASE1) {
            continue;
        }
        saw_applied_screen = 1;
        assert(modifier->invoked);
        assert(modifier->modifier_before_q12 == 4096);
        assert(modifier->modifier_after_q12 == 2048);
        assert(modifier->output < modifier->input);
    }
    assert(saw_applied_screen);
    assert(pokemon_battle_check_invariants(&battle));
}

static void test_side_condition_expiry_dispatches_end_handler(void) {
    enum { TEST_SCREEN_END_HANDLER = 61000 };
    PokemonHandlerOp program = {POKEMON_HANDLER_OP_RETURN_UNDEFINED, 0};
    PokemonHandlerDescriptor handler = {
        .event = POKEMON_HANDLER_EVENT_END, .id = TEST_SCREEN_END_HANDLER,
        .source_kind = POKEMON_HANDLER_SOURCE_CONDITION,
        .source_id = POKEMON_GEN3_CONDITION_SIDE_LIGHTSCREEN,
        .program_offset = 0, .program_count = 1,
        .scope = POKEMON_HANDLER_SCOPE_TARGET,
        .route = POKEMON_HANDLER_ROUTE_OWNER, .raw_hook = "onSideEnd",
    };
    PokemonOwnerBindingIndex binding = {
        .owner_kind = POKEMON_OWNER_SIDE,
        .owner_id = POKEMON_GEN3_CONDITION_SIDE_LIGHTSCREEN,
        .event = POKEMON_HANDLER_EVENT_END,
        .scope = POKEMON_HANDLER_SCOPE_TARGET,
        .route = POKEMON_HANDLER_ROUTE_OWNER,
        .binding_offset = 0, .binding_count = 1,
    };
    PokemonData data = POKEMON_GEN3_SLICE_DATA;
    PokemonMoveData synthetic_moves[POKEMON_GEN3_MOVE_COUNT];
    remove_move_call_capability(&data, synthetic_moves);
    data.handlers = &handler;
    data.handler_count = 1;
    data.handler_programs = &program;
    data.handler_program_count = 1;
    data.owner_binding_index = &binding;
    data.owner_binding_index_count = 1;
    PokemonResolvedBundle bundle = POKEMON_GEN3_OU_BUNDLE;
    PokemonFormatPolicy policy = *bundle.policy;
    policy.status_clauses = NULL;
    policy.status_clause_count = 0;
    bundle.policy = &policy;
    bundle.data = &data;
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_ALAKAZAM, POKEMON_GEN3_MOVE_LIGHTSCREEN,
        POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_SPLASH);
    init.bundle = &bundle;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    for (size_t turn = 0; turn < 5; turn++) {
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    }
    assert(battle.sides[0].condition_count == 0);
    int saw_end = 0;
    for (size_t i = 0; i < battle.handler_count; i++) {
        saw_end |= battle.handlers[i].handler.descriptor.id ==
                TEST_SCREEN_END_HANDLER &&
            battle.handlers[i].handler.owner.kind == POKEMON_OWNER_SIDE &&
            battle.handlers[i].invoked;
    }
    assert(saw_end);
    assert(pokemon_battle_check_invariants(&battle));
}

static void test_move_owned_try_hit_removes_selected_side_conditions(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_BRICKBREAK,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[1].members[0].stats[0] = 600;
    init.teams[1].members[0].stats[2] = 300;
    init.initial_hp[1][0] = 600;
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    PokemonBattle control;
    assert(pokemon_battle_init(&control, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&control, choices) == POKEMON_OK);
    uint16_t control_hp = control.sides[1].state[0].hp;

    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    battle.sides[1].conditions[0] = (PokemonSideConditionState){
        .kind = POKEMON_SIDE_CONDITION_REFLECT,
        .descriptor_id = POKEMON_GEN3_CONDITION_SIDE_REFLECT,
        .duration = 5, .state_generation = 1,
        .effect_order = ++battle.next_holder_effect_order,
    };
    battle.sides[1].conditions[1] = (PokemonSideConditionState){
        .kind = POKEMON_SIDE_CONDITION_SPECIAL_SCREEN,
        .descriptor_id = POKEMON_GEN3_CONDITION_SIDE_LIGHTSCREEN,
        .duration = 5, .state_generation = 1,
        .effect_order = ++battle.next_holder_effect_order,
    };
    battle.sides[1].condition_count = 2;
    assert(pokemon_battle_check_invariants(&battle));
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].condition_count == 0);
    assert(battle.sides[1].state[0].hp == control_hp);
    uint16_t removed[2] = {0, 0};
    size_t removed_count = 0;
    for (size_t i = 0; i < battle.condition_trace_count; i++) {
        const PokemonConditionTrace *trace = &battle.condition_traces[i];
        if (trace->scope == POKEMON_CONDITION_SCOPE_SIDE &&
            trace->operation == POKEMON_CONDITION_REMOVE &&
            removed_count < 2) removed[removed_count++] = trace->condition_id;
    }
    assert(removed_count == 2);
    assert(removed[0] == POKEMON_SIDE_CONDITION_REFLECT);
    assert(removed[1] == POKEMON_SIDE_CONDITION_SPECIAL_SCREEN);
    uint8_t saw_try_hit = 0;
    for (size_t i = 0; i < battle.handler_count; i++) {
        saw_try_hit |= battle.handlers[i].handler.descriptor.id ==
                POKEMON_GEN3_HANDLER_BRICK_BREAK_TRY_HIT &&
            battle.handlers[i].invoked;
    }
    assert(saw_try_hit);
    assert(pokemon_battle_check_invariants(&battle));

    /* Natural immunity gates the move-owned program, preserving the screen. */
    init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_BRICKBREAK,
        POKEMON_GEN3_SPECIES_GENGAR, POKEMON_GEN3_MOVE_SPLASH);
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    battle.sides[1].conditions[0] = (PokemonSideConditionState){
        .kind = POKEMON_SIDE_CONDITION_REFLECT,
        .descriptor_id = POKEMON_GEN3_CONDITION_SIDE_REFLECT,
        .duration = 5, .state_generation = 1,
        .effect_order = ++battle.next_holder_effect_order,
    };
    battle.sides[1].condition_count = 1;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].condition_count == 1);
    assert(battle.sides[1].conditions[0].kind ==
        POKEMON_SIDE_CONDITION_REFLECT);
}

static void test_generated_effect_program_boosts_and_reset(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_MACHOP, POKEMON_GEN3_MOVE_BULKUP,
        POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_SPLASH
    );
    PokemonBattle battle;
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].boosts[POKEMON_STAT_ATK] == 1);
    assert(battle.sides[0].state[0].boosts[POKEMON_STAT_DEF] == 1);
    assert(battle.effect_trace_count == 2);
    assert(battle.effect_traces[0].kind == POKEMON_EFFECT_BOOST);
    assert(battle.effect_traces[1].kind == POKEMON_EFFECT_BOOST);

    choices[0] = switch_to(1);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].boosts[POKEMON_STAT_ATK] == 0);
    assert(battle.sides[0].state[0].boosts[POKEMON_STAT_DEF] == 0);

    /* Double Team is banned from submitted Gen 3 OU sets but remains
     * reachable through Metronome. Its denotation is the ordinary generated
     * self-boost program; no move-identity branch is required. */
    init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_DOUBLETEAM,
        POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_SPLASH);
    choices[0] = move(0);
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].boosts[POKEMON_STAT_EVASION] == 1);
    assert(battle.effect_trace_count == 1);
    assert(battle.effect_traces[0].kind == POKEMON_EFFECT_BOOST);
    assert(battle.effect_traces[0].argument == POKEMON_STAT_EVASION);
    assert(battle.effect_traces[0].amount == 1);
    battle.sides[0].state[0].boosts[POKEMON_STAT_EVASION] = 6;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].boosts[POKEMON_STAT_EVASION] == 6);
    assert(battle.effect_trace_count == 1);
    assert(battle.effect_traces[0].result == POKEMON_EFFECT_FAILED);

    init = condition_init(
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_GROWL,
        POKEMON_GEN3_SPECIES_SNORLAX, POKEMON_GEN3_MOVE_SPLASH
    );
    choices[0] = move(0);
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].state[0].boosts[POKEMON_STAT_ATK] == -1);

    init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_CLEARBODY;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].state[0].boosts[POKEMON_STAT_ATK] == 0);
    assert(battle.handler_count == 1);
    assert(battle.handlers[0].handler.descriptor.id ==
        POKEMON_GEN3_HANDLER_CLEAR_BODY);
    assert(battle.handlers[0].handler.owner.effect_id ==
        POKEMON_GEN3_ABILITY_CLEARBODY);
    uint8_t saw_accuracy = 0;
    for (size_t i = 0; i < battle.draw_count; i++) {
        saw_accuracy |= battle.draws[i].label == POKEMON_DRAW_ACCURACY;
        assert(battle.draws[i].label != POKEMON_DRAW_EVENT_HANDLER_ORDER);
    }
    assert(saw_accuracy);

    init = condition_init(
        POKEMON_GEN3_SPECIES_MACHOP, POKEMON_GEN3_MOVE_BULKUP,
        POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[0].members[0].ability_id = POKEMON_GEN3_ABILITY_CLEARBODY;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    battle.sides[0].state[0].boosts[POKEMON_STAT_ATK] = 6;
    battle.sides[0].state[0].boosts[POKEMON_STAT_DEF] = 5;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].boosts[POKEMON_STAT_ATK] == 6);
    assert(battle.sides[0].state[0].boosts[POKEMON_STAT_DEF] == 6);
    assert(battle.effect_trace_count == 2);
    assert(battle.effect_traces[0].argument == POKEMON_STAT_ATK);
    assert(battle.effect_traces[0].result == POKEMON_EFFECT_FAILED);
    assert(battle.effect_traces[1].argument == POKEMON_STAT_DEF);
    assert(battle.effect_traces[1].result == POKEMON_EFFECT_APPLIED);
    assert(battle.handlers[0].handler.descriptor.id ==
        POKEMON_GEN3_HANDLER_CLEAR_BODY);
    assert(battle.handlers[0].handler.owner.side == 0);
    assert(battle.handlers[0].handler.holder_side == 0);
}

static void test_boosts_modify_standard_damage(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SNORLAX, POKEMON_GEN3_MOVE_BODYSLAM,
        POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_SPLASH
    );
    init.teams[1].members[0].stats[0] = 500;
    init.teams[1].members[0].stats[2] = 200;
    PokemonBattle plain;
    PokemonBattle boosted;
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_init(&plain, &init) == POKEMON_OK);
    assert(pokemon_battle_init(&boosted, &init) == POKEMON_OK);
    boosted.sides[0].state[0].boosts[POKEMON_STAT_ATK] = 1;
    assert(pokemon_battle_step(&plain, choices) == POKEMON_OK);
    assert(pokemon_battle_step(&boosted, choices) == POKEMON_OK);
    assert(boosted.sides[1].state[0].hp < plain.sides[1].state[0].hp);
}

static void test_damage_secondaries_and_owned_prng(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_CHARMANDER, POKEMON_GEN3_MOVE_EMBER,
        POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_SPLASH
    );
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    int found_success = 0;
    int found_failure = 0;
    for (uint16_t tail = 1; tail < 512 && (!found_success || !found_failure); tail++) {
        PokemonBattle battle;
        init.seed[3] = tail;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        int saw_secondary = 0;
        for (size_t draw = 0; draw < battle.draw_count; draw++) {
            if (battle.draws[draw].label != POKEMON_DRAW_SECONDARY) continue;
            saw_secondary = 1;
            assert(battle.draws[draw].upper_bound == 100);
            if (battle.draws[draw].result < 10) {
                found_success = 1;
                assert(battle.sides[1].state[0].status.kind == POKEMON_STATUS_BURN);
                assert(battle.effect_trace_count == 1);
                int saw_burn_damage = 0;
                for (size_t event = 0; event < battle.event_count; event++) {
                    if (battle.events[event].kind == POKEMON_EVENT_DAMAGE &&
                        battle.events[event].condition_scope ==
                            POKEMON_CONDITION_SCOPE_STATUS &&
                        battle.events[event].condition_id == POKEMON_STATUS_BURN) {
                        saw_burn_damage = 1;
                        assert(battle.events[event].amount ==
                            battle.sides[1].sets[0].stats[0] / 8u);
                    }
                }
                assert(saw_burn_damage);
            } else {
                found_failure = 1;
                assert(battle.sides[1].state[0].status.kind == POKEMON_STATUS_NONE);
                assert(battle.effect_trace_count == 0);
            }
        }
        assert(saw_secondary);
        if (battle.effect_trace_count != 0) {
            assert(battle.effect_traces[0].phase == POKEMON_EFFECT_PHASE_AFTER_HIT);
        }
    }
    assert(found_success && found_failure);

    init = condition_init(
        POKEMON_GEN3_SPECIES_SKARMORY, POKEMON_GEN3_MOVE_STEELWING,
        POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_SPLASH
    );
    int found_defense = 0;
    for (uint16_t tail = 1; tail < 512 && !found_defense; tail++) {
        PokemonBattle battle;
        init.seed[3] = tail;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        found_defense = battle.sides[0].state[0].boosts[POKEMON_STAT_DEF] == 1;
    }
    assert(found_defense);
}

static void test_fixed_heal_berry_transaction(void) {
    static const struct { uint16_t item; uint16_t heal; } cases[] = {
        {POKEMON_GEN3_ITEM_ORANBERRY, 10},
        {POKEMON_GEN3_ITEM_SITRUSBERRY, 30},
    };
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    for (size_t i = 0; i < sizeof(cases) / sizeof(cases[0]); i++) {
        PokemonBattleInit init = condition_init(
            POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SPLASH,
            POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_SPLASH);
        init.teams[0].members[0].stats[0] = 301;
        init.teams[0].members[0].item_id = cases[i].item;
        init.initial_hp[0][0] = 150;
        PokemonBattle battle;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        assert(battle.sides[0].state[0].hp == (uint16_t)(150 + cases[i].heal));
        assert(battle.sides[0].state[0].item_id == 0);
        assert(battle.sides[0].state[0].last_item_id == cases[i].item);
        assert(battle.sides[0].state[0].ate_berry == 1);
        assert(battle.sides[0].state[0].used_item_this_turn == 0);

        init.initial_hp[0][0] = 151;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        assert(battle.sides[0].state[0].hp == 151);
        assert(battle.sides[0].state[0].item_id == cases[i].item);
        assert(battle.sides[0].state[0].last_item_id == 0);

        init.teams[0].members[0].stats[0] = 11;
        init.initial_hp[0][0] = 5;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        assert(battle.sides[0].state[0].hp == 11);
        assert(battle.sides[0].state[0].item_id == 0);

        init.initial_hp[0][0] = 11;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        assert(battle.sides[0].state[0].hp == 11);
        assert(battle.sides[0].state[0].item_id == cases[i].item);
    }
}

static void test_leppa_berry_pp_transaction(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_PSYCHUP,
        POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[0].members[0].move_ids[1] = POKEMON_GEN3_MOVE_LOCKON;
    init.teams[0].members[0].move_ids[2] = POKEMON_GEN3_MOVE_SPLASH;
    init.teams[0].members[0].move_ids[3] = POKEMON_GEN3_MOVE_RECYCLE;
    init.teams[0].members[0].item_id = POKEMON_GEN3_ITEM_LEPPABERRY;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);

    /* Stable two-pass selection chooses the first exact-zero slot, not an
     * earlier merely depleted slot or a later exact-zero slot. */
    test_set_base_backed_pp(&battle, 0, 0, 0, 3);
    test_set_base_backed_pp(&battle, 0, 0, 1, 0);
    PokemonChoice choices[POKEMON_SIDES] = {move(2), move(0)};
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].pp[0] == 3);
    assert(battle.sides[0].state[0].pp[1] == 8);
    assert(battle.sides[0].state[0].item_id == 0);
    assert(battle.sides[0].state[0].last_item_id == POKEMON_GEN3_ITEM_LEPPABERRY);
    assert(battle.sides[0].state[0].ate_berry == 1);
    assert(battle.sides[0].state[0].staleness == POKEMON_STALENESS_NONE);

    /* A recycled restorative berry stages internal staleness and commits it
     * only when the berry is consumed. */
    test_set_base_backed_pp(&battle, 0, 0, 0, 0);
    choices[0] = move(3);
    int recycle_status = pokemon_battle_step(&battle, choices);
    assert(recycle_status == POKEMON_OK);
    assert(battle.sides[0].state[0].item_id == 0);
    assert(battle.sides[0].state[0].staleness ==
        POKEMON_STALENESS_INTERNAL);
    assert(battle.sides[0].state[0].pending_staleness ==
        POKEMON_STALENESS_NONE);

    /* Partial depletion alone does not trigger Update consumption. */
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    test_set_base_backed_pp(&battle, 0, 0, 0,
        (uint8_t)(battle.sides[0].state[0].pp[0] - 1u));
    choices[0] = move(2);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].item_id == POKEMON_GEN3_ITEM_LEPPABERRY);

    /* The selected move's base PP debit precedes action-tail Update. */
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    test_set_base_backed_pp(&battle, 0, 0, 0, 1);
    choices[0] = move(0);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].pp[0] == 10);
    assert(battle.sides[0].state[0].item_id == 0);
}

static void test_pinch_boost_berry_transaction(void) {
    static const struct { uint16_t item; uint8_t stat; } cases[] = {
        {POKEMON_GEN3_ITEM_LIECHIBERRY, POKEMON_STAT_ATK},
        {POKEMON_GEN3_ITEM_GANLONBERRY, POKEMON_STAT_DEF},
        {POKEMON_GEN3_ITEM_SALACBERRY, POKEMON_STAT_SPE},
        {POKEMON_GEN3_ITEM_PETAYABERRY, POKEMON_STAT_SPA},
        {POKEMON_GEN3_ITEM_APICOTBERRY, POKEMON_STAT_SPD},
    };
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    for (size_t i = 0; i < sizeof(cases) / sizeof(cases[0]); i++) {
        PokemonBattleInit init = condition_init(
            POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SPLASH,
            POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_SPLASH);
        init.teams[0].members[0].stats[0] = 301;
        init.teams[0].members[0].item_id = cases[i].item;
        init.initial_hp[0][0] = 75;
        if (i == 0) {
            init.teams[0].members[0].ability_id = POKEMON_GEN3_ABILITY_CLEARBODY;
        }
        PokemonBattle battle;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        assert(battle.sides[0].state[0].boosts[cases[i].stat] == 1);
        assert(battle.sides[0].state[0].item_id == 0);
        assert(battle.sides[0].state[0].last_item_id == cases[i].item);
        assert(battle.sides[0].state[0].ate_berry == 1);

        init.initial_hp[0][0] = 76;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        assert(battle.sides[0].state[0].boosts[cases[i].stat] == 0);
        assert(battle.sides[0].state[0].item_id == cases[i].item);

        init.initial_hp[0][0] = 74;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        battle.sides[0].state[0].boosts[cases[i].stat] = 6;
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        assert(battle.sides[0].state[0].boosts[cases[i].stat] == 6);
        assert(battle.sides[0].state[0].item_id == 0);
        assert(battle.sides[0].state[0].last_item_id == cases[i].item);
    }
}

static void test_lansat_berry_volatile_transaction(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SPLASH,
        POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[0].members[0].stats[0] = 301;
    init.teams[0].members[0].item_id = POKEMON_GEN3_ITEM_LANSATBERRY;
    init.initial_hp[0][0] = 75;
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    PokemonMutable *holder = &battle.sides[0].state[0];
    assert(holder->item_id == 0);
    assert(holder->last_item_id == POKEMON_GEN3_ITEM_LANSATBERRY);
    assert(holder->ate_berry == 1);
    assert(holder->volatile_count == 1);
    assert(test_volatile_index(holder, POKEMON_VOLATILE_FOCUS_ENERGY) == 0);
    assert(holder->volatiles[0].source.side == 0);
    assert(holder->volatiles[0].source.slot == 0);
    assert(holder->volatiles[0].source_effect.kind ==
        POKEMON_SOURCE_EFFECT_ITEM);
    assert(holder->volatiles[0].source_effect.id ==
        POKEMON_GEN3_ITEM_LANSATBERRY);

    init.initial_hp[0][0] = 76;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    holder = &battle.sides[0].state[0];
    assert(holder->item_id == POKEMON_GEN3_ITEM_LANSATBERRY);
    assert(holder->volatile_count == 0);

    init.initial_hp[0][0] = 75;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    PokemonEffectResult result = POKEMON_EFFECT_FAILED;
    assert(pokemon_try_add_or_restart_volatile(
        &battle, (PokemonEntityRef){POKEMON_ENTITY_POKEMON, 0, 0},
        (PokemonEntityRef){POKEMON_ENTITY_POKEMON, 0, 0},
        (PokemonSourceEffectRef){POKEMON_SOURCE_EFFECT_MOVE,
            POKEMON_GEN3_MOVE_FOCUSENERGY},
        POKEMON_VOLATILE_FOCUS_ENERGY, POKEMON_CONDITION_REASON_MOVE,
        &result) == POKEMON_OK);
    assert(result == POKEMON_EFFECT_APPLIED);
    holder = &battle.sides[0].state[0];
    assert(holder->volatile_count == 1);
    uint16_t generation = holder->volatiles[0].state_generation;
    uint32_t effect_order = holder->volatiles[0].effect_order;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(holder->item_id == 0);
    assert(holder->last_item_id == POKEMON_GEN3_ITEM_LANSATBERRY);
    assert(holder->volatile_count == 1);
    assert(holder->volatiles[0].state_generation == generation);
    assert(holder->volatiles[0].effect_order == effect_order);
    assert(holder->volatiles[0].source_effect.kind ==
        POKEMON_SOURCE_EFFECT_MOVE);
    assert(holder->volatiles[0].source_effect.id ==
        POKEMON_GEN3_MOVE_FOCUSENERGY);
}

static void test_starf_berry_random_eligible_boost_transaction(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SPLASH,
        POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[0].members[0].stats[0] = 301;
    init.teams[0].members[0].item_id = POKEMON_GEN3_ITEM_STARFBERRY;
    init.initial_hp[0][0] = 75;
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    PokemonBattle battle;

    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    PokemonMutable *holder = &battle.sides[0].state[0];
    unsigned boosted = 0;
    for (uint8_t stat = POKEMON_STAT_ATK; stat <= POKEMON_STAT_SPE; stat++) {
        if (holder->boosts[stat] == 2) boosted++;
        else assert(holder->boosts[stat] == 0);
    }
    assert(boosted == 1);
    assert(holder->boosts[POKEMON_STAT_ACCURACY] == 0);
    assert(holder->boosts[POKEMON_STAT_EVASION] == 0);
    assert(holder->item_id == 0);
    assert(holder->last_item_id == POKEMON_GEN3_ITEM_STARFBERRY);
    assert(holder->ate_berry == 1);
    unsigned selection_draws = 0;
    for (size_t i = 0; i < battle.draw_count; i++) {
        if (battle.draws[i].label == POKEMON_DRAW_ITEM_RANDOM_STAT) {
            selection_draws++;
            assert(battle.draws[i].upper_bound == 5);
        }
    }
    assert(selection_draws == 1);

    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    holder = &battle.sides[0].state[0];
    for (uint8_t stat = POKEMON_STAT_ATK; stat < POKEMON_STAT_SPE; stat++) {
        holder->boosts[stat] = 6;
    }
    holder->boosts[POKEMON_STAT_SPE] = 5;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(holder->boosts[POKEMON_STAT_SPE] == 6);
    selection_draws = 0;
    for (size_t i = 0; i < battle.draw_count; i++) {
        if (battle.draws[i].label == POKEMON_DRAW_ITEM_RANDOM_STAT) {
            selection_draws++;
            assert(battle.draws[i].upper_bound == 1);
            assert(battle.draws[i].result == 0);
        }
    }
    assert(selection_draws == 1);

    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    holder = &battle.sides[0].state[0];
    for (uint8_t stat = POKEMON_STAT_ATK; stat <= POKEMON_STAT_SPE; stat++) {
        holder->boosts[stat] = 6;
    }
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(holder->item_id == 0);
    for (size_t i = 0; i < battle.draw_count; i++) {
        assert(battle.draws[i].label != POKEMON_DRAW_ITEM_RANDOM_STAT);
    }

    init.initial_hp[0][0] = 76;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].item_id == POKEMON_GEN3_ITEM_STARFBERRY);
    for (size_t i = 0; i < battle.draw_count; i++) {
        assert(battle.draws[i].label != POKEMON_DRAW_ITEM_RANDOM_STAT);
    }
}

static void test_status_cure_berry_transaction(void) {
    static const struct { uint16_t item; PokemonStatus status; } cases[] = {
        {POKEMON_GEN3_ITEM_CHERIBERRY, POKEMON_STATUS_PARALYSIS},
        {POKEMON_GEN3_ITEM_CHESTOBERRY, POKEMON_STATUS_SLEEP},
        {POKEMON_GEN3_ITEM_PECHABERRY, POKEMON_STATUS_POISON},
        {POKEMON_GEN3_ITEM_PECHABERRY, POKEMON_STATUS_TOXIC},
        {POKEMON_GEN3_ITEM_RAWSTBERRY, POKEMON_STATUS_BURN},
        {POKEMON_GEN3_ITEM_ASPEARBERRY, POKEMON_STATUS_FREEZE},
    };
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    for (size_t i = 0; i < sizeof(cases) / sizeof(cases[0]); i++) {
        PokemonBattleInit init = condition_init(
            POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SPLASH,
            POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_SPLASH);
        init.teams[0].members[0].item_id = cases[i].item;
        init.initial_status[0][0] = cases[i].status == POKEMON_STATUS_SLEEP ?
            POKEMON_STATUS_NONE : cases[i].status;
        PokemonBattle battle;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        if (cases[i].status == POKEMON_STATUS_SLEEP) {
            battle.sides[0].state[0].status.kind = POKEMON_STATUS_SLEEP;
            battle.sides[0].state[0].status.descriptor_id =
                POKEMON_GEN3_CONDITION_STATUS_SLP;
            battle.sides[0].state[0].status.state_generation = 1;
            battle.sides[0].state[0].status.effect_order =
                ++battle.next_holder_effect_order;
            battle.sides[0].state[0].status.state.sleep.time = 3;
            battle.sides[0].state[0].status.state.sleep.skipped_time = 1;
            assert(pokemon_battle_check_invariants(&battle));
        }
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        assert(battle.sides[0].state[0].status.kind == POKEMON_STATUS_NONE);
        assert(battle.sides[0].state[0].status.state.sleep.time == 0);
        assert(battle.sides[0].state[0].status.state.sleep.skipped_time == 0);
        assert(battle.sides[0].state[0].item_id == 0);
        assert(battle.sides[0].state[0].last_item_id == cases[i].item);
        assert(battle.sides[0].state[0].ate_berry == 1);
    }

    PokemonBattleInit mismatch = condition_init(
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SPLASH,
        POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_SPLASH);
    mismatch.teams[0].members[0].item_id = POKEMON_GEN3_ITEM_CHERIBERRY;
    mismatch.initial_status[0][0] = POKEMON_STATUS_BURN;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &mismatch) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].status.kind == POKEMON_STATUS_BURN);
    assert(battle.sides[0].state[0].item_id == POKEMON_GEN3_ITEM_CHERIBERRY);
    assert(battle.sides[0].state[0].last_item_id == 0);
}

static void test_volatile_cure_berry_transaction(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_CONFUSERAY,
        POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[1].members[0].item_id = POKEMON_GEN3_ITEM_PERSIMBERRY;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    uint8_t target_pp = battle.sides[1].state[0].pp[0];
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    PokemonMutable *holder = &battle.sides[1].state[0];
    assert(test_volatile_index(holder, POKEMON_VOLATILE_CONFUSION) < 0);
    assert(holder->item_id == 0);
    assert(holder->last_item_id == POKEMON_GEN3_ITEM_PERSIMBERRY);
    assert(holder->ate_berry == 1);
    assert(holder->pp[0] == (uint8_t)(target_pp - 1));

    /* The generated Update predicate is a strict volatile-kind match. */
    init.teams[0].members[0].move_ids[0] = POKEMON_GEN3_MOVE_SPLASH;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    holder = &battle.sides[1].state[0];
    assert(holder->item_id == POKEMON_GEN3_ITEM_PERSIMBERRY);
    assert(holder->last_item_id == 0);
    assert(holder->ate_berry == 0);

    /* Residual entry refreshes the mutable cached speed before its following
     * Update discovers holder callbacks. Handler metadata must use that cache,
     * not the immutable set Speed. */
    init = condition_init(
        POKEMON_GEN3_SPECIES_GENGAR, POKEMON_GEN3_MOVE_THUNDERWAVE,
        POKEMON_GEN3_SPECIES_MACHOP, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[1].members[0].item_id = POKEMON_GEN3_ITEM_PERSIMBERRY;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    holder = &battle.sides[1].state[0];
    assert(holder->status.kind == POKEMON_STATUS_PARALYSIS);
    assert(holder->cached_speed == battle.sides[1].sets[0].stats[5] / 4);
    assert(battle.handler_count != 0);
    const PokemonHandlerRef *last = &battle.handlers[
        battle.handler_count - 1].handler;
    assert(last->descriptor.id == POKEMON_GEN3_HANDLER_PERSIMBERRY_UPDATE);
    assert(last->speed == holder->cached_speed);
}

static void test_combined_cure_berry_transaction(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_GENGAR, POKEMON_GEN3_MOVE_THUNDERWAVE,
        POKEMON_GEN3_SPECIES_MACHOP, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[1].members[0].item_id = POKEMON_GEN3_ITEM_LUMBERRY;
    PokemonBattle battle;
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    PokemonMutable *holder = &battle.sides[1].state[0];
    assert(holder->status.kind == POKEMON_STATUS_NONE);
    assert(holder->item_id == 0);
    assert(holder->last_item_id == POKEMON_GEN3_ITEM_LUMBERRY);
    assert(holder->ate_berry == 1);

    /* ItemEat is one transaction: cure major status first, then remove the
     * installed confusion through its generic End lifecycle. */
    init.teams[0].members[0].move_ids[0] = POKEMON_GEN3_MOVE_SPLASH;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    holder = &battle.sides[1].state[0];
    holder->volatiles[holder->volatile_count++] = (PokemonVolatileState){
        .kind = POKEMON_VOLATILE_CONFUSION,
        .descriptor_id = POKEMON_GEN3_CONDITION_VOLATILE_CONFUSION,
        .state_generation = 1,
        .effect_order = ++battle.next_holder_effect_order,
        .source = {POKEMON_ENTITY_POKEMON, 0, 0},
        .source_effect = {POKEMON_SOURCE_EFFECT_MOVE,
            POKEMON_GEN3_MOVE_CONFUSERAY},
        .payload.confusion.time = 3,
    };
    uint8_t applied = 0;
    assert(pokemon_set_status(&battle,
        (PokemonEntityRef){POKEMON_ENTITY_POKEMON, 1, 0},
        POKEMON_STATUS_PARALYSIS,
        (PokemonEntityRef){POKEMON_ENTITY_POKEMON, 0, 0},
        (PokemonSourceEffectRef){POKEMON_SOURCE_EFFECT_MOVE,
            POKEMON_GEN3_MOVE_THUNDERWAVE}, 1, &applied) == POKEMON_OK);
    assert(applied == 1);
    assert(holder->status.kind == POKEMON_STATUS_NONE);
    assert(test_volatile_index(holder, POKEMON_VOLATILE_CONFUSION) < 0);
    assert(holder->item_id == 0);
    assert(holder->last_item_id == POKEMON_GEN3_ITEM_LUMBERRY);
    assert(holder->ate_berry == 1);
    assert(battle.condition_trace_count >= 3);
    size_t status_remove_index = SIZE_MAX;
    size_t confusion_remove_index = SIZE_MAX;
    for (size_t i = 0; i < battle.condition_trace_count; i++) {
        const PokemonConditionTrace *trace = &battle.condition_traces[i];
        if (trace->operation != POKEMON_CONDITION_REMOVE) continue;
        if (trace->scope == POKEMON_CONDITION_SCOPE_STATUS) {
            status_remove_index = i;
        } else if (trace->scope == POKEMON_CONDITION_SCOPE_VOLATILE &&
                   trace->condition_id ==
                       POKEMON_VOLATILE_CONFUSION) {
            confusion_remove_index = i;
        }
    }
    assert(status_remove_index != SIZE_MAX);
    assert(confusion_remove_index != SIZE_MAX);
    assert(status_remove_index < confusion_remove_index);

    init.teams[1].members[0].item_id = POKEMON_GEN3_ITEM_LUMBERRY;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    holder = &battle.sides[1].state[0];
    assert(holder->item_id == POKEMON_GEN3_ITEM_LUMBERRY);
    assert(holder->last_item_id == 0);
    assert(holder->ate_berry == 0);
}

static void test_flavor_berry_nature_transaction(void) {
    static const struct {
        uint16_t item;
        PokemonNature nature;
        PokemonFlavor flavor;
    } cases[] = {
        {POKEMON_GEN3_ITEM_AGUAVBERRY, POKEMON_NATURE_NAUGHTY,
            POKEMON_FLAVOR_BITTER},
        {POKEMON_GEN3_ITEM_FIGYBERRY, POKEMON_NATURE_BOLD,
            POKEMON_FLAVOR_SPICY},
        {POKEMON_GEN3_ITEM_IAPAPABERRY, POKEMON_NATURE_LONELY,
            POKEMON_FLAVOR_SOUR},
        {POKEMON_GEN3_ITEM_MAGOBERRY, POKEMON_NATURE_BRAVE,
            POKEMON_FLAVOR_SWEET},
        {POKEMON_GEN3_ITEM_WIKIBERRY, POKEMON_NATURE_ADAMANT,
            POKEMON_FLAVOR_DRY},
    };
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    for (size_t i = 0; i < sizeof(cases) / sizeof(cases[0]); i++) {
        PokemonBattleInit init = condition_init(
            POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SPLASH,
            POKEMON_GEN3_SPECIES_MACHOP, POKEMON_GEN3_MOVE_SPLASH);
        init.teams[0].members[0].item_id = cases[i].item;
        init.teams[0].members[0].nature = cases[i].nature;
        init.teams[0].members[0].stats[0] = 271;
        init.initial_hp[0][0] = 135;
        PokemonBattle battle;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        assert(battle.sides[0].sets[0].disliked_flavor == cases[i].flavor);
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        PokemonMutable *holder = &battle.sides[0].state[0];
        assert(holder->hp == 168); /* floor(271 / 8) = 33 */
        assert(holder->item_id == 0 && holder->last_item_id == cases[i].item);
        assert(test_volatile_index(holder, POKEMON_VOLATILE_CONFUSION) >= 0);
        assert(draw_label_count(&battle, POKEMON_DRAW_CONFUSION_DURATION) == 1);

        init.teams[0].members[0].nature = POKEMON_NATURE_HARDY;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        assert(battle.sides[0].sets[0].disliked_flavor == POKEMON_FLAVOR_NONE);
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        holder = &battle.sides[0].state[0];
        assert(holder->hp == 168 && holder->item_id == 0);
        assert(test_volatile_index(holder, POKEMON_VOLATILE_CONFUSION) < 0);
        assert(draw_label_count(&battle, POKEMON_DRAW_CONFUSION_DURATION) == 0);
    }

    PokemonBattleInit own_tempo = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_SPLASH,
        POKEMON_GEN3_SPECIES_MACHOP, POKEMON_GEN3_MOVE_SPLASH);
    own_tempo.teams[0].members[0].item_id = POKEMON_GEN3_ITEM_FIGYBERRY;
    own_tempo.teams[0].members[0].ability_id = POKEMON_GEN3_ABILITY_OWNTEMPO;
    own_tempo.teams[0].members[0].nature = POKEMON_NATURE_BOLD;
    own_tempo.teams[0].members[0].stats[0] = 251;
    own_tempo.initial_hp[0][0] = 125;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &own_tempo) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].hp == 156); /* floor(251 / 8) = 31 */
    assert(battle.sides[0].state[0].item_id == 0);
    assert(test_volatile_index(&battle.sides[0].state[0],
        POKEMON_VOLATILE_CONFUSION) < 0);
    assert(draw_label_count(&battle, POKEMON_DRAW_CONFUSION_DURATION) == 0);

    PokemonBattleInit invalid = own_tempo;
    invalid.teams[0].members[0].disliked_flavor = POKEMON_FLAVOR_DRY;
    PokemonBattle untouched;
    memset(&untouched, 0x5a, sizeof(untouched));
    PokemonBattle before = untouched;
    assert(pokemon_battle_init(&untouched, &invalid) ==
        POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&untouched, &before, sizeof(untouched)) == 0);
}

static void test_effect_trace_capacity_failure_is_atomic(void) {
    PokemonEffectOp effects[POKEMON_EFFECT_TRACE_CAPACITY + 1];
    for (size_t i = 0; i < POKEMON_EFFECT_TRACE_CAPACITY + 1; i++) {
        effects[i] = (PokemonEffectOp){
            .kind = POKEMON_EFFECT_BOOST,
            .phase = POKEMON_EFFECT_PHASE_PRIMARY,
            .target = POKEMON_EFFECT_TARGET_USER,
            .chance = 100,
            .argument = POKEMON_STAT_ATK,
            .amount = 1,
        };
    }
    PokemonMoveData program_move = {
        .id = 1, .type = POKEMON_GEN3_TYPE_NORMAL,
        .category = POKEMON_CATEGORY_STATUS,
        .accuracy = {POKEMON_ACCURACY_PERCENT, 100},
        .raw_pp = 10, .pp = 16,
        .target = POKEMON_TARGET_SELF, .effect_offset = 0,
        .effect_count = POKEMON_EFFECT_TRACE_CAPACITY + 1,
        .damage_formula = POKEMON_DAMAGE_STANDARD,
    };
    PokemonData data = POKEMON_GEN3_SLICE_DATA;
    data.moves = &program_move;
    data.move_count = 1;
    data.move_invocation_profiles = NULL;
    data.move_invocation_profile_count = 0;
    data.move_profile_selections = NULL;
    data.move_profile_selection_count = 0;
    data.effects = effects;
    data.effect_count = POKEMON_EFFECT_TRACE_CAPACITY + 1;
    data.effect_secondary_groups = NULL;
    data.effect_secondary_group_count = 0;
    data.two_turn_moves = NULL;
    data.two_turn_move_count = 0;
    data.move_call_pools = NULL;
    data.move_call_pool_count = 0;
    data.move_call_pool_candidates = NULL;
    data.move_call_pool_candidate_count = 0;
    data.constructed_hit_templates = NULL;
    data.constructed_hit_template_count = 0;
    data.move_pre_use_programs = NULL;
    data.move_pre_use_program_count = 0;
    data.handlers = NULL;
    data.handler_count = 0;
    data.handler_programs = NULL;
    data.handler_program_count = 0;
    data.owner_binding_index = NULL;
    data.owner_binding_index_count = 0;
    data.locked_ramp_policies = NULL;
    data.locked_ramp_policy_count = 0;
    PokemonBattleInit init = battle_init();
    PokemonResolvedBundle bundle = *init.bundle;
    PokemonGeneration generation = *bundle.rules;
    generation.fallback_move_id = program_move.id;
    generation.choice_control_policies = NULL;
    generation.choice_control_policy_count = 0;
    PokemonFormatPolicy policy = *bundle.policy;
    policy.status_clauses = NULL;
    policy.status_clause_count = 0;
    bundle.policy = &policy;
    bundle.data = &data;
    bundle.rules = &generation;
    init.bundle = &bundle;
    for (size_t side = 0; side < POKEMON_SIDES; side++) {
        for (size_t slot = 0; slot < 2; slot++) {
            init.teams[side].members[slot].move_ids[0] = 1;
            init.teams[side].members[slot].move_ids[1] = 0;
        }
    }
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    PokemonBattle before = battle;
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_step(&battle, choices) == POKEMON_CAPACITY_EXCEEDED);
    assert(memcmp(&battle, &before, sizeof(battle)) == 0);
}

static void test_fixed_duration_volatile_install_is_atomic(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_ALAKAZAM, POKEMON_GEN3_MOVE_SNATCH,
        POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_SPLASH);
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    PokemonMutable *holder = &battle.sides[0].state[0];
    holder->volatiles[0] = (PokemonVolatileState){
        .kind = POKEMON_VOLATILE_PROTECT,
        .descriptor_id = POKEMON_GEN3_CONDITION_VOLATILE_PROTECT,
        .duration = 1, .state_generation = 1,
        .effect_order = ++battle.next_holder_effect_order};
    holder->volatiles[1] = (PokemonVolatileState){
        .kind = POKEMON_VOLATILE_STALL,
        .descriptor_id = POKEMON_GEN3_CONDITION_VOLATILE_STALL,
        .duration = 1, .counter = 2, .state_generation = 1,
        .effect_order = ++battle.next_holder_effect_order};
    holder->volatiles[2] = (PokemonVolatileState){
        .kind = POKEMON_VOLATILE_SUBSTITUTE,
        .descriptor_id = POKEMON_GEN3_CONDITION_VOLATILE_SUBSTITUTE,
        .state_generation = 1,
        .effect_order = ++battle.next_holder_effect_order,
        .payload.substitute.hp = 1};
    holder->volatiles[3] = (PokemonVolatileState){
        .kind = POKEMON_VOLATILE_MAGIC_COAT,
        .descriptor_id = POKEMON_GEN3_CONDITION_VOLATILE_MAGICCOAT,
        .duration = 1, .state_generation = 1,
        .effect_order = ++battle.next_holder_effect_order};
    holder->volatile_count = POKEMON_VOLATILE_CAPACITY;
    assert(pokemon_battle_check_invariants(&battle));
    PokemonBattle before = battle;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_CAPACITY_EXCEEDED);
    assert(memcmp(&battle, &before, sizeof(battle)) == 0);

    init = condition_init(
        POKEMON_GEN3_SPECIES_ALAKAZAM, POKEMON_GEN3_MOVE_MAGICCOAT,
        POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_SPLASH);
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    holder = &battle.sides[0].state[0];
    holder->volatiles[holder->volatile_count++] = (PokemonVolatileState){
        .kind = POKEMON_VOLATILE_MAGIC_COAT,
        .descriptor_id = POKEMON_GEN3_CONDITION_VOLATILE_MAGICCOAT,
        .duration = 1, .state_generation = 1,
        .effect_order = ++battle.next_holder_effect_order,
        .source = {POKEMON_ENTITY_POKEMON, 0, 0},
        .source_effect = {POKEMON_SOURCE_EFFECT_MOVE,
            POKEMON_GEN3_MOVE_MAGICCOAT},
    };
    assert(pokemon_battle_check_invariants(&battle));
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    for (size_t i = 0; i < battle.condition_trace_count; i++) {
        assert(battle.condition_traces[i].operation != POKEMON_CONDITION_ADD);
    }
}

static void test_damage_relative_recoil_and_rock_head(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_MAROWAK, POKEMON_GEN3_MOVE_DOUBLEEDGE,
        POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_SPLASH
    );
    init.teams[0].members[0].ability_id = POKEMON_GEN3_ABILITY_LIGHTNINGROD;
    init.teams[1].members[0].stats[0] = 10;
    PokemonBattle recoil;
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_init(&recoil, &init) == POKEMON_OK);
    uint16_t hp_before = recoil.sides[0].state[0].hp;
    assert(pokemon_battle_step(&recoil, choices) == POKEMON_OK);
    assert(recoil.sides[1].state[0].hp == 0);
    assert(recoil.sides[0].state[0].hp == hp_before - 3);
    assert(recoil.effect_trace_count == 1);
    assert(recoil.effect_traces[0].kind == POKEMON_EFFECT_DAMAGE_RELATIVE);
    assert(recoil.effect_traces[0].argument == POKEMON_DAMAGE_RELATIVE_RECOIL);
    assert(recoil.effect_traces[0].damage_basis == 10);
    assert(recoil.effect_traces[0].numerator == 1);
    assert(recoil.effect_traces[0].denominator == 3);
    assert(recoil.effect_traces[0].requested == 3);
    assert(recoil.effect_traces[0].damage_target_side == 1);
    assert(recoil.effect_traces[0].damage_target_slot == 0);
    assert(recoil.effect_traces[0].value == 3);

    init.teams[0].members[0].ability_id = POKEMON_GEN3_ABILITY_ROCKHEAD;
    PokemonBattle protected;
    assert(pokemon_battle_init(&protected, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&protected, choices) == POKEMON_OK);
    assert(protected.sides[0].state[0].hp == hp_before);
    assert(protected.effect_trace_count == 2);
    assert(protected.effect_traces[0].prevention);
    assert(protected.effect_traces[0].result == POKEMON_EFFECT_APPLIED);
    assert(protected.effect_traces[0].requested == 3);
    assert(protected.effect_traces[1].result == POKEMON_EFFECT_FAILED);
    assert(protected.effect_traces[1].damage_basis == 10);
    assert(protected.effect_traces[1].requested == 3);
    assert(protected.effect_traces[1].value == 0);
    assert(protected.handler_count == 1);
    assert(protected.handlers[0].handler.descriptor.id == POKEMON_GEN3_HANDLER_ROCK_HEAD);
    assert(protected.handlers[0].handler.descriptor.sub_order == 7);
    assert(protected.handlers[0].result == POKEMON_HANDLER_PREVENT);

    const PokemonMoveData *struggle = NULL;
    for (size_t i = 0; i < POKEMON_GEN3_SLICE_DATA.move_count; i++) {
        if (POKEMON_GEN3_SLICE_DATA.moves[i].id == POKEMON_GEN3_MOVE_STRUGGLE) {
            struggle = &POKEMON_GEN3_SLICE_DATA.moves[i];
            break;
        }
    }
    assert(struggle != NULL && struggle->effect_count == 1);
    const PokemonEffectOp *struggle_recoil =
        &POKEMON_GEN3_SLICE_DATA.effects[struggle->effect_offset];
    assert(struggle_recoil->damage_preventability ==
        POKEMON_DAMAGE_UNPREVENTABLE);

    PokemonEffectOp invalid_effects[512];
    assert(POKEMON_GEN3_SLICE_DATA.effect_count <=
        sizeof(invalid_effects) / sizeof(invalid_effects[0]));
    memcpy(invalid_effects, POKEMON_GEN3_SLICE_DATA.effects,
        POKEMON_GEN3_SLICE_DATA.effect_count * sizeof(invalid_effects[0]));
    const PokemonMoveData *double_edge = NULL;
    for (size_t i = 0; i < POKEMON_GEN3_SLICE_DATA.move_count; i++) {
        if (POKEMON_GEN3_SLICE_DATA.moves[i].id ==
                POKEMON_GEN3_MOVE_DOUBLEEDGE) {
            double_edge = &POKEMON_GEN3_SLICE_DATA.moves[i];
            break;
        }
    }
    assert(double_edge != NULL && double_edge->effect_count == 1);
    invalid_effects[double_edge->effect_offset].damage_preventability =
        POKEMON_DAMAGE_PREVENTABILITY_NONE;
    PokemonData invalid_data = POKEMON_GEN3_SLICE_DATA;
    invalid_data.effects = invalid_effects;
    PokemonResolvedBundle invalid_bundle = POKEMON_GEN3_OU_BUNDLE;
    invalid_bundle.data = &invalid_data;
    PokemonBattleInit invalid_init = condition_init(
        POKEMON_GEN3_SPECIES_MAROWAK, POKEMON_GEN3_MOVE_DOUBLEEDGE,
        POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_SPLASH);
    invalid_init.bundle = &invalid_bundle;
    PokemonBattle untouched;
    memset(&untouched, 0xa5, sizeof(untouched));
    PokemonBattle untouched_before = untouched;
    assert(pokemon_battle_init(&untouched, &invalid_init) ==
        POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&untouched, &untouched_before, sizeof(untouched)) == 0);
}

static void test_generated_recoil_move_family(void) {
    static const struct {
        uint16_t id;
        uint8_t power;
        uint8_t accuracy;
        uint8_t denominator;
    } cases[] = {
        {POKEMON_GEN3_MOVE_SUBMISSION, 80, 80, 4},
        {POKEMON_GEN3_MOVE_TAKEDOWN, 90, 85, 4},
        {POKEMON_GEN3_MOVE_VOLTTACKLE, 120, 100, 3},
    };
    for (size_t expected = 0;
         expected < sizeof(cases) / sizeof(cases[0]); expected++) {
        const PokemonMoveData *move_data = NULL;
        for (size_t i = 0; i < POKEMON_GEN3_SLICE_DATA.move_count; i++) {
            if (POKEMON_GEN3_SLICE_DATA.moves[i].id == cases[expected].id) {
                move_data = &POKEMON_GEN3_SLICE_DATA.moves[i];
                break;
            }
        }
        assert(move_data != NULL);
        assert(move_data->power == cases[expected].power);
        assert(move_data->accuracy.kind == POKEMON_ACCURACY_PERCENT);
        assert(move_data->accuracy.percent == cases[expected].accuracy);
        assert(move_data->effect_count == 1);
        const PokemonEffectOp *effect = &POKEMON_GEN3_SLICE_DATA.effects[
            move_data->effect_offset];
        assert(effect->kind == POKEMON_EFFECT_DAMAGE_RELATIVE);
        assert(effect->phase == POKEMON_EFFECT_PHASE_AFTER_MOVE);
        assert(effect->target == POKEMON_EFFECT_TARGET_USER);
        assert(effect->chance == 100);
        assert(effect->argument == POKEMON_DAMAGE_RELATIVE_RECOIL);
        assert(effect->fraction_numerator == 1);
        assert(effect->fraction_denominator == cases[expected].denominator);
        assert(effect->damage_preventability == POKEMON_DAMAGE_PREVENTABLE);
    }
}

static void test_damage_relative_drain_and_nonhit_gates(void) {
    const uint16_t drain_ids[] = {
        POKEMON_GEN3_MOVE_ABSORB, POKEMON_GEN3_MOVE_MEGADRAIN,
        POKEMON_GEN3_MOVE_GIGADRAIN, POKEMON_GEN3_MOVE_LEECHLIFE,
    };
    const uint16_t base_powers[] = {20, 40, 60, 20};
    /* The native descriptor stores Gen 3 maximum PP after PP Ups. */
    const uint8_t pp[] = {32, 16, 8, 24};
    for (size_t expected = 0;
         expected < sizeof(drain_ids) / sizeof(drain_ids[0]); expected++) {
        const PokemonMoveData *move_data = NULL;
        for (size_t i = 0; i < POKEMON_GEN3_SLICE_DATA.move_count; i++) {
            if (POKEMON_GEN3_SLICE_DATA.moves[i].id == drain_ids[expected]) {
                move_data = &POKEMON_GEN3_SLICE_DATA.moves[i];
                break;
            }
        }
        assert(move_data != NULL);
        assert(move_data->power == base_powers[expected]);
        assert(move_data->pp == pp[expected]);
        assert(move_data->effect_count == 1);
        const PokemonEffectOp *effect = &POKEMON_GEN3_SLICE_DATA.effects[
            move_data->effect_offset];
        assert(effect->kind == POKEMON_EFFECT_DAMAGE_RELATIVE);
        assert(effect->phase == POKEMON_EFFECT_PHASE_AFTER_DAMAGE);
        assert(effect->target == POKEMON_EFFECT_TARGET_USER);
        assert(effect->argument == POKEMON_DAMAGE_RELATIVE_DRAIN);
        assert(effect->fraction_numerator == 1);
        assert(effect->fraction_denominator == 2);
    }
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_VENUSAUR, POKEMON_GEN3_MOVE_GIGADRAIN,
        POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_SPLASH
    );
    init.teams[1].members[0].stats[0] = 10;
    PokemonBattle battle;
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    uint16_t full_hp = battle.sides[0].state[0].hp;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].hp == full_hp);
    assert(battle.effect_trace_count == 1);
    assert(battle.effect_traces[0].result == POKEMON_EFFECT_FAILED);
    assert(battle.effect_traces[0].damage_basis == 10);
    assert(battle.effect_traces[0].numerator == 1);
    assert(battle.effect_traces[0].denominator == 2);
    assert(battle.effect_traces[0].requested == 5);
    assert(battle.effect_traces[0].value == 0);

    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    battle.sides[0].state[0].hp -= 20;
    uint16_t hp_before = battle.sides[0].state[0].hp;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].hp == hp_before + 5);
    assert(battle.effect_traces[0].argument == POKEMON_DAMAGE_RELATIVE_DRAIN);
    assert(battle.effect_traces[0].damage_basis == 10);
    assert(battle.effect_traces[0].requested == 5);
    assert(battle.effect_traces[0].value == 5);

    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    battle.sides[0].state[0].hp -= 2;
    hp_before = battle.sides[0].state[0].hp;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].hp == hp_before + 2);
    assert(battle.effect_traces[0].value == 2);

    init = condition_init(
        POKEMON_GEN3_SPECIES_MAROWAK, POKEMON_GEN3_MOVE_DOUBLEEDGE,
        POKEMON_GEN3_SPECIES_BANETTE, POKEMON_GEN3_MOVE_SPLASH
    );
    init.teams[0].members[0].ability_id = POKEMON_GEN3_ABILITY_LIGHTNINGROD;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    hp_before = battle.sides[0].state[0].hp;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].hp == hp_before);
    assert(battle.effect_trace_count == 0);

    init = condition_init(
        POKEMON_GEN3_SPECIES_MAROWAK, POKEMON_GEN3_MOVE_DOUBLEEDGE,
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_PROTECT
    );
    init.teams[0].members[0].ability_id = POKEMON_GEN3_ABILITY_LIGHTNINGROD;
    init.teams[0].members[0].stats[5] = 100;
    init.teams[1].members[0].stats[5] = 300;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    hp_before = battle.sides[0].state[0].hp;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].hp == hp_before);
    assert(battle.effect_trace_count == 0);
}

static void test_recoil_faint_replacement_and_terminal(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_MAROWAK, POKEMON_GEN3_MOVE_DOUBLEEDGE,
        POKEMON_GEN3_SPECIES_SKARMORY, POKEMON_GEN3_MOVE_SPLASH
    );
    init.teams[0].members[0].ability_id = POKEMON_GEN3_ABILITY_LIGHTNINGROD;
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    battle.sides[0].state[0].hp = 1;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].fainted);
    assert(battle.request.kind[0] == POKEMON_REQUEST_SWITCH);
    assert(!battle.terminal);

    init.team_sizes[0] = 1;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    battle.sides[0].state[0].hp = 1;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.terminal);
    assert(battle.winner == 1);
    assert(battle.events[battle.event_count - 1].kind == POKEMON_EVENT_WIN);
}

static void test_multihit_distribution_and_per_hit_resolution(void) {
    static const uint8_t distribution[8] = {2, 2, 2, 3, 3, 3, 4, 5};
    uint8_t seen[6] = {0};
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    for (uint16_t tail = 1; tail < 1024; tail++) {
        PokemonBattleInit init = condition_init(
            POKEMON_GEN3_SPECIES_MAROWAK, POKEMON_GEN3_MOVE_BONERUSH,
            POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_SPLASH
        );
        init.seed[3] = tail;
        init.teams[1].members[0].stats[0] = 5000;
        init.teams[1].members[0].stats[2] = 1000;
        PokemonBattle battle;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        if (battle.hit_trace_count == 0) continue;
        assert(battle.draws[0].label == POKEMON_DRAW_ACCURACY);
        assert(battle.draws[1].label == POKEMON_DRAW_MULTIHIT_COUNT);
        assert(battle.draws[1].upper_bound == 8);
        uint8_t requested = distribution[battle.draws[1].result];
        seen[requested] = 1;
        assert(battle.hit_trace_count == requested + 2);
        assert(battle.hit_traces[0].kind == POKEMON_HIT_PLAN);
        assert(battle.hit_traces[0].requested_hits == requested);
        uint16_t total_damage = 0;
        for (uint8_t hit = 0; hit < requested; hit++) {
            const PokemonHitTrace *trace = &battle.hit_traces[hit + 1];
            assert(trace->kind == POKEMON_HIT_CONNECTED);
            assert(trace->hit_index == hit + 1);
            assert(trace->requested_hits == requested);
            assert(trace->damage != 0);
            total_damage = (uint16_t)(total_damage + trace->damage);
            assert(battle.draws[2 + hit * 2].label == POKEMON_DRAW_CRITICAL);
            assert(battle.draws[3 + hit * 2].label == POKEMON_DRAW_DAMAGE_ROLL);
        }
        const PokemonHitTrace *result = &battle.hit_traces[requested + 1];
        assert(result->kind == POKEMON_HIT_RESULT);
        assert(result->actual_hits == requested);
        assert(result->total_damage == total_damage);
        assert(result->stop_reason == POKEMON_HIT_STOP_COMPLETED);
        if (seen[2] && seen[3] && seen[4] && seen[5]) break;
    }
    assert(seen[2] && seen[3] && seen[4] && seen[5]);

    /* Exhausting the plan and fainting on its final hit is completion, not an
     * early target-fainted stop. */
    PokemonBattleInit final_ko = condition_init(
        POKEMON_GEN3_SPECIES_MAROWAK, POKEMON_GEN3_MOVE_BONERUSH,
        POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_SPLASH
    );
    final_ko.seed[3] = 36;
    final_ko.teams[1].members[0].stats[0] = 5000;
    final_ko.teams[1].members[0].stats[2] = 1000;
    PokemonBattle calibration;
    assert(pokemon_battle_init(&calibration, &final_ko) == POKEMON_OK);
    assert(pokemon_battle_step(&calibration, choices) == POKEMON_OK);
    const PokemonHitTrace *calibrated =
        &calibration.hit_traces[calibration.hit_trace_count - 1];
    assert(calibrated->kind == POKEMON_HIT_RESULT);
    assert(calibrated->requested_hits == 5);
    final_ko.teams[1].members[0].stats[0] = calibrated->total_damage;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &final_ko) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    const PokemonHitTrace *result = &battle.hit_traces[battle.hit_trace_count - 1];
    assert(result->actual_hits == result->requested_hits);
    assert(result->stop_reason == POKEMON_HIT_STOP_COMPLETED);
    assert(battle.sides[1].state[0].hp == 0);
}

static void test_multihit_descriptor_family_and_fixed_count(void) {
    static const struct {
        uint16_t move_id;
        uint8_t minimum;
        uint8_t maximum;
    } cases[] = {
        {POKEMON_GEN3_MOVE_ARMTHRUST, 2, 5},
        {POKEMON_GEN3_MOVE_BARRAGE, 2, 5},
        {POKEMON_GEN3_MOVE_BONEMERANG, 2, 2},
        {POKEMON_GEN3_MOVE_BULLETSEED, 2, 5},
        {POKEMON_GEN3_MOVE_COMETPUNCH, 2, 5},
        {POKEMON_GEN3_MOVE_DOUBLEKICK, 2, 2},
        {POKEMON_GEN3_MOVE_DOUBLESLAP, 2, 5},
        {POKEMON_GEN3_MOVE_FURYATTACK, 2, 5},
        {POKEMON_GEN3_MOVE_FURYSWIPES, 2, 5},
        {POKEMON_GEN3_MOVE_ICICLESPEAR, 2, 5},
        {POKEMON_GEN3_MOVE_PINMISSILE, 2, 5},
        {POKEMON_GEN3_MOVE_ROCKBLAST, 2, 5},
        {POKEMON_GEN3_MOVE_SPIKECANNON, 2, 5},
    };
    for (size_t i = 0; i < sizeof(cases) / sizeof(cases[0]); i++) {
        const PokemonMoveData *move_data = NULL;
        for (size_t j = 0; j < POKEMON_GEN3_SLICE_DATA.move_count; j++) {
            if (POKEMON_GEN3_SLICE_DATA.moves[j].id == cases[i].move_id) {
                move_data = &POKEMON_GEN3_SLICE_DATA.moves[j];
                break;
            }
        }
        assert(move_data != NULL);
        assert(move_data->multihit_min == cases[i].minimum);
        assert(move_data->multihit_max == cases[i].maximum);
        assert(move_data->damage_formula == POKEMON_DAMAGE_STANDARD);
        assert(move_data->effect_count == 0);
    }

    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_BONEMERANG,
        POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_SPLASH
    );
    init.teams[0].members[0].ability_id = POKEMON_GEN3_ABILITY_OWNTEMPO;
    init.teams[1].members[0].stats[0] = 5000;
    init.teams[1].members[0].stats[2] = 1000;
    PokemonBattle battle;
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.hit_trace_count == 4);
    assert(battle.hit_traces[0].kind == POKEMON_HIT_PLAN);
    assert(battle.hit_traces[0].requested_hits == 2);
    assert(battle.hit_traces[3].kind == POKEMON_HIT_RESULT);
    assert(battle.hit_traces[3].actual_hits == 2);
    for (size_t i = 0; i < battle.draw_count; i++) {
        assert(battle.draws[i].label != POKEMON_DRAW_MULTIHIT_COUNT);
    }
}

static void test_specialized_per_hit_composition(void) {
    const PokemonMoveData *triple = NULL;
    const PokemonMoveData *twin = NULL;
    for (size_t i = 0; i < POKEMON_GEN3_SLICE_DATA.move_count; i++) {
        const PokemonMoveData *candidate = &POKEMON_GEN3_SLICE_DATA.moves[i];
        if (candidate->id == POKEMON_GEN3_MOVE_TRIPLEKICK) triple = candidate;
        if (candidate->id == POKEMON_GEN3_MOVE_TWINEEDLE) twin = candidate;
    }
    assert(triple != NULL && twin != NULL);
    assert(triple->multihit_min == 3 && triple->multihit_max == 3);
    assert(triple->multihit_accuracy ==
        POKEMON_MULTIHIT_ACCURACY_EACH_HIT);
    assert(triple->base_power_policy == POKEMON_BASE_POWER_HIT_INDEX);
    assert(twin->multihit_min == 2 && twin->multihit_max == 2);
    assert(twin->multihit_accuracy == POKEMON_MULTIHIT_ACCURACY_ONCE);
    assert(twin->effect_count == 1);

    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_TRIPLEKICK,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[0].members[0].ability_id = POKEMON_GEN3_ABILITY_OWNTEMPO;
    init.teams[1].members[0].stats[0] = 5000;
    init.teams[1].members[0].stats[2] = 1000;
    uint16_t complete_seed = 0;
    uint16_t repeat_miss_seed = 0;
    for (uint16_t tail = 1; tail < 4096 &&
         (!complete_seed || !repeat_miss_seed); tail++) {
        init.seed[3] = tail;
        PokemonBattle candidate;
        assert(pokemon_battle_init(&candidate, &init) == POKEMON_OK);
        assert(pokemon_battle_step(&candidate, choices) == POKEMON_OK);
        if (candidate.hit_trace_count == 0) continue;
        const PokemonHitTrace *result =
            &candidate.hit_traces[candidate.hit_trace_count - 1];
        if (result->kind != POKEMON_HIT_RESULT) continue;
        if (result->actual_hits == 3) complete_seed = tail;
        if (result->actual_hits > 0 && result->actual_hits < 3 &&
            result->stop_reason == POKEMON_HIT_STOP_ACCURACY) {
            repeat_miss_seed = tail;
        }
    }
    assert(complete_seed != 0 && repeat_miss_seed != 0);

    PokemonBattle battle;
    init.seed[3] = complete_seed;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.hit_trace_count == 5);
    assert(battle.hit_traces[0].kind == POKEMON_HIT_PLAN);
    assert(battle.hit_traces[4].stop_reason == POKEMON_HIT_STOP_COMPLETED);
    assert(battle.hit_traces[1].calculated_damage <
        battle.hit_traces[2].calculated_damage);
    assert(battle.hit_traces[2].calculated_damage <
        battle.hit_traces[3].calculated_damage);
    size_t accuracy_draws = 0;
    for (size_t i = 0; i < battle.draw_count; i++) {
        accuracy_draws += battle.draws[i].label == POKEMON_DRAW_ACCURACY;
        assert(battle.draws[i].label != POKEMON_DRAW_MULTIHIT_COUNT);
    }
    assert(accuracy_draws == 3);

    init.seed[3] = repeat_miss_seed;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    const PokemonHitTrace *repeat_miss =
        &battle.hit_traces[battle.hit_trace_count - 1];
    assert(repeat_miss->kind == POKEMON_HIT_RESULT);
    assert(repeat_miss->stop_reason == POKEMON_HIT_STOP_ACCURACY);
    for (size_t i = 0; i < battle.event_count; i++) {
        assert(battle.events[i].kind != POKEMON_EVENT_MISS);
    }

    init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_TWINEEDLE,
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[0].members[0].ability_id = POKEMON_GEN3_ABILITY_OWNTEMPO;
    init.teams[1].members[0].stats[0] = 5000;
    init.teams[1].members[0].stats[2] = 1000;
    uint16_t poison_seed = 0;
    for (uint16_t tail = 1; tail < 4096 && !poison_seed; tail++) {
        init.seed[3] = tail;
        PokemonBattle candidate;
        assert(pokemon_battle_init(&candidate, &init) == POKEMON_OK);
        assert(pokemon_battle_step(&candidate, choices) == POKEMON_OK);
        if (candidate.sides[1].state[0].status.kind == POKEMON_STATUS_POISON) {
            poison_seed = tail;
        }
    }
    assert(poison_seed != 0);
    init.seed[3] = poison_seed;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.hit_traces[battle.hit_trace_count - 1].actual_hits == 2);
    size_t secondary_draws = 0;
    accuracy_draws = 0;
    for (size_t i = 0; i < battle.draw_count; i++) {
        secondary_draws += battle.draws[i].label == POKEMON_DRAW_SECONDARY;
        accuracy_draws += battle.draws[i].label == POKEMON_DRAW_ACCURACY;
    }
    assert(secondary_draws == 2);
    assert(accuracy_draws == 1);
    assert(pokemon_battle_check_invariants(&battle));
}

static void test_secret_power_resolved_terrain_free_descriptor(void) {
    const PokemonMoveData *move_data = NULL;
    const PokemonHandlerDescriptor *modify_move = NULL;
    for (size_t i = 0; i < POKEMON_GEN3_SLICE_DATA.move_count; i++) {
        if (POKEMON_GEN3_SLICE_DATA.moves[i].id ==
                POKEMON_GEN3_MOVE_SECRETPOWER) {
            move_data = &POKEMON_GEN3_SLICE_DATA.moves[i];
            break;
        }
    }
    for (size_t i = 0; i < POKEMON_GEN3_SLICE_DATA.handler_count; i++) {
        if (POKEMON_GEN3_SLICE_DATA.handlers[i].id ==
                POKEMON_GEN3_HANDLER_SECRET_POWER_MODIFY_MOVE) {
            modify_move = &POKEMON_GEN3_SLICE_DATA.handlers[i];
            break;
        }
    }
    assert(move_data != NULL && modify_move != NULL);
    assert(move_data->type == POKEMON_GEN3_TYPE_NORMAL);
    assert(move_data->category == POKEMON_CATEGORY_PHYSICAL);
    assert(move_data->power == 70);
    assert(move_data->accuracy.kind == POKEMON_ACCURACY_PERCENT);
    assert(move_data->accuracy.percent == 100);
    assert(move_data->effect_count == 1);
    const PokemonEffectOp *effect =
        &POKEMON_GEN3_SLICE_DATA.effects[move_data->effect_offset];
    assert(effect->kind == POKEMON_EFFECT_SET_STATUS);
    assert(effect->phase == POKEMON_EFFECT_PHASE_AFTER_HIT);
    assert(effect->target == POKEMON_EFFECT_TARGET_MOVE_TARGET);
    assert(effect->chance == 30);
    assert(effect->argument == POKEMON_STATUS_PARALYSIS);

    /* The inherited callback is still observable in handler discovery, but
     * terrain is absent from the resolved Gen 3 field domain, so its program
     * is the honest identity transformation. */
    assert(modify_move->event == POKEMON_HANDLER_EVENT_MODIFY_MOVE);
    assert(modify_move->source_kind == POKEMON_HANDLER_SOURCE_MOVE);
    assert(modify_move->source_id == POKEMON_GEN3_MOVE_SECRETPOWER);
    assert(modify_move->scope == POKEMON_HANDLER_SCOPE_SOURCE);
    assert(modify_move->route == POKEMON_HANDLER_ROUTE_MOVE_SELF);
    assert(modify_move->program_count == 0);
    assert(modify_move->exceptional_handler_id == POKEMON_EXCEPTION_NONE);
}

static void test_multihit_configuration_rejection(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_ARMTHRUST,
        POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_SPLASH
    );
    init.teams[0].members[0].ability_id = POKEMON_GEN3_ABILITY_OWNTEMPO;
    PokemonMoveData malformed_moves[POKEMON_GEN3_MOVE_COUNT];
    PokemonData malformed_data = POKEMON_GEN3_SLICE_DATA;
    PokemonResolvedBundle malformed_bundle = *init.bundle;
    PokemonBattle untouched;
    memset(&untouched, 0x5a, sizeof(untouched));
    PokemonBattle before = untouched;
    size_t index = 0;
    while (POKEMON_GEN3_SLICE_DATA.moves[index].id !=
            POKEMON_GEN3_MOVE_ARMTHRUST) index++;

    static const uint8_t invalid_shapes[][2] = {
        {0, 5}, {1, 1}, {2, 4}, {5, 2},
    };
    for (size_t i = 0;
         i < sizeof(invalid_shapes) / sizeof(invalid_shapes[0]); i++) {
        memcpy(malformed_moves, POKEMON_GEN3_SLICE_DATA.moves,
            sizeof(malformed_moves));
        malformed_moves[index].multihit_min = invalid_shapes[i][0];
        malformed_moves[index].multihit_max = invalid_shapes[i][1];
        malformed_data.moves = malformed_moves;
        malformed_bundle.data = &malformed_data;
        init.bundle = &malformed_bundle;
        assert(pokemon_battle_init(&untouched, &init) ==
            POKEMON_INVALID_CONFIGURATION);
        assert(memcmp(&untouched, &before, sizeof(untouched)) == 0);
    }

    uint8_t invalid_outcomes[8] = {2, 2, 2, 3, 3, 3, 4, 6};
    PokemonGeneration malformed_generation = POKEMON_GEN3_RULES;
    malformed_generation.multihit.outcomes = invalid_outcomes;
    malformed_bundle = POKEMON_GEN3_OU_BUNDLE;
    malformed_bundle.rules = &malformed_generation;
    init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_ARMTHRUST,
        POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_SPLASH
    );
    init.teams[0].members[0].ability_id = POKEMON_GEN3_ABILITY_OWNTEMPO;
    init.bundle = &malformed_bundle;
    assert(pokemon_battle_init(&untouched, &init) ==
        POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&untouched, &before, sizeof(untouched)) == 0);

    malformed_generation = POKEMON_GEN3_RULES;
    malformed_generation.multihit.outcomes = NULL;
    malformed_bundle.rules = &malformed_generation;
    assert(pokemon_battle_init(&untouched, &init) ==
        POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&untouched, &before, sizeof(untouched)) == 0);

}

static void test_multihit_gates_early_stop_and_capacity(void) {
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_MAROWAK, POKEMON_GEN3_MOVE_BONERUSH,
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_PROTECT
    );
    init.teams[1].members[0].stats[5] = 400;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.hit_trace_count == 0);
    for (size_t draw = 0; draw < battle.draw_count; draw++) {
        assert(battle.draws[draw].label != POKEMON_DRAW_MULTIHIT_COUNT);
    }

    init = condition_init(
        POKEMON_GEN3_SPECIES_MAROWAK, POKEMON_GEN3_MOVE_BONERUSH,
        POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_SPLASH
    );
    init.teams[1].members[0].stats[0] = 1;
    int connected = 0;
    for (uint16_t tail = 1; tail < 128 && !connected; tail++) {
        init.seed[3] = tail;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        connected = battle.hit_trace_count != 0;
    }
    assert(connected);
    assert(battle.hit_trace_count == 3);
    assert(battle.hit_traces[0].kind == POKEMON_HIT_PLAN);
    assert(battle.hit_traces[1].kind == POKEMON_HIT_CONNECTED);
    assert(battle.hit_traces[2].kind == POKEMON_HIT_RESULT);
    assert(battle.hit_traces[2].actual_hits == 1);
    assert(battle.hit_traces[2].total_damage == 1);
    assert(battle.hit_traces[2].stop_reason == POKEMON_HIT_STOP_TARGET_FAINTED);
    assert(battle.request.kind[1] == POKEMON_REQUEST_SWITCH);

    init = condition_init(
        POKEMON_GEN3_SPECIES_MAROWAK, POKEMON_GEN3_MOVE_BONERUSH,
        POKEMON_GEN3_SPECIES_MAROWAK, POKEMON_GEN3_MOVE_BONERUSH
    );
    for (size_t side = 0; side < POKEMON_SIDES; side++) {
        init.teams[side].members[0].stats[0] = 5000;
        init.teams[side].members[0].stats[2] = 1000;
    }
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.hit_trace_count <= POKEMON_HIT_TRACE_CAPACITY);
    assert(pokemon_battle_check_invariants(&battle));
    PokemonBattleView view;
    pokemon_battle_view(&battle, &view);
    assert(view.hit_trace_count == battle.hit_trace_count);
    assert(memcmp(view.hit_traces, battle.hit_traces, sizeof(view.hit_traces)) == 0);
}

static void assert_no_damage_randomness(const PokemonBattle *battle) {
    for (size_t i = 0; i < battle->draw_count; i++) {
        assert(battle->draws[i].label != POKEMON_DRAW_CRITICAL);
        assert(battle->draws[i].label != POKEMON_DRAW_DAMAGE_ROLL);
    }
}

static void test_typed_ohko_pipeline(void) {
    const uint16_t ohko_moves[] = {
        POKEMON_GEN3_MOVE_FISSURE, POKEMON_GEN3_MOVE_GUILLOTINE,
        POKEMON_GEN3_MOVE_HORNDRILL, POKEMON_GEN3_MOVE_SHEERCOLD,
    };
    for (size_t expected = 0;
         expected < sizeof(ohko_moves) / sizeof(ohko_moves[0]); expected++) {
        const PokemonMoveData *descriptor = NULL;
        for (size_t i = 0; i < POKEMON_GEN3_SLICE_DATA.move_count; i++) {
            if (POKEMON_GEN3_SLICE_DATA.moves[i].id == ohko_moves[expected]) {
                descriptor = &POKEMON_GEN3_SLICE_DATA.moves[i];
                break;
            }
        }
        assert(descriptor != NULL);
        assert(descriptor->ohko.kind == POKEMON_OHKO_ANY);
        assert(descriptor->ohko.excluded_type == 0);
        assert(descriptor->damage_formula ==
            POKEMON_DAMAGE_TARGET_CURRENT_HP);
    }
    assert(POKEMON_GEN3_RULES.ohko.base_accuracy == 30);

    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_FISSURE,
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[1].members[0].stats[0] = 200;
    init.initial_hp[1][0] = 200;
    uint16_t hit_seed = 0;
    uint16_t miss_seed = 0;
    for (uint16_t tail = 1; tail < 4096 && (!hit_seed || !miss_seed); tail++) {
        init.seed[3] = tail;
        PokemonBattle candidate;
        assert(pokemon_battle_init(&candidate, &init) == POKEMON_OK);
        assert(pokemon_battle_step(&candidate, choices) == POKEMON_OK);
        for (size_t draw = 0; draw < candidate.draw_count; draw++) {
            if (candidate.draws[draw].label != POKEMON_DRAW_ACCURACY) continue;
            if (candidate.draws[draw].result < 30 && !hit_seed) hit_seed = tail;
            if (candidate.draws[draw].result >= 30 && !miss_seed) miss_seed = tail;
            break;
        }
    }
    assert(hit_seed && miss_seed);

    PokemonBattle battle;
    init.seed[3] = hit_seed;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    battle.sides[0].state[0].boosts[POKEMON_STAT_ACCURACY] = -6;
    battle.sides[1].state[0].boosts[POKEMON_STAT_EVASION] = 6;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].state[0].hp == 0);
    assert(!battle.terminal);
    assert(battle.request.kind[1] == POKEMON_REQUEST_SWITCH);
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 1);
    assert(battle.damage_formula_trace_count == 1);
    assert(battle.damage_formula_traces[0].formula ==
        POKEMON_DAMAGE_TARGET_CURRENT_HP);
    assert(battle.damage_formula_traces[0].resolved_value == 200);
    assert_no_damage_randomness(&battle);

    PokemonBattleInit terminal_init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_FISSURE,
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SPLASH);
    terminal_init.team_sizes[1] = 1;
    terminal_init.teams[1].members[0].stats[0] = 200;
    terminal_init.initial_hp[1][0] = 200;
    terminal_init.seed[3] = hit_seed;
    assert(pokemon_battle_init(&battle, &terminal_init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.terminal && battle.winner == 0);

    init.seed[3] = miss_seed;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].state[0].hp == 200);
    assert(event_kind_count(&battle, POKEMON_EVENT_MISS) == 1);
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 1);

    /* The generation policy adds the level delta to the base probability. A
     * roll in [30, 40) misses at equal level and connects at +10 levels. */
    uint16_t level_delta_seed = 0;
    for (uint16_t tail = 1; tail < 4096 && !level_delta_seed; tail++) {
        init.seed[3] = tail;
        PokemonBattle candidate;
        assert(pokemon_battle_init(&candidate, &init) == POKEMON_OK);
        assert(pokemon_battle_step(&candidate, choices) == POKEMON_OK);
        for (size_t draw = 0; draw < candidate.draw_count; draw++) {
            if (candidate.draws[draw].label == POKEMON_DRAW_ACCURACY &&
                candidate.draws[draw].result >= 30 &&
                candidate.draws[draw].result < 40) {
                level_delta_seed = tail;
                break;
            }
        }
    }
    assert(level_delta_seed);
    init.seed[3] = level_delta_seed;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].state[0].hp == 200);
    assert(event_kind_count(&battle, POKEMON_EVENT_MISS) == 1);
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 1);
    init.teams[1].members[0].level = 90;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].state[0].hp == 0);
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 1);

    /* Natural immunity is deferred until after the accuracy draw. Gen 3
     * reports immunity even when the same roll would otherwise miss. */
    init.teams[1].members[0].level = 100;
    init.teams[1].members[0].species_id = POKEMON_GEN3_SPECIES_ARTICUNO;
    init.seed[3] = miss_seed;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].state[0].hp == 200);
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 1);
    assert(event_kind_count(&battle, POKEMON_EVENT_MISS) == 0);
    assert(event_kind_count(&battle, POKEMON_EVENT_IMMUNE) == 1);
    uint8_t saw_type_immunity = 0;
    for (size_t i = 0; i < battle.event_count; i++) {
        saw_type_immunity |= battle.events[i].kind == POKEMON_EVENT_IMMUNE &&
            battle.events[i].immunity_cause ==
                POKEMON_IMMUNITY_NATURAL_TYPE;
    }
    assert(saw_type_immunity);
    assert_no_damage_randomness(&battle);

    init.seed[3] = hit_seed;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].state[0].hp == 200);
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 1);
    assert(event_kind_count(&battle, POKEMON_EVENT_IMMUNE) == 1);
    assert_no_damage_randomness(&battle);

    /* A higher-level target is an OHKO-rule immunity before Accuracy/TryHit
     * and consumes no PRNG. */
    init.teams[1].members[0].species_id = POKEMON_GEN3_SPECIES_PERSIAN;
    init.teams[0].members[0].level = 99;
    init.teams[1].members[0].level = 100;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 0);
    assert(battle.draw_count == 1);
    assert(battle.draws[0].label == POKEMON_DRAW_END_TURN);
    assert(battle.handler_count == 0);
    assert(battle.damage_formula_trace_count == 0);
    assert(event_kind_count(&battle, POKEMON_EVENT_IMMUNE) == 1);
    uint8_t saw_ohko_rule = 0;
    for (size_t i = 0; i < battle.event_count; i++) {
        saw_ohko_rule |= battle.events[i].kind == POKEMON_EVENT_IMMUNE &&
            battle.events[i].immunity_cause == POKEMON_IMMUNITY_OHKO_RULE;
    }
    assert(saw_ohko_rule);

    /* A miss never reaches Sturdy's TryHit handler. */
    init.teams[0].members[0].level = 100;
    init.teams[1].members[0].species_id = POKEMON_GEN3_SPECIES_AGGRON;
    init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_STURDY;
    init.teams[1].members[0].move_ids[0] = POKEMON_GEN3_MOVE_TELEPORT;
    uint16_t sturdy_miss_seed = 0;
    for (uint16_t tail = 1; tail < 4096 && !sturdy_miss_seed; tail++) {
        init.seed[3] = tail;
        PokemonBattle candidate;
        assert(pokemon_battle_init(&candidate, &init) == POKEMON_OK);
        assert(pokemon_battle_step(&candidate, choices) == POKEMON_OK);
        if (event_kind_count(&candidate, POKEMON_EVENT_MISS) == 1) {
            sturdy_miss_seed = tail;
        }
    }
    assert(sturdy_miss_seed);
    init.seed[3] = sturdy_miss_seed;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(handler_id_count(
        &battle, POKEMON_GEN3_HANDLER_STURDY_TRY_HIT) == 0);
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 1);

    /* Sturdy is an ordinary generated TryHit cancellation after a successful
     * roll, not a move-ID branch or modern full-HP damage cap. */
    init.seed[3] = hit_seed;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].state[0].hp == 200);
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 1);
    assert(handler_id_count(
        &battle, POKEMON_GEN3_HANDLER_STURDY_TRY_HIT) >= 1);
    uint8_t saw_sturdy_immunity = 0;
    for (size_t i = 0; i < battle.event_count; i++) {
        saw_sturdy_immunity |= battle.events[i].kind == POKEMON_EVENT_IMMUNE &&
            battle.events[i].handler_id ==
                POKEMON_GEN3_HANDLER_STURDY_TRY_HIT;
    }
    assert(saw_sturdy_immunity);
    assert_no_damage_randomness(&battle);

    /* Gen 3 Sturdy owns only the OHKO TryHit guard. It must not acquire the
     * later-generation full-HP survival behavior for ordinary damage. */
    init.teams[0].members[0].move_ids[0] = POKEMON_GEN3_MOVE_AERIALACE;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    battle.sides[1].state[0].hp = 1;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].state[0].hp == 0);
    assert(event_kind_count(&battle, POKEMON_EVENT_FAINT) == 1);
    assert(event_kind_count(&battle, POKEMON_EVENT_IMMUNE) == 0);

    init.teams[0].members[0].move_ids[0] = POKEMON_GEN3_MOVE_FISSURE;

    /* Current real HP is the requested amount even when Substitute owns the
     * hit. At 1/200 HP a healthier Substitute loses exactly one HP. */
    init.teams[1].members[0].species_id = POKEMON_GEN3_SPECIES_PERSIAN;
    init.teams[1].members[0].ability_id = 0;
    init.initial_hp[1][0] = 1;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    PokemonMutable *target = &battle.sides[1].state[0];
    target->volatiles[target->volatile_count++] = (PokemonVolatileState){
        .kind = POKEMON_VOLATILE_SUBSTITUTE,
        .descriptor_id = POKEMON_GEN3_CONDITION_VOLATILE_SUBSTITUTE,
        .state_generation = 1,
        .effect_order = ++battle.next_holder_effect_order,
        .source = {POKEMON_ENTITY_POKEMON, 1, 0},
        .source_effect = {POKEMON_SOURCE_EFFECT_MOVE,
            POKEMON_GEN3_MOVE_SUBSTITUTE},
        .payload.substitute = {.hp = 50},
    };
    assert(pokemon_battle_check_invariants(&battle));
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(target->hp == 1);
    int substitute = test_volatile_index(target, POKEMON_VOLATILE_SUBSTITUTE);
    assert(substitute >= 0);
    assert(target->volatiles[substitute].payload.substitute.hp == 49);
    assert(battle.damage_formula_traces[0].resolved_value == 1);

    /* When current HP exceeds Substitute HP, the Substitute breaks and the
     * excess still never spills into the holder. */
    init.initial_hp[1][0] = 200;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    target = &battle.sides[1].state[0];
    target->volatiles[target->volatile_count++] = (PokemonVolatileState){
        .kind = POKEMON_VOLATILE_SUBSTITUTE,
        .descriptor_id = POKEMON_GEN3_CONDITION_VOLATILE_SUBSTITUTE,
        .state_generation = 1,
        .effect_order = ++battle.next_holder_effect_order,
        .source = {POKEMON_ENTITY_POKEMON, 1, 0},
        .source_effect = {POKEMON_SOURCE_EFFECT_MOVE,
            POKEMON_GEN3_MOVE_SUBSTITUTE},
        .payload.substitute = {.hp = 50},
    };
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(target->hp == 200);
    assert(test_volatile_index(target, POKEMON_VOLATILE_SUBSTITUTE) < 0);
    assert(battle.damage_formula_traces[0].resolved_value == 200);

    /* Invalid typed descriptors are rejected before battle mutation or PRNG. */
    PokemonData data = POKEMON_GEN3_SLICE_DATA;
    PokemonMoveData moves[data.move_count];
    memcpy(moves, data.moves, sizeof(moves));
    data.moves = moves;
    for (size_t i = 0; i < data.move_count; i++) {
        if (moves[i].id == POKEMON_GEN3_MOVE_FISSURE) {
            moves[i].ohko.kind = POKEMON_OHKO_EXCLUDED_TYPE;
            moves[i].ohko.excluded_type = data.type_count;
        }
    }
    PokemonResolvedBundle bundle = *init.bundle;
    PokemonFormatPolicy policy = *bundle.policy;
    policy.status_clauses = NULL;
    policy.status_clause_count = 0;
    bundle.policy = &policy;
    bundle.data = &data;
    init.bundle = &bundle;
    memset(&battle, 0xA5, sizeof(battle));
    PokemonBattle before = battle;
    assert(pokemon_battle_init(&battle, &init) ==
        POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&battle, &before, sizeof(battle)) == 0);
}

static void assert_invalid_resolved_data_is_atomic(
    PokemonBattleInit init, const PokemonData *data
) {
    PokemonResolvedBundle bundle = *init.bundle;
    bundle.data = data;
    init.bundle = &bundle;
    PokemonBattle battle;
    memset(&battle, 0xA5, sizeof(battle));
    PokemonBattle before = battle;
    assert(pokemon_battle_init(&battle, &init) ==
        POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&battle, &before, sizeof(battle)) == 0);
}

static void test_curse_invocation_profiles_and_lifecycle(void) {
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};

    /* The non-Ghost profile is an invocation-local rewrite to a self-targeted
     * three-stat selfDrop program. Gen 3 owns one unconditional secondary
     * draw for the grouped selfDrop, not one draw per stat. */
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SNORLAX, POKEMON_GEN3_MOVE_CURSE,
        POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_SPLASH);
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    PokemonMutable *user = &battle.sides[0].state[0];
    assert(user->boosts[POKEMON_STAT_ATK] == 1);
    assert(user->boosts[POKEMON_STAT_DEF] == 1);
    assert(user->boosts[POKEMON_STAT_SPE] == -1);
    assert(draw_label_count(&battle, POKEMON_DRAW_SECONDARY) == 1);
    const PokemonMoveInvocationTrace *curse_trace = NULL;
    for (size_t i = 0; i < battle.move_invocation_count; i++) {
        if (battle.move_invocations[i].invocation.move_id ==
                POKEMON_GEN3_MOVE_CURSE) {
            curse_trace = &battle.move_invocations[i];
            break;
        }
    }
    assert(curse_trace != NULL);
    assert(curse_trace->resolved_target.kind == POKEMON_ENTITY_POKEMON);
    assert(curse_trace->resolved_target.side == 0);
    assert(curse_trace->resolved_target.slot == 0);

    /* The Ghost profile installs the target-owned condition before charging
     * half of the source's maximum HP. Its residual runs on the same turn. */
    init = condition_init(
        POKEMON_GEN3_SPECIES_GENGAR, POKEMON_GEN3_MOVE_CURSE,
        POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_SPLASH);
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    const uint16_t source_max_hp = init.teams[0].members[0].stats[0];
    const uint16_t target_max_hp = init.teams[1].members[0].stats[0];
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    user = &battle.sides[0].state[0];
    PokemonMutable *target = &battle.sides[1].state[0];
    assert(user->hp == source_max_hp - source_max_hp / 2);
    assert(target->hp == target_max_hp - target_max_hp / 4);
    assert(test_volatile_index(target, POKEMON_VOLATILE_CURSE) >= 0);
    assert(handler_id_count(&battle, POKEMON_GEN3_HANDLER_CURSE_START) == 1);
    assert(handler_id_count(&battle, POKEMON_GEN3_HANDLER_CURSE_RESIDUAL) == 1);
    assert(draw_label_count(&battle, POKEMON_DRAW_SECONDARY) == 0);

    /* The move-owned TryHit guard rejects a duplicate before another payment;
     * only the already-installed condition continues its residual work. */
    const uint16_t source_hp_after_first = user->hp;
    const uint16_t target_hp_after_first = target->hp;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(user->hp == source_hp_after_first);
    assert(target->hp == target_hp_after_first - target_max_hp / 4);
    assert(handler_id_count(&battle, POKEMON_GEN3_HANDLER_CURSE_HIT) == 0);
    assert(handler_id_count(&battle, POKEMON_GEN3_HANDLER_CURSE_RESIDUAL) == 1);

    /* Substitute removes the invocation-local primary program during
     * ModifyMove. It therefore blocks installation and the source payment. */
    init = condition_init(
        POKEMON_GEN3_SPECIES_GENGAR, POKEMON_GEN3_MOVE_CURSE,
        POKEMON_GEN3_SPECIES_ALAKAZAM, POKEMON_GEN3_MOVE_SUBSTITUTE);
    init.teams[0].members[0].stats[5] = 100;
    init.teams[1].members[0].stats[5] = 300;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    const uint16_t ghost_hp_before = battle.sides[0].state[0].hp;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].hp == ghost_hp_before);
    assert(test_volatile_index(
        &battle.sides[1].state[0], POKEMON_VOLATILE_SUBSTITUTE) >= 0);
    assert(test_volatile_index(
        &battle.sides[1].state[0], POKEMON_VOLATILE_CURSE) < 0);
    assert(handler_id_count(&battle, POKEMON_GEN3_HANDLER_CURSE_HIT) == 0);
}

static void test_generated_move_call_pool_and_atomic_delegation(void) {
    const PokemonData *data = &POKEMON_GEN3_SLICE_DATA;
    assert(pokemon_validate_move_call_pools(data));
    assert(data->move_call_pool_count == 1);
    const PokemonMoveCallPool *pool = &data->move_call_pools[0];
    assert(pool->id == 1);
    assert(pool->caller_move_id == POKEMON_GEN3_MOVE_METRONOME);
    assert(pool->candidate_count == 336);
    static const struct {
        size_t index;
        uint16_t executable_id;
        const char *id;
    } ohko[] = {
        {11, POKEMON_GEN3_MOVE_GUILLOTINE, "guillotine"},
        {31, POKEMON_GEN3_MOVE_HORNDRILL, "horndrill"},
        {88, POKEMON_GEN3_MOVE_FISSURE, "fissure"},
        {311, POKEMON_GEN3_MOVE_SHEERCOLD, "sheercold"},
    };
    for (size_t i = 0; i < sizeof(ohko) / sizeof(ohko[0]); i++) {
        const PokemonMoveIdentity *identity = pokemon_move_identity(
            data, data->move_call_pool_candidates[
                pool->candidate_offset + ohko[i].index]);
        assert(identity != NULL);
        assert(identity->executable_id == ohko[i].executable_id);
        assert(strcmp(identity->id, ohko[i].id) == 0);
    }

    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_METRONOME,
        POKEMON_GEN3_SPECIES_ARTICUNO, POKEMON_GEN3_MOVE_TELEPORT);
    init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_PRESSURE;
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    uint16_t fissure_seed = 0;
    for (uint32_t tail = 1; tail <= UINT16_MAX && !fissure_seed; tail++) {
        init.seed[3] = (uint16_t)tail;
        PokemonBattle candidate;
        assert(pokemon_battle_init(&candidate, &init) == POKEMON_OK);
        int status = pokemon_battle_step(&candidate, choices);
        if (status != POKEMON_OK) {
            assert(status == POKEMON_UNSUPPORTED_CAPABILITY);
            continue;
        }
        for (size_t draw = 0; draw < candidate.draw_count; draw++) {
            if (candidate.draws[draw].label ==
                    POKEMON_DRAW_MOVE_DELEGATION_SELECTION &&
                candidate.draws[draw].result == 88) {
                fissure_seed = (uint16_t)tail;
                break;
            }
        }
    }
    assert(fissure_seed);
    init.seed[3] = fissure_seed;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    uint8_t pp_before = battle.sides[0].state[0].pp[0];
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(draw_label_count(
        &battle, POKEMON_DRAW_MOVE_DELEGATION_SELECTION) == 1);
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 1);
    assert(battle.sides[0].state[0].pp[0] + 1 == pp_before);
    assert(battle.move_invocation_count >= 2);
    const PokemonMoveInvocation *child = NULL;
    for (size_t i = 0; i < battle.move_invocation_count; i++) {
        if (battle.move_invocations[i].invocation.entry ==
                POKEMON_MOVE_ENTRY_CALLED &&
            battle.move_invocations[i].invocation.move_id ==
                POKEMON_GEN3_MOVE_FISSURE) {
            child = &battle.move_invocations[i].invocation;
            break;
        }
    }
    assert(child != NULL);
    assert(child->entry == POKEMON_MOVE_ENTRY_CALLED);
    assert(child->move_id == POKEMON_GEN3_MOVE_FISSURE);
    assert(child->parent_invocation_id ==
        battle.move_invocations[0].invocation.invocation_id);
    assert(child->source_effect.kind == POKEMON_SOURCE_EFFECT_MOVE);
    assert(child->source_effect.id == POKEMON_GEN3_MOVE_METRONOME);
    assert(!child->owns_pp_deduction);
    assert(event_kind_count(&battle, POKEMON_EVENT_IMMUNE) == 1);

    /* Every pinned Gen 3 Metronome candidate now resolves to an executable
     * descriptor; child-invocation closure is a generated-data invariant. */
    for (size_t i = 0; i < pool->candidate_count; i++) {
        uint16_t candidate = data->move_call_pool_candidates[
            pool->candidate_offset + i];
        const PokemonMoveIdentity *identity = pokemon_move_identity(
            data, candidate);
        assert(identity != NULL && identity->executable_id != 0);
    }

    /* Pool membership is a set, and generated catalog-to-executable links
     * must preserve one immutable move identity. */
    uint16_t duplicate_candidates[data->move_call_pool_candidate_count];
    memcpy(duplicate_candidates, data->move_call_pool_candidates,
        sizeof(duplicate_candidates));
    duplicate_candidates[1] = duplicate_candidates[0];
    PokemonData invalid_data = *data;
    invalid_data.move_call_pool_candidates = duplicate_candidates;
    assert(!pokemon_validate_move_call_pools(&invalid_data));
    assert_invalid_resolved_data_is_atomic(init, &invalid_data);

    PokemonMoveIdentity mismatched_catalog[data->move_catalog_count];
    memcpy(mismatched_catalog, data->move_catalog,
        sizeof(mismatched_catalog));
    const uint16_t fissure_catalog = data->move_call_pool_candidates[
        pool->candidate_offset + 88];
    mismatched_catalog[fissure_catalog - 1].executable_id =
        POKEMON_GEN3_MOVE_GUILLOTINE;
    invalid_data = *data;
    invalid_data.move_catalog = mismatched_catalog;
    assert(!pokemon_validate_move_call_pools(&invalid_data));
    assert_invalid_resolved_data_is_atomic(init, &invalid_data);

    size_t call_handler = SIZE_MAX;
    size_t call_binding = SIZE_MAX;
    for (size_t i = 0; i < data->handler_count; i++) {
        if (data->handlers[i].source_id == POKEMON_GEN3_MOVE_METRONOME &&
            data->handlers[i].event ==
                POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK) call_handler = i;
    }
    for (size_t i = 0; i < data->owner_binding_index_count; i++) {
        if (data->owner_binding_index[i].owner_kind == POKEMON_OWNER_MOVE &&
            data->owner_binding_index[i].owner_id ==
                POKEMON_GEN3_MOVE_METRONOME &&
            data->owner_binding_index[i].event ==
                POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK) call_binding = i;
    }
    assert(call_handler != SIZE_MAX && call_binding != SIZE_MAX);
    const size_t call_program = data->handlers[call_handler].program_offset;
    assert(data->handlers[call_handler].program_count == 1);

    PokemonHandlerOp invalid_programs[data->handler_program_count];
    memcpy(invalid_programs, data->handler_programs, sizeof(invalid_programs));
    invalid_programs[call_program].opcode = POKEMON_HANDLER_OP_RETURN_UNDEFINED;
    invalid_data = *data;
    invalid_data.handler_programs = invalid_programs;
    assert(!pokemon_validate_move_call_pools(&invalid_data));
    assert_invalid_resolved_data_is_atomic(init, &invalid_data);

    memcpy(invalid_programs, data->handler_programs, sizeof(invalid_programs));
    invalid_programs[call_program].argument = pool->id + 1;
    invalid_data = *data;
    invalid_data.handler_programs = invalid_programs;
    assert(!pokemon_validate_move_call_pools(&invalid_data));
    assert_invalid_resolved_data_is_atomic(init, &invalid_data);

    PokemonHandlerDescriptor duplicate_handlers[data->handler_count + 1];
    memcpy(duplicate_handlers, data->handlers,
        data->handler_count * sizeof(duplicate_handlers[0]));
    duplicate_handlers[data->handler_count] = data->handlers[call_handler];
    invalid_data = *data;
    invalid_data.handlers = duplicate_handlers;
    invalid_data.handler_count = data->handler_count + 1;
    assert(!pokemon_validate_move_call_pools(&invalid_data));
    assert_invalid_resolved_data_is_atomic(init, &invalid_data);

    PokemonMoveData invalid_moves[data->move_count];
    memcpy(invalid_moves, data->moves, sizeof(invalid_moves));
    for (size_t i = 0; i < data->move_count; i++) {
        if (invalid_moves[i].id == POKEMON_GEN3_MOVE_FISSURE) {
            invalid_moves[i].accuracy.percent = 99;
        }
    }
    invalid_data = *data;
    invalid_data.moves = invalid_moves;
    assert_invalid_resolved_data_is_atomic(init, &invalid_data);
}

static void test_generated_fixed_move_delegation(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_NATUREPOWER,
        POKEMON_GEN3_SPECIES_ARTICUNO, POKEMON_GEN3_MOVE_TELEPORT);
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    uint16_t hp_before = battle.sides[1].state[0].hp;
    uint8_t pp_before = battle.sides[0].state[0].pp[0];
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].state[0].hp < hp_before);
    assert(battle.sides[0].state[0].pp[0] + 1 == pp_before);
    /* Gen 3 inherits the older accuracy algorithm: numeric self-target status
     * moves still dispatch Accuracy and consume their ordinary roll. */
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 1);
    assert(draw_label_count(
        &battle, POKEMON_DRAW_MOVE_DELEGATION_SELECTION) == 0);
    assert(battle.move_invocation_count >= 2);
    const PokemonMoveInvocation *parent =
        &battle.move_invocations[0].invocation;
    const PokemonMoveInvocation *child =
        &battle.move_invocations[1].invocation;
    assert(parent->move_id == POKEMON_GEN3_MOVE_NATUREPOWER);
    assert(child->entry == POKEMON_MOVE_ENTRY_CALLED);
    assert(child->move_id == POKEMON_GEN3_MOVE_SWIFT);
    assert(child->parent_invocation_id == parent->invocation_id);
    assert(child->source_effect.kind == POKEMON_SOURCE_EFFECT_MOVE);
    assert(child->source_effect.id == POKEMON_GEN3_MOVE_NATUREPOWER);
    assert(!child->owns_pp_deduction);

    size_t fixed_handler = SIZE_MAX;
    for (size_t i = 0; i < POKEMON_GEN3_SLICE_DATA.handler_count; i++) {
        if (POKEMON_GEN3_SLICE_DATA.handlers[i].source_id ==
                POKEMON_GEN3_MOVE_NATUREPOWER &&
            POKEMON_GEN3_SLICE_DATA.handlers[i].event ==
                POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK) {
            fixed_handler = i;
        }
    }
    assert(fixed_handler != SIZE_MAX);
    const PokemonHandlerDescriptor *descriptor =
        &POKEMON_GEN3_SLICE_DATA.handlers[fixed_handler];
    assert(descriptor->program_count == 1);
    PokemonHandlerOp programs[
        POKEMON_GEN3_SLICE_DATA.handler_program_count];
    memcpy(programs, POKEMON_GEN3_SLICE_DATA.handler_programs,
        sizeof(programs));
    programs[descriptor->program_offset].argument = UINT16_MAX;
    PokemonData invalid_data = POKEMON_GEN3_SLICE_DATA;
    invalid_data.handler_programs = programs;
    assert(!pokemon_validate_move_call_pools(&invalid_data));
    assert_invalid_resolved_data_is_atomic(init, &invalid_data);
}

static void test_generated_current_slot_move_delegation(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_SLEEPTALK,
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[0].members[0].move_ids[1] = POKEMON_GEN3_MOVE_SPLASH;
    init.initial_status[0][0] = POKEMON_STATUS_SLEEP;
    init.initial_sleep_time[0][0] = 3;
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    uint8_t parent_pp = battle.sides[0].state[0].pp[0];
    uint8_t child_pp = battle.sides[0].state[0].pp[1];
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].pp[0] + 1 == parent_pp);
    assert(battle.sides[0].state[0].pp[1] == child_pp);
    assert(draw_label_count(
        &battle, POKEMON_DRAW_MOVE_DELEGATION_SELECTION) == 1);
    const PokemonMoveInvocation *child = NULL;
    for (size_t i = 0; i < battle.move_invocation_count; i++) {
        const PokemonMoveInvocation *candidate =
            &battle.move_invocations[i].invocation;
        if (candidate->entry == POKEMON_MOVE_ENTRY_CALLED &&
            candidate->source_effect.kind == POKEMON_SOURCE_EFFECT_MOVE &&
            candidate->source_effect.id == POKEMON_GEN3_MOVE_SLEEPTALK) {
            assert(child == NULL);
            child = candidate;
        }
    }
    assert(child != NULL);
    assert(child->entry == POKEMON_MOVE_ENTRY_CALLED);
    assert(child->move_id == POKEMON_GEN3_MOVE_SPLASH);
    assert(child->source_effect.kind == POKEMON_SOURCE_EFFECT_MOVE);
    assert(child->source_effect.id == POKEMON_GEN3_MOVE_SLEEPTALK);
    assert(!child->owns_pp_deduction);
    assert(battle.sides[0].state[0].last_move_used.present);
    assert(battle.sides[0].state[0].last_move_used.move_id ==
        POKEMON_GEN3_MOVE_SPLASH);

    /* The inherited TryHit callback is one generated predicate over the
     * existing Choice Lock/Encore state product. It rejects before child
     * selection while preserving the ordinary parent PP debit. */
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    PokemonMutable *locked = &battle.sides[0].state[0];
    locked->volatiles[locked->volatile_count++] = (PokemonVolatileState){
        .kind = POKEMON_VOLATILE_CHOICE_LOCK,
        .descriptor_id = POKEMON_GEN3_CONDITION_VOLATILE_CHOICELOCK,
        .state_generation = 1,
        .effect_order = ++battle.next_holder_effect_order,
        .source = {POKEMON_ENTITY_POKEMON, 0, 0},
        .source_effect = {POKEMON_SOURCE_EFFECT_ITEM,
            POKEMON_GEN3_ITEM_CHOICEBAND},
        .payload.choice_control = {
            .stored_move_id = POKEMON_GEN3_MOVE_SLEEPTALK},
    };
    assert(pokemon_battle_check_invariants(&battle));
    parent_pp = locked->pp[0];
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(locked->pp[0] + 1 == parent_pp);
    assert(draw_label_count(
        &battle, POKEMON_DRAW_MOVE_DELEGATION_SELECTION) == 0);
    assert(battle.move_invocation_count == 2);
    uint8_t saw_try_hit_reject = 0;
    for (size_t i = 0; i < battle.handler_count; i++) {
        saw_try_hit_reject |= battle.handlers[i].handler.descriptor.id ==
                POKEMON_GEN3_HANDLER_SLEEP_TALK_TRY_HIT &&
            battle.handlers[i].result == POKEMON_HANDLER_PREVENT;
    }
    assert(saw_try_hit_reject);

    /* Gen 3 samples eligible slots before checking the selected slot's PP. */
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    test_set_base_backed_pp(&battle, 0, 0, 1, 0);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(draw_label_count(
        &battle, POKEMON_DRAW_MOVE_DELEGATION_SELECTION) == 1);
    assert(battle.move_invocation_count == 2);

    /* The descriptor-owned Try gate rejects an awake user before hit work or
     * delegation selection. */
    init.initial_status[0][0] = POKEMON_STATUS_NONE;
    init.initial_sleep_time[0][0] = 0;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(draw_label_count(
        &battle, POKEMON_DRAW_MOVE_DELEGATION_SELECTION) == 0);
    assert(battle.move_invocation_count == 2);

    /* A generated charge move is ineligible. With no candidate, Hit returns
     * false without a selection draw or a child invocation. */
    init.teams[0].members[0].move_ids[1] = POKEMON_GEN3_MOVE_FLY;
    init.initial_status[0][0] = POKEMON_STATUS_SLEEP;
    init.initial_sleep_time[0][0] = 3;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(draw_label_count(
        &battle, POKEMON_DRAW_MOVE_DELEGATION_SELECTION) == 0);
    assert(battle.move_invocation_count == 2);
    assert(pokemon_battle_check_invariants(&battle));

    size_t hit_handler = SIZE_MAX;
    for (size_t i = 0; i < POKEMON_GEN3_SLICE_DATA.handler_count; i++) {
        if (POKEMON_GEN3_SLICE_DATA.handlers[i].id ==
                POKEMON_GEN3_HANDLER_SLEEP_TALK_HIT) hit_handler = i;
    }
    assert(hit_handler != SIZE_MAX);
    const PokemonHandlerDescriptor *descriptor =
        &POKEMON_GEN3_SLICE_DATA.handlers[hit_handler];
    PokemonHandlerOp programs[
        POKEMON_GEN3_SLICE_DATA.handler_program_count];
    memcpy(programs, POKEMON_GEN3_SLICE_DATA.handler_programs,
        sizeof(programs));
    programs[descriptor->program_offset].argument = UINT32_C(2);
    PokemonData invalid_data = POKEMON_GEN3_SLICE_DATA;
    invalid_data.handler_programs = programs;
    assert(!pokemon_validate_move_call_pools(&invalid_data));
    assert_invalid_resolved_data_is_atomic(init, &invalid_data);
}

static void test_assist_current_party_slot_delegation(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_ASSIST,
        POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_SPLASH);
    init.team_sizes[0] = 3;
    init.teams[0].members[1] = make_set(
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_TACKLE,
        200, 100, 100, 100, 100, 100);
    init.teams[0].members[1].move_ids[1] = POKEMON_GEN3_MOVE_TACKLE;
    init.teams[0].members[2] = make_set(
        POKEMON_GEN3_SPECIES_CHARMANDER, POKEMON_GEN3_MOVE_EMBER,
        200, 100, 100, 100, 100, 100);
    init.initial_status[0][1] = POKEMON_STATUS_POISON;
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};

    /* Current party order and current move-slot order form one ordered
     * multiset. Duplicate move IDs remain distinct candidates. */
    uint16_t seed_for_first = 0;
    for (uint32_t tail = 1; tail <= UINT16_MAX && !seed_for_first; tail++) {
        init.seed[3] = (uint16_t)tail;
        PokemonBattle candidate;
        assert(pokemon_battle_init(&candidate, &init) == POKEMON_OK);
        candidate.sides[0].party_order[1] = 2;
        candidate.sides[0].party_order[2] = 1;
        candidate.sides[0].state[2].hp = 0;
        candidate.sides[0].state[2].fainted = 1;
        assert(pokemon_battle_check_invariants(&candidate));
        int status = pokemon_battle_step(&candidate, choices);
        assert(status == POKEMON_OK);
        for (size_t draw = 0; draw < candidate.draw_count; draw++) {
            const PokemonDraw *record = &candidate.draws[draw];
            if (record->label == POKEMON_DRAW_MOVE_DELEGATION_SELECTION &&
                record->upper_bound == 3 && record->result == 0) {
                seed_for_first = (uint16_t)tail;
                break;
            }
        }
    }
    assert(seed_for_first);
    init.seed[3] = seed_for_first;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    battle.sides[0].party_order[1] = 2;
    battle.sides[0].party_order[2] = 1;
    battle.sides[0].state[2].hp = 0;
    battle.sides[0].state[2].fainted = 1;
    test_set_base_backed_pp(&battle, 0, 2, 0, 0);
    assert(pokemon_battle_check_invariants(&battle));
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(draw_label_count(
        &battle, POKEMON_DRAW_MOVE_DELEGATION_SELECTION) == 1);
    const PokemonDraw *selection = NULL;
    for (size_t draw = 0; draw < battle.draw_count; draw++) {
        if (battle.draws[draw].label ==
                POKEMON_DRAW_MOVE_DELEGATION_SELECTION) {
            selection = &battle.draws[draw];
            break;
        }
    }
    assert(selection != NULL && selection->upper_bound == 3 &&
        selection->result == 0);
    assert(battle.move_invocation_count >= 2);
    assert(battle.move_invocations[1].invocation.move_id ==
        POKEMON_GEN3_MOVE_EMBER);
    assert(battle.sides[0].state[2].pp[0] == 0);
    assert(battle.sides[0].state[2].fainted);
    assert(battle.sides[0].state[1].status.kind == POKEMON_STATUS_POISON);

    /* No eligible teammate slot is an ordinary false result: no selection
     * draw and no child invocation. */
    init.teams[0].members[1].move_ids[0] = POKEMON_GEN3_MOVE_ASSIST;
    init.teams[0].members[1].move_ids[1] = 0;
    init.teams[0].members[2].move_ids[0] = POKEMON_GEN3_MOVE_ASSIST;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(draw_label_count(
        &battle, POKEMON_DRAW_MOVE_DELEGATION_SELECTION) == 0);
    for (size_t invocation = 0; invocation < battle.move_invocation_count;
         invocation++) {
        assert(battle.move_invocations[invocation].invocation.entry !=
            POKEMON_MOVE_ENTRY_CALLED);
    }
}

static void test_beat_up_party_hit_plan(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_BEATUP,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SPLASH);
    init.team_sizes[0] = 3;
    init.teams[0].members[1] = make_set(
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SPLASH,
        300, 100, 100, 100, 100, 100);
    init.teams[0].members[2] = make_set(
        POKEMON_GEN3_SPECIES_MACHOP, POKEMON_GEN3_MOVE_SPLASH,
        300, 100, 100, 100, 100, 100);
    init.teams[1].members[0].stats[0] = 2000;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    battle.sides[0].party_order[1] = 2;
    battle.sides[0].party_order[2] = 1;
    assert(pokemon_battle_check_invariants(&battle));
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(draw_label_count(&battle, POKEMON_DRAW_MULTIHIT_COUNT) == 0);
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 1);
    assert(draw_label_count(&battle, POKEMON_DRAW_CRITICAL) == 3);
    assert(draw_label_count(&battle, POKEMON_DRAW_DAMAGE_ROLL) == 3);
    assert(handler_id_count(&battle,
        POKEMON_GEN3_HANDLER_BEAT_UP_MODIFY_MOVE) == 1);
    size_t beat_up_spa = 0;
    size_t beat_up_spd = 0;
    for (size_t i = 0; i < battle.modifier_count; i++) {
        beat_up_spa += battle.modifiers[i].handler.descriptor.id ==
            POKEMON_GEN3_HANDLER_BEAT_UP_MODIFY_SPA;
        beat_up_spd += battle.modifiers[i].handler.descriptor.id ==
            POKEMON_GEN3_HANDLER_BEAT_UP_MODIFY_SPD;
    }
    assert(beat_up_spa == 3);
    assert(beat_up_spd == 3);
    const PokemonHitTrace *plan = NULL;
    for (size_t i = 0; i < battle.hit_trace_count; i++) {
        if (battle.hit_traces[i].kind == POKEMON_HIT_PLAN &&
            battle.hit_traces[i].move_id == POKEMON_GEN3_MOVE_BEATUP) {
            plan = &battle.hit_traces[i];
            break;
        }
    }
    assert(plan != NULL && plan->requested_hits == 3);
    assert(test_volatile_index(
        &battle.sides[0].state[0], POKEMON_VOLATILE_PARTY_HIT) < 0);

    /* A fully statused party produces the inherited BasePower null result
     * after accuracy, before any critical or damage-roll draw. */
    init.initial_status[0][0] = POKEMON_STATUS_POISON;
    init.initial_status[0][1] = POKEMON_STATUS_POISON;
    init.initial_status[0][2] = POKEMON_STATUS_POISON;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 1);
    assert(draw_label_count(&battle, POKEMON_DRAW_CRITICAL) == 0);
    assert(draw_label_count(&battle, POKEMON_DRAW_DAMAGE_ROLL) == 0);
    assert(handler_id_count(
        &battle, POKEMON_GEN3_HANDLER_BEAT_UP_BASE_POWER) == 1);
}

static void test_generated_move_slot_copy_family(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_SPLASH,
        POKEMON_GEN3_SPECIES_ALAKAZAM, POKEMON_GEN3_MOVE_RECOVER);
    init.teams[0].members[0].move_ids[1] = POKEMON_GEN3_MOVE_MIMIC;
    init.teams[0].members[0].stats[5] = 300;
    init.teams[1].members[0].stats[5] = 100;
    PokemonBattle battle;
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    choices[0] = move(1);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    PokemonMutable *mimic = &battle.sides[0].state[0];
    assert(mimic->move_ids[1] == POKEMON_GEN3_MOVE_RECOVER);
    assert(mimic->pp[1] == 5 && mimic->max_pp[1] == 32);
    assert(mimic->base_move_ids[1] == POKEMON_GEN3_MOVE_MIMIC);
    assert(mimic->base_pp[1] == 15 && mimic->base_max_pp[1] == 16);
    assert((mimic->temporary_move_slots & (1u << 1)) != 0);
    assert(draw_label_count(&battle, POKEMON_DRAW_MOVE_DELEGATION_SELECTION) == 0);
    PokemonChoice switch_choices[POKEMON_SIDES] = {switch_to(1), move(0)};
    assert(pokemon_battle_step(&battle, switch_choices) == POKEMON_OK);
    assert(mimic->move_ids[1] == POKEMON_GEN3_MOVE_MIMIC);
    assert(mimic->pp[1] == 15 && mimic->max_pp[1] == 16);
    assert(mimic->temporary_move_slots == 0);
    assert(pokemon_battle_check_invariants(&battle));

    init.teams[0].members[0].move_ids[0] = POKEMON_GEN3_MOVE_SKETCH;
    init.teams[0].members[0].move_ids[1] = POKEMON_GEN3_MOVE_SPLASH;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    choices[0] = move(1);
    choices[1] = move(0);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    choices[0] = move(0);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    PokemonMutable *sketch = &battle.sides[0].state[0];
    assert(sketch->move_ids[0] == POKEMON_GEN3_MOVE_RECOVER);
    assert(sketch->pp[0] == 20 && sketch->max_pp[0] == 20);
    assert(sketch->base_move_ids[0] == POKEMON_GEN3_MOVE_RECOVER);
    assert(sketch->base_pp[0] == 20 && sketch->base_max_pp[0] == 20);
    assert((sketch->temporary_move_slots & 1u) == 0);
    choices[0] = move(0);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(sketch->pp[0] == 19 && sketch->base_pp[0] == 19);
    assert(pokemon_battle_step(&battle, switch_choices) == POKEMON_OK);
    assert(sketch->move_ids[0] == POKEMON_GEN3_MOVE_RECOVER);
    assert(sketch->pp[0] == 19 && sketch->max_pp[0] == 20);
    assert(pokemon_battle_check_invariants(&battle));

    /* Copy admission is atomic after the ordinary caller PP debit. */
    init.teams[0].members[0].move_ids[0] = POKEMON_GEN3_MOVE_MIMIC;
    init.teams[0].members[0].move_ids[1] = POKEMON_GEN3_MOVE_RECOVER;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    choices[0] = move(0);
    choices[1] = move(0);
    uint8_t mimic_pp = battle.sides[0].state[0].pp[0];
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].move_ids[0] == POKEMON_GEN3_MOVE_MIMIC);
    assert(battle.sides[0].state[0].pp[0] + 1 == mimic_pp);

    /* Copy admission failures mutate only the caller's ordinary PP debit. */
    init.teams[0].members[0].move_ids[1] = 0;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    battle.sides[1].state[0].last_move_id = POKEMON_GEN3_MOVE_RECOVER;
    battle.sides[0].state[0].transformed = 1;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].move_ids[0] == POKEMON_GEN3_MOVE_MIMIC);

    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    battle.sides[1].state[0].last_move_id = POKEMON_GEN3_MOVE_RECOVER;
    PokemonMutable *copy_target = &battle.sides[1].state[0];
    copy_target->volatiles[copy_target->volatile_count++] =
        (PokemonVolatileState){
            .kind = POKEMON_VOLATILE_SUBSTITUTE,
            .descriptor_id = POKEMON_GEN3_CONDITION_VOLATILE_SUBSTITUTE,
            .state_generation = 1,
            .effect_order = ++battle.next_holder_effect_order,
            .source = {POKEMON_ENTITY_POKEMON, 1, 0},
            .source_effect = {POKEMON_SOURCE_EFFECT_MOVE,
                POKEMON_GEN3_MOVE_SUBSTITUTE},
            .payload.substitute = {.hp = 1},
        };
    assert(pokemon_battle_check_invariants(&battle));
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].move_ids[0] == POKEMON_GEN3_MOVE_MIMIC);

    init.teams[0].members[0].move_ids[0] = POKEMON_GEN3_MOVE_MIMIC;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    battle.sides[1].state[0].last_move_id = POKEMON_GEN3_MOVE_SKETCH;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].move_ids[0] == POKEMON_GEN3_MOVE_MIMIC);

    size_t mimic_handler = POKEMON_GEN3_HANDLER_MIMIC_HIT - 1;
    const PokemonHandlerDescriptor *descriptor =
        &POKEMON_GEN3_SLICE_DATA.handlers[mimic_handler];
    assert(descriptor->id == POKEMON_GEN3_HANDLER_MIMIC_HIT);
    PokemonHandlerOp programs[
        POKEMON_GEN3_SLICE_DATA.handler_program_count];
    memcpy(programs, POKEMON_GEN3_SLICE_DATA.handler_programs,
        sizeof(programs));
    programs[descriptor->program_offset].argument = UINT32_C(3);
    PokemonData invalid_data = POKEMON_GEN3_SLICE_DATA;
    invalid_data.handler_programs = programs;
    assert(!pokemon_validate_move_call_pools(&invalid_data));
    assert_invalid_resolved_data_is_atomic(init, &invalid_data);
}

static void test_fixed_level_damage_and_gates(void) {
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_MACHOP, POKEMON_GEN3_MOVE_SEISMICTOSS,
        POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_SPLASH
    );
    init.teams[1].members[0].stats[0] = 500;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    uint16_t hp_before = battle.sides[1].state[0].hp;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].state[0].hp == hp_before - 100);
    assert(battle.damage_formula_trace_count == 1);
    assert(battle.damage_formula_traces[0].formula == POKEMON_DAMAGE_FIXED_LEVEL);
    assert(battle.damage_formula_traces[0].resolved_value == 100);
    assert_no_damage_randomness(&battle);

    init = condition_init(
        POKEMON_GEN3_SPECIES_GENGAR, POKEMON_GEN3_MOVE_NIGHTSHADE,
        POKEMON_GEN3_SPECIES_MACHOP, POKEMON_GEN3_MOVE_SPLASH
    );
    init.teams[1].members[0].stats[0] = 500;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    hp_before = battle.sides[1].state[0].hp;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].state[0].hp == hp_before - 100);
    assert_no_damage_randomness(&battle);

    init = condition_init(
        POKEMON_GEN3_SPECIES_MACHOP, POKEMON_GEN3_MOVE_SEISMICTOSS,
        POKEMON_GEN3_SPECIES_GENGAR, POKEMON_GEN3_MOVE_SPLASH
    );
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.events[1].kind == POKEMON_EVENT_IMMUNE);
    assert(battle.damage_formula_trace_count == 0);
    assert_no_damage_randomness(&battle);

    init = condition_init(
        POKEMON_GEN3_SPECIES_GENGAR, POKEMON_GEN3_MOVE_NIGHTSHADE,
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SPLASH
    );
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.events[1].kind == POKEMON_EVENT_IMMUNE);
    assert(battle.damage_formula_trace_count == 0);

    init = condition_init(
        POKEMON_GEN3_SPECIES_MACHOP, POKEMON_GEN3_MOVE_SEISMICTOSS,
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_PROTECT
    );
    init.teams[1].members[0].stats[5] = 400;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.damage_formula_trace_count == 0);
    assert_no_damage_randomness(&battle);

    init = condition_init(
        POKEMON_GEN3_SPECIES_MACHOP, POKEMON_GEN3_MOVE_SEISMICTOSS,
        POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_SPLASH
    );
    init.teams[1].members[0].stats[0] = 500;
    init.initial_hp[1][0] = 80;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].state[0].hp == 0);
    assert(battle.request.kind[1] == POKEMON_REQUEST_SWITCH);
    assert(battle.events[1].amount == 80);
}

static void test_fixed_literal_damage_and_type_boundary(void) {
    static const struct {
        uint16_t move_id;
        uint16_t damage;
        PokemonCategory category;
        PokemonAccuracy accuracy;
    } descriptors[] = {
        {POKEMON_GEN3_MOVE_SONICBOOM, 20, POKEMON_CATEGORY_PHYSICAL,
         {POKEMON_ACCURACY_PERCENT, 90}},
        {POKEMON_GEN3_MOVE_DRAGONRAGE, 40, POKEMON_CATEGORY_SPECIAL,
         {POKEMON_ACCURACY_PERCENT, 100}},
    };
    for (size_t expected = 0;
         expected < sizeof(descriptors) / sizeof(descriptors[0]); expected++) {
        const PokemonMoveData *move_data = NULL;
        for (size_t i = 0; i < POKEMON_GEN3_SLICE_DATA.move_count; i++) {
            if (POKEMON_GEN3_SLICE_DATA.moves[i].id ==
                descriptors[expected].move_id) {
                move_data = &POKEMON_GEN3_SLICE_DATA.moves[i];
                break;
            }
        }
        assert(move_data != NULL);
        assert(move_data->power == 0);
        assert(move_data->damage_formula == POKEMON_DAMAGE_FIXED_LITERAL);
        assert(move_data->damage_parameter == descriptors[expected].damage);
        assert(move_data->category == descriptors[expected].category);
        assert(move_data->accuracy.kind == descriptors[expected].accuracy.kind);
        assert(move_data->accuracy.percent == descriptors[expected].accuracy.percent);
    }

    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_CHARIZARD, POKEMON_GEN3_MOVE_DRAGONRAGE,
        POKEMON_GEN3_SPECIES_METAGROSS, POKEMON_GEN3_MOVE_AGILITY
    );
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    uint16_t hp_before = battle.sides[1].state[0].hp;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].state[0].hp == hp_before - 40);
    assert(battle.damage_formula_trace_count == 1);
    assert(battle.damage_formula_traces[0].formula ==
        POKEMON_DAMAGE_FIXED_LITERAL);
    assert(battle.damage_formula_traces[0].resolved_value == 40);
    assert_no_damage_randomness(&battle);

    init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_SONICBOOM,
        POKEMON_GEN3_SPECIES_GENGAR, POKEMON_GEN3_MOVE_TOXIC
    );
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    hp_before = battle.sides[1].state[0].hp;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].state[0].hp == hp_before);
    assert(battle.damage_formula_trace_count == 0);
    assert_no_damage_randomness(&battle);
}

static void test_prepared_retaliation_damage_provenance(void) {
    static const struct {
        uint16_t source_species;
        uint16_t incoming_move;
        uint16_t response_move;
        uint16_t incoming_damage;
    } cases[] = {
        {POKEMON_GEN3_SPECIES_MACHOP, POKEMON_GEN3_MOVE_SEISMICTOSS,
         POKEMON_GEN3_MOVE_COUNTER, 100},
        {POKEMON_GEN3_SPECIES_CHARIZARD, POKEMON_GEN3_MOVE_DRAGONRAGE,
         POKEMON_GEN3_MOVE_MIRRORCOAT, 40},
    };
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    for (size_t i = 0; i < sizeof(cases) / sizeof(cases[0]); i++) {
        PokemonBattleInit init = condition_init(
            cases[i].source_species, cases[i].incoming_move,
            POKEMON_GEN3_SPECIES_SMEARGLE, cases[i].response_move);
        init.teams[0].members[0].stats[0] = 500;
        init.teams[1].members[0].stats[0] = 500;
        PokemonBattle battle;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        assert(battle.sides[1].state[0].hp ==
            500 - cases[i].incoming_damage);
        assert(battle.sides[0].state[0].hp ==
            500 - 2 * cases[i].incoming_damage);
        assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 2);
        assert(draw_label_count(&battle, POKEMON_DRAW_CRITICAL) == 0);
        assert(draw_label_count(&battle, POKEMON_DRAW_DAMAGE_ROLL) == 0);
        assert(test_volatile_index(
            &battle.sides[1].state[battle.sides[1].active],
            POKEMON_VOLATILE_PREPARED_RETALIATION) < 0);
    }

    PokemonBattleInit wrong_class = condition_init(
        POKEMON_GEN3_SPECIES_CHARIZARD, POKEMON_GEN3_MOVE_DRAGONRAGE,
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_COUNTER);
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &wrong_class) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].hp ==
        wrong_class.teams[0].members[0].stats[0]);
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 1);

    /* Damage provenance follows the resolved active move category. Weather
     * Ball is physical in clear weather and special in rain; retaliation
     * must not re-read its immutable base descriptor after frame mutation. */
    static const struct {
        PokemonWeatherKind weather;
        uint16_t response_move;
        uint8_t should_respond;
    } weather_ball_cases[] = {
        {POKEMON_WEATHER_NONE, POKEMON_GEN3_MOVE_COUNTER, 1},
        {POKEMON_WEATHER_NONE, POKEMON_GEN3_MOVE_MIRRORCOAT, 0},
        {POKEMON_WEATHER_RAIN, POKEMON_GEN3_MOVE_COUNTER, 0},
        {POKEMON_WEATHER_RAIN, POKEMON_GEN3_MOVE_MIRRORCOAT, 1},
    };
    for (size_t i = 0;
         i < sizeof(weather_ball_cases) / sizeof(weather_ball_cases[0]); i++) {
        PokemonBattleInit init = condition_init(
            POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_WEATHERBALL,
            POKEMON_GEN3_SPECIES_SMEARGLE,
            weather_ball_cases[i].response_move);
        init.teams[0].members[0].stats[0] = 1000;
        init.teams[0].members[0].stats[5] = 200;
        init.teams[1].members[0].stats[0] = 1000;
        init.teams[1].members[0].stats[5] = 100;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        if (weather_ball_cases[i].weather != POKEMON_WEATHER_NONE) {
            battle.field.weather = (PokemonWeatherState){
                .kind = weather_ball_cases[i].weather,
                .descriptor_id = battle.generation->condition_descriptor(
                    POKEMON_OWNER_FIELD, weather_ball_cases[i].weather),
                .duration = 5, .source_side = 0, .source_slot = 0,
                .state_generation = 1,
            };
        }
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        uint16_t incoming = (uint16_t)(1000 - battle.sides[1].state[0].hp);
        assert(incoming > 0);
        assert(battle.sides[0].state[0].hp ==
            (weather_ball_cases[i].should_respond ?
                (uint16_t)(1000 - 2 * incoming) : 1000));
        assert(pokemon_battle_check_invariants(&battle));
    }

    /* Damage handlers receive the requested damage before real-HP clamping.
     * Exercise the internal commit boundary directly because a one-HP holder
     * naturally faints and clears the prepared condition before a later move
     * can expose its payload. */
    PokemonBattleInit overkill = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_SONICBOOM,
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_COUNTER);
    overkill.initial_hp[1][0] = 1;
    assert(pokemon_battle_init(&battle, &overkill) == POKEMON_OK);
    PokemonMutable *prepared = &battle.sides[1].state[0];
    prepared->volatiles[prepared->volatile_count++] = (PokemonVolatileState){
        .kind = POKEMON_VOLATILE_PREPARED_RETALIATION,
        .descriptor_id = POKEMON_GEN3_CONDITION_VOLATILE_COUNTER,
        .duration = 1,
        .state_generation = 1,
        .effect_order = ++battle.next_holder_effect_order,
        .source = {POKEMON_ENTITY_POKEMON, 1, 0},
        .source_effect = {POKEMON_SOURCE_EFFECT_MOVE,
            POKEMON_GEN3_MOVE_COUNTER},
    };
    PokemonEventFrame damage_frame;
    assert(pokemon_run_event(&battle, &(PokemonEventInput){
        .event = POKEMON_HANDLER_EVENT_DAMAGE,
        .source = {POKEMON_ENTITY_POKEMON, 0, 0},
        .target_side = 1, .target_slot = 0,
        .source_effect = {POKEMON_SOURCE_EFFECT_MOVE,
            POKEMON_GEN3_MOVE_SONICBOOM},
        .context_kind = POKEMON_EVENT_CONTEXT_DAMAGE,
        .context.damage = {
            .kind = POKEMON_DAMAGE_EVENT_ORDINARY_MOVE,
            .source_move_id = POKEMON_GEN3_MOVE_SONICBOOM,
            .retaliation_class_mask = POKEMON_RETALIATION_PHYSICAL,
        },
        .relay = {.kind = POKEMON_RELAY_U32, .value.u32 = 20},
    }, &damage_frame) == POKEMON_OK);
    assert(damage_frame.relay.kind == POKEMON_RELAY_U32);
    assert(damage_frame.relay.value.u32 == 20);
    assert(prepared->hp == 1);
    assert(prepared->volatiles[0].payload.retaliation.captured);
    assert(prepared->volatiles[0].payload.retaliation.damage == 40);
    assert(prepared->volatiles[0].payload.retaliation.source_side == 0);
    assert(pokemon_battle_check_invariants(&battle));

}

static void test_target_relative_damage_and_early_predicate(void) {
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_SUPERFANG,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SPLASH
    );
    init.teams[0].members[0].stats[0] = 251;
    init.teams[1].members[0].stats[0] = 651;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].state[0].hp == 326);
    assert(battle.damage_formula_trace_count == 1);
    assert(battle.damage_formula_traces[0].formula ==
        POKEMON_DAMAGE_TARGET_HP_FRACTION);
    assert(battle.damage_formula_traces[0].resolved_value == 325);
    assert_no_damage_randomness(&battle);

    init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_ENDEAVOR,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SPLASH
    );
    init.teams[0].members[0].stats[0] = 251;
    init.initial_hp[0][0] = 100;
    init.teams[1].members[0].stats[0] = 651;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].state[0].hp == 100);
    assert(battle.damage_formula_trace_count == 1);
    assert(battle.damage_formula_traces[0].formula ==
        POKEMON_DAMAGE_TARGET_SOURCE_HP_DIFFERENCE);
    assert(battle.damage_formula_traces[0].resolved_value == 551);
    assert_no_damage_randomness(&battle);

    init.initial_hp[1][0] = 100;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].state[0].hp == 100);
    assert(battle.damage_formula_trace_count == 0);
    uint8_t saw_endeavor_try = 0;
    for (size_t i = 0; i < battle.handler_count; i++) {
        if (battle.handlers[i].handler.descriptor.id ==
            POKEMON_GEN3_HANDLER_ENDEAVOR_TRY_MOVE) {
            saw_endeavor_try = 1;
        }
    }
    assert(saw_endeavor_try);
    for (size_t i = 0; i < battle.draw_count; i++) {
        assert(battle.draws[i].label != POKEMON_DRAW_ACCURACY);
    }
}

static void test_random_level_percent_damage_and_owned_prng(void) {
    PokemonDamageFormulaOutput formula = {0};
    POKEMON_GEN3_RULES.resolve_damage_formula(
        &(PokemonDamageFormulaInput){
            .formula = POKEMON_DAMAGE_RANDOM_LEVEL_PERCENT,
            .level = 1,
            .random_value = 50,
        },
        &formula);
    assert(formula.fixed_damage == 1);

    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_PSYWAVE,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SPLASH
    );
    init.teams[0].members[0].level = 99;
    init.teams[1].members[0].stats[0] = 651;
    PokemonBattle battle;
    int connected = 0;
    for (uint16_t tail = 1; tail < 128 && !connected; tail++) {
        init.seed[3] = tail;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        connected = battle.damage_formula_trace_count == 1;
    }
    assert(connected);
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 1);
    assert(draw_label_count(&battle, POKEMON_DRAW_DAMAGE_FORMULA) == 1);
    assert(draw_label_count(&battle, POKEMON_DRAW_CRITICAL) == 0);
    assert(draw_label_count(&battle, POKEMON_DRAW_DAMAGE_ROLL) == 0);
    const PokemonDraw *damage_draw = NULL;
    for (size_t i = 0; i < battle.draw_count; i++) {
        if (battle.draws[i].label == POKEMON_DRAW_DAMAGE_FORMULA) {
            damage_draw = &battle.draws[i];
            break;
        }
    }
    assert(damage_draw != NULL);
    assert(damage_draw->upper_bound == 101);
    assert(battle.damage_formula_traces[0].formula ==
        POKEMON_DAMAGE_RANDOM_LEVEL_PERCENT);
    assert(battle.damage_formula_traces[0].resolved_value ==
        (uint16_t)((damage_draw->result + 50u) * 99u / 100u));

    init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_PSYWAVE,
        POKEMON_GEN3_SPECIES_TYRANITAR, POKEMON_GEN3_MOVE_CRUNCH
    );
    init.teams[0].members[0].stats[5] = 500;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 2);
    assert(draw_label_count(&battle, POKEMON_DRAW_DAMAGE_FORMULA) == 0);
    assert(battle.damage_formula_trace_count == 0);

    init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_PSYWAVE,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_PROTECT
    );
    init.teams[1].members[0].stats[5] = 400;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(draw_label_count(&battle, POKEMON_DRAW_DAMAGE_FORMULA) == 0);
    assert(battle.damage_formula_trace_count == 0);
}

static void test_reversal_hp_brackets_and_initial_hp_boundary(void) {
    static const struct { uint16_t hp; uint8_t ratio; uint16_t power; } cases[] = {
        {301, 48, 20}, {207, 33, 20}, {206, 32, 40},
        {107, 17, 40}, {106, 16, 80}, {63, 10, 80},
        {62, 9, 100}, {32, 5, 100}, {31, 4, 150},
        {13, 2, 150}, {12, 1, 200}, {1, 1, 200},
    };
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    for (size_t i = 0; i < sizeof(cases) / sizeof(cases[0]); i++) {
        PokemonBattleInit init = condition_init(
            POKEMON_GEN3_SPECIES_HERACROSS, POKEMON_GEN3_MOVE_REVERSAL,
            POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_SPLASH
        );
        init.teams[0].members[0].ability_id = POKEMON_GEN3_ABILITY_GUTS;
        init.teams[0].members[0].stats[0] = 301;
        init.teams[0].members[0].stats[1] = 286;
        init.teams[0].members[0].stats[2] = 186;
        init.initial_hp[0][0] = cases[i].hp;
        init.teams[1].members[0].stats[0] = 1000;
        init.teams[1].members[0].stats[2] = 1000;
        PokemonBattle battle;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        assert(battle.damage_formula_trace_count == 1);
        const PokemonDamageFormulaTrace *trace = &battle.damage_formula_traces[0];
        assert(trace->formula == POKEMON_DAMAGE_HP_BRACKET);
        assert(trace->hp == cases[i].hp);
        assert(trace->max_hp == 301);
        assert(trace->ratio == cases[i].ratio);
        assert(trace->resolved_value == cases[i].power);
        assert(battle.draws[1].label == POKEMON_DRAW_CRITICAL);
        assert(battle.draws[2].label == POKEMON_DRAW_DAMAGE_ROLL);
    }

    PokemonBattleInit invalid = condition_init(
        POKEMON_GEN3_SPECIES_HERACROSS, POKEMON_GEN3_MOVE_REVERSAL,
        POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_SPLASH
    );
    invalid.initial_hp[0][0] = (uint16_t)(invalid.teams[0].members[0].stats[0] + 1);
    PokemonBattle untouched;
    memset(&untouched, 0x5a, sizeof(untouched));
    PokemonBattle before = untouched;
    assert(pokemon_battle_init(&untouched, &invalid) == POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&untouched, &before, sizeof(untouched)) == 0);
}

static void test_live_hp_scaled_base_power_family(void) {
    static const uint16_t moves[] = {
        POKEMON_GEN3_MOVE_ERUPTION, POKEMON_GEN3_MOVE_WATERSPOUT,
    };
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    uint16_t family_damage[2] = {0, 0};
    for (size_t i = 0; i < sizeof(moves) / sizeof(moves[0]); i++) {
        PokemonBattleInit init = condition_init(
            POKEMON_GEN3_SPECIES_SMEARGLE, moves[i],
            POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_SPLASH);
        init.teams[0].members[0].stats[0] = 301;
        init.teams[0].members[0].stats[3] = 200;
        init.initial_hp[0][0] = 151;
        init.teams[1].members[0].stats[0] = 1000;
        init.teams[1].members[0].stats[4] = 200;
        init.seed[3] = 1;
        PokemonBattle battle;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        assert(battle.data->moves[moves[i] - 1].base_power_policy ==
            POKEMON_BASE_POWER_SOURCE_HP_RATIO);
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        family_damage[i] = (uint16_t)(1000 - battle.sides[1].state[0].hp);
        assert(family_damage[i] != 0);
    }
    /* Magikarp resists both Fire and Water, so equal inputs prove both move
     * identities share one generated policy and one kernel operation. */
    assert(family_damage[0] == family_damage[1]);
}

static void test_target_weight_base_power_policy(void) {
    static const struct { uint16_t weight_hg; uint16_t power; } cases[] = {
        {1, 20}, {99, 20}, {100, 40}, {249, 40}, {250, 60},
        {499, 60}, {500, 80}, {999, 80}, {1000, 100},
        {1999, 100}, {2000, 120}, {5000, 120},
    };
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    uint16_t previous_power = 0;
    uint16_t previous_damage = 0;
    for (size_t i = 0; i < sizeof(cases) / sizeof(cases[0]); i++) {
        PokemonSpeciesData species[POKEMON_GEN3_SPECIES_COUNT];
        memcpy(species, POKEMON_GEN3_SLICE_DATA.species, sizeof(species));
        species[POKEMON_GEN3_SPECIES_MAGIKARP - 1].weight_hg =
            cases[i].weight_hg;
        PokemonData data = POKEMON_GEN3_SLICE_DATA;
        data.species = species;
        PokemonResolvedBundle bundle = POKEMON_GEN3_OU_BUNDLE;
        bundle.data = &data;
        PokemonBattleInit init = condition_init(
            POKEMON_GEN3_SPECIES_MACHOP, POKEMON_GEN3_MOVE_LOWKICK,
            POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_SPLASH);
        init.bundle = &bundle;
        init.teams[0].members[0].stats[1] = 300;
        init.teams[1].members[0].stats[0] = 5000;
        init.teams[1].members[0].stats[2] = 300;
        init.seed[3] = 1;
        PokemonBattle battle;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        const PokemonMoveData *low_kick =
            &battle.data->moves[POKEMON_GEN3_MOVE_LOWKICK - 1];
        assert(low_kick->base_power_policy ==
            POKEMON_BASE_POWER_TARGET_WEIGHT);
        assert(low_kick->weight_power_policy_id == 1);
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        uint16_t damage = (uint16_t)(5000 - battle.sides[1].state[0].hp);
        assert(damage != 0);
        if (cases[i].power == previous_power) {
            assert(damage == previous_damage);
        } else if (previous_power != 0) {
            assert(damage > previous_damage);
        }
        previous_power = cases[i].power;
        previous_damage = damage;
        assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 1);
        assert(draw_label_count(&battle, POKEMON_DRAW_CRITICAL) == 1);
        assert(draw_label_count(&battle, POKEMON_DRAW_DAMAGE_ROLL) == 1);
    }

    PokemonBattleInit invalid = condition_init(
        POKEMON_GEN3_SPECIES_MACHOP, POKEMON_GEN3_MOVE_LOWKICK,
        POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_SPLASH);
    PokemonWeightPowerPolicy malformed =
        POKEMON_GEN3_SLICE_DATA.weight_power_policies[0];
    malformed.upper_bounds_hg[2] = malformed.upper_bounds_hg[1];
    PokemonData invalid_data = POKEMON_GEN3_SLICE_DATA;
    invalid_data.weight_power_policies = &malformed;
    PokemonResolvedBundle invalid_bundle = POKEMON_GEN3_OU_BUNDLE;
    invalid_bundle.data = &invalid_data;
    invalid.bundle = &invalid_bundle;
    PokemonBattle untouched;
    memset(&untouched, 0x51, sizeof(untouched));
    PokemonBattle before = untouched;
    assert(pokemon_battle_init(&untouched, &invalid) ==
        POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&untouched, &before, sizeof(untouched)) == 0);

    PokemonBattleInit immune = condition_init(
        POKEMON_GEN3_SPECIES_MACHOP, POKEMON_GEN3_MOVE_LOWKICK,
        POKEMON_GEN3_SPECIES_GASTLY, POKEMON_GEN3_MOVE_SPLASH);
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &immune) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(draw_label_count(&battle, POKEMON_DRAW_CRITICAL) == 0);
    assert(draw_label_count(&battle, POKEMON_DRAW_DAMAGE_ROLL) == 0);
}

static void test_transform_generic_profile_copy_policy(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_DITTO, POKEMON_GEN3_MOVE_TRANSFORM,
        POKEMON_GEN3_SPECIES_ALAKAZAM, POKEMON_GEN3_MOVE_SUBSTITUTE);
    init.team_sizes[0] = 2;
    init.teams[0].members[0].ability_id = POKEMON_GEN3_ABILITY_LIMBER;
    init.teams[0].members[0].stats[5] = 132;
    init.teams[0].members[1] = make_set(
        POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_SPLASH,
        180, 40, 60, 50, 70, 80);
    init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_INNERFOCUS;
    init.teams[1].members[0].move_ids[1] = POKEMON_GEN3_MOVE_HIDDENPOWER;
    init.teams[1].members[0].move_ids[2] = POKEMON_GEN3_MOVE_CALMMIND;
    init.teams[1].members[0].move_ids[3] = POKEMON_GEN3_MOVE_RECOVER;
    init.teams[1].members[0].stats[1] = 111;
    init.teams[1].members[0].stats[2] = 122;
    init.teams[1].members[0].stats[3] = 333;
    init.teams[1].members[0].stats[4] = 244;
    init.teams[1].members[0].stats[5] = 400;
    init.teams[1].members[0].ivs_specified = 1;
    for (size_t stat = 0; stat < 6; stat++) {
        init.teams[1].members[0].ivs[stat] = 30;
    }
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    PokemonEffectResult volatile_result = POKEMON_EFFECT_FAILED;
    assert(pokemon_try_add_or_restart_volatile(
        &battle, (PokemonEntityRef){POKEMON_ENTITY_POKEMON, 1, 0},
        (PokemonEntityRef){POKEMON_ENTITY_POKEMON, 1, 0},
        (PokemonSourceEffectRef){POKEMON_SOURCE_EFFECT_MOVE,
            POKEMON_GEN3_MOVE_FOCUSENERGY},
        POKEMON_VOLATILE_FOCUS_ENERGY, POKEMON_CONDITION_REASON_MOVE,
        &volatile_result) == POKEMON_OK);
    assert(volatile_result == POKEMON_EFFECT_APPLIED);
    battle.sides[1].state[0].boosts[POKEMON_STAT_SPA] = 2;
    battle.sides[1].state[0].boosts[POKEMON_STAT_SPD] = 1;
    uint16_t source_hp = battle.sides[0].state[0].hp;
    uint16_t source_max_hp = battle.sides[0].sets[0].stats[0];
    uint16_t source_base_species = battle.sides[0].sets[0].species_id;
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);

    PokemonMutable *source = &battle.sides[0].state[0];
    const PokemonMutable *target = &battle.sides[1].state[0];
    assert(test_volatile_index(target, POKEMON_VOLATILE_SUBSTITUTE) >= 0);
    assert(test_volatile_index(target, POKEMON_VOLATILE_FOCUS_ENERGY) >= 0);
    assert(test_volatile_index(source, POKEMON_VOLATILE_FOCUS_ENERGY) < 0);
    assert(source->transformed == 1);
    assert(source->species_id == target->species_id);
    assert(source->effective_type_count == target->effective_type_count);
    assert(memcmp(source->effective_types, target->effective_types,
        sizeof(source->effective_types)) == 0);
    assert(memcmp(source->stored_stats, target->stored_stats,
        sizeof(source->stored_stats)) == 0);
    assert(memcmp(source->boosts, target->boosts, sizeof(source->boosts)) == 0);
    assert(source->ability_id == target->ability_id);
    assert(source->personal_move_profile.kind ==
        target->personal_move_profile.kind);
    assert(source->personal_move_profile.type == target->personal_move_profile.type);
    assert(source->personal_move_profile.power == target->personal_move_profile.power);
    assert(source->hp == source_hp);
    assert(battle.sides[0].sets[0].stats[0] == source_max_hp);
    assert(battle.sides[0].sets[0].species_id == source_base_species);
    assert(source->base_move_ids[0] == POKEMON_GEN3_MOVE_TRANSFORM);
    assert(source->base_pp[0] == 15);
    for (size_t slot = 0; slot < POKEMON_MOVE_CAPACITY; slot++) {
        const PokemonMoveData *copied = NULL;
        for (size_t i = 0; i < battle.data->move_count; i++) {
            if (battle.data->moves[i].id == target->move_ids[slot]) {
                copied = &battle.data->moves[i];
                break;
            }
        }
        assert(copied != NULL);
        assert(source->move_ids[slot] == target->move_ids[slot]);
        assert(source->pp[slot] == (copied->raw_pp < 5 ? copied->raw_pp : 5));
        uint8_t pp_ups = copied->no_pp_boosts ? 0 : source->pp_ups[slot];
        assert(source->max_pp[slot] ==
            copied->raw_pp * (uint16_t)(5u + pp_ups) / 5u);
        assert(source->temporary_move_slots & (1u << slot));
    }
    assert(draw_label_count(&battle, POKEMON_DRAW_CRITICAL) == 0);
    assert(draw_label_count(&battle, POKEMON_DRAW_DAMAGE_ROLL) == 0);
    assert(pokemon_battle_check_invariants(&battle));

    PokemonChoice switching[POKEMON_SIDES] = {switch_to(1), move(0)};
    assert(pokemon_battle_step(&battle, switching) == POKEMON_OK);
    source = &battle.sides[0].state[0];
    assert(source->transformed == 0);
    assert(source->species_id == source_base_species);
    assert(source->ability_id == POKEMON_GEN3_ABILITY_LIMBER);
    assert(source->move_ids[0] == POKEMON_GEN3_MOVE_TRANSFORM);
    assert(source->pp[0] == 15);
    assert(source->temporary_move_slots == 0);
    assert(source->personal_move_profile.kind == 0);
    for (size_t stat = 0; stat < 5; stat++) {
        assert(source->stored_stats[stat] ==
            battle.sides[0].sets[0].stats[stat + 1]);
    }
    assert(pokemon_battle_check_invariants(&battle));

    PokemonBattleInit rejected_init = condition_init(
        POKEMON_GEN3_SPECIES_DITTO, POKEMON_GEN3_MOVE_TRANSFORM,
        POKEMON_GEN3_SPECIES_ALAKAZAM, POKEMON_GEN3_MOVE_SPLASH);
    assert(pokemon_battle_init(&battle, &rejected_init) == POKEMON_OK);
    battle.sides[1].state[0].transformed = 1;
    assert(pokemon_battle_check_invariants(&battle));
    uint8_t pp_before = battle.sides[0].state[0].pp[0];
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(!battle.sides[0].state[0].transformed);
    assert(battle.sides[0].state[0].pp[0] == pp_before - 1);

    PokemonTransformPolicy malformed =
        POKEMON_GEN3_SLICE_DATA.transform_policies[0];
    malformed.copied_move_pp_cap = 0;
    PokemonData invalid_data = POKEMON_GEN3_SLICE_DATA;
    invalid_data.transform_policies = &malformed;
    PokemonResolvedBundle invalid_bundle = POKEMON_GEN3_OU_BUNDLE;
    invalid_bundle.data = &invalid_data;
    rejected_init.bundle = &invalid_bundle;
    PokemonBattle untouched;
    memset(&untouched, 0x3c, sizeof(untouched));
    PokemonBattle before = untouched;
    assert(pokemon_battle_init(&untouched, &rejected_init) ==
        POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&untouched, &before, sizeof(untouched)) == 0);
}

static void test_generated_atomic_formula_moves(void) {
    PokemonBattleInit salts_init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_SMELLINGSALTS,
        POKEMON_GEN3_SPECIES_SNORLAX, POKEMON_GEN3_MOVE_SPLASH);
    salts_init.teams[1].members[0].stats[0] = 500;
    salts_init.initial_status[1][0] = POKEMON_STATUS_PARALYSIS;
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    PokemonBattle paralyzed;
    assert(pokemon_battle_init(&paralyzed, &salts_init) == POKEMON_OK);
    assert(pokemon_battle_step(&paralyzed, choices) == POKEMON_OK);
    uint16_t doubled_damage = first_damage(&paralyzed);
    assert(paralyzed.sides[1].state[0].status.kind == POKEMON_STATUS_NONE);
    assert(handler_id_count(
        &paralyzed, POKEMON_GEN3_HANDLER_SMELLING_SALTS_HIT) == 1);
    assert(paralyzed.effect_trace_count == 1);
    assert(paralyzed.effect_traces[0].kind == POKEMON_EFFECT_CURE_STATUS);
    assert(paralyzed.effect_traces[0].move_id ==
        POKEMON_GEN3_MOVE_SMELLINGSALTS);
    assert(paralyzed.effect_traces[0].source_side == 0);
    assert(paralyzed.effect_traces[0].target_side == 1);
    assert(paralyzed.effect_traces[0].before == POKEMON_STATUS_PARALYSIS);
    assert(paralyzed.effect_traces[0].after == POKEMON_STATUS_NONE);

    salts_init.initial_status[1][0] = POKEMON_STATUS_NONE;
    PokemonBattle ordinary;
    assert(pokemon_battle_init(&ordinary, &salts_init) == POKEMON_OK);
    assert(pokemon_battle_step(&ordinary, choices) == POKEMON_OK);
    assert(doubled_damage > first_damage(&ordinary));
    assert(ordinary.sides[1].state[0].status.kind == POKEMON_STATUS_NONE);
    PokemonBattleInit drum_init = condition_init(
        POKEMON_GEN3_SPECIES_CHARIZARD, POKEMON_GEN3_MOVE_BELLYDRUM,
        POKEMON_GEN3_SPECIES_SNORLAX, POKEMON_GEN3_MOVE_SPLASH);
    drum_init.teams[0].members[0].stats[0] = 301;
    PokemonBattle drum;
    assert(pokemon_battle_init(&drum, &drum_init) == POKEMON_OK);
    assert(pokemon_battle_step(&drum, choices) == POKEMON_OK);
    assert(drum.sides[0].state[0].hp == 151);
    assert(drum.sides[0].state[0].boosts[POKEMON_STAT_ATK] == 6);
    assert(handler_id_count(
        &drum, POKEMON_GEN3_HANDLER_BELLY_DRUM_HIT) == 1);

    drum_init.initial_hp[0][0] = 150;
    assert(pokemon_battle_init(&drum, &drum_init) == POKEMON_OK);
    assert(pokemon_battle_step(&drum, choices) == POKEMON_OK);
    assert(drum.sides[0].state[0].hp == 150);
    assert(drum.sides[0].state[0].boosts[POKEMON_STAT_ATK] == 0);

    drum_init.initial_hp[0][0] = 301;
    assert(pokemon_battle_init(&drum, &drum_init) == POKEMON_OK);
    drum.sides[0].state[0].boosts[POKEMON_STAT_ATK] = 6;
    assert(pokemon_battle_step(&drum, choices) == POKEMON_OK);
    assert(drum.sides[0].state[0].hp == 301);
    assert(drum.sides[0].state[0].boosts[POKEMON_STAT_ATK] == 6);

    PokemonBattleInit shedinja = condition_init(
        POKEMON_GEN3_SPECIES_SHEDINJA, POKEMON_GEN3_MOVE_BELLYDRUM,
        POKEMON_GEN3_SPECIES_SNORLAX, POKEMON_GEN3_MOVE_SPLASH);
    shedinja.teams[0].members[0].stats[0] = 1;
    assert(pokemon_battle_init(&drum, &shedinja) == POKEMON_OK);
    assert(pokemon_battle_step(&drum, choices) == POKEMON_OK);
    assert(drum.sides[0].state[0].hp == 1);
    assert(drum.sides[0].state[0].boosts[POKEMON_STAT_ATK] == 0);
    assert(pokemon_battle_check_invariants(&drum));

    PokemonHandlerOp programs[
        POKEMON_GEN3_SLICE_DATA.handler_program_count];
    memcpy(programs, POKEMON_GEN3_SLICE_DATA.handler_programs,
        sizeof(programs));
    for (size_t i = 0; i < POKEMON_GEN3_SLICE_DATA.handler_count; i++) {
        const PokemonHandlerDescriptor *handler =
            &POKEMON_GEN3_SLICE_DATA.handlers[i];
        if (handler->id != POKEMON_GEN3_HANDLER_BELLY_DRUM_HIT) continue;
        assert(handler->program_count == 1);
        programs[handler->program_offset].argument &= ~UINT32_C(0xff);
    }
    PokemonData invalid_data = POKEMON_GEN3_SLICE_DATA;
    invalid_data.handler_programs = programs;
    assert_invalid_resolved_data_is_atomic(drum_init, &invalid_data);

    PokemonMoveData moves[POKEMON_GEN3_SLICE_DATA.move_count];
    memcpy(moves, POKEMON_GEN3_SLICE_DATA.moves, sizeof(moves));
    moves[POKEMON_GEN3_MOVE_SMELLINGSALTS - 1]
        .target_status_power_multiplier = 1;
    invalid_data = POKEMON_GEN3_SLICE_DATA;
    invalid_data.moves = moves;
    assert_invalid_resolved_data_is_atomic(salts_init, &invalid_data);
}

static void test_initial_toxic_stage_payload(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SEVIPER, POKEMON_GEN3_MOVE_SCREECH,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SOFTBOILED
    );
    init.initial_status[0][0] = POKEMON_STATUS_TOXIC;
    init.initial_toxic_stage[0][0] = 7;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(battle.sides[0].state[0].status.kind == POKEMON_STATUS_TOXIC);
    /* Initial actives execute the ordinary SwitchIn lifecycle during init. */
    assert(battle.sides[0].state[0].status.state.toxic.stage == 0);
    assert(pokemon_battle_check_invariants(&battle));

    PokemonBattle untouched;
    memset(&untouched, 0x6b, sizeof(untouched));
    PokemonBattle before = untouched;
    init.initial_toxic_stage[0][0] =
        (uint8_t)(POKEMON_GEN3_RULES.toxic_stage_cap + 1u);
    assert(pokemon_battle_init(&untouched, &init) ==
        POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&untouched, &before, sizeof(untouched)) == 0);

    init.initial_status[0][0] = POKEMON_STATUS_POISON;
    init.initial_toxic_stage[0][0] = 1;
    assert(pokemon_battle_init(&untouched, &init) ==
        POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&untouched, &before, sizeof(untouched)) == 0);
}

static void test_residual_active_turn_boost_family(void) {
    enum { TEST_SPEED_ABILITY = 62300, TEST_SPEED_HANDLER = 62301 };
    PokemonAbilityData ability = {
        .id = TEST_SPEED_ABILITY, .handler_offset = 0, .handler_count = 1,
    };
    PokemonHandlerDescriptor handler = {
        .event = POKEMON_HANDLER_EVENT_RESIDUAL,
        .id = TEST_SPEED_HANDLER,
        .source_kind = POKEMON_HANDLER_SOURCE_ABILITY,
        .source_id = TEST_SPEED_ABILITY,
        .program_offset = 0, .program_count = 3,
        .order = 10, .sub_order = 3,
        .scope = POKEMON_HANDLER_SCOPE_TARGET,
        .route = POKEMON_HANDLER_ROUTE_OWNER,
        .raw_hook = "onResidual",
    };
    PokemonOwnerBindingIndex binding = {
        .owner_kind = POKEMON_OWNER_ABILITY,
        .owner_id = TEST_SPEED_ABILITY,
        .event = POKEMON_HANDLER_EVENT_RESIDUAL,
        .scope = POKEMON_HANDLER_SCOPE_TARGET,
        .route = POKEMON_HANDLER_ROUTE_OWNER,
        .binding_offset = 0, .binding_count = 1,
    };
    PokemonHandlerOp programs[] = {
        {POKEMON_HANDLER_OP_GUARD_HOLDER_ALIVE, 0},
        {POKEMON_HANDLER_OP_GUARD_HOLDER_ACTIVE_TURNS, 0},
        {POKEMON_HANDLER_OP_BOOST_HOLDER_STAT,
            (POKEMON_STAT_SPE << 8) | UINT8_C(1)},
    };
    PokemonData data = POKEMON_GEN3_SLICE_DATA;
    PokemonMoveData synthetic_moves[POKEMON_GEN3_MOVE_COUNT];
    remove_move_call_capability(&data, synthetic_moves);
    data.abilities = &ability;
    data.ability_count = 1;
    data.handlers = &handler;
    data.handler_count = 1;
    data.handler_programs = programs;
    data.handler_program_count = sizeof(programs) / sizeof(programs[0]);
    data.owner_binding_index = &binding;
    data.owner_binding_index_count = 1;
    PokemonResolvedBundle bundle = POKEMON_GEN3_OU_BUNDLE;
    PokemonFormatPolicy policy = *bundle.policy;
    policy.status_clauses = NULL;
    policy.status_clause_count = 0;
    bundle.policy = &policy;
    bundle.data = &data;

    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SPLASH,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SPLASH);
    init.bundle = &bundle;
    init.team_sizes[0] = 2;
    init.teams[0].members[0].ability_id = TEST_SPEED_ABILITY;
    init.teams[0].members[1] = make_set(
        POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_SPLASH,
        200, 50, 50, 50, 50, 50);
    init.teams[0].members[1].ability_id = TEST_SPEED_ABILITY;
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(battle.sides[0].state[0].active_turns == 1);
    assert(battle.sides[0].state[1].active_turns == 0);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].boosts[POKEMON_STAT_SPE] == 1);
    assert(battle.sides[0].state[0].active_turns == 2);

    choices[0] = switch_to(1);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[1].boosts[POKEMON_STAT_SPE] == 0);
    assert(battle.sides[0].state[1].active_turns == 1);
    choices[0] = move(0);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[1].boosts[POKEMON_STAT_SPE] == 1);

    programs[2].argument = POKEMON_STAT_SPE << 8;
    PokemonBattle invalid;
    assert(pokemon_battle_init(&invalid, &init) == POKEMON_OK);
    PokemonBattle before = invalid;
    choices[0] = move(0);
    assert(pokemon_battle_step(&invalid, choices) ==
        POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&invalid, &before, sizeof(invalid)) == 0);
}

static void test_generated_truant_pokemon_owned_phase(void) {
    const uint32_t phase_mask = UINT32_C(1) <<
        POKEMON_BOOLEAN_STATE_ALTERNATING_ACTION_PHASE;
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SLAKING, POKEMON_GEN3_MOVE_SPLASH,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SPLASH);
    init.team_sizes[0] = 1;
    init.team_sizes[1] = 1;
    init.teams[0].members[0].ability_id = POKEMON_GEN3_ABILITY_TRUANT;
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    PokemonBattle battle;

    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(battle.initial_setup_complete == 1);
    assert((battle.sides[0].state[0].boolean_states & phase_mask) == 0);
    assert(handler_id_count(
        &battle, POKEMON_GEN3_HANDLER_TRUANT_SWITCH_IN) == 1);

    uint8_t initial_pp = battle.sides[0].state[0].pp[0];
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].pp[0] == initial_pp - 1);
    assert(battle.sides[0].state[0].last_move_id == POKEMON_GEN3_MOVE_SPLASH);
    assert((battle.sides[0].state[0].boolean_states & phase_mask) != 0);
    assert(handler_id_count(
        &battle, POKEMON_GEN3_HANDLER_TRUANT_BEFORE_MOVE) == 1);
    assert(handler_id_count(
        &battle, POKEMON_GEN3_HANDLER_TRUANT_RESIDUAL) == 1);

    uint8_t acted_pp = battle.sides[0].state[0].pp[0];
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].pp[0] == acted_pp);
    assert((battle.sides[0].state[0].boolean_states & phase_mask) == 0);
    assert(handler_id_count(
        &battle, POKEMON_GEN3_HANDLER_TRUANT_BEFORE_MOVE) == 1);
    assert(handler_id_count(
        &battle, POKEMON_GEN3_HANDLER_TRUANT_RESIDUAL) == 1);

    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].pp[0] == acted_pp - 1);
    assert((battle.sides[0].state[0].boolean_states & phase_mask) != 0);
    assert(pokemon_battle_check_invariants(&battle));

    /* A mid-turn SwitchIn initializes the incoming Pokémon's own bit. The
     * same turn's order-27 residual toggles it, so its first selectable move
     * on the following turn executes. */
    init = condition_init(
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SPLASH,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SPLASH);
    init.team_sizes[0] = 2;
    init.team_sizes[1] = 1;
    init.teams[0].members[1] = make_set(
        POKEMON_GEN3_SPECIES_SLAKING, POKEMON_GEN3_MOVE_SPLASH,
        300, 200, 150, 150, 150, 100);
    init.teams[0].members[1].ability_id = POKEMON_GEN3_ABILITY_TRUANT;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    PokemonChoice switch_choices[POKEMON_SIDES] = {switch_to(1), move(0)};
    assert(pokemon_battle_step(&battle, switch_choices) == POKEMON_OK);
    assert(battle.sides[0].active == 1);
    assert((battle.sides[0].state[1].boolean_states & phase_mask) == 0);
    assert(handler_id_count(
        &battle, POKEMON_GEN3_HANDLER_TRUANT_SWITCH_IN) == 1);
    assert(handler_id_count(
        &battle, POKEMON_GEN3_HANDLER_TRUANT_RESIDUAL) == 1);
    uint8_t switched_pp = battle.sides[0].state[1].pp[0];
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[1].pp[0] == switched_pp - 1);

    /* The inherited empty condition remains catalog evidence only. */
    for (size_t i = 0; i < battle.data->owner_binding_index_count; i++) {
        const PokemonOwnerBindingIndex *binding =
            &battle.data->owner_binding_index[i];
        assert(!(binding->owner_kind == POKEMON_OWNER_VOLATILE &&
            binding->owner_id == POKEMON_GEN3_CONDITION_VOLATILE_TRUANT));
    }

    PokemonBattle malformed = battle;
    malformed.initial_setup_complete = 2;
    assert(!pokemon_battle_check_invariants(&malformed));
    malformed = battle;
    malformed.sides[0].state[0].boolean_states |= UINT32_C(1);
    assert(!pokemon_battle_check_invariants(&malformed));
    malformed = battle;
    malformed.sides[0].state[0].boolean_states |=
        UINT32_C(1) << POKEMON_BOOLEAN_STATE_COUNT;
    assert(!pokemon_battle_check_invariants(&malformed));
}

static void test_pain_split_atomic_bilateral_hp_assignment(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_DUSCLOPS, POKEMON_GEN3_MOVE_PAINSPLIT,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[0].members[0].stats[0] = 300;
    init.teams[1].members[0].stats[0] = 700;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    const PokemonMoveData *pain_split =
        &POKEMON_GEN3_SLICE_DATA.moves[POKEMON_GEN3_MOVE_PAINSPLIT - 1];
    const PokemonHandlerDescriptor *handler =
        &POKEMON_GEN3_SLICE_DATA.handlers[
            POKEMON_GEN3_HANDLER_PAIN_SPLIT_HIT - 1];
    assert(pain_split->id == POKEMON_GEN3_MOVE_PAINSPLIT);
    assert(handler->event == POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK);
    assert(handler->source_kind == POKEMON_HANDLER_SOURCE_MOVE);
    assert(handler->source_id == POKEMON_GEN3_MOVE_PAINSPLIT);
    assert(handler->program_count == 1);
    assert(POKEMON_GEN3_SLICE_DATA.handler_programs[
        handler->program_offset].opcode ==
        POKEMON_HANDLER_OP_SET_SOURCE_TARGET_HP_TO_FLOOR_AVERAGE);

    PokemonEventInput input = {
        .event = POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK,
        .source = {POKEMON_ENTITY_POKEMON, 0, 0},
        .target_side = 1, .target_slot = 0,
        .source_effect = {POKEMON_SOURCE_EFFECT_MOVE,
            POKEMON_GEN3_MOVE_PAINSPLIT},
        .relay = {.kind = POKEMON_RELAY_BOOLEAN, .value.boolean = 1},
        .context_kind = POKEMON_EVENT_CONTEXT_MOVE,
        .context.move = {.move = pain_split},
        .include_move_self = 1,
    };
    PokemonEventFrame frame;
    battle.sides[0].state[0].hp = 101;
    battle.sides[1].state[0].hp = 200;
    uint16_t event_count = battle.event_count;
    uint16_t draw_count = battle.draw_count;
    assert(pokemon_run_event(&battle, &input, &frame) == POKEMON_OK);
    assert(battle.sides[0].state[0].hp == 150);
    assert(battle.sides[1].state[0].hp == 150);
    assert(battle.event_count == event_count);
    assert(battle.draw_count == draw_count);

    /* The shared requested value is computed once from the snapshot, then
     * clamped independently; target mutation cannot feed source calculation. */
    uint16_t source_max = battle.sides[0].sets[0].stats[0];
    battle.sides[0].state[0].hp = source_max;
    battle.sides[1].state[0].hp = 600;
    uint16_t requested = (uint16_t)((source_max + 600u) / 2u);
    assert(requested > source_max);
    assert(pokemon_run_event(&battle, &input, &frame) == POKEMON_OK);
    assert(battle.sides[0].state[0].hp == source_max);
    assert(battle.sides[1].state[0].hp == requested);

    init = condition_init(
        POKEMON_GEN3_SPECIES_DUSCLOPS, POKEMON_GEN3_MOVE_PAINSPLIT,
        POKEMON_GEN3_SPECIES_SHEDINJA, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[0].members[0].stats[0] = 300;
    init.teams[1].members[0].stats[0] = 1;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    battle.sides[0].state[0].hp = 249;
    battle.sides[1].state[0].hp = 1;
    assert(pokemon_run_event(&battle, &input, &frame) == POKEMON_OK);
    assert(battle.sides[0].state[0].hp == 125);
    assert(battle.sides[1].state[0].hp == 1);
    assert(battle.faint_count == 0);

    battle.sides[0].state[0].hp = 1;
    battle.sides[1].state[0].hp = 1;
    assert(pokemon_run_event(&battle, &input, &frame) == POKEMON_OK);
    assert(battle.sides[0].state[0].hp == 1);
    assert(battle.sides[1].state[0].hp == 1);
    assert(pokemon_battle_check_invariants(&battle));
}

static void test_major_status_replacement_transaction(void) {
    const PokemonStatus occupied[] = {
        POKEMON_STATUS_BURN, POKEMON_STATUS_TOXIC,
        POKEMON_STATUS_PARALYSIS, POKEMON_STATUS_POISON,
        POKEMON_STATUS_FREEZE,
    };
    PokemonEntityRef holder = {POKEMON_ENTITY_POKEMON, 0, 0};
    PokemonSourceEffectRef effect = {
        POKEMON_SOURCE_EFFECT_MOVE, POKEMON_GEN3_MOVE_SPLASH};

    for (size_t i = 0; i < sizeof(occupied) / sizeof(occupied[0]); i++) {
        PokemonBattleInit init = condition_init(
            POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_SPLASH,
            POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SPLASH);
        init.initial_status[0][0] = occupied[i];
        PokemonBattle battle;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        PokemonStatusState before = battle.sides[0].state[0].status;
        uint8_t applied = 99;

        assert(pokemon_set_status(
            &battle, holder, POKEMON_STATUS_SLEEP, holder, effect,
            0, &applied) == POKEMON_OK);
        assert(!applied);
        assert(memcmp(&battle.sides[0].state[0].status, &before,
            sizeof(before)) == 0);
        assert(draw_label_count(&battle, POKEMON_DRAW_SLEEP_DURATION) == 0);

        assert(pokemon_set_status_with_policy(
            &battle, holder, POKEMON_STATUS_SLEEP, holder, effect,
            POKEMON_STATUS_SET_REPLACE_DIFFERENT, 0, &applied) == POKEMON_OK);
        assert(applied);
        const PokemonStatusState *after = &battle.sides[0].state[0].status;
        assert(after->kind == POKEMON_STATUS_SLEEP);
        assert(after->state_generation == before.state_generation + 1);
        assert(after->state.sleep.time >= 2 && after->state.sleep.time <= 5);
        assert(draw_label_count(&battle, POKEMON_DRAW_SLEEP_DURATION) == 1);
        assert(battle.condition_trace_count >= 2);
        const PokemonConditionTrace *removed = &battle.condition_traces[
            battle.condition_trace_count - 2];
        const PokemonConditionTrace *added = &battle.condition_traces[
            battle.condition_trace_count - 1];
        assert(removed->operation == POKEMON_CONDITION_REMOVE);
        assert(removed->condition_id == occupied[i]);
        assert(added->operation == POKEMON_CONDITION_ADD);
        assert(added->condition_id == POKEMON_STATUS_SLEEP);

        size_t draws = battle.draw_count;
        assert(pokemon_set_status_with_policy(
            &battle, holder, POKEMON_STATUS_SLEEP, holder, effect,
            POKEMON_STATUS_SET_REPLACE_DIFFERENT, 0, &applied) == POKEMON_OK);
        assert(!applied && battle.draw_count == draws);
        assert(pokemon_battle_check_invariants(&battle));
    }

    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_SPLASH,
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SPLASH);
    init.initial_status[0][0] = POKEMON_STATUS_BURN;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    PokemonStatusState before = battle.sides[0].state[0].status;
    battle.condition_trace_count = POKEMON_CONDITION_TRACE_CAPACITY - 1;
    uint8_t applied = 99;
    assert(pokemon_set_status_with_policy(
        &battle, holder, POKEMON_STATUS_SLEEP, holder, effect,
        POKEMON_STATUS_SET_REPLACE_DIFFERENT, 0, &applied) ==
        POKEMON_CAPACITY_EXCEEDED);
    assert(!applied);
    assert(memcmp(&battle.sides[0].state[0].status, &before,
        sizeof(before)) == 0);
    assert(draw_label_count(&battle, POKEMON_DRAW_SLEEP_DURATION) == 0);
}

static void test_generated_rest_programs(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_REST,
        POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_SPLASH);
    uint16_t max_hp = init.teams[0].members[0].stats[0];
    init.initial_hp[0][0] = (uint16_t)(max_hp / 2u);
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    const PokemonMutable *holder = &battle.sides[0].state[0];
    assert(holder->hp == max_hp);
    assert(holder->status.kind == POKEMON_STATUS_SLEEP);
    assert(holder->status.state.sleep.time == 3);
    assert(holder->status.state.sleep.skipped_time == 0);
    assert(draw_label_count(&battle, POKEMON_DRAW_SLEEP_DURATION) == 1);
    assert(handler_event_count(&battle, POKEMON_HANDLER_EVENT_TRY) == 1);
    assert(handler_event_count(
        &battle, POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK) == 1);

    init.initial_hp[0][0] = max_hp;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    holder = &battle.sides[0].state[0];
    assert(holder->hp == max_hp);
    assert(holder->status.kind == POKEMON_STATUS_NONE);
    assert(draw_label_count(&battle, POKEMON_DRAW_SLEEP_DURATION) == 0);
    assert(handler_event_count(&battle, POKEMON_HANDLER_EVENT_TRY) == 1);
    assert(handler_event_count(
        &battle, POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK) == 0);

    init = condition_init(
        POKEMON_GEN3_SPECIES_BANETTE, POKEMON_GEN3_MOVE_REST,
        POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[0].members[0].ability_id = POKEMON_GEN3_ABILITY_INSOMNIA;
    init.initial_hp[0][0] = (uint16_t)(init.teams[0].members[0].stats[0] / 2u);
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(battle.sides[0].state[0].ability_id ==
        POKEMON_GEN3_ABILITY_INSOMNIA);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    holder = &battle.sides[0].state[0];
    assert(holder->status.kind == POKEMON_STATUS_NONE);
    assert(draw_label_count(&battle, POKEMON_DRAW_SLEEP_DURATION) == 0);
    assert(handler_event_count(
        &battle, POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK) == 0);
}

static void test_generated_synchronize_after_set_status(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_TOXIC,
        POKEMON_GEN3_SPECIES_ALAKAZAM, POKEMON_GEN3_MOVE_RECOVER);
    init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_SYNCHRONIZE;
    PokemonBattle battle;
    PokemonEntityRef source = {POKEMON_ENTITY_POKEMON, 0, 0};
    PokemonEntityRef target = {POKEMON_ENTITY_POKEMON, 1, 0};
    PokemonSourceEffectRef effect = {
        POKEMON_SOURCE_EFFECT_MOVE, POKEMON_GEN3_MOVE_TOXIC};
    uint8_t applied = 0;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_set_status(
        &battle, target, POKEMON_STATUS_BURN, source, effect,
        1, &applied) == POKEMON_OK && applied);
    assert(battle.sides[0].state[0].status.kind == POKEMON_STATUS_BURN);
    assert(battle.sides[1].state[0].status.kind == POKEMON_STATUS_BURN);

    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_set_status(
        &battle, target, POKEMON_STATUS_TOXIC, source, effect,
        1, &applied) == POKEMON_OK && applied);
    assert(battle.sides[0].state[0].status.kind == POKEMON_STATUS_POISON);
    assert(battle.sides[1].state[0].status.kind == POKEMON_STATUS_TOXIC);

    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_set_status(
        &battle, target, POKEMON_STATUS_SLEEP, source, effect,
        1, &applied) == POKEMON_OK && applied);
    assert(battle.sides[0].state[0].status.kind == POKEMON_STATUS_NONE);
    assert(battle.sides[1].state[0].status.kind == POKEMON_STATUS_SLEEP);
    assert(draw_label_count(&battle, POKEMON_DRAW_SLEEP_DURATION) == 1);
}

static void test_primary_major_status_family(void) {
    static const struct { uint16_t move; PokemonStatus status; } descriptors[] = {
        {POKEMON_GEN3_MOVE_GLARE, POKEMON_STATUS_PARALYSIS},
        {POKEMON_GEN3_MOVE_GRASSWHISTLE, POKEMON_STATUS_SLEEP},
        {POKEMON_GEN3_MOVE_HYPNOSIS, POKEMON_STATUS_SLEEP},
        {POKEMON_GEN3_MOVE_LOVELYKISS, POKEMON_STATUS_SLEEP},
        {POKEMON_GEN3_MOVE_POISONGAS, POKEMON_STATUS_POISON},
        {POKEMON_GEN3_MOVE_POISONPOWDER, POKEMON_STATUS_POISON},
        {POKEMON_GEN3_MOVE_SING, POKEMON_STATUS_SLEEP},
        {POKEMON_GEN3_MOVE_SLEEPPOWDER, POKEMON_STATUS_SLEEP},
        {POKEMON_GEN3_MOVE_SPORE, POKEMON_STATUS_SLEEP},
        {POKEMON_GEN3_MOVE_STUNSPORE, POKEMON_STATUS_PARALYSIS},
        {POKEMON_GEN3_MOVE_THUNDERWAVE, POKEMON_STATUS_PARALYSIS},
        {POKEMON_GEN3_MOVE_WILLOWISP, POKEMON_STATUS_BURN},
    };
    for (size_t i = 0; i < sizeof(descriptors) / sizeof(descriptors[0]); i++) {
        const PokemonMoveData *move_data = NULL;
        for (size_t j = 0; j < POKEMON_GEN3_SLICE_DATA.move_count; j++) {
            if (POKEMON_GEN3_SLICE_DATA.moves[j].id == descriptors[i].move) {
                move_data = &POKEMON_GEN3_SLICE_DATA.moves[j];
                break;
            }
        }
        assert(move_data != NULL && move_data->effect_count == 1);
        const PokemonEffectOp *effect =
            &POKEMON_GEN3_SLICE_DATA.effects[move_data->effect_offset];
        assert(effect->kind == POKEMON_EFFECT_SET_STATUS);
        assert(effect->argument == descriptors[i].status);
        assert(move_data->checks_natural_type_immunity ==
            (descriptors[i].move == POKEMON_GEN3_MOVE_GLARE ||
             descriptors[i].move == POKEMON_GEN3_MOVE_THUNDERWAVE));
    }

    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_GENGAR, POKEMON_GEN3_MOVE_SPORE,
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SPLASH);
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].state[0].status.kind == POKEMON_STATUS_SLEEP);
    assert(battle.sides[1].state[0].status.source.side == 0);
    assert(battle.sides[1].state[0].status.source_effect.kind ==
        POKEMON_SOURCE_EFFECT_MOVE);
    assert(battle.sides[1].state[0].status.source_effect.id ==
        POKEMON_GEN3_MOVE_SPORE);
    assert(battle.sides[1].state[0].status.state.sleep.time >= 1 &&
        battle.sides[1].state[0].status.state.sleep.time <= 4);
    int saw_duration = 0;
    for (size_t i = 0; i < battle.draw_count; i++) {
        if (battle.draws[i].label == POKEMON_DRAW_SLEEP_DURATION) {
            assert(battle.draws[i].upper_bound == 4);
            saw_duration = 1;
        }
    }
    assert(saw_duration);

    init = condition_init(
        POKEMON_GEN3_SPECIES_GENGAR, POKEMON_GEN3_MOVE_THUNDERWAVE,
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_LIMBER;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].state[0].status.kind == POKEMON_STATUS_NONE);

    init = condition_init(
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_GLARE,
        POKEMON_GEN3_SPECIES_GENGAR, POKEMON_GEN3_MOVE_SPLASH);
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].state[0].status.kind == POKEMON_STATUS_NONE);
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 1);
    assert(battle.immunity_count == 0);
    assert(event_kind_count(&battle, POKEMON_EVENT_IMMUNE) == 1);

    init = condition_init(
        POKEMON_GEN3_SPECIES_GENGAR, POKEMON_GEN3_MOVE_THUNDERWAVE,
        POKEMON_GEN3_SPECIES_MAROWAK, POKEMON_GEN3_MOVE_SPLASH);
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].state[0].status.kind == POKEMON_STATUS_NONE);
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 1);
    assert(battle.immunity_count == 0);

    init = condition_init(
        POKEMON_GEN3_SPECIES_GENGAR, POKEMON_GEN3_MOVE_POISONPOWDER,
        POKEMON_GEN3_SPECIES_VENUSAUR, POKEMON_GEN3_MOVE_SPLASH);
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].state[0].status.kind == POKEMON_STATUS_NONE);
}

static void test_status_ability_hooks_and_clauses(void) {
    static const struct {
        uint16_t ability;
        PokemonStatus status;
        PokemonEventId gate_event;
        uint8_t blocks_sleep_volatile;
    } cases[] = {
        {POKEMON_GEN3_ABILITY_IMMUNITY, POKEMON_STATUS_POISON,
            POKEMON_HANDLER_EVENT_SET_STATUS, 0},
        {POKEMON_GEN3_ABILITY_IMMUNITY, POKEMON_STATUS_TOXIC,
            POKEMON_HANDLER_EVENT_SET_STATUS, 0},
        {POKEMON_GEN3_ABILITY_INSOMNIA, POKEMON_STATUS_SLEEP,
            POKEMON_HANDLER_EVENT_SET_STATUS, 1},
        {POKEMON_GEN3_ABILITY_VITALSPIRIT, POKEMON_STATUS_SLEEP,
            POKEMON_HANDLER_EVENT_SET_STATUS, 1},
        {POKEMON_GEN3_ABILITY_LIMBER, POKEMON_STATUS_PARALYSIS,
            POKEMON_HANDLER_EVENT_SET_STATUS, 0},
        {POKEMON_GEN3_ABILITY_WATERVEIL, POKEMON_STATUS_BURN,
            POKEMON_HANDLER_EVENT_SET_STATUS, 0},
        {POKEMON_GEN3_ABILITY_MAGMAARMOR, POKEMON_STATUS_FREEZE,
            POKEMON_HANDLER_EVENT_IMMUNITY, 0},
    };
    for (size_t i = 0; i < sizeof(cases) / sizeof(cases[0]); i++) {
        PokemonBattleInit init = condition_init(
            POKEMON_GEN3_SPECIES_GENGAR, POKEMON_GEN3_MOVE_SPLASH,
            POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SPLASH);
        init.teams[1].members[0].ability_id = cases[i].ability;
        PokemonBattle battle;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        size_t initial_draw_count = battle.draw_count;
        size_t initial_event_count = battle.event_count;
        uint8_t applied = 1;
        assert(pokemon_set_status(
            &battle, (PokemonEntityRef){POKEMON_ENTITY_POKEMON, 1, 0},
            cases[i].status,
            (PokemonEntityRef){POKEMON_ENTITY_POKEMON, 0, 0},
            (PokemonSourceEffectRef){POKEMON_SOURCE_EFFECT_CONDITION, 1},
            1, &applied) == POKEMON_OK);
        assert(!applied && battle.sides[1].state[0].status.kind ==
            POKEMON_STATUS_NONE);
        assert(battle.event_count == initial_event_count + 1);
        assert(battle.events[battle.event_count - 1].kind ==
            POKEMON_EVENT_IMMUNE);
        assert(battle.events[battle.event_count - 1].immunity_cause ==
            POKEMON_IMMUNITY_HANDLER);
        if (cases[i].gate_event == POKEMON_HANDLER_EVENT_SET_STATUS) {
            assert(battle.draw_count == initial_draw_count + 1);
            assert(battle.draws[initial_draw_count].label ==
                POKEMON_DRAW_EVENT_HANDLER_ORDER);
            assert(battle.draws[initial_draw_count].context_event_id ==
                POKEMON_HANDLER_EVENT_SET_STATUS);
            assert(battle.draws[initial_draw_count].lower_bound == 1);
            assert(battle.draws[initial_draw_count].upper_bound == 2);
        } else {
            assert(battle.draw_count == initial_draw_count);
        }
        uint8_t blocked = 0;
        assert(pokemon_ability_blocks_sleep_volatile(
            battle.data, cases[i].ability, &blocked) == POKEMON_OK);
        assert(blocked == cases[i].blocks_sleep_volatile);

        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        battle.sides[1].state[0].status.kind = cases[i].status;
        battle.sides[1].state[0].status.descriptor_id =
            battle.generation->condition_descriptor(
                POKEMON_OWNER_STATUS, cases[i].status);
        assert(pokemon_update_status_abilities(&battle) == POKEMON_OK);
        assert(battle.sides[1].state[0].status.kind == POKEMON_STATUS_NONE);
        assert(battle.condition_trace_count == 1);
        assert(battle.condition_traces[0].operation == POKEMON_CONDITION_REMOVE);
        assert(battle.condition_traces[0].reason ==
            POKEMON_CONDITION_REASON_HANDLER);
    }

    for (PokemonStatus clause_status = POKEMON_STATUS_SLEEP;
         clause_status <= POKEMON_STATUS_FREEZE; clause_status++) {
        if (clause_status != POKEMON_STATUS_SLEEP &&
            clause_status != POKEMON_STATUS_FREEZE) continue;
        PokemonBattleInit init = condition_init(
            POKEMON_GEN3_SPECIES_GENGAR, POKEMON_GEN3_MOVE_SPLASH,
            POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SPLASH);
        PokemonBattle battle;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        uint8_t applied = 0;
        PokemonSourceEffectRef source_effect = {
            POKEMON_SOURCE_EFFECT_CONDITION, 1};
        assert(pokemon_set_status(
            &battle, (PokemonEntityRef){POKEMON_ENTITY_POKEMON, 1, 0},
            clause_status, (PokemonEntityRef){POKEMON_ENTITY_POKEMON, 0, 0},
            source_effect, 0, &applied) == POKEMON_OK && applied);
        applied = 1;
        assert(pokemon_set_status(
            &battle, (PokemonEntityRef){POKEMON_ENTITY_POKEMON, 1, 1},
            clause_status, (PokemonEntityRef){POKEMON_ENTITY_POKEMON, 0, 0},
            source_effect, 0, &applied) == POKEMON_OK && !applied);
        assert(battle.sides[1].state[1].status.kind == POKEMON_STATUS_NONE);
        applied = 0;
        assert(pokemon_set_status(
            &battle, (PokemonEntityRef){POKEMON_ENTITY_POKEMON, 1, 1},
            clause_status, (PokemonEntityRef){POKEMON_ENTITY_POKEMON, 1, 0},
            source_effect, 0, &applied) == POKEMON_OK && applied);
    }

    /* The same runtime geometry can be bound to another resolved policy. */
    PokemonFormatManifest no_clause_manifest = POKEMON_GEN3_OU_FORMAT;
    no_clause_manifest.id = "gen3unclausedtest";
    no_clause_manifest.name = "[Gen 3] Unclaused Test";
    no_clause_manifest.rules = NULL;
    no_clause_manifest.rule_count = 0;
    PokemonFormatPolicy no_clauses = POKEMON_GEN3_OU_POLICY;
    no_clauses.manifest = &no_clause_manifest;
    no_clauses.status_clauses = NULL;
    no_clauses.status_clause_count = 0;
    PokemonResolvedBundle no_clause_bundle = POKEMON_GEN3_OU_BUNDLE;
    no_clause_bundle.policy = &no_clauses;
    no_clause_bundle.manifest = &no_clause_manifest;
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_GENGAR, POKEMON_GEN3_MOVE_SPLASH,
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SPLASH);
    init.bundle = &no_clause_bundle;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(no_clause_bundle.runtime_format == POKEMON_GEN3_OU_BUNDLE.runtime_format);
    PokemonSourceEffectRef source_effect = {
        POKEMON_SOURCE_EFFECT_CONDITION, 1};
    uint8_t applied = 0;
    assert(pokemon_set_status(
        &battle, (PokemonEntityRef){POKEMON_ENTITY_POKEMON, 1, 0},
        POKEMON_STATUS_SLEEP,
        (PokemonEntityRef){POKEMON_ENTITY_POKEMON, 0, 0},
        source_effect, 0, &applied) == POKEMON_OK && applied);
    applied = 0;
    assert(pokemon_set_status(
        &battle, (PokemonEntityRef){POKEMON_ENTITY_POKEMON, 1, 1},
        POKEMON_STATUS_SLEEP,
        (PokemonEntityRef){POKEMON_ENTITY_POKEMON, 0, 0},
        source_effect, 0, &applied) == POKEMON_OK && applied);

    /* A resolved format policy cannot name a handler outside its data bundle. */
    PokemonStatusClausePolicy invalid_clause = {
        .status = POKEMON_STATUS_FREEZE,
        .handler_id = UINT16_MAX - 1,
        .requires_opposing_source = 1,
        .block_any_existing = 1,
    };
    PokemonFormatPolicy invalid_policy = POKEMON_GEN3_OU_POLICY;
    invalid_policy.status_clauses = &invalid_clause;
    invalid_policy.status_clause_count = 1;
    PokemonResolvedBundle invalid_bundle = POKEMON_GEN3_OU_BUNDLE;
    invalid_bundle.policy = &invalid_policy;
    init = condition_init(
        POKEMON_GEN3_SPECIES_GENGAR, POKEMON_GEN3_MOVE_SPLASH,
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SPLASH);
    init.bundle = &invalid_bundle;
    memset(&battle, 0, sizeof(battle));
    PokemonBattle untouched = battle;
    assert(pokemon_battle_init(&battle, &init) ==
        POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&battle, &untouched, sizeof(battle)) == 0);
}

static void test_freeze_thaw_boundaries(void) {
    PokemonMoveData moves[POKEMON_GEN3_MOVE_COUNT];
    memcpy(moves, POKEMON_GEN3_SLICE_DATA.moves,
        POKEMON_GEN3_SLICE_DATA.move_count * sizeof(moves[0]));
    PokemonData data = POKEMON_GEN3_SLICE_DATA;
    data.moves = moves;
    PokemonResolvedBundle bundle = POKEMON_GEN3_OU_BUNDLE;
    bundle.data = &data;

    /* Status installation discovers the generated Start owner even though
     * Gen 3 has no additional mutable payload for freeze. */
    PokemonBattleInit start_init = condition_init(
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SCRATCH,
        POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_SPLASH);
    start_init.bundle = &bundle;
    PokemonBattle start_battle;
    assert(pokemon_battle_init(&start_battle, &start_init) == POKEMON_OK);
    uint8_t applied = 0;
    assert(pokemon_set_status(
        &start_battle,
        (PokemonEntityRef){POKEMON_ENTITY_POKEMON, 1, 0},
        POKEMON_STATUS_FREEZE,
        (PokemonEntityRef){POKEMON_ENTITY_POKEMON, 0, 0},
        (PokemonSourceEffectRef){POKEMON_SOURCE_EFFECT_MOVE,
            POKEMON_GEN3_MOVE_ICEBEAM},
        0, &applied) == POKEMON_OK && applied);
    uint8_t saw_freeze_start = 0;
    for (size_t i = 0; i < start_battle.handler_count; i++) {
        saw_freeze_start |= start_battle.handlers[i].handler.descriptor.id ==
            POKEMON_GEN3_HANDLER_FREEZE_START;
    }
    assert(saw_freeze_start);

    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SCRATCH,
        POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_SPLASH);
    init.bundle = &bundle;
    init.initial_status[0][0] = POKEMON_STATUS_FREEZE;
    for (size_t i = 0; i < data.move_count; i++) {
        if (moves[i].id == POKEMON_GEN3_MOVE_SCRATCH) moves[i].defrost = 1;
    }
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    uint8_t saw_random_thaw = 0;
    uint8_t saw_defrost_bypass = 0;
    for (uint16_t tail = 0; tail <= UINT8_MAX; tail++) {
        init.seed[3] = (uint8_t)tail;
        PokemonBattle battle;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        size_t thaw_draws = 0;
        uint32_t thaw_result = 0;
        for (size_t i = 0; i < battle.draw_count; i++) {
            if (battle.draws[i].label != POKEMON_DRAW_FREEZE_THAW) continue;
            thaw_draws++;
            thaw_result = battle.draws[i].result;
        }
        assert(thaw_draws == 1);
        assert(handler_event_count(
            &battle, POKEMON_HANDLER_EVENT_BEFORE_MOVE) == 1);
        if (thaw_result == 0) {
            saw_random_thaw = 1;
            assert(battle.effect_trace_count == 1);
            assert(battle.effect_traces[0].kind ==
                POKEMON_EFFECT_CURE_STATUS);
            assert(battle.effect_traces[0].move_id ==
                POKEMON_GEN3_MOVE_SCRATCH);
            assert(battle.effect_traces[0].before == POKEMON_STATUS_FREEZE);
            assert(battle.effect_traces[0].after == POKEMON_STATUS_NONE);
            assert(battle.sides[0].state[0].status.kind == POKEMON_STATUS_NONE);
        } else {
            saw_defrost_bypass = 1;
            assert(battle.effect_trace_count == 0);
            assert(battle.sides[0].state[0].status.kind == POKEMON_STATUS_NONE);
            assert(handler_event_count(
                &battle, POKEMON_HANDLER_EVENT_MODIFY_MOVE) == 1);
        }
        if (saw_random_thaw && saw_defrost_bypass) break;
    }
    assert(saw_random_thaw && saw_defrost_bypass);

    /* A defrost move bypasses only freeze's own BeforeMove cancellation.
     * A later handler can still cancel the action, in which case ModifyMove
     * never runs and the user remains frozen. */
    uint8_t saw_later_cancel = 0;
    for (uint16_t tail = 1; tail < 512 && !saw_later_cancel; tail++) {
        init.seed[3] = tail;
        PokemonBattle cancelled;
        assert(pokemon_battle_init(&cancelled, &init) == POKEMON_OK);
        PokemonEffectResult added = POKEMON_EFFECT_FAILED;
        assert(pokemon_try_add_or_restart_volatile(
            &cancelled,
            (PokemonEntityRef){POKEMON_ENTITY_POKEMON, 0, 0},
            (PokemonEntityRef){POKEMON_ENTITY_POKEMON, 1, 0},
            (PokemonSourceEffectRef){POKEMON_SOURCE_EFFECT_MOVE,
                POKEMON_GEN3_MOVE_BITE},
            POKEMON_VOLATILE_FLINCH, POKEMON_CONDITION_REASON_MOVE,
            &added) == POKEMON_OK && added == POKEMON_EFFECT_APPLIED);
        assert(pokemon_battle_step(&cancelled, choices) == POKEMON_OK);
        uint32_t thaw_result = 0;
        for (size_t i = 0; i < cancelled.draw_count; i++) {
            if (cancelled.draws[i].label == POKEMON_DRAW_FREEZE_THAW) {
                thaw_result = cancelled.draws[i].result;
            }
        }
        if (thaw_result == 0) continue;
        saw_later_cancel = 1;
        assert(cancelled.sides[0].state[0].status.kind ==
            POKEMON_STATUS_FREEZE);
        assert(cancelled.sides[0].state[0].last_move_id == 0);
        assert(handler_event_count(
            &cancelled, POKEMON_HANDLER_EVENT_MODIFY_MOVE) == 0);
        assert(cancelled.effect_trace_count == 0);
    }
    assert(saw_later_cancel);

    memcpy(moves, POKEMON_GEN3_SLICE_DATA.moves,
        POKEMON_GEN3_SLICE_DATA.move_count * sizeof(moves[0]));
    for (size_t i = 0; i < data.move_count; i++) {
        if (moves[i].id == POKEMON_GEN3_MOVE_SCRATCH) moves[i].thaws_target = 1;
    }
    init = condition_init(
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SCRATCH,
        POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_SPLASH);
    init.bundle = &bundle;
    init.initial_status[1][0] = POKEMON_STATUS_FREEZE;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].state[0].status.kind == POKEMON_STATUS_NONE);

    memcpy(moves, POKEMON_GEN3_SLICE_DATA.moves,
        POKEMON_GEN3_SLICE_DATA.move_count * sizeof(moves[0]));
    init = condition_init(
        POKEMON_GEN3_SPECIES_CHARMANDER, POKEMON_GEN3_MOVE_EMBER,
        POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_SPLASH);
    init.bundle = &bundle;
    init.initial_status[1][0] = POKEMON_STATUS_FREEZE;
    int saw_fire_thaw = 0;
    int saw_blocked_burn_then_thaw = 0;
    for (uint16_t tail = 1; tail < 512 && !saw_blocked_burn_then_thaw; tail++) {
        init.seed[3] = tail;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        for (size_t i = 0; i < battle.condition_trace_count; i++) {
            if (battle.condition_traces[i].operation == POKEMON_CONDITION_REMOVE &&
                battle.condition_traces[i].condition_id == POKEMON_STATUS_FREEZE) {
                saw_fire_thaw = 1;
            }
        }
        for (size_t i = 0; i < battle.handler_count; i++) {
            if (battle.handlers[i].handler.descriptor.id ==
                    POKEMON_GEN3_HANDLER_FREEZE_DAMAGING_HIT) {
                saw_fire_thaw = 1;
            }
        }
        for (size_t i = 0; i < battle.draw_count; i++) {
            if (battle.draws[i].label == POKEMON_DRAW_SECONDARY &&
                battle.draws[i].result < 10) {
                saw_blocked_burn_then_thaw = 1;
                assert(battle.sides[1].state[0].status.kind ==
                    POKEMON_STATUS_NONE);
            }
        }
    }
    assert(saw_fire_thaw && saw_blocked_burn_then_thaw);

    /* DamagingHit cureStatus is a living-holder operation: a lethal Fire hit
     * must not manufacture a thaw after HP reaches zero. */
    init.teams[1].members[0].stats[0] = 1;
    init.seed[3] = 1;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].state[0].hp == 0);
    assert(battle.sides[1].state[0].status.kind == POKEMON_STATUS_FREEZE);
    for (size_t i = 0; i < battle.condition_trace_count; i++) {
        assert(!(battle.condition_traces[i].operation ==
                POKEMON_CONDITION_REMOVE &&
            battle.condition_traces[i].condition_id == POKEMON_STATUS_FREEZE));
    }
}

static void test_generated_weather_form_projection(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_CASTFORM, POKEMON_GEN3_MOVE_SPLASH,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[0].members[0].ability_id = POKEMON_GEN3_ABILITY_FORECAST;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    PokemonMutable *castform = &battle.sides[0].state[0];
    assert(castform->species_id == POKEMON_GEN3_SPECIES_CASTFORM);
    assert(castform->effective_type_count == 1);
    assert(castform->effective_types[0] == POKEMON_GEN3_TYPE_NORMAL);

    battle.field.weather = (PokemonWeatherState){
        .kind = POKEMON_WEATHER_SUN,
        .descriptor_id = battle.generation->condition_descriptor(
            POKEMON_OWNER_FIELD, POKEMON_WEATHER_SUN),
        .duration = 5, .state_generation = 1,
    };
    PokemonEventFrame frame;
    PokemonEventInput weather_change = {
        .event = POKEMON_HANDLER_EVENT_WEATHER_CHANGE,
        .source = {POKEMON_ENTITY_NONE, 0, 0},
        .target_side = 0, .target_slot = 0,
        .relay = {.kind = POKEMON_RELAY_UNDEFINED},
    };
    assert(pokemon_run_event(&battle, &weather_change, &frame) == POKEMON_OK);
    assert(castform->species_id == POKEMON_GEN3_SPECIES_CASTFORMSUNNY);
    assert(castform->effective_type_count == 1);
    assert(castform->effective_types[0] == POKEMON_GEN3_TYPE_FIRE);

    /* Transform owns the effective profile while installed. Forecast must
     * not partially overwrite either current identity or current types. */
    castform->transformed = 1;
    castform->species_id = POKEMON_GEN3_SPECIES_PERSIAN;
    castform->effective_types[0] = POKEMON_GEN3_TYPE_NORMAL;
    battle.field.weather.kind = POKEMON_WEATHER_HAIL;
    battle.field.weather.descriptor_id =
        battle.generation->condition_descriptor(
            POKEMON_OWNER_FIELD, POKEMON_WEATHER_HAIL);
    assert(pokemon_run_event(&battle, &weather_change, &frame) == POKEMON_OK);
    assert(castform->species_id == POKEMON_GEN3_SPECIES_PERSIAN);
    assert(castform->effective_type_count == 1);
    assert(castform->effective_types[0] == POKEMON_GEN3_TYPE_NORMAL);
    castform->transformed = 0;
    castform->species_id = POKEMON_GEN3_SPECIES_CASTFORMSNOWY;
    castform->effective_types[0] = POKEMON_GEN3_TYPE_ICE;
    assert(pokemon_battle_check_invariants(&battle));

    /* Malformed form families fail bundle admission before battle mutation.
     * Each mutation violates a different generated-data invariant. */
    for (size_t variant = 0; variant < 4; variant++) {
        PokemonWeatherFormPolicy policy =
            POKEMON_GEN3_SLICE_DATA.weather_form_policies[0];
        if (variant == 0) {
            policy.clear_species_id = POKEMON_GEN3_SPECIES_CASTFORMSUNNY;
        } else if (variant == 1) {
            policy.rain_species_id = policy.sun_species_id;
        } else if (variant == 2) {
            policy.hail_species_id = UINT16_MAX;
        } else {
            policy.hail_species_id = POKEMON_GEN3_SPECIES_PERSIAN;
        }
        PokemonData invalid_data = POKEMON_GEN3_SLICE_DATA;
        invalid_data.weather_form_policies = &policy;
        PokemonResolvedBundle invalid_bundle = POKEMON_GEN3_OU_BUNDLE;
        invalid_bundle.data = &invalid_data;
        init.bundle = &invalid_bundle;
        PokemonBattle untouched;
        memset(&untouched, 0x5a, sizeof(untouched));
        PokemonBattle before = untouched;
        assert(pokemon_battle_init(&untouched, &init) ==
            POKEMON_INVALID_CONFIGURATION);
        assert(memcmp(&untouched, &before, sizeof(untouched)) == 0);
    }
}

static void test_generated_ability_lifecycle_weather(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_GOLDUCK, POKEMON_GEN3_MOVE_SURF,
        POKEMON_GEN3_SPECIES_TYRANITAR, POKEMON_GEN3_MOVE_PROTECT);
    init.teams[0].members[0].ability_id = POKEMON_GEN3_ABILITY_CLOUDNINE;
    init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_SANDSTREAM;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(battle.field.weather.kind == POKEMON_WEATHER_SANDSTORM);
    assert(battle.field.weather.duration == 0);
    assert(battle.sides[0].state[0].ability_ending == 0);
    assert(battle.handler_count == 2);
    assert(battle.handlers[0].handler.descriptor.id ==
        POKEMON_GEN3_HANDLER_CLOUD_NINE_START);
    assert(battle.handlers[1].handler.descriptor.id ==
        POKEMON_GEN3_HANDLER_SAND_STREAM_START);

    PokemonChoice choices[POKEMON_SIDES] = {switch_to(1), move(0)};
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].active == 1);
    assert(battle.sides[0].state[0].ability_ending == 1);
    assert(battle.field.weather.kind == POKEMON_WEATHER_SANDSTORM);
    assert(battle.field.weather.duration == 0);
    assert(battle.handler_count == 1);
    assert(battle.handlers[0].handler.descriptor.id ==
        POKEMON_GEN3_HANDLER_CLOUD_NINE_END);

    PokemonHandlerOp programs[POKEMON_GEN3_SLICE_DATA.handler_program_count];
    memcpy(programs, POKEMON_GEN3_SLICE_DATA.handler_programs,
        POKEMON_GEN3_SLICE_DATA.handler_program_count * sizeof(programs[0]));
    PokemonData invalid_data = POKEMON_GEN3_SLICE_DATA;
    invalid_data.handler_programs = programs;
    for (size_t i = 0; i < invalid_data.handler_count; i++) {
        if (invalid_data.handlers[i].id == POKEMON_GEN3_HANDLER_CLOUD_NINE_START) {
            programs[invalid_data.handlers[i].program_offset].opcode =
                POKEMON_HANDLER_OP_RETURN_FALSE;
        }
    }
    PokemonResolvedBundle invalid_bundle = POKEMON_GEN3_OU_BUNDLE;
    invalid_bundle.data = &invalid_data;
    init.bundle = &invalid_bundle;
    PokemonBattle untouched;
    memset(&untouched, 0x5a, sizeof(untouched));
    PokemonBattle before = untouched;
    assert(pokemon_battle_init(&untouched, &init) ==
        POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&untouched, &before, sizeof(untouched)) == 0);

    /* A generated Update lifecycle failure after an ordinary action is an
     * operational failure of that step and the public transaction rolls
     * back. This also proves status-immunity cures use ordinary dispatch. */
    PokemonBattleInit runtime_init = condition_init(
        POKEMON_GEN3_SPECIES_BANETTE, POKEMON_GEN3_MOVE_SPLASH,
        POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_SPLASH);
    runtime_init.teams[0].members[0].ability_id =
        POKEMON_GEN3_ABILITY_INSOMNIA;
    PokemonBattle runtime_failure;
    assert(pokemon_battle_init(&runtime_failure, &runtime_init) == POKEMON_OK);
    memcpy(programs, POKEMON_GEN3_SLICE_DATA.handler_programs,
        POKEMON_GEN3_SLICE_DATA.handler_program_count * sizeof(programs[0]));
    invalid_data = POKEMON_GEN3_SLICE_DATA;
    invalid_data.handler_programs = programs;
    uint8_t found_insomnia_update = 0;
    for (size_t i = 0; i < invalid_data.handler_count; i++) {
        if (invalid_data.handlers[i].id ==
                POKEMON_GEN3_HANDLER_INSOMNIA_UPDATE) {
            programs[invalid_data.handlers[i].program_offset].opcode =
                POKEMON_HANDLER_OP_RETURN_FALSE;
            found_insomnia_update = 1;
        }
    }
    assert(found_insomnia_update);
    runtime_failure.data = &invalid_data;
    runtime_failure.sides[0].state[0].status.kind = POKEMON_STATUS_SLEEP;
    runtime_failure.sides[0].state[0].status.descriptor_id =
        runtime_failure.generation->condition_descriptor(
            POKEMON_OWNER_STATUS, POKEMON_STATUS_SLEEP);
    before = runtime_failure;
    PokemonChoice runtime_choices[POKEMON_SIDES] = {
        move(0), move(0),
    };
    assert(pokemon_battle_step(&runtime_failure, runtime_choices) ==
        POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&runtime_failure, &before, sizeof(runtime_failure)) == 0);
}

static void test_generated_paralysis_action_owner(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SCRATCH,
        POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_SPLASH);
    init.initial_status[0][0] = POKEMON_STATUS_PARALYSIS;
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    uint8_t generated_start_owner = 0;
    for (size_t i = 0; i < POKEMON_GEN3_SLICE_DATA.handler_count; i++) {
        const PokemonHandlerDescriptor *descriptor =
            &POKEMON_GEN3_SLICE_DATA.handlers[i];
        generated_start_owner |= descriptor->id ==
                POKEMON_GEN3_HANDLER_PARALYSIS_START &&
            descriptor->source_kind == POKEMON_HANDLER_SOURCE_CONDITION &&
            descriptor->source_id == POKEMON_GEN3_CONDITION_STATUS_PAR &&
            descriptor->event == POKEMON_HANDLER_EVENT_START;
    }
    assert(generated_start_owner);
    uint8_t saw_action = 0;
    uint8_t saw_cancellation = 0;
    for (uint16_t tail = 1; tail < 256 && !(saw_action && saw_cancellation);
         tail++) {
        init.seed[3] = tail;
        PokemonBattle battle;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        assert(draw_label_count(&battle, POKEMON_DRAW_PARALYSIS) == 1);
        uint8_t saw_owner = 0;
        for (size_t i = 0; i < battle.handler_count; i++) {
            const PokemonHandlerDescriptor *descriptor =
                &battle.handlers[i].handler.descriptor;
            if (descriptor->id !=
                    POKEMON_GEN3_HANDLER_PARALYSIS_BEFORE_MOVE) continue;
            saw_owner = 1;
            assert(descriptor->source_kind ==
                POKEMON_HANDLER_SOURCE_CONDITION);
            assert(descriptor->source_id == POKEMON_GEN3_CONDITION_STATUS_PAR);
            assert(descriptor->event == POKEMON_HANDLER_EVENT_BEFORE_MOVE);
            assert(descriptor->priority == 1);
        }
        assert(saw_owner);
        uint8_t saw_speed_owner = 0;
        for (size_t i = 0; i < battle.modifier_count; i++) {
            const PokemonHandlerDescriptor *descriptor =
                &battle.modifiers[i].handler.descriptor;
            if (descriptor->id != POKEMON_GEN3_HANDLER_PARALYSIS_SPEED) continue;
            saw_speed_owner = 1;
            assert(descriptor->source_kind == POKEMON_HANDLER_SOURCE_CONDITION);
            assert(descriptor->source_id == POKEMON_GEN3_CONDITION_STATUS_PAR);
            assert(descriptor->event == POKEMON_HANDLER_EVENT_MODIFY_SPE);
            assert(battle.modifiers[i].modifier_q12 == 1024);
        }
        assert(saw_speed_owner);
        /* Persian's 266 Speed is quartered below Magikarp's 196 before the
         * action queue is sorted. */
        assert(battle.last_queue.values[0].side == 1);
        uint32_t roll = UINT32_MAX;
        for (size_t i = 0; i < battle.draw_count; i++) {
            if (battle.draws[i].label == POKEMON_DRAW_PARALYSIS) {
                roll = battle.draws[i].result;
            }
        }
        assert(roll < 4);
        if (roll == 0) saw_cancellation = 1;
        else saw_action = 1;
    }
    assert(saw_action && saw_cancellation);

    PokemonHandlerOp programs[POKEMON_GEN3_SLICE_DATA.handler_program_count];
    memcpy(programs, POKEMON_GEN3_SLICE_DATA.handler_programs,
        sizeof(programs));
    uint8_t found_policy = 0;
    for (size_t i = 0; i < POKEMON_GEN3_SLICE_DATA.handler_count; i++) {
        const PokemonHandlerDescriptor *descriptor =
            &POKEMON_GEN3_SLICE_DATA.handlers[i];
        if (descriptor->id !=
                POKEMON_GEN3_HANDLER_PARALYSIS_BEFORE_MOVE) continue;
        programs[descriptor->program_offset].argument =
            (POKEMON_DRAW_PARALYSIS << 24) | (1u << 16);
        found_policy = 1;
    }
    assert(found_policy);
    PokemonData invalid_data = POKEMON_GEN3_SLICE_DATA;
    invalid_data.handler_programs = programs;
    PokemonResolvedBundle invalid_bundle = POKEMON_GEN3_OU_BUNDLE;
    invalid_bundle.data = &invalid_data;
    init.bundle = &invalid_bundle;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    PokemonBattle before = battle;
    assert(pokemon_battle_step(&battle, choices) ==
        POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&battle, &before, sizeof(battle)) == 0);
}

static void test_generated_intimidate_start_family(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SPLASH,
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[0].members[0].ability_id = POKEMON_GEN3_ABILITY_INTIMIDATE;
    init.teams[0].members[0].stats[5] = 400;
    init.teams[1].members[0].stats[5] = 100;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(battle.sides[1].state[0].boosts[POKEMON_STAT_ATK] == -1);

    /* Both initial active slots are installed before either per-entrant
     * Gen 3 runSwitch action executes, so speed cannot erase the first drop. */
    init.teams[0].members[0].stats[5] = 100;
    init.teams[1].members[0].stats[5] = 400;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(battle.sides[1].state[0].boosts[POKEMON_STAT_ATK] == -1);

    init.teams[0].members[0].ability_id = 0;
    init.teams[0].members[1].ability_id = POKEMON_GEN3_ABILITY_INTIMIDATE;
    PokemonChoice choices[POKEMON_SIDES] = {switch_to(1), move(0)};
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].state[0].boosts[POKEMON_STAT_ATK] == -1);
    assert(handler_event_count(&battle, POKEMON_HANDLER_EVENT_START) == 1);

    /* The directed transaction retains the entering holder as source, so
     * ordinary hostile-source TryBoost filters remain authoritative. */
    init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_CLEARBODY;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].state[0].boosts[POKEMON_STAT_ATK] == 0);
    assert(handler_event_count(&battle, POKEMON_HANDLER_EVENT_TRY_BOOST) == 1);

    /* The resolved Gen 3 override excludes Substitute holders before the
     * ChangeBoost/TryBoost transaction rather than filtering it afterward. */
    init.teams[1].members[0].ability_id = 0;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    PokemonMutable *target = &battle.sides[1].state[0];
    target->volatiles[0] = (PokemonVolatileState){
        .kind = POKEMON_VOLATILE_SUBSTITUTE,
        .descriptor_id = POKEMON_GEN3_CONDITION_VOLATILE_SUBSTITUTE,
        .state_generation = 1,
        .effect_order = ++battle.next_holder_effect_order,
        .payload.substitute.hp = 1,
    };
    target->volatile_count = 1;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(target->boosts[POKEMON_STAT_ATK] == 0);
    assert(handler_event_count(&battle, POKEMON_HANDLER_EVENT_CHANGE_BOOST) == 0);
    assert(handler_event_count(&battle, POKEMON_HANDLER_EVENT_TRY_BOOST) == 0);
}

static void test_trace_replaces_ability_without_starting_copy(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_PORYGON2, POKEMON_GEN3_MOVE_SPLASH,
        POKEMON_GEN3_SPECIES_MAWILE, POKEMON_GEN3_MOVE_SPLASH);
    init.team_sizes[0] = 2;
    init.teams[0].members[0].ability_id = POKEMON_GEN3_ABILITY_TRACE;
    init.teams[0].members[1] = make_set(
        POKEMON_GEN3_SPECIES_ALAKAZAM, POKEMON_GEN3_MOVE_SPLASH,
        250, 100, 100, 350, 200, 320);
    init.teams[0].members[1].ability_id = POKEMON_GEN3_ABILITY_INNERFOCUS;
    init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_INTIMIDATE;

    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(battle.sides[0].sets[0].ability_id == POKEMON_GEN3_ABILITY_TRACE);
    assert(battle.sides[0].state[0].ability_id ==
        POKEMON_GEN3_ABILITY_INTIMIDATE);
    assert(battle.sides[1].state[0].boosts[POKEMON_STAT_ATK] == 0);
    assert(draw_label_count(&battle, POKEMON_DRAW_ABILITY_TARGET) == 1);
    assert(battle.draws[0].upper_bound == 1 && battle.draws[0].result == 0);
    assert(battle.handlers[0].handler.descriptor.id ==
        POKEMON_GEN3_HANDLER_TRACE_START);

    PokemonChoice leave[POKEMON_SIDES] = {switch_to(1), move(0)};
    assert(pokemon_battle_step(&battle, leave) == POKEMON_OK);
    assert(battle.sides[0].state[0].ability_id == POKEMON_GEN3_ABILITY_TRACE);
    assert(draw_label_count(&battle, POKEMON_DRAW_ABILITY_TARGET) == 0);

    PokemonChoice return_trace[POKEMON_SIDES] = {switch_to(0), move(0)};
    assert(pokemon_battle_step(&battle, return_trace) == POKEMON_OK);
    assert(battle.sides[0].state[0].ability_id ==
        POKEMON_GEN3_ABILITY_INTIMIDATE);
    assert(battle.sides[1].state[0].boosts[POKEMON_STAT_ATK] == 0);
    assert(draw_label_count(&battle, POKEMON_DRAW_ABILITY_TARGET) == 1);
    assert(pokemon_battle_check_invariants(&battle));
}

static void test_alternate_plugin_boundary_and_behavior(void) {
    PokemonBattleInit ordinary_init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_BONERUSH,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SPLASH);
    ordinary_init.teams[0].members[0].ability_id = POKEMON_GEN3_ABILITY_OWNTEMPO;
    ordinary_init.seed[3] = 36;
    ordinary_init.teams[1].members[0].stats[0] = 5000;
    ordinary_init.teams[1].members[0].stats[2] = 1000;
    PokemonBattleInit proof_init = ordinary_init;
    pokemon_test_plugin_rebind(&proof_init);
    PokemonBattle ordinary;
    PokemonBattle proof;
    assert((proof_init.bundle->capabilities &
        POKEMON_CAP_CONDITION(POKEMON_RULE_CONDITION_FOCUS_ENERGY)) == 0);
    assert(proof_init.bundle->rules->condition_rule_count + 2 ==
        POKEMON_GEN3_RULES.condition_rule_count);
    assert(pokemon_battle_init(&ordinary, &ordinary_init) == POKEMON_OK);
    assert(pokemon_battle_init(&proof, &proof_init) == POKEMON_OK);
    PokemonDamageRequest damage_request = {
        .mode = POKEMON_DAMAGE_MODE_ORDINARY_MOVE,
        .source = {POKEMON_ENTITY_POKEMON, 0, 0},
        .target = {POKEMON_ENTITY_POKEMON, 1, 0},
        .move = generated_move(POKEMON_GEN3_MOVE_STRENGTH),
        .critical = 0,
    };
    PokemonCalculatedDamage ordinary_damage;
    PokemonCalculatedDamage proof_damage;
    assert(pokemon_calculate_damage(&ordinary, &damage_request,
        &ordinary_damage) == POKEMON_OK);
    assert(pokemon_calculate_damage(&proof, &damage_request,
        &proof_damage) == POKEMON_OK);
    assert(ordinary_damage.damage != proof_damage.damage);
    assert(pokemon_battle_init(&ordinary, &ordinary_init) == POKEMON_OK);
    assert(pokemon_battle_init(&proof, &proof_init) == POKEMON_OK);
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_step(&ordinary, choices) == POKEMON_OK);
    assert(pokemon_battle_step(&proof, choices) == POKEMON_OK);
    const PokemonHitTrace *proof_result = NULL;
    for (size_t i = 0; i < proof.hit_trace_count; i++) {
        if (proof.hit_traces[i].kind == POKEMON_HIT_RESULT) {
            proof_result = &proof.hit_traces[i];
        } else if (proof.hit_traces[i].kind == POKEMON_HIT_CONNECTED) {
            assert(proof.hit_traces[i].critical == 1);
        }
    }
    assert(proof_result != NULL && proof_result->requested_hits == 4);
    assert(proof.generation->fraction(5, 1, 2) == 3);
    assert(ordinary.generation->fraction(5, 1, 2) == 2);

    PokemonBattleInit duration_init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_REFLECT,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SPLASH);
    pokemon_test_plugin_rebind(&duration_init);
    assert(pokemon_battle_init(&proof, &duration_init) == POKEMON_OK);
    assert(pokemon_battle_step(&proof, choices) == POKEMON_OK);
    assert(proof.sides[0].condition_count == 1);
    assert(proof.sides[0].conditions[0].duration == 6);

    PokemonBattle untouched;
    memset(&untouched, 0x5a, sizeof(untouched));
    PokemonBattle before = untouched;
    const PokemonResolvedBundle *base = duration_init.bundle;
    PokemonResolvedBundle mixed;
    PokemonGeneration foreign_rules;
    PokemonData foreign_data;
    PokemonFormat foreign_format;
    PokemonFormatPolicy foreign_policy;
    PokemonFormatManifest foreign_manifest;
#define ASSERT_PLUGIN_REJECTS() do { \
    duration_init.bundle = &mixed; \
    assert(pokemon_battle_init(&untouched, &duration_init) == \
        POKEMON_INVALID_CONFIGURATION); \
    assert(memcmp(&untouched, &before, sizeof(untouched)) == 0); \
} while (0)

    mixed = *base; mixed.plugin_fingerprint = 0; ASSERT_PLUGIN_REJECTS();
    mixed = *base; mixed.capability_version++; ASSERT_PLUGIN_REJECTS();
    mixed = *base; mixed.capabilities ^= POKEMON_CAP_CONDITION(
        POKEMON_RULE_CONDITION_REFLECT); ASSERT_PLUGIN_REJECTS();

#define ASSERT_FOREIGN_COMPONENT(member, object) do { \
    mixed = *base; object = *base->member; \
    object.plugin_fingerprint = POKEMON_GEN3_PLUGIN_FINGERPRINT; \
    mixed.member = &object; ASSERT_PLUGIN_REJECTS(); \
    mixed = *base; object = *base->member; \
    object.capabilities ^= POKEMON_CAP_CONDITION(POKEMON_RULE_CONDITION_REFLECT); \
    mixed.member = &object; ASSERT_PLUGIN_REJECTS(); \
} while (0)
    ASSERT_FOREIGN_COMPONENT(rules, foreign_rules);
    ASSERT_FOREIGN_COMPONENT(data, foreign_data);
    ASSERT_FOREIGN_COMPONENT(runtime_format, foreign_format);
    ASSERT_FOREIGN_COMPONENT(policy, foreign_policy);
#undef ASSERT_FOREIGN_COMPONENT

    /* Keep the policy link coherent so these failures isolate manifest
     * identity/capability rather than the pointer-pair invariant. */
    mixed = *base; foreign_manifest = *base->manifest;
    foreign_policy = *base->policy;
    foreign_manifest.plugin_fingerprint = POKEMON_GEN3_PLUGIN_FINGERPRINT;
    foreign_policy.manifest = &foreign_manifest;
    mixed.manifest = &foreign_manifest; mixed.policy = &foreign_policy;
    ASSERT_PLUGIN_REJECTS();
    mixed = *base; foreign_manifest = *base->manifest;
    foreign_policy = *base->policy;
    foreign_manifest.capabilities ^= POKEMON_CAP_CONDITION(
        POKEMON_RULE_CONDITION_REFLECT);
    foreign_policy.manifest = &foreign_manifest;
    mixed.manifest = &foreign_manifest; mixed.policy = &foreign_policy;
    ASSERT_PLUGIN_REJECTS();

    /* These bundles remain internally coherent; rejection therefore proves
     * subsystem capability/table validation rather than identity equality. */
#define ASSERT_COHERENT_MASK_REJECTS(mask_value) do { \
    uint64_t test_mask = (mask_value); \
    mixed = *base; foreign_rules = *base->rules; foreign_data = *base->data; \
    foreign_format = *base->runtime_format; foreign_policy = *base->policy; \
    foreign_manifest = *base->manifest; \
    mixed.capabilities = test_mask; foreign_rules.capabilities = test_mask; \
    foreign_data.capabilities = test_mask; foreign_format.capabilities = test_mask; \
    foreign_policy.capabilities = test_mask; foreign_manifest.capabilities = test_mask; \
    foreign_policy.manifest = &foreign_manifest; \
    mixed.rules = &foreign_rules; mixed.data = &foreign_data; \
    mixed.runtime_format = &foreign_format; mixed.policy = &foreign_policy; \
    mixed.manifest = &foreign_manifest; ASSERT_PLUGIN_REJECTS(); \
} while (0)
    ASSERT_COHERENT_MASK_REJECTS(
        base->capabilities & ~POKEMON_CAP_HANDLER_PROGRAMS);
    ASSERT_COHERENT_MASK_REJECTS(
        base->capabilities & ~POKEMON_CAP_EFFECT_PROGRAMS);
    ASSERT_COHERENT_MASK_REJECTS(
        base->capabilities & ~POKEMON_CAP_EVENT_INTERPRETER);
    ASSERT_COHERENT_MASK_REJECTS(
        base->capabilities & ~POKEMON_CAP_FORMAT_POLICY);
    ASSERT_COHERENT_MASK_REJECTS(base->capabilities | (UINT64_C(1) << 63));
#undef ASSERT_COHERENT_MASK_REJECTS
#undef ASSERT_PLUGIN_REJECTS
}

static void test_partial_trap_condition_programs(void) {
    static const uint16_t moves[] = {
        POKEMON_GEN3_MOVE_BIND, POKEMON_GEN3_MOVE_CLAMP,
        POKEMON_GEN3_MOVE_FIRESPIN, POKEMON_GEN3_MOVE_WHIRLPOOL,
        POKEMON_GEN3_MOVE_WRAP, POKEMON_GEN3_MOVE_SANDTOMB,
    };
    for (size_t i = 0; i < sizeof(moves) / sizeof(moves[0]); i++) {
        const PokemonMoveData *move_data = NULL;
        for (size_t move_index = 0;
             move_index < POKEMON_GEN3_SLICE_DATA.move_count; move_index++) {
            if (POKEMON_GEN3_SLICE_DATA.moves[move_index].id == moves[i]) {
                move_data = &POKEMON_GEN3_SLICE_DATA.moves[move_index];
                break;
            }
        }
        assert(move_data != NULL && move_data->effect_count == 1);
        const PokemonEffectOp *effect = &POKEMON_GEN3_SLICE_DATA.effects[
            move_data->effect_offset];
        assert(effect->kind == POKEMON_EFFECT_ADD_VOLATILE);
        assert(effect->argument == POKEMON_VOLATILE_PARTIALLY_TRAPPED);
        assert(effect->target == POKEMON_EFFECT_TARGET_MOVE_TARGET);
    }

    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_BIND,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[1].members[0].stats[0] = 640;
    init.teams[1].members[0].stats[2] = 300;
    init.initial_hp[1][0] = 640;
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    PokemonBattle battle;
    int trapped = -1;
    for (uint16_t tail = 1; tail < 4096 && trapped < 0; tail++) {
        init.seed[3] = tail;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        trapped = test_volatile_index(
            &battle.sides[1].state[0], POKEMON_VOLATILE_PARTIALLY_TRAPPED);
    }
    assert(trapped >= 0);
    assert(draw_label_count(
        &battle, POKEMON_DRAW_PARTIALLY_TRAPPED_DURATION) == 1);
    assert(battle.sides[1].state[0].volatiles[trapped].duration >= 2);
    assert(battle.sides[1].state[0].volatiles[trapped].duration <= 5);
    assert(battle.sides[1].state[0].volatiles[trapped].source.side == 0);
    assert(battle.request.legal_moves[1] != 0);
    assert(battle.request.legal_switches[1] == 0);

    /* Residual damage is one sixteenth of base max HP, minimum one. */
    battle.sides[1].state[0].hp = 640;
    test_replace_base_move(
        &battle, 0, 0, 0, POKEMON_GEN3_MOVE_SPLASH, 64);
    choices[0] = move(0);
    choices[1] = move(0);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].state[0].hp == 600);
    assert(test_volatile_index(
        &battle.sides[1].state[0], POKEMON_VOLATILE_PARTIALLY_TRAPPED) >= 0);

    /* A fainted source is no longer a live owner. Forced replacement resumes
     * residual work, which removes the volatile without a final damage tick. */
    battle.sides[0].state[0].hp = 1;
    test_replace_base_move(
        &battle, 1, 0, 0, POKEMON_GEN3_MOVE_QUICKATTACK, 48);
    battle.sides[1].sets[0].stats[1] = 400;
    battle.sides[1].state[0].stored_stats[0] = 400;
    uint16_t hp_before_source_faint = battle.sides[1].state[0].hp;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].fainted);
    assert(battle.request.kind[0] == POKEMON_REQUEST_SWITCH);
    assert(battle.request.kind[1] == POKEMON_REQUEST_WAIT);
    assert(test_volatile_index(
        &battle.sides[1].state[0], POKEMON_VOLATILE_PARTIALLY_TRAPPED) >= 0);
    PokemonChoice replacement[POKEMON_SIDES] = {
        switch_to(1), wait_choice(),
    };
    assert(pokemon_battle_step(&battle, replacement) == POKEMON_OK);
    assert(test_volatile_index(
        &battle.sides[1].state[0], POKEMON_VOLATILE_PARTIALLY_TRAPPED) < 0);
    assert(battle.sides[1].state[0].hp == hp_before_source_faint);
    assert(battle.request.legal_switches[1] != 0);
    assert(pokemon_battle_check_invariants(&battle));

    /* Rebuild to exercise source switching independently of source fainting. */
    choices[0] = move(0);
    choices[1] = move(0);
    trapped = -1;
    for (uint16_t tail = 1; tail < 4096 && trapped < 0; tail++) {
        init.seed[3] = tail;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        trapped = test_volatile_index(
            &battle.sides[1].state[0], POKEMON_VOLATILE_PARTIALLY_TRAPPED);
    }
    assert(trapped >= 0);

    uint16_t hp_before = battle.sides[1].state[0].hp;
    choices[0] = switch_to(1);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(test_volatile_index(
        &battle.sides[1].state[0], POKEMON_VOLATILE_PARTIALLY_TRAPPED) < 0);
    assert(battle.sides[1].state[0].hp == hp_before);
    assert(battle.request.legal_switches[1] != 0);

    const PokemonMoveData *rapid_spin = generated_move(
        POKEMON_GEN3_MOVE_RAPIDSPIN);
    assert(rapid_spin != NULL && rapid_spin->effect_count == 3);
    const PokemonEffectOp *cleanups = &POKEMON_GEN3_SLICE_DATA.effects[
        rapid_spin->effect_offset];
    assert(cleanups[0].kind == POKEMON_EFFECT_REMOVE_VOLATILE);
    assert(cleanups[0].argument == POKEMON_VOLATILE_LEECH_SEED);
    assert(cleanups[1].kind == POKEMON_EFFECT_REMOVE_SIDE_CONDITION);
    assert(cleanups[1].argument == POKEMON_GEN3_CONDITION_SIDE_SPIKES);
    assert(cleanups[2].kind == POKEMON_EFFECT_REMOVE_VOLATILE);
    assert(cleanups[2].argument == POKEMON_VOLATILE_PARTIALLY_TRAPPED);
    for (size_t i = 0; i < rapid_spin->effect_count; i++) {
        assert(cleanups[i].phase == POKEMON_EFFECT_PHASE_AFTER_HIT_CALLBACK);
        assert(cleanups[i].target == POKEMON_EFFECT_TARGET_USER);
    }
    init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_RAPIDSPIN,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SPLASH);
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    PokemonMutable *spinner = &battle.sides[0].state[0];
    spinner->volatiles[spinner->volatile_count++] = (PokemonVolatileState){
        .kind = POKEMON_VOLATILE_PARTIALLY_TRAPPED,
        .descriptor_id = POKEMON_GEN3_CONDITION_VOLATILE_PARTIALLYTRAPPED,
        .duration = 4, .source = {POKEMON_ENTITY_POKEMON, 1, 0},
        .source_effect = {POKEMON_SOURCE_EFFECT_MOVE, POKEMON_GEN3_MOVE_BIND},
        .state_generation = 1,
        .effect_order = ++battle.next_holder_effect_order,
    };
    choices[0] = move(0);
    choices[1] = move(0);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(test_volatile_index(
        spinner, POKEMON_VOLATILE_PARTIALLY_TRAPPED) < 0);
    const PokemonConditionTrace *removed = &battle.condition_traces[
        battle.condition_trace_count - 1];
    assert(removed->operation == POKEMON_CONDITION_REMOVE);
    assert(removed->reason == POKEMON_CONDITION_REASON_MOVE);
    assert(removed->condition_id == POKEMON_VOLATILE_PARTIALLY_TRAPPED);
    assert(pokemon_battle_check_invariants(&battle));
}

static void test_source_linked_trap_family(void) {
	static const uint16_t moves[] = {
		POKEMON_GEN3_MOVE_BLOCK, POKEMON_GEN3_MOVE_MEANLOOK,
		POKEMON_GEN3_MOVE_SPIDERWEB,
	};
	for (size_t i = 0; i < sizeof(moves) / sizeof(moves[0]); i++) {
		const PokemonMoveData *move_data = generated_move(moves[i]);
		assert(move_data != NULL && move_data->accuracy.kind ==
			POKEMON_ACCURACY_ALWAYS && move_data->effect_count == 0);
	}

	PokemonBattleInit init = condition_init(
		POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_BLOCK,
		POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SPLASH);
	init.teams[0].members[0].ability_id = POKEMON_GEN3_ABILITY_OWNTEMPO;
	init.team_sizes[0] = 2;
	init.team_sizes[1] = 2;
	init.teams[0].members[1] = make_set(
		POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SPLASH,
		250, 100, 100, 100, 100, 100);
	init.teams[1].members[1] = make_set(
		POKEMON_GEN3_SPECIES_STARMIE, POKEMON_GEN3_MOVE_SPLASH,
		250, 100, 100, 100, 100, 100);
	PokemonChoice first[POKEMON_SIDES] = {move(0), move(0)};
	PokemonBattle battle;
	assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
	uint16_t effect_order_before = battle.next_holder_effect_order;
	assert(pokemon_battle_step(&battle, first) == POKEMON_OK);
	int trapped = test_volatile_index(
		&battle.sides[1].state[0], POKEMON_VOLATILE_TRAPPED);
	assert(trapped >= 0);
	const PokemonVolatileState *condition =
		&battle.sides[1].state[0].volatiles[trapped];
	assert(condition->source.side == 0 && condition->source.slot == 0);
	assert(condition->source_effect.kind == POKEMON_SOURCE_EFFECT_MOVE);
	assert(condition->source_effect.id == POKEMON_GEN3_MOVE_BLOCK);
	assert(condition->linked_source_state_generation == 1);
	assert(condition->linked_source_effect_order ==
		condition->effect_order + 1);
	assert(battle.next_holder_effect_order == effect_order_before + 2);
	assert(battle.request.legal_switches[1] == 0);
	assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 0);
	assert(handler_event_count(
		&battle, POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK) == 1);
	assert(handler_event_count(&battle, POKEMON_HANDLER_EVENT_START) == 1);
	assert(handler_event_count(
		&battle, POKEMON_HANDLER_EVENT_TRY_ADD_VOLATILE) == 1);
	assert(handler_event_count(
		&battle, POKEMON_HANDLER_EVENT_TRAP_POKEMON) >= 1);

	/* Duplicate installation returns before the hidden counterpart boundary:
	 * it neither relinks provenance nor consumes another effect order. */
	uint16_t visible_order = condition->effect_order;
	uint16_t linked_order = condition->linked_source_effect_order;
	assert(pokemon_battle_step(&battle, first) == POKEMON_OK);
	trapped = test_volatile_index(
		&battle.sides[1].state[0], POKEMON_VOLATILE_TRAPPED);
	assert(trapped >= 0);
	condition = &battle.sides[1].state[0].volatiles[trapped];
	assert(condition->effect_order == visible_order);
	assert(condition->linked_source_effect_order == linked_order);
	assert(battle.next_holder_effect_order == effect_order_before + 2);
	assert(handler_event_count(
		&battle, POKEMON_HANDLER_EVENT_TRY_ADD_VOLATILE) == 0);

	/* The generated source-linked policy removes the target endpoint when its
	 * source clears volatile state on an ordinary switch. */
	PokemonChoice release[POKEMON_SIDES] = {switch_to(1), move(0)};
	assert(pokemon_battle_step(&battle, release) == POKEMON_OK);
	assert(test_volatile_index(
		&battle.sides[1].state[0], POKEMON_VOLATILE_TRAPPED) < 0);
	assert(battle.request.legal_switches[1] != 0);
	assert(pokemon_battle_check_invariants(&battle));
}

static void test_pre_hit_self_faint_and_fifo_drain(void) {
    const PokemonMoveData *explosion = NULL;
    const PokemonMoveData *self_destruct = NULL;
    for (size_t i = 0; i < POKEMON_GEN3_SLICE_DATA.move_count; i++) {
        const PokemonMoveData *move_data = &POKEMON_GEN3_SLICE_DATA.moves[i];
        if (move_data->id == POKEMON_GEN3_MOVE_EXPLOSION) explosion = move_data;
        if (move_data->id == POKEMON_GEN3_MOVE_SELFDESTRUCT) {
            self_destruct = move_data;
        }
    }
    assert(explosion != NULL && self_destruct != NULL);
    assert(explosion->self_faint_timing == POKEMON_SELF_FAINT_PRE_HIT);
    assert(self_destruct->self_faint_timing == POKEMON_SELF_FAINT_PRE_HIT);
    assert(explosion->defense_policy == POKEMON_DEFENSE_POLICY_SELF_DESTRUCT);
    assert(self_destruct->defense_policy ==
        POKEMON_DEFENSE_POLICY_SELF_DESTRUCT);

    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SNORLAX, POKEMON_GEN3_MOVE_EXPLOSION,
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_PROTECT);
    uint16_t protected_hp = init.teams[1].members[0].stats[0];
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].fainted);
    assert(!battle.sides[0].state[0].faint_queued && battle.faint_count == 0);
    assert(battle.sides[1].state[0].hp == protected_hp);
    assert(event_kind_count(&battle, POKEMON_EVENT_BLOCK) == 1);
    assert(draw_label_count(&battle, POKEMON_DRAW_CRITICAL) == 0);
    assert(draw_label_count(&battle, POKEMON_DRAW_DAMAGE_ROLL) == 0);
    assert(battle.request.kind[0] == POKEMON_REQUEST_SWITCH);
    assert(pokemon_battle_check_invariants(&battle));

    init = condition_init(
        POKEMON_GEN3_SPECIES_SNORLAX, POKEMON_GEN3_MOVE_SELFDESTRUCT,
        POKEMON_GEN3_SPECIES_DUSCLOPS, POKEMON_GEN3_MOVE_SPLASH);
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].fainted);
    assert(event_kind_count(&battle, POKEMON_EVENT_IMMUNE) == 1);
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 1);
    assert(draw_label_count(&battle, POKEMON_DRAW_CRITICAL) == 0);
    assert(pokemon_battle_check_invariants(&battle));

    /* Gen 3 faint processing truncates every remaining queued action. A
     * faster Explosion into an immune Ghost therefore prevents the slower
     * Substitute from spending PP or installing its volatile, then suspends
     * the turn at forced replacement. */
    init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_EXPLOSION,
        POKEMON_GEN3_SPECIES_BANETTE, POKEMON_GEN3_MOVE_SUBSTITUTE);
    init.team_sizes[0] = 2;
    init.team_sizes[1] = 1;
    init.teams[0].members[1] = make_set(
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SPLASH,
        651, 56, 56, 186, 306, 146);
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    uint16_t target_hp = battle.sides[1].state[0].hp;
    uint8_t substitute_pp = battle.sides[1].state[0].pp[0];
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.last_queue.count == 2);
    assert(battle.last_queue.values[0].side == 0);
    assert(battle.last_queue.values[0].selected_move_id ==
        POKEMON_GEN3_MOVE_EXPLOSION);
    assert(battle.last_queue.values[1].side == 1);
    assert(battle.last_queue.values[1].selected_move_id ==
        POKEMON_GEN3_MOVE_SUBSTITUTE);
    assert(battle.queue.count == 0);
    assert(battle.sides[1].state[0].hp == target_hp);
    assert(battle.sides[1].state[0].pp[0] == substitute_pp);
    assert(test_volatile_index(
        &battle.sides[1].state[0], POKEMON_VOLATILE_SUBSTITUTE) < 0);
    assert(battle.phase == POKEMON_PHASE_FORCED_REPLACEMENT);
    assert(battle.turn_suspended == POKEMON_TURN_SUSPENDED_BEFORE_RESIDUAL);
    assert(battle.request.kind[0] == POKEMON_REQUEST_SWITCH);
    assert(battle.request.kind[1] == POKEMON_REQUEST_WAIT);
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 1);
    assert(draw_label_count(&battle, POKEMON_DRAW_CRITICAL) == 0);
    assert(draw_label_count(&battle, POKEMON_DRAW_DAMAGE_ROLL) == 0);
    PokemonChoice replacement[POKEMON_SIDES] = {switch_to(1), wait_choice()};
    assert(pokemon_battle_step(&battle, replacement) == POKEMON_OK);
    assert(battle.sides[1].state[0].hp == target_hp);
    assert(battle.sides[1].state[0].pp[0] == substitute_pp);
    assert(test_volatile_index(
        &battle.sides[1].state[0], POKEMON_VOLATILE_SUBSTITUTE) < 0);
    assert(pokemon_battle_check_invariants(&battle));

    init = condition_init(
        POKEMON_GEN3_SPECIES_SNORLAX, POKEMON_GEN3_MOVE_EXPLOSION,
        POKEMON_GEN3_SPECIES_MACHOP, POKEMON_GEN3_MOVE_SPLASH);
    init.team_sizes[0] = 1;
    init.team_sizes[1] = 1;
    init.teams[1].members[0].stats[0] = 1;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.terminal && battle.winner == -1);
    assert(event_kind_count(&battle, POKEMON_EVENT_FAINT) == 2);
    assert(event_kind_count(&battle, POKEMON_EVENT_TIE) == 1);
    assert(battle.events[battle.event_count - 3].kind == POKEMON_EVENT_FAINT);
    assert(battle.events[battle.event_count - 3].side == 0);
    assert(battle.events[battle.event_count - 2].kind == POKEMON_EVENT_FAINT);
    assert(battle.events[battle.event_count - 2].side == 1);
    assert(battle.events[battle.event_count - 1].kind == POKEMON_EVENT_TIE);
    assert(pokemon_battle_check_invariants(&battle));
}

static void test_global_try_move_handler_blocks_self_faint_family(void) {
    enum { TEST_DAMP_ABILITY = 60000, TEST_DAMP_HANDLER = 60001 };
    PokemonAbilityData ability = {
        .id = TEST_DAMP_ABILITY, .handler_offset = 0, .handler_count = 1,
    };
    PokemonHandlerDescriptor handler = {
        .event = POKEMON_HANDLER_EVENT_TRY_MOVE,
        .id = TEST_DAMP_HANDLER,
        .source_kind = POKEMON_HANDLER_SOURCE_ABILITY,
        .source_id = TEST_DAMP_ABILITY,
        .program_offset = 0, .program_count = 2,
        .scope = POKEMON_HANDLER_SCOPE_ANY,
        .route = POKEMON_HANDLER_ROUTE_OWNER,
        .raw_hook = "onAnyTryMove",
    };
    PokemonHandlerOp programs[] = {
        {POKEMON_HANDLER_OP_GUARD_MOVE_SELF_FAINT_TIMING,
            POKEMON_SELF_FAINT_PRE_HIT},
        {POKEMON_HANDLER_OP_RETURN_FALSE, 0},
    };
    PokemonOwnerBindingIndex binding = {
        .owner_kind = POKEMON_OWNER_ABILITY,
        .owner_id = TEST_DAMP_ABILITY,
        .event = POKEMON_HANDLER_EVENT_TRY_MOVE,
        .scope = POKEMON_HANDLER_SCOPE_ANY,
        .route = POKEMON_HANDLER_ROUTE_OWNER,
        .binding_offset = 0, .binding_count = 1,
    };
    PokemonMoveData moves[POKEMON_GEN3_MOVE_COUNT];
    memcpy(moves, POKEMON_GEN3_SLICE_DATA.moves, sizeof(moves));
    for (size_t i = 0; i < POKEMON_GEN3_MOVE_COUNT; i++) {
        moves[i].call_pool_id = 0;
    }

    PokemonData data = POKEMON_GEN3_SLICE_DATA;
    data.moves = moves;
    data.abilities = &ability;
    data.ability_count = 1;
    data.handlers = &handler;
    data.handler_count = 1;
    data.handler_programs = programs;
    data.handler_program_count = 2;
    data.owner_binding_index = &binding;
    data.owner_binding_index_count = 1;
    data.move_call_pools = NULL;
    data.move_call_pool_count = 0;
    data.move_call_pool_candidates = NULL;
    data.move_call_pool_candidate_count = 0;
    data.constructed_hit_templates = NULL;
    data.constructed_hit_template_count = 0;
    data.move_pre_use_programs = NULL;
    data.move_pre_use_program_count = 0;
    PokemonResolvedBundle bundle = POKEMON_GEN3_OU_BUNDLE;
    PokemonFormatPolicy policy = *bundle.policy;
    policy.status_clauses = NULL;
    policy.status_clause_count = 0;
    bundle.policy = &policy;
    bundle.data = &data;

    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SNORLAX, POKEMON_GEN3_MOVE_EXPLOSION,
        POKEMON_GEN3_SPECIES_VAPOREON, POKEMON_GEN3_MOVE_SPLASH);
    init.bundle = &bundle;
    init.teams[0].members[0].ability_id = 0;
    init.teams[1].members[0].ability_id = TEST_DAMP_ABILITY;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    uint16_t source_hp = battle.sides[0].state[0].hp;
    uint16_t target_hp = battle.sides[1].state[0].hp;
    uint8_t pp = battle.sides[0].state[0].pp[0];
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].hp == source_hp);
    assert(battle.sides[1].state[0].hp == target_hp);
    assert(battle.sides[0].state[0].pp[0] == pp - 1);
    assert(battle.handler_count >= 1);
    assert(battle.handlers[0].handler.descriptor.id == TEST_DAMP_HANDLER);
    assert(battle.handlers[0].handler.holder_side == 1);
    assert(battle.handlers[0].invoked);
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 0);
    assert(draw_label_count(&battle, POKEMON_DRAW_CRITICAL) == 0);
    assert(draw_label_count(&battle, POKEMON_DRAW_DAMAGE_ROLL) == 0);

    /* onAnyTryMove applies when the move user itself owns the ability. */
    init.teams[0].members[0].ability_id = TEST_DAMP_ABILITY;
    init.teams[1].members[0].ability_id = 0;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(!battle.sides[0].state[0].fainted);
    assert(battle.handlers[0].handler.holder_side == 0);

    /* Membership follows descriptor semantics, not an Explosion ID. */
    for (size_t i = 0; i < POKEMON_GEN3_MOVE_COUNT; i++) {
        if (moves[i].id == POKEMON_GEN3_MOVE_TACKLE) {
            moves[i].self_faint_timing = POKEMON_SELF_FAINT_PRE_HIT;
            break;
        }
    }
    init.teams[0].members[0].move_ids[0] = POKEMON_GEN3_MOVE_TACKLE;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    target_hp = battle.sides[1].state[0].hp;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(!battle.sides[0].state[0].fainted);
    assert(battle.sides[1].state[0].hp == target_hp);

    /* An ordinary move passes the handler and reaches the hit pipeline. */
    for (size_t i = 0; i < POKEMON_GEN3_MOVE_COUNT; i++) {
        if (moves[i].id == POKEMON_GEN3_MOVE_TACKLE) {
            moves[i].self_faint_timing = POKEMON_SELF_FAINT_NONE;
            break;
        }
    }
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    target_hp = battle.sides[1].state[0].hp;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].state[0].hp < target_hp);
}

static void test_if_hit_self_faint_family(void) {
    const PokemonMoveData *memento =
        &POKEMON_GEN3_SLICE_DATA.moves[POKEMON_GEN3_MOVE_MEMENTO - 1];
    assert(memento->id == POKEMON_GEN3_MOVE_MEMENTO);
    assert(memento->self_faint_timing == POKEMON_SELF_FAINT_IF_HIT);
    assert(memento->defense_policy == POKEMON_DEFENSE_POLICY_STANDARD);
    assert(memento->accuracy.kind == POKEMON_ACCURACY_ALWAYS);

    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_ALAKAZAM, POKEMON_GEN3_MOVE_MEMENTO,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SPLASH);
    init.team_sizes[0] = 2;
    init.teams[0].members[1] = make_set(
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SPLASH,
        300, 200, 150, 150, 150, 200);
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].fainted);
    assert(battle.sides[1].state[0].boosts[POKEMON_STAT_ATK] == -2);
    assert(battle.sides[1].state[0].boosts[POKEMON_STAT_SPA] == -2);
    assert(battle.request.kind[0] == POKEMON_REQUEST_SWITCH);
    assert(battle.request.kind[1] == POKEMON_REQUEST_WAIT);
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 0);
    assert(pokemon_battle_check_invariants(&battle));

    /* A target-side boost filter does not turn a successful hit into a
     * failure: Memento still pays its descriptor-owned self-faint. */
    init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_CLEARBODY;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].fainted);
    assert(battle.sides[1].state[0].boosts[POKEMON_STAT_ATK] == 0);
    assert(battle.sides[1].state[0].boosts[POKEMON_STAT_SPA] == 0);

    /* A successful hit is also independent of whether either requested
     * stage can move farther. */
    init.teams[1].members[0].ability_id = 0;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    battle.sides[1].state[0].boosts[POKEMON_STAT_ATK] = -6;
    battle.sides[1].state[0].boosts[POKEMON_STAT_SPA] = -6;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].fainted);
    assert(battle.sides[1].state[0].boosts[POKEMON_STAT_ATK] == -6);
    assert(battle.sides[1].state[0].boosts[POKEMON_STAT_SPA] == -6);

    /* Protect cancels the hit before the IF_HIT payment boundary. */
    init.teams[1].members[0].move_ids[0] = POKEMON_GEN3_MOVE_PROTECT;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    uint16_t user_hp = battle.sides[0].state[0].hp;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].hp == user_hp);
    assert(!battle.sides[0].state[0].fainted);
    assert(event_kind_count(&battle, POKEMON_EVENT_BLOCK) == 1);

    /* The target's post-hit item transaction occurs before faint drain. */
    init.teams[1].members[0].move_ids[0] = POKEMON_GEN3_MOVE_SPLASH;
    init.teams[1].members[0].item_id = POKEMON_GEN3_ITEM_WHITEHERB;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].fainted);
    assert(battle.sides[1].state[0].boosts[POKEMON_STAT_ATK] == 0);
    assert(battle.sides[1].state[0].boosts[POKEMON_STAT_SPA] == 0);
    assert(battle.sides[1].state[0].item_id == 0);
    assert(battle.sides[1].state[0].last_item_id ==
        POKEMON_GEN3_ITEM_WHITEHERB);
    assert(pokemon_battle_check_invariants(&battle));

    /* The public transition owns rollback if the bounded faint queue cannot
     * accept the IF_HIT payment after the target transaction. */
    init.teams[1].members[0].item_id = 0;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    battle.faint_count = POKEMON_FAINT_QUEUE_CAPACITY;
    PokemonBattle before = battle;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_CAPACITY_EXCEEDED);
    assert(memcmp(&battle, &before, sizeof(battle)) == 0);
}

static void test_damaging_hit_contact_response_boundary(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_TACKLE,
        POKEMON_GEN3_SPECIES_VAPOREON, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_FLAMEBODY;
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(draw_label_count(&battle, POKEMON_DRAW_CONTACT_RESPONSE) == 1);
    uint32_t activation = 3;
    for (size_t i = 0; i < battle.draw_count; i++) {
        if (battle.draws[i].label == POKEMON_DRAW_CONTACT_RESPONSE) {
            activation = battle.draws[i].result;
        }
    }
    assert(activation < 3);
    assert(battle.sides[0].state[0].status.kind ==
        (activation == 0 ? POKEMON_STATUS_BURN : POKEMON_STATUS_NONE));
    assert(pokemon_battle_check_invariants(&battle));

    /* Event membership is the generated contact flag, not a move ID. */
    init.teams[0].members[0].move_ids[0] = POKEMON_GEN3_MOVE_SURF;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(draw_label_count(&battle, POKEMON_DRAW_CONTACT_RESPONSE) == 0);
    assert(battle.sides[0].state[0].status.kind == POKEMON_STATUS_NONE);
    assert(pokemon_battle_check_invariants(&battle));
}

static void test_generated_attraction_family(void) {
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_DELCATTY, POKEMON_GEN3_MOVE_ATTRACT,
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[0].members[0].gender = POKEMON_GENDER_FEMALE;
    init.teams[1].members[0].gender = POKEMON_GENDER_MALE;
    PokemonBattle direct;
    assert(pokemon_battle_init(&direct, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&direct, choices) == POKEMON_OK);
    int position = test_volatile_index(
        &direct.sides[1].state[0], POKEMON_VOLATILE_ATTRACT);
    assert(position >= 0);
    const PokemonVolatileState *attract =
        &direct.sides[1].state[0].volatiles[position];
    assert(attract->source.side == 0 && attract->source.slot == 0);
    assert(attract->source_effect.kind == POKEMON_SOURCE_EFFECT_MOVE);
    assert(attract->source_effect.id == POKEMON_GEN3_MOVE_ATTRACT);
    assert(draw_label_count(&direct, POKEMON_DRAW_ACCURACY) == 1);
    assert(handler_event_count(&direct, POKEMON_HANDLER_EVENT_START) == 1);

    init.teams[0].members[0].gender = POKEMON_GENDER_MALE;
    PokemonBattle immune;
    assert(pokemon_battle_init(&immune, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&immune, choices) == POKEMON_OK);
    assert(test_volatile_index(
        &immune.sides[1].state[0], POKEMON_VOLATILE_ATTRACT) < 0);
    /* Gen 3 preserves the accuracy draw even though TryImmunity has already
     * determined the eventual result; immunity wins over a simultaneous miss. */
    assert(draw_label_count(&immune, POKEMON_DRAW_ACCURACY) == 1);
    assert(event_kind_count(&immune, POKEMON_EVENT_IMMUNE) == 1);

    /* Volatile admission has its own generic Immunity boundary after
     * accuracy and before TryAddVolatile.  Oblivious rejects only Attract;
     * its inherited legal-domain TryHit callback remains observable but is a
     * no-op because Captivate does not exist in Gen 3. */
    init = condition_init(
        POKEMON_GEN3_SPECIES_DELCATTY, POKEMON_GEN3_MOVE_ATTRACT,
        POKEMON_GEN3_SPECIES_SLOWPOKE, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[0].members[0].gender = POKEMON_GENDER_FEMALE;
    init.teams[1].members[0].gender = POKEMON_GENDER_MALE;
    init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_OBLIVIOUS;
    PokemonBattle oblivious;
    assert(pokemon_battle_init(&oblivious, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&oblivious, choices) == POKEMON_OK);
    assert(test_volatile_index(
        &oblivious.sides[1].state[0], POKEMON_VOLATILE_ATTRACT) < 0);
    assert(draw_label_count(&oblivious, POKEMON_DRAW_ACCURACY) == 1);
    assert(draw_label_count(
        &oblivious, POKEMON_DRAW_ATTRACTION_ACTION) == 0);
    assert(event_kind_count(&oblivious, POKEMON_EVENT_IMMUNE) == 0);
    uint8_t saw_try_hit = 0;
    uint8_t saw_immunity = 0;
    uint8_t saw_try_add = 0;
    for (size_t i = 0; i < oblivious.handler_count; i++) {
        uint16_t id = oblivious.handlers[i].handler.descriptor.id;
        saw_try_hit |= id == POKEMON_GEN3_HANDLER_OBLIVIOUS_TRY_HIT;
        saw_immunity |= id == POKEMON_GEN3_HANDLER_OBLIVIOUS_IMMUNITY &&
            oblivious.handlers[i].result == POKEMON_HANDLER_PREVENT;
        saw_try_add |= oblivious.handlers[i].handler.descriptor.event ==
            POKEMON_HANDLER_EVENT_TRY_ADD_VOLATILE;
    }
    assert(saw_try_hit);
    assert(saw_immunity);
    assert(!saw_try_add);
    assert(pokemon_battle_check_invariants(&oblivious));

    PokemonEventFrame confusion_admission;
    assert(pokemon_run_event(&oblivious, &(PokemonEventInput){
        .event = POKEMON_HANDLER_EVENT_IMMUNITY,
        .source = {POKEMON_ENTITY_POKEMON, 0, 0},
        .target_side = 1, .target_slot = 0,
        .source_effect = {POKEMON_SOURCE_EFFECT_MOVE,
            POKEMON_GEN3_MOVE_CONFUSERAY},
        .relay = {.kind = POKEMON_RELAY_BOOLEAN, .value.boolean = 1},
        .context_kind = POKEMON_EVENT_CONTEXT_VOLATILE,
        .context.volatile_condition = {.kind = POKEMON_VOLATILE_CONFUSION},
    }, &confusion_admission) == POKEMON_OK);
    assert(confusion_admission.cancellation == POKEMON_EVENT_CANCEL_NONE);
    assert(confusion_admission.relay.value.boolean);

    init = condition_init(
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_TACKLE,
        POKEMON_GEN3_SPECIES_DELCATTY, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[0].members[0].gender = POKEMON_GENDER_MALE;
    init.teams[1].members[0].gender = POKEMON_GENDER_FEMALE;
    init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_CUTECHARM;
    init.teams[1].members[0].stats[0] = 500;
    uint8_t activated = 0;
    for (uint16_t tail = 1; tail < 2048 && !activated; tail++) {
        init.seed[3] = tail;
        PokemonBattle battle;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        position = test_volatile_index(
            &battle.sides[0].state[0], POKEMON_VOLATILE_ATTRACT);
        if (position < 0) continue;
        activated = 1;
        attract = &battle.sides[0].state[0].volatiles[position];
        assert(attract->source.side == 1 && attract->source.slot == 0);
        assert(attract->source_effect.kind == POKEMON_SOURCE_EFFECT_ABILITY);
        assert(attract->source_effect.id == POKEMON_GEN3_ABILITY_CUTECHARM);
        assert(draw_label_count(
            &battle, POKEMON_DRAW_CONTACT_RESPONSE) == 1);
    }
    assert(activated);
}

static void test_role_play_generic_ability_transfer(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_ALAKAZAM, POKEMON_GEN3_MOVE_SPLASH,
        POKEMON_GEN3_SPECIES_SLOWPOKE, POKEMON_GEN3_MOVE_ATTRACT);
    init.teams[0].members[0].move_ids[1] = POKEMON_GEN3_MOVE_ROLEPLAY;
    init.teams[0].members[0].ability_id = POKEMON_GEN3_ABILITY_SYNCHRONIZE;
    init.teams[0].members[0].gender = POKEMON_GENDER_MALE;
    init.teams[1].members[0].move_ids[1] = POKEMON_GEN3_MOVE_REST;
    init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_OBLIVIOUS;
    init.teams[1].members[0].gender = POKEMON_GENDER_FEMALE;
    init.teams[0].members[0].stats[5] = 276;
    init.teams[1].members[0].stats[5] = 66;
    PokemonChoice first[POKEMON_SIDES] = {move(0), move(0)};
    PokemonChoice second[POKEMON_SIDES] = {move(1), move(1)};
    PokemonBattle battle;
    uint8_t copied = 0;
    for (uint16_t tail = 1; tail < 4096 && !copied; tail++) {
        init.seed[3] = tail;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        assert(pokemon_battle_step(&battle, first) == POKEMON_OK);
        assert(test_volatile_index(
            &battle.sides[0].state[0], POKEMON_VOLATILE_ATTRACT) >= 0);
        size_t ability_draws = draw_label_count(
            &battle, POKEMON_DRAW_ABILITY_TARGET);
        assert(pokemon_battle_step(&battle, second) == POKEMON_OK);
        copied = battle.sides[0].state[0].ability_id ==
            POKEMON_GEN3_ABILITY_OBLIVIOUS;
        if (!copied) continue;
        assert(draw_label_count(
            &battle, POKEMON_DRAW_ABILITY_TARGET) == ability_draws);
        assert(test_volatile_index(
            &battle.sides[0].state[0], POKEMON_VOLATILE_ATTRACT) < 0);
        uint8_t saw_try = 0;
        uint8_t saw_hit = 0;
        uint8_t saw_update = 0;
        for (size_t i = 0; i < battle.handler_count; i++) {
            uint16_t id = battle.handlers[i].handler.descriptor.id;
            saw_try |= id == POKEMON_GEN3_HANDLER_ROLE_PLAY_TRY_HIT;
            saw_hit |= id == POKEMON_GEN3_HANDLER_ROLE_PLAY_HIT;
            saw_update |= id == POKEMON_GEN3_HANDLER_OBLIVIOUS_UPDATE;
        }
        assert(saw_try && saw_hit && saw_update);
        assert(pokemon_battle_check_invariants(&battle));
    }
    assert(copied);

    init = condition_init(
        POKEMON_GEN3_SPECIES_ALAKAZAM, POKEMON_GEN3_MOVE_ROLEPLAY,
        POKEMON_GEN3_SPECIES_ALAKAZAM, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[0].members[0].ability_id = POKEMON_GEN3_ABILITY_SYNCHRONIZE;
    init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_SYNCHRONIZE;
    PokemonChoice same[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, same) == POKEMON_OK);
    assert(battle.sides[0].state[0].ability_id ==
        POKEMON_GEN3_ABILITY_SYNCHRONIZE);
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 0);
    uint8_t prevented = 0;
    for (size_t i = 0; i < battle.handler_count; i++) {
        prevented |= battle.handlers[i].handler.descriptor.id ==
                POKEMON_GEN3_HANDLER_ROLE_PLAY_TRY_HIT &&
            battle.handlers[i].result == POKEMON_HANDLER_PREVENT;
    }
    assert(prevented);
    assert(pokemon_battle_check_invariants(&battle));

    /* Ability-transfer restrictions are generated capabilities, not catalog
     * identities.  Prove both directions reject atomically before PRNG. */
    for (size_t variant = 0; variant < 2; variant++) {
        PokemonAbilityData abilities[POKEMON_GEN3_SLICE_DATA.ability_count];
        memcpy(abilities, POKEMON_GEN3_SLICE_DATA.abilities,
            sizeof(abilities));
        for (size_t i = 0; i < POKEMON_GEN3_SLICE_DATA.ability_count; i++) {
            if (variant == 0 &&
                abilities[i].id == POKEMON_GEN3_ABILITY_OBLIVIOUS) {
                abilities[i].semantic_flags |=
                    POKEMON_ABILITY_SEMANTIC_FAIL_ROLE_PLAY;
            }
            if (variant == 1 &&
                abilities[i].id == POKEMON_GEN3_ABILITY_SYNCHRONIZE) {
                abilities[i].semantic_flags |=
                    POKEMON_ABILITY_SEMANTIC_CANT_SUPPRESS;
            }
        }
        PokemonData data = POKEMON_GEN3_SLICE_DATA;
        data.abilities = abilities;
        PokemonResolvedBundle bundle = POKEMON_GEN3_OU_BUNDLE;
        bundle.data = &data;
        init = condition_init(
            POKEMON_GEN3_SPECIES_ALAKAZAM, POKEMON_GEN3_MOVE_ROLEPLAY,
            POKEMON_GEN3_SPECIES_SLOWPOKE, POKEMON_GEN3_MOVE_SPLASH);
        init.teams[0].members[0].ability_id =
            POKEMON_GEN3_ABILITY_SYNCHRONIZE;
        init.teams[1].members[0].ability_id =
            POKEMON_GEN3_ABILITY_OBLIVIOUS;
        init.bundle = &bundle;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        uint16_t before_source_ability = battle.sides[0].state[0].ability_id;
        uint16_t before_source_generation =
            battle.sides[0].state[0].ability_generation;
        uint16_t before_source_order =
            battle.sides[0].state[0].ability_effect_order;
        uint16_t before_target_ability = battle.sides[1].state[0].ability_id;
        uint16_t before_target_generation =
            battle.sides[1].state[0].ability_generation;
        uint16_t before_target_order =
            battle.sides[1].state[0].ability_effect_order;
        uint16_t before_effect_order = battle.next_holder_effect_order;
        assert(pokemon_battle_step(&battle, same) == POKEMON_OK);
        assert(battle.sides[0].state[0].ability_id == before_source_ability);
        assert(battle.sides[0].state[0].ability_generation ==
            before_source_generation);
        assert(battle.sides[0].state[0].ability_effect_order ==
            before_source_order);
        assert(battle.sides[1].state[0].ability_id == before_target_ability);
        assert(battle.sides[1].state[0].ability_generation ==
            before_target_generation);
        assert(battle.sides[1].state[0].ability_effect_order ==
            before_target_order);
        assert(battle.next_holder_effect_order == before_effect_order);
        assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 0);
        assert(draw_label_count(&battle, POKEMON_DRAW_ABILITY_TARGET) == 0);
    }

    /* Unknown capability bits make the resolved plugin invalid before the
     * destination battle or its PRNG can be touched. */
    PokemonAbilityData malformed_abilities[
        POKEMON_GEN3_SLICE_DATA.ability_count];
    memcpy(malformed_abilities, POKEMON_GEN3_SLICE_DATA.abilities,
        sizeof(malformed_abilities));
    malformed_abilities[0].semantic_flags |= UINT8_C(0x80);
    PokemonData malformed_data = POKEMON_GEN3_SLICE_DATA;
    malformed_data.abilities = malformed_abilities;
    PokemonResolvedBundle malformed_bundle = POKEMON_GEN3_OU_BUNDLE;
    malformed_bundle.data = &malformed_data;
    init.bundle = &malformed_bundle;
    PokemonBattle untouched;
    memset(&untouched, 0xa5, sizeof(untouched));
    PokemonBattle untouched_before = untouched;
    assert(pokemon_battle_init(&untouched, &init) ==
        POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&untouched, &untouched_before, sizeof(untouched)) == 0);
}

static void test_skill_swap_transaction(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_ALAKAZAM, POKEMON_GEN3_MOVE_SKILLSWAP,
        POKEMON_GEN3_SPECIES_SALAMENCE, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[0].members[0].ability_id = POKEMON_GEN3_ABILITY_SYNCHRONIZE;
    init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_INTIMIDATE;
    init.team_sizes[0] = 2;
    init.teams[0].members[1] = init.teams[0].members[0];
    init.teams[0].members[1].species_id = POKEMON_GEN3_SPECIES_SLOWPOKE;
    init.teams[0].members[1].ability_id = POKEMON_GEN3_ABILITY_OBLIVIOUS;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    int8_t source_attack = battle.sides[0].state[0].boosts[POKEMON_STAT_ATK];
    int8_t target_attack = battle.sides[1].state[0].boosts[POKEMON_STAT_ATK];
    uint16_t source_generation = battle.sides[0].state[0].ability_generation;
    uint16_t target_generation = battle.sides[1].state[0].ability_generation;
    uint16_t before_order = battle.next_holder_effect_order;
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].ability_id ==
        POKEMON_GEN3_ABILITY_INTIMIDATE);
    assert(battle.sides[1].state[0].ability_id ==
        POKEMON_GEN3_ABILITY_SYNCHRONIZE);
    assert(battle.sides[0].state[0].volatile_staleness ==
        POKEMON_STALENESS_NONE);
    assert(battle.sides[1].state[0].volatile_staleness ==
        POKEMON_STALENESS_EXTERNAL);
    assert(battle.sides[0].sets[0].ability_id ==
        POKEMON_GEN3_ABILITY_SYNCHRONIZE);
    assert(battle.sides[1].sets[0].ability_id ==
        POKEMON_GEN3_ABILITY_INTIMIDATE);
    assert(battle.sides[0].state[0].ability_generation ==
        source_generation + 1);
    assert(battle.sides[1].state[0].ability_generation ==
        target_generation + 1);
    assert(battle.next_holder_effect_order == before_order + 2);
    assert(battle.event_frames[1].event == POKEMON_HANDLER_EVENT_SET_ABILITY);
    /* Gen 3 installs the exchanged abilities without Start callbacks. */
    assert(battle.sides[0].state[0].boosts[POKEMON_STAT_ATK] == source_attack);
    assert(battle.sides[1].state[0].boosts[POKEMON_STAT_ATK] == target_attack);
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 0);
    assert(pokemon_battle_check_invariants(&battle));
    PokemonChoice switch_out[POKEMON_SIDES] = {switch_to(1), move(0)};
    PokemonChoice switch_back[POKEMON_SIDES] = {switch_to(0), move(0)};
    assert(pokemon_battle_step(&battle, switch_out) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, switch_back) == POKEMON_OK);
    assert(battle.sides[0].state[0].ability_id ==
        POKEMON_GEN3_ABILITY_SYNCHRONIZE);

    /* Equal abilities and either orientation of fail-skillswap reject before
     * installation, lifecycle mutation, or move-owned PRNG. */
    for (size_t variant = 0; variant < 3; variant++) {
        init = condition_init(
            variant == 1 ? POKEMON_GEN3_SPECIES_SHEDINJA :
                POKEMON_GEN3_SPECIES_ALAKAZAM,
            POKEMON_GEN3_MOVE_SKILLSWAP,
            variant == 2 ? POKEMON_GEN3_SPECIES_SHEDINJA :
                POKEMON_GEN3_SPECIES_ALAKAZAM,
            POKEMON_GEN3_MOVE_SPLASH);
        init.teams[0].members[0].ability_id = variant == 1 ?
            POKEMON_GEN3_ABILITY_WONDERGUARD :
            POKEMON_GEN3_ABILITY_SYNCHRONIZE;
        init.teams[1].members[0].ability_id = variant == 2 ?
            POKEMON_GEN3_ABILITY_WONDERGUARD :
            POKEMON_GEN3_ABILITY_SYNCHRONIZE;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        uint16_t source_id = battle.sides[0].state[0].ability_id;
        uint16_t target_id = battle.sides[1].state[0].ability_id;
        uint16_t order = battle.next_holder_effect_order;
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        assert(battle.sides[0].state[0].ability_id == source_id);
        assert(battle.sides[1].state[0].ability_id == target_id);
        assert(battle.next_holder_effect_order == order);
        assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 0);
        assert(pokemon_battle_check_invariants(&battle));
    }

    /* SetAbility is a two-gate transaction. A generated ability handler may
     * reject either destination; neither ability lifecycle may begin until
     * both gates admit the exchange. */
    for (size_t rejected_gate = 0; rejected_gate < 2; rejected_gate++) {
        enum { TEST_SET_ABILITY_REJECT = 65000 };
        PokemonHandlerDescriptor handlers[
            POKEMON_GEN3_SLICE_DATA.handler_count + 1];
        PokemonHandlerOp programs[
            POKEMON_GEN3_SLICE_DATA.handler_program_count + 1];
        PokemonOwnerBindingIndex bindings[
            POKEMON_GEN3_SLICE_DATA.owner_binding_index_count + 1];
        memcpy(handlers, POKEMON_GEN3_SLICE_DATA.handlers,
            POKEMON_GEN3_SLICE_DATA.handler_count * sizeof(handlers[0]));
        memcpy(programs, POKEMON_GEN3_SLICE_DATA.handler_programs,
            POKEMON_GEN3_SLICE_DATA.handler_program_count * sizeof(programs[0]));
        memcpy(bindings, POKEMON_GEN3_SLICE_DATA.owner_binding_index,
            POKEMON_GEN3_SLICE_DATA.owner_binding_index_count *
                sizeof(bindings[0]));
        handlers[POKEMON_GEN3_SLICE_DATA.handler_count] =
            (PokemonHandlerDescriptor){
                .event = POKEMON_HANDLER_EVENT_SET_ABILITY,
                .id = TEST_SET_ABILITY_REJECT,
                .source_kind = POKEMON_HANDLER_SOURCE_ABILITY,
                .source_id = rejected_gate == 0 ?
                    POKEMON_GEN3_ABILITY_INTIMIDATE :
                    POKEMON_GEN3_ABILITY_SYNCHRONIZE,
                .program_offset =
                    POKEMON_GEN3_SLICE_DATA.handler_program_count,
                .program_count = 1,
                .scope = POKEMON_HANDLER_SCOPE_TARGET,
                .route = POKEMON_HANDLER_ROUTE_OWNER,
                .raw_hook = "synthetic SetAbility rejection",
            };
        programs[POKEMON_GEN3_SLICE_DATA.handler_program_count] =
            (PokemonHandlerOp){POKEMON_HANDLER_OP_RETURN_FALSE, 0};
        bindings[POKEMON_GEN3_SLICE_DATA.owner_binding_index_count] =
            (PokemonOwnerBindingIndex){
                .owner_kind = POKEMON_OWNER_ABILITY,
                .owner_id = rejected_gate == 0 ?
                    POKEMON_GEN3_ABILITY_INTIMIDATE :
                    POKEMON_GEN3_ABILITY_SYNCHRONIZE,
                .event = POKEMON_HANDLER_EVENT_SET_ABILITY,
                .scope = POKEMON_HANDLER_SCOPE_TARGET,
                .route = POKEMON_HANDLER_ROUTE_OWNER,
                .binding_offset = POKEMON_GEN3_SLICE_DATA.handler_count,
                .binding_count = 1,
            };
        PokemonData rejecting_data = POKEMON_GEN3_SLICE_DATA;
        rejecting_data.handlers = handlers;
        rejecting_data.handler_count++;
        rejecting_data.handler_programs = programs;
        rejecting_data.handler_program_count++;
        rejecting_data.owner_binding_index = bindings;
        rejecting_data.owner_binding_index_count++;
        PokemonResolvedBundle rejecting_bundle = POKEMON_GEN3_OU_BUNDLE;
        rejecting_bundle.data = &rejecting_data;
        init = condition_init(
            POKEMON_GEN3_SPECIES_ALAKAZAM, POKEMON_GEN3_MOVE_SKILLSWAP,
            POKEMON_GEN3_SPECIES_SALAMENCE, POKEMON_GEN3_MOVE_SPLASH);
        init.teams[0].members[0].ability_id =
            POKEMON_GEN3_ABILITY_SYNCHRONIZE;
        init.teams[1].members[0].ability_id =
            POKEMON_GEN3_ABILITY_INTIMIDATE;
        init.bundle = &rejecting_bundle;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        uint16_t source_generation =
            battle.sides[0].state[0].ability_generation;
        uint16_t target_generation =
            battle.sides[1].state[0].ability_generation;
        uint16_t source_order =
            battle.sides[0].state[0].ability_effect_order;
        uint16_t target_order =
            battle.sides[1].state[0].ability_effect_order;
        uint16_t next_order = battle.next_holder_effect_order;
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        assert(battle.sides[0].state[0].ability_id ==
            POKEMON_GEN3_ABILITY_SYNCHRONIZE);
        assert(battle.sides[1].state[0].ability_id ==
            POKEMON_GEN3_ABILITY_INTIMIDATE);
        assert(battle.sides[0].state[0].ability_generation ==
            source_generation);
        assert(battle.sides[1].state[0].ability_generation ==
            target_generation);
        assert(battle.sides[0].state[0].ability_effect_order == source_order);
        assert(battle.sides[1].state[0].ability_effect_order == target_order);
        assert(battle.next_holder_effect_order == next_order);
        assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 0);
        assert(pokemon_battle_check_invariants(&battle));
    }
}

static void test_wonder_guard_generic_effectiveness_gate(void) {
	PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
	PokemonBattleInit init = condition_init(
		POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_WATERGUN,
		POKEMON_GEN3_SPECIES_SHEDINJA, POKEMON_GEN3_MOVE_SPLASH);
	init.teams[0].members[0].ability_id = POKEMON_GEN3_ABILITY_OWNTEMPO;
	init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_WONDERGUARD;
	init.teams[1].members[0].stats[0] = 1;
	PokemonBattle battle;
	assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
	assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
	assert(battle.sides[1].state[0].hp == 1);
	/* Gen 3 stages numeric move accuracy before target TryHit handlers. */
	assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 1);
	assert(draw_label_count(&battle, POKEMON_DRAW_CRITICAL) == 0);
	assert(draw_label_count(&battle, POKEMON_DRAW_DAMAGE_ROLL) == 0);
	uint8_t prevented = 0;
	for (size_t i = 0; i < battle.handler_count; i++) {
		prevented |= battle.handlers[i].handler.descriptor.id ==
				POKEMON_GEN3_HANDLER_WONDER_GUARD_TRY_HIT &&
			battle.handlers[i].result == POKEMON_HANDLER_IMMUNE;
	}
	assert(prevented);

	init.teams[0].members[0].move_ids[0] = POKEMON_GEN3_MOVE_EMBER;
	assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
	assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
	assert(battle.sides[1].state[0].hp == 0);
	assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 1);
	assert(draw_label_count(&battle, POKEMON_DRAW_CRITICAL) == 1);
	assert(draw_label_count(&battle, POKEMON_DRAW_DAMAGE_ROLL) == 1);

	init.teams[0].members[0].move_ids[0] = POKEMON_GEN3_MOVE_GROWL;
	assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
	assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
	assert(battle.sides[1].state[0].boosts[POKEMON_STAT_ATK] == -1);

	/* Ability-transfer rejection is data on the resolved ability, not an ID
	 * branch in Role Play or the generic TryHit gate. */
	init.teams[0].members[0].move_ids[0] = POKEMON_GEN3_MOVE_ROLEPLAY;
	assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
	assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
	assert(battle.sides[0].state[0].ability_id ==
		POKEMON_GEN3_ABILITY_OWNTEMPO);
	assert(pokemon_battle_check_invariants(&battle));

	const PokemonMoveData *struggle = NULL;
	for (size_t i = 0; i < battle.data->move_count; i++) {
		if (battle.data->moves[i].id == POKEMON_GEN3_MOVE_STRUGGLE) {
			struggle = &battle.data->moves[i];
			break;
		}
	}
	assert(struggle != NULL);
	PokemonMoveData active_struggle = *struggle;
	active_struggle.type = POKEMON_GEN3_TYPE_TYPELESS;
	PokemonEventFrame typeless;
	assert(pokemon_run_event(&battle, &(PokemonEventInput){
		.event = POKEMON_HANDLER_EVENT_TRY_HIT,
		.source = {POKEMON_ENTITY_POKEMON, 0, 0},
		.target_side = 1, .target_slot = 0,
		.source_effect = {POKEMON_SOURCE_EFFECT_MOVE, POKEMON_GEN3_MOVE_STRUGGLE},
		.relay = {.kind = POKEMON_RELAY_BOOLEAN, .value.boolean = 1},
		.context_kind = POKEMON_EVENT_CONTEXT_MOVE,
		.context.move = {.move = &active_struggle},
	}, &typeless) == POKEMON_OK);
	assert(typeless.cancellation == POKEMON_EVENT_CANCEL_NONE);
	assert(typeless.relay.kind == POKEMON_RELAY_BOOLEAN &&
		typeless.relay.value.boolean);
}

static void test_white_herb_after_move_transaction(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SPLASH,
        POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[0].members[0].item_id = POKEMON_GEN3_ITEM_WHITEHERB;
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    PokemonBattle battle;
    int init_status = pokemon_battle_init(&battle, &init);
    assert(init_status == POKEMON_OK);
    PokemonMutable *holder = &battle.sides[0].state[0];
    holder->boosts[POKEMON_STAT_ATK] = -2;
    holder->boosts[POKEMON_STAT_SPA] = 3;
    holder->boosts[POKEMON_STAT_ACCURACY] = -1;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(holder->boosts[POKEMON_STAT_ATK] == 0);
    assert(holder->boosts[POKEMON_STAT_ACCURACY] == 0);
    assert(holder->boosts[POKEMON_STAT_SPA] == 3);
    assert(holder->item_id == 0);
    assert(holder->last_item_id == POKEMON_GEN3_ITEM_WHITEHERB);
    assert(holder->used_item_this_turn == 0);
    assert(holder->ate_berry == 0);
    unsigned after_move_handlers = 0;
    for (size_t i = 0; i < battle.handler_count; i++) {
        if (battle.handlers[i].handler.descriptor.id ==
                POKEMON_GEN3_HANDLER_WHITE_HERB_ANY_AFTER_MOVE &&
            battle.handlers[i].invoked) {
            after_move_handlers++;
        }
    }
    assert(after_move_handlers == 1);

    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    holder = &battle.sides[0].state[0];
    holder->boosts[POKEMON_STAT_ATK] = 2;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(holder->boosts[POKEMON_STAT_ATK] == 2);
    assert(holder->item_id == POKEMON_GEN3_ITEM_WHITEHERB);
    assert(holder->last_item_id == 0);
}

static void test_mental_herb_use_item_transaction(void) {
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_DELCATTY, POKEMON_GEN3_MOVE_ATTRACT,
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[0].members[0].gender = POKEMON_GENDER_FEMALE;
    init.teams[1].members[0].gender = POKEMON_GENDER_MALE;
    init.teams[1].members[0].item_id = POKEMON_GEN3_ITEM_MENTALHERB;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    PokemonMutable *holder = &battle.sides[1].state[0];
    assert(test_volatile_index(holder, POKEMON_VOLATILE_ATTRACT) < 0);
    assert(holder->item_id == 0);
    assert(holder->last_item_id == POKEMON_GEN3_ITEM_MENTALHERB);
    assert(holder->ate_berry == 0);
    assert(draw_label_count(&battle, POKEMON_DRAW_ATTRACTION_ACTION) == 0);
    size_t attract_update = SIZE_MAX;
    size_t mental_herb_update = SIZE_MAX;
    for (size_t i = 0; i < battle.handler_count; i++) {
        if (battle.handlers[i].handler.descriptor.id ==
            POKEMON_GEN3_HANDLER_ATTRACT_UPDATE) attract_update = i;
        if (battle.handlers[i].handler.descriptor.id ==
            POKEMON_GEN3_HANDLER_MENTAL_HERB_UPDATE) mental_herb_update = i;
    }
    assert(attract_update != SIZE_MAX && mental_herb_update != SIZE_MAX);
    assert(attract_update < mental_herb_update);

    init.teams[0].members[0].move_ids[0] = POKEMON_GEN3_MOVE_SPLASH;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    holder = &battle.sides[1].state[0];
    assert(holder->item_id == POKEMON_GEN3_ITEM_MENTALHERB);
    assert(holder->last_item_id == 0);

    init.teams[0].members[0].move_ids[0] = POKEMON_GEN3_MOVE_ATTRACT;
    init.teams[0].members[0].gender = POKEMON_GENDER_MALE;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    holder = &battle.sides[1].state[0];
    assert(holder->item_id == POKEMON_GEN3_ITEM_MENTALHERB);
    assert(test_volatile_index(holder, POKEMON_VOLATILE_ATTRACT) < 0);
}

static void test_effect_spore_uniform_status_selection(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_TACKLE,
        POKEMON_GEN3_SPECIES_BRELOOM, POKEMON_GEN3_MOVE_BULKUP);
    init.teams[0].members[0].ability_id = 0;
    init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_EFFECTSPORE;
    init.teams[1].members[0].stats[0] = 600;
    init.teams[1].members[0].stats[2] = 300;
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    const PokemonStatus expected[3] = {
        POKEMON_STATUS_SLEEP, POKEMON_STATUS_PARALYSIS, POKEMON_STATUS_POISON,
    };
    uint8_t seen = 0;
    uint8_t saw_failed_activation = 0;

    for (uint16_t tail = 1; tail < 512 && (seen != 7 || !saw_failed_activation);
         tail++) {
        init.seed[3] = tail;
        PokemonBattle battle;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        if (draw_label_count(&battle, POKEMON_DRAW_CONTACT_RESPONSE) == 0) {
            continue;
        }
        size_t selections = draw_label_count(
            &battle, POKEMON_DRAW_CONTACT_STATUS_SELECTION);
        if (selections == 0) {
            saw_failed_activation = 1;
            assert(battle.sides[0].state[0].status.kind == POKEMON_STATUS_NONE);
            continue;
        }
        assert(selections == 1);
        uint32_t selected = 3;
        for (size_t i = 0; i < battle.draw_count; i++) {
            if (battle.draws[i].label !=
                    POKEMON_DRAW_CONTACT_STATUS_SELECTION) continue;
            selected = battle.draws[i].result;
            assert(battle.draws[i].upper_bound == 3);
        }
        assert(selected < 3);
        assert(battle.sides[0].state[0].status.kind == expected[selected]);
        seen |= (uint8_t)(1u << selected);
        assert(pokemon_battle_check_invariants(&battle));
    }
    assert(seen == 7 && saw_failed_activation);

    /* Selection occurs before admission; an existing status does not refund
     * either ability-owned draw. Seed 22 activates and selects sleep. */
    init.seed[3] = 22;
    init.initial_status[0][0] = POKEMON_STATUS_BURN;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].status.kind == POKEMON_STATUS_BURN);
    assert(draw_label_count(&battle, POKEMON_DRAW_CONTACT_RESPONSE) == 1);
    assert(draw_label_count(
        &battle, POKEMON_DRAW_CONTACT_STATUS_SELECTION) == 1);
}

static void test_residual_status_cure_family(void) {
    enum { TEST_SHED_SKIN_ABILITY = 62200, TEST_SHED_SKIN_HANDLER = 62201 };
    PokemonAbilityData ability = {
        .id = TEST_SHED_SKIN_ABILITY, .handler_offset = 0, .handler_count = 1,
    };
    PokemonHandlerDescriptor handler = {
        .event = POKEMON_HANDLER_EVENT_RESIDUAL,
        .id = TEST_SHED_SKIN_HANDLER,
        .source_kind = POKEMON_HANDLER_SOURCE_ABILITY,
        .source_id = TEST_SHED_SKIN_ABILITY,
        .program_offset = 0, .program_count = 4,
        .order = 10, .sub_order = 3,
        .scope = POKEMON_HANDLER_SCOPE_TARGET,
        .route = POKEMON_HANDLER_ROUTE_OWNER,
        .raw_hook = "onResidual",
    };
    PokemonOwnerBindingIndex binding = {
        .owner_kind = POKEMON_OWNER_ABILITY,
        .owner_id = TEST_SHED_SKIN_ABILITY,
        .event = POKEMON_HANDLER_EVENT_RESIDUAL,
        .scope = POKEMON_HANDLER_SCOPE_TARGET,
        .route = POKEMON_HANDLER_ROUTE_OWNER,
        .binding_offset = 0, .binding_count = 1,
    };
    PokemonHandlerOp programs[] = {
        {POKEMON_HANDLER_OP_GUARD_HOLDER_ALIVE, 0},
        {POKEMON_HANDLER_OP_GUARD_STATUS_PRESENT, 0},
        {POKEMON_HANDLER_OP_GUARD_RANDOM_CHANCE,
            (POKEMON_DRAW_RESIDUAL_STATUS_CURE << 24) | (33u << 16) | 100u},
        {POKEMON_HANDLER_OP_CLEAR_MAJOR_STATUS, 0},
    };
    PokemonData data = POKEMON_GEN3_SLICE_DATA;
    PokemonMoveData moves[data.move_count];
    memcpy(moves, data.moves, sizeof(moves));
    for (size_t i = 0; i < data.move_count; i++) moves[i].call_pool_id = 0;
    data.moves = moves;
    data.abilities = &ability;
    data.ability_count = 1;
    data.handlers = &handler;
    data.handler_count = 1;
    data.handler_programs = programs;
    data.handler_program_count = sizeof(programs) / sizeof(programs[0]);
    data.owner_binding_index = &binding;
    data.owner_binding_index_count = 1;
    data.move_call_pools = NULL;
    data.move_call_pool_count = 0;
    data.move_call_pool_candidates = NULL;
    data.move_call_pool_candidate_count = 0;
    data.constructed_hit_templates = NULL;
    data.constructed_hit_template_count = 0;
    data.move_pre_use_programs = NULL;
    data.move_pre_use_program_count = 0;
    PokemonResolvedBundle bundle = POKEMON_GEN3_OU_BUNDLE;
    PokemonFormatPolicy policy = *bundle.policy;
    policy.status_clauses = NULL;
    policy.status_clause_count = 0;
    bundle.policy = &policy;
    bundle.data = &data;

    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SPLASH,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SPLASH);
    init.bundle = &bundle;
    init.teams[0].members[0].ability_id = TEST_SHED_SKIN_ABILITY;
    init.initial_status[0][0] = POKEMON_STATUS_POISON;
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    uint8_t saw_cure = 0;
    uint8_t saw_no_cure = 0;
    for (uint16_t tail = 1; tail < 256 && !(saw_cure && saw_no_cure); tail++) {
        init.seed[3] = (uint8_t)tail;
        PokemonBattle battle;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        assert(draw_label_count(
            &battle, POKEMON_DRAW_RESIDUAL_STATUS_CURE) == 1);
        for (size_t i = 0; i < battle.draw_count; i++) {
            if (battle.draws[i].label !=
                    POKEMON_DRAW_RESIDUAL_STATUS_CURE) continue;
            assert(battle.draws[i].upper_bound == 100);
            if (battle.draws[i].result < 33) {
                saw_cure = 1;
                assert(battle.sides[0].state[0].status.kind ==
                    POKEMON_STATUS_NONE);
                assert(battle.sides[0].state[0].hp ==
                    init.teams[0].members[0].stats[0]);
                uint8_t found_removal = 0;
                for (size_t trace_index = 0;
                     trace_index < battle.condition_trace_count; trace_index++) {
                    const PokemonConditionTrace *trace =
                        &battle.condition_traces[trace_index];
                    found_removal |=
                        trace->scope == POKEMON_CONDITION_SCOPE_STATUS &&
                        trace->operation == POKEMON_CONDITION_REMOVE &&
                        trace->reason == POKEMON_CONDITION_REASON_HANDLER;
                }
                assert(found_removal);
            } else {
                saw_no_cure = 1;
                assert(battle.sides[0].state[0].status.kind ==
                    POKEMON_STATUS_POISON);
            }
        }
        assert(battle.handler_count >= 1);
        assert(battle.handlers[0].handler.descriptor.id ==
            TEST_SHED_SKIN_HANDLER);
        assert(battle.handlers[0].handler.descriptor.order == 10);
        assert(battle.handlers[0].handler.descriptor.sub_order == 3);
        assert(pokemon_battle_check_invariants(&battle));
    }
    assert(saw_cure && saw_no_cure);

    /* The status guard owns staging: no status means no cure draw. */
    init.initial_status[0][0] = POKEMON_STATUS_NONE;
    PokemonBattle clear;
    assert(pokemon_battle_init(&clear, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&clear, choices) == POKEMON_OK);
    assert(draw_label_count(
        &clear, POKEMON_DRAW_RESIDUAL_STATUS_CURE) == 0);

    /* A statused holder which faints before Residual owns no cure draw. */
    init.initial_status[0][0] = POKEMON_STATUS_POISON;
    init.team_sizes[0] = 2;
    init.teams[0].members[1] = make_set(
        POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_SPLASH,
        200, 50, 50, 50, 50, 50);
    init.initial_hp[0][0] = 1;
    init.teams[1].members[0].move_ids[0] = POKEMON_GEN3_MOVE_STRENGTH;
    init.teams[1].members[0].stats[1] = 999;
    init.teams[1].members[0].stats[5] = 999;
    PokemonBattle fainted;
    assert(pokemon_battle_init(&fainted, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&fainted, choices) == POKEMON_OK);
    assert(fainted.sides[0].state[0].hp == 0);
    assert(fainted.request.kind[0] == POKEMON_REQUEST_SWITCH);
    assert(draw_label_count(
        &fainted, POKEMON_DRAW_RESIDUAL_STATUS_CURE) == 0);
}

static void test_add_or_restart_volatile_transaction(void) {
    enum { TEST_ABILITY = 62300, TEST_TRY_HIT = 62301,
        TEST_RESTART = 62302 };
    PokemonAbilityData ability = {
        .id = TEST_ABILITY, .handler_offset = 0, .handler_count = 1,
    };
    PokemonHandlerOp programs[] = {
        {POKEMON_HANDLER_OP_TRY_ADD_OR_RESTART_HOLDER_VOLATILE,
            POKEMON_VOLATILE_TORMENT},
        {POKEMON_HANDLER_OP_RETURN_NULL, 0},
        {POKEMON_HANDLER_OP_RETURN_UNDEFINED, 0},
    };
    PokemonHandlerDescriptor handlers[] = {
        {
            .event = POKEMON_HANDLER_EVENT_TRY_HIT, .id = TEST_TRY_HIT,
            .source_kind = POKEMON_HANDLER_SOURCE_ABILITY,
            .source_id = TEST_ABILITY, .program_offset = 0,
            .program_count = 2, .scope = POKEMON_HANDLER_SCOPE_TARGET,
            .route = POKEMON_HANDLER_ROUTE_OWNER, .raw_hook = "synthetic",
        },
        {
            .event = POKEMON_HANDLER_EVENT_RESTART, .id = TEST_RESTART,
            .source_kind = POKEMON_HANDLER_SOURCE_CONDITION,
            .source_id = POKEMON_GEN3_CONDITION_VOLATILE_TORMENT,
            .program_offset = 2, .program_count = 1,
            .scope = POKEMON_HANDLER_SCOPE_TARGET,
            .route = POKEMON_HANDLER_ROUTE_OWNER, .raw_hook = "synthetic",
        },
    };
    PokemonOwnerBindingIndex bindings[] = {
        {
            .owner_kind = POKEMON_OWNER_ABILITY, .owner_id = TEST_ABILITY,
            .event = POKEMON_HANDLER_EVENT_TRY_HIT,
            .scope = POKEMON_HANDLER_SCOPE_TARGET,
            .route = POKEMON_HANDLER_ROUTE_OWNER,
            .binding_offset = 0, .binding_count = 1,
        },
        {
            .owner_kind = POKEMON_OWNER_VOLATILE,
            .owner_id = POKEMON_GEN3_CONDITION_VOLATILE_TORMENT,
            .event = POKEMON_HANDLER_EVENT_RESTART,
            .scope = POKEMON_HANDLER_SCOPE_TARGET,
            .route = POKEMON_HANDLER_ROUTE_OWNER,
            .binding_offset = 1, .binding_count = 1,
        },
    };
    PokemonData data = POKEMON_GEN3_SLICE_DATA;
    PokemonMoveData moves[data.move_count];
    memcpy(moves, data.moves, sizeof(moves));
    for (size_t i = 0; i < data.move_count; i++) moves[i].call_pool_id = 0;
    data.moves = moves;
    data.abilities = &ability; data.ability_count = 1;
    data.handlers = handlers; data.handler_count = 1;
    data.handler_programs = programs;
    data.handler_program_count = sizeof(programs) / sizeof(programs[0]);
    data.owner_binding_index = bindings; data.owner_binding_index_count = 1;
    data.move_call_pools = NULL; data.move_call_pool_count = 0;
    data.move_call_pool_candidates = NULL;
    data.move_call_pool_candidate_count = 0;
    data.constructed_hit_templates = NULL;
    data.constructed_hit_template_count = 0;
    data.move_pre_use_programs = NULL;
    data.move_pre_use_program_count = 0;
    PokemonResolvedBundle bundle = POKEMON_GEN3_OU_BUNDLE;
    PokemonFormatPolicy policy = *bundle.policy;
    policy.status_clauses = NULL;
    policy.status_clause_count = 0;
    bundle.policy = &policy;
    bundle.data = &data;
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SPLASH,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_TACKLE);
    init.bundle = &bundle;
    init.teams[0].members[0].ability_id = TEST_ABILITY;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    PokemonEventInput input = {
        .event = POKEMON_HANDLER_EVENT_TRY_HIT,
        .source = {POKEMON_ENTITY_POKEMON, 1, 0},
        .target_side = 0, .target_slot = 0,
        .source_effect = {POKEMON_SOURCE_EFFECT_MOVE, POKEMON_GEN3_MOVE_TACKLE},
        .relay = {.kind = POKEMON_RELAY_BOOLEAN, .value.boolean = 1},
        .context_kind = POKEMON_EVENT_CONTEXT_MOVE,
        .context.move = {.move = &data.moves[0]},
    };
    PokemonEventFrame frame;
    assert(pokemon_run_event(&battle, &input, &frame) == POKEMON_OK);
    assert(frame.cancellation == POKEMON_EVENT_CANCEL_NULL);
    assert(frame.cancellation_emits_immunity == 0);
    assert(test_volatile_index(&battle.sides[0].state[0],
        POKEMON_VOLATILE_TORMENT) >= 0);

    assert(pokemon_run_event(&battle, &input, &frame) == POKEMON_OK);
    assert(frame.cancellation_emits_immunity == 1);

    data.handler_count = 2;
    data.owner_binding_index_count = 2;
    bundle.data = &data;
    battle.data = &data;
    uint8_t count_before = battle.sides[0].state[0].volatile_count;
    assert(pokemon_run_event(&battle, &input, &frame) == POKEMON_OK);
    assert(frame.cancellation_emits_immunity == 0);
    assert(battle.sides[0].state[0].volatile_count == count_before);
    assert(battle.condition_traces[battle.condition_trace_count - 1].operation ==
        POKEMON_CONDITION_RESTART);
    assert(pokemon_battle_check_invariants(&battle));
}

static void test_source_base_max_hp_fraction_contact_damage(void) {
    enum { TEST_ROUGH_ABILITY = 62100, TEST_ROUGH_HANDLER = 62101 };
    PokemonAbilityData ability = {
        .id = TEST_ROUGH_ABILITY, .handler_offset = 0, .handler_count = 1,
    };
    PokemonHandlerDescriptor handler = {
        .event = POKEMON_HANDLER_EVENT_DAMAGING_HIT,
        .id = TEST_ROUGH_HANDLER,
        .source_kind = POKEMON_HANDLER_SOURCE_ABILITY,
        .source_id = TEST_ROUGH_ABILITY,
        .program_offset = 0, .program_count = 2,
        .scope = POKEMON_HANDLER_SCOPE_TARGET,
        .route = POKEMON_HANDLER_ROUTE_OWNER,
        .raw_hook = "onDamagingHit",
    };
    PokemonOwnerBindingIndex binding = {
        .owner_kind = POKEMON_OWNER_ABILITY,
        .owner_id = TEST_ROUGH_ABILITY,
        .event = POKEMON_HANDLER_EVENT_DAMAGING_HIT,
        .scope = POKEMON_HANDLER_SCOPE_TARGET,
        .route = POKEMON_HANDLER_ROUTE_OWNER,
        .binding_offset = 0, .binding_count = 1,
    };
    PokemonHandlerOp programs[2] = {
        {POKEMON_HANDLER_OP_GUARD_MOVE_FLAG, 5},
        {POKEMON_HANDLER_OP_DAMAGE_EVENT_SOURCE_BASE_MAX_HP_FRACTION,
            (1u << 16) | 16u},
    };
    PokemonData data = POKEMON_GEN3_SLICE_DATA;
    PokemonMoveData moves[data.move_count];
    memcpy(moves, data.moves, sizeof(moves));
    for (size_t i = 0; i < data.move_count; i++) moves[i].call_pool_id = 0;
    data.moves = moves;
    data.abilities = &ability;
    data.ability_count = 1;
    data.handlers = &handler;
    data.handler_count = 1;
    data.handler_programs = programs;
    data.handler_program_count = 2;
    data.owner_binding_index = &binding;
    data.owner_binding_index_count = 1;
    data.move_call_pools = NULL; data.move_call_pool_count = 0;
    data.move_call_pool_candidates = NULL;
    data.move_call_pool_candidate_count = 0;
    data.constructed_hit_templates = NULL;
    data.constructed_hit_template_count = 0;
    data.move_pre_use_programs = NULL;
    data.move_pre_use_program_count = 0;
    PokemonResolvedBundle bundle = POKEMON_GEN3_OU_BUNDLE;
    PokemonFormatPolicy policy = *bundle.policy;
    policy.status_clauses = NULL;
    policy.status_clause_count = 0;
    bundle.policy = &policy;
    bundle.data = &data;
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_DOUBLEKICK,
        POKEMON_GEN3_SPECIES_VAPOREON, POKEMON_GEN3_MOVE_SPLASH);
    init.bundle = &bundle;
    init.teams[0].members[0].ability_id = 0;
    init.teams[0].members[0].stats[0] = 33;
    init.initial_hp[0][0] = 33;
    init.teams[1].members[0].ability_id = TEST_ROUGH_ABILITY;
    init.teams[1].members[0].stats[0] = 5000;
    init.teams[1].members[0].stats[2] = 1000;
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].hp == 29);
    const PokemonHitTrace *result =
        &battle.hit_traces[battle.hit_trace_count - 1];
    assert(result->kind == POKEMON_HIT_RESULT);
    assert(result->actual_hits == 2);
    size_t responses = 0;
    for (size_t i = 0; i < battle.event_count; i++) {
        const PokemonEvent *event = &battle.events[i];
        if (event->kind == POKEMON_EVENT_DAMAGE && event->side == 0) {
            assert(event->amount == 2);
            assert(event->target_side == 1);
            responses++;
        }
    }
    assert(responses == 2);
    assert(battle.handlers[0].handler.holder_side == 1);

    /* Fractions below one still deal one damage. */
    init.teams[0].members[0].stats[0] = 15;
    init.initial_hp[0][0] = 15;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].hp == 13);

    /* Fainting the attacker on the first response stops the hit plan. */
    init.initial_hp[0][0] = 1;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    result = &battle.hit_traces[battle.hit_trace_count - 1];
    assert(result->kind == POKEMON_HIT_RESULT);
    assert(result->actual_hits == 1);
    assert(result->stop_reason == POKEMON_HIT_STOP_SOURCE_FAINTED);
    assert(battle.sides[0].state[0].fainted);
    assert(pokemon_battle_check_invariants(&battle));
}

static void test_recharge_synthetic_hard_lock_lifecycle(void) {
    static const uint16_t recharge_moves[] = {
        POKEMON_GEN3_MOVE_HYPERBEAM, POKEMON_GEN3_MOVE_BLASTBURN,
        POKEMON_GEN3_MOVE_FRENZYPLANT, POKEMON_GEN3_MOVE_HYDROCANNON,
    };
    const PokemonHandlerDescriptor *start =
        &POKEMON_GEN3_SLICE_DATA.handlers[
            POKEMON_GEN3_HANDLER_MUST_RECHARGE_START - 1];
    assert(start->id == POKEMON_GEN3_HANDLER_MUST_RECHARGE_START);
    assert(start->event == POKEMON_HANDLER_EVENT_START);
    assert(start->source_kind == POKEMON_HANDLER_SOURCE_CONDITION);
    assert(start->source_id ==
        POKEMON_GEN3_CONDITION_VOLATILE_MUSTRECHARGE);
    assert(start->program_count == 0);
    for (size_t i = 0;
            i < POKEMON_GEN3_SLICE_DATA.owner_binding_index_count; i++) {
        const PokemonOwnerBindingIndex *binding =
            &POKEMON_GEN3_SLICE_DATA.owner_binding_index[i];
        assert(!(binding->owner_kind == POKEMON_OWNER_VOLATILE &&
            binding->owner_id ==
                POKEMON_GEN3_CONDITION_VOLATILE_MUSTRECHARGE &&
            binding->event == POKEMON_HANDLER_EVENT_START));
    }
    for (size_t i = 0; i < sizeof(recharge_moves) / sizeof(recharge_moves[0]); i++) {
        const PokemonMoveData *move_data = NULL;
        for (size_t j = 0; j < POKEMON_GEN3_SLICE_DATA.move_count; j++) {
            if (POKEMON_GEN3_SLICE_DATA.moves[j].id == recharge_moves[i]) {
                move_data = &POKEMON_GEN3_SLICE_DATA.moves[j];
                break;
            }
        }
        assert(move_data != NULL && move_data->effect_count == 1);
        const PokemonEffectOp *effect = &POKEMON_GEN3_SLICE_DATA.effects[
            move_data->effect_offset];
        assert(effect->kind == POKEMON_EFFECT_ADD_VOLATILE);
        assert(effect->phase == POKEMON_EFFECT_PHASE_AFTER_MOVE);
        assert(effect->target == POKEMON_EFFECT_TARGET_USER);
        assert(effect->argument == POKEMON_VOLATILE_MUST_RECHARGE);
    }
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SNORLAX, POKEMON_GEN3_MOVE_HYPERBEAM,
        POKEMON_GEN3_SPECIES_METAGROSS, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[1].members[0].stats[0] = 600;
    init.teams[1].members[0].stats[2] = 400;
    init.initial_hp[1][0] = 600;
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    PokemonBattle battle;
    uint8_t connected = 0;
    for (uint16_t tail = 1; tail < 4096 && !connected; tail++) {
        init.seed[3] = tail;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        connected = test_volatile_index(
            &battle.sides[0].state[0], POKEMON_VOLATILE_MUST_RECHARGE) >= 0;
    }
    assert(connected);
    assert(battle.request.legal_moves[0] == 1);
    assert(battle.request.legal_switches[0] == 0);
    assert(battle.request.forced_move_id[0] == POKEMON_GEN3_MOVE_RECHARGE);
    uint8_t hyper_beam_pp = battle.sides[0].state[0].pp[0];
    uint16_t last_move = battle.sides[0].state[0].last_move_id;
    assert(last_move == POKEMON_GEN3_MOVE_HYPERBEAM);

    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(test_volatile_index(
        &battle.sides[0].state[0], POKEMON_VOLATILE_MUST_RECHARGE) < 0);
    assert(battle.sides[0].state[0].pp[0] == hyper_beam_pp);
    assert(battle.sides[0].state[0].last_move_id == last_move);
    assert(battle.request.forced_move_id[0] == 0);
    assert(battle.request.legal_switches[0] != 0);
    uint8_t found_prevent = 0;
    for (size_t i = 0; i < battle.handler_count; i++) {
        const PokemonHandlerInvocation *handler = &battle.handlers[i];
        found_prevent |= handler->handler.descriptor.event ==
                POKEMON_HANDLER_EVENT_BEFORE_MOVE &&
            handler->handler.descriptor.source_id ==
                POKEMON_GEN3_CONDITION_VOLATILE_MUSTRECHARGE &&
            handler->handler.descriptor.priority == 11 &&
            handler->result == POKEMON_HANDLER_PREVENT;
    }
    assert(found_prevent);
    assert(pokemon_battle_check_invariants(&battle));

    uint8_t missed = 0;
    for (uint16_t tail = 1; tail < 4096 && !missed; tail++) {
        init.seed[3] = tail;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        missed = event_kind_count(&battle, POKEMON_EVENT_MISS) != 0;
        if (missed) {
            assert(test_volatile_index(
                &battle.sides[0].state[0], POKEMON_VOLATILE_MUST_RECHARGE) < 0);
            assert(battle.request.forced_move_id[0] == 0);
            assert(battle.request.legal_switches[0] != 0);
        }
    }
    assert(missed);
}

static void test_safeguard_generic_admission_and_lifecycle(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_ALAKAZAM, POKEMON_GEN3_MOVE_SAFEGUARD,
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[0].members[0].stats[5] = 200;
    init.teams[1].members[0].stats[5] = 100;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].condition_count == 1);
    assert(battle.sides[0].conditions[0].kind ==
        POKEMON_SIDE_CONDITION_SAFEGUARD);
    assert(battle.sides[0].conditions[0].duration == 4);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].condition_count == 1);
    assert(battle.sides[0].conditions[0].duration == 3);

    uint8_t applied = 1;
    size_t draw_count = battle.draw_count;
    assert(pokemon_set_status(
        &battle, (PokemonEntityRef){POKEMON_ENTITY_POKEMON, 0, 0},
        POKEMON_STATUS_PARALYSIS,
        (PokemonEntityRef){POKEMON_ENTITY_POKEMON, 1, 0},
        (PokemonSourceEffectRef){POKEMON_SOURCE_EFFECT_MOVE,
            POKEMON_GEN3_MOVE_THUNDERWAVE}, 0, &applied) == POKEMON_OK);
    assert(!applied);
    assert(battle.sides[0].state[0].status.kind == POKEMON_STATUS_NONE);
    assert(battle.draw_count == draw_count + 1);
    assert(battle.draws[draw_count].label ==
        POKEMON_DRAW_EVENT_HANDLER_ORDER);
    assert(battle.draws[draw_count].context_event_id ==
        POKEMON_HANDLER_EVENT_SET_STATUS);
    assert(battle.draws[draw_count].lower_bound == 1);
    assert(battle.draws[draw_count].upper_bound == 2);
    uint8_t saw_safeguard_handler = 0;
    for (size_t i = 0; i < battle.handler_count; i++) {
        saw_safeguard_handler |=
            battle.handlers[i].handler.descriptor.id ==
                POKEMON_GEN3_HANDLER_SAFEGUARD_SET_STATUS &&
            battle.handlers[i].invoked;
    }
    assert(saw_safeguard_handler);

    PokemonEventFrame confusion;
    assert(pokemon_run_event(&battle, &(PokemonEventInput){
        .event = POKEMON_HANDLER_EVENT_TRY_ADD_VOLATILE,
        .source = {POKEMON_ENTITY_POKEMON, 1, 0},
        .target_side = 0, .target_slot = 0,
        .source_effect = {POKEMON_SOURCE_EFFECT_MOVE,
            POKEMON_GEN3_MOVE_CONFUSERAY},
        .relay = {.kind = POKEMON_RELAY_BOOLEAN, .value.boolean = 1},
        .context_kind = POKEMON_EVENT_CONTEXT_VOLATILE,
        .context.volatile_condition = {.kind = POKEMON_VOLATILE_CONFUSION},
    }, &confusion) == POKEMON_OK);
    assert(confusion.cancellation == POKEMON_EVENT_CANCEL_NULL);

    PokemonEventFrame self_confusion;
    assert(pokemon_run_event(&battle, &(PokemonEventInput){
        .event = POKEMON_HANDLER_EVENT_TRY_ADD_VOLATILE,
        .source = {POKEMON_ENTITY_POKEMON, 0, 0},
        .target_side = 0, .target_slot = 0,
        .source_effect = {POKEMON_SOURCE_EFFECT_MOVE,
            POKEMON_GEN3_MOVE_CONFUSERAY},
        .relay = {.kind = POKEMON_RELAY_BOOLEAN, .value.boolean = 1},
        .context_kind = POKEMON_EVENT_CONTEXT_VOLATILE,
        .context.volatile_condition = {.kind = POKEMON_VOLATILE_CONFUSION},
    }, &self_confusion) == POKEMON_OK);
    assert(self_confusion.cancellation == POKEMON_EVENT_CANCEL_NONE);
    assert(self_confusion.relay.value.boolean);
}

static void test_yawn_delayed_status_lifecycle(void) {
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_TORKOAL, POKEMON_GEN3_MOVE_YAWN,
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_SPLASH);
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    int yawn = test_volatile_index(
        &battle.sides[1].state[0], POKEMON_VOLATILE_YAWN);
    assert(yawn >= 0);
    assert(battle.sides[1].state[0].volatiles[yawn].duration == 1);
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 0);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(test_volatile_index(
        &battle.sides[1].state[0], POKEMON_VOLATILE_YAWN) < 0);
    assert(battle.sides[1].state[0].status.kind == POKEMON_STATUS_SLEEP);
    assert(draw_label_count(&battle, POKEMON_DRAW_SLEEP_DURATION) == 1);
    assert(pokemon_battle_check_invariants(&battle));

    init = condition_init(
        POKEMON_GEN3_SPECIES_TORKOAL, POKEMON_GEN3_MOVE_YAWN,
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_SPLASH);
    init.initial_status[1][0] = POKEMON_STATUS_POISON;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(test_volatile_index(
        &battle.sides[1].state[0], POKEMON_VOLATILE_YAWN) < 0);

    init.initial_status[1][0] = POKEMON_STATUS_NONE;
    const uint16_t yawn_immunities[] = {
        POKEMON_GEN3_ABILITY_INSOMNIA,
        POKEMON_GEN3_ABILITY_VITALSPIRIT,
    };
    for (size_t i = 0; i < sizeof(yawn_immunities) /
            sizeof(yawn_immunities[0]); i++) {
        init.teams[1].members[0].ability_id = yawn_immunities[i];
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        assert(test_volatile_index(
            &battle.sides[1].state[0], POKEMON_VOLATILE_YAWN) < 0);
    }

    init = condition_init(
        POKEMON_GEN3_SPECIES_ALAKAZAM, POKEMON_GEN3_MOVE_SAFEGUARD,
        POKEMON_GEN3_SPECIES_TORKOAL, POKEMON_GEN3_MOVE_YAWN);
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(test_volatile_index(
        &battle.sides[0].state[0], POKEMON_VOLATILE_YAWN) < 0);

    init = condition_init(
        POKEMON_GEN3_SPECIES_TORKOAL, POKEMON_GEN3_MOVE_YAWN,
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[0].members[0].move_ids[1] = POKEMON_GEN3_MOVE_SPLASH;
    init.teams[1].members[0].move_ids[1] = POKEMON_GEN3_MOVE_SAFEGUARD;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    PokemonChoice second[POKEMON_SIDES] = {move(1), move(1)};
    assert(pokemon_battle_step(&battle, second) == POKEMON_OK);
    assert(battle.sides[1].condition_count == 1);
    assert(battle.sides[1].conditions[0].kind ==
        POKEMON_SIDE_CONDITION_SAFEGUARD);
    assert(battle.sides[1].state[0].status.kind == POKEMON_STATUS_SLEEP);
    assert(test_volatile_index(
        &battle.sides[1].state[0], POKEMON_VOLATILE_YAWN) < 0);
    assert(pokemon_battle_check_invariants(&battle));
}

static void test_nightmare_generated_lifecycle(void) {
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_GENGAR, POKEMON_GEN3_MOVE_NIGHTMARE,
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_SPLASH);
    PokemonBattle battle;

    /* Gen 3 Nightmare is always-hit, but its generated Start handler rejects
     * an awake holder before installation and consumes no accuracy draw. */
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(test_volatile_index(
        &battle.sides[1].state[0], POKEMON_VOLATILE_NIGHTMARE) < 0);
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 0);

    init.initial_status[1][0] = POKEMON_STATUS_SLEEP;
    init.initial_sleep_time[1][0] = 3;
    init.teams[1].members[0].stats[0] = 400;
    init.seed[0] = 811;
    init.seed[1] = 17;
    init.seed[2] = 43;
    init.seed[3] = 11;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(battle.sides[1].state[0].status.state.sleep.time > 1);
    uint16_t hp_before = battle.sides[1].state[0].hp;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    int nightmare = test_volatile_index(
        &battle.sides[1].state[0], POKEMON_VOLATILE_NIGHTMARE);
    assert(nightmare >= 0);
    assert(battle.sides[1].state[0].volatiles[nightmare].duration == 0);
    assert(battle.sides[1].state[0].hp == hp_before - 100);
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 0);
    assert(handler_event_count(&battle, POKEMON_HANDLER_EVENT_START) >= 1);
    assert(handler_event_count(&battle, POKEMON_HANDLER_EVENT_RESIDUAL) >= 1);
    assert(pokemon_battle_check_invariants(&battle));
}

static void test_team_major_status_cure_handlers(void) {
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_AROMATHERAPY,
        POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_SPLASH);
    init.team_sizes[0] = 3;
    init.teams[0].members[1] = make_set(
        POKEMON_GEN3_SPECIES_MILOTIC, POKEMON_GEN3_MOVE_SPLASH,
        220, 100, 100, 100, 100, 100);
    init.teams[0].members[2] = make_set(
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SPLASH,
        220, 100, 100, 100, 100, 100);
    init.initial_status[0][0] = POKEMON_STATUS_POISON;
    init.initial_status[0][1] = POKEMON_STATUS_TOXIC;
    init.initial_status[0][2] = POKEMON_STATUS_SLEEP;
    init.initial_sleep_time[0][2] = 3;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    PokemonEffectResult added = POKEMON_EFFECT_FAILED;
    assert(pokemon_try_add_or_restart_volatile(
        &battle, (PokemonEntityRef){POKEMON_ENTITY_POKEMON, 0, 2},
        (PokemonEntityRef){POKEMON_ENTITY_POKEMON, 1, 0},
        (PokemonSourceEffectRef){POKEMON_SOURCE_EFFECT_MOVE,
            POKEMON_GEN3_MOVE_NIGHTMARE},
        POKEMON_VOLATILE_NIGHTMARE, POKEMON_CONDITION_REASON_MOVE,
        &added) == POKEMON_OK && added == POKEMON_EFFECT_APPLIED);
    size_t effects_before = battle.effect_trace_count;
    size_t draws_before = battle.draw_count;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    for (size_t slot = 0; slot < 3; slot++) {
        assert(battle.sides[0].state[slot].status.kind == POKEMON_STATUS_NONE);
    }
    assert(test_volatile_index(
        &battle.sides[0].state[2], POKEMON_VOLATILE_NIGHTMARE) < 0);
    assert(battle.effect_trace_count == effects_before);
    for (size_t i = draws_before; i < battle.draw_count; i++) {
        assert(battle.draws[i].label != POKEMON_DRAW_ACCURACY);
    }
    assert(handler_event_count(
        &battle, POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK) >= 1);
    assert(pokemon_battle_check_invariants(&battle));

    init.teams[0].members[0].move_ids[0] = POKEMON_GEN3_MOVE_HEALBELL;
    init.initial_status[0][2] = POKEMON_STATUS_BURN;
    init.initial_sleep_time[0][2] = 0;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    effects_before = battle.effect_trace_count;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].status.kind == POKEMON_STATUS_NONE);
    assert(battle.sides[0].state[1].status.kind == POKEMON_STATUS_NONE);
    assert(battle.sides[0].state[2].status.kind == POKEMON_STATUS_NONE);
    assert(battle.effect_trace_count == effects_before + 3);
    assert(battle.effect_traces[effects_before].target_slot == 0);
    assert(battle.effect_traces[effects_before + 1].target_slot == 1);
    assert(battle.effect_traces[effects_before + 2].target_slot == 2);
    assert(pokemon_battle_check_invariants(&battle));

}

static void test_spikes_layered_side_condition_and_entry_hazard(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SKARMORY, POKEMON_GEN3_MOVE_SPIKES,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[0].members[0].ability_id = POKEMON_GEN3_ABILITY_STURDY;
    PokemonBattle battle;
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    for (uint8_t layer = 1; layer <= 3; layer++) {
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        assert(battle.sides[1].condition_count == 1);
        assert(battle.sides[1].conditions[0].kind ==
            POKEMON_SIDE_CONDITION_SPIKES);
        assert(battle.sides[1].conditions[0].duration == 0);
        assert(battle.sides[1].conditions[0].counter == layer);
        for (size_t i = 0; i < battle.handler_count; i++) {
            assert(battle.handlers[i].handler.descriptor.id !=
                POKEMON_GEN3_HANDLER_STURDY_TRY_HIT);
        }
        assert(pokemon_battle_check_invariants(&battle));
    }
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].conditions[0].counter == 3);
    uint16_t hp_before = battle.sides[1].state[0].hp;
    PokemonEventFrame hazard;
    assert(pokemon_run_event(&battle, &(PokemonEventInput){
        .event = POKEMON_HANDLER_EVENT_ENTRY_HAZARD,
        .source = {POKEMON_ENTITY_POKEMON, 1, 0},
        .target_side = 1, .target_slot = 0,
        .relay = {.kind = POKEMON_RELAY_BOOLEAN, .value.boolean = 1},
    }, &hazard) == POKEMON_OK);
    uint16_t expected = battle.sides[1].sets[0].stats[0] / 4;
    if (expected == 0) expected = 1;
    assert(battle.sides[1].state[0].hp == hp_before - expected);
    assert(pokemon_battle_check_invariants(&battle));
}

static void test_entry_hazard_ko_skips_incoming_start_lifecycle(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SKARMORY, POKEMON_GEN3_MOVE_SPIKES,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[0].members[0].move_ids[1] = POKEMON_GEN3_MOVE_SPLASH;
    init.teams[1].members[1] = make_set(
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SPLASH,
        8, 56, 56, 186, 306, 146);
    init.teams[1].members[1].ability_id = POKEMON_GEN3_ABILITY_PRESSURE;
    init.initial_hp[1][1] = 1;
    PokemonBattle battle;
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};

    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].condition_count == 1);
    assert(battle.sides[1].conditions[0].kind ==
        POKEMON_SIDE_CONDITION_SPIKES);

    choices[0] = move(1);
    choices[1] = switch_to(1);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].active == 1);
    assert(battle.sides[1].state[1].hp == 0);
    for (size_t i = 0; i < battle.handler_count; i++) {
        assert(battle.handlers[i].handler.descriptor.id !=
            POKEMON_GEN3_HANDLER_PRESSURE_START);
    }
    assert(pokemon_battle_check_invariants(&battle));
}

static void test_initial_run_switch_lifecycle_order(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_GOLDUCK, POKEMON_GEN3_MOVE_SPLASH,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[0].members[0].ability_id = POKEMON_GEN3_ABILITY_PRESSURE;
    init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_PRESSURE;
    init.teams[0].members[0].stats[5] = 80;
    init.teams[1].members[0].stats[5] = 180;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(battle.events[0].kind == POKEMON_EVENT_SWITCH);
    assert(battle.events[0].side == 0);
    assert(battle.events[1].kind == POKEMON_EVENT_SWITCH);
    assert(battle.events[1].side == 1);
    assert(battle.handler_count == 2);
    assert(battle.handlers[0].handler.owner.side == 1);
    assert(battle.handlers[1].handler.owner.side == 0);
    assert(draw_label_count(&battle, POKEMON_DRAW_QUEUE_TIE) == 0);

    init.teams[0].members[0].stats[5] = 180;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(draw_label_count(&battle, POKEMON_DRAW_QUEUE_TIE) == 1);
    size_t tie = 0;
    while (battle.draws[tie].label != POKEMON_DRAW_QUEUE_TIE) tie++;
    assert(battle.draws[tie].upper_bound == 2);
    assert(battle.handler_count == 2);
    assert(battle.handlers[0].handler.owner.side ==
        (battle.draws[tie].result == 0 ? 1 : 0));
}

static void test_run_switch_faint_update_request_boundary(void) {
    PokemonBattleInit init = battle_init();
    init.teams[0].members[1].ability_id = POKEMON_GEN3_ABILITY_PRESSURE;
    init.teams[0].members[1].stats[5] = 300;
    init.teams[1].members[1].ability_id = POKEMON_GEN3_ABILITY_OWNTEMPO;
    init.teams[1].members[1].stats[5] = 100;
    init.initial_hp[0][1] = 1;
    init.team_sizes[0] = 3;
    init.teams[0].members[2] = make_set(
        POKEMON_GEN3_SPECIES_MACHOP, POKEMON_GEN3_MOVE_SPLASH,
        50, 80, 80, 80, 80, 80);
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    for (size_t side = 0; side < POKEMON_SIDES; side++) {
        battle.sides[side].state[0].hp = 0;
        battle.sides[side].state[0].fainted = 1;
        battle.request.kind[side] = POKEMON_REQUEST_SWITCH;
        battle.request.legal_moves[side] = 0;
        battle.request.legal_switches[side] = 2;
    }
    battle.request.required_sides = 3;
    battle.phase = POKEMON_PHASE_FORCED_REPLACEMENT;
    battle.turn_suspended = 1;
    battle.sides[0].conditions[0] = (PokemonSideConditionState){
        .kind = POKEMON_SIDE_CONDITION_SPIKES,
        .descriptor_id = POKEMON_GEN3_CONDITION_SIDE_SPIKES,
        .counter = 3, .state_generation = 1,
        .effect_order = ++battle.next_holder_effect_order,
    };
    battle.sides[0].condition_count = 1;
    PokemonChoice choices[POKEMON_SIDES] = {switch_to(1), switch_to(1)};
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[1].fainted);
    assert(battle.sides[1].active == 1);
    assert(battle.request.kind[0] == POKEMON_REQUEST_SWITCH);
    assert(battle.request.kind[1] == POKEMON_REQUEST_WAIT);
    assert(battle.phase == POKEMON_PHASE_FORCED_REPLACEMENT);
    assert(pokemon_battle_check_invariants(&battle));
}

static void test_atomic_copy_boost_stage_product(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_VAPOREON, POKEMON_GEN3_MOVE_SPLASH,
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SPLASH);
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);

    PokemonHandlerOp program = {
        POKEMON_HANDLER_OP_COPY_EVENT_TARGET_BOOST_STAGES_TO_SOURCE, 0};
    PokemonData data = POKEMON_GEN3_SLICE_DATA;
    data.handler_programs = &program;
    data.handler_program_count = 1;
    battle.data = &data;
    const PokemonMoveData *splash = generated_move(POKEMON_GEN3_MOVE_SPLASH);
    assert(splash != NULL);

    const int8_t source_before[POKEMON_STAT_COUNT] = {6, 5, 4, 3, 2, 1, 0};
    const int8_t target_product[POKEMON_STAT_COUNT] = {-6, -4, -2, 0, 2, 4, 6};
    memcpy(battle.sides[0].state[0].boosts, source_before, sizeof(source_before));
    memcpy(battle.sides[1].state[0].boosts, target_product, sizeof(target_product));
    uint8_t draws_before = battle.draw_count;
    size_t traces_before = battle.handler_count;

    PokemonEventFrame frame;
    assert(pokemon_run_event(&battle, &(PokemonEventInput){
        .event = POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK,
        .source = {POKEMON_ENTITY_POKEMON, 0, 0},
        .target_side = 1, .target_slot = 0,
        .source_effect = {POKEMON_SOURCE_EFFECT_MOVE, splash->id},
        .relay = {.kind = POKEMON_RELAY_BOOLEAN, .value.boolean = 1},
        .context_kind = POKEMON_EVENT_CONTEXT_MOVE,
        .context.move = {.move = splash},
        .has_only_handler = 1,
        .only_handler = {
            .descriptor = {
                .event = POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK,
                .id = 65000,
                .source_kind = POKEMON_HANDLER_SOURCE_MOVE,
                .source_id = POKEMON_GEN3_MOVE_SPLASH,
                .program_offset = 0, .program_count = 1,
                .scope = POKEMON_HANDLER_SCOPE_SOURCE,
                .route = POKEMON_HANDLER_ROUTE_MOVE_SELF,
            },
            .owner = {POKEMON_OWNER_MOVE, 0, 0, POKEMON_GEN3_MOVE_SPLASH, 1},
            .holder_side = 1, .holder_slot = 0,
        },
    }, &frame) == POKEMON_OK);
    assert(memcmp(battle.sides[0].state[0].boosts, target_product,
        sizeof(target_product)) == 0);
    assert(memcmp(battle.sides[1].state[0].boosts, target_product,
        sizeof(target_product)) == 0);
    assert(battle.draw_count == draws_before);
    assert(battle.handler_count == traces_before + 1);
    assert(frame.executed_count == 1 && frame.skipped_count == 0);
    assert(frame.relay.kind == POKEMON_RELAY_BOOLEAN && frame.relay.value.boolean);
    assert(pokemon_battle_check_invariants(&battle));
}

static void test_post_hit_self_drop_product(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_MACHOP, POKEMON_GEN3_MOVE_SUPERPOWER,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[0].members[0].ability_id = POKEMON_GEN3_ABILITY_CLEARBODY;
    PokemonBattle battle;
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].boosts[POKEMON_STAT_ATK] == -1);
    assert(battle.sides[0].state[0].boosts[POKEMON_STAT_DEF] == -1);
    size_t secondary_draws = 0;
    for (size_t i = 0; i < battle.draw_count; i++) {
        secondary_draws += battle.draws[i].label == POKEMON_DRAW_SECONDARY;
    }
    assert(secondary_draws == 1);
    assert(battle.effect_trace_count == 2);
    assert(battle.effect_traces[0].phase == POKEMON_EFFECT_PHASE_SELF_DROP);
    assert(battle.effect_traces[1].phase == POKEMON_EFFECT_PHASE_SELF_DROP);
    assert(pokemon_battle_check_invariants(&battle));
}

static void test_haze_field_hit_and_pressure_targeting(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_VAPOREON, POKEMON_GEN3_MOVE_HAZE,
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SPLASH);
    PokemonBattle battle;
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    const int8_t left[POKEMON_STAT_COUNT] = {6, 5, 4, 3, 2, 1, -1};
    const int8_t right[POKEMON_STAT_COUNT] = {-6, -5, -4, -3, -2, -1, 1};
    memcpy(battle.sides[0].state[0].boosts, left, sizeof(left));
    memcpy(battle.sides[1].state[0].boosts, right, sizeof(right));
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    const int8_t zero[POKEMON_STAT_COUNT] = {0};
    assert(memcmp(battle.sides[0].state[0].boosts, zero, sizeof(zero)) == 0);
    assert(memcmp(battle.sides[1].state[0].boosts, zero, sizeof(zero)) == 0);
    uint8_t saw_field_hit = 0;
    for (size_t i = 0; i < battle.handler_count; i++) {
        saw_field_hit |= battle.handlers[i].handler.descriptor.id ==
            POKEMON_GEN3_HANDLER_HAZE_HIT_FIELD;
    }
    assert(saw_field_hit);
    assert(pokemon_battle_check_invariants(&battle));

    init = condition_init(
        POKEMON_GEN3_SPECIES_VAPOREON, POKEMON_GEN3_MOVE_HAZE,
        POKEMON_GEN3_SPECIES_DUSCLOPS, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_PRESSURE;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    uint8_t pp_before = battle.sides[0].state[0].pp[0];
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].pp[0] + 2 == pp_before);
    assert(pokemon_battle_check_invariants(&battle));
}

static void test_generated_sleep_start_program(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_GENGAR, POKEMON_GEN3_MOVE_SPLASH,
        POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_SPLASH);
    PokemonEntityRef source = {POKEMON_ENTITY_POKEMON, 0, 0};
    PokemonEntityRef target = {POKEMON_ENTITY_POKEMON, 1, 0};
    PokemonSourceEffectRef effect = {POKEMON_SOURCE_EFFECT_CONDITION, 1};
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    size_t draw_start = battle.draw_count;
    size_t handler_start = battle.handler_count;
    uint8_t applied = 0;
    assert(pokemon_set_status(&battle, target, POKEMON_STATUS_SLEEP, source,
        effect, 0, &applied) == POKEMON_OK && applied);
    assert(battle.sides[1].state[0].status.state.sleep.time >= 2);
    assert(battle.sides[1].state[0].status.state.sleep.time < 6);
    assert(battle.sides[1].state[0].status.state.sleep.skipped_time == 0);
    size_t sleep_draws = 0;
    size_t sleep_draw_index = 0;
    for (size_t i = draw_start; i < battle.draw_count; i++) {
        if (battle.draws[i].label == POKEMON_DRAW_SLEEP_DURATION) {
            sleep_draws++;
            sleep_draw_index = i;
        }
    }
    assert(sleep_draws == 1);
    assert(battle.draws[sleep_draw_index].upper_bound == 4);
    uint8_t saw_status_start = 0;
    for (size_t i = handler_start; i < battle.handler_count; i++) {
        saw_status_start |= battle.handlers[i].handler.owner.kind ==
                POKEMON_OWNER_STATUS &&
            battle.handlers[i].handler.descriptor.event ==
                POKEMON_HANDLER_EVENT_START;
    }
    assert(saw_status_start);

    PokemonHandlerOp programs[
        POKEMON_GEN3_SLICE_DATA.handler_program_count];
    memcpy(programs, POKEMON_GEN3_SLICE_DATA.handler_programs,
        POKEMON_GEN3_SLICE_DATA.handler_program_count * sizeof(programs[0]));
    const PokemonHandlerDescriptor *sleep_start = NULL;
    for (size_t i = 0; i < POKEMON_GEN3_SLICE_DATA.handler_count; i++) {
        const PokemonHandlerDescriptor *candidate =
            &POKEMON_GEN3_SLICE_DATA.handlers[i];
        if (candidate->source_kind == POKEMON_HANDLER_SOURCE_CONDITION &&
            candidate->source_id == POKEMON_GEN3_CONDITION_STATUS_SLP &&
            candidate->event == POKEMON_HANDLER_EVENT_START) sleep_start = candidate;
    }
    assert(sleep_start != NULL && sleep_start->program_count == 1);
    programs[sleep_start->program_offset].argument =
        (POKEMON_DRAW_SLEEP_DURATION << 24) | (3u << 16) | (4u << 8);
    PokemonData alternate_data = POKEMON_GEN3_SLICE_DATA;
    alternate_data.handler_programs = programs;
    PokemonResolvedBundle alternate_bundle = POKEMON_GEN3_OU_BUNDLE;
    alternate_bundle.data = &alternate_data;
    init.bundle = &alternate_bundle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    applied = 0;
    assert(pokemon_set_status(&battle, target, POKEMON_STATUS_SLEEP, source,
        effect, 0, &applied) == POKEMON_OK && applied);
    assert(battle.sides[1].state[0].status.state.sleep.time == 3);

    PokemonData incomplete_data = POKEMON_GEN3_SLICE_DATA;
    incomplete_data.handler_count = (size_t)(sleep_start -
        POKEMON_GEN3_SLICE_DATA.handlers);
    PokemonResolvedBundle incomplete_bundle = POKEMON_GEN3_OU_BUNDLE;
    incomplete_bundle.data = &incomplete_data;
    init.bundle = &incomplete_bundle;
    PokemonBattle before_invalid_init = battle;
    assert(pokemon_battle_init(&battle, &init) ==
        POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&battle, &before_invalid_init, sizeof(battle)) == 0);

    init.bundle = &POKEMON_GEN3_OU_BUNDLE;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    uint16_t order_before = battle.next_holder_effect_order;
    uint16_t seed_before[4];
    memcpy(seed_before, battle.seed, sizeof(seed_before));
    battle.event_count = POKEMON_EVENT_CAPACITY;
    draw_start = battle.draw_count;
    handler_start = battle.handler_count;
    applied = 1;
    assert(pokemon_set_status(&battle, target, POKEMON_STATUS_SLEEP, source,
        effect, 0, &applied) == POKEMON_CAPACITY_EXCEEDED);
    assert(!applied && battle.sides[1].state[0].status.kind == POKEMON_STATUS_NONE);
    assert(battle.next_holder_effect_order == order_before);
    assert(battle.handler_count == handler_start && battle.draw_count == draw_start);
    assert(memcmp(seed_before, battle.seed, sizeof(seed_before)) == 0);
}

static void install_test_sleep(
    PokemonBattle *battle, uint8_t side, uint8_t slot,
    uint8_t time, uint8_t skipped_time
) {
    PokemonEntityRef holder = {POKEMON_ENTITY_POKEMON, side, slot};
    PokemonSourceEffectRef effect = {POKEMON_SOURCE_EFFECT_CONDITION, 1};
    uint8_t applied = 0;
    assert(pokemon_set_status(battle, holder, POKEMON_STATUS_SLEEP, holder,
        effect, 0, &applied) == POKEMON_OK && applied);
    assert(battle->condition_trace_count != 0);
    const PokemonConditionTrace *added =
        &battle->condition_traces[battle->condition_trace_count - 1u];
    assert(added->scope == POKEMON_CONDITION_SCOPE_STATUS);
    assert(added->operation == POKEMON_CONDITION_ADD);
    assert(added->condition_id == POKEMON_STATUS_SLEEP);
    assert(!added->has_duration_before && added->has_duration_after);
    assert(added->duration_after ==
        battle->sides[side].state[slot].status.state.sleep.time);
    assert(!added->has_counter_before && added->has_counter_after);
    assert(added->counter_after == 0);
    battle->sides[side].state[slot].status.state.sleep.time = time;
    battle->sides[side].state[slot].status.state.sleep.skipped_time = skipped_time;
}

static void test_generated_sleep_lifecycle_programs(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_SPLASH,
        POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_SPLASH);
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    PokemonBattle battle;

    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    install_test_sleep(&battle, 0, 0, 2, 1);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].status.kind == POKEMON_STATUS_SLEEP);
    assert(battle.sides[0].state[0].status.state.sleep.time == 1);
    assert(battle.sides[0].state[0].status.state.sleep.skipped_time == 0);
    assert(draw_label_count(&battle, POKEMON_DRAW_SLEEP_DURATION) == 0);
    assert(handler_event_count(&battle, POKEMON_HANDLER_EVENT_BEFORE_MOVE) >= 1);
    assert(pokemon_battle_check_invariants(&battle));

    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    install_test_sleep(&battle, 0, 0, 1, 2);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].status.kind == POKEMON_STATUS_NONE);
    assert(pokemon_battle_check_invariants(&battle));

    init.teams[0].members[0].move_ids[0] = POKEMON_GEN3_MOVE_SNORE;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    install_test_sleep(&battle, 0, 0, 3, 0);
    uint16_t target_hp = battle.sides[1].state[0].hp;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].status.kind == POKEMON_STATUS_SLEEP);
    assert(battle.sides[0].state[0].status.state.sleep.time == 2);
    assert(battle.sides[0].state[0].status.state.sleep.skipped_time == 1);
    assert(battle.sides[1].state[0].hp < target_hp);
    assert(pokemon_battle_check_invariants(&battle));

    init.teams[0].members[0].ability_id = POKEMON_GEN3_ABILITY_EARLYBIRD;
    init.teams[0].members[0].move_ids[0] = POKEMON_GEN3_MOVE_SPLASH;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    install_test_sleep(&battle, 0, 0, 2, 0);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].status.kind == POKEMON_STATUS_NONE);
    assert(pokemon_battle_check_invariants(&battle));

    init.team_sizes[0] = 2;
    init.teams[0].members[1] = make_set(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_SPLASH,
        220, 100, 100, 100, 100, 100);
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    install_test_sleep(&battle, 0, 1, 2, 1);
    PokemonChoice switch_choices[POKEMON_SIDES] = {switch_to(1), move(0)};
    assert(pokemon_battle_step(&battle, switch_choices) == POKEMON_OK);
    assert(battle.sides[0].active == 1);
    assert(battle.sides[0].state[1].status.state.sleep.time == 3);
    assert(battle.sides[0].state[1].status.state.sleep.skipped_time == 0);
    assert(handler_event_count(&battle, POKEMON_HANDLER_EVENT_SWITCH_IN) >= 1);
    assert(pokemon_battle_check_invariants(&battle));
}

static void test_shared_turn_speed_item_policy(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_SPLASH,
        POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[0].members[0].item_id = POKEMON_GEN3_ITEM_QUICKCLAW;
    init.teams[0].members[0].stats[5] = 50;
    init.teams[1].members[0].stats[5] = 200;
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    uint8_t saw_active = 0;
    uint8_t saw_inactive = 0;
    for (uint16_t tail = 1; tail < 256 && !(saw_active && saw_inactive); tail++) {
        init.seed[3] = tail;
        PokemonBattle battle;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        uint8_t active = battle.shared_turn_speed_active;
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        assert(battle.last_queue.count == 2);
        if (active) {
            saw_active = 1;
            assert(battle.last_queue.values[0].side == 0);
            assert(battle.last_queue.values[0].speed == UINT16_MAX);
        } else {
            saw_inactive = 1;
            assert(battle.last_queue.values[0].side == 1);
            assert(battle.last_queue.values[1].speed == 50);
        }
        assert(draw_label_count(&battle, POKEMON_DRAW_END_TURN) == 1);
        assert(pokemon_battle_check_invariants(&battle));
    }
    assert(saw_active && saw_inactive);

    /* Action priority remains ahead of the generation's speed sentinel. */
    init.teams[1].members[0].move_ids[0] = POKEMON_GEN3_MOVE_QUICKATTACK;
    uint8_t proved_priority = 0;
    for (uint16_t tail = 1; tail < 256 && !proved_priority; tail++) {
        init.seed[3] = tail;
        PokemonBattle battle;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        if (!battle.shared_turn_speed_active) continue;
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        assert(battle.last_queue.values[0].side == 1);
        assert(battle.last_queue.values[0].priority == 1);
        assert(battle.last_queue.values[1].speed == UINT16_MAX);
        proved_priority = 1;
    }
    assert(proved_priority);

    /* A bundle cannot advertise an eligible item with the policy disabled. */
    PokemonGeneration disabled = POKEMON_GEN3_RULES;
    memset(&disabled.shared_turn_speed, 0, sizeof(disabled.shared_turn_speed));
    PokemonResolvedBundle invalid_bundle = POKEMON_GEN3_OU_BUNDLE;
    invalid_bundle.rules = &disabled;
    init.bundle = &invalid_bundle;
    PokemonBattle untouched;
    memset(&untouched, 0xa5, sizeof(untouched));
    PokemonBattle before = untouched;
    assert(pokemon_battle_init(&untouched, &init) ==
        POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&untouched, &before, sizeof(untouched)) == 0);
}

static void test_generated_grouped_secondary_products(void) {
    const uint16_t moves[] = {
        POKEMON_GEN3_MOVE_ANCIENTPOWER, POKEMON_GEN3_MOVE_SILVERWIND,
    };
    for (size_t move_index = 0; move_index < 2; move_index++) {
        const PokemonMoveData *move_data = NULL;
        for (size_t i = 0; i < POKEMON_GEN3_SLICE_DATA.move_count; i++) {
            if (POKEMON_GEN3_SLICE_DATA.moves[i].id == moves[move_index]) {
                move_data = &POKEMON_GEN3_SLICE_DATA.moves[i];
                break;
            }
        }
        assert(move_data != NULL && move_data->effect_count == 5);
        uint8_t group = POKEMON_GEN3_SLICE_DATA.effect_secondary_groups[
            move_data->effect_offset];
        assert(group != 0);
        for (size_t stat = POKEMON_STAT_ATK; stat <= POKEMON_STAT_SPE; stat++) {
            size_t effect_index = move_data->effect_offset + stat;
            const PokemonEffectOp *effect =
                &POKEMON_GEN3_SLICE_DATA.effects[effect_index];
            assert(POKEMON_GEN3_SLICE_DATA.effect_secondary_groups[
                effect_index] == group);
            assert(effect->kind == POKEMON_EFFECT_BOOST);
            assert(effect->phase == POKEMON_EFFECT_PHASE_AFTER_HIT);
            assert(effect->target == POKEMON_EFFECT_TARGET_USER);
            assert(effect->chance == 10 && effect->argument == stat &&
                effect->amount == 1);
        }
    }
    assert(POKEMON_GEN3_SLICE_DATA.secondary_chance_policy_count == 1);
    assert(POKEMON_GEN3_SLICE_DATA.secondary_chance_policies[0].ability_id ==
        POKEMON_GEN3_ABILITY_SERENEGRACE);
    assert(POKEMON_GEN3_SLICE_DATA.secondary_chance_policies[0].numerator == 2);
    assert(POKEMON_GEN3_SLICE_DATA.secondary_chance_policies[0].denominator == 1);

    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_JIRACHI, POKEMON_GEN3_MOVE_ANCIENTPOWER,
        POKEMON_GEN3_SPECIES_DUSTOX, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[0].members[0].ability_id = POKEMON_GEN3_ABILITY_SERENEGRACE;
    init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_SHIELDDUST;
    init.seed[0] = 811; init.seed[1] = 17; init.seed[2] = 43; init.seed[3] = 11;
    PokemonBattle battle;
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(draw_label_count(&battle, POKEMON_DRAW_SECONDARY) == 1);
    for (size_t stat = POKEMON_STAT_ATK; stat <= POKEMON_STAT_SPE; stat++) {
        assert(battle.sides[0].state[0].boosts[stat] == 1);
    }

    PokemonData incomplete = POKEMON_GEN3_SLICE_DATA;
    incomplete.effect_secondary_group_count--;
    PokemonResolvedBundle bundle = *init.bundle;
    bundle.data = &incomplete;
    init.bundle = &bundle;
    PokemonBattle before;
    memset(&before, 0xA5, sizeof(before));
    battle = before;
    assert(pokemon_battle_init(&battle, &init) ==
        POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&battle, &before, sizeof(battle)) == 0);
}

static void test_sampled_status_secondary_distribution(void) {
    const PokemonMoveData *tri_attack = NULL;
    for (size_t i = 0; i < POKEMON_GEN3_SLICE_DATA.move_count; i++) {
        if (POKEMON_GEN3_SLICE_DATA.moves[i].id ==
                POKEMON_GEN3_MOVE_TRIATTACK) {
            tri_attack = &POKEMON_GEN3_SLICE_DATA.moves[i];
            break;
        }
    }
    assert(tri_attack != NULL && tri_attack->effect_count == 1);
    const PokemonEffectOp *effect = &POKEMON_GEN3_SLICE_DATA.effects[
        tri_attack->effect_offset];
    assert(effect->kind == POKEMON_EFFECT_SET_STATUS_FROM_DISTRIBUTION);
    assert(effect->phase == POKEMON_EFFECT_PHASE_AFTER_HIT);
    assert(effect->target == POKEMON_EFFECT_TARGET_MOVE_TARGET);
    assert(effect->chance == 20 && effect->argument == 1);
    assert(POKEMON_GEN3_SLICE_DATA.status_distribution_count == 1);
    const PokemonStatusDistribution *distribution =
        &POKEMON_GEN3_SLICE_DATA.status_distributions[0];
    assert(distribution->id == 1 && distribution->candidate_offset == 0 &&
        distribution->candidate_count == 3 &&
        distribution->draw_label == POKEMON_DRAW_MOVE_STATUS_SELECTION);
    const PokemonStatus expected[] = {
        POKEMON_STATUS_BURN, POKEMON_STATUS_PARALYSIS, POKEMON_STATUS_FREEZE,
    };
    for (size_t i = 0; i < 3; i++) {
        assert(POKEMON_GEN3_SLICE_DATA.status_distribution_candidates[i] ==
            expected[i]);
    }

    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_PORYGON2, POKEMON_GEN3_MOVE_TRIATTACK,
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[0].members[0].ability_id = 0;
    init.teams[1].members[0].ability_id = 0;
    init.teams[0].members[0].stats[5] = 1;
    init.teams[1].members[0].stats[0] = 1000;
    init.teams[1].members[0].stats[2] = 500;
    init.teams[1].members[0].stats[5] = 500;
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    uint8_t seen = 0;
    uint8_t saw_failed_gate = 0;
    uint16_t successful_seed = 0;
    for (uint16_t tail = 1; tail < 4096 &&
         (seen != 7 || !saw_failed_gate); tail++) {
        init.seed[3] = tail;
        PokemonBattle battle;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        assert(draw_label_count(&battle, POKEMON_DRAW_SECONDARY) == 1);
        size_t selections = draw_label_count(
            &battle, POKEMON_DRAW_MOVE_STATUS_SELECTION);
        if (selections == 0) {
            saw_failed_gate = 1;
            assert(battle.sides[1].state[0].status.kind == POKEMON_STATUS_NONE);
            continue;
        }
        assert(selections == 1);
        uint32_t selected = 3;
        for (size_t draw = 0; draw < battle.draw_count; draw++) {
            if (battle.draws[draw].label !=
                    POKEMON_DRAW_MOVE_STATUS_SELECTION) continue;
            selected = battle.draws[draw].result;
            assert(battle.draws[draw].upper_bound == 3);
        }
        assert(selected < 3);
        assert(battle.sides[1].state[0].status.kind == expected[selected]);
        seen |= (uint8_t)(1u << selected);
        successful_seed = tail;
        assert(pokemon_battle_check_invariants(&battle));
    }
    assert(seen == 7 && saw_failed_gate && successful_seed != 0);

    /* Selection precedes central admission, so an existing status does not
     * refund either move-owned draw. */
    init.seed[3] = successful_seed;
    init.initial_status[1][0] = POKEMON_STATUS_BURN;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].state[0].status.kind == POKEMON_STATUS_BURN);
    assert(draw_label_count(&battle, POKEMON_DRAW_SECONDARY) == 1);
    assert(draw_label_count(
        &battle, POKEMON_DRAW_MOVE_STATUS_SELECTION) == 1);

    /* Shield Dust removes the secondary before its gate. */
    init.initial_status[1][0] = POKEMON_STATUS_NONE;
    init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_SHIELDDUST;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(draw_label_count(&battle, POKEMON_DRAW_SECONDARY) == 0);
    assert(draw_label_count(
        &battle, POKEMON_DRAW_MOVE_STATUS_SELECTION) == 0);

    /* Substitute is later: the chance draw occurs, but callback-owned
     * selection does not target the real holder. */
    init.teams[1].members[0].ability_id = 0;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    PokemonMutable *target = &battle.sides[1].state[0];
    target->volatiles[target->volatile_count++] = (PokemonVolatileState){
        .kind = POKEMON_VOLATILE_SUBSTITUTE,
        .descriptor_id = POKEMON_GEN3_CONDITION_VOLATILE_SUBSTITUTE,
        .state_generation = 1,
        .effect_order = ++battle.next_holder_effect_order,
        .source = {POKEMON_ENTITY_POKEMON, 1, 0},
        .source_effect = {POKEMON_SOURCE_EFFECT_MOVE,
            POKEMON_GEN3_MOVE_SUBSTITUTE},
        .payload.substitute = {.hp = 1},
    };
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(draw_label_count(&battle, POKEMON_DRAW_SECONDARY) == 1);
    assert(draw_label_count(
        &battle, POKEMON_DRAW_MOVE_STATUS_SELECTION) == 0);
    assert(target->status.kind == POKEMON_STATUS_NONE);

    PokemonData invalid = POKEMON_GEN3_SLICE_DATA;
    PokemonStatusDistribution bad = *distribution;
    bad.candidate_count = 0;
    invalid.status_distributions = &bad;
    assert_invalid_resolved_data_is_atomic(init, &invalid);
    bad = *distribution;
    bad.draw_label = POKEMON_DRAW_MOVE_TYPE_SELECTION;
    assert_invalid_resolved_data_is_atomic(init, &invalid);
    uint8_t candidates[] = {
        POKEMON_STATUS_BURN, POKEMON_STATUS_NONE, POKEMON_STATUS_FREEZE,
    };
    invalid = POKEMON_GEN3_SLICE_DATA;
    invalid.status_distribution_candidates = candidates;
    assert_invalid_resolved_data_is_atomic(init, &invalid);
}

static void test_false_swipe_generic_damage_relay(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_FALSESWIPE,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[0].members[0].ability_id = POKEMON_GEN3_ABILITY_OWNTEMPO;
    init.teams[0].members[0].stats[1] = 500;
    init.teams[1].members[0].stats[0] = 500;
    init.teams[1].members[0].stats[2] = 50;
    init.initial_hp[1][0] = 2;
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].state[0].hp == 1);
    assert(!battle.sides[1].state[0].faint_queued);
    assert(battle.request.kind[1] == POKEMON_REQUEST_MOVE);
    assert(handler_event_count(&battle, POKEMON_HANDLER_EVENT_DAMAGE) == 1);
    size_t false_swipe_handler = SIZE_MAX;
    for (size_t i = 0; i < battle.handler_count; i++) {
        if (battle.handlers[i].handler.descriptor.id ==
            POKEMON_GEN3_HANDLER_FALSE_SWIPE_DAMAGE) false_swipe_handler = i;
    }
    assert(false_swipe_handler != SIZE_MAX);
    assert(battle.handlers[false_swipe_handler].handler.holder_side == 1);
    assert(battle.handlers[false_swipe_handler].handler.holder_slot == 0);

    /* Numeric zero is a successful Damage relay result: the hit resolves,
     * later handlers are skipped, and no faint/replacement work is created. */
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].state[0].hp == 1);
    assert(!battle.sides[1].state[0].faint_queued);
    uint8_t found_second_handler = 0;
    for (size_t i = 0; i < battle.handler_count; i++) {
        if (battle.handlers[i].handler.descriptor.id ==
            POKEMON_GEN3_HANDLER_FALSE_SWIPE_DAMAGE) {
            assert(battle.handlers[i].invoked);
            found_second_handler = 1;
        }
    }
    assert(found_second_handler);
    uint8_t found_zero_damage = 0;
    for (size_t i = 0; i < battle.event_count; i++) {
        if (battle.events[i].kind == POKEMON_EVENT_DAMAGE &&
            battle.events[i].move_id == POKEMON_GEN3_MOVE_FALSESWIPE) {
            assert(battle.events[i].amount == 0);
            assert(battle.events[i].hp == 1);
            found_zero_damage = 1;
        }
    }
    assert(found_zero_damage);

    /* Substitute owns its separate damage transaction.  The real-HP Damage
     * callback is neither discovered nor invoked when the substitute breaks. */
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    PokemonMutable *target = &battle.sides[1].state[0];
    target->volatiles[target->volatile_count++] = (PokemonVolatileState){
        .kind = POKEMON_VOLATILE_SUBSTITUTE,
        .descriptor_id = POKEMON_GEN3_CONDITION_VOLATILE_SUBSTITUTE,
        .state_generation = 1,
        .effect_order = ++battle.next_holder_effect_order,
        .source = {POKEMON_ENTITY_POKEMON, 1, 0},
        .source_effect = {POKEMON_SOURCE_EFFECT_MOVE,
            POKEMON_GEN3_MOVE_SUBSTITUTE},
        .payload.substitute = {.hp = 1},
    };
    assert(pokemon_battle_check_invariants(&battle));
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(target->hp == 2);
    assert(test_volatile_index(target, POKEMON_VOLATILE_SUBSTITUTE) < 0);
    assert(handler_event_count(&battle, POKEMON_HANDLER_EVENT_DAMAGE) == 0);
    assert(pokemon_battle_check_invariants(&battle));
}

static void test_focus_band_generated_damage_gate(void) {
	PokemonBattleInit init = condition_init(
		POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_STRENGTH,
		POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SPLASH);
	init.teams[1].members[0].item_id = POKEMON_GEN3_ITEM_FOCUSBAND;
	init.teams[1].members[0].stats[0] = 1;
	PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
	uint8_t survived = 0;
	for (uint16_t tail = 1; tail < 4096 && !survived; tail++) {
		init.seed[3] = tail;
		PokemonBattle battle;
		assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
		assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
		assert(draw_label_count(&battle, POKEMON_DRAW_FOCUS_BAND) == 1);
		survived = battle.sides[1].state[0].hp == 1;
		if (!survived) continue;
		uint8_t invoked = 0;
		for (size_t i = 0; i < battle.handler_count; i++) {
			invoked |= battle.handlers[i].handler.descriptor.id ==
				POKEMON_GEN3_HANDLER_FOCUS_BAND_DAMAGE;
		}
		assert(invoked);
		assert(pokemon_battle_check_invariants(&battle));
	}
	assert(survived);

	/* The callback owns its draw before its lethal predicate. */
	init.teams[1].members[0].stats[0] = 500;
	init.teams[1].members[0].stats[2] = 500;
	PokemonBattle battle;
	assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
	assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
	assert(battle.sides[1].state[0].hp > 0);
	assert(draw_label_count(&battle, POKEMON_DRAW_FOCUS_BAND) == 1);
}

static void test_generic_charge_lifecycle(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_PIKACHU, POKEMON_GEN3_MOVE_CHARGE,
        POKEMON_GEN3_SPECIES_MAGIKARP, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[0].members[0].move_ids[1] = POKEMON_GEN3_MOVE_THUNDERBOLT;
    PokemonChoice charge[POKEMON_SIDES] = {move(0), move(0)};
    PokemonChoice follow_up[POKEMON_SIDES] = {move(1), move(0)};
    PokemonBattle battle;

    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, charge) == POKEMON_OK);
    assert(test_volatile_index(&battle.sides[0].state[0],
        POKEMON_VOLATILE_CHARGE) >= 0);
    assert(handler_id_count(&battle, POKEMON_GEN3_HANDLER_CHARGE_START) == 1);
    assert(pokemon_battle_step(&battle, follow_up) == POKEMON_OK);
    assert(test_volatile_index(&battle.sides[0].state[0],
        POKEMON_VOLATILE_CHARGE) < 0);
    assert(handler_id_count(&battle,
        POKEMON_GEN3_HANDLER_CHARGE_AFTER_MOVE) == 1);
    assert(handler_id_count(&battle, POKEMON_GEN3_HANDLER_CHARGE_END) == 1);
    uint8_t doubled = 0;
    for (size_t i = 0; i < battle.modifier_count; i++) {
        if (battle.modifiers[i].handler.descriptor.id ==
                POKEMON_GEN3_HANDLER_CHARGE_BASE_POWER) {
            assert(battle.modifiers[i].modifier_q12 == 8192);
            doubled = 1;
        }
    }
    assert(doubled);

    /* Charge restarts itself rather than consuming the installed condition. */
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, charge) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, charge) == POKEMON_OK);
    assert(test_volatile_index(&battle.sides[0].state[0],
        POKEMON_VOLATILE_CHARGE) >= 0);
    assert(handler_id_count(&battle,
        POKEMON_GEN3_HANDLER_CHARGE_RESTART) == 1);
    assert(handler_id_count(&battle, POKEMON_GEN3_HANDLER_CHARGE_END) == 0);

    /* Resolved Gen 3 inherits Gen 8's cleanup override through the recursive
     * mod chain, so any non-Charge move consumes Charge. */
    init.teams[0].members[0].move_ids[1] = POKEMON_GEN3_MOVE_SPLASH;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, charge) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, follow_up) == POKEMON_OK);
    assert(test_volatile_index(&battle.sides[0].state[0],
        POKEMON_VOLATILE_CHARGE) < 0);
    assert(handler_id_count(&battle,
        POKEMON_GEN3_HANDLER_CHARGE_AFTER_MOVE) == 1);
    assert(handler_id_count(&battle, POKEMON_GEN3_HANDLER_CHARGE_END) == 1);

    /* The consuming Electric move may itself be a status move. */
    init.teams[0].members[0].move_ids[1] = POKEMON_GEN3_MOVE_THUNDERWAVE;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, charge) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, follow_up) == POKEMON_OK);
    assert(test_volatile_index(&battle.sides[0].state[0],
        POKEMON_VOLATILE_CHARGE) < 0);
    assert(handler_id_count(&battle,
        POKEMON_GEN3_HANDLER_CHARGE_AFTER_MOVE) == 1);
    assert(handler_id_count(&battle, POKEMON_GEN3_HANDLER_CHARGE_END) == 1);

    /* BeforeMove cancellation uses the generic MoveAborted event and still
     * performs explicit condition removal, including End. */
    uint8_t saw_abort = 0;
    init.teams[0].members[0].move_ids[1] = POKEMON_GEN3_MOVE_THUNDERBOLT;
    init.initial_status[0][0] = POKEMON_STATUS_PARALYSIS;
    for (uint16_t tail = 1; tail < 512 && !saw_abort; tail++) {
        init.seed[3] = tail;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        assert(pokemon_battle_step(&battle, charge) == POKEMON_OK);
        if (test_volatile_index(&battle.sides[0].state[0],
                POKEMON_VOLATILE_CHARGE) < 0) continue;
        assert(pokemon_battle_step(&battle, follow_up) == POKEMON_OK);
        if (handler_id_count(&battle,
                POKEMON_GEN3_HANDLER_CHARGE_MOVE_ABORTED) == 0) continue;
        saw_abort = 1;
        assert(test_volatile_index(&battle.sides[0].state[0],
            POKEMON_VOLATILE_CHARGE) < 0);
        assert(handler_id_count(&battle,
            POKEMON_GEN3_HANDLER_CHARGE_END) == 1);
        assert(draw_label_count(&battle, POKEMON_DRAW_PARALYSIS) == 1);
    }
    assert(saw_abort);

    /* Switching clears Pokemon-owned volatiles silently. */
    init.initial_status[0][0] = POKEMON_STATUS_NONE;
    init.team_sizes[0] = 2;
    init.teams[0].members[1] = make_set(
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SPLASH,
        200, 100, 100, 100, 100, 100);
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, charge) == POKEMON_OK);
    PokemonChoice switch_out[POKEMON_SIDES] = {switch_to(1), move(0)};
    assert(pokemon_battle_step(&battle, switch_out) == POKEMON_OK);
    assert(test_volatile_index(&battle.sides[0].state[0],
        POKEMON_VOLATILE_CHARGE) < 0);
    assert(handler_id_count(&battle, POKEMON_GEN3_HANDLER_CHARGE_END) == 0);
}

static void test_source_linked_residual_transfer_family(void) {
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_LEECHSEED,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[0].members[0].stats[0] = 400;
    init.teams[1].members[0].stats[0] = 400;
    init.initial_hp[0][0] = 100;
    PokemonBattle battle;
    uint8_t connected = 0;
    for (uint16_t tail = 1; tail < 512 && !connected; tail++) {
        init.seed[3] = tail;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        connected = test_volatile_index(&battle.sides[1].state[0],
            POKEMON_VOLATILE_LEECH_SEED) >= 0;
    }
    assert(connected);
    assert(battle.sides[1].state[0].hp == 350);
    assert(battle.sides[0].state[0].hp == 150);
    assert(handler_id_count(&battle,
        POKEMON_GEN3_HANDLER_LEECH_SEED_TRY_IMMUNITY) == 1);
    assert(handler_id_count(&battle,
        POKEMON_GEN3_HANDLER_LEECH_SEED_RESIDUAL) == 1);
    assert(pokemon_battle_check_invariants(&battle));

    /* The same transfer operation discovers Liquid Ooze through TryHeal.
     * It damages the would-be recipient and cancels the heal with numeric 0. */
    init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_LIQUIDOOZE;
    connected = 0;
    for (uint16_t tail = 1; tail < 512 && !connected; tail++) {
        init.seed[3] = tail;
        assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
        assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
        connected = test_volatile_index(&battle.sides[1].state[0],
            POKEMON_VOLATILE_LEECH_SEED) >= 0;
    }
    assert(connected);
    assert(battle.sides[1].state[0].hp == 350);
    assert(battle.sides[0].state[0].hp == 50);
    assert(handler_id_count(&battle,
        POKEMON_GEN3_HANDLER_LIQUID_OOZE_SOURCE_TRY_HEAL) == 1);
    assert(pokemon_battle_check_invariants(&battle));

    /* Grass immunity is a move-owned predicate whose result is deferred until
     * after Gen 3 consumes accuracy. */
    init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_LEECHSEED,
        POKEMON_GEN3_SPECIES_BULBASAUR, POKEMON_GEN3_MOVE_SPLASH);
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(test_volatile_index(&battle.sides[1].state[0],
        POKEMON_VOLATILE_LEECH_SEED) < 0);
    assert(handler_id_count(&battle,
        POKEMON_GEN3_HANDLER_LEECH_SEED_TRY_IMMUNITY) == 1);
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 1);
    assert(pokemon_battle_check_invariants(&battle));
}

static void test_flash_fire_generated_lifecycle(void) {
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_CHARIZARD, POKEMON_GEN3_MOVE_FLAMETHROWER,
        POKEMON_GEN3_SPECIES_PONYTA, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_FLASHFIRE;
    init.teams[1].members[0].stats[0] = 500;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    uint16_t hp_before = battle.sides[1].state[0].hp;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    int flash_fire = test_volatile_index(
        &battle.sides[1].state[0], POKEMON_VOLATILE_FLASH_FIRE);
    assert(flash_fire >= 0);
    assert(battle.sides[1].state[0].hp == hp_before);
    assert(battle.sides[1].state[0].volatiles[flash_fire].duration == 0);
    assert(battle.sides[1].state[0].volatiles[flash_fire].source_effect.kind ==
        POKEMON_SOURCE_EFFECT_ABILITY);
    assert(battle.sides[1].state[0].volatiles[flash_fire].source_effect.id ==
        POKEMON_GEN3_ABILITY_FLASHFIRE);
    assert(handler_id_count(
        &battle, POKEMON_GEN3_HANDLER_FLASH_FIRE_TRY_HIT) == 2);
    assert(handler_id_count(
        &battle, POKEMON_GEN3_HANDLER_FLASH_FIRE_CONDITION_START) == 1);
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 1);
    assert(draw_label_count(&battle, POKEMON_DRAW_CRITICAL) == 0);
    assert(draw_label_count(&battle, POKEMON_DRAW_DAMAGE_ROLL) == 0);

    size_t volatile_count = battle.sides[1].state[0].volatile_count;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].state[0].volatile_count == volatile_count);
    assert(handler_id_count(
        &battle, POKEMON_GEN3_HANDLER_FLASH_FIRE_TRY_HIT) == 2);
    assert(handler_id_count(
        &battle, POKEMON_GEN3_HANDLER_FLASH_FIRE_CONDITION_START) == 0);
    assert(pokemon_battle_check_invariants(&battle));

    /* Frozen holders fall through to the ordinary Fire hit, which owns the
     * damage draws and thaws the target. */
    init.initial_status[1][0] = POKEMON_STATUS_FREEZE;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    hp_before = battle.sides[1].state[0].hp;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(test_volatile_index(
        &battle.sides[1].state[0], POKEMON_VOLATILE_FLASH_FIRE) < 0);
    assert(battle.sides[1].state[0].hp < hp_before);
    assert(battle.sides[1].state[0].status.kind == POKEMON_STATUS_NONE);
    assert(draw_label_count(&battle, POKEMON_DRAW_CRITICAL) == 1);
    assert(draw_label_count(&battle, POKEMON_DRAW_DAMAGE_ROLL) == 1);
    assert(pokemon_battle_check_invariants(&battle));

    /* Gen 3's Will-O-Wisp exception leaves naturally ineligible targets to
     * the ordinary status pipeline instead of activating Flash Fire. */
    init = condition_init(
        POKEMON_GEN3_SPECIES_DUSCLOPS, POKEMON_GEN3_MOVE_WILLOWISP,
        POKEMON_GEN3_SPECIES_PONYTA, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_FLASHFIRE;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(test_volatile_index(
        &battle.sides[1].state[0], POKEMON_VOLATILE_FLASH_FIRE) < 0);
    assert(battle.sides[1].state[0].status.kind == POKEMON_STATUS_NONE);
    assert(pokemon_battle_check_invariants(&battle));

    /* The boost is condition-owned data, not an ability-specific damage
     * branch. Install the condition in two otherwise identical fresh games
     * so both executions consume the same labeled random draws. */
    init = condition_init(
        POKEMON_GEN3_SPECIES_PONYTA, POKEMON_GEN3_MOVE_FLAMETHROWER,
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[0].members[0].ability_id = POKEMON_GEN3_ABILITY_FLASHFIRE;
    init.teams[1].members[0].stats[0] = 500;
    PokemonBattle boosted;
    PokemonBattle control;
    assert(pokemon_battle_init(&boosted, &init) == POKEMON_OK);
    assert(pokemon_battle_init(&control, &init) == POKEMON_OK);
    PokemonEffectResult added = POKEMON_EFFECT_FAILED;
    assert(pokemon_try_add_or_restart_volatile(
        &boosted, (PokemonEntityRef){POKEMON_ENTITY_POKEMON, 0, 0},
        (PokemonEntityRef){POKEMON_ENTITY_POKEMON, 0, 0},
        (PokemonSourceEffectRef){POKEMON_SOURCE_EFFECT_ABILITY,
            POKEMON_GEN3_ABILITY_FLASHFIRE},
        POKEMON_VOLATILE_FLASH_FIRE, POKEMON_CONDITION_REASON_HANDLER,
        &added) == POKEMON_OK && added == POKEMON_EFFECT_APPLIED);
    assert(pokemon_battle_step(&boosted, choices) == POKEMON_OK);
    assert(pokemon_battle_step(&control, choices) == POKEMON_OK);
    assert(boosted.sides[1].state[0].hp < control.sides[1].state[0].hp);
    uint8_t found_boost = 0;
    for (size_t i = 0; i < boosted.modifier_count; i++) {
        if (boosted.modifiers[i].handler.descriptor.id !=
                POKEMON_GEN3_HANDLER_FLASH_FIRE_MODIFY_DAMAGE_PHASE1) {
            continue;
        }
        assert(boosted.modifiers[i].modifier_q12 == 6144);
        found_boost = 1;
    }
    assert(found_boost);
    assert(draw_label_count(&boosted, POKEMON_DRAW_ACCURACY) ==
        draw_label_count(&control, POKEMON_DRAW_ACCURACY));
    assert(draw_label_count(&boosted, POKEMON_DRAW_CRITICAL) ==
        draw_label_count(&control, POKEMON_DRAW_CRITICAL));
    assert(draw_label_count(&boosted, POKEMON_DRAW_DAMAGE_ROLL) ==
        draw_label_count(&control, POKEMON_DRAW_DAMAGE_ROLL));
    assert(pokemon_battle_check_invariants(&boosted));

    /* Ability replacement owns teardown. Flash Fire's ability End removes
     * its no-copy volatile, whose own End callback remains independently
     * observable. */
    init = condition_init(
        POKEMON_GEN3_SPECIES_PONYTA, POKEMON_GEN3_MOVE_ROLEPLAY,
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[0].members[0].ability_id = POKEMON_GEN3_ABILITY_FLASHFIRE;
    init.teams[1].members[0].ability_id = POKEMON_GEN3_ABILITY_LIMBER;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    added = POKEMON_EFFECT_FAILED;
    assert(pokemon_try_add_or_restart_volatile(
        &battle, (PokemonEntityRef){POKEMON_ENTITY_POKEMON, 0, 0},
        (PokemonEntityRef){POKEMON_ENTITY_POKEMON, 0, 0},
        (PokemonSourceEffectRef){POKEMON_SOURCE_EFFECT_ABILITY,
            POKEMON_GEN3_ABILITY_FLASHFIRE},
        POKEMON_VOLATILE_FLASH_FIRE, POKEMON_CONDITION_REASON_HANDLER,
        &added) == POKEMON_OK && added == POKEMON_EFFECT_APPLIED);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].ability_id == POKEMON_GEN3_ABILITY_LIMBER);
    assert(test_volatile_index(
        &battle.sides[0].state[0], POKEMON_VOLATILE_FLASH_FIRE) < 0);
    assert(handler_id_count(
        &battle, POKEMON_GEN3_HANDLER_FLASH_FIRE_ABILITY_END) == 1);
    assert(handler_id_count(
        &battle, POKEMON_GEN3_HANDLER_FLASH_FIRE_CONDITION_END) == 1);
    assert(pokemon_battle_check_invariants(&battle));
}

static void test_rage_generated_reactive_lifecycle(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_RAGE,
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_TACKLE);
    init.team_sizes[0] = 1;
    init.team_sizes[1] = 1;
    init.teams[0].members[0].move_ids[1] = POKEMON_GEN3_MOVE_SPLASH;
    init.teams[0].members[0].stats[0] = 500;
    init.teams[0].members[0].stats[5] = 100;
    init.teams[1].members[0].move_ids[1] = POKEMON_GEN3_MOVE_TAILWHIP;
    init.teams[1].members[0].stats[0] = 500;
    init.teams[1].members[0].stats[5] = 300;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);

    PokemonChoice tackle_then_rage[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_step(&battle, tackle_then_rage) == POKEMON_OK);
    int rage = test_volatile_index(
        &battle.sides[0].state[0], POKEMON_VOLATILE_RAGE);
    assert(rage >= 0);
    assert(battle.sides[0].state[0].boosts[POKEMON_STAT_ATK] == 0);
    assert(battle.sides[0].state[0].volatiles[rage].source_effect.kind ==
        POKEMON_SOURCE_EFFECT_MOVE);
    assert(battle.sides[0].state[0].volatiles[rage].source_effect.id ==
        POKEMON_GEN3_MOVE_RAGE);

    /* Status moves dispatch Hit but cannot trigger Rage's category guard.
     * The holder's own BeforeMove removes the old condition, and the
     * connected Rage installs a fresh instance through the ordinary effect
     * pipeline. */
    PokemonChoice tail_whip_then_rage[POKEMON_SIDES] = {move(0), move(1)};
    assert(pokemon_battle_step(&battle, tail_whip_then_rage) == POKEMON_OK);
    assert(battle.sides[0].state[0].boosts[POKEMON_STAT_ATK] == 0);
    assert(test_volatile_index(
        &battle.sides[0].state[0], POKEMON_VOLATILE_RAGE) >= 0);
    assert(handler_id_count(&battle, POKEMON_GEN3_HANDLER_RAGE_HIT) == 1);
    assert(handler_id_count(
        &battle, POKEMON_GEN3_HANDLER_RAGE_BEFORE_MOVE) == 1);

    /* An incoming damaging hit boosts exactly once. Choosing another move
     * then tears Rage down before that move executes and does not reinstall
     * it. */
    PokemonChoice tackle_then_splash[POKEMON_SIDES] = {move(1), move(0)};
    assert(pokemon_battle_step(&battle, tackle_then_splash) == POKEMON_OK);
    assert(battle.sides[0].state[0].boosts[POKEMON_STAT_ATK] == 1);
    assert(test_volatile_index(
        &battle.sides[0].state[0], POKEMON_VOLATILE_RAGE) < 0);
    assert(handler_id_count(&battle, POKEMON_GEN3_HANDLER_RAGE_HIT) == 1);
    assert(handler_id_count(
        &battle, POKEMON_GEN3_HANDLER_RAGE_BEFORE_MOVE) == 1);
    assert(pokemon_battle_check_invariants(&battle));
}

static void test_minimize_generated_marker_and_damage_modifier(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_MINIMIZE,
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SPLASH);
    init.team_sizes[0] = 1;
    init.team_sizes[1] = 1;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    PokemonChoice minimize[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_step(&battle, minimize) == POKEMON_OK);
    assert(battle.sides[0].state[0].boosts[POKEMON_STAT_EVASION] == 1);
    assert(test_volatile_index(
        &battle.sides[0].state[0], POKEMON_VOLATILE_MINIMIZE) >= 0);
    assert(pokemon_battle_step(&battle, minimize) == POKEMON_OK);
    assert(battle.sides[0].state[0].boosts[POKEMON_STAT_EVASION] == 2);
    assert(handler_id_count(
        &battle, POKEMON_GEN3_HANDLER_MINIMIZE_RESTART) == 1);
    assert(pokemon_battle_check_invariants(&battle));

    init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_SPLASH,
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_STOMP);
    init.team_sizes[0] = 1;
    init.team_sizes[1] = 1;
    init.teams[0].members[0].stats[0] = 1000;
    PokemonBattle boosted;
    PokemonBattle control;
    assert(pokemon_battle_init(&boosted, &init) == POKEMON_OK);
    assert(pokemon_battle_init(&control, &init) == POKEMON_OK);
    PokemonEffectResult added = POKEMON_EFFECT_FAILED;
    assert(pokemon_try_add_or_restart_volatile(
        &boosted, (PokemonEntityRef){POKEMON_ENTITY_POKEMON, 0, 0},
        (PokemonEntityRef){POKEMON_ENTITY_POKEMON, 0, 0},
        (PokemonSourceEffectRef){POKEMON_SOURCE_EFFECT_MOVE,
            POKEMON_GEN3_MOVE_MINIMIZE},
        POKEMON_VOLATILE_MINIMIZE, POKEMON_CONDITION_REASON_MOVE,
        &added) == POKEMON_OK && added == POKEMON_EFFECT_APPLIED);
    PokemonChoice stomp[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_step(&boosted, stomp) == POKEMON_OK);
    assert(pokemon_battle_step(&control, stomp) == POKEMON_OK);
    assert(1000 - boosted.sides[0].state[0].hp ==
        2 * (1000 - control.sides[0].state[0].hp));
    uint8_t found_modifier = 0;
    for (size_t i = 0; i < boosted.modifier_count; i++) {
        if (boosted.modifiers[i].handler.descriptor.id ==
                POKEMON_GEN3_HANDLER_MINIMIZE_SOURCE_MODIFY_DAMAGE) {
            assert(boosted.modifiers[i].modifier_q12 == 8192);
            found_modifier = 1;
        }
    }
    assert(found_modifier);
    assert(draw_label_count(&boosted, POKEMON_DRAW_ACCURACY) ==
        draw_label_count(&control, POKEMON_DRAW_ACCURACY));
    assert(draw_label_count(&boosted, POKEMON_DRAW_CRITICAL) ==
        draw_label_count(&control, POKEMON_DRAW_CRITICAL));
    assert(draw_label_count(&boosted, POKEMON_DRAW_DAMAGE_ROLL) ==
        draw_label_count(&control, POKEMON_DRAW_DAMAGE_ROLL));
    assert(pokemon_battle_check_invariants(&boosted));
}

static void test_spite_target_last_move_pp_transaction(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_BANETTE, POKEMON_GEN3_MOVE_SPITE,
        POKEMON_GEN3_SPECIES_DUSCLOPS, POKEMON_GEN3_MOVE_SPLASH);
    init.team_sizes[0] = 1;
    init.team_sizes[1] = 1;
    init.teams[0].members[0].stats[5] = 100;
    init.teams[1].members[0].stats[5] = 300;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    uint8_t before = battle.sides[1].state[0].pp[0];
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    uint8_t spent = (uint8_t)(before - battle.sides[1].state[0].pp[0]);
    assert(spent >= 3 && spent <= 6);
    assert(battle.sides[1].state[0].base_pp[0] ==
        battle.sides[1].state[0].pp[0]);
    assert(draw_label_count(&battle, POKEMON_DRAW_MOVE_PP_REDUCTION) == 1);
    assert(handler_id_count(&battle, POKEMON_GEN3_HANDLER_SPITE_HIT) == 1);
    assert(pokemon_battle_check_invariants(&battle));

    /* The effect draw belongs to Spite's callback and occurs even when the
     * target has no last selected move. The target's later action then owns
     * its ordinary one-PP debit. */
    init.teams[0].members[0].stats[5] = 300;
    init.teams[1].members[0].stats[5] = 100;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    before = battle.sides[1].state[0].pp[0];
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].state[0].pp[0] == before - 1);
    assert(draw_label_count(&battle, POKEMON_DRAW_MOVE_PP_REDUCTION) == 1);

    /* Deduction clamps at zero after the faster target spends its penultimate
     * PP. This isolates Spite's clamp from queued no-PP action semantics. */
    init.teams[0].members[0].stats[5] = 100;
    init.teams[1].members[0].stats[5] = 300;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    test_set_base_backed_pp(&battle, 1, 0, 0, 2);
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[1].state[0].pp[0] == 0);
    assert(battle.sides[1].state[0].base_pp[0] == 0);
    assert(battle.sides[1].state[0].last_move_id == POKEMON_GEN3_MOVE_SPLASH);
    assert(draw_label_count(&battle, POKEMON_DRAW_MOVE_PP_REDUCTION) == 1);
    assert(pokemon_battle_check_invariants(&battle));
}

static size_t move_event_id_count(
    const PokemonBattle *battle, uint16_t move_id
) {
    size_t count = 0;
    for (size_t i = 0; i < battle->event_count; i++) {
        count += battle->events[i].kind == POKEMON_EVENT_MOVE &&
            battle->events[i].move_id == move_id;
    }
    return count;
}

static void test_bide_stored_damage_and_direct_pre_use_stage(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_BIDE,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SEISMICTOSS);
    init.teams[0].members[0].stats[0] = 300;
    init.teams[1].members[0].stats[0] = 651;
    init.teams[1].members[0].move_ids[1] = POKEMON_GEN3_MOVE_HEALBELL;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    PokemonChoice strike[POKEMON_SIDES] = {move(0), move(0)};
    PokemonChoice release[POKEMON_SIDES] = {move(0), move(1)};

    assert(battle.sides[0].state[0].pp[0] == 16);
    assert(pokemon_battle_step(&battle, strike) == POKEMON_OK);
    int index = test_volatile_index(
        &battle.sides[0].state[0], POKEMON_VOLATILE_STORED_DAMAGE);
    assert(index >= 0);
    PokemonVolatileState *bide =
        &battle.sides[0].state[0].volatiles[index];
    assert(battle.sides[0].state[0].pp[0] == 15);
    assert(bide->duration == 2);
    assert(bide->payload.stored_damage.value == 100);
    assert(bide->payload.stored_damage.captured);
    assert(bide->payload.stored_damage.last_source.side == 1);
    assert(move_event_id_count(&battle, POKEMON_GEN3_MOVE_BIDE) == 1);
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 2);

    /* The forced middle action reaches BeforeMove, then the direct generated
     * pre-use program cancels before PP, announcement, AfterMove, or accuracy.
     * Incoming move damage remains independently accumulated. */
    assert(pokemon_battle_step(&battle, strike) == POKEMON_OK);
    index = test_volatile_index(
        &battle.sides[0].state[0], POKEMON_VOLATILE_STORED_DAMAGE);
    assert(index >= 0);
    bide = &battle.sides[0].state[0].volatiles[index];
    assert(battle.sides[0].state[0].pp[0] == 15);
    assert(bide->duration == 1);
    assert(bide->payload.stored_damage.value == 200);
    assert(move_event_id_count(&battle, POKEMON_GEN3_MOVE_BIDE) == 0);
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 1);

    uint16_t target_hp = battle.sides[1].state[0].hp;
    assert(pokemon_battle_step(&battle, release) == POKEMON_OK);
    assert(test_volatile_index(
        &battle.sides[0].state[0], POKEMON_VOLATILE_STORED_DAMAGE) < 0);
    assert(battle.sides[0].state[0].pp[0] == 15);
    assert(battle.sides[1].state[0].hp == target_hp - 400);
    assert(move_event_id_count(&battle, POKEMON_GEN3_MOVE_BIDE) == 0);
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 1);
    assert(draw_label_count(&battle, POKEMON_DRAW_CRITICAL) == 0);
    assert(draw_label_count(&battle, POKEMON_DRAW_DAMAGE_ROLL) == 0);
    assert(pokemon_battle_check_invariants(&battle));
}

static void test_fury_cutter_generated_ramping_power_lifecycle(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_FURYCUTTER,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[0].members[0].move_ids[1] = POKEMON_GEN3_MOVE_SPLASH;
    init.teams[1].members[0].stats[0] = 5000;
    init.teams[1].members[0].stats[2] = 1000;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    PokemonChoice hit[POKEMON_SIDES] = {move(0), move(0)};
    const uint8_t counters[] = {2, 4, 8, 16, 16};
    uint16_t previous_damage = 0;
    for (size_t turn = 0; turn < sizeof(counters); turn++) {
        uint16_t hp_before = battle.sides[1].state[0].hp;
        assert(pokemon_battle_step(&battle, hit) == POKEMON_OK);
        uint16_t damage = (uint16_t)(
            hp_before - battle.sides[1].state[0].hp);
        assert(damage > previous_damage || turn == 4);
        previous_damage = damage;
        int index = test_volatile_index(
            &battle.sides[0].state[0], POKEMON_VOLATILE_FURY_CUTTER);
        assert(index >= 0);
        const PokemonVolatileState *ramp =
            &battle.sides[0].state[0].volatiles[index];
        assert(ramp->descriptor_id ==
            POKEMON_GEN3_CONDITION_VOLATILE_FURYCUTTER);
        assert(ramp->counter == counters[turn]);
        assert(ramp->duration == 1);
        assert(ramp->source_effect.kind == POKEMON_SOURCE_EFFECT_MOVE);
        assert(ramp->source_effect.id == POKEMON_GEN3_MOVE_FURYCUTTER);
        assert(handler_id_count(
            &battle, POKEMON_GEN3_HANDLER_FURY_CUTTER_HIT) == 1);
        assert(pokemon_battle_check_invariants(&battle));
    }

    /* A turn without a successful Fury Cutter does not refresh the two-tick
     * condition. Residual expiry removes it, and the next hit starts from
     * the initial counter rather than retaining hidden move-specific state. */
    PokemonChoice gap[POKEMON_SIDES] = {move(1), move(0)};
    assert(pokemon_battle_step(&battle, gap) == POKEMON_OK);
    assert(test_volatile_index(
        &battle.sides[0].state[0], POKEMON_VOLATILE_FURY_CUTTER) < 0);
    assert(pokemon_battle_step(&battle, hit) == POKEMON_OK);
    int index = test_volatile_index(
        &battle.sides[0].state[0], POKEMON_VOLATILE_FURY_CUTTER);
    assert(index >= 0);
    assert(battle.sides[0].state[0].volatiles[index].counter == 2);
    assert(battle.sides[0].state[0].volatiles[index].duration == 1);
    assert(pokemon_battle_check_invariants(&battle));
}

static void test_ramping_power_bundle_validation_is_atomic(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_FURYCUTTER,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SPLASH);
    PokemonResolvedBundle bundle = *init.bundle;
    PokemonData data = *bundle.data;
    PokemonHandlerDescriptor handlers[data.handler_count];
    memcpy(handlers, data.handlers, sizeof(handlers));
    uint8_t found = 0;
    for (size_t i = 0; i < data.handler_count; i++) {
        if (data.handlers[i].id !=
                POKEMON_GEN3_HANDLER_FURY_CUTTER_HIT) continue;
        assert(data.handlers[i].program_count == 1);
        handlers[i].program_offset = data.handler_program_count;
        found = 1;
        break;
    }
    assert(found);
    data.handlers = handlers;
    bundle.data = &data;
    init.bundle = &bundle;
    PokemonBattle battle;
    memset(&battle, 0xa5, sizeof(battle));
    PokemonBattle before = battle;
    assert(pokemon_battle_init(&battle, &init) ==
        POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&battle, &before, sizeof(battle)) == 0);
}

static void test_locked_ramp_rollout_ice_ball_and_defense_curl(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_ROLLOUT,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[0].members[0].move_ids[1] = POKEMON_GEN3_MOVE_DEFENSECURL;
    init.teams[0].members[0].move_ids[2] = POKEMON_GEN3_MOVE_ICEBALL;
    init.teams[1].members[0].stats[0] = 60000;
	init.initial_hp[1][0] = 60000;
    init.teams[1].members[0].stats[2] = 1000;
    init.teams[1].members[0].stats[4] = 1000;
    PokemonChoice rollout[POKEMON_SIDES] = {move(0), move(0)};
    PokemonChoice curl[POKEMON_SIDES] = {move(1), move(0)};

    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    battle.sides[0].state[0].boosts[POKEMON_STAT_ACCURACY] = 6;
    battle.sides[1].state[0].boosts[POKEMON_STAT_EVASION] = -6;
    uint16_t damages[5];
    for (size_t turn = 0; turn < 5; turn++) {
        uint16_t before = battle.sides[1].state[0].hp;
        assert(pokemon_battle_step(&battle, rollout) == POKEMON_OK);
        damages[turn] = (uint16_t)(before - battle.sides[1].state[0].hp);
        if (turn != 4) {
            int index = test_volatile_index(
                &battle.sides[0].state[0], POKEMON_VOLATILE_ROLLOUT);
            assert(index >= 0);
            assert(battle.sides[0].state[0].volatiles[index].descriptor_id ==
                POKEMON_GEN3_CONDITION_VOLATILE_ROLLOUT);
            assert(battle.sides[0].state[0].volatiles[index].counter ==
                turn + 1);
            assert(battle.sides[0].state[0].volatiles[index].duration == 1);
            assert(battle.request.forced_move_id[0] ==
                POKEMON_GEN3_MOVE_ROLLOUT);
        }
        assert(pokemon_battle_check_invariants(&battle));
    }
    for (size_t turn = 1; turn < 5; turn++) {
        assert(damages[turn] >= damages[turn - 1]);
    }
    assert(damages[4] > damages[0]);
    assert(test_volatile_index(
        &battle.sides[0].state[0], POKEMON_VOLATILE_ROLLOUT) < 0);

    /* Defense Curl is independent persistent state. It doubles the first
     * connected ramp step without changing lock/counter ownership. */
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    battle.sides[0].state[0].boosts[POKEMON_STAT_ACCURACY] = 6;
    battle.sides[1].state[0].boosts[POKEMON_STAT_EVASION] = -6;
    assert(pokemon_battle_step(&battle, curl) == POKEMON_OK);
    assert(test_volatile_index(
        &battle.sides[0].state[0], POKEMON_VOLATILE_DEFENSE_CURL) >= 0);
    uint16_t before = battle.sides[1].state[0].hp;
    assert(pokemon_battle_step(&battle, rollout) == POKEMON_OK);
    assert((uint16_t)(before - battle.sides[1].state[0].hp) > damages[0]);

    /* Ice Ball shares the interpreter operation but owns a distinct lock
     * identity and selects itself through the condition's source move. */
    PokemonChoice ice_ball[POKEMON_SIDES] = {move(2), move(0)};
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    battle.sides[0].state[0].boosts[POKEMON_STAT_ACCURACY] = 6;
    battle.sides[1].state[0].boosts[POKEMON_STAT_EVASION] = -6;
    assert(pokemon_battle_step(&battle, ice_ball) == POKEMON_OK);
    int ice = test_volatile_index(
        &battle.sides[0].state[0], POKEMON_VOLATILE_ICE_BALL);
    assert(ice >= 0);
    assert(battle.sides[0].state[0].volatiles[ice].descriptor_id ==
        POKEMON_GEN3_CONDITION_VOLATILE_ICEBALL);
    assert(battle.sides[0].state[0].volatiles[ice].counter == 1);
    assert(battle.request.forced_move_id[0] == POKEMON_GEN3_MOVE_ICEBALL);
    assert(pokemon_battle_check_invariants(&battle));

    /* A miss never reaches BasePower, so the one-tick condition expires at
     * residual instead of advancing or refreshing. */
    uint16_t miss_seed = 0;
    for (uint16_t tail = 1; tail < 4096 && !miss_seed; tail++) {
        init.seed[3] = tail;
        PokemonBattle candidate;
        assert(pokemon_battle_init(&candidate, &init) == POKEMON_OK);
        assert(pokemon_battle_step(&candidate, rollout) == POKEMON_OK);
        for (size_t draw = 0; draw < candidate.draw_count; draw++) {
            if (candidate.draws[draw].label == POKEMON_DRAW_ACCURACY &&
                candidate.draws[draw].result >= 90) {
                miss_seed = tail;
                break;
            }
        }
    }
    assert(miss_seed != 0);
    init.seed[3] = miss_seed;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, rollout) == POKEMON_OK);
    assert(event_kind_count(&battle, POKEMON_EVENT_MISS) == 1);
    assert(test_volatile_index(
        &battle.sides[0].state[0], POKEMON_VOLATILE_ROLLOUT) < 0);
    assert(pokemon_battle_check_invariants(&battle));
}

static void test_stockpile_counter_power_and_heal_family(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_STOCKPILE,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[0].members[0].move_ids[1] = POKEMON_GEN3_MOVE_SPITUP;
    init.teams[0].members[0].move_ids[2] = POKEMON_GEN3_MOVE_SWALLOW;
    init.teams[0].members[0].stats[0] = 301;
    init.initial_hp[0][0] = 301;
    init.teams[1].members[0].stats[0] = 5000;
    init.initial_hp[1][0] = 5000;
    init.teams[1].members[0].stats[2] = 500;
    PokemonChoice stockpile[POKEMON_SIDES] = {move(0), move(0)};
    PokemonChoice spit_up[POKEMON_SIDES] = {move(1), move(0)};
    PokemonChoice swallow[POKEMON_SIDES] = {move(2), move(0)};
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    uint8_t saw_stockpile_rule = 0;
    for (size_t rule = 0; rule < battle.generation->condition_rule_count; rule++) {
        const PokemonConditionRule *condition =
            &battle.generation->condition_rules[rule];
        if (condition->descriptor_id ==
                POKEMON_GEN3_CONDITION_VOLATILE_STOCKPILE) {
            assert(condition->kind == POKEMON_RULE_CONDITION_BOUNDED_COUNTER);
            assert(condition->no_copy == 1);
            saw_stockpile_rule = 1;
        }
    }
    assert(saw_stockpile_rule);

    for (uint8_t layer = 1; layer <= 3; layer++) {
        assert(pokemon_battle_step(&battle, stockpile) == POKEMON_OK);
        int index = test_volatile_index(
            &battle.sides[0].state[0], POKEMON_VOLATILE_STOCKPILE);
        assert(index >= 0);
        assert(battle.sides[0].state[0].volatiles[index].descriptor_id ==
            POKEMON_GEN3_CONDITION_VOLATILE_STOCKPILE);
        assert(battle.sides[0].state[0].volatiles[index].counter == layer);
        assert(battle.sides[0].state[0].volatiles[index].duration == 0);
        assert(battle.sides[0].state[0].boosts[POKEMON_STAT_DEF] == 0);
        assert(battle.sides[0].state[0].boosts[POKEMON_STAT_SPD] == 0);
        assert(pokemon_battle_check_invariants(&battle));
    }
    uint8_t pp_before = battle.sides[0].state[0].pp[0];
    assert(pokemon_battle_step(&battle, stockpile) == POKEMON_OK);
    assert(battle.sides[0].state[0].pp[0] == pp_before - 1);
    int index = test_volatile_index(
        &battle.sides[0].state[0], POKEMON_VOLATILE_STOCKPILE);
    assert(index >= 0);
    assert(battle.sides[0].state[0].volatiles[index].counter == 3);

    uint16_t foe_hp = battle.sides[1].state[0].hp;
    assert(pokemon_battle_step(&battle, spit_up) == POKEMON_OK);
    assert(battle.sides[1].state[0].hp < foe_hp);
    assert(test_volatile_index(
        &battle.sides[0].state[0], POKEMON_VOLATILE_STOCKPILE) < 0);
    assert(handler_id_count(
        &battle, POKEMON_GEN3_HANDLER_SPIT_UP_AFTER_MOVE) == 1);
    assert(pokemon_battle_check_invariants(&battle));

    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, stockpile) == POKEMON_OK);
    battle.sides[0].state[0].hp = 1;
    assert(pokemon_battle_step(&battle, swallow) == POKEMON_OK);
    /* Showdown modify(301, 0.25) rounds half down through Q12. */
    assert(battle.sides[0].state[0].hp == 76);
    assert(test_volatile_index(
        &battle.sides[0].state[0], POKEMON_VOLATILE_STOCKPILE) < 0);
    assert(handler_id_count(&battle, POKEMON_GEN3_HANDLER_SWALLOW_HIT) == 1);
    uint8_t saw_swallow_target = 0;
    for (size_t event = 0; event < battle.event_count; event++) {
        if (battle.events[event].kind == POKEMON_EVENT_MOVE &&
            battle.events[event].move_id == POKEMON_GEN3_MOVE_SWALLOW) {
            assert(battle.events[event].target_side == 0);
            saw_swallow_target = 1;
        }
    }
    assert(saw_swallow_target);
    assert(pokemon_battle_check_invariants(&battle));

    /* A zero-delta heal still completes Hit and consumes Stockpile. */
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, stockpile) == POKEMON_OK);
    assert(battle.sides[0].state[0].hp == 301);
    assert(pokemon_battle_step(&battle, swallow) == POKEMON_OK);
    assert(battle.sides[0].state[0].hp == 301);
    assert(test_volatile_index(
        &battle.sides[0].state[0], POKEMON_VOLATILE_STOCKPILE) < 0);
    assert(handler_id_count(&battle, POKEMON_GEN3_HANDLER_SWALLOW_HIT) == 1);
    assert(pokemon_battle_check_invariants(&battle));
}

static void test_move_driven_switch_retains_queue_and_transfers_state(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_BATONPASS,
        POKEMON_GEN3_SPECIES_BANETTE, POKEMON_GEN3_MOVE_STRENGTH);
    init.teams[0].members[1] = make_set(
        POKEMON_GEN3_SPECIES_ALAKAZAM, POKEMON_GEN3_MOVE_SPLASH,
        250, 100, 100, 350, 200, 320);
    init.team_sizes[0] = 2;
    init.team_sizes[1] = 1;
    PokemonBattle battle;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    PokemonMutable *passer = &battle.sides[0].state[0];
    passer->boosts[POKEMON_STAT_SPA] = 2;
    passer->boosts[POKEMON_STAT_SPD] = -1;
    passer->volatiles[0] = (PokemonVolatileState){
        .kind = POKEMON_VOLATILE_FOCUS_ENERGY,
        .descriptor_id = POKEMON_GEN3_CONDITION_VOLATILE_FOCUSENERGY,
        .state_generation = 1,
        .effect_order = ++battle.next_holder_effect_order,
        .source = {POKEMON_ENTITY_POKEMON, 0, 0},
        .source_effect = {POKEMON_SOURCE_EFFECT_MOVE,
            POKEMON_GEN3_MOVE_FOCUSENERGY},
    };
    passer->volatiles[1] = (PokemonVolatileState){
        .kind = POKEMON_VOLATILE_STOCKPILE,
        .descriptor_id = POKEMON_GEN3_CONDITION_VOLATILE_STOCKPILE,
        .counter = 2,
        .state_generation = 1,
        .effect_order = ++battle.next_holder_effect_order,
        .source = {POKEMON_ENTITY_POKEMON, 0, 0},
        .source_effect = {POKEMON_SOURCE_EFFECT_MOVE,
            POKEMON_GEN3_MOVE_STOCKPILE},
    };
    passer->volatiles[2] = (PokemonVolatileState){
        .kind = POKEMON_VOLATILE_TRAPPED,
        .descriptor_id = POKEMON_GEN3_CONDITION_VOLATILE_TRAPPED,
        .state_generation = 1,
        .effect_order = ++battle.next_holder_effect_order,
        .source = {POKEMON_ENTITY_POKEMON, 1, 0},
        .source_effect = {POKEMON_SOURCE_EFFECT_MOVE,
            POKEMON_GEN3_MOVE_MEANLOOK},
        .linked_source_state_generation = 1,
        .linked_source_effect_order = ++battle.next_holder_effect_order,
    };
    passer->volatile_count = 3;
    PokemonChoice turn[POKEMON_SIDES] = {move(0), move(0)};
    assert(pokemon_battle_step(&battle, turn) == POKEMON_OK);
    assert(battle.pending_move_switch.active);
    assert(battle.pending_move_switch.transfer ==
        POKEMON_SWITCH_TRANSFER_BOOSTS_AND_VOLATILES);
    assert(battle.request.kind[0] == POKEMON_REQUEST_SWITCH);
    assert(battle.request.kind[1] == POKEMON_REQUEST_WAIT);
    assert(battle.request.switch_choices[0].mode ==
        POKEMON_SWITCH_CHOICE_MOVE_DRIVEN);
    assert(battle.phase == POKEMON_PHASE_MOVE_SWITCH);
    assert(battle.request.legal_switches[0] == (1u << 1));
    assert(battle.queue.count == 1);
    assert(battle.queue.values[0].kind == POKEMON_ACTION_MOVE);
    assert(battle.queue.values[0].side == 1);
    uint16_t incoming_hp = battle.sides[0].state[1].hp;

    PokemonChoice replacement[POKEMON_SIDES] = {
        switch_to(1), wait_choice()};
    assert(pokemon_battle_step(&battle, replacement) == POKEMON_OK);
    assert(!battle.pending_move_switch.active);
    assert(battle.sides[0].active == 1);
    assert(battle.sides[0].state[1].hp < incoming_hp);
    assert(battle.sides[0].state[1].boosts[POKEMON_STAT_SPA] == 2);
    assert(battle.sides[0].state[1].boosts[POKEMON_STAT_SPD] == -1);
    assert(test_volatile_index(
        &battle.sides[0].state[1], POKEMON_VOLATILE_FOCUS_ENERGY) >= 0);
    assert(test_volatile_index(
        &battle.sides[0].state[1], POKEMON_VOLATILE_STOCKPILE) < 0);
    /* Resolved Gen 3 inherits the Gen 4 mod override which makes the linked
     * trapped/trapper relation copyable; the modern base noCopy value is not
     * authoritative for this generation. */
    assert(test_volatile_index(
        &battle.sides[0].state[1], POKEMON_VOLATILE_TRAPPED) >= 0);
    assert(battle.sides[0].state[0].boosts[POKEMON_STAT_SPA] == 0);
    assert(battle.sides[0].state[0].volatile_count == 0);
    assert(pokemon_battle_check_invariants(&battle));

    /* A descriptor may request a move switch even though the ordinary switch
     * mask is trapped. With no bench the move simply cannot create a pending
     * continuation; the slower action and turn still complete. */
    init.team_sizes[0] = 1;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    assert(pokemon_battle_step(&battle, turn) == POKEMON_OK);
    assert(!battle.pending_move_switch.active);
    assert(battle.phase == POKEMON_PHASE_AWAITING_CHOICES);
    assert(battle.request.kind[0] == POKEMON_REQUEST_MOVE);
    assert(pokemon_battle_check_invariants(&battle));
}

static void test_counter_heal_policy_validation_is_atomic(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_SWALLOW,
        POKEMON_GEN3_SPECIES_BLISSEY, POKEMON_GEN3_MOVE_SPLASH);
    PokemonResolvedBundle bundle = *init.bundle;
    PokemonData data = *bundle.data;
    assert(data.counter_heal_policy_count == 1);
    PokemonCounterHealPolicy malformed = data.counter_heal_policies[0];
    malformed.maximum_counter = POKEMON_COUNTER_HEAL_MAX_ENTRIES + 1;
    data.counter_heal_policies = &malformed;
    bundle.data = &data;
    init.bundle = &bundle;
    PokemonBattle battle;
    memset(&battle, 0xa5, sizeof(battle));
    PokemonBattle before = battle;
    assert(pokemon_battle_init(&battle, &init) ==
        POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&battle, &before, sizeof(battle)) == 0);
}

static void test_type_response_policy_validation_is_atomic(void) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_CONVERSION2,
        POKEMON_GEN3_SPECIES_CHARIZARD, POKEMON_GEN3_MOVE_DRAGONRAGE);
    PokemonResolvedBundle bundle = *init.bundle;
    PokemonData data = *bundle.data;
    assert(data.type_response_policy_count == 1);

    data.type_response_policies = NULL;
    assert_invalid_resolved_data_is_atomic(init, &data);

    data = *bundle.data;
    PokemonTypeResponsePolicy malformed = data.type_response_policies[0];
    uint8_t duplicate_candidates[2] = {
        POKEMON_GEN3_TYPE_STEEL, POKEMON_GEN3_TYPE_STEEL,
    };
    malformed.candidate_types = duplicate_candidates;
    malformed.candidate_count = 2;
    data.type_response_policies = &malformed;
    assert_invalid_resolved_data_is_atomic(init, &data);
}

static void test_move_pre_use_program_bundle_validation_is_atomic(void) {
    PokemonBattleInit init = battle_init();
    PokemonResolvedBundle bundle = *init.bundle;
    PokemonData data = *bundle.data;
    PokemonMovePreUseProgram duplicate[2] = {
        {POKEMON_GEN3_MOVE_BIDE,
            POKEMON_MOVE_PRE_USE_CANCEL_IF_VOLATILE_KIND,
            POKEMON_VOLATILE_STORED_DAMAGE},
        {POKEMON_GEN3_MOVE_BIDE,
            POKEMON_MOVE_PRE_USE_CANCEL_IF_VOLATILE_KIND,
            POKEMON_VOLATILE_STORED_DAMAGE},
    };
    data.move_pre_use_programs = duplicate;
    data.move_pre_use_program_count = 2;
    bundle.data = &data;
    init.bundle = &bundle;
    PokemonBattle battle;
    memset(&battle, 0x5a, sizeof(battle));
    PokemonBattle before = battle;
    assert(pokemon_battle_init(&battle, &init) ==
        POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&battle, &before, sizeof(battle)) == 0);

    data.move_pre_use_programs = NULL;
    data.move_pre_use_program_count = 1;
    battle = before;
    assert(pokemon_battle_init(&battle, &init) ==
        POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&battle, &before, sizeof(battle)) == 0);
}

static void test_move_fail_hypothetical_damage_family(void) {
    const PokemonMoveData *jump_kick = NULL;
    const PokemonMoveData *high_jump_kick = NULL;
    for (size_t i = 0; i < POKEMON_GEN3_SLICE_DATA.move_count; i++) {
        const PokemonMoveData *move_data = &POKEMON_GEN3_SLICE_DATA.moves[i];
        if (move_data->id == POKEMON_GEN3_MOVE_JUMPKICK) jump_kick = move_data;
        if (move_data->id == POKEMON_GEN3_MOVE_HIGHJUMPKICK) {
            high_jump_kick = move_data;
        }
    }
    assert(jump_kick != NULL && high_jump_kick != NULL);
    assert(jump_kick->failure_policy.kind ==
        POKEMON_MOVE_FAILURE_HYPOTHETICAL_DAMAGE_TO_SOURCE);
    assert(high_jump_kick->failure_policy.kind ==
        POKEMON_MOVE_FAILURE_HYPOTHETICAL_DAMAGE_TO_SOURCE);
    assert(jump_kick->failure_policy.numerator == 1 &&
        jump_kick->failure_policy.denominator == 2);
    assert(jump_kick->failure_policy.minimum == 1 &&
        jump_kick->failure_policy.require_target_type_admission == 1);

    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_JUMPKICK,
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SPLASH);
    init.teams[0].members[0].stats[0] = 300;
    init.teams[0].members[0].stats[1] = 240;
    init.teams[1].members[0].stats[0] = 240;
    init.teams[1].members[0].stats[2] = 120;
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    uint16_t miss_seed = 0;
    uint16_t hit_seed = 0;
    for (uint16_t tail = 1; tail < 8192 && (!miss_seed || !hit_seed); tail++) {
        init.seed[3] = tail;
        PokemonBattle candidate;
        assert(pokemon_battle_init(&candidate, &init) == POKEMON_OK);
        assert(pokemon_battle_step(&candidate, choices) == POKEMON_OK);
        for (size_t draw = 0; draw < candidate.draw_count; draw++) {
            if (candidate.draws[draw].label != POKEMON_DRAW_ACCURACY) continue;
            if (candidate.draws[draw].result >= 95 && !miss_seed) miss_seed = tail;
            if (candidate.draws[draw].result < 95 && !hit_seed) hit_seed = tail;
            break;
        }
    }
    assert(miss_seed && hit_seed);

    PokemonBattle battle;
    init.seed[3] = miss_seed;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    uint16_t hp_before = battle.sides[0].state[0].hp;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].hp < hp_before);
    assert(battle.sides[1].state[0].hp == 240);
    assert(handler_event_count(&battle, POKEMON_HANDLER_EVENT_MOVE_FAIL) == 1);
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 1);
    assert(draw_label_count(&battle, POKEMON_DRAW_CRITICAL) == 1);
    assert(draw_label_count(&battle, POKEMON_DRAW_DAMAGE_ROLL) == 1);
    assert(battle.effect_trace_count == 1);
    const PokemonEffectTrace *crash = &battle.effect_traces[0];
    assert(crash->kind == POKEMON_EFFECT_CRASH_DAMAGE);
    assert(crash->phase == POKEMON_EFFECT_PHASE_MOVE_FAIL);
    assert(crash->move_id == POKEMON_GEN3_MOVE_JUMPKICK);
    assert(crash->target_side == 1 && crash->target_slot == 0);
    assert(crash->damage_target_side == 0 && crash->damage_target_slot == 0);
    assert(crash->damage_basis > 0 && crash->numerator == 1 &&
        crash->denominator == 2 && crash->minimum == 1);
    assert(crash->cap_numerator == 1 && crash->cap_denominator == 2 &&
        crash->cap_value == 120);
    assert(crash->requested == crash->value);
    assert(crash->before == hp_before && crash->after == battle.sides[0].state[0].hp);

    init.seed[3] = hit_seed;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    hp_before = battle.sides[0].state[0].hp;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].hp == hp_before);
    assert(battle.sides[1].state[0].hp < 240);
    assert(handler_event_count(&battle, POKEMON_HANDLER_EVENT_MOVE_FAIL) == 0);
    assert(battle.effect_trace_count == 0);

    /* TryHit failure is still a failed resolved attempt. Accuracy precedes
     * Protect; the crash calculation then owns only its fresh
     * critical and damage draws. Rock Head does not treat this as recoil. */
    init.teams[0].members[0].ability_id = POKEMON_GEN3_ABILITY_ROCKHEAD;
    init.teams[0].members[0].stats[5] = 100;
    init.teams[1].members[0].move_ids[0] = POKEMON_GEN3_MOVE_PROTECT;
    init.teams[1].members[0].stats[5] = 400;
    init.seed[3] = hit_seed;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    hp_before = battle.sides[0].state[0].hp;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].hp < hp_before);
    assert(battle.sides[1].state[0].hp == 240);
    assert(handler_event_count(&battle, POKEMON_HANDLER_EVENT_MOVE_FAIL) == 1);
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 1);
    assert(draw_label_count(&battle, POKEMON_DRAW_CRITICAL) == 1);
    assert(draw_label_count(&battle, POKEMON_DRAW_DAMAGE_ROLL) == 1);
    assert(battle.effect_trace_count == 1);
    assert(battle.effect_traces[0].kind == POKEMON_EFFECT_CRASH_DAMAGE);

    init.teams[0].members[0].ability_id = 0;
    init.teams[0].members[0].stats[5] = 100;
    init.teams[1].members[0].move_ids[0] = POKEMON_GEN3_MOVE_SPLASH;
    init.teams[1].members[0].stats[5] = 100;
    init.teams[1].members[0].species_id = POKEMON_GEN3_SPECIES_BANETTE;
    init.seed[3] = miss_seed;
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    hp_before = battle.sides[0].state[0].hp;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.sides[0].state[0].hp == hp_before);
    assert(handler_event_count(&battle, POKEMON_HANDLER_EVENT_MOVE_FAIL) == 1);
    assert(draw_label_count(&battle, POKEMON_DRAW_ACCURACY) == 1);
    assert(draw_label_count(&battle, POKEMON_DRAW_CRITICAL) == 0);
    assert(draw_label_count(&battle, POKEMON_DRAW_DAMAGE_ROLL) == 0);
    assert(battle.effect_trace_count == 0);
}

static PokemonBattleInit endless_policy_init(uint8_t both_cycle) {
    PokemonBattleInit init = condition_init(
        POKEMON_GEN3_SPECIES_SMEARGLE, POKEMON_GEN3_MOVE_SPLASH,
        POKEMON_GEN3_SPECIES_ALAKAZAM, POKEMON_GEN3_MOVE_SPLASH);
    init.team_sizes[0] = 1;
    init.team_sizes[1] = 1;
    init.teams[0].members[0].item_id = POKEMON_GEN3_ITEM_LEPPABERRY;
    init.teams[0].members[0].move_ids[1] = POKEMON_GEN3_MOVE_RECYCLE;
    if (both_cycle) {
        init.teams[1].members[0].item_id = POKEMON_GEN3_ITEM_LEPPABERRY;
        init.teams[1].members[0].move_ids[1] = POKEMON_GEN3_MOVE_RECYCLE;
    }
    return init;
}

static void test_endless_battle_terminal_policy(void) {
    PokemonChoice choices[POKEMON_SIDES] = {move(0), move(0)};
    PokemonBattleInit init = endless_policy_init(0);
    PokemonBattle battle;

    /* The check is post-turn and strictly after turn 100. It terminates
     * before the Gen 3 shared-turn-speed draw or next request survives. */
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    battle.turn = 100;
    battle.sides[0].state[0].staleness = POKEMON_STALENESS_INTERNAL;
    battle.sides[1].state[0].volatile_staleness =
        POKEMON_STALENESS_EXTERNAL;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.terminal && battle.winner == 1);
    assert(battle.phase == POKEMON_PHASE_TERMINAL);
    assert(draw_label_count(&battle, POKEMON_DRAW_END_TURN) == 0);
    assert(event_kind_count(&battle, POKEMON_EVENT_WIN) == 1);
    assert(pokemon_battle_check_invariants(&battle));

    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    battle.turn = 99;
    battle.sides[0].state[0].staleness = POKEMON_STALENESS_INTERNAL;
    battle.sides[1].state[0].volatile_staleness =
        POKEMON_STALENESS_EXTERNAL;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(!battle.terminal && battle.turn == 100);
    assert(draw_label_count(&battle, POKEMON_DRAW_END_TURN) == 1);

    /* Internal-only cycles cannot blame an opponent. If both submitted sets
     * have restorative cycling means, the terminal result is a tie. */
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    battle.turn = 100;
    battle.sides[0].state[0].staleness = POKEMON_STALENESS_INTERNAL;
    battle.sides[1].state[0].staleness = POKEMON_STALENESS_INTERNAL;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(!battle.terminal);

    /* The clause does not fire when both sides have a legal living non-stale
     * replacement. This consumes request-projected legality, not raw bench
     * occupancy. */
    init = endless_policy_init(0);
    init.team_sizes[0] = 2;
    init.team_sizes[1] = 2;
    init.teams[0].members[1] = make_set(
        POKEMON_GEN3_SPECIES_PERSIAN, POKEMON_GEN3_MOVE_SPLASH,
        250, 100, 100, 100, 100, 100);
    init.teams[1].members[1] = make_set(
        POKEMON_GEN3_SPECIES_STARMIE, POKEMON_GEN3_MOVE_SPLASH,
        250, 100, 100, 100, 100, 100);
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    battle.turn = 100;
    battle.sides[0].state[0].staleness = POKEMON_STALENESS_INTERNAL;
    battle.sides[1].state[0].volatile_staleness =
        POKEMON_STALENESS_EXTERNAL;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(!battle.terminal && battle.turn == 101);
    assert((battle.request.legal_switches[0] & (UINT8_C(1) << 1)) != 0);
    assert((battle.request.legal_switches[1] & (UINT8_C(1) << 1)) != 0);

    init = endless_policy_init(1);
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    battle.turn = 100;
    battle.sides[0].state[0].staleness = POKEMON_STALENESS_INTERNAL;
    battle.sides[1].state[0].volatile_staleness =
        POKEMON_STALENESS_EXTERNAL;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.terminal && battle.winner == -1);
    assert(event_kind_count(&battle, POKEMON_EVENT_TIE) == 1);

    /* Showdown's universal turn limit is independent of EBC evidence. */
    init = endless_policy_init(0);
    assert(pokemon_battle_init(&battle, &init) == POKEMON_OK);
    battle.turn = 1000;
    assert(pokemon_battle_step(&battle, choices) == POKEMON_OK);
    assert(battle.terminal && battle.winner == -1 && battle.turn == 1001);
    assert(draw_label_count(&battle, POKEMON_DRAW_END_TURN) == 0);

    /* Malformed resolved terminal policy fails before destination mutation. */
    PokemonFormatPolicy malformed_policy = POKEMON_GEN3_OU_POLICY;
    malformed_policy.terminal.endless_minimum_turn = 0;
    PokemonResolvedBundle malformed_bundle = POKEMON_GEN3_OU_BUNDLE;
    malformed_bundle.policy = &malformed_policy;
    init.bundle = &malformed_bundle;
    PokemonBattle untouched;
    memset(&untouched, 0xa5, sizeof(untouched));
    PokemonBattle before = untouched;
    assert(pokemon_battle_init(&untouched, &init) ==
        POKEMON_INVALID_CONFIGURATION);
    assert(memcmp(&untouched, &before, sizeof(untouched)) == 0);
}

int main(void) {
    test_curse_invocation_profiles_and_lifecycle();
    test_perish_song_generated_lifecycle();
    test_flash_fire_generated_lifecycle();
    test_rage_generated_reactive_lifecycle();
    test_minimize_generated_marker_and_damage_modifier();
    test_spite_target_last_move_pp_transaction();
    test_source_linked_residual_transfer_family();
    test_generic_charge_lifecycle();
    test_generic_queued_move_interception();
    test_bide_stored_damage_and_direct_pre_use_stage();
    test_fury_cutter_generated_ramping_power_lifecycle();
    test_ramping_power_bundle_validation_is_atomic();
	test_locked_ramp_rollout_ice_ball_and_defense_curl();
    test_stockpile_counter_power_and_heal_family();
    test_move_driven_switch_retains_queue_and_transfers_state();
    test_counter_heal_policy_validation_is_atomic();
    test_type_response_policy_validation_is_atomic();
    test_move_pre_use_program_bundle_validation_is_atomic();
    test_generic_forced_drag_transaction();
    test_generated_drag_blockers();
    test_false_swipe_generic_damage_relay();
    test_color_change_effective_type_product();
    test_generated_sleep_start_program();
    test_generated_sleep_lifecycle_programs();
    test_shared_turn_speed_item_policy();
    test_generated_grouped_secondary_products();
    test_sampled_status_secondary_distribution();
    test_major_status_replacement_transaction();
    test_generated_rest_programs();
    test_generated_synchronize_after_set_status();
    test_haze_field_hit_and_pressure_targeting();
    test_post_hit_self_drop_product();
    test_initial_run_switch_lifecycle_order();
    test_run_switch_faint_update_request_boundary();
    test_atomic_copy_boost_stage_product();
    test_recharge_synthetic_hard_lock_lifecycle();
    test_pre_hit_self_faint_and_fifo_drain();
    test_global_try_move_handler_blocks_self_faint_family();
    test_if_hit_self_faint_family();
    test_damaging_hit_contact_response_boundary();
    test_generated_attraction_family();
    test_role_play_generic_ability_transfer();
    test_skill_swap_transaction();
	test_wonder_guard_generic_effectiveness_gate();
	test_focus_band_generated_damage_gate();
    test_white_herb_after_move_transaction();
    test_mental_herb_use_item_transaction();
    test_effect_spore_uniform_status_selection();
    test_entry_hazard_ko_skips_incoming_start_lifecycle();
    test_residual_status_cure_family();
    test_add_or_restart_volatile_transaction();
    test_source_base_max_hp_fraction_contact_damage();
    test_partial_trap_condition_programs();
	test_source_linked_trap_family();
    test_alternate_plugin_boundary_and_behavior();
    test_gen3_rule_plugin_boundaries();
    test_generated_direct_half_heal_family();
    test_generated_weather_recovery_family();
    test_weather_ball_active_frame_mutation();
    test_conversion_2_resolved_last_move_response();
    test_current_move_slot_type_overlays();
    test_focus_punch_prepared_action_lifecycle();
    test_faint_response_condition_family();
    test_uproar_global_status_and_lock_lifecycle();
    test_thunder_weather_accuracy_pipeline();
    test_solar_beam_two_turn_lifecycle();
    test_generated_two_turn_descriptor_rotation();
    test_fly_two_turn_invulnerability_family();
    test_lock_on_source_bound_accuracy_and_invulnerability();
    test_semi_invulnerable_descriptor_masks_and_validation();
    test_locked_move_action_lock_and_fatigue();
    test_move_invocation_stack_foundation();
    test_magic_coat_reflects_through_called_move_entry();
    test_mirror_move_provenance_and_called_move_entry();
    test_snatch_reenters_active_move_as_handler_owner();
    test_pressure_generic_pp_deduction_stage();
    test_initial_request_and_atomic_rejection();
    test_empty_pp_projects_and_executes_struggle();
    test_explicit_move_slot_and_no_fallback();
    test_move_choice_reducer_composition();
    test_switch_choice_reducer();
    test_transactional_choice_attempt();
    test_request_choice_kind_matrix();
    test_disabled_selection_does_not_force_fallback();
    test_hidden_trap_rejection_updates_only_request();
    test_choice_override_changes_execution_not_queue_priority();
    test_choice_control_start_policies();
    test_choice_band_choice_lock_lifecycle();
    test_choice_control_residual_ends_exact_unusable_owner();
    test_imprison_foe_scoped_choice_lifecycle();
    test_taunt_choice_control_lifecycle();
    test_torment_request_time_cycle();
    test_disable_atomic_start_and_queued_guard();
    test_encore_choice_control_lifecycle();
    test_generated_inert_ability_inventory();
    test_complete_identity_catalog_maps_executable_support();
    test_gen3_ou_format_manifest_and_bounded_legality();
    test_priority_immunity_and_prng_staging();
    test_move_fail_hypothetical_damage_family();
    test_switch_faint_replacement_and_terminal();
    test_mutable_party_order_permutation();
    test_deterministic_replay();
    test_unspecified_gender_is_resolved_at_team_construction();
    test_singles_target_algebra();
    test_miss_stops_later_hit_draws();
    test_critical_and_exact_damage_roll();
    test_high_critical_stage_pipeline();
    test_speed_tie_has_one_owned_draw();
    test_generic_pre_turn_action_and_four_action_sort();
    test_staged_speed_orders_actions_before_tie_draw();
    test_shared_fractional_accuracy_and_always_hit();
    test_unsupported_stage_handler_fails_closed_when_installed();
    test_ground_immunity_causes_are_not_handlers();
    test_foresight_generic_immunity_and_boost_staging();
    test_foresight_positive_and_negative_evasion_product();
    test_water_absorb_is_a_scoped_try_hit_handler();
    test_volt_absorb_generated_interception();
    test_event_interpreter_contract_and_water_absorb_heal();
    test_weighted_active_move_power_distribution();
    test_weighted_move_resolution_outcomes();
    test_boost_table_event_contract();
    test_negative_boost_filter_programs();
    test_safeguard_generic_admission_and_lifecycle();
    test_yawn_delayed_status_lifecycle();
    test_delayed_slot_condition_family();
    test_nightmare_generated_lifecycle();
    test_team_major_status_cure_handlers();
    test_spikes_layered_side_condition_and_entry_hazard();
    test_event_handler_tie_ordering();
    test_event_discovery_d1_scopes();
    test_event_discovery_d2_installed_conditions();
    test_event_discovery_d3_side_and_weather();
    test_holder_installation_lifecycle();
    test_natural_immunity_wins_after_accuracy_consumption();
    test_gen3_accuracy_precedes_protect_try_hit();
    test_bone_rush_immunity_and_accuracy_precedence();
    test_handler_order_and_capacity_failure();
    test_modify_atk_relay_and_burn_stage();
    test_generated_scalar_owner_handlers();
    test_relational_active_ability_modifier();
    test_generated_species_stat_item_handlers();
    test_guts_major_status_evidence_rotation();
    test_starter_ability_base_power_family();
    test_sport_ambient_base_power_family();
    test_holder_status_mask_base_power_predicate();
    test_recent_damage_from_resolved_target_base_power_guard();
    test_dream_eater_move_immunity_is_deferred_after_accuracy();
    test_refresh_move_hit_callback_boundary();
    test_thick_fat_source_base_power();
    test_marvel_scale_modify_defense_staging();
    test_leftovers_residual_healing();
    test_natural_cure_switch_out();
    test_generated_ordinary_attack_family();
    test_generated_type_boost_item_family();
    test_modifier_capacity_failure_is_atomic();
    test_typed_synthetic_self_hit_damage();
    test_confusion_primary_lifecycle_and_own_tempo();
    test_flatter_ordered_primary_effects();
    test_teeter_dance_target_iteration();
    test_confusion_damaging_secondaries_and_shield_dust();
    test_flinch_secondary_family_and_inner_focus();
    test_fake_out_selected_action_counter();
    test_follow_me_singles_try_rejection();
    test_declarative_move_try_rejection();
    test_happiness_base_power_policies();
    test_personal_move_profile_hidden_power();
    test_kings_rock_appended_secondary_pipeline();
    test_shell_bell_actual_move_damage_transaction();
    test_toxic_lifecycle_and_immunity();
    test_generated_status_residual_policy_family();
    test_sandstorm_duration_and_residual_order();
    test_generic_weather_install_replace_and_expire();
    test_weather_modify_damage_event_and_gen3_stage();
    test_cloud_nine_suppresses_effective_not_stored_weather();
    test_weather_status_immunity_is_generated_and_suppressible();
    test_toxic_switch_reset_and_residual_faint();
    test_protect_stall_and_expiry();
    test_generic_stalling_guard_and_endure_damage_relay();
    test_reflect_duration_and_damage_handler();
    test_light_screen_uses_generic_side_condition_lifecycle();
    test_side_condition_expiry_dispatches_end_handler();
    test_move_owned_try_hit_removes_selected_side_conditions();
    test_generated_effect_program_boosts_and_reset();
    test_boosts_modify_standard_damage();
    test_damage_secondaries_and_owned_prng();
    test_generic_item_mutation_family();
    test_trick_item_swap_family();
    test_fixed_heal_berry_transaction();
    test_leppa_berry_pp_transaction();
    test_pinch_boost_berry_transaction();
    test_lansat_berry_volatile_transaction();
    test_starf_berry_random_eligible_boost_transaction();
    test_status_cure_berry_transaction();
    test_volatile_cure_berry_transaction();
    test_combined_cure_berry_transaction();
    test_flavor_berry_nature_transaction();
    test_effect_trace_capacity_failure_is_atomic();
    test_fixed_duration_volatile_install_is_atomic();
    test_damage_relative_recoil_and_rock_head();
    test_generated_recoil_move_family();
    test_damage_relative_drain_and_nonhit_gates();
    test_recoil_faint_replacement_and_terminal();
    test_multihit_distribution_and_per_hit_resolution();
    test_multihit_descriptor_family_and_fixed_count();
    test_specialized_per_hit_composition();
    test_secret_power_resolved_terrain_free_descriptor();
    test_multihit_configuration_rejection();
    test_multihit_gates_early_stop_and_capacity();
    test_typed_ohko_pipeline();
    test_generated_move_call_pool_and_atomic_delegation();
    test_assist_current_party_slot_delegation();
    test_beat_up_party_hit_plan();
    test_generated_fixed_move_delegation();
    test_generated_current_slot_move_delegation();
    test_generated_move_slot_copy_family();
    test_fixed_level_damage_and_gates();
    test_fixed_literal_damage_and_type_boundary();
    test_prepared_retaliation_damage_provenance();
    test_target_relative_damage_and_early_predicate();
    test_random_level_percent_damage_and_owned_prng();
    test_reversal_hp_brackets_and_initial_hp_boundary();
    test_live_hp_scaled_base_power_family();
    test_target_weight_base_power_policy();
    test_transform_generic_profile_copy_policy();
    test_generated_atomic_formula_moves();
    test_initial_toxic_stage_payload();
    test_residual_active_turn_boost_family();
    test_generated_truant_pokemon_owned_phase();
    test_pain_split_atomic_bilateral_hp_assignment();
    test_primary_major_status_family();
    test_status_ability_hooks_and_clauses();
    test_freeze_thaw_boundaries();
    test_generated_weather_form_projection();
    test_generated_ability_lifecycle_weather();
    test_endless_battle_terminal_policy();
    test_generated_paralysis_action_owner();
    test_generated_intimidate_start_family();
    test_trace_replaces_ability_without_starting_copy();
    test_substitute_family();
    test_substitute_blocks_primary_status_family();
    puts("generic Pokemon battle slice tests passed");
    return 0;
}
