'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');

const ROOT = __dirname;
const census = JSON.parse(fs.readFileSync(path.join(ROOT, 'all-test-census.json'), 'utf8'));
const overlay = JSON.parse(fs.readFileSync(path.join(ROOT, 'gen3ou-item-test-overlay.json'), 'utf8'));

assert.strictEqual(overlay.schema, 'pokemon-gen3ou-upstream-item-test-overlay-v1');
assert.strictEqual(overlay.pinned_revision, census.pinned_revision);

const expected = census.records.filter(record =>
  record.adjudication_source === 'gen3ou-item-test-overlay.json' && record.source_file.startsWith('test/sim/items/')
);
const key = record => `${record.source_file}:${record.source_line}:${record.full_test_name}`;
const actualKeys = overlay.records.map(record => key(record.identity));
const expectedKeys = expected.map(key);

assert.strictEqual(new Set(actualKeys).size, actualKeys.length, 'overlay identities must be unique');
assert.deepStrictEqual([...actualKeys].sort(), [...expectedKeys].sort(), 'overlay must exactly cover item declarations');
assert.strictEqual(overlay.summary.declarations, expected.length);
assert.strictEqual(expected.length, 115, 'review expected count if pinned upstream census changes');

for (const record of overlay.records) {
  assert.strictEqual(record.identity.pinned_revision, census.pinned_revision);
  assert.ok(['mechanic_unreachable_gen3', 'different_generation_not_direct_evidence'].includes(record.disposition));
  assert.ok(Array.isArray(record.evidence) && record.evidence.length >= 2);
  assert.ok(Array.isArray(record.mechanics_and_boundaries) && record.mechanics_and_boundaries.length >= 2);
  assert.ok(['not_required_for_gen3ou', 'different_generation_assertion_not_covered'].includes(record.native_coverage.status));
  assert.deepStrictEqual(Object.keys(record.native_coverage.channels).sort(), [
    'differential_fixture', 'invariant', 'native_unit', 'randomized_scenario',
  ]);
  for (const channel of Object.values(record.native_coverage.channels)) assert.ok(Array.isArray(channel));
  assert.ok(record.native_coverage.evidence);
  assert.strictEqual(record.required_case, null);
  assert.strictEqual(record.uncertainty, null);
}

const choice = overlay.records.filter(record => record.identity.source_file.endsWith('/choiceitem.js'));
assert.strictEqual(choice.length, 1);
assert.strictEqual(choice[0].disposition, 'different_generation_not_direct_evidence');
assert.strictEqual(choice[0].native_coverage.status, 'different_generation_assertion_not_covered');
assert.strictEqual(choice[0].native_coverage.channels.differential_fixture.length, 4);
assert.match(choice[0].evidence.join(' '), /Gen 3 item/);
assert.match(choice[0].evidence.join(' '), /Gen 8 transition/);

assert.deepStrictEqual(overlay.summary.by_disposition, {
  different_generation_not_direct_evidence: 1,
  mechanic_unreachable_gen3: 114,
});
assert.strictEqual(overlay.summary.requiring_new_case, 0);
assert.strictEqual(overlay.summary.unresolved, 0);

console.log(`validated ${overlay.records.length} complete item-test adjudications`);
