#!/usr/bin/env node
'use strict';

const childProcess = require('child_process');
const fs = require('fs');
const path = require('path');
const {scan} = require('./runtime-condition-source-audit');
const {reconcileSourceCensus} = require('./runtime-condition-review');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const showdownInput = process.env.POKEMON_SHOWDOWN_DIR || process.argv[2];
if (!showdownInput) throw new Error('usage: build-runtime-condition-paths.js SHOWDOWN [OUTPUT]');
const showdownDir = path.resolve(showdownInput);
const outputPath = path.resolve(process.argv[3] || path.join(__dirname, 'runtime-condition-paths.json'));
const revision = childProcess.execFileSync('git', ['rev-parse', 'HEAD'], {
	encoding: 'utf8', cwd: showdownDir,
}).trim();
if (revision !== REVISION) throw new Error(`expected Showdown ${REVISION}, got ${revision}`);
const dirty = childProcess.execFileSync('git', ['status', '--porcelain', '--untracked-files=no'], {
	encoding: 'utf8', cwd: showdownDir,
}).trim();
if (dirty) throw new Error('runtime condition census requires a clean pinned Showdown checkout');

const prior = JSON.parse(fs.readFileSync(path.join(__dirname, 'runtime-condition-paths.json')));
const semanticPaths = prior.semantic_paths || prior.paths;
if (!Array.isArray(semanticPaths)) throw new Error('runtime manifest has no semantic paths');
if (!Array.isArray(prior.source_census)) {
	throw new Error('runtime source census has not been reviewed; bootstrap it explicitly before regeneration');
}
const sourceRows = scan(showdownDir);
const sourceCensus = reconcileSourceCensus(sourceRows, prior.source_census);
const artifact = {
	schema: 'pokemon-gen3ou-runtime-condition-paths-v2', revision: REVISION,
	method: [
		'Parse every pinned sim/**/*.ts file with the pinned TypeScript parser and census every condition API call.',
		'Census non-invocation lifecycle API references, including methods stored as event-handler end callbacks.',
		'Parse direct status/weather and condition-container writes/deletes in every pinned sim/**/*.ts file.',
		'Separate identity-owning lifecycle mutations from nested payload writes and BattleStream debug commands.',
		'Keep semantic lifecycle/expiry paths as a reviewed layer above the exhaustive syntactic census.',
	],
	semantic_paths: semanticPaths,
	source_census: sourceCensus,
};
fs.writeFileSync(outputPath, `${JSON.stringify(artifact, null, 2)}\n`);
process.stdout.write(`wrote ${sourceCensus.length} source rows and ${semanticPaths.length} semantic paths\n`);
