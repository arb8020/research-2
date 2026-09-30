#!/usr/bin/env node
'use strict';

const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');

function sameFailure(candidate, evaluate, fingerprint) {
	const first = evaluate(candidate);
	const second = evaluate(candidate);
	return !first.equal && first.fingerprint === fingerprint &&
		!second.equal && second.fingerprint === fingerprint;
}

function causalTeamPrefix(testCase, memberIndex) {
	const result = JSON.parse(JSON.stringify(testCase));
	if (Number.isInteger(memberIndex)) {
		assert(memberIndex >= 0 && memberIndex < result.team.length);
		result.team = result.team.slice(0, memberIndex + 1);
		result.member_index = memberIndex;
	}
	return result;
}

function minimizeCase(testCase, evaluate, comparison) {
	assert(!comparison.equal && comparison.fingerprint);
	let candidate = causalTeamPrefix(testCase,
		testCase.rule === 'obtainablemoves' ? testCase.member_index : null);
	if (!sameFailure(candidate, evaluate, comparison.fingerprint)) {
		candidate = JSON.parse(JSON.stringify(testCase));
	}
	for (let member = candidate.team.length - 1; member >= 0; member--) {
		if (member === candidate.member_index) continue;
		const trial = JSON.parse(JSON.stringify(candidate));
		trial.team.splice(member, 1);
		if (trial.member_index > member) trial.member_index--;
		if (trial.team.length && sameFailure(trial, evaluate, comparison.fingerprint)) candidate = trial;
	}
	for (let member = 0; member < candidate.team.length; member++) {
		for (let move = candidate.team[member].moves.length - 1; move >= 0; move--) {
			if (candidate.team[member].moves.length === 1) break;
			const trial = JSON.parse(JSON.stringify(candidate));
			trial.team[member].moves.splice(move, 1);
			if (sameFailure(trial, evaluate, comparison.fingerprint)) candidate = trial;
		}
	}
	return candidate;
}

function persistFailure(directory, original, minimized, comparison, replays) {
	fs.mkdirSync(path.dirname(directory), {recursive: true});
	const stage = fs.mkdtempSync(path.join(path.dirname(directory), `.${path.basename(directory)}.tmp-`));
	try {
		fs.writeFileSync(path.join(stage, 'case.json'), `${JSON.stringify(minimized, null, 2)}\n`);
		fs.writeFileSync(path.join(stage, 'failure.json'), `${JSON.stringify({
			schema: 'pokemon-gen3ou-admission-random-failure-v1',
			fingerprint: comparison.fingerprint,
			difference: comparison.difference,
			original_team_size: original.team.length,
			minimized_team_size: minimized.team.length,
			replays,
		}, null, 2)}\n`);
		fs.renameSync(stage, directory);
	} catch (error) {
		fs.rmSync(stage, {recursive: true, force: true});
		throw error;
	}
}

module.exports = {causalTeamPrefix, minimizeCase, persistFailure, sameFailure};
