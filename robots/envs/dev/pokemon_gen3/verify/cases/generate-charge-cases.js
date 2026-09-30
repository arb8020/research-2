#!/usr/bin/env node
'use strict';

const cp = require('child_process');
const fs = require('fs');
const path = require('path');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const showdownDir = path.resolve(process.argv[2] || '');
if (!process.argv[2]) {
	throw new Error('usage: generate-charge-cases.js POKEMON_SHOWDOWN_DIR');
}
if (cp.execFileSync('git', ['-C', showdownDir, 'rev-parse', 'HEAD'], {
	encoding: 'utf8',
}).trim() !== REVISION) throw new Error('wrong Showdown revision');

const {Dex, Teams, TeamValidator} = require(showdownDir);
const {normalizeCase} = require('./normalize');
const dex = Dex.forGen(3);
const validator = new TeamValidator('gen3ou');
const out = path.join(__dirname, 'derived');

function stats(species, speedEvs = 0) {
	const base = dex.species.get(species).baseStats;
	const value = stat => Math.floor(2 * base[stat] + 31 +
		Math.floor((stat === 'spe' ? speedEvs : 0) / 4));
	return [value('hp') + 110, value('atk') + 5, value('def') + 5,
		value('spa') + 5, value('spd') + 5, value('spe') + 5];
}

function member(species, ability, moves, gender, speedEvs = 0, initialHp) {
	const result = {
		species, level: 100, gender, nature: 'hardy', ability, item: '', moves,
		stats: stats(species, speedEvs), status: null,
	};
	if (initialHp !== undefined) result.initial_hp = initialHp;
	return result;
}

function teamText(team) {
	return team.map(set => {
		const evs = set.stats[5] !== stats(set.species)[5] ?
			'EVs: 1 HP / 252 Spe\n' : 'EVs: 1 HP\n';
		return `${dex.species.get(set.species).name} (${set.gender})\n` +
			`Ability: ${dex.abilities.get(set.ability).name}\nLevel: 100\n${evs}` +
			`Hardy Nature\n${set.moves.map(move =>
				`- ${dex.moves.get(move).name}`).join('\n')}\n`;
	}).join('\n');
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
			source_file: 'data/moves.ts:2261-2302; data/mods/gen3/moves.ts:116-119',
			test_name: spec.description, oracle_revision: REVISION,
		},
		format: 'gen3ou', seed: spec.seed,
		teams: spec.teams.map((team, side) => ({
			source: sources[side], normalized: team,
		})),
		source_choices: spec.choices,
		choices: spec.nativeChoices || spec.choices,
		forced_outcomes: spec.forcedOutcomes || [],
		features: ['choice.move', 'condition.volatile', 'handler.base-power',
			'handler.after-move', 'state.canonical', 'prng.labeled',
			'move.charge', 'volatile.charge', ...(spec.features || [])],
		boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
		limits: {max_boundaries: spec.choices.length + 1,
			max_actions: spec.choices.length * 2},
	});
	fs.writeFileSync(path.join(out, `${spec.id}.json`),
		`${JSON.stringify(fixture, null, 2)}\n`);
}

const fastSmeargle = moves => member('smeargle', 'owntempo', moves, 'M', 252);
const smeargle = (moves, initialHp) =>
	member('smeargle', 'owntempo', moves, 'M', 0, initialHp);
const blissey = moves => member('blissey', 'naturalcure', moves, 'F');
const magikarp = moves => member('magikarp', 'swiftswim', moves, 'M');

emit({
	id: 'charge-gen3-electric-base-power', seed: [811, 23, 47, 71],
	description: 'Gen 3 Charge doubles the next Electric move without a SpD boost',
	teams: [[fastSmeargle(['charge', 'thunderbolt'])], [blissey(['softboiled'])]],
	choices: [['move 1', 'move 1'], ['move 2', 'move 1']],
});

emit({
	id: 'charge-gen3-any-move-and-electric-status', seed: [812, 23, 47, 71],
	description: 'resolved Gen 3 consumes Charge after any non-Charge move, including Electric status moves',
	teams: [[fastSmeargle(['charge', 'tackle', 'thunderwave'])], [blissey(['softboiled'])]],
	choices: [['move 1', 'move 1'], ['move 2', 'move 1'],
		['move 1', 'move 1'], ['move 3', 'move 1']],
	features: ['status.paralysis'],
});

emit({
	id: 'charge-gen3-restart', seed: [813, 23, 47, 71],
	description: 'Charge restarts without duplicating before Electric consumption',
	teams: [[fastSmeargle(['charge', 'thunderbolt'])], [blissey(['softboiled'])]],
	choices: [['move 1', 'move 1'], ['move 1', 'move 1'], ['move 2', 'move 1']],
});

emit({
	id: 'charge-gen3-move-aborted', seed: [1, 23, 47, 71],
	description: 'a fully paralyzed Electric move consumes Charge through MoveAborted',
	teams: [[fastSmeargle(['charge', 'thunderbolt'])],
		[blissey(['thunderwave', 'softboiled'])]],
	choices: [['move 1', 'move 1'], ['move 2', 'move 2']],
	forcedOutcomes: [{label: 'status.paralysis.before_move', occurrence: 1,
		range: 4, result: 0}],
	features: ['handler.before-move', 'handler.move-aborted', 'status.paralysis'],
});

emit({
	id: 'charge-gen3-switch-silent-clear', seed: [815, 23, 47, 71],
	description: 'switching silently clears Charge without its End callback',
	teams: [[fastSmeargle(['charge']), blissey(['softboiled'])], [magikarp(['splash'])]],
	choices: [['move 1', 'move 1'], ['switch 2', 'move 1']],
	features: ['choice.switch', 'lifecycle.switch-persistence'],
});

emit({
	id: 'charge-gen3-faint-silent-clear', seed: [816, 23, 47, 71],
	description: 'self-faint clears Charge silently after zero-HP removal is rejected',
	teams: [[smeargle(['charge', 'volttackle'], 1)], [blissey(['softboiled'])]],
	choices: [['move 1', 'move 1'], ['move 2', 'move 1']],
	features: ['lifecycle.faint'],
});

console.log('generated 6 Charge cases');
