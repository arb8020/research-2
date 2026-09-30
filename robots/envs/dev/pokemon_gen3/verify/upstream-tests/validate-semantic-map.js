'use strict';

const fs = require('fs');
const path = require('path');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const directoryArgument = process.argv.slice(2).find(argument => !argument.startsWith('--'));
const directory = path.resolve(directoryArgument || __dirname);
const inherited = JSON.parse(fs.readFileSync(path.join(directory, 'gen3ou-inherited-test-map.json'), 'utf8'));
const core = JSON.parse(fs.readFileSync(path.join(directory, 'core-test-census.json'), 'utf8'));
const supplemental = JSON.parse(fs.readFileSync(path.join(directory, 'resolved-gen3-entity-test-gaps.json'), 'utf8'));
const canonical = JSON.parse(fs.readFileSync(path.join(directory, 'gen3ou-test-map.json'), 'utf8'));

for (const artifact of [inherited, core, supplemental]) {
  if ((artifact.oracle_revision || artifact.pinned_revision || artifact.revision) !== REVISION) {
    throw new Error(`${artifact.schema || 'map'} has the wrong pinned revision`);
  }
}
if (canonical.schema !== 'pokemon-gen3ou-upstream-regression-map-v1' ||
	canonical.pinned_revision !== REVISION) {
	throw new Error('canonical Gen 3 OU upstream regression map has the wrong schema or revision');
}

const rows = [
  ...inherited.records.map(record => ({partition: 'inherited', key: `${record.source_file}:${record.source_line}`, record})),
  ...core.records.map(record => ({partition: 'core', key: `${record.source_file}:${record.source_line}`, record})),
  ...supplemental.records.map(record => ({partition: 'supplemental', key: `${record.source_file}:${record.source_line}`, record})),
];
const keys = new Set();
for (const row of rows) {
  if (keys.has(row.key)) throw new Error(`duplicate upstream assertion ${row.key}`);
  keys.add(row.key);
}

const unresolved = rows.filter(({partition, record}) =>
  (partition === 'inherited' && record.applicability === 'candidate_requires_gen3_source_adjudication') ||
  (partition === 'core' && record.applicability === 'requires-source-adjudication') ||
  (partition === 'supplemental' && record.ou_reachability === 'unproven-gen3ou-reachability'));
const assertionEvidence = rows.filter(({partition, record}) =>
  partition === 'inherited' ? record.coverage_evidence_scope === 'assertion_specific' :
    partition === 'supplemental' ? record.evidence_scope === 'assertion-covered-compositionally' :
      record.existing_evidence_ids.length > 0);

if (canonical.records.length !== rows.length) {
	throw new Error(`canonical map has ${canonical.records.length} declarations; expected ${rows.length}`);
}
const canonicalKeys = new Set();
const evidenceScopes = new Set([
	'none', 'partial', 'assertion_specific', 'entity_level_candidates_only',
	'source-proven-reachability-closure',
]);
for (const record of canonical.records) {
	const key = `${record.source.file}:${record.source.line}`;
	if (!keys.has(key)) throw new Error(`canonical map contains unknown declaration ${key}`);
	if (canonicalKeys.has(key)) throw new Error(`canonical map duplicates declaration ${key}`);
	canonicalKeys.add(key);
	if (!record.applicability?.disposition || !record.applicability.evidence ||
		!record.semantic_sources?.length || !record.boundaries?.length) {
		throw new Error(`canonical declaration ${key} lacks semantic adjudication`);
	}
	if (['g3_explicit', 'gen3-explicit', 'g3_source_applicable', 'verifier-admission']
		.includes(record.applicability.disposition) && !record.mechanics?.length) {
		throw new Error(`applicable canonical declaration ${key} lacks mechanics`);
	}
	if (record.required_case && record.terminal_reason) {
		throw new Error(`canonical declaration ${key} has both a required case and terminal reason`);
	}
	if (!evidenceScopes.has(record.evidence_scope)) {
		throw new Error(`canonical declaration ${key} has invalid evidence scope ${record.evidence_scope}`);
	}
	if (record.required_case && record.evidence_scope === 'assertion_specific') {
		throw new Error(`canonical declaration ${key} claims assertion-specific proof but still requires a case`);
	}
	if (!record.required_case && !record.terminal_reason && record.evidence_scope !== 'assertion_specific') {
		throw new Error(`canonical declaration ${key} lacks proof, required case, or terminal disposition`);
	}
}
if (canonicalKeys.size !== keys.size) throw new Error('canonical map omits upstream declarations');

const result = {
  schema: 'pokemon-gen3ou-upstream-semantic-map-validation-v1',
  oracle_revision: REVISION,
  declarations: rows.length,
  structural_census_assertion_specific_evidence: assertionEvidence.length,
  assertion_specific_evidence: canonical.records.filter(record => record.evidence_scope === 'assertion_specific').length,
  structural_census_rows_requiring_manual_overlay: unresolved.length,
  unresolved_semantic_adjudications: 0,
  structural_manual_overlay_rows_by_partition: Object.fromEntries(['inherited', 'core', 'supplemental'].map(partition => [
    partition, unresolved.filter(row => row.partition === partition).length,
  ])),
};
process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
