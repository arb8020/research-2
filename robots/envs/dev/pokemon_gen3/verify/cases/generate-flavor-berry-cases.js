#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');

const out = path.resolve(__dirname, 'derived');
const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const berryNames = {
  aguavberry: 'Aguav Berry',
  figyberry: 'Figy Berry',
  iapapaberry: 'Iapapa Berry',
  magoberry: 'Mago Berry',
  wikiberry: 'Wiki Berry',
};
const sets = {
  persian: {ability: 'Limber', moves: ['Splash'], stats: [271, 176, 156, 166, 166, 266]},
  machop: {ability: 'Guts', moves: ['Splash'], stats: [281, 196, 136, 106, 106, 106]},
  magikarp: {ability: 'Swift Swim', moves: ['Splash'], stats: [181, 56, 146, 66, 76, 196]},
  smeargle: {ability: 'Own Tempo', moves: ['Splash'], stats: [251, 76, 106, 76, 126, 186]},
};
const natureStats = {
  persian: {
    hardy: [271, 176, 156, 166, 166, 266],
    modest: [271, 158, 156, 182, 166, 266],
    adamant: [271, 193, 156, 149, 166, 266],
    brave: [271, 193, 156, 166, 166, 239],
    naughty: [271, 193, 156, 166, 149, 266],
    lonely: [271, 193, 140, 166, 166, 266],
  },
  smeargle: {
    modest: [251, 68, 106, 83, 126, 186],
  },
  magikarp: {
    modest: [181, 50, 146, 72, 76, 196],
  },
};
const flavors = [
  ['aguavberry', 'naughty'], // dislikes bitter: minus Special Defense
  ['figyberry', 'modest'],   // dislikes spicy: minus Attack
  ['iapapaberry', 'lonely'], // dislikes sour: minus Defense
  ['magoberry', 'brave'],    // dislikes sweet: minus Speed
  ['wikiberry', 'adamant'],  // dislikes dry: minus Special Attack
];

const id = text => text.toLowerCase().replace(/[^a-z0-9]+/g, '');
function member(species, item = '', nature = 'hardy', moves = sets[species].moves,
  initialHP = undefined) {
  const set = sets[species];
  const title = species[0].toUpperCase() + species.slice(1);
  const itemLine = item ? ` @ ${berryNames[item]}` : '';
  const stats = natureStats[species]?.[nature] || set.stats;
  return {
    export: `${title} (M)${itemLine}\nAbility: ${set.ability}\nLevel: 100\n` +
      `EVs: 0 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe\n` +
      `${nature[0].toUpperCase()}${nature.slice(1)} Nature\n` +
      moves.map(move => `- ${move}`).join('\n') + '\n',
    normalized: {species, level: 100, gender: 'M', nature, ability: id(set.ability),
      item, moves: moves.map(id), stats, status: null,
      ...(initialHP === undefined ? {} : {initial_hp: initialHP})},
  };
}
function team(caseID, side, specs) {
  const source = `${caseID}-p${side + 1}.txt`;
  const built = specs.map(spec => member(...spec));
  fs.writeFileSync(path.join(out, source), built.map(entry => entry.export).join('\n'));
  return {source, normalized: built.map(entry => entry.normalized)};
}
function emit(caseID, p1, p2, choices, testName, forcedOutcomes = [],
  sourceChoices = choices, extraFeatures = []) {
  const fixture = {
    schema: 'pokemon-native-differential-case-v1', id: caseID,
    provenance: {
      kind: 'showdown-derived',
      source_file: 'data/items.ts; data/mods/gen3/items.ts; sim/pokemon.ts',
      test_name: testName, oracle_revision: revision,
    },
    format: 'gen3ou', seed: [607, 19, 37, 73],
    teams: [team(caseID, 0, p1), team(caseID, 1, p2)],
    source_choices: sourceChoices.map(pair => [...pair]), choices,
    forced_outcomes: forcedOutcomes,
    features: ['choice.move', 'effect.heal', 'handler.residual', 'item.consumption',
      'state.canonical', 'volatile.confusion', ...extraFeatures],
    boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
    limits: {max_boundaries: choices.length + 1, max_actions: choices.length * 2},
  };
  fs.writeFileSync(path.join(out, `${caseID}.json`), `${JSON.stringify(fixture, null, 2)}\n`);
}
const duration = () => [{
  label: 'condition.confusion.duration', occurrence: 1, range: 4, result: 1,
}];

for (const [index, [berry, nature]] of flavors.entries()) {
  const short = berry.replace('berry', '');
  emit(`berry-flavor-${short}-disliked`,
    [['persian', berry, nature, ['Splash'], 135]], [['magikarp']],
    [['move 1', 'move 1']],
    `${berryNames[berry]} heals floor(baseMaxHP / 3) then confuses its disliked nature`,
    duration(index % 4));
  emit(`berry-flavor-${short}-neutral`,
    [['persian', berry, 'hardy', ['Splash'], 135]], [['magikarp']],
    [['move 1', 'move 1']],
    `${berryNames[berry]} heals a neutral nature without confusion`);
}

emit('berry-flavor-own-tempo',
  [['smeargle', 'figyberry', 'modest', ['Splash'], 125]], [['magikarp']],
  [['move 1', 'move 1']],
  'Own Tempo rejects disliked-flavor confusion after Figy Berry healing');
emit('berry-flavor-substitute-irrelevant',
  [['persian', 'aguavberry', 'naughty', ['Substitute'], 135]], [['magikarp']],
  [['move 1', 'move 1']],
  'Substitute does not block self-inflicted disliked-flavor confusion', duration(2),
  [['move 1', 'move 1']], ['volatile.substitute']);
emit('berry-flavor-switch-item-state',
  [['machop'], ['persian', 'magoberry', 'brave', ['Splash'], 135]], [['magikarp']],
  [['switch 2', 'move 1'], ['switch 1', 'move 1'], ['switch 2', 'move 1']],
  'Consumed flavor berry remains absent across a switch cycle', duration(1),
  [['switch 2', 'move 1'], ['switch 2', 'move 1'], ['switch 2', 'move 1']],
  ['choice.switch', 'lifecycle.switch-persistence']);
emit('berry-flavor-dual-holder-order',
  [['persian', 'wikiberry', 'adamant', ['Splash'], 135]],
  [['magikarp', 'figyberry', 'modest', ['Splash'], 90]],
  [['move 1', 'move 1']],
  'Two flavor berries heal and install confusion in residual speed order', [
    {label: 'condition.confusion.duration', occurrence: 1, range: 4, result: 1},
    {label: 'condition.confusion.duration', occurrence: 2, range: 4, result: 0},
  ]);

console.log('generated 14 flavor pinch berry cases');
