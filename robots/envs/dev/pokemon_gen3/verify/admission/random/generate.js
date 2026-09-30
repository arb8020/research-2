#!/usr/bin/env node
'use strict';

const assert = require('assert');
const childProcess = require('child_process');
const fs = require('fs');
const path = require('path');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const manifest = require('./manifest.json');
const showdownDir = process.argv[2];
const outputFile = process.argv[3];
if (!showdownDir || !outputFile) {
	throw new Error('usage: node generate.js SHOWDOWN_DIR OUTPUT.json');
}
assert.strictEqual(manifest.schema, 'pokemon-gen3ou-admission-random-manifest-v1');
assert.strictEqual(manifest.oracle_revision, REVISION);
assert(Array.isArray(manifest.seeds) && manifest.seeds.length > 0);
assert(Number.isInteger(manifest.accepted_per_seed) && manifest.accepted_per_seed > 0);
assert(Number.isInteger(manifest.rejected_per_seed) && manifest.rejected_per_seed > 0);
const revision = childProcess.execFileSync('git', ['-C', showdownDir, 'rev-parse', 'HEAD'], {encoding: 'utf8'}).trim();
assert.strictEqual(revision, REVISION);
const dirty = childProcess.execFileSync('git', ['-C', showdownDir, 'status', '--porcelain', '--untracked-files=no'], {encoding: 'utf8'}).trim();
assert.strictEqual(dirty, '', 'random admission generation requires a clean pinned Showdown checkout');

const {TeamValidator} = require(showdownDir);
const validator = new TeamValidator(manifest.format);
const bases = [
	['Pikachu', 'Static', ['Thunderbolt', 'Quick Attack', 'Fly', 'Surf', 'Agility', 'Body Slam'], ['M', 'F']],
	['Skarmory', 'Keen Eye', ['Drill Peck', 'Whirlwind', 'Curse', 'Rest', 'Toxic', 'Rapid Spin'], ['M', 'F']],
	['Shedinja', 'Wonder Guard', ['Silver Wind', 'Baton Pass', 'Swords Dance', 'Gust', 'Protect', 'Surf'], ['N']],
	['Weezing', 'Levitate', ['Pain Split', 'Will-O-Wisp', 'Sludge Bomb', 'Haze', 'Destiny Bond', 'Heal Bell'], ['M', 'F']],
	['Nidoking', 'Poison Point', ['Earthquake', 'Body Slam', 'Thunderbolt', 'Ice Beam', 'Bubble Beam', 'Lovely Kiss'], ['M']],
	['Bulbasaur', 'Overgrow', ['Growth', 'Razor Leaf', 'Sleep Powder', 'Ancient Power', 'Bide', 'Charm'], ['M', 'F']],
	['Hitmontop', 'Intimidate', ['High Jump Kick', 'Mach Punch', 'Rapid Spin', 'Rock Slide', 'Curse', 'Fly'], ['M']],
	['Zigzagoon', 'Pickup', ['Belly Drum', 'Extreme Speed', 'Shadow Ball', 'Thunderbolt', 'Surf', 'Spore'], ['M', 'F']],
	['Seel', 'Thick Fat', ['Perish Song', 'Fake Out', 'Surf', 'Ice Beam', 'Body Slam', 'Spore'], ['M', 'F']],
	['Mightyena', 'Intimidate', ['Heal Bell', 'Crunch', 'Shadow Ball', 'Body Slam', 'Toxic', 'Spore'], ['M', 'F']],
	['Gligar', 'Hyper Cutter', ['Razor Wind', 'Earthquake', 'Quick Attack', 'Swords Dance', 'Rock Slide', 'Surf'], ['M', 'F']],
	['Forretress', 'Sturdy', ['Flail', 'Spikes', 'Rapid Spin', 'Explosion', 'Toxic', 'Fly'], ['M', 'F']],
];
const natures = ['Serious', 'Adamant', 'Modest', 'Jolly', 'Calm'];
const levels = [50, 73, 100];
const evSpreads = [
	{hp: 1, atk: 0, def: 0, spa: 0, spd: 0, spe: 0},
	{hp: 4, atk: 252, def: 0, spa: 0, spd: 0, spe: 252},
	{hp: 252, atk: 0, def: 128, spa: 0, spd: 128, spe: 0},
];

function rng(seed) {
	let state = seed >>> 0;
	return limit => {
		state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
		return state % limit;
	};
}

function shuffled(values, random) {
	const result = [...values];
	for (let index = result.length - 1; index > 0; index--) {
		const other = random(index + 1);
		[result[index], result[other]] = [result[other], result[index]];
	}
	return result;
}

function makeSet(base, random) {
	const [species, ability, pool, genders] = base;
	const count = 1 + random(4);
	const iv = () => random(32);
	return {
		species, ability,
		item: random(2) ? 'Leftovers' : '',
		moves: shuffled(pool, random).slice(0, count),
		level: levels[random(levels.length)],
		gender: genders[random(genders.length)],
		nature: natures[random(natures.length)],
		shiny: random(2) === 1,
		ivs: {hp: iv(), atk: iv(), def: iv(), spa: iv(), spd: iv(), spe: iv()},
		evs: evSpreads[random(evSpreads.length)],
	};
}

function normalize(set) {
	return {...set, level: set.level ?? 100, nature: set.nature ?? 'Serious',
		evs: set.evs ?? {hp: 1, atk: 0, def: 0, spa: 0, spd: 0, spe: 0}};
}

function sourceDisposition(team) {
	const problems = validator.validateTeam(team.map(normalize)) || [];
	if (!problems.length) return {rule: null, member: 0};
	if (!problems.every(problem => /can't learn|moves .* are incompatible|can't get its egg move combination|move only available from an event|egg, which cannot be obtained at levels below 5|is learned at level|can't be transferred from Gen/.test(problem))) return null;
	for (let member = 0; member < team.length; member++) {
		if ((validator.validateSet(normalize(team[member]), {}) || []).some(problem =>
			/can't learn|moves .* are incompatible|can't get its egg move combination|move only available from an event|egg, which cannot be obtained at levels below 5|is learned at level|can't be transferred from Gen/.test(problem))) {
			return {rule: 'obtainablemoves', member};
		}
	}
	return null;
}

const cases = [];
for (const seed of manifest.seeds) {
	const random = rng(seed);
	const wanted = {legal: manifest.accepted_per_seed, rejected: manifest.rejected_per_seed};
	const found = {legal: 0, rejected: 0};
	const seen = new Set();
	for (let attempt = 0; (found.legal < wanted.legal || found.rejected < wanted.rejected) && attempt < 100000; attempt++) {
		const size = 2 + random(5);
		const selected = shuffled(bases, random).slice(0, size);
		const team = selected.map(base => makeSet(base, random));
		const key = JSON.stringify(team);
		if (seen.has(key)) continue;
		seen.add(key);
		const disposition = sourceDisposition(team);
		if (!disposition) continue;
		const bucket = disposition.rule ? 'rejected' : 'legal';
		if (found[bucket] >= wanted[bucket]) continue;
		const ordinal = found[bucket]++;
		cases.push({
			id: `seed-${seed}-${bucket}-${String(ordinal).padStart(2, '0')}`,
			team,
			rule: disposition.rule,
			member_index: disposition.member,
			seed,
		});
	}
	assert.deepStrictEqual(found, wanted, `seed ${seed} did not produce a balanced batch`);
}

const fixture = {
	schema: 'pokemon-gen3ou-admission-cases-v2',
	oracle_revision: REVISION,
	format: manifest.format,
	generator: {algorithm: 'LCG32', manifest: path.basename(require.resolve('./manifest.json'))},
	cases,
};
const members = cases.flatMap(testCase => testCase.team);
const coverage = {
	cases: cases.length,
	accepted: cases.filter(testCase => testCase.rule === null).length,
	rejected: cases.filter(testCase => testCase.rule !== null).length,
	species: [...new Set(members.map(member => member.species))].sort(),
	team_sizes: [...new Set(cases.map(testCase => testCase.team.length))].sort((a, b) => a - b),
	move_counts: [...new Set(members.map(member => member.moves.length))].sort((a, b) => a - b),
	levels: [...new Set(members.map(member => member.level))].sort((a, b) => a - b),
	natures: [...new Set(members.map(member => member.nature))].sort(),
	genders: [...new Set(members.map(member => member.gender))].sort(),
	shiny_values: [...new Set(members.map(member => member.shiny))].sort(),
	items: [...new Set(members.map(member => member.item))].sort(),
};
assert.strictEqual(coverage.cases, manifest.seeds.length *
	(manifest.accepted_per_seed + manifest.rejected_per_seed));
assert.strictEqual(coverage.accepted, manifest.seeds.length * manifest.accepted_per_seed);
assert.strictEqual(coverage.rejected, manifest.seeds.length * manifest.rejected_per_seed);
assert.strictEqual(coverage.species.length, bases.length);
assert.deepStrictEqual(coverage.team_sizes, [2, 3, 4, 5, 6]);
assert.deepStrictEqual(coverage.move_counts, [1, 2, 3, 4]);
assert.deepStrictEqual(coverage.levels, [...levels].sort((a, b) => a - b));
assert.deepStrictEqual(coverage.natures, [...natures].sort());
assert.deepStrictEqual(coverage.genders, ['F', 'M', 'N']);
assert.deepStrictEqual(coverage.shiny_values, [false, true]);
fixture.coverage = coverage;
fs.writeFileSync(outputFile, `${JSON.stringify(fixture, null, 2)}\n`);
