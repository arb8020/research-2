#!/usr/bin/env node
'use strict';

const childProcess = require('child_process');
const fs = require('fs');
const path = require('path');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const showdownDir = path.resolve(process.argv[2] || '');
if (!process.argv[2]) throw new Error('usage: node generate-drag-cases.js POKEMON_SHOWDOWN_DIR');
const actual = childProcess.execFileSync(
	'git', ['-C', showdownDir, 'rev-parse', 'HEAD'], {encoding: 'utf8'}).trim();
if (actual !== REVISION) throw new Error(`expected ${REVISION}, got ${actual}`);

const {Dex, Teams} = require(showdownDir);
const {TeamValidator} = require(path.join(showdownDir, 'dist/sim/team-validator'));
const {normalizeCase} = require('./normalize');
const dex = Dex.forGen(3);
const validator = TeamValidator.get('gen3ou');
const outputDir = path.join(__dirname, 'derived');
fs.mkdirSync(outputDir, {recursive: true});

function stats(speciesID, level = 100) {
	const base = dex.species.get(speciesID).baseStats;
	const scaled = stat => Math.floor((2 * base[stat] + 31) * level / 100);
	return [scaled('hp') + level + 10, scaled('atk') + 5, scaled('def') + 5,
		scaled('spa') + 5, scaled('spd') + 5, scaled('spe') + 5];
}

function member(species, ability, moves, options = {}) {
	const level = options.level || 100;
	return {species, level, gender: options.gender || 'M', ability, item: '', moves,
		stats: stats(species, level), status: options.status || null,
		...(options.statusState ? {status_state: options.statusState} : {})};
}

function teamText(team) {
	return team.map(set => `${dex.species.get(set.species).name} (${set.gender})\n` +
		`Ability: ${dex.abilities.get(set.ability).name}\nLevel: ${set.level}\n` +
		`EVs: 1 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe\nHardy Nature\n` +
		`${set.moves.map(id => `- ${dex.moves.get(id).name}`).join('\n')}\n`).join('\n');
}

function emit(spec) {
	const sources = [`${spec.id}-p1.txt`, `${spec.id}-p2.txt`];
	for (let side = 0; side < 2; side++) {
		const text = teamText(spec.teams[side]);
		const errors = validator.validateTeam(Teams.import(text));
		if (errors) throw new Error(`${spec.id} p${side + 1}: ${errors.join('; ')}`);
		fs.writeFileSync(path.join(outputDir, sources[side]), text);
	}
	const fixture = normalizeCase({
		schema: 'pokemon-native-differential-case-v1', id: spec.id,
		provenance: {kind: 'showdown-derived',
			source_file: 'sim/battle-actions.ts; sim/battle.ts; data/moves.ts; data/abilities.ts',
			test_name: spec.description, oracle_revision: REVISION},
		format: 'gen3ou', seed: spec.seed,
		teams: spec.teams.map((team, side) => ({source: sources[side], normalized: team})),
		source_choices: spec.choices, choices: spec.choices,
		forced_outcomes: spec.forcedOutcomes || [],
		features: ['choice.move', 'prng.labeled', 'queue.move-priority', 'state.canonical',
			...(spec.features || [])],
		boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
		limits: {max_boundaries: spec.choices.length + 1,
			max_actions: spec.choices.length * 2},
	});
	fs.writeFileSync(path.join(outputDir, `${spec.id}.json`),
		`${JSON.stringify(fixture, null, 2)}\n`);
}

const smeargle = moves => member('smeargle', 'owntempo', moves);
const idle = (species, ability, move = 'rest') => member(species, ability, [move]);

for (const spec of [
	{
		id: 'drag-roar-one-eligible', seed: [101, 102, 103, 104],
		description: 'Roar deterministically drags the sole eligible bench member',
		teams: [[smeargle(['roar'])], [idle('snorlax', 'immunity'), idle('magikarp', 'swiftswim', 'splash')]],
		choices: [['move 1', 'move 1']],
	},
	{
		id: 'drag-whirlwind-multiple-eligible', seed: [111, 112, 113, 114],
		description: 'Whirlwind uniformly selects one of multiple eligible bench members',
		teams: [[smeargle(['whirlwind'])], [idle('snorlax', 'immunity'),
			idle('magikarp', 'swiftswim', 'splash'), idle('horsea', 'swiftswim', 'splash')]],
		choices: [['move 1', 'move 1']],
	},
	{
		id: 'drag-roar-no-eligible', seed: [121, 122, 123, 124],
		description: 'Roar cannot force a switch when the target has no eligible bench member',
		teams: [[smeargle(['roar'])], [idle('snorlax', 'immunity')]],
		choices: [['move 1', 'move 1']],
	},
	{
		id: 'drag-cancels-queued-move', seed: [131, 132, 133, 134],
		description: 'A faster equal-priority Roar cancels the dragged target queued Whirlwind',
		teams: [[smeargle(['roar'])], [member('smeargle', 'owntempo', ['whirlwind'], {level: 50}),
			idle('magikarp', 'swiftswim', 'splash')]],
		choices: [['move 1', 'move 1']],
	},
	{
		id: 'drag-entry-lifecycle-recombination', seed: [141, 142, 143, 144],
		description: 'Drag composes with Natural Cure, Spikes entry damage, and Intimidate',
		teams: [[smeargle(['spikes', 'roar'])], [
			member('blissey', 'naturalcure', ['softboiled'], {status: 'psn'}),
			member('mawile', 'intimidate', ['protect']),
		]],
		choices: [['move 1', 'move 1'], ['move 2', 'move 1']],
		features: ['ability.natural-cure', 'ability.intimidate', 'condition.side',
			'handler.entry-hazard', 'handler.switch-out', 'status.poison'],
	},
	{
		id: 'drag-suction-cups-block', seed: [151, 152, 153, 154],
		description: 'Suction Cups cancels DragOut before random bench selection',
		teams: [[smeargle(['roar'])], [idle('cradily', 'suctioncups'),
			idle('magikarp', 'swiftswim', 'splash')]],
		choices: [['move 1', 'move 1']],
	},
	{
		id: 'drag-ingrain-block', seed: [161, 162, 163, 164],
		description: 'Ingrain installs a volatile DragOut cancellation handler',
		teams: [[smeargle(['splash', 'roar'])], [member('roselia', 'naturalcure', ['ingrain', 'gigadrain']),
			idle('magikarp', 'swiftswim', 'splash')]],
		choices: [['move 1', 'move 1'], ['move 2', 'move 2']],
		features: ['condition.volatile'],
	},
]) emit(spec);

console.log('generated 7 drag/phazing differential fixtures');
