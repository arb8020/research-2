'use strict';

const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');

const {normalizeCase} = require('../cases/normalize');
const {divergenceFingerprint, firstDifference} = require('../slice/compare');
const {
	causalPrefix, minimizeFailure, persistFailure, persistOriginalFailure,
	recordMinimizationFailure,
} = require('./minimize');

const fixturePath = path.resolve(__dirname, '../cases/accepted/decisions-switch-targets.json');
const fixture = JSON.parse(fs.readFileSync(fixturePath, 'utf8'));

assert.deepStrictEqual(
	divergenceFingerprint(
		[{boundary: 0, state: {hp: 10}}, {boundary: 1, state: {hp: 9}}],
		[{boundary: 0, state: {hp: 10}}, {boundary: 1, state: {hp: 8}}]),
	{boundary: 1, path: '$.state.hp', mismatch_class: 'value'});
assert.strictEqual(firstDifference([{a: 1}], [{a: 1}, {a: 2}]).mismatchClass, 'array-length');
assert.strictEqual(firstDifference([{a: 1}], [{a: 1, b: 2}]).mismatchClass, 'object-keys');

const prefix = causalPrefix(fixture, 2);
assert.strictEqual(prefix.choices.length, 2);
assert.strictEqual(prefix.source_choices.length, 2);
assert.deepStrictEqual(prefix.teams, normalizeCase(fixture).teams);
assert.deepStrictEqual(prefix.seed, fixture.seed);
assert.deepStrictEqual(prefix.limits, {max_boundaries: 3, max_actions: 4});

let evaluations = 0;
const evaluate = candidate => {
	evaluations++;
	const oracle = [];
	const native = [];
	for (let boundary = 0; boundary <= candidate.choices.length; boundary++) {
		oracle.push({case_id: candidate.id, boundary, state: {hp: 10 - boundary}});
		native.push({case_id: candidate.id, boundary, state: {hp: 10 - boundary}});
	}
	if (candidate.choices.length >= 2) native[2].state.hp--;
	return {oracle, native};
};
const result = minimizeFailure(fixture, evaluate);
assert.strictEqual(evaluations, 3, 'one discovery and two fresh minimized replays');
assert.strictEqual(result.fixture.choices.length, 2);
assert.deepStrictEqual(result.fingerprint,
	{boundary: 2, path: '$.state.hp', mismatch_class: 'value'});

let unstableCalls = 0;
assert.throws(() => minimizeFailure(fixture, candidate => {
	const output = evaluate(candidate);
	unstableCalls++;
	if (unstableCalls === 3) output.native[2].state.hp--;
	return output;
}), /native causal-prefix replay is nondeterministic/);
assert.throws(() => causalPrefix({...fixture, forced_outcomes: [
	{label: 'move.accuracy', occurrence: 1, range: 100, result: 0},
]}, 2), /does not infer ownership of forced outcomes/);

const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'pokemon-minimizer-test-'));
try {
	const artifact = path.join(temporary, 'retained-failure');
	persistFailure(artifact, result, path.dirname(fixturePath));
	const casePath = path.join(artifact, `${fixture.id}.case.json`);
	const originalCasePath = path.join(artifact, `${fixture.id}.original.case.json`);
	const failurePath = path.join(artifact, `${fixture.id}.failure.json`);
	assert.ok(fs.statSync(casePath).isFile());
	assert.ok(fs.statSync(originalCasePath).isFile());
	assert.ok(fs.statSync(failurePath).isFile());
	const persisted = normalizeCase(JSON.parse(fs.readFileSync(casePath, 'utf8')));
	assert.strictEqual(persisted.choices.length, 2);
	for (const team of persisted.teams) {
		assert.ok(fs.statSync(path.join(artifact, team.source)).isFile());
	}
	const metadata = JSON.parse(fs.readFileSync(failurePath, 'utf8'));
	assert.strictEqual(metadata.schema, 'pokemon-native-differential-failure-v2');
	assert.deepStrictEqual(metadata.fingerprint, result.fingerprint);
	assert.strictEqual(metadata.original.choices, 3);
	assert.strictEqual(metadata.minimization.status, 'complete');
	assert.strictEqual(metadata.minimization.choices, 2);
	assert.strictEqual(metadata.minimization.deterministic_replays, 2);
	for (const filename of [
		'original.oracle.jsonl', 'original.native.jsonl',
		'minimized.oracle.jsonl', 'minimized.native.jsonl',
	]) assert.ok(fs.statSync(path.join(artifact, filename)).isFile());
	assert.throws(() => persistFailure(artifact, result, path.dirname(fixturePath)),
		/artifact target already exists/);

	const failedArtifact = path.join(temporary, 'minimizer-failed');
	persistOriginalFailure(failedArtifact, result.originalFixture, result.original,
		result.fingerprint, path.dirname(fixturePath));
	const subprocessError = new Error('deadline exceeded');
	subprocessError.metadata = {command: 'oracle', timeout_ms: 10, status: null, signal: 'SIGKILL'};
	recordMinimizationFailure(failedArtifact, fixture.id, subprocessError);
	const failedMetadata = JSON.parse(fs.readFileSync(
		path.join(failedArtifact, `${fixture.id}.failure.json`), 'utf8'));
	assert.strictEqual(failedMetadata.minimization.status, 'failed');
	assert.strictEqual(failedMetadata.minimization.error, 'deadline exceeded');
	assert.deepStrictEqual(failedMetadata.minimization.subprocess, subprocessError.metadata);
	assert.ok(fs.statSync(path.join(failedArtifact, `${fixture.id}.original.case.json`)).isFile());
	assert.ok(fs.statSync(path.join(failedArtifact, 'original.oracle.jsonl')).isFile());
} finally {
	fs.rmSync(temporary, {recursive: true, force: true});
}

console.log('causal-prefix minimizer contract passed');
