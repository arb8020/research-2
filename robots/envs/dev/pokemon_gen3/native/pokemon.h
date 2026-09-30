#pragma once

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define POKEMON_SIDES 2u
#define POKEMON_TEAM_CAPACITY 6u
#define POKEMON_MOVE_CAPACITY 4u
#define POKEMON_QUEUE_CAPACITY 4u
#define POKEMON_EVENT_CAPACITY 32u
#define POKEMON_DRAW_CAPACITY 32u
#define POKEMON_HANDLER_CAPACITY 64u
#define POKEMON_EVENT_FRAME_CAPACITY 8u
#define POKEMON_MOVE_FRAME_CAPACITY 8u
#define POKEMON_MOVE_INVOCATION_TRACE_CAPACITY 16u
#define POKEMON_IMMUNITY_CAPACITY 8u
#define POKEMON_MODIFIER_CAPACITY 20u
#define POKEMON_RELAY_RESULT_CAPACITY 20u
#define POKEMON_DAMAGE_STAGE_CAPACITY 30u
#define POKEMON_EFFECT_TRACE_CAPACITY 16u
#define POKEMON_HIT_TRACE_CAPACITY 14u
#define POKEMON_DAMAGE_FORMULA_TRACE_CAPACITY 4u
#define POKEMON_CONDITION_TRACE_CAPACITY 32u
#define POKEMON_RESIDUAL_CAPACITY 32u
#define POKEMON_FAINT_QUEUE_CAPACITY (POKEMON_TEAM_CAPACITY * POKEMON_SIDES)
#define POKEMON_VOLATILE_CAPACITY 4u
#define POKEMON_SIDE_CONDITION_CAPACITY 5u
#define POKEMON_ACTIVE_POSITION_CAPACITY 2u
#define POKEMON_SLOT_CONDITION_CAPACITY 2u
#define POKEMON_TYPE_CAPACITY 18u

typedef enum {
    POKEMON_OK = 0,
    POKEMON_INVALID_ARGUMENT,
    POKEMON_INVALID_CONFIGURATION,
    POKEMON_ILLEGAL_CHOICE,
    POKEMON_CAPACITY_EXCEEDED,
    /* A legal generated operation selected semantics which this resolved
     * native bundle does not yet execute. The enclosing step rolls back. */
    POKEMON_UNSUPPORTED_CAPABILITY,
} PokemonResult;

typedef enum {
    POKEMON_CATEGORY_PHYSICAL = 1,
    POKEMON_CATEGORY_SPECIAL = 2,
    POKEMON_CATEGORY_STATUS = 3,
} PokemonCategory;

typedef struct {
    uint16_t move_id;
    uint8_t pp;
    PokemonCategory category;
} PokemonMoveChoiceSlot;

typedef enum {
    POKEMON_MOVE_RESTRICTION_DISABLE_EQUAL = 1,
    POKEMON_MOVE_RESTRICTION_DISABLE_UNEQUAL,
    POKEMON_MOVE_RESTRICTION_DISABLE_CATEGORY,
    POKEMON_MOVE_RESTRICTION_DISABLE_LAST_NONFALLBACK,
} PokemonMoveRestrictionKind;

typedef struct {
    PokemonMoveRestrictionKind kind;
    uint16_t move_id;
    uint16_t fallback_move_id;
    PokemonCategory category;
} PokemonMoveRestriction;

typedef struct {
    PokemonMoveRestriction *values;
    size_t count;
    size_t capacity;
    uint16_t last_move_id;
    uint16_t fallback_move_id;
} PokemonMoveRestrictionBuffer;

typedef enum {
    POKEMON_SWITCH_CHOICE_VOLUNTARY = 1,
    POKEMON_SWITCH_CHOICE_FORCED_REPLACEMENT,
    /* A replacement selected after a move has already resolved.  This is
     * neither a voluntary turn choice (trapping does not apply) nor a faint
     * replacement (the retained action queue must resume). */
    POKEMON_SWITCH_CHOICE_MOVE_DRIVEN,
} PokemonSwitchChoiceMode;

typedef enum {
    POKEMON_SWITCH_RESTRICTION_DISALLOW_ALL = 1,
} PokemonSwitchRestrictionKind;

typedef struct {
    PokemonSwitchRestrictionKind kind;
    uint8_t hidden;
} PokemonSwitchRestriction;

typedef struct {
    PokemonSwitchRestriction *values;
    size_t count;
    size_t capacity;
} PokemonSwitchRestrictionBuffer;

typedef enum {
    POKEMON_TRAP_DISCLOSURE_NONE = 0,
    POKEMON_TRAP_DISCLOSURE_MAYBE,
    POKEMON_TRAP_DISCLOSURE_KNOWN,
} PokemonTrapDisclosure;

typedef struct {
    uint8_t candidate_mask;
    uint8_t definitive_mask;
    PokemonSwitchChoiceMode mode;
    PokemonTrapDisclosure trap_disclosure;
    uint8_t updated;
} PokemonSwitchChoiceRequest;

typedef enum {
    POKEMON_CHOICE_ATTEMPT_ACCEPTED = 1,
    POKEMON_CHOICE_ATTEMPT_REJECTED_HIDDEN_TRAP,
    POKEMON_CHOICE_ATTEMPT_REJECTED_CANT_UNDO,
} PokemonChoiceAttemptOutcome;

typedef enum {
    POKEMON_MOVE_CHOICE_SET_SELECTABLE = 1,
    POKEMON_MOVE_CHOICE_SET_HARD_LOCK,
    POKEMON_MOVE_CHOICE_SET_FALLBACK,
} PokemonMoveChoiceSetKind;

typedef struct {
    PokemonMoveChoiceSetKind kind;
    uint8_t slot_count;
    uint8_t legal_slot_mask;
    uint16_t synthetic_move_id;
} PokemonMoveChoiceSet;

typedef enum {
    POKEMON_CHOICE_REQUEST_NONE = 0,
    POKEMON_CHOICE_REQUEST_DISABLE_STORED_MOVE,
    POKEMON_CHOICE_REQUEST_DISABLE_EXCEPT_STORED_MOVE,
    POKEMON_CHOICE_REQUEST_DISABLE_CATEGORY,
    POKEMON_CHOICE_REQUEST_DISABLE_LAST_MOVE,
    POKEMON_CHOICE_REQUEST_HARD_LOCK_SYNTHETIC,
} PokemonChoiceRequestOp;

typedef enum {
    POKEMON_CHOICE_ACTION_NONE = 0,
    POKEMON_CHOICE_ACTION_OVERRIDE_WITH_STORED_MOVE,
    POKEMON_CHOICE_ACTION_REJECT_STORED_MOVE,
    POKEMON_CHOICE_ACTION_REJECT_CATEGORY,
    POKEMON_CHOICE_ACTION_CONSUME_AND_PREVENT_SYNTHETIC,
} PokemonChoiceActionOp;

typedef enum {
    POKEMON_CHOICE_RESIDUAL_NONE = 0,
    POKEMON_CHOICE_RESIDUAL_END_IF_STORED_MOVE_UNUSABLE,
} PokemonChoiceResidualOp;

typedef enum {
    POKEMON_CHOICE_START_NONE = 0,
    POKEMON_CHOICE_START_CAPTURE_LAST_USABLE_MOVE,
    POKEMON_CHOICE_START_CAPTURE_LAST_ENCORE_ELIGIBLE_MOVE,
} PokemonChoiceStartOp;

typedef enum {
    POKEMON_CHOICE_START_DURATION_UNCHANGED = 0,
    POKEMON_CHOICE_START_DURATION_INCREMENT_IF_ALREADY_MOVED,
} PokemonChoiceStartDurationOp;

typedef struct {
    uint16_t owner_descriptor_id;
    PokemonChoiceStartOp start_op;
    PokemonChoiceStartDurationOp start_duration_op;
    PokemonChoiceRequestOp request_op;
    PokemonChoiceActionOp action_op;
    PokemonChoiceResidualOp residual_op;
    PokemonCategory category;
    uint16_t synthetic_move_id;
    uint16_t required_held_item_id;
    uint8_t allows_indefinite_start;
    int8_t request_priority;
    int8_t action_priority;
    uint16_t start_handler_id;
    uint16_t request_handler_id;
    uint16_t action_handler_id;
    uint16_t residual_handler_id;
} PokemonChoiceControlPolicy;

typedef struct {
    uint16_t stored_move_id;
    uint8_t duration;
    uint8_t admitted;
} PokemonChoiceControlStart;

typedef enum {
    POKEMON_MOVE_SLOT_ABSENT = 0,
    POKEMON_MOVE_SLOT_PRESENT_ZERO_PP,
    POKEMON_MOVE_SLOT_PRESENT_WITH_PP,
} PokemonMoveSlotState;

typedef enum {
    POKEMON_CHOICE_ACTION_STAGE_OVERRIDE = 1,
    POKEMON_CHOICE_ACTION_STAGE_GUARD,
} PokemonChoiceActionStage;

typedef struct {
    uint16_t executed_move_id;
    uint8_t allowed;
} PokemonChoiceActionDecision;

typedef enum {
    POKEMON_ACCURACY_ALWAYS = 1,
    POKEMON_ACCURACY_PERCENT,
} PokemonAccuracyKind;

typedef struct {
    PokemonAccuracyKind kind;
    uint8_t percent;
} PokemonAccuracy;

typedef enum {
    POKEMON_CHOICE_NONE = 0,
    POKEMON_CHOICE_MOVE,
    POKEMON_CHOICE_SWITCH,
} PokemonChoiceKind;

typedef struct {
    uint8_t flags;
    uint8_t type;
    PokemonCategory category;
    PokemonAccuracy accuracy;
    uint16_t power_q12;
} PokemonWeatherMovePolicy;

enum {
    POKEMON_WEATHER_MOVE_TYPE = 1u << 0,
    POKEMON_WEATHER_MOVE_CATEGORY = 1u << 1,
    POKEMON_WEATHER_MOVE_ACCURACY = 1u << 2,
    POKEMON_WEATHER_MOVE_POWER = 1u << 3,
    POKEMON_WEATHER_MOVE_SKIP_CHARGE = 1u << 4,
    POKEMON_WEATHER_MOVE_SUPPRESS_TARGET = 1u << 5,
};

typedef struct {
    PokemonChoiceKind kind;
    uint8_t slot;
} PokemonChoice;

typedef enum {
    POKEMON_REQUEST_MOVE = 1,
    POKEMON_REQUEST_SWITCH,
    POKEMON_REQUEST_WAIT,
    POKEMON_REQUEST_TERMINAL,
} PokemonRequestKind;

typedef struct {
    PokemonRequestKind kind[POKEMON_SIDES];
    uint8_t required_sides;
    uint8_t legal_moves[POKEMON_SIDES];
    uint8_t legal_switches[POKEMON_SIDES];
    PokemonSwitchChoiceRequest switch_choices[POKEMON_SIDES];
    uint16_t forced_move_id[POKEMON_SIDES];
} PokemonRequest;

typedef struct {
    PokemonRequestKind request_kind;
    uint8_t legal_move_mask;
    PokemonSwitchChoiceRequest switches;
    PokemonChoice choice;
    uint8_t has_choice;
    uint8_t cant_undo;
} PokemonChoiceAttemptState;

typedef struct {
    uint16_t id;
    uint8_t types[2];
    uint8_t type_count;
    /* Current-form mass in hectograms. Mutable form identity selects a row;
     * the kernel does not cache a second, drift-prone weight value. */
    uint16_t weight_hg;
} PokemonSpeciesData;

#define POKEMON_WEIGHT_POWER_MAX_BRACKETS 6

typedef struct {
    uint16_t id;
    uint8_t bracket_count;
    /* For bracket i < count - 1, weight < upper_bounds_hg[i] selects
     * powers[i]. The final bracket is unbounded. */
    uint16_t upper_bounds_hg[POKEMON_WEIGHT_POWER_MAX_BRACKETS - 1];
    uint16_t powers[POKEMON_WEIGHT_POWER_MAX_BRACKETS];
} PokemonWeightPowerPolicy;

typedef struct {
    uint16_t id;
    uint16_t personal_move_profile_kind;
    uint8_t copied_move_pp_cap;
    uint8_t reject_source_transformed;
    uint8_t reject_target_transformed;
    uint8_t reject_target_substitute;
    uint8_t copied_ability_runs_start;
} PokemonTransformPolicy;

/* A resolved generation bundle maps one immutable base species family onto
 * battle-time forms selected by effective weather. Zero denotes the base
 * form. This first kernel capability preserves calculated stats; bundle
 * validation therefore requires every mapped form to have identical base
 * stats. Generations needing form-stat recalculation declare another kernel
 * capability instead of silently relying on this policy. */
typedef struct {
    uint16_t id;
    uint16_t base_species_id;
    uint16_t clear_species_id;
    uint16_t sun_species_id;
    uint16_t rain_species_id;
    uint16_t hail_species_id;
} PokemonWeatherFormPolicy;

typedef uint8_t PokemonSemiInvulnerableMask;
enum {
    POKEMON_SEMI_INVULNERABLE_AIRBORNE = 1u << 0,
    POKEMON_SEMI_INVULNERABLE_UNDERGROUND = 1u << 1,
    POKEMON_SEMI_INVULNERABLE_UNDERWATER = 1u << 2,
};

typedef enum {
    POKEMON_DAMAGE_STANDARD = 1,
    POKEMON_DAMAGE_FIXED_LEVEL,
    POKEMON_DAMAGE_FIXED_LITERAL,
    POKEMON_DAMAGE_TARGET_HP_FRACTION,
    POKEMON_DAMAGE_TARGET_SOURCE_HP_DIFFERENCE,
    /* Fixed damage equal to the target's current real HP. Substitute still
     * intercepts the resolved amount at the ordinary primary-hit boundary. */
    POKEMON_DAMAGE_TARGET_CURRENT_HP,
    POKEMON_DAMAGE_RANDOM_LEVEL_PERCENT,
    POKEMON_DAMAGE_HP_BRACKET,
    /* Fixed damage read from the selected move user's installed condition.
     * damage_parameter names the condition descriptor. */
    POKEMON_DAMAGE_OWNER_CONDITION_VALUE,
} PokemonDamageFormula;

typedef enum {
    POKEMON_OHKO_NONE = 0,
    POKEMON_OHKO_ANY,
    /* Later generations may exclude one effective target type. */
    POKEMON_OHKO_EXCLUDED_TYPE,
} PokemonOhkoKind;

typedef struct {
    PokemonOhkoKind kind;
    uint8_t excluded_type;
} PokemonOhkoMovePolicy;

typedef uint8_t PokemonRetaliationClassMask;
enum {
    POKEMON_RETALIATION_PHYSICAL = 1u << 0,
    POKEMON_RETALIATION_SPECIAL = 1u << 1,
};

typedef enum {
    POKEMON_RETALIATION_FROM_ACTIVE_CATEGORY = 0,
    POKEMON_RETALIATION_FIXED_CLASS,
} PokemonRetaliationClassPolicy;

typedef enum {
    POKEMON_SELF_FAINT_NONE = 0,
    POKEMON_SELF_FAINT_PRE_HIT,
    /* Queue the user after the complete primary hit transaction succeeds;
     * the selected-action owner retains AfterMove before faint drain. */
    POKEMON_SELF_FAINT_IF_HIT,
} PokemonSelfFaintTiming;

/* A generated move callback may react only after ordinary target/hit
 * admission has failed. The plugin owns the formula; the kernel owns event
 * staging and mutation. */
typedef enum {
    POKEMON_MOVE_FAILURE_NONE = 0,
    POKEMON_MOVE_FAILURE_HYPOTHETICAL_DAMAGE_TO_SOURCE,
} PokemonMoveFailureKind;

typedef struct {
    PokemonMoveFailureKind kind;
    uint8_t numerator;
    uint8_t denominator;
    uint8_t target_max_hp_cap_numerator;
    uint8_t target_max_hp_cap_denominator;
    uint8_t minimum;
    uint8_t require_target_type_admission;
} PokemonMoveFailurePolicy;

typedef enum {
    POKEMON_DEFENSE_POLICY_STANDARD = 0,
    POKEMON_DEFENSE_POLICY_SELF_DESTRUCT,
} PokemonMoveDefensePolicy;

typedef enum {
    POKEMON_TARGET_ADJACENT_ALLY = 1,
    POKEMON_TARGET_ALL,
    POKEMON_TARGET_ALL_ADJACENT,
    POKEMON_TARGET_ALL_ADJACENT_FOES,
    POKEMON_TARGET_ALLY_SIDE,
    POKEMON_TARGET_ALLY_TEAM,
    POKEMON_TARGET_ANY,
    POKEMON_TARGET_FOE_SIDE,
    POKEMON_TARGET_NORMAL,
    POKEMON_TARGET_RANDOM_NORMAL,
    POKEMON_TARGET_SCRIPTED,
    POKEMON_TARGET_SELF,
} PokemonMoveTarget;

typedef enum {
    POKEMON_RESOLVED_TARGET_NONE = 1,
    POKEMON_RESOLVED_TARGET_USER,
    POKEMON_RESOLVED_TARGET_FOE,
    POKEMON_RESOLVED_TARGET_FIELD,
    POKEMON_RESOLVED_TARGET_USER_SIDE,
    POKEMON_RESOLVED_TARGET_USER_TEAM,
    POKEMON_RESOLVED_TARGET_FOE_SIDE,
    POKEMON_RESOLVED_TARGET_SCRIPTED,
} PokemonResolvedTarget;

typedef enum {
    POKEMON_TARGET_SUPPORTED = 1,
    POKEMON_TARGET_UNSUPPORTED_TEAM_SCOPE,
    POKEMON_TARGET_UNSUPPORTED_FOE_SIDE_SCOPE,
    POKEMON_TARGET_UNSUPPORTED_SCRIPTED_PROVENANCE,
} PokemonTargetCapability;

typedef struct {
    PokemonMoveTarget mode;
    PokemonResolvedTarget resolved;
    PokemonTargetCapability capability;
    int8_t target_loc;
} PokemonTargetRule;

typedef enum {
    POKEMON_BASE_POWER_STANDARD = 0,
    POKEMON_BASE_POWER_SOURCE_HP_RATIO,
    POKEMON_BASE_POWER_SOURCE_HAPPINESS,
    POKEMON_BASE_POWER_SOURCE_UNHAPPINESS,
    /* Power is supplied by immutable set data normalized through the
     * generation plugin.  The generic kernel never derives it from IVs. */
    POKEMON_BASE_POWER_PERSONAL_MOVE_PROFILE,
    /* Multiply the descriptor's base power by the one-based hit index. */
    POKEMON_BASE_POWER_HIT_INDEX,
    /* Resolve power from the target's current species identity and a
     * generation-owned monotone weight bracket table. */
    POKEMON_BASE_POWER_TARGET_WEIGHT,
} PokemonBasePowerPolicy;

typedef enum {
    POKEMON_MULTIHIT_ACCURACY_ONCE = 0,
    POKEMON_MULTIHIT_ACCURACY_EACH_HIT,
} PokemonMultiHitAccuracyPolicy;

/* Category answers the generation's physical/special/status question. It
 * does not, by itself, say whether selecting the move enters the damage
 * pipeline: Bide is Physical in Gen 3 but its selected action only installs
 * and advances a condition. Generated data resolves that independent fact. */
typedef enum {
    POKEMON_MOVE_RESOLUTION_DEFAULT = 0,
    POKEMON_MOVE_RESOLUTION_NONE,
    POKEMON_MOVE_RESOLUTION_DAMAGE,
} PokemonMoveResolution;

typedef struct {
    /* Opaque generation-owned identity selected by generated move data. */
    uint16_t kind;
    uint8_t type;
    PokemonCategory category;
    uint8_t power;
} PokemonPersonalMoveProfile;

typedef enum {
    POKEMON_SWITCH_TRANSFER_NONE = 0,
    /* Copy boost stages and every volatile whose resolved condition does not
     * carry no_copy. The kernel never enumerates generation condition IDs. */
    POKEMON_SWITCH_TRANSFER_BOOSTS_AND_VOLATILES,
} PokemonSwitchTransferPolicy;

typedef struct {
    uint16_t id;
    /* Immutable catalog identity for generated moves. Zero is reserved for
     * kernel-owned synthetic descriptors which can never enter a call pool. */
    uint16_t catalog_id;
    uint8_t type;
    PokemonCategory category;
	/* Dynamic Gen 3 power callbacks reach 480 (Rollout/Ice Ball) and must not
	 * truncate at the immutable move descriptor boundary. */
    uint16_t power;
    PokemonAccuracy accuracy;
    uint8_t ignore_accuracy;
    uint8_t ignore_evasion;
    int8_t priority;
    /* Raw generation descriptor PP and the resolved submitted-set maximum.
     * Replacement mechanics calculate a new slot maximum from raw_pp and the
     * destination slot's immutable PP-Up count. */
    uint8_t raw_pp;
    uint8_t pp;
    uint8_t no_pp_boosts;
    PokemonMoveTarget target;
    uint64_t flags;
    /* Build-time-flattened generation/plugin modifier classes. The kernel
     * interprets only generated tag operands and never move identities. */
    uint64_t modifier_tags;
    /* Generation-flattened reachability against hidden target states. Hit
     * admission and doubled damage are independent facts; marker handlers
     * select the exact damage stage at which the latter composes. */
    PokemonSemiInvulnerableMask semi_invulnerable_hit_mask;
    PokemonSemiInvulnerableMask semi_invulnerable_double_mask;
    uint16_t effect_offset;
    uint8_t effect_count;
    uint8_t multihit_min;
    uint8_t multihit_max;
    PokemonMultiHitAccuracyPolicy multihit_accuracy;
    PokemonDamageFormula damage_formula;
    /* Operand for descriptor-owned formulas such as literal fixed damage.
     * Zero when the selected formula has no descriptor operand. */
    uint16_t damage_parameter;
    /* Declarative pre-BasePower-event formula. The generic kernel resolves
     * this from live battle state; generated data selects the policy. */
    PokemonBasePowerPolicy base_power_policy;
    /* Descriptor-owned target-status adjustment performed after the
     * pre-BasePower formula and before BasePower event dispatch. A zero mask
     * requires a zero multiplier; otherwise the multiplier must be at least
     * two. Status identities remain generation/plugin data. */
    uint16_t target_status_power_mask;
    uint8_t target_status_power_multiplier;
    /* Effective Showdown ignoreImmunity policy after generation inheritance.
     * Damaging moves always enter ordinary hit admission; this bit selects
     * the exceptional status moves which also consult natural type immunity. */
    uint8_t checks_natural_type_immunity;
    /* Effective, generation-flattened flag. It is independent of sound. */
    uint8_t bypass_substitute;
    uint8_t defrost;
    uint8_t thaws_target;
    /* Base critical-hit stage from the generation-flattened move descriptor.
     * The generation plugin maps the post-event stage to a probability. */
    uint8_t critical_stage;
    /* Generation-flattened calling-move policy.  This is data, not a
     * caller-ID check in the generic interpreter. */
    uint8_t mirror_eligible;
    PokemonWeatherMovePolicy weather_policy[5];
    PokemonSelfFaintTiming self_faint_timing;
    PokemonMoveDefensePolicy defense_policy;
    /* Effective after generation inheritance. Choice-control conditions use
     * this fact without knowing the generation's raw move-flag vocabulary. */
    uint8_t encore_eligible;
    /* Generated semantic families in which this move may be selected by a
     * caller. Raw generation flag vocabularies stay outside the kernel. */
    uint8_t call_eligibility;
    /* Generated copy-family admission bits (for example failmimic and
     * nosketch after generation inheritance). */
    uint8_t copy_eligibility;
    /* Effective generated semantic bit used by sleep lifecycle policies. */
    uint8_t sleep_usable;
    /* Optional condition catalog identity installed on the move user by a
     * separate pre-turn queue action.  This is the fixed-data form of
     * Showdown's beforeTurnCallback boundary; zero means no preparation. */
    uint16_t pre_turn_condition_descriptor;
    /* Generation-flattened class used by generic damage-provenance handlers.
     * This is independent of the ordinary damage category where a generation
     * defines an exception such as Gen 3 Hidden Power. */
    PokemonRetaliationClassMask retaliation_class_mask;
    PokemonRetaliationClassPolicy retaliation_class_policy;
    /* Zero for ordinary moves.  Nonzero selects a generation-owned profile
     * derived from the user's immutable set data at battle construction. */
    uint16_t personal_move_profile_kind;
    /* Optional battlefield-position-owned condition installed before the
     * ordinary hit pipeline. The resolved descriptor selects lifecycle and
     * expiry semantics; zero denotes an ordinary move. */
    uint16_t slot_condition_descriptor;
    /* Generated pre-turn installation and admission policy. Zero retains the
     * historical USER default for descriptors without pre-turn work. */
    uint8_t pre_turn_target;
    uint16_t pre_turn_blocked_status_mask;
    /* Declarative transformation used only while the resolved target is in a
     * switch transaction. Zero denotes ordinary accuracy/power behavior. */
    uint8_t switching_target_always_hit;
    uint8_t switching_target_power_multiplier;
    /* A successful move may suspend the current action queue and request a
     * replacement. Zero denotes an ordinary move. The skip bit is explicit:
     * pivot families differ in whether BeforeSwitchOut participates. */
    PokemonSwitchTransferPolicy self_switch_transfer;
    uint8_t self_switch_skip_before_switch_out;
    PokemonOhkoMovePolicy ohko;
    /* Zero means this move never delegates through an immutable call pool. */
    uint16_t call_pool_id;
    PokemonMoveResolution resolution;
    /* Scale for POKEMON_DAMAGE_OWNER_CONDITION_VALUE. Zero defaults to one
     * for compatibility with hand-built test descriptors. */
    uint8_t owner_condition_damage_multiplier;
    PokemonMoveFailurePolicy failure_policy;
    /* Required exactly for POKEMON_BASE_POWER_TARGET_WEIGHT. */
    uint16_t weight_power_policy_id;
} PokemonMoveData;

/* Invocation-local variants are flattened generation data. A ModifyMove
 * handler selects one profile; the generic kernel then continues through the
 * ordinary target/effect pipeline without knowing the owning move identity. */
typedef struct {
    uint16_t id;
    uint16_t owner_move_id;
    PokemonMoveTarget target;
    uint16_t effect_offset;
    uint8_t effect_count;
    uint16_t tag;
} PokemonMoveInvocationProfile;

typedef struct {
    uint16_t id;
    uint32_t current_user_type_mask;
    uint16_t matching_profile_id;
    uint16_t nonmatching_profile_id;
} PokemonMoveProfileSelection;

typedef enum {
    POKEMON_PRE_TURN_TARGET_USER = 1,
    POKEMON_PRE_TURN_TARGET_MOVE_TARGET,
} PokemonPreTurnTarget;

typedef enum {
    POKEMON_EFFECT_PHASE_PRIMARY = 1,
    POKEMON_EFFECT_PHASE_PRIMARY_HIT,
    POKEMON_EFFECT_PHASE_AFTER_HIT,
    /* A guaranteed move callback after a connected hit. Unlike a secondary,
     * this phase never owns a probability roll. */
    POKEMON_EFFECT_PHASE_AFTER_HIT_CALLBACK,
    /* A move-owned post-hit effect which Showdown treats as part of the
     * primary move result, rather than as a conventional secondary. */
    POKEMON_EFFECT_PHASE_SELF_DROP,
    POKEMON_EFFECT_PHASE_AFTER_DAMAGE,
    POKEMON_EFFECT_PHASE_AFTER_MOVE,
    /* A generated move failure callback after target/hit admission fails. */
    POKEMON_EFFECT_PHASE_MOVE_FAIL,
} PokemonEffectPhase;

typedef enum {
    POKEMON_EFFECT_TARGET_USER = 1,
    POKEMON_EFFECT_TARGET_MOVE_TARGET,
} PokemonEffectTarget;

typedef enum {
    POKEMON_EFFECT_SET_STATUS = 1,
    POKEMON_EFFECT_ADD_VOLATILE,
    POKEMON_EFFECT_ADD_SIDE_CONDITION,
    POKEMON_EFFECT_ADD_WEATHER,
    POKEMON_EFFECT_BOOST,
    POKEMON_EFFECT_DAMAGE_RELATIVE,
    POKEMON_EFFECT_CREATE_SUBSTITUTE,
    POKEMON_EFFECT_ADD_TIMED_VOLATILE,
    POKEMON_EFFECT_CALL_LAST_ATTACK_MOVE,
    POKEMON_EFFECT_HEAL_FRACTION,
    POKEMON_EFFECT_HEAL_WEATHER_FRACTION,
    POKEMON_EFFECT_CURE_STATUS,
    POKEMON_EFFECT_RECYCLE_ITEM,
    POKEMON_EFFECT_STEAL_ITEM,
    POKEMON_EFFECT_KNOCK_OFF_ITEM,
    POKEMON_EFFECT_SWAP_ITEMS,
    POKEMON_EFFECT_REMOVE_VOLATILE,
    /* Remove a generated descriptor from the selected side after a
     * qualifying hit.  The descriptor, not a generation-local condition ID
     * in kernel control flow, owns the mechanic. */
    POKEMON_EFFECT_REMOVE_SIDE_CONDITION,
    /* Showdown's stallingMove protocol: require a later actionable queue
     * entry, resolve the generation-owned shared stall policy, install the
     * descriptor-selected one-turn guard, then add/restart Stall. */
    POKEMON_EFFECT_INSTALL_STALLING_GUARD,
    /* Install a volatile on the move user while preserving the resolved move
     * target as its source provenance. */
    POKEMON_EFFECT_ADD_SOURCE_BOUND_VOLATILE,
    /* Select one generated major-status candidate after the ordinary
     * secondary gate and target-effect admission, then enter SetStatus. */
    POKEMON_EFFECT_SET_STATUS_FROM_DISTRIBUTION,
    POKEMON_EFFECT_FORCE_SWITCH,
    /* Trace-only result of a typed move-failure policy. */
    POKEMON_EFFECT_CRASH_DAMAGE,
} PokemonEffectKind;

typedef enum {
    POKEMON_DAMAGE_RELATIVE_DRAIN = 1,
    POKEMON_DAMAGE_RELATIVE_RECOIL,
    /* An ordinary move's real-HP commit.  Despite the legacy type name this
     * is not relative damage; it identifies the shared pre-mutation Damage
     * relay used by move, item, ability, and condition handlers. */
    POKEMON_DAMAGE_EVENT_ORDINARY_MOVE,
} PokemonDamageRelativeKind;

typedef enum {
    POKEMON_DAMAGE_PREVENTABILITY_NONE = 0,
    POKEMON_DAMAGE_UNPREVENTABLE,
    POKEMON_DAMAGE_PREVENTABLE,
} PokemonDamagePreventability;

/* Damage calculation is deliberately separate from move-hit admission.  A
 * caller which already owns accuracy/immunity/critical staging can request an
 * ordinary calculation; installed conditions can request the generation's
 * synthetic self-hit calculation without pretending to be a selected move. */
typedef enum {
    POKEMON_DAMAGE_MODE_ORDINARY_MOVE = 1,
    POKEMON_DAMAGE_MODE_SYNTHETIC_SELF_HIT,
} PokemonDamageMode;

typedef enum {
    POKEMON_STAT_ATK = 0,
    POKEMON_STAT_DEF,
    POKEMON_STAT_SPA,
    POKEMON_STAT_SPD,
    POKEMON_STAT_SPE,
    POKEMON_STAT_ACCURACY,
    POKEMON_STAT_EVASION,
    POKEMON_STAT_COUNT,
} PokemonStat;

typedef struct {
    PokemonEffectKind kind;
    PokemonEffectPhase phase;
    PokemonEffectTarget target;
    uint8_t chance;
    uint16_t argument;
    int8_t amount;
    uint8_t fraction_numerator;
    uint8_t fraction_denominator;
    PokemonDamagePreventability damage_preventability;
} PokemonEffectOp;

typedef uint8_t PokemonEventId;
typedef PokemonEventId PokemonHandlerEvent;
enum {
    POKEMON_HANDLER_EVENT_ACCURACY = 1,
    POKEMON_HANDLER_EVENT_AFTER_MOVE = 4,
    POKEMON_HANDLER_EVENT_AFTER_MOVE_SECONDARY_SELF = 6,
    POKEMON_HANDLER_EVENT_BEFORE_MOVE = 10,
    POKEMON_HANDLER_EVENT_BEFORE_SWITCH_OUT = 11,
    POKEMON_HANDLER_EVENT_DISABLE_MOVE = 15,
    POKEMON_HANDLER_EVENT_HIT = 21,
    POKEMON_HANDLER_EVENT_LOCK_MOVE = 25,
    POKEMON_HANDLER_EVENT_BASE_POWER = 9,
    POKEMON_HANDLER_EVENT_MOVE_ABORTED = 40,
    POKEMON_HANDLER_EVENT_MOVE_FAIL = 41,
    POKEMON_HANDLER_EVENT_OVERRIDE_ACTION = 43,
    POKEMON_HANDLER_EVENT_DAMAGE = 12,
    POKEMON_HANDLER_EVENT_DAMAGING_HIT = 13,
    POKEMON_HANDLER_EVENT_DEDUCT_PP = 14,
    POKEMON_HANDLER_EVENT_IMMUNITY = 23,
    POKEMON_HANDLER_EVENT_MODIFY_ACCURACY = 27,
    POKEMON_HANDLER_EVENT_MODIFY_ATK = 28,
    POKEMON_HANDLER_EVENT_MODIFY_CRIT_RATIO = 30,
    POKEMON_HANDLER_EVENT_MODIFY_DAMAGE = 31,
    POKEMON_HANDLER_EVENT_MODIFY_DAMAGE_PHASE1 = 32,
    POKEMON_HANDLER_EVENT_MODIFY_DEF = 33,
    POKEMON_HANDLER_EVENT_MODIFY_MOVE = 34,
    POKEMON_HANDLER_EVENT_MODIFY_BOOST = 29,
    POKEMON_HANDLER_EVENT_MODIFY_SECONDARIES = 35,
    POKEMON_HANDLER_EVENT_MODIFY_SPA = 36,
    POKEMON_HANDLER_EVENT_MODIFY_SPD = 37,
    POKEMON_HANDLER_EVENT_MODIFY_SPE = 38,
    POKEMON_HANDLER_EVENT_MODIFY_TYPE = 39,
    POKEMON_HANDLER_EVENT_NEGATE_IMMUNITY = 42,
    POKEMON_HANDLER_EVENT_PREPARE_HIT = 44,
    POKEMON_HANDLER_EVENT_REDIRECT_TARGET = 45,
    POKEMON_HANDLER_EVENT_RESIDUAL = 46,
    POKEMON_HANDLER_EVENT_RESTART = 47,
    POKEMON_HANDLER_EVENT_SET_STATUS = 48,
    POKEMON_HANDLER_EVENT_TRAP_POKEMON = 54,
    POKEMON_HANDLER_EVENT_TRY = 55,
    POKEMON_HANDLER_EVENT_TRY_BOOST = 57,
    POKEMON_HANDLER_EVENT_TRY_ADD_VOLATILE = 56,
    POKEMON_HANDLER_EVENT_TRY_HIT = 60,
    POKEMON_HANDLER_EVENT_TRY_IMMUNITY = 61,
    POKEMON_HANDLER_EVENT_TRY_MOVE = 62,
    POKEMON_HANDLER_EVENT_UPDATE = 64,
    POKEMON_HANDLER_EVENT_WEATHER_MODIFY_DAMAGE = 69,
    POKEMON_HANDLER_EVENT_CHANGE_BOOST = 70,
    POKEMON_HANDLER_EVENT_ENTRY_HAZARD = 19,
    POKEMON_HANDLER_EVENT_FAINT = 20,
    POKEMON_HANDLER_EVENT_END = 18,
    POKEMON_HANDLER_EVENT_START = 50,
    POKEMON_HANDLER_EVENT_SWITCH_IN = 51,
    POKEMON_HANDLER_EVENT_SWITCH_OUT = 52,
    POKEMON_HANDLER_EVENT_DRAG_OUT = 16,
    POKEMON_HANDLER_EVENT_WEATHER_CHANGE = 68,
    POKEMON_HANDLER_EVENT_AFTER_SUB_DAMAGE = 8,
    POKEMON_HANDLER_EVENT_AFTER_SET_STATUS = 7,
    POKEMON_HANDLER_EVENT_TRY_PRIMARY_HIT = 63,
    POKEMON_HANDLER_EVENT_TRY_HEAL = 59,
    POKEMON_HANDLER_EVENT_TRY_EAT_ITEM = 58,
    /* Direct item effect callback; outside Battle#runEvent's frozen table. */
    POKEMON_HANDLER_EVENT_ITEM_EAT = 71,
    /* Explicit interpreter boundaries absent from the frozen callback-derived
     * vocabulary because Gen 3's CriticalHit callbacks are literal `false`. */
    POKEMON_HANDLER_EVENT_CRITICAL_HIT = 72,
    /* Move-owned singleEvent('Hit') callback. This boolean/null event is
     * distinct from holder-wide void runEvent('Hit'). */
    POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK = 73,
    /* Move-owned singleEvent('HitField') callback. */
    POKEMON_HANDLER_EVENT_MOVE_HIT_FIELD_CALLBACK = 74,
    /* Typed admission boundary for transactional ability installation. */
    POKEMON_HANDLER_EVENT_SET_ABILITY = 75,
    /* Move-owned singleEvent('UseMoveMessage') notification. */
    POKEMON_HANDLER_EVENT_USE_MOVE_MESSAGE = 66,
    POKEMON_HANDLER_EVENT_INVULNERABILITY = 24,
};

typedef enum {
    POKEMON_EVENT_ALGEBRA_NUMERIC_OR_CANCEL = 1,
    POKEMON_EVENT_ALGEBRA_MUTABLE_VALUE,
    POKEMON_EVENT_ALGEBRA_BOOLEAN_OR_NULL,
    /* Invulnerability distinguishes boolean false (miss) from numeric zero
     * (successful source-owned bypass). */
    POKEMON_EVENT_ALGEBRA_BOOLEAN_OR_NUMBER,
    POKEMON_EVENT_ALGEBRA_TARGET_REDIRECT,
    POKEMON_EVENT_ALGEBRA_SELECTOR_REPLACEMENT,
    POKEMON_EVENT_ALGEBRA_STATE_NOTIFICATION,
    POKEMON_EVENT_ALGEBRA_VOID_NOTIFICATION,
    POKEMON_EVENT_ALGEBRA_MUTABLE_BOOST_TABLE,
} PokemonEventAlgebra;

typedef enum {
    POKEMON_EVENT_ORDER_ORDINARY = 1,
    POKEMON_EVENT_ORDER_LEFT_TO_RIGHT,
    POKEMON_EVENT_ORDER_REDIRECT,
} PokemonEventOrdering;

typedef struct {
    PokemonEventId id;
    const char *name;
    PokemonEventAlgebra algebra;
    PokemonEventOrdering ordering;
    uint16_t frozen_handler_count;
    uint8_t supported;
} PokemonEventSpec;

typedef enum {
    POKEMON_RELAY_UNDEFINED = 1,
    POKEMON_RELAY_NULL,
    /* Showdown's empty-string NOT_FAIL sentinel: a successful interception,
     * distinct from undefined success and null/false failure. */
    POKEMON_RELAY_NOT_FAIL,
    POKEMON_RELAY_BOOLEAN,
    POKEMON_RELAY_U32,
    /* JavaScript numeric relay retained for accuracy, whose stage arithmetic
     * can be fractional even though ordinary stat relays are integers. */
    POKEMON_RELAY_NUMBER,
    POKEMON_RELAY_TARGET,
    POKEMON_RELAY_SELECTOR,
    POKEMON_RELAY_BOOST_TABLE,
} PokemonRelayKind;

typedef struct {
    int8_t delta[POKEMON_STAT_COUNT];
    uint8_t present[POKEMON_STAT_COUNT];
} PokemonBoostTable;

typedef struct {
    PokemonRelayKind kind;
    union {
        uint8_t boolean;
        uint32_t u32;
        double number;
        struct { uint8_t side; uint8_t slot; } target;
        uint16_t selector;
        PokemonBoostTable boosts;
    } value;
} PokemonRelay;

typedef enum {
    POKEMON_OWNER_ABILITY = 1,
    POKEMON_OWNER_ITEM,
    POKEMON_OWNER_STATUS,
    POKEMON_OWNER_VOLATILE,
    POKEMON_OWNER_SIDE,
    POKEMON_OWNER_FIELD,
    POKEMON_OWNER_FORMAT,
    POKEMON_OWNER_MOVE,
    POKEMON_OWNER_SLOT,
} PokemonOwnerKind;

typedef struct {
    PokemonOwnerKind kind;
    uint8_t side;
    uint8_t slot;
    uint16_t effect_id;
    uint16_t state_generation;
} PokemonOwnerRef;

typedef enum {
    POKEMON_ENTITY_NONE = 0,
    POKEMON_ENTITY_POKEMON,
} PokemonEntityRefKind;

typedef struct {
    PokemonEntityRefKind kind;
    uint8_t side;
    uint8_t slot;
} PokemonEntityRef;

typedef struct {
    PokemonDamageMode mode;
    PokemonEntityRef source;
    PokemonEntityRef target;
    const PokemonMoveData *move;
    uint8_t critical;
} PokemonDamageRequest;

typedef struct {
    uint8_t critical;
    uint8_t damage_roll;
    uint16_t damage;
} PokemonCalculatedDamage;

typedef enum {
    POKEMON_SOURCE_EFFECT_NONE = 0,
    POKEMON_SOURCE_EFFECT_MOVE,
    POKEMON_SOURCE_EFFECT_CONDITION,
    POKEMON_SOURCE_EFFECT_ITEM,
    POKEMON_SOURCE_EFFECT_ABILITY,
} PokemonSourceEffectKind;

typedef struct {
    PokemonSourceEffectKind kind;
    uint16_t id;
} PokemonSourceEffectRef;

/* Showdown's `lastMoveUsed`: the latest invoked active move after type
 * resolution. This is deliberately distinct from `last_move_id`, which is
 * the latest selected outer action and drives choice-control semantics. */
typedef struct {
    uint8_t present;
    uint16_t move_id;
    uint8_t resolved_type;
} PokemonLastUsedMove;

typedef struct {
    PokemonEntityRef source;
    PokemonEntityRef target;
    PokemonSourceEffectRef source_effect;
    uint16_t amount;
} PokemonDirectDamageRequest;

typedef enum {
    POKEMON_MOVE_ENTRY_SELECTED = 1,
    POKEMON_MOVE_ENTRY_CALLED,
} PokemonMoveEntryKind;

typedef enum {
    POKEMON_TARGET_REQUEST_RESOLVE = 1,
    POKEMON_TARGET_REQUEST_EXPLICIT,
} PokemonTargetRequestKind;

typedef struct {
    PokemonTargetRequestKind kind;
    PokemonEntityRef explicit_target;
} PokemonTargetRequest;

typedef struct {
    PokemonMoveEntryKind entry;
    uint16_t move_id;
    PokemonEntityRef user;
    PokemonTargetRequest target_request;
    PokemonSourceEffectRef source_effect;
    uint8_t has_bounced;
    int8_t inherited_priority;
    uint8_t selected_slot;
    /* True only for the selected ordinary move invocation which owns the
     * base PP debit. Called moves and forced continuations cannot acquire it. */
    uint8_t owns_pp_deduction;
    /* True only for a queued selected action claimed by an in-progress
     * switch transaction. Generated move data interprets this context. */
    uint8_t target_switching;
    uint32_t invocation_id;
    uint32_t parent_invocation_id;
} PokemonMoveInvocation;

#define POKEMON_ACTIVE_SECONDARY_CAPACITY 4

typedef struct {
    PokemonMoveInvocation invocation;
    PokemonEntityRef resolved_target;
    PokemonMoveTarget target_mode;
    uint64_t flags;
    uint8_t type;
    PokemonCategory category;
    uint16_t base_power;
    /* Generated power variants may carry an associated protocol integer
     * without coupling the kernel to a particular move or message. */
    uint16_t message_value;
    uint8_t has_message_value;
    /* Invocation-local generated resolution selected by ModifyMove. Damage
     * is the zero/default variant for ordinary and constructed moves. */
    uint8_t weighted_outcome_kind;
    uint8_t heal_numerator;
    uint8_t heal_denominator;
    PokemonAccuracy accuracy;
    uint16_t effect_offset;
    uint8_t effect_count;
    uint8_t multihit_min;
    uint8_t multihit_max;
    /* Invocation-local party-hit snapshot. Entries are stable team slots in
     * the mutable party order captured by ModifyMove. */
    uint8_t party_hit_slots[POKEMON_TEAM_CAPACITY];
    uint8_t party_hit_count;
    uint8_t party_hit_cursor;
    uint8_t party_hit_plan_active;
    uint16_t profile_tag;
    uint8_t suppress_protocol_target;
    int8_t priority;
    PokemonEffectOp appended_secondaries[POKEMON_ACTIVE_SECONDARY_CAPACITY];
    uint8_t appended_secondary_count;
    /* Actual opposing HP damage returned by this invocation, accumulated
     * across connected hits. Substitute damage is deliberately excluded. */
    uint16_t actual_damage;
    uint8_t move_succeeded;
    enum {
        POKEMON_MOVE_ATTEMPT_PENDING = 0,
        POKEMON_MOVE_ATTEMPT_NO_TARGET,
        POKEMON_MOVE_ATTEMPT_ABORTED_BEFORE_HIT,
        POKEMON_MOVE_ATTEMPT_FAILED_AFTER_TARGET,
        POKEMON_MOVE_ATTEMPT_SUCCEEDED,
    } attempt_outcome;
    int result;
} PokemonActiveMoveFrame;

typedef struct {
    PokemonMoveInvocation invocation;
    PokemonEntityRef resolved_target;
    int result;
} PokemonMoveInvocationTrace;

typedef enum {
    POKEMON_HANDLER_OP_GUARD_STATUS_PRESENT = 1,
    /* Bit N corresponds to PokemonStatus N. NONE is deliberately excluded. */
    POKEMON_HANDLER_OP_GUARD_HOLDER_STATUS_MASK,
    /* Continue only when the holder's current major status is absent from
     * the generated mask. NONE always passes. */
    POKEMON_HANDLER_OP_GUARD_HOLDER_STATUS_NOT_MASK,
    /* A mismatch explicitly returns false instead of skipping the callback. */
    POKEMON_HANDLER_OP_REQUIRE_HOLDER_STATUS_MASK,
    POKEMON_HANDLER_OP_GUARD_MOVE_TYPE,
    /* Continue only for an active move with typed OHKO semantics. */
    POKEMON_HANDLER_OP_GUARD_MOVE_OHKO,
    POKEMON_HANDLER_OP_GUARD_MOVE_FLAG,
    POKEMON_HANDLER_OP_GUARD_DAMAGE_KIND,
    POKEMON_HANDLER_OP_GUARD_SOURCE_NOT_TARGET,
    /* Packed source-effect kind:id in bits 24..31:0..15.  A match makes the
     * remaining program inapplicable; generated conditions use this for
     * provenance exemptions such as a previously installed Yawn. */
    POKEMON_HANDLER_OP_GUARD_SOURCE_EFFECT_NOT,
    /* Continue only when an Immunity event's condition descriptor resolves to
     * a weather whose bit is present in the operand. Generation data owns the
     * identity mapping; generic control flow knows no weather condition IDs. */
    POKEMON_HANDLER_OP_GUARD_IMMUNITY_WEATHER_MASK,
    /* Attempt a holder heal through the shared TryHeal transaction. Argument
     * is packed numerator:denominator. Its explicit result determines whether
     * a later cancellation emits an immunity message. */
    POKEMON_HANDLER_OP_TRY_HEAL_HOLDER_MAX_HP_FRACTION,
    /* Add or restart the generated volatile kind on the discovered holder.
     * The shared transaction records APPLIED only for a completed add or a
     * dispatched Restart; duplicate/no-op and admission rejection are FAILED.
     * TryHit interceptors use that result to distinguish activation from the
     * protocol-visible immunity emitted by an already-active condition. */
    POKEMON_HANDLER_OP_TRY_ADD_OR_RESTART_HOLDER_VOLATILE,
    /* Item-owned Update programs use these as an explicit transaction:
     * observe a holder condition, consume the current item without berry
     * semantics, then end and remove that condition. */
    POKEMON_HANDLER_OP_GUARD_HOLDER_VOLATILE_KIND,
    /* Reject a Boolean-or-null event when the holder owns this volatile. */
    POKEMON_HANDLER_OP_REQUIRE_HOLDER_WITHOUT_VOLATILE_KIND,
    /* Continue only when the discovered holder owns the generated volatile
     * kind with counter at least the packed threshold (kind:threshold). */
    POKEMON_HANDLER_OP_GUARD_HOLDER_VOLATILE_COUNTER_AT_LEAST,
    POKEMON_HANDLER_OP_USE_HANDLER_OWNED_HELD_ITEM,
    POKEMON_HANDLER_OP_REMOVE_HOLDER_VOLATILE_KIND,
    /* Item-owned lifecycle programs use this predicate and mutation pair to
     * implement generated negative-stage restoration without item IDs. */
    POKEMON_HANDLER_OP_GUARD_HOLDER_HAS_NEGATIVE_BOOST,
    POKEMON_HANDLER_OP_CLEAR_HOLDER_NEGATIVE_BOOST_STAGES,
    POKEMON_HANDLER_OP_CHAIN_Q12,
    POKEMON_HANDLER_OP_RETURN_UNDEFINED,
    POKEMON_HANDLER_OP_RETURN_TRUE,
    POKEMON_HANDLER_OP_RETURN_FALSE,
    POKEMON_HANDLER_OP_RETURN_NULL,
    /* Mark a cancelled move announcement as targetless without changing the
     * callback's own null/false algebra. */
    POKEMON_HANDLER_OP_SUPPRESS_ACTIVE_MOVE_PROTOCOL_TARGET,
    POKEMON_HANDLER_OP_RETURN_NOT_FAIL,
    POKEMON_HANDLER_OP_NEST_EVENT,
    /* Dispatch an event independently to every active Pokémon in
     * generation-defined speed order. This models Showdown's eachEvent,
     * distinct from NEST_EVENT's direct single-owner callback. */
    POKEMON_HANDLER_OP_EACH_EVENT,
    /* Project the holder's current species/types through a generated
     * PokemonWeatherFormPolicy using effective (possibly suppressed) weather. */
    POKEMON_HANDLER_OP_PROJECT_HOLDER_WEATHER_FORM,
    POKEMON_HANDLER_OP_DROP_BOOST_STAT,
    POKEMON_HANDLER_OP_DROP_NEGATIVE_BOOST_STAT,
    POKEMON_HANDLER_OP_DROP_ALL_NEGATIVE_BOOSTS,
    /* Preserve the relay product field while replacing only a positive
     * stage with zero.  This differs from DROP_BOOST_STAT, which models
     * deleting a requested boost product before application. */
    POKEMON_HANDLER_OP_ZERO_POSITIVE_BOOST_STAT,
    /* Packed numerator:denominator in the high:low 16 bits. */
    POKEMON_HANDLER_OP_GUARD_HOLDER_HP_AT_MOST_FRACTION,
    POKEMON_HANDLER_OP_RETURN_SOURCE_HP_BELOW_TARGET,
    POKEMON_HANDLER_OP_GUARD_ACTIVE_MOVE_NOT_BOUNCED,
    POKEMON_HANDLER_OP_REMOVE_OWNER_VOLATILE,
    POKEMON_HANDLER_OP_REFLECT_ACTIVE_MOVE,
    /* Re-enter the current move as the discovered handler holder.  Unlike
     * reflection this resolves a fresh target and deliberately carries no
     * bounce guard; Gen 3 Snatch chains by rediscovering remaining owners. */
    POKEMON_HANDLER_OP_CALL_ACTIVE_MOVE_AS_OWNER,
    POKEMON_HANDLER_OP_DEDUCT_OWNER_MOVE_PP_FROM_TARGET_EVENT,
    /* Pack the move type in bits 24..31 and a Q12 modifier in bits 0..15.
     * Unlike GUARD_MOVE_TYPE, a mismatch is a no-op so one generated
     * callback can express Showdown's type alternatives compositionally. */
    POKEMON_HANDLER_OP_CHAIN_Q12_IF_MOVE_TYPE,
    POKEMON_HANDLER_OP_SET_OWNER_ENDING,
    POKEMON_HANDLER_OP_SET_WEATHER,
    POKEMON_HANDLER_OP_GUARD_EFFECTIVE_WEATHER,
    POKEMON_HANDLER_OP_HEAL_MAX_HP_FRACTION,
    POKEMON_HANDLER_OP_EAT_FIXED_HEAL_BERRY,
    POKEMON_HANDLER_OP_HEAL_FIXED_BERRY,
    POKEMON_HANDLER_OP_TRY_HEAL_BERRY_GATE,
    POKEMON_HANDLER_OP_EAT_PINCH_BOOST_BERRY,
    POKEMON_HANDLER_OP_BOOST_PINCH_BERRY,
    /* Uniformly choose one generated eligible holder stat which is below the
     * generation's maximum stage, then apply the item's generated delta
     * through the ordinary ChangeBoost/TryBoost transaction. */
    POKEMON_HANDLER_OP_BOOST_RANDOM_ELIGIBLE_HOLDER_STAT,
    POKEMON_HANDLER_OP_EAT_STATUS_CURE_BERRY,
    POKEMON_HANDLER_OP_CURE_STATUS_BERRY,
    POKEMON_HANDLER_OP_EAT_VOLATILE_CURE_BERRY,
    POKEMON_HANDLER_OP_CURE_VOLATILE_BERRY,
    POKEMON_HANDLER_OP_EAT_HELD_BERRY,
    /* Item-owned Update/Eat programs can observe and restore PP without
     * naming a move or item in the kernel. Selection is stable move-slot
     * order: exact-zero slots first, then merely depleted slots. */
    POKEMON_HANDLER_OP_GUARD_HOLDER_HAS_ZERO_MOVE_PP,
    POKEMON_HANDLER_OP_RESTORE_FIRST_HOLDER_MOVE_PP,
    /* Draw first, then deduct from the event target's first current slot
     * matching its canonical last selected move. Operand packs
     * draw-label:min:max-exclusive in successive bytes. A missing or empty
     * slot returns false after consuming the draw. */
    POKEMON_HANDLER_OP_DEDUCT_TARGET_LAST_MOVE_PP_UNIFORM,
    /* Generated ModifyMove programs can classify a move by a flattened tag
     * and append an ordinary volatile secondary to the active invocation.
     * The append operand packs chance:volatile-kind in bits 31..16:0..15. */
    POKEMON_HANDLER_OP_GUARD_MOVE_MODIFIER_TAG,
    /* Untagged moves pass. For a tagged major-status move, continue only
     * when the holder has no status, no Substitute, and not the generated
     * excluded effective type. Argument packs tag:type in high:low 16 bits. */
    POKEMON_HANDLER_OP_GUARD_TAGGED_STATUS_MOVE_TARGET_ELIGIBLE,
    POKEMON_HANDLER_OP_APPEND_ACTIVE_MOVE_VOLATILE_SECONDARY,
    /* Packed numerator:denominator. The basis is the current active move's
     * actual opposing HP damage, not calculated or Substitute damage. */
    POKEMON_HANDLER_OP_HEAL_HOLDER_FROM_MOVE_DAMAGE_FRACTION,
    POKEMON_HANDLER_OP_EAT_CONDITION_CURE_BERRY,
    POKEMON_HANDLER_OP_HEAL_FRACTION_BERRY,
    POKEMON_HANDLER_OP_CONFUSE_DISLIKED_FLAVOR,
    /* Scalar predicates and relay transforms are data, not owner-specific
     * callbacks.  Masks use generated generation-local type/species IDs. */
    POKEMON_HANDLER_OP_GUARD_MOVE_TYPE_MASK,
    POKEMON_HANDLER_OP_GUARD_HOLDER_SPECIES_PAIR,
    POKEMON_HANDLER_OP_MODIFY_RELAY_Q12,
    /* Add a generated integer delta to an integer relay.  Critical-stage
     * sources use this reusable operation; the kernel knows no move, item,
     * ability, or species identities. */
    POKEMON_HANDLER_OP_ADD_RELAY_U32,
    /* If the numeric damage relay would faint the discovered holder, replace
     * it with holder HP minus one.  The event boundary, not this operation,
     * owns source-effect discovery and numeric-zero short circuiting. */
    POKEMON_HANDLER_OP_CAP_DAMAGE_TO_HOLDER_HP_MINUS_ONE,
    /* Continue only when TryAddVolatile names this semantic volatile kind.
     * This keeps admission abilities declarative and generation-owned. */
    POKEMON_HANDLER_OP_GUARD_VOLATILE_KIND,
    POKEMON_HANDLER_OP_GUARD_VOLATILE_KIND_MASK,
    /* Emit the protocol-visible immunity owned by the current ability
     * handler. Only generated callbacks that explicitly do so use this op. */
    POKEMON_HANDLER_OP_EMIT_HANDLER_IMMUNITY,
    /* Source-bound condition programs use recorded volatile provenance. */
    POKEMON_HANDLER_OP_GUARD_OWNER_SOURCE_ACTIVE,
    POKEMON_HANDLER_OP_DISALLOW_TARGET_SWITCHES,
    /* Pack numerator in bits 16..23 and denominator in bits 0..15.  When the
     * recorded source is inactive, remove the owner condition instead. */
    POKEMON_HANDLER_OP_SOURCE_BOUND_MAX_HP_DAMAGE,
    POKEMON_HANDLER_OP_SET_ACTIVE_MOVE_TYPE,
    POKEMON_HANDLER_OP_SET_ACTIVE_MOVE_CATEGORY,
    /* Snapshot living, major-status-free party members in current party
     * order and use the snapshot as this invocation's fixed hit plan. */
    POKEMON_HANDLER_OP_SNAPSHOT_ACTIVE_MOVE_PARTY_HITS,
    /* Beat-Up-shaped stat relays remain generic operations over that plan and
     * immutable normalized set species. */
    POKEMON_HANDLER_OP_SET_RELAY_FROM_NEXT_PARTY_HIT_BASE_STAT,
    POKEMON_HANDLER_OP_SET_RELAY_FROM_EVENT_TARGET_BASE_SPECIES_STAT,
    POKEMON_HANDLER_OP_RETURN_NULL_IF_NO_ACTIVE_PARTY_HITS,
    /* Apply the current user's normalized personal move type and category.
     * Power remains staged at the ordinary base-power boundary. */
    POKEMON_HANDLER_OP_APPLY_ACTIVE_MOVE_PERSONAL_PROFILE,
    /* Sample a generated weighted distribution and replace the active move's
     * base power plus optional integer message payload. */
    POKEMON_HANDLER_OP_SAMPLE_ACTIVE_MOVE_OUTCOME_WEIGHTED,
    /* Reject a move-owned TryHit before primary effects when the target has
     * no ordinary last move. The generation plugin owns fallback identity. */
    POKEMON_HANDLER_OP_REQUIRE_TARGET_LAST_NONFALLBACK,
    /* Move-owned TryHit rejection shared by delayed-status producers such as
     * Yawn. This is a status predicate, not a move-identity branch. */
    POKEMON_HANDLER_OP_REQUIRE_TARGET_STATUS_NONE,
    /* Condition-owned expiry programs apply a major status with the
     * installed condition as source effect and its recorded source entity. */
    POKEMON_HANDLER_OP_SET_STATUS_FROM_OWNER_SOURCE,
    /* Side-owned condition lifecycle programs mutate their own compact
     * payload.  The owner identity, rather than a condition ID, selects the
     * state so these operations remain generation-neutral. */
    POKEMON_HANDLER_OP_SET_OWNER_SIDE_COUNTER,
    POKEMON_HANDLER_OP_INCREMENT_OWNER_SIDE_COUNTER_UP_TO,
    /* Entry-hazard programs use the generation's type chart and declarative
     * ability ground-immunity flag. */
    POKEMON_HANDLER_OP_GUARD_TARGET_GROUNDED,
    /* Trapping predicates are owner/target relations. A future multi-active
     * format can replace adjacency policy without changing ability IDs. */
    POKEMON_HANDLER_OP_GUARD_OWNER_ADJACENT_TO_TARGET,
    POKEMON_HANDLER_OP_GUARD_TARGET_CURRENT_TYPE,
    /* Pack denominator,numerator[1],numerator[2],numerator[3] in bytes from
     * most to least significant.  The owner side condition counter selects
     * the numerator. */
    POKEMON_HANDLER_OP_DAMAGE_TARGET_MAX_HP_BY_OWNER_COUNTER_FRACTIONS,
    POKEMON_HANDLER_OP_GUARD_MOVE_CATEGORY,
    POKEMON_HANDLER_OP_GUARD_HOLDER_SIDE_CONTAINS_TARGET,
    POKEMON_HANDLER_OP_GUARD_MOVE_HIT_NOT_CRITICAL,
    /* Remove a generated side-condition descriptor from a side selected by
     * the handler program.  The packed operand is selector:descriptor in
     * bits 24..31:0..15; generation data owns both facts. */
    POKEMON_HANDLER_OP_REMOVE_SIDE_CONDITION,
    /* Clear the major status of the discovered handler holder through the
     * central status transaction. */
    POKEMON_HANDLER_OP_CLEAR_MAJOR_STATUS,
    /* Continue only when the event source is on the opposing side from the
     * discovered holder. */
    POKEMON_HANDLER_OP_GUARD_SOURCE_OPPOSES_HOLDER,
    /* Faint an event source without inventing provenance, or set every
     * matching current slot for a living source's last move to zero PP. */
    POKEMON_HANDLER_OP_FAINT_EVENT_SOURCE,
    POKEMON_HANDLER_OP_ZERO_LIVING_EVENT_SOURCE_LAST_MOVE_PP,
    /* Match a generated move semantic, not a generation-local move ID. */
    POKEMON_HANDLER_OP_GUARD_MOVE_SELF_FAINT_TIMING,
    /* Packed draw-label:numerator:denominator in bits 24..31:16..23:0..15. */
    POKEMON_HANDLER_OP_GUARD_RANDOM_CHANCE,
    /* Apply the generated major status to the event source, with the
     * discovered handler holder as provenance. */
    POKEMON_HANDLER_OP_SET_EVENT_SOURCE_STATUS_FROM_HOLDER,
    /* Uniformly select one of three generated major statuses. The packed
     * operand is draw-label:status0:status1:status2 in successive bytes. */
    POKEMON_HANDLER_OP_SET_EVENT_SOURCE_STATUS_FROM_HOLDER_UNIFORM_3,
    /* Install a generated volatile on the event source while retaining the
     * discovered holder as provenance. Contact-response abilities use this
     * after their own activation draw; volatile Start owns admission. */
    POKEMON_HANDLER_OP_TRY_ADD_EVENT_SOURCE_VOLATILE_FROM_HOLDER,
    /* Start-time relational admission for source-bound conditions such as
     * attraction. Unspecified/genderless and equal genders are rejected. */
    POKEMON_HANDLER_OP_REQUIRE_SOURCE_OPPOSITE_GENDER_TO_HOLDER,
    /* Remove a source-bound owner volatile when its recorded source no longer
     * occupies the active slot. Fainting alone does not make Showdown's
     * `isActive` false; replacement/switching does. */
    POKEMON_HANDLER_OP_REMOVE_OWNER_VOLATILE_IF_SOURCE_INACTIVE,
    /* Continue only when the status carried by the current status event is
     * one of the generated status bits. */
    POKEMON_HANDLER_OP_GUARD_EVENT_STATUS_MASK,
    /* Reapply the event status to its source. The low bytes optionally encode
     * a generated from:to rewrite such as toxic to ordinary poison. */
    POKEMON_HANDLER_OP_REFLECT_EVENT_STATUS_TO_SOURCE,
    /* Damage the event source by floor(base max HP * numerator / denominator),
     * with Showdown's minimum-one damage rule. The packed operand is
     * numerator:denominator in the high:low 16 bits. */
    POKEMON_HANDLER_OP_DAMAGE_EVENT_SOURCE_BASE_MAX_HP_FRACTION,
    /* Continue only when the active move cannot reach the one generated
     * semi-invulnerable state encoded by the operand. */
    POKEMON_HANDLER_OP_GUARD_MOVE_LACKS_SEMI_INVULNERABLE_BYPASS,
    /* Continue only when the active move receives doubled damage against the
     * generated semi-invulnerable state encoded by the operand. */
    POKEMON_HANDLER_OP_GUARD_MOVE_HAS_SEMI_INVULNERABLE_DOUBLE,
    /* Atomically replace the event source's complete stage product with the
     * event target's stage product. This intentionally bypasses ordinary
     * ChangeBoost/TryBoost processing and owns no PRNG. */
    POKEMON_HANDLER_OP_COPY_EVENT_TARGET_BOOST_STAGES_TO_SOURCE,
    /* Clear the complete seven-stage product of every living active. */
    POKEMON_HANDLER_OP_CLEAR_LIVING_ACTIVE_BOOST_STAGES,
    /* Clear matching major statuses from every living active in canonical
     * battlefield order. Operand bits are indexed by PokemonStatus. */
    POKEMON_HANDLER_OP_CLEAR_LIVING_ACTIVE_STATUS_MASK,
    /* Initialize installed sleep from resolved generation Start data.
     * Operand: draw-label:min:max-exclusive:reserved. */
    POKEMON_HANDLER_OP_INITIALIZE_OWNER_SLEEP_UNIFORM,
    /* Conditional callback returns used by generated admission programs. */
    POKEMON_HANDLER_OP_RETURN_FALSE_IF_HOLDER_STATUS_MASK,
    /* Return false when the source has attempted more than the generated
     * number of selected move actions since entering the field. */
    POKEMON_HANDLER_OP_RETURN_FALSE_IF_HOLDER_MOVE_ACTIONS_ABOVE,
    POKEMON_HANDLER_OP_RETURN_NULL_IF_HOLDER_HP_FULL,
    POKEMON_HANDLER_OP_RETURN_NULL_IF_HOLDER_ABILITY_BLOCKS_STATUS,
    /* Direct setStatus-style replacement on the discovered holder. A failed
     * semantic transaction returns false from the callback. */
    POKEMON_HANDLER_OP_REPLACE_HOLDER_MAJOR_STATUS,
    /* Operand: typed counter selector in bits 16..23, literal in bits 0..15. */
    POKEMON_HANDLER_OP_SET_HOLDER_STATUS_COUNTER,
    /* Status-owner policies over the typed sleep payload. The advance
     * operand is the generated ability ID which receives an extra decrement. */
    POKEMON_HANDLER_OP_ADVANCE_OWNER_SLEEP,
    POKEMON_HANDLER_OP_RESTORE_OWNER_SLEEP_SKIPPED,
    /* Residual callbacks can require a living holder independently of their
     * other predicates while the faint queue is being drained. */
    POKEMON_HANDLER_OP_GUARD_HOLDER_ALIVE,
    /* Require a holder that was active before the current turn. */
    POKEMON_HANDLER_OP_GUARD_HOLDER_ACTIVE_TURNS,
    /* Continue only when any non-fainted active has the generated effective
     * ability ID. Relational abilities such as Plus/Minus use this without
     * assuming that the matching holder is an ally. */
    POKEMON_HANDLER_OP_GUARD_ANY_LIVING_ACTIVE_ABILITY,
    /* Apply one generated stat delta through ChangeBoost/TryBoost.
     * Operand: stat in bits 8..15, signed nonzero delta in bits 0..7. */
    POKEMON_HANDLER_OP_BOOST_HOLDER_STAT,
    /* Apply an ordinary directed boost transaction to every living opposing
     * active which lacks the generated excluded volatile. Operand packs
     * excluded volatile:stat:signed delta in bits 31..16:15..8:7..0. */
    POKEMON_HANDLER_OP_BOOST_OPPOSING_ACTIVES_EXCEPT_VOLATILE,
    /* Damage the discovered holder by floor(base max HP * numerator /
     * denominator), minimum one. Operand packs numerator:denominator. */
    POKEMON_HANDLER_OP_DAMAGE_HOLDER_BASE_MAX_HP_FRACTION,
    /* Replace the holder's ability from a typed target selector. The
     * transaction owns old-End, installation identity, and the generation's
     * copied-Start policy. */
    POKEMON_HANDLER_OP_REPLACE_HOLDER_ABILITY_FROM_TARGET,
    /* Replace the holder's mutable effective-type product with the active
     * move's resolved type. Species/base types remain immutable generated
     * data and switch cleanup restores them. */
    POKEMON_HANDLER_OP_SET_HOLDER_EFFECTIVE_TYPE_FROM_MOVE,
    /* Replace the discovered holder's effective type with one generated
     * literal type, returning false when it already has that type. */
    POKEMON_HANDLER_OP_SET_HOLDER_EFFECTIVE_TYPE_LITERAL,
    /* Sample the type of one current mutable move slot, preserving duplicate
     * slot weighting. Operand packs draw-label:excluded-catalog-id. */
    POKEMON_HANDLER_OP_SAMPLE_HOLDER_MOVE_SLOT_TYPE,
    /* Clear major status from every living member of the move user's team in
     * canonical slot order. Operand bits 0..15 name an optional excluded
     * generated ability; bit 16 records silent per-member cure effects; bit
     * 17 emits the callback's active-holder immunity event for an exclusion. */
    POKEMON_HANDLER_OP_CLEAR_USER_TEAM_MAJOR_STATUS,
    /* Compare the immutable catalog move type rather than the active move
     * frame's possibly transformed type. */
    POKEMON_HANDLER_OP_GUARD_BASE_MOVE_TYPE,
    POKEMON_HANDLER_OP_GUARD_MOVE_DEFROST,
    /* Packed draw-label:numerator:denominator:reserved.  A successful draw
     * clears the status owner.  A failed draw cancels the boolean event unless
     * the active move has the typed defrost semantic. */
    POKEMON_HANDLER_OP_RANDOM_CURE_OR_REQUIRE_DEFROST,
    /* Boolean admission for copying the event target's ability to the event
     * source. Operand packs forbidden target flags in bits 0..15 and
     * forbidden source flags in bits 16..31; equal abilities also reject. */
    POKEMON_HANDLER_OP_REQUIRE_ABILITY_TRANSFER_ALLOWED,
    /* Replace the event source's ability with the event target's ability.
     * The generic transaction owns old-End, installation identity, and the
     * generation policy for copied-Start. */
    POKEMON_HANDLER_OP_REPLACE_SOURCE_ABILITY_FROM_EVENT_TARGET,
    /* Atomically exchange the event source and target's current abilities.
     * Admission for both installations precedes lifecycle mutation. */
    POKEMON_HANDLER_OP_SWAP_SOURCE_TARGET_ABILITIES,
	/* Install a generated source-bound volatile on the event target from a
	 * move-owned Hit callback. The boolean relay is the addVolatile result. */
	POKEMON_HANDLER_OP_TRY_ADD_EVENT_TARGET_VOLATILE_FROM_SOURCE,
	/* Match a typed damage cause without conflating it with the independent
	 * preventability policy. Endure uses this on the ordinary Move relay. */
	POKEMON_HANDLER_OP_GUARD_DAMAGE_KIND_ANY,
    /* Require an owner volatile whose recorded source is the current event
     * target. This models target-bound provenance without linked state. */
    POKEMON_HANDLER_OP_GUARD_OWNER_SOURCE_IS_EVENT_TARGET,
    /* A volatile installed by an ability remains applicable only while the
     * holder still owns that same ability identity. */
    POKEMON_HANDLER_OP_GUARD_OWNER_SOURCE_ABILITY_ACTIVE,
    /* Return numeric zero. Unlike boolean false this is a successful relay
     * value and stops later handlers without cancelling the event. */
    POKEMON_HANDLER_OP_RETURN_NUMBER_ZERO,
    /* Condition-owned residual transfer: damage the holder by a max-HP
     * fraction, relay actual damage through TryHeal to the current occupant
     * of the recorded source battlefield position, then drain faint work. */
    POKEMON_HANDLER_OP_TRANSFER_HOLDER_MAX_HP_FRACTION_TO_SOURCE_POSITION,
    /* Source-scoped numeric relay inversion. Apply the incoming amount as
     * immediate indirect damage to the event source; a following generated
     * RETURN_NUMBER_ZERO suppresses the original heal. */
    POKEMON_HANDLER_OP_DAMAGE_EVENT_TARGET_BY_RELAY_IMMEDIATE,
	/* Active-move predicates for generated damage-admission handlers.
	 * Category masks use bit PokemonCategory; effectiveness uses the kernel's
	 * neutral=4 type-product scale and rejects with null at or below operand. */
	POKEMON_HANDLER_OP_GUARD_MOVE_CATEGORY_MASK,
	POKEMON_HANDLER_OP_REQUIRE_HOLDER_TYPE_EFFECTIVENESS_ABOVE,
    /* Prepared-retaliation condition operations. These consume generated
     * class masks and owner payloads; no move identity enters the kernel. */
    POKEMON_HANDLER_OP_INITIALIZE_OWNER_RETALIATION,
    POKEMON_HANDLER_OP_GUARD_DAMAGE_RETALIATION_CLASS,
    POKEMON_HANDLER_OP_CAPTURE_OWNER_RETALIATION_X2,
    POKEMON_HANDLER_OP_REQUIRE_OWNER_RETALIATION_CAPTURE,
    /* Cumulative move-damage storage and delayed constructed-hit release.
     * The generated operand identifies a template, never a move name. */
    POKEMON_HANDLER_OP_INITIALIZE_OWNER_STORED_DAMAGE,
    POKEMON_HANDLER_OP_GUARD_DAMAGE_FROM_MOVE_SOURCE,
    POKEMON_HANDLER_OP_ACCUMULATE_OWNER_STORED_DAMAGE,
    POKEMON_HANDLER_OP_RELEASE_OWNER_STORED_DAMAGE_HIT,
    /* Return the move identity which installed this condition. */
    POKEMON_HANDLER_OP_RETURN_OWNER_SOURCE_MOVE_SELECTOR,
    /* Remove the exact queued selected move named by this condition's stored
     * source and source-effect, then execute it after the selected-action
     * BeforeMove boundary. The switch transaction remains the caller. */
    POKEMON_HANDLER_OP_CLAIM_QUEUED_SELECTED_MOVE,
    /* Uniformly select a generated catalog move and re-enter the ordinary
     * called-move path. The operand is a resolved immutable pool identity. */
    POKEMON_HANDLER_OP_CALL_MOVE_FROM_POOL,
    /* Re-enter the ordinary called-move path with one generated executable
     * move identity. This is the fixed-call counterpart to a call pool. */
    POKEMON_HANDLER_OP_CALL_FIXED_MOVE,
    /* Uniformly select an eligible move from the user's current fixed-capacity
     * slots and re-enter the called-move path. The operand is an eligibility
     * bit, not a caller identity. */
    POKEMON_HANDLER_OP_CALL_MOVE_FROM_USER_SLOTS,
    /* Uniformly select an eligible move slot owned by another member of the
     * user's current mutable party order. Duplicate slots remain duplicate
     * candidates; the operand is a generated eligibility bit. */
    POKEMON_HANDLER_OP_CALL_MOVE_FROM_PARTY_SLOTS,
    /* Replace the move user's current slot containing the handler owner with
     * the target's last selected move. Operand bits 0..7 select a generated
     * eligibility family, bit 8 persists the replacement into the base slot,
     * and bits 16..23 cap initial current PP (zero means raw descriptor PP). */
    POKEMON_HANDLER_OP_COPY_TARGET_LAST_MOVE_TO_SOURCE_SLOT,
    /* Queue a faint for the living Pokémon holder of a condition-owned End
     * callback. Faint draining remains owned by the surrounding event phase. */
    POKEMON_HANDLER_OP_FAINT_HOLDER,
    /* Field-move callback: visit each living active in canonical battlefield
     * order, run its Invulnerability and TryHit admission boundaries, and add
     * the generated volatile only when absent. */
    POKEMON_HANDLER_OP_APPLY_VOLATILE_TO_ADMITTED_ACTIVES,
    /* Ensure a generated volatile exists on the discovered holder without
     * restarting an existing instance. Move-owned BasePower callbacks use
     * this before reading condition state. */
    POKEMON_HANDLER_OP_ENSURE_HOLDER_VOLATILE,
    /* Initialize and advance the generic counter carried by a condition
     * owner. ADVANCE packs multiplier:cap in the high:low 16 bits and also
     * refreshes the descriptor's fixed lifecycle duration. */
    POKEMON_HANDLER_OP_SET_OWNER_VOLATILE_COUNTER,
    POKEMON_HANDLER_OP_ADVANCE_OWNER_VOLATILE_COUNTER,
    /* Add one to a condition-owned counter up to the generated cap without
     * implying any duration refresh.  This is distinct from multiplicative
     * ramp state such as Fury Cutter. */
    POKEMON_HANDLER_OP_INCREMENT_OWNER_VOLATILE_COUNTER_UP_TO,
    /* Multiply a U32 relay by the selected holder volatile's counter. */
    POKEMON_HANDLER_OP_MULTIPLY_RELAY_BY_HOLDER_VOLATILE_COUNTER,
    /* Multiply a U32 relay directly by the literal operand. This models a
     * callback returning a new relay value, not event-chain modification. */
    POKEMON_HANDLER_OP_MULTIPLY_RELAY_U32,
    /* Continue a BasePower program only when the move user took positive
     * numeric damage from the current resolved target during this turn. */
    POKEMON_HANDLER_OP_GUARD_HOLDER_ATTACKED_BY_TARGET_THIS_TURN,
    /* Move-owned predicates over generic condition state.  Operands pack
     * volatile-kind:counter in the high:low 16 bits. */
    POKEMON_HANDLER_OP_RETURN_FALSE_IF_HOLDER_VOLATILE_COUNTER_AT_LEAST,
    POKEMON_HANDLER_OP_RETURN_FALSE_UNLESS_HOLDER_VOLATILE,
    /* Operand is a generated PokemonVolatileKind bit mask. */
    POKEMON_HANDLER_OP_RETURN_FALSE_IF_HOLDER_VOLATILE_MASK,
    /* Replace a U32 relay with holder-counter * scale.  Operand packing is
     * volatile-kind:scale in the high:low 16 bits. */
    POKEMON_HANDLER_OP_SET_RELAY_FROM_HOLDER_VOLATILE_COUNTER_TIMES,
    /* Heal the holder using an immutable counter-indexed Q12 policy. */
    POKEMON_HANDLER_OP_HEAL_HOLDER_BY_COUNTER_POLICY,
    POKEMON_HANDLER_OP_TRY_ADD_OR_RESTART_SOURCE_VOLATILE,
	/* Generated locked-ramp policy operations. The operand is an immutable
	 * resolved policy identity; no move or condition identity is encoded. */
	POKEMON_HANDLER_OP_INSTALL_LOCKED_RAMP_IF_TARGET_AWAKE,
	POKEMON_HANDLER_OP_APPLY_LOCKED_RAMP_BASE_POWER,
	POKEMON_HANDLER_OP_REMOVE_OWNER_IF_LAST_MOVE_FALLBACK,
    /* Sample a defensive type response to the event target's most recently
     * invoked resolved move and replace the event source's effective types.
     * The operand selects an immutable generation-owned response policy. */
    POKEMON_HANDLER_OP_SAMPLE_SOURCE_TYPE_RESPONSE,
    /* Foe-scoped move-sharing operations. The discovered condition holder is
     * the authority; operands remain identity-free so later generations can
     * bind the same request/action semantics from generated data. */
    POKEMON_HANDLER_OP_REQUIRE_ACTIVE_FOE_SHARES_HOLDER_MOVE,
    POKEMON_HANDLER_OP_APPEND_HOLDER_MOVES_TO_EVENT_RESTRICTIONS,
    POKEMON_HANDLER_OP_REJECT_EVENT_MOVE_SHARED_WITH_HOLDER,
    /* Select an immutable invocation-local target/effect profile by the
     * move user's current effective types. Operand is a resolved selector ID. */
    POKEMON_HANDLER_OP_SELECT_ACTIVE_MOVE_PROFILE_BY_USER_TYPE,
    /* Invocation-local predicates compose after profile selection. These
     * operate on the active frame and resolved event target, never move IDs. */
    POKEMON_HANDLER_OP_GUARD_ACTIVE_MOVE_PROFILE_TAG,
    POKEMON_HANDLER_OP_CLEAR_ACTIVE_MOVE_EFFECTS_IF_TARGET_VOLATILE,
    POKEMON_HANDLER_OP_RETURN_FALSE_IF_EVENT_TARGET_VOLATILE,
    /* Pokémon-owned Boolean state survives ability replacement. Generated
     * handlers select a typed key; SwitchIn overwrites, BeforeMove reads, and
     * Residual toggles it without fabricating a condition owner. */
    POKEMON_HANDLER_OP_SET_HOLDER_BOOLEAN_FROM_BATTLE_STARTED,
    POKEMON_HANDLER_OP_RETURN_FALSE_IF_HOLDER_BOOLEAN,
    POKEMON_HANDLER_OP_TOGGLE_HOLDER_BOOLEAN,
    /* One atomic bilateral assignment: snapshot both current HP values,
     * average once, then clamp independently to each participant's maximum. */
    POKEMON_HANDLER_OP_SET_SOURCE_TARGET_HP_TO_FLOOR_AVERAGE,
    /* Replace the move user's mutable battle profile with the event target's
     * current profile. The operand is a validated generation policy ID. */
    POKEMON_HANDLER_OP_COPY_EVENT_TARGET_BATTLE_PROFILE,
    /* Move-owned callbacks may inspect and mutate the resolved invocation
     * target even when the event relay itself is source-scoped. Status masks
     * use the ordinary PokemonStatus bit representation. */
    POKEMON_HANDLER_OP_GUARD_ACTIVE_MOVE_TARGET_STATUS_MASK,
    POKEMON_HANDLER_OP_CLEAR_ACTIVE_MOVE_TARGET_MAJOR_STATUS,
    /* One atomic self-cost/stat transaction. Operand packs stat:numerator:
     * denominator in bits 16..23:8..15:0..7. Admission requires HP strictly
     * above the cost, a non-degenerate maximum HP, and room below the
     * generation's maximum stage; success pays direct damage then requests a
     * boost large enough to reach that maximum. */
    POKEMON_HANDLER_OP_PAY_MAX_HP_FRACTION_AND_MAXIMIZE_HOLDER_STAT,
} PokemonHandlerOpcode;

typedef enum {
    POKEMON_BOOLEAN_STATE_NONE = 0,
    POKEMON_BOOLEAN_STATE_ALTERNATING_ACTION_PHASE,
    POKEMON_BOOLEAN_STATE_COUNT,
} PokemonBooleanStateKey;

typedef enum {
    POKEMON_MOVE_CALL_ELIGIBLE_SLEEP_TALK = UINT8_C(1) << 0,
    POKEMON_MOVE_CALL_ELIGIBLE_ASSIST = UINT8_C(1) << 1,
} PokemonMoveCallEligibility;

typedef enum {
    POKEMON_MOVE_COPY_ELIGIBLE_MIMIC = UINT8_C(1) << 0,
    POKEMON_MOVE_COPY_ELIGIBLE_SKETCH = UINT8_C(1) << 1,
} PokemonMoveCopyEligibility;

#define POKEMON_MOVE_COPY_PERSIST_BASE (UINT32_C(1) << 8)
#define POKEMON_MOVE_COPY_INITIAL_PP_CAP(value) ((uint32_t)(value) << 16)

typedef enum {
    POKEMON_HANDLER_TARGET_RANDOM_ACTIVE_FOE = 1,
} PokemonHandlerTargetSelector;

typedef enum {
    POKEMON_STATUS_COUNTER_SLEEP_TIME = 1,
    POKEMON_STATUS_COUNTER_TOXIC_STAGE,
} PokemonStatusCounterSelector;

typedef enum {
    POKEMON_SIDE_SELECTOR_SOURCE = 1,
    POKEMON_SIDE_SELECTOR_SOURCE_OPPOSING,
    POKEMON_SIDE_SELECTOR_EVENT_TARGET,
} PokemonSideSelector;

typedef struct {
    PokemonHandlerOpcode opcode;
    uint32_t argument;
} PokemonHandlerOp;

typedef uint16_t PokemonHandlerId;

typedef enum {
    POKEMON_EXCEPTION_NONE = 0,
    POKEMON_EXCEPTION_SUBSTITUTE_TRY_PRIMARY_HIT,
    POKEMON_EXCEPTION_CONFUSION_START,
    POKEMON_EXCEPTION_CONFUSION_BEFORE_MOVE,
    POKEMON_EXCEPTION_CONFUSION_END,
    POKEMON_EXCEPTION_OWN_TEMPO_TRY_ADD,
    POKEMON_EXCEPTION_OWN_TEMPO_HIT,
    POKEMON_EXCEPTION_OWN_TEMPO_UPDATE,
    POKEMON_EXCEPTION_SHIELD_DUST_MODIFY_SECONDARIES,
    POKEMON_EXCEPTION_LOCKED_MOVE_START,
    POKEMON_EXCEPTION_LOCKED_MOVE_RESTART,
    POKEMON_EXCEPTION_LOCKED_MOVE_RESIDUAL,
    POKEMON_EXCEPTION_LOCKED_MOVE_END,
    POKEMON_EXCEPTION_LOCKED_MOVE_SELECTOR,
    POKEMON_EXCEPTION_WEATHER_BALL_MODIFY_TYPE,
    POKEMON_EXCEPTION_WEATHER_BALL_MODIFY_MOVE,
    POKEMON_EXCEPTION_THUNDER_MODIFY_MOVE,
    POKEMON_EXCEPTION_TWO_TURN_LOCK_MOVE,
    POKEMON_EXCEPTION_TWO_TURN_MOVE_ABORTED,
    POKEMON_EXCEPTION_TWO_TURN_END,
    POKEMON_EXCEPTION_SOLAR_BEAM_TRY_MOVE,
    POKEMON_EXCEPTION_SOLAR_BEAM_BASE_POWER,
    POKEMON_EXCEPTION_CHOICE_CONTROL,
    POKEMON_EXCEPTION_STATUS_CLAUSE,
    POKEMON_EXCEPTION_STATUS_IMMUNITY,
} PokemonExceptionalHandler;

/* Semantic family name retained at the same wire value while generated data
 * migrates away from the historical Solar Beam spelling. */
#define POKEMON_EXCEPTION_TWO_TURN_TRY_MOVE \
    POKEMON_EXCEPTION_SOLAR_BEAM_TRY_MOVE

typedef enum {
    POKEMON_HANDLER_SCOPE_TARGET = 1,
    POKEMON_HANDLER_SCOPE_SOURCE,
    POKEMON_HANDLER_SCOPE_FOE,
    POKEMON_HANDLER_SCOPE_ANY,
    POKEMON_HANDLER_SCOPE_SIDE,
    POKEMON_HANDLER_SCOPE_FIELD,
} PokemonHandlerScope;

typedef enum {
    POKEMON_HANDLER_ROUTE_OWNER = 1,
    POKEMON_HANDLER_ROUTE_SOURCE_EFFECT,
    POKEMON_HANDLER_ROUTE_MOVE_SELF,
    POKEMON_HANDLER_ROUTE_MOVE_SECONDARY,
} PokemonHandlerRoute;

typedef enum {
    POKEMON_HANDLER_SOURCE_ABILITY = 1,
    POKEMON_HANDLER_SOURCE_ITEM,
    POKEMON_HANDLER_SOURCE_CONDITION,
    POKEMON_HANDLER_SOURCE_MOVE,
} PokemonHandlerSourceKind;

typedef struct {
    PokemonHandlerEvent event;
    PokemonHandlerId id;
    PokemonHandlerSourceKind source_kind;
    uint16_t source_id;
    int16_t order;
    int8_t priority;
    int8_t sub_order;
    uint8_t argument_type;
    uint32_t modifier_q12;
    uint8_t requires_status;
    uint8_t filters_move_type;
    uint16_t program_offset;
    uint8_t program_count;
    uint16_t exceptional_handler_id;
    PokemonHandlerScope scope;
    PokemonHandlerRoute route;
    uint16_t hook_ordinal;
    const char *raw_hook;
    /* Zero means always present. Nonzero move-self callbacks exist only for
     * the selected invocation profile carrying this generated tag. */
    uint16_t required_move_profile_tag;
} PokemonHandlerDescriptor;

typedef struct {
    PokemonOwnerKind owner_kind;
    uint16_t owner_id;
    PokemonEventId event;
    PokemonHandlerScope scope;
    PokemonHandlerRoute route;
    uint16_t binding_offset;
    uint16_t binding_count;
} PokemonOwnerBindingIndex;

typedef struct {
    uint16_t id;
    uint16_t handler_offset;
    uint8_t handler_count;
    uint8_t grants_ground_immunity;
    uint8_t ground_immunity_type;
    uint8_t ignores_burn_attack_penalty;
    uint8_t pressure_pp;
    uint8_t suppresses_weather;
    /* Generated semantic capability; generic item mutation never knows the
     * owning ability's catalog identity. */
    uint8_t semantic_flags;
} PokemonAbilityData;

enum {
    POKEMON_ABILITY_SEMANTIC_BLOCKS_EXTERNAL_ITEM_TAKE = UINT8_C(1) << 0,
    POKEMON_ABILITY_SEMANTIC_CANT_SUPPRESS = UINT8_C(1) << 1,
    POKEMON_ABILITY_SEMANTIC_FAIL_ROLE_PLAY = UINT8_C(1) << 2,
    POKEMON_ABILITY_SEMANTIC_FAIL_SKILL_SWAP = UINT8_C(1) << 3,
    /* Initial-set capability consumed only by terminal policy. */
    POKEMON_ABILITY_SEMANTIC_CYCLES_RESTORATIVE_ITEM = UINT8_C(1) << 4,
};

typedef struct {
    uint16_t ability_id;
    uint8_t numerator;
    uint8_t denominator;
} PokemonSecondaryChancePolicy;

typedef struct {
    uint16_t id;
    uint16_t handler_offset;
    uint8_t handler_count;
    uint8_t berry_threshold_denominator;
    uint8_t fixed_heal;
    uint8_t try_heal_fixed;
    uint8_t try_heal_denominator;
    uint8_t boost_stat;
    int8_t boost_delta;
    uint16_t cure_status_mask;
    uint16_t cure_volatile_kind;
    uint8_t heal_denominator;
    uint8_t disliked_flavor;
    uint8_t flags;
    /* Optional volatile installed by this item's ItemEat handler. */
    uint16_t add_volatile_kind;
    /* Bit PokemonStat identifies a stat eligible for uniform selection. */
    uint8_t eligible_boost_mask;
} PokemonItemData;

enum {
    POKEMON_ITEM_FLAG_RESTRICT_EXTERNAL_TAKE = UINT8_C(1) << 0,
    POKEMON_ITEM_FLAG_SHARED_TURN_SPEED_SENTINEL = UINT8_C(1) << 1,
    POKEMON_ITEM_FLAG_RESTORATIVE = UINT8_C(1) << 2,
};

typedef struct {
    uint16_t catalog_id;
    uint16_t source_num;
    uint16_t executable_id;
    const char *id;
    const char *name;
    const char *tier;
    uint8_t types[2];
    uint8_t type_count;
    uint8_t base_stats[6];
    uint16_t max_hp_override;
    uint16_t weight_hg;
} PokemonSpeciesIdentity;

typedef PokemonMoveTarget PokemonCatalogMoveTarget;

typedef struct {
    uint16_t catalog_id;
    uint16_t source_num;
    uint16_t executable_id;
    const char *id;
    const char *name;
    uint8_t type;
    PokemonCategory category;
    uint16_t base_power;
    PokemonAccuracy accuracy;
    int8_t priority;
    uint8_t pp;
    PokemonCatalogMoveTarget target;
    uint64_t flags;
} PokemonMoveIdentity;

typedef struct {
    uint16_t catalog_id;
    uint16_t source_num;
    uint16_t executable_id;
    const char *id;
    const char *name;
} PokemonNamedIdentity;

typedef enum {
    POKEMON_CONDITION_DOMAIN_STATUS = 1,
    POKEMON_CONDITION_DOMAIN_VOLATILE,
    POKEMON_CONDITION_DOMAIN_SIDE,
    POKEMON_CONDITION_DOMAIN_WEATHER,
    POKEMON_CONDITION_DOMAIN_PSEUDO_WEATHER,
    POKEMON_CONDITION_DOMAIN_SLOT,
} PokemonConditionDomain;

/* Conditions have one authoritative, generation-local catalog identity.
 * semantic_kind is the compact kernel representation when that condition is
 * executable today; zero means catalogued but not yet executable. */
typedef struct {
    uint16_t catalog_id;
    PokemonConditionDomain domain;
    uint16_t semantic_kind;
    const char *id;
    const char *name;
} PokemonConditionIdentity;

typedef enum {
    POKEMON_FORMAT_OPERAND_SPECIES = 1,
    POKEMON_FORMAT_OPERAND_MOVE,
    POKEMON_FORMAT_OPERAND_ABILITY,
    POKEMON_FORMAT_OPERAND_ITEM,
    POKEMON_FORMAT_OPERAND_SPECIES_TIER,
} PokemonFormatOperandKind;

typedef struct {
    PokemonFormatOperandKind kind;
    uint16_t catalog_id;
} PokemonFormatOperand;

typedef enum {
    POKEMON_FORMAT_RULE_SPECIES_CLAUSE = 1,
    POKEMON_FORMAT_RULE_BAN,
    POKEMON_FORMAT_RULE_COMPLEX_SET_BAN,
    POKEMON_FORMAT_RULE_UNSUPPORTED_SET_FIELDS,
    POKEMON_FORMAT_RULE_UNSUPPORTED_ADMISSION_UNIVERSE,
    POKEMON_FORMAT_RULE_RUNTIME_ONLY,
    POKEMON_FORMAT_RULE_REQUEST_PROTOCOL,
    POKEMON_FORMAT_RULE_PRESENTATION,
    POKEMON_FORMAT_RULE_ASSERTION,
    POKEMON_FORMAT_RULE_METADATA,
} PokemonFormatRuleKind;

typedef struct {
    PokemonFormatRuleKind kind;
    const char *id;
    uint8_t operand_count;
    PokemonFormatOperand operands[3];
} PokemonFormatRule;

typedef enum {
    POKEMON_GAME_TYPE_SINGLES = 1,
    POKEMON_GAME_TYPE_DOUBLES,
} PokemonGameType;

typedef struct {
    uint64_t plugin_fingerprint;
    uint32_t capability_version;
    uint64_t capabilities;
    const char *id;
    const char *name;
    uint8_t generation;
    PokemonGameType game_type;
    uint8_t min_team_size;
    uint8_t max_team_size;
    uint8_t max_move_count;
    uint8_t min_level;
    uint8_t max_level;
    uint8_t default_level;
    uint8_t ev_limit_enabled;
    uint16_t ev_limit;
    const PokemonFormatRule *rules;
    size_t rule_count;
} PokemonFormatManifest;

typedef enum {
    POKEMON_VALIDATION_ACCEPTED_BOUNDED = 1,
    POKEMON_VALIDATION_REJECTED,
} PokemonValidationDecision;

typedef enum {
    POKEMON_VALIDATION_NONE = 0,
    POKEMON_VALIDATION_TEAM_SIZE,
    POKEMON_VALIDATION_LEVEL,
    POKEMON_VALIDATION_MOVE_COUNT,
    POKEMON_VALIDATION_UNKNOWN_DESCRIPTOR,
    POKEMON_VALIDATION_SPECIES_CLAUSE,
    POKEMON_VALIDATION_BANNED,
    POKEMON_VALIDATION_COMPLEX_BAN,
} PokemonValidationReason;

typedef struct {
    PokemonValidationDecision decision;
    PokemonValidationReason reason;
    uint16_t rule_index;
    uint8_t team_slot;
    uint16_t unsupported_rule_count;
} PokemonValidationResult;

typedef struct {
    uint16_t species_catalog_id;
    uint16_t ability_catalog_id;
    uint16_t item_catalog_id;
    uint16_t move_catalog_ids[POKEMON_MOVE_CAPACITY];
    uint8_t level;
} PokemonCatalogSet;

typedef struct {
    PokemonCatalogSet members[POKEMON_TEAM_CAPACITY];
} PokemonCatalogTeam;

typedef struct {
    uint16_t ability_id;
    uint8_t blocked_status;
    PokemonEventId event;
    uint8_t cure_on_update;
    uint8_t blocks_sleep_volatile;
} PokemonStatusImmunity;

typedef struct PokemonStatusResidualPolicy PokemonStatusResidualPolicy;

typedef enum {
    POKEMON_RESIDUAL_FORMULA_NONE = 0,
    POKEMON_RESIDUAL_FORMULA_SAND,
    POKEMON_RESIDUAL_FORMULA_BURN,
    POKEMON_RESIDUAL_FORMULA_POISON,
    POKEMON_RESIDUAL_FORMULA_TOXIC,
} PokemonResidualFormula;

/* Resolved weather condition behavior. Lifecycle scheduling stays in the
 * kernel; immutable generated data supplies generation-local effects. */
typedef struct {
    uint8_t kind;
    uint16_t descriptor_id;
    PokemonResidualFormula residual_damage_formula;
    uint32_t residual_immune_type_mask;
    uint32_t blocked_status_mask;
} PokemonWeatherPolicy;

typedef enum {
    POKEMON_SLOT_EFFECT_DELAYED_FIXED_DAMAGE = 1,
    POKEMON_SLOT_EFFECT_HEAL_ACTIVE_MAX_HP_FRACTION,
} PokemonSlotEffectKind;

typedef enum {
    POKEMON_SLOT_CONDITION_NONE = 0,
    POKEMON_SLOT_CONDITION_FUTURE_MOVE,
    POKEMON_SLOT_CONDITION_WISH,
} PokemonSlotConditionKind;

/* Flattened generation data for one battlefield-position-owned condition. */
typedef struct {
    uint16_t descriptor_id;
    PokemonSlotConditionKind semantic_kind;
    PokemonSlotEffectKind effect_kind;
    uint8_t duration;
    uint8_t residual_order;
    uint8_t residual_sub_order;
    uint8_t numerator;
    uint8_t denominator;
} PokemonSlotConditionPolicy;

typedef struct {
    uint16_t move_id;
    uint16_t marker_descriptor_id;
    uint8_t marker_duration;
    /* Optional charge-stage boost, applied exactly once before marker/lock
     * installation. Zero delta denotes no charge mutation. */
    uint8_t charge_boost_stat;
    int8_t charge_boost_delta;
} PokemonTwoTurnMoveDescriptor;

typedef enum {
    POKEMON_WEIGHTED_MOVE_OUTCOME_DAMAGE = 0,
    POKEMON_WEIGHTED_MOVE_OUTCOME_TARGET_MAX_HP_HEAL,
} PokemonWeightedMoveOutcomeKind;

typedef struct {
    uint16_t weight;
    PokemonWeightedMoveOutcomeKind kind;
    union {
        struct {
            uint16_t power;
            uint16_t message_value;
        } damage;
        struct {
            uint8_t numerator;
            uint8_t denominator;
        } heal;
    } value;
} PokemonWeightedMoveOutcome;

typedef struct {
    uint16_t id;
    uint16_t outcome_offset;
    uint8_t outcome_count;
    uint8_t draw_label;
} PokemonWeightedMoveOutcomeDistribution;

typedef struct {
    uint16_t id;
    uint16_t candidate_offset;
    uint8_t candidate_count;
    uint8_t draw_label;
} PokemonStatusDistribution;

/* Candidates use immutable catalog identities, not executable-table indexes.
 * A pool can remain complete while unsupported candidates fail honestly at
 * the runtime capability boundary. */
typedef struct {
    uint16_t id;
    uint16_t caller_move_id;
    uint16_t candidate_offset;
    uint16_t candidate_count;
} PokemonMoveCallPool;

typedef enum {
    POKEMON_CONSTRUCTED_TARGET_LAST_SOURCE_OR_CURRENT_FOE = 1,
} PokemonConstructedTargetPolicy;

/* Generated hit frames are not selectable moves and own no move callback
 * dictionary. They enter at the tryMoveHit boundary with one observable move
 * identity; their owner condition supplies mutable payload. */
typedef struct {
    uint16_t id;
    uint16_t owner_condition_descriptor;
    PokemonConstructedTargetPolicy target_policy;
    PokemonMoveData move;
} PokemonConstructedHitTemplate;

/* Direct move callbacks which Showdown runs between BeforeMove and resource
 * commitment are not discoverable battle events.  Flatten them into a small
 * typed program so the kernel preserves their distinct cancellation stage
 * without dynamic callback dictionaries or generation-specific move IDs. */
typedef enum {
    POKEMON_MOVE_PRE_USE_CANCEL_IF_VOLATILE_KIND = 1,
} PokemonMovePreUseOperation;

typedef struct {
    uint16_t move_id;
    PokemonMovePreUseOperation operation;
    uint16_t volatile_kind;
} PokemonMovePreUseProgram;

typedef struct {
	uint16_t id;
	uint16_t move_id;
	uint16_t volatile_kind;
	uint16_t condition_descriptor_id;
	uint16_t marker_kind;
	uint16_t marker_descriptor_id;
	uint8_t maximum_hits;
	uint8_t power_multiplier;
	uint8_t refresh_duration;
} PokemonLockedRampPolicy;

#define POKEMON_COUNTER_HEAL_MAX_ENTRIES 3

typedef struct {
    uint16_t id;
    uint16_t volatile_kind;
    uint16_t condition_descriptor_id;
    uint8_t default_counter;
    uint8_t maximum_counter;
    uint16_t modifiers_q12[POKEMON_COUNTER_HEAL_MAX_ENTRIES];
} PokemonCounterHealPolicy;

typedef struct {
    uint16_t id;
    const uint8_t *candidate_types;
    uint8_t candidate_count;
    uint8_t resistant_multiplier_q2;
    uint8_t immune_multiplier_q2;
    uint8_t exclude_source_current_types;
    uint16_t move_type_override_catalog_id;
    uint8_t move_type_override;
} PokemonTypeResponsePolicy;

typedef struct {
    uint64_t plugin_fingerprint;
    uint32_t capability_version;
    uint64_t capabilities;
    uint8_t generation;
    const PokemonSpeciesData *species;
    size_t species_count;
    const PokemonMoveData *moves;
    size_t move_count;
    const PokemonMoveInvocationProfile *move_invocation_profiles;
    size_t move_invocation_profile_count;
    const PokemonMoveProfileSelection *move_profile_selections;
    size_t move_profile_selection_count;
    const PokemonEffectOp *effects;
    size_t effect_count;
    const PokemonAbilityData *abilities;
    size_t ability_count;
    const PokemonItemData *items;
    size_t item_count;
    const PokemonStatusImmunity *status_immunities;
    size_t status_immunity_count;
    const PokemonWeatherPolicy *weather_policies;
    size_t weather_policy_count;
    const PokemonSlotConditionPolicy *slot_condition_policies;
    size_t slot_condition_policy_count;
    const PokemonHandlerDescriptor *handlers;
    size_t handler_count;
    const PokemonOwnerBindingIndex *owner_binding_index;
    size_t owner_binding_index_count;
    const PokemonHandlerOp *handler_programs;
    size_t handler_program_count;
    const PokemonEventSpec *event_specs;
    size_t event_spec_count;
    const PokemonTwoTurnMoveDescriptor *two_turn_moves;
    size_t two_turn_move_count;
    const PokemonWeightedMoveOutcome *weighted_move_outcomes;
    size_t weighted_move_outcome_count;
    const PokemonWeightedMoveOutcomeDistribution *weighted_move_distributions;
    size_t weighted_move_distribution_count;
    const PokemonStatusDistribution *status_distributions;
    size_t status_distribution_count;
    const uint8_t *status_distribution_candidates;
    size_t status_distribution_candidate_count;
    const PokemonWeatherFormPolicy *weather_form_policies;
    size_t weather_form_policy_count;
    const PokemonWeightPowerPolicy *weight_power_policies;
    size_t weight_power_policy_count;
    const PokemonTransformPolicy *transform_policies;
    size_t transform_policy_count;
    const PokemonMoveCallPool *move_call_pools;
    size_t move_call_pool_count;
    const uint16_t *move_call_pool_candidates;
    size_t move_call_pool_candidate_count;
    const PokemonConstructedHitTemplate *constructed_hit_templates;
    size_t constructed_hit_template_count;
    const PokemonMovePreUseProgram *move_pre_use_programs;
    size_t move_pre_use_program_count;
	const PokemonLockedRampPolicy *locked_ramp_policies;
	size_t locked_ramp_policy_count;
    const PokemonCounterHealPolicy *counter_heal_policies;
    size_t counter_heal_policy_count;
    const PokemonTypeResponsePolicy *type_response_policies;
    size_t type_response_policy_count;
    const PokemonSpeciesIdentity *species_catalog;
    size_t species_catalog_count;
    const PokemonMoveIdentity *move_catalog;
    size_t move_catalog_count;
    const PokemonNamedIdentity *ability_catalog;
    size_t ability_catalog_count;
    const PokemonNamedIdentity *item_catalog;
    size_t item_catalog_count;
    const PokemonConditionIdentity *condition_catalog;
    size_t condition_catalog_count;
    /* Row-major attack type by defense type. Values are quarter-units:
     * 0 immune, 2 half, 4 neutral, 8 super-effective. */
    const uint8_t *type_chart;
    uint8_t type_count;
    /* A resolved plugin may designate one type as non-interacting. Moves of
     * that type skip the observable immunity decision, matching Showdown's
     * early-success path for `???`, while retaining ordinary accuracy. */
    uint8_t has_non_interacting_type;
    uint8_t non_interacting_type;
    uint8_t poison_type;
    uint8_t fire_type;
    uint8_t ice_type;
    uint8_t ground_type;
    uint8_t rock_type;
    uint8_t steel_type;
    /* Optional parallel ownership map. Zero denotes an independent effect;
     * equal nonzero keys within one move denote one secondary product. */
    const uint8_t *effect_secondary_groups;
    size_t effect_secondary_group_count;
    const PokemonSecondaryChancePolicy *secondary_chance_policies;
    size_t secondary_chance_policy_count;
    const PokemonStatusResidualPolicy *status_residual_policies;
    size_t status_residual_policy_count;
} PokemonData;

const PokemonSpeciesIdentity *pokemon_species_identity(
    const PokemonData *data, uint16_t catalog_id
);
const PokemonMoveIdentity *pokemon_move_identity(
    const PokemonData *data, uint16_t catalog_id
);
int pokemon_validate_move_call_pools(const PokemonData *data);
const PokemonNamedIdentity *pokemon_ability_identity(
    const PokemonData *data, uint16_t catalog_id
);
const PokemonNamedIdentity *pokemon_item_identity(
    const PokemonData *data, uint16_t catalog_id
);
const PokemonConditionIdentity *pokemon_condition_identity(
    const PokemonData *data, uint16_t catalog_id
);

typedef struct PokemonDamageInput PokemonDamageInput;
typedef uint16_t (*PokemonBaseDamageFn)(const PokemonDamageInput *input);

typedef struct {
    PokemonDamageFormula formula;
    uint16_t parameter;
    uint8_t level;
    uint16_t hp;
    uint16_t max_hp;
    uint16_t target_hp;
    uint16_t random_value;
} PokemonDamageFormulaInput;

typedef struct {
    uint16_t resolved_power;
    uint16_t fixed_damage;
    uint8_t ratio;
    uint8_t bracket;
} PokemonDamageFormulaOutput;

typedef enum {
    POKEMON_RULE_CONDITION_TOXIC = 1,
    POKEMON_RULE_CONDITION_BURN,
    POKEMON_RULE_CONDITION_POISON,
    POKEMON_RULE_CONDITION_PROTECT,
    POKEMON_RULE_CONDITION_STALL,
    POKEMON_RULE_CONDITION_REFLECT,
    POKEMON_RULE_CONDITION_SANDSTORM,
    POKEMON_RULE_CONDITION_MAGIC_COAT,
    POKEMON_RULE_CONDITION_SNATCH,
    POKEMON_RULE_CONDITION_HAIL,
    POKEMON_RULE_CONDITION_RAIN,
    POKEMON_RULE_CONDITION_SUN,
    POKEMON_RULE_CONDITION_CONFUSION,
    POKEMON_RULE_CONDITION_LOCKED_MOVE,
    POKEMON_RULE_CONDITION_TWO_TURN_MOVE,
    POKEMON_RULE_CONDITION_FLINCH,
    POKEMON_RULE_CONDITION_FOCUS_ENERGY,
    POKEMON_RULE_CONDITION_LIGHT_SCREEN,
    POKEMON_RULE_CONDITION_PARTIALLY_TRAPPED,
    POKEMON_RULE_CONDITION_TAUNT,
    POKEMON_RULE_CONDITION_TORMENT,
    POKEMON_RULE_CONDITION_DISABLE,
    POKEMON_RULE_CONDITION_ENCORE,
    POKEMON_RULE_CONDITION_MIST,
    POKEMON_RULE_CONDITION_SAFEGUARD,
    POKEMON_RULE_CONDITION_YAWN,
    POKEMON_RULE_CONDITION_SPIKES,
    POKEMON_RULE_CONDITION_MUST_RECHARGE,
    POKEMON_RULE_CONDITION_NIGHTMARE,
    POKEMON_RULE_CONDITION_ATTRACT,
	POKEMON_RULE_CONDITION_CHOICE_LOCK,
	POKEMON_RULE_CONDITION_TRAPPED,
	POKEMON_RULE_CONDITION_TRAPPER,
	POKEMON_RULE_CONDITION_MUD_SPORT,
	POKEMON_RULE_CONDITION_WATER_SPORT,
    POKEMON_RULE_CONDITION_ENDURE,
    POKEMON_RULE_CONDITION_LOCK_ON,
    POKEMON_RULE_CONDITION_RETALIATION_PHYSICAL,
    POKEMON_RULE_CONDITION_RETALIATION_SPECIAL,
    POKEMON_RULE_CONDITION_INGRAIN,
    POKEMON_RULE_CONDITION_QUEUED_MOVE_INTERCEPT,
    POKEMON_RULE_CONDITION_CHARGE,
    POKEMON_RULE_CONDITION_LEECH_SEED,
    POKEMON_RULE_CONDITION_FLASH_FIRE,
    POKEMON_RULE_CONDITION_COUNTDOWN_FAINT,
    POKEMON_RULE_CONDITION_PERSISTENT_HANDLER_DRIVEN,
    POKEMON_RULE_CONDITION_STORED_DAMAGE,
    POKEMON_RULE_CONDITION_BOUNDED_COUNTER,
} PokemonRuleConditionKind;

/* Compatibility spelling for existing focused tests and generated history. */
#define POKEMON_RULE_CONDITION_FORESIGHT \
    POKEMON_RULE_CONDITION_PERSISTENT_HANDLER_DRIVEN

/* Compatibility spelling for existing generated/test data. The semantic
 * capability is the bounded counter; power ramps are one consumer. */
#define POKEMON_RULE_CONDITION_RAMPING_POWER \
    POKEMON_RULE_CONDITION_BOUNDED_COUNTER

typedef enum {
    POKEMON_CONDITION_DURATION_NONE = 0,
    POKEMON_CONDITION_DURATION_FIXED,
    POKEMON_CONDITION_DURATION_UNIFORM,
} PokemonConditionDurationKind;

typedef enum {
    POKEMON_DRAW_TEAM_GENDER = 1,
    POKEMON_DRAW_QUEUE_TIE,
    POKEMON_DRAW_ACCURACY,
    POKEMON_DRAW_CRITICAL,
    POKEMON_DRAW_DAMAGE_ROLL,
    POKEMON_DRAW_END_TURN,
    POKEMON_DRAW_STALL_SUCCESS,
    POKEMON_DRAW_SET_STATUS_HANDLER_ORDER,
    POKEMON_DRAW_SET_STATUS_HANDLER_ORDER_OFFSET_ONE,
    POKEMON_DRAW_RESIDUAL_HANDLER_ORDER,
    POKEMON_DRAW_SECONDARY,
    POKEMON_DRAW_MULTIHIT_COUNT,
    POKEMON_DRAW_EVENT_HANDLER_ORDER,
    POKEMON_DRAW_SLEEP_DURATION,
    POKEMON_DRAW_PARALYSIS,
    POKEMON_DRAW_FREEZE_THAW,
    POKEMON_DRAW_EACH_EVENT_BEFORE_TURN_ACTIVE_ORDER,
    POKEMON_DRAW_EACH_EVENT_UPDATE_ACTIVE_ORDER,
    POKEMON_DRAW_EACH_EVENT_WEATHER_ACTIVE_ORDER,
    POKEMON_DRAW_EACH_EVENT_WEATHER_CHANGE_ACTIVE_ORDER,
    POKEMON_DRAW_CONFUSION_DURATION,
    POKEMON_DRAW_CONFUSION_ACTION,
    POKEMON_DRAW_LOCKED_MOVE_DURATION,
    POKEMON_DRAW_PARTIALLY_TRAPPED_DURATION,
    POKEMON_DRAW_DISABLE_DURATION,
    POKEMON_DRAW_ENCORE_DURATION,
    POKEMON_DRAW_UPROAR_DURATION,
    POKEMON_DRAW_DAMAGE_FORMULA,
    POKEMON_DRAW_CONTACT_RESPONSE,
    POKEMON_DRAW_CONTACT_STATUS_SELECTION,
    /* Ability-owned residual major-status cure gates, such as Shed Skin. */
    POKEMON_DRAW_RESIDUAL_STATUS_CURE,
    /* Selection owned by an ability handler, including singleton samples. */
    POKEMON_DRAW_ABILITY_TARGET,
    /* Source-bound attraction condition's per-action immobilization gate. */
    POKEMON_DRAW_ATTRACTION_ACTION,
    /* Item-owned uniform selection from a generated eligible-stat set. */
    POKEMON_DRAW_ITEM_RANDOM_STAT,
    /* Move-owned generated weighted base-power selection. */
    POKEMON_DRAW_MOVE_POWER_DISTRIBUTION,
    /* Move-owned selection which can change the active resolution kind. */
    POKEMON_DRAW_MOVE_RESOLUTION_DISTRIBUTION,
	/* Item-owned survival gate; evaluated before lethal/cause predicates. */
	POKEMON_DRAW_FOCUS_BAND,
    /* Uniform selection from the target side's living inactive party. */
    POKEMON_DRAW_FORCED_SWITCH_TARGET,
    /* Move-owned uniform selection from a generated delegation pool. */
    POKEMON_DRAW_MOVE_DELEGATION_SELECTION,
    /* Uniform selection from a generated type-response candidate order. */
    POKEMON_DRAW_TYPE_RESPONSE_SELECTION,
    POKEMON_DRAW_MOVE_PP_REDUCTION,
    POKEMON_DRAW_MOVE_TYPE_SELECTION,
    /* Move-secondary callback-owned selection from generated status data. */
    POKEMON_DRAW_MOVE_STATUS_SELECTION,
    POKEMON_DRAW_LABEL_COUNT,
} PokemonDrawLabel;

typedef struct {
    PokemonConditionDurationKind kind;
    uint8_t minimum;
    uint8_t maximum;
} PokemonConditionDuration;

typedef enum {
    POKEMON_STATUS_NONE = 0,
    POKEMON_STATUS_BURN,
    POKEMON_STATUS_TOXIC,
    POKEMON_STATUS_PARALYSIS,
    POKEMON_STATUS_POISON,
    POKEMON_STATUS_SLEEP,
    POKEMON_STATUS_FREEZE,
} PokemonStatus;

typedef struct {
    PokemonStatus status;
    PokemonHandlerId handler_id;
    /* Apply only when the proposed status source is on the opposing side. */
    uint8_t requires_opposing_source;
    /* Existing matching status blocks regardless of HP or provenance. */
    uint8_t block_any_existing;
    /* Otherwise, only a living member statused by an opponent blocks. */
    uint8_t block_living_opponent_caused;
} PokemonStatusClausePolicy;

typedef enum {
    POKEMON_STATUS_RESIDUAL_STATELESS = 1,
    POKEMON_STATUS_RESIDUAL_TICK,
    POKEMON_STATUS_RESIDUAL_ESCALATE,
} PokemonStatusResidualStatePolicy;

struct PokemonStatusResidualPolicy {
    uint16_t descriptor_id;
    PokemonStatus status;
    PokemonResidualFormula formula;
    PokemonStatusResidualStatePolicy state_policy;
};

typedef struct {
    PokemonRuleConditionKind kind;
    uint16_t descriptor_id;
    PokemonConditionDuration lifecycle_duration;
    uint8_t has_residual;
    uint8_t has_order;
    uint8_t residual_order;
    uint8_t residual_sub_order;
    uint8_t speed_tied;
    /* Random duration is a semantic PRNG operation owned by this resolved
     * condition descriptor. Fixed and durationless conditions use zero. */
    PokemonDrawLabel duration_draw_label;
    /* Structural transfer policy. Executable Start/Residual behavior remains
     * in generated handler programs. */
    uint8_t no_copy;
    /* Remove this volatile when the named major status ends. Zero means no
     * status-lifetime dependency. */
    PokemonStatus remove_with_status;
	/* Optional hidden counterpart installed on the recorded source.  This is
	 * the flattened fixed-capacity representation of Showdown linkedStatus:
	 * zero means unlinked; otherwise this names the counterpart volatile kind
	 * whose admission and effect-order boundary must still execute. */
    uint16_t source_linked_kind;
    /* This resolved condition may be installed by the shared stalling-move
     * operation. The capability belongs to plugin data rather than to a
     * generation-specific volatile ID in the generic kernel. */
    uint8_t flags;
} PokemonConditionRule;

enum {
	POKEMON_CONDITION_RULE_STALLING_GUARD = UINT8_C(1) << 0,
	POKEMON_CONDITION_RULE_REPEATABLE_FAMILY = UINT8_C(1) << 1,
};

typedef struct {
    uint8_t initial_denominator;
    uint8_t multiplier;
    uint8_t denominator_cap;
} PokemonStallPolicy;

typedef struct {
    uint16_t numerator;
    uint16_t denominator;
} PokemonStageRatio;

typedef struct {
    int8_t minimum;
    int8_t maximum;
    PokemonStageRatio ordinary[13];
    PokemonStageRatio accuracy[13];
} PokemonStagePolicy;

/* A generation owns the probability law for ranged multi-hit moves.  Fixed
 * counts remain move data and consume no PRNG draw.  Keeping the finite
 * outcome table here prevents the generation-neutral hit loop from encoding
 * Gen 3's 3/8, 3/8, 1/8, 1/8 distribution. */
typedef struct {
    uint8_t minimum;
    uint8_t maximum;
    const uint8_t *outcomes;
    uint8_t outcome_count;
} PokemonMultiHitPolicy;

typedef struct {
    uint8_t base_accuracy;
} PokemonOhkoRules;

typedef struct {
    PokemonDamageFormula formula;
    uint16_t minimum;
    uint16_t maximum_exclusive;
} PokemonDamageFormulaRandomPolicy;

typedef enum {
    POKEMON_WEATHER_DAMAGE_BEFORE_FINAL_BASE_OFFSET = 1,
    POKEMON_WEATHER_DAMAGE_AFTER_FINAL_BASE_OFFSET,
} PokemonWeatherDamageStage;

typedef struct {
    uint8_t numerator;
    uint8_t denominator;
    uint16_t speed_sentinel;
} PokemonSharedTurnSpeedPolicy;

/* A generation owns the relative staging of immunity, accuracy, and target
 * TryHit.  Gen 3 discovers natural and move-owned immunity first, but defers
 * the visible rejection until after accuracy and a successful target TryHit. */
typedef enum {
    POKEMON_HIT_STAGING_INVALID = 0,
    POKEMON_HIT_STAGING_DEFER_IMMUNITY_AFTER_ACCURACY_AND_TRY_HIT,
} PokemonHitStagingPolicy;

uint32_t pokemon_apply_stage_ratio(
    const PokemonStagePolicy *policy, uint32_t value, int8_t stage,
    uint8_t accuracy
);

typedef void (*PokemonResolveDamageFormulaFn)(
    const PokemonDamageFormulaInput *input,
    PokemonDamageFormulaOutput *output
);
typedef uint16_t (*PokemonResidualDamageFn)(
    PokemonResidualFormula formula, uint16_t max_hp, uint8_t stage
);
typedef uint16_t (*PokemonFractionFn)(
    uint16_t basis, uint8_t numerator, uint8_t denominator
);
typedef uint16_t (*PokemonConditionDescriptorFn)(
    PokemonOwnerKind owner_kind, uint16_t semantic_kind
);
typedef void (*PokemonCriticalChanceFn)(
    uint32_t stage, uint8_t *numerator, uint8_t *denominator
);
typedef int (*PokemonResolvePersonalMoveProfileFn)(
    uint16_t kind, const uint8_t ivs[6], PokemonPersonalMoveProfile *output
);
typedef int (*PokemonRecalculateSpeciesStatFn)(
    uint16_t original_stat, uint8_t original_base, uint8_t replacement_base,
    uint8_t iv, uint8_t level, uint8_t nature, uint16_t *output
);

typedef struct {
    uint64_t plugin_fingerprint;
    uint32_t capability_version;
    uint64_t capabilities;
    uint8_t generation;
    uint8_t critical_multiplier;
    PokemonSharedTurnSpeedPolicy shared_turn_speed;
    uint8_t toxic_stage_cap;
    uint8_t paralysis_speed_numerator;
    uint8_t paralysis_speed_denominator;
    uint8_t confusion_duration_min;
    uint8_t confusion_duration_max;
    uint8_t confusion_action_denominator;
    uint8_t locked_move_duration_min;
    uint8_t locked_move_duration_max;
    uint8_t has_separate_modify_type_phase;
    PokemonHitStagingPolicy hit_staging;
    PokemonWeatherDamageStage weather_damage_stage;
    PokemonBaseDamageFn base_damage;
    PokemonResolveDamageFormulaFn resolve_damage_formula;
    PokemonResidualDamageFn residual_damage;
    PokemonFractionFn fraction;
    PokemonConditionDescriptorFn condition_descriptor;
    PokemonCriticalChanceFn critical_chance;
    PokemonResolvePersonalMoveProfileFn resolve_personal_move_profile;
    PokemonRecalculateSpeciesStatFn recalculate_species_stat;
    const PokemonConditionRule *condition_rules;
    size_t condition_rule_count;
    PokemonStallPolicy stall;
    const PokemonStagePolicy *stages;
    PokemonMultiHitPolicy multihit;
    PokemonOhkoRules ohko;
    const PokemonDamageFormulaRandomPolicy *random_damage_formulas;
    size_t random_damage_formula_count;
    uint8_t substitute_cost_denominator;
    uint8_t substitute_reject_max_hp_one;
    uint8_t knock_off_locks_item_slot;
    uint8_t cancel_all_actions_on_faint;
    uint8_t self_destruct_defense_divisor;
    /* Whether an ability replacement transaction starts the new ability. */
    uint8_t replaced_ability_runs_start;
    /* Gen 2-4 continue a switch selected before an interception KO. */
    uint8_t continue_preselected_switch_after_interception_faint;
    uint16_t fallback_move_id;
    const PokemonChoiceControlPolicy *choice_control_policies;
    size_t choice_control_policy_count;
} PokemonGeneration;

typedef struct {
    uint64_t plugin_fingerprint;
    uint32_t capability_version;
    uint64_t capabilities;
    uint8_t generation;
    uint8_t team_size;
    uint8_t active_per_side;
    const PokemonTargetRule *target_rules;
    uint8_t target_rule_count;
} PokemonFormat;

typedef enum {
    POKEMON_VOLUNTARY_SWITCH_ORDER_NONE = 0,
    POKEMON_VOLUNTARY_SWITCH_ORDER_SPEED,
} PokemonVoluntarySwitchOrder;

/* Resolved server-protocol behavior. The Ocean ABI commits both sides'
 * choices atomically and exposes canonical exact HP/state, so these facts do
 * not mutate PokemonBattle. Keeping them typed prevents flattened RuleTable
 * leaves from becoming unowned string metadata. */
typedef struct {
    uint8_t report_hp_percentages;
    uint8_t allow_uncommitted_choice_cancel;
    uint8_t hide_beat_up_party_identity;
} PokemonProtocolPolicy;

/* A resolved format terminal policy. The turn limit is deliberately
 * independent of Endless Battle Clause, matching Showdown's Battle boundary. */
typedef struct {
    uint16_t endless_minimum_turn;
    uint16_t turn_limit;
    uint8_t endless_battle_clause;
} PokemonTerminalPolicy;

/* Effective battle-time policy resolved from a format's RuleTable. Geometry
 * remains reusable across formats which select different rule policies. */
typedef struct {
    uint64_t plugin_fingerprint;
    uint32_t capability_version;
    uint64_t capabilities;
    uint8_t generation;
    const PokemonFormatManifest *manifest;
    const PokemonStatusClausePolicy *status_clauses;
    size_t status_clause_count;
    PokemonVoluntarySwitchOrder voluntary_switch_order;
    PokemonProtocolPolicy protocol;
    PokemonTerminalPolicy terminal;
} PokemonFormatPolicy;

/* A format selects one already-flattened generation implementation. Keeping
 * these pointers in one immutable value prevents callers from independently
 * pairing data, mechanics, runtime geometry, and legality from different
 * generations. */
typedef struct PokemonResolvedBundle {
    uint64_t plugin_fingerprint;
    uint32_t capability_version;
    uint64_t capabilities;
    uint8_t generation;
    const PokemonGeneration *rules;
    const PokemonData *data;
    const PokemonFormat *runtime_format;
    const PokemonFormatPolicy *policy;
    const PokemonFormatManifest *manifest;
} PokemonResolvedBundle;

#define POKEMON_KERNEL_PLUGIN_ABI_VERSION UINT32_C(34)
#define POKEMON_CAP_CONDITION(kind) (UINT64_C(1) << ((uint64_t)(kind) - 1u))
#define POKEMON_CAP_ALL_CURRENT_CONDITIONS \
    ((UINT64_C(1) << POKEMON_RULE_CONDITION_BOUNDED_COUNTER) - UINT64_C(1))
/* Reserve the low 48 bits for independently selectable condition families.
 * Kernel-service capabilities begin at bit 48 so extending the condition
 * vocabulary cannot alias a required service capability. */
#define POKEMON_CAP_SINGLES_GEOMETRY       (UINT64_C(1) << 48)
#define POKEMON_CAP_TARGETING              (UINT64_C(1) << 49)
#define POKEMON_CAP_EVENT_INTERPRETER      (UINT64_C(1) << 50)
#define POKEMON_CAP_HANDLER_PROGRAMS       (UINT64_C(1) << 51)
#define POKEMON_CAP_EFFECT_PROGRAMS        (UINT64_C(1) << 52)
#define POKEMON_CAP_CRITICAL_POLICY        (UINT64_C(1) << 53)
#define POKEMON_CAP_MULTIHIT_POLICY        (UINT64_C(1) << 54)
#define POKEMON_CAP_CONDITION_RULES        (UINT64_C(1) << 55)
#define POKEMON_CAP_DAMAGE_RULES           (UINT64_C(1) << 56)
#define POKEMON_CAP_FORMAT_POLICY          (UINT64_C(1) << 57)
#define POKEMON_CAP_PERSONAL_MOVE_PROFILE  (UINT64_C(1) << 58)
#define POKEMON_CAP_SLOT_CONDITIONS         (UINT64_C(1) << 59)
#define POKEMON_CAP_REQUIRED_BASE \
    (POKEMON_CAP_SINGLES_GEOMETRY | POKEMON_CAP_TARGETING | \
     POKEMON_CAP_EVENT_INTERPRETER | POKEMON_CAP_CRITICAL_POLICY | \
     POKEMON_CAP_MULTIHIT_POLICY | POKEMON_CAP_CONDITION_RULES | \
     POKEMON_CAP_DAMAGE_RULES | POKEMON_CAP_FORMAT_POLICY | \
     POKEMON_CAP_PERSONAL_MOVE_PROFILE | POKEMON_CAP_SLOT_CONDITIONS)
#define POKEMON_CAP_KNOWN \
    (POKEMON_CAP_ALL_CURRENT_CONDITIONS | POKEMON_CAP_REQUIRED_BASE | \
     POKEMON_CAP_HANDLER_PROGRAMS | POKEMON_CAP_EFFECT_PROGRAMS)
#define POKEMON_CAP_GEN3 \
    (POKEMON_CAP_KNOWN)
#ifdef __cplusplus
#define POKEMON_STATIC_ASSERT static_assert
#else
#define POKEMON_STATIC_ASSERT _Static_assert
#endif
POKEMON_STATIC_ASSERT(POKEMON_RULE_CONDITION_BOUNDED_COUNTER <= 48,
    "condition capabilities must remain below kernel-service capabilities");
POKEMON_STATIC_ASSERT((POKEMON_CAP_ALL_CURRENT_CONDITIONS &
    POKEMON_CAP_REQUIRED_BASE) == 0,
    "condition and kernel-service capability domains must not overlap");
#undef POKEMON_STATIC_ASSERT

int pokemon_resolve_move_target(
    const PokemonFormat *format,
    PokemonMoveTarget mode,
    PokemonTargetRule *resolved
);

typedef enum {
    POKEMON_GENDER_UNSPECIFIED = 0,
    POKEMON_GENDER_MALE,
    POKEMON_GENDER_FEMALE,
    POKEMON_GENDER_NONE,
} PokemonGender;

typedef enum {
    POKEMON_FLAVOR_NONE = 0,
    POKEMON_FLAVOR_SPICY,
    POKEMON_FLAVOR_DRY,
    POKEMON_FLAVOR_SWEET,
    POKEMON_FLAVOR_BITTER,
    POKEMON_FLAVOR_SOUR,
} PokemonFlavor;

typedef enum {
    POKEMON_NATURE_UNSPECIFIED = 0,
    POKEMON_NATURE_HARDY,
    POKEMON_NATURE_LONELY,
    POKEMON_NATURE_BRAVE,
    POKEMON_NATURE_ADAMANT,
    POKEMON_NATURE_NAUGHTY,
    POKEMON_NATURE_BOLD,
    POKEMON_NATURE_DOCILE,
    POKEMON_NATURE_RELAXED,
    POKEMON_NATURE_IMPISH,
    POKEMON_NATURE_LAX,
    POKEMON_NATURE_TIMID,
    POKEMON_NATURE_HASTY,
    POKEMON_NATURE_SERIOUS,
    POKEMON_NATURE_JOLLY,
    POKEMON_NATURE_NAIVE,
    POKEMON_NATURE_MODEST,
    POKEMON_NATURE_MILD,
    POKEMON_NATURE_QUIET,
    POKEMON_NATURE_BASHFUL,
    POKEMON_NATURE_RASH,
    POKEMON_NATURE_CALM,
    POKEMON_NATURE_GENTLE,
    POKEMON_NATURE_SASSY,
    POKEMON_NATURE_CAREFUL,
    POKEMON_NATURE_QUIRKY,
} PokemonNature;

typedef struct {
    uint16_t species_id;
    uint16_t ability_id;
    uint16_t item_id;
    uint16_t move_ids[POKEMON_MOVE_CAPACITY];
    uint16_t stats[6]; /* HP, Attack, Defense, Sp. Atk, Sp. Def, Speed */
    /* HP, Attack, Defense, Sp. Atk, Sp. Def, Speed.  Omitted IVs normalize
     * to 31 at the input boundary before plugin-owned derivation. */
    uint8_t ivs[6];
    uint8_t ivs_specified;
    uint8_t level;
    PokemonGender gender;
    PokemonNature nature;
    PokemonFlavor disliked_flavor;
    uint8_t happiness;
    uint8_t happiness_specified;
} PokemonSet;

typedef struct {
    PokemonSet members[POKEMON_TEAM_CAPACITY];
} PokemonTeam;

PokemonValidationResult pokemon_validate_catalog_team(
    const PokemonFormatManifest *format,
    const PokemonData *data,
    const PokemonCatalogTeam *team,
    uint8_t team_size
);

typedef struct {
    const PokemonResolvedBundle *bundle;
    PokemonTeam teams[POKEMON_SIDES];
    uint16_t seed[4];
    uint8_t team_sizes[POKEMON_SIDES];
    uint8_t initial_status[POKEMON_SIDES][POKEMON_TEAM_CAPACITY];
    uint8_t initial_sleep_time[POKEMON_SIDES][POKEMON_TEAM_CAPACITY];
    uint8_t initial_sleep_skipped_time[POKEMON_SIDES][POKEMON_TEAM_CAPACITY];
    uint8_t initial_toxic_stage[POKEMON_SIDES][POKEMON_TEAM_CAPACITY];
    uint16_t initial_hp[POKEMON_SIDES][POKEMON_TEAM_CAPACITY];
} PokemonBattleInit;

struct PokemonDamageInput {
    const PokemonSet *attacker;
    const PokemonSet *defender;
    const PokemonMoveData *move;
    uint8_t critical;
    uint32_t attack;
    uint32_t defense;
};

typedef enum {
    POKEMON_EVENT_SWITCH = 1,
    POKEMON_EVENT_MOVE,
    POKEMON_EVENT_MISS,
    POKEMON_EVENT_IMMUNE,
    POKEMON_EVENT_DAMAGE,
    POKEMON_EVENT_FAINT,
    POKEMON_EVENT_WIN,
    POKEMON_EVENT_STATUS,
    POKEMON_EVENT_CONDITION,
    POKEMON_EVENT_BLOCK,
    POKEMON_EVENT_HEAL,
    POKEMON_EVENT_TIE,
} PokemonEventKind;

typedef enum {
    POKEMON_IMMUNITY_NONE = 0,
    POKEMON_IMMUNITY_NATURAL_TYPE,
    POKEMON_IMMUNITY_LEVITATE,
    POKEMON_IMMUNITY_HANDLER,
    POKEMON_IMMUNITY_OHKO_RULE,
} PokemonImmunityCause;

typedef enum {
    POKEMON_SWITCH_CAUSE_NONE = 0,
    POKEMON_SWITCH_CAUSE_INITIAL,
    POKEMON_SWITCH_CAUSE_VOLUNTARY,
    POKEMON_SWITCH_CAUSE_FORCED_REPLACEMENT,
    POKEMON_SWITCH_CAUSE_DRAG,
    POKEMON_SWITCH_CAUSE_MOVE_DRIVEN,
} PokemonSwitchCause;

typedef struct {
    PokemonEventKind kind;
    uint8_t side;
    uint8_t target_side;
    uint8_t slot;
    uint16_t species_id;
    uint16_t move_id;
    uint16_t amount;
    uint16_t hp;
    uint8_t condition_scope;
    uint16_t condition_id;
    uint8_t damage_relative_kind;
    PokemonImmunityCause immunity_cause;
    PokemonHandlerId handler_id;
    PokemonSwitchCause switch_cause;
} PokemonEvent;

typedef enum {
    POKEMON_HANDLER_CONTINUE = 0,
    POKEMON_HANDLER_IMMUNE,
    POKEMON_HANDLER_PREVENT,
    POKEMON_HANDLER_HIT_SUBSTITUTE,
} PokemonHandlerResult;

typedef struct {
    PokemonHandlerDescriptor descriptor;
    uint16_t binding_index;
    PokemonOwnerRef owner;
    uint8_t holder_side;
    uint8_t holder_slot;
    uint16_t speed;
    uint16_t effect_order;
} PokemonHandlerRef;

typedef enum {
    POKEMON_EVENT_CANCEL_NONE = 0,
    POKEMON_EVENT_CANCEL_FALSE,
    POKEMON_EVENT_CANCEL_NULL,
    POKEMON_EVENT_CANCEL_NOT_FAIL,
} PokemonEventCancellation;

typedef struct {
    PokemonEventId event;
    PokemonEventAlgebra algebra;
    uint8_t depth;
    PokemonEntityRef source;
    PokemonEntityRef target;
    PokemonSourceEffectRef source_effect;
    PokemonOwnerRef effect;
    PokemonRelay relay;
    uint32_t modifier_q12;
    PokemonOwnerRef cancelling_owner;
    PokemonHandlerId cancelling_handler_id;
    PokemonEventCancellation cancellation;
    uint8_t cancellation_emits_immunity;
    uint8_t executed_count;
    uint8_t skipped_count;
} PokemonEventFrame;

typedef struct {
    PokemonEventId event;
    PokemonEntityRef source;
    uint8_t target_side;
    uint8_t target_slot;
    PokemonSourceEffectRef source_effect;
    PokemonRelay relay;
    enum {
        POKEMON_EVENT_CONTEXT_MOVE = 1,
        POKEMON_EVENT_CONTEXT_DAMAGE,
        POKEMON_EVENT_CONTEXT_VOLATILE,
        POKEMON_EVENT_CONTEXT_STATUS,
        POKEMON_EVENT_CONTEXT_MOVE_RESTRICTIONS,
        POKEMON_EVENT_CONTEXT_SWITCH_RESTRICTIONS,
        POKEMON_EVENT_CONTEXT_IMMUNITY,
        POKEMON_EVENT_CONTEXT_ABILITY,
    } context_kind;
    union {
        struct {
            const PokemonMoveData *move;
            uint8_t critical;
            uint16_t damage;
            /* ModifySecondaries still targets the opposing holder when the
             * candidate product contains only self-directed effects. */
            uint8_t secondary_self_only;
        } move;
        struct {
            PokemonDamageRelativeKind kind;
            uint16_t source_move_id;
            uint8_t preventable;
            PokemonRetaliationClassMask retaliation_class_mask;
        } damage;
        struct { uint16_t kind; } volatile_condition;
        struct { uint8_t proposed; uint8_t emit_immunity; } status;
        PokemonMoveRestrictionBuffer *move_restrictions;
        PokemonSwitchRestrictionBuffer *switch_restrictions;
        struct { uint16_t condition_descriptor_id; } immunity;
        struct { uint16_t proposed; } ability;
    } context;
    uint8_t suppress_trace;
    uint8_t include_move_self;
    /* Add the move callback named by source_effect.  Unlike move-self events,
     * the effect holder is the event target (for example Damage callbacks). */
    uint8_t include_source_effect_move;
    uint8_t has_only_handler;
    uint8_t suppress_handler_trace;
    PokemonHandlerRef only_handler;
} PokemonEventInput;

typedef struct {
    PokemonHandlerRef handler;
    uint32_t semantic_sequence;
    uint8_t invoked;
    PokemonHandlerResult result;
} PokemonHandlerInvocation;

typedef struct {
    PokemonHandlerRef handler;
    uint32_t semantic_sequence;
    double input;
    uint32_t modifier_before_q12;
    uint32_t modifier_q12;
    uint32_t modifier_after_q12;
    double output;
    uint8_t invoked;
} PokemonModifierInvocation;

typedef struct {
    PokemonHandlerEvent event;
    uint32_t semantic_sequence;
    uint8_t holder_side;
    uint8_t holder_slot;
    double input;
    uint32_t modifier_q12;
    double output;
} PokemonRelayResult;

typedef enum {
    POKEMON_DAMAGE_STAGE_BURN = 1,
} PokemonDamageStageKind;

typedef enum {
    POKEMON_BURN_NOT_BURNED = 1,
    POKEMON_BURN_ZERO_DAMAGE,
    POKEMON_BURN_NOT_PHYSICAL,
    POKEMON_BURN_GUTS,
    POKEMON_BURN_APPLIED,
} PokemonBurnReason;

typedef struct {
    PokemonDamageStageKind kind;
    PokemonDamageMode mode;
    uint32_t semantic_sequence;
    uint32_t input;
    uint32_t modifier_q12;
    uint32_t output;
    uint8_t source_side;
    uint8_t target_side;
    uint16_t move_id;
    uint16_t side_condition_kind;
    uint8_t applied;
    PokemonBurnReason reason;
} PokemonDamageStageTrace;

typedef struct {
    uint8_t move_type;
    uint8_t target_side;
    uint8_t target_slot;
    PokemonImmunityCause cause;
    uint16_t effect_id;
} PokemonImmunityDecision;

/* Ordinary trySetStatus-style effects may only fill an empty slot. Direct
 * setStatus-style effects may explicitly replace a different status. */
typedef enum {
    POKEMON_STATUS_SET_EMPTY_ONLY = 0,
    POKEMON_STATUS_SET_REPLACE_DIFFERENT,
} PokemonStatusSetPolicy;

typedef struct {
    PokemonStatus kind;
    uint16_t descriptor_id;
    uint16_t state_generation;
    uint16_t effect_order;
    PokemonEntityRef source;
    PokemonSourceEffectRef source_effect;
    union {
        struct { uint8_t stage; } toxic;
        struct { uint8_t time; uint8_t skipped_time; } sleep;
    } state;
} PokemonStatusState;

typedef enum {
    POKEMON_VOLATILE_NONE = 0,
    POKEMON_VOLATILE_PROTECT,
    POKEMON_VOLATILE_STALL,
    POKEMON_VOLATILE_SUBSTITUTE,
    POKEMON_VOLATILE_SUBSTITUTE_BROKEN,
    POKEMON_VOLATILE_PARTIALLY_TRAPPED,
    POKEMON_VOLATILE_MAGIC_COAT,
    POKEMON_VOLATILE_SNATCH,
    POKEMON_VOLATILE_CONFUSION,
    POKEMON_VOLATILE_LOCKED_MOVE,
    POKEMON_VOLATILE_TWO_TURN_MOVE,
    POKEMON_VOLATILE_TWO_TURN_MARKER,
    POKEMON_VOLATILE_FLINCH,
    POKEMON_VOLATILE_FOCUS_ENERGY,
    POKEMON_VOLATILE_TAUNT,
    POKEMON_VOLATILE_TORMENT,
    POKEMON_VOLATILE_DISABLE,
    POKEMON_VOLATILE_ENCORE,
    POKEMON_VOLATILE_YAWN,
    POKEMON_VOLATILE_MUST_RECHARGE,
    POKEMON_VOLATILE_NIGHTMARE,
    POKEMON_VOLATILE_ATTRACT,
	POKEMON_VOLATILE_CHOICE_LOCK,
	POKEMON_VOLATILE_TRAPPED,
	POKEMON_VOLATILE_TRAPPER,
	POKEMON_VOLATILE_MUD_SPORT,
	POKEMON_VOLATILE_WATER_SPORT,
	POKEMON_VOLATILE_ENDURE,
	POKEMON_VOLATILE_LOCK_ON,
	POKEMON_VOLATILE_PREPARED_RETALIATION,
	POKEMON_VOLATILE_INGRAIN,
	POKEMON_VOLATILE_QUEUED_MOVE_INTERCEPT,
	POKEMON_VOLATILE_CHARGE,
	POKEMON_VOLATILE_LEECH_SEED,
	POKEMON_VOLATILE_FLASH_FIRE,
	POKEMON_VOLATILE_COUNTDOWN_FAINT,
	POKEMON_VOLATILE_FORESIGHT,
	POKEMON_VOLATILE_STORED_DAMAGE,
	POKEMON_VOLATILE_FURY_CUTTER,
	POKEMON_VOLATILE_ROLLOUT,
	POKEMON_VOLATILE_ICE_BALL,
	POKEMON_VOLATILE_DEFENSE_CURL,
	POKEMON_VOLATILE_STOCKPILE,
	/* Reactive self condition installed by a generated move effect. */
	POKEMON_VOLATILE_RAGE,
	POKEMON_VOLATILE_MINIMIZE,
	POKEMON_VOLATILE_PREPARED_ACTION,
	POKEMON_VOLATILE_SOURCE_FAINT_RESPONSE,
	POKEMON_VOLATILE_SOURCE_PP_ZERO_RESPONSE,
	POKEMON_VOLATILE_UPROAR,
	POKEMON_VOLATILE_IMPRISON,
	POKEMON_VOLATILE_CURSE,
	POKEMON_VOLATILE_PARTY_HIT,
	POKEMON_VOLATILE_KIND_COUNT,
} PokemonVolatileKind;

typedef struct {
    PokemonVolatileKind kind;
    uint16_t descriptor_id;
    uint8_t duration;
    uint8_t counter;
    uint16_t state_generation;
    uint16_t effect_order;
    PokemonEntityRef source;
    PokemonSourceEffectRef source_effect;
    /* Identity of a hidden source-side linkedStatus marker.  Multiple
     * visible relations may share one marker/effect order. */
    uint16_t linked_source_state_generation;
    uint16_t linked_source_effect_order;
    union {
        struct { uint16_t hp; } substitute;
        struct { uint16_t breaking_move_id; } substitute_broken;
        struct { uint8_t time; } confusion;
        struct { uint16_t move_id; uint8_t true_duration; } locked_move;
        struct { uint16_t stored_move_id; } choice_control;
        struct {
            uint16_t move_id;
            uint8_t target_side;
            uint8_t target_slot;
            uint8_t released;
        } two_turn;
        struct {
            uint32_t damage;
            uint8_t source_side;
            uint8_t source_position;
            uint8_t captured;
        } retaliation;
        struct {
            uint32_t value;
            PokemonEntityRef last_source;
            uint8_t captured;
        } stored_damage;
    } payload;
} PokemonVolatileState;

typedef enum {
    POKEMON_SIDE_CONDITION_NONE = 0,
    POKEMON_SIDE_CONDITION_PHYSICAL_SCREEN,
    POKEMON_SIDE_CONDITION_SPECIAL_SCREEN,
    POKEMON_SIDE_CONDITION_MIST,
    POKEMON_SIDE_CONDITION_SAFEGUARD,
    POKEMON_SIDE_CONDITION_SPIKES,
    POKEMON_SIDE_CONDITION_REFLECT = POKEMON_SIDE_CONDITION_PHYSICAL_SCREEN,
} PokemonSideConditionKind;

typedef struct {
    PokemonSideConditionKind kind;
    uint16_t descriptor_id;
    uint8_t duration;
    uint8_t counter;
    uint16_t state_generation;
    uint16_t effect_order;
} PokemonSideConditionState;

typedef struct {
    uint16_t descriptor_id;
    PokemonSlotConditionKind semantic_kind;
    uint8_t duration;
    uint8_t position;
    uint16_t state_generation;
    uint16_t effect_order;
    PokemonEntityRef source;
    PokemonSourceEffectRef source_effect;
    union {
        struct {
            uint16_t move_id;
            uint16_t fixed_damage;
        } delayed_move;
    } payload;
} PokemonSlotConditionState;

typedef enum {
    POKEMON_WEATHER_NONE = 0,
    POKEMON_WEATHER_SANDSTORM,
    POKEMON_WEATHER_HAIL,
    POKEMON_WEATHER_RAIN,
    POKEMON_WEATHER_SUN,
} PokemonWeatherKind;

typedef struct {
    PokemonWeatherKind kind;
    uint16_t descriptor_id;
    uint8_t duration;
    uint8_t source_side;
    uint8_t source_slot;
    uint16_t state_generation;
    uint16_t effect_order;
} PokemonWeatherState;

typedef struct {
    PokemonDrawLabel label;
    PokemonEventId context_event_id;
    uint32_t semantic_sequence;
    uint16_t seed_before[4];
    uint16_t seed_after[4];
    uint32_t upper_bound;
    uint32_t lower_bound;
    uint32_t raw;
    uint32_t result;
} PokemonDraw;

typedef struct {
    PokemonEntityRef source;
    uint16_t move_id;
    uint16_t damage;
    uint8_t damage_was_number;
    uint8_t this_turn;
    uint8_t present;
} PokemonAttackRecord;

typedef enum {
    POKEMON_STALENESS_NONE = 0,
    POKEMON_STALENESS_INTERNAL,
    POKEMON_STALENESS_EXTERNAL,
} PokemonStaleness;

typedef struct {
    uint16_t hp;
    uint16_t cached_speed;
    /* Current non-HP stored stats in PokemonSet.stats[1..5] order. */
    uint16_t stored_stats[5];
    /* Current battle-time identity; PokemonSet.species_id remains the
     * immutable submitted/base identity and switch-reset source. */
    uint16_t species_id;
    uint8_t effective_types[2];
    uint8_t effective_type_count;
    /* Operative move-slot state. PokemonSet.move_ids is immutable submitted
     * input; battle semantics read these current identities instead.  The
     * base product is the switch-reset source and may diverge from the
     * submitted set for persistent replacement effects such as Sketch. */
    uint16_t move_ids[POKEMON_MOVE_CAPACITY];
    uint8_t pp[POKEMON_MOVE_CAPACITY];
    uint8_t max_pp[POKEMON_MOVE_CAPACITY];
    uint16_t base_move_ids[POKEMON_MOVE_CAPACITY];
    uint8_t base_pp[POKEMON_MOVE_CAPACITY];
    uint8_t base_max_pp[POKEMON_MOVE_CAPACITY];
    uint8_t pp_ups[POKEMON_MOVE_CAPACITY];
    uint8_t temporary_move_slots;
    uint8_t transformed;
    uint8_t fainted;
    uint8_t faint_queued;
    PokemonStatusState status;
    int8_t boosts[POKEMON_STAT_COUNT];
    PokemonVolatileState volatiles[POKEMON_VOLATILE_CAPACITY];
    uint8_t volatile_count;
    uint16_t ability_id;
    uint16_t item_id;
    uint16_t ability_generation;
    uint16_t item_generation;
    uint16_t ability_effect_order;
    uint16_t item_effect_order;
    uint16_t last_item_id;
    PokemonStaleness staleness;
    PokemonStaleness pending_staleness;
    PokemonStaleness volatile_staleness;
    uint32_t active_turns;
    /* Selected runMove-style actions since switch-in. Called moves do not
     * increment this counter; it is intentionally distinct from turns. */
    uint32_t active_move_actions;
    uint8_t used_item_this_turn;
    uint8_t ate_berry;
    uint8_t item_knocked_off;
    uint8_t ability_ending;
    uint32_t boolean_states;
    /* `last_move_id` is the last selected move (`moveUsed` in Showdown), not
     * the most recent called move.  Singles needs one retained attackedBy
     * record because only one opposing source can remain active. */
    uint16_t last_move_id;
    PokemonLastUsedMove last_move_used;
    PokemonAttackRecord last_attacked_by;
    PokemonPersonalMoveProfile personal_move_profile;
    PokemonPersonalMoveProfile base_personal_move_profile;
} PokemonMutable;

typedef struct {
    PokemonSet sets[POKEMON_TEAM_CAPACITY];
    PokemonMutable state[POKEMON_TEAM_CAPACITY];
    /* Showdown swaps Side.pokemon entries on every successful switch. Native
     * set/state storage stays at immutable team slots; this permutation maps
     * current party position to that stable slot. Position zero is the active
     * Pokemon in singles. */
    uint8_t party_order[POKEMON_TEAM_CAPACITY];
    uint8_t active;
    PokemonSideConditionState conditions[POKEMON_SIDE_CONDITION_CAPACITY];
    uint8_t condition_count;
    PokemonSlotConditionState slot_conditions[POKEMON_ACTIVE_POSITION_CAPACITY]
        [POKEMON_SLOT_CONDITION_CAPACITY];
    uint8_t slot_condition_count[POKEMON_ACTIVE_POSITION_CAPACITY];
} PokemonSide;

typedef struct {
    PokemonWeatherState weather;
} PokemonField;

typedef enum {
    POKEMON_CONDITION_SCOPE_STATUS = 1,
    POKEMON_CONDITION_SCOPE_VOLATILE,
    POKEMON_CONDITION_SCOPE_SIDE,
    POKEMON_CONDITION_SCOPE_FIELD,
    POKEMON_CONDITION_SCOPE_SLOT,
} PokemonConditionScope;

typedef enum {
    POKEMON_CONDITION_ADD = 1,
    POKEMON_CONDITION_UPDATE,
    POKEMON_CONDITION_RESTART,
    POKEMON_CONDITION_REMOVE,
} PokemonConditionOperation;

typedef enum {
    POKEMON_CONDITION_REASON_MOVE = 1,
    POKEMON_CONDITION_REASON_RESIDUAL,
    POKEMON_CONDITION_REASON_EXPIRY,
    POKEMON_CONDITION_REASON_SWITCH,
    POKEMON_CONDITION_REASON_HANDLER,
} PokemonConditionReason;

typedef enum {
    POKEMON_CONDITION_VALUE_NONE = 0,
    POKEMON_CONDITION_VALUE_DURATION,
    POKEMON_CONDITION_VALUE_STAGE,
    POKEMON_CONDITION_VALUE_COUNTER,
} PokemonConditionValueKind;

typedef struct {
    uint32_t semantic_sequence;
    PokemonConditionScope scope;
    PokemonConditionOperation operation;
    PokemonConditionReason reason;
    PokemonConditionValueKind value_kind;
    uint8_t side;
    uint8_t slot;
    uint16_t condition_id;
    /* Resolved descriptor identity when multiple descriptors intentionally
     * share one kernel semantic kind (for example Counter/Mirror Coat). */
    uint16_t descriptor_id;
    uint8_t before_value;
    uint8_t after_value;
    uint8_t has_duration_before;
    uint8_t has_duration_after;
    uint8_t duration_before;
    uint8_t duration_after;
    uint8_t has_counter_before;
    uint8_t has_counter_after;
    uint8_t counter_before;
    uint8_t counter_after;
    uint8_t has_stage_before;
    uint8_t has_stage_after;
    uint8_t stage_before;
    uint8_t stage_after;
} PokemonConditionTrace;

typedef enum {
    POKEMON_EFFECT_APPLIED = 1,
    POKEMON_EFFECT_FAILED,
} PokemonEffectResult;

typedef struct {
    uint32_t semantic_sequence;
    PokemonEffectKind kind;
    PokemonEffectPhase phase;
    PokemonEffectTarget target;
    PokemonEffectResult result;
    uint8_t source_side;
    uint8_t source_slot;
    uint8_t target_side;
    uint8_t target_slot;
    uint16_t move_id;
    uint16_t argument;
    int8_t amount;
    uint16_t value;
    uint16_t damage_basis;
    uint16_t requested;
    uint8_t numerator;
    uint8_t denominator;
    uint8_t damage_target_side;
    uint8_t damage_target_slot;
    uint8_t prevention;
    uint8_t critical;
    uint8_t damage_roll;
    uint8_t minimum;
    uint8_t cap_numerator;
    uint8_t cap_denominator;
    uint16_t cap_value;
    int16_t before;
    int16_t after;
} PokemonEffectTrace;

typedef enum {
    POKEMON_HIT_PLAN = 1,
    POKEMON_HIT_CONNECTED,
    POKEMON_HIT_RESULT,
    POKEMON_HIT_SUBSTITUTE,
} PokemonHitTraceKind;

typedef enum {
    POKEMON_HIT_STOP_COMPLETED = 1,
    POKEMON_HIT_STOP_TARGET_FAINTED,
    POKEMON_HIT_STOP_SOURCE_FAINTED,
    POKEMON_HIT_STOP_ACCURACY,
    POKEMON_HIT_STOP_SOURCE_ASLEEP,
} PokemonHitStopReason;

typedef struct {
    uint32_t semantic_sequence;
    PokemonHitTraceKind kind;
    uint16_t move_id;
    uint8_t source_side;
    uint8_t source_slot;
    uint8_t target_side;
    uint8_t target_slot;
    uint8_t hit_index;
    uint8_t requested_hits;
    uint8_t dynamic_plan;
    uint8_t critical;
    uint8_t damage_roll;
    uint16_t damage;
    uint16_t calculated_damage;
    uint8_t substitute_broke;
    uint8_t after_sub_damage_dispatched;
    uint16_t total_damage;
    uint16_t hp_before;
    uint16_t hp_after;
    uint16_t source_hp_after;
    uint8_t actual_hits;
    PokemonHitStopReason stop_reason;
} PokemonHitTrace;

typedef struct {
    uint32_t semantic_sequence;
    PokemonDamageFormula formula;
    uint16_t move_id;
    uint8_t source_side;
    uint8_t source_slot;
    uint8_t target_side;
    uint8_t target_slot;
    uint16_t hp;
    uint16_t max_hp;
    uint8_t ratio;
    uint8_t bracket;
    uint16_t resolved_value;
} PokemonDamageFormulaTrace;

typedef enum {
    POKEMON_RESIDUAL_WEATHER = 1,
    POKEMON_RESIDUAL_STATUS,
    POKEMON_RESIDUAL_VOLATILE,
    POKEMON_RESIDUAL_SIDE_CONDITION,
    POKEMON_RESIDUAL_OWNER_EVENT,
    POKEMON_RESIDUAL_SLOT_CONDITION,
} PokemonResidualKind;

typedef struct {
    PokemonResidualKind kind;
    uint8_t order;
    uint8_t has_order;
    uint8_t sub_order;
    int8_t priority;
    uint8_t side;
    uint8_t slot;
    uint16_t condition_id;
    uint16_t descriptor_id;
    uint16_t state_generation;
    uint16_t speed;
    uint16_t effect_order;
    PokemonHandlerRef handler;
    uint32_t semantic_sequence;
    uint8_t duration_before;
    uint8_t duration_after;
    uint8_t counter_before;
    uint8_t counter_after;
    /* True only when a weather residual reached its nested per-Pokemon
     * Weather event. Global suppression (for example Cloud Nine) leaves the
     * outer FieldResidual work observable without dispatching that event. */
    uint8_t weather_event_dispatched;
    /* Resolved nested EachEvent order, retained for structural tracing even
     * when immunity suppresses an individual damage event. */
    uint8_t weather_order[POKEMON_SIDES];
} PokemonResidualWork;

typedef enum {
    POKEMON_ACTION_MOVE = 1,
    POKEMON_ACTION_SWITCH,
    POKEMON_ACTION_RUN_SWITCH,
    POKEMON_ACTION_BEFORE_TURN_MOVE,
} PokemonActionKind;

typedef enum {
    POKEMON_MOVE_CHOICE_SELECTED_SLOT = 1,
    POKEMON_MOVE_CHOICE_FORCED,
    POKEMON_MOVE_CHOICE_FALLBACK,
} PokemonMoveChoiceKind;

typedef struct {
    PokemonActionKind kind;
    uint8_t side;
    uint8_t slot;
    /* Identity chosen during normalization.  Execution may later derive a
     * different move through OverrideAction, but queue priority continues to
     * belong to this selected move. */
    uint16_t selected_move_id;
    PokemonMoveChoiceKind move_choice_kind;
    int16_t order;
    int8_t priority;
    uint16_t speed;
    PokemonMoveTarget target_mode;
    PokemonResolvedTarget resolved_target;
    int8_t target_loc;
    PokemonSwitchCause switch_cause;
    PokemonSwitchTransferPolicy switch_transfer;
    uint8_t skip_before_switch_out;
} PokemonAction;

typedef struct {
    PokemonAction values[POKEMON_QUEUE_CAPACITY];
    uint8_t count;
} PokemonQueue;

typedef struct {
    PokemonEntityRef target;
    PokemonEntityRef source;
    PokemonSourceEffectRef source_effect;
} PokemonPendingFaint;

typedef struct {
    uint8_t active;
    PokemonEntityRef target;
} PokemonPendingDrag;

typedef enum {
    POKEMON_PHASE_AWAITING_CHOICES = 1,
    POKEMON_PHASE_ACTION_QUEUE,
    POKEMON_PHASE_EXECUTING_ACTION,
    POKEMON_PHASE_RESIDUAL,
    POKEMON_PHASE_FAINT_DRAIN,
    POKEMON_PHASE_FORCED_REPLACEMENT,
    POKEMON_PHASE_TERMINAL,
    POKEMON_PHASE_MOVE_SWITCH,
} PokemonPhase;

typedef enum {
    POKEMON_TURN_NOT_SUSPENDED = 0,
    POKEMON_TURN_SUSPENDED_BEFORE_RESIDUAL,
    POKEMON_TURN_SUSPENDED_AFTER_RESIDUAL,
} PokemonTurnSuspension;

typedef struct {
    uint8_t active;
    uint8_t side;
    uint8_t outgoing_slot;
    uint16_t source_move_id;
    PokemonSwitchTransferPolicy transfer;
    uint8_t skip_before_switch_out;
} PokemonPendingMoveSwitch;

typedef struct {
    const PokemonGeneration *generation;
    const PokemonData *data;
    PokemonFormat format;
    PokemonFormatPolicy policy;
    uint8_t team_sizes[POKEMON_SIDES];
    PokemonSide sides[POKEMON_SIDES];
    PokemonField field;
    PokemonQueue queue;
    /* Immutable snapshot of the most recently constructed, sorted queue. */
    PokemonQueue last_queue;
    PokemonPendingDrag pending_drag;
    PokemonPendingMoveSwitch pending_move_switch;
    PokemonRequest request;
    PokemonEvent events[POKEMON_EVENT_CAPACITY];
    PokemonDraw draws[POKEMON_DRAW_CAPACITY];
    PokemonHandlerInvocation handlers[POKEMON_HANDLER_CAPACITY];
    PokemonImmunityDecision immunities[POKEMON_IMMUNITY_CAPACITY];
    PokemonModifierInvocation modifiers[POKEMON_MODIFIER_CAPACITY];
    PokemonRelayResult relay_results[POKEMON_RELAY_RESULT_CAPACITY];
    PokemonDamageStageTrace damage_stages[POKEMON_DAMAGE_STAGE_CAPACITY];
    PokemonEffectTrace effect_traces[POKEMON_EFFECT_TRACE_CAPACITY];
    PokemonHitTrace hit_traces[POKEMON_HIT_TRACE_CAPACITY];
    PokemonDamageFormulaTrace damage_formula_traces[
        POKEMON_DAMAGE_FORMULA_TRACE_CAPACITY];
    PokemonConditionTrace condition_traces[POKEMON_CONDITION_TRACE_CAPACITY];
    PokemonResidualWork residuals[POKEMON_RESIDUAL_CAPACITY];
    PokemonPendingFaint faint_queue[POKEMON_FAINT_QUEUE_CAPACITY];
    PokemonEventFrame event_frames[POKEMON_EVENT_FRAME_CAPACITY];
    PokemonActiveMoveFrame move_frames[POKEMON_MOVE_FRAME_CAPACITY];
    PokemonMoveInvocationTrace move_invocations[
        POKEMON_MOVE_INVOCATION_TRACE_CAPACITY];
    uint16_t seed[4];
    uint32_t turn;
    uint32_t semantic_sequence;
    uint32_t next_move_invocation_id;
    uint16_t next_holder_effect_order;
    uint8_t shared_turn_speed_active;
    uint8_t initial_setup_complete;
    uint8_t event_count;
    uint8_t draw_count;
    uint8_t handler_count;
    uint8_t immunity_count;
    uint8_t modifier_count;
    uint8_t relay_result_count;
    uint8_t damage_stage_count;
    uint8_t effect_trace_count;
    uint8_t hit_trace_count;
    uint8_t damage_formula_trace_count;
    uint8_t condition_trace_count;
    uint8_t residual_count;
    uint8_t residual_index;
    uint8_t residual_pending;
    uint8_t faint_count;
    uint8_t event_depth;
    uint8_t move_frame_depth;
    uint8_t move_invocation_count;
    uint8_t terminal;
    int8_t winner;
    uint8_t turn_suspended; /* PokemonTurnSuspension */
    PokemonPhase phase;
} PokemonBattle;

typedef struct {
    uint8_t team_sizes[POKEMON_SIDES];
    PokemonSide sides[POKEMON_SIDES];
    PokemonField field;
    PokemonQueue last_queue;
    PokemonRequest request;
    PokemonEvent events[POKEMON_EVENT_CAPACITY];
    PokemonDraw draws[POKEMON_DRAW_CAPACITY];
    PokemonHandlerInvocation handlers[POKEMON_HANDLER_CAPACITY];
    PokemonImmunityDecision immunities[POKEMON_IMMUNITY_CAPACITY];
    PokemonModifierInvocation modifiers[POKEMON_MODIFIER_CAPACITY];
    PokemonRelayResult relay_results[POKEMON_RELAY_RESULT_CAPACITY];
    PokemonDamageStageTrace damage_stages[POKEMON_DAMAGE_STAGE_CAPACITY];
    PokemonEffectTrace effect_traces[POKEMON_EFFECT_TRACE_CAPACITY];
    PokemonHitTrace hit_traces[POKEMON_HIT_TRACE_CAPACITY];
    PokemonDamageFormulaTrace damage_formula_traces[
        POKEMON_DAMAGE_FORMULA_TRACE_CAPACITY];
    PokemonConditionTrace condition_traces[POKEMON_CONDITION_TRACE_CAPACITY];
    PokemonResidualWork residuals[POKEMON_RESIDUAL_CAPACITY];
    uint16_t seed[4];
    uint32_t turn;
    uint32_t semantic_sequence;
    uint8_t event_count;
    uint8_t draw_count;
    uint8_t handler_count;
    uint8_t immunity_count;
    uint8_t modifier_count;
    uint8_t relay_result_count;
    uint8_t damage_stage_count;
    uint8_t effect_trace_count;
    uint8_t hit_trace_count;
    uint8_t damage_formula_trace_count;
    uint8_t condition_trace_count;
    uint8_t residual_count;
    uint8_t residual_index;
    uint8_t residual_pending;
    uint8_t terminal;
    int8_t winner;
    PokemonPhase phase;
} PokemonBattleView;

int pokemon_battle_init(PokemonBattle *battle, const PokemonBattleInit *init);
int pokemon_reduce_move_choices(
    const PokemonMoveChoiceSlot slots[POKEMON_MOVE_CAPACITY],
    uint8_t slot_count, uint16_t hard_lock_move_id,
    uint16_t fallback_move_id,
    const PokemonMoveRestriction *restrictions, size_t restriction_count,
    PokemonMoveChoiceSet *result
);
int pokemon_reduce_switch_choices(
    uint8_t candidate_mask, PokemonSwitchChoiceMode mode,
    const PokemonSwitchRestriction *restrictions, size_t restriction_count,
    uint8_t *legal_mask
);
int pokemon_append_switch_restriction(
    PokemonSwitchRestrictionBuffer *buffer,
    PokemonSwitchRestriction restriction
);
int pokemon_make_switch_choice_request(
    uint8_t candidate_mask, PokemonSwitchChoiceMode mode,
    const PokemonSwitchRestriction *restrictions, size_t restriction_count,
    PokemonTrapDisclosure disclosure, PokemonSwitchChoiceRequest *request
);
int pokemon_attempt_choice(
    PokemonChoiceAttemptState *state, PokemonChoice choice,
    PokemonChoiceAttemptOutcome *outcome
);
int pokemon_move_choice_set_check_invariants(const PokemonMoveChoiceSet *set);
int pokemon_validate_choice_control_policies(
    const PokemonChoiceControlPolicy *policies, size_t count
);
int pokemon_prepare_choice_control_start(
    const PokemonChoiceControlPolicy *policy, uint16_t last_move_id,
    PokemonMoveSlotState last_move_slot_state,
    uint8_t last_move_encore_eligible,
    uint8_t target_will_move, uint8_t sampled_duration,
    PokemonChoiceControlStart *start
);
int pokemon_apply_choice_action_stage(
    const PokemonChoiceControlPolicy *policies, size_t policy_count,
    const PokemonVolatileState *volatiles, size_t volatile_count,
    const PokemonMoveChoiceSlot slots[POKEMON_MOVE_CAPACITY],
    uint16_t selected_move_id, PokemonChoiceActionStage stage,
    PokemonChoiceActionDecision *decision
);
int pokemon_calculate_damage(
    PokemonBattle *battle, const PokemonDamageRequest *request,
    PokemonCalculatedDamage *calculated
);
int pokemon_apply_direct_damage(
    PokemonBattle *battle, const PokemonDirectDamageRequest *request,
    uint16_t *applied
);
int pokemon_set_status(
    PokemonBattle *battle, PokemonEntityRef target, PokemonStatus proposed,
    PokemonEntityRef source, PokemonSourceEffectRef source_effect,
    uint8_t emit_immunity, uint8_t *applied
);
int pokemon_set_status_with_policy(
    PokemonBattle *battle, PokemonEntityRef target, PokemonStatus proposed,
    PokemonEntityRef source, PokemonSourceEffectRef source_effect,
    PokemonStatusSetPolicy policy, uint8_t emit_immunity, uint8_t *applied
);
int pokemon_try_add_or_restart_volatile(
    PokemonBattle *battle, PokemonEntityRef target, PokemonEntityRef source,
    PokemonSourceEffectRef source_effect, PokemonVolatileKind kind,
    PokemonConditionReason reason, PokemonEffectResult *effect_result
);
int pokemon_update_status_abilities(PokemonBattle *battle);
int pokemon_ability_blocks_sleep_volatile(
    const PokemonData *data, uint16_t ability_id, uint8_t *blocked
);
int pokemon_battle_step(
    PokemonBattle *battle,
    const PokemonChoice choices[POKEMON_SIDES]
);
PokemonRequest pokemon_battle_request(const PokemonBattle *battle);
void pokemon_battle_view(const PokemonBattle *battle, PokemonBattleView *view);
int pokemon_battle_check_invariants(const PokemonBattle *battle);
int pokemon_compare_handler_refs(
    const PokemonHandlerRef *left, const PokemonHandlerRef *right
);
void pokemon_order_handler_refs(PokemonHandlerRef *handlers, size_t count);
int pokemon_run_event(
    PokemonBattle *battle, const PokemonEventInput *input,
    PokemonEventFrame *result
);

#ifdef __cplusplus
}
#endif
