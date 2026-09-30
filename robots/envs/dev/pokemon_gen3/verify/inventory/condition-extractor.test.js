'use strict';

const assert = require('assert');
const {
	API_SPECS, extractCalls, extractDirectDeletes, literalID, splitArguments,
} = require('./condition-extractor');

const toID = value => value.toLowerCase().replace(/[^a-z0-9]+/g, '');

assert.deepStrictEqual(splitArguments(`target, this.getAtSlot(foo(bar, [1, 2])), 'futuremove'`), [
	'target', 'this.getAtSlot(foo(bar, [1, 2]))', "'futuremove'",
]);
assert.throws(() => splitArguments(`target, foo(bar`), /unbalanced condition call arguments/);

const source = `function callback(target, source, move) {
	// target.addVolatile('commentedout');
	const text = "target.addVolatile('insideastring')";
	target.side.addSlotCondition(this.getAtSlot(foo(target.position)), 'futuremove');
	target.addVolatile('trapped', source, move, 'trapper');
	target.forceStatus(computedStatus(), source);
	target.side.removeSideCondition(condition);
	this.field.clearWeather();
}`;
const calls = extractCalls(source);
assert.deepStrictEqual(calls.map(call => call.api), [
	'addSlotCondition', 'addVolatile', 'forceStatus', 'removeSideCondition', 'clearWeather',
]);
assert.deepStrictEqual(calls[0].arguments, [
	'this.getAtSlot(foo(target.position))', "'futuremove'",
]);
assert.deepStrictEqual(calls[1].arguments, ["'trapped'", 'source', 'move', "'trapper'"]);
assert.strictEqual(literalID(calls[0].arguments[1], toID), 'futuremove');
assert.strictEqual(literalID(calls[1].arguments[3], toID), 'trapper');
assert.strictEqual(literalID(calls[2].arguments[0], toID), null);

assert.deepStrictEqual(API_SPECS.addSlotCondition.ids, [{kind: 'slot', argument: 1}]);
assert.deepStrictEqual(API_SPECS.addVolatile.ids, [
	{kind: 'volatile', argument: 0},
	{kind: 'volatile', argument: 3, optional: true, role: 'linkedStatus'},
]);
assert.deepStrictEqual(API_SPECS.forceStatus.ids, [{kind: 'status', argument: 0}]);
assert.deepStrictEqual(API_SPECS.clearWeather.ids, []);

const deletes = extractDirectDeletes(`function cleanup(pokemon, side) {
	delete pokemon.volatiles['lockedmove'];
	delete side.slotConditions[target.position]['futuremove'];
	delete side.sideConditions[computedCondition];
}`, toID);
assert.deepStrictEqual(deletes, [
	{container: 'volatiles', id: 'lockedmove', expression: "delete pokemon.volatiles['lockedmove']"},
	{container: 'slotConditions', id: 'futuremove', expression: "delete side.slotConditions[target.position]['futuremove']"},
	{container: 'sideConditions', id: null, expression: 'computedCondition'},
]);

assert.throws(() => extractCalls(`function broken() { target.addVolatile(foo(bar); }`), /unbalanced addVolatile call/);

process.stdout.write('condition extractor tests passed\n');
