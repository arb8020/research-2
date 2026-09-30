#!/usr/bin/env node
'use strict';

const childProcess = require('child_process');
const fs = require('fs');
const path = require('path');
const {normalizeCase} = require('./normalize');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
if (!process.argv[2]) throw new Error(
	'usage: node generate-checkpoint7-small-cases.js POKEMON_SHOWDOWN_DIR [OUTPUT_DIR]');
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
	return {species, level, gender: options.gender || 'M', ability,
		item: options.item || '', moves, stats: stats(species, level), status: null};
}

function teamText(team) {
	return team.map(set => `${dex.species.get(set.species).name} (${set.gender})` +
		(set.item ? ` @ ${dex.items.get(set.item).name}` : '') + '\n' +
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
		provenance: {kind: 'showdown-derived', source_file: spec.source,
			test_name: spec.description, oracle_revision: REVISION},
		format: 'gen3ou', seed: spec.seed || [1, 2, 3, 4],
		teams: spec.teams.map((team, side) => ({source: sources[side], normalized: team})),
		source_choices: spec.choices, choices: spec.choices,
		forced_outcomes: spec.forcedOutcomes || [],
		features: ['choice.move', 'prng.labeled', 'state.canonical', ...(spec.features || [])],
		boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
		limits: {max_boundaries: spec.choices.length + 1,
			max_actions: spec.choices.flat().filter(Boolean).length},
	});
	fs.writeFileSync(path.join(outputDir, `${spec.id}.json`),
		`${JSON.stringify(fixture, null, 2)}\n`);
}

for (const spec of [
	{
		id: 'clear-body-negative-cap-order',
		description: 'a boost already at -6 rejects before Clear Body prevention',
		source: 'test/sim/abilities/clearbody.js:86; data/abilities.ts#clearbody',
		teams: [[member('registeel', 'clearbody', ['curse', 'rest'])],
			[member('smeargle', 'owntempo', ['splash', 'scaryface'])]],
		choices: [
			...Array.from({length: 6}, () => ['move 1', 'move 1']),
			['move 2', 'move 2'],
		],
		features: ['effect.boost', 'handler.try-boost'],
	},
	{
		id: 'rock-head-does-not-block-crash',
		description: 'Rock Head does not suppress protected Jump Kick crash damage',
		source: 'test/sim/abilities/rockhead.js:35; data/mods/gen3/moves.ts#jumpkick',
		teams: [[member('sudowoodo', 'rockhead', ['mimic'])],
			[member('hitmonlee', 'limber', ['jumpkick', 'protect'])]],
		choices: [['move 1', 'move 1'], ['move 1', 'move 2']],
		features: ['effect.crash-damage', 'handler.rock-head', 'volatile.protect'],
	},
	{
		id: 'rock-head-does-not-block-indirect',
		description: 'Rock Head does not suppress toxic residual damage',
		source: 'test/sim/abilities/rockhead.js:42; data/abilities.ts#rockhead',
		teams: [[member('sudowoodo', 'rockhead', ['mimic'])],
			[member('crobat', 'innerfocus', ['toxic'])]],
		seed: [1, 2, 3, 12],
		choices: [['move 1', 'move 1']],
		features: ['damage.residual', 'handler.rock-head', 'status.toxic'],
	},
	{
		id: 'mail-knock-off-removal',
		description: 'Gen 3 Knock Off removes Mail despite its transfer restrictions',
		source: 'test/sim/items/mail.js:37; data/mods/gen3/moves.ts#knockoff',
		teams: [[member('sableye', 'keeneye', ['knockoff'])],
			[member('tyrogue', 'guts', ['tackle'], {item: 'mail'})]],
		choices: [['move 1', 'move 1']],
		features: ['handler.take-item', 'item.take'],
	},
	{
		id: 'substitute-routing-product',
		description: 'sound damage, self-targeting moves, and foe-side hazards route independently around Substitute',
		source: 'data/mods/gen4/moves.ts#substitute; sim/battle-actions.ts#spreadMoveHit',
		teams: [[member('smeargle', 'owntempo', ['hypervoice', 'spikes'])],
			[member('alakazam', 'synchronize', ['substitute', 'calmmind'])]],
		choices: [['move 1', 'move 1'], ['move 2', 'move 2']],
		features: ['condition.side', 'effect.boost', 'side.spikes',
			'volatile.substitute'],
	},
]) writeCase(spec);

console.log('generated and legality-validated 5 Checkpoint 7 regression fixtures');
