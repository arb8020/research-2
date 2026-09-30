'use strict';

const assert = require('assert');
const {campaignCoverage} = require('./coverage');

function boundary(caseID, ordinal, tie = false) {
	return {
		case_id: caseID, boundary: ordinal,
		request: [{kind: 'move'}, {kind: 'move'}],
		choices: ordinal ? [{kind: 'move'}, {kind: 'move'}] : [],
		queue: ordinal ? [{kind: 'move', side: 0}, {kind: 'move', side: 1}] : [],
		events: ordinal ? [{kind: 'win', side: 0}] : [],
		prng: tie ? [{label: 'queue.tie', from: 2, to: null}] : [],
		handlers: ordinal ? [{event: 'deduct-pp', source_kind: 'ability', source_id: 'pressure', holder: {kind: 'pokemon'}}] : [],
		conditions: [], effects: [],
	};
}

const entries = ['a', 'b'].map(id => ({id, team_pairing: `pair-${id}`, expected_boundaries: 2}));
const fixtures = entries.map(entry => ({id: entry.id, teams: [{normalized: [{
	species: 'aerodactyl', moves: ['rockslide'], ability: 'pressure', item: 'choiceband',
}]}]}));
const records = entries.flatMap(entry => [boundary(entry.id, 0), boundary(entry.id, 1, true)]);
const manifest = {
	cases: entries, coverage_dimensions: ['terminal', 'prng', 'ingredients', 'handlers'], coverage_targets: [
		{id: 'tie', selector: {kind: 'prng', match: {label: 'queue.tie'}}, min_cases: 2, min_team_pairings: 2},
		{id: 'win', selector: {kind: 'terminal', match: {kind: 'win'}}, min_cases: 2, min_team_pairings: 2},
	],
};

const result = campaignCoverage(manifest, fixtures, records);
assert.strictEqual(result.acceptance.status, 'pass');
assert.deepStrictEqual(result.ingredients_present.items, ['choiceband']);
assert.deepStrictEqual(result.dimensions, ['handlers', 'ingredients', 'prng', 'terminal']);

const reversed = campaignCoverage({...manifest, cases: [...entries].reverse(),
	coverage_dimensions: [...manifest.coverage_dimensions].reverse(),
	coverage_targets: [...manifest.coverage_targets].reverse()}, [...fixtures].reverse(),
	[...records.slice(2), ...records.slice(0, 2)]);
assert.deepStrictEqual(reversed, result, 'campaign aggregation must be order-independent');

const itemTarget = campaignCoverage({...manifest, coverage_targets: [{
	id: 'item-handler', selector: {kind: 'handler', match: {source_kind: 'item', source_id: 'choiceband'}},
}]}, fixtures, records);
assert.strictEqual(itemTarget.targets[0].status, 'unmet', 'ingredient presence is not execution evidence');

const duplicateTie = [boundary('a', 0), boundary('a', 1, true)];
duplicateTie[1].prng.push({label: 'queue.tie', from: 2, to: null});
const oneCase = campaignCoverage({...manifest, cases: [entries[0]], coverage_targets: [{
	id: 'cross-case', selector: {kind: 'prng', match: {label: 'queue.tie'}}, min_cases: 2,
}]}, [fixtures[0]], duplicateTie);
assert.strictEqual(oneCase.targets[0].status, 'unmet', 'occurrence count cannot replace case diversity');

assert.throws(() => campaignCoverage({...manifest, coverage_targets: [{
	id: 'bad', selector: {kind: 'prng', match: {arbitrary: true}},
}]}, fixtures, records), /not valid/);
assert.throws(() => campaignCoverage({...manifest, coverage_targets: [{
	id: 'negative', selector: {kind: 'negative', match: {}},
}]}, fixtures, records), /unknown witness kind/);
assert.throws(() => campaignCoverage({...manifest, coverage_dimensions: ['terminal'], coverage_targets: [{
	id: 'tie', selector: {kind: 'prng', match: {label: 'queue.tie'}},
}]}, fixtures, records), /undeclared dimension/);
assert.throws(() => campaignCoverage({...manifest, cases: [{...entries[0], expected_boundaries: 1}]},
	[fixtures[0]], [boundary('a', 1)]), /contiguous/);

console.log('random campaign coverage contract passed');
