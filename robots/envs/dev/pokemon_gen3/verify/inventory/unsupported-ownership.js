#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');

const manifest = JSON.parse(fs.readFileSync(path.join(__dirname, 'descriptor-map.json'), 'utf8'));
const records = manifest.inventories.flatMap(inventory => inventory.entries
	.filter(entry => entry.classification === 'unsupported')
	.map(entry => ({kind: inventory.kind, id: entry.id})));

const is = (record, kind, pattern) => record.kind === kind && pattern.test(record.id);
const rules = [
	['A', 'resolved admission/validation universe', r =>
		r.kind === 'format_rule' && !/^(switchpriorityclausemod|endlessbattleclause|hppercentagemod|cancelmod|beatupnicknamesmod|freezeclausemod)$/.test(r.id)],
	['C', 'queue and terminal policy', r => is(r, 'format_rule', /^(switchpriorityclausemod|endlessbattleclause)$/)],
	['D', 'protocol/presentation adapters', r => is(r, 'format_rule', /^(hppercentagemod|cancelmod|beatupnicknamesmod)$/)],
	['F', 'damage provenance and scripted retaliation', r =>
		is(r, 'move', /^(counter|mirrorcoat)$/) || is(r, 'condition', /^volatiles\.(counter|mirrorcoat)$/) ||
		is(r, 'event_hook', /^move\.(counter|mirrorcoat)\.condition\.onDamage$/) || is(r, 'target_mode', /^scripted$/)],
	['H', 'switching, dragging, interception, transfer', r =>
		is(r, 'move', /^(roar|whirlwind|pursuit|batonpass|ingrain)$/) || is(r, 'ability', /^suctioncups$/) ||
		is(r, 'condition', /^volatiles\.(pursuit|trapper|ingrain)$/) ||
		is(r, 'event_hook', /^(move\.(pursuit|batonpass|ingrain)\.|ability\.suctioncups\.)/)],
	['I', 'active-move construction and runtime overlays', r =>
		is(r, 'move', /^(present|secretpower|beatup|conversion|conversion2|camouflage|transform)$/) ||
		is(r, 'condition', /^volatiles\.beatup$/) ||
		is(r, 'event_hook', /^(move\.(present|secretpower|beatup|conversion|conversion2|camouflage|transform)\.)/)],
	['J', 'child invocation and moveset mutation', r =>
		is(r, 'move', /^(assist|metronome|naturepower|sleeptalk|snatch|mimic|sketch)$/) ||
		is(r, 'condition', /^volatiles\.snatch$/) ||
		is(r, 'event_hook', /^move\.(assist|metronome|naturepower|sleeptalk|snatch|mimic|sketch)\./)],
	['K', 'typed formulas and atomic mutations', r =>
		is(r, 'move', /^(doubleteam|fissure|guillotine|horndrill|sheercold|lowkick|smellingsalts|bellydrum|painsplit|memento|spite|highjumpkick|jumpkick)$/) ||
		is(r, 'ability', /^sturdy$/) || is(r, 'event_hook', /^ability\.sturdy\./) ||
		is(r, 'event_hook', /^move\.(lowkick|revenge|smellingsalts|bellydrum|painsplit|memento|spite|highjumpkick|jumpkick)\./)],
	['L', 'ability lifecycle and relational handlers', r =>
		is(r, 'ability', /^(plus|minus|flashfire|forecast|liquidooze|truant)$/) || is(r, 'move', /^skillswap$/) ||
		is(r, 'condition', /^volatiles\.(flashfire|truant)$/) ||
		is(r, 'event_hook', /^(ability\.(plus|minus|flashfire|forecast|liquidooze|truant)\.|move\.skillswap\.)/)],
	['M', 'specialized per-hit sequencing', r => is(r, 'move', /^(triplekick|twineedle)$/)],
	['N', 'declarative rejection', r => is(r, 'move', /^teleport$/)],
	['E', 'bounded move-local state machines', r =>
		is(r, 'move', /^(minimize|furycutter|rollout|iceball|defensecurl|stockpile|spitup|swallow|focuspunch|imprison|bide|destinybond|grudge)$/) ||
		is(r, 'condition', /^volatiles\.(minimize|furycutter|rollout|rolloutstorage|iceball|defensecurl|stockpile|focuspunch|imprison|bide|destinybond|grudge)$/) ||
		is(r, 'event_hook', /^move\.(minimize|furycutter|rollout|iceball|defensecurl|stockpile|spitup|swallow|focuspunch|imprison|bide|destinybond|grudge)\.|^condition\.rolloutstorage\./)],
	['B', 'typed condition/status lifecycle', r =>
		is(r, 'format_rule', /^freezeclausemod$/) ||
		is(r, 'move', /^(charge|curse|foresight|leechseed|odorsleuth|perishsong|rage|swagger|uproar)$/) ||
		is(r, 'condition', /^(volatiles\.(charge|curse|foresight|leechseed|perishsong|rage|uproar)|pseudo_weather\.(freezeclausemod|sleepclausemod))$/) ||
		is(r, 'event_hook', /^(move\.(charge|curse|foresight|leechseed|odorsleuth|perishsong|rage|uproar|rapidspin)\.|format\.(freezeclausemod|sleepclausemod)\.|condition\.mustrecharge\.|ability\.(insomnia|vitalspirit)\.)/)],
];

const owned = new Map();
for (const record of records) {
	const matches = rules.filter(([, , predicate]) => predicate(record));
	if (matches.length > 1) throw new Error(`${record.kind}:${record.id}: overlapping owners ${matches.map(x => x[0]).join(',')}`);
	if (matches.length === 0) throw new Error(`${record.kind}:${record.id}: no owner`);
	owned.set(`${record.kind}:${record.id}`, matches[0][0]);
}

const counts = Object.fromEntries(rules.map(([node]) => [node, 0]));
for (const node of owned.values()) counts[node]++;
const total = Object.values(counts).reduce((sum, count) => sum + count, 0);
if (total !== records.length) throw new Error(`ownership total ${total}; live unsupported ${records.length}`);

if (process.argv.includes('--list')) {
	for (const record of records) console.log(`${owned.get(`${record.kind}:${record.id}`)}\t${record.kind}\t${record.id}`);
} else {
	for (const [node, label] of rules) console.log(`${node}\t${counts[node]}\t${label}`);
	console.log(`TOTAL\t${total}`);
}
