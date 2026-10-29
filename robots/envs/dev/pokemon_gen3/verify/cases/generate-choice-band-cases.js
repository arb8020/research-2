#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const out = path.resolve(__dirname, 'derived');
const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const catalog = {
  smeargle: {name: 'Smeargle', gender: 'M', ability: 'Own Tempo', abilityID: 'owntempo',
    stats: [251, 76, 106, 76, 126, 186]},
  blissey: {name: 'Blissey', gender: 'F', ability: 'Natural Cure', abilityID: 'naturalcure',
    stats: [651, 56, 56, 186, 306, 146]},
  alakazam: {name: 'Alakazam', gender: 'M', ability: 'Synchronize', abilityID: 'synchronize',
    stats: [251, 136, 126, 306, 206, 276]},
};
const names = {tackle: 'Tackle', howl: 'Howl', overheat: 'Overheat', splash: 'Splash'};

function member(species, moves, item = '') {
  const p = catalog[species];
  return {export: `${p.name} (${p.gender})${item ? ' @ Choice Band' : ''}\nAbility: ${p.ability}\nLevel: 100\nEVs: 1 HP\nSerious Nature\n${moves.map(move => `- ${names[move]}`).join('\n')}\n`,
    normalized: {species, level: 100, gender: p.gender, nature: 'serious',
      ability: p.abilityID, item, moves, stats: p.stats, status: null}};
}
function team(id, side, members) {
  const source = `${id}-p${side + 1}.txt`;
  fs.writeFileSync(path.join(out, source), members.map(x => x.export).join('\n'));
  return {source, normalized: members.map(x => x.normalized)};
}
function emitFixture(
  id, teams, choices, seed, forced, test, features = [], sourceChoices = choices
) {
  const fixture = {schema: 'pokemon-native-differential-case-v1', id,
    provenance: {kind: 'showdown-derived',
      source_file: 'data/mods/gen4/items.ts; data/mods/gen4/conditions.ts; data/items.ts; data/conditions.ts',
      test_name: test, oracle_revision: revision}, format: 'gen3ou', seed,
    teams,
    source_choices: sourceChoices, choices, forced_outcomes: forced,
    features: ['choice.move', 'handler.modify-attack', 'state.canonical',
      'prng.labeled', 'condition.volatile', 'request.legal-choices', ...features],
    boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
    limits: {max_boundaries: choices.length + 1, max_actions: choices.length * 2}};
  fs.writeFileSync(path.join(out, `${id}.json`), `${JSON.stringify(fixture, null, 2)}\n`);
}

function emit(id, move, choices, seed, forced, test) {
  emitFixture(id,
    [team(id, 0, [member('smeargle', [move, move === 'howl' ? 'tackle' : 'howl'], 'choiceband')]),
      team(id, 1, [member('blissey', ['splash'])])],
    choices, seed, forced, test);
}

emit('item-choice-band-connected-lock', 'tackle',
  [['move 1', 'move 1'], ['move 1', 'move 1']], [17, 31, 73, 107], [],
  'Choice Band scales physical Attack and locks a connected selected move at AfterMove');
emit('item-choice-band-miss-lock', 'overheat',
  [['move 1', 'move 1'], ['move 1', 'move 1']], [743, 31, 47, 1],
  [{label: 'move.accuracy', occurrence: 1, range: 100, result: 90}],
  'A missed selected move still installs Choice Lock at AfterMove');
emit('item-choice-band-status-lock', 'howl',
  [['move 1', 'move 1'], ['move 1', 'move 1']], [191, 17, 29, 43], [],
  'A normally executed status move installs Choice Lock at AfterMove');

{
  const id = 'item-choice-band-switch-reset';
  emitFixture(id,
    [team(id, 0, [
      member('smeargle', ['tackle', 'howl'], 'choiceband'),
      member('alakazam', ['splash']),
    ]), team(id, 1, [member('blissey', ['splash'])])],
    [['move 1', 'move 1'], ['switch 2', 'move 1'],
      ['switch 1', 'move 1'], ['move 2', 'move 1']],
    [211, 223, 227, 229], [],
    'Choice Lock permits switching and generic switch cleanup restores both moves',
    ['choice.switch'],
    [['move 1', 'move 1'], ['switch 2', 'move 1'],
      ['switch 2', 'move 1'], ['move 2', 'move 1']]);
}

console.log('generated 4 Choice Band cases');
