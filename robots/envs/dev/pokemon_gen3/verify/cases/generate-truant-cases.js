#!/usr/bin/env node
'use strict';

const childProcess = require('child_process');
const fs = require('fs');
const path = require('path');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
if (!process.argv[2]) throw new Error(
	'usage: node generate-truant-cases.js POKEMON_SHOWDOWN_DIR [OUTPUT_DIR]');
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

function member(species, ability, moves, options = {}) {
	return {species, level: 100, gender: options.gender || 'M', ability,
		item: '', moves, stats: stats(species), status: options.status || null,
		...(options.status === 'tox' ?
			{status_state: {kind: 'toxic', stage: 0}} : {}),
		...(options.initialHP === undefined ? {} : {initial_hp: options.initialHP})};
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
			source_file: 'data/mods/gen3/abilities.ts#truant; sim/battle.ts; sim/battle-actions.ts; sim/pokemon.ts',
			test_name: spec.description, oracle_revision: REVISION},
		format: 'gen3ou', seed: spec.seed,
		teams: spec.teams.map((team, side) =>
			({source: sources[side], normalized: team})),
		source_choices: spec.choices, choices: spec.choices, forced_outcomes: [],
		features: ['choice.move', 'choice.switch', 'handler.before-move',
			'handler.residual', 'lifecycle.switch-persistence', 'state.canonical'],
		boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
		limits: {max_boundaries: spec.choices.length + 1,
			max_actions: spec.choices.flat().filter(Boolean).length},
	});
	fs.writeFileSync(path.join(outputDir, `${spec.id}.json`),
		`${JSON.stringify(fixture, null, 2)}\n`);
}

const slaking = (moves = ['bulkup']) => member('slaking', 'truant', moves);
const blissey = () => member(
	'blissey', 'naturalcure', ['softboiled'], {gender: 'F'});
const smeargle = (moves = ['softboiled']) => member(
	'smeargle', 'owntempo', moves);
const aggron = () => member('aggron', 'sturdy', ['protect']);
const zigzagoon = options => member('zigzagoon', 'pickup', ['tackle'], options);

for (const spec of [
	{
		id: 'truant-basic-alternation', seed: [691, 692, 693, 694],
		description: 'Pinned Truant regression: a connected move is followed by a loafing turn',
		teams: [[slaking(['scratch'])], [blissey()]],
		choices: [['move 1', 'move 1'], ['move 1', 'move 1']],
	},
	{
		id: 'truant-opening-alternation', seed: [701, 702, 703, 704],
		description: 'Initial Truant phase acts, loafs, then acts across residual toggles',
		teams: [[slaking()], [blissey()]],
		choices: [['move 1', 'move 1'], ['move 1', 'move 1'], ['move 1', 'move 1']],
	},
	{
		id: 'truant-voluntary-switch-entry', seed: [711, 712, 713, 714],
		description: 'A mid-turn Truant SwitchIn initializes true before the same residual toggles false',
		teams: [[zigzagoon(), slaking()], [blissey()]],
		choices: [['switch 2', 'move 1'], ['move 1', 'move 1']],
	},
	{
		id: 'truant-post-residual-replacement', seed: [721, 722, 723, 724],
		description: 'A post-residual forced replacement receives no second toggle and loafs first',
		teams: [[zigzagoon({status: 'tox', initialHP: 1}), slaking()], [blissey()]],
		choices: [['move 1', 'move 1'], ['switch 2', null], ['move 1', 'move 1']],
	},
	{
		id: 'truant-recharge-staging', seed: [731, 732, 733, 734],
		description: 'Pinned Truant regression: recharge occupies the loafing phase and the next move executes',
		teams: [[slaking(['hyperbeam'])], [aggron()]],
		choices: [['move 1', 'move 1'], ['move 1', 'move 1'], ['move 1', 'move 1']],
	},
	{
		id: 'truant-wake-after-acting-turn', seed: [741, 742, 743, 744],
		description: 'Pinned Truant regression: Rest on an acting phase leaves the waking phase loafing',
		teams: [[slaking(['rest', 'scratch'])], [blissey()]],
		choices: [['move 1', 'move 1'], ['move 2', 'move 1'],
			['move 2', 'move 1'], ['move 2', 'move 1']],
	},
	{
		id: 'truant-wake-after-loafing-turn', seed: [751, 752, 753, 754],
		description: 'Pinned Truant regression: sleep installed on a loafing phase permits the waking action',
		teams: [[slaking(['bulkup', 'scratch'])], [smeargle(['softboiled', 'spore'])]],
		choices: [['move 1', 'move 1'], ['move 1', 'move 2'],
			['move 2', 'move 1'], ['move 2', 'move 1'], ['move 2', 'move 1'],
			['move 2', 'move 1'], ['move 2', 'move 1']],
	},
	{
		id: 'truant-two-turn-move-failure', seed: [761, 762, 763, 764],
		description: 'Pinned Truant regression: the loafing phase cancels a charged two-turn move release',
		teams: [[slaking(['solarbeam'])], [blissey()]],
		choices: [['move 1', 'move 1'], ['move 1', 'move 1']],
	},
]) writeCase(spec);

console.log('generated and legality-validated 8 Truant fixtures');
