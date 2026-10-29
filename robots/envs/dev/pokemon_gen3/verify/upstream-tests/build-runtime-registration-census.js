'use strict';

const childProcess = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const oracle = path.resolve(process.argv[2] || '');
const output = path.resolve(process.argv[3] || path.join(__dirname, 'runtime-registration-census.json'));
if (!process.argv[2]) throw new Error('usage: node build-runtime-registration-census.js SHOWDOWN_DIR [OUTPUT]');
const revision = childProcess.execFileSync('git', ['rev-parse', 'HEAD'], {cwd: oracle, encoding: 'utf8'}).trim();
if (revision !== REVISION) throw new Error(`oracle revision ${revision}; expected ${REVISION}`);

const census = JSON.parse(fs.readFileSync(path.join(__dirname, 'all-test-census.json'), 'utf8'));
const mocha = path.join(oracle, 'node_modules/.bin/mocha');
const args = ['--no-config', '--dry-run', '--reporter', 'json', 'test/sim/**/*.js'];
const run = childProcess.spawnSync(mocha, args, {cwd: oracle, encoding: 'utf8', maxBuffer: 20e6});
if (run.status !== 0) throw new Error(`Mocha registration failed: ${run.stderr}`);
const report = JSON.parse(run.stdout);

function countsByFile(rows, fileOf) {
	const counts = new Map();
	for (const row of rows) {
		const file = fileOf(row);
		counts.set(file, (counts.get(file) || 0) + 1);
	}
	return counts;
}
const runtimeCounts = countsByFile(report.tests, test => path.relative(oracle, test.file));
const staticCounts = countsByFile(census.records, record => record.source_file);
const dynamicFiles = [...runtimeCounts].flatMap(([file, runtime]) => {
	const declarations = staticCounts.get(file) || 0;
	return runtime === declarations ? [] : [{file, declarations, runtime, expansion: runtime - declarations}];
}).sort((a, b) => a.file.localeCompare(b.file));

const families = [
	{
		file: 'test/sim/moves/rollout.js', parameter: 'move', values: ['iceball', 'rollout'],
		assertions: [
			[18, 'five-turn-base-power-progression-reset'],
			[42, 'miss-resets-progression'],
			[72, 'immobilization-resets-progression'],
			[100, 'defense-curl-doubles-base-power'],
		],
	},
	{
		file: 'test/sim/misc/trapmoves.js', parameter: 'move', values: ['block', 'meanlook', 'spiderweb'],
		assertions: [[16, 'prevents-normal-switch'], [28, 'permits-baton-pass-switch'], [52, 'source-no-longer-active-removes-trap']],
	},
	{
		file: 'test/sim/misc/trapmoves.js', parameter: 'move', values: ['bind', 'clamp', 'firespin', 'sandtomb', 'whirlpool', 'wrap'],
		assertions: [[131, 'prevents-normal-switch'], [143, 'permits-baton-pass-switch'], [167, 'source-no-longer-active-removes-trap'], [182, 'rapid-spin-removes-trap']],
	},
];

const sourceTrapCases = {
	block: 'source-trap-block-release',
	meanlook: 'source-trap-mean-look-rotation',
	spiderweb: 'source-trap-spider-web-rotation',
};
const partialTrapCases = {
	bind: 'partial-trap-bind-source-switch',
	clamp: 'partial-trap-clamp-rotation',
	firespin: 'partial-trap-fire-spin-rotation',
	sandtomb: 'partial-trap-sand-tomb-rotation',
	whirlpool: 'partial-trap-whirlpool-rotation',
	wrap: 'partial-trap-wrap-rotation',
};
const batonPassTrapCases = {
	block: 'baton-pass-trap-block',
	meanlook: 'baton-pass-trap-meanlook',
	spiderweb: 'baton-pass-trap-spiderweb',
	bind: 'baton-pass-trap-bind',
	clamp: 'baton-pass-trap-clamp',
	firespin: 'baton-pass-trap-firespin',
	sandtomb: 'baton-pass-trap-sandtomb',
	whirlpool: 'baton-pass-trap-whirlpool',
	wrap: 'baton-pass-trap-wrap',
};

function rolloutEvidence(entity, line) {
	const prefix = entity === 'iceball' ? 'ice-ball' : 'rollout';
	const fixture = line === 18 || line === 100 ?
		`${prefix}-defense-curl-cycle` : `${prefix}-miss-immobilize-reset`;
	return {
		native_units: [
			'native/test_pokemon.c#test_locked_ramp_rollout_ice_ball_and_defense_curl',
		],
		differential_cases: [fixture],
		descriptor_equivalence: null,
	};
}

function trappingEvidence(entity, line) {
	if ((line === 28 || line === 143) && batonPassTrapCases[entity]) {
		return {
			native_units: [
				'native/test_pokemon.c#test_move_driven_switch_retains_queue_and_transfers_state',
			],
			differential_cases: [batonPassTrapCases[entity]],
			descriptor_equivalence: null,
		};
	}
	if (sourceTrapCases[entity]) {
		const differentialCases = [sourceTrapCases[entity]];
		let descriptorEquivalence = null;
		if (line === 52 && entity !== 'block') {
			differentialCases.push('source-trap-block-release');
			descriptorEquivalence =
				'All three descriptors bind the same generated add-source-linked-trap program; the entity case proves its binding and Block proves source-departure cleanup.';
		}
		return {
			native_units: ['native/test_pokemon.c#test_source_linked_trap_family'],
			differential_cases: differentialCases,
			descriptor_equivalence: descriptorEquivalence,
		};
	}
	if (partialTrapCases[entity]) {
		const differentialCases = [partialTrapCases[entity]];
		let descriptorEquivalence = null;
		if (line === 182) {
			differentialCases.push('partial-trap-rapid-spin-cleanup');
			descriptorEquivalence =
				'Every descriptor installs the same partiallytrapped condition; Rapid Spin removes that condition independently of the source move identity.';
		}
		return {
			native_units: ['native/test_pokemon.c#test_partial_trap_condition_programs'],
			differential_cases: differentialCases,
			descriptor_equivalence: descriptorEquivalence,
		};
	}
	return null;
}
const rolloutSource = fs.readFileSync(path.join(oracle, 'test/sim/moves/rollout.js'), 'utf8');
const trappingSource = fs.readFileSync(path.join(oracle, 'test/sim/misc/trapmoves.js'), 'utf8');
assert.match(rolloutSource, /const moves = \['Ice Ball', 'Rollout'\];/);
assert.match(trappingSource, /const trappers = \['Block', 'Mean Look', 'Spider Web', 'Thousand Waves', 'Anchor Shot', 'Spirit Shackle'\];/);
assert.match(trappingSource, /const partialtrappers = \['Bind', 'Clamp', 'Fire Spin', 'Infestation', 'Magma Storm', 'Sand Tomb', 'Whirlpool', 'Wrap'\];/);
const declarationByKey = new Map(census.records.map(record => [`${record.source_file}:${record.source_line}`, record]));
const applicableVariants = families.flatMap(family => family.assertions.map(([line, assertion]) => ({
	source: {
		file: family.file,
		line,
		full_test_name: declarationByKey.get(`${family.file}:${line}`)?.full_test_name,
	},
	execution_status: 'active',
	loop_parameter: {name: family.parameter, literal_values: family.values},
	variants: family.values.map(entity => {
		const mappedEvidence = family.file === 'test/sim/moves/rollout.js' ?
			rolloutEvidence(entity, line) : trappingEvidence(entity, line);
		return {
			key: `${entity}:${line}`,
			entity,
			assertion,
			evidence: mappedEvidence ||
				{native_units: [], differential_cases: [], descriptor_equivalence: null},
			required_case: mappedEvidence ? null : `upstream-${entity}-${line}`,
		};
	}),
})));
for (const record of applicableVariants) {
	if (!record.source.full_test_name) throw new Error(`missing static declaration ${record.source.file}:${record.source.line}`);
}

const value = {
	schema: 'pokemon-showdown-runtime-registration-census-v1',
	pinned_revision: REVISION,
	runner: {binary: 'node_modules/.bin/mocha', args},
	summary: {
		registered: report.tests.length,
		active: report.tests.length - report.pending.length,
		pending: report.pending.length,
		static_declarations: census.records.length,
		dynamic_expansions: report.tests.length - census.records.length,
		gen3ou_applicable_dynamic_variants: applicableVariants.reduce(
			(total, declaration) => total + declaration.variants.length, 0),
		gen3ou_applicable_dynamic_variants_proven: applicableVariants.reduce(
			(total, declaration) => total + declaration.variants.filter(variant =>
				variant.evidence.native_units.length ||
				variant.evidence.differential_cases.length ||
				variant.evidence.descriptor_equivalence).length, 0),
	},
	dynamic_files: dynamicFiles,
	gen3ou_applicable_dynamic_declarations: applicableVariants,
};
fs.writeFileSync(output, `${JSON.stringify(value, null, 2)}\n`);
console.log(JSON.stringify(value.summary));
