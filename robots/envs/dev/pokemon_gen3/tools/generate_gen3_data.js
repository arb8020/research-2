#!/usr/bin/env node
'use strict';

const path = require('path');

const showdownDir = process.argv[2];
const output = process.argv[3];
if (!showdownDir || !['header', 'ids'].includes(output)) {
  throw new Error(
    'usage: generate_gen3_data.js POKEMON_SHOWDOWN_DIR header|ids'
  );
}

const {Dex} = require(path.resolve(showdownDir));
const dex = Dex.forGen(3);
const TYPE_NAMES = [
  'Bug', 'Dark', 'Dragon', 'Electric', 'Fighting', 'Fire', 'Flying',
  'Ghost', 'Grass', 'Ground', 'Ice', 'Normal', 'Poison', 'Psychic',
  'Rock', 'Steel', 'Water',
];
const TYPE_IDS = new Map(TYPE_NAMES.map((name, index) => [name, index]));
const MOVE_FLAGS = [
  'bite', 'bullet', 'charge', 'contact', 'dance', 'defrost', 'distance',
  'gravity', 'heal', 'mirror', 'nonsky', 'powder', 'protect', 'pulse',
  'punch', 'recharge', 'reflectable', 'snatch', 'sound',
];
const MOVE_TARGETS = [
  'adjacentAlly', 'all', 'allAdjacent', 'allAdjacentFoes', 'allySide',
  'allyTeam', 'any', 'foeSide', 'normal', 'randomNormal', 'scripted', 'self',
];
const MOVE_TARGET_IDS = new Map(MOVE_TARGETS.map((name, index) => [name, index]));
const STATUS_IDS = new Map([
  ['brn', 'GEN3_PROGRAM_STATUS_BURN'],
  ['frz', 'GEN3_PROGRAM_STATUS_FREEZE'],
  ['par', 'GEN3_PROGRAM_STATUS_PARALYSIS'],
  ['psn', 'GEN3_PROGRAM_STATUS_POISON'],
  ['slp', 'GEN3_PROGRAM_STATUS_SLEEP'],
  ['tox', 'GEN3_PROGRAM_STATUS_TOXIC'],
]);
const BOOST_IDS = new Map([
  ['atk', 'GEN3_PROGRAM_STAT_ATTACK'],
  ['def', 'GEN3_PROGRAM_STAT_DEFENSE'],
  ['spa', 'GEN3_PROGRAM_STAT_SPECIAL_ATTACK'],
  ['spd', 'GEN3_PROGRAM_STAT_SPECIAL_DEFENSE'],
  ['spe', 'GEN3_PROGRAM_STAT_SPEED'],
  ['accuracy', 'GEN3_PROGRAM_STAT_ACCURACY'],
  ['evasion', 'GEN3_PROGRAM_STAT_EVASION'],
]);

/*
 * Reviewed boundary between Showdown's executable TypeScript effects and the
 * native interpreter. Scheduling metadata is read from the fully-resolved
 * Gen 3 Dex below; callback denotations remain explicit native handler IDs.
 * Keep the expected callback set narrow so an upstream behavior change fails
 * generation instead of silently producing an incomplete descriptor table.
 */
const EFFECT_MANIFEST = [
  {
    kind: 'side_condition', id: 'GEN3_CONDITION_SPIKES', name: 'Spikes',
    source: () => dex.moves.get('spikes').condition,
    callbacks: [
      ['SideStart', 'SPIKES_START'],
      ['SideRestart', 'SPIKES_RESTART'],
      ['EntryHazard', 'SPIKES_ENTRY'],
    ],
    absent: ['SwitchIn'],
    capabilities: [],
  },
  {
    kind: 'item', id: 'GEN3_ITEM_LEFTOVERS', name: 'Leftovers',
    source: () => dex.items.get('leftovers'),
    callbacks: [['Residual', 'LEFTOVERS_RESIDUAL']],
    absent: ['Update'],
    capabilities: [],
  },
  {
    kind: 'ability', id: 'GEN3_ABILITY_NATURAL_CURE', name: 'Natural Cure',
    source: () => dex.abilities.get('naturalcure'),
    callbacks: [['SwitchOut', 'NATURAL_CURE_SWITCH_OUT']],
    absent: ['CheckShow'],
    capabilities: [],
  },
  {
    kind: 'ability', id: 'GEN3_ABILITY_LEVITATE', name: 'Levitate',
    source: () => dex.abilities.get('levitate'),
    callbacks: [], absent: [],
    capabilities: ['AIRBORNE', 'GROUND_IMMUNE'],
  },
  {
    kind: 'ability', id: 'GEN3_ABILITY_STURDY', name: 'Sturdy',
    source: () => dex.abilities.get('sturdy'),
    callbacks: [['TryHit', 'STURDY_TRY_HIT']],
    absent: ['Damage'],
    capabilities: [],
  },
  {
    kind: 'ability', id: 'GEN3_ABILITY_TORRENT', name: 'Torrent',
    source: () => dex.abilities.get('torrent'),
    callbacks: [['BasePower', 'TORRENT_BASE_POWER']],
    absent: ['ModifyAtk', 'ModifySpA'],
    capabilities: [],
  },
];

const EFFECT_KINDS = {
  side_condition: 'GEN3_EFFECT_SIDE_CONDITION',
  ability: 'GEN3_EFFECT_ABILITY',
  item: 'GEN3_EFFECT_ITEM',
};
const DEFAULT_SUB_ORDERS = {side_condition: 4, ability: 7, item: 8};
const DEFAULT_HANDLER_ORDER = 32767;

function callbackNames(effect) {
  return Object.keys(effect)
    .filter(key => /^on[A-Z]/.test(key))
    .filter(key => !/(?:Order|Priority|SubOrder)$/.test(key))
    .filter(key => effect[key] !== undefined)
    .map(key => key.slice(2))
    .sort();
}

function resolvedEffects() {
  return EFFECT_MANIFEST.map(entry => {
    const source = entry.source();
    const expected = entry.callbacks.map(([event]) => event).sort();
    const actual = callbackNames(source);
    if (JSON.stringify(actual) !== JSON.stringify(expected)) {
      throw new Error(
        `${entry.name} callback drift: expected ${expected.join(', ') || '(none)'}, ` +
        `got ${actual.join(', ') || '(none)'}`
      );
    }
    for (const event of entry.absent) {
      if (source[`on${event}`] !== undefined) {
        throw new Error(`${entry.name} unexpectedly defines on${event}`);
      }
    }
    return {...entry, source};
  });
}

function legal(effect) {
  return effect.exists && effect.gen <= 3 && effect.num > 0 &&
    effect.isNonstandard !== 'CAP' && effect.isNonstandard !== 'Custom' &&
    effect.isNonstandard !== 'Future';
}

function cString(value) {
  return JSON.stringify(value).replace(/\\u2028|\\u2029/g, ' ');
}

function cName(value) {
  return value.toUpperCase().replace(/[^A-Z0-9]+/g, '_').replace(/^_|_$/g, '');
}

function eventCName(value) {
  return cName(value.replace(/([a-z0-9])([A-Z])/g, '$1_$2'));
}

function uniqueSpecies() {
  const species = dex.species.all().filter(legal);
  const base = species.filter(value => !value.forme);
  const formes = species.filter(value => value.forme)
    .sort((left, right) => left.id.localeCompare(right.id));
  const result = base.map(value => [value, value.num]);
  let next = Math.max(...base.map(value => value.num)) + 1;
  for (const value of formes) result.push([value, next++]);
  return result.sort((left, right) => left[1] - right[1]);
}

const species = uniqueSpecies();
const speciesIDs = Object.fromEntries(species.map(([value, id]) => [value.id, id]));

if (output === 'ids') {
  process.stdout.write(`${JSON.stringify({
    schema: 1,
    showdown_gen: 3,
    species: speciesIDs,
  }, null, 2)}\n`);
  process.exit(0);
}

function typeID(name) {
  if (name === '???') return 255;
  const result = TYPE_IDS.get(name);
  if (result === undefined) throw new Error(`unexpected Gen 3 type: ${name}`);
  return result;
}

function flags(move) {
  let result = 0;
  MOVE_FLAGS.forEach((name, index) => {
    if (move.flags[name]) result |= 1 << index;
  });
  return result;
}

function accuracy(move) {
  return move.accuracy === true ? 0 : move.accuracy;
}

function category(move) {
  return {Status: 0, Physical: 1, Special: 2}[move.category];
}

function target(move) {
  const result = MOVE_TARGET_IDS.get(move.target);
  if (result === undefined) throw new Error(`unexpected move target: ${move.target}`);
  return result;
}

function ignoreImmunity(move) {
  if (typeof move.ignoreImmunity !== 'boolean') {
    throw new Error(`unexpected Gen 3 ignoreImmunity shape for ${move.id}`);
  }
  return move.ignoreImmunity ? 1 : 0;
}

function critRatio(move) {
  const result = move.critRatio ?? 1;
  if (!Number.isInteger(result) || result < 1 || result > 255) {
    throw new Error(`unexpected critical-hit ratio for ${move.id}: ${result}`);
  }
  return result;
}

function programOperations(effect, defaultTarget) {
  const operations = [];
  if (effect.status) {
    const status = STATUS_IDS.get(effect.status);
    if (!status) throw new Error(`unexpected move status: ${effect.status}`);
    operations.push({opcode: 'STATUS', target: defaultTarget, argument: status, amount: 0});
  }
  for (const [stat, amount] of Object.entries(effect.boosts || {})) {
    const argument = BOOST_IDS.get(stat);
    if (!argument) throw new Error(`unexpected boost stat: ${stat}`);
    operations.push({opcode: 'BOOST', target: defaultTarget, argument, amount});
  }
  for (const [stat, amount] of Object.entries(effect.self?.boosts || {})) {
    const argument = BOOST_IDS.get(stat);
    if (!argument) throw new Error(`unexpected self boost stat: ${stat}`);
    operations.push({opcode: 'BOOST', target: 'SELF', argument, amount});
  }
  return operations;
}

/*
 * A program is a probability bundle: all of its operations share one roll.
 * Unsupported executable semantics are retained as NATIVE_REQUIRED rather
 * than silently erased.  This is the reviewed boundary for the first
 * declarative family, not a claim that every move is data-only yet.
 */
function movePrograms(move) {
  const programs = [];
  const primaryEffect = {
    status: move.status,
    boosts: move.boosts,
    self: move.self,
  };
  const primaryOps = programOperations(
    primaryEffect, move.target === 'self' ? 'SELF' : 'TARGET'
  );
  const primaryUnsupported = Boolean(
    move.volatileStatus || move.sideCondition || move.weather ||
    move.pseudoWeather || move.heal || move.drain || move.recoil ||
    move.forceSwitch || move.selfSwitch || move.ohko || move.damage ||
    move.damageCallback || move.basePowerCallback || callbackNames(move).length ||
    (move.self && Object.keys(move.self).some(key => key !== 'boosts'))
  );
  if (primaryOps.length || primaryUnsupported) {
    programs.push({chance: 0, operations: primaryOps, nativeRequired: primaryUnsupported});
  }

  for (const secondary of move.secondaries || []) {
    const allowed = new Set(['chance', 'status', 'boosts', 'self']);
    const nativeRequired = Object.keys(secondary).some(key => !allowed.has(key)) ||
      Boolean(secondary.self &&
        Object.keys(secondary.self).some(key => key !== 'boosts'));
    programs.push({
      chance: secondary.chance ?? 100,
      operations: programOperations(secondary, 'TARGET'),
      nativeRequired,
    });
  }
  return programs;
}

/*
 * Admission to the ordinary native hit pipeline is deliberately closed-world.
 * These fields denote execution outside its type/accuracy/damage/program
 * algebra.  Keeping the classification in generated data means the runtime
 * never guesses from a move ID (and newly resolved Showdown semantics fail
 * closed until represented).
 */
function requiresNativeExecution(move) {
  return Boolean(
    callbackNames(move).length || move.beforeMoveCallback ||
    move.beforeTurnCallback || move.basePowerCallback || move.damageCallback ||
    move.priorityChargeCallback || move.callsMove || move.drain ||
    move.forceSwitch || move.forceSTAB || move.hasCrashDamage ||
    move.ignoreAbility || move.ignoreDefensive || move.ignoreNegativeOffensive ||
    move.ignoreOffensive || move.ignorePositiveDefensive || move.multiaccuracy ||
    move.multihit || move.nonGhostTarget || move.ohko ||
    move.overrideDefensivePokemon || move.overrideDefensiveStat ||
    move.overrideOffensivePokemon || move.overrideOffensiveStat ||
    move.pseudoWeather || move.recoil || move.selfSwitch || move.selfdestruct ||
    move.sideCondition || move.sleepUsable || move.slotCondition ||
    move.stallingMove || move.struggleRecoil || move.volatileStatus || move.weather
  );
}

function emit(line = '') {
  process.stdout.write(`${line}\n`);
}

emit('/* Generated by tools/generate_gen3_data.js from the pinned Showdown oracle. */');
emit('/* Do not edit by hand. */');
emit('#pragma once');
emit('#include <stdint.h>');
emit();
emit(`enum { GEN3_TYPE_COUNT = ${TYPE_NAMES.length} };`);
emit('typedef enum {');
TYPE_NAMES.forEach((name, index) => emit(`    GEN3_TYPE_${cName(name)} = ${index},`));
emit('    GEN3_TYPE_NONE = 255,');
emit('} Gen3Type;');
emit();
emit('typedef struct {');
emit('    uint16_t national_dex;');
emit('    uint8_t types[2];');
emit('    uint8_t type_count;');
emit('    uint8_t base_stats[6];');
emit('    uint16_t abilities[2];');
emit('    const char *name;');
emit('} Gen3SpeciesData;');
emit();
emit('typedef enum {');
MOVE_TARGETS.forEach((name, index) =>
  emit(`    GEN3_MOVE_TARGET_${eventCName(name)} = ${index},`));
emit(`    GEN3_MOVE_TARGET_COUNT = ${MOVE_TARGETS.length},`);
emit('} Gen3MoveTarget;');
emit();
emit('typedef enum {');
emit('    GEN3_PROGRAM_OP_STATUS = 0,');
emit('    GEN3_PROGRAM_OP_BOOST = 1,');
emit('} Gen3ProgramOpcode;');
emit();
emit('typedef enum {');
emit('    GEN3_PROGRAM_TARGET_TARGET = 0,');
emit('    GEN3_PROGRAM_TARGET_SELF = 1,');
emit('} Gen3ProgramTarget;');
emit();
emit('typedef enum {');
[...STATUS_IDS.values()].forEach((name, index) => emit(`    ${name} = ${index},`));
emit(`    GEN3_PROGRAM_STATUS_COUNT = ${STATUS_IDS.size},`);
emit('} Gen3ProgramStatus;');
emit();
emit('typedef enum {');
[...BOOST_IDS.values()].forEach((name, index) => emit(`    ${name} = ${index},`));
emit(`    GEN3_PROGRAM_STAT_COUNT = ${BOOST_IDS.size},`);
emit('} Gen3ProgramStat;');
emit();
emit('#define GEN3_MOVE_PROGRAM_NATIVE_REQUIRED (UINT8_C(1) << 0)');
emit('typedef struct {');
emit('    uint8_t opcode;');
emit('    uint8_t target;');
emit('    uint8_t argument; /* Gen3ProgramStatus or Gen3ProgramStat */');
emit('    int8_t amount; /* only used by BOOST */');
emit('} Gen3MoveProgramOp;');
emit();
emit('typedef struct {');
emit('    uint16_t first_op;');
emit('    uint8_t op_count;');
emit('    uint8_t chance; /* 0 means unconditional primary program */');
emit('    uint8_t flags;');
emit('} Gen3MoveProgram;');
emit();
emit('typedef struct {');
emit('    uint16_t id;');
emit('    uint16_t base_power;');
emit('    uint8_t type;');
emit('    uint8_t accuracy; /* 0 means always hits */');
emit('    uint8_t pp;');
emit('    int8_t priority;');
emit('    uint8_t category; /* 0 status, 1 physical, 2 special */');
emit('    uint8_t target;');
emit('    uint8_t ignore_immunity;');
emit('    uint8_t crit_ratio;');
emit('    uint16_t primary_program; /* 0 means none */');
emit('    uint16_t first_secondary_program;');
emit('    uint8_t secondary_program_count;');
emit('    uint8_t native_execution_required;');
emit('    uint32_t flags;');
emit('    const char *name;');
emit('} Gen3MoveData;');
emit();
MOVE_FLAGS.forEach((name, index) => {
  emit(`#define GEN3_MOVE_FLAG_${cName(name)} (UINT32_C(1) << ${index})`);
});
emit();
emit(`enum { GEN3_SPECIES_COUNT = ${species.length}, GEN3_SPECIES_MAX_ID = ${species.at(-1)[1]} };`);
emit('static const Gen3SpeciesData GEN3_SPECIES[GEN3_SPECIES_MAX_ID + 1] = {');
for (const [value, id] of species) {
  const types = value.types.map(typeID);
  const abilities = Object.entries(value.abilities)
    .filter(([slot]) => slot !== 'H' && slot !== 'S')
    .map(([, name]) => dex.abilities.get(name).num);
  while (types.length < 2) types.push(0);
  while (abilities.length < 2) abilities.push(0);
  const stats = ['hp', 'atk', 'def', 'spa', 'spd', 'spe']
    .map(name => value.baseStats[name]);
  emit(`    [${id}] = {${value.num}, {${types.join(', ')}}, ${value.types.length}, ` +
    `{${stats.join(', ')}}, {${abilities.slice(0, 2).join(', ')}}, ${cString(value.name)}},`);
}
emit('};');
emit();

const movesByNum = new Map();
for (const move of dex.moves.all().filter(legal)) {
  if (!movesByNum.has(move.num) || move.id === 'hiddenpower') movesByNum.set(move.num, move);
}
const moves = [...movesByNum.values()].sort((left, right) => left.num - right.num);
const programs = [{chance: 0, operations: [], nativeRequired: false}];
const moveProgramRefs = new Map();
for (const move of moves) {
  const resolved = movePrograms(move);
  const primary = resolved[0]?.chance === 0 ? resolved.shift() : null;
  const primaryProgram = primary ? programs.push(primary) - 1 : 0;
  const firstSecondaryProgram = resolved.length ? programs.length : 0;
  programs.push(...resolved);
  moveProgramRefs.set(move.num, {
    primaryProgram,
    firstSecondaryProgram,
    secondaryProgramCount: resolved.length,
  });
}
const programOps = [];
for (const program of programs) {
  program.firstOp = programOps.length;
  programOps.push(...program.operations);
}

/* Generator-time semantic assertions: resolved Gen 3 data, not move IDs at runtime. */
function assertGenerated(condition, message) {
  if (!condition) throw new Error(`generated move-program invariant failed: ${message}`);
}
const assertMove = id => ({
  move: dex.moves.get(id),
  refs: moveProgramRefs.get(dex.moves.get(id).num),
});
const primaryFor = id => programs[assertMove(id).refs.primaryProgram];
const secondariesFor = id => {
  const refs = assertMove(id).refs;
  return programs.slice(
    refs.firstSecondaryProgram,
    refs.firstSecondaryProgram + refs.secondaryProgramCount
  );
};
assertGenerated(primaryFor('toxic').operations.length === 1 &&
  primaryFor('toxic').operations[0].argument === 'GEN3_PROGRAM_STATUS_TOXIC',
  'Toxic is one primary toxic-status operation');
assertGenerated(primaryFor('calmmind').operations.length === 2 &&
  primaryFor('calmmind').operations.every(op => op.opcode === 'BOOST' && op.target === 'SELF'),
  'Calm Mind is one two-operation self-boost program');
assertGenerated(secondariesFor('icebeam').length === 1 &&
  secondariesFor('icebeam')[0].chance === 10 &&
  secondariesFor('icebeam')[0].operations[0].argument === 'GEN3_PROGRAM_STATUS_FREEZE',
  'Ice Beam has one 10% freeze bundle');
assertGenerated(secondariesFor('psychic').length === 1 &&
  secondariesFor('psychic')[0].operations[0].argument ===
    'GEN3_PROGRAM_STAT_SPECIAL_DEFENSE' &&
  secondariesFor('psychic')[0].operations[0].amount === -1,
  'Psychic has one 10% Special Defense drop bundle');
assertGenerated(assertMove('earthquake').refs.primaryProgram === 0 &&
  assertMove('earthquake').refs.secondaryProgramCount === 0,
  'Earthquake has no ordinary effect program');
assertGenerated(ignoreImmunity(assertMove('toxic').move) === 1,
  'Toxic ignores natural type immunity');
assertGenerated(ignoreImmunity(assertMove('earthquake').move) === 0,
  'Earthquake observes natural type immunity');
assertGenerated(critRatio(assertMove('surf').move) === 1,
  'ordinary moves use critical-hit ratio stage 1');
assertGenerated(critRatio(assertMove('slash').move) === 2,
  'high-critical-hit moves retain their resolved ratio stage');
assertGenerated(programs.length <= 65535, 'program IDs fit uint16_t');
assertGenerated(programOps.length <= 65535, 'operation offsets fit uint16_t');
assertGenerated(programs.every(program => program.operations.length <= 255),
  'program operation counts fit uint8_t');
emit(`enum { GEN3_MOVE_COUNT = ${moves.length}, GEN3_MOVE_MAX_ID = ${moves.at(-1).num} };`);
moves.forEach(value => emit(`#define GEN3_MOVE_${cName(value.name)} ${value.num}`));
emit('static const Gen3MoveData GEN3_MOVES[GEN3_MOVE_MAX_ID + 1] = {');
for (const move of moves) {
  const refs = moveProgramRefs.get(move.num);
  emit(`    [${move.num}] = {${move.num}, ${move.basePower}, ${typeID(move.type)}, ` +
    `${accuracy(move)}, ${move.pp}, ${move.priority}, ${category(move)}, ` +
    `${target(move)}, ${ignoreImmunity(move)}, ${critRatio(move)}, ` +
    `${refs.primaryProgram}, ${refs.firstSecondaryProgram}, ` +
    `${refs.secondaryProgramCount}, ${requiresNativeExecution(move) ? 1 : 0}, ` +
    `UINT32_C(${flags(move)}), ${cString(move.name)}},`);
}
emit('};');
emit();
emit(`enum { GEN3_MOVE_PROGRAM_COUNT = ${programs.length}, ` +
  `GEN3_MOVE_PROGRAM_OP_COUNT = ${programOps.length} };`);
emit('static const Gen3MoveProgram GEN3_MOVE_PROGRAMS[GEN3_MOVE_PROGRAM_COUNT] = {');
for (const program of programs) {
  const flags = program.nativeRequired ? 'GEN3_MOVE_PROGRAM_NATIVE_REQUIRED' : 'UINT8_C(0)';
  emit(`    {${program.firstOp}, ${program.operations.length}, ${program.chance}, ${flags}},`);
}
emit('};');
emit();
emit('static const Gen3MoveProgramOp GEN3_MOVE_PROGRAM_OPS[GEN3_MOVE_PROGRAM_OP_COUNT] = {');
for (const operation of programOps) {
  emit(`    {GEN3_PROGRAM_OP_${operation.opcode}, GEN3_PROGRAM_TARGET_${operation.target}, ` +
    `${operation.argument}, ${operation.amount}},`);
}
emit('};');
emit();

const abilities = dex.abilities.all().filter(legal).sort((a, b) => a.num - b.num);
const itemsByNum = new Map();
for (const item of dex.items.all().filter(legal)) {
  const current = itemsByNum.get(item.num);
  if (!current || (current.isNonstandard && !item.isNonstandard)) {
    itemsByNum.set(item.num, item);
  }
}
const items = [...itemsByNum.values()].sort((a, b) => a.num - b.num);
emit(`enum { GEN3_ABILITY_COUNT = ${abilities.length}, GEN3_ABILITY_MAX_ID = ${abilities.at(-1).num} };`);
abilities.forEach(value => emit(`#define GEN3_ABILITY_${cName(value.name)} ${value.num}`));
emit('static const char *const GEN3_ABILITY_NAMES[GEN3_ABILITY_MAX_ID + 1] = {');
abilities.forEach(value => emit(`    [${value.num}] = ${cString(value.name)},`));
emit('};');
emit();
emit(`enum { GEN3_ITEM_COUNT = ${items.length}, GEN3_ITEM_MAX_ID = ${items.at(-1).num} };`);
items.forEach(value => emit(`#define GEN3_ITEM_${cName(value.name)} ${value.num}`));
emit('static const char *const GEN3_ITEM_NAMES[GEN3_ITEM_MAX_ID + 1] = {');
items.forEach(value => emit(`    [${value.num}] = ${cString(value.name)},`));
emit('};');
emit();

const effects = resolvedEffects();
const handlers = effects.flatMap((effect, effectIndex) =>
  effect.callbacks.map(([event, nativeHandler]) => ({
    effectIndex, event, nativeHandler, source: effect.source,
    kind: effect.kind,
  }))
);
const eventNames = [...new Set(handlers.map(handler => handler.event))].sort();
const nativeHandlerNames = handlers.map(handler => handler.nativeHandler);

emit('/* Effect descriptors are generated from resolved Gen 3 Showdown data. */');
emit('/* Native handler IDs are the reviewed executable-semantics boundary. */');
emit('typedef enum {');
emit('    GEN3_EFFECT_MOVE = 0,');
emit('    GEN3_EFFECT_SIDE_CONDITION = 1,');
emit('    GEN3_EFFECT_ABILITY = 2,');
emit('    GEN3_EFFECT_ITEM = 3,');
emit('    GEN3_EFFECT_STATUS = 4,');
emit('} Gen3EffectKind;');
emit();
emit('typedef enum {');
eventNames.forEach((name, index) =>
  emit(`    GEN3_EFFECT_EVENT_${eventCName(name)} = ${index},`));
emit(`    GEN3_EFFECT_EVENT_COUNT = ${eventNames.length},`);
emit('} Gen3EffectEventId;');
emit();
emit('typedef enum {');
emit('    GEN3_NATIVE_HANDLER_NONE = 0,');
nativeHandlerNames.forEach((name, index) =>
  emit(`    GEN3_NATIVE_HANDLER_${name} = ${index + 1},`));
emit(`    GEN3_NATIVE_HANDLER_COUNT = ${nativeHandlerNames.length + 1},`);
emit('} Gen3NativeHandlerId;');
emit();
emit('#define GEN3_EFFECT_CAP_AIRBORNE (UINT32_C(1) << 0)');
emit('#define GEN3_EFFECT_CAP_GROUND_IMMUNE (UINT32_C(1) << 1)');
emit(`enum { GEN3_HANDLER_ORDER_DEFAULT = ${DEFAULT_HANDLER_ORDER} };`);
emit('enum { GEN3_CONDITION_SPIKES = 1 };');
emit();
emit('typedef struct {');
emit('    uint16_t effect_id;');
emit('    uint8_t kind;');
emit('    uint8_t handler_count;');
emit('    uint16_t first_handler;');
emit('    uint32_t capability_bits;');
emit('    const char *name;');
emit('} Gen3EffectDescriptor;');
emit();
emit('typedef struct {');
emit('    uint16_t event_id;');
emit('    uint16_t native_handler_id;');
emit('    int16_t order;');
emit('    int16_t priority;');
emit('    int16_t sub_order;');
emit('} Gen3HandlerDescriptor;');
emit();
emit(`enum { GEN3_EFFECT_DESCRIPTOR_COUNT = ${effects.length}, ` +
  `GEN3_HANDLER_DESCRIPTOR_COUNT = ${handlers.length} };`);
emit('static const Gen3EffectDescriptor GEN3_EFFECT_DESCRIPTORS[GEN3_EFFECT_DESCRIPTOR_COUNT] = {');
let firstHandler = 0;
for (const effect of effects) {
  const capabilities = effect.capabilities.length ?
    effect.capabilities.map(name => `GEN3_EFFECT_CAP_${name}`).join(' | ') :
    'UINT32_C(0)';
  emit(`    {${effect.id}, ${EFFECT_KINDS[effect.kind]}, ${effect.callbacks.length}, ` +
    `${firstHandler}, ${capabilities}, ${cString(effect.name)}},`);
  firstHandler += effect.callbacks.length;
}
emit('};');
emit();
emit('static const Gen3HandlerDescriptor GEN3_HANDLER_DESCRIPTORS[GEN3_HANDLER_DESCRIPTOR_COUNT] = {');
for (const handler of handlers) {
  const prefix = `on${handler.event}`;
  const order = handler.source[`${prefix}Order`] ?? DEFAULT_HANDLER_ORDER;
  const priority = handler.source[`${prefix}Priority`] ?? 0;
  const subOrder = handler.source[`${prefix}SubOrder`] ??
    DEFAULT_SUB_ORDERS[handler.kind];
  emit(`    {GEN3_EFFECT_EVENT_${eventCName(handler.event)}, ` +
    `GEN3_NATIVE_HANDLER_${handler.nativeHandler}, ${order}, ${priority}, ${subOrder}},`);
}
emit('};');
emit();

emit('/* Values are damage multipliers in halves: 0, 1, 2, or 4. */');
emit('static const uint8_t GEN3_TYPE_EFFECTIVENESS[GEN3_TYPE_COUNT][GEN3_TYPE_COUNT] = {');
for (const attacking of TYPE_NAMES) {
  const row = TYPE_NAMES.map(defending => {
    const code = dex.types.get(defending).damageTaken[attacking];
    return ({0: 2, 1: 4, 2: 1, 3: 0})[code];
  });
  emit(`    [GEN3_TYPE_${cName(attacking)}] = {${row.join(', ')}},`);
}
emit('};');
