#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');

const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const out = path.resolve(__dirname, 'derived');
const moves = [
  ['recover', 1], ['milk-drink', 2], ['slack-off', 3], ['soft-boiled', 4],
];
const states = [
  ['odd', 100], ['clamp', 250], ['full', 251],
];
for (const [label, slot] of moves) {
  for (const [state, initialHP] of states) {
    const id = `direct-heal-${label}-${state}`;
    const fixture = {
      schema: 'pokemon-native-differential-case-v1', id,
      provenance: {
        kind: 'showdown-derived', source_file: 'data/moves.ts; sim/battle-actions.ts; sim/battle.ts',
        test_name: `${label} direct half-heal ${state} transaction`,
        oracle_revision: revision,
      },
      format: 'gen3ou', seed: [1, 2, 3, 4],
      teams: [
        {source: 'alakazam-direct-heals-p1.txt', normalized: [{
          species: 'alakazam', level: 100, gender: 'M', ability: 'synchronize', item: '',
          moves: ['recover', 'milkdrink', 'slackoff', 'softboiled'],
          stats: [251, 136, 126, 306, 206, 276], status: null,
          initial_hp: initialHP,
        }]},
        {source: 'magikarp-splash-p2.txt', normalized: [{
          species: 'magikarp', level: 100, gender: 'M', ability: 'swiftswim', item: '',
          moves: ['splash'], stats: [181, 56, 146, 66, 76, 196], status: null,
        }]},
      ],
      source_choices: [[`move ${slot}`, 'move 1']],
      choices: [[`move ${slot}`, 'move 1']], forced_outcomes: [],
      features: ['choice.move', 'effect.direct-heal', 'handler.try-heal',
        'state.canonical'],
      boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events',
        'prng'], limits: {max_boundaries: 2, max_actions: 2},
    };
    fs.writeFileSync(path.join(out, `${id}.json`), `${JSON.stringify(fixture, null, 2)}\n`);
  }
}

const alakazam = (moves, initialHP = 100, status = null) => ({
  species: 'alakazam', level: 100, gender: 'M', ability: 'synchronize', item: '',
  moves, stats: [251, 136, 126, 306, 206, 276], status, initial_hp: initialHP,
});
const magikarp = {
  species: 'magikarp', level: 100, gender: 'M', ability: 'swiftswim', item: '',
  moves: ['splash'], stats: [181, 56, 146, 66, 76, 196], status: null,
};
const writeCase = fixture => fs.writeFileSync(
  path.join(out, `${fixture.id}.json`), `${JSON.stringify(fixture, null, 2)}\n`);
const interaction = (id, teams, choices, extraFeatures = []) => ({
  schema: 'pokemon-native-differential-case-v1', id,
  provenance: {
    kind: 'showdown-derived', source_file: 'sim/battle-actions.ts; sim/battle.ts',
    test_name: `${id} direct heal interaction`, oracle_revision: revision,
  },
  format: 'gen3ou', seed: [1, 2, 3, 4], teams,
  source_choices: choices.map(pair => [...pair]), choices, forced_outcomes: [],
  features: ['choice.move', 'effect.direct-heal', 'handler.try-heal',
    'state.canonical', ...extraFeatures],
  boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
  limits: {max_boundaries: choices.length + 1, max_actions: choices.length * 2},
});
writeCase(interaction('direct-heal-protect-irrelevant', [
  {source: 'alakazam-direct-heals-p1.txt', normalized: [alakazam(
    ['recover', 'milkdrink', 'slackoff', 'softboiled'])]},
  {source: 'persian-protect-p2.txt', normalized: [{
    species: 'persian', level: 100, gender: 'M', ability: 'limber', item: '',
    moves: ['protect'], stats: [271, 176, 156, 166, 166, 266], status: null,
  }]},
], [['move 1', 'move 1']], ['volatile.protect']));
writeCase(interaction('direct-heal-substitute-irrelevant', [
  {source: 'alakazam-recover-substitute-p1.txt', normalized: [alakazam(
    ['recover', 'substitute'])]},
  {source: 'magikarp-splash-p2.txt', normalized: [magikarp]},
], [['move 2', 'move 1'], ['move 1', 'move 1']], ['volatile.substitute']));
writeCase(interaction('direct-heal-burn-residual', [
  {source: 'alakazam-direct-heals-p1.txt', normalized: [alakazam(
    ['recover', 'milkdrink', 'slackoff', 'softboiled'], 100, 'brn')]},
  {source: 'magikarp-splash-p2.txt', normalized: [magikarp]},
], [['move 1', 'move 1']], ['handler.residual', 'status.burn']));
const switchPersistence = interaction('direct-heal-switch-persistence', [
  {source: 'alakazam-recover-persian-p1.txt', normalized: [
    alakazam(['recover']),
    {species: 'persian', level: 100, gender: 'M', ability: 'limber', item: '',
      moves: ['splash'], stats: [271, 176, 156, 166, 166, 266], status: null},
  ]},
  {source: 'magikarp-splash-p2.txt', normalized: [magikarp]},
], [['switch 2', 'move 1'], ['switch 1', 'move 1'], ['move 1', 'move 1']],
['choice.switch', 'lifecycle.switch-persistence']);
switchPersistence.source_choices[1][0] = 'switch 2';
writeCase(switchPersistence);
writeCase(interaction('direct-heal-snatch-steal', [
  {source: 'alakazam-direct-heals-p1.txt', normalized: [alakazam(
    ['recover', 'milkdrink', 'slackoff', 'softboiled'])]},
  {source: 'alakazam-snatch-p2.txt', normalized: [{...alakazam(['snatch', 'splash'], 100),
    stats: [251, 136, 126, 306, 206, 306]}]},
], [['move 1', 'move 1']], ['move.snatch', 'volatile.snatch']));
