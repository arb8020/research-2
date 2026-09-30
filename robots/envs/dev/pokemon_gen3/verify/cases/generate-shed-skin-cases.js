#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const out = path.resolve(__dirname, 'derived');
const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const display = new Map([
  ['seviper', 'Seviper'], ['blissey', 'Blissey'], ['persian', 'Persian'],
  ['alakazam', 'Alakazam'], ['shedskin', 'Shed Skin'],
  ['naturalcure', 'Natural Cure'], ['synchronize', 'Synchronize'],
  ['softboiled', 'Soft-Boiled'],
]);
const name = id => display.get(id) || id[0].toUpperCase() + id.slice(1);
const mon = (species, ability, moves, stats, status = null, initialHP) => ({
  species, level: 100, gender: 'M', nature: 'hardy', ability, item: '', moves,
  stats, status, ...(initialHP === undefined ? {} : {initial_hp: initialHP}),
});
const seviper = (status = null, initialHP, move = 'screech') =>
  mon('seviper', 'shedskin', [move], [287, 236, 156, 236, 156, 166], status, initialHP);
const blissey = () =>
  mon('blissey', 'naturalcure', ['softboiled'], [651, 56, 56, 186, 306, 146]);
const persian = () =>
  mon('persian', 'limber', ['scratch'], [271, 176, 156, 166, 166, 266]);
const alakazam = () =>
  mon('alakazam', 'synchronize', ['psychic'], [251, 136, 126, 306, 206, 276]);

function writeTeam(file, pokemon) {
  fs.writeFileSync(path.join(out, file), pokemon.map(p =>
    `${name(p.species)} (M)\nAbility: ${name(p.ability)}\nLevel: 100\nEVs: 1 HP\nHardy Nature\n${p.moves.map(move => `- ${name(move)}`).join('\n')}\n`
  ).join('\n'));
}

function writeCase({id, p1, p2, choices, seed = [1, 2, 3, 4], outcomes = [], features}) {
  const a = `${id}-p1.txt`;
  const b = `${id}-p2.txt`;
  writeTeam(a, p1);
  writeTeam(b, p2);
  const value = {
    schema: 'pokemon-native-differential-case-v1', id,
    provenance: {
      kind: 'showdown-derived',
      source_file: 'data/abilities.ts; data/mods/gen4/abilities.ts; sim/battle.ts',
      test_name: id, oracle_revision: revision,
    },
    format: 'gen3ou', seed,
    teams: [{source: a, normalized: p1}, {source: b, normalized: p2}],
    source_choices: choices, choices,
    forced_outcomes: outcomes,
    features,
    boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
    limits: {max_boundaries: choices.length + 1, max_actions: choices.flat().filter(Boolean).length},
  };
  fs.writeFileSync(path.join(out, `${id}.json`), `${JSON.stringify(value, null, 2)}\n`);
}

const forced = result => [{
  label: 'ability.residual_status_cure', occurrence: 1, range: 100, result,
}];
const statusFeature = new Map([
  ['brn', 'status.burn'], ['tox', 'status.toxic'], ['par', 'status.paralysis'],
  ['psn', 'status.poison'], ['frz', 'status.freeze'],
]);
const outcomes = new Map([
  ['brn', {cure: [1, 7], preserve: [3, 46]}],
  ['tox', {cure: [1, 7], preserve: [3, 46]}],
  ['par', {cure: [4, 13], preserve: [1, 50]}],
  ['psn', {cure: [1, 7], preserve: [3, 46]}],
  ['frz', {cure: [1, 7], preserve: [3, 46]}],
]);
for (const status of ['brn', 'tox', 'par', 'psn', 'frz']) {
  for (const outcome of ['cure', 'preserve']) {
    const [tail, result] = outcomes.get(status)[outcome];
    writeCase({
      id: `shed-skin-${status}-${outcome}`,
      p1: [seviper(status)], p2: [blissey()],
      choices: [['move 1', 'move 1']], seed: [1, 2, 3, tail],
      outcomes: forced(result),
      features: ['choice.move', 'handler.residual', statusFeature.get(status),
        'state.canonical', 'prng.labeled'],
    });
  }
}
writeCase({
  id: 'shed-skin-no-status', p1: [seviper()], p2: [blissey()],
  choices: [['move 1', 'move 1']],
  features: ['choice.move', 'handler.residual', 'state.canonical', 'prng.labeled'],
});
writeCase({
  id: 'shed-skin-ko-before-residual',
  p1: [seviper(null, 1, 'bite'), persian()], p2: [alakazam()],
  choices: [['move 1', 'move 1'], ['switch 2', null]],
  features: ['choice.move', 'choice.switch', 'handler.residual',
    'state.canonical', 'prng.labeled'],
});

/* Case v1 cannot serialize nonzero sleep time or skippedTime. Emitting `slp`
 * would construct an invalid native state, so sleep clear/preserve cases must
 * wait for those fields at the shared oracle/native normalization boundary.
 * Toxic exercises the same handler after its canonical residual-stage
 * projection is normalized at the observer boundary. */
