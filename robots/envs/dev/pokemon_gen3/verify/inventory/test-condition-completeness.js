#!/usr/bin/env node
'use strict';

const childProcess = require('child_process');
const fs = require('fs');
const path = require('path');

const showdownDir = process.env.POKEMON_SHOWDOWN_DIR;
if (!showdownDir) throw new Error('POKEMON_SHOWDOWN_DIR must name the clean pinned Showdown checkout');
const tests = [
	'test-condition-extractor.js',
	'test-runtime-condition-review.js',
	'test-runtime-condition-paths.js',
	'test-generation-script-condition-surface.js',
	'test-condition-integration.js',
];
for (const test of tests) {
	childProcess.execFileSync(process.execPath, [path.join(__dirname, test)], {
		env: {...process.env, POKEMON_SHOWDOWN_DIR: showdownDir}, stdio: 'inherit',
	});
}
const inventory = JSON.parse(fs.readFileSync(path.join(__dirname, 'gen3ou-inventory.json')));
const runtime = JSON.parse(fs.readFileSync(path.join(__dirname, 'runtime-condition-paths.json')));
if (inventory.oracle.revision !== runtime.revision) {
	throw new Error('resolved-descriptor and generic-runtime condition audits use different revisions');
}
process.stdout.write(`composed condition completeness passed: ` +
	`${inventory.condition_mutation_calls.length} effective descriptor calls, ` +
	`${runtime.source_census.length} generic runtime rows\n`);
