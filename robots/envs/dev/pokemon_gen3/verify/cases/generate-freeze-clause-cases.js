#!/usr/bin/env node
'use strict';

const cp = require('child_process');
const fs = require('fs');
const path = require('path');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const showdownDir = path.resolve(process.argv[2] || '');
if (!process.argv[2]) throw new Error('usage: generate-freeze-clause-cases.js POKEMON_SHOWDOWN_DIR');
if (cp.execFileSync('git', ['-C', showdownDir, 'rev-parse', 'HEAD'], {encoding: 'utf8'}).trim() !== REVISION) {
	throw new Error('wrong Showdown revision');
}

const {Dex, TeamValidator, Teams} = require(showdownDir);
const {normalizeCase} = require('./normalize');
const dex = Dex.forGen(3);
const validator = new TeamValidator('gen3ou');
const out = path.join(__dirname, 'derived');

function stats(speciesID) {
	const base = dex.species.get(speciesID).baseStats;
	const scaled = stat => 2 * base[stat] + 31;
	return [scaled('hp') + 110, scaled('atk') + 5, scaled('def') + 5,
		scaled('spa') + 5, scaled('spd') + 5, scaled('spe') + 5];
}

function member(species, ability, moves, status = null) {
	return {species, level: 100, gender: 'M', ability, item: '', moves,
		stats: stats(species), status};
}

function teamText(team) {
	return team.map(set => `${dex.species.get(set.species).name} (${set.gender})\n` +
		`Ability: ${dex.abilities.get(set.ability).name}\nLevel: 100\n` +
		'EVs: 1 HP\nHardy Nature\n' +
		`${set.moves.map(move => `- ${dex.moves.get(move).name}`).join('\n')}\n`).join('\n');
}

function emit(id, teams, choices, forcedOutcomes, testName, sourceChoices = choices) {
	const sources = [`${id}-p1.txt`, `${id}-p2.txt`];
	for (let side = 0; side < 2; side++) {
		const text = teamText(teams[side]);
		const errors = validator.validateTeam(Teams.import(text));
		if (errors) throw new Error(`${id} p${side + 1}: ${errors.join('; ')}`);
		fs.writeFileSync(path.join(out, sources[side]), text);
	}
	const fixture = normalizeCase({
		schema: 'pokemon-native-differential-case-v1', id,
		provenance: {
			kind: 'showdown-derived',
			source_file: 'data/rulesets.ts#freezeclausemod.onSetStatus',
			test_name: testName,
			oracle_revision: REVISION,
		},
		format: 'gen3ou', seed: [34, 509, 521,
			id === 'freeze-clause-cure-readmits' ? 3 : 523],
		teams: teams.map((team, side) => ({source: sources[side], normalized: team})),
		source_choices: sourceChoices, choices, forced_outcomes: forcedOutcomes,
		features: [
			'choice.move', 'choice.switch', 'condition.nonvolatile-status',
			'effect.secondary', 'prng.labeled', 'rule.freeze-clause',
			'state.canonical', 'status.freeze',
		],
		boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
		limits: {max_boundaries: choices.length + 1, max_actions: choices.length * 2},
	});
	fs.writeFileSync(path.join(out, `${id}.json`), `${JSON.stringify(fixture, null, 2)}\n`);
}

const attacker = () => member('smeargle', 'owntempo', ['icebeam', 'splash']);
const target = () => member('magikarp', 'swiftswim', ['splash']);
const frozenBench = () => member('blissey', 'naturalcure', ['pound'], 'frz');

emit('freeze-clause-first-foe-freeze', [[attacker()], [target()]],
	[['move 1', 'move 1']],
	[{label: 'move.secondary', occurrence: 1, range: 100, result: 5}],
	'Freeze Clause Mod admits the first foe-caused freeze');

emit('freeze-clause-frozen-bench-rejects', [[attacker()], [target(), frozenBench()]],
	[['move 1', 'move 1']],
	[{label: 'move.secondary', occurrence: 1, range: 100, result: 5}],
	'Freeze Clause Mod rejects foe-caused freeze when a benched teammate is frozen');

emit('freeze-clause-cure-readmits', [[attacker()], [frozenBench(), target()]],
	[['move 2', 'switch 2'], ['move 1', 'move 1']],
	[{label: 'move.secondary', occurrence: 1, range: 100, result: 7}],
	'Natural Cure removes the only freeze before a later foe-caused freeze is admitted',
	[['move 2', 'switch 2'], ['move 1', 'move 1']]);

console.log('generated and legality-validated 3 Freeze Clause fixtures');
