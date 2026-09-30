'use strict';

const fs = require('fs');
const path = require('path');

const ROOT = __dirname;
const INPUT = path.join(ROOT, 'gen3ou-unified-regression-map.json');
const OUTPUT = path.join(ROOT, 'gen3ou-applicable-regression-map.tsv');

function field(value) {
  const text = Array.isArray(value) ? value.join(' | ') : String(value ?? '');
  return text.replaceAll('\t', ' ').replaceAll('\r', ' ').replaceAll('\n', ' ');
}

const map = JSON.parse(fs.readFileSync(INPUT, 'utf8'));
if (map.pinned_revision !== '6e71625b9e6cffeda268b548ae7f43a7643fc3f0') {
  throw new Error(`unexpected pinned revision: ${map.pinned_revision}`);
}

const records = map.records.filter(record => record.applicable);
if (records.length !== map.summary.applicable) {
  throw new Error(`applicable count mismatch: ${records.length} != ${map.summary.applicable}`);
}

const header = [
  'source_file',
  'line',
  'test_name',
  'pinned_revision',
  'mechanics',
  'semantic_boundaries',
  'native_units',
  'differential_cases',
  'invariants',
  'randomized_scenarios',
  'evidence_scope',
  'required_case',
  'semantic_sources',
];

const rows = records.map(record => [
  record.source.file,
  record.source.line,
  record.source.full_test_name,
  record.revision,
  record.mechanics,
  record.boundaries,
  record.evidence.native_units,
  record.evidence.differential_cases,
  record.evidence.invariants,
  record.evidence.randomized_scenarios,
  record.evidence_scope,
  record.required_case,
  record.semantic_sources,
].map(field).join('\t'));

fs.writeFileSync(OUTPUT, `${header.join('\t')}\n${rows.join('\n')}\n`);
console.log(`wrote ${records.length} applicable assertions to ${OUTPUT}`);
