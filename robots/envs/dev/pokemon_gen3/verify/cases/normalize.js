'use strict';

// Strict, dependency-free build-time normalization. It deliberately constructs
// the result in schema order: JSON.stringify(output) is the canonical artifact.

const fs = require('fs');
const path = require('path');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const ROOT = __dirname;
const supported = new Set(JSON.parse(fs.readFileSync(path.join(ROOT, 'features.json'), 'utf8')).features);

function fail(where, message) {
	throw new Error(`${where}: ${message}`);
}

function object(value, where, keys, optional = []) {
	if (!value || typeof value !== 'object' || Array.isArray(value)) fail(where, 'expected object');
	for (const key of Object.keys(value)) if (![...keys, ...optional].includes(key)) fail(where, `unknown field ${JSON.stringify(key)}`);
	for (const key of keys) if (!(key in value)) fail(where, `missing field ${JSON.stringify(key)}`);
	return value;
}

function string(value, where, pattern) {
	if (typeof value !== 'string' || !pattern.test(value)) fail(where, `invalid string ${JSON.stringify(value)}`);
	return value;
}

function integer(value, where, minimum, maximum) {
	if (!Number.isInteger(value) || value < minimum || value > maximum) fail(where, `expected integer in [${minimum}, ${maximum}]`);
	return value;
}

function array(value, where, minimum, maximum) {
	if (!Array.isArray(value) || value.length < minimum || value.length > maximum) fail(where, `expected array length in [${minimum}, ${maximum}]`);
	return value;
}

function uniqueStrings(value, where, allowed) {
	const result = array(value, where, 1, 64).map((entry, index) => string(entry, `${where}[${index}]`, /^[a-z0-9][a-z0-9._-]*$/));
	if (new Set(result).size !== result.length) fail(where, 'duplicate entry');
	if (allowed) for (const entry of result) if (!allowed.has(entry)) fail(where, `unsupported feature ${JSON.stringify(entry)}`);
	return result.slice().sort();
}

function normalizeMember(value, where) {
	object(value, where, ['species', 'level', 'gender', 'ability', 'item', 'moves', 'stats', 'status'], ['initial_hp', 'nature', 'status_state', 'happiness', 'ivs']);
	if (value.gender !== null && !['M', 'F', 'N'].includes(value.gender)) fail(`${where}.gender`, 'expected M, F, N, or null');
	if (value.status !== null && !['brn', 'frz', 'par', 'psn', 'slp', 'tox'].includes(value.status)) {
		fail(`${where}.status`, 'expected a Gen 3 major status or null');
	}
	let statusState;
	if (value.status === 'slp') {
		statusState = object(value.status_state, `${where}.status_state`,
			['kind', 'time', 'skipped_time']);
		if (statusState.kind !== 'sleep') fail(`${where}.status_state.kind`, 'expected sleep');
		statusState = {
			kind: 'sleep',
			time: integer(statusState.time, `${where}.status_state.time`, 1, 5),
			skipped_time: integer(statusState.skipped_time,
				`${where}.status_state.skipped_time`, 0, 5),
		};
	} else if (value.status === 'tox') {
		if (value.status_state === undefined) {
			statusState = {kind: 'toxic', stage: 0};
		} else {
			statusState = object(value.status_state, `${where}.status_state`,
				['kind', 'stage']);
			if (statusState.kind !== 'toxic') fail(`${where}.status_state.kind`, 'expected toxic');
			statusState = {
				kind: 'toxic',
				stage: integer(statusState.stage, `${where}.status_state.stage`, 0, 15),
			};
		}
	} else if (value.status_state !== undefined) {
		fail(`${where}.status_state`, 'allowed only when status is slp or tox');
	}
	const nature = value.nature === undefined ? undefined :
		string(value.nature, `${where}.nature`, /^[a-z]+$/);
	if (nature !== undefined && !['hardy', 'lonely', 'brave', 'adamant', 'naughty', 'bold', 'docile',
		'relaxed', 'impish', 'lax', 'timid', 'hasty', 'serious', 'jolly', 'naive',
		'modest', 'mild', 'quiet', 'bashful', 'rash', 'calm', 'gentle', 'sassy',
		'careful', 'quirky'].includes(nature)) fail(`${where}.nature`, 'expected a Gen 3 nature');
	const stats = array(value.stats, `${where}.stats`, 6, 6).map((stat, index) => integer(stat, `${where}.stats[${index}]`, 1, 999));
	const ivs = value.ivs === undefined ? undefined :
		array(value.ivs, `${where}.ivs`, 6, 6).map((iv, index) => integer(iv, `${where}.ivs[${index}]`, 0, 31));
	const initialHP = value.initial_hp === undefined ? undefined :
		integer(value.initial_hp, `${where}.initial_hp`, 1, stats[0]);
	const happiness = value.happiness === undefined ? undefined :
		integer(value.happiness, `${where}.happiness`, 0, 255);
	return {
		species: string(value.species, `${where}.species`, /^[a-z0-9]+$/),
		level: integer(value.level, `${where}.level`, 1, 100),
		gender: value.gender,
		...(nature === undefined ? {} : {nature}),
		ability: string(value.ability, `${where}.ability`, /^[a-z0-9]*$/),
		item: string(value.item, `${where}.item`, /^[a-z0-9]*$/),
		moves: array(value.moves, `${where}.moves`, 1, 4).map((move, index) => string(move, `${where}.moves[${index}]`, /^[a-z0-9]+$/)),
		stats,
		...(ivs === undefined ? {} : {ivs}),
		status: value.status,
		...(statusState === undefined ? {} : {status_state: statusState}),
		...(initialHP === undefined ? {} : {initial_hp: initialHP}),
		...(happiness === undefined ? {} : {happiness}),
	};
}

function normalizeCase(value) {
	object(value, '$', ['schema', 'id', 'provenance', 'format', 'seed', 'teams', 'source_choices', 'choices', 'forced_outcomes', 'features', 'boundaries', 'limits']);
	if (value.schema !== 'pokemon-native-differential-case-v1') fail('$.schema', 'unsupported schema');
	if (value.format !== 'gen3ou') fail('$.format', 'only gen3ou is supported');
	const provenance = object(value.provenance, '$.provenance', ['kind', 'source_file', 'test_name', 'oracle_revision']);
	if (!['showdown-test', 'showdown-derived', 'differential-regression'].includes(provenance.kind)) fail('$.provenance.kind', 'unsupported kind');
	if (provenance.oracle_revision !== REVISION) fail('$.provenance.oracle_revision', `must equal ${REVISION}`);
	function normalizeChoices(input, where) {
		return array(input, where, 0, 1024).map((turn, turnIndex) =>
		array(turn, `${where}[${turnIndex}]`, 2, 2).map((choice, side) => {
			if (choice === null) return null;
			return string(choice, `${where}[${turnIndex}][${side}]`, /^(move [1-4]|switch [1-6])$/);
		}));
	}
	const sourceChoices = normalizeChoices(value.source_choices, '$.source_choices');
	const choices = normalizeChoices(value.choices, '$.choices');
	if (sourceChoices.length !== choices.length) fail('$.source_choices', 'must have the same number of boundaries as choices');
	const labels = new Set(['team.gender', 'queue.tie', 'move.accuracy', 'move.critical', 'move.damage_roll', 'move.damage_formula', 'move.power_variant', 'move.resolution_variant', 'move.delegation.selection', 'move.type_response.selection', 'move.pp_reduction', 'move.type_selection', 'move.status_selection', 'move.secondary', 'move.multihit_count', 'stall.success', 'turn.quick_claw', 'status.paralysis.before_move', 'status.freeze.before_move', 'condition.confusion.duration', 'condition.confusion.action', 'condition.attract.action', 'condition.lockedmove.duration', 'condition.partiallytrapped.duration', 'condition.disable.duration', 'condition.encore.duration', 'condition.uproar.duration', 'ability.contact_response.activation', 'ability.residual_status_cure', 'ability.trace.target', 'item.starfberry.stat', 'item.focus_band', 'drag.switch_candidate']);
	const outcomes = array(value.forced_outcomes, '$.forced_outcomes', 0, 4096).map((outcome, index) => {
		const where = `$.forced_outcomes[${index}]`;
		object(outcome, where, ['label', 'occurrence', 'range', 'result']);
		if (!labels.has(outcome.label)) fail(`${where}.label`, 'unknown PRNG owner label');
		const range = integer(outcome.range, `${where}.range`, 1, 65536);
		const result = integer(outcome.result, `${where}.result`, 0, 65535);
		if (result >= range) fail(`${where}.result`, 'must be less than range');
		return {label: outcome.label, occurrence: integer(outcome.occurrence, `${where}.occurrence`, 1, 4096), range, result};
	});
	const seenOutcomes = new Set();
	for (const outcome of outcomes) {
		const key = `${outcome.label}:${outcome.occurrence}`;
		if (seenOutcomes.has(key)) fail('$.forced_outcomes', `duplicate ${key}`);
		seenOutcomes.add(key);
	}
	const allowedBoundaries = new Set(['request', 'choice', 'queue', 'handlers', 'immunity', 'state', 'events', 'prng', 'terminal']);
	const boundaries = uniqueStrings(value.boundaries, '$.boundaries');
	for (const boundary of boundaries) if (!allowedBoundaries.has(boundary)) fail('$.boundaries', `unsupported boundary ${JSON.stringify(boundary)}`);
	const limits = object(value.limits, '$.limits', ['max_boundaries', 'max_actions']);
	const normalizedLimits = {
		max_boundaries: integer(limits.max_boundaries, '$.limits.max_boundaries', 1, 1024),
		max_actions: integer(limits.max_actions, '$.limits.max_actions', 0, 4096),
	};
	if (choices.length + 1 > normalizedLimits.max_boundaries) {
		fail('$.limits.max_boundaries', `case requires ${choices.length + 1} stable boundaries`);
	}
	const actionCount = choices.flat().filter(choice => choice !== null).length;
	if (actionCount > normalizedLimits.max_actions) {
		fail('$.limits.max_actions', `case requires ${actionCount} submitted actions`);
	}
	return {
		schema: value.schema,
		id: string(value.id, '$.id', /^[a-z0-9][a-z0-9._-]*$/),
		provenance: {
			kind: provenance.kind,
			source_file: string(provenance.source_file, '$.provenance.source_file', /^(test|verify|sim|data)\/[^\\]+$/),
			test_name: string(provenance.test_name, '$.provenance.test_name', /\S/),
			oracle_revision: provenance.oracle_revision,
		},
		format: value.format,
		seed: array(value.seed, '$.seed', 4, 4).map((part, index) => integer(part, `$.seed[${index}]`, 0, 65535)),
		teams: array(value.teams, '$.teams', 2, 2).map((team, side) => {
			const where = `$.teams[${side}]`;
			object(team, where, ['source', 'normalized']);
			const normalized = array(team.normalized, `${where}.normalized`, 1, 6)
				.map((member, index) => normalizeMember(member, `${where}.normalized[${index}]`));
			const species = normalized.map(member => member.species);
			if (new Set(species).size !== species.length) {
				fail(`${where}.normalized`, 'duplicate species require a stable set identity, which case v1 does not provide');
			}
			return {
				source: string(team.source, `${where}.source`, /^[A-Za-z0-9][A-Za-z0-9._-]*\.txt$/),
				normalized,
			};
		}),
		source_choices: sourceChoices,
		choices,
		forced_outcomes: outcomes,
		features: uniqueStrings(value.features, '$.features', supported),
		boundaries,
		limits: normalizedLimits,
	};
}

function normalizeInventory(value) {
	object(value, '$', ['schema', 'oracle_revision', 'entries']);
	if (value.schema !== 'pokemon-native-test-inventory-v1') fail('$.schema', 'unsupported inventory schema');
	if (value.oracle_revision !== REVISION) fail('$.oracle_revision', `must equal ${REVISION}`);
	const identities = new Set();
	const entries = array(value.entries, '$.entries', 0, 10000).map((entry, index) => {
		const where = `$.entries[${index}]`;
		if (!entry || typeof entry !== 'object' || Array.isArray(entry)) fail(where, 'expected object');
		const common = {
			source_file: string(entry.source_file, `${where}.source_file`, /^test\/[^\\]+$/),
			test_name: string(entry.test_name, `${where}.test_name`, /\S/),
		};
		const identity = `${common.source_file}\n${common.test_name}`;
		if (identities.has(identity)) fail(where, 'duplicate source file and test name');
		identities.add(identity);
		if (entry.disposition === 'accepted') {
			object(entry, where, ['source_file', 'test_name', 'disposition', 'case']);
			return {...common, disposition: 'accepted', case: string(entry.case, `${where}.case`, /^accepted\/[a-z0-9][a-z0-9._-]*\.json$/)};
		}
		if (entry.disposition === 'rejected') {
			object(entry, where, ['source_file', 'test_name', 'disposition', 'reason', 'detail']);
			const reasons = new Set(['generation-mismatch', 'topology-unsupported', 'feature-unsupported', 'observer-boundary-unsupported', 'randomness-control-unrepresentable']);
			if (!reasons.has(entry.reason)) fail(`${where}.reason`, 'unknown rejection reason');
			return {...common, disposition: 'rejected', reason: entry.reason, detail: string(entry.detail, `${where}.detail`, /\S/)};
		}
		fail(`${where}.disposition`, 'must be accepted or rejected');
	});
	return {schema: value.schema, oracle_revision: value.oracle_revision, entries};
}

function main(argv) {
	if (argv.length !== 1) throw new Error('usage: node normalize.js CASE.json');
	const filename = path.resolve(argv[0]);
	const normalized = normalizeCase(JSON.parse(fs.readFileSync(filename, 'utf8')));
	process.stdout.write(`${JSON.stringify(normalized, null, 2)}\n`);
}

if (require.main === module) main(process.argv.slice(2));
module.exports = {normalizeCase, normalizeInventory};
