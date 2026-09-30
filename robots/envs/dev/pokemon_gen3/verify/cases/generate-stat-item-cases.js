#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const out = path.resolve(__dirname, 'derived');
const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';

const names = new Map([
  ['clamperl', 'Clamperl'], ['vaporeon', 'Vaporeon'], ['pikachu', 'Pikachu'],
  ['persian', 'Persian'], ['smeargle', 'Smeargle'], ['blissey', 'Blissey'],
  ['ditto', 'Ditto'],
  ['shellarmor', 'Shell Armor'], ['waterabsorb', 'Water Absorb'],
  ['static', 'Static'], ['limber', 'Limber'], ['owntempo', 'Own Tempo'],
  ['naturalcure', 'Natural Cure'], ['deepseascale', 'Deep Sea Scale'],
  ['deepseatooth', 'Deep Sea Tooth'], ['lightball', 'Light Ball'],
  ['machobrace', 'Macho Brace'], ['souldew', 'Soul Dew'],
  ['metalpowder', 'Metal Powder'],
  ['surf', 'Surf'], ['thunderbolt', 'Thunderbolt'], ['scratch', 'Scratch'],
  ['splash', 'Splash'], ['irondefense', 'Iron Defense'], ['psychic', 'Psychic'],
]);

const mon = (species, gender, ability, item, moves, stats) => ({
  species, level: 100, gender, ability, item, moves, stats, status: null,
});
const clamperl = (item, moves = ['surf']) => mon(
  'clamperl', 'F', 'shellarmor', item, moves, [211, 164, 206, 184, 146, 100]);
const vaporeon = (item = '') => mon(
  'vaporeon', 'F', 'waterabsorb', item, ['surf'], [401, 166, 156, 256, 226, 166]);
const pikachu = (item, moves) => mon(
  'pikachu', 'M', 'static', item, moves, [211, 146, 96, 136, 116, 216]);
const persian = item => mon(
  'persian', 'M', 'limber', item, ['scratch'], [271, 176, 156, 166, 166, 266]);
const smeargle = (item = '', moves = ['splash']) => mon(
  'smeargle', 'M', 'owntempo', item, moves, [251, 76, 106, 76, 126, 186]);
const blissey = () => mon(
  'blissey', 'F', 'naturalcure', '', ['splash'], [651, 56, 56, 186, 306, 146]);
const ditto = (item = '') => mon(
  'ditto', 'N', 'limber', item, ['splash'], [237, 132, 132, 132, 132, 132]);

function writeTeam(filename, team) {
  const text = team.map(pokemon => {
    const held = pokemon.item ? ` @ ${names.get(pokemon.item)}` : '';
    const gender = pokemon.gender === 'N' ? '' : ` (${pokemon.gender})`;
    return [
      `${names.get(pokemon.species)}${gender}${held}`,
      `Ability: ${names.get(pokemon.ability)}`,
      'Level: 100', 'Hardy Nature',
      ...pokemon.moves.map(move => `- ${names.get(move)}`), '',
    ].join('\n');
  }).join('\n');
  fs.writeFileSync(path.join(out, filename), text);
}

function emit(id, p1, p2, features) {
  const left = `${id}-p1.txt`;
  const right = `${id}-p2.txt`;
  writeTeam(left, p1);
  writeTeam(right, p2);
  const choices = [['move 1', 'move 1']];
  const value = {
    schema: 'pokemon-native-differential-case-v1', id,
    provenance: {
      kind: 'showdown-derived',
      source_file: 'data/items.ts; data/mods/gen3/items.ts; sim/battle.ts',
      test_name: id, oracle_revision: revision,
    },
    format: 'gen3ou', seed: [1, 2, 3, 4],
    teams: [{source: left, normalized: p1}, {source: right, normalized: p2}],
    source_choices: choices, choices, forced_outcomes: [],
    features: [
      'choice.move', 'damage.gen3', 'queue.speed',
      'prng.labeled', 'state.canonical', ...features,
    ],
    boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
    limits: {max_boundaries: 2, max_actions: 2},
  };
  fs.writeFileSync(path.join(out, `${id}.json`), `${JSON.stringify(value, null, 2)}\n`);
}

emit('stat-item-deep-sea-tooth', [clamperl('deepseatooth')], [blissey()],
  ['item.deep-sea-tooth', 'handler.modify-special-attack']);
emit('stat-item-deep-sea-tooth-guard', [vaporeon('deepseatooth')], [blissey()],
  ['item.deep-sea-tooth', 'handler.species-guard']);
emit('stat-item-deep-sea-scale', [vaporeon()], [clamperl('deepseascale', ['irondefense'])],
  ['item.deep-sea-scale', 'handler.modify-special-defense']);
emit('stat-item-deep-sea-scale-guard', [vaporeon()],
  [smeargle('deepseascale', ['irondefense'])],
  ['item.deep-sea-scale', 'handler.species-guard']);
emit('stat-item-light-ball-special', [pikachu('lightball', ['thunderbolt'])], [blissey()],
  ['item.light-ball', 'handler.modify-special-attack']);
emit('stat-item-light-ball-physical-control', [pikachu('lightball', ['scratch'])], [blissey()],
  ['item.light-ball']);
emit('stat-item-macho-brace', [persian('machobrace')], [smeargle()],
  ['item.macho-brace', 'handler.modify-spe']);
emit('stat-item-macho-brace-control', [persian('')], [smeargle()],
  ['item.macho-brace']);
emit('stat-item-soul-dew-legal-noop', [smeargle('souldew', ['psychic'])],
  [smeargle('souldew')],
  ['item.soul-dew', 'handler.modify-special-attack',
    'handler.modify-special-defense', 'format.validation']);
emit('stat-item-metal-powder', [persian('')], [ditto('metalpowder')],
  ['item.metal-powder', 'handler.modify-defense']);
emit('stat-item-metal-powder-guard', [persian('metalpowder')], [ditto()],
  ['item.metal-powder', 'handler.species-guard']);
