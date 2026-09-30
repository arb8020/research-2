#!/usr/bin/env node
'use strict';

const childProcess = require('child_process');
const fs = require('fs');
const path = require('path');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
if (!process.argv[2]) throw new Error(
	'usage: node generate-pain-split-cases.js POKEMON_SHOWDOWN_DIR [OUTPUT_DIR]');
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
	return [speciesID === 'shedinja' ? 1 : scaled('hp') + 110,
		scaled('atk') + 5, scaled('def') + 5,
		scaled('spa') + 5, scaled('spd') + 5, scaled('spe') + 5];
}

function member(species, ability, moves, initialHP) {
	return {species, level: 100, gender: 'M', ability, item: '', moves,
		stats: stats(species), status: null,
		...(initialHP === undefined ? {} : {initial_hp: initialHP})};
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
		provenance: {kind: 'showdown-derived',
			source_file: 'data/moves.ts#painsplit; sim/battle-actions.ts; sim/pokemon.ts#sethp',
			test_name: spec.description, oracle_revision: REVISION},
		format: 'gen3ou', seed: spec.seed,
		teams: spec.teams.map((team, side) => ({source: sources[side], normalized: team})),
		source_choices: spec.choices, choices: spec.choices, forced_outcomes: [],
		features: ['choice.move', 'hit.protect', 'hit.substitute', 'state.canonical'],
		boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
		limits: {max_boundaries: spec.choices.length + 1,
			max_actions: spec.choices.flat().filter(Boolean).length},
	});
	fs.writeFileSync(path.join(outputDir, `${spec.id}.json`),
		`${JSON.stringify(fixture, null, 2)}\n`);
}

const dusclops = hp => member('dusclops', 'pressure', ['painsplit'], hp);
const blissey = hp => member('blissey', 'naturalcure', ['softboiled'], hp);

for (const spec of [
	{
		id: 'pain-split-odd-floor', seed: [801, 802, 803, 804],
		description: 'Pain Split snapshots an odd HP sum and floors one shared average',
		teams: [[dusclops(101)], [blissey(200)]], choices: [['move 1', 'move 1']],
	},
	{
		id: 'pain-split-source-max-clamp', seed: [811, 812, 813, 814],
		description: 'Pain Split independently clamps the lower-maximum source',
		teams: [[dusclops(221)], [blissey(600)]], choices: [['move 1', 'move 1']],
	},
	{
		id: 'pain-split-shedinja-target-clamp', seed: [821, 822, 823, 824],
		description: 'Pain Split bypasses Wonder Guard and clamps Shedinja to one HP',
		teams: [[dusclops(219)], [member('shedinja', 'wonderguard', ['swordsdance'], 1)]],
		choices: [['move 1', 'move 1']],
	},
	{
		id: 'pain-split-protect-block', seed: [831, 832, 833, 834],
		description: 'Protect prevents the Pain Split hit callback and both assignments',
		teams: [[dusclops(101)], [member('aggron', 'sturdy', ['protect'], 200)]],
		choices: [['move 1', 'move 1']],
	},
	{
		id: 'pain-split-substitute-block', seed: [841, 842, 843, 844],
		description: 'An intact Substitute prevents Pain Split from assigning real HP',
		teams: [[dusclops(101)], [member('alakazam', 'synchronize', ['substitute'], 250)]],
		choices: [['move 1', 'move 1']],
	},
	{
		id: 'pain-split-equal-hp', seed: [851, 852, 853, 854],
		description: 'Equal HP is a successful zero-delta Pain Split callback',
		teams: [[dusclops(100)], [blissey(100)]], choices: [['move 1', 'move 1']],
	},
]) writeCase(spec);

console.log('generated and legality-validated 6 Pain Split fixtures');
