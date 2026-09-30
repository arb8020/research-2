#!/usr/bin/env node
'use strict';

const childProcess = require('child_process');
const fs = require('fs');
const path = require('path');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
if (!process.argv[2]) {
	throw new Error('usage: node generate-curse-cases.js POKEMON_SHOWDOWN_DIR [OUTPUT_DIR]');
}
const showdownDir = path.resolve(process.argv[2]);
const outputDir = path.resolve(process.argv[3] || path.join(__dirname, 'derived'));
const actual = childProcess.execFileSync(
	'git', ['-C', showdownDir, 'rev-parse', 'HEAD'], {encoding: 'utf8'}).trim();
if (actual !== REVISION) throw new Error(`expected ${REVISION}, got ${actual}`);

const {Dex, Teams} = require(showdownDir);
const {TeamValidator} = require(path.join(showdownDir, 'dist/sim/team-validator'));
const {normalizeCase} = require('./normalize');
const dex = Dex.forGen(3);
const validator = TeamValidator.get('gen3ou');
fs.mkdirSync(outputDir, {recursive: true});

function stats(speciesID) {
	const base = dex.species.get(speciesID).baseStats;
	const scaled = stat => 2 * base[stat] + 31;
	return [scaled('hp') + 110, scaled('atk') + 5, scaled('def') + 5,
		scaled('spa') + 5, scaled('spd') + 5, scaled('spe') + 5];
}

function member(species, ability, moves, gender = 'M') {
	return {species, level: 100, gender, ability, item: '', moves,
		stats: stats(species), status: null};
}

function teamText(team) {
	return team.map(set => `${dex.species.get(set.species).name} (${set.gender})\n` +
		`Ability: ${dex.abilities.get(set.ability).name}\nLevel: 100\n` +
		'EVs: 1 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe\n' +
		'Hardy Nature\n' +
		`${set.moves.map(id => `- ${dex.moves.get(id).name}`).join('\n')}\n`).join('\n');
}

function writeCase(spec) {
	const sources = [`${spec.id}-p1.txt`, `${spec.id}-p2.txt`];
	for (let side = 0; side < 2; side++) {
		const text = teamText(spec.teams[side]);
		const errors = validator.validateTeam(Teams.import(text));
		if (errors) throw new Error(`${spec.id} p${side + 1}:\n${errors.join('\n')}`);
		fs.writeFileSync(path.join(outputDir, sources[side]), text);
	}
	const fixture = normalizeCase({
		schema: 'pokemon-native-differential-case-v1', id: spec.id,
		provenance: {
			kind: 'showdown-derived',
			source_file: 'data/moves.ts#curse; data/mods/gen4/moves.ts#curse; sim/battle-actions.ts; sim/pokemon.ts',
			test_name: spec.description,
			oracle_revision: REVISION,
		},
		format: 'gen3ou', seed: spec.seed,
		teams: spec.teams.map((team, side) => ({source: sources[side], normalized: team})),
		source_choices: spec.choices, choices: spec.choices, forced_outcomes: [],
		features: [
			'choice.move', 'choice.switch', 'condition.volatile',
			'handler.modify-move', 'state.canonical',
		],
		boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
		limits: {
			max_boundaries: spec.choices.length + 1,
			max_actions: spec.choices.flat().filter(Boolean).length,
		},
	});
	fs.writeFileSync(path.join(outputDir, `${spec.id}.json`),
		`${JSON.stringify(fixture, null, 2)}\n`);
}

const gengar = moves => member('gengar', 'levitate', moves);
const snorlax = moves => member('snorlax', 'immunity', moves);
const magikarp = moves => member('magikarp', 'swiftswim', moves);
const smeargle = moves => member('smeargle', 'owntempo', moves);
const blissey = moves => member('blissey', 'naturalcure', moves, 'F');

for (const spec of [
	{
		id: 'curse-nonghost-self-profile', seed: [601, 602, 603, 604],
		description: 'A non-Ghost Curse retargets its user and changes Attack, Defense, and Speed',
		teams: [[snorlax(['curse'])], [magikarp(['splash'])]],
		choices: [['move 1', 'move 1']],
	},
	{
		id: 'curse-ghost-lifecycle', seed: [611, 612, 613, 614],
		description: 'Ghost Curse installs before its half-HP payment and deals same-turn residual damage',
		teams: [[gengar(['curse'])], [magikarp(['splash'])]],
		choices: [['move 1', 'move 1']],
	},
	{
		id: 'curse-ghost-duplicate-rejects', seed: [621, 622, 623, 624],
		description: 'A duplicate Ghost Curse rejects before a second HP payment while the existing condition persists',
		teams: [[gengar(['curse'])], [magikarp(['splash'])]],
		choices: [['move 1', 'move 1'], ['move 1', 'move 1']],
	},
	{
		id: 'curse-ghost-substitute-block', seed: [631, 632, 633, 634],
		description: 'A preexisting Substitute blocks Ghost Curse without losing HP or charging the source',
		teams: [[gengar(['curse'])], [member('alakazam', 'synchronize', ['substitute'])]],
		choices: [['move 1', 'move 1']],
	},
	{
		id: 'curse-ghost-protect-nonblock', seed: [641, 642, 643, 644],
		description: 'Protect does not block Gen 3 Ghost Curse because its resolved flags omit protect',
		teams: [[gengar(['curse'])], [smeargle(['protect'])]],
		choices: [['move 1', 'move 1']],
	},
	{
		id: 'curse-target-switch-teardown', seed: [651, 652, 653, 654],
		description: 'Switching the cursed target removes Curse and does not transfer it to the replacement',
		teams: [[gengar(['curse', 'protect'])],
			[magikarp(['splash']), blissey(['pound'])]],
		choices: [['move 1', 'move 1'], ['move 2', 'switch 2']],
	},
	{
		id: 'curse-source-switch-independent', seed: [661, 662, 663, 664],
		description: 'Ghost Curse keeps damaging its target after the source switches out',
		teams: [[gengar(['curse']), blissey(['pound'])], [magikarp(['splash'])]],
		choices: [['move 1', 'move 1'], ['switch 2', 'move 1']],
	},
]) writeCase(spec);

console.log('generated and legality-validated 7 Curse fixtures');
