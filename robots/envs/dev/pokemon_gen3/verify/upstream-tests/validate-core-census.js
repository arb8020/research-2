'use strict';

const fs = require('fs');
const path = require('path');

const file = process.argv[2] || path.join(__dirname, 'core-test-census.json');
const census = JSON.parse(fs.readFileSync(file, 'utf8'));
const valid = new Set([
  'gen3-explicit', 'verifier-admission', 'format-unreachable',
  'different-generation', 'post-gen3-unreachable', 'requires-source-adjudication',
]);
const keys = new Set();
for (const record of census.records) {
  const key = `${record.source_file}:${record.source_line}:${record.full_test_name}`;
  if (keys.has(key)) throw new Error(`duplicate record: ${key}`);
  keys.add(key);
  if (record.pinned_revision !== census.revision) throw new Error(`revision mismatch: ${key}`);
  if (!valid.has(record.applicability)) throw new Error(`bad applicability: ${key}`);
  if (!record.applicability_evidence) throw new Error(`missing applicability evidence: ${key}`);
  if (!record.semantic_boundaries.length) throw new Error(`missing boundaries: ${key}`);
  if (record.needs_new_case && !record.proposed_case) throw new Error(`missing proposed case: ${key}`);
}
if (census.summary.total !== census.records.length) throw new Error('summary total mismatch');
console.log(`validated ${census.records.length} unique upstream tests at ${census.revision}`);
