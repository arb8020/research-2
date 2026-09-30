'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const {
	API_SPECS, extractCalls, extractDirectDeletes, literalID,
} = require('./condition-extractor');
const {buildDescriptorSourceIndex, descriptorSource} = require('./descriptor-source-index');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const showdownDir = process.env.POKEMON_SHOWDOWN_DIR;
if (!showdownDir) throw new Error('POKEMON_SHOWDOWN_DIR must name the pinned Showdown checkout');
const outputPath = process.argv[2];
if (!outputPath) throw new Error('usage: node generate.js OUTPUT.json');

const {Dex, TeamValidator} = require(showdownDir);
const descriptorSources = buildDescriptorSourceIndex(showdownDir);
const validator = new TeamValidator('gen3ou');
const dex = validator.dex;
const revision = require('child_process').execFileSync('git', ['rev-parse', 'HEAD'], {
	encoding: 'utf8', cwd: showdownDir,
}).trim();
if (revision !== REVISION) throw new Error(`expected Showdown ${REVISION}, got ${revision}`);
const dirtyTrackedFiles = require('child_process').execFileSync(
	'git', ['status', '--porcelain', '--untracked-files=no'], {encoding: 'utf8', cwd: showdownDir}
).trim();
if (dirtyTrackedFiles) {
	throw new Error('inventory generation requires a clean pinned Showdown checkout; use a separate instrumented oracle');
}

const idMapPath = path.resolve(__dirname, '../cases/native-id-map.json');
const nativeIDs = JSON.parse(fs.readFileSync(idMapPath, 'utf8'));
const supported = {
	species: new Set(Object.keys(nativeIDs.species)),
	moves: new Set(Object.keys(nativeIDs.moves)),
	abilities: new Set(Object.keys(nativeIDs.abilities).filter(Boolean)),
	items: new Set(Object.keys(nativeIDs.items).filter(Boolean)),
	statuses: new Set(['brn', 'par', 'tox']),
	volatiles: new Set(['protect', 'stall']),
	side_conditions: new Set(['reflect', 'lightscreen']),
	weather: new Set(['sandstorm']),
};

const sources = {
	format: ['config/formats.ts', 'data/rulesets.ts', 'data/mods/gen3/rulesets.ts', 'sim/dex-formats.ts', 'sim/team-validator.ts'],
	species: ['data/pokedex.ts', 'data/mods/gen3/formats-data.ts'],
	moves: ['data/moves.ts', 'data/mods/gen3/moves.ts', 'data/mods/gen4/moves.ts', 'data/mods/gen5/moves.ts', 'data/learnsets.ts'],
	abilities: ['data/abilities.ts', 'data/mods/gen3/abilities.ts', 'data/mods/gen4/abilities.ts'],
	items: ['data/items.ts', 'data/mods/gen3/items.ts', 'data/mods/gen4/items.ts'],
	conditions: ['data/conditions.ts', 'data/mods/gen3/conditions.ts', 'data/mods/gen4/conditions.ts', 'data/mods/gen5/conditions.ts'],
	runtime: ['sim/battle.ts', 'sim/battle-actions.ts', 'sim/pokemon.ts', 'sim/side.ts', 'sim/field.ts', 'data/mods/gen3/scripts.ts'],
};

const blankStats = () => ({hp: 1, atk: 0, def: 0, spa: 0, spd: 0, spe: 0});
function candidateSet(species, ability, move, item = '') {
	return {
		name: species.name, species: species.name, item, ability, moves: [move], nature: 'Serious',
		level: 100, evs: blankStats(), ivs: {hp: 31, atk: 31, def: 31, spa: 31, spd: 31, spe: 31},
	};
}
function legalSpecies(species) {
	if (!species.exists || species.gen > 3) return false;
	const set = candidateSet(species, species.abilities[0] || '', 'Splash');
	const {tierSpecies} = validator.getValidationSpecies(set);
	return !validator.checkSpecies(set, species, tierSpecies, {});
}
function nativeIDPresent(kind, id) {
	return supported[kind]?.has(id) || false;
}

const speciesCandidates = dex.species.all().filter(legalSpecies).sort((a, b) => a.id.localeCompare(b.id));
const moveCandidates = dex.moves.all().filter(move => move.exists && move.gen <= 3)
	.sort((a, b) => a.id.localeCompare(b.id));
let seedSet = null;
const reachableMoveIDs = new Set();
const reachableAbilityIDs = new Set();
const legalSpeciesIDs = new Set();

for (const species of speciesCandidates) {
	const abilities = [...new Set(Object.values(species.abilities).filter(Boolean))];
	let speciesReachable = false;
	for (const ability of abilities) {
		for (const move of moveCandidates) {
			const set = candidateSet(species, ability, move.name);
			if (validator.validateSet(set, {})) continue;
			speciesReachable = true;
			reachableMoveIDs.add(move.id);
			reachableAbilityIDs.add(dex.abilities.get(ability).id);
			if (!seedSet) seedSet = {
				species: species.id, ability: dex.abilities.get(ability).id, move: move.id,
			};
		}
	}
	if (speciesReachable) legalSpeciesIDs.add(species.id);
}

const submittedMoveIDs = new Set(reachableMoveIDs);
const moveReachability = new Map([...submittedMoveIDs].map(id => [id, [{
	kind: 'submitted-set',
	source: 'TeamValidator(gen3ou).validateSet',
}]]));
function addRuntimeMove(id, provenance) {
	if (!moveReachability.has(id)) moveReachability.set(id, []);
	moveReachability.get(id).push(provenance);
	reachableMoveIDs.add(id);
}
const metronomePool = [];
if (submittedMoveIDs.has('metronome')) {
	for (const move of dex.moves.all()) {
		if ((!move.isNonstandard || move.isNonstandard === 'Unobtainable') && move.flags.metronome) {
			metronomePool.push(move.id);
			addRuntimeMove(move.id, {
				kind: 'move-delegation', caller: 'metronome',
				source: 'data/mods/gen4/moves.ts:metronome.onHit (inherited by Gen 3)',
			});
		}
	}
}
addRuntimeMove('struggle', {
	kind: 'simulator-forced',
	source: 'sim/pokemon.ts:getMoves and sim/side.ts:chooseMove',
});

if (!seedSet) throw new Error('validator produced no legal Gen 3 OU sets');
const seedSpecies = dex.species.get(seedSet.species);
const reachableItemIDs = new Set();
for (const item of dex.items.all().filter(item => item.exists && item.gen <= 3).sort((a, b) => a.id.localeCompare(b.id))) {
	const set = candidateSet(seedSpecies, dex.abilities.get(seedSet.ability).name, dex.moves.get(seedSet.move).name, item.name);
	if (!validator.validateSet(set, {})) reachableItemIDs.add(item.id);
}

function ownCallbacks(value, prefix = '', result = [], seen = new Set()) {
	if (!value || typeof value !== 'object' || seen.has(value)) return result;
	seen.add(value);
	for (const [key, child] of Object.entries(value)) {
		const location = prefix ? `${prefix}.${key}` : key;
		if (/^on[A-Z]/.test(key) &&
			(typeof child === 'function' || (key === 'onCriticalHit' && child === false))) {
			result.push({hook: location, callback: child});
		}
		if (child && typeof child === 'object') ownCallbacks(child, location, result, seen);
	}
	return result;
}

const conditionRefs = {
	status: new Set(['slp', 'frz', 'brn', 'par', 'psn', 'tox']),
	volatile: new Set(), side: new Set(), weather: new Set(), pseudoWeather: new Set(), slot: new Set(),
};
const dynamicConditionCalls = [];
const conditionMutationCalls = [];
const conditionDirectDeletes = [];
const dynamicResolution = new Map();
function resolveDynamic(key, kind, source, candidates) {
	dynamicResolution.set(key, {kind, source, candidates});
}
resolveDynamic('ability:effectspore:onDamagingHit:trySetStatus:0:status', 'status',
	'data/mods/gen3/abilities.ts:12-19', [
		{id: 'slp', disposition: 'reachable', reason: 'sampled by Effect Spore'},
		{id: 'par', disposition: 'reachable', reason: 'sampled by Effect Spore'},
		{id: 'psn', disposition: 'reachable', reason: 'sampled by Effect Spore'},
	]);
resolveDynamic('ability:synchronize:onAfterSetStatus:trySetStatus:0:id', 'status',
	'data/mods/gen4/abilities.ts:469-478 (inherited by Gen 3)', [
		{id: 'brn', disposition: 'reachable', reason: 'forwarded status'},
		{id: 'par', disposition: 'reachable', reason: 'forwarded status'},
		{id: 'psn', disposition: 'reachable', reason: 'forwarded directly, or normalized from tox'},
		{id: 'slp', disposition: 'unreachable-call', reason: 'callback returns before the call'},
		{id: 'frz', disposition: 'unreachable-call', reason: 'callback returns before the call'},
		{id: 'tox', disposition: 'unreachable-call', reason: 'normalized to psn before the call'},
	]);
const twoTurnSources = {
	bounce: 'data/moves.ts:1700',
	dig: 'data/mods/gen3/moves.ts:197',
	dive: 'data/mods/gen3/moves.ts:214',
	fly: 'data/mods/gen3/moves.ts:299',
	razorwind: 'data/moves.ts:14779',
	skullbash: 'data/moves.ts:16629',
	skyattack: 'data/moves.ts:16655',
	solarbeam: 'data/moves.ts:17227',
};
for (const [id, source] of Object.entries(twoTurnSources)) {
	resolveDynamic(`move:${id}:onTryMove:removeVolatile:0:move.id`, 'volatile',
		source, [
			{id, disposition: 'reachable', reason: 'move.id is the executing two-turn move identifier'},
		]);
}
for (const hook of ['onAfterHit', 'onAfterSubDamage']) {
	resolveDynamic(`move:rapidspin:${hook}:removeSideCondition:0:condition`, 'side',
		'effective Gen 3 Rapid Spin callback inherited from data/moves.ts', [
			{id: 'spikes', disposition: 'reachable', reason: 'Spikes is establishable by a legal Gen 3 move'},
			...['toxicspikes', 'stealthrock', 'stickyweb', 'gmaxsteelsurge'].map(id => ({
				id, disposition: 'unreachable-condition', reason: 'no legal Gen 3 descriptor can establish this later-generation side condition',
			})),
		]);
}
resolveDynamic('move:rapidspin:self.onHit:removeSideCondition:0:condition', 'side',
	'data/mods/gen4/moves.ts:1083-1101 (inherited by Gen 3)', [
		{id: 'spikes', disposition: 'reachable', reason: 'Spikes is establishable by a legal Gen 3 move'},
		...['toxicspikes', 'stealthrock', 'stickyweb'].map(id => ({
			id, disposition: 'unreachable-condition', reason: 'no legal Gen 3 descriptor can establish this later-generation side condition',
		})),
	]);
resolveDynamic('move:triattack:secondary.onHit:trySetStatus:0:status', 'status',
	'data/moves.ts:19855 (effective Tri Attack secondary inherited by Gen 3)', [
		{id: 'brn', disposition: 'reachable', reason: 'sampled by Tri Attack'},
		{id: 'par', disposition: 'reachable', reason: 'sampled by Tri Attack'},
		{id: 'frz', disposition: 'reachable', reason: 'sampled by Tri Attack'},
	]);
resolveDynamic('condition:twoturnmove:onStart:addVolatile:0:effect.id', 'volatile',
	'data/conditions.ts:287-321', Object.keys(twoTurnSources).map(id => ({
		id, disposition: 'reachable', reason: 'effect.id is the executing two-turn move identifier',
	})));
resolveDynamic('condition:twoturnmove:onEnd:removeVolatile:0:this.effectState.move', 'volatile',
	'data/conditions.ts:287-321', Object.keys(twoTurnSources).map(id => ({
		id, disposition: 'reachable', reason: 'stored move is the executing two-turn move identifier',
	})));
function addRef(kind, value) {
	if (typeof value === 'string' && value) conditionRefs[kind].add(Dex.toID(value));
}
function scanDescriptor(value, ownerKind, ownerId, descriptorPath = '', seen = new Set()) {
	if (!value || (typeof value !== 'object' && typeof value !== 'function') || seen.has(value)) return;
	seen.add(value);
	for (const [key, child] of Object.entries(value)) {
		const childPath = descriptorPath ? `${descriptorPath}.${key}` : key;
		if (key === 'status' || key === 'forceStatus') addRef('status', child);
		if (key === 'volatileStatus') addRef('volatile', child);
		if (key === 'sideCondition') addRef('side', child);
		if (key === 'slotCondition') addRef('slot', child);
		if (key === 'weather') addRef('weather', child);
		if (key === 'pseudoWeather') addRef('pseudoWeather', child);
		if (typeof child === 'function') {
			const text = Function.prototype.toString.call(child);
			const calls = extractCalls(text);
			const directDeletes = extractDirectDeletes(text, Dex.toID);
			const showdownSource = calls.length || directDeletes.length ? descriptorSource(
				descriptorSources, child, `${ownerKind}:${ownerId}:${childPath}`
			) : null;
			for (const call of calls) {
				conditionMutationCalls.push({
					owner_kind: ownerKind, owner_id: ownerId, hook: childPath,
					api: call.api, arguments: call.arguments,
					showdown_source: showdownSource,
					snippet: text.slice(Math.max(0, call.index - 40), Math.min(text.length, call.index + call.text.length + 40))
						.replace(/\s+/g, ' ').trim(),
				});
				for (const idSpec of API_SPECS[call.api].ids) {
					const expression = call.arguments[idSpec.argument];
					if (idSpec.optional && !expression) continue;
					if (expression === undefined || expression === '') {
						throw new Error(`missing condition ID argument ${idSpec.argument} in ${ownerKind}:${ownerId}:${childPath}:${call.api}`);
					}
					const id = literalID(expression, Dex.toID);
					if (id) {
						addRef(idSpec.kind, id);
						continue;
					}
					const resolutionKey = `${ownerKind}:${ownerId}:${childPath}:${call.api}:${idSpec.argument}:${expression}`;
					const resolution = dynamicResolution.get(resolutionKey);
					if (!resolution) throw new Error(`unresolved dynamic condition call: ${resolutionKey}`);
					if (resolution.kind !== idSpec.kind) {
						throw new Error(`condition kind mismatch for ${resolutionKey}: expected ${idSpec.kind}, got ${resolution.kind}`);
					}
					for (const candidate of resolution.candidates) {
						if (candidate.disposition === 'reachable') addRef(resolution.kind, candidate.id);
					}
					dynamicConditionCalls.push({
						owner_kind: ownerKind, owner_id: ownerId, hook: childPath,
						api: call.api, argument: idSpec.argument, role: idSpec.role || 'condition', expression,
						showdown_source: showdownSource,
						snippet: text.slice(Math.max(0, call.index - 40), Math.min(text.length, call.index + call.text.length + 40))
							.replace(/\s+/g, ' ').trim(),
						resolution,
					});
				}
			}
			const directDeleteKinds = {
				volatiles: 'volatile', sideConditions: 'side', slotConditions: 'slot', pseudoWeather: 'pseudoWeather',
			};
			for (const deletion of directDeletes) {
				if (!deletion.id) {
					throw new Error(`unresolved dynamic condition deletion: ${ownerKind}:${ownerId}:${childPath}:${deletion.container}:${deletion.expression}`);
				}
				addRef(directDeleteKinds[deletion.container], deletion.id);
				conditionDirectDeletes.push({
					owner_kind: ownerKind, owner_id: ownerId, hook: childPath,
					container: deletion.container, id: deletion.id, expression: deletion.expression,
					showdown_source: showdownSource,
				});
			}
		}
		if (child && typeof child === 'object') scanDescriptor(child, ownerKind, ownerId, childPath, seen);
	}
}

const reachableMoves = [...reachableMoveIDs].map(id => dex.moves.get(id));
const reachableAbilities = [...reachableAbilityIDs].map(id => dex.abilities.get(id));
const reachableItems = [...reachableItemIDs].map(id => dex.items.get(id));
const format = dex.formats.get('gen3ou');
const ruleTable = dex.formats.getRuleTable(format);
const runtimeRuleCallbackExclusions = new Set([
	'onBegin', 'onTeamPreview', 'onBattleStart', 'onValidateRule',
	'onValidateTeam', 'onChangeSet', 'onValidateSet',
]);
const runtimeFormatRules = [...ruleTable.keys()]
	.filter(id => !'+*-!'.includes(id.charAt(0)))
	.map(id => dex.formats.get(id))
	.filter(rule => rule.exists && Object.keys(rule).some(key =>
		key.startsWith('on') && !runtimeRuleCallbackExclusions.has(key)));
for (const rule of runtimeFormatRules) conditionRefs.pseudoWeather.add(rule.id);
for (const entry of reachableMoves) scanDescriptor(entry, 'move', entry.id);
for (const entry of reachableAbilities) scanDescriptor(entry, 'ability', entry.id);
for (const entry of reachableItems) scanDescriptor(entry, 'item', entry.id);
for (const entry of runtimeFormatRules) scanDescriptor(entry, 'format', entry.id);
for (const move of reachableMoves) {
	if (!move.condition) continue;
	if (move.sideCondition || move.slotCondition || move.weather || move.pseudoWeather || move.status) continue;
	conditionRefs.volatile.add(move.id);
}
for (const ability of reachableAbilities) if (ability.condition) conditionRefs.volatile.add(ability.id);
for (const item of reachableItems) if (item.condition) conditionRefs.volatile.add(item.id);

const effectiveConditions = Object.keys(dex.data.Conditions).sort();
const scannedConditionIDs = new Set();
let discoveredCondition = true;
while (discoveredCondition) {
	discoveredCondition = false;
	for (const id of new Set(Object.values(conditionRefs).flatMap(set => [...set]))) {
		if (scannedConditionIDs.has(id) || !dex.data.Conditions[id]) continue;
		scannedConditionIDs.add(id);
		scanDescriptor(dex.data.Conditions[id], 'condition', id);
		discoveredCondition = true;
	}
}
const encounteredDynamicKeys = new Set(dynamicConditionCalls.map(call =>
	`${call.owner_kind}:${call.owner_id}:${call.hook}:${call.api}:${call.argument}:${call.expression}`));
for (const key of dynamicResolution.keys()) {
	if (!encounteredDynamicKeys.has(key)) throw new Error(`stale dynamic condition resolution: ${key}`);
}
const reachableConditionIDs = new Set(Object.values(conditionRefs).flatMap(set => [...set]));
const targetModes = [...new Set(reachableMoves.map(move => move.target))].sort();
const formatRules = [
	...[...ruleTable.entries()].map(([id, inherited_from]) => ({
		id, kind: id.startsWith('-') ? 'ban' : 'rule', inherited_from,
		sources: sources.format,
	})),
	...ruleTable.complexBans.map(([id, inherited_from, limit, components]) => ({
		id, kind: 'complex-ban', inherited_from, limit, components,
		sources: sources.format,
	})),
].sort((a, b) => `${a.kind}:${a.id}`.localeCompare(`${b.kind}:${b.id}`));
const formatConstraints = {
	base_ruleset: format.baseRuleset,
	banlist: format.banlist,
	tag_rules: [...ruleTable.tagRules],
	value_rules: Object.fromEntries(ruleTable.valueRules),
	team: {
		min_size: ruleTable.minTeamSize, max_size: ruleTable.maxTeamSize,
		max_moves: ruleTable.maxMoveCount, min_source_gen: ruleTable.minSourceGen,
		min_level: ruleTable.minLevel, max_level: ruleTable.maxLevel,
		default_level: ruleTable.defaultLevel, ev_limit: ruleTable.evLimit,
	},
};

function entry(id, name, kind, extra = {}) {
	return {id, name, native_id_present: nativeIDPresent(kind, id), ...extra};
}
function hookSource(kind, id, hook, callback) {
	if (typeof callback === 'function') {
		return descriptorSource(
			descriptorSources, callback, `${kind}:${id}:${hook}`);
	}
	assert.strictEqual(callback, false);
	assert.strictEqual(kind, 'ability');
	assert(['battlearmor', 'shellarmor'].includes(id) && hook === 'onCriticalHit',
		`unreviewed non-function callback sentinel: ${kind}:${id}:${hook}`);
	return {path: 'data/abilities.ts', symbol: `Abilities.${id}.${hook}`};
}
function hooksFor(kind, values) {
	return values.flatMap(value => ownCallbacks(value).map(({hook, callback}) => ({
		owner_kind: kind, owner_id: value.id, hook,
		showdown_source: hookSource(kind, value.id, hook, callback),
	}))).sort((a, b) => `${a.hook}:${a.owner_kind}:${a.owner_id}`.localeCompare(`${b.hook}:${b.owner_kind}:${b.owner_id}`));
}

const callbackHooks = [
	...hooksFor('move', reachableMoves),
	...hooksFor('ability', reachableAbilities),
	...hooksFor('item', reachableItems),
	...effectiveConditions.filter(id => reachableConditionIDs.has(id))
		.flatMap(id => ownCallbacks(dex.data.Conditions[id]).map(({hook, callback}) => ({
			owner_kind: 'condition', owner_id: id, hook,
			showdown_source: descriptorSource(
				descriptorSources, callback, `condition:${id}:${hook}`),
		}))),
	...runtimeFormatRules.flatMap(rule => ownCallbacks(rule)
		.filter(({hook}) => !runtimeRuleCallbackExclusions.has(hook.split('.')[0]))
		.map(({hook, callback}) => ({
			owner_kind: 'format', owner_id: rule.id, hook,
			showdown_source: descriptorSource(
				descriptorSources, callback, `format:${rule.id}:${hook}`),
		}))),
].sort((a, b) => `${a.hook}:${a.owner_kind}:${a.owner_id}`.localeCompare(`${b.hook}:${b.owner_kind}:${b.owner_id}`));

const artifact = {
	schema: 'pokemon-gen3ou-authoritative-inventory-v2',
	oracle: {repository: 'https://github.com/smogon/pokemon-showdown.git', revision: REVISION, format: 'gen3ou'},
	extraction: {
		generator: 'robots/envs/dev/pokemon_gen3/verify/inventory/generate.js',
		method: [
			'Load Dex.forFormat(gen3ou) and TeamValidator(gen3ou) from the pinned checkout.',
			'Accept species only when checkSpecies passes and at least one single-move, legal-ability set passes validateSet.',
			'Derive submitted-set moves and abilities only when they occur in at least one such validated set; accept items by validating them on a known legal set.',
			'Close runtime-reachable moves over the effective Gen 3 Metronome selection predicate when Metronome is submitted-set reachable, then add simulator-forced Struggle.',
			'Flatten the effective Gen 3 OU RuleTable, including inherited simple rules, bans, complex bans, value rules, and team constraints.',
			'Extract conditions to a fixed point from declarative effect fields, balanced parsing of every condition API call, direct condition-container deletions, embedded condition objects, runtime format rules, and an exhaustively reviewed table of computed condition API arguments on reachable descriptors.',
			'Extract callback hooks from effective reachable descriptors and runtime RuleTable pseudo-weather; simulator-only conditions are effective Gen 3 condition-table entries with no reachable reference.',
		],
		limitations: [
			'Computed condition API arguments are finite manual resolutions checked against every dynamically shaped call found in effective reachable descriptors; generation fails for an unreviewed or stale resolution.',
			'native_id_present means only that the canonical ID exists in the current native ID tables; it makes no behavioral-support claim.',
		],
	},
	runtime_move_closure: {
		submitted_set_count: submittedMoveIDs.size,
		metronome_submitted_set_reachable: submittedMoveIDs.has('metronome'),
		metronome_pool_count: metronomePool.length,
		metronome_only_ids: metronomePool.filter(id => !submittedMoveIDs.has(id)).sort(),
		simulator_forced_ids: ['struggle'],
	},
	sources,
	counts: {},
	species: speciesCandidates.filter(s => legalSpeciesIDs.has(s.id)).map(s => entry(s.id, s.name, 'species', {num: s.num, tier: s.tier})),
	moves: reachableMoves.sort((a, b) => a.id.localeCompare(b.id)).map(m => entry(m.id, m.name, 'moves', {
		target: m.target, category: m.category, type: m.type,
		reachability: moveReachability.get(m.id),
	})),
	abilities: reachableAbilities.sort((a, b) => a.id.localeCompare(b.id)).map(a => entry(a.id, a.name, 'abilities')),
	items: reachableItems.sort((a, b) => a.id.localeCompare(b.id)).map(i => entry(i.id, i.name, 'items')),
	statuses: [...conditionRefs.status].sort().map(id => entry(id, dex.conditions.get(id).name, 'statuses')),
	volatiles: [...conditionRefs.volatile].sort().map(id => entry(id, dex.conditions.get(id).name, 'volatiles')),
	side_conditions: [...conditionRefs.side].sort().map(id => entry(id, dex.conditions.get(id).name, 'side_conditions')),
	weather: [...conditionRefs.weather].sort().map(id => entry(id, dex.conditions.get(id).name, 'weather')),
	pseudo_weather: [...conditionRefs.pseudoWeather].sort().map(id => entry(id, dex.conditions.get(id).name, 'pseudo_weather')),
	slot_conditions: [...conditionRefs.slot].sort().map(id => entry(id, dex.conditions.get(id).name, 'slot_conditions')),
	target_modes: targetModes,
	format_rules: formatRules,
	format_constraints: formatConstraints,
	callback_hooks: callbackHooks,
	dynamic_condition_calls: dynamicConditionCalls.sort((a, b) =>
		`${a.owner_kind}:${a.owner_id}:${a.hook}:${a.api}:${a.argument}:${a.expression}`
			.localeCompare(`${b.owner_kind}:${b.owner_id}:${b.hook}:${b.api}:${b.argument}:${b.expression}`)),
	condition_mutation_calls: conditionMutationCalls.sort((a, b) =>
		`${a.owner_kind}:${a.owner_id}:${a.hook}:${a.api}:${a.arguments.join(',')}`
			.localeCompare(`${b.owner_kind}:${b.owner_id}:${b.hook}:${b.api}:${b.arguments.join(',')}`)),
	condition_direct_deletes: conditionDirectDeletes.sort((a, b) =>
		`${a.owner_kind}:${a.owner_id}:${a.hook}:${a.container}:${a.id}`
			.localeCompare(`${b.owner_kind}:${b.owner_id}:${b.hook}:${b.container}:${b.id}`)),
	scanned_conditions: [...scannedConditionIDs].sort(),
	simulator_only_conditions: effectiveConditions.filter(id => !reachableConditionIDs.has(id)).map(id => ({id, name: dex.conditions.get(id).name})),
};
for (const key of ['species', 'moves', 'abilities', 'items', 'statuses', 'volatiles', 'side_conditions',
	'weather', 'pseudo_weather', 'slot_conditions', 'target_modes', 'format_rules', 'callback_hooks', 'dynamic_condition_calls',
	'condition_mutation_calls', 'condition_direct_deletes', 'scanned_conditions', 'simulator_only_conditions']) {
	artifact.counts[key] = artifact[key].length;
}
fs.mkdirSync(path.dirname(path.resolve(outputPath)), {recursive: true});
fs.writeFileSync(path.resolve(outputPath), `${JSON.stringify(artifact, null, 2)}\n`);
