#!/usr/bin/env node
'use strict';

const assert = require('assert');
const childProcess = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const showdown = path.resolve(process.env.POKEMON_SHOWDOWN_DIR || process.argv[2] || '');
if (!process.env.POKEMON_SHOWDOWN_DIR && !process.argv[2]) {
	throw new Error('POKEMON_SHOWDOWN_DIR or argv[2] must name the pinned Showdown checkout');
}
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'pokemon-move-overlay-'));
try {
	const generated = path.join(temporary, 'overlay.json');
	childProcess.execFileSync(process.execPath, [
		path.join(__dirname, 'build-move-declaration-overlay.js'), showdown, generated,
	], {stdio: 'inherit'});
	const checkedIn = path.join(__dirname, 'move-declaration-overlay.json');
	assert.deepStrictEqual(fs.readFileSync(generated), fs.readFileSync(checkedIn),
		'checked-in move declaration overlay is stale');
	const overlay = JSON.parse(fs.readFileSync(checkedIn));
	assert.deepStrictEqual(overlay.summary, {
		declarations: 391, source_files: 90,
		not_applicable_subject_unavailable: 379,
		applicable_transposed_alias: 3,
		applicable_transposed_generic: 9,
		uncertain: 0,
	});
	process.stdout.write('move declaration overlay passed (391 exact rows, 0 uncertainty)\n');
} finally {
	fs.rmSync(temporary, {recursive: true, force: true});
}
