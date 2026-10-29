'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const {validate} = require('./validate');
const {validateEventVocabulary} = require('./validate-event-vocabulary');

const root = path.resolve(__dirname, '../..');
const eventVocabulary = JSON.parse(fs.readFileSync(path.join(__dirname, 'event-vocabulary.json'), 'utf8'));
assert.deepStrictEqual(validateEventVocabulary(eventVocabulary), []);
const collapsedTryBoost = JSON.parse(JSON.stringify(eventVocabulary));
collapsedTryBoost.events.find(event => event.event === 'TryBoost').algebra = 'boolean-or-null-gate';
assert(validateEventVocabulary(collapsedTryBoost).includes('TryBoost has the wrong algebra'));
const missingRuntimeEvent = JSON.parse(JSON.stringify(eventVocabulary));
missingRuntimeEvent.events.pop();
missingRuntimeEvent.unique_events--;
assert(validateEventVocabulary(missingRuntimeEvent).some(failure => failure.includes('event count')));
const completeMap = JSON.parse(fs.readFileSync(path.join(__dirname, 'descriptor-map.json'), 'utf8'));
const frozenInventory = JSON.parse(fs.readFileSync(path.join(__dirname, 'gen3ou-inventory.json'), 'utf8'));
const eventHookEntries = new Map(completeMap.inventories
	.find(inventory => inventory.kind === 'event_hook').entries.map(entry => [entry.id, entry]));
assert.strictEqual(frozenInventory.callback_hooks.length, eventHookEntries.size);
for (const hook of frozenInventory.callback_hooks) {
	const id = `${hook.owner_kind}.${hook.owner_id}.${hook.hook}`;
	assert(hook.showdown_source?.path && hook.showdown_source?.symbol,
		`frozen callback hook lacks physical source: ${id}`);
	assert.deepStrictEqual(eventHookEntries.get(id)?.showdown_sources[0], hook.showdown_source,
		`descriptor map does not lead with the frozen defining source: ${id}`);
}
const draft = JSON.parse(JSON.stringify(completeMap));
draft.freeze_status = 'draft';
for (const inventory of draft.inventories) inventory.entries = [];
const result = validate(draft, root);
assert.strictEqual(result.schema_valid, true);
assert.strictEqual(result.inventory_ready, false);
assert.strictEqual(result.completion_ready, false);
assert.strictEqual(result.progress.descriptors_expected, 1560);
assert.strictEqual(result.progress.descriptors_classified, 0);
assert(result.readiness_failures.includes('descriptor inventory is not frozen'));

const implemented = JSON.parse(JSON.stringify(draft));
implemented.inventories = [{
	kind: 'move', source: 'native/gen3_slice_data.c', selector: 'test fixture', expected_count: 1,
	frozen_digest: '0'.repeat(64), entries: [{
		id: 'earthquake', numeric_id: 7, classification: 'implemented',
		oracle_revision: draft.oracle_revision,
		showdown_sources: [{path: 'data/moves.ts', symbol: 'earthquake'}],
		generation_boundaries: [{path: 'native/gen3_slice_data.c', symbol: 'POKEMON_GEN3_MOVE_EARTHQUAKE'}],
		native_boundaries: [{path: 'native/pokemon.c', symbol: 'resolve_move_hit'}],
		semantic_features: ['damage.gen3'], focused_tests: ['native/test_pokemon.c#earthquake'],
		differential_cases: ['derived-grounded-earthquake'], verification_artifacts: [], reachability_evidence: [], gap_witnesses: [], rationale: 'ordinary generated Ground damage',
	}],
}];
implemented.freeze_status = 'frozen';
const ready = validate(implemented, root);
assert.strictEqual(ready.schema_valid, true);
assert.strictEqual(ready.inventory_ready, true);
assert.strictEqual(ready.completion_ready, false);
assert.strictEqual(ready.progress.descriptors_expected, 1);
assert.strictEqual(ready.progress.descriptors_classified, 1);
assert.strictEqual(ready.progress.score, 90);

const unsupported = JSON.parse(JSON.stringify(implemented));
unsupported.inventories[0].entries[0].classification = 'unsupported';
unsupported.inventories[0].entries[0].native_boundaries = [];
unsupported.inventories[0].entries[0].semantic_features = [];
unsupported.inventories[0].entries[0].focused_tests = [];
unsupported.inventories[0].entries[0].reachability_evidence = ['accepted by pinned Gen3OU validator'];
unsupported.inventories[0].entries[0].gap_witnesses = ['semantics-unverified:move:earthquake'];
const gap = validate(unsupported, root);
assert.strictEqual(gap.schema_valid, true);
assert.strictEqual(gap.completion_ready, false);
assert(gap.readiness_failures.some(failure => failure.includes('remains unsupported')));

process.stdout.write('descriptor inventory contract passed\n');
