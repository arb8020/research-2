'use strict';

const SELECTOR_FIELDS = Object.freeze({
	request: ['kind', 'side'],
	choice: ['kind', 'side'],
	queue: ['kind', 'side'],
	event: ['kind'],
	prng: ['label', 'from', 'to'],
	handler: ['event', 'source_kind', 'source_id', 'holder_kind'],
	condition: ['scope', 'id', 'phase'],
	effect: ['phase', 'operation', 'move', 'applied'],
	terminal: ['kind', 'winner'],
});
const DIMENSIONS = new Set([
	'ingredients', 'requests', 'choices', 'queue', 'events', 'prng', 'handlers',
	'conditions', 'effects', 'terminal',
]);
const SELECTOR_DIMENSION = Object.freeze({
	request: 'requests', choice: 'choices', queue: 'queue', event: 'events', prng: 'prng',
	handler: 'handlers', condition: 'conditions', effect: 'effects', terminal: 'terminal',
});

function fail(message) {
	throw new Error(`random coverage: ${message}`);
}

function stable(value) {
	if (Array.isArray(value)) return value.map(stable);
	if (!value || typeof value !== 'object') return value;
	return Object.fromEntries(Object.keys(value).sort().map(key => [key, stable(value[key])]));
}

function observationKey(kind, value) {
	return `${kind}\0${JSON.stringify(stable(value))}`;
}

function add(table, witnessKind, value, caseID, pairing) {
	const key = observationKey(witnessKind, value);
	let item = table.get(key);
	if (!item) {
		item = {witnessKind, value: stable(value), count: 0, cases: new Set(), pairings: new Set()};
		table.set(key, item);
	}
	item.count++;
	item.cases.add(caseID);
	item.pairings.add(pairing);
}

function validateSelector(selector) {
	if (!selector || typeof selector !== 'object' || !SELECTOR_FIELDS[selector.kind]) {
		fail(`unknown witness kind ${JSON.stringify(selector?.kind)}`);
	}
	if (!selector.match || typeof selector.match !== 'object' || Array.isArray(selector.match)) {
		fail('selector.match must be an object');
	}
	for (const field of Object.keys(selector.match)) {
		if (!SELECTOR_FIELDS[selector.kind].includes(field)) {
			fail(`field ${field} is not valid for ${selector.kind}`);
		}
	}
}

function observeCase(table, entry, records) {
	for (const record of records) {
		for (let side = 0; side < record.request.length; side++) {
			add(table, 'request', {kind: record.request[side].kind, side}, entry.id, entry.team_pairing);
		}
		for (let side = 0; side < record.choices.length; side++) {
			add(table, 'choice', {kind: record.choices[side].kind, side}, entry.id, entry.team_pairing);
		}
		for (const value of record.queue) add(table, 'queue', {kind: value.kind, side: value.side}, entry.id, entry.team_pairing);
		for (const value of record.events) add(table, 'event', {kind: value.kind}, entry.id, entry.team_pairing);
		for (const value of record.prng) add(table, 'prng', {
			label: value.label, from: value.from, to: value.to,
		}, entry.id, entry.team_pairing);
		for (const value of record.handlers) add(table, 'handler', {
			event: value.event, source_kind: value.source_kind, source_id: value.source_id,
			holder_kind: value.holder?.kind || 'pokemon',
		}, entry.id, entry.team_pairing);
		for (const value of record.conditions) add(table, 'condition', {
			scope: value.scope, id: value.id, phase: value.phase,
		}, entry.id, entry.team_pairing);
		for (const value of record.effects) add(table, 'effect', {
			phase: value.phase, operation: value.operation, move: value.move, applied: value.applied,
		}, entry.id, entry.team_pairing);
		for (const value of record.events) {
			if (value.kind === 'win' || value.kind === 'tie') add(table, 'terminal', {
				kind: value.kind, winner: value.kind === 'win' ? value.side : null,
			}, entry.id, entry.team_pairing);
		}
	}
}

function ingredientCoverage(fixtures) {
	const values = {species: new Set(), moves: new Set(), abilities: new Set(), items: new Set()};
	for (const fixture of fixtures) for (const team of fixture.teams) for (const pokemon of team.normalized) {
		values.species.add(pokemon.species);
		for (const move of pokemon.moves) values.moves.add(move);
		if (pokemon.ability) values.abilities.add(pokemon.ability);
		if (pokemon.item) values.items.add(pokemon.item);
	}
	return Object.fromEntries(Object.entries(values).map(([key, set]) => [key, [...set].sort()]));
}

function campaignCoverage(manifest, fixtures, records) {
	if (!Array.isArray(manifest.coverage_dimensions) || !manifest.coverage_dimensions.length ||
		!Array.isArray(manifest.coverage_targets)) fail('manifest lacks coverage dimensions or targets');
	const dimensions = [...manifest.coverage_dimensions].sort();
	if (new Set(dimensions).size !== dimensions.length) fail('duplicate coverage dimension');
	for (const dimension of dimensions) if (!DIMENSIONS.has(dimension)) fail(`unknown coverage dimension ${dimension}`);
	const fixtureByID = new Map(fixtures.map(value => [value.id, value]));
	const recordsByID = new Map();
	for (const record of records) {
		if (!recordsByID.has(record.case_id)) recordsByID.set(record.case_id, []);
		recordsByID.get(record.case_id).push(record);
	}
	const table = new Map();
	for (const entry of manifest.cases) {
		if (!fixtureByID.has(entry.id)) fail(`missing fixture ${entry.id}`);
		const caseRecords = recordsByID.get(entry.id);
		if (!caseRecords || caseRecords.length !== entry.expected_boundaries) {
			fail(`${entry.id}: expected ${entry.expected_boundaries} boundaries`);
		}
		caseRecords.forEach((record, index) => {
			if (record.boundary !== index) fail(`${entry.id}: boundaries must be contiguous and start at zero`);
		});
		observeCase(table, entry, caseRecords);
	}
	const observations = [...table.values()].sort((left, right) =>
		observationKey(left.witnessKind, left.value).localeCompare(
			observationKey(right.witnessKind, right.value))).map(item => ({
		witness_kind: item.witnessKind, ...item.value, count: item.count,
		cases: [...item.cases].sort(), team_pairings: [...item.pairings].sort(),
	}));
	const targetIDs = new Set();
	const targets = manifest.coverage_targets.map(target => {
		if (!target || typeof target.id !== 'string' || targetIDs.has(target.id)) fail('invalid or duplicate target ID');
		targetIDs.add(target.id);
		validateSelector(target.selector);
		if (!dimensions.includes(SELECTOR_DIMENSION[target.selector.kind])) {
			fail(`target ${target.id} uses undeclared dimension ${SELECTOR_DIMENSION[target.selector.kind]}`);
		}
		const witnesses = observations.filter(value => value.witness_kind === target.selector.kind &&
			Object.entries(target.selector.match).every(([key, expected]) => Object.is(value[key], expected)));
		const observedCases = [...new Set(witnesses.flatMap(value => value.cases))].sort();
		const observedPairings = [...new Set(witnesses.flatMap(value => value.team_pairings))].sort();
		const minCases = target.min_cases ?? 1;
		const minPairings = target.min_team_pairings ?? 1;
		return {
			id: target.id, selector: stable(target.selector), min_cases: minCases,
			min_team_pairings: minPairings, observed_cases: observedCases,
			observed_team_pairings: observedPairings,
			status: observedCases.length >= minCases && observedPairings.length >= minPairings ? 'met' : 'unmet',
		};
	}).sort((left, right) => left.id.localeCompare(right.id));
	const failures = targets.filter(value => value.status === 'unmet').map(value => `unmet target ${value.id}`);
	return stable({
		dimensions, ingredients_present: ingredientCoverage(fixtures), observations, targets,
		acceptance: {status: failures.length ? 'fail' : 'pass', failures},
	});
}

module.exports = {SELECTOR_FIELDS, campaignCoverage, stable};
