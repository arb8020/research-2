#!/usr/bin/env node
'use strict';

const cp = require('child_process');
const fs = require('fs');
const path = require('path');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const showdownDir = path.resolve(process.argv[2] || '');
if (!process.argv[2]) throw new Error('usage: generate-bide-cases.js POKEMON_SHOWDOWN_DIR');
if (cp.execFileSync('git', ['-C', showdownDir, 'rev-parse', 'HEAD'], {
	encoding: 'utf8',
}).trim() !== REVISION) throw new Error('wrong Showdown revision');

const {Dex, Teams, TeamValidator} = require(showdownDir);
const {normalizeCase} = require('./normalize');
const dex = Dex.forGen(3);
const validator = new TeamValidator('gen3ou');
const out = path.join(__dirname, 'derived');

function stats(species, level = 100) {
	const base = dex.species.get(species).baseStats;
	const scaled = stat => Math.floor((2 * base[stat] + 31) * level / 100);
	return [scaled('hp') + level + 10, scaled('atk') + 5, scaled('def') + 5,
		scaled('spa') + 5, scaled('spd') + 5, scaled('spe') + 5];
}

function member(species, ability, moves, options = {}) {
	const level = options.level || 100;
	return {
		species, level, gender: options.gender || 'M', ability,
		item: options.item || '', moves, stats: stats(species, level),
		status: options.status || null,
		...(options.initialHP === undefined ? {} : {initial_hp: options.initialHP}),
	};
}

function teamText(team) {
	return team.map(set => `${dex.species.get(set.species).name} (${set.gender})\n` +
		`Ability: ${dex.abilities.get(set.ability).name}\n` +
		(set.item ? `Item: ${dex.items.get(set.item).name}\n` : '') +
		`Level: ${set.level}\nEVs: 1 HP\nHardy Nature\n` +
		`${set.moves.map(move => `- ${dex.moves.get(move).name}`).join('\n')}\n`)
		.join('\n');
}

function emit(spec) {
	const sources = [`${spec.id}-p1.txt`, `${spec.id}-p2.txt`];
	for (let side = 0; side < 2; side++) {
		const text = teamText(spec.teams[side]);
		const errors = validator.validateTeam(Teams.import(text));
		if (errors) throw new Error(`${spec.id} p${side + 1}: ${errors.join('; ')}`);
		fs.writeFileSync(path.join(out, sources[side]), text);
	}
	const fixture = normalizeCase({
		schema: 'pokemon-native-differential-case-v1', id: spec.id,
		provenance: {
			kind: 'showdown-derived',
			source_file: 'data/moves.ts:1261-1309; data/mods/gen3/moves.ts:57-101',
			test_name: spec.description, oracle_revision: REVISION,
		},
		format: 'gen3ou', seed: spec.seed,
		teams: spec.teams.map((team, side) => ({
			source: sources[side], normalized: team,
		})),
		source_choices: spec.choices,
		choices: spec.choices,
		forced_outcomes: spec.forcedOutcomes || [],
		features: ['choice.move', 'condition.volatile', 'handler.before-move',
			'handler.damage', 'handler.move-aborted', 'handler.try',
			'prng.labeled', 'state.canonical',
			...(spec.features || [])],
		boundaries: ['request', 'choice', 'queue', 'handlers', 'immunity',
			'state', 'events', 'prng'],
		limits: {max_boundaries: spec.choices.length + 1,
			max_actions: spec.choices.length * 2},
	});
	fs.writeFileSync(path.join(out, `${spec.id}.json`),
		`${JSON.stringify(fixture, null, 2)}\n`);
}

const smeargle = (moves, options) => member('smeargle', 'owntempo', moves, options);
const blissey = (moves, options = {}) =>
	member('blissey', 'naturalcure', moves, {...options, gender: 'F'});
const magikarp = moves => member('magikarp', 'swiftswim', moves);

emit({
	id: 'bide-core-additive', seed: [901, 23, 47, 71],
	description: 'Bide stores two requested move-damage relays, locks choices, spends PP once, and releases twice the sum',
	teams: [[smeargle(['bide'])], [blissey(['seismictoss', 'healbell'])]],
	choices: [['move 1', 'move 1'], ['move 1', 'move 1'], ['move 1', 'move 2']],
});

emit({
	id: 'bide-no-damage', seed: [902, 23, 47, 71],
	description: 'Bide with no captured move damage fails and removes itself without release accuracy',
	teams: [[smeargle(['bide'])], [blissey(['healbell'])]],
	choices: [['move 1', 'move 1'], ['move 1', 'move 1'], ['move 1', 'move 1']],
});

emit({
	id: 'bide-protect-release', seed: [903, 23, 47, 71],
	description: 'Bide release performs numeric accuracy before Protect blocks the constructed hit',
	teams: [[smeargle(['bide'])], [blissey(['seismictoss', 'healbell', 'protect'])]],
	choices: [['move 1', 'move 1'], ['move 1', 'move 2'], ['move 1', 'move 3']],
	features: ['volatile.protect'],
});

emit({
	id: 'bide-substitute-release', seed: [904, 23, 47, 71],
	description: 'Bide release routes fixed damage through Substitute interception',
	teams: [[smeargle(['bide'])], [blissey(['substitute', 'seismictoss', 'healbell'])]],
	choices: [['move 1', 'move 1'], ['move 1', 'move 2'], ['move 1', 'move 3']],
	features: ['volatile.substitute'],
});

emit({
	id: 'bide-ghost-immunity', seed: [905, 23, 47, 71],
	description: 'Bide release consumes numeric accuracy then respects Normal immunity',
	teams: [[smeargle(['bide'])], [member('banette', 'insomnia', ['thunderbolt', 'rest'])]],
	choices: [['move 1', 'move 1'], ['move 1', 'move 2'], ['move 1', 'move 2']],
});

emit({
	id: 'bide-source-switch-retarget', seed: [906, 23, 47, 71],
	description: 'Bide retargets the current foe when the last damage source switches out',
	teams: [[smeargle(['bide'])], [blissey(['seismictoss']), magikarp(['splash'])]],
	choices: [['move 1', 'move 1'], ['move 1', 'switch 2'], ['move 1', 'move 1']],
	features: ['choice.switch'],
});

emit({
	id: 'bide-forced-drag-cleanup', seed: [907, 23, 47, 71],
	description: 'forced drag clears the Bide volatile from the switched-out owner',
	teams: [[smeargle(['bide']), blissey(['healbell'])],
		[member('skarmory', 'keeneye', ['whirlwind'])]],
	choices: [['move 1', 'move 1']],
	forcedOutcomes: [{label: 'drag.switch_candidate', occurrence: 1,
		range: 1, result: 0}],
	features: ['choice.switch', 'lifecycle.switch-persistence'],
});

emit({
	id: 'bide-source-faint-retarget', seed: [908, 23, 47, 71],
	description: 'forced replacement does not tick Bide and release retargets after the recorded source faints',
	teams: [[smeargle(['bide'])], [
		blissey(['seismictoss'], {status: 'psn', initialHP: 1}),
		magikarp(['splash']),
	]],
	choices: [['move 1', 'move 1'], [null, 'switch 2'],
		['move 1', 'move 1'], ['move 1', 'move 1']],
	features: ['choice.switch', 'lifecycle.faint',
		'lifecycle.forced-replacement', 'status.poison'],
});

emit({
	id: 'bide-paralysis-abort', seed: [16, 23, 47, 71],
	description: 'full paralysis on a locked Bide turn invokes MoveAborted cleanup without another PP spend',
	teams: [[smeargle(['bide'], {status: 'par'})], [blissey(['healbell'])]],
	choices: [['move 1', 'move 1'], ['move 1', 'move 1']],
	features: ['status.paralysis'],
});

console.log('generated and legality-validated 9 Bide fixtures');
