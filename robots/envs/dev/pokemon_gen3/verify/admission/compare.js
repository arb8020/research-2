#!/usr/bin/env node
'use strict';

const assert = require('assert');
const fs = require('fs');

function readJsonl(file) {
	const contents = fs.readFileSync(file, 'utf8').trim();
	return contents ? contents.split('\n').map(line => JSON.parse(line)) : [];
}

function firstDifference(expected, actual, path = []) {
	if (Object.is(expected, actual)) return null;
	if (typeof expected !== typeof actual || expected === null || actual === null ||
		(typeof expected !== 'object')) return {path, expected, actual, kind: 'value'};
	if (Array.isArray(expected) !== Array.isArray(actual)) {
		return {path, expected, actual, kind: 'type'};
	}
	const expectedKeys = Object.keys(expected).sort();
	const actualKeys = Object.keys(actual).sort();
	if (expectedKeys.length !== actualKeys.length ||
		expectedKeys.some((key, index) => key !== actualKeys[index])) {
		return {path, expected: expectedKeys, actual: actualKeys, kind: 'keys'};
	}
	for (const key of expectedKeys) {
		const difference = firstDifference(expected[key], actual[key], [...path, key]);
		if (difference) return difference;
	}
	return null;
}

function compareRecords(expected, actual) {
	const difference = firstDifference(expected, actual);
	return difference ? {
		equal: false,
		fingerprint: `${difference.kind}:${difference.path.join('.')}`,
		difference,
	} : {equal: true, fingerprint: null, difference: null};
}

if (require.main === module) {
	const [oracleFile, nativeFile] = process.argv.slice(2);
	if (!oracleFile || !nativeFile) throw new Error('usage: compare.js ORACLE.jsonl NATIVE.jsonl');
	const oracle = readJsonl(oracleFile);
	const native = readJsonl(nativeFile);
	const comparison = compareRecords(oracle, native);
	assert.deepStrictEqual(native, oracle,
		comparison.difference && JSON.stringify(comparison.difference));
	process.stdout.write(`admission differential: ${native.length}/${oracle.length} exact\n`);
}

module.exports = {compareRecords, firstDifference, readJsonl};
