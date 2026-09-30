#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');

const out = path.resolve(__dirname, 'derived');
const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';

const catalog = {
  smeargle: {
    name: 'Smeargle', gender: 'M', ability: 'Own Tempo', abilityID: 'owntempo',
    stats: [251, 76, 106, 76, 126, 186],
  },
  blissey: {
    name: 'Blissey', gender: 'F', ability: 'Natural Cure', abilityID: 'naturalcure',
    stats: [651, 56, 56, 186, 306, 146],
  },
  alakazam: {
    name: 'Alakazam', gender: 'M', ability: 'Synchronize', abilityID: 'synchronize',
    stats: [251, 136, 126, 306, 206, 276],
  },
  magikarp: {
    name: 'Magikarp', gender: 'M', ability: 'Swift Swim', abilityID: 'swiftswim',
    stats: [181, 56, 146, 66, 76, 196],
  },
};
const moveNames = {
  aromatherapy: 'Aromatherapy',
  healbell: 'Heal Bell',
  softboiled: 'Soft-Boiled',
  psychic: 'Psychic',
  splash: 'Splash',
};

function member(species, moves, status = null) {
  const pokemon = catalog[species];
  return {
    export: [
      `${pokemon.name} (${pokemon.gender})`,
      `Ability: ${pokemon.ability}`,
      'Level: 100',
      'EVs: 1 HP',
      'Hardy Nature',
      ...moves.map(move => `- ${moveNames[move]}`),
      '',
    ].join('\n'),
    normalized: {
      species, level: 100, gender: pokemon.gender, nature: 'hardy',
      ability: pokemon.abilityID, item: '', moves,
      stats: pokemon.stats, status,
    },
  };
}

function team(id, side, members) {
  const source = `${id}-p${side + 1}.txt`;
  fs.writeFileSync(path.join(out, source), members.map(pokemon => pokemon.export).join('\n'));
  return {source, normalized: members.map(pokemon => pokemon.normalized)};
}

function emit(id, move, statuses, description) {
  const p1 = statuses === null ?
    [member('smeargle', [move])] :
    [
      member('smeargle', [move], statuses[0]),
      member('blissey', ['softboiled'], statuses[1]),
      member('alakazam', ['psychic'], statuses[2]),
    ];
  const p2 = [member('magikarp', ['splash'])];
  const choices = [['move 1', 'move 1']];
  const fixture = {
    schema: 'pokemon-native-differential-case-v1', id,
    provenance: {
      kind: 'showdown-derived',
      source_file: 'data/mods/gen4/moves.ts; sim/pokemon.ts',
      test_name: description,
      oracle_revision: revision,
    },
    format: 'gen3ou', seed: [307, 311, 313, 317],
    teams: [team(id, 0, p1), team(id, 1, p2)],
    source_choices: choices,
    choices,
    forced_outcomes: [],
    features: [
      'choice.move', 'condition.nonvolatile-status', 'hit.always',
      'state.canonical', 'target.singles-normalization',
    ],
    boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
    limits: {max_boundaries: 2, max_actions: 2},
  };
  fs.writeFileSync(path.join(out, `${id}.json`), `${JSON.stringify(fixture, null, 2)}\n`);
}

emit(
  'team-cure-aromatherapy-mixed', 'aromatherapy', ['brn', 'par', 'psn'],
  'Aromatherapy clears major status from the active user and every benched ally in party order'
);
emit(
  'team-cure-heal-bell-mixed', 'healbell', ['psn', 'brn', 'par'],
  'Heal Bell silently cures the active user and every eligible benched ally in party order'
);
emit(
  'team-cure-aromatherapy-clean', 'aromatherapy', null,
  'Aromatherapy executes without PRNG when no team member has a major status'
);
emit(
  'team-cure-heal-bell-clean', 'healbell', null,
  'Heal Bell executes without PRNG when no team member has a major status'
);

console.log('generated 4 team-status-cure cases');
