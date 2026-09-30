'use strict';

const assert = require('assert');
const {
	API_SPECS, extractCalls, extractDirectDeletes, literalID, splitArguments,
} = require('./condition-extractor');

const toID = value => value.toLowerCase().replace(/[^a-z0-9]+/g, '');

assert.deepStrictEqual(splitArguments("foo(bar, [1, 2]), 'futuremove', {x: ')' }"), [
	'foo(bar, [1, 2])', "'futuremove'", "{x: ')' }",
]);
assert.deepStrictEqual(extractCalls(
	"const example = \"addVolatile('not-code')\"; // setStatus('not-code')\n" +
	"/* addSideCondition('not-code') */ side.removeSlotCondition(this.getAtSlot(foo(bar)), 'futuremove'); " +
	"pokemon.addVolatile('trapped', source, move, 'trapper');"
).map(call => [call.api, call.arguments]), [
	['removeSlotCondition', ['this.getAtSlot(foo(bar))', "'futuremove'"]],
	['addVolatile', ["'trapped'", 'source', 'move', "'trapper'"]],
]);
assert.strictEqual(literalID("'Future Sight'", toID), 'futuresight');
assert.strictEqual(literalID('computed', toID), null);
assert.deepStrictEqual(API_SPECS, {
	addVolatile: {ids: [
		{kind: 'volatile', argument: 0},
		{kind: 'volatile', argument: 3, optional: true, role: 'linkedStatus'},
	]},
	removeVolatile: {ids: [{kind: 'volatile', argument: 0}]},
	addSideCondition: {ids: [{kind: 'side', argument: 0}]},
	removeSideCondition: {ids: [{kind: 'side', argument: 0}]},
	addSlotCondition: {ids: [{kind: 'slot', argument: 1}]},
	removeSlotCondition: {ids: [{kind: 'slot', argument: 1}]},
	setWeather: {ids: [{kind: 'weather', argument: 0}]},
	clearWeather: {ids: []},
	addPseudoWeather: {ids: [{kind: 'pseudoWeather', argument: 0}]},
	removePseudoWeather: {ids: [{kind: 'pseudoWeather', argument: 0}]},
	setStatus: {ids: [{kind: 'status', argument: 0}]},
	forceStatus: {ids: [{kind: 'status', argument: 0}]},
	trySetStatus: {ids: [{kind: 'status', argument: 0}]},
	cureStatus: {ids: []},
	clearStatus: {ids: []},
}, 'the extractor must fail when any condition lifecycle API or identity argument drifts');
assert.deepStrictEqual(extractDirectDeletes(
	"const example = \"delete pokemon.volatiles['not-code']\"; /* delete side.sideConditions['not-code'] */ " +
	"delete pokemon.volatiles['lockedmove']; delete side.slotConditions[position][computed];", toID
), [
	{container: 'volatiles', id: 'lockedmove', expression: "delete pokemon.volatiles['lockedmove']"},
	{container: 'slotConditions', id: null, expression: 'computed'},
]);
assert.throws(() => extractCalls("pokemon.addVolatile(foo('x')"), /unbalanced/);
assert.deepStrictEqual(extractCalls(
	"const x = `removeVolatile('not-code')`; /* addSlotCondition(target, 'not-code') */ addVolatile('real');"
).map(call => [call.api, call.arguments]), [['addVolatile', ["'real'"]]]);
assert.deepStrictEqual(extractCalls(
	"const x = `raw addVolatile('not-code') ${side.addSlotCondition(target, 'futuremove')}`; " +
	"const y = `outer ${`nested ${pokemon.removeVolatile('twoturnmove')}`}`;"
).map(call => [call.api, call.arguments]), [
	['addSlotCondition', ['target', "'futuremove'"]],
	['removeVolatile', ["'twoturnmove'"]],
], 'template interpolation is executable code even though template text is not');
assert.deepStrictEqual(extractDirectDeletes(
	"const x = `raw delete pokemon.volatiles['not-code'] ${delete pokemon.volatiles['lockedmove']}`;", toID
), [
	{container: 'volatiles', id: 'lockedmove', expression: "delete pokemon.volatiles['lockedmove']"},
], 'direct deletes inside executable template interpolation must remain visible');
assert.throws(() => extractCalls("const x = `unterminated ${addVolatile('x')};"),
	/unbalanced source/, 'unterminated templates must fail closed');
const computedSlot = extractCalls("side.addSlotCondition(target, computedCondition(source));")[0];
assert.deepStrictEqual(computedSlot.arguments, ['target', 'computedCondition(source)']);
assert.strictEqual(literalID(computedSlot.arguments[1], toID), null,
	'computed slot IDs must be routed to explicit dynamic review');
const computedSlotRemoval = extractCalls("side.removeSlotCondition(target, computedCondition(source));")[0];
assert.strictEqual(literalID(
	computedSlotRemoval.arguments[API_SPECS.removeSlotCondition.ids[0].argument], toID
), null, 'computed slot removals must be routed to explicit dynamic review');
const computedLinkedStatus = extractCalls(
	"pokemon.addVolatile('partiallytrapped', source, move, linkedStatus(move));"
)[0];
assert.strictEqual(literalID(
	computedLinkedStatus.arguments[API_SPECS.addVolatile.ids[1].argument], toID
), null, 'computed linked volatile IDs must be routed to explicit dynamic review');

process.stdout.write('condition extractor contract passed\n');
