#!/usr/bin/env node
'use strict';

// Verifier-only full-battle case generator. Battle randomness belongs to
// Showdown; choice-policy randomness is an independent, recorded stream.

process.env.PS_GEN3_VERIFY_TRACE = '1';

const childProcess = require('child_process');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const {execute, timeoutFromEnvironment} = require('./subprocess');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const DEFAULT_BOUNDARIES = [
	'choice', 'events', 'handlers', 'immunity', 'prng', 'queue', 'request',
	'state', 'terminal',
];

function fail(message) {
	throw new Error(`random full-battle generator: ${message}`);
}

function parseArguments(argv) {
	const values = new Map();
	for (let index = 0; index < argv.length; index += 2) {
		const key = argv[index];
		if (!key.startsWith('--') || index + 1 === argv.length) fail(`invalid argument ${key}`);
		if (values.has(key)) fail(`duplicate argument ${key}`);
		values.set(key, argv[index + 1]);
	}
	for (const required of ['--showdown', '--team-p1', '--team-p2', '--id', '--battle-seed', '--policy-seed']) {
		if (!values.has(required)) fail(`missing ${required}`);
	}
	const id = values.get('--id');
	if (!/^[a-z0-9][a-z0-9._-]*$/.test(id)) fail('invalid case ID');
	const battleSeed = values.get('--battle-seed').split(',').map(Number);
	if (battleSeed.length !== 4 || battleSeed.some(word => !Number.isInteger(word) || word < 0 || word > 65535)) {
		fail('--battle-seed must contain four comma-separated uint16 values');
	}
	const policySeed = Number(values.get('--policy-seed'));
	if (!Number.isSafeInteger(policySeed) || policySeed < 0 || policySeed > 0xFFFFFFFF) {
		fail('--policy-seed must be a uint32');
	}
	const maxDecisions = values.has('--max-decisions') ? Number(values.get('--max-decisions')) : 1023;
	if (!Number.isInteger(maxDecisions) || maxDecisions < 1 || maxDecisions > 1023) {
		fail('--max-decisions must be in [1, 1023]');
	}
	return {
		showdown: path.resolve(values.get('--showdown')),
		teamPaths: [path.resolve(values.get('--team-p1')), path.resolve(values.get('--team-p2'))],
		id, battleSeed, policySeed, maxDecisions,
	};
}

function requirePinnedShowdown(directory) {
	const revision = execute('git', ['-C', directory, 'rev-parse', 'HEAD']).trim();
	if (revision !== REVISION) fail(`Showdown revision is ${revision}, expected ${REVISION}`);
	const observerPatch = path.resolve(__dirname,
		'../../harbor/gen3ou-native/tests/oracle-observer.patch');
	const observerChecksum = path.resolve(__dirname,
		'../../harbor/gen3ou-native/tests/oracle-observer.sha256');
	const expectedDigest = fs.readFileSync(observerChecksum, 'utf8').trim().split(/\s+/)[0];
	const actualDigest = crypto.createHash('sha256').update(fs.readFileSync(observerPatch)).digest('hex');
	if (actualDigest !== expectedDigest) fail('observer patch digest mismatch');
	const applied = childProcess.spawnSync(
		'git', ['-C', directory, 'apply', '--reverse', '--check', observerPatch],
		{encoding: 'utf8', timeout: timeoutFromEnvironment(), killSignal: 'SIGKILL'});
	if (applied.error) {
		fail(`observer patch check failed (${applied.error.code || 'spawn-error'}): ` +
			`${applied.error.message}`);
	}
	if (applied.status !== 0) fail('Showdown observer patch is not exactly applied');
	return require(directory);
}

function readAndValidateTeams(showdown, teamPaths) {
	const validator = showdown.TeamValidator.get('gen3ou');
	return teamPaths.map((filename, side) => {
		const source = fs.readFileSync(filename, 'utf8');
		const team = showdown.Teams.import(source);
		if (!team) fail(`player ${side + 1} team could not be parsed`);
		if (team.length !== 6) fail(`player ${side + 1} team has ${team.length} members, expected 6`);
		const problems = validator.validateTeam(team);
		if (problems) fail(`player ${side + 1} team is not legal Gen 3 OU:\n${problems.join('\n')}`);
		return {source, team};
	});
}

class PolicyPRNG {
	constructor(seed) {
		this.initialSeed = seed >>> 0;
		this.state = this.initialSeed;
		this.draws = 0;
	}

	pick(values) {
		if (!values.length) fail('policy was asked to choose from an empty set');
		this.state = (Math.imul(this.state, 1664525) + 1013904223) >>> 0;
		this.draws++;
		return values[Math.floor((this.state / 0x100000000) * values.length)];
	}
}

function normalizeTeams(battle, importedTeams, teamPaths) {
	return battle.sides.map((side, sideIndex) => ({
		source: path.basename(teamPaths[sideIndex]),
		normalized: side.pokemon.map((pokemon, slot) => {
			const source = importedTeams[sideIndex].team[slot];
			return {
				species: pokemon.baseSpecies.id,
				level: pokemon.level,
				gender: source.gender ? (pokemon.gender || 'N') :
					pokemon.species.gender === 'N' ? 'N' : null,
				nature: pokemon.set.nature.toLowerCase(),
				ability: pokemon.baseAbility,
				item: pokemon.set.item ? battle.dex.items.get(pokemon.set.item).id : '',
				moves: pokemon.baseMoveSlots.map(move => move.id),
				stats: ['hp', 'atk', 'def', 'spa', 'spd', 'spe'].map(stat =>
					stat === 'hp' ? pokemon.maxhp : pokemon.storedStats[stat]),
				status: null,
			};
		}),
	}));
}

function latestDecision(battle) {
	const decisions = battle.verificationTrace.filter(record => record.kind === 'decision');
	return decisions[decisions.length - 1];
}

function chooseRequest(request, policy) {
	if (request.kind === 'wait') return null;
	if (!Array.isArray(request.legal) || request.legal.length === 0) {
		fail(`non-wait request ${request.kind} has no legal choices`);
	}
	const legal = request.legal.filter(choice => /^(move [1-4]|switch [1-6])$/.test(choice));
	if (legal.length !== request.legal.length) {
		fail(`request contains an unsupported choice: ${JSON.stringify(request.legal)}`);
	}
	return policy.pick(legal);
}

function normalizeChoice(choice, side, initialOrder) {
	if (choice === null || choice.startsWith('move ')) return choice;
	const match = /^switch ([1-6])$/.exec(choice);
	if (!match) fail(`cannot normalize choice ${choice}`);
	const target = side.pokemon[Number(match[1]) - 1];
	const originalSlot = initialOrder.indexOf(target);
	if (!target || originalSlot < 0) fail(`switch target ${choice} has no stable team slot`);
	return `switch ${originalSlot + 1}`;
}

function generate(options) {
	const showdown = requirePinnedShowdown(options.showdown);
	const imported = readAndValidateTeams(showdown, options.teamPaths);
	const common = require(path.join(options.showdown, 'test/common')).gen(3);
	const battle = common.createBattle(
		{formatid: 'gen3ou', seed: options.battleSeed}, imported.map(entry => entry.team));
	if (!Array.isArray(battle.verificationTrace)) fail('the verifier observer patch is not applied');
	const teams = normalizeTeams(battle, imported, options.teamPaths);
	const initialOrder = battle.sides.map(side => side.pokemon.slice());
	const policy = new PolicyPRNG(options.policySeed);
	const sourceChoices = [];
	const choices = [];
	let decision = latestDecision(battle);
	if (!decision || decision.ordinal !== 0) fail('observer omitted the initial decision boundary');
	while (!battle.ended && choices.length < options.maxDecisions) {
		if (!decision || !Array.isArray(decision.request) || decision.request.length !== 2) {
			fail(`observer omitted request at decision ${choices.length}`);
		}
		const sourcePair = decision.request.map(request => chooseRequest(request, policy));
		const normalizedPair = sourcePair.map((choice, side) =>
			normalizeChoice(choice, battle.sides[side], initialOrder[side]));
		sourceChoices.push(sourcePair);
		choices.push(normalizedPair);
		battle.makeChoices(sourcePair[0] || '', sourcePair[1] || '');
		if (!battle.ended) {
			const next = latestDecision(battle);
			if (!next || next.ordinal !== choices.length) {
				fail(`observer did not advance to decision ${choices.length}`);
			}
			decision = next;
		}
	}
	if (!battle.ended) fail(`battle did not terminate within ${options.maxDecisions} decisions`);
	const actionCount = choices.flat().filter(choice => choice !== null).length;
	return {
		schema: 'pokemon-native-differential-case-v1',
		id: options.id,
		provenance: {
			kind: 'showdown-derived',
			source_file: 'verify/random-battles/generate.js',
			test_name: `deterministic legal full battle; policy=lcg32-v1 seed=${options.policySeed}`,
			oracle_revision: REVISION,
		},
		format: 'gen3ou',
		seed: options.battleSeed,
		teams,
		source_choices: sourceChoices,
		choices,
		forced_outcomes: [],
		features: ['request.legal-choices', 'state.canonical'],
		boundaries: DEFAULT_BOUNDARIES,
		limits: {max_boundaries: choices.length + 1, max_actions: actionCount},
	};
}

function main() {
	const options = parseArguments(process.argv.slice(2));
	process.stdout.write(`${JSON.stringify(generate(options), null, 2)}\n`);
}

if (require.main === module) main();

module.exports = {PolicyPRNG, generate, parseArguments};
