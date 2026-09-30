#!/usr/bin/env node
'use strict';

const childProcess = require('child_process');
const fs = require('fs');
const path = require('path');
const {normalizeCase} = require('./normalize');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
if (!process.argv[2]) throw new Error(
	'usage: node generate-atomic-formula-cases.js POKEMON_SHOWDOWN_DIR [OUTPUT_DIR]');
const showdownDir = path.resolve(process.argv[2]);
const outputDir = path.resolve(process.argv[3] || path.join(__dirname, 'derived'));
const revision = childProcess.execFileSync(
	'git', ['-C', showdownDir, 'rev-parse', 'HEAD'], {encoding: 'utf8'}).trim();
if (revision !== REVISION) throw new Error(`expected ${REVISION}, got ${revision}`);

const {Dex, Teams} = require(showdownDir);
const {TeamValidator} = require(path.join(showdownDir, 'dist/sim/team-validator'));
const common = require(path.join(showdownDir, 'test/common')).gen(3);
const dex = Dex.forGen(3);
const validator = TeamValidator.get('gen3ou');
fs.mkdirSync(outputDir, {recursive: true});

function stats(speciesID, hpEV = 1) {
	const base = dex.species.get(speciesID).baseStats;
	const scaled = stat => 2 * base[stat] + 31;
	return [scaled('hp') + Math.floor(hpEV / 4) + 110,
		scaled('atk') + 5, scaled('def') + 5, scaled('spa') + 5,
		scaled('spd') + 5, scaled('spe') + 5];
}

function member(species, ability, moves, options = {}) {
	const hpEV = options.hpEV || 1;
	return {species, level: 100, gender: options.gender || 'M', ability,
		item: '', moves, stats: stats(species, hpEV), status: options.status || null,
		...(options.initialHP === undefined ? {} : {initial_hp: options.initialHP}),
		_hpEV: hpEV};
}

function canonicalMember(set) {
	const {_hpEV, ...canonical} = set;
	return canonical;
}

function teamText(team) {
	return team.map(set => `${dex.species.get(set.species).name} (${set.gender})\n` +
		`Ability: ${dex.abilities.get(set.ability).name}\nLevel: 100\n` +
		`EVs: ${set._hpEV} HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe\n` +
		'Hardy Nature\n' + set.moves.map(move => `- ${dex.moves.get(move).name}`).join('\n') +
		'\n').join('\n');
}

function installInitialState(battle, teams) {
	for (let side = 0; side < 2; side++) {
		for (let slot = 0; slot < teams[side].length; slot++) {
			const expected = teams[side][slot];
			const pokemon = battle.sides[side].pokemon[slot];
			if (expected.initial_hp !== undefined) pokemon.hp = expected.initial_hp;
			if (!expected.status) continue;
			pokemon.status = expected.status;
			pokemon.statusState = battle.initEffectState({id: expected.status, target: pokemon});
		}
	}
}

function assert(condition, message) {
	if (!condition) throw new Error(message);
}

function validateTransition(spec, imported) {
	const battle = common.createBattle({formatid: 'gen3ou', seed: spec.seed}, imported);
	installInitialState(battle, spec.teams);
	const user = battle.p1.active[0];
	const target = battle.p2.active[0];
	const start = {userHP: user.hp, targetHP: target.hp};
	for (let turn = 0; turn < spec.choices.length; turn++) {
		battle.makeChoices(spec.choices[turn][0], spec.choices[turn][1]);
	}
	spec.verify({battle, user, target, start});
}

function writeCase(spec) {
	const sourceNames = [`${spec.id}-p1.txt`, `${spec.id}-p2.txt`];
	const imported = [];
	for (let side = 0; side < 2; side++) {
		const text = teamText(spec.teams[side]);
		const team = Teams.import(text);
		const errors = validator.validateTeam(team);
		if (errors) throw new Error(`${spec.id} p${side + 1}:\n${errors.join('\n')}`);
		imported.push(team);
		fs.writeFileSync(path.join(outputDir, sourceNames[side]), text);
	}
	validateTransition(spec, imported);
	const fixture = normalizeCase({
		schema: 'pokemon-native-differential-case-v1', id: spec.id,
		provenance: {kind: 'showdown-derived',
			source_file: 'data/moves.ts#smellingsalts,bellydrum; sim/battle-actions.ts#moveHit',
			test_name: spec.description, oracle_revision: REVISION},
		format: 'gen3ou', seed: spec.seed,
		teams: spec.teams.map((team, side) => ({source: sourceNames[side],
			normalized: team.map(canonicalMember)})),
		source_choices: spec.choices, choices: spec.choices, forced_outcomes: [],
		features: ['choice.move', 'state.canonical', ...spec.features],
		boundaries: ['request', 'choice', 'queue', 'handlers', 'state', 'events', 'prng'],
		limits: {max_boundaries: spec.choices.length + 1,
			max_actions: spec.choices.flat().filter(Boolean).length},
	});
	fs.writeFileSync(path.join(outputDir, `${spec.id}.json`),
		`${JSON.stringify(fixture, null, 2)}\n`);
}

const smeargle = (moves, options = {}) => member('smeargle', 'owntempo', moves, options);
const passive = () => member('blissey', 'naturalcure', ['softboiled'], {gender: 'F'});
const saltsFeatures = ['condition.nonvolatile-status', 'damage.gen3',
	'handler.base-power', 'hit.accuracy'];
const drumFeatures = ['effect.boost', 'handler.move-fail'];

for (const spec of [
	{
		id: 'smelling-salts-paralyzed-double-cure', seed: [1701, 1702, 1703, 1704],
		description: 'Smelling Salts doubles base power against paralysis and cures it after a connected hit',
		teams: [[smeargle(['smellingsalts'])],
			[member('machop', 'guts', ['bulkup'], {status: 'par'})]],
		choices: [['move 1', 'move 1']], features: saltsFeatures,
		verify: ({target, start}) => {
			assert(target.hp < start.targetHP, 'paralyzed Smelling Salts must damage');
			assert(!target.status, 'connected Smelling Salts must cure paralysis');
		},
	},
	{
		id: 'smelling-salts-clean-baseline', seed: [1701, 1702, 1703, 1704],
		description: 'Smelling Salts preserves ordinary base power and status when the target is not paralyzed',
		teams: [[smeargle(['smellingsalts'])], [member('machop', 'guts', ['bulkup'])]],
		choices: [['move 1', 'move 1']], features: saltsFeatures,
		verify: ({target, start}) => {
			assert(target.hp < start.targetHP, 'clean Smelling Salts must damage');
			assert(!target.status, 'clean target must remain status-free');
		},
	},
	{
		id: 'smelling-salts-substitute-preserves-paralysis', seed: [1711, 1712, 1713, 1714],
		description: 'Substitute receives Smelling Salts damage and prevents its paralysis cure',
		teams: [[smeargle(['splash', 'smellingsalts'])],
			[member('alakazam', 'synchronize', ['substitute', 'recover'], {status: 'par'})]],
		choices: [['move 1', 'move 1'], ['move 2', 'move 2']],
		features: [...saltsFeatures, 'hit.substitute', 'volatile.substitute'],
		verify: ({target}) => {
			assert(target.status === 'par', 'Substitute must prevent the paralysis cure');
			assert(!target.volatiles.substitute, 'Smelling Salts must damage and break this Substitute');
		},
	},
	{
		id: 'belly-drum-odd-max-hp-success', seed: [1721, 1722, 1723, 1724],
		description: 'Belly Drum at odd maximum HP pays floor(max HP / 2) and maximizes Attack',
		teams: [[smeargle(['bellydrum'])], [passive()]],
		choices: [['move 1', 'move 1']], features: drumFeatures,
		verify: ({user, start}) => {
			assert(start.userHP === 251 && user.hp === 126, 'odd-HP Belly Drum payment must be 125');
			assert(user.boosts.atk === 6, 'Belly Drum must maximize Attack');
		},
	},
	{
		id: 'belly-drum-even-max-hp-success', seed: [1731, 1732, 1733, 1734],
		description: 'Belly Drum at even maximum HP pays exactly half and maximizes Attack',
		teams: [[smeargle(['bellydrum'], {hpEV: 4})], [passive()]],
		choices: [['move 1', 'move 1']], features: drumFeatures,
		verify: ({user, start}) => {
			assert(start.userHP === 252 && user.hp === 126, 'even-HP Belly Drum payment must be 126');
			assert(user.boosts.atk === 6, 'Belly Drum must maximize Attack');
		},
	},
	{
		id: 'belly-drum-half-hp-failure', seed: [1741, 1742, 1743, 1744],
		description: 'Belly Drum fails without payment when current HP is at most half maximum HP',
		teams: [[smeargle(['bellydrum'], {hpEV: 4, initialHP: 126})], [passive()]],
		choices: [['move 1', 'move 1']], features: drumFeatures,
		verify: ({user}) => {
			assert(user.hp === 126, 'failed Belly Drum must not pay HP');
			assert(user.boosts.atk === 0, 'failed Belly Drum must not boost Attack');
		},
	},
	{
		id: 'belly-drum-plus-six-failure', seed: [1751, 1752, 1753, 1754],
		description: 'Belly Drum fails without a second payment when Attack is already +6',
		teams: [[smeargle(['bellydrum'])], [passive()]],
		choices: [['move 1', 'move 1'], ['move 1', 'move 1']], features: drumFeatures,
		verify: ({user}) => {
			assert(user.hp === 126, 'already-maximized Belly Drum must not pay HP again');
			assert(user.boosts.atk === 6, 'already-maximized Attack must remain +6');
		},
	},
]) writeCase(spec);

console.log('generated, legality-validated, and transition-validated 7 atomic-formula fixtures');
