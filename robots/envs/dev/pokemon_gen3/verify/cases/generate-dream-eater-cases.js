#!/usr/bin/env node
'use strict';

const childProcess = require('child_process');
const fs = require('fs');
const path = require('path');
const {normalizeCase} = require('./normalize');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
if (!process.argv[2]) throw new Error(
	'usage: node generate-dream-eater-cases.js POKEMON_SHOWDOWN_DIR [OUTPUT_DIR]');
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

function stats(species) {
	const base = dex.species.get(species).baseStats;
	const scaled = stat => 2 * base[stat] + 31;
	return [scaled('hp') + 110, scaled('atk') + 5, scaled('def') + 5,
		scaled('spa') + 5, scaled('spd') + 5, scaled('spe') + 5];
}

function member(species, ability, moves, status = null, initialHP) {
	return {species, level: 100, gender: 'M', ability, item: '', moves,
		stats: stats(species), status,
		...(initialHP === undefined ? {} : {initial_hp: initialHP}),
		...(status === 'slp' ? {
			status_state: {kind: 'sleep', time: 3, skipped_time: 0},
		} : {})};
}

function teamText(team) {
	return team.map(set => `${dex.species.get(set.species).name} (${set.gender})\n` +
		`Ability: ${dex.abilities.get(set.ability).name}\nLevel: 100\n` +
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
			source_file: 'data/moves.ts#dreameater; data/mods/gen4/moves.ts#dreameater; data/mods/gen4/abilities.ts#liquidooze; data/mods/gen3/scripts.ts#tryMoveHit; sim/battle.ts#damage,heal',
			test_name: spec.description, oracle_revision: REVISION},
		format: 'gen3ou', seed: spec.seed || [43, 19, 31, 11],
		teams: spec.teams.map((team, side) => ({source: sources[side], normalized: team})),
		source_choices: spec.choices, choices: spec.choices,
		forced_outcomes: spec.forcedOutcomes || [],
		features: ['choice.move', 'handler.immunity', 'effect.drain',
			'prng.labeled', 'state.canonical', ...(spec.features || [])],
		boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
		limits: {max_boundaries: spec.choices.length + 1,
			max_actions: spec.choices.flat().filter(Boolean).length},
	});
	fs.writeFileSync(path.join(outputDir, `${spec.id}.json`),
		`${JSON.stringify(fixture, null, 2)}\n`);
}

const dreamer = (moves = ['dreameater']) => member('gengar', 'levitate', moves);
for (const spec of [
	{id: 'dream-eater-awake-rejection',
		description: 'Dream Eater rejects an awake target before accuracy',
		teams: [[dreamer()], [member('magikarp', 'swiftswim', ['splash'])]],
		choices: [['move 1', 'move 1']]},
	{id: 'dream-eater-sleeping-target',
		description: 'Dream Eater damages a sleeping target and drains half the damage',
		teams: [[member('gengar', 'levitate', ['dreameater'], null, 50)],
			[member('smeargle', 'owntempo', ['splash'], 'slp')]],
		choices: [['move 1', 'move 1']]},
	{id: 'dream-eater-full-hp-user',
		description: 'Dream Eater still damages when its user cannot recover HP',
		teams: [[dreamer()], [member('smeargle', 'owntempo', ['splash'], 'slp')]],
		choices: [['move 1', 'move 1']], features: ['handler.try-heal']},
	{id: 'dream-eater-liquid-ooze-exception',
		description: 'Gen 3 Liquid Ooze excludes Dream Eater from drain reversal',
		teams: [[member('gengar', 'levitate', ['dreameater'], null, 50)],
			[member('tentacool', 'liquidooze', ['rest'], 'slp')]],
		choices: [['move 1', 'move 1']], features: ['handler.try-heal']},
	{id: 'dream-eater-dark-immunity',
		description: 'natural Psychic immunity rejects Dream Eater before its move predicate and accuracy',
		teams: [[dreamer()], [member('tyranitar', 'sandstream', ['protect'], 'slp')]],
		choices: [['move 1', 'move 1']], features: ['hit.type-immunity']},
	{id: 'dream-eater-protect',
		description: 'Protect rejects Dream Eater at target TryHit before move TryImmunity and accuracy',
		teams: [[dreamer()], [member('persian', 'limber', ['protect'])]],
		choices: [['move 1', 'move 1']],
		features: ['hit.protect', 'volatile.protect']},
	{id: 'dream-eater-substitute',
		description: 'Dream Eater rejects a sleeping target behind Substitute before accuracy',
		teams: [[dreamer()],
			[member('persian', 'limber', ['substitute', 'rest', 'growl'])]],
		choices: [['move 1', 'move 1'], ['move 1', 'move 2'], ['move 1', 'move 3']],
		features: ['hit.substitute', 'volatile.substitute', 'status.sleep']},
]) writeCase(spec);

console.log('generated and legality-validated 7 Dream Eater fixtures');
