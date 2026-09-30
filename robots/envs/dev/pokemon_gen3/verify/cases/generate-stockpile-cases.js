#!/usr/bin/env node
'use strict';

const cp = require('child_process');
const fs = require('fs');
const path = require('path');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const showdownDir = path.resolve(process.argv[2] || '');
if (!process.argv[2]) throw new Error('usage: generate-stockpile-cases.js POKEMON_SHOWDOWN_DIR');
if (cp.execFileSync('git', ['-C', showdownDir, 'rev-parse', 'HEAD'], {
	encoding: 'utf8',
}).trim() !== REVISION) throw new Error('wrong Showdown revision');

const {Dex, Teams, TeamValidator} = require(showdownDir);
const common = require(path.join(showdownDir, 'test/common')).gen(3);
const {normalizeCase} = require('./normalize');
const dex = Dex.forGen(3);
const validator = new TeamValidator('gen3ou');
const out = path.join(__dirname, 'derived');

function stats(species) {
	const base = dex.species.get(species).baseStats;
	const scaled = stat => 2 * base[stat] + 31;
	return [scaled('hp') + 110, scaled('atk') + 5, scaled('def') + 5,
		scaled('spa') + 5, scaled('spd') + 5, scaled('spe') + 5];
}

function member(species, ability, moves, gender = 'M', initialHP) {
	return {species, level: 100, gender, ability, item: '', moves,
		stats: stats(species), status: null,
		...(initialHP === undefined ? {} : {initial_hp: initialHP})};
}

function teamText(team) {
	return team.map(set => `${dex.species.get(set.species).name}${
		set.gender === 'N' ? '' : ` (${set.gender})`}\n` +
		`Ability: ${dex.abilities.get(set.ability).name}\nLevel: 100\n` +
		`EVs: 1 HP\nHardy Nature\n` +
		`${set.moves.map(move => `- ${dex.moves.get(move).name}`).join('\n')}\n`)
		.join('\n');
}

function emit(spec) {
	const sources = [`${spec.id}-p1.txt`, `${spec.id}-p2.txt`];
	const imported = [];
	for (let side = 0; side < 2; side++) {
		const text = teamText(spec.teams[side]);
		const team = Teams.import(text);
		const errors = validator.validateTeam(team);
		if (errors) throw new Error(`${spec.id} p${side + 1}: ${errors.join('; ')}`);
		imported.push(team);
		fs.writeFileSync(path.join(out, sources[side]), text);
	}
	const sourceChoices = spec.sourceChoices || spec.choices;
	const battle = common.createBattle({formatid: 'gen3ou', seed: spec.seed || [431, 73, 31, 11]}, imported);
	for (let turn = 0; turn < sourceChoices.length; turn++) {
		try {
			battle.makeChoices(sourceChoices[turn][0] || '', sourceChoices[turn][1] || '');
		} catch (error) {
			throw new Error(`${spec.id} source choice ${turn + 1}: ${error.message}`);
		}
	}
	const fixture = normalizeCase({
		schema: 'pokemon-native-differential-case-v1', id: spec.id,
		provenance: {
			kind: 'showdown-derived',
			source_file: 'data/moves.ts#stockpile,spitup,swallow; data/mods/gen4/moves.ts#swallow; data/mods/gen3/moves.ts#stockpile',
			test_name: spec.description, oracle_revision: REVISION,
		},
		format: 'gen3ou', seed: spec.seed || [431, 73, 31, 11],
		teams: spec.teams.map((team, side) => ({source: sources[side], normalized: team})),
		source_choices: sourceChoices, choices: spec.choices,
		forced_outcomes: spec.forcedOutcomes || [],
		features: ['choice.move', 'condition.volatile', 'handler.try',
			'lifecycle.condition-duration', 'state.canonical', 'prng.labeled',
			...(spec.features || [])],
		boundaries: ['request', 'choice', 'queue', 'handlers', 'immunity',
			'state', 'events', 'prng'],
		limits: {max_boundaries: spec.choices.length + 1,
			max_actions: spec.choices.length * 2},
	});
	fs.writeFileSync(path.join(out, `${spec.id}.json`),
		`${JSON.stringify(fixture, null, 2)}\n`);
}

const smeargle = (moves, initialHP) => member('smeargle', 'owntempo', moves, 'M', initialHP);
const blissey = moves => member('blissey', 'naturalcure', moves, 'F');

emit({
	id: 'stockpile-cap-spit-up',
	description: 'Gen 3 Stockpile caps at three without stat boosts; Spit Up consumes all layers',
	teams: [[smeargle(['stockpile', 'spitup'])], [blissey(['softboiled'])]],
	choices: [
		['move 1', 'move 1'], ['move 1', 'move 1'], ['move 1', 'move 1'],
		['move 1', 'move 1'], ['move 2', 'move 1'],
	],
	features: ['handler.base-power', 'handler.after-move'],
});

emit({
	id: 'spit-up-immune-consumes',
	description: 'Normal immunity still reaches Spit Up AfterMove and consumes Stockpile',
	teams: [[smeargle(['stockpile', 'spitup'])],
		[member('banette', 'insomnia', ['thief'])]],
	choices: [['move 1', 'move 1'], ['move 2', 'move 1'], ['move 2', 'move 1']],
	features: ['hit.immunity-cause', 'handler.after-move'],
});

for (const layers of [1, 2, 3]) {
	emit({
		id: `swallow-layer-${layers}`,
		description: `Swallow consumes ${layers} Stockpile layer${layers === 1 ? '' : 's'} and applies its exact Q12 heal`,
		teams: [[smeargle(['stockpile', 'swallow'], 1)], [blissey(['softboiled'])]],
		choices: [
			...Array.from({length: layers}, () => ['move 1', 'move 1']),
			['move 2', 'move 1'],
		],
		features: ['effect.heal', 'handler.try-heal'],
	});
}

emit({
	id: 'swallow-full-hp-cleanup',
	description: 'Swallow consumes Stockpile even when healing cannot increase full HP',
	teams: [[smeargle(['stockpile', 'swallow'])], [blissey(['softboiled'])]],
	choices: [['move 1', 'move 1'], ['move 2', 'move 1']],
	features: ['effect.heal', 'handler.try-heal'],
});

emit({
	id: 'stockpile-switch-clears',
	description: 'ordinary switch cleanup removes the noCopy Stockpile condition',
	teams: [[smeargle(['stockpile']), member('magikarp', 'swiftswim', ['splash'])],
		[blissey(['softboiled'])]],
	sourceChoices: [['move 1', 'move 1'], ['switch 2', 'move 1'], ['switch 2', 'move 1']],
	choices: [['move 1', 'move 1'], ['switch 2', 'move 1'], ['switch 1', 'move 1']],
	features: ['choice.switch', 'lifecycle.switch-persistence'],
});

emit({
	id: 'spit-up-without-stockpile',
	description: 'Spit Up fails before hit resolution when the user has no Stockpile condition',
	teams: [[smeargle(['spitup'])], [blissey(['softboiled'])]],
	choices: [['move 1', 'move 1']],
	features: [],
});

emit({
	id: 'swallow-without-stockpile',
	description: 'Gen 3 Swallow fails before healing when the user has no Stockpile condition',
	teams: [[smeargle(['swallow'], 1)], [blissey(['softboiled'])]],
	choices: [['move 1', 'move 1']],
	features: ['effect.heal'],
});

emit({
	id: 'metronome-spit-up-after-move',
	description: 'a called Spit Up owns its AfterMove cleanup at the generic invocation boundary',
	seed: [111, 73, 31, 11],
	teams: [[smeargle(['stockpile', 'metronome'])],
		[member('banette', 'insomnia', ['thief'])]],
	choices: [['move 1', 'move 1'], ['move 2', 'move 1']],
	forcedOutcomes: [{label: 'move.delegation.selection', occurrence: 1,
		range: 336, result: 242}],
	features: ['move.called-entry', 'handler.after-move', 'hit.immunity-cause'],
});

emit({
	id: 'snatch-stockpile-transfer',
	description: 'Snatch re-enters Stockpile with the snatcher as the condition owner',
	teams: [[smeargle(['stockpile'])],
		[member('alakazam', 'synchronize', ['snatch'], 'M')]],
	choices: [['move 1', 'move 1']],
	features: ['move.snatch', 'volatile.snatch', 'move.called-entry'],
});

emit({
	id: 'snatch-swallow-gen3-rejection',
	description: 'resolved Gen 3 Swallow rejects a snatcher without Stockpile and preserves the original user condition',
	teams: [[smeargle(['stockpile', 'swallow'], 1)],
		[member('alakazam', 'synchronize', ['recover', 'snatch'], 'M', 1)]],
	choices: [['move 1', 'move 1'], ['move 2', 'move 2']],
	features: ['move.snatch', 'volatile.snatch', 'move.called-entry', 'effect.heal'],
});

console.log('generated and legality-validated 12 Stockpile-family fixtures');
