#!/usr/bin/env node
'use strict';

const childProcess = require('child_process');
const fs = require('fs');
const path = require('path');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const showdownDir = path.resolve(process.argv[2] || '');
if (!process.argv[2]) throw new Error('usage: node generate-pursuit-cases.js POKEMON_SHOWDOWN_DIR');
const actual = childProcess.execFileSync(
	'git', ['-C', showdownDir, 'rev-parse', 'HEAD'], {encoding: 'utf8'}).trim();
if (actual !== REVISION) throw new Error(`expected ${REVISION}, got ${actual}`);
if (childProcess.execFileSync(
	'git', ['-C', showdownDir, 'status', '--porcelain'], {encoding: 'utf8'}).trim()) {
	throw new Error('Pursuit fixtures require a clean pinned Showdown checkout');
}

const {Dex, Teams} = require(showdownDir);
const {TeamValidator} = require(path.join(showdownDir, 'dist/sim/team-validator'));
const common = require(path.join(showdownDir, 'test/common')).gen(3);
const {PRNG} = require(path.join(showdownDir, 'dist/sim/prng'));
const dex = Dex.forGen(3);
const validator = TeamValidator.get('gen3ou');
const outputDir = path.join(__dirname, 'derived');
fs.mkdirSync(outputDir, {recursive: true});

function stats(speciesID, level = 100) {
	const base = dex.species.get(speciesID).baseStats;
	const scaled = stat => Math.floor((2 * base[stat] + 31) * level / 100);
	return [scaled('hp') + level + 10, scaled('atk') + 5, scaled('def') + 5,
		scaled('spa') + 5, scaled('spd') + 5, scaled('spe') + 5];
}

function member(species, ability, moves, options = {}) {
	const value = {
		species, level: 100, gender: options.gender || 'M', ability, item: '', moves,
		stats: stats(species), status: options.status || null,
	};
	if (options.initialHP !== undefined) value.initial_hp = options.initialHP;
	if (options.statusState) value.status_state = options.statusState;
	return value;
}

function teamText(team) {
	return team.map(set => `${dex.species.get(set.species).name} (${set.gender})\n` +
		`Ability: ${dex.abilities.get(set.ability).name}\nLevel: ${set.level}\n` +
		`EVs: 1 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe\nHardy Nature\n` +
		`${set.moves.map(id => `- ${dex.moves.get(id).name}`).join('\n')}\n`).join('\n');
}

function installConstructedState(battle, teams) {
	for (let side = 0; side < teams.length; side++) {
		for (let slot = 0; slot < teams[side].length; slot++) {
			const expected = teams[side][slot];
			const pokemon = battle.sides[side].pokemon[slot];
			if (expected.initial_hp !== undefined) pokemon.hp = expected.initial_hp;
			if (!expected.status) continue;
			pokemon.status = expected.status;
			pokemon.statusState = battle.initEffectState({id: expected.status, target: pokemon});
			if (expected.status === 'slp') {
				pokemon.statusState.time = expected.status_state.time;
				pokemon.statusState.skippedTime = expected.status_state.skipped_time;
			}
		}
	}
}

function drawLabel(from, to, stack) {
	const upper = to === undefined ? from : to - from;
	if (upper === 5) return 'turn.quick_claw';
	if (upper === 4 && stack.includes('randomChance')) return 'status.paralysis.before_move';
	if (from === 2 && to === 6 && stack.includes('conditions.js')) return 'condition.sleep.duration';
	if (upper === 2 && stack.includes('PRNG.shuffle') && stack.includes('Pokemon.setStatus')) {
		return 'event.setstatus.handler_order';
	}
	if (upper === 100 && stack.includes('randomChance')) return 'move.accuracy';
	if (upper === 16 && stack.includes('randomChance')) return 'move.critical';
	if (upper === 16) return 'move.damage_roll';
	return `unclassified(${from},${to})`;
}

function audit(spec, imported) {
	const calls = [];
	const originalRandom = PRNG.prototype.random;
	PRNG.prototype.random = function (from, to) {
		const before = this.getSeed();
		const stack = new Error().stack;
		const result = originalRandom.call(this, from, to);
		calls.push({label: drawLabel(from, to, stack), from, to: to ?? null,
			result, seed_before: before, seed_after: this.getSeed()});
		return result;
	};
	const battle = common.createBattle({formatid: 'gen3ou', seed: spec.seed}, imported);
	installConstructedState(battle, spec.teams);
	const initialDrawCount = calls.length;
	const outgoing = battle.p2.pokemon[0];
	const incoming = battle.p2.pokemon[1];
	const initial = {outgoing_hp: outgoing.hp, incoming_hp: incoming.hp,
		pursuit_pp: battle.p1.active[0].getMoveData(dex.moves.get('pursuit')).pp};
	const boundaries = [];
	for (const choices of spec.choices) {
		const drawStart = calls.length;
		battle.makeChoices(...choices);
		boundaries.push({
			active_species: battle.p2.active[0].baseSpecies.id,
			p1_status: battle.p1.active[0].status || null,
			pursuit_pp: battle.p1.active[0].getMoveData(dex.moves.get('pursuit')).pp,
			p2_hp: battle.p2.pokemon.map(pokemon => pokemon.hp),
			draws: calls.slice(drawStart).map(call => ({label: call.label,
				result: call.result, seed_before: call.seed_before,
				seed_after: call.seed_after})),
		});
	}
	const observed = {
		active_species: battle.p2.active[0].baseSpecies.id,
		outgoing_hp: outgoing.hp,
		incoming_hp: incoming.hp,
		pursuit_pp: battle.p1.active[0].getMoveData(dex.moves.get('pursuit')).pp,
		outgoing_fainted: outgoing.fainted,
		initial_draws: calls.slice(0, initialDrawCount).map(call => ({
			label: call.label, result: call.result,
			seed_before: call.seed_before, seed_after: call.seed_after,
		})),
		boundaries,
		log: battle.log.filter(line => line.startsWith('|move|') ||
			line.startsWith('|cant|') || line.startsWith('|switch|') ||
			line.startsWith('|faint|')),
		draws: calls.map(call => ({label: call.label, result: call.result,
			seed_before: call.seed_before, seed_after: call.seed_after})),
	};
	try {
		spec.assert(initial, observed);
	} catch (error) {
		battle.destroy();
		PRNG.prototype.random = originalRandom;
		throw new Error(`${spec.id}: ${JSON.stringify({initial, observed})}`, {cause: error});
	}
	battle.destroy();
	PRNG.prototype.random = originalRandom;
	return observed;
}

function emit(spec) {
	const sources = [`${spec.id}-p1.txt`, `${spec.id}-p2.txt`];
	const imported = [];
	for (let side = 0; side < 2; side++) {
		const text = teamText(spec.teams[side]);
		const parsed = Teams.import(text);
		const errors = validator.validateTeam(parsed);
		if (errors) throw new Error(`${spec.id} p${side + 1}: ${errors.join('; ')}`);
		fs.writeFileSync(path.join(outputDir, sources[side]), text);
		imported.push(parsed);
	}
	const observed = audit(spec, imported);
	const fixture = {
		schema: 'pokemon-native-differential-case-v1', id: spec.id,
		provenance: {kind: 'showdown-derived',
			source_file: 'data/mods/gen3/moves.ts#pursuit; data/moves.ts#pursuit; sim/battle-actions.ts#switchIn; sim/battle.ts#runAction',
			test_name: spec.description, oracle_revision: REVISION},
		format: 'gen3ou', seed: spec.seed,
		teams: spec.teams.map((team, side) => ({source: sources[side], normalized: team})),
		source_choices: spec.choices, choices: spec.choices, forced_outcomes: [],
		features: ['choice.move', 'choice.switch', 'condition.volatile',
			'handler.switch-out', 'prng.labeled', 'queue.move-priority',
			'state.canonical', ...(spec.features || [])],
		boundaries: ['choice', 'events', 'handlers', 'prng', 'queue', 'request', 'state'],
		limits: {max_boundaries: spec.choices.length + 1,
			max_actions: spec.choices.length * 2},
	};
	fs.writeFileSync(path.join(outputDir, `${spec.id}.json`),
		`${JSON.stringify(fixture, null, 2)}\n`);
	return {id: spec.id, observed};
}

const tyranitar = options => member('tyranitar', 'sandstream', ['pursuit'], options);
const alakazam = options => member('alakazam', 'synchronize', ['calmmind'], options);
const blissey = () => member('blissey', 'naturalcure', ['softboiled'], {gender: 'F'});

const specs = [
	{
		id: 'pursuit-switch-survives', seed: [401, 402, 403, 404],
		description: 'Pursuit intercepts a voluntary switch with doubled power and the switch continues',
		teams: [[tyranitar()], [alakazam(), blissey()]],
		choices: [['move 1', 'switch 2']],
		assert(initial, value) {
			if (value.active_species !== 'blissey' || value.outgoing_hp >= initial.outgoing_hp ||
				value.incoming_hp !== initial.incoming_hp - Math.floor(initial.incoming_hp / 16) ||
				value.pursuit_pp !== initial.pursuit_pp - 1) throw new Error(this.id);
		},
	},
	{
		id: 'pursuit-switch-ko-continues', seed: [411, 412, 413, 414],
		description: 'Gen 3 completes a preselected switch after Pursuit KOs the outgoing Pokemon',
		teams: [[tyranitar()], [alakazam({initialHP: 1}), blissey()]],
		choices: [['move 1', 'switch 2']], features: ['lifecycle.faint'],
		assert(initial, value) {
			if (value.active_species !== 'blissey' || value.outgoing_hp !== 0 ||
				!value.outgoing_fainted ||
				value.incoming_hp !== initial.incoming_hp - Math.floor(initial.incoming_hp / 16) ||
				value.pursuit_pp !== initial.pursuit_pp - 1) throw new Error(this.id);
		},
	},
	{
		id: 'pursuit-gen3-paralysis-intercept', seed: [100, 101, 102, 103],
		description: 'Gen 3 Pursuit interception bypasses a second paralysis check after the prior selected action was fully paralyzed',
		teams: [[tyranitar()], [member('alakazam', 'synchronize', ['thunderwave']), blissey()]],
		choices: [['move 1', 'move 1'], ['move 1', 'switch 2']], features: ['status.paralysis'],
		assert(initial, value) {
			const beforeSwitch = value.boundaries[0];
			const intercepted = value.boundaries[1];
			if (value.active_species !== 'blissey' ||
				value.outgoing_hp >= beforeSwitch.p2_hp[0] ||
				intercepted.pursuit_pp !== beforeSwitch.pursuit_pp - 1 ||
				intercepted.draws.some(draw => draw.label === 'status.paralysis')) {
				throw new Error(this.id);
			}
		},
	},
	{
		id: 'pursuit-sleep-at-turn-start', seed: [431, 432, 433, 434],
		description: 'Sleep at turn start suppresses interception even when the user wakes and attacks the incoming Pokemon',
		teams: [[tyranitar()], [member('breloom', 'effectspore', ['spore']), blissey()]],
		choices: [['move 1', 'move 1'], ['move 1', 'switch 2']],
		features: ['status.sleep'],
		assert(initial, value) {
			const pursuitMoves = value.log.filter(line => line.includes('|Pursuit|'));
			if (value.active_species !== 'blissey' || value.boundaries[0].p1_status !== 'slp' ||
				value.boundaries[1].p1_status !== null || pursuitMoves.length !== 1 ||
				!pursuitMoves[0].includes('Blissey')) {
				throw new Error(this.id);
			}
		},
	},
	{
		id: 'pursuit-no-switch-control', seed: [441, 442, 443, 444],
		description: 'Ordinary non-switching Pursuit remains 40 power and retains normal hit PRNG staging',
		teams: [[tyranitar()], [alakazam(), blissey()]],
		choices: [['move 1', 'move 1']],
		assert(initial, value) {
			if (value.active_species !== 'alakazam' || value.outgoing_hp >= initial.outgoing_hp ||
				value.incoming_hp !== initial.incoming_hp ||
				value.pursuit_pp !== initial.pursuit_pp - 1 ||
				!value.draws.some(draw => draw.label === 'move.accuracy')) throw new Error(this.id);
		},
	},
];

const results = specs.map(emit);
fs.writeFileSync(path.join(outputDir, 'pursuit-oracle-expectations.json'),
	`${JSON.stringify({oracle_revision: REVISION, cases: results}, null, 2)}\n`);
console.log('generated and audited 5 Pursuit differential fixtures');
