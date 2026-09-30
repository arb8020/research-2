#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');

const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const out = path.resolve(__dirname, 'derived');
const recoveries = ['moonlight', 'morningsun', 'synthesis'];
const weather = {
  sun: 'sunnyday', rain: 'raindance', sand: 'sandstorm', hail: 'hail',
};

const alakazam = (moves, initialHP = 100, speed = 276) => ({
  species: 'alakazam', level: 100, gender: 'M', ability: 'synchronize', item: '',
  moves, stats: [251, 136, 126, 306, 206, speed], status: null,
  initial_hp: initialHP,
});
const magikarp = {
  species: 'magikarp', level: 100, gender: 'M', ability: 'swiftswim', item: '',
  moves: ['splash'], stats: [181, 56, 146, 66, 76, 196], status: null,
};
const cloudNine = {
  species: 'blissey', level: 100, gender: 'F', ability: 'cloudnine', item: '',
  moves: ['splash'], stats: [651, 56, 56, 186, 306, 146], status: null,
};

function displayMove(id) {
  return {morningsun: 'Morning Sun', sunnyday: 'Sunny Day',
    raindance: 'Rain Dance'}[id] || id[0].toUpperCase() + id.slice(1);
}

function writeTeam(file, pokemon) {
  const lines = [`${pokemon.species[0].toUpperCase()}${pokemon.species.slice(1)} (${pokemon.gender})`,
    `Ability: ${pokemon.ability === 'cloudnine' ? 'Cloud Nine' :
      pokemon.ability[0].toUpperCase() + pokemon.ability.slice(1)}`,
    `Level: ${pokemon.level}`];
  if (pokemon.species === 'alakazam' && pokemon.stats[5] === 306) lines.push('EVs: 120 Spe');
  lines.push('Hardy Nature');
  for (const move of pokemon.moves) lines.push(`- ${displayMove(move)}`);
  fs.writeFileSync(path.join(out, file), `${lines.join('\n')}\n`);
}

function makeCase(id, p1, p2, choices, features, testName) {
  const p1Source = `${id}-p1.txt`;
  const p2Source = `${id}-p2.txt`;
  writeTeam(p1Source, p1);
  writeTeam(p2Source, p2);
  const fixture = {
    schema: 'pokemon-native-differential-case-v1', id,
    provenance: {
      kind: 'showdown-derived',
      source_file: 'data/mods/gen3/moves.ts; sim/battle.ts; sim/battle-actions.ts',
      test_name: testName, oracle_revision: revision,
    },
    format: 'gen3ou', seed: [1, 2, 3, 4],
    teams: [{source: p1Source, normalized: [p1]}, {source: p2Source, normalized: [p2]}],
    source_choices: choices.map(pair => [...pair]), choices, forced_outcomes: [],
    features: [...new Set(['choice.move', 'effect.heal', 'handler.try-heal',
      'state.canonical', ...features])],
    boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
    limits: {max_boundaries: choices.length + 1, max_actions: choices.length * 2},
  };
  fs.writeFileSync(path.join(out, `${id}.json`), `${JSON.stringify(fixture, null, 2)}\n`);
}

for (const recovery of recoveries) {
  makeCase(`weather-recovery-${recovery}-neutral`, alakazam([recovery]), magikarp,
    [['move 1', 'move 1']], [], `${displayMove(recovery)} heals half at odd max HP without weather`);
  for (const [weatherName, setter] of Object.entries(weather)) {
    makeCase(`weather-recovery-${recovery}-${weatherName}`, alakazam([setter, recovery]), magikarp,
      [['move 1', 'move 1'], ['move 2', 'move 1']],
      ['condition.weather', `weather.${weatherName === 'sand' ? 'sandstorm' : weatherName}`],
      `${displayMove(recovery)} uses its Gen 3 ${weatherName} recovery fraction at odd max HP`);
  }
  makeCase(`weather-recovery-${recovery}-full`, alakazam([recovery], 251), magikarp,
    [['move 1', 'move 1']], [], `${displayMove(recovery)} fails cleanly at full HP`);
  makeCase(`weather-recovery-${recovery}-snatch`, alakazam([recovery]),
    alakazam(['snatch'], 100, 306), [['move 1', 'move 1']],
    ['move.snatch', 'volatile.snatch'], `${displayMove(recovery)} is redirected by Snatch`);
}

makeCase('weather-recovery-cloud-nine-suppression', alakazam(['sunnyday', 'moonlight']),
  cloudNine, [['move 1', 'move 1'], ['move 2', 'move 1']],
  ['condition.weather', 'weather.sun', 'weather.suppression'],
  'Cloud Nine makes Moonlight use its neutral fraction while sun remains stored');

makeCase('weather-recovery-replacement-expiry',
  alakazam(['raindance', 'moonlight', 'sunnyday', 'splash']), magikarp,
  [['move 1', 'move 1'], ['move 2', 'move 1'], ['move 3', 'move 1'],
    ['move 4', 'move 1'], ['move 4', 'move 1'], ['move 4', 'move 1'],
    ['move 4', 'move 1'], ['move 2', 'move 1']],
  ['condition.weather', 'lifecycle.condition-duration',
    'lifecycle.condition-replacement', 'weather.rain', 'weather.sun'],
  'Moonlight observes rain, replacement sun, and neutral weather after expiry');
