'use strict';

const fs = require('fs');
const path = require('path');

const source = JSON.parse(fs.readFileSync(path.join(__dirname, 'gen3ou-inventory.json'), 'utf8'));
const output = process.argv[2] || path.join(__dirname, 'handler-binding-shape.json');

function parseHook(hook) {
	const parts = hook.split('.');
	const callback = parts.at(-1);
	let event = callback.slice(2);
	let scope = 'target';
	for (const prefix of ['Source', 'Ally', 'Foe', 'Any', 'Side', 'Field']) {
		if (!event.startsWith(prefix)) continue;
		scope = prefix.toLowerCase();
		event = event.slice(prefix.length);
		break;
	}
	return {event, scope, embedded_path: parts.slice(0, -1).join('.')};
}
function increment(map, key, count = 1) { map.set(key, (map.get(key) || 0) + count); }
function orderedCounts(map, name) {
	return [...map].sort(([left], [right]) => left.localeCompare(right)).map(([id, binding_count]) => ({[name]: id, binding_count}));
}

const ownerKinds = new Map();
const ownerKindOwners = new Map();
const scopes = new Map();
const events = new Map();
const owners = new Map();
for (const binding of source.callback_hooks) {
	const parsed = parseHook(binding.hook);
	const ownerKey = `${binding.owner_kind}:${binding.owner_id}`;
	increment(ownerKinds, binding.owner_kind);
	if (!ownerKindOwners.has(binding.owner_kind)) ownerKindOwners.set(binding.owner_kind, new Set());
	ownerKindOwners.get(binding.owner_kind).add(binding.owner_id);
	increment(scopes, parsed.scope);
	increment(events, parsed.event);
	const owner = owners.get(ownerKey) || {owner_kind: binding.owner_kind, owner_id: binding.owner_id, bindings: []};
	owner.bindings.push({hook: binding.hook, event: parsed.event, scope: parsed.scope, embedded_path: parsed.embedded_path});
	owners.set(ownerKey, owner);
}

const ownerRecords = [...owners.values()].sort((a, b) =>
	a.owner_kind.localeCompare(b.owner_kind) || a.owner_id.localeCompare(b.owner_id));
const duplicateEventScopes = [];
const embeddedBindings = [];
const embeddedPaths = new Map();
for (const owner of ownerRecords) {
	owner.bindings.sort((a, b) => a.hook.localeCompare(b.hook));
	owner.binding_count = owner.bindings.length;
	const groups = new Map();
	for (const binding of owner.bindings) {
		const key = `${binding.scope}:${binding.event}`;
		if (!groups.has(key)) groups.set(key, []);
		groups.get(key).push(binding.hook);
		if (binding.embedded_path) {
			embeddedBindings.push({owner_kind: owner.owner_kind, owner_id: owner.owner_id, ...binding});
			increment(embeddedPaths, binding.embedded_path.split('.')[0]);
		}
	}
	owner.max_same_event_scope_span = Math.max(...[...groups.values()].map(values => values.length));
	for (const [key, hooks] of groups) {
		if (hooks.length < 2) continue;
		const separator = key.indexOf(':');
		duplicateEventScopes.push({
			owner_kind: owner.owner_kind, owner_id: owner.owner_id,
			scope: key.slice(0, separator), event: key.slice(separator + 1),
			binding_count: hooks.length, hooks,
		});
	}
}

const maxHandlerSpan = Math.max(...ownerRecords.map(owner => owner.binding_count));
const result = {
	schema: 'pokemon-gen3ou-handler-binding-shape-v1',
	oracle_revision: source.oracle.revision,
	format: source.oracle.format,
	frozen_binding_count: source.callback_hooks.length,
	owner_descriptor_count: ownerRecords.length,
	max_handler_span_per_owner: maxHandlerSpan,
	owners_at_max_span: ownerRecords.filter(owner => owner.binding_count === maxHandlerSpan)
		.map(owner => ({owner_kind: owner.owner_kind, owner_id: owner.owner_id})),
	by_owner_kind: orderedCounts(ownerKinds, 'owner_kind').map(record => ({
		...record, owner_count: ownerKindOwners.get(record.owner_kind).size,
		max_handler_span: Math.max(...ownerRecords.filter(owner => owner.owner_kind === record.owner_kind).map(owner => owner.binding_count)),
	})),
	by_scope: ['target', 'source', 'ally', 'foe', 'any', 'side', 'field']
		.map(scope => ({scope, binding_count: scopes.get(scope) || 0})),
	by_event: orderedCounts(events, 'event'),
	by_embedded_path: orderedCounts(embeddedPaths, 'embedded_path'),
	owners: ownerRecords,
	duplicate_event_scope_groups: duplicateEventScopes,
	embedded_bindings: embeddedBindings,
};
fs.writeFileSync(output, `${JSON.stringify(result, null, 2)}\n`);
