'use strict';

const childProcess = require('child_process');
const fs = require('fs');
const path = require('path');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const showdown = path.resolve(process.argv[2] || '');
const output = path.resolve(process.argv[3] || path.join(__dirname, 'gen3ou-runtime-regression-map.json'));
if (!process.argv[2]) throw new Error('usage: node build-runtime-regression-map.js SHOWDOWN_DIR [OUTPUT]');

const revision = childProcess.execFileSync('git', ['rev-parse', 'HEAD'], {cwd: showdown, encoding: 'utf8'}).trim();
if (revision !== REVISION) throw new Error(`oracle revision ${revision}; expected ${REVISION}`);

const read = file => JSON.parse(fs.readFileSync(path.join(__dirname, file), 'utf8'));
const staticCensus = read('all-test-census.json');
const staticMap = read('gen3ou-unified-regression-map.json');
const projectRoot = path.resolve(__dirname, '../..');
const admissionCaseIds = new Set(JSON.parse(fs.readFileSync(
	path.join(projectRoot, 'verify/admission/cases.json'), 'utf8')).cases.map(value => value.id));
const mocha = path.join(showdown, 'node_modules/.bin/mocha');
const args = ['--no-config', '--dry-run', '--reporter', 'json', 'test/sim/**/*.js'];
const run = childProcess.spawnSync(mocha, args, {cwd: showdown, encoding: 'utf8', maxBuffer: 20e6});
if (run.status !== 0) throw new Error(`Mocha registration failed: ${run.stderr}`);
const report = JSON.parse(run.stdout);
const pendingRemaining = new Map();
for (const test of report.pending) {
	const key = `${path.relative(showdown, test.file)}\n${test.fullTitle}`;
	pendingRemaining.set(key, (pendingRemaining.get(key) || 0) + 1);
}

const canonicalByParent = new Map(staticMap.records.map(record => [
	`${record.source.file}:${record.source.line}`, record,
]));
const declarationsByFile = new Map();
for (const declaration of staticCensus.records) {
	const rows = declarationsByFile.get(declaration.source_file) || [];
	rows.push(declaration);
	declarationsByFile.set(declaration.source_file, rows);
}

const parameterValues = new Map();
function parameters(file, lines, values, name) {
	for (const line of lines) parameterValues.set(`${file}:${line}`, {name, values});
}
parameters('test/sim/data.js', [388], ['gen1', 'gen2', 'gen3', 'gen4', 'gen5', 'gen6', 'gen7', 'gen8', 'gen9'], 'generation');
parameters('test/sim/data.js', [411], ['gen7letsgo', 'gen8bdsp', 'gen8legends', 'gen9legends'], 'mod');
parameters('test/sim/decisions.js', [756, 773, 787, 806, 822, 855, 877, 912, 946, 982, 1020, 1044, 1069, 1098, 1126, 1150, 1176, 1207], ['revoke', 'override'], 'mode');
parameters('test/sim/items/drives.js', [19, 37, 45, 53], ['burndrive', 'chilldrive', 'dousedrive', 'shockdrive'], 'item');
parameters('test/sim/items/plates.js', [22, 40, 48, 56], [
	'dracoplate', 'dreadplate', 'earthplate', 'fistplate', 'flameplate', 'icicleplate',
	'insectplate', 'ironplate', 'meadowplate', 'mindplate', 'pixieplate', 'skyplate',
	'splashplate', 'spookyplate', 'stoneplate', 'toxicplate', 'zapplate',
], 'item');
parameters('test/sim/misc/ateabilities.js', [16, 26], ['refrigerate', 'pixilate', 'aerilate', 'galvanize'], 'ability');
parameters('test/sim/misc/trapmoves.js', [16, 28, 40, 52, 67], ['block', 'meanlook', 'spiderweb', 'thousandwaves', 'anchorshot', 'spiritshackle'], 'move');
parameters('test/sim/misc/trapmoves.js', [92], ['block', 'meanlook', 'spiderweb'], 'move');
parameters('test/sim/misc/trapmoves.js', [120, 131, 143, 155, 167, 182], ['bind', 'clamp', 'firespin', 'infestation', 'magmastorm', 'sandtomb', 'whirlpool', 'wrap'], 'move');
parameters('test/sim/misc/typechange.js', [20, 28, 36, 46, 56], ['trickortreat', 'forestscurse'], 'move');
parameters('test/sim/moves/curse.js', [229], ['position0', 'position1', 'position2'], 'position');
parameters('test/sim/moves/rollout.js', [18, 42, 72, 100, 117, 134, 154, 172, 187], ['iceball', 'rollout'], 'move');

function escapeRegex(value) {
	return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function declarationPattern(fullName) {
	const dynamicSegments = new Set(['drive', 'plate', 'moveData.name', 'move', 'ate']);
	let value = fullName.split(' > ').map(segment => dynamicSegments.has(segment) ? '__DYNAMIC__' : segment).join(' ').replace(/`/g, '');
	value = escapeRegex(value).replace(/__DYNAMIC__/g, '.+?');
	value = value.replace(/\\\$\\\{[^}]+\\\}/g, '.+?');
	return new RegExp(`^${value}$`);
}

function dynamicTypeChangeParent(title, declarations) {
	let line;
	if (title.includes(' should add ')) line = 20;
	else if (title.includes(' should not add ')) line = 28;
	else if (title.includes(' should be able to add ')) line = 36;
	else if (title.endsWith(' should fail on repeated use')) line = 46;
	else if (title.includes(' should override ')) line = 56;
	return declarations.find(record => record.source_line === line);
}

const parentResolutionOccurrence = new Map();
function resolveParent(file, fullTitle) {
	const declarations = declarationsByFile.get(file) || [];
	const exact = declarations.filter(record => record.full_test_name.replace(/ > /g, ' ') === fullTitle);
	if (exact.length === 1) return exact[0];
	if (exact.length > 1) {
		const key = `${file}\n${fullTitle}`;
		const occurrence = parentResolutionOccurrence.get(key) || 0;
		parentResolutionOccurrence.set(key, occurrence + 1);
		if (occurrence < exact.length) return exact[occurrence];
	}
	if (file === 'test/sim/data.js' && /^Dex data Gen \d/.test(fullTitle)) {
		return declarations.find(record => record.source_line === 388);
	}
	if (file === 'test/sim/data.js' && /^Dex data gen\d/.test(fullTitle)) {
		return declarations.find(record => record.source_line === 411);
	}
	if (file === 'test/sim/moves/curse.js' && /opponent in Triples even if the user is on position \d$/.test(fullTitle)) {
		return declarations.find(record => record.source_line === 229);
	}
	const patterned = declarations.filter(record => declarationPattern(record.full_test_name).test(fullTitle));
	if (patterned.length === 1) return patterned[0];
	if (file === 'test/sim/misc/typechange.js') {
		const parent = dynamicTypeChangeParent(fullTitle, declarations);
		if (parent) return parent;
	}
	throw new Error(`cannot uniquely resolve runtime test ${file}: ${fullTitle} (${patterned.length} candidates)`);
}

function differentialReference(id) {
	if (id.endsWith('.json') && fs.existsSync(path.join(projectRoot, id))) {
		return {kind: 'differential_case', path: id, selector: id};
	}
	const candidates = [
		`verify/cases/accepted/${id}.json`,
		`verify/cases/derived/${id}.json`,
		`verify/cases/derived/${id.replace(/^derived-/, '')}.json`,
	];
	const found = candidates.find(candidate => fs.existsSync(path.join(projectRoot, candidate)));
	if (found) return {kind: 'differential_case', path: found, selector: id};
	if (admissionCaseIds.has(id)) {
		return {kind: 'admission_case', path: 'verify/admission/cases.json', selector: id};
	}
	throw new Error(`cannot resolve differential evidence ${id}`);
}

function structuredEvidence(evidence) {
	return [
		...evidence.native_units.map(reference => {
			const [file, symbol] = reference.includes('#') ? reference.split('#') : ['native/test_pokemon.c', reference];
			const target = path.join(projectRoot, file);
			if (!fs.existsSync(target) || !fs.readFileSync(target, 'utf8').includes(symbol)) return null;
			return {kind: 'native_unit', path: file, selector: symbol};
		}),
		...evidence.differential_cases.map(reference => {
			if (reference.includes('.c#')) {
				const [file, symbol] = reference.split('#');
				return {kind: 'native_unit', path: file, selector: symbol};
			}
			return differentialReference(reference);
		}),
		...evidence.invariants.map(reference => ({kind: 'invariant', path: null, selector: reference})),
		...evidence.randomized_scenarios.map(reference => ({kind: 'randomized_scenario', path: null, selector: reference})),
	].filter(Boolean);
}

function gapId(parentId, expansion) {
	const base = `upstream-runtime-${parentId}`.replace(/[^a-z0-9]+/gi, '-').replace(/^-|-$/g, '').toLowerCase();
	return expansion ? `${base}-${expansion.value}` : base;
}

const occurrenceByParent = new Map();
const titleOccurrence = new Map();
const records = report.tests.map(test => {
	const file = path.relative(showdown, test.file);
	const parent = resolveParent(file, test.fullTitle);
	const parentId = `${file}:${parent.source_line}`;
	const canonical = canonicalByParent.get(parentId);
	if (!canonical) throw new Error(`missing canonical disposition for ${parentId}`);
	if (canonical.applicable && !canonical.semantic_sources.length) {
		throw new Error(`${parentId} lacks semantic sources`);
	}
	const occurrence = occurrenceByParent.get(parentId) || 0;
	occurrenceByParent.set(parentId, occurrence + 1);
	const definition = parameterValues.get(parentId);
	let expansion = null;
	if (definition) {
		if (occurrence >= definition.values.length) throw new Error(`too many expansions for ${parentId}`);
		expansion = {parameter: definition.name, value: definition.values[occurrence], index: occurrence};
	}
	const titleKey = `${file}\n${test.fullTitle}`;
	const runtimeOrdinal = titleOccurrence.get(titleKey) || 0;
	titleOccurrence.set(titleKey, runtimeOrdinal + 1);
	const evidence = structuredEvidence(canonical.evidence);
	const proven = canonical.evidence_scope === 'assertion_specific' && evidence.length > 0;
	const unavailableExpansion = expansion && (
		(file === 'test/sim/misc/trapmoves.js' && ['thousandwaves', 'anchorshot', 'spiritshackle', 'infestation', 'magmastorm'].includes(expansion.value))
	);
	const applicable = unavailableExpansion ? false : canonical.applicable;
	const disposition = unavailableExpansion ? 'mechanic_unreachable_gen3' : canonical.disposition;
	const applicabilityEvidence = unavailableExpansion ?
		`${expansion.value} did not exist in Gen 3; the parameterized modern test instance is not a Gen 3 OU runtime scenario.` :
		canonical.applicability_evidence;
	let requiredCase = canonical.required_case;
	if (requiredCase && expansion) requiredCase = `${requiredCase}-${expansion.value}`;
	if (applicable && !proven && !requiredCase) requiredCase = gapId(parentId, expansion);
	const pendingKey = `${file}\n${test.fullTitle}`;
	const isPending = (pendingRemaining.get(pendingKey) || 0) > 0;
	if (isPending) pendingRemaining.set(pendingKey, pendingRemaining.get(pendingKey) - 1);
	return {
		revision: REVISION,
		runtime_id: `${file}:${parent.source_line}:${runtimeOrdinal}:${expansion?.value || 'singleton'}`,
		source: {file, line: parent.source_line, full_test_name: test.fullTitle},
		parent_declaration_id: parentId,
		execution_status: isPending ? 'pending' : 'active',
		expansion,
		applicability: {
			disposition,
			applicable,
			evidence: applicabilityEvidence,
			semantic_sources: canonical.semantic_sources,
		},
		mechanics: canonical.mechanics,
		boundaries: canonical.boundaries,
		evidence,
		evidence_scope: proven ? 'assertion_specific' : (evidence.length ? 'candidate_only' : 'none'),
		required_case: applicable && !proven ? requiredCase : null,
		terminal_reason: applicable ? null : (unavailableExpansion ? applicabilityEvidence : canonical.terminal_reason),
	};
});

for (const [parentId, definition] of parameterValues) {
	if (occurrenceByParent.get(parentId) !== definition.values.length) {
		throw new Error(`${parentId} registered ${occurrenceByParent.get(parentId) || 0}; expected ${definition.values.length}`);
	}
}

const value = {
	schema: 'pokemon-gen3ou-runtime-regression-map-v1',
	pinned_revision: REVISION,
	runner: {binary: 'node_modules/.bin/mocha', args},
	scope: 'One record per Mocha-registered test instance below pinned test/sim, including every parameterized expansion.',
	summary: {
		registered: records.length,
		active: records.filter(record => record.execution_status === 'active').length,
		pending: records.filter(record => record.execution_status === 'pending').length,
		static_declarations: staticCensus.records.length,
		dynamic_expansions: records.length - staticCensus.records.length,
		applicable: records.filter(record => record.applicability.applicable).length,
		assertion_specific: records.filter(record => record.evidence_scope === 'assertion_specific').length,
		requiring_case: records.filter(record => record.required_case).length,
	},
	records,
};
fs.writeFileSync(output, `${JSON.stringify(value, null, 2)}\n`);
console.log(JSON.stringify(value.summary));
