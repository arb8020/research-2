#!/usr/bin/env node
'use strict';

const cp = require('child_process');
const fs = require('fs');
const path = require('path');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const showdownDir = path.resolve(process.argv[2] || '');
if (!process.argv[2]) throw new Error('usage: generate-imprison-cases.js POKEMON_SHOWDOWN_DIR');
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
		stats: stats(species, level), status: null};
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
			source_file: 'data/mods/gen4/moves.ts#imprison; data/moves.ts#imprison',
			test_name: spec.description, oracle_revision: REVISION,
		},
		format: 'gen3ou', seed: spec.seed,
		teams: spec.teams.map((team, side) => ({source: sources[side], normalized: team})),
		source_choices: spec.choices, choices: spec.choices,
		forced_outcomes: [],
		features: ['choice.move', 'request.legal-choices', 'condition.volatile',
			'handler.try-hit', 'handler.disable-move', 'handler.before-move',
			'lifecycle.switch-persistence', 'state.canonical'],
		boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
		limits: {max_boundaries: spec.choices.length + 1,
			max_actions: spec.choices.length * 2},
	});
	fs.writeFileSync(path.join(out, `${spec.id}.json`),
		`${JSON.stringify(fixture, null, 2)}\n`);
}

const smeargle = moves => member('smeargle', 'owntempo', moves);

emit({
	id: 'imprison-queued-shared-move-cancel',
	description: 'a faster Imprison cancels an already queued shared move and removes it from the next request',
	seed: [221, 31, 17, 9],
	teams: [[smeargle(['imprison', 'splash'])], [smeargle(['splash', 'pound'])]],
	choices: [['move 1', 'move 1']],
});

emit({
	id: 'imprison-no-shared-move-fails',
	description: 'Imprison fails without installing its volatile when the active foe shares no move',
	seed: [222, 31, 17, 9],
	teams: [[smeargle(['imprison', 'splash'])], [smeargle(['pound'])]],
	choices: [['move 1', 'move 1']],
});

emit({
	id: 'imprison-all-shared-forces-struggle',
	description: 'Imprison disables every shared move while preserving Struggle as the fallback choice',
	seed: [223, 31, 17, 9],
	teams: [[smeargle(['imprison', 'splash', 'pound'])], [smeargle(['splash', 'pound'])]],
	choices: [['move 1', 'move 1']],
});

emit({
	id: 'imprison-source-switch-clears',
	description: 'switching the Imprison source silently removes the volatile before the foe executes its queued shared move',
	seed: [224, 31, 17, 9],
	teams: [[smeargle(['imprison', 'splash']),
		member('magikarp', 'swiftswim', ['splash'])], [smeargle(['splash'])]],
	choices: [['move 1', 'move 1'], ['switch 2', 'move 1']],
});

emit({
	id: 'imprison-foe-switch-reprojects',
	description: 'Imprison persists on its source and applies shared-move restrictions to a newly switched-in foe',
	seed: [225, 31, 17, 9],
	teams: [[smeargle(['imprison', 'splash', 'pound'])],
		[smeargle(['splash']), member('magikarp', 'swiftswim', ['splash'])]],
	choices: [['move 1', 'move 1'], ['move 2', 'switch 2']],
});

console.log('generated and legality-validated 5 Imprison fixtures (12 boundaries)');
