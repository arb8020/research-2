#!/usr/bin/env node
'use strict';

const childProcess = require('child_process');
const fs = require('fs');
const path = require('path');
const {normalizeCase} = require('./normalize');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
if (!process.argv[2]) throw new Error(
	'usage: node generate-tri-attack-cases.js POKEMON_SHOWDOWN_DIR [OUTPUT_DIR]');
const showdownDir = path.resolve(process.argv[2]);
const outputDir = path.resolve(process.argv[3] || path.join(__dirname, 'derived'));
const revision = childProcess.execFileSync(
	'git', ['-C', showdownDir, 'rev-parse', 'HEAD'], {encoding: 'utf8'}).trim();
if (revision !== REVISION) throw new Error(`expected ${REVISION}, got ${revision}`);
const {Dex, Teams} = require(showdownDir);
const {TeamValidator} = require(path.join(showdownDir, 'dist/sim/team-validator'));
const dex = Dex.forGen(3);
const validator = TeamValidator.get('gen3ou');
fs.mkdirSync(outputDir, {recursive: true});

function stats(species, level = 100) {
	const base = dex.species.get(species).baseStats;
	const ordinary = stat => Math.floor((2 * base[stat] + 31) * level / 100) + 5;
	return [Math.floor((2 * base.hp + 31) * level / 100) + level + 10,
		ordinary('atk'), ordinary('def'), ordinary('spa'), ordinary('spd'), ordinary('spe')];
}

function member(species, ability, moves, options = {}) {
	const level = options.level || 100;
	return {species, level, gender: options.gender || 'M', nature: 'hardy', ability,
		item: '', moves, stats: stats(species, level), status: options.status || null,
		...(options.initial_hp === undefined ? {} : {initial_hp: options.initial_hp})};
}

function teamText(team) {
	return team.map(set => `${dex.species.get(set.species).name} (${set.gender})\n` +
		`Ability: ${dex.abilities.get(set.ability).name}\nLevel: ${set.level}\n` +
		'EVs: 1 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe\nHardy Nature\n' +
		set.moves.map(id => `- ${dex.moves.get(id).name}`).join('\n') + '\n').join('\n');
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
			source_file: 'data/moves.ts#triattack.secondary.onHit; sim/battle-actions.ts#secondaries',
			test_name: spec.description, oracle_revision: REVISION},
		format: 'gen3ou', seed: spec.seed,
		teams: spec.teams.map((team, side) => ({source: sources[side], normalized: team})),
		source_choices: spec.choices, choices: spec.choices,
		forced_outcomes: spec.forced_outcomes || [],
		features: ['choice.move', 'damage.gen3', 'effect.secondary', 'hit.accuracy',
			'prng.labeled', 'prng.secondary', 'state.canonical', ...(spec.features || [])],
		boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
		limits: {max_boundaries: spec.choices.length + 1,
			max_actions: spec.choices.flat().filter(Boolean).length},
	});
	fs.writeFileSync(path.join(outputDir, `${spec.id}.json`),
		`${JSON.stringify(fixture, null, 2)}\n`);
}

const porygon = () => member('porygon2', 'trace', ['triattack']);
const blissey = options => member('blissey', 'naturalcure', ['softboiled'], options);
const oneTurn = [['move 1', 'move 1']];
const cases = [
	{id: 'tri-attack-burn', description: 'Tri Attack selects burn after its secondary gate',
		seed: [1, 2, 3, 5], teams: [[porygon()], [blissey()]], choices: oneTurn,
		forced_outcomes: [{label: 'move.secondary', occurrence: 1, range: 100, result: 0},
			{label: 'move.status_selection', occurrence: 1, range: 3, result: 0}],
		features: ['condition.nonvolatile-status', 'status.burn']},
	{id: 'tri-attack-paralysis', description: 'Tri Attack selects paralysis after its secondary gate',
		seed: [1, 2, 3, 3], teams: [[porygon()], [blissey()]], choices: oneTurn,
		forced_outcomes: [{label: 'move.secondary', occurrence: 1, range: 100, result: 14},
			{label: 'move.status_selection', occurrence: 1, range: 3, result: 1}],
		features: ['condition.nonvolatile-status', 'status.paralysis']},
	{id: 'tri-attack-freeze', description: 'Tri Attack selects freeze after its secondary gate',
		seed: [1, 2, 3, 10], teams: [[porygon()], [blissey()]], choices: oneTurn,
		forced_outcomes: [{label: 'move.secondary', occurrence: 1, range: 100, result: 14},
			{label: 'move.status_selection', occurrence: 1, range: 3, result: 2}],
		features: ['condition.nonvolatile-status', 'status.freeze']},
	{id: 'tri-attack-secondary-fails', description: 'Tri Attack fails its base secondary gate without selecting a status',
		seed: [1, 2, 3, 1], teams: [[porygon()], [blissey()]], choices: oneTurn,
		forced_outcomes: [{label: 'move.secondary', occurrence: 1, range: 100, result: 29}]},
	{id: 'tri-attack-serene-grace', description: 'Serene Grace doubles Tri Attack secondary chance from 20 to 40',
		seed: [1, 2, 3, 1], teams: [[porygon()], [member('blissey', 'serenegrace', ['softboiled'])]],
		choices: oneTurn, features: ['ability.serenegrace', 'ability.trace',
			'condition.nonvolatile-status'],
		forced_outcomes: [{label: 'move.secondary', occurrence: 1, range: 100, result: 29},
			{label: 'move.status_selection', occurrence: 1, range: 3, result: 2}]},
	{id: 'tri-attack-shield-dust', description: 'Shield Dust removes Tri Attack secondary before either owned draw',
		seed: [1, 2, 3, 5], teams: [[porygon()], [member('dustox', 'shielddust', ['moonlight'])]],
		choices: oneTurn},
	{id: 'tri-attack-substitute', description: 'Substitute permits the secondary gate but blocks status selection',
		seed: [1, 2, 3, 5], teams: [[porygon()], [member('alakazam', 'synchronize', ['substitute', 'recover'])]],
		choices: [['move 1', 'move 1'], ['move 1', 'move 2']],
		forced_outcomes: [{label: 'move.secondary', occurrence: 1, range: 100, result: 0},
			{label: 'move.secondary', occurrence: 2, range: 100, result: 60}],
		features: ['hit.substitute', 'volatile.substitute']},
	{id: 'tri-attack-protect', description: 'Protect stops Tri Attack before damage and secondary work',
		seed: [1, 2, 3, 1], teams: [[porygon()], [member('milotic', 'marvelscale', ['protect'])]],
		choices: oneTurn, features: ['hit.protect', 'volatile.protect']},
	{id: 'tri-attack-ghost-immunity', description: 'Normal immunity stops Tri Attack before damage and secondary work',
		seed: [1, 2, 3, 1], teams: [[porygon()], [member('gengar', 'levitate', ['haze'])]],
		choices: oneTurn, features: ['hit.type-immunity', 'handler.immunity']},
	{id: 'tri-attack-status-rejected', description: 'Tri Attack selects a status before rejecting an already-statused target',
		seed: [1, 2, 3, 5], teams: [[porygon()], [blissey({status: 'par'})]], choices: oneTurn,
		forced_outcomes: [{label: 'move.secondary', occurrence: 1, range: 100, result: 0},
			{label: 'move.status_selection', occurrence: 1, range: 3, result: 0}],
		features: ['condition.nonvolatile-status', 'handler.set-status', 'status.paralysis']},
	{id: 'tri-attack-lethal', description: 'A lethal Tri Attack still owns secondary and status-selection draws',
		seed: [1, 2, 3, 5], teams: [[porygon()],
			[member('magikarp', 'swiftswim', ['splash'], {initial_hp: 1})]], choices: oneTurn,
		forced_outcomes: [{label: 'move.secondary', occurrence: 1, range: 100, result: 0},
			{label: 'move.status_selection', occurrence: 1, range: 3, result: 0}],
		features: ['condition.nonvolatile-status']},
];

for (const spec of cases) writeCase(spec);
console.log(`generated and legality-validated ${cases.length} Tri Attack fixtures`);
