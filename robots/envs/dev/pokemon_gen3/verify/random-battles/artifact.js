'use strict';

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const SCHEMA = 'pokemon-gen3ou-random-campaign-failure-v1';
const KINDS = new Set([
	'generation', 'subprocess-timeout', 'subprocess-nonzero', 'subprocess-spawn',
	'malformed-output', 'coverage', 'semantic-mismatch', 'replay', 'internal',
]);

function digest(value) {
	return crypto.createHash('sha256').update(value).digest('hex');
}

function classifyFailure(stage, error) {
	if (error && error.metadata) {
		if (error.metadata.timed_out || error.code === 'ETIMEDOUT') return 'subprocess-timeout';
		if (error.metadata.status !== null && error.metadata.status !== 0) return 'subprocess-nonzero';
		return 'subprocess-spawn';
	}
	if (stage === 'generation') return 'generation';
	if (stage === 'parse') return 'malformed-output';
	if (stage === 'coverage') return 'coverage';
	if (stage === 'comparison') return 'semantic-mismatch';
	if (stage === 'replay') return 'replay';
	return 'internal';
}

function availableTarget(root, stem) {
	const safe = stem.replace(/[^a-zA-Z0-9_.-]/g, '-');
	for (let suffix = 0; ; suffix++) {
		const target = path.join(root, suffix ? `${safe}-${suffix}` : safe);
		if (!fs.existsSync(target)) return target;
	}
}

function writePayload(directory, name, value) {
	const bytes = Buffer.isBuffer(value) ? value : Buffer.from(
		typeof value === 'string' ? value : `${JSON.stringify(value, null, 2)}\n`);
	fs.writeFileSync(path.join(directory, name), bytes, {flag: 'wx'});
	return {file: name, sha256: digest(bytes), bytes: bytes.length};
}

function persistCampaignFailure(root, context, error) {
	const kind = classifyFailure(context.stage, error);
	const id = context.caseId || 'campaign';
	const target = availableTarget(root, `${id}-${kind}`);
	fs.mkdirSync(root, {recursive: true});
	const stage = fs.mkdtempSync(path.join(root, `.${path.basename(target)}.tmp-`));
	try {
		const files = {};
		if (context.manifestText !== undefined) {
			files.manifest = writePayload(stage, 'manifest.json', context.manifestText);
		}
		if (context.fixture) files.case = writePayload(stage, 'case.json', context.fixture);
		for (let side = 0; side < (context.teamSources || []).length; side++) {
			if (!fs.existsSync(context.teamSources[side])) continue;
			files[`team_p${side + 1}`] = writePayload(stage, `team-p${side + 1}.txt`,
				fs.readFileSync(context.teamSources[side]));
		}
		const subprocess = error && error.metadata ? {...error.metadata} : null;
		if (subprocess) {
			files.stdout = writePayload(stage, 'stdout.txt', subprocess.stdout || '');
			files.stderr = writePayload(stage, 'stderr.txt', subprocess.stderr || '');
			delete subprocess.stdout;
			delete subprocess.stderr;
		}
		if (context.oracleText !== undefined) {
			files.oracle = writePayload(stage, 'oracle.jsonl', context.oracleText);
		}
		if (context.nativeText !== undefined) {
			files.native = writePayload(stage, 'native.jsonl', context.nativeText);
		}
		const metadata = {
			schema: SCHEMA, kind, stage: context.stage, case_id: context.caseId || null,
			message: error instanceof Error ? error.message : String(error),
			oracle_revision: context.oracleRevision, subprocess, files,
			replay: {
				mode: files.case && kind === 'semantic-mismatch' ? 'differential-case' : 'validation-only',
			},
		};
		writePayload(stage, 'failure.json', metadata);
		fs.renameSync(stage, target);
		return target;
	} catch (failure) {
		fs.rmSync(stage, {recursive: true, force: true});
		throw failure;
	}
}

function validateCampaignFailure(target) {
	const filename = path.join(target, 'failure.json');
	const metadata = JSON.parse(fs.readFileSync(filename, 'utf8'));
	if (metadata.schema !== SCHEMA || !KINDS.has(metadata.kind) ||
		typeof metadata.stage !== 'string' || !metadata.files || !metadata.replay) {
		throw new Error('invalid randomized failure artifact');
	}
	for (const [label, descriptor] of Object.entries(metadata.files)) {
		if (!descriptor || typeof descriptor.file !== 'string' ||
			typeof descriptor.sha256 !== 'string' || !Number.isInteger(descriptor.bytes)) {
			throw new Error(`invalid ${label} descriptor`);
		}
		if (path.basename(descriptor.file) !== descriptor.file) {
			throw new Error(`invalid ${label} filename`);
		}
		const value = fs.readFileSync(path.join(target, descriptor.file));
		if (value.length !== descriptor.bytes || digest(value) !== descriptor.sha256) {
			throw new Error(`${label} digest mismatch`);
		}
	}
	return metadata;
}

module.exports = {SCHEMA, classifyFailure, persistCampaignFailure, validateCampaignFailure};
