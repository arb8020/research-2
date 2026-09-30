#!/usr/bin/env node
'use strict';

const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');

const {compile} = require('../cases/compile-c');
const {compareDocuments, parseJSONL} = require('../slice/compare');
const {campaignCoverage} = require('./coverage');
const {generate} = require('./generate');
const {
	createEvaluator, minimizeFailure, persistMinimizedFailure, persistOriginalFailure,
	recordMinimizationFailure,
} = require('./minimize');
const {execute} = require('./subprocess');
const {persistCampaignFailure} = require('./artifact');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const root = path.resolve(__dirname, '../..');
const manifestPath = path.resolve(process.argv[3] || path.join(__dirname, 'manifest.json'));
const failureRoot = path.resolve(process.argv[4] || path.join(__dirname, 'failures'));
const summaryPathValue = process.argv[5] || process.env.POKEMON_RANDOM_SUMMARY;
const summaryPath = summaryPathValue ? path.resolve(summaryPathValue) : null;
const showdown = process.argv[2] && path.resolve(process.argv[2]);
if (!showdown) {
	throw new Error('usage: node run.js SHOWDOWN_DIR [MANIFEST.json] [FAILURE_DIR] [SUMMARY.json]');
}

function sha256(value) {
	return crypto.createHash('sha256').update(value).digest('hex');
}

function writeSummary(filename, summary) {
	fs.mkdirSync(path.dirname(filename), {recursive: true});
	const temporary = `${filename}.tmp-${process.pid}`;
	fs.writeFileSync(temporary, `${JSON.stringify(summary, null, 2)}\n`, {flag: 'wx'});
	fs.renameSync(temporary, filename);
}

function validateManifest(value) {
	if (value.schema !== 'pokemon-gen3ou-random-battle-manifest-v2' ||
		value.oracle_revision !== REVISION || !Array.isArray(value.cases) ||
		value.cases.length === 0 || value.policy !== 'lcg32-v1' ||
		!Array.isArray(value.coverage_dimensions) || !Array.isArray(value.coverage_targets)) {
		throw new Error('invalid randomized battle manifest');
	}
	const ids = new Set();
	for (const entry of value.cases) {
		if (!entry || typeof entry.id !== 'string' || ids.has(entry.id) ||
			typeof entry.team_pairing !== 'string' || entry.team_pairing.length === 0 ||
			!Array.isArray(entry.battle_seed) || entry.battle_seed.length !== 4 ||
			!Number.isInteger(entry.policy_seed) || !Number.isInteger(entry.max_decisions) ||
			!Number.isInteger(entry.expected_decisions) ||
			entry.expected_boundaries !== entry.expected_decisions + 1) {
			throw new Error(`invalid randomized manifest entry ${JSON.stringify(entry?.id)}`);
		}
		ids.add(entry.id);
	}
}

function appendOracle(casePath, environment) {
	return execute(process.execPath, [path.join(root, 'verify/slice/oracle.js'), casePath], {
		env: environment,
	});
}

function availableFailureTarget(caseId, boundary) {
	const stem = `${caseId}-boundary-${boundary}`.replace(/[^a-zA-Z0-9_.-]/g, '-');
	for (let suffix = 0; ; suffix++) {
		const target = path.join(failureRoot, suffix === 0 ? stem : `${stem}-${suffix}`);
		if (!fs.existsSync(target)) return target;
	}
}

const manifestText = fs.readFileSync(manifestPath, 'utf8');
let manifest;
const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'pokemon-gen3-random-'));
const failureContext = {
	stage: 'generation', manifestText, oracleRevision: REVISION,
	caseId: null, fixture: null, teamSources: [], oracleText: undefined, nativeText: undefined,
};
try {
	manifest = JSON.parse(manifestText);
	validateManifest(manifest);
	const fixtures = [];
	const casePaths = [];
	for (const entry of manifest.cases) {
		failureContext.stage = 'generation';
		failureContext.caseId = entry.id;
		failureContext.fixture = null;
		failureContext.teamSources = [entry.team_p1, entry.team_p2].map(filename =>
			path.resolve(path.dirname(manifestPath), filename));
		const teamPaths = [entry.team_p1, entry.team_p2].map((filename, side) => {
			const source = path.resolve(path.dirname(manifestPath), filename);
			const target = path.join(directory, `${entry.id}-p${side + 1}.txt`);
			fs.copyFileSync(source, target);
			return target;
		});
		const fixture = generate({
			showdown, teamPaths, id: entry.id,
			battleSeed: entry.battle_seed,
			policySeed: entry.policy_seed,
			maxDecisions: entry.max_decisions,
		});
		failureContext.fixture = fixture;
		if (fixture.choices.length !== entry.expected_decisions) {
			throw new Error(`${entry.id}: decision count drift`);
		}
		if (fixture.limits.max_boundaries !== entry.expected_boundaries) {
			throw new Error(`${entry.id}: boundary count drift`);
		}
		const casePath = path.join(directory, `${entry.id}.json`);
		fs.writeFileSync(casePath, `${JSON.stringify(fixture, null, 2)}\n`);
		fixtures.push(fixture);
		casePaths.push(casePath);
	}

	failureContext.caseId = null;
	failureContext.fixture = null;
	failureContext.teamSources = [];
	failureContext.stage = 'build';
	const ids = JSON.parse(fs.readFileSync(path.join(root, 'verify/cases/native-id-map.json')));
	fs.writeFileSync(path.join(directory, 'generated_cases.h'), compile(fixtures, ids));
	fs.copyFileSync(path.join(root, 'verify/slice/native.c'), path.join(directory, 'native.c'));
	const native = path.join(directory, 'native');
	execute(process.env.CC || 'cc', [
		'-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-O2',
		`-I${path.join(root, 'native')}`,
		`-I${path.join(root, 'verify/cases')}`,
		`-I${directory}`,
		path.join(directory, 'native.c'),
		path.join(root, 'native/pokemon.c'),
		path.join(root, 'native/gen3_rules.c'),
		path.join(root, 'native/gen3_slice_data.c'),
		path.join(root, 'native/singles2.c'), '-o', native,
	]);

	const environment = {...process.env, POKEMON_SHOWDOWN_DIR: showdown};
	failureContext.stage = 'oracle-subprocess';
	const oracle = casePaths.map(casePath => appendOracle(casePath, environment)).join('');
	failureContext.oracleText = oracle;
	failureContext.stage = 'native-subprocess';
	const nativeOutput = execute(native, []);
	failureContext.nativeText = nativeOutput;
	const oraclePath = path.join(directory, 'oracle.jsonl');
	const nativePath = path.join(directory, 'native.jsonl');
	fs.writeFileSync(oraclePath, oracle);
	fs.writeFileSync(nativePath, nativeOutput);
	failureContext.stage = 'parse';
	const oracleRecords = parseJSONL(oracle, 'random battle oracle output');
	const nativeRecords = parseJSONL(nativeOutput, 'random battle native output');
	failureContext.stage = 'comparison';
	const comparison = compareDocuments(oracleRecords, nativeRecords);
	if (comparison.fingerprint) {
		const boundary = comparison.fingerprint.boundary;
		const indexMatch = /^\$\[(\d+)\]/.exec(comparison.difference.path);
		const record = indexMatch ?
			(oracleRecords[Number(indexMatch[1])] || nativeRecords[Number(indexMatch[1])]) : null;
		if (!record) throw new Error(`cannot identify divergent case at boundary ${boundary}`);
		const index = fixtures.findIndex(value => value.id === record.case_id);
		if (index < 0) throw new Error(`unknown divergent case ${record.case_id}`);
		const target = availableFailureTarget(record.case_id, boundary);
		const original = {
			oracle: oracleRecords.filter(value => value.case_id === record.case_id),
			native: nativeRecords.filter(value => value.case_id === record.case_id),
		};
		persistOriginalFailure(target, fixtures[index], original, comparison.fingerprint, directory);
		try {
			const minimized = minimizeFailure(fixtures[index], createEvaluator(showdown, directory));
			persistMinimizedFailure(target, minimized, directory);
		} catch (error) {
			recordMinimizationFailure(target, record.case_id, error);
			const failure = new Error(`random battle divergence ${JSON.stringify(comparison.fingerprint)}; ` +
				`full failure retained at ${target}; minimization failed: ${error.message}`);
			failure.retainedArtifact = target;
			throw failure;
		}
		const failure = new Error(`random battle divergence ${JSON.stringify(comparison.fingerprint)}; ` +
			`minimized failure retained at ${target}`);
		failure.retainedArtifact = target;
		throw failure;
	}
	console.log(`matched ${oracleRecords.length} boundaries`);

	failureContext.stage = 'replay';
	const repeatedOracle = casePaths.map(casePath => appendOracle(casePath, environment)).join('');
	const repeatedNative = execute(native, []);
	if (repeatedOracle !== oracle) throw new Error('oracle randomized replay is nondeterministic');
	if (repeatedNative !== nativeOutput) throw new Error('native randomized replay is nondeterministic');
	console.log(`randomized replay stable for ${manifest.cases.length} complete battle(s)`);
	failureContext.stage = 'coverage';
	const coverage = campaignCoverage(manifest, fixtures, oracleRecords);
	if (coverage.acceptance.status !== 'pass') {
		throw new Error(`randomized campaign coverage failed: ${coverage.acceptance.failures.join('; ')}`);
	}
	if (summaryPath) {
		writeSummary(summaryPath, {
			schema: 'pokemon-gen3ou-random-campaign-summary-v2',
			oracle_revision: REVISION,
			manifest_sha256: sha256(manifestText),
			totals: {
				cases: fixtures.length,
				decisions: fixtures.reduce((total, fixture) => total + fixture.choices.length, 0),
				boundaries: oracleRecords.length,
			},
			oracle_sha256: sha256(oracle),
			native_sha256: sha256(nativeOutput),
			replay: {oracle: 'stable', native: 'stable'},
			coverage,
		});
		console.log(`wrote deterministic campaign summary ${summaryPath}`);
	}
} catch (error) {
	if (error.retainedArtifact) throw error;
	const target = persistCampaignFailure(failureRoot, failureContext, error);
	const failure = new Error(`${error.message}; failure retained at ${target}`);
	failure.cause = error;
	failure.retainedArtifact = target;
	throw failure;
} finally {
	fs.rmSync(directory, {recursive: true, force: true});
}
