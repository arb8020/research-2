'use strict';

process.env.PS_GEN3_VERIFY_TRACE = '1';
const fs = require('fs');
const {loadCase} = require('./shared_case');
const showdownDir = process.env.POKEMON_SHOWDOWN_DIR || '/opt/pokemon-showdown';
const common = require(`${showdownDir}/test/common`).gen(3);
const {Teams} = require(showdownDir);

const casePath = process.argv[2];
if (!casePath) throw new Error('usage: oracle_boundary_driver.js CASE');
const fixture = loadCase(casePath);
const teams = fixture.teams.map(teamPath => Teams.import(fs.readFileSync(teamPath, 'utf8')));
const battle = common.createBattle({formatid: fixture.format, seed: fixture.seed}, teams);

function legalMask(choices) {
	let mask = 0;
	for (const choice of choices) {
		let match = /^move ([1-4])$/.exec(choice);
		if (match) mask |= 1 << (Number(match[1]) - 1);
		match = /^switch ([2-6])$/.exec(choice);
		if (match) mask |= 1 << (Number(match[1]) + 2);
	}
	return mask;
}

function phase(requests) {
	if (requests.every(request => request.kind === 'move')) {
		return {kind: 0, required_side_mask: 3, forced_first_side: 0, continuation: 0};
	}
	const required = requests.map((request, side) => request.kind === 'switch' ? side : -1).filter(side => side >= 0);
	return {kind: 1, required_side_mask: required.reduce((mask, side) => mask | (1 << side), 0),
		forced_first_side: required[0], continuation: 1};
}

const statusIds = {brn: 1, par: 2, psn: 3, tox: 4, slp: 5, frz: 6};
function state(record) {
	const draws = battle.verificationTrace.filter(entry => entry.kind === 'prng' && entry.sequence < record.sequence);
	const lastDraw = draws[draws.length - 1];
	if (!lastDraw) throw new Error(`boundary ${record.ordinal} has no observable PRNG state`);
	return {
		turn: record.state.turn,
		seed: lastDraw.draw.after.split(',').map(Number),
		force_switch_side: record.request.findIndex(request => request.kind === 'switch'),
		spikes: record.state.sides.map(side => side.sideConditions.includes('spikes') ? 1 : 0),
		resume_residuals: record.request.some(request => request.kind === 'switch') ? 1 : 0,
		done: 0,
		winner_side: -1,
		pokemon: record.state.sides.map(side => side.pokemon.map(pokemon => ({
			species_id: battle.dex.species.get(pokemon.species).num,
			hp: pokemon.hp,
			max_hp: pokemon.maxhp,
			pp: pokemon.moves.map(move => move.pp),
			status: statusIds[pokemon.status] || 0,
			protect_counter: 0,
			toxic_counter: pokemon.statusState && pokemon.status === 'tox' ? pokemon.statusState.stage || 0 : 0,
			leech_seeded: pokemon.volatiles.includes('leechseed') ? 1 : 0,
			stat_stages: ['atk', 'def', 'spa', 'spd', 'spe'].map(stat => pokemon.boosts[stat]),
		}))),
	};
}

function protocolEvents(lines) {
	const events = [];
	for (const line of lines) {
		let match = /^\|switch\|p([12])a: [^|]+\|([^,|]+)(?:,[^|]*)?\|(\d+)\/(\d+)$/.exec(line);
		if (match) {
			const event = {kind: 1, side: Number(match[1]) - 1, status: 0, amount: 0,
				species_id: battle.dex.species.get(match[2]).num, move_id: 0,
				hp: Number(match[3]), max_hp: Number(match[4])};
			const previous = events[events.length - 1];
			if (!previous || previous.kind !== event.kind || previous.side !== event.side ||
				previous.species_id !== event.species_id) events.push(event);
			continue;
		}
		match = /^\|move\|p([12])a: ([^|]+)\|([^|]+)\|/.exec(line);
		if (match) {
			events.push({kind: 2, side: Number(match[1]) - 1, status: 0, amount: 0,
				species_id: battle.dex.species.get(match[2]).num,
				move_id: battle.dex.moves.get(match[3]).num, hp: 0, max_hp: 0});
			continue;
		}
		match = /^\|faint\|p([12])a: (.+)$/.exec(line);
		if (match) events.push({kind: 6, side: Number(match[1]) - 1, status: 0, amount: 0,
			species_id: battle.dex.species.get(match[2]).num, move_id: 0, hp: 0, max_hp: 0});
	}
	return events;
}

for (const choices of fixture.showdownChoices) battle.makeChoices(choices[0], choices[1]);
const records = battle.verificationTrace.filter(record => record.kind === 'decision').slice(1);
if (records.length !== fixture.showdownChoices.length) throw new Error('oracle boundary count disagrees with shared choices');
for (const record of records) {
	const value = {
		schema: 'gen3-boundary-v1',
		case_id: fixture.id,
		boundary: record.ordinal,
		point: 'request',
		phase: phase(record.request),
		legal_masks: record.request.map(request => legalMask(request.legal)),
		state: state(record),
		events: protocolEvents(record.protocol),
	};
	process.stdout.write(`${JSON.stringify(value)}\n`);
}
