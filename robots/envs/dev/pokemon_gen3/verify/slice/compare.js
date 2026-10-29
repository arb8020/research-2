'use strict';

const fs = require('fs');

function parseJSONL(source, label = 'JSONL artifact') {
	if (source.length === 0) throw new Error(`${label}: empty JSONL artifact`);
	if (!source.endsWith('\n')) {
		throw new Error(`${label}: truncated JSONL artifact (missing final newline)`);
	}
	return source.split(/\r?\n/).filter(line => line.length).map((line, index) => {
		try {
			return JSON.parse(line);
		} catch (error) {
			throw new Error(`${label}:${index + 1}: invalid JSON: ${error.message}`);
		}
	});
}

function readJSONL(filename) {
	return parseJSONL(fs.readFileSync(filename, 'utf8'), filename);
}

function firstDifference(expected, actual, path = '$') {
	if (Object.is(expected, actual)) return null;
	if (expected === undefined) return {path, mismatchClass: 'missing-oracle', expected, actual};
	if (actual === undefined) return {path, mismatchClass: 'missing-native', expected, actual};
	if (typeof expected !== typeof actual || expected === null || actual === null) {
		return {path, mismatchClass: 'type', expected, actual};
	}
	if (Array.isArray(expected) || Array.isArray(actual)) {
		if (!Array.isArray(expected) || !Array.isArray(actual)) {
			return {path, mismatchClass: 'type', expected, actual};
		}
		const commonLength = Math.min(expected.length, actual.length);
		for (let i = 0; i < commonLength; i++) {
			const difference = firstDifference(expected[i], actual[i], `${path}[${i}]`);
			if (difference) return difference;
		}
		if (expected.length !== actual.length) {
			return {
				path: `${path}[${commonLength}]`, mismatchClass: 'array-length',
				expected: expected[commonLength], actual: actual[commonLength],
			};
		}
		return null;
	}
	if (typeof expected !== 'object') return {path, mismatchClass: 'value', expected, actual};
	const expectedKeys = Object.keys(expected).sort();
	const actualKeys = Object.keys(actual).sort();
	const keyDifference = firstDifference(expectedKeys, actualKeys, `${path}.__keys__`);
	if (keyDifference) return {...keyDifference, mismatchClass: 'object-keys'};
	for (const key of expectedKeys) {
		const difference = firstDifference(expected[key], actual[key], `${path}.${key}`);
		if (difference) return difference;
	}
	return null;
}

function divergenceFingerprint(expected, actual) {
	const difference = firstDifference(expected, actual);
	if (!difference) return null;
	const match = /^\$\[(\d+)\](.*)$/.exec(difference.path);
	if (!match) {
		return {boundary: null, path: difference.path, mismatch_class: difference.mismatchClass};
	}
	const index = Number(match[1]);
	const record = expected[index] || actual[index];
	return {
		boundary: record && Number.isInteger(record.boundary) ? record.boundary : index,
		path: `$${match[2]}`,
		mismatch_class: difference.mismatchClass,
	};
}

function compareDocuments(expected, actual) {
	const difference = firstDifference(expected, actual);
	return {difference, fingerprint: difference ? divergenceFingerprint(expected, actual) : null};
}

function main(argv) {
	if (argv.length !== 2) throw new Error('usage: node compare.js ORACLE.jsonl NATIVE.jsonl');
	const expected = readJSONL(argv[0]);
	const actual = readJSONL(argv[1]);
	const {difference} = compareDocuments(expected, actual);
	if (difference) {
		const boundary = /^\$\[(\d+)\]/.exec(difference.path);
		const record = boundary ? (expected[Number(boundary[1])] || actual[Number(boundary[1])]) : null;
		const prefix = record && typeof record.case_id === 'string' && Number.isInteger(record.boundary) ?
			`case ${record.case_id}, boundary ${record.boundary}` :
			boundary ? `record ${boundary[1]}` : 'document';
		console.error(`${prefix}: first divergence at ${difference.path}`);
		console.error(`oracle: ${JSON.stringify(difference.expected)}`);
		console.error(`native: ${JSON.stringify(difference.actual)}`);
		process.exitCode = 1;
	} else {
		console.log(`matched ${expected.length} boundaries`);
	}
}

if (require.main === module) main(process.argv.slice(2));

module.exports = {compareDocuments, divergenceFingerprint, firstDifference, parseJSONL, readJSONL};
