#!/usr/bin/env node
'use strict';

const assert = require('assert');
const childProcess = require('child_process');
const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');
const {compareRecords} = require('../compare');
const {minimizeCase, persistFailure} = require('./minimize');

const root = path.resolve(__dirname, '../../..');
const showdown = process.argv[2];
const artifactRoot = path.resolve(process.argv[3] || path.join(__dirname, 'failures'));
const reportFile = path.resolve(process.argv[4] ||
	path.join(__dirname, '../randomized-obtainability-report.json'));
if (!showdown) throw new Error('usage: node run.js SHOWDOWN_DIR [FAILURE_DIR]');

function run(command, args, options = {}) {
	return childProcess.execFileSync(command, args, {encoding: 'utf8', ...options});
}

function readJsonl(contents) {
	const text = contents.trim();
	return text ? text.split('\n').map(line => JSON.parse(line)) : [];
}

function writeFixture(file, template, cases) {
	fs.writeFileSync(file, `${JSON.stringify({...template, cases}, null, 2)}\n`);
}

function compileNative(directory, fixtureFile) {
	const header = path.join(directory, 'cases.generated.h');
	const binary = path.join(directory, 'native');
	const generated = run('node', [path.join(root, 'verify/admission/compile-cases.js')], {
		env: {...process.env, POKEMON_ADMISSION_CASES_FILE: fixtureFile},
	});
	fs.writeFileSync(header, generated);
	const sources = [
		path.join(__dirname, 'native.c'),
		path.join(root, 'native/pokemon_admission.c'),
		path.join(root, 'native/pokemon_acquisition.c'),
		path.join(root, 'native/gen3_admission_data.c'),
		path.join(root, 'native/pokemon.c'),
		path.join(root, 'native/gen3_rules.c'),
		path.join(root, 'native/gen3_slice_data.c'),
		path.join(root, 'native/singles2.c'),
	];
	run(process.env.CC || 'cc', ['-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-O2',
		`-DPOKEMON_ADMISSION_CASES_HEADER="${header}"`, ...sources, '-o', binary]);
	return binary;
}

function evaluate(directory, fixture) {
	const fixtureFile = path.join(directory, 'evaluate.json');
	writeFixture(fixtureFile, fixture, fixture.cases);
	const oracle = readJsonl(run('node', [path.join(__dirname, 'oracle.js'), showdown, fixtureFile]));
	const binary = compileNative(directory, fixtureFile);
	const native = readJsonl(run(binary, []));
	return {oracle, native, ...compareRecords(oracle, native)};
}

const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'pokemon-admission-random-'));
try {
	const fixtureA = path.join(temporary, 'cases-a.json');
	const fixtureB = path.join(temporary, 'cases-b.json');
	run('node', [path.join(__dirname, 'generate.js'), showdown, fixtureA]);
	run('node', [path.join(__dirname, 'generate.js'), showdown, fixtureB]);
	assert.strictEqual(fs.readFileSync(fixtureA, 'utf8'), fs.readFileSync(fixtureB, 'utf8'),
		'random fixture generation is not deterministic');
	const fixture = JSON.parse(fs.readFileSync(fixtureA, 'utf8'));
	const first = evaluate(temporary, fixture);
	const second = evaluate(temporary, fixture);
	assert.deepStrictEqual(second.oracle, first.oracle, 'oracle replay changed');
	assert.deepStrictEqual(second.native, first.native, 'native replay changed');
	if (!first.equal) {
		const index = Number(first.difference.path[0]);
		assert(Number.isInteger(index) && fixture.cases[index], 'divergence is not owned by one case');
		const original = fixture.cases[index];
		const oneCase = testCase => {
			const candidateFixture = {...fixture, cases: [testCase]};
			const result = evaluate(temporary, candidateFixture);
			if (!result.equal && result.difference.path[0] === 0) {
				result.fingerprint = result.fingerprint.replace(/^(\w+):0(?=\.|$)/, '$1:CASE');
			}
			return result;
		};
		const baseline = oneCase(original);
		const minimized = minimizeCase(original, oneCase, baseline);
		const replayA = oneCase(minimized);
		const replayB = oneCase(minimized);
		let target = path.join(artifactRoot, original.id);
		for (let suffix = 1; fs.existsSync(target); suffix++) {
			target = path.join(artifactRoot, `${original.id}-${suffix}`);
		}
		persistFailure(target, original, minimized, baseline, [replayA, replayB]);
		throw new Error(`admission mismatch ${baseline.fingerprint}; minimized artifact: ${target}`);
	}
	const accepted = first.oracle.filter(record => record.disposition === 'INCOMPLETE').length;
	const rejected = first.oracle.length - accepted;
	const digest = value => crypto.createHash('sha256').update(value).digest('hex');
	const report = {
		schema: 'pokemon-gen3ou-obtainability-random-report-v2',
		oracle_revision: fixture.oracle_revision,
		generator: fixture.generator,
		manifest: require('./manifest.json'),
		coverage: fixture.coverage,
		result: {
			total: first.oracle.length,
			accepted_as_native_incomplete: accepted,
			source_rejected: rejected,
			mismatches: 0,
			replay_stable: true,
		},
		sha256: {
			fixture: digest(fs.readFileSync(fixtureA)),
			oracle_json: digest(`${JSON.stringify(first.oracle)}\n`),
			native_json: digest(`${JSON.stringify(first.native)}\n`),
		},
	};
	const serializedReport = `${JSON.stringify(report, null, 2)}\n`;
	if (process.env.POKEMON_ADMISSION_UPDATE_REPORT === '1') {
		fs.writeFileSync(reportFile, serializedReport);
	} else {
		assert.strictEqual(fs.readFileSync(reportFile, 'utf8'), serializedReport,
			'randomized admission report is stale; rerun with POKEMON_ADMISSION_UPDATE_REPORT=1');
	}
	process.stdout.write(`random admission differential: ${first.oracle.length}/${first.oracle.length} exact ` +
		`(${accepted} oracle-accepted/native-INCOMPLETE, ${rejected} source-rejected); replay stable\n`);
} finally {
	fs.rmSync(temporary, {recursive: true, force: true});
}
