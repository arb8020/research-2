#!/usr/bin/env node
'use strict';

const childProcess = require('child_process');
const fs = require('fs');
const path = require('path');
const {normalizeCase} = require('./normalize');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
if (!process.argv[2]) throw new Error(
	'usage: node generate-jump-kick-cases.js POKEMON_SHOWDOWN_DIR [OUTPUT_DIR]');
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

function stats(speciesID, level) {
	const base = dex.species.get(speciesID).baseStats;
	const scaled = stat => Math.floor((2 * base[stat] + 31) * level / 100);
	return [scaled('hp') + level + 10, scaled('atk') + 5, scaled('def') + 5,
		scaled('spa') + 5, scaled('spd') + 5, scaled('spe') + 5];
}

function member(species, ability, moves, options = {}) {
	const level = options.level || 100;
	return {species, level, gender: options.gender || 'M', ability, item: '', moves,
		stats: stats(species, level), status: null,
		...(options.initialHP === undefined ? {} : {initial_hp: options.initialHP})};
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
			source_file: 'data/mods/gen3/moves.ts#jumpkick,highjumpkick; sim/battle-actions.ts#tryMoveHit',
			test_name: spec.description, oracle_revision: REVISION},
		format: 'gen3ou', seed: spec.seed || [1, 2, 3, 4],
		teams: spec.teams.map((team, side) => ({source: sources[side], normalized: team})),
		source_choices: spec.choices, choices: spec.choices,
		forced_outcomes: spec.forcedOutcomes || [],
		features: ['choice.move', 'effect.crash-damage', 'handler.move-fail',
			'hit.accuracy', 'prng.labeled', 'state.canonical', ...(spec.features || [])],
		boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng',
			...(spec.terminal ? ['terminal'] : [])],
		limits: {max_boundaries: spec.choices.length + 1,
			max_actions: spec.choices.flat().filter(Boolean).length},
	});
	fs.writeFileSync(path.join(outputDir, `${spec.id}.json`),
		`${JSON.stringify(fixture, null, 2)}\n`);
}

const smeargle = (moves, options = {}) => member('smeargle', 'owntempo', moves, options);
for (const spec of [
	{id: 'jump-kick-miss-cap-lethal',
		description: 'HJK miss crash is capped by target max HP and then source current HP',
		teams: [[smeargle(['highjumpkick'], {initialHP: 5})],
			[member('charmander', 'blaze', ['growl'], {level: 5})]],
		seed: [1, 2, 3, 2], choices: [['move 1', 'move 1']], terminal: true,
		forcedOutcomes: [{label: 'move.accuracy', occurrence: 1, range: 100, result: 99}],
		features: ['lifecycle.faint', 'lifecycle.terminal']},
	{id: 'jump-kick-protect', description: 'Protect invokes Jump Kick MoveFail and crash damage',
		teams: [[smeargle(['jumpkick'])], [member('persian', 'limber', ['protect'])]],
		choices: [['move 1', 'move 1']], features: ['handler.try-hit', 'volatile.protect']},
	{id: 'jump-kick-ghost-foresight',
		description: 'Ghost immunity suppresses crash until Foresight negates that immunity',
		teams: [[smeargle(['highjumpkick', 'foresight'])],
			[member('dusclops', 'pressure', ['rest'])]],
		seed: [1, 2, 3, 12],
		choices: [['move 1', 'move 1'], ['move 2', 'move 1'], ['move 1', 'move 1']],
		forcedOutcomes: [
			{label: 'move.accuracy', occurrence: 1, range: 100, result: 45},
			{label: 'move.accuracy', occurrence: 2, range: 100, result: 80},
			{label: 'move.accuracy', occurrence: 3, range: 100, result: 99}],
		features: ['condition.volatile', 'hit.type-immunity']},
	{id: 'jump-kick-dig', description: 'underground target failure invokes HJK crash damage',
		teams: [[smeargle(['highjumpkick'])], [member('persian', 'limber', ['dig'])]],
		choices: [['move 1', 'move 1']], features: ['handler.try-hit', 'move.charge']},
	{id: 'jump-kick-target-gone-cancel',
		description: 'faster Memento cancels queued HJK without MoveFail',
		teams: [[smeargle(['highjumpkick'], {level: 5})],
			[smeargle(['memento']), member('magikarp', 'swiftswim', ['splash'])]],
		choices: [['move 1', 'move 1']],
		features: ['lifecycle.faint', 'lifecycle.forced-replacement', 'request.legal-choices']},
]) writeCase(spec);

console.log('generated and legality-validated 5 Jump Kick fixtures');
