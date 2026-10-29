#!/usr/bin/env node
'use strict';

const childProcess = require('child_process');
const fs = require('fs');
const path = require('path');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const showdownDir = path.resolve(process.argv[2] || '');
if (!process.argv[2]) throw new Error('usage: node generate-delayed-slot-cases.js POKEMON_SHOWDOWN_DIR');
const actual = childProcess.execFileSync('git', ['-C', showdownDir, 'rev-parse', 'HEAD'],
	{encoding: 'utf8'}).trim();
if (actual !== REVISION) throw new Error(`expected ${REVISION}, got ${actual}`);

const {Dex, Teams} = require(showdownDir);
const {TeamValidator} = require(path.join(showdownDir, 'dist/sim/team-validator'));
const {normalizeCase} = require('./normalize');
const dex = Dex.forGen(3);
const validator = TeamValidator.get('gen3ou');
const outputDir = path.join(__dirname, 'derived');

function stats(speciesID) {
	const base = dex.species.get(speciesID).baseStats;
	const scaled = stat => 2 * base[stat] + 31;
	return [speciesID === 'shedinja' ? 1 : scaled('hp') + 110,
		scaled('atk') + 5, scaled('def') + 5,
		scaled('spa') + 5, scaled('spd') + 5, scaled('spe') + 5];
}

function member(species, ability, moves, options = {}) {
	return {
		species, level: 100, gender: options.gender || 'M', ability, item: '', moves,
		stats: stats(species), status: options.status || null,
		...(options.initialHP === undefined ? {} : {initial_hp: options.initialHP}),
	};
}

function teamText(team) {
	return team.map(set => `${dex.species.get(set.species).name} (${set.gender})\n` +
		`Ability: ${dex.abilities.get(set.ability).name}\nLevel: 100\n` +
		`EVs: 1 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe\nHardy Nature\n` +
		`${set.moves.map(id => `- ${dex.moves.get(id).name}`).join('\n')}\n`).join('\n');
}

function writeCase(spec) {
	const sources = [`${spec.id}-p1.txt`, `${spec.id}-p2.txt`];
	for (let side = 0; side < 2; side++) {
		const text = teamText(spec.teams[side]);
		const errors = validator.validateTeam(Teams.import(text));
		if (errors) throw new Error(`${spec.id} p${side + 1} is illegal:\n${errors.join('\n')}`);
		fs.writeFileSync(path.join(outputDir, sources[side]), text);
	}
	const value = normalizeCase({
		schema: 'pokemon-native-differential-case-v1', id: spec.id,
		provenance: {kind: 'showdown-derived', source_file: spec.source,
			test_name: spec.description, oracle_revision: REVISION},
		format: 'gen3ou', seed: spec.seed,
		teams: spec.teams.map((team, side) => ({source: sources[side], normalized: team})),
		source_choices: spec.choices, choices: spec.normalizedChoices || spec.choices,
		forced_outcomes: spec.forcedOutcomes || [],
		features: spec.features,
		boundaries: spec.boundaries ||
			['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
		limits: {max_boundaries: spec.choices.length + 1, max_actions: spec.choices.length * 2},
	});
	fs.writeFileSync(path.join(outputDir, `${spec.id}.json`), `${JSON.stringify(value, null, 2)}\n`);
}

const smeargle = moves => member('smeargle', 'owntempo', moves);
const blissey = (moves, options = {}) => member('blissey', 'naturalcure', moves, options);
const snorlax = moves => member('snorlax', 'immunity', moves);

const commonFeatures = ['choice.move', 'condition.slot', 'lifecycle.condition-duration',
	'prng.labeled', 'state.canonical'];

for (const spec of [
	{
		id: 'future-sight-shared-collision-switch-protect-hit', seed: [1, 2, 3, 4],
		source: 'data/mods/gen3/moves.ts',
		description: 'Future Sight owns the target position, rejects Doom Desire on the shared key, removes Protect, and hits the replacement',
		teams: [[smeargle(['futuresight', 'doomdesire', 'splash'])], [
			blissey(['softboiled', 'protect']), snorlax(['protect'])]],
		choices: [['move 1', 'move 1'], ['move 2', 'switch 2'], ['move 3', 'move 1']],
		forcedOutcomes: [{label: 'move.accuracy', occurrence: 1, range: 100, result: 57}],
		features: [...commonFeatures, 'slot.futuremove', 'prng.delayed-hit', 'hit.protect',
			'choice.switch', 'lifecycle.switch-persistence'],
	},
	{
		id: 'doom-desire-endure-expiry-miss', seed: [1, 2, 3, 0],
		source: 'data/mods/gen3/moves.ts',
		description: 'Doom Desire clears Endure and consumes its only accuracy draw at expiry even when it misses',
		teams: [[smeargle(['doomdesire', 'splash'])], [blissey(['softboiled', 'endure'])]],
		choices: [['move 1', 'move 1'], ['move 2', 'move 1'], ['move 2', 'move 2']],
		forcedOutcomes: [{label: 'move.accuracy', occurrence: 1, range: 100, result: 86}],
		features: [...commonFeatures, 'slot.futuremove', 'prng.delayed-hit',
			'volatile.endure'],
	},
	{
		id: 'wish-futuremove-coexist-switch-residual-order', seed: [1, 2, 3, 4],
		source: 'data/mods/gen4/moves.ts',
		description: 'Wish and Future Sight coexist on one position and resolve around poison in Gen 3 residual order',
		teams: [[member('vaporeon', 'waterabsorb', ['haze', 'wish']),
			blissey(['softboiled'], {status: 'psn', initialHP: 100})],
			[smeargle(['futuresight', 'splash'])]],
		choices: [['move 1', 'move 1'], ['move 2', 'move 2'], ['switch 2', 'move 2']],
		forcedOutcomes: [{label: 'move.accuracy', occurrence: 1, range: 100, result: 84}],
		features: [...commonFeatures, 'slot.futuremove', 'slot.wish', 'prng.delayed-hit',
			'status.poison', 'choice.switch', 'lifecycle.switch-persistence'],
	},
	{
		id: 'upstream-wish-31', seed: [1, 2, 3, 4],
		source: 'test/sim/moves/wish.js:31; data/mods/gen4/moves.ts#wish',
		description: 'Wish duration progresses while its position is empty after the user faints, then heals the forced replacement',
		teams: [[member('pichu', 'static', ['wish'], {initialHP: 1}),
			member('parasect', 'effectspore', ['sleeptalk'], {initialHP: 100})],
			[blissey(['seismictoss', 'softboiled'])]],
		choices: [['move 1', 'move 1'], ['switch 2', null], ['move 1', 'move 2']],
		features: [...commonFeatures, 'slot.wish', 'lifecycle.faint',
			'lifecycle.forced-replacement', 'effect.direct-heal'],
	},
	{
		id: 'upstream-wish-64', seed: [1, 2, 3, 4],
		source: 'test/sim/moves/wish.js:64; data/mods/gen4/moves.ts#wish',
		description: 'Wish does not heal a fainted occupant or survive terminal resolution when hazards leave its position empty',
		teams: [[member('vaporeon', 'waterabsorb', ['wish'], {initialHP: 1}),
			member('shedinja', 'wonderguard', ['sleeptalk'])],
			[member('skarmory', 'keeneye', ['spikes', 'protect'])]],
		choices: [['move 1', 'move 1'], ['switch 2', 'move 2'], ['switch 2', null]],
		normalizedChoices: [['move 1', 'move 1'], ['switch 2', 'move 2'],
			['switch 1', null]],
		features: [...commonFeatures, 'slot.wish', 'condition.side', 'side.spikes',
			'lifecycle.faint', 'lifecycle.forced-replacement',
			'lifecycle.terminal'],
		boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng',
			'terminal'],
	},
	{
		id: 'futuremove-fainted-occupant-no-accuracy', seed: [1, 2, 3, 4],
		source: 'data/conditions.ts',
		description: 'Poison faints the current occupant before Future Sight, which clears without accuracy and requests replacement',
		teams: [[smeargle(['futuresight', 'splash'])], [
			blissey(['protect'], {status: 'psn', initialHP: 200}), snorlax(['protect'])]],
		choices: [['move 1', 'move 1'], ['move 2', 'move 1'], ['move 2', 'move 1']],
		features: [...commonFeatures, 'slot.futuremove', 'prng.delayed-hit',
			'status.poison', 'lifecycle.forced-replacement'],
	},
	{
		id: 'futuremove-terminal-winner', seed: [1, 2, 3, 4],
		source: 'data/conditions.ts',
		description: 'Future Sight expiry drains its faint and resolves the winner before another request',
		teams: [[smeargle(['futuresight', 'splash'])], [
			blissey(['aromatherapy'], {initialHP: 1})]],
		choices: [['move 1', 'move 1'], ['move 2', 'move 1'], ['move 2', 'move 1']],
		forcedOutcomes: [{label: 'move.accuracy', occurrence: 1, range: 100, result: 84}],
		features: [...commonFeatures, 'slot.futuremove', 'prng.delayed-hit',
			'lifecycle.faint', 'lifecycle.terminal'],
		boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng',
			'terminal'],
	},
	{
		id: 'doom-desire-lethal-forced-replacement', seed: [1, 2, 3, 4],
		source: 'data/mods/gen3/moves.ts',
		description: 'Doom Desire expiry drains its faint, requests a replacement, and resumes after the switch',
		teams: [[smeargle(['doomdesire', 'splash'])], [
			blissey(['aromatherapy'], {initialHP: 1}), snorlax(['protect'])]],
		choices: [['move 1', 'move 1'], ['move 2', 'move 1'], ['move 2', 'move 1'],
			[null, 'switch 2']],
		forcedOutcomes: [{label: 'move.accuracy', occurrence: 1, range: 100, result: 84}],
		features: [...commonFeatures, 'slot.futuremove', 'prng.delayed-hit',
			'lifecycle.faint', 'lifecycle.forced-replacement'],
	},
]) writeCase(spec);

console.log('generated and legality-validated 8 delayed-slot fixtures');
