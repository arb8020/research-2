'use strict';

const fs = require('fs');
const path = require('path');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const directory = path.resolve(process.argv[2] || __dirname);
const output = path.resolve(process.argv[3] || path.join(directory, 'gen3ou-test-map.json'));
const read = name => JSON.parse(fs.readFileSync(path.join(directory, name), 'utf8'));

const inherited = read('gen3ou-inherited-test-map.json');
const core = read('core-test-census.json');
const supplemental = read('resolved-gen3-entity-test-gaps.json');
const entityManual = read('entity-manual-adjudications.json');
const coreManual = read('core-manual-adjudications.json');

function requireRevision(value, name) {
	const actual = value.oracle_revision || value.pinned_revision || value.revision;
	if (actual !== REVISION) throw new Error(`${name}: expected revision ${REVISION}, got ${actual}`);
}
for (const [name, value] of Object.entries({inherited, core, supplemental, entityManual, coreManual})) {
	requireRevision(value, name);
}

const sourceKey = record => `${record.source_file}:${record.source_line}:${record.full_test_name || record.full_name}`;
function exactOverlay(base, manual, predicate, name) {
	const expected = base.records.filter(predicate);
	const byKey = new Map(manual.records.map(record => [sourceKey(record), record]));
	if (byKey.size !== manual.records.length) throw new Error(`${name}: duplicate manual source key`);
	for (const record of expected) {
		if (!byKey.has(sourceKey(record))) throw new Error(`${name}: missing ${sourceKey(record)}`);
	}
	if (byKey.size !== expected.length) {
		throw new Error(`${name}: expected ${expected.length} manual rows, got ${byKey.size}`);
	}
	return byKey;
}
const entityOverlay = exactOverlay(inherited, entityManual,
	record => record.applicability === 'candidate_requires_gen3_source_adjudication', 'entity overlay');
const coreOverlay = exactOverlay(core, coreManual,
	record => record.applicability === 'requires-source-adjudication', 'core overlay');

function evidence(nativeUnits = [], differentials = [], invariants = [], randomized = []) {
	return {
		native_units: [...nativeUnits], differential_cases: [...differentials],
		invariants: [...invariants], randomized_scenarios: [...randomized],
	};
}
function evidenceFromIDs(ids) {
	const out = evidence();
	for (const id of ids || []) {
		if (id.startsWith('differential:') || id.startsWith('case:')) {
			out.differential_cases.push(id.slice(id.indexOf(':') + 1));
		} else if (id.startsWith('invariant:')) {
			out.invariants.push(id.slice('invariant:'.length));
		} else if (id.startsWith('random:')) {
			out.randomized_scenarios.push(id.slice('random:'.length));
		} else if (id.startsWith('native/') && id.includes('#test_')) {
			out.native_units.push(id);
		} else if (!id.startsWith('test_')) {
			out.differential_cases.push(id);
		} else {
			out.native_units.push(id);
		}
	}
	return out;
}
const hasEvidence = value => Object.values(value).some(values => values.length);
const applicable = disposition => [
	'g3_explicit', 'gen3-explicit', 'g3_source_applicable', 'verifier-admission',
].includes(disposition);

function coreMechanics(record) {
	if (record.source_file === 'test/sim/misc/faint-order.js' && record.source_line === 26) {
		return ['pre-hit self-faint', 'Gen 3 queued-action cancellation', 'forced replacement'];
	}
	if (record.source_file === 'test/sim/misc/ohko.js' && record.source_line === 38) {
		return ['current-HP OHKO damage', 'Substitute routing', 'called-move reachability'];
	}
	if (record.applicability === 'verifier-admission') {
		const mechanics = ['learnset source compatibility', 'generation-aware set admission'];
		if (/egg|breed|chainbreed/i.test(record.full_test_name)) {
			mechanics.push('egg-move and breeding-chain legality');
		}
		if (/event|Pomeg/i.test(record.full_test_name)) {
			mechanics.push('event-origin legality');
		}
		if (/ability|evolving/i.test(record.full_test_name)) {
			mechanics.push('cross-generation ability and evolution compatibility');
		}
		return mechanics;
	}
	return [];
}

function inheritedRecord(record) {
	const manual = entityOverlay.get(sourceKey(record));
	if (manual) {
		const assertion = evidence(
			manual.assertion_specific_evidence.native_unit_tests,
			manual.assertion_specific_evidence.differential_cases);
		const isApplicable = applicable(manual.applicability);
		return {
			partition: 'entity', source: {file: record.source_file, line: record.source_line,
				full_test_name: record.full_name},
			descriptor: {kind: manual.corrected_descriptor_kind, id: manual.corrected_descriptor_id,
				original_id: manual.original_descriptor_id},
			applicability: {disposition: manual.applicability, evidence: manual.applicability_evidence},
			semantic_sources: manual.semantic_sources, mechanics: manual.corrected_mechanics,
			boundaries: manual.corrected_semantic_boundaries,
			evidence: assertion,
			evidence_scope: hasEvidence(assertion) ?
				(manual.needs_new_case ? 'partial' : 'assertion_specific') : 'none',
			entity_candidate_evidence: manual.entity_candidate_evidence,
			required_case: manual.needs_new_case ? manual.proposed_case_or_terminal.replace(/^case:\s*/, '') : null,
			terminal_reason: isApplicable ? null :
				manual.proposed_case_or_terminal.replace(/^terminal:\s*/, ''),
		};
	}
	const assertion = evidence(record.native_unit_tests.filter(reference =>
		reference !== 'native/test_pokemon.c#generated-descriptor-evidence'), record.differential_cases,
		record.invariant_ids, record.randomized_scenario_ids);
	const isApplicable = applicable(record.applicability);
	const proven = record.coverage_evidence_scope === 'assertion_specific' && hasEvidence(assertion);
	return {
		partition: 'entity', source: {file: record.source_file, line: record.source_line,
			full_test_name: record.full_name}, descriptor: {kind: record.descriptor_kind, id: record.descriptor_id},
		applicability: {disposition: record.applicability, evidence: record.applicability_evidence},
		semantic_sources: record.showdown_semantic_sources, mechanics: record.mechanics,
		boundaries: record.semantic_boundaries, evidence: assertion,
		evidence_scope: record.coverage_evidence_scope,
		required_case: isApplicable && !proven ? (record.needed_case || `upstream-${record.descriptor_id}-${record.source_line}`) : null,
		terminal_reason: isApplicable ? null : (record.note || record.applicability_evidence),
	};
}

function coreRecord(record) {
	if (record.source_file === 'test/sim/team-validator/formes.js' &&
		record.source_line === 22 &&
		record.full_test_name === 'Team Validator > should handle Deoxys formes in Gen 3') {
		return {
			partition: 'core', source: {file: record.source_file, line: record.source_line,
				full_test_name: record.full_test_name}, descriptor: null,
			applicability: {disposition: 'format_unreachable_gen3ou_singles', evidence:
				'The assertion is specific to Gen 3 Ubers and custom +nonexistent rules. Every Deoxys forme is Uber in the pinned Gen 3 OU RuleTable, so OU rejects each set before the cross-form Species Clause interaction is observable.'},
			semantic_sources: [
				'test/sim/team-validator/formes.js:22', 'sim/team-validator.ts#validateTeam',
				'sim/team-validator.ts#validateForme',
			],
			mechanics: ['selectable Deoxys formes', 'base-species uniqueness'],
			boundaries: ['admission/rule validation'], evidence: evidence([], []),
			evidence_scope: 'none', required_case: null,
			terminal_reason: 'The upstream assertion requires Gen 3 Ubers or a custom rule table; all Deoxys formes are rejected as Uber in Gen 3 OU.',
		};
	}
	if (record.source_file === 'test/sim/team-validator/basic.js' &&
		record.source_line === 103 && record.full_test_name === 'Team Validator > should validate EVs') {
		return {
			partition: 'core', source: {file: record.source_file, line: record.source_line,
				full_test_name: record.full_test_name}, descriptor: null,
			applicability: {disposition: 'g3_source_applicable', evidence:
				'The fixture names Gen 8 OU, but the assertion exercises shared validateStats EV normalization and the same Auto-to-510 value-rule path resolved by Gen 3 OU.'},
			semantic_sources: [
				'test/sim/team-validator/basic.js', 'sim/team-validator.ts#validateStats',
				'sim/dex-formats.ts#RuleTable.resolveNumbers', 'data/rulesets.ts#obtainable',
			],
			mechanics: ['normalized EV vector', 'per-stat EV bounds', 'resolved total EV limit'],
			boundaries: ['set input normalization', 'admission/rule validation'],
			evidence: evidence(
				['native/test_admission.c#test_ev_stat_vector_policy'],
				['ban-ev-omitted', 'ban-ev-zero', 'legal-ev-one', 'legal-ev-510',
					'ban-ev-511', 'legal-ev-stat-255', 'ban-ev-stat-256']),
			evidence_scope: 'assertion_specific', required_case: null, terminal_reason: null,
		};
	}
	const manual = coreOverlay.get(sourceKey(record));
	if (manual) {
		const mappedEvidence = evidenceFromIDs(manual.evidence_ids);
		const isApplicable = applicable(manual.applicability);
		return {
			partition: 'core', source: {file: record.source_file, line: record.source_line,
				full_test_name: record.full_test_name}, descriptor: null,
			applicability: {disposition: manual.applicability, evidence: manual.applicability_evidence},
			semantic_sources: manual.semantic_sources, mechanics: [manual.adjudication_group],
			boundaries: manual.corrected_semantic_boundaries, evidence: mappedEvidence,
			evidence_scope: hasEvidence(mappedEvidence) ?
				(manual.needs_new_case ? 'partial' : 'assertion_specific') : 'none',
			required_case: manual.needs_new_case ? manual.proposed_case_or_terminal.replace(/^case:\s*/, '') : null,
			terminal_reason: isApplicable ? null :
				manual.proposed_case_or_terminal.replace(/^terminal:\s*/, ''),
		};
	}
	const mappedEvidence = evidenceFromIDs(record.existing_evidence_ids);
	if (record.source_file === 'test/sim/misc/faint-order.js' && record.source_line === 26) {
		mappedEvidence.native_units.push(
			'native/test_pokemon.c#test_pre_hit_self_faint_and_fifo_drain');
	}
	const isApplicable = applicable(record.applicability);
	return {
		partition: 'core', source: {file: record.source_file, line: record.source_line,
			full_test_name: record.full_test_name}, descriptor: null,
		applicability: {disposition: record.applicability, evidence: record.applicability_evidence},
		semantic_sources: [record.source_file], mechanics: coreMechanics(record),
		boundaries: record.semantic_boundaries,
		evidence: mappedEvidence, evidence_scope: hasEvidence(mappedEvidence) ? 'assertion_specific' : 'none',
		required_case: isApplicable && !hasEvidence(mappedEvidence) ?
			(record.proposed_case || `upstream-core-${record.id}`) : null,
		terminal_reason: isApplicable ? null : record.applicability_evidence,
	};
}

function supplementalRecord(record) {
	return {
		partition: 'supplemental', source: {file: record.source_file, line: record.source_line,
			full_test_name: record.full_test_name}, descriptor: {kind: record.descriptor_kind, id: record.descriptor_id},
		applicability: {disposition: record.ou_reachability, evidence: record.ou_reachability_evidence},
		semantic_sources: record.showdown_semantic_sources, mechanics: record.mechanics,
		boundaries: record.semantic_boundaries,
		evidence: evidence(record.native_unit_tests, record.differential_cases,
			record.invariant_ids, record.randomized_scenario_ids),
		evidence_scope: record.evidence_scope, required_case: record.needs_new_case ? record.proposed_case : null,
		terminal_reason: record.needs_new_case ? null : record.ou_reachability_evidence,
	};
}

const records = [
	...inherited.records.map(inheritedRecord),
	...core.records.map(coreRecord),
	...supplemental.records.map(supplementalRecord),
].sort((a, b) => a.source.file.localeCompare(b.source.file) || a.source.line - b.source.line);
const keys = new Set();
for (const record of records) {
	const key = `${record.source.file}:${record.source.line}`;
	if (keys.has(key)) throw new Error(`duplicate upstream declaration ${key}`);
	keys.add(key);
	if (!record.semantic_sources.length || !record.boundaries.length ||
		(applicable(record.applicability.disposition) && !record.mechanics.length) ||
		!record.applicability.evidence) {
		throw new Error(`${key}: incomplete semantic adjudication`);
	}
	if (record.required_case && record.terminal_reason) throw new Error(`${key}: both case and terminal reason`);
	if (!record.required_case && !record.terminal_reason && record.evidence_scope !== 'assertion_specific') {
		throw new Error(`${key}: no proof, required case, or terminal reason`);
	}
}
const summary = {
	declarations: records.length,
	by_partition: Object.fromEntries(['entity', 'core', 'supplemental'].map(partition =>
		[partition, records.filter(record => record.partition === partition).length])),
	by_disposition: Object.fromEntries([...new Set(records.map(record => record.applicability.disposition))]
		.sort().map(disposition => [disposition, records.filter(record => record.applicability.disposition === disposition).length])),
	assertion_specific: records.filter(record => record.evidence_scope === 'assertion_specific').length,
	requiring_new_case: records.filter(record => record.required_case).length,
};
const artifact = {
	schema: 'pokemon-gen3ou-upstream-regression-map-v1', pinned_revision: REVISION,
	scope: 'Every statically declared test in the frozen entity, core, and resolved-entity supplemental partitions; applicability is manually adjudicated for Gen 3 OU.',
	summary, records,
};
fs.writeFileSync(output, `${JSON.stringify(artifact, null, 2)}\n`);
console.log(JSON.stringify(summary));
