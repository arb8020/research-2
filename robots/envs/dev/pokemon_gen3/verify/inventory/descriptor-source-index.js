'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');

const TABLES = Object.freeze({
	moves: 'Moves', abilities: 'Abilities', items: 'Items', conditions: 'Conditions', rulesets: 'Rulesets',
});
const ANCESTRY = Object.freeze(['', 'gen8', 'gen7', 'gen6', 'gen5', 'gen4', 'gen3']);

function verifySourceMap(showdownDir, compiledPath) {
	const mapPath = `${compiledPath}.map`;
	assert(fs.existsSync(mapPath), `missing source map for ${compiledPath}`);
	const map = JSON.parse(fs.readFileSync(mapPath, 'utf8'));
	assert.strictEqual(map.sources.length, map.sourcesContent?.length,
		`source map has incomplete embedded sources: ${mapPath}`);
	for (let index = 0; index < map.sources.length; index++) {
		const sourcePath = path.resolve(path.dirname(mapPath), map.sources[index]);
		assert(sourcePath.startsWith(`${path.resolve(showdownDir)}${path.sep}`),
			`source map escapes pinned checkout: ${map.sources[index]}`);
		assert.strictEqual(map.sourcesContent[index], fs.readFileSync(sourcePath, 'utf8'),
			`stale compiled Showdown source map: ${path.relative(showdownDir, sourcePath)}`);
	}
}

function indexFunctions(value, symbol, source, index, targets, seen = new Set()) {
	if (!value || (typeof value !== 'object' && typeof value !== 'function')) return;
	if (typeof value === 'function') {
		if (targets && !targets.has(value)) return;
		if (!index.has(value)) index.set(value, []);
		index.get(value).push({path: source, symbol});
		return;
	}
	if (seen.has(value)) return;
	seen.add(value);
	for (const [key, child] of Object.entries(value)) {
		indexFunctions(child, `${symbol}.${key}`, source, index, targets, seen);
	}
}

function buildDescriptorSourceIndex(showdownDir, targets = null) {
	const index = new Map();
	for (const generation of ANCESTRY) {
		for (const [kind, exportName] of Object.entries(TABLES)) {
			const source = generation ? `data/mods/${generation}/${kind}.ts` : `data/${kind}.ts`;
			const compiledPath = path.join(showdownDir, 'dist', source.replace(/\.ts$/, '.js'));
			if (!fs.existsSync(compiledPath)) continue;
			verifySourceMap(showdownDir, compiledPath);
			const table = require(compiledPath)[exportName];
			assert(table && typeof table === 'object', `missing ${exportName} export in ${compiledPath}`);
			indexFunctions(table, exportName, source, index, targets);
		}
	}
	return index;
}

function descriptorSource(index, callback, identity) {
	const sources = index.get(callback) || [];
	assert.strictEqual(sources.length, 1,
		`${identity} must resolve to exactly one physical Showdown callback source; got ${JSON.stringify(sources)}`);
	return sources[0];
}

module.exports = {ANCESTRY, TABLES, buildDescriptorSourceIndex, descriptorSource, verifySourceMap};
