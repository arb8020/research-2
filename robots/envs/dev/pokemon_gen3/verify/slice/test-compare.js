'use strict';

const assert = require('assert');
const childProcess = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'pokemon-compare-'));
const compare = path.join(__dirname, 'compare.js');
const record = (caseID, boundary) => ({case_id: caseID, boundary, state: {turn: boundary + 1}});

function write(name, records, finalNewline = true) {
	const filename = path.join(directory, name);
	const body = records.map(value => JSON.stringify(value)).join('\n');
	fs.writeFileSync(filename, `${body}${finalNewline ? '\n' : ''}`);
	return filename;
}

function run(oracle, native) {
	return childProcess.spawnSync(process.execPath, [compare, oracle, native], {encoding: 'utf8'});
}

try {
	const two = [record('first', 0), record('second', 1)];
	let result = run(write('exact.oracle', two), write('exact.native', two));
	assert.strictEqual(result.status, 0);
	assert.match(result.stdout, /matched 2 boundaries/);

	result = run(write('missing-native.oracle', two), write('missing-native.native', two.slice(0, 1)));
	assert.strictEqual(result.status, 1);
	assert.match(result.stderr, /case second, boundary 1: first divergence at \$\[1\]/);
	assert.match(result.stderr, /native: undefined/);

	result = run(write('missing-oracle.oracle', two.slice(0, 1)), write('missing-oracle.native', two));
	assert.strictEqual(result.status, 1);
	assert.match(result.stderr, /case second, boundary 1: first divergence at \$\[1\]/);
	assert.match(result.stderr, /oracle: undefined/);

	result = run(write('truncated.oracle', two, false), write('truncated.native', two));
	assert.notStrictEqual(result.status, 0);
	assert.match(result.stderr, /truncated JSONL artifact \(missing final newline\)/);
} finally {
	fs.rmSync(directory, {recursive: true, force: true});
}

console.log('differential comparator contract passed');
