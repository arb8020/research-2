'use strict';

// Observation-only driver for the pinned Pokemon Showdown oracle. It writes one
// JSON object per stable input boundary, including the initial and terminal
// boundaries. PS_GEN3_VERIFY_TRACE requires the verifier's
// harbor/gen3ou-native/tests/oracle-observer.patch to be applied to the pinned
// tree; without it, the driver refuses to imply that it observed PRNG draws.

process.env.PS_GEN3_VERIFY_TRACE = '1';

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const {execFileSync} = require('child_process');
const {normalizeCase} = require('../cases/normalize');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const showdownDir = process.env.POKEMON_SHOWDOWN_DIR;
if (!showdownDir) throw new Error('POKEMON_SHOWDOWN_DIR must name the pinned Showdown checkout');
const observerPatch = path.resolve(__dirname,
	'../../harbor/gen3ou-native/tests/oracle-observer.patch');
const observerChecksum = path.resolve(__dirname,
	'../../harbor/gen3ou-native/tests/oracle-observer.sha256');
const checkoutRevision = execFileSync(
	'git', ['-C', showdownDir, 'rev-parse', 'HEAD'], {encoding: 'utf8'}).trim();
if (checkoutRevision !== REVISION) throw new Error(`wrong Showdown checkout revision: ${checkoutRevision}`);
const expectedPatchDigest = fs.readFileSync(observerChecksum, 'utf8').trim().split(/\s+/)[0];
const patchDigest = crypto.createHash('sha256').update(fs.readFileSync(observerPatch)).digest('hex');
if (patchDigest !== expectedPatchDigest) throw new Error('observer patch digest mismatch');
try {
	execFileSync('git', ['-C', showdownDir, 'apply', '--reverse', '--check', observerPatch],
		{stdio: 'ignore'});
} catch {
	throw new Error('Showdown observer patch is not exactly applied');
}

const common = require(path.join(showdownDir, 'test/common')).gen(3);
const {Teams} = require(showdownDir);
const casePath = path.resolve(process.argv[2] || path.join(__dirname, 'case.json'));
const fixture = normalizeCase(JSON.parse(fs.readFileSync(casePath, 'utf8')));
const fixtureItemIDs = new Set(fixture.teams.flatMap(team =>
	team.normalized.map(pokemon => pokemon.item).filter(Boolean)));
if (fixture.provenance.oracle_revision !== REVISION) throw new Error('wrong Showdown revision');
if (fixture.choices.length + 1 > fixture.limits.max_boundaries) {
	throw new Error(`case requires ${fixture.choices.length + 1} boundaries, limit is ${fixture.limits.max_boundaries}`);
}
const actionCount = fixture.choices.flat().filter(choice => choice !== null).length;
if (actionCount > fixture.limits.max_actions) {
	throw new Error(`case requires ${actionCount} actions, limit is ${fixture.limits.max_actions}`);
}

const fixtureDir = path.dirname(casePath);
const teams = fixture.teams.map(team => {
	return Teams.import(fs.readFileSync(path.join(fixtureDir, team.source), 'utf8'));
});
const battle = common.createBattle({formatid: fixture.format, seed: fixture.seed}, teams);
if (!Array.isArray(battle.verificationTrace)) {
	throw new Error('Showdown observer patch is absent; PRNG records cannot be reported honestly');
}

for (let side = 0; side < 2; side++) {
	for (let slot = 0; slot < fixture.teams[side].normalized.length; slot++) {
		const expected = fixture.teams[side].normalized[slot];
		const source = teams[side][slot];
		const pokemon = battle.sides[side].pokemon[slot];
		const observed = {
			species: pokemon.baseSpecies.id,
			level: pokemon.level,
			gender: source.gender ? (pokemon.gender || 'N') :
				pokemon.species.gender === 'N' ? 'N' : null,
			...(Object.hasOwn(expected, 'nature') ?
				{nature: pokemon.set.nature.toLowerCase()} : {}),
			ability: pokemon.baseAbility,
			// Construction may already have consumed an onStart item. Team
			// normalization checks the immutable imported set; mutable item state
			// is compared separately at every recorded boundary below.
			item: pokemon.set.item ? battle.dex.items.get(pokemon.set.item).id : '',
			moves: pokemon.baseMoveSlots.map(move => move.id),
			stats: ['hp', 'atk', 'def', 'spa', 'spd', 'spe'].map(stat =>
				stat === 'hp' ? pokemon.maxhp : pokemon.storedStats[stat]),
			...(Object.hasOwn(expected, 'ivs') ?
				{ivs: ['hp', 'atk', 'def', 'spa', 'spd', 'spe'].map(stat =>
					pokemon.set.ivs[stat])} : {}),
			status: pokemon.status || null,
			...(Object.hasOwn(expected, 'happiness') ?
				{happiness: pokemon.happiness} : {}),
		};
		const {initial_hp: initialHP, status_state: initialStatusState, ...expectedSet} = expected;
		void initialStatusState;
		const expectedTeamData = {...expectedSet, status: null};
		if (JSON.stringify(observed) !== JSON.stringify(expectedTeamData)) {
			throw new Error(`normalized team diverges from Showdown at side ${side + 1}, slot ${slot + 1}: ` +
				`expected ${JSON.stringify(expectedTeamData)}, observed ${JSON.stringify(observed)}`);
		}
	}
}

const initialDecision = battle.verificationTrace.find(record =>
	record.kind === 'decision' && record.ordinal === 0);
if (!initialDecision) throw new Error('Showdown observer omitted the initial decision boundary');
for (let side = 0; side < 2; side++) {
	for (let slot = 0; slot < fixture.teams[side].normalized.length; slot++) {
		const status = fixture.teams[side].normalized[slot].status;
		const initialHP = fixture.teams[side].normalized[slot].initial_hp;
		if (initialHP !== undefined) {
			const pokemon = battle.sides[side].pokemon[slot];
			pokemon.hp = initialHP;
			initialDecision.state.sides[side].pokemon[slot].hp = initialHP;
		}
		if (!status) continue;
		const pokemon = battle.sides[side].pokemon[slot];
		pokemon.status = status;
		pokemon.statusState = battle.initEffectState({id: status, target: pokemon});
		if (status === 'slp') {
			const statusState = fixture.teams[side].normalized[slot].status_state;
			pokemon.statusState.time = statusState.time;
			pokemon.statusState.skippedTime = statusState.skipped_time;
		} else if (status === 'tox') {
			pokemon.statusState.stage =
				fixture.teams[side].normalized[slot].status_state.stage;
		}
		const observed = initialDecision.state.sides[side].pokemon[slot];
		observed.status = status;
		observed.statusState = status === 'slp' ? {
			stage: 0,
			time: pokemon.statusState.time,
			skippedTime: pokemon.statusState.skippedTime,
		} : {stage: pokemon.statusState.stage || 0, duration: 0};
		if (pokemon.status !== status || observed.status !== status) {
			throw new Error(`failed to install canonical initial status at side ${side + 1}, slot ${slot + 1}`);
		}
	}
}

const initialStats = new Map();
const teamOrder = battle.sides.map(side => side.pokemon.map(pokemon => pokemon.baseSpecies.id));
for (let side = 0; side < 2; side++) {
	for (const pokemon of battle.sides[side].pokemon) {
		initialStats.set(`${side}:${pokemon.baseSpecies.id}`, {
			level: pokemon.level,
			gender: pokemon.gender || 'N',
			stats: ['hp', 'atk', 'def', 'spa', 'spd', 'spe'].map(stat =>
				stat === 'hp' ? pokemon.maxhp : pokemon.storedStats[stat]),
		});
	}
}

function projectState(state, terminal = false) {
	return {
		turn: state.turn,
		terminal,
		winner: terminal ? (battle.winner === 'Player 1' ? 0 : battle.winner === 'Player 2' ? 1 : null) : null,
		field: {
			weather: state.weather,
			weather_state: state.weatherState ? {
				id: state.weatherState.id, duration: state.weatherState.duration,
			} : null,
			terrain: state.terrain,
		},
		sides: state.sides.map((side, sideIndex) => {
			const activeSpecies = side.pokemon.find(pokemon => pokemon.position === side.active[0]).species;
			const bySpecies = new Map(side.pokemon.map(pokemon => [pokemon.species, pokemon]));
			return {
				active: teamOrder[sideIndex].indexOf(activeSpecies),
				side_conditions: side.sideConditions.map(condition => ({
					id: condition.id,
					...(condition.layers === undefined ?
						{duration: condition.duration} : {layers: condition.layers}),
				})),
				slot_conditions: side.slotConditions.map(condition => ({
					position: condition.position,
					id: condition.id,
					duration: condition.duration,
					source_side: condition.sourceSide,
					source_slot: teamOrder[condition.sourceSide].indexOf(condition.sourceSpecies),
					source_effect: {
						kind: condition.sourceEffectType === 'Move' || condition.move ? 'move' : 'condition',
						id: condition.sourceEffect || condition.move,
					},
					payload: condition.id === 'futuremove' ? {
						kind: 'delayed-move', move: condition.move,
						fixed_damage: condition.damage,
					} : {kind: 'wish'},
				})),
				pokemon: teamOrder[sideIndex].map(species => bySpecies.get(species)).map(pokemon => ({
				species: pokemon.species,
				...initialStats.get(`${sideIndex}:${pokemon.species}`),
				hp: pokemon.hp,
				max_hp: pokemon.maxhp,
				ability: pokemon.ability,
				effective_types: pokemon.types,
				moves: pokemon.moves.map(move => ({id: move.id, pp: move.pp, max_pp: move.maxpp})),
				boosts: {...pokemon.boosts},
				status: pokemon.status === 'fnt' ? null : pokemon.status,
				status_state: pokemon.statusState ? {
					stage: pokemon.statusState.stage,
					duration: pokemon.statusState.time ?? pokemon.statusState.duration,
					...(pokemon.status === 'slp' ?
						{skipped_time: pokemon.statusState.skippedTime ?? 0} : {}),
				} : null,
				volatiles: pokemon.volatiles.filter(volatile =>
					volatile.id !== 'trapper').map(volatile => ({
					id: volatile.id, duration: volatile.duration,
					counter: volatile.counter ?? volatile.multiplier ?? volatile.layers,
					...(volatile.id === 'substitute' ? {hp: volatile.hp} : {}),
					...(volatile.id === 'substitutebroken' ?
						{breaking_move: volatile.breakingMove} : {}),
					...(volatile.id === 'lockedmove' ? {
						move: volatile.move, true_duration: volatile.trueDuration,
					} : {}),
					...((volatile.id === 'disable' || volatile.id === 'encore') ?
						{move: volatile.move} : {}),
					...((volatile.id === 'attract' || volatile.id === 'trapped' ||
						volatile.id === 'lockon') ? {
						source_side: volatile.sourceSide,
						source_slot: teamOrder[volatile.sourceSide].indexOf(volatile.sourceSpecies),
						source_effect: {
							kind: volatile.sourceEffectType === 'Ability' ? 'ability' : 'move',
							id: volatile.sourceEffect,
						},
					} : {}),
					...(volatile.id === 'bide' ? {
						total_damage: volatile.totalDamage,
						last_source: volatile.lastSourceSide === null ? null : {
							side: volatile.lastSourceSide,
							slot: teamOrder[volatile.lastSourceSide].indexOf(
								volatile.lastSourceSpecies),
						},
					} : {}),
				})),
				last_move: pokemon.lastMove || null,
				last_move_used: pokemon.lastMoveUsed ? {
					move: pokemon.lastMoveUsed.move,
					resolved_type: pokemon.lastMoveUsed.resolvedType.toLowerCase(),
				} : null,
				attacked_by: pokemon.lastAttackedBy ? {
					source_side: pokemon.lastAttackedBy.sourceSide,
					source_slot: teamOrder[pokemon.lastAttackedBy.sourceSide].indexOf(
						pokemon.lastAttackedBy.sourceSpecies),
					move: pokemon.lastAttackedBy.move,
					damage: pokemon.lastAttackedBy.damage,
					damage_was_number: pokemon.lastAttackedBy.damageWasNumber,
					this_turn: pokemon.lastAttackedBy.thisTurn,
				} : null,
				item: pokemon.item || null,
				last_item: pokemon.lastItem || null,
				staleness: pokemon.staleness || null,
				pending_staleness: pokemon.pendingStaleness || null,
				volatile_staleness: pokemon.volatileStaleness || null,
				used_item_this_turn: !!pokemon.usedItemThisTurn,
				ate_berry: !!pokemon.ateBerry,
				item_knocked_off: !!pokemon.itemKnockedOff,
				fainted: pokemon.fainted,
			})),
		};
		}),
	};
}

function liveState() {
	return {
		turn: battle.turn,
		weather: battle.field.weather || null,
		weatherState: battle.field.weather ? {
			id: battle.field.weather, duration: battle.field.weatherState.duration || 0,
		} : null,
		terrain: battle.field.terrain || null,
		sides: battle.sides.map((side, sideIndex) => ({
			active: [side.active[0].position],
			sideConditions: Object.keys(side.sideConditions).sort().map(id => {
				const condition = side.sideConditions[id];
				return {
					id, duration: condition.duration || 0,
					...(condition.layers === undefined ? {} : {layers: condition.layers}),
				};
			}),
			slotConditions: side.slotConditions.flatMap((conditions, position) =>
				Object.keys(conditions).sort().map(id => ({
					position, id, duration: conditions[id].duration || 0,
					sourceSide: conditions[id].source?.side === battle.sides[0] ? 0 : 1,
					sourceSpecies: conditions[id].source?.baseSpecies.id || null,
					sourceEffect: conditions[id].sourceEffect?.id || null,
					sourceEffectType: conditions[id].sourceEffect?.effectType || null,
					...(conditions[id].move ? {move: conditions[id].move} : {}),
					...(conditions[id].moveData?.damage !== undefined ?
						{damage: conditions[id].moveData.damage} : {}),
				}))),
			pokemon: side.pokemon.map(pokemon => ({
				species: pokemon.baseSpecies.id,
				position: pokemon.position,
				hp: pokemon.hp,
				maxhp: pokemon.maxhp,
				ability: pokemon.ability,
				types: pokemon.getTypes().map(type => type.toLowerCase()),
				status: pokemon.status || null,
				statusState: pokemon.status ? {
					stage: pokemon.statusState.stage || 0,
					duration: pokemon.statusState.time || pokemon.statusState.duration || 0,
				} : null,
				volatiles: Object.keys(pokemon.volatiles).filter(id => id !== 'trapper').sort().map(id => ({
					id,
					duration: pokemon.volatiles[id].duration || 0,
					counter: pokemon.volatiles[id].counter ||
						pokemon.volatiles[id].multiplier ||
						pokemon.volatiles[id].layers || 0,
					...(id === 'substitute' ? {hp: pokemon.volatiles[id].hp} : {}),
					...(id === 'substitutebroken' ?
						{breakingMove: pokemon.volatiles[id].sourceEffect?.id || null} : {}),
					...(id === 'lockedmove' ? {
						move: pokemon.volatiles[id].move || null,
						trueDuration: pokemon.volatiles[id].trueDuration || 0,
					} : {}),
					...((id === 'disable' || id === 'encore') ? {
						move: pokemon.volatiles[id].move || null,
					} : {}),
					...((id === 'trapped' || id === 'lockon') ? {
						sourceSide: pokemon.volatiles[id].source.side === battle.sides[0] ? 0 : 1,
						sourceSpecies: pokemon.volatiles[id].source.baseSpecies.id,
						sourceEffect: pokemon.volatiles[id].sourceEffect.id,
						 sourceEffectType: pokemon.volatiles[id].sourceEffect.effectType,
					} : {}),
					...(id === 'bide' ? {
						totalDamage: pokemon.volatiles[id].totalDamage || 0,
						lastSourceSide: pokemon.volatiles[id].lastDamageSource ?
							(pokemon.volatiles[id].lastDamageSource.side === battle.sides[0] ? 0 : 1) : null,
						lastSourceSpecies: pokemon.volatiles[id].lastDamageSource?.baseSpecies.id || null,
					} : {}),
				})),
				lastMove: pokemon.lastMove?.id || null,
				lastMoveUsed: pokemon.lastMoveUsed ? {
					move: pokemon.lastMoveUsed.id,
					resolvedType: pokemon.lastMoveUsed.type,
				} : null,
				lastAttackedBy: pokemon.getLastAttackedBy() ? {
					sourceSide: pokemon.getLastAttackedBy().source.side === battle.sides[0] ? 0 : 1,
					sourceSlot: pokemon.getLastAttackedBy().source.position,
					sourceSpecies: pokemon.getLastAttackedBy().source.baseSpecies.id,
					move: pokemon.getLastAttackedBy().move,
					damage: pokemon.getLastAttackedBy().damage,
					damageWasNumber: typeof pokemon.getLastAttackedBy().damageValue === 'number',
					thisTurn: pokemon.getLastAttackedBy().thisTurn,
				} : null,
				item: pokemon.item || null,
				lastItem: pokemon.lastItem || null,
				staleness: pokemon.staleness || null,
				pendingStaleness: pokemon.pendingStaleness || null,
				volatileStaleness: pokemon.volatileStaleness || null,
				usedItemThisTurn: !!pokemon.usedItemThisTurn,
				ateBerry: !!pokemon.ateBerry,
				fainted: pokemon.fainted,
				boosts: {...pokemon.boosts},
				moves: pokemon.moveSlots.map(move => ({id: move.id, pp: move.pp, maxpp: move.maxpp})),
			})),
		})),
	};
}

function canonicalSwitchChoice(choice, sideIndex, state) {
	const match = /^switch (\d+)$/.exec(choice);
	if (!match) return choice;
	const pokemon = state.sides[sideIndex].pokemon[Number(match[1]) - 1];
	if (!pokemon) throw new Error(`invalid Showdown switch choice: ${choice}`);
	const originalSlot = teamOrder[sideIndex].indexOf(pokemon.species);
	if (originalSlot < 0) throw new Error(`unknown original team member: ${pokemon.species}`);
	return `switch ${originalSlot + 1}`;
}

function requests(request, state) {
	return request.map((value, sideIndex) => ({
		kind: value.kind,
		legal: value.legal.map(choice => canonicalSwitchChoice(choice, sideIndex, state)).sort((left, right) => {
			const [leftKind, leftSlot] = left.split(' ');
			const [rightKind, rightSlot] = right.split(' ');
			if (leftKind !== rightKind) return leftKind === 'switch' ? -1 : 1;
			return Number(leftSlot) - Number(rightSlot);
		}),
	}));
}

function canonicalSlot(side, slot, state) {
	const pokemon = state.sides[side].pokemon[slot];
	if (!pokemon) throw new Error(`invalid Showdown party position ${slot + 1} for side ${side + 1}`);
	const originalSlot = teamOrder[side].indexOf(pokemon.species);
	if (originalSlot < 0) throw new Error(`unknown original team member: ${pokemon.species}`);
	return originalSlot;
}

function canonicalTransition(record, state, request) {
	const canonicalMoveSlot = (value, side) => value.kind === 'move' &&
		request[side].kind === 'move' && request[side].legal.length === 1 &&
		request[side].legal[0] === 'move 1' ? {...value, slot: 0} : value;
	return {
		choices: record.choices.map((choice, side) => choice.kind === 'switch' ?
			{...choice, slot: canonicalSlot(side, choice.slot, state)} :
			canonicalMoveSlot(choice, side)),
		queue: record.actions.map(action => action.kind === 'switch' ?
			{...action, slot: canonicalSlot(action.side, action.slot, state)} : action),
	};
}

function expectedChoices(pair) {
	return pair.map(value => {
		if (value === null) return {kind: 'none', slot: null};
		const match = /^(move|switch) ([1-6])$/.exec(value);
		if (!match) throw new Error(`invalid normalized choice ${JSON.stringify(value)}`);
		return {kind: match[1], slot: Number(match[2]) - 1};
	});
}

function sideOf(token) {
	const match = /^p([12])a:/.exec(token);
	return match ? Number(match[1]) - 1 : null;
}

function exactCondition(condition) {
	const match = /^(\d+)\/(\d+)(?: [a-z]+)?$/.exec(condition);
	if (match) return {hp: Number(match[1]), max_hp: Number(match[2])};
	return condition === '0 fnt' ? {hp: 0, max_hp: null} : null;
}

function speciesOf(token) {
	return battle.dex.species.get(token.replace(/^p[12]a: /, '')).id;
}

function protocolEvents(lines, priorState) {
	const events = [];
	const hp = new Map();
	for (let side = 0; side < 2; side++) {
		for (const pokemon of priorState.sides[side].pokemon) hp.set(`${side}:${pokemon.species}`, pokemon.hp);
	}
	let skipPublicSplitLine = false;
	for (const line of lines) {
		if (line.startsWith('|split|')) {
			skipPublicSplitLine = false;
			continue;
		}
		const parts = line.split('|');
		const kind = parts[1];
		if (skipPublicSplitLine && (kind === 'switch' || kind === 'drag' || kind === '-damage' || kind === '-heal')) {
			skipPublicSplitLine = false;
			continue;
		}
		if (kind === 'switch' || kind === 'drag') {
			const condition = exactCondition(parts[4]);
			if (!condition) continue;
			const side = sideOf(parts[2]);
			const species = battle.dex.species.get(parts[3].split(',')[0]).id;
			const canonical = priorState.sides[side].pokemon.find(pokemon => pokemon.species === species);
			const switchState = canonical ? {hp: canonical.hp, max_hp: condition.max_hp} : condition;
			events.push({kind, side, species, ...switchState});
			hp.set(`${side}:${species}`, switchState.hp);
			skipPublicSplitLine = true;
		} else if (kind === 'move') {
			events.push({kind: 'move', side: sideOf(parts[2]), move: battle.dex.moves.get(parts[3]).id,
				target_side: sideOf(parts[4])});
		} else if (kind === '-miss') {
			events.push({kind: 'miss', side: sideOf(parts[2])});
		} else if (kind === '-immune') {
			events.push({kind: 'immune', side: sideOf(parts[2])});
		} else if (kind === '-damage') {
			const condition = exactCondition(parts[3]);
			if (!condition) continue;
			const side = sideOf(parts[2]);
			const species = speciesOf(parts[2]);
			const key = `${side}:${species}`;
			const before = hp.get(key);
			events.push({kind: 'damage', side, species, amount: before - condition.hp, hp: condition.hp});
			hp.set(key, condition.hp);
			skipPublicSplitLine = true;
		} else if (kind === '-heal') {
			const condition = exactCondition(parts[3]);
			if (!condition) continue;
			const side = sideOf(parts[2]);
			const species = speciesOf(parts[2]);
			const key = `${side}:${species}`;
			const before = hp.get(key);
			events.push({kind: 'heal', side, species, amount: condition.hp - before, hp: condition.hp});
			hp.set(key, condition.hp);
			skipPublicSplitLine = true;
		} else if (kind === '-hitcount') {
			events.push({kind: 'hit-count', side: sideOf(parts[2]), hits: Number(parts[3])});
		} else if (kind === 'faint') {
			events.push({kind: 'faint', side: sideOf(parts[2])});
		} else if (kind === 'win') {
			events.push({kind: 'win', side: parts[2] === 'Player 1' ? 0 : 1});
		} else if (kind === 'tie') {
			events.push({kind: 'tie'});
		}
	}
	return events;
}

function canonicalPrngRecord(record) {
		const sleepDuration = record.label.startsWith('unlabeled:Start:slp:');
		const paralysis = record.label.startsWith('unlabeled:BeforeMove:par:');
		const freeze = record.label.startsWith('unlabeled:BeforeMove:frz:');
		const slotDelegation = record.label.startsWith(
			'unlabeled:Hit:sleeptalk:sleeptalk');
		const ppReduction = record.label.startsWith(
			'unlabeled:Hit:spite:spite');
		const moveTypeSelection = record.label.startsWith(
			'unlabeled:Hit:conversion:conversion');
		return {
		label: sleepDuration ? 'status.sleep.duration' :
			paralysis ? 'status.paralysis.before_move' :
			freeze ? 'status.freeze.before_move' :
			slotDelegation ? 'move.delegation.selection' :
			ppReduction ? 'move.pp_reduction' :
			moveTypeSelection ? 'move.type_selection' : record.label,
		before: numericSeed(record.draw.before),
		after: numericSeed(record.draw.after),
		from: sleepDuration ? 4 :
			(record.draw.from === undefined ? null : record.draw.from),
		to: sleepDuration ? null :
			(record.draw.to === undefined ? null : record.draw.to),
			result: sleepDuration ? record.draw.result - 2 : record.draw.result,
		};
}

function prngBetween(afterSequence, throughSequence) {
	return battle.verificationTrace.filter(record => record.kind === 'prng' &&
		record.sequence > afterSequence && record.sequence < throughSequence)
		.map(canonicalPrngRecord);
}

function canonicalHolder(holder) {
	const match = /^p([12]):(\d+):([a-z0-9]+)$/.exec(holder);
	if (!match) throw new Error(`unsupported handler/immunity holder ${JSON.stringify(holder)}`);
	const side = Number(match[1]) - 1;
	const species = match[3];
	const slot = teamOrder[side].indexOf(species);
	if (slot < 0) throw new Error(`unknown holder species ${species} on side ${side + 1}`);
	return {side, slot};
}

function canonicalEventHolder(holder) {
	if (holder === 'field') return {kind: 'field'};
	const sideMatch = /^p([12])$/.exec(holder);
	if (sideMatch) return {kind: 'side', side: Number(sideMatch[1]) - 1};
	return canonicalHolder(holder);
}

function canonicalConditionHolder(holder) {
	if (holder === 'field') return {kind: 'field'};
	const slotMatch = /^p([12]):slot:(\d+)$/.exec(holder);
	if (slotMatch) return {
		kind: 'slot', side: Number(slotMatch[1]) - 1, position: Number(slotMatch[2]),
	};
	const sideMatch = /^p([12])$/.exec(holder);
	if (sideMatch) return {kind: 'side', side: Number(sideMatch[1]) - 1};
	return {kind: 'pokemon', ...canonicalHolder(holder)};
}

function conditionState(record) {
	return {
		duration_before: record.durationBefore === undefined ? null : record.durationBefore,
		duration_after: record.durationAfter === undefined ? null : record.durationAfter,
		counter_before: record.counterBefore === undefined ? null : record.counterBefore,
		counter_after: record.counterAfter === undefined ? null : record.counterAfter,
		stage_before: record.stageBefore === undefined ? null : record.stageBefore,
		stage_after: record.stageAfter === undefined ? null : record.stageAfter,
	};
}

function conditionsBetween(afterSequence, throughSequence) {
	const records = battle.verificationTrace.filter(record =>
		record.sequence > afterSequence && record.sequence < throughSequence);
	// Showdown creates a slot-condition shell and lets the move callback fill
	// its payload. The native boundary exposes that as one atomic installation,
	// so coalesce the observer's adjacent add/update construction records.
	const slotConstructionUpdates = new Map();
	const coalescedSequences = new Set();
	for (let i = 0; i < records.length; i++) {
		const add = records[i];
		if (add.kind !== 'condition' || add.phase !== 'add' || add.scope !== 'slot') continue;
		for (let j = i + 1; j < records.length; j++) {
			const update = records[j];
			if (update.kind !== 'condition') continue;
			if (update.effect !== add.effect || update.holder !== add.holder) continue;
			if (update.phase === 'update') {
				slotConstructionUpdates.set(add.sequence, update);
				coalescedSequences.add(update.sequence);
			}
			break;
		}
	}
	const result = [];
	let sawScreenModifier = false;
	for (const record of records) {
		if (coalescedSequences.has(record.sequence)) continue;
		if (record.kind === 'prng' && [
			'stall.success', 'field_event.residual.handler_order', 'event.setstatus.handler_order',
		].includes(record.label)) {
			result.push({
				kind: 'prng', label: record.label,
				from: record.draw.from === undefined ? null : record.draw.from,
				to: record.draw.to === undefined ? null : record.draw.to,
				result: record.draw.result,
			});
			continue;
		}
		if (record.kind === 'condition') {
			if (record.effect === 'spikes' && record.phase === 'damage') continue;
			const common = {
				scope: record.scope,
				id: record.effect,
				holder: canonicalConditionHolder(record.holder),
			};
			if (record.phase === 'damage') {
				result.push({kind: 'damage', ...common, amount: record.amount});
			} else if (record.phase.startsWith('residual-')) {
				result.push({
					kind: 'residual', phase: record.phase.slice('residual-'.length), ...common,
					...conditionState(record),
					order: record.order === false || record.order === undefined ? null : record.order,
					priority: record.priority === undefined ? 0 : record.priority,
					sub_order: record.subOrder === undefined ? 0 : record.subOrder,
				});
			} else {
				const state = conditionState(record);
				const constructionUpdate = slotConstructionUpdates.get(record.sequence);
				if (constructionUpdate) {
					const updated = conditionState(constructionUpdate);
					state.duration_after = updated.duration_after;
					state.counter_after = updated.counter_after;
					state.stage_after = updated.stage_after;
				}
				result.push({kind: 'lifecycle', phase: record.phase, ...common, ...state});
			}
			continue;
		}
		if (record.kind === 'handlers' && ['TryHit', 'ModifyDamagePhase1'].includes(record.event)) {
			for (const handler of record.handlers) {
				const projected = record.event === 'TryHit' ?
					['protect', 'fly', 'dig', 'dive', 'futuremove'].includes(handler.effect) :
					['reflect', 'lightscreen', 'fly', 'dig', 'dive', 'flashfire'].includes(handler.effect);
				if (!projected) continue;
				result.push({
					kind: 'handler',
					event: record.event === 'TryHit' ? 'try-hit' : 'modify-damage-phase1',
					id: handler.effect,
					holder: canonicalConditionHolder(handler.holder),
					order: handler.order === false ? null : handler.order,
					priority: handler.priority,
					sub_order: handler.subOrder,
				});
			}
			continue;
		}
		if (record.kind === 'modifier' && record.event === 'ModifyDamagePhase1') {
			if (record.phase === 'handler' &&
				['reflect', 'lightscreen', 'fly', 'dig', 'dive', 'flashfire'].includes(record.effect)) {
				sawScreenModifier = true;
				result.push({
					kind: 'relay-handler', event: 'modify-damage-phase1', id: record.effect,
					holder: canonicalConditionHolder(record.holder), relay: record.relay,
					modifier_q12_before: record.modifierQ12Before,
					modifier_q12_after: record.modifierQ12After,
				});
			} else if (record.phase === 'result' && sawScreenModifier) {
				result.push({
					kind: 'relay-result', event: 'modify-damage-phase1', relay: record.relay,
					modifier_q12: record.modifierQ12After, result: record.result,
				});
				sawScreenModifier = false;
			}
		}
	}
	return result;
}

function effectsBetween(afterSequence, throughSequence) {
	/* Primary-effect observation remains bounded to the currently verified
	 * family. Secondary transactions are a generic semantic boundary and are
	 * therefore projected independently of move identity. */
	const supportedPrimaryMoves = new Set([
		'bulkup', 'growl', 'ember', 'flamethrower', 'steelwing', 'bodyslam', 'doubleedge',
		'absorb', 'megadrain', 'gigadrain', 'leechlife',
		'dreameater',
		'sonicboom', 'dragonrage',
		'superfang', 'endeavor', 'psywave', 'hyperbeam',
		'seismictoss', 'nightshade', 'reversal', 'flail', 'tickle', 'howl', 'calmmind',
		'acidarmor', 'agility', 'amnesia', 'barrier', 'charm', 'cosmicpower',
		'cottonspore', 'dragondance', 'faketears', 'featherdance', 'flash', 'growth',
		'defensecurl', 'harden', 'irondefense', 'kinesis', 'leer', 'meditate', 'metalsound',
		'minimize',
		'sandattack', 'scaryface', 'screech', 'sharpen', 'smokescreen', 'stringshot',
		'sweetscent', 'swordsdance', 'tailglow', 'tailwhip', 'withdraw',
		'recover', 'milkdrink', 'slackoff', 'softboiled',
		'moonlight', 'morningsun', 'synthesis',
		'flatter', 'swagger', 'struggle', 'overheat', 'psychoboost', 'superpower',
		'memento',
		'jumpkick', 'highjumpkick',
		'submission', 'takedown', 'volttackle',
		'aromatherapy', 'healbell',
	]);
	return battle.verificationTrace.filter(record => record.kind === 'effect' &&
		(record.phase === 'hit-loop' || record.phase === 'secondary' || record.phase === 'self-secondary' ||
			record.operation === 'cure-status' || supportedPrimaryMoves.has(record.move)) &&
		record.sequence > afterSequence && record.sequence < throughSequence).map(record => {
		const common = {
			kind: 'effect', phase: record.phase, operation: record.operation, move: record.move,
			source: canonicalHolder(record.source), target: canonicalHolder(record.target),
			applied: record.applied,
		};
		if (record.operation === 'boost') {
			return {...common, stat: record.stat, delta: record.delta, before: record.before, after: record.after};
		}
		if (record.operation === 'set-status' || record.operation === 'cure-status') {
			return {...common, status: record.status, before: record.before, after: record.after};
		}
		if (record.operation === 'direct-heal') {
			return {
				...common, basis: record.basis, damage_basis: record.damageBasis,
				numerator: record.numerator, denominator: record.denominator,
				requested: record.requested, hp_before: record.hpBefore,
				hp_after: record.hpAfter, amount: record.amount,
			};
		}
		if (record.operation === 'crash-damage') {
			return {
				...common, basis: record.basis, damage_basis: record.damageBasis,
				critical: record.critical, damage_roll: record.damageRoll,
				numerator: record.numerator, denominator: record.denominator,
				minimum: record.minimum, cap_numerator: record.capNumerator,
				cap_denominator: record.capDenominator, cap_value: record.capValue,
				requested: record.requested,
				damage_target: canonicalHolder(record.damageTarget),
				hp_before: record.hpBefore, hp_after: record.hpAfter, amount: record.amount,
			};
		}
		if (record.operation === 'prevent-recoil') {
			return {
				...common, cause: record.cause, requested: record.requested,
				...(record.damageTarget ? {damage_target: canonicalHolder(record.damageTarget)} : {}),
			};
		}
		if (record.operation === 'multihit-plan') {
			return {...common, requested: record.requested};
		}
		if (record.operation === 'multihit-hit') {
			return {
				...common, requested: record.requested, ordinal: record.ordinal,
				critical: record.critical, damage_roll: record.damageRoll, damage: record.damage,
				target_hp_after: record.targetHPAfter, source_hp_after: record.sourceHPAfter,
			};
		}
		if (record.operation === 'multihit-result') {
			return {
				...common, requested: record.requested, actual: record.actual,
				stop_reason: record.stopReason,
			};
		}
		if (record.operation === 'fixed-damage') {
			return {
				...common, formula: record.formula, resolved: Math.trunc(record.resolved),
			};
		}
		if (record.operation === 'variable-power') {
			return {
				...common, formula: record.formula, ratio: record.ratio,
				bracket: record.bracket, resolved: record.resolved,
			};
		}
		return {
			...common, cause: record.cause, damage_target: canonicalHolder(record.damageTarget),
			damage_basis: record.damageBasis, numerator: record.numerator,
			denominator: record.denominator, requested: record.requested,
			hp_before: record.hpBefore, hp_after: record.hpAfter, amount: record.amount,
		};
	});
}

function handlersBetween(afterSequence, throughSequence) {
	const records = battle.verificationTrace.filter(record =>
		record.sequence > afterSequence && record.sequence < throughSequence);
	const hasRecoilEffect = records.some(record => record.kind === 'effect' &&
		record.move === 'doubleedge' && ['recoil', 'prevent-recoil'].includes(record.operation));
	const discovered = records.filter(record => record.kind === 'handlers' &&
		(record.event !== 'Update' || afterSequence >= 0) &&
			(record.event === 'TryHit' || record.event === 'SetStatus' || record.event === 'AfterSetStatus' || record.event === 'ModifyAtk' || record.event === 'ModifyDef' || record.event === 'ModifySpA' || record.event === 'ModifySpD' || record.event === 'ModifySpe' || record.event === 'ModifyBoost' || record.event === 'NegateImmunity' || record.event === 'Accuracy' || record.event === 'ModifyAccuracy' ||
			record.event === 'AfterMove' ||
			record.event === 'TryMove' ||
			record.event === 'TryHeal' ||
			record.event === 'Invulnerability' ||
			record.event === 'DamagingHit' ||
			record.event === 'ModifyCritRatio' || record.event === 'CriticalHit' ||
			record.event === 'WeatherModifyDamage' ||
			record.event === 'WeatherChange' ||
			record.event === 'ModifyDamage' ||
			record.event === 'BasePower' ||
			record.event === 'Residual' ||
			record.event === 'SwitchIn' ||
			record.event === 'SwitchOut' ||
			record.event === 'BeforeSwitchOut' ||
			record.event === 'DragOut' ||
			record.event === 'DeductPP' ||
			record.event === 'Update' ||
			record.event === 'TryEatItem' ||
			record.event === 'TryBoost' || record.event === 'TryPrimaryHit' ||
			record.event === 'PrepareHit' ||
			record.event === 'BeforeMove' ||
			record.event === 'DisableMove' ||
			record.event === 'OverrideAction' ||
			record.event === 'MoveAborted' ||
			record.event === 'AfterMoveSecondarySelf' ||
			record.event === 'LockMove' ||
			record.event === 'TrapPokemon' ||
			record.event === 'EntryHazard' ||
			record.event === 'Faint' ||
			record.event === 'ModifySecondaries' ||
			record.event === 'ModifyMove' ||
			record.event === 'TryAddVolatile' || record.event === 'Hit' ||
			record.event === 'Immunity' ||
			record.event === 'Damage')).flatMap(record =>
		record.handlers.filter(handler =>
			(record.event !== 'TryHeal' || handler.effect === 'liquidooze') &&
			(record.event !== 'Damage' ||
			 (handler.effect === 'falseswipe' &&
			  record.sourceEffect?.effectType === 'Move') ||
				 ['counter', 'mirrorcoat', 'bide'].includes(handler.effect) ||
			 (handler.effect === 'endure' && handler.ownerScope === 'volatile' &&
			  record.sourceEffect?.effectType === 'Move') ||
			 handler.effect === 'focusband' ||
			 (handler.effect === 'rockhead' &&
			  (record.sourceEffect?.effectType === 'Move' || hasRecoilEffect))) &&
			(record.event !== 'SetStatus' || handler.effect === 'safeguard') &&
			(record.event !== 'BasePower' ||
				 ['solarbeam', 'bounce', 'blaze', 'overgrow', 'swarm', 'torrent', 'thickfat', 'facade', 'mudsport', 'watersport', 'charge'].includes(handler.effect)) &&
			(record.event !== 'ModifyDamage' || ['fly', 'dig', 'dive', 'minimize'].includes(handler.effect)) &&
			(record.event !== 'BeforeMove' || handler.ownerScope === 'volatile' ||
				(handler.ownerScope === 'ability' && handler.effect === 'truant') ||
				(handler.ownerScope === 'status' && ['slp', 'par', 'frz'].includes(handler.effect))) &&
			(record.event !== 'BeforeSwitchOut' || handler.effect === 'pursuit') &&
			(record.event !== 'ModifyMove' ||
				(handler.ownerScope === 'status' && handler.effect === 'frz') ||
				(handler.ownerScope === 'item' && handler.effect === 'kingsrock' &&
				 fixtureItemIDs.has('kingsrock'))) &&
			(record.event !== 'AfterMoveSecondarySelf' ||
				(handler.ownerScope === 'item' && handler.effect === 'shellbell' &&
				 fixtureItemIDs.has('shellbell'))) &&
			(record.event !== 'SwitchIn' ||
				(handler.ownerScope === 'status' && ['slp', 'tox'].includes(handler.effect)) ||
				['whiteherb', 'truant'].includes(handler.effect)) &&
			(record.event !== 'Update' || handler.effectType === 'Item' ||
			 ['owntempo', 'oblivious', 'immunity', 'insomnia', 'vitalspirit',
			  'limber', 'waterveil', 'magmaarmor'].includes(handler.effect)) &&
			(record.event !== 'Immunity' ||
			 ['oblivious', 'dig', 'dive'].includes(handler.effect)) &&
			(record.event !== 'Residual' || ['Ability', 'Item'].includes(handler.effectType) ||
				(handler.effectType === 'Condition' && handler.ownerScope === 'volatile' &&
				 (battle.dex.conditions.get(handler.effect).onResidual !== undefined ||
				  (handler.effect !== 'mustrecharge' &&
				   battle.dex.conditions.get(handler.effect).onLockMove !== undefined) ||
				  handler.effect === 'partiallytrapped')))).map(handler => ({
				event: record.event === 'TryHit' ? 'try-hit' :
				record.event === 'TryMove' ? 'try-move' :
				record.event === 'TryHeal' ? 'try-heal' :
				record.event === 'Invulnerability' ? 'invulnerability' :
				record.event === 'DamagingHit' ? 'damaging-hit' :
				record.event === 'SetStatus' ? 'set-status' :
				record.event === 'AfterSetStatus' ? 'after-set-status' :
				record.event === 'AfterMove' ? 'after-move' :
				record.event === 'ModifyAtk' ? 'modify-atk' :
				record.event === 'ModifyDef' ? 'modify-def' :
				record.event === 'ModifySpA' ? 'modify-spa' :
				record.event === 'ModifySpD' ? 'modify-spd' :
				record.event === 'ModifySpe' ? 'modify-spe' :
				record.event === 'ModifyBoost' ? 'modify-boost' :
				record.event === 'NegateImmunity' ? 'negate-immunity' :
				record.event === 'Accuracy' ? 'accuracy' :
				record.event === 'ModifyAccuracy' ? 'modify-accuracy' :
				record.event === 'ModifyCritRatio' ? 'modify-crit-ratio' :
				record.event === 'CriticalHit' ? 'critical-hit' :
				record.event === 'Residual' ? 'residual' :
				record.event === 'SwitchIn' ? 'switch-in' :
				record.event === 'SwitchOut' ? 'switch-out' :
				record.event === 'BeforeSwitchOut' ? 'before-switch-out' :
				record.event === 'DragOut' ? 'drag-out' :
				record.event === 'DeductPP' ? 'deduct-pp' :
				record.event === 'Update' ? 'update' :
				record.event === 'TryEatItem' ? 'try-eat-item' :
				record.event === 'WeatherModifyDamage' ? 'weather-modify-damage' :
				record.event === 'WeatherChange' ? 'weather-change' :
				record.event === 'ModifyDamage' ? 'modify-damage' :
				record.event === 'BasePower' ? 'base-power' :
			record.event === 'TryBoost' ? 'try-boost' :
				record.event === 'PrepareHit' ? 'prepare-hit' :
				record.event === 'BeforeMove' ? 'before-move' :
				record.event === 'DisableMove' ? 'disable-move' :
				record.event === 'OverrideAction' ? 'override-action' :
				record.event === 'MoveAborted' ? 'move-aborted' :
				record.event === 'LockMove' ? 'lock-move' :
				record.event === 'TrapPokemon' ? 'trap-pokemon' :
				record.event === 'EntryHazard' ? 'entry-hazard' :
				record.event === 'Faint' ? 'faint' :
				record.event === 'ModifySecondaries' ? 'modify-secondaries' :
				record.event === 'ModifyMove' ? 'modify-move' :
				record.event === 'AfterMoveSecondarySelf' ?
					'after-move-secondary-self' :
				record.event === 'AfterMove' ? 'after-move' :
				record.event === 'TryAddVolatile' ? 'try-add-volatile' :
				record.event === 'Immunity' ? 'immunity' :
				record.event === 'Hit' ? 'hit' :
				record.event === 'TryPrimaryHit' ? 'try-primary-hit' : 'damage',
			source_kind: handler.effectType.toLowerCase(),
			source_id: handler.effect,
			holder: canonicalEventHolder(handler.holder),
			order: handler.order === false ? null : handler.order,
			priority: handler.priority,
			sub_order: handler.subOrder,
			effect_order: handler.effectOrder === undefined ? null : handler.effectOrder,
			speed: record.event === 'ModifySpe' ? null :
				(handler.speed === undefined ? null :
					record.event === 'SwitchIn' ? Math.ceil(handler.speed) : handler.speed),
			sequence: record.sequence,
		})));
	const lifecycle = records.filter(record => record.kind === 'single-handler' &&
		 (((record.event === 'ModifyType' || record.event === 'ModifyMove' ||
		   record.event === 'BasePower' || record.event === 'MoveFail' ||
		   record.event === 'UseMoveMessage' ||
		   record.event === 'Try' || record.event === 'TryMove' ||
		   record.event === 'TryImmunity' || record.event === 'TryHit' ||
		   record.event === 'AfterSubDamage' || record.event === 'AfterMove') &&
		  record.effectType === 'Move' &&
		  (record.event !== 'BasePower' || record.effect === 'beatup' || record.effect === 'furycutter' || record.effect === 'spitup' || record.effect === 'revenge' ||
		   battle.dex.conditions.get(record.effect).onLockMove === record.effect) &&
		  (record.event !== 'MoveFail' ||
		   ['jumpkick', 'highjumpkick'].includes(record.effect)) &&
		  (record.event !== 'Try' || ['endeavor', 'rest', 'snore', 'fakeout', 'followme', 'counter', 'mirrorcoat', 'teleport', 'sleeptalk', 'stockpile', 'spitup', 'swallow', 'focuspunch'].includes(record.effect)) &&
		  (record.event !== 'TryMove' || [
			  'solarbeam', 'fly', 'bounce', 'dig', 'dive', 'razorwind',
			  'skullbash', 'skyattack', 'endeavor',
		  ].includes(record.effect)) &&
		  (record.event !== 'TryHit' || [
			  'disable', 'yawn', 'brickbreak', 'roleplay', 'lockon', 'mindreader',
			  'foresight', 'odorsleuth', 'curse',
		  ].includes(record.effect)) &&
		  (record.event !== 'TryImmunity' || record.effect === 'dreameater') &&
		  (record.event !== 'AfterSubDamage' || record.effect === 'rapidspin') &&
		  (record.event !== 'AfterMove' || record.effect === 'spitup')) ||
		 (record.event === 'Hit' && record.effectType === 'Move' &&
		  ['refresh', 'psychup', 'rest', 'aromatherapy', 'healbell', 'roleplay', 'skillswap', 'metronome', 'assist', 'naturepower', 'sleeptalk', 'mimic', 'sketch', 'conversion2', 'spite', 'camouflage', 'conversion', 'curse', 'transform', 'smellingsalts', 'bellydrum',
		   'block', 'meanlook', 'spiderweb', 'furycutter', 'swallow', 'painsplit'].includes(record.effect)) ||
		 (record.event === 'HitField' && record.effectType === 'Move' &&
		  (record.effect === 'haze' || record.effect === 'perishsong')) ||
		 (record.event === 'Start' || record.event === 'Restart' || record.event === 'End' ||
		  record.event === 'SideStart' || record.event === 'SideRestart') &&
		 record.effect !== 'mustrecharge' &&
		 ((record.effect === 'spikes') ||
		  (record.event === 'Start' && record.effectType === 'Status' &&
		   ['brn', 'psn', 'tox'].includes(record.effect)) ||
		  (((record.effectType === 'Condition') ||
		  (record.effectType === 'Status' && ['slp', 'par', 'frz'].includes(record.effect))) &&
		  (battle.dex.conditions.get(record.effect).onBeforeMove !== undefined ||
		   battle.dex.conditions.get(record.effect).onDisableMove !== undefined ||
		   record.effect === 'focusenergy' || record.effect === 'charge' ||
		   record.effect === 'leechseed' || record.effect === 'flashfire' ||
		   record.effect === 'foresight' ||
		   record.effect === 'perishsong' ||
		   record.effect === 'yawn' ||
		   record.effect === 'trapped' ||
		   record.effect === 'ingrain' || record.effect === 'pursuit' ||
		   record.effect === 'counter' || record.effect === 'mirrorcoat' ||
		   record.effect === 'focuspunch' ||
		   record.effect === 'furycutter' ||
		   record.effect === 'defensecurl' || record.effect === 'minimize' ||
		   record.effect === 'stockpile' ||
		   record.effect === 'curse' ||
		   battle.dex.conditions.get(record.effect).onLockMove !== undefined) ||
		  record.effect === 'cloudnine' || record.effect === 'sandstream' ||
		  record.effect === 'forecast' ||
		  (record.effectType === 'Ability' && record.effect === 'flashfire') ||
		  record.effect === 'pressure' || record.effect === 'intimidate' ||
		  record.effect === 'trace' || record.effect === 'whiteherb')) ||
		 (record.event === 'Eat' && fixtureItemIDs.has(record.effect)))).map(record => ({
		event: record.event === 'SideStart' ? 'start' :
			record.event === 'SideRestart' ? 'restart' :
			record.event === 'Eat' ? 'eat' :
			record.event === 'ModifyType' ? 'modify-type' :
			record.event === 'ModifyMove' ? 'modify-move' :
			record.event === 'BasePower' ? 'base-power' :
			record.event === 'MoveFail' ? 'move-fail' :
			record.event === 'BeforeSwitchOut' ? 'before-switch-out' :
			record.event === 'UseMoveMessage' ? 'use-move-message' :
			record.event === 'Try' ? 'try' :
			record.event === 'TryMove' ? 'try-move' :
			record.event === 'TryImmunity' ? 'try-immunity' :
			record.event === 'TryHit' ? 'try-hit' :
			record.event === 'AfterSubDamage' ? 'after-sub-damage' :
			record.event === 'AfterMove' ? 'after-move' :
			record.event === 'AfterMoveSecondarySelf' ?
				'after-move-secondary-self' :
			record.event === 'HitField' ? 'hit-field' : record.event.toLowerCase(),
		source_kind: record.effect === 'spikes' ? 'condition' :
			record.effectType.toLowerCase(), source_id: record.effect,
		holder: canonicalEventHolder(record.holder), order: null,
		priority: record.priority, sub_order: record.subOrder,
		effect_order: record.event === 'Eat' ? null :
			(record.effectOrder === undefined ? null : record.effectOrder),
		/* singleEvent lifecycle callbacks are not speed-ordered; exposing a
		 * cached pre/post-mutation speed would make observer timing semantic. */
		speed: ['Start', 'Restart', 'End'].includes(record.event) ? null :
			(record.speed === undefined ? null : record.speed),
		sequence: record.sequence,
	}));
	return [...discovered, ...lifecycle].sort((left, right) =>
		left.sequence - right.sequence).map(({sequence, ...handler}) => handler);
}

function modifiersBetween(afterSequence, throughSequence) {
	const interval = battle.verificationTrace.filter(record =>
		record.sequence > afterSequence && record.sequence < throughSequence);
	const hasProjectedBasePower = interval.some(record => record.kind === 'modifier' &&
		record.event === 'BasePower' && record.phase === 'handler' &&
		(['bounce', 'blaze', 'overgrow', 'swarm', 'torrent', 'thickfat', 'facade', 'mudsport', 'watersport', 'charge', 'beatup', 'furycutter', 'spitup', 'revenge'].includes(record.effect) ||
		 battle.dex.conditions.get(record.effect).onLockMove === record.effect));
	return interval.filter(record =>
		(record.kind === 'modifier' || record.kind === 'damage-stage') &&
		(record.kind !== 'modifier' || record.event === 'BasePower' || record.event === 'ModifyAtk' || record.event === 'ModifyDef' || record.event === 'ModifySpA' || record.event === 'ModifySpD' || record.event === 'ModifySpe' || record.event === 'ModifyAccuracy' ||
			record.event === 'ModifyCritRatio' ||
			record.event === 'ModifyDamage' ||
			record.event === 'WeatherModifyDamage') &&
		(record.kind !== 'modifier' || record.event !== 'BasePower' ||
			(record.phase === 'handler' ?
				(['bounce', 'blaze', 'overgrow', 'swarm', 'torrent', 'thickfat', 'facade', 'mudsport', 'watersport', 'charge', 'beatup', 'furycutter', 'spitup', 'revenge'].includes(record.effect) ||
				 battle.dex.conditions.get(record.effect).onLockMove === record.effect) :
				hasProjectedBasePower))).map(record => {
		if (record.kind === 'damage-stage') {
			return {
				kind: 'damage-stage',
				stage: record.stage,
				source: canonicalHolder(record.source),
				target: canonicalHolder(record.target),
				move: record.move,
				before: record.before,
				after: record.after,
				multiplier_q12: record.multiplierQ12,
				applied: record.applied,
				reason: record.reason,
			};
		}
		if (record.phase === 'handler') {
			return {
				kind: 'relay-handler',
				event: record.event === 'BasePower' ? 'base-power' :
					record.event === 'ModifyAtk' ? 'modify-atk' :
					record.event === 'ModifyDef' ? 'modify-def' :
					record.event === 'ModifySpA' ? 'modify-spa' :
					record.event === 'ModifySpD' ? 'modify-spd' :
					record.event === 'ModifySpe' ? 'modify-spe' :
					record.event === 'ModifyAccuracy' ? 'modify-accuracy' :
					record.event === 'ModifyCritRatio' ? 'modify-crit-ratio' :
					record.event === 'ModifyDamage' ? 'modify-damage' :
					'weather-modify-damage',
				source_kind: record.effectType.toLowerCase(),
				source_id: record.effect,
				holder: canonicalEventHolder(record.holder),
				relay: record.relay,
				modifier_q12_before: record.modifierQ12Before,
				modifier_q12_after: record.modifierQ12After,
			};
		}
		return {
			kind: 'relay-result',
			event: record.event === 'BasePower' ? 'base-power' :
				record.event === 'ModifyAtk' ? 'modify-atk' :
				record.event === 'ModifyDef' ? 'modify-def' :
				record.event === 'ModifySpA' ? 'modify-spa' :
				record.event === 'ModifySpD' ? 'modify-spd' :
				record.event === 'ModifySpe' ? 'modify-spe' :
				record.event === 'ModifyAccuracy' ? 'modify-accuracy' :
				record.event === 'ModifyCritRatio' ? 'modify-crit-ratio' :
				record.event === 'ModifyDamage' ? 'modify-damage' :
					'weather-modify-damage',
			relay: record.relay,
			modifier_q12: record.modifierQ12After,
			result: record.result,
		};
	});
}

function immunitiesBeforeAccuracy(afterSequence, throughSequence) {
	const records = battle.verificationTrace.filter(record =>
		record.sequence > afterSequence && record.sequence < throughSequence);
	const result = [];
	let pending = null;
	let pendingHadAccuracyHandler = false;
	let moveFrame = null;
	const appendPending = () => {
		if (!pending) return;
		result.push({
			attack_type: recordTypeID(pending.attackType),
			target: canonicalHolder(pending.target), result: pending.result,
			effect: pending.effect || null,
		});
		pending = null;
		pendingHadAccuracyHandler = false;
	};
	for (const record of records) {
		if (record.kind === 'active-move-frame' && record.event === 'ModifyMove') {
			if (pending && moveFrame?.accuracy === true && moveFrame.category !== 'Status') appendPending();
			moveFrame = record;
		}
		if (record.kind === 'immunity') {
			if (pending && pending.move?.id !== record.move?.id) {
				if (pending.move?.category !== 'Status' &&
					(pending.move?.accuracy === true || pendingHadAccuracyHandler)) {
					appendPending();
				} else {
					pending = null;
					pendingHadAccuracyHandler = false;
				}
			}
			pending = record;
		}
		if (record.kind === 'handlers' && record.event === 'Accuracy' &&
			record.handlers.some(handler => handler.effect === 'lockon')) {
			pendingHadAccuracyHandler = true;
		}
		if (record.kind === 'prng' && record.label === 'move.accuracy') {
			if (record.moveCategory === 'Status') {
				pending = null;
				continue;
			}
			if (!pending) {
				if (record.move === 'struggle') continue;
				// Selected Gen 3 Bide is Physical with numeric accuracy, but it
				// targets its user and only installs the storage condition. Its
				// later constructed release has an ordinary target-immunity record
				// and therefore reaches appendPending above instead of this branch.
				if (record.move === 'bide') continue;
				// Gen 3 Beat Up rewrites itself to the typeless "???" type.
				// Pokemon.runImmunity returns true before the observer's typed
				// immunity decision boundary, so accuracy legitimately has no
				// preceding immunity record.
				if (record.move === 'beatup') continue;
				// Gen 3's delayed attacks carry ignoreImmunity in their stored
				// move data, so Pokemon.runImmunity intentionally emits no
				// decision before the expiry-time accuracy draw.
				if (record.move === 'futuresight' || record.move === 'doomdesire') continue;
				throw new Error(`damaging move ${record.move || 'unknown'} accuracy draw has no preceding immunity decision`);
			}
			appendPending();
		}
	}
	if (pending && pending.move?.category !== 'Status' &&
		(pending.move?.accuracy === true ||
		 moveFrame?.accuracy === true || pendingHadAccuracyHandler)) {
		appendPending();
	}
	return result;
}

function recordTypeID(type) {
	return String(type).toLowerCase().replace(/[^a-z0-9]+/g, '');
}

function numericSeed(seed) {
	const values = Array.isArray(seed) ? seed : String(seed).split(',');
	if (values.length !== 4) throw new Error(`unsupported PRNG seed: ${seed}`);
	const numeric = values.map(Number);
	if (numeric.some(value => !Number.isInteger(value) || value < 0 || value > 0xFFFF)) {
		throw new Error(`invalid Gen 5 PRNG seed: ${seed}`);
	}
	return numeric;
}

for (const pair of fixture.source_choices) battle.makeChoices(pair[0] || '', pair[1] || '');
const decisions = battle.verificationTrace.filter(record => record.kind === 'decision');
const queues = battle.verificationTrace.filter(record => record.kind === 'queue');
const expectedDecisionCount = fixture.choices.length + (battle.ended ? 0 : 1);
if (decisions.length !== expectedDecisionCount) {
	throw new Error(`expected ${expectedDecisionCount} request records, observed ${decisions.length}`);
}
if (queues.length !== fixture.choices.length) {
	throw new Error(`expected ${fixture.choices.length} queue records, observed ${queues.length}`);
}
const transitions = queues.map((record, index) =>
	canonicalTransition(record, decisions[index].state, decisions[index].request));
for (let index = 0; index < transitions.length; index++) {
	const observed = JSON.stringify(transitions[index].choices);
	const expected = JSON.stringify(expectedChoices(fixture.choices[index]));
	if (observed !== expected) {
		throw new Error(`choice normalization diverged at transition ${index}: expected ${expected}, observed ${observed}`);
	}
}

for (const forced of fixture.forced_outcomes) {
	const matches = battle.verificationTrace.filter(record => record.kind === 'prng')
		.map(canonicalPrngRecord).filter(record => record.label === forced.label);
	const record = matches[forced.occurrence - 1];
	if (!record || record.from !== forced.range || record.result !== forced.result) {
		throw new Error(`forced outcome ${forced.label}:${forced.occurrence} was not reproduced by the case seed`);
	}
}

if (process.env.PS_GEN3_DUMP_RAW_TRACE === '1') {
	process.stderr.write(`${JSON.stringify(battle.verificationTrace)}\n`);
}

let priorState = decisions[0].state;
let priorSequence = -1;
for (const record of decisions) {
	const transition = record.ordinal === 0 ? {choices: [], queue: []} : transitions[record.ordinal - 1];
	const output = {
		schema: 'pokemon-native-slice-boundary-v1',
		case_id: fixture.id,
		boundary: record.ordinal,
		request: requests(record.request, record.state),
		choices: transition.choices,
		queue: transition.queue,
		handlers: handlersBetween(priorSequence, record.sequence),
		conditions: conditionsBetween(priorSequence, record.sequence),
		effects: effectsBetween(priorSequence, record.sequence),
		immunity: immunitiesBeforeAccuracy(priorSequence, record.sequence),
		modifiers: modifiersBetween(priorSequence, record.sequence),
		state: projectState(record.state),
		events: protocolEvents(record.protocol, priorState),
		prng: prngBetween(priorSequence, record.sequence),
	};
	process.stdout.write(`${JSON.stringify(output)}\n`);
	priorState = record.state;
	priorSequence = record.sequence;
}

if (battle.ended) {
	const terminalState = liveState();
	const terminalEvents = battle.log.slice(battle.verificationProtocolCursor)
		.filter(line => line && !line.startsWith('|t:|'));
	const transition = transitions[transitions.length - 1];
	process.stdout.write(`${JSON.stringify({
		schema: 'pokemon-native-slice-boundary-v1',
		case_id: fixture.id,
		boundary: decisions.length,
		request: [{kind: 'terminal', legal: []}, {kind: 'terminal', legal: []}],
		choices: transition.choices,
		queue: transition.queue,
		handlers: handlersBetween(priorSequence, Number.POSITIVE_INFINITY),
		conditions: conditionsBetween(priorSequence, Number.POSITIVE_INFINITY),
		effects: effectsBetween(priorSequence, Number.POSITIVE_INFINITY),
		immunity: immunitiesBeforeAccuracy(priorSequence, Number.POSITIVE_INFINITY),
		modifiers: modifiersBetween(priorSequence, Number.POSITIVE_INFINITY),
		state: projectState(terminalState, true),
		events: protocolEvents(terminalEvents, priorState),
		prng: prngBetween(priorSequence, Number.POSITIVE_INFINITY),
	})}\n`);
}

battle.destroy();
