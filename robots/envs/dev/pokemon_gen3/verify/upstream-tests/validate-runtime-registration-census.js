'use strict';

const childProcess = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const {validateRuntimeRegistrationContract} = require('./runtime-registration-contract');

const oracle = path.resolve(process.argv[2] || '');
if (!process.argv[2]) throw new Error('usage: node validate-runtime-registration-census.js SHOWDOWN_DIR');
const checked = path.join(__dirname, 'runtime-registration-census.json');
const temporary = path.join(os.tmpdir(), `pokemon-runtime-registration-${process.pid}.json`);
try {
	childProcess.execFileSync(process.execPath, [path.join(__dirname, 'build-runtime-registration-census.js'), oracle, temporary], {stdio: 'inherit'});
	const expected = JSON.parse(fs.readFileSync(checked, 'utf8'));
	const actual = JSON.parse(fs.readFileSync(temporary, 'utf8'));
	validateRuntimeRegistrationContract(expected);
	if (JSON.stringify(actual) !== JSON.stringify(expected)) throw new Error('runtime registration census is stale');
	console.log('validated 2172 registered tests, 41 applicable loop variants, 8 locked-ramp variants, and 33 proven trapping variants');
} finally {
	if (fs.existsSync(temporary)) fs.unlinkSync(temporary);
}
