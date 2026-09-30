'use strict';

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';

function hasProof(variant) {
	return Boolean(variant.evidence.native_units.length ||
		variant.evidence.differential_cases.length ||
		variant.evidence.descriptor_equivalence);
}

function validateRuntimeRegistrationContract(value) {
	if (value.schema !== 'pokemon-showdown-runtime-registration-census-v1' ||
		value.pinned_revision !== REVISION) {
		throw new Error('runtime registration census schema/revision mismatch');
	}
	if (value.summary.registered !== 2172 || value.summary.active !== 2129 ||
		value.summary.pending !== 43 || value.summary.static_declarations !== 1976 ||
		value.summary.dynamic_expansions !== 196 ||
		value.summary.gen3ou_applicable_dynamic_variants !== 41 ||
		value.summary.gen3ou_applicable_dynamic_variants_proven !== 41) {
		throw new Error('pinned runtime registration totals changed');
	}
	const variants = value.gen3ou_applicable_dynamic_declarations.flatMap(record => record.variants);
	if (variants.length !== 41 || new Set(variants.map(variant => variant.key)).size !== 41) {
		throw new Error('expected 41 distinct Gen 3 OU-applicable runtime variants');
	}
	for (const variant of variants) {
		const proven = hasProof(variant);
		if (!proven && !variant.required_case) throw new Error(`${variant.key} lacks proof or a required case`);
		if (proven && variant.required_case) throw new Error(`${variant.key} has proof and a required case`);
	}
	const trapping = value.gen3ou_applicable_dynamic_declarations.filter(record =>
		record.source.file === 'test/sim/misc/trapmoves.js').flatMap(record => record.variants);
	if (trapping.length !== 33) throw new Error(`expected 33 trapping variants, got ${trapping.length}`);
	const batonPass = trapping.filter(variant => variant.assertion === 'permits-baton-pass-switch');
	if (batonPass.length !== 9 || batonPass.some(variant =>
		!hasProof(variant) || variant.required_case)) {
		throw new Error('all nine Baton Pass variants require assertion-specific proof');
	}
	const provenTrapping = trapping.filter(variant => !variant.required_case);
	if (provenTrapping.length !== 33) {
		throw new Error(`expected 33 proven trapping variants, got ${provenTrapping.length}`);
	}
}

module.exports = {validateRuntimeRegistrationContract};
