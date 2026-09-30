'use strict';

const fs = require('fs');
const path = require('path');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const ALGEBRAS = new Set([
	'numeric-or-cancel-relay', 'mutable-value-relay',
	'mutable-boost-table-relay', 'boolean-or-null-gate',
	'target-redirect-relay', 'selector-or-replacement-relay',
	'state-mutation-notification', 'void-notification',
]);

function validateEventVocabulary(value) {
	const failures = [];
	if (value.schema !== 'pokemon-gen3ou-event-vocabulary-v2') failures.push('unsupported schema');
	if (value.oracle_revision !== REVISION) failures.push('wrong oracle revision');
	if (value.format !== 'gen3ou') failures.push('wrong format');
	if (value.frozen_hook_records !== 514) failures.push('wrong frozen hook count');
	if (value.hook_derived_events !== 70) failures.push('wrong hook-derived event count');
	if (JSON.stringify(value.runtime_callsite_events) !== '["ChangeBoost"]') failures.push('wrong runtime call-site events');
	if (value.unique_events !== 71 || value.events?.length !== 71) failures.push('wrong event count');
	if (!Array.isArray(value.events)) return failures;
	const names = new Set();
	let handlerCount = 0;
	for (const [index, event] of value.events.entries()) {
		if (!event || typeof event.event !== 'string' || !event.event) failures.push(`event ${index + 1}: invalid name`);
		if (names.has(event.event)) failures.push(`event ${index + 1}: duplicate name`);
		names.add(event.event);
		if (!ALGEBRAS.has(event.algebra)) failures.push(`event ${event.event}: invalid algebra`);
		if (!Number.isInteger(event.frozen_handler_count) || event.frozen_handler_count < 0) failures.push(`event ${event.event}: invalid handler count`);
		handlerCount += event.frozen_handler_count || 0;
		for (const key of ['raw_hooks', 'scopes', 'owner_kinds', 'ordering']) {
			if (!Array.isArray(event[key])) failures.push(`event ${event.event}: ${key} is not an array`);
		}
		if (typeof event.discovery !== 'string' || !event.discovery) failures.push(`event ${event.event}: invalid discovery`);
		if (typeof event.current_native_kernel !== 'boolean') failures.push(`event ${event.event}: invalid native support flag`);
	}
	if (handlerCount !== 514) failures.push('event handler counts do not total 514');
	const id = name => value.events.findIndex(event => event.event === name) + 1;
	for (const [name, expected] of [['Damage', 12], ['ModifyAtk', 28], ['TryBoost', 57], ['TryHit', 60], ['ChangeBoost', 70]]) {
		if (id(name) !== expected) failures.push(`${name} ID changed`);
	}
	for (const name of ['TryBoost', 'ChangeBoost']) {
		const event = value.events.find(candidate => candidate.event === name);
		if (event?.algebra !== 'mutable-boost-table-relay') failures.push(`${name} has the wrong algebra`);
		if (!event?.current_native_kernel) failures.push(`${name} is not enabled in the native kernel`);
	}
	const change = value.events[69];
	if (change?.frozen_handler_count !== 0 || change?.raw_hooks?.length !== 0) failures.push('ChangeBoost must be a zero-handler runtime event');
	const critical = value.events[70];
	if (critical?.event !== 'CriticalHit' || critical?.frozen_handler_count !== 2 ||
		critical?.algebra !== 'boolean-or-null-gate') {
		failures.push('CriticalHit must append two literal-false cancellation bindings');
	}
	return failures;
}

if (require.main === module) {
	const filename = process.argv[2] || path.join(__dirname, 'event-vocabulary.json');
	const failures = validateEventVocabulary(JSON.parse(fs.readFileSync(filename, 'utf8')));
	if (failures.length) {
		process.stderr.write(`${failures.join('\n')}\n`);
		process.exitCode = 1;
	} else {
		process.stdout.write('event vocabulary is structurally valid\n');
	}
}

module.exports = {validateEventVocabulary};
