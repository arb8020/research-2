'use strict';

const assert = require('assert');
const childProcess = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const {
	scanFunctionConditionCalls, scanFunctionConditionReferences, scanFunctionDirectConditionMutations,
} = require('./runtime-condition-source-audit');
const {API_SPECS} = require('./condition-extractor');
const {descriptorSource} = require('./descriptor-source-index');

const showdownDir = process.env.POKEMON_SHOWDOWN_DIR;
if (!showdownDir) throw new Error('POKEMON_SHOWDOWN_DIR must name the pinned clean Showdown checkout');
const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';

const sourceProbe = function sourceProbe() {};
assert.throws(() => descriptorSource(new Map(), sourceProbe, 'missing-probe'),
	/exactly one physical Showdown callback source/);
assert.throws(() => descriptorSource(new Map([[sourceProbe, [
	{path: 'data/moves.ts', symbol: 'Moves.a.onHit'},
	{path: 'data/moves.ts', symbol: 'Moves.b.onHit'},
]]]), sourceProbe, 'ambiguous-probe'), /exactly one physical Showdown callback source/);

const temporaryDir = fs.mkdtempSync(path.join(os.tmpdir(), 'pokemon-condition-extractor-'));
const generatedPath = path.join(temporaryDir, 'inventory.json');
try {
	childProcess.execFileSync(process.execPath, [path.join(__dirname, 'generate.js'), generatedPath], {
		env: {...process.env, POKEMON_SHOWDOWN_DIR: showdownDir}, stdio: 'inherit',
	});
	const audit = JSON.parse(childProcess.execFileSync(process.execPath, [
		path.join(__dirname, 'gen3-condition-completeness-audit.js'),
	], {env: {...process.env, POKEMON_SHOWDOWN_DIR: showdownDir}, encoding: 'utf8'}));
	const generated = JSON.parse(fs.readFileSync(generatedPath, 'utf8'));
	assert.strictEqual(generated.schema, 'pokemon-gen3ou-authoritative-inventory-v2');
	assert.strictEqual(audit.revision, revision);
	assert.strictEqual(audit.unresolved.length, 0);
	const normalizeCall = call => JSON.stringify([
		call.owner_kind ? `${call.owner_kind}:${call.owner_id}` : call.owner,
		call.hook || call.path, call.api,
		(call.arguments || call.args).length === 1 && !(call.arguments || call.args)[0] ? [] : (call.arguments || call.args),
	]);
	const normalizeDelete = deletion => JSON.stringify([
		deletion.owner_kind ? `${deletion.owner_kind}:${deletion.owner_id}` : deletion.owner,
		deletion.hook || deletion.path, deletion.container, deletion.id,
	]);
	assert.deepStrictEqual(
		generated.condition_mutation_calls.map(normalizeCall).sort(), audit.calls.map(normalizeCall).sort(),
		'producer and independent audit condition-call multisets differ'
	);
	assert.deepStrictEqual(
		generated.condition_direct_deletes.map(normalizeDelete).sort(), audit.directDeletes.map(normalizeDelete).sort(),
		'producer and independent audit direct-delete multisets differ'
	);
	assert.deepStrictEqual(generated.scanned_conditions, audit.scanned_conditions);
	const sourceBearingRows = [
		...generated.condition_mutation_calls,
		...generated.condition_direct_deletes,
		...generated.dynamic_condition_calls,
	];
	for (const row of sourceBearingRows) {
		assert(row.showdown_source?.path && row.showdown_source?.symbol,
			`condition mutation lacks physical Showdown provenance: ${JSON.stringify(row)}`);
		assert(fs.existsSync(path.join(showdownDir, row.showdown_source.path)),
			`condition mutation source does not exist: ${JSON.stringify(row.showdown_source)}`);
	}
	const sourceFor = (ownerKind, ownerId, hook) => generated.condition_mutation_calls.find(call =>
		call.owner_kind === ownerKind && call.owner_id === ownerId && call.hook === hook)?.showdown_source;
	assert.deepStrictEqual(sourceFor('ability', 'effectspore', 'onDamagingHit'), {
		path: 'data/mods/gen3/abilities.ts', symbol: 'Abilities.effectspore.onDamagingHit',
	});
	assert.deepStrictEqual(sourceFor('ability', 'oblivious', 'onUpdate'), {
		path: 'data/mods/gen5/abilities.ts', symbol: 'Abilities.oblivious.onUpdate',
	});
	assert.deepStrictEqual(sourceFor('item', 'aguavberry', 'onEat'), {
		path: 'data/mods/gen6/items.ts', symbol: 'Items.aguavberry.onEat',
	});
	assert.deepStrictEqual(sourceFor('move', 'charge', 'condition.onAfterMove'), {
		path: 'data/mods/gen8/moves.ts', symbol: 'Moves.charge.condition.onAfterMove',
	});
	for (const dynamic of generated.dynamic_condition_calls) {
		const mutation = generated.condition_mutation_calls.find(call =>
			call.owner_kind === dynamic.owner_kind && call.owner_id === dynamic.owner_id &&
			call.hook === dynamic.hook && call.api === dynamic.api &&
			call.arguments[dynamic.argument] === dynamic.expression);
		assert(mutation, `dynamic condition call lacks its mutation row: ${JSON.stringify(dynamic)}`);
		assert.deepStrictEqual(dynamic.showdown_source, mutation.showdown_source,
			`dynamic condition provenance differs from its mutation row: ${JSON.stringify(dynamic)}`);
	}
	for (const kind of ['species', 'moves', 'abilities', 'items', 'statuses', 'volatiles',
		'side_conditions', 'weather', 'pseudo_weather', 'slot_conditions']) {
		for (const descriptor of generated[kind]) {
			assert.strictEqual(typeof descriptor.native_id_present, 'boolean',
				`${kind}:${descriptor.id} lacks native-ID presence`);
			assert(!Object.hasOwn(descriptor, 'support'),
				`${kind}:${descriptor.id} must not confuse native-ID presence with support`);
		}
	}
	const futureMoveCreators = generated.condition_mutation_calls.filter(call =>
		call.api === 'addSlotCondition' && call.arguments[1] === '"futuremove"');
	assert.deepStrictEqual(API_SPECS.addSlotCondition.ids, [{kind: 'slot', argument: 1}],
		'addSlotCondition condition identity must remain argument index 1');
	assert.deepStrictEqual(futureMoveCreators.map(call => `${call.owner_kind}:${call.owner_id}:${call.hook}`), [
		'move:doomdesire:onTry', 'move:futuresight:onTry',
	], 'literal futuremove slot creators must remain explicit in the effective descriptor census');
	for (const creator of futureMoveCreators) {
		assert.strictEqual(creator.arguments[API_SPECS.addSlotCondition.ids[0].argument], '"futuremove"',
			`${creator.owner_id} must create futuremove through addSlotCondition argument index 1`);
	}
	assert(generated.slot_conditions.some(entry => entry.id === 'futuremove'));
	for (const call of generated.dynamic_condition_calls) {
		assert(call.expression && call.resolution && call.resolution.kind,
			`dynamic condition call lacks reviewed resolution: ${JSON.stringify(call)}`);
		assert(call.resolution.candidates.length > 0,
			`dynamic condition call has no candidate domain: ${JSON.stringify(call)}`);
		for (const candidate of call.resolution.candidates) {
			assert(['reachable', 'unreachable-call', 'unreachable-condition'].includes(candidate.disposition),
				`unknown dynamic candidate disposition ${candidate.disposition}`);
		}
	}
	const {TeamValidator} = require(showdownDir);
	const dex = new TeamValidator('gen3ou').dex;
	const ts = require(path.join(showdownDir, 'node_modules/typescript'));
	const observedDirectDeletes = [];
	const observedCalls = [];
	function scanOwner(value, ownerKind, ownerId, prefix = '', seen = new Set()) {
		if (!value || (typeof value !== 'object' && typeof value !== 'function') || seen.has(value)) return;
		seen.add(value);
		for (const [key, child] of Object.entries(value)) {
			const hook = prefix ? `${prefix}.${key}` : key;
			if (typeof child === 'function') {
				const source = Function.prototype.toString.call(child);
				for (const call of scanFunctionConditionCalls(source, ts)) {
					observedCalls.push(JSON.stringify([`${ownerKind}:${ownerId}`, hook, call.api, call.arguments]));
				}
				const directMutations = scanFunctionDirectConditionMutations(source, ts)
					.filter(mutation => mutation.mutation_role === 'lifecycle-owning');
				const assignments = directMutations.filter(mutation => mutation.kind === 'direct-assignment');
				assert.deepStrictEqual(assignments, [],
					`effective descriptor function has an unreviewed direct condition identity assignment: ` +
					`${ownerKind}:${ownerId}:${hook}`);
				const references = scanFunctionConditionReferences(source, ts);
				assert.deepStrictEqual(references, [],
					`effective descriptor function has an unreviewed lifecycle API reference: ` +
					`${ownerKind}:${ownerId}:${hook}`);
				for (const deletion of directMutations.filter(mutation => mutation.kind === 'direct-delete')) {
					observedDirectDeletes.push(`${ownerKind}:${ownerId}:${hook}:${deletion.container}`);
				}
			}
			if (child && typeof child === 'object') scanOwner(child, ownerKind, ownerId, hook, seen);
		}
	}
	for (const move of generated.moves) scanOwner(dex.moves.get(move.id), 'move', move.id);
	for (const ability of generated.abilities) scanOwner(dex.abilities.get(ability.id), 'ability', ability.id);
	for (const item of generated.items) scanOwner(dex.items.get(item.id), 'item', item.id);
	for (const id of generated.scanned_conditions) scanOwner(dex.data.Conditions[id], 'condition', id);
	for (const id of new Set(generated.callback_hooks.filter(record => record.owner_kind === 'format')
		.map(record => record.owner_id))) scanOwner(dex.formats.get(id), 'format', id);
	assert.deepStrictEqual(observedCalls.sort(), generated.condition_mutation_calls.map(normalizeCall).sort(),
		'effective callback AST condition-call census differs from extracted calls');
	assert.deepStrictEqual(observedDirectDeletes.sort(), generated.condition_direct_deletes.map(deletion =>
		`${deletion.owner_kind}:${deletion.owner_id}:${deletion.hook}:${deletion.container}`).sort(),
	'effective callback direct-delete census differs from reviewed extracted deletes');
	const domains = {
		status: 'statuses', volatile: 'volatiles', side: 'side_conditions', slot: 'slot_conditions',
		weather: 'weather', pseudo_weather: 'pseudo_weather',
	};
	for (const [auditKind, generatedKind] of Object.entries(domains)) {
		assert.deepStrictEqual(generated[generatedKind].map(entry => entry.id), audit.compare[auditKind].expected);
		assert.deepStrictEqual(audit.compare[auditKind].missing_in_artifact, []);
		assert.deepStrictEqual(audit.compare[auditKind].extra_in_artifact, []);
	}
	const checkedIn = fs.readFileSync(path.join(__dirname, 'gen3ou-inventory.json'));
	assert.deepStrictEqual(fs.readFileSync(generatedPath), checkedIn, 'checked-in inventory is stale');
	process.stdout.write('condition extraction integration passed\n');
} finally {
	fs.rmSync(temporaryDir, {recursive: true, force: true});
}
