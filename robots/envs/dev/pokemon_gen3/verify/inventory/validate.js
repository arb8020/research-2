'use strict';

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const CLASSES = new Set(['implemented', 'inert', 'unreachable', 'unsupported']);
const GENERATED_SOURCE = 'verify/inventory/gen3ou-inventory.json';

function generatedCount(source, selector) {
	const counts = source.counts;
	const direct = {
		species: counts.species,
		moves: counts.moves,
		abilities: counts.abilities,
		items: counts.items,
		format_rules: counts.format_rules,
		target_modes: counts.target_modes,
		callback_hooks: counts.callback_hooks,
		simulator_only_conditions: counts.simulator_only_conditions,
	};
	if (selector in direct) return direct[selector];
	if (selector === 'statuses + volatiles + side_conditions + weather + pseudo_weather + slot_conditions') {
		return counts.statuses + counts.volatiles + counts.side_conditions + counts.weather + counts.pseudo_weather + counts.slot_conditions;
	}
	return null;
}

function generatedIDs(source, selector) {
	if (selector === 'statuses + volatiles + side_conditions + weather + pseudo_weather + slot_conditions') {
		return ['statuses', 'volatiles', 'side_conditions', 'weather', 'pseudo_weather', 'slot_conditions']
			.flatMap(kind => source[kind].map(entry => `${kind}.${entry.id}`));
	}
	if (selector === 'callback_hooks') return source.callback_hooks.map(entry => `${entry.owner_kind}.${entry.owner_id}.${entry.hook}`);
	const values = source[selector];
	if (!Array.isArray(values)) return null;
	return values.map(entry => typeof entry === 'string' ? entry : entry.id);
}

function jsonFiles(root) {
	const result = [];
	for (const entry of fs.readdirSync(root, {withFileTypes: true})) {
		const filename = path.join(root, entry.name);
		if (entry.isDirectory()) result.push(...jsonFiles(filename));
		else if (entry.name.endsWith('.json')) result.push(filename);
	}
	return result;
}

function caseIDs(casesRoot, admissionPath) {
	const result = new Set();
	for (const filename of jsonFiles(casesRoot)) {
		const value = JSON.parse(fs.readFileSync(filename, 'utf8'));
		if (value.schema === 'pokemon-native-differential-case-v1') result.add(value.id);
	}
	const admission = JSON.parse(fs.readFileSync(admissionPath, 'utf8'));
	if (admission.schema !== 'pokemon-gen3ou-admission-cases-v2' || !Array.isArray(admission.cases)) {
		throw new Error('admission differential corpus is missing or structurally invalid');
	}
	for (const admissionCase of admission.cases) result.add(admissionCase.id);
	return result;
}

function validate(manifest, projectRoot) {
	const structural = [];
	const readiness = [];
	if (manifest.schema !== 'pokemon-native-descriptor-map-v1') structural.push('unsupported schema');
	if (manifest.oracle_revision !== REVISION) structural.push('wrong oracle revision');
	if (manifest.format !== 'gen3ou') structural.push('wrong format');
	if (!['draft', 'frozen'].includes(manifest.freeze_status)) structural.push('invalid freeze_status');
	if (!Array.isArray(manifest.inventories)) structural.push('inventories must be an array');
	if (structural.length) return {schema_valid: false, inventory_ready: false, completion_ready: false, progress: null, structural_failures: structural, readiness_failures: readiness};

	const features = new Set(JSON.parse(fs.readFileSync(path.join(projectRoot, 'verify/cases/features.json'), 'utf8')).features);
	const cases = caseIDs(
		path.join(projectRoot, 'verify/cases'),
		path.join(projectRoot, 'verify/admission/cases.json'));
	const inventoryKinds = new Set();
	const identities = new Set();
	const generatedPath = path.join(projectRoot, GENERATED_SOURCE);
	const generatedBytes = fs.readFileSync(generatedPath);
	const generated = JSON.parse(generatedBytes);
	const generatedDigest = crypto.createHash('sha256').update(generatedBytes).digest('hex');
	if (generated.oracle?.revision !== REVISION || generated.oracle?.format !== 'gen3ou') structural.push('generated inventory oracle identity mismatch');
	let classified = 0;
	let expected = 0;
	const earned = {classified: 0, source_mapped: 0, generation_mapped: 0, native_or_gap_mapped: 0, focused_evidence: 0, differential_evidence: 0};

	for (const inventory of manifest.inventories) {
		if (inventoryKinds.has(inventory.kind)) structural.push(`duplicate inventory kind ${inventory.kind}`);
		inventoryKinds.add(inventory.kind);
		if (inventory.source === GENERATED_SOURCE) {
			const sourceCount = generatedCount(generated, inventory.selector);
			const sourceIDs = generatedIDs(generated, inventory.selector);
			if (sourceCount === null) structural.push(`${inventory.kind}: unknown generated selector ${inventory.selector}`);
			else if (inventory.expected_count !== sourceCount) structural.push(`${inventory.kind}: expected_count does not match generated source (${sourceCount})`);
			if (inventory.frozen_digest !== generatedDigest) structural.push(`${inventory.kind}: digest does not match generated source`);
			if (sourceIDs) {
				const actualIDs = new Set(inventory.entries.map(entry => entry.id));
				for (const id of actualIDs) if (!sourceIDs.includes(id)) structural.push(`${inventory.kind}: descriptor ${id} is absent from generated source`);
				if (manifest.freeze_status === 'frozen') for (const id of sourceIDs) if (!actualIDs.has(id)) readiness.push(`${inventory.kind}: generated descriptor ${id} is unclassified`);
			}
		}
		if (Number.isInteger(inventory.expected_count)) {
			expected += inventory.expected_count;
			if (inventory.entries.length > inventory.expected_count) structural.push(`${inventory.kind}: entries exceed expected_count`);
		}
		if (manifest.freeze_status === 'frozen') {
			if (!Number.isInteger(inventory.expected_count)) readiness.push(`${inventory.kind}: expected_count is not frozen`);
			if (!/^[0-9a-f]{64}$/.test(inventory.frozen_digest || '')) readiness.push(`${inventory.kind}: frozen_digest is missing`);
			if (Number.isInteger(inventory.expected_count) && inventory.entries.length !== inventory.expected_count) {
				readiness.push(`${inventory.kind}: expected ${inventory.expected_count} entries, found ${inventory.entries.length}`);
			}
		}
		for (const entry of inventory.entries) {
			classified++;
			const identity = `${inventory.kind}:${entry.id}`;
			if (identities.has(identity)) structural.push(`duplicate descriptor ${identity}`);
			identities.add(identity);
			if (!CLASSES.has(entry.classification)) structural.push(`${identity}: invalid classification`);
			if (entry.oracle_revision !== REVISION) structural.push(`${identity}: wrong oracle revision`);
			if (!entry.showdown_sources.length) structural.push(`${identity}: missing Showdown source`);
			if (!entry.generation_boundaries.length) structural.push(`${identity}: missing generation boundary`);
			for (const ref of [...entry.generation_boundaries, ...entry.native_boundaries]) {
				if (!fs.existsSync(path.join(projectRoot, ref.path))) structural.push(`${identity}: missing project path ${ref.path}`);
			}
			for (const feature of entry.semantic_features) if (!features.has(feature)) structural.push(`${identity}: unknown feature ${feature}`);
			for (const caseID of entry.differential_cases) if (!cases.has(caseID)) structural.push(`${identity}: unknown differential case ${caseID}`);
			for (const artifact of entry.verification_artifacts) {
				if (!fs.existsSync(path.join(projectRoot, artifact.path))) structural.push(`${identity}: missing verification artifact ${artifact.path}`);
			}

			earned.classified++;
			if (entry.showdown_sources.length) earned.source_mapped++;
			if (entry.generation_boundaries.length) earned.generation_mapped++;
			if (entry.classification === 'implemented' || entry.classification === 'inert') {
				if (!entry.native_boundaries.length) readiness.push(`${identity}: ${entry.classification} entry lacks native boundary`);
				if (!entry.semantic_features.length) readiness.push(`${identity}: ${entry.classification} entry lacks semantic feature`);
				if (!entry.focused_tests.length) readiness.push(`${identity}: ${entry.classification} entry lacks focused evidence`);
				if (!entry.differential_cases.length && !entry.verification_artifacts.length) readiness.push(`${identity}: ${entry.classification} entry lacks verification evidence`);
				if (entry.native_boundaries.length) earned.native_or_gap_mapped++;
				if (entry.focused_tests.length) earned.focused_evidence++;
				if (entry.differential_cases.length || entry.verification_artifacts.some(artifact =>
					artifact.kind === 'catalog-differential' || artifact.kind === 'admission-differential')) earned.differential_evidence++;
			} else if (entry.classification === 'unreachable') {
				if (!entry.reachability_evidence.length) readiness.push(`${identity}: unreachable entry lacks reachability proof`);
				if (entry.native_boundaries.length || entry.focused_tests.length || entry.differential_cases.length || entry.verification_artifacts.length || entry.gap_witnesses.length) {
					structural.push(`${identity}: unreachable entry must not claim runtime evidence`);
				}
				if (entry.reachability_evidence.length) earned.native_or_gap_mapped++;
			} else if (entry.classification === 'unsupported') {
				if (!entry.reachability_evidence.length) readiness.push(`${identity}: unsupported entry lacks a reachable-gap witness`);
				if (!entry.gap_witnesses.length) readiness.push(`${identity}: unsupported entry lacks a stable gap witness`);
				if (entry.reachability_evidence.length) earned.native_or_gap_mapped++;
				if (entry.focused_tests.length) earned.focused_evidence++;
				if (entry.differential_cases.length) earned.differential_evidence++;
				readiness.push(`${identity}: reachable descriptor remains unsupported`);
			}
		}
	}

	const weights = manifest.coverage_contract.progress_weights;
	if (Object.values(weights).reduce((sum, value) => sum + value, 0) !== 100) structural.push('progress weights must total 100');
	const gateIDs = new Set();
	for (const gate of manifest.coverage_contract.recombination_gates) {
		if (gateIDs.has(gate.id)) structural.push(`duplicate recombination gate ${gate.id}`);
		gateIDs.add(gate.id);
	}
	const fraction = key => expected ? earned[key] / expected : 0;
	const mappedScore =
		weights.classified * fraction('classified') +
		weights.source_mapped * fraction('source_mapped') +
		weights.generation_mapped * fraction('generation_mapped') +
		weights.native_or_gap_mapped * fraction('native_or_gap_mapped') +
		weights.focused_evidence * fraction('focused_evidence') +
		weights.differential_evidence * fraction('differential_evidence');
	const recombination = 0;
	const score = mappedScore + weights.recombination * recombination;
	if (manifest.freeze_status !== 'frozen') readiness.push('descriptor inventory is not frozen');
	if (!classified) readiness.push('descriptor inventory has no classified entries');

	return {
		schema_valid: !structural.length,
		inventory_ready: !structural.length && !readiness.length,
		completion_ready: false,
		completion_note: 'overall completion additionally requires observed semantic, recombination, determinism, robustness, and performance gates',
		progress: {score, maximum: 100, descriptors_expected: expected, descriptors_classified: classified, earned, recombination},
		structural_failures: structural,
		readiness_failures: readiness,
	};
}

function main(argv) {
	if (argv.length !== 1) throw new Error('usage: node validate.js DESCRIPTOR_MAP.json');
	const projectRoot = path.resolve(__dirname, '../..');
	const manifest = JSON.parse(fs.readFileSync(path.resolve(argv[0]), 'utf8'));
	const result = validate(manifest, projectRoot);
	process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
	return result.schema_valid ? 0 : 1;
}

if (require.main === module) process.exitCode = main(process.argv.slice(2));

module.exports = {validate};
