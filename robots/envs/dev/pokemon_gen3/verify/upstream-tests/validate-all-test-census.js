'use strict';

const fs = require('fs');
const path = require('path');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const directory = path.resolve(process.argv[2] || __dirname);
const census = JSON.parse(fs.readFileSync(path.join(directory, 'all-test-census.json'), 'utf8'));
const canonical = JSON.parse(fs.readFileSync(path.join(directory, 'gen3ou-test-map.json'), 'utf8'));
const overlayFiles = [
	'ability-unadjudicated-overlay.json',
	'gen3ou-item-test-overlay.json',
	'move-declaration-overlay.json',
	'scope-test-overlay.json',
];
if (census.schema !== 'pokemon-showdown-all-sim-test-census-v1' || census.pinned_revision !== REVISION) {
	throw new Error('all-test census has the wrong schema or pinned revision');
}
if (canonical.pinned_revision !== REVISION) throw new Error('canonical map revision mismatch');

const keys = new Set();
for (const record of census.records) {
	const key = `${record.source_file}:${record.source_line}`;
	if (keys.has(key)) throw new Error(`duplicate all-test declaration ${key}`);
	keys.add(key);
	if (!record.full_test_name) throw new Error(`${key} lacks a test name`);
	if (!['active', 'pending'].includes(record.execution_status)) {
		throw new Error(`${key} lacks an execution status`);
	}
	if (!['canonical', 'overlay_adjudicated'].includes(record.audit_status)) {
		throw new Error(`${key} has invalid audit status ${record.audit_status}`);
	}
	if (!record.adjudication_source || !record.disposition || record.required_case === undefined) {
		throw new Error(`${key} lacks adjudication metadata`);
	}
}
const canonicalByKey = new Map(canonical.records.map(record => [
	`${record.source.file}:${record.source.line}`,
	{
		audit_status: 'canonical',
		adjudication_source: 'gen3ou-test-map.json',
		partition: record.partition,
		disposition: record.applicability.disposition,
		required_case: record.required_case || null,
	},
]));
const expectedByKey = new Map(canonicalByKey);
for (const file of overlayFiles) {
	const overlay = JSON.parse(fs.readFileSync(path.join(directory, file), 'utf8'));
	if (overlay.pinned_revision !== REVISION) throw new Error(`${file} revision mismatch`);
	for (const source of overlay.records) {
		const key = source.identity && typeof source.identity === 'object' ?
			`${source.identity.source_file}:${source.identity.source_line}` :
			(source.identity || `${source.source_file}:${source.source_line}`);
		if (expectedByKey.has(key)) throw new Error(`duplicate adjudication ${key} in ${file}`);
		expectedByKey.set(key, {
			audit_status: 'overlay_adjudicated',
			adjudication_source: file,
			disposition: source.disposition,
			required_case: source.required_case !== undefined ? source.required_case :
				source.required_native_or_differential_case || null,
		});
	}
}
for (const record of census.records) {
	const key = `${record.source_file}:${record.source_line}`;
	const expected = expectedByKey.get(key);
	if (!expected) throw new Error(`${key} is unadjudicated`);
	for (const field of ['audit_status', 'adjudication_source', 'disposition', 'required_case']) {
		if (JSON.stringify(record[field]) !== JSON.stringify(expected[field])) {
			throw new Error(`${key} ${field} disagrees with ${expected.adjudication_source}`);
		}
	}
	if ((record.partition || null) !== (expected.partition || null)) throw new Error(`${key} partition mismatch`);
}
for (const key of expectedByKey.keys()) if (!keys.has(key)) throw new Error(`adjudicated declaration ${key} is absent`);
const actual = {
	declarations: census.records.length,
	active: census.records.filter(record => record.execution_status === 'active').length,
	pending: census.records.filter(record => record.execution_status === 'pending').length,
	canonical: census.records.filter(record => record.audit_status === 'canonical').length,
	overlay_adjudicated: census.records.filter(record => record.audit_status === 'overlay_adjudicated').length,
	unadjudicated: census.records.filter(record => record.audit_status === 'unadjudicated').length,
};
if (JSON.stringify(census.summary) !== JSON.stringify(actual)) throw new Error('all-test census summary is stale');
if (actual.declarations !== 1976 || actual.canonical !== 1053 ||
	actual.overlay_adjudicated !== 923 || actual.unadjudicated !== 0) {
	throw new Error(`pinned census changed: ${JSON.stringify(actual)}`);
}
console.log(`validated ${actual.declarations} pinned declarations: ${actual.canonical} canonical, ${actual.overlay_adjudicated} overlay-adjudicated, no omissions`);
