'use strict';

process.env.PS_GEN3_VERIFY_TRACE = '1';
const showdownDir = process.env.POKEMON_SHOWDOWN_DIR || '/opt/pokemon-showdown';
const common = require(`${showdownDir}/test/common`).gen(3);
const {Teams} = require(showdownDir);

const battle = common.createBattle({ seed: 'gen5,0001000200030004' }, [[
	{ species: 'Snorlax', ability: 'Immunity', item: 'Leftovers', moves: ['Earthquake'] },
], [
	{ species: 'Gengar', ability: 'Levitate', item: 'Leftovers', moves: ['Thunderbolt'] },
]]);
battle.makeChoices('move 1', 'move 1');

const trace = battle.verificationTrace;
if (!Array.isArray(trace)) throw new Error('trace not enabled');
if (!trace.some(record => record.kind === 'handlers')) throw new Error('handler records missing');
if (!trace.some(record => record.kind === 'immunity' && record.attackType === 'Ground' &&
	record.result === 'ability' && record.effect === 'levitate')) {
	throw new Error('Levitate immunity record missing');
}
if (!trace.some(record => record.kind === 'prng')) throw new Error('PRNG records missing');
for (let i = 0; i < trace.length; i++) {
	if (trace[i].sequence !== i) throw new Error('trace sequence is not contiguous');
}

const modifierBattle = common.createBattle({ seed: 'gen5,0001000200030004' }, [[
	{ species: 'Machamp', ability: 'Guts', item: 'Black Belt', moves: ['Mach Punch'] },
], [
	{ species: 'Snorlax', ability: 'Immunity', moves: ['Splash'] },
]]);
const gutsUser = modifierBattle.p1.active[0];
gutsUser.status = 'brn';
gutsUser.statusState = modifierBattle.initEffectState({id: 'brn', target: gutsUser});
modifierBattle.makeChoices('move 1', 'move 1');
const modifierTrace = modifierBattle.verificationTrace;
if (!modifierTrace.some(record => record.kind === 'modifier' && record.phase === 'handler' &&
	record.effect === 'guts' && record.modifierQ12Before === 4096 && record.modifierQ12After === 6144)) {
	throw new Error('Guts modifier step missing');
}
if (!modifierTrace.some(record => record.kind === 'modifier' && record.phase === 'handler' &&
	record.effect === 'blackbelt' && record.modifierQ12Before === 6144 && record.modifierQ12After === 6758)) {
	throw new Error('Black Belt modifier step missing');
}
if (!modifierTrace.some(record => record.kind === 'damage-stage' && record.stage === 'burn' &&
	!record.applied && record.reason === 'guts' && record.before === record.after)) {
	throw new Error('Guts burn suppression record missing');
}

const burnBattle = common.createBattle({ seed: 'gen5,0001000200030004' }, [[
	{ species: 'Machamp', ability: 'No Guard', moves: ['Mach Punch'] },
], [
	{ species: 'Snorlax', ability: 'Immunity', moves: ['Splash'] },
]]);
const burnedUser = burnBattle.p1.active[0];
burnedUser.status = 'brn';
burnedUser.statusState = burnBattle.initEffectState({id: 'brn', target: burnedUser});
burnBattle.makeChoices('move 1', 'move 1');
const burnTrace = burnBattle.verificationTrace;
if (!burnTrace.some(record => record.kind === 'damage-stage' && record.stage === 'burn' &&
	record.applied && record.reason === 'applied' && record.after < record.before)) {
	throw new Error('applied burn damage-stage record missing');
}

const protectBattle = common.createBattle({ seed: 'gen5,0001000200030004' }, [[
	{ species: 'Skarmory', ability: 'Sturdy', moves: ['Protect', 'Splash'] },
], [
	{ species: 'Snorlax', ability: 'Immunity', moves: ['Tackle'] },
]]);
protectBattle.makeChoices('move 1', 'move 1');
protectBattle.makeChoices('move 1', 'move 1');
const protectTrace = protectBattle.verificationTrace;
if (!protectTrace.some(record => record.kind === 'condition' && record.phase === 'add' &&
	record.effect === 'protect' && record.durationAfter === 1)) {
	throw new Error('Protect lifecycle add missing');
}
if (!protectTrace.some(record => record.kind === 'condition' && record.phase === 'add' &&
	record.effect === 'stall' && record.counterAfter === 2)) {
	throw new Error('Protect stall counter initialization missing');
}
if (!protectTrace.some(record => record.kind === 'prng' && record.label === 'stall.success' &&
	record.draw.from === 2)) {
	throw new Error('Protect repeated-use PRNG missing');
}

const reflectBattle = common.createBattle({ seed: 'gen5,0001000200030004' }, [[
	{ species: 'Alakazam', ability: 'Synchronize', moves: ['Reflect'] },
], [
	{ species: 'Snorlax', ability: 'Immunity', moves: ['Tackle'] },
]]);
reflectBattle.makeChoices('move 1', 'move 1');
const reflectTrace = reflectBattle.verificationTrace;
if (!reflectTrace.some(record => record.kind === 'condition' && record.phase === 'add' &&
	record.effect === 'reflect' && record.durationAfter === 5)) {
	throw new Error('Reflect lifecycle add missing');
}
if (!reflectTrace.some(record => record.kind === 'modifier' && record.phase === 'handler' &&
	record.event === 'ModifyDamagePhase1' && record.effect === 'reflect' &&
	record.modifierQ12After === 2048)) {
	throw new Error('Reflect modifier step missing');
}

const toxicBattle = common.createBattle({ seed: 'gen5,0001000200030004' }, [[
	{ species: 'Alakazam', ability: 'Synchronize', moves: ['Splash'] },
], [
	{ species: 'Machamp', ability: 'Guts', moves: ['Splash'] },
]]);
toxicBattle.p2.active[0].setStatus('tox', toxicBattle.p1.active[0]);
toxicBattle.makeChoices('move 1', 'move 1');
const toxicTrace = toxicBattle.verificationTrace;
if (!toxicTrace.some(record => record.kind === 'condition' && record.phase === 'residual-execute' &&
	record.effect === 'tox' && record.order === 10 && record.subOrder === 6 &&
	record.stageBefore === 0 && record.stageAfter === 1)) {
	throw new Error('Toxic residual staging missing');
}
if (!toxicTrace.some(record => record.kind === 'condition' && record.phase === 'damage' &&
	record.effect === 'tox' && record.amount > 0)) {
	throw new Error('Toxic residual damage missing');
}

const sandBattle = common.createBattle({ seed: 'gen5,0001000200030004' }, [[
	{ species: 'Mew', ability: 'Synchronize', moves: ['Sandstorm', 'Splash'] },
], [
	{ species: 'Machamp', ability: 'Guts', moves: ['Splash'] },
]]);
sandBattle.makeChoices('move 1', 'move 1');
for (let turn = 0; turn < 4; turn++) sandBattle.makeChoices('move 2', 'move 1');
const sandTrace = sandBattle.verificationTrace;
if (!sandTrace.some(record => record.kind === 'condition' && record.phase === 'residual-discover' &&
	record.effect === 'sandstorm' && record.order === 8)) {
	throw new Error('Sandstorm residual ordering missing');
}
if (!sandTrace.some(record => record.kind === 'condition' && record.phase === 'damage' &&
	record.effect === 'sandstorm' && record.amount > 0)) {
	throw new Error('Sandstorm residual damage missing');
}
if (!sandTrace.some(record => record.kind === 'condition' && record.phase === 'remove' &&
	record.effect === 'sandstorm' && record.durationBefore === 0)) {
	throw new Error('Sandstorm expiry missing');
}

const effectBattle = common.createBattle({ seed: 'gen5,0001000200030004' }, [[
	{ species: 'Machamp', ability: 'No Guard', moves: ['Swords Dance', 'Refresh', 'Body Slam'] },
], [
	{ species: 'Mew', ability: 'Synchronize', moves: ['Will-O-Wisp', 'Splash'] },
]]);
effectBattle.onEvent('Accuracy', effectBattle.format, true);
effectBattle.makeChoices('move 1', 'move 1');
effectBattle.makeChoices('move 2', 'move 2');
effectBattle.makeChoices('move 3', 'move 2');
const effectTrace = effectBattle.verificationTrace;
if (!effectTrace.some(record => record.kind === 'effect' && record.phase === 'primary' &&
	record.operation === 'boost' && record.move === 'swordsdance' && record.stat === 'atk' &&
	record.before === 0 && record.after === 2 && record.applied)) {
	throw new Error('primary boost effect record missing');
}
if (!effectTrace.some(record => record.kind === 'effect' && record.phase === 'primary' &&
	record.operation === 'set-status' && record.move === 'willowisp' && record.status === 'brn' &&
	record.before === null && record.after === 'brn' && record.applied)) {
	throw new Error('primary status effect record missing');
}
if (!effectTrace.some(record => record.kind === 'effect' && record.phase === 'primary' &&
	record.operation === 'cure-status' && record.move === 'refresh' && record.status === 'brn' &&
	record.before === 'brn' && record.after === null && record.applied)) {
	throw new Error('status cure effect record missing');
}
if (!effectTrace.some(record => record.kind === 'prng' && record.label === 'move.secondary' &&
	record.move === 'bodyslam' && record.draw.from === 100)) {
	throw new Error('secondary-effect PRNG record missing');
}

const recoilBattle = common.createBattle({ seed: 'gen5,0001000200030004' }, [[
	{ species: 'Snorlax', ability: 'Immunity', moves: ['Double-Edge'] },
], [
	{ species: 'Blissey', ability: 'Natural Cure', moves: ['Splash'] },
]]);
recoilBattle.makeChoices('move 1', 'move 1');
const recoilTrace = recoilBattle.verificationTrace;
if (!recoilTrace.some(record => record.kind === 'effect' && record.operation === 'recoil' &&
	record.move === 'doubleedge' && record.damageBasis > 0 && record.requested > 0 &&
	record.amount === record.hpBefore - record.hpAfter && record.applied)) {
	throw new Error('move recoil effect record missing');
}

const rockHeadBattle = common.createBattle({ seed: 'gen5,0001000200030004' }, [[
	{ species: 'Marowak', ability: 'Rock Head', moves: ['Double-Edge'] },
], [
	{ species: 'Blissey', ability: 'Natural Cure', moves: ['Splash'] },
]]);
rockHeadBattle.makeChoices('move 1', 'move 1');
const rockHeadTrace = rockHeadBattle.verificationTrace;
if (!rockHeadTrace.some(record => record.kind === 'handlers' && record.event === 'Damage' &&
	record.handlers.some(handler => handler.effect === 'rockhead'))) {
	throw new Error('Rock Head Damage handler discovery missing');
}
if (!rockHeadTrace.some(record => record.kind === 'effect' && record.operation === 'prevent-recoil' &&
	record.cause === 'rockhead' && record.move === 'doubleedge' && record.applied)) {
	throw new Error('Rock Head recoil prevention record missing');
}
if (!rockHeadTrace.some(record => record.kind === 'effect' && record.operation === 'recoil' &&
	record.move === 'doubleedge' && record.amount === 0 && !record.applied)) {
	throw new Error('prevented move recoil result missing');
}

const drainBattle = common.createBattle({ seed: 'gen5,0001000200030004' }, [[
	{ species: 'Venusaur', ability: 'Overgrow', moves: ['Giga Drain'] },
], [
	{ species: 'Blissey', ability: 'Natural Cure', moves: ['Seismic Toss'] },
]]);
drainBattle.makeChoices('move 1', 'move 1');
drainBattle.makeChoices('move 1', 'move 1');
const drainTrace = drainBattle.verificationTrace;
if (!drainTrace.some(record => record.kind === 'effect' && record.operation === 'drain' &&
	record.move === 'gigadrain' && record.damageBasis > 0 && record.requested > 0 &&
	record.amount === record.hpAfter - record.hpBefore && record.applied)) {
	throw new Error('move drain effect record missing');
}

const multiHitBattle = common.createBattle({ seed: 'gen5,0001000200030004' }, [[
	{ species: 'Marowak', ability: 'Rock Head', moves: ['Bone Rush'] },
], [
	{ species: 'Blissey', ability: 'Natural Cure', moves: ['Splash'] },
]]);
multiHitBattle.makeChoices('move 1', 'move 1');
const multiHitTrace = multiHitBattle.verificationTrace;
const multiHitPlan = multiHitTrace.find(record => record.kind === 'effect' &&
	record.operation === 'multihit-plan');
const multiHitResult = multiHitTrace.find(record => record.kind === 'effect' &&
	record.operation === 'multihit-result');
const multiHitHits = multiHitTrace.filter(record => record.kind === 'effect' &&
	record.operation === 'multihit-hit');
if (!multiHitTrace.some(record => record.kind === 'prng' &&
	record.label === 'move.multihit_count' && record.draw.from === 8)) {
	throw new Error('multi-hit count PRNG record missing');
}
if (!multiHitPlan || !multiHitResult || multiHitPlan.requested !== multiHitResult.requested ||
	multiHitResult.actual !== multiHitHits.length || multiHitResult.stopReason !== 'completed') {
	throw new Error('multi-hit plan/result records are inconsistent');
}
for (let index = 0; index < multiHitHits.length; index++) {
	const hit = multiHitHits[index];
	if (hit.ordinal !== index + 1 || typeof hit.critical !== 'boolean' ||
		hit.damageRoll === null || hit.damage <= 0) {
		throw new Error('multi-hit per-hit record is malformed');
	}
}

const fixedDamageBattle = common.createBattle({ seed: 'gen5,0001000200030004' }, [[
	{ species: 'Machamp', level: 90, ability: 'Guts', moves: ['Seismic Toss'] },
], [
	{ species: 'Blissey', ability: 'Natural Cure', moves: ['Splash'] },
]]);
fixedDamageBattle.makeChoices('move 1', 'move 1');
const fixedDamageTrace = fixedDamageBattle.verificationTrace;
if (!fixedDamageTrace.some(record => record.kind === 'effect' &&
	record.operation === 'fixed-damage' && record.formula === 'level' &&
	record.move === 'seismictoss' && record.resolved === 90)) {
	throw new Error('fixed level-damage formula record missing');
}
if (fixedDamageTrace.some(record => record.kind === 'prng' && record.move === 'seismictoss' &&
	['move.critical', 'move.damage_roll'].includes(record.label))) {
	throw new Error('fixed damage incorrectly consumed critical or damage-roll PRNG');
}

const variablePowerBattle = common.createBattle({ seed: 'gen5,0001000200030004' }, [[
	{ species: 'Machamp', ability: 'Guts', moves: ['Reversal'] },
], [
	{ species: 'Blissey', ability: 'Natural Cure', moves: ['Splash'] },
]]);
variablePowerBattle.makeChoices('move 1', 'move 1');
variablePowerBattle.p1.active[0].hp = 1;
variablePowerBattle.makeChoices('move 1', 'move 1');
const variablePowerTrace = variablePowerBattle.verificationTrace;
if (!variablePowerTrace.some(record => record.kind === 'effect' &&
	record.operation === 'variable-power' && record.formula === 'hp-bracket' &&
	record.move === 'reversal' && record.ratio === 48 && record.bracket === 5 && record.resolved === 20)) {
	throw new Error('full-HP Reversal formula record missing');
}
if (!variablePowerTrace.some(record => record.kind === 'effect' &&
	record.operation === 'variable-power' && record.formula === 'hp-bracket' &&
	record.move === 'reversal' && record.ratio === 1 && record.bracket === 0 && record.resolved === 200)) {
	throw new Error('low-HP Reversal formula record missing');
}
if (!variablePowerTrace.some(record => record.kind === 'prng' && record.move === 'reversal' &&
	record.label === 'move.critical') ||
	!variablePowerTrace.some(record => record.kind === 'prng' && record.move === 'reversal' &&
	record.label === 'move.damage_roll')) {
	throw new Error('variable power did not enter ordinary damage PRNG stages');
}

const team1 = Teams.import(`Starmie @ Leftovers
Ability: Natural Cure
- Surf
- Thunderbolt
- Ice Beam
- Recover

Skarmory (M) @ Leftovers
Ability: Sturdy
- Spikes
- Whirlwind
- Protect
- Toxic

Blissey (F) @ Leftovers
Ability: Natural Cure
- Soft-Boiled
- Seismic Toss
- Toxic
- Aromatherapy

Gengar (M) @ Leftovers
Ability: Levitate
- Thunderbolt
- Ice Punch
- Will-O-Wisp
- Explosion

Swampert (M) @ Leftovers
Ability: Torrent
- Earthquake
- Ice Beam
- Protect
- Toxic

Celebi @ Leftovers
Ability: Natural Cure
- Recover
- Psychic
- Leech Seed
- Heal Bell`);
const team2 = Teams.import(`Gengar (M) @ Leftovers
Ability: Levitate
- Thunderbolt
- Ice Punch
- Will-O-Wisp
- Explosion

Swampert (M) @ Leftovers
Ability: Torrent
- Earthquake
- Ice Beam
- Protect
- Toxic

Celebi @ Leftovers
Ability: Natural Cure
- Recover
- Psychic
- Leech Seed
- Heal Bell

Starmie @ Leftovers
Ability: Natural Cure
- Surf
- Thunderbolt
- Ice Beam
- Recover

Skarmory (M) @ Leftovers
Ability: Sturdy
- Spikes
- Whirlwind
- Protect
- Toxic

Blissey (F) @ Leftovers
Ability: Natural Cure
- Soft-Boiled
- Seismic Toss
- Toxic
- Aromatherapy`);
if (!team1 || !team2) throw new Error('fixture import failed');

const forced = common.createBattle({formatid: 'gen3ou', seed: [46, 42, 4, 0]}, [team1, team2]);
forced.makeChoices('switch 4', 'move 4');
forced.makeChoices('', 'switch 4');
const decisions = forced.verificationTrace.filter(record => record.kind === 'decision');
if (decisions.length !== 3) throw new Error(`expected 3 decision records, got ${decisions.length}`);
const observed = decisions.slice(1);
if (observed[0].ordinal !== 1 || observed[0].request[0].kind !== 'wait' ||
	observed[0].request[1].kind !== 'switch') {
	throw new Error('first forced-replacement boundary is malformed');
}
if (observed[1].ordinal !== 2 || observed[1].request.some(request => request.kind !== 'move')) {
	throw new Error('post-replacement boundary is malformed');
}

const crashBattle = common.createBattle({seed: [1, 2, 3, 2]}, [[
	{species: 'Smeargle', gender: 'M', ability: 'Own Tempo', moves: ['High Jump Kick']},
], [
	{species: 'Charmander', level: 5, gender: 'M', ability: 'Blaze', moves: ['Growl']},
]]);
crashBattle.makeChoices('move 1', 'move 1');
const crashTrace = crashBattle.verificationTrace;
if (!crashTrace.some(record => record.kind === 'single-handler' &&
	record.event === 'MoveFail' && record.effect === 'highjumpkick')) {
	throw new Error('High Jump Kick MoveFail record missing');
}
if (!crashTrace.some(record => record.kind === 'effect' &&
	record.phase === 'move-fail' && record.operation === 'crash-damage' &&
	record.move === 'highjumpkick' && record.damageBasis > 0 && record.applied)) {
	throw new Error('High Jump Kick crash-damage record missing');
}

process.stdout.write(`${JSON.stringify({
	trace, modifierTrace, burnTrace, protectTrace, reflectTrace, toxicTrace, sandTrace, effectTrace,
	recoilTrace, rockHeadTrace, drainTrace,
	multiHitTrace,
	fixedDamageTrace, variablePowerTrace,
	forcedReplacement: observed,
	crashTrace,
})}\n`);
