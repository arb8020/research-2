#!/usr/bin/env node
'use strict';

const assert = require('assert');
const fs = require('fs');

const [mode, resultFile, contractFile] = process.argv.slice(2);
if (!['candidate', 'reference'].includes(mode) || !resultFile || !contractFile) {
	throw new Error('usage: node check.js candidate|reference RESULT.json CONTRACT.json');
}
const result = JSON.parse(fs.readFileSync(resultFile, 'utf8'));
const contract = JSON.parse(fs.readFileSync(contractFile, 'utf8'));

function sameWorkload(expected) {
	assert.strictEqual(result.workload, expected.workload);
	assert.strictEqual(result.env_count, expected.environment_count);
	assert.strictEqual(result.deterministic_digest, expected.deterministic_digest,
		'performance workload digest changed');
}

if (mode === 'candidate') {
	assert.strictEqual(contract.schema, 'pokemon-gen3ou-ocean-candidate-calibration-v1');
	assert.strictEqual(contract.kind, 'retained-candidate-calibration');
	sameWorkload(contract);
	const floor = contract.candidate_floor;
	const failures = [];
	if (result.batch_median_boundaries_per_second < floor.batch_median_boundaries_per_second) {
		failures.push(`median ${result.batch_median_boundaries_per_second} < ${floor.batch_median_boundaries_per_second}`);
	}
	if (result.batch_p99_sweep_latency_ms > floor.batch_p99_sweep_latency_ms) {
		failures.push(`p99 ${result.batch_p99_sweep_latency_ms} > ${floor.batch_p99_sweep_latency_ms}`);
	}
	if (result.incremental_rss_per_env_bytes > floor.incremental_rss_per_env_bytes) {
		failures.push(`RSS/env ${result.incremental_rss_per_env_bytes} > ${floor.incremental_rss_per_env_bytes}`);
	}
	if (failures.length) throw new Error(`Ocean candidate performance gate failed: ${failures.join('; ')}`);
	process.stdout.write(`Ocean candidate performance gate passed: ` +
		`${result.batch_median_boundaries_per_second.toFixed(3)} boundaries/s, ` +
		`${result.batch_p99_sweep_latency_ms.toFixed(3)} ms p99, ` +
		`${result.incremental_rss_per_env_bytes.toFixed(3)} bytes RSS/env\n`);
} else {
	assert.strictEqual(contract.schema, 'pokemon-gen3ou-ocean-reference-contract-v1');
	assert.strictEqual(contract.kind, 'independent-verifier-reference');
	if (contract.status !== 'frozen') {
		throw new Error(`Ocean reference gate unavailable: contract status is ${JSON.stringify(contract.status)}`);
	}
	assert.strictEqual(typeof contract.reference_implementation_id, 'string');
	assert.ok(contract.reference_implementation_id.length > 0);
	assert.notStrictEqual(contract.reference_implementation_id,
		contract.candidate_implementation_id,
		'reference and candidate implementations must be independently identified');
	assert.strictEqual(typeof contract.container_digest, 'string');
	assert.match(contract.container_digest, /^sha256:[0-9a-f]{64}$/);
	assert.ok(Number.isFinite(contract.reference_batch_median_boundaries_per_second));
	assert.ok(contract.reference_batch_median_boundaries_per_second > 0);
	assert.ok(Number.isFinite(contract.minimum_reference_ratio));
	assert.ok(contract.minimum_reference_ratio > 0);
	sameWorkload(contract);
	const floor = contract.reference_batch_median_boundaries_per_second *
		contract.minimum_reference_ratio;
	if (result.batch_median_boundaries_per_second < floor) {
		throw new Error(`Ocean reference performance gate failed: median ` +
			`${result.batch_median_boundaries_per_second} < ${contract.minimum_reference_ratio}x ` +
			`independent frozen reference (${floor})`);
	}
	process.stdout.write(`Ocean reference performance gate passed: ` +
		`${result.batch_median_boundaries_per_second.toFixed(3)} boundaries/s >= ` +
		`${contract.minimum_reference_ratio}x independent frozen reference (${floor.toFixed(3)})\n`);
}
