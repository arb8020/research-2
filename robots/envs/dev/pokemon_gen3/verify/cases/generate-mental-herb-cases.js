#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const out = path.resolve(__dirname, 'derived');
const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';

const catalog = {
  delcatty: {ability: 'cutecharm', stats: [281, 166, 166, 146, 146, 176]},
  persian: {ability: 'limber', stats: [271, 176, 156, 166, 166, 266]},
  smeargle: {ability: 'owntempo', stats: [251, 76, 106, 76, 126, 186]},
};
const names = {delcatty: 'Delcatty', persian: 'Persian', smeargle: 'Smeargle'};
const moveName = id => ({attract: 'Attract', splash: 'Splash', encore: 'Encore',
  tackle: 'Tackle', recycle: 'Recycle'})[id];
function member(species, gender, item, moves, ability = catalog[species].ability) {
  return {
    export: `${names[species]} (${gender})${item ? ' @ Mental Herb' : ''}\n` +
      `Ability: ${ability === 'cutecharm' ? 'Cute Charm' :
        ability === 'owntempo' ? 'Own Tempo' : 'Limber'}\nLevel: 100\n` +
      `EVs: 0 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe\nHardy Nature\n` +
      moves.map(move => `- ${moveName(move)}`).join('\n') + '\n',
    normalized: {species, level: 100, gender, nature: 'hardy', ability, item,
      moves, stats: catalog[species].stats, status: null},
  };
}
function team(caseID, side, entries) {
  const source = `${caseID}-p${side + 1}.txt`;
  fs.writeFileSync(path.join(out, source), entries.map(entry => entry.export).join('\n'));
  return {source, normalized: entries.map(entry => entry.normalized)};
}
function emit(caseID, p1, p2, choices, testName, forcedOutcomes = [], extra = []) {
  const fixture = {
    schema: 'pokemon-native-differential-case-v1', id: caseID,
    provenance: {kind: 'showdown-derived',
      source_file: 'data/mods/gen4/items.ts; sim/pokemon.ts; sim/battle.ts',
      test_name: testName, oracle_revision: revision},
    format: 'gen3ou', seed: [631, 29, 43, 83],
    teams: [team(caseID, 0, p1), team(caseID, 1, p2)],
    source_choices: choices.map(pair => [...pair]), choices, forced_outcomes: forcedOutcomes,
    features: ['choice.move', 'condition.attract', 'item.consumption',
      'state.canonical', ...extra],
    boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
    limits: {max_boundaries: choices.length + 1, max_actions: choices.length * 2},
  };
  fs.writeFileSync(path.join(out, `${caseID}.json`), `${JSON.stringify(fixture, null, 2)}\n`);
}

emit('item-mental-herb-attract',
  [member('delcatty', 'F', '', ['attract'])],
  [member('persian', 'M', 'mentalherb', ['splash'])],
  [['move 1', 'move 1']], 'Mental Herb uses itself and removes Attract at Update');
emit('item-mental-herb-no-attract',
  [member('delcatty', 'F', '', ['splash'])],
  [member('persian', 'M', 'mentalherb', ['splash'])],
  [['move 1', 'move 1']], 'Mental Herb remains held without Attract');
emit('item-mental-herb-same-gender-immunity',
  [member('delcatty', 'M', '', ['attract'])],
  [member('persian', 'M', 'mentalherb', ['splash'])],
  [['move 1', 'move 1']], 'Mental Herb remains held when Attract is immune');
emit('item-mental-herb-encore-not-cured',
  [member('smeargle', 'F', '', ['encore'])],
  [member('persian', 'M', 'mentalherb', ['splash'])],
  [['move 1', 'move 1']], 'Effective Gen 3 Mental Herb does not cure Encore');
emit('item-mental-herb-cute-charm',
  [member('persian', 'M', 'mentalherb', ['tackle'])],
  [member('delcatty', 'F', '', ['splash'])],
  [['move 1', 'move 1']], 'Mental Herb cures Cute Charm Attract at final Update',
  [{label: 'ability.contact_response.activation', occurrence: 1, range: 3, result: 0}]);
emit('item-mental-herb-recycle',
  [member('delcatty', 'F', '', ['attract', 'splash'])],
  [member('smeargle', 'M', 'mentalherb', ['splash', 'recycle'])],
  [['move 1', 'move 1'], ['move 2', 'move 2']],
  'Recycle restores a used Mental Herb without berry semantics', [], ['item.recycle']);

console.log('generated 6 Mental Herb cases');
