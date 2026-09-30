'use strict';

const fs = require('fs');
const path = require('path');
const childProcess = require('child_process');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const directory = __dirname;
const showdown = path.resolve(process.argv[2] || '');
if (!process.argv[2]) throw new Error('usage: node build-unified-regression-map.js POKEMON_SHOWDOWN_DIR');
const actualRevision = childProcess.execFileSync('git', ['rev-parse', 'HEAD'], {cwd: showdown, encoding: 'utf8'}).trim();
if (actualRevision !== REVISION) throw new Error(`expected pinned Showdown ${REVISION}, got ${actualRevision}`);

const read = file => JSON.parse(fs.readFileSync(path.join(directory, file), 'utf8'));
const census = read('all-test-census.json');
const canonical = read('gen3ou-test-map.json');
const overlayNames = [
	'ability-unadjudicated-overlay.json',
	'gen3ou-item-test-overlay.json',
	'move-declaration-overlay.json',
	'scope-test-overlay.json',
];
const overlays = new Map();
for (const file of overlayNames) {
	const value = read(file);
	if (value.pinned_revision !== REVISION) throw new Error(`${file} revision mismatch`);
	for (const record of value.records) {
		const key = record.identity && typeof record.identity === 'object' ?
			`${record.identity.source_file}:${record.identity.source_line}` :
			(record.identity || `${record.source_file}:${record.source_line}`);
		if (overlays.has(key)) throw new Error(`duplicate overlay record ${key}`);
		overlays.set(key, {file, record});
	}
}
const canonicalByKey = new Map(canonical.records.map(record => [`${record.source.file}:${record.source.line}`, record]));
const applicable = new Set([
	'g3_source_applicable', 'g3_explicit', 'gen3-explicit', 'verifier-admission',
	'applicable-transposed-generic', 'applicable-transposed-alias',
]);
const emptyEvidence = () => ({native_units: [], differential_cases: [], invariants: [], randomized_scenarios: []});
const legacyMechanics = record => {
	if (record.source.file === 'test/sim/misc/faint-order.js' && record.source.line === 26) {
		return ['pre-hit self-faint', 'action-queue truncation', 'forced replacement'];
	}
	if (record.source.file === 'test/sim/misc/ohko.js' && record.source.line === 38) {
		return ['current-HP OHKO damage', 'Substitute interception', 'called-move reachability'];
	}
	if (record.applicability.disposition === 'verifier-admission') {
		return ['team validation', 'learnset/event legality', 'normalization admission'];
	}
	return record.mechanics;
};
const records = census.records.map(source => {
	const key = `${source.source_file}:${source.source_line}`;
	const base = canonicalByKey.get(key);
	if (base) {
		return {
			revision: REVISION,
			source: base.source,
			execution_status: source.execution_status,
			partition: base.partition,
			disposition: base.applicability.disposition,
			applicable: applicable.has(base.applicability.disposition),
			applicability_evidence: base.applicability.evidence,
			semantic_sources: base.semantic_sources,
			mechanics: legacyMechanics(base),
			boundaries: base.boundaries,
			evidence: base.evidence,
			evidence_scope: base.evidence_scope,
			required_case: base.required_case,
			terminal_reason: base.terminal_reason,
			adjudication_source: 'gen3ou-test-map.json',
		};
	}
	const overlay = overlays.get(key);
	if (!overlay) throw new Error(`missing adjudication for ${key}`);
	const value = overlay.record;
	return {
		revision: REVISION,
		source: {file: source.source_file, line: source.source_line, full_test_name: source.full_test_name},
		execution_status: source.execution_status,
		partition: 'all-test-overlay',
		disposition: value.disposition,
		applicable: applicable.has(value.disposition),
		applicability_evidence: value.resolved_source_evidence || value.reason || value.evidence,
		semantic_sources: value.semantic_sources || [],
		mechanics: value.mechanics || [],
		boundaries: value.semantic_boundaries || value.boundaries || [],
		evidence: value.assertion_evidence || emptyEvidence(),
		evidence_scope: value.assertion_evidence_scope || 'none',
		required_case: value.required_case || value.required_native_or_differential_case || null,
		terminal_reason: applicable.has(value.disposition) ? null :
			(value.resolved_source_evidence || value.reason || value.evidence),
		adjudication_source: overlay.file,
	};
});

const dynamicRandomBattleAdmission = [
	['Max Move Count', 'Gen 3 Random Battle should support Max Move Count = 24', 40],
	['set data', 'gen3/sets.json should have valid set data', 168],
	['move count', 'all Pokemon should have 4 moves, except for Ditto and Unown', 228],
	['moveset reachability', 'all moves on all sets should exist and be obtainable', 233],
	['generated team validity', 'should generate valid [Gen 3] Random Battle teams', 283],
].map(([mechanic, testName, sourceLine]) => ({
	revision: REVISION,
	source: {file: 'test/random-battles/all-gens.js', line: sourceLine, full_test_name: testName},
	partition: 'dynamic-random-battle-admission',
	disposition: 'outside_gen3ou_native_runtime_random_battle_admission',
	applicable: false,
	applicability_evidence: 'The dynamically expanded test targets gen3randombattle team generation/data, not Gen 3 OU battle transitions.',
	semantic_sources: ['test/random-battles/all-gens.js'],
	mechanics: [`random battle ${mechanic}`],
	boundaries: ['team generation/admission'],
	evidence: emptyEvidence(),
	evidence_scope: 'none',
	required_case: null,
	terminal_reason: 'Keep as verifier/data-generation evidence; it is outside the Gen 3 OU native battle runtime contract.',
	adjudication_source: 'dynamic expansion audit',
}));

if (records.length !== 1976) throw new Error(`expected 1976 static declarations, got ${records.length}`);
for (const record of records) {
	const key = `${record.source.file}:${record.source.line}`;
	if (!record.source.full_test_name || record.revision !== REVISION) throw new Error(`${key} lacks source identity`);
	for (const category of ['native_units', 'differential_cases', 'invariants', 'randomized_scenarios']) {
		if (!Array.isArray(record.evidence[category])) throw new Error(`${key} lacks evidence.${category}`);
	}
	if (applicable.has(record.disposition)) {
		if (!record.semantic_sources.length) throw new Error(`${key} lacks semantic sources`);
		if (!record.mechanics.length || !record.boundaries.length) throw new Error(`${key} lacks applicable semantics`);
		const proof = record.evidence_scope === 'assertion_specific' && Object.values(record.evidence).some(values => values.length);
		if (!proof && !record.required_case) throw new Error(`${key} lacks assertion proof or required case`);
	} else if (!record.terminal_reason) {
		throw new Error(`${key} lacks terminal reason`);
	}
}
const output = {
	schema: 'pokemon-gen3ou-unified-upstream-regression-map-v1',
	pinned_revision: REVISION,
	scope: 'Every static it()/test() declaration below test/sim, plus separately enumerated dynamic Gen 3 Random Battle admission tests.',
	summary: {
		static_declarations: records.length,
		applicable: records.filter(record => applicable.has(record.disposition)).length,
		assertion_specific_total: records.filter(record =>
			record.evidence_scope === 'assertion_specific').length,
		applicable_assertion_specific: records.filter(record =>
			applicable.has(record.disposition) && record.evidence_scope === 'assertion_specific').length,
		requiring_case: records.filter(record => record.required_case).length,
		dynamic_random_battle_admission: dynamicRandomBattleAdmission.length,
	},
	records,
	dynamic_random_battle_admission: dynamicRandomBattleAdmission,
};
fs.writeFileSync(path.join(directory, 'gen3ou-unified-regression-map.json'), `${JSON.stringify(output, null, 2)}\n`);
console.log(JSON.stringify(output.summary, null, 2));
