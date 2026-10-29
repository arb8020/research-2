#!/usr/bin/env node
'use strict';

const cp = require('child_process');
const fs = require('fs');
const path = require('path');
const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const showdownDir = path.resolve(process.argv[2] || '');
if (!process.argv[2]) throw new Error('usage: generate-focus-punch-cases.js POKEMON_SHOWDOWN_DIR');
if (cp.execFileSync('git', ['-C', showdownDir, 'rev-parse', 'HEAD'], {encoding: 'utf8'}).trim() !== REVISION) throw new Error('wrong Showdown revision');
const {Dex, Teams, TeamValidator} = require(showdownDir);
const {normalizeCase} = require('./normalize');
const dex = Dex.forGen(3);
const validator = new TeamValidator('gen3ou');
const out = path.join(__dirname, 'derived');

function stats(id) {
	const base = dex.species.get(id).baseStats;
	const stat = key => 2 * base[key] + 36;
	return [2 * base.hp + 141, stat('atk'), stat('def'), stat('spa'), stat('spd'), stat('spe')];
}
function member(species, ability, moves, gender = 'M') {
	return {species, level: 100, gender, nature: 'hardy', ability, item: '', moves,
		stats: stats(species), status: null};
}
function teamText(team) {
	return team.map(set => `${dex.species.get(set.species).name} (${set.gender})\nAbility: ${dex.abilities.get(set.ability).name}\nLevel: 100\nEVs: 1 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe\nHardy Nature\n${set.moves.map(move => `- ${dex.moves.get(move).name}`).join('\n')}\n`).join('\n');
}
function emit(spec) {
	const teamFiles = [`${spec.id}-p1.txt`, `${spec.id}-p2.txt`];
	for (let side = 0; side < 2; side++) {
		const text = teamText(spec.teams[side]);
		const errors = validator.validateTeam(Teams.import(text));
		if (errors) throw new Error(`${spec.id} p${side + 1}: ${errors.join('; ')}`);
		fs.writeFileSync(path.join(out, teamFiles[side]), text);
	}
	const value = {
		schema: 'pokemon-native-differential-case-v1', id: spec.id,
		provenance: {kind: 'showdown-derived',
			source_file: 'data/mods/gen4/moves.ts; sim/battle.ts; sim/battle-actions.ts',
			test_name: spec.description, oracle_revision: REVISION},
		format: 'gen3ou', seed: spec.seed || [1, 2, 3, 4],
		teams: spec.teams.map((team, side) => ({source: teamFiles[side], normalized: team})),
		source_choices: spec.choices, choices: spec.choices, forced_outcomes: [],
		features: ['choice.move', 'handler.try', 'state.canonical', 'prng.labeled',
			'condition.volatile', ...(spec.features || [])],
		boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
		limits: {max_boundaries: spec.choices.length + 1, max_actions: spec.choices.length * 2},
	};
	fs.writeFileSync(path.join(out, `${spec.id}.json`), `${JSON.stringify(normalizeCase(value), null, 2)}\n`);
}

emit({
	id: 'focus-punch-interrupted-pp-spent',
	description: 'Gen 3 damage interrupts Focus Punch after its ordinary PP deduction',
	teams: [[member('breloom', 'effectspore', ['focuspunch'])],
		[member('venusaur', 'overgrow', ['tackle'])]],
	choices: [['move 1', 'move 1']],
});
emit({
	id: 'focus-punch-status-hit-succeeds',
	description: 'a status move does not invalidate the prepared Focus Punch',
	teams: [[member('breloom', 'effectspore', ['focuspunch'])],
		[member('venusaur', 'overgrow', ['growl'])]],
	choices: [['move 1', 'move 1']],
});
emit({
	id: 'focus-punch-substitute-interception',
	description: 'damage intercepted by Substitute does not dispatch target-owned Hit',
	teams: [[member('breloom', 'effectspore', ['substitute', 'focuspunch'])],
		[member('venusaur', 'overgrow', ['growl', 'tackle'])]],
	choices: [['move 1', 'move 1'], ['move 2', 'move 2']],
	features: ['hit.substitute', 'volatile.substitute'],
});
emit({
	id: 'focus-punch-preparation-before-switch',
	description: 'the preparation action precedes a switch and Focus Punch hits the replacement',
	teams: [[member('breloom', 'effectspore', ['focuspunch'])],
		[member('magikarp', 'swiftswim', ['splash']), member('venusaur', 'overgrow', ['growl'])]],
	choices: [['move 1', 'switch 2']],
	features: ['choice.switch'],
});
emit({
	id: 'focus-punch-fake-out-interruption',
	description: 'Fake Out damage invalidates Focus Punch while its flinch is rejected',
	teams: [[member('breloom', 'effectspore', ['focuspunch'])],
		[member('persian', 'limber', ['fakeout'], 'F')]],
	choices: [['move 1', 'move 1']],
	features: ['handler.try-add-volatile', 'volatile.flinch'],
});

console.log('generated 5 Focus Punch cases');
