#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const {generate} = require('./generate');
const {buildCampaign, loadManifest, pinnedShowdown} = require('./recombine');

function reject(message) {
	throw new Error(`recombined battle probe: ${message}`);
}

function writeNew(filename, contents) {
	fs.writeFileSync(filename, contents, {flag: 'wx'});
}

function materialize(showdownPath, sourceManifestPath, targetDirectory) {
	const resolvedManifest = path.resolve(sourceManifestPath);
	const target = path.resolve(targetDirectory);
	if (fs.existsSync(target)) reject(`target already exists: ${target}`);
	const parent = path.dirname(target);
	if (!fs.existsSync(parent)) reject(`target parent does not exist: ${parent}`);
	const temporary = fs.mkdtempSync(path.join(parent, `.${path.basename(target)}.tmp-`));
	try {
		const sourceManifest = loadManifest(resolvedManifest);
		const showdown = pinnedShowdown(path.resolve(showdownPath));
		const campaign = buildCampaign(showdown, sourceManifest, resolvedManifest);
		const baseline = JSON.parse(fs.readFileSync(path.resolve(__dirname, 'manifest.json'), 'utf8'));
		const teamsDirectory = path.join(temporary, 'teams');
		fs.mkdirSync(teamsDirectory);
		const cases = [];
		for (const entry of campaign.cases) {
			const teamNames = [`${entry.id}-p1.txt`, `${entry.id}-p2.txt`];
			const teamPaths = teamNames.map((name, side) => {
				const filename = path.join(teamsDirectory, name);
				writeNew(filename, entry.teams[side].source);
				return filename;
			});
			const fixture = generate({
				showdown: path.resolve(showdownPath), teamPaths, id: `rc-${entry.id}`,
				battleSeed: entry.battle_seed, policySeed: entry.policy_seed, maxDecisions: 1023,
			});
			cases.push({
				id: fixture.id,
				team_pairing: `${entry.id}-pool-v1`,
				team_p1: `teams/${teamNames[0]}`,
				team_p2: `teams/${teamNames[1]}`,
				battle_seed: entry.battle_seed,
				policy_seed: entry.policy_seed,
				max_decisions: 1023,
				expected_decisions: fixture.choices.length,
				expected_boundaries: fixture.limits.max_boundaries,
			});
		}
		const output = {
			schema: 'pokemon-gen3ou-random-battle-manifest-v2',
			oracle_revision: sourceManifest.oracle_revision,
			policy: baseline.policy,
			coverage_dimensions: baseline.coverage_dimensions,
			coverage_targets: baseline.coverage_targets,
			provenance: {
				kind: 'deterministic-legal-team-recombination',
				campaign_seed: sourceManifest.campaign_seed,
				pool: sourceManifest.pool,
			},
			cases,
		};
		writeNew(path.join(temporary, 'manifest.json'), `${JSON.stringify(output, null, 2)}\n`);
		fs.renameSync(temporary, target);
		return output;
	} catch (error) {
		fs.rmSync(temporary, {recursive: true, force: true});
		throw error;
	}
}

function main() {
	if (process.argv.length !== 5) {
		reject('usage: node probe-recombined.js SHOWDOWN_DIR RECOMBINATION_MANIFEST.json OUTPUT_DIR');
	}
	const manifest = materialize(process.argv[2], process.argv[3], process.argv[4]);
	const decisions = manifest.cases.reduce((sum, entry) => sum + entry.expected_decisions, 0);
	const boundaries = manifest.cases.reduce((sum, entry) => sum + entry.expected_boundaries, 0);
	console.log(`materialized ${manifest.cases.length} naturally terminating battles ` +
		`(${decisions} decisions, ${boundaries} boundaries)`);
}

if (require.main === module) main();

module.exports = {materialize};
