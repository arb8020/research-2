#!/usr/bin/env node
'use strict';

const cp = require('child_process');
const fs = require('fs');
const path = require('path');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const showdownDir = path.resolve(process.argv[2] || '');
if (!process.argv[2]) throw new Error('usage: generate-uproar-cases.js POKEMON_SHOWDOWN_DIR');
if (cp.execFileSync('git', ['-C', showdownDir, 'rev-parse', 'HEAD'], {
	encoding: 'utf8',
}).trim() !== REVISION) throw new Error('wrong Showdown revision');

const {Dex, Teams, TeamValidator} = require(showdownDir);
const {normalizeCase} = require('./normalize');
const dex = Dex.forGen(3);
const validator = new TeamValidator('gen3ou');
const out = path.join(__dirname, 'derived');

function stats(species, level = 100) {
	const data = dex.species.get(species);
	const scaled = stat => Math.floor((2 * data.baseStats[stat] + 31) * level / 100);
	return [scaled('hp') + level + 10, scaled('atk') + 5, scaled('def') + 5,
		scaled('spa') + 5, scaled('spd') + 5, scaled('spe') + 5];
}

function member(species, ability, moves, options = {}) {
	const level = options.level || 100;
	return {species, level, gender: options.gender || 'M', ability, item: '', moves,
		stats: stats(species, level), status: options.status || null,
		...(options.statusState ? {status_state: options.statusState} : {}),
		...(options.initialHP === undefined ? {} : {initial_hp: options.initialHP})};
}

function teamText(team) {
	return team.map(set => `${dex.species.get(set.species).name} (${set.gender})\n` +
		`Ability: ${dex.abilities.get(set.ability).name}\nLevel: ${set.level}\n` +
		`EVs: 1 HP\nHardy Nature\n` +
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
			source_file: 'data/moves.ts#uproar; data/mods/gen5/moves.ts#uproar; data/mods/gen4/moves.ts#uproar; data/mods/gen3/moves.ts#uproar',
			test_name: spec.description, oracle_revision: REVISION,
		},
		format: 'gen3ou', seed: spec.seed,
		teams: spec.teams.map((team, side) => ({source: sources[side], normalized: team})),
		source_choices: spec.choices, choices: spec.choices,
		forced_outcomes: spec.forcedOutcomes,
		features: ['choice.move', 'request.legal-choices', 'condition.volatile',
			'handler.try-hit', 'handler.set-status', 'handler.try',
			'lifecycle.condition-duration', 'prng.labeled', 'state.canonical',
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

emit({
	id: 'uproar-wake-rest-duration2-expiry',
	description: 'connected Uproar wakes a foe which just used Rest, locks its user, and naturally expires at duration two',
	seed: [4, 31, 17, 9],
	teams: [[smeargle(['quickattack', 'uproar'])],
		[member('persian', 'limber', ['growl', 'rest'])]],
	choices: [['move 1', 'move 1'], ['move 2', 'move 2'], ['move 1', 'move 1']],
	forcedOutcomes: [{label: 'condition.uproar.duration', occurrence: 1,
		range: 4, result: 0}],
	features: ['status.sleep'],
});

emit({
	id: 'uproar-duration5-rest-block',
	description: 'an installed Uproar globally rejects a faster foe Rest before status mutation or healing',
	seed: [28, 31, 17, 9],
	teams: [[smeargle(['uproar'])],
		[member('persian', 'limber', ['growl', 'rest'])]],
	choices: [['move 1', 'move 1'], ['move 1', 'move 2']],
	forcedOutcomes: [{label: 'condition.uproar.duration', occurrence: 1,
		range: 4, result: 3}],
	features: ['status.sleep', 'effect.heal'],
});

emit({
	id: 'uproar-protect-no-install',
	description: 'Protect cancels before Uproar move-owned TryHit, wake, duration draw, and installation',
	seed: [7, 31, 17, 9],
	teams: [[smeargle(['uproar'])],
		[member('persian', 'limber', ['protect'])]],
	choices: [['move 1', 'move 1']],
	forcedOutcomes: [],
	features: ['volatile.protect'],
});

emit({
	id: 'uproar-ghost-sleeper-immunity',
	description: 'Normal type immunity precedes move-owned Uproar TryHit, so a sleeping Ghost is not awakened',
	seed: [11, 31, 17, 9],
	teams: [[smeargle(['splash', 'uproar'])],
		[member('gengar', 'levitate', ['substitute', 'rest'])]],
	choices: [['move 1', 'move 1'], ['move 2', 'move 2']],
	forcedOutcomes: [],
	features: ['hit.type-immunity', 'status.sleep', 'volatile.substitute'],
});

emit({
	id: 'uproar-holder-sleep-nonsleep-recombination',
	description: 'global Uproar status prevention composes with holder Vital Spirit and Sleep Clause while non-sleep Toxic passes',
	seed: [201, 31, 17, 9],
	teams: [[member('vigoroth', 'vitalspirit', ['uproar']),
		member('magikarp', 'swiftswim', ['splash'], {
			status: 'slp', statusState: {kind: 'sleep', time: 5, skipped_time: 0},
		})], [smeargle(['spore', 'toxic'])]],
	choices: [['move 1', 'move 1'], ['move 1', 'move 2']],
	forcedOutcomes: [
		{label: 'condition.uproar.duration', occurrence: 1, range: 4, result: 2},
		{label: 'move.accuracy', occurrence: 4, range: 100, result: 52},
	],
	features: ['status.sleep', 'status.toxic', 'ability.vital-spirit', 'rule.sleep-clause'],
});

emit({
	id: 'uproar-forced-drag-silent-cleanup',
	description: 'Whirlwind drags an Uproar holder after its locked action and switch teardown removes Uproar without End',
	seed: [202, 31, 17, 9],
	teams: [[smeargle(['uproar']), member('magikarp', 'swiftswim', ['splash'])],
		[smeargle(['splash', 'whirlwind'])]],
	choices: [['move 1', 'move 1'], ['move 1', 'move 2']],
	forcedOutcomes: [
		{label: 'condition.uproar.duration', occurrence: 1, range: 4, result: 2},
		{label: 'drag.switch_candidate', occurrence: 1, range: 1, result: 0},
	],
	features: ['choice.switch', 'lifecycle.switch-persistence'],
});

emit({
	id: 'uproar-poison-faint-residual-order',
	description: 'poison residual faints an Uproar holder before Uproar upkeep and forced replacement observes silent volatile teardown',
	seed: [203, 31, 17, 9],
	teams: [[smeargle(['uproar'], {status: 'psn', initialHP: 1}),
		member('magikarp', 'swiftswim', ['splash'])],
		[member('blissey', 'naturalcure', ['softboiled'])]],
	choices: [['move 1', 'move 1'], ['switch 2', null]],
	forcedOutcomes: [{label: 'condition.uproar.duration', occurrence: 1, range: 4, result: 0}],
	features: ['status.poison', 'lifecycle.faint', 'lifecycle.forced-replacement'],
});

emit({
	id: 'uproar-accuracy-miss-no-wake',
	description: 'an accuracy-lowered Uproar misses a newly sleeping target without waking or installing its volatile',
	seed: [204, 31, 17, 9],
	teams: [[smeargle(['splash', 'uproar'], {level: 50})],
		[smeargle(['sandattack', 'rest'])]],
	choices: [['move 1', 'move 1'], ['move 2', 'move 2']],
	forcedOutcomes: [{label: 'move.accuracy', occurrence: 2, range: 100, result: 82}],
	features: ['hit.accuracy', 'status.sleep'],
});

emit({
	id: 'uproar-substitute-wakes-before-intercept',
	description: 'Uproar wakes its target in move-owned TryHit before Substitute intercepts damage',
	seed: [205, 31, 17, 9],
	teams: [[smeargle(['splash', 'uproar'])],
		[member('persian', 'limber', ['substitute', 'rest'])]],
	choices: [['move 1', 'move 1'], ['move 2', 'move 2']],
	forcedOutcomes: [{label: 'condition.uproar.duration', occurrence: 1, range: 4, result: 3}],
	features: ['status.sleep', 'volatile.substitute'],
});

emit({
	id: 'metronome-uproar-absent-slot-lock',
	description: 'Metronome delegates to absent-slot Uproar and the following request is forced to the called move',
	seed: [198, 31, 17, 9],
	teams: [[smeargle(['metronome'])],
		[member('blissey', 'naturalcure', ['softboiled'])]],
	choices: [['move 1', 'move 1'], ['move 1', 'move 1']],
	forcedOutcomes: [
		{label: 'move.delegation.selection', occurrence: 1, range: 336, result: 240},
		{label: 'condition.uproar.duration', occurrence: 1, range: 4, result: 3},
	],
	features: ['move.called-entry'],
});

emit({
	id: 'sleep-talk-excludes-uproar',
	description: 'Sleep Talk excludes both itself and nosleeptalk Uproar, while direct Uproar is unavailable during sleep',
	seed: [207, 31, 17, 9],
	teams: [[smeargle(['sleeptalk', 'uproar'], {
		status: 'slp', statusState: {kind: 'sleep', time: 5, skipped_time: 0},
	})], [member('blissey', 'naturalcure', ['softboiled'])]],
	choices: [['move 1', 'move 1']],
	forcedOutcomes: [],
	features: ['status.sleep', 'move.slot-delegation'],
});

console.log('generated and legality-validated 11 Uproar fixtures (27 boundaries)');
