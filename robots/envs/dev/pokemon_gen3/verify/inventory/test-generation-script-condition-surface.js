#!/usr/bin/env node
'use strict';

const assert = require('assert');
const childProcess = require('child_process');
const path = require('path');
const {extractCalls, extractDirectDeletes} = require('./condition-extractor');

const showdownDir = process.env.POKEMON_SHOWDOWN_DIR;
if (!showdownDir) throw new Error('POKEMON_SHOWDOWN_DIR must name the clean pinned Showdown checkout');
const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
assert.strictEqual(childProcess.execFileSync('git', ['rev-parse', 'HEAD'], {
	cwd: showdownDir, encoding: 'utf8',
}).trim(), revision);

const {Dex, TeamValidator} = require(showdownDir);
const dex = new TeamValidator('gen3ou').dex;
assert.strictEqual(dex.gen, 3);

const rows = [];
function scan(value, owner = '', seen = new Set()) {
	if (!value || (typeof value !== 'object' && typeof value !== 'function') || seen.has(value)) return;
	seen.add(value);
	for (const [key, child] of Object.entries(value)) {
		const location = owner ? `${owner}.${key}` : key;
		if (typeof child === 'function') {
			const source = Function.prototype.toString.call(child);
			for (const call of extractCalls(source)) {
				rows.push({location, api: call.api, arguments: call.arguments, source});
			}
			for (const deletion of extractDirectDeletes(source, Dex.toID)) {
				rows.push({location, api: 'delete', container: deletion.container, id: deletion.id, source});
			}
		}
		if (child && typeof child === 'object') scan(child, location, seen);
	}
}
scan(dex.data.Scripts);

assert.deepStrictEqual(rows.map(({location, api, arguments: args, container, id}) =>
	({location, api, ...(args ? {arguments: args} : {container, id})})), [{
	location: 'actions.runSwitch', api: 'removeVolatile', arguments: ['"substitutebroken"'],
}], 'resolved Gen 3 script condition surface changed and needs an explicit reachability review');
assert.match(rows[0].source, /if \(this\.battle\.gen === 4\)/,
	'inherited substitutebroken cleanup is only excluded because the effective callback guards it to Gen 4');

process.stdout.write('resolved generation-script condition surface passed (one Gen-4-only call)\n');
