#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const out = path.resolve(__dirname, 'derived');
const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const items = [
  ['masterball', 'Master Ball'], ['ultraball', 'Ultra Ball'],
  ['greatball', 'Great Ball'], ['pokeball', 'Poke Ball'],
  ['netball', 'Net Ball'], ['diveball', 'Dive Ball'],
  ['nestball', 'Nest Ball'], ['repeatball', 'Repeat Ball'],
  ['timerball', 'Timer Ball'], ['luxuryball', 'Luxury Ball'],
  ['premierball', 'Premier Ball'], ['sunstone', 'Sun Stone'],
  ['moonstone', 'Moon Stone'], ['firestone', 'Fire Stone'],
  ['thunderstone', 'Thunder Stone'], ['waterstone', 'Water Stone'],
  ['leafstone', 'Leaf Stone'], ['rootfossil', 'Root Fossil'],
  ['clawfossil', 'Claw Fossil'], ['helixfossil', 'Helix Fossil'],
  ['domefossil', 'Dome Fossil'], ['oldamber', 'Old Amber'],
  ['dragonscale', 'Dragon Scale'], ['upgrade', 'Up-Grade'],
  ['friendball', 'Friend Ball'],
  ['belueberry', 'Belue Berry'], ['blukberry', 'Bluk Berry'],
  ['cornnberry', 'Cornn Berry'], ['durinberry', 'Durin Berry'],
  ['grepaberry', 'Grepa Berry'], ['hondewberry', 'Hondew Berry'],
  ['kelpsyberry', 'Kelpsy Berry'], ['magostberry', 'Magost Berry'],
  ['nanabberry', 'Nanab Berry'], ['nomelberry', 'Nomel Berry'],
  ['pamtreberry', 'Pamtre Berry'], ['pinapberry', 'Pinap Berry'],
  ['pomegberry', 'Pomeg Berry'], ['qualotberry', 'Qualot Berry'],
  ['rabutaberry', 'Rabuta Berry'], ['razzberry', 'Razz Berry'],
  ['spelonberry', 'Spelon Berry'], ['tamatoberry', 'Tamato Berry'],
  ['watmelberry', 'Watmel Berry'], ['wepearberry', 'Wepear Berry'],
];
const alakazam = item => ({species: 'alakazam', level: 100, gender: 'M',
  ability: 'synchronize', item, moves: ['trick', 'psychic'],
  stats: [251, 136, 126, 306, 206, 276], status: null});
const magikarp = {species: 'magikarp', level: 100, gender: 'M',
  ability: 'swiftswim', item: 'oranberry', moves: ['splash'],
  stats: [181, 56, 146, 66, 76, 196], status: null};
for (const [id, name] of items) {
  const caseID = `passive-item-${id}`;
  const p1File = `${caseID}-p1.txt`;
  const p2File = `${caseID}-p2.txt`;
  fs.writeFileSync(path.join(out, p1File), [
    `Alakazam (M) @ ${name}`, 'Ability: Synchronize', 'Level: 100',
    'EVs: 1 HP', 'Hardy Nature', '- Trick', '- Psychic', '',
  ].join('\n'));
  fs.writeFileSync(path.join(out, p2File), [
    'Magikarp (M) @ Oran Berry', 'Ability: Swift Swim', 'Level: 100',
    'EVs: 1 HP', 'Hardy Nature', '- Splash', '',
  ].join('\n'));
  const value = {
    schema: 'pokemon-native-differential-case-v1', id: caseID,
    provenance: {kind: 'showdown-derived',
      source_file: 'data/items.ts; data/mods/gen3/items.ts; data/moves.ts; sim/battle-actions.ts',
      test_name: `${name} is a callback-free identity moved by generic Trick`,
      oracle_revision: revision},
    format: 'gen3ou', seed: [1, 2, 3, 4],
    teams: [{source: p1File, normalized: [alakazam(id)]},
      {source: p2File, normalized: [magikarp]}],
    source_choices: [['move 1', 'move 1']],
    choices: [['move 1', 'move 1']], forced_outcomes: [],
    features: ['choice.move', 'item.passive-identity', 'item.set',
      'item.swap', 'item.take', 'state.canonical'],
    boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
    limits: {max_boundaries: 2, max_actions: 2},
  };
  fs.writeFileSync(path.join(out, `${caseID}.json`),
    `${JSON.stringify(value, null, 2)}\n`);
}
