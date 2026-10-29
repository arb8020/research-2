#!/usr/bin/env node
'use strict';

// A full-battle trace is causal: choice N produces boundary N + 1. Removing an
// interior choice changes the battle, so the only generally honest reduction is
// to retain the prefix through the first divergent boundary.

const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');

const {compile} = require('../cases/compile-c');
const {normalizeCase} = require('../cases/normalize');
const {compareDocuments, parseJSONL} = require('../slice/compare');
const {execute} = require('./subprocess');

const root = path.resolve(__dirname, '../..');

function sameFingerprint(left, right) {
	return JSON.stringify(left) === JSON.stringify(right);
}

function causalPrefix(fixture, boundary) {
	if (!Number.isInteger(boundary) || boundary < 0) {
		throw new Error(`cannot minimize non-boundary divergence ${JSON.stringify(boundary)}`);
	}
	const choiceCount = Math.min(boundary, fixture.choices.length);
	if (fixture.forced_outcomes.length !== 0) {
		throw new Error('causal-prefix minimization does not infer ownership of forced outcomes');
	}
	const minimized = JSON.parse(JSON.stringify(fixture));
	minimized.choices = minimized.choices.slice(0, choiceCount);
	minimized.source_choices = minimized.source_choices.slice(0, choiceCount);
	minimized.limits = {
		max_boundaries: choiceCount + 1,
		max_actions: minimized.choices.flat().filter(choice => choice !== null).length,
	};
	return normalizeCase(minimized);
}

function resultFingerprint(result) {
	const comparison = compareDocuments(result.oracle, result.native);
	if (!comparison.fingerprint) throw new Error('cannot minimize an agreeing replay');
	return comparison.fingerprint;
}

function minimizeFailure(fixture, evaluate) {
	const normalized = normalizeCase(fixture);
	const original = evaluate(normalized);
	const fingerprint = resultFingerprint(original);
	const minimized = causalPrefix(normalized, fingerprint.boundary);
	const first = evaluate(minimized);
	const second = evaluate(minimized);
	const firstFingerprint = resultFingerprint(first);
	const secondFingerprint = resultFingerprint(second);
	if (!sameFingerprint(fingerprint, firstFingerprint) ||
		!sameFingerprint(firstFingerprint, secondFingerprint)) {
		throw new Error(`causal-prefix fingerprint drift: original=${JSON.stringify(fingerprint)} ` +
			`first=${JSON.stringify(firstFingerprint)} second=${JSON.stringify(secondFingerprint)}`);
	}
	if (JSON.stringify(first.oracle) !== JSON.stringify(second.oracle)) {
		throw new Error('oracle causal-prefix replay is nondeterministic');
	}
	if (JSON.stringify(first.native) !== JSON.stringify(second.native)) {
		throw new Error('native causal-prefix replay is nondeterministic');
	}
	return {
		fixture: minimized, originalFixture: normalized, fingerprint, original, replay: first,
		originalChoiceCount: normalized.choices.length,
	};
}

function copyTeamSources(fixture, sourceDirectory, targetDirectory) {
	for (let side = 0; side < fixture.teams.length; side++) {
		const source = path.resolve(sourceDirectory, fixture.teams[side].source);
		const name = `${fixture.id}.p${side + 1}.txt`;
		if (!fs.statSync(source).isFile()) throw new Error(`invalid source team ${source}`);
		fs.copyFileSync(source, path.join(targetDirectory, name));
		fixture.teams[side].source = name;
	}
}

function createEvaluator(showdown, sourceDirectory) {
	const ids = JSON.parse(fs.readFileSync(path.join(root, 'verify/cases/native-id-map.json'), 'utf8'));
	return fixture => {
		const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'pokemon-gen3-minimize-run-'));
		try {
			const executableFixture = JSON.parse(JSON.stringify(fixture));
			copyTeamSources(executableFixture, sourceDirectory, directory);
			const casePath = path.join(directory, `${fixture.id}.case.json`);
			fs.writeFileSync(casePath, `${JSON.stringify(executableFixture, null, 2)}\n`);
			fs.writeFileSync(path.join(directory, 'generated_cases.h'), compile([executableFixture], ids));
			fs.copyFileSync(path.join(root, 'verify/slice/native.c'), path.join(directory, 'native.c'));
			const native = path.join(directory, 'native');
			execute(process.env.CC || 'cc', [
				'-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-O2',
				`-I${path.join(root, 'native')}`, `-I${path.join(root, 'verify/cases')}`,
				`-I${directory}`, path.join(directory, 'native.c'),
				path.join(root, 'native/pokemon.c'), path.join(root, 'native/gen3_rules.c'),
				path.join(root, 'native/gen3_slice_data.c'), path.join(root, 'native/singles2.c'),
				'-o', native,
			]);
			const oracleText = execute(process.execPath,
				[path.join(root, 'verify/slice/oracle.js'), casePath],
				{env: {...process.env, POKEMON_SHOWDOWN_DIR: showdown}});
			const nativeText = execute(native, []);
			return {
				oracle: parseJSONL(oracleText, 'oracle output'),
				native: parseJSONL(nativeText, 'native output'),
			};
		} finally {
			fs.rmSync(directory, {recursive: true, force: true});
		}
	};
}

function digest(value) {
	const bytes = typeof value === 'string' || Buffer.isBuffer(value) ? value : JSON.stringify(value);
	return crypto.createHash('sha256').update(bytes).digest('hex');
}

function recordsJSONL(records) {
	return records.map(record => JSON.stringify(record)).join('\n') + '\n';
}

function persistOriginalFailure(target, fixture, result, fingerprint, sourceDirectory) {
	const parent = path.dirname(target);
	fs.mkdirSync(parent, {recursive: true});
	if (fs.existsSync(target)) throw new Error(`artifact target already exists: ${target}`);
	const stage = fs.mkdtempSync(path.join(parent, `.${path.basename(target)}.tmp-`));
	try {
		const original = JSON.parse(JSON.stringify(fixture));
		copyTeamSources(original, sourceDirectory, stage);
		fs.writeFileSync(path.join(stage, `${original.id}.original.case.json`),
			`${JSON.stringify(original, null, 2)}\n`, {flag: 'wx'});
		fs.writeFileSync(path.join(stage, 'original.oracle.jsonl'), recordsJSONL(result.oracle), {flag: 'wx'});
		fs.writeFileSync(path.join(stage, 'original.native.jsonl'), recordsJSONL(result.native), {flag: 'wx'});
		fs.writeFileSync(path.join(stage, `${original.id}.failure.json`), `${JSON.stringify({
			schema: 'pokemon-native-differential-failure-v2',
			fingerprint,
			original: {
				case: `${original.id}.original.case.json`,
				choices: original.choices.length,
				oracle: 'original.oracle.jsonl', native: 'original.native.jsonl',
				oracle_sha256: digest(recordsJSONL(result.oracle)),
				native_sha256: digest(recordsJSONL(result.native)),
			},
			minimization: {status: 'pending'},
		}, null, 2)}\n`, {flag: 'wx'});
		fs.renameSync(stage, target);
	} catch (error) {
		fs.rmSync(stage, {recursive: true, force: true});
		throw error;
	}
}

function persistMinimizedFailure(target, result, sourceDirectory) {
	const fixture = JSON.parse(JSON.stringify(result.fixture));
	copyTeamSources(fixture, sourceDirectory, target);
	const caseName = `${fixture.id}.case.json`;
	const failureName = `${fixture.id}.failure.json`;
	fs.writeFileSync(path.join(target, caseName), `${JSON.stringify(fixture, null, 2)}\n`, {flag: 'wx'});
	fs.writeFileSync(path.join(target, 'minimized.oracle.jsonl'), recordsJSONL(result.replay.oracle), {flag: 'wx'});
	fs.writeFileSync(path.join(target, 'minimized.native.jsonl'), recordsJSONL(result.replay.native), {flag: 'wx'});
	const metadata = JSON.parse(fs.readFileSync(path.join(target, failureName), 'utf8'));
	metadata.minimization = {
		status: 'complete', case: caseName,
		choices: fixture.choices.length, boundaries: fixture.limits.max_boundaries,
		oracle: 'minimized.oracle.jsonl', native: 'minimized.native.jsonl',
		oracle_sha256: digest(recordsJSONL(result.replay.oracle)),
		native_sha256: digest(recordsJSONL(result.replay.native)),
		deterministic_replays: 2,
	};
	fs.writeFileSync(path.join(target, failureName), `${JSON.stringify(metadata, null, 2)}\n`);
}

function recordMinimizationFailure(target, fixtureId, error) {
	const failureName = `${fixtureId}.failure.json`;
	const filename = path.join(target, failureName);
	const metadata = JSON.parse(fs.readFileSync(filename, 'utf8'));
	metadata.minimization = {
		status: 'failed',
		error: error.message,
		...(error.metadata ? {subprocess: error.metadata} : {}),
	};
	fs.writeFileSync(filename, `${JSON.stringify(metadata, null, 2)}\n`);
}

function persistFailure(target, result, sourceDirectory) {
	persistOriginalFailure(target, result.originalFixture, result.original,
		result.fingerprint, sourceDirectory);
	persistMinimizedFailure(target, result, sourceDirectory);
}

function main(argv) {
	if (argv.length !== 3) {
		throw new Error('usage: node minimize.js SHOWDOWN_DIR CASE.json ARTIFACT_DIR');
	}
	const showdown = path.resolve(argv[0]);
	const casePath = path.resolve(argv[1]);
	const target = path.resolve(argv[2]);
	const fixture = JSON.parse(fs.readFileSync(casePath, 'utf8'));
	const result = minimizeFailure(fixture, createEvaluator(showdown, path.dirname(casePath)));
	persistFailure(target, result, path.dirname(casePath));
	console.log(`retained ${result.fixture.choices.length} choices through boundary ` +
		`${result.fingerprint.boundary}: ${target}`);
}

if (require.main === module) main(process.argv.slice(2));

module.exports = {
	causalPrefix, createEvaluator, minimizeFailure, persistFailure, persistOriginalFailure,
	persistMinimizedFailure, recordMinimizationFailure, sameFingerprint,
};
