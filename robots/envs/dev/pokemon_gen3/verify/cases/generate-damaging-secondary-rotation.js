#!/usr/bin/env node
'use strict';

const childProcess = require('child_process');
const fs = require('fs');
const path = require('path');

const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const showdownDir = process.argv[2];
if (!showdownDir) throw new Error('usage: generate-damaging-secondary-rotation.js POKEMON_SHOWDOWN_DIR');
const actual = childProcess.execFileSync('git', ['-C', showdownDir, 'rev-parse', 'HEAD'], {encoding: 'utf8'}).trim();
if (actual !== revision) throw new Error(`expected ${revision}, got ${actual}`);
const {Dex} = require(path.resolve(showdownDir));
const dex = Dex.forGen(3);
const outputDir = path.resolve(__dirname, 'derived');

const moves = [
  'blizzard', 'dragonbreath', 'fireblast', 'firepunch', 'flamethrower',
  'flamewheel', 'heatwave', 'icebeam', 'icepunch', 'lick', 'poisonfang',
  'poisonsting', 'powdersnow', 'sludge', 'sludgebomb', 'smog', 'spark',
  'thunderbolt', 'thunderpunch', 'thundershock', 'zapcannon',
  'acid', 'aurorabeam', 'bubble', 'bubblebeam', 'constrict', 'crunch',
  'crushclaw', 'icywind', 'irontail', 'metalclaw', 'meteormash', 'mudshot',
  'mudslap', 'octazooka', 'psychic', 'rocksmash', 'rocktomb', 'shadowball',
  /* Existing generated products whose legal-holder rotation was incomplete. */
  'sacredfire', 'blazekick', 'poisontail',
  'lusterpurge', 'mistball', 'muddywater',
];
const holders = [
  ['aggron', 'rockhead'], ['tentacool', 'clearbody'],
  ['corsola', 'naturalcure'], ['raikou', 'pressure'],
  ['cyndaquil', 'blaze'], ['horsea', 'swiftswim'],
  ['koffing', 'levitate'], ['articuno', 'pressure'],
  ['charizard', 'blaze'], ['gastly', 'levitate'],
  ['kabuto', 'swiftswim'], ['mawile', 'hypercutter'],
  ['metagross', 'clearbody'], ['regice', 'clearbody'],
];
const addedSuccessSeeds = new Map([
  ['sacredfire', 1], ['blazekick', 14], ['poisontail', 14],
  ['lusterpurge', 1], ['mistball', 44], ['muddywater', 1],
]);

function stats(species) {
  const base = species.baseStats;
  return [2 * base.hp + 141, 2 * base.atk + 36, 2 * base.def + 36,
    2 * base.spa + 36, 2 * base.spd + 36, 2 * base.spe + 36];
}
function gender(species) {
  return species.gender === 'N' ? 'N' : species.gender === 'F' ? 'F' : 'M';
}
function sourceMember(species, ability, move) {
  const sex = gender(species) === 'N' ? '' : ` (${gender(species)})`;
  return `${species.name}${sex}\nAbility: ${dex.abilities.get(ability).name}\nLevel: 100\n` +
    `EVs: 1 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe\nHardy Nature\n- ${move.name}\n`;
}
function normalizedMember(species, ability, move) {
  return {species: species.id, level: 100, gender: gender(species), ability,
    item: '', moves: [move.id], stats: stats(species), status: null};
}
function legalHolder(moveID) {
  for (const [speciesID, ability] of holders) {
    const learned = dex.species.getLearnsetData(speciesID).learnset?.[moveID] || [];
    if (learned.some(source => source.startsWith('3'))) return [speciesID, ability];
  }
  /* Smeargle legally obtains these finite Gen 3 moves through Sketch. */
  return ['smeargle', 'owntempo'];
}

for (const [index, moveID] of moves.entries()) {
  const move = dex.moves.get(moveID);
  const [holderID, ability] = legalHolder(moveID);
  const holder = dex.species.get(holderID);
  const targetID = move.category === 'Physical' ? 'golem' : 'blissey';
  const targetAbility = targetID === 'golem' ? 'rockhead' : 'naturalcure';
  const target = dex.species.get(targetID);
  const source1 = `secondary-${moveID}-p1.txt`;
  const source2 = `secondary-${moveID}-p2.txt`;
  fs.writeFileSync(path.join(outputDir, source1), sourceMember(holder, ability, move));
  fs.writeFileSync(path.join(outputDir, source2), sourceMember(
    target, targetAbility, dex.moves.get('splash')));
  const secondary = move.secondary;
  if (!secondary || (move.secondaries && move.secondaries.length !== 1)) {
    throw new Error(`expected one secondary on ${moveID}`);
  }
  const features = new Set([
    'choice.move', 'damage.gen3', 'effect.secondary', 'hit.accuracy',
    'prng.labeled', 'state.canonical',
  ]);
  features.add('prng.secondary');
  if (secondary.status === 'brn') features.add('status.burn');
  if (secondary.status === 'frz') features.add('status.freeze');
  if (secondary.status === 'par') features.add('status.paralysis');
  if (secondary.status === 'psn') features.add('status.poison');
  if (secondary.status === 'tox') features.add('status.toxic');
  if (secondary.boosts || secondary.self?.boosts) features.add('effect.boost');
  /* These are deterministic seed vectors, not a mutation API. The verifier's
   * `forced_outcomes` field asserts an already-observed draw; it does not
   * override Showdown's PRNG. Success/failure recombinations use separately
   * selected seeds after the descriptor rotation is generated. */
  const forced = [];
  const battleCase = {
    schema: 'pokemon-native-differential-case-v1', id: `secondary-${moveID}`,
    provenance: {kind: 'showdown-derived', source_file: 'data/moves.ts',
      test_name: `Generated single-effect damaging secondary: ${move.name}`,
      oracle_revision: revision},
    format: 'gen3ou', seed: [313, 197, 83,
      addedSuccessSeeds.get(moveID) || index + 1],
    teams: [
      {source: source1, normalized: [normalizedMember(holder, ability, move)]},
      {source: source2, normalized: [normalizedMember(target, targetAbility, dex.moves.get('splash'))]},
    ],
    source_choices: [['move 1', 'move 1']], choices: [['move 1', 'move 1']],
    forced_outcomes: forced, features: [...features].sort(),
    boundaries: ['request', 'choice', 'queue', 'handlers', 'immunity', 'state', 'events', 'prng'],
    limits: {max_boundaries: 2, max_actions: 2},
  };
  fs.writeFileSync(path.join(outputDir, `secondary-${moveID}.json`),
    `${JSON.stringify(battleCase, null, 2)}\n`);
}

console.log(`generated ${moves.length} damaging-secondary differential cases`);
