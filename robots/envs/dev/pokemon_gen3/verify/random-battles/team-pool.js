#!/usr/bin/env node
'use strict';

const fs = require('fs');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';

function reject(message) {
	throw new Error(`team recombination: ${message}`);
}

function uint32(value, label) {
	if (!Number.isSafeInteger(value) || value < 0 || value > 0xFFFFFFFF) {
		reject(`${label} must be a uint32`);
	}
	return value >>> 0;
}

class TeamPRNG {
	constructor(seed) {
		this.initialSeed = uint32(seed, 'team seed');
		this.state = this.initialSeed;
	}

	next(limit) {
		if (!Number.isSafeInteger(limit) || limit < 1) reject('invalid PRNG limit');
		this.state = (Math.imul(this.state, 1664525) + 1013904223) >>> 0;
		return Math.floor((this.state / 0x100000000) * limit);
	}
}

function loadPool(filename, showdown) {
	let document;
	try {
		document = JSON.parse(fs.readFileSync(filename, 'utf8'));
	} catch (error) {
		reject(`cannot read pool ${filename}: ${error.message}`);
	}
	if (!document || document.schema !== 'pokemon-gen3ou-supported-set-pool-v1' ||
		document.oracle_revision !== REVISION || !Array.isArray(document.source_teams) ||
		!Array.isArray(document.sets)) {
		reject('invalid pool header');
	}
	const ids = new Set();
	const species = new Set();
	const sets = document.sets.map((entry, index) => {
		if (!entry || typeof entry.id !== 'string' || !/^[a-z0-9]+$/.test(entry.id) ||
			typeof entry.species !== 'string' || typeof entry.packed !== 'string') {
			reject(`invalid set record ${index}`);
		}
		if (ids.has(entry.id)) reject(`duplicate set ID ${entry.id}`);
		ids.add(entry.id);
		const unpacked = showdown.Teams.unpack(entry.packed);
		if (!unpacked || unpacked.length !== 1) reject(`${entry.id} is not exactly one packed set`);
		const canonical = showdown.Teams.pack(unpacked);
		if (canonical !== entry.packed) reject(`${entry.id} is not canonically packed`);
		const speciesId = showdown.Dex.toID(unpacked[0].species);
		if (speciesId !== entry.species) reject(`${entry.id} species is ${speciesId}, expected ${entry.species}`);
		if (species.has(speciesId)) reject(`duplicate species ${speciesId}`);
		species.add(speciesId);
		return {id: entry.id, species: speciesId, set: unpacked[0]};
	});
	if (sets.length < 6) reject(`pool has ${sets.length} distinct species, expected at least 6`);
	return {document, sets};
}

function chooseTeam(pool, seed) {
	const candidates = pool.sets.slice();
	const random = new TeamPRNG(seed);
	const chosen = [];
	while (chosen.length < 6) {
		const index = random.next(candidates.length);
		chosen.push(candidates[index]);
		candidates.splice(index, 1);
	}
	return chosen;
}

function validateTeam(showdown, chosen, side) {
	const team = chosen.map(entry => entry.set);
	const species = new Set(chosen.map(entry => entry.species));
	if (team.length !== 6 || species.size !== 6) reject(`player ${side} does not have six distinct species`);
	const problems = showdown.TeamValidator.get('gen3ou').validateTeam(team);
	if (problems) reject(`player ${side} is not legal Gen 3 OU:\n${problems.join('\n')}`);
	return {
		seed: null,
		set_ids: chosen.map(entry => entry.id),
		species: chosen.map(entry => entry.species),
		source: showdown.Teams.export(team),
	};
}

function recombinePair(showdown, pool, seeds) {
	if (!Array.isArray(seeds) || seeds.length !== 2) reject('team seeds must contain two values');
	return seeds.map((seed, side) => {
		uint32(seed, `player ${side + 1} team seed`);
		const result = validateTeam(showdown, chooseTeam(pool, seed), side + 1);
		result.seed = seed;
		return result;
	});
}

module.exports = {REVISION, TeamPRNG, chooseTeam, loadPool, recombinePair, uint32};
