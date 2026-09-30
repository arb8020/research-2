'use strict';

const assert = require('assert');
const childProcess = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const {
	API_NAMES, identity, scan, scanFunctionConditionCalls, scanFunctionConditionReferences,
} = require('./runtime-condition-source-audit');
const {API_SPECS} = require('./condition-extractor');
const {reconcileSourceCensus} = require('./runtime-condition-review');

const showdownDir = process.env.POKEMON_SHOWDOWN_DIR;
if (!showdownDir) throw new Error('POKEMON_SHOWDOWN_DIR must name the pinned clean Showdown checkout');
const artifactPath = path.join(__dirname, 'runtime-condition-paths.json');
const manifest = JSON.parse(fs.readFileSync(artifactPath));
const revision = childProcess.execFileSync('git', ['rev-parse', 'HEAD'], {
	cwd: showdownDir, encoding: 'utf8',
}).trim();
assert.strictEqual(revision, manifest.revision);
assert.strictEqual(childProcess.execFileSync(
	'git', ['status', '--porcelain', '--untracked-files=no'], {cwd: showdownDir, encoding: 'utf8'}
).trim(), '', 'runtime condition source must be a clean pinned checkout');
assert.deepStrictEqual([...API_NAMES].sort(), Object.keys(API_SPECS).sort(),
	'the independent runtime census and resolved-descriptor extractor must cover the same lifecycle APIs');

const ts = require(path.join(showdownDir, 'node_modules/typescript'));
assert.deepStrictEqual(scanFunctionConditionCalls(
	`onEnd(target) {
		target.addVolatile(compute("x", nested(1, 2)), source, effect, 'trapper');
		target.side.addSlotCondition(target, 'futuremove');
		// target.removeVolatile('comment-only');
	}`, ts), [
	{api: 'addVolatile', arguments: ['compute("x", nested(1, 2))', 'source', 'effect', "'trapper'"]},
	{api: 'addSlotCondition', arguments: ['target', "'futuremove'"]},
]);
assert.deepStrictEqual(scanFunctionConditionReferences(
	`onResidual(pokemon) {
		const handler = {end: pokemon.removeVolatile};
		pokemon.removeVolatile('called-directly');
		const status = moveData.forceStatus;
	}`, ts), [
	{api: 'removeVolatile', snippet: 'pokemon.removeVolatile'},
	{api: 'forceStatus', snippet: 'moveData.forceStatus'},
], 'stored lifecycle callbacks and data-field aliases must be censused, but direct calls must not be duplicated');
assert.deepStrictEqual(scanFunctionConditionReferences(
	`beforeTurnCallback(pokemon) {
		const remove = pokemon.removeVolatile;
		pokemon.removeVolatile('called-directly');
	}`, ts), [
	{api: 'removeVolatile', snippet: 'pokemon.removeVolatile'},
], 'non-on* descriptor functions must fail closed on aliased lifecycle methods');
const syntheticDirectMutations = require('./runtime-condition-source-audit')
	.scanFunctionDirectConditionMutations(
		`beforeTurnCallback(pokemon) { pokemon.status = 'slp'; }`, ts
	);
assert.deepStrictEqual(syntheticDirectMutations.map(mutation => [
	mutation.kind, mutation.scalar, mutation.mutation_role,
]), [['direct-assignment', 'status', 'lifecycle-owning']],
'direct condition writes in non-on* descriptor functions must remain visible');

const live = scan(showdownDir);
const reconciled = reconcileSourceCensus(live, manifest.source_census);
assert.deepStrictEqual(reconciled, manifest.source_census,
	'checked-in reviewed runtime source census is stale');
assert.strictEqual(new Set(live.map(identity)).size, live.length, 'duplicate runtime source identity');
assert.deepStrictEqual(
	Object.fromEntries(['api-call', 'direct-assignment', 'direct-delete', 'method-reference'].map(kind =>
		[kind, live.filter(record => record.kind === kind).length])),
	{'api-call': 33, 'direct-assignment': 41, 'direct-delete': 15, 'method-reference': 8},
);
assert.deepStrictEqual(
	Object.fromEntries(['lifecycle-owning', 'payload-only', 'debug/test-only'].map(role =>
		[role, manifest.source_census.filter(record => record.ownership === role).length])),
	{'lifecycle-owning': 71, 'payload-only': 21, 'debug/test-only': 5},
);
assert.deepStrictEqual(live.filter(record => record.path === 'sim/dex-data.ts').map(record =>
	[record.kind, record.scalar, record.mutation_role]), [
	['direct-assignment', 'status', 'payload-only'],
	['direct-assignment', 'weather', 'payload-only'],
], 'the direct-write census must cover non-state-owner files and classify descriptor construction explicitly');

const identities = new Set();
const semanticReachability = new Set([
	'reachable', 'reachable-call-no-proven-rejector', 'unreachable-no-effective-descriptor',
]);
for (const entry of manifest.semantic_paths) {
	assert(semanticReachability.has(entry.gen3ou), `unknown Gen 3 OU reachability ${entry.gen3ou}`);
	const semanticIdentity = `${entry.path}:${entry.line}:${entry.operation}`;
	assert(!identities.has(semanticIdentity), `duplicate runtime condition path ${semanticIdentity}`);
	identities.add(semanticIdentity);
	const lines = fs.readFileSync(path.join(showdownDir, entry.path), 'utf8').split('\n');
	assert(lines[entry.line - 1]?.includes(entry.anchor),
		`${entry.path}:${entry.line} no longer contains ${JSON.stringify(entry.anchor)}`);
}

const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'pokemon-runtime-condition-paths-'));
try {
	const generated = path.join(tempDir, 'runtime-condition-paths.json');
	childProcess.execFileSync(process.execPath, [
		path.join(__dirname, 'build-runtime-condition-paths.js'), showdownDir, generated,
	], {env: {...process.env, POKEMON_SHOWDOWN_DIR: showdownDir}, stdio: 'inherit'});
	assert.deepStrictEqual(fs.readFileSync(generated), fs.readFileSync(artifactPath),
		'runtime condition path artifact is not deterministic');
} finally {
	fs.rmSync(tempDir, {recursive: true, force: true});
}

process.stdout.write(`runtime condition path contract passed ` +
	`(${manifest.source_census.length} source rows, ${manifest.semantic_paths.length} semantic paths)\n`);
