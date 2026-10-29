#!/usr/bin/env node
'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');

const fixtureFile = process.env.POKEMON_ADMISSION_CASES_FILE || path.join(__dirname, 'cases.json');
const fixture = JSON.parse(fs.readFileSync(fixtureFile, 'utf8'));
assert.strictEqual(fixture.schema, 'pokemon-gen3ou-admission-cases-v2');
assert.strictEqual(fixture.oracle_revision, '6e71625b9e6cffeda268b548ae7f43a7643fc3f0');

function toID(value) {
	assert.strictEqual(typeof value, 'string');
	return value.toLowerCase().replace(/[^a-z0-9]+/g, '');
}

function cString(value) {
	return JSON.stringify(value).replace(/\\u2028|\\u2029/g, '');
}

const lines = [
	'/* Generated from verify/admission/cases.json; do not edit. */',
	'#ifndef POKEMON_ADMISSION_CASES_H',
	'#define POKEMON_ADMISSION_CASES_H',
	'',
	'typedef struct {',
	'    const char *species_id;',
	'    const char *ability_id;',
	'    const char *item_id;',
	'    const char *move_ids[POKEMON_ADMISSION_MAX_MOVES];',
	'    uint8_t move_count;',
	'    uint8_t level;',
	'    uint8_t has_evs;',
	'    int16_t evs[POKEMON_ADMISSION_STAT_COUNT];',
	'    const char *name;',
	'    PokemonAcquisitionGender gender;',
	'    const char *nature_id;',
	'    uint8_t shiny;',
	'    uint8_t has_ivs;',
	'    uint8_t ivs[POKEMON_ADMISSION_STAT_COUNT];',
	'    const char *hidden_power_type_id;',
	'} PokemonAdmissionCaseMember;',
	'',
	'typedef enum { POKEMON_ADMISSION_CASE_SET, POKEMON_ADMISSION_CASE_TEAM } PokemonAdmissionCaseScope;',
	'typedef enum { POKEMON_ADMISSION_FORMAT_GEN3OU, POKEMON_ADMISSION_FORMAT_GEN3OU_POMEG } PokemonAdmissionCaseFormat;',
	'',
	'typedef struct {',
	'    const char *id;',
	'    PokemonAdmissionCaseScope scope;',
	'    PokemonAdmissionCaseFormat format;',
	'    PokemonAdmissionCaseMember members[POKEMON_ADMISSION_MAX_TEAM_SIZE];',
	'    uint8_t member_count;',
	'    const char *expected_rule;',
	'    uint8_t expected_member_index;',
	'} PokemonAdmissionCase;',
	'',
	'static const PokemonAdmissionCase POKEMON_ADMISSION_CASES[] = {',
];

for (const testCase of fixture.cases) {
	assert(/^[a-z0-9-]+$/.test(testCase.id));
	assert.strictEqual(!!testCase.set + !!testCase.team, 1);
	const members = testCase.set ? [testCase.set] : testCase.team;
	const format = testCase.format ?? fixture.format;
	assert(['gen3ou', 'gen3ou@@@pomegglitchclause'].includes(format));
	const formatToken = format === 'gen3ou' ?
		'POKEMON_ADMISSION_FORMAT_GEN3OU' : 'POKEMON_ADMISSION_FORMAT_GEN3OU_POMEG';
	assert(Array.isArray(members) && members.length > 0 && members.length <= 6);
	const compiledMembers = members.map(member => {
		assert(Array.isArray(member.moves));
		assert(member.moves.length > 0 && member.moves.length <= 4);
		const moves = member.moves.map(move => cString(toID(move)));
		while (moves.length < 4) moves.push('NULL');
		const item = member.item ? cString(toID(member.item)) : 'NULL';
		const level = member.level ?? 100;
		assert(Number.isInteger(level) && level >= 1 && level <= 100);
		const statNames = ['hp', 'atk', 'def', 'spa', 'spd', 'spe'];
		let hasEVs = 1;
		let evs = [1, 0, 0, 0, 0, 0];
		if (member.ev_input) {
			assert(['omitted', 'values'].includes(member.ev_input.kind));
			if (member.ev_input.kind === 'omitted') {
				hasEVs = 0;
				evs = [0, 0, 0, 0, 0, 0];
			} else {
				assert.deepStrictEqual(Object.keys(member.ev_input.values).sort(), [...statNames].sort());
				evs = statNames.map(stat => member.ev_input.values[stat]);
				for (const value of evs) assert(Number.isInteger(value) && value >= -32768 && value <= 32767);
			}
		}
		const name = member.name === undefined ? 'NULL' : cString(member.name);
		const genders = {M: 'POKEMON_ACQUISITION_GENDER_MALE', F: 'POKEMON_ACQUISITION_GENDER_FEMALE', N: 'POKEMON_ACQUISITION_GENDER_NEUTER'};
		const gender = member.gender === undefined ? 'POKEMON_ACQUISITION_GENDER_UNSPECIFIED' : genders[member.gender];
		assert(gender);
		const nature = member.nature === undefined ? 'NULL' : cString(toID(member.nature));
		const shiny = member.shiny === true ? 1 : 0;
		let hasIVs = 0;
		let ivs = [0, 0, 0, 0, 0, 0];
		if (member.ivs) {
			hasIVs = 1;
			assert.deepStrictEqual(Object.keys(member.ivs).sort(), [...statNames].sort());
			ivs = statNames.map(stat => member.ivs[stat]);
			for (const value of ivs) assert(Number.isInteger(value) && value >= 0 && value <= 31);
		}
		const hpType = member.hpType === undefined ? 'NULL' : cString(toID(member.hpType));
		return `{${cString(toID(member.species))}, ${cString(toID(member.ability))}, ` +
			`${item}, {${moves.join(', ')}}, ${member.moves.length}, ${level}, ${hasEVs}, ` +
			`{${evs.join(', ')}}, ${name}, ${gender}, ${nature}, ${shiny}, ${hasIVs}, ` +
			`{${ivs.join(', ')}}, ${hpType}}`;
	});
	while (compiledMembers.length < 6) compiledMembers.push('{0}');
	const rule = testCase.rule === null ? 'NULL' : cString(testCase.rule);
	const memberIndex = testCase.member_index ?? 0;
	assert(Number.isInteger(memberIndex) && memberIndex >= 0 && memberIndex < members.length);
	lines.push(
		`    {${cString(testCase.id)}, POKEMON_ADMISSION_CASE_${testCase.set ? 'SET' : 'TEAM'}, ${formatToken}, ` +
		`{${compiledMembers.join(', ')}}, ${members.length}, ${rule}, ${memberIndex}},`
	);
}

lines.push(
	'};',
	'',
	'#define POKEMON_ADMISSION_CASE_COUNT \\',
	'    (sizeof POKEMON_ADMISSION_CASES / sizeof POKEMON_ADMISSION_CASES[0])',
	'',
	'#endif',
	''
);
process.stdout.write(lines.join('\n'));
