'use strict';

const assert = require('assert');
const childProcess = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const {classifyFailure, persistCampaignFailure, validateCampaignFailure} = require('./artifact');

const classifications = [
	['generation', {}, 'generation'],
	['parse', {}, 'malformed-output'],
	['coverage', {}, 'coverage'],
	['comparison', {}, 'semantic-mismatch'],
	['replay', {}, 'replay'],
	['native-subprocess', {metadata: {status: null, timed_out: true}}, 'subprocess-timeout'],
	['native-subprocess', {metadata: {status: 9, timed_out: false}}, 'subprocess-nonzero'],
	['native-subprocess', {metadata: {status: null, timed_out: false}}, 'subprocess-spawn'],
];
for (const [stage, error, expected] of classifications) {
	assert.strictEqual(classifyFailure(stage, error), expected);
}

const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'pokemon-random-artifact-test-'));
try {
	const error = new Error('native exploded');
	error.metadata = {
		command: '/native', args: ['--case', 'x'], timeout_ms: 19, status: 7,
		signal: null, timed_out: false, stdout: 'partial output\n', stderr: 'diagnostic\n',
	};
	const context = {
		stage: 'native-subprocess', caseId: 'case/a', oracleRevision: 'revision',
		manifestText: '{"schema":"test"}\n', fixture: {id: 'case/a'},
		oracleText: '{"oracle":true}\n', nativeText: '{"native":true}\n',
	};
	const team = path.join(temporary, 'source-team.txt');
	fs.writeFileSync(team, 'Pokemon @ Item\n');
	context.teamSources = [team];
	const target = persistCampaignFailure(temporary, context, error);
	const originalMetadataText = fs.readFileSync(path.join(target, 'failure.json'), 'utf8');
	const metadata = validateCampaignFailure(target);
	assert.strictEqual(metadata.kind, 'subprocess-nonzero');
	assert.deepStrictEqual(metadata.subprocess, {
		command: '/native', args: ['--case', 'x'], timeout_ms: 19, status: 7,
		signal: null, timed_out: false,
	});
	assert.strictEqual(fs.readFileSync(path.join(target, 'stdout.txt'), 'utf8'), 'partial output\n');
	assert.strictEqual(fs.readFileSync(path.join(target, 'stderr.txt'), 'utf8'), 'diagnostic\n');
	assert.strictEqual(fs.readFileSync(path.join(target, 'team-p1.txt'), 'utf8'), 'Pokemon @ Item\n');

	const replay = childProcess.spawnSync(process.execPath,
		[path.join(__dirname, 'replay-artifact.js'), target], {encoding: 'utf8'});
	assert.strictEqual(replay.status, 0, replay.stderr);
	assert.match(replay.stdout, /validated subprocess-nonzero artifact/);

	fs.appendFileSync(path.join(target, 'stderr.txt'), 'tampered');
	assert.throws(() => validateCampaignFailure(target), /stderr digest mismatch/);
	const second = persistCampaignFailure(temporary, context, error);
	assert.notStrictEqual(second, target, 'retention must never overwrite prior evidence');
	assert.strictEqual(fs.readFileSync(path.join(second, 'failure.json'), 'utf8'), originalMetadataText,
		'identical evidence must have deterministic metadata');

	const invalidManifest = path.join(temporary, 'invalid-manifest.json');
	const integrationFailures = path.join(temporary, 'integration-failures');
	fs.writeFileSync(invalidManifest, '{not json}\n');
	const integration = childProcess.spawnSync(process.execPath, [
		path.join(__dirname, 'run.js'), temporary, invalidManifest, integrationFailures,
	], {encoding: 'utf8'});
	assert.notStrictEqual(integration.status, 0, 'invalid manifest must fail');
	const retained = fs.readdirSync(integrationFailures);
	assert.strictEqual(retained.length, 1, 'invalid manifest must retain exactly one artifact');
	const retainedMetadata = validateCampaignFailure(path.join(integrationFailures, retained[0]));
	assert.strictEqual(retainedMetadata.kind, 'generation');
	assert.match(integration.stderr, /failure retained at/);

	for (const [stage, failure, expected] of classifications) {
		const classified = failure instanceof Error ? failure : Object.assign(new Error(expected), failure);
		const retained = persistCampaignFailure(temporary, {...context, stage}, classified);
		assert.strictEqual(validateCampaignFailure(retained).kind, expected);
	}
} finally {
	fs.rmSync(temporary, {recursive: true, force: true});
}

console.log('random failure artifact contract passed');
