#!/usr/bin/env node
'use strict';

const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const {compareRecords} = require('../compare');
const {causalTeamPrefix, minimizeCase, persistFailure} = require('./minimize');

const source = {
	id: 'synthetic', rule: 'obtainablemoves', member_index: 2,
	team: [
		{species: 'Pikachu', moves: ['Thunderbolt']},
		{species: 'Persian', moves: ['Scratch']},
		{species: 'Skarmory', moves: ['Toxic', 'Curse', 'Drill Peck']},
		{species: 'Blissey', moves: ['Soft-Boiled']},
	],
};
assert.strictEqual(causalTeamPrefix(source, 2).team.length, 3);
const evaluate = candidate => {
	const divergent = candidate.team.some(set =>
		set.species === 'Skarmory' && set.moves.includes('Curse') && set.moves.includes('Drill Peck'));
	return divergent ? {
		equal: false, fingerprint: 'value:CASE.disposition',
		difference: {kind: 'value', path: [0, 'disposition'], expected: 'BANNED', actual: 'INCOMPLETE'},
	} : {equal: true, fingerprint: null, difference: null};
};
const comparison = evaluate(source);
const minimized = minimizeCase(source, evaluate, comparison);
assert.strictEqual(minimized.team.length, 1);
assert.deepStrictEqual(minimized.team[0].moves, ['Curse', 'Drill Peck']);
assert.strictEqual(minimized.member_index, 0);

const structured = compareRecords([{id: 'x', disposition: 'BANNED'}],
	[{id: 'x', disposition: 'INCOMPLETE'}]);
assert.strictEqual(structured.fingerprint, 'value:0.disposition');

const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'pokemon-admission-minimize-test-'));
try {
	const target = path.join(temporary, 'retained');
	persistFailure(target, source, minimized, comparison, [comparison, comparison]);
	assert(fs.existsSync(path.join(target, 'case.json')));
	assert(fs.existsSync(path.join(target, 'failure.json')));
} finally {
	fs.rmSync(temporary, {recursive: true, force: true});
}
process.stdout.write('admission causal minimizer contract passed\n');
