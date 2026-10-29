'use strict';

const fs = require('fs');
const path = require('path');
const {normalizeCase} = require('./normalize');

function lookup(map, family, id, where) {
	if (!map[family] || !Number.isInteger(map[family][id]) || map[family][id] < 0 || map[family][id] > 65535) {
		throw new Error(`${where}: no numeric ${family} ID for ${JSON.stringify(id)}`);
	}
	return map[family][id];
}

function cString(value) {
	return `"${Buffer.from(value, 'utf8').toString('hex').replace(/../g, byte => `\\x${byte}`)}"`;
}

function choice(value) {
	if (value === null) return '{POKEMON_CHOICE_NONE, 0}';
	const match = /^(move|switch) ([1-6])$/.exec(value);
	const kind = match[1] === 'move' ? 'POKEMON_CHOICE_MOVE' : 'POKEMON_CHOICE_SWITCH';
	return `{${kind}, ${Number(match[2]) - 1}}`;
}

function gender(value) {
	return value === null ? 'POKEMON_GENDER_UNSPECIFIED' : {
		M: 'POKEMON_GENDER_MALE', F: 'POKEMON_GENDER_FEMALE', N: 'POKEMON_GENDER_NONE',
	}[value];
}

function nature(value) {
	return `POKEMON_NATURE_${value.toUpperCase()}`;
}

function status(value) {
	return value === null ? 'POKEMON_STATUS_NONE' : {
		brn: 'POKEMON_STATUS_BURN', tox: 'POKEMON_STATUS_TOXIC',
		par: 'POKEMON_STATUS_PARALYSIS', psn: 'POKEMON_STATUS_POISON',
		slp: 'POKEMON_STATUS_SLEEP', frz: 'POKEMON_STATUS_FREEZE',
	}[value];
}

function compile(values, map) {
	if (!Array.isArray(values)) values = [values];
	const fixtures = values.map(normalizeCase);
	if (!fixtures.length) throw new Error('at least one case is required');
	for (const key of ['data_symbol', 'generation_symbol']) {
		if (typeof map[key] !== 'string' || !/^[A-Z][A-Z0-9_]*$/.test(map[key])) throw new Error(`ID map: invalid ${key}`);
	}
	if (!map.format_symbols || typeof map.format_symbols !== 'object' || Array.isArray(map.format_symbols)) {
		throw new Error('ID map: invalid format_symbols');
	}
	const symbols = new Set();
	const lines = ['#pragma once', '', '#include "verify_case.h"', ''];
	for (const fixture of fixtures) {
		const teamSize = Math.max(...fixture.teams.map(team => team.normalized.length));
		const formatSymbol = map.format_symbols[String(teamSize)];
		if (typeof formatSymbol !== 'string' || !/^[A-Z][A-Z0-9_]*$/.test(formatSymbol)) {
			throw new Error(`case ${fixture.id}: no format symbol for team size ${teamSize}`);
		}
		const symbol = fixture.id.toUpperCase().replace(/[^A-Z0-9]/g, '_');
		if (symbols.has(symbol)) throw new Error(`case IDs collide as C symbol ${symbol}`);
		symbols.add(symbol);
		if (fixture.choices.length) {
			lines.push(`static const PokemonChoice VERIFY_CHOICES_${symbol}[][POKEMON_SIDES] = {`);
			for (const turn of fixture.choices) lines.push(`    {${choice(turn[0])}, ${choice(turn[1])}},`);
			lines.push('};', '');
		}
	}
	lines.push('static const VerifyCase VERIFY_CASES[] = {');
	for (const fixture of fixtures) {
		const teamSizes = fixture.teams.map(team => team.normalized.length);
		const symbol = fixture.id.toUpperCase().replace(/[^A-Z0-9]/g, '_');
		lines.push('  {', `    .id = ${cString(fixture.id)},`,
		`    .source_file = ${cString(fixture.provenance.source_file)},`, `    .test_name = ${cString(fixture.provenance.test_name)},`,
		'    .init = {', '        .bundle = &POKEMON_GEN3_OU_BUNDLE,',
		`        .team_sizes = {${teamSizes.join(', ')}},`, '        .teams = {');
		for (let side = 0; side < fixture.teams.length; side++) {
			lines.push('            {.members = {');
			for (let slot = 0; slot < fixture.teams[side].normalized.length; slot++) {
				const member = fixture.teams[side].normalized[slot];
				const species = lookup(map, 'species', member.species, `case ${fixture.id} team ${side + 1} slot ${slot + 1}`);
				const ability = lookup(map, 'abilities', member.ability, `case ${fixture.id} team ${side + 1} slot ${slot + 1}`);
				const item = lookup(map, 'items', member.item, `case ${fixture.id} team ${side + 1} slot ${slot + 1}`);
				const moves = member.moves.map((move, index) => lookup(map, 'moves', move, `case ${fixture.id} team ${side + 1} slot ${slot + 1} move ${index + 1}`));
				while (moves.length < 4) moves.push(0);
				lines.push(`                {.species_id = ${species}, .ability_id = ${ability}, .item_id = ${item},`,
					`                 .move_ids = {${moves.join(', ')}}, .stats = {${member.stats.join(', ')}}, .ivs = {${(member.ivs || [0, 0, 0, 0, 0, 0]).join(', ')}}, .ivs_specified = ${member.ivs === undefined ? 0 : 1}, .level = ${member.level}, .gender = ${gender(member.gender)}, .nature = ${nature(member.nature || 'hardy')}, .happiness = ${member.happiness || 0}, .happiness_specified = ${member.happiness === undefined ? 0 : 1}},`);
			}
			lines.push('            }},');
		}
		lines.push('        },', `        .seed = {${fixture.seed.join(', ')}},`, '        .initial_status = {');
		for (const team of fixture.teams) {
			const statuses = team.normalized.map(member => status(member.status));
			while (statuses.length < 6) statuses.push('POKEMON_STATUS_NONE');
			lines.push(`            {${statuses.join(', ')}},`);
		}
		lines.push('        },', '        .initial_sleep_time = {');
		for (const team of fixture.teams) {
			const times = team.normalized.map(member => member.status_state?.time || 0);
			while (times.length < 6) times.push(0);
			lines.push(`            {${times.join(', ')}},`);
		}
		lines.push('        },', '        .initial_sleep_skipped_time = {');
		for (const team of fixture.teams) {
			const skipped = team.normalized.map(member => member.status_state?.skipped_time || 0);
			while (skipped.length < 6) skipped.push(0);
			lines.push(`            {${skipped.join(', ')}},`);
		}
		lines.push('        },', '        .initial_toxic_stage = {');
		for (const team of fixture.teams) {
			const stages = team.normalized.map(member => member.status_state?.kind === 'toxic' ? member.status_state.stage : 0);
			while (stages.length < 6) stages.push(0);
			lines.push(`            {${stages.join(', ')}},`);
		}
		lines.push('        },', '        .initial_hp = {');
		for (const team of fixture.teams) {
			const hp = team.normalized.map(member => member.initial_hp || 0);
			while (hp.length < 6) hp.push(0);
			lines.push(`            {${hp.join(', ')}},`);
		}
		lines.push('        },', '    },', fixture.choices.length ?
			`    .choices = VERIFY_CHOICES_${symbol},` : '    .choices = NULL,',
			fixture.choices.length ?
				`    .choice_count = sizeof(VERIFY_CHOICES_${symbol}) / sizeof(VERIFY_CHOICES_${symbol}[0]),` :
				'    .choice_count = 0,', '  },');
	}
	lines.push('};', '', '#define VERIFY_CASE_COUNT (sizeof(VERIFY_CASES) / sizeof(VERIFY_CASES[0]))', '');
	return lines.join('\n');
}

function validateSourceFixtures(values, filenames) {
	if (!Array.isArray(values)) values = [values];
	if (!Array.isArray(filenames) || filenames.length !== values.length) {
		throw new Error('source validation requires one filename per case');
	}
	for (let index = 0; index < values.length; index++) {
		const fixture = normalizeCase(values[index]);
		const caseDirectory = path.dirname(path.resolve(filenames[index]));
		for (let side = 0; side < fixture.teams.length; side++) {
			const source = path.resolve(caseDirectory, fixture.teams[side].source);
			if (!fs.existsSync(source) || !fs.statSync(source).isFile()) {
				throw new Error(`case ${fixture.id} team ${side + 1}: missing source fixture ${source}`);
			}
		}
	}
}

if (require.main === module) {
	if (process.argv.length < 4) throw new Error('usage: node compile-c.js CASE.json [CASE.json ...] ID_MAP.json');
	const filenames = process.argv.slice(2, -1);
	const fixtures = filenames.map(filename =>
		JSON.parse(fs.readFileSync(path.resolve(filename), 'utf8')));
	validateSourceFixtures(fixtures, filenames);
	const map = JSON.parse(fs.readFileSync(path.resolve(process.argv.at(-1)), 'utf8'));
	process.stdout.write(compile(fixtures, map));
}

module.exports = {compile, validateSourceFixtures};
