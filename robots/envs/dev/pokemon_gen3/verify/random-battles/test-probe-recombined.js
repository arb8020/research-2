#!/usr/bin/env node
'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const {materialize} = require('./probe-recombined');

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

if (process.argv.length !== 3) throw new Error('usage: node test-probe-recombined.js SHOWDOWN_DIR');

function snapshot(directory) {
	const result = {};
	function visit(relative) {
		for (const name of fs.readdirSync(path.join(directory, relative)).sort()) {
			const child = path.join(relative, name);
			const absolute = path.join(directory, child);
			if (fs.statSync(absolute).isDirectory()) visit(child);
			else result[child] = fs.readFileSync(absolute, 'utf8');
		}
	}
	visit('');
	return result;
}

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'pokemon-recombined-probe-test-'));
try {
	const source = path.resolve(__dirname, 'recombination-manifest.json');
	const first = path.join(root, 'first');
	const second = path.join(root, 'second');
	const firstManifest = materialize(path.resolve(process.argv[2]), source, first);
	const secondManifest = materialize(path.resolve(process.argv[2]), source, second);
	assert.deepStrictEqual(firstManifest, secondManifest);
	assert.deepStrictEqual(snapshot(first), snapshot(second), 'materialized trees must be byte-identical');
	assert.strictEqual(firstManifest.cases.length, 4);
	for (const entry of firstManifest.cases) {
		assert(entry.expected_decisions > 0 && entry.expected_decisions <= entry.max_decisions);
		assert.strictEqual(entry.expected_boundaries, entry.expected_decisions + 1);
		assert(fs.existsSync(path.join(first, entry.team_p1)));
		assert(fs.existsSync(path.join(first, entry.team_p2)));
	}
	assert.throws(() => materialize(path.resolve(process.argv[2]), source, first), /target already exists/);
} finally {
	fs.rmSync(root, {recursive: true, force: true});
}

console.log('recombined battle materialization contract passed');
