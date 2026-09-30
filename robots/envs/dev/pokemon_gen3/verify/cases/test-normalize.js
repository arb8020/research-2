'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const {normalizeCase, normalizeInventory} = require('./normalize');
const {compile, validateSourceFixtures} = require('./compile-c');

const base = {
	schema: 'pokemon-native-differential-case-v1',
	id: 'contract-smoke',
	provenance: {kind: 'showdown-test', source_file: 'test/sim/misc/faint-order.js', test_name: 'Fainting > should end the turn in Gen 3', oracle_revision: '6e71625b9e6cffeda268b548ae7f43a7643fc3f0'},
	format: 'gen3ou', seed: [1, 2, 3, 4],
	teams: [0, 1].map(side => ({source: `p${side + 1}.txt`, normalized: [{species: side ? 'machop' : 'persian', level: 100, gender: null, ability: side ? 'guts' : 'limber', item: '', moves: ['tackle'], stats: [271, 176, 156, 166, 166, 266], status: null}]})),
	source_choices: [['move 1', 'move 1']], choices: [['move 1', 'move 1']], forced_outcomes: [],
	features: ['state.canonical', 'choice.move'], boundaries: ['terminal', 'state', 'request'],
	limits: {max_boundaries: 4, max_actions: 8},
};

const first = JSON.stringify(normalizeCase(base), null, 2);
const second = JSON.stringify(normalizeCase(JSON.parse(JSON.stringify(base))), null, 2);
assert.strictEqual(first, second);
assert.deepStrictEqual(normalizeCase(base).features, ['choice.move', 'state.canonical']);
assert.deepStrictEqual(normalizeCase(base).boundaries, ['request', 'state', 'terminal']);

assert.throws(() => normalizeCase({...base, surprise: true}), /unknown field/);
assert.throws(() => normalizeCase({...base, features: ['mechanic.not-implemented']}), /unsupported feature/);
assert.throws(() => normalizeCase({...base, choices: [['mega 1', 'move 1']]}), /invalid string/);
assert.throws(() => normalizeCase({...base, source_choices: [...base.source_choices, ...base.source_choices]}), /same number of boundaries/);
assert.throws(() => normalizeCase({...base, forced_outcomes: [{label: 'move.accuracy', occurrence: 1, range: 100, result: 100}]}), /less than range/);
const forcedStall = {...base, forced_outcomes: [{label: 'stall.success', occurrence: 1, range: 2, result: 0}]};
assert.deepStrictEqual(normalizeCase(forcedStall).forced_outcomes, forcedStall.forced_outcomes);
const forcedFreeze = {...base, forced_outcomes: [{label: 'status.freeze.before_move', occurrence: 1, range: 5, result: 0}]};
assert.deepStrictEqual(normalizeCase(forcedFreeze).forced_outcomes, forcedFreeze.forced_outcomes);
const forcedDrag = {...base, forced_outcomes: [{label: 'drag.switch_candidate', occurrence: 1, range: 1, result: 0}]};
assert.deepStrictEqual(normalizeCase(forcedDrag).forced_outcomes, forcedDrag.forced_outcomes);
assert.throws(() => normalizeCase({...base, provenance: {...base.provenance, oracle_revision: 'wrong'}}), /must equal/);
assert.throws(() => normalizeCase({...base, limits: {max_boundaries: 1, max_actions: 8}}), /requires 2 stable boundaries/);
assert.throws(() => normalizeCase({...base, limits: {max_boundaries: 4, max_actions: 1}}), /requires 2 submitted actions/);
const invalidGender = JSON.parse(JSON.stringify(base));
invalidGender.teams[0].normalized[0].gender = 'X';
assert.throws(() => normalizeCase(invalidGender), /expected M, F, N, or null/);
const invalidStatus = JSON.parse(JSON.stringify(base));
invalidStatus.teams[0].normalized[0].status = 'bad';
assert.throws(() => normalizeCase(invalidStatus), /expected a Gen 3 major status or null/);
const burned = JSON.parse(JSON.stringify(base));
burned.teams[0].normalized[0].status = 'brn';
assert.strictEqual(normalizeCase(burned).teams[0].normalized[0].status, 'brn');
for (const status of ['frz', 'par', 'psn', 'slp', 'tox']) {
	const statused = JSON.parse(JSON.stringify(base));
	statused.teams[0].normalized[0].status = status;
	if (status === 'slp') {
		statused.teams[0].normalized[0].status_state =
			{kind: 'sleep', time: 2, skipped_time: 0};
	}
	assert.strictEqual(normalizeCase(statused).teams[0].normalized[0].status, status);
}
const reducedHP = JSON.parse(JSON.stringify(base));
reducedHP.teams[0].normalized[0].initial_hp = 7;
assert.strictEqual(normalizeCase(reducedHP).teams[0].normalized[0].initial_hp, 7);
const zeroHP = JSON.parse(JSON.stringify(base));
zeroHP.teams[0].normalized[0].initial_hp = 0;
assert.throws(() => normalizeCase(zeroHP), /initial_hp.*\[1, 271\]/);
const excessHP = JSON.parse(JSON.stringify(base));
excessHP.teams[0].normalized[0].initial_hp = 272;
assert.throws(() => normalizeCase(excessHP), /initial_hp.*\[1, 271\]/);
const duplicate = JSON.parse(JSON.stringify(base));
duplicate.teams[0].normalized.push({...duplicate.teams[0].normalized[0]});
assert.throws(() => normalizeCase(duplicate), /stable set identity/);

const inventory = JSON.parse(fs.readFileSync(path.join(__dirname, 'inventory.json'), 'utf8'));
assert.deepStrictEqual(normalizeInventory(inventory), inventory);
assert.throws(() => normalizeInventory({...inventory, entries: [...inventory.entries, inventory.entries[0]]}), /duplicate source file and test name/);

const ids = {
	data_symbol: 'TEST_DATA', generation_symbol: 'TEST_RULES', format_symbols: {'1': 'TEST_FORMAT'},
	species: {persian: 1, machop: 2}, moves: {tackle: 1}, abilities: {limber: 1, guts: 2}, items: {'': 0},
};
assert.strictEqual(compile(base, ids), compile(JSON.parse(JSON.stringify(base)), ids));
assert.match(compile(base, ids), /\.source_file = "\\x74\\x65\\x73\\x74/);
assert.match(compile(base, ids), /\.gender = POKEMON_GENDER_UNSPECIFIED/);
assert.match(compile(burned, ids), /POKEMON_STATUS_BURN/);
assert.match(compile(reducedHP, ids), /\.initial_hp = \{[\s\S]*\{7, 0, 0, 0, 0, 0\}/);
const explicitIVs = JSON.parse(JSON.stringify(base));
explicitIVs.teams[0].normalized[0].ivs = [31, 30, 29, 28, 27, 26];
assert.deepStrictEqual(normalizeCase(explicitIVs).teams[0].normalized[0].ivs, [31, 30, 29, 28, 27, 26]);
assert.match(compile(explicitIVs, ids), /\.ivs = \{31, 30, 29, 28, 27, 26\}, \.ivs_specified = 1/);
assert.match(compile(base, ids), /\.ivs = \{0, 0, 0, 0, 0, 0\}, \.ivs_specified = 0/);
const invalidIVs = JSON.parse(JSON.stringify(base));
invalidIVs.teams[0].normalized[0].ivs = [31, 31, 31, 31, 31, 32];
assert.throws(() => normalizeCase(invalidIVs), /ivs\[5\].*\[0, 31\]/);
assert.match(compile([base, {...base, id: 'contract-smoke-2'}], ids), /#define VERIFY_CASE_COUNT/);
assert.throws(() => compile([base, {...base, id: 'contract.smoke'}], ids), /collide as C symbol/);
assert.throws(() => compile(base, {...ids, moves: {}}), /no numeric moves ID/);

const weatherCasePath = path.join(__dirname, 'derived/weather-hail-lifecycle.json');
const weatherCase = JSON.parse(fs.readFileSync(weatherCasePath, 'utf8'));
assert.doesNotThrow(() => validateSourceFixtures([weatherCase], [weatherCasePath]));
assert.throws(
	() => validateSourceFixtures([base], [path.join(__dirname, 'missing-case.json')]),
	/missing source fixture.*p1\.txt/
);

const hiddenPowerPaths = fs.readdirSync(path.join(__dirname, 'derived'))
	.filter(filename => /^hidden-power-.*\.json$/.test(filename)).sort()
	.map(filename => path.join(__dirname, 'derived', filename));
assert.strictEqual(hiddenPowerPaths.length, 6);
const hiddenPowerCases = hiddenPowerPaths.map(filename => JSON.parse(fs.readFileSync(filename, 'utf8')));
assert.doesNotThrow(() => validateSourceFixtures(hiddenPowerCases, hiddenPowerPaths));
for (const fixture of hiddenPowerCases) {
	for (const team of normalizeCase(fixture).teams) {
		for (const member of team.normalized) assert.strictEqual(member.ivs.length, 6);
	}
}
const hiddenPowerIDs = JSON.parse(fs.readFileSync(path.join(__dirname, 'native-id-map.json'), 'utf8'));
hiddenPowerIDs.species = {...hiddenPowerIDs.species, umbreon: 1000, dugtrio: 1001, swampert: 1002};
const hiddenPowerC = compile(hiddenPowerCases, hiddenPowerIDs);
assert.strictEqual((hiddenPowerC.match(/\.ivs_specified = 1/g) || []).length, 12);
assert.match(hiddenPowerC, /\.ivs = \{29, 29, 29, 29, 29, 29\}, \.ivs_specified = 1/);
assert.match(hiddenPowerC, /\.ivs = \{30, 30, 30, 31, 31, 30\}, \.ivs_specified = 1/);

process.stdout.write('case normalization contract passed\n');
