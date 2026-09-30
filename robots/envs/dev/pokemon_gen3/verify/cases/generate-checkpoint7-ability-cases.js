#!/usr/bin/env node
'use strict';

const childProcess = require('child_process');
const fs = require('fs');
const path = require('path');
const {normalizeCase} = require('./normalize');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const showdownDir = path.resolve(process.argv[2] || '');
const outputDir = path.resolve(process.argv[3] || path.join(__dirname, 'derived'));
if (!process.argv[2]) {
	throw new Error('usage: node generate-checkpoint7-ability-cases.js POKEMON_SHOWDOWN_DIR [OUTPUT_DIR]');
}
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
		features: ['prng.labeled', 'state.canonical', ...(spec.features || [])],
		boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
		limits: {max_boundaries: spec.choices.length + 1,
			max_actions: spec.choices.flat().filter(Boolean).length},
	});
	fs.writeFileSync(path.join(outputDir, `${spec.id}.json`),
		`${JSON.stringify(fixture, null, 2)}\n`);
}

for (const spec of [
	{
		id: 'immunity-skill-swap-cure',
		description: 'a poisoned Pokemon is cured after Skill Swap gives it Immunity',
		source: 'test/sim/abilities/immunity.js:22; data/abilities.ts#immunity',
		seed: [1, 2, 3, 12],
		teams: [[member('alakazam', 'innerfocus', ['skillswap', 'calmmind'])],
			[member('snorlax', 'immunity', ['toxic', 'rest'])]],
		choices: [['move 2', 'move 1'], ['move 1', 'move 2']],
		features: ['choice.move', 'handler.immunity', 'handler.update', 'move.skill-swap',
			'status.toxic'],
	},
	{
		id: 'thief-target-faint-transfer',
		description: 'Thief transfers the target item even when its hit faints the target',
		source: 'test/sim/abilities/magician.js:23 (shared post-hit item-transfer operation); data/moves.ts#thief',
		teams: [[member('sableye', 'keeneye', ['thief'])],
			[member('abra', 'synchronize', ['teleport'], {level: 1, item: 'leftovers'}),
				member('magikarp', 'swiftswim', ['splash'])]],
		choices: [['move 1', 'move 1']],
		features: ['choice.move', 'lifecycle.faint', 'handler.take-item', 'item.take'],
	},
	{
		id: 'magnet-pull-baton-pass-escape',
		description: 'a Steel target trapped by Magnet Pull can still leave through Baton Pass',
		source: 'test/sim/abilities/magnetpull.js:32; data/abilities.ts#magnetpull',
		seed: [1, 2, 3, 12],
		teams: [[member('magneton', 'magnetpull', ['toxic'])],
			[member('scizor', 'swarm', ['batonpass']), member('tentacruel', 'clearbody', ['rapidspin'])]],
		choices: [['move 1', 'move 1'], [null, 'switch 2']],
		features: ['ability.magnetpull', 'choice.switch', 'handler.trap-pokemon',
			'lifecycle.forced-replacement', 'request.legal-choices'],
	},
	{
		id: 'pressure-magic-coat-no-double-deduction',
		description: 'a Magic Coat reflected move does not deduct its unused local slot or a second source PP',
		source: 'test/sim/abilities/pressure.js:172; sim/battle-actions.ts#useMoveInner',
		teams: [[member('spoink', 'owntempo', ['magiccoat', 'confuseray'])],
			[member('dusclops', 'pressure', ['confuseray'])]],
		choices: [['move 1', 'move 1']],
		features: ['ability.pressure', 'choice.move', 'handler.deduct-pp', 'move.magic-coat'],
	},
]) writeCase(spec);

console.log('generated and legality-validated 4 Checkpoint 7 ability fixtures');
