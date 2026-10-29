#!/usr/bin/env node
'use strict';

const childProcess = require('child_process');
const fs = require('fs');
const path = require('path');
const {normalizeCase} = require('./normalize');
const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
if (!process.argv[2]) throw new Error('usage: node generate-party-delegation-cases.js POKEMON_SHOWDOWN_DIR [OUTPUT_DIR]');
const showdownDir = path.resolve(process.argv[2]);
const outputDir = path.resolve(process.argv[3] || path.join(__dirname, 'derived'));
const revision = childProcess.execFileSync('git', ['-C', showdownDir, 'rev-parse', 'HEAD'], {encoding: 'utf8'}).trim();
if (revision !== REVISION) throw new Error(`expected ${REVISION}, got ${revision}`);
const {Dex, Teams} = require(showdownDir);
const {TeamValidator} = require(path.join(showdownDir, 'dist/sim/team-validator'));
const dex = Dex.forGen(3);
const validator = TeamValidator.get('gen3ou');
fs.mkdirSync(outputDir, {recursive: true});

function member(species, ability, moves, options = {}) {
	const base = dex.species.get(species).baseStats;
	const scaled = stat => 2 * base[stat] + 31;
	return {species, level: 100, gender: options.gender || 'M', ability, item: '', moves,
		stats: [scaled('hp') + 110, scaled('atk') + 5, scaled('def') + 5,
			scaled('spa') + 5, scaled('spd') + 5, scaled('spe') + 5], status: options.status || null};
}

function teamText(team) {
	return team.map(set => `${dex.species.get(set.species).name} (${set.gender})\n` +
		`Ability: ${dex.abilities.get(set.ability).name}\nLevel: 100\n` +
		'EVs: 1 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe\nHardy Nature\n' +
		set.moves.map(id => `- ${dex.moves.get(id).name}`).join('\n') + '\n').join('\n');
}

function emit(spec) {
	const sources = [`${spec.id}-p1.txt`, `${spec.id}-p2.txt`];
	for (let side = 0; side < 2; side++) {
		const text = teamText(spec.teams[side]);
		const errors = validator.validateTeam(Teams.import(text));
		if (errors) throw new Error(`${spec.id} p${side + 1}:\n${errors.join('\n')}`);
		fs.writeFileSync(path.join(outputDir, sources[side]), text);
	}
	const fixture = normalizeCase({schema: 'pokemon-native-differential-case-v1', id: spec.id,
		provenance: {kind: 'showdown-derived', source_file: spec.sourceFile,
			test_name: spec.testName, oracle_revision: REVISION},
		format: 'gen3ou', seed: spec.seed,
		teams: spec.teams.map((team, side) => ({source: sources[side], normalized: team})),
		source_choices: spec.sourceChoices, choices: spec.choices,
		forced_outcomes: spec.forcedOutcomes, features: spec.features,
		boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
		limits: {max_boundaries: spec.choices.length + 1, max_actions: spec.choices.length * 2}});
	fs.writeFileSync(path.join(outputDir, `${spec.id}.json`), `${JSON.stringify(fixture, null, 2)}\n`);
}

const passive = [member('blissey', 'naturalcure', ['softboiled'], {gender: 'F'})];
const sourceSwitches = [['switch 2', 'move 1'], ['switch 3', 'move 1'], ['switch 2', 'move 1']];
const stableSwitches = [['switch 2', 'move 1'], ['switch 3', 'move 1'], ['switch 1', 'move 1']];

emit({id: 'beat-up-party-order', seed: [419, 71, 29, 7],
	teams: [[member('smeargle', 'owntempo', ['beatup', 'splash']),
		member('machop', 'guts', ['bulkup']), member('alakazam', 'synchronize', ['recover'])], passive],
	sourceChoices: [...sourceSwitches, ['move 1', 'move 1']],
	choices: [...stableSwitches, ['move 1', 'move 1']],
	forcedOutcomes: [{label: 'move.accuracy', occurrence: 1, range: 100, result: 73},
		{label: 'move.critical', occurrence: 1, range: 16, result: 10},
		{label: 'move.damage_roll', occurrence: 1, range: 16, result: 3},
		{label: 'move.critical', occurrence: 2, range: 16, result: 1},
		{label: 'move.damage_roll', occurrence: 2, range: 16, result: 5},
		{label: 'move.critical', occurrence: 3, range: 16, result: 13},
		{label: 'move.damage_roll', occurrence: 3, range: 16, result: 14}],
	sourceFile: 'sim/battle-actions.ts#switchIn; data/mods/gen3/moves.ts#beatup; data/mods/gen4/moves.ts#beatup',
	testName: 'Beat Up snapshots healthy contributors in mutable party order',
	features: ['choice.move', 'choice.switch', 'hit.multihit',
		'prng.labeled', 'state.canonical']});

emit({id: 'beat-up-status-filter', seed: [419, 71, 29, 7],
	teams: [[member('smeargle', 'owntempo', ['beatup', 'splash']),
		member('machop', 'guts', ['bulkup']),
		member('alakazam', 'synchronize', ['recover'], {status: 'par'})], passive],
	sourceChoices: [['move 1', 'move 1']], choices: [['move 1', 'move 1']],
	forcedOutcomes: [{label: 'move.accuracy', occurrence: 1, range: 100, result: 92},
		{label: 'move.critical', occurrence: 1, range: 16, result: 7},
		{label: 'move.damage_roll', occurrence: 1, range: 16, result: 9},
		{label: 'move.critical', occurrence: 2, range: 16, result: 11},
		{label: 'move.damage_roll', occurrence: 2, range: 16, result: 10}],
	sourceFile: 'data/mods/gen3/moves.ts#beatup; data/mods/gen4/moves.ts#beatup',
	testName: 'Beat Up excludes a statused party member from its contributor snapshot',
	features: ['choice.move', 'hit.multihit', 'status.paralysis', 'prng.labeled', 'state.canonical']});

emit({id: 'beat-up-typeless-ghost', seed: [557, 89, 31, 11],
	teams: [[member('smeargle', 'owntempo', ['beatup'])],
		[member('banette', 'insomnia', ['thunderbolt'])]],
	sourceChoices: [['move 1', 'move 1']], choices: [['move 1', 'move 1']],
	forcedOutcomes: [{label: 'move.accuracy', occurrence: 1, range: 100, result: 47},
		{label: 'move.critical', occurrence: 1, range: 16, result: 14},
		{label: 'move.damage_roll', occurrence: 1, range: 16, result: 3}],
	sourceFile: 'data/mods/gen3/moves.ts#beatup; sim/pokemon.ts#runImmunity',
	testName: 'Gen 3 Beat Up becomes typeless and connects against Ghost',
	features: ['choice.move', 'hit.multihit', 'hit.type-immunity', 'prng.labeled', 'state.canonical']});

emit({id: 'beat-up-zero-contributors', seed: [563, 97, 37, 13],
	teams: [[member('smeargle', 'owntempo', ['beatup'], {status: 'psn'})], passive],
	sourceChoices: [['move 1', 'move 1']], choices: [['move 1', 'move 1']],
	forcedOutcomes: [{label: 'move.accuracy', occurrence: 1, range: 100, result: 79}],
	sourceFile: 'data/mods/gen3/moves.ts#beatup; data/mods/gen4/moves.ts#beatup',
	testName: 'Beat Up with no healthy contributors fails after accuracy without hit draws',
	features: ['choice.move', 'hit.multihit', 'status.poison', 'prng.labeled', 'state.canonical']});

emit({id: 'assist-metronome-party-order-duplicate-weight', seed: [1031, 197, 83, 14],
	teams: [[member('smeargle', 'owntempo', ['metronome']), member('persian', 'limber', ['scratch'], {status: 'psn'}),
		member('charmander', 'blaze', ['ember', 'scratch'])], passive],
	sourceChoices: [...sourceSwitches, ['move 1', 'move 1']],
	choices: [...stableSwitches, ['move 1', 'move 1']],
	forcedOutcomes: [{label: 'move.delegation.selection', occurrence: 1, range: 336, result: 257},
		{label: 'move.delegation.selection', occurrence: 2, range: 3, result: 0},
		{label: 'move.accuracy', occurrence: 1, range: 100, result: 43},
		{label: 'move.critical', occurrence: 1, range: 16, result: 13},
		{label: 'move.damage_roll', occurrence: 1, range: 16, result: 5},
		{label: 'move.secondary', occurrence: 1, range: 100, result: 35}],
	sourceFile: 'sim/battle-actions.ts#switchIn; data/moves.ts#assist; data/mods/gen3/moves.ts#metronome',
	testName: 'legal Metronome to Assist samples duplicate move slots in mutable party order',
	features: ['choice.move', 'choice.switch', 'move.called-entry', 'prng.labeled',
		'state.canonical', 'status.poison']});

emit({id: 'assist-metronome-empty-noassist-pool', seed: [166, 211, 101, 17],
	teams: [[member('smeargle', 'owntempo', ['metronome']),
		member('chansey', 'naturalcure', ['metronome'], {gender: 'F'})], passive],
	sourceChoices: [['move 1', 'move 1']], choices: [['move 1', 'move 1']],
	forcedOutcomes: [{label: 'move.delegation.selection', occurrence: 1, range: 336, result: 257}],
	sourceFile: 'data/moves.ts#assist; data/mods/gen3/moves.ts#metronome',
	testName: 'Metronome to Assist has no second draw when all party moves are noassist',
	features: ['choice.move', 'move.called-entry', 'prng.labeled', 'state.canonical']});

console.log('generated and legality-validated party-order delegation fixtures');
