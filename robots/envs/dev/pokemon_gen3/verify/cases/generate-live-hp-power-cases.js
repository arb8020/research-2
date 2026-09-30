#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const out = path.resolve(__dirname, 'derived');
const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';

const blissey = {
  species: 'blissey', level: 100, gender: 'F', ability: 'naturalcure', item: '',
  moves: ['splash'], stats: [651, 56, 56, 186, 306, 146], status: null,
};

for (const move of ['eruption', 'waterspout']) {
  const source = `smeargle-${move}-p1.txt`;
  fs.writeFileSync(path.join(out, source), [
    'Smeargle (M)', 'Ability: Own Tempo', 'Level: 100', 'Hardy Nature',
    `- ${move === 'waterspout' ? 'Water Spout' : 'Eruption'}`, '',
  ].join('\n'));
  for (const [suffix, initialHP] of [['full', undefined], ['half-floor', 126]]) {
    const id = `live-hp-power-${move}-${suffix}`;
    const attacker = {
      species: 'smeargle', level: 100, gender: 'M', ability: 'owntempo', item: '',
      moves: [move], stats: [251, 76, 106, 76, 126, 186], status: null,
    };
    if (initialHP !== undefined) attacker.initial_hp = initialHP;
    const value = {
      schema: 'pokemon-native-differential-case-v1', id,
      provenance: {
        kind: 'showdown-derived', source_file: 'data/moves.ts; sim/battle-actions.ts',
        test_name: `${move} resolves live-source-HP base power (${suffix})`,
        oracle_revision: revision,
      },
      format: 'gen3ou', seed: [29, 43, 71, move === 'eruption' ? 101 : 103],
      teams: [
        {source, normalized: [attacker]},
        {source: 'blissey-toxic-p2-item-target.txt', normalized: [blissey]},
      ],
      source_choices: [['move 1', 'move 1']],
      choices: [['move 1', 'move 1']], forced_outcomes: [],
      features: ['choice.move', 'damage.gen3', 'damage.variable-power',
        'hit.resolved-power', 'state.canonical'],
      boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
      limits: {max_boundaries: 2, max_actions: 2},
    };
    fs.writeFileSync(path.join(out, `${id}.json`), `${JSON.stringify(value, null, 2)}\n`);
  }
}
