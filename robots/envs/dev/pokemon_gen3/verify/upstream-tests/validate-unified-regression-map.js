'use strict';

const fs = require('fs');
const path = require('path');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const file = path.join(__dirname, 'gen3ou-unified-regression-map.json');
const value = JSON.parse(fs.readFileSync(file, 'utf8'));
if (value.schema !== 'pokemon-gen3ou-unified-upstream-regression-map-v1' || value.pinned_revision !== REVISION) {
	throw new Error('unified map schema/revision mismatch');
}
if (value.records.length !== 1976 || value.dynamic_random_battle_admission.length !== 5) {
	throw new Error('unified map count changed');
}
if (value.summary.assertion_specific_total !== 257 ||
	value.summary.applicable_assertion_specific !== 246 ||
	value.summary.applicable !== 246 || value.summary.requiring_case !== 0) {
	throw new Error('unified assertion-specific summary changed');
}
const abilityAliases = value.records.filter(record =>
	record.adjudication_source === 'ability-unadjudicated-overlay.json' &&
	record.disposition === 'applicable-transposed-alias');
if (abilityAliases.length !== 7 || abilityAliases.some(record => {
	const proven = record.evidence_scope === 'assertion_specific' &&
		Object.values(record.evidence).some(values => values.length);
	return !record.applicable || (!record.required_case && !proven) ||
		Boolean(record.required_case) === proven || !record.semantic_sources.length;
})) {
	throw new Error('ability semantic-transposition contract changed');
}
const keys = new Set();
for (const record of value.records) {
	const key = `${record.source.file}:${record.source.line}`;
	if (keys.has(key)) throw new Error(`duplicate declaration ${key}`);
	keys.add(key);
	if (!['active', 'pending'].includes(record.execution_status)) throw new Error(`${key} lacks execution status`);
	for (const category of ['native_units', 'differential_cases', 'invariants', 'randomized_scenarios']) {
		if (!Array.isArray(record.evidence?.[category])) throw new Error(`${key} lacks ${category}`);
	}
	if (record.evidence.differential_cases.some(reference => reference.includes('.c#test_'))) {
		throw new Error(`${key} misclassifies a native unit as differential evidence`);
	}
	if (record.applicable && (!record.semantic_sources.length || !record.mechanics.length || !record.boundaries.length)) {
		throw new Error(`${key} lacks applicable sources/mechanics/boundaries`);
	}
	if (!record.applicable && !record.terminal_reason) throw new Error(`${key} lacks terminal disposition`);
	if (!record.required_case && !record.terminal_reason && record.evidence_scope !== 'assertion_specific') {
		throw new Error(`${key} lacks proof, required case, or terminal disposition`);
	}
}
console.log(`validated ${value.records.length} static declarations and ${value.dynamic_random_battle_admission.length} dynamic Random Battle admission records at ${REVISION}`);
