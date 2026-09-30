#!/usr/bin/env node
'use strict';

const assert = require('assert');
const childProcess = require('child_process');
const fs = require('fs');
const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const [showdownDir, fixtureFile] = process.argv.slice(2);
if (!showdownDir || !fixtureFile) throw new Error('usage: node oracle.js SHOWDOWN_DIR CASES.json');
assert.strictEqual(childProcess.execFileSync('git', ['-C', showdownDir, 'rev-parse', 'HEAD'], {encoding: 'utf8'}).trim(), REVISION);
assert.strictEqual(childProcess.execFileSync('git', ['-C', showdownDir, 'status', '--porcelain', '--untracked-files=no'], {encoding: 'utf8'}).trim(), '');
const fixture = JSON.parse(fs.readFileSync(fixtureFile, 'utf8'));
assert.strictEqual(fixture.oracle_revision, REVISION);
const {Dex, TeamValidator} = require(showdownDir);
const validator = new TeamValidator(fixture.format);
const sourcePattern = /can't learn|moves .* are incompatible|can't get its egg move combination|move only available from an event|egg, which cannot be obtained at levels below 5|is learned at level|can't be transferred from Gen/;
const normalize = source => ({...source, moves: [...source.moves], level: source.level ?? 100,
	nature: source.nature ?? 'Serious',
	evs: source.evs ?? {hp: 1, atk: 0, def: 0, spa: 0, spd: 0, spe: 0}});
for (const testCase of fixture.cases) {
	const sets = testCase.team.map(normalize);
	const problems = validator.validateTeam(sets) || [];
	const rejected = problems.some(problem => sourcePattern.test(problem));
	if (problems.length && !rejected) throw new Error(`${testCase.id}: out-of-scope rejection: ${problems.join('; ')}`);
	let memberIndex = 0;
	if (rejected) {
		memberIndex = sets.findIndex(set => (validator.validateSet(set, {}) || []).some(problem => sourcePattern.test(problem)));
		assert(memberIndex >= 0, `${testCase.id}: no causal source-invalid team member`);
	}
	process.stdout.write(`${JSON.stringify({id: testCase.id,
		disposition: rejected ? 'BANNED' : 'INCOMPLETE',
		rule: rejected ? 'obtainablemoves' : null,
		member_index: rejected ? memberIndex : null,
		normalized_species: rejected ? null : sets.map(set => Dex.toID(set.species)),
	})}\n`);
}
