'use strict';

// This is deliberately a separate audit overlay. It does not feed the canonical
// semantic map or any support classification.

const fs = require('fs');
const path = require('path');

const PINNED_REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const AS_ONE_IDS = ['asoneglastrier', 'asonespectrier'];
const ADJUDICATION_FILE = 'ability-semantic-transposition-adjudications.json';

function classifyMechanics(name) {
	const text = name.toLowerCase();
	const mechanics = ['post-Gen-3 ability behavior'];
	const boundaries = ['event-handler discovery and ordered dispatch', 'canonical battle state'];
	const add = (mechanic, boundary) => {
		if (!mechanics.includes(mechanic)) mechanics.push(mechanic);
		if (!boundaries.includes(boundary)) boundaries.push(boundary);
	};

	if (/switch|switched|forced out|switch-out|enters (?:battle|the field)|leaves the field/.test(text)) {
		add('switch lifecycle', 'switching, faint replacement, and request transitions');
	}
	if (/priority|speed|move first|move last|order/.test(text)) {
		add('priority or speed modification', 'action-queue construction and ordering');
	}
	if (/faint|ko(?:ed)?|knock out/.test(text)) {
		add('faint-triggered behavior', 'faint queue and terminal resolution');
	}
	if (/accuracy|miss|always hit/.test(text)) {
		add('accuracy modification', 'targeting, immunity, and hit resolution');
	}
	if (/damage|hp|heal|restore|recoil|quarter|max hp|half/.test(text)) {
		add('damage or healing modification', 'damage, healing, and HP transition');
	}
	if (/status|poison|burn|paraly|sleep|freeze|toxic/.test(text)) {
		add('status interaction', 'status creation, prevention, and removal');
	}
	if (/item|berry|consume|eating|held/.test(text)) {
		add('held-item interaction', 'item activation, consumption, and ownership');
	}
	if (/boost|stat|maximi[sz]e attack|attack (?:is |was )?(?:raised|lowered)|defense|sp\. atk|sp\. def|evasion/.test(text)) {
		add('stat-stage or stat modification', 'boost validation and stat calculation');
	}
	if (/weather|rain|sun|sand|hail|snow/.test(text)) {
		add('weather interaction', 'weather lifecycle and suppression');
	}
	if (/move|type|power|contact|critical|secondary|immun|super effective/.test(text)) {
		add('move-resolution interaction', 'move targeting, hit, damage, and effects');
	}
	if (/ability|suppress|mold breaker|neutralizing gas|copy|transform/.test(text)) {
		add('ability identity or suppression', 'ability ownership, suppression, and handler visibility');
	}
	if (/double|ally|adjacent|partner|both foes|multiple target/.test(text)) {
		add('multi-active positioning', 'target topology and multi-active event order');
	}
	return {mechanics, boundaries};
}

function sourceLines(text) {
	const lines = text.split(/\r?\n/);
	const result = new Map();
	for (let index = 0; index < lines.length; index++) {
		const match = lines[index].match(/^\t([a-z0-9]+): \{$/);
		if (match) result.set(match[1], index + 1);
	}
	return result;
}

function assertionEvidence(ids) {
	const evidence = {
		native_units: [], differential_cases: [], invariants: [], randomized_scenarios: [],
	};
	for (const id of ids || []) {
		if (id.startsWith('differential:')) evidence.differential_cases.push(id.slice(13));
		else if (id.startsWith('focused-c:')) evidence.native_units.push(id.slice(10));
		else throw new Error(`unsupported assertion evidence id ${id}`);
	}
	return evidence;
}

function main() {
	const showdown = path.resolve(process.argv[2] || '/private/tmp/pokemon-lockon-clean');
	const output = path.resolve(process.argv[3] || path.join(__dirname, 'ability-unadjudicated-overlay.json'));
	const census = JSON.parse(fs.readFileSync(path.join(__dirname, 'all-test-census.json'), 'utf8'));
	const adjudications = JSON.parse(fs.readFileSync(path.join(__dirname, ADJUDICATION_FILE), 'utf8'));
	if (adjudications.schema !== 'pokemon-gen3ou-ability-semantic-transposition-adjudications-v1' ||
		adjudications.pinned_revision !== PINNED_REVISION) {
		throw new Error(`${ADJUDICATION_FILE}: schema/revision mismatch`);
	}
	const exceptions = new Map(Object.entries(adjudications.records));
	if (exceptions.size !== 43 || adjudications.summary.records !== exceptions.size) {
		throw new Error(`${ADJUDICATION_FILE}: expected exactly 43 reviewed exception rows`);
	}
	const abilitySourcePath = path.join(showdown, 'data', 'abilities.ts');
	const abilitySource = fs.readFileSync(abilitySourcePath, 'utf8');
	const linesById = sourceLines(abilitySource);
	const {Dex} = require(path.join(showdown, 'dist', 'sim'));
	const resolved = Dex.forGen(3);

	const declarations = census.records.filter(record =>
		record.source_file.startsWith('test/sim/abilities/') &&
		(record.audit_status === 'unadjudicated' ||
			record.adjudication_source === 'ability-unadjudicated-overlay.json'));
	const records = declarations.map(declaration => {
		const fileId = path.basename(declaration.source_file, '.js');
		const ids = fileId === 'asone' ? AS_ONE_IDS : [fileId];
		const abilities = ids.map(id => resolved.abilities.get(id));
		for (const ability of abilities) {
			if (!ability.exists || ability.gen <= 3 || ability.isNonstandard !== 'Future') {
				throw new Error(`${declaration.source_file}: expected ${ability.id} to resolve as a post-Gen-3 Future ability`);
			}
		}
		const sourceReferences = ids.map(id => {
			const line = linesById.get(id);
			if (!line) throw new Error(`missing base-data source line for ${id}`);
			return `data/abilities.ts:${line}`;
		});
		sourceReferences.push('sim/dex-abilities.ts:52-66', 'sim/dex-abilities.ts:103-107');
		const {mechanics, boundaries} = classifyMechanics(declaration.full_test_name);
		const generations = [...new Set(abilities.map(ability => ability.gen))];
		const key = `${declaration.source_file}:${declaration.source_line}:${declaration.full_test_name}`;
		const reviewed = exceptions.get(key);
		if (reviewed) {
			exceptions.delete(key);
			if (reviewed.key !== key || reviewed.source_file !== declaration.source_file ||
				reviewed.source_line !== declaration.source_line ||
				reviewed.full_test_name !== declaration.full_test_name ||
				reviewed.pinned_revision !== PINNED_REVISION) {
				throw new Error(`${ADJUDICATION_FILE}: stale identity ${key}`);
			}
		}
		const semanticDisposition = reviewed?.disposition || 'owner_specific_terminal';
		const disposition = semanticDisposition === 'gen3_alias_applicable' ?
			'applicable-transposed-alias' : semanticDisposition;
		const applicable = disposition === 'applicable-transposed-alias';
		const proof = assertionEvidence(reviewed?.evidence_ids);
		const proven = Object.values(proof).some(values => values.length);
		if (applicable && ((!reviewed.required_case && !proven) || !reviewed.gen3_alias_owner_or_mechanic ||
			!reviewed.pinned_source_references.length)) {
			throw new Error(`${ADJUDICATION_FILE}: incomplete applicable alias ${key}`);
		}
		const defaultTerminalEvidence =
			`The Gen 3 ModdedDex resolves ${ids.join('/')} as Future generation ${generations.join('/')}. ` +
			'The assertion depends on that absent ability\'s unique trigger, state, or effect; no legal Gen 3 descriptor preserves its denotation after substituting test scaffolding. Shared low-level operations alone are not semantic equivalence.';
		const evidence = applicable ?
			`The named ability is unavailable in Gen 3, but this assertion transposes to the legal Gen 3 ${reviewed.gen3_alias_owner_or_mechanic} boundary. The required case proves only that aliased boundary, not the future ability.` :
			reviewed ?
				`The named ability is unavailable in Gen 3. ${reviewed.gen3_alias_owner_or_mechanic || 'Its asserted behavior is owner-specific.'} This does not preserve the complete trigger, ownership, ordering, and effect denotation of the upstream assertion.` :
				defaultTerminalEvidence;
		return {
			source_file: declaration.source_file,
			source_line: declaration.source_line,
			full_test_name: declaration.full_test_name,
			ability_ids: ids,
			resolved_generations: generations,
			disposition,
			semantic_transposition_disposition: semanticDisposition,
			evidence,
			resolved_gen3_source_references: sourceReferences,
			semantic_sources: reviewed?.pinned_source_references || sourceReferences,
			mechanics,
			semantic_boundaries: boundaries,
			assertion_evidence: proof,
			assertion_evidence_scope: proven ? 'assertion_specific' : 'none',
			required_native_or_differential_case: reviewed?.required_case || null,
			case_decision: applicable ?
				(proven ? 'Assertion-specific evidence is checked.' :
					`Required case: ${reviewed.required_case}.`) :
				`No case from this assertion: ${semanticDisposition.replaceAll('_', ' ')}.`,
		};
	});
	if (exceptions.size) {
		throw new Error(`${ADJUDICATION_FILE}: ${exceptions.size} reviewed rows no longer match the pinned census`);
	}

	const generationCounts = {};
	for (const record of records) {
		for (const gen of record.resolved_generations) generationCounts[gen] = (generationCounts[gen] || 0) + 1;
	}
	const overlay = {
		schema: 'pokemon-showdown-gen3ou-ability-semantic-overlay-v2',
		pinned_revision: PINNED_REVISION,
		scope: 'Every declaration assigned to the post-Gen-3 ability overlay in all-test-census.json, with explicit semantic-transposition review. This audit overlay does not modify support claims.',
		summary: {
			declarations: records.length,
			files: new Set(records.map(record => record.source_file)).size,
			applicable: records.filter(record => record.disposition === 'applicable-transposed-alias').length,
			applicable_transposed_alias: records.filter(record => record.disposition === 'applicable-transposed-alias').length,
			shared_operation_not_equivalent: records.filter(record => record.disposition === 'shared_operation_not_equivalent').length,
			owner_specific_terminal: records.filter(record => record.disposition === 'owner_specific_terminal').length,
			semantic_exception_records: adjudications.summary.records,
			default_terminal_records: records.length - adjudications.summary.records,
			uncertain: 0,
			declarations_by_introduction_generation: generationCounts,
		},
		records,
	};
	fs.writeFileSync(output, `${JSON.stringify(overlay, null, 2)}\n`);
	console.log(`wrote ${records.length} ability declarations from ${overlay.summary.files} files to ${output}`);
}

main();
