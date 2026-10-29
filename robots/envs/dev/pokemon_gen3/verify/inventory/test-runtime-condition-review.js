'use strict';

const assert = require('assert');
const {reconcileSourceCensus} = require('./runtime-condition-review');

const live = [{
	kind: 'api-call', path: 'sim/example.ts', line: 1, column: 1,
	api: 'addVolatile', arguments: ["'futuremove'"], mutation_role: 'lifecycle-owning',
	snippet: "target.addVolatile('futuremove')",
}];
const reviewed = [{...live[0], ownership: 'lifecycle-owning',
	gen3ou: 'reachable-generic-runtime', evidence: 'synthetic reviewed path'}];
assert.deepStrictEqual(reconcileSourceCensus(live, reviewed), reviewed);
assert.throws(() => reconcileSourceCensus([...live, {...live[0], line: 2}], reviewed), /1 unknown/);
assert.throws(() => reconcileSourceCensus([], reviewed), /1 stale/);
assert.throws(() => reconcileSourceCensus(live, [{...live[0], ownership: 'unreviewed'}]), /unreviewed/);

const methodReference = {
	kind: 'method-reference', path: 'sim/example.ts', line: 3, column: 8,
	api: 'removeVolatile', mutation_role: 'lifecycle-owning',
	snippet: 'pokemon.removeVolatile',
};
const reviewedMethodReference = {...methodReference, ownership: 'lifecycle-owning',
	gen3ou: 'reachable-generic-runtime', evidence: 'stored as the condition end callback'};
assert.deepStrictEqual(reconcileSourceCensus([methodReference], [reviewedMethodReference]),
	[reviewedMethodReference]);
assert.throws(() => reconcileSourceCensus([methodReference], []), /1 unknown/,
	'new lifecycle method references must fail closed');

process.stdout.write('runtime condition review fail-closed contract passed\n');
