#!/usr/bin/env node
'use strict';

const childProcess = require('child_process');
const fs = require('fs');
const path = require('path');
const {normalizeCase} = require('./normalize');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
if (!process.argv[2]) throw new Error(
	'usage: node generate-checkpoint7-item-cases.js POKEMON_SHOWDOWN_DIR [OUTPUT_DIR]');
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
		item: options.item || '', moves, stats: stats(species, level), status: null,
		...(options.initialHP === undefined ? {} : {initial_hp: options.initialHP})};
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
		id: 'quick-claw-induced-speed-tie',
		description: 'one shared Quick Claw activation places unequal natural speeds in a tie bracket',
		source: 'test/sim/items/quickclaw.js:30; data/mods/gen3/items.ts#quickclaw',
		seed: [1, 2, 3, 3],
		teams: [[member('smeargle', 'owntempo', ['splash'], {item: 'quickclaw'})],
			[member('magikarp', 'swiftswim', ['splash'], {item: 'quickclaw'})]],
		choices: [['move 1', 'move 1']],
		forcedOutcomes: [{label: 'turn.quick_claw', occurrence: 1, range: 5, result: 0}],
		features: ['item.quick-claw', 'queue.speed'],
	},
	{
		id: 'synchronize-before-lum-berry',
		description: 'Synchronize reflection completes before either Lum Berry update consumes',
		source: 'test/sim/abilities/synchronize.js:13; data/abilities.ts#synchronize; data/items.ts#lumberry',
		teams: [[member('alakazam', 'synchronize', ['thunderwave'], {item: 'lumberry'})],
			[member('umbreon', 'synchronize', ['moonlight'], {item: 'lumberry'})]],
		choices: [['move 1', 'move 1']],
		features: ['condition.nonvolatile-status', 'handler.update', 'item.consumption', 'status.paralysis'],
	},
	{
		id: 'thick-fat-type-item-composition',
		description: 'Never-Melt Ice source modifier composes with target-side Thick Fat',
		source: 'test/sim/abilities/thickfat.js:27; data/mods/gen3/abilities.ts#thickfat',
		teams: [[member('alakazam', 'synchronize', ['icepunch'], {item: 'nevermeltice'})],
			[member('snorlax', 'thickfat', ['tackle'])]],
		choices: [['move 1', 'move 1']],
		features: ['handler.thick-fat', 'handler.type-boost-item'],
	},
	{
		id: 'sitrus-knock-off-before-residual',
		description: 'Knock Off removes Sitrus before its same-turn residual threshold check',
		source: 'test/sim/items/sitrusberry.js:35; data/mods/gen3/items.ts#sitrusberry',
		teams: [[member('sableye', 'keeneye', ['knockoff'])],
			[member('tyrogue', 'guts', ['tackle'], {item: 'sitrusberry', initialHP: 100})]],
		choices: [['move 1', 'move 1']],
		features: ['handler.take-item', 'item.consumption', 'item.take'],
	},
	{
		id: 'sitrus-status-residual-deferral',
		description: 'Toxic crossing half HP after the Sitrus check defers consumption one residual pass',
		source: 'test/sim/items/sitrusberry.js:69; data/mods/gen3/items.ts#sitrusberry',
		seed: [1, 2, 3, 12],
		teams: [[member('swampert', 'torrent', ['sleeptalk'], {item: 'sitrusberry'})],
			[member('charizard', 'blaze', ['toxic'])]],
		choices: Array.from({length: 5}, () => ['move 1', 'move 1']),
		features: ['damage.residual', 'handler.residual', 'item.consumption', 'status.toxic'],
	},
]) writeCase(spec);

console.log('generated and legality-validated 5 Checkpoint 7 item/order fixtures');
