#!/usr/bin/env node
'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const {buildCampaign, loadManifest, pinnedShowdown} = require('./recombine');
const {loadPool, recombinePair} = require('./team-pool');

function assert(value, message = 'assertion failed') {
	if (!value) throw new Error(message);
}
assert.strictEqual = (actual, expected, message = 'values differ') => {
	if (actual !== expected) throw new Error(`${message}: ${actual} !== ${expected}`);
};
assert.deepStrictEqual = (actual, expected, message = 'structures differ') => {
	if (JSON.stringify(actual) !== JSON.stringify(expected)) throw new Error(message);
};
assert.throws = (operation, pattern) => {
	try {
		operation();
	} catch (error) {
		if (!pattern.test(error.message)) throw error;
		return;
	}
	throw new Error(`expected error ${pattern}`);
};

if (process.argv.length !== 3) throw new Error('usage: node test-team-pool.js SHOWDOWN_DIR');
const showdown = pinnedShowdown(path.resolve(process.argv[2]));
const manifestPath = path.resolve(__dirname, 'recombination-manifest.json');
const manifest = loadManifest(manifestPath);
const first = buildCampaign(showdown, manifest, manifestPath);
const second = buildCampaign(showdown, manifest, manifestPath);

assert.strictEqual(JSON.stringify(first), JSON.stringify(second), 'same inputs must be byte-identical');
assert.strictEqual(first.cases.length, 4);
for (const entry of first.cases) {
	assert.deepStrictEqual(entry.battle_seed,
		manifest.cases.find(candidate => candidate.id === entry.id).battle_seed);
	assert.strictEqual(entry.policy_seed,
		manifest.cases.find(candidate => candidate.id === entry.id).policy_seed);
	for (const team of entry.teams) {
		assert.strictEqual(team.set_ids.length, 6);
		assert.strictEqual(new Set(team.species).size, 6);
		const imported = showdown.Teams.import(team.source);
		assert(imported && imported.length === 6);
		assert.strictEqual(showdown.TeamValidator.get('gen3ou').validateTeam(imported), null);
	}
}

const reordered = buildCampaign(showdown, {...manifest, campaign_seed: 3237998082}, manifestPath);
const byId = campaign => campaign.cases.map(entry => [entry.id, {
	team_seeds: entry.team_seeds,
	battle_seed: entry.battle_seed,
	policy_seed: entry.policy_seed,
	teams: entry.teams,
}]).sort((left, right) => left[0].localeCompare(right[0]));
assert.deepStrictEqual(byId(reordered), byId(first),
	'campaign ordering must not consume team, battle, or policy randomness');

const poolPath = path.resolve(__dirname, 'team-pool.json');
const pool = loadPool(poolPath, showdown);
const sourceSets = new Set();
for (const relative of pool.document.source_teams) {
	const filename = path.resolve(__dirname, relative);
	const imported = showdown.Teams.import(fs.readFileSync(filename, 'utf8'));
	assert(imported, `cannot import source team ${relative}`);
	for (const set of imported) sourceSets.add(showdown.Teams.pack([set]));
}
for (const entry of pool.document.sets) {
	assert(sourceSets.has(entry.packed), `${entry.id} is not derived from a declared source team`);
}

const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'pokemon-team-pool-test-'));
try {
	const tooSmall = {...pool.document, sets: pool.document.sets.slice(0, 5)};
	const tooSmallPath = path.join(temporary, 'too-small.json');
	fs.writeFileSync(tooSmallPath, JSON.stringify(tooSmall));
	assert.throws(() => loadPool(tooSmallPath, showdown), /expected at least 6/);

	const duplicate = JSON.parse(JSON.stringify(pool.document));
	duplicate.sets[1].species = duplicate.sets[0].species;
	const duplicatePath = path.join(temporary, 'wrong-species.json');
	fs.writeFileSync(duplicatePath, JSON.stringify(duplicate));
	assert.throws(() => loadPool(duplicatePath, showdown), /species is ludicolo, expected pelipper/);

	const illegal = JSON.parse(JSON.stringify(pool.document));
	const badSet = showdown.Teams.unpack(illegal.sets[0].packed)[0];
	badSet.moves = ['Spore', 'Surf', 'Toxic', 'Protect'];
	illegal.sets[0].packed = showdown.Teams.pack([badSet]);
	illegal.sets = illegal.sets.slice(0, 6);
	const illegalPath = path.join(temporary, 'illegal.json');
	fs.writeFileSync(illegalPath, JSON.stringify(illegal));
	const illegalPool = loadPool(illegalPath, showdown);
	assert.throws(() => recombinePair(showdown, illegalPool, [1, 2]), /not legal Gen 3 OU/);
} finally {
	fs.rmSync(temporary, {recursive: true, force: true});
}

console.log('team recombination contract passed');
