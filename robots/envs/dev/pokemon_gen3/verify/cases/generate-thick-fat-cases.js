#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const out = path.resolve(__dirname, 'derived');
const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const display = new Map([
  ['alakazam', 'Alakazam'], ['snorlax', 'Snorlax'],
  ['synchronize', 'Synchronize'], ['thickfat', 'Thick Fat'],
  ['firepunch', 'Fire Punch'], ['icepunch', 'Ice Punch'],
  ['psychic', 'Psychic'], ['tackle', 'Tackle'],
]);
const mon = (species, gender, ability, moves, stats) => ({
  species, level: 100, gender, ability, item: '', moves, stats, status: null,
});
const attacker = move => mon(
  'alakazam', 'M', 'synchronize', [move], [251, 136, 126, 306, 206, 276]);
const defender = mon(
  'snorlax', 'M', 'thickfat', ['tackle'], [461, 256, 166, 166, 256, 96]);

function writeTeam(filename, pokemon) {
  const text = pokemon.map(p => [
    `${display.get(p.species)} (${p.gender})`,
    `Ability: ${display.get(p.ability)}`,
    'Level: 100',
    'Hardy Nature',
    ...p.moves.map(move => `- ${display.get(move)}`),
    '',
  ].join('\n')).join('\n');
  fs.writeFileSync(path.join(out, filename), text);
}

function writeCase(move) {
  const id = `thick-fat-${move}`;
  const left = `${id}-p1.txt`;
  const right = `${id}-p2.txt`;
  const p1 = attacker(move);
  writeTeam(left, [p1]);
  writeTeam(right, [defender]);
  const fixture = {
    schema: 'pokemon-native-differential-case-v1', id,
    provenance: {
      kind: 'showdown-derived',
      source_file: 'data/mods/gen4/abilities.ts; sim/battle-actions.ts',
      test_name: id, oracle_revision: revision,
    },
    format: 'gen3ou', seed: [1, 2, 3, 4],
    teams: [
      {source: left, normalized: [p1]},
      {source: right, normalized: [defender]},
    ],
    source_choices: [['move 1', 'move 1']],
    choices: [['move 1', 'move 1']], forced_outcomes: [],
    features: [
      'choice.move', 'handler.base-power', 'handler.thick-fat',
      'hit.accuracy', 'damage.critical', 'damage.gen3', 'prng.labeled',
      'queue.speed', 'state.canonical',
    ],
    boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
    limits: {max_boundaries: 2, max_actions: 2},
  };
  fs.writeFileSync(
    path.join(out, `${id}.json`), `${JSON.stringify(fixture, null, 2)}\n`);
}

for (const move of ['firepunch', 'icepunch', 'psychic']) writeCase(move);
