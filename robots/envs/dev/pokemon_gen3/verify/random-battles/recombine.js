#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const {execute} = require('./subprocess');
const {REVISION, TeamPRNG, loadPool, recombinePair, uint32} = require('./team-pool');

function reject(message) {
	throw new Error(`team recombination campaign: ${message}`);
}

function pinnedShowdown(directory) {
	const revision = execute('git', ['-C', directory, 'rev-parse', 'HEAD']).trim();
	if (revision !== REVISION) reject(`Showdown revision is ${revision}, expected ${REVISION}`);
	return require(directory);
}

function loadManifest(filename) {
	const document = JSON.parse(fs.readFileSync(filename, 'utf8'));
	if (!document || document.schema !== 'pokemon-gen3ou-team-recombination-manifest-v1' ||
		document.oracle_revision !== REVISION || typeof document.pool !== 'string' ||
		!Array.isArray(document.cases) || document.cases.length === 0) {
		reject('invalid manifest header');
	}
	uint32(document.campaign_seed, 'campaign seed');
	const ids = new Set();
	for (const entry of document.cases) {
		if (!entry || typeof entry.id !== 'string' || !/^[a-z0-9][a-z0-9-]*$/.test(entry.id) ||
			ids.has(entry.id) || !Array.isArray(entry.team_seeds) || entry.team_seeds.length !== 2 ||
			!Array.isArray(entry.battle_seed) || entry.battle_seed.length !== 4) {
			reject(`invalid case ${JSON.stringify(entry && entry.id)}`);
		}
		ids.add(entry.id);
		entry.team_seeds.forEach((seed, side) => uint32(seed, `${entry.id} player ${side + 1} team seed`));
		entry.battle_seed.forEach((word, index) => {
			if (!Number.isInteger(word) || word < 0 || word > 65535) {
				reject(`${entry.id} battle seed word ${index} must be a uint16`);
			}
		});
		uint32(entry.policy_seed, `${entry.id} policy seed`);
	}
	return document;
}

function buildCampaign(showdown, manifest, manifestPath) {
	const poolPath = path.resolve(path.dirname(manifestPath), manifest.pool);
	const pool = loadPool(poolPath, showdown);
	const remaining = manifest.cases.slice();
	const campaignRandom = new TeamPRNG(manifest.campaign_seed);
	const ordered = [];
	while (remaining.length) ordered.push(remaining.splice(campaignRandom.next(remaining.length), 1)[0]);
	return {
		schema: 'pokemon-gen3ou-recombined-teams-v1',
		oracle_revision: REVISION,
		campaign_seed: manifest.campaign_seed,
		pool: path.basename(poolPath),
		cases: ordered.map(entry => ({
			id: entry.id,
			team_seeds: entry.team_seeds,
			battle_seed: entry.battle_seed,
			policy_seed: entry.policy_seed,
			teams: recombinePair(showdown, pool, entry.team_seeds),
		})),
	};
}

function main() {
	if (process.argv.length !== 4) reject('usage: node recombine.js SHOWDOWN_DIR MANIFEST.json');
	const showdownPath = path.resolve(process.argv[2]);
	const manifestPath = path.resolve(process.argv[3]);
	const result = buildCampaign(pinnedShowdown(showdownPath), loadManifest(manifestPath), manifestPath);
	process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
}

if (require.main === module) main();

module.exports = {buildCampaign, loadManifest, pinnedShowdown};
