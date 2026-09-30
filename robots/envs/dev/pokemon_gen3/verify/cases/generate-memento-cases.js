#!/usr/bin/env node
'use strict';

const childProcess = require('child_process');
const fs = require('fs');
const path = require('path');
const {normalizeCase} = require('./normalize');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
if (!process.argv[2]) throw new Error(
	'usage: node generate-memento-cases.js POKEMON_SHOWDOWN_DIR [OUTPUT_DIR]');
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

function member(species, ability, moves, item = '') {
	const base = dex.species.get(species).baseStats;
	const scaled = stat => 2 * base[stat] + 31;
	return {species, level: 100, gender: species === 'blissey' ? 'F' : 'M',
		ability, item, moves,
		stats: [species === 'shedinja' ? 1 : scaled('hp') + 110,
			scaled('atk') + 5, scaled('def') + 5, scaled('spa') + 5,
			scaled('spd') + 5, scaled('spe') + 5], status: null};
}

function teamText(team) {
	return team.map(set => `${dex.species.get(set.species).name} (${set.gender})` +
		(set.item ? ` @ ${dex.items.get(set.item).name}` : '') + '\n' +
		`Ability: ${dex.abilities.get(set.ability).name}\n` +
		'Level: 100\nEVs: 1 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe\n' +
		'Hardy Nature\n' + set.moves.map(id => `- ${dex.moves.get(id).name}`).join('\n') +
		'\n').join('\n');
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
		provenance: {kind: 'showdown-derived',
			source_file: 'data/moves.ts#memento; data/mods/gen3/moves.ts#memento; sim/battle-actions.ts#moveHit',
			test_name: spec.description, oracle_revision: REVISION},
		format: 'gen3ou', seed: spec.seed,
		teams: spec.teams.map((team, side) => ({source: sources[side], normalized: team})),
		source_choices: spec.choices, choices: spec.choices, forced_outcomes: [],
		features: ['choice.move', 'effect.boost', 'lifecycle.faint',
			'request.legal-choices', 'state.canonical'],
		boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
		limits: {max_boundaries: spec.choices.length + 1,
			max_actions: spec.choices.flat().filter(Boolean).length},
	});
	fs.writeFileSync(path.join(outputDir, `${spec.id}.json`),
		`${JSON.stringify(fixture, null, 2)}\n`);
}

const smeargle = () => member('smeargle', 'owntempo', ['memento']);
const bench = () => member('blissey', 'naturalcure', ['softboiled']);

for (const spec of [
	{
		id: 'memento-standard-force-replacement', seed: [901, 902, 903, 904],
		description: 'successful Memento applies both drops, faints its user, and requests replacement',
		teams: [[smeargle(), bench()], [member('persian', 'limber', ['scratch'])]],
		choices: [['move 1', 'move 1']],
	},
	{
		id: 'memento-clear-body-still-faints', seed: [911, 912, 913, 914],
		description: 'Clear Body rejects both drops without preventing ifHit self-faint',
		teams: [[smeargle(), bench()], [member('metagross', 'clearbody', ['meteormash'])]],
		choices: [['move 1', 'move 1']],
	},
	{
		id: 'memento-protect-no-faint', seed: [921, 922, 923, 924],
		description: 'Protect cancels Memento before its ifHit self-faint payment',
		teams: [[smeargle()], [member('persian', 'limber', ['protect'])]],
		choices: [['move 1', 'move 1']],
	},
	{
		id: 'memento-substitute-no-faint', seed: [931, 932, 933, 934],
		description: 'an intact Substitute cancels Memento before its ifHit self-faint payment',
		teams: [[smeargle()], [member('alakazam', 'synchronize', ['substitute'])]],
		choices: [['move 1', 'move 1']],
	},
	{
		id: 'memento-white-herb-before-faint', seed: [941, 942, 943, 944],
		description: 'White Herb clears Memento drops before the source faint is drained',
		teams: [[smeargle(), bench()],
			[member('persian', 'limber', ['scratch'], 'whiteherb')]],
		choices: [['move 1', 'move 1']],
	},
	{
		id: 'memento-terminal-loss', seed: [951, 952, 953, 954],
		description: 'a last-Pokemon Memento self-faint resolves the opposing winner',
		teams: [[smeargle()], [member('persian', 'limber', ['scratch'])]],
		choices: [['move 1', 'move 1']],
	},
]) writeCase(spec);

console.log('generated and legality-validated 6 Memento fixtures');
