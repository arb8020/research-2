'use strict';

const fs = require('fs');
const path = require('path');

const source = JSON.parse(fs.readFileSync(path.join(__dirname, 'gen3ou-inventory.json'), 'utf8'));
const output = process.argv[2] || path.join(__dirname, 'event-vocabulary.json');

const numeric = new Set([
	'Accuracy', 'BasePower', 'Damage', 'DeductPP', 'ModifyAtk', 'ModifyCritRatio',
	'ModifyDamage', 'ModifyDamagePhase1', 'ModifyDef', 'ModifySpA', 'ModifySpD',
	'ModifySpe', 'TryHeal', 'WeatherModifyDamage',
]);
const mutable = new Set(['ModifyBoost', 'ModifyMove', 'ModifySecondaries', 'ModifyType']);
const boostTable = new Set(['ChangeBoost', 'TryBoost']);
const redirect = new Set(['RedirectTarget']);
const selector = new Set(['LockMove', 'OverrideAction']);
const gate = new Set([
	'BeforeMove', 'BeforeSwitchOut', 'DragOut', 'EntryHazard', 'Immunity',
	'Invulnerability', 'NegateImmunity', 'PrepareHit', 'SetStatus', 'StallMove',
	'TakeItem', 'Try', 'TryAddVolatile', 'TryEatItem', 'TryHit',
	'TryImmunity', 'TryMove', 'TryPrimaryHit',
]);
const sideEffect = new Set(['DisableMove', 'MaybeTrapPokemon', 'TrapPokemon']);
const current = new Set([
	'ChangeBoost', 'CriticalHit', 'Damage', 'ModifyAtk', 'ModifyBoost', 'ModifySpD',
	'NegateImmunity', 'TryBoost', 'TryHit',
]);
const runtimeCallsiteEvents = [{event: 'ChangeBoost', algebra: 'mutable-boost-table-relay'}];

function parseHook(hook) {
	const callback = hook.split('.').at(-1);
	let event = callback.slice(2);
	let scope = 'target';
	for (const prefix of ['Source', 'Field', 'Side', 'Ally', 'Foe', 'Any']) {
		if (!event.startsWith(prefix)) continue;
		scope = prefix.toLowerCase();
		event = event.slice(prefix.length);
		break;
	}
	return {callback, event, scope};
}

function algebra(event) {
	if (boostTable.has(event)) return 'mutable-boost-table-relay';
	if (numeric.has(event)) return 'numeric-or-cancel-relay';
	if (mutable.has(event)) return 'mutable-value-relay';
	if (redirect.has(event)) return 'target-redirect-relay';
	if (selector.has(event)) return 'selector-or-replacement-relay';
	if (gate.has(event)) return 'boolean-or-null-gate';
	if (sideEffect.has(event)) return 'state-mutation-notification';
	return 'void-notification';
}

const events = new Map();
for (const record of source.callback_hooks) {
	const parsed = parseHook(record.hook);
	const value = events.get(parsed.event) || {
		event: parsed.event, algebra: algebra(parsed.event), frozen_handler_count: 0,
		raw_hooks: new Set(), scopes: new Set(), owner_kinds: new Set(),
	};
	value.frozen_handler_count++;
	value.raw_hooks.add(record.hook);
	value.scopes.add(parsed.scope);
	value.owner_kinds.add(record.owner_kind);
	events.set(parsed.event, value);
}

/* Preserve the 69 callback-derived IDs frozen before literal-false callback
 * extraction was corrected.  CriticalHit already has an explicit native
 * event ID because false is a cancellation sentinel rather than a callable
 * function, so append its vocabulary record instead of renumbering every
 * later event. */
const records = [...events.values()]
	.filter(value => value.event !== 'CriticalHit')
	.sort((a, b) => a.event.localeCompare(b.event)).map(value => ({
	event: value.event,
	algebra: value.algebra,
	frozen_handler_count: value.frozen_handler_count,
	raw_hooks: [...value.raw_hooks].sort(),
	scopes: [...value.scopes].sort(),
	owner_kinds: [...value.owner_kinds].sort(),
	discovery: 'runEvent target/source topology or direct singleEvent owner; fieldEvent is separate for Residual/SwitchIn',
	ordering: ['order', 'priority', 'speed', 'subOrder', 'effectOrder for SwitchIn/RedirectTarget ties'],
	current_native_kernel: current.has(value.event),
}));
/* Hook-derived IDs are append-only: runtime-only events must not renumber the
 * 69 frozen callback events consumed by existing traces. */
for (const runtime of runtimeCallsiteEvents) {
	if (events.has(runtime.event)) continue;
	records.push({
		event: runtime.event,
		algebra: runtime.algebra,
		frozen_handler_count: 0,
		raw_hooks: [],
		scopes: [],
		owner_kinds: [],
		discovery: 'runtime call-site event; ordinary runEvent discovery currently yields zero handlers',
		ordering: ['order', 'priority', 'speed', 'subOrder', 'effectOrder for SwitchIn/RedirectTarget ties'],
		current_native_kernel: current.has(runtime.event),
	});
}
if (events.has('CriticalHit')) {
	const value = events.get('CriticalHit');
	records.push({
		event: value.event,
		algebra: 'boolean-or-null-gate',
		frozen_handler_count: value.frozen_handler_count,
		raw_hooks: [...value.raw_hooks].sort(),
		scopes: [...value.scopes].sort(),
		owner_kinds: [...value.owner_kinds].sort(),
		discovery: 'runEvent target topology; literal false cancels a sampled critical hit',
		ordering: ['order', 'priority', 'speed', 'subOrder', 'effectOrder for SwitchIn/RedirectTarget ties'],
		current_native_kernel: true,
	});
}

const result = {
	schema: 'pokemon-gen3ou-event-vocabulary-v2',
	oracle_revision: source.oracle.revision,
	format: source.oracle.format,
	frozen_hook_records: source.callback_hooks.length,
	hook_derived_events: events.size,
	runtime_callsite_events: runtimeCallsiteEvents.map(value => value.event),
	unique_events: records.length,
	events: records,
};
fs.writeFileSync(output, `${JSON.stringify(result, null, 2)}\n`);
