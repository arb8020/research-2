#!/usr/bin/env node
'use strict';

const assert = require('assert');
const childProcess = require('child_process');
const fs = require('fs');
const path = require('path');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const showdownDir = process.env.POKEMON_SHOWDOWN_DIR;
if (!showdownDir) throw new Error('POKEMON_SHOWDOWN_DIR must name the pinned clean Showdown checkout');
const revision = childProcess.execFileSync('git', ['-C', showdownDir, 'rev-parse', 'HEAD'], {encoding: 'utf8'}).trim();
if (revision !== REVISION) throw new Error(`expected Showdown ${REVISION}, got ${revision}`);
const dirty = childProcess.execFileSync('git', ['-C', showdownDir, 'status', '--porcelain', '--untracked-files=no'], {encoding: 'utf8'}).trim();
if (dirty) throw new Error('admission oracle requires a clean pinned Showdown checkout');

const fixture = JSON.parse(fs.readFileSync(path.join(__dirname, 'cases.json'), 'utf8'));
assert.strictEqual(fixture.schema, 'pokemon-gen3ou-admission-cases-v2');
assert.strictEqual(fixture.oracle_revision, REVISION);
const {Dex, TeamValidator} = require(showdownDir);
const validators = new Map();
const validatorFor = format => {
	if (!validators.has(format)) validators.set(format, new TeamValidator(format));
	return validators.get(format);
};

for (const battleCase of fixture.cases) {
	const validator = validatorFor(battleCase.format ?? fixture.format);
	const normalizeSet = source => {
		const {ev_input: evInput, ...fields} = source;
		const set = {
			...fields,
			moves: [...source.moves],
			level: source.level ?? 100,
			nature: source.nature ?? 'Serious',
		};
		if (!evInput) set.evs = {hp: 1, atk: 0, def: 0, spa: 0, spd: 0, spe: 0};
		else if (evInput.kind === 'values') set.evs = {...evInput.values};
		else assert.strictEqual(evInput.kind, 'omitted');
		return set;
	};
	assert.strictEqual(!!battleCase.set + !!battleCase.team, 1);
	const sets = battleCase.set ? [normalizeSet(battleCase.set)] : battleCase.team.map(normalizeSet);
	const problems = battleCase.set ?
		validator.validateSet(sets[0], {}) || [] : validator.validateTeam(sets) || [];
	const patterns = battleCase.rule === '-pokemontag:unobtainable' ? [/not obtainable/] :
		battleCase.rule === '-nonexistent' ? [/does not exist/, /is a CAP/] :
		battleCase.rule === 'ohkoclause' ? [/banned by OHKO Clause/] :
		battleCase.rule === 'accuracytrapclause' ? [/combination of a trapping move\/ability and a guaranteed accuracy-lowering move/] :
		battleCase.rule === 'oneboostpasserclause' ? [/banned by One Boost Passer Clause/] :
		battleCase.rule === 'speedpassclause' ? [/banned by Speed Pass Clause/] :
		battleCase.rule === 'evlimit' ? [/has exactly 0 EVs/, /has more than 255 EVs/, /total EVs, which is more than this format's limit of 510/] :
		battleCase.rule === 'obtainableabilities' ? [/can't have/] :
		battleCase.rule === 'obtainableformes' ? [/transforms in-battle with/] :
		battleCase.rule === 'nicknameclause' ? [/must have different nicknames/, /must not be nicknamed a different Pok.mon species/, /Nickname .* too long/] :
		battleCase.rule === 'obtainablemisc' ? [
			/has multiple copies of/,
			/Hidden Power type .* is incompatible/,
			/Hidden Power type .* does not match/,
			/Hidden Power type .* is invalid/,
			/has Hidden Power .*, but its IVs are for Hidden Power/,
			/not a valid Hidden Power type/,
			/must be at least level .* to be evolved/,
			/gender must be .* to be underleveled from an event/,
			/is only obtainable from event/,
			/must be at least level .* from its event/,
			/must have .* nature/,
			/must have .* IV/,
		] :
		battleCase.rule === 'obtainablemoves' ? [/can't learn/, /moves .* are incompatible/, /can't get its egg move combination/, /move only available from an event/, /egg, which cannot be obtained at levels below 5/, /is learned at level/, /can't be transferred from Gen/] :
		[/\bis banned\b/, /\bbanned by\b/];
	const rejected = battleCase.rule !== null && problems.some(problem =>
		patterns.some(pattern => pattern.test(problem)));
	if (battleCase.rule === null && problems.length) {
		throw new Error(`${battleCase.id}: control is not legal: ${problems.join('; ')}`);
	}
	if (battleCase.rule !== null && !rejected) {
		throw new Error(`${battleCase.id}: expected admission rejection: ${problems.join('; ')}`);
	}
	const normalized_species = rejected ? null : sets.map(set => Dex.toID(set.species));
	const normalized_names = rejected ? null : sets.map(set => set.name);
	const statNames = ['hp', 'atk', 'def', 'spa', 'spd', 'spe'];
	const normalized_fields = rejected ? null : sets.map(set => ({
		gender: set.gender || '-', nature: Dex.toID(set.nature), shiny: !!set.shiny,
		ivs: statNames.map(stat => set.ivs[stat]), hp_type: Dex.toID(set.hpType || ''),
	}));
	process.stdout.write(`${JSON.stringify({id: battleCase.id, rejected, normalized_species, normalized_names, normalized_fields})}\n`);
}
