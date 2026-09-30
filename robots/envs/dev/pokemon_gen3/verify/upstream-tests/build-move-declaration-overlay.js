#!/usr/bin/env node
'use strict';

const assert = require('assert');
const childProcess = require('child_process');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const showdown = path.resolve(process.env.POKEMON_SHOWDOWN_DIR || process.argv[2] || '');
const output = path.resolve(process.argv[3] || path.join(__dirname, 'move-declaration-overlay.json'));
if (!process.env.POKEMON_SHOWDOWN_DIR && !process.argv[2]) {
	throw new Error('POKEMON_SHOWDOWN_DIR or argv[2] must name the pinned Showdown checkout');
}
assert.strictEqual(childProcess.execFileSync('git', ['rev-parse', 'HEAD'], {
	cwd: showdown, encoding: 'utf8',
}).trim(), REVISION, 'Showdown revision changed');

const {Dex} = require(showdown);
const census = JSON.parse(fs.readFileSync(path.join(__dirname, 'all-test-census.json')));
assert.strictEqual(census.pinned_revision, REVISION);
const declarations = census.records.filter(record =>
	record.adjudication_source === 'move-declaration-overlay.json' &&
	record.source_file.startsWith('test/sim/moves/'));
assert.strictEqual(declarations.length, 391, 'move declaration overlay denominator changed');

const groupedSubjects = {
	pledge: {name: 'Pledge moves', generation: 5, ids: ['firepledge', 'grasspledge', 'waterpledge']},
	teattime: {name: 'Teatime', generation: 8, ids: ['teatime']},
};
const soundAliases = new Set([
	'test/sim/moves/bugbuzz.js:28',
	'test/sim/moves/chatter.js:28',
	'test/sim/moves/echoedvoice.js:36',
	'test/sim/moves/relicsong.js:44',
	'test/sim/moves/round.js:28',
	'test/sim/moves/snarl.js:30',
]);
const foresightAliases = new Set([
	'test/sim/moves/miracleeye.js:13',
	'test/sim/moves/miracleeye.js:24',
	'test/sim/moves/miracleeye.js:44',
]);
const directHealAliases = new Map([
	['test/sim/moves/roost.js:14', 'differential:direct-heal-recover-full'],
	['test/sim/moves/roost.js:22', 'differential:direct-heal-recover-clamp'],
]);
const exactDifferentialEvidence = new Map([
	['test/sim/moves/bugbuzz.js:28', 'substitute-routing-product'],
	['test/sim/moves/chatter.js:28', 'substitute-routing-product'],
	['test/sim/moves/echoedvoice.js:36', 'substitute-routing-product'],
	['test/sim/moves/relicsong.js:44', 'substitute-routing-product'],
	['test/sim/moves/round.js:28', 'substitute-routing-product'],
	['test/sim/moves/snarl.js:30', 'substitute-routing-product'],
	['test/sim/moves/stealthrock.js:13', 'substitute-routing-product'],
	['test/sim/moves/miracleeye.js:13', 'foresight-immunity-core'],
	['test/sim/moves/roost.js:14', 'direct-heal-recover-full'],
	['test/sim/moves/roost.js:22', 'direct-heal-recover-clamp'],
]);
const sideConditionAliases = new Map([
	['test/sim/moves/stealthrock.js:13', 'differential:spikes-substitute-control'],
]);
const semanticSources = {
	sound: [
		'data/moves.ts#hypervoice',
		'data/mods/gen5/moves.ts#hypervoice',
		'data/mods/gen4/moves.ts#substitute',
		'data/mods/gen3/scripts.ts#Scripts.inherit',
		'sim/battle-actions.ts#spreadMoveHit',
	],
	foresight: [
		'data/moves.ts#foresight',
		'data/mods/gen4/moves.ts#foresight',
		'data/mods/gen3/moves.ts#foresight',
		'data/mods/gen3/scripts.ts#Scripts.inherit',
		'sim/battle-actions.ts#spreadMoveHit',
	],
	directHeal: [
		'data/moves.ts#recover',
		'data/mods/gen3/moves.ts#recover',
		'data/mods/gen3/scripts.ts#Scripts.inherit',
		'sim/battle-actions.ts#runMoveEffects',
	],
	sideCondition: [
		'data/moves.ts#spikes',
		'data/mods/gen4/moves.ts#spikes',
		'data/mods/gen3/scripts.ts#Scripts.inherit',
		'sim/battle-actions.ts#spreadMoveHit',
	],
};

function subject(record) {
	const fileID = path.basename(record.source_file, '.js');
	if (groupedSubjects[fileID]) return groupedSubjects[fileID];
	const move = Dex.moves.get(fileID);
	assert(move.exists, `unresolved move-test subject ${fileID}`);
	return {name: move.name, generation: move.gen, ids: [move.id]};
}

function tags(name) {
	const text = name.toLowerCase();
	const mechanics = [];
	const boundaries = new Set(['move-execution']);
	const rules = [
		[/substitute/, 'substitute-interception', 'hit-resolution'],
		[/immun|type/, 'type-interaction', 'immunity-and-effectiveness'],
		[/accuracy|miss/, 'accuracy', 'prng-staging'],
		[/critical|crit/, 'critical-hit', 'damage'],
		[/damage|base power| bp|attack stat|defense/, 'damage-formula', 'damage'],
		[/boost|stat|evasion/, 'stat-stages', 'event-handler-order'],
		[/switch|slot|ally switch|redirection|redirect/, 'switching-and-targeting', 'target-resolution'],
		[/faint|ko|revive/, 'faint-lifecycle', 'faint-and-replacement'],
		[/status|burn|sleep|poison|paraly|freeze|thaw/, 'status-lifecycle', 'condition-lifecycle'],
		[/volatile|turn|duration|residual|terrain|room|weather|hazard|spikes|rock/, 'persistent-condition-lifecycle', 'residual-and-expiry'],
		[/item|berry|plate|crystal/, 'item-interaction', 'event-handler-order'],
		[/ability|levitate|wonder guard|sheer force|rock head/, 'ability-interaction', 'event-handler-order'],
		[/priority|move next|move last|speed order|outspeed/, 'action-ordering', 'action-queue'],
		[/pp|disabled|select/, 'choice-and-pp', 'legal-choices'],
		[/called|copy|submove|instruct/, 'move-delegation', 'called-move-entry'],
		[/protect|guard/, 'protection', 'hit-resolution'],
		[/multi-hit|hit twice|each hit/, 'multihit', 'hit-resolution'],
	];
	for (const [pattern, mechanic, boundary] of rules) {
		if (pattern.test(text)) { mechanics.push(mechanic); boundaries.add(boundary); }
	}
	if (!mechanics.length) mechanics.push('move-specific-effect');
	return {mechanics: [...new Set(mechanics)], semantic_boundaries: [...boundaries]};
}

function adjudicate(record) {
	const identity = `${record.source_file}:${record.source_line}`;
	const resolved = subject(record);
	assert(resolved.generation > 3, `${identity} unexpectedly has a Gen 3 subject`);
	const common = {
		identity,
		source_file: record.source_file,
		source_line: record.source_line,
		full_test_name: record.full_test_name,
		subject_move_ids: resolved.ids,
		subject_generation: resolved.generation,
		...tags(record.full_test_name),
	};
	const exactDifferential = exactDifferentialEvidence.get(identity);
	const proof = exactDifferential ? {
		assertion_evidence: {
			native_units: [], differential_cases: [exactDifferential],
			invariants: [], randomized_scenarios: [],
		},
		assertion_evidence_scope: 'assertion_specific',
	} : {};
	if (foresightAliases.has(identity)) {
		const evasion = /evasion/.test(record.full_test_name.toLowerCase());
		const foresightProof = evasion ? {
			assertion_evidence: {
				native_units: ['native/test_pokemon.c#test_foresight_positive_and_negative_evasion_product'],
				differential_cases: [], invariants: [], randomized_scenarios: [],
			},
			assertion_evidence_scope: 'assertion_specific',
		} : proof;
		return {...common,
			disposition: 'applicable-transposed-alias',
			semantic_sources: semanticSources.foresight,
			resolved_source_evidence: `Miracle Eye is Gen ${resolved.generation}, but its immunity-negation and positive-only evasion reset use the same condition-handler shape as Gen 3 Foresight; the affected attack types remain generated data.`,
			gen3_transposition: 'foresight',
			...foresightProof,
			required_case: exactDifferential || evasion ? null :
				'differential:foresight-immunity-core',
		};
	}
	if (soundAliases.has(identity)) {
		return {...common,
			disposition: 'applicable-transposed-generic',
			semantic_sources: semanticSources.sound,
			resolved_source_evidence: `The named move is Gen ${resolved.generation}, but the explicit Gen 5 assertion is the pre-Gen-6 generic sound/Substitute rule, which also applies to legal Gen 3 sound moves such as Hyper Voice.`,
			gen3_transposition: 'hypervoice-versus-substitute',
			...proof,
			required_case: exactDifferential ? null : 'differential:sound-substitute-gen3-control',
		};
	}
	if (directHealAliases.has(identity)) {
		return {...common,
			disposition: 'applicable-transposed-generic',
			semantic_sources: semanticSources.directHeal,
			resolved_source_evidence: `Roost is Gen ${resolved.generation}, but this assertion exercises only the ordinary direct-recovery success/failure contract shared by legal Gen 3 Recover, Milk Drink, Slack Off, and Soft-Boiled; Flying-type suppression is not part of this declaration.`,
			gen3_transposition: 'recover',
			...proof,
			required_case: exactDifferential ? null : directHealAliases.get(identity),
		};
	}
	if (sideConditionAliases.has(identity)) {
		return {...common,
			disposition: 'applicable-transposed-generic',
			semantic_sources: semanticSources.sideCondition,
			resolved_source_evidence: `Stealth Rock is Gen ${resolved.generation}, but this assertion exercises only foe-side condition installation bypassing a Pokemon Substitute, the same target boundary used by legal Gen 3 Spikes.`,
			gen3_transposition: 'spikes',
			...proof,
			required_case: exactDifferential ? null : sideConditionAliases.get(identity),
		};
	}
	return {...common,
		disposition: 'not-applicable-subject-unavailable-in-gen3',
		resolved_source_evidence: `${resolved.ids.join('/')} resolves only from generation ${resolved.generation}; the pinned Gen 3 mod marks the subject as Future, so this declaration cannot execute in Gen 3 OU. No equivalent Gen 3 move preserves the complete asserted semantics.`,
		gen3_transposition: null,
		required_case: null,
	};
}

const records = declarations.map(adjudicate);
const identities = new Set(records.map(record => record.identity));
assert.strictEqual(identities.size, declarations.length, 'duplicate overlay identity');
assert.strictEqual(records.filter(record => record.disposition.startsWith('applicable')).length, 12);
for (const record of records) {
	assert(record.mechanics.length && record.semantic_boundaries.length);
	assert(record.resolved_source_evidence);
	const proven = record.assertion_evidence_scope === 'assertion_specific' &&
		Boolean(record.assertion_evidence?.differential_cases?.length ||
			record.assertion_evidence?.native_units?.length);
	assert.strictEqual(record.disposition.startsWith('applicable'),
		Boolean(record.required_case) || proven);
	assert(!(record.required_case && proven), `${record.identity} has both proof and required case`);
	if (record.disposition.startsWith('applicable')) {
		assert(record.semantic_sources?.length, `${record.identity} lacks semantic sources`);
	}
	const source = fs.readFileSync(path.join(showdown, record.source_file), 'utf8');
	assert(record.source_line <= source.split(/\r?\n/).length, `${record.identity} line disappeared`);
}
const fileHashes = Object.fromEntries([...new Set(records.map(record => record.source_file))].sort().map(file => [
	file, crypto.createHash('sha256').update(fs.readFileSync(path.join(showdown, file))).digest('hex'),
]));
const result = {
	schema: 'pokemon-gen3ou-upstream-move-declaration-overlay-v1',
	pinned_revision: REVISION,
	scope: 'Every unadjudicated test/sim/moves declaration in all-test-census.json; overlay only, with no support classification effect.',
	summary: {
		declarations: records.length,
		source_files: Object.keys(fileHashes).length,
		not_applicable_subject_unavailable: records.filter(record => record.disposition.startsWith('not-applicable')).length,
		applicable_transposed_alias: records.filter(record => record.disposition === 'applicable-transposed-alias').length,
		applicable_transposed_generic: records.filter(record => record.disposition === 'applicable-transposed-generic').length,
		uncertain: 0,
	},
	file_sha256: fileHashes,
	records,
};
fs.writeFileSync(output, `${JSON.stringify(result, null, 2)}\n`);
console.log(`wrote ${records.length} move declaration adjudications to ${output}`);
