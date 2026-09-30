#!/usr/bin/env node
'use strict';

const childProcess = require('child_process');
const fs = require('fs');
const path = require('path');
const {normalizeCase} = require('./normalize');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
if (!process.argv[2]) throw new Error(
	'usage: node generate-transform-cases.js POKEMON_SHOWDOWN_DIR [OUTPUT_DIR]');
const showdownDir = path.resolve(process.argv[2]);
const outputDir = path.resolve(process.argv[3] || path.join(__dirname, 'derived'));
const revision = childProcess.execFileSync(
	'git', ['-C', showdownDir, 'rev-parse', 'HEAD'], {encoding: 'utf8'}).trim();
if (revision !== REVISION) throw new Error(`expected ${REVISION}, got ${revision}`);

const {Dex, Teams} = require(showdownDir);
const {TeamValidator} = require(path.join(showdownDir, 'dist/sim/team-validator'));
const dex = Dex.forGen(3);
const validator = TeamValidator.get('gen3ou');
const statNames = ['hp', 'atk', 'def', 'spa', 'spd', 'spe'];
const perfect = {hp: 31, atk: 31, def: 31, spa: 31, spd: 31, spe: 31};
const all30 = {hp: 30, atk: 30, def: 30, spa: 30, spd: 30, spe: 30};
fs.mkdirSync(outputDir, {recursive: true});

function calculatedStats(speciesID, ivs) {
	const base = dex.species.get(speciesID).baseStats;
	return [2 * base.hp + ivs.hp + 110,
		...statNames.slice(1).map(stat => 2 * base[stat] + ivs[stat] + 5)];
}

function member(species, ability, moves, ivs = perfect) {
	const resolved = dex.species.get(species);
	return {
		species, level: 100, gender: resolved.gender === 'N' ? 'N' : 'M',
		nature: 'hardy', ability, item: '', moves,
		stats: calculatedStats(species, ivs),
		...(ivs === perfect ? {} : {ivs: statNames.map(stat => ivs[stat])}),
		status: null,
	};
}

function teamText(team) {
	return team.map(set => {
		const ivs = Object.hasOwn(set, 'ivs') ?
			Object.fromEntries(statNames.map((stat, index) => [stat, set.ivs[index]])) : perfect;
		const moves = set.moves.map(id => id === 'hiddenpower' ?
			`Hidden Power [${dex.getHiddenPower(ivs).type}]` : dex.moves.get(id).name);
		const gender = set.gender === 'N' ? '' : ` (${set.gender})`;
		const ivLine = Object.hasOwn(set, 'ivs') ?
			`IVs: ${set.ivs[0]} HP / ${set.ivs[1]} Atk / ${set.ivs[2]} Def / ` +
			`${set.ivs[3]} SpA / ${set.ivs[4]} SpD / ${set.ivs[5]} Spe\n` : '';
		return `${dex.species.get(set.species).name}${gender}\n` +
			`Ability: ${dex.abilities.get(set.ability).name}\nLevel: 100\n` +
			'EVs: 1 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe\n' + ivLine +
			`Hardy Nature\n${moves.map(name => `- ${name}`).join('\n')}\n`;
	}).join('\n');
}

function writeCase(spec) {
	const sources = [`${spec.id}-p1.txt`, `${spec.id}-p2.txt`];
	for (let side = 0; side < 2; side++) {
		const source = teamText(spec.teams[side]);
		const errors = validator.validateTeam(Teams.import(source));
		if (errors) throw new Error(`${spec.id} p${side + 1}:\n${errors.join('\n')}`);
		fs.writeFileSync(path.join(outputDir, sources[side]), source);
	}
	const fixture = normalizeCase({
		schema: 'pokemon-native-differential-case-v1', id: spec.id,
		provenance: {
			kind: 'showdown-derived',
			source_file: 'data/moves.ts#transform; sim/pokemon.ts#transformInto; sim/pokemon.ts#clearVolatile',
			test_name: spec.description, oracle_revision: REVISION,
		},
		format: 'gen3ou', seed: spec.seed,
		teams: spec.teams.map((team, side) => ({source: sources[side], normalized: team})),
		source_choices: spec.sourceChoices || spec.choices,
		choices: spec.choices, forced_outcomes: [], features: spec.features,
		boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
		limits: {max_boundaries: spec.choices.length + 1,
			max_actions: spec.choices.length * 2},
	});
	fs.writeFileSync(path.join(outputDir, `${spec.id}.json`),
		`${JSON.stringify(fixture, null, 2)}\n`);
}

const cases = [
	{
		id: 'transform-substitute-hidden-power', seed: [131, 132, 133, 134],
		description: 'Gen 3 Transform bypasses Substitute and copies operative moves, PP, types, ability, boosts, and Hidden Power profile',
		teams: [
			[member('ditto', 'limber', ['transform'])],
			[member('alakazam', 'innerfocus',
				['substitute', 'hiddenpower', 'calmmind', 'recover'], all30)],
		],
		choices: [['move 1', 'move 1'], ['move 2', 'move 3']],
		features: ['choice.move', 'damage.gen3', 'hit.substitute', 'prng.labeled',
			'state.canonical', 'state.effective-type', 'state.transform-profile',
			'volatile.substitute'],
	},
	{
		id: 'transform-source-retransform', seed: [135, 136, 137, 138],
		description: 'a transformed source may use its copied Transform again in Gen 3',
		teams: [
			[member('ditto', 'limber', ['transform'])],
			[member('smeargle', 'owntempo', ['transform', 'splash']),
				member('gengar', 'levitate', ['nightshade'])],
		],
		choices: [['move 1', 'move 2'], ['move 1', 'switch 2']],
		features: ['choice.move', 'choice.switch', 'state.canonical',
			'state.effective-type', 'state.transform-profile'],
	},
	{
		id: 'transform-target-rejection', seed: [139, 140, 141, 142],
		description: 'Gen 3 Transform rejects an already-transformed target without copying its boosts',
		teams: [
			[member('smeargle', 'owntempo', ['transform', 'calmmind', 'splash'])],
			[member('ditto', 'limber', ['transform'])],
		],
		choices: [['move 3', 'move 1'], ['move 3', 'move 2'], ['move 1', 'move 3']],
		features: ['choice.move', 'effect.boost', 'prng.labeled', 'queue.speed',
			'state.canonical', 'state.transform-profile'],
	},
	{
		id: 'transform-ability-start-switch-reset', seed: [143, 144, 145, 146],
		description: 'copied Gen 3 abilities do not run Start and switching restores the immutable base profile',
		teams: [
			[member('ditto', 'limber', ['transform']),
				member('magikarp', 'swiftswim', ['splash'])],
			[member('gyarados', 'intimidate', ['splash'])],
		],
		choices: [['move 1', 'move 1'], ['switch 2', 'move 1'], ['switch 1', 'move 1']],
		sourceChoices: [['move 1', 'move 1'], ['switch 2', 'move 1'], ['switch 2', 'move 1']],
		features: ['ability.intimidate', 'choice.move', 'choice.switch',
			'lifecycle.boost-reset', 'state.canonical', 'state.effective-type',
			'state.transform-profile'],
	},
	{
		id: 'transform-forecast-freeze', seed: [147, 148, 149, 150],
		description: 'a transformed Forecast holder retains the copied current form across later weather changes',
		teams: [
			[member('ditto', 'limber', ['transform'])],
			[member('castform', 'forecast', ['sunnyday', 'raindance', 'rest'])],
		],
		choices: [['move 1', 'move 1'], ['move 3', 'move 2']],
		features: ['ability.forecast', 'choice.move', 'condition.weather',
			'prng.labeled', 'state.canonical', 'state.effective-type', 'state.form-overlay',
			'state.transform-profile'],
	},
];

for (const spec of cases) writeCase(spec);
process.stdout.write(`generated and legality-validated ${cases.length} Transform fixtures\n`);
