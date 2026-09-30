'use strict';

const fs = require('fs');
const path = require('path');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const KINDS = new Map([
  ['move', 'moves'],
  ['ability', 'abilities'],
  ['item', 'items'],
]);

function fail(message) {
  throw new Error(message);
}

function arg(name) {
  const index = process.argv.indexOf(name);
  if (index < 0 || !process.argv[index + 1]) fail(`missing ${name}`);
  return path.resolve(process.argv[index + 1]);
}

function literalName(ts, node) {
  const expression = node.arguments[0];
  if (ts.isStringLiteral(expression) || ts.isNoSubstitutionTemplateLiteral(expression)) return expression.text;
  return expression.getText().replace(/\s+/g, ' ');
}

function callName(ts, node) {
  if (!ts.isCallExpression(node)) return '';
  const expression = node.expression;
  if (ts.isIdentifier(expression)) return expression.text;
  if (ts.isPropertyAccessExpression(expression) && ts.isIdentifier(expression.expression)) {
    return `${expression.expression.text}.${expression.name.text}`;
  }
  return '';
}

function declaredGenerations(text) {
  const generations = new Set();
  for (const match of text.matchAll(/common\.gen\((\d+)\)|\[Gen\s+(\d+)\]|\bGen(?:eration)?\s+(\d+)\b/gi)) {
    generations.add(Number(match[1] || match[2] || match[3]));
  }
  return [...generations].sort((a, b) => a - b);
}

const POST_GEN3 = [
  ['dynamax', /\bdynamax|max move|gmax/i],
  ['tera', /\btera(?:stal|type|blast)?\b/i],
  ['z-move', /\bz[- ]?move|zpower|\bz[- ][a-z]/i],
  ['mega-evolution', /\bmega evolve|megaevolution/i],
  ['terrain', /\bterrain\b/i],
  ['later-generation mechanic', /assault[ -]?vest|ability[ -]?shield|eject[ -]?button|life[ -]?orb|mold[ -]?breaker|protean|unaware|poison[ -]?touch|poison[ -]?puppeteer|opportunist|costar|dancer|shell[ -]?trap|final[ -]?gambit|\bflung\b/i],
];

function semanticTags(text, descriptor) {
  const tags = new Set(descriptor.semantic_features || []);
  const rules = [
    ['choice.normalization', /makeChoices|choose\(/i],
    ['switch.lifecycle', /switch|drag|trap/i],
    ['request.legal-choices', /trapped|request|choice/i],
    ['queue.ordering', /priority|speed|before|after|order|tie/i],
    ['event.dispatch', /activate|trigger|on[A-Z]|ability/i],
    ['hit.accuracy', /accuracy|miss|always hit/i],
    ['hit.immunity', /immune|immunity/i],
    ['damage', /damage|hp|hurt|recoil|counter|mirror coat/i],
    ['condition.status', /status|poison|burn|sleep|paraly|freeze/i],
    ['condition.volatile', /volatile|confusion|flinch|disable|encore/i],
    ['condition.weather', /weather|rain|sun|sand|hail/i],
    ['condition.side', /reflect|light screen|spikes/i],
    ['item.lifecycle', /item|berry|eat|consume|knock off|steal/i],
    ['prng', /random|chance|seed|roll|accuracy|critical/i],
    ['faint.terminal', /faint|knock out|winner|tie/i],
  ];
  for (const [tag, pattern] of rules) if (pattern.test(text)) tags.add(tag);
  return [...tags].sort();
}

function boundaries(tags) {
  const result = new Set(['canonical-state']);
  for (const tag of tags) {
    if (/choice|request|switch/.test(tag)) result.add('choices-requests');
    if (/queue|switch|faint/.test(tag)) result.add('action-queue');
    if (/event|condition|ability|item/.test(tag)) result.add('event-handlers');
    if (/hit|damage/.test(tag)) result.add('hit-damage');
    if (/prng|accuracy|critical|random|chance/.test(tag)) result.add('labeled-prng');
    if (/faint|terminal/.test(tag)) result.add('faint-terminal');
  }
  return [...result].sort();
}

const applicableGap = (evidence, needed_case) => ({
  applicability: 'g3_source_applicable', coverage: 'none', evidence, needed_case,
});
const notApplicable = (applicability, evidence) => ({
  applicability, coverage: 'not_applicable', evidence, needed_case: '',
});
const complete = (evidence, differential = [], unit = []) => ({
  applicability: 'g3_source_applicable', coverage: 'complete', evidence,
  needed_case: '', differential, unit,
});
const partial = (evidence, needed_case, differential = [], unit = []) => ({
  applicability: 'g3_source_applicable', coverage: 'partial', evidence,
  needed_case, differential, unit,
});

const DIRECT = new Map(Object.entries({
	'test/sim/moves/memento.js:13': complete(
		'Gen 3 Memento queues its ifHit self-faint after the target boost transaction; Clear Body can reject both drops but does not cancel that successful hit.',
		['memento-clear-body-still-faints'],
		['native/test_pokemon.c#test_if_hit_self_faint_family']),
	'test/sim/moves/memento.js:24': complete(
		'An intact Substitute cancels Gen 3 Memento before the descriptor-owned ifHit self-faint boundary.',
		['memento-substitute-no-faint'],
		['native/test_pokemon.c#test_if_hit_self_faint_family']),
  'test/sim/abilities/arenatrap.js:13': {
    applicability: 'g3_source_applicable', coverage: 'complete', needed_case: '',
    evidence: 'Gen 3 Arena Trap uses the same groundedness/trap boundary. Modern Telekinesis, Gravity, Magnet Rise, and Air Balloon scaffolding is not ported; legal grounded and Flying escape fixtures prove the Gen 3 branches.',
    differential: ['arena-trap-grounded-block', 'arena-trap-flying-escape'],
    unit: ['native/test_pokemon.c#test_hidden_trap_rejection_updates_only_request'],
  },
  'test/sim/abilities/battlearmor.js:13': {
    applicability: 'g3_source_applicable', coverage: 'complete', needed_case: '',
    evidence: 'Pinned Gen 3 inherits Battle Armor critical-hit cancellation. Frost Breath is only modern scaffolding; the exact forced-critical differential proves the same cancellation boundary.',
    differential: ['critical-battle-armor-cancel'], unit: [],
  },
  'test/sim/abilities/clearbody.js:13': {
    applicability: 'g3_source_applicable', coverage: 'complete', needed_case: '',
    evidence: 'Pinned Gen 3 Clear Body rejects negative boosts whose source is not the holder. The generated handler is stat-generic; the exact differential proves the opponent-negative branch.',
    differential: ['try-boost-clear-body'], unit: [],
  },
  'test/sim/abilities/clearbody.js:30': {
    applicability: 'g3_source_applicable', coverage: 'complete', needed_case: '',
    evidence: 'Pinned Gen 3 Clear Body explicitly permits a negative boost when source and target are the same. Replace modern scaffolding with a legal Gen 3 self-drop move.',
    unit: ['native/test_pokemon.c#test_post_hit_self_drop_product'],
  },
  'test/sim/abilities/clearbody.js:41': {
    applicability: 'g3_source_applicable', coverage: 'complete', needed_case: '',
    evidence: 'Pinned Gen 3 Clear Body filters only negative boosts; positive boosts from an opponent remain legal.',
    differential: ['boost-positive-filter-clear-white'], unit: [],
  },
  'test/sim/abilities/clearbody.js:51': {
    applicability: 'mechanic_unreachable_gen3', coverage: 'not_applicable', needed_case: '',
    evidence: 'The assertion uses Topsy-Turvy absolute boost inversion, which did not exist in Gen 3; no legal Gen 3 OU operation exercises this boundary.',
  },
  'test/sim/abilities/clearbody.js:86': {
    applicability: 'g3_source_applicable', coverage: 'complete', needed_case: '',
    evidence: 'The exact legal Gen 3 fixture drives the Clear Body holder to -6 Speed, then proves a hostile Scary Face is rejected at the boost cap before ability prevention.',
    differential: ['clear-body-negative-cap-order'], unit: [],
  },
  'test/sim/abilities/immunity.js:13': {
    applicability: 'g3_source_applicable', coverage: 'complete', needed_case: '',
    evidence: 'Pinned Gen 3 Immunity rejects poison and toxic status through its SetStatus handler; the status-ability rotation covers that branch.',
    differential: ['status-ability-rotation'], unit: ['native/test_pokemon.c#test_status_ability_hooks_and_clauses'],
  },
  'test/sim/abilities/immunity.js:22': {
	applicability: 'g3_source_applicable', coverage: 'complete', needed_case: '',
	evidence: 'Skill Swap is legal in Gen 3 and can transfer Immunity to an already poisoned target; the exact fixture proves the effective Gen 3 Start handler immediately cures the status.',
	differential: ['immunity-skill-swap-cure'], unit: [],
  },
  'test/sim/abilities/levitate.js:13': {
    applicability: 'g3_source_applicable', coverage: 'complete', needed_case: '',
    evidence: 'Pinned Gen 3 Levitate supplies Ground immunity; exact Earthquake and Bone Rush fixtures prove both ordinary and multihit gates.',
    differential: ['derived-levitate-earthquake-immunity', 'derived-levitate-bone-rush-immunity'], unit: [],
  },
  'test/sim/abilities/levitate.js:22': {
    applicability: 'g3_source_applicable', coverage: 'complete', needed_case: '',
    evidence: 'Electric Terrain is modern scaffolding, but the exact three-layer Spikes fixture switches a Levitate Gengar in without entry damage, directly proving the Gen 3 groundedness relation.',
    differential: ['spikes-layers-cap-immunity'], unit: [],
  },
  'test/sim/abilities/rockhead.js:13': {
    applicability: 'g3_source_applicable', coverage: 'complete', needed_case: '',
    evidence: 'Pinned Gen 3 Rock Head prevents ordinary move recoil. The Double-Edge transaction is covered exactly.',
    differential: ['recoil-rock-head-prevention'], unit: ['native/test_pokemon.c#test_damage_relative_recoil_and_rock_head'],
  },
  'test/sim/abilities/rockhead.js:20': {
    applicability: 'mechanic_unreachable_gen3', coverage: 'not_applicable', needed_case: '',
    evidence: 'The assertion requires Mummy to replace Rock Head during the damaging hit; Mummy and this mid-hit removal path do not exist in Gen 3.',
  },
  'test/sim/abilities/rockhead.js:27': {
    applicability: 'g3_source_applicable', coverage: 'complete', needed_case: '',
    evidence: 'Gen 3 Struggle recoil bypasses Rock Head. Focused and differential evidence exercise the forced Struggle transaction.',
    differential: ['recoil-rock-head-struggle'], unit: ['native/test_pokemon.c#test_empty_pp_projects_and_executes_struggle', 'native/test_pokemon.c#test_damage_relative_recoil_and_rock_head'],
  },
  'test/sim/abilities/rockhead.js:35': {
    applicability: 'g3_source_applicable', coverage: 'complete', needed_case: '',
    evidence: 'A legal Sudowoodo copies Jump Kick with Mimic and crashes into Protect; exact state and event evidence proves Rock Head does not suppress crash damage.',
    differential: ['rock-head-does-not-block-crash'], unit: [],
  },
  'test/sim/abilities/rockhead.js:42': {
    applicability: 'g3_source_applicable', coverage: 'complete', needed_case: '',
    evidence: 'The exact legal Gen 3 fixture poisons a Rock Head Sudowoodo and observes toxic residual damage, proving the ability is scoped only to recoil.',
    differential: ['rock-head-does-not-block-indirect'], unit: [],
  },
  'test/sim/abilities/shellarmor.js:13': {
    applicability: 'g3_source_applicable', coverage: 'complete', needed_case: '',
    evidence: 'Pinned Gen 3 inherits Shell Armor critical-hit cancellation. An exact forced-critical differential proves the assertion without Frost Breath scaffolding.',
    differential: ['critical-shell-armor-cancel'], unit: [],
  },
  'test/sim/abilities/shielddust.js:23': {
    applicability: 'g3_source_applicable', coverage: 'complete', needed_case: '',
    evidence: 'Pinned Gen 3 Shield Dust suppresses secondaries received by the holder, not source-owned self effects. Exact Silver Wind and Ancient Power fixtures prove the self-secondary remains intact.',
    differential: ['shield-dust-holder-secondary-ownership', 'grouped-ancient-power-serene-grace'], unit: [],
  },
  'test/sim/abilities/shielddust.js:31': {
    applicability: 'format_unreachable_gen3ou_singles', coverage: 'not_applicable', needed_case: '',
    evidence: 'The only Gen 3 item-added flinch secondary is King\'s Rock, which the pinned Gen 3 OU RuleTable bans and no runtime item operation can create.',
  },
  'test/sim/abilities/shielddust.js:49': {
    applicability: 'mechanic_unreachable_gen3', coverage: 'not_applicable', needed_case: '',
    evidence: 'Fling is a Gen 4 move and has no Gen 3 runtime path.',
  },
  'test/sim/abilities/shielddust.js:57': {
    applicability: 'g3_source_applicable', coverage: 'complete', needed_case: '',
    evidence: 'The effective Gen 3 handler is target-side. An exact legal fixture proves a Shield Dust holder\'s Psychic still lowers the target\'s Special Defense and its Silver Wind self-secondary remains intact.',
    differential: ['shield-dust-holder-secondary-ownership'], unit: [],
  },
  'test/sim/abilities/suctioncups.js:13': {
    applicability: 'g3_source_applicable', coverage: 'complete', needed_case: '',
    evidence: 'Pinned Gen 3 Suction Cups cancels forced drag; the legal Roar fixture and focused generated-blocker test prove the assertion.',
    differential: ['drag-suction-cups-block'], unit: ['native/test_pokemon.c#test_generated_drag_blockers'],
  },
  'test/sim/abilities/sturdy.js:13': {
    applicability: 'g3_source_applicable', coverage: 'complete', needed_case: '',
    evidence: 'Effective Gen 3 Sturdy retains only its OHKO TryHit cancellation. A successful legal Sheer Cold differential proves the cancellation, while the focused family test proves ordered dispatch and ordinary lethal-damage fallthrough.',
    differential: ['ohko-sheer-cold-sturdy'], unit: ['native/test_pokemon.c#test_typed_ohko_pipeline'],
  },
  'test/sim/abilities/cloudnine.js:13': partial(
    'Gen 3 Cloud Nine suppresses effective weather without removing field weather. Existing fixtures cover several consumers but not the Forecast forme boundary named by the assertion.',
    'cloud-nine-forecast-and-consumer-basis',
    ['solar-beam-cloud-nine-sun', 'weather-ball-cloud-nine', 'weather-swift-swim-suppressed', 'weather-recovery-cloud-nine-suppression', 'weather-rain-dish-suppressed'],
    []),
  'test/sim/abilities/cloudnine.js:25': complete(
    'Gen 3 Cloud Nine suppresses sun damage modifiers while preserving stored weather; the exact product fixture uses legal Fire- and Water-type attacks.',
    ['weather-cloud-nine-damage-product'],
    ['native/test_pokemon.c#test_cloud_nine_suppresses_effective_not_stored_weather']),
  'test/sim/abilities/cloudnine.js:41': complete(
    'Gen 3 Cloud Nine suppresses rain damage modifiers while preserving stored weather; the exact product fixture uses legal Fire- and Water-type attacks.',
    ['weather-cloud-nine-damage-product'],
    ['native/test_pokemon.c#test_cloud_nine_suppresses_effective_not_stored_weather']),
  'test/sim/abilities/cloudnine.js:57': complete(
    'Gen 3 Cloud Nine suppresses the nested Sandstorm Weather event while preserving FieldResidual execution and weather duration.',
    ['weather-cloud-nine-residual-product'],
    ['native/test_pokemon.c#test_cloud_nine_suppresses_effective_not_stored_weather']),
  'test/sim/abilities/cloudnine.js:66': complete(
    'Gen 3 Cloud Nine suppresses the nested Hail Weather event while preserving FieldResidual execution and weather duration.',
    ['weather-cloud-nine-residual-product'],
    ['native/test_pokemon.c#test_cloud_nine_suppresses_effective_not_stored_weather']),
  'test/sim/abilities/cloudnine.js:75': notApplicable('mechanic_unreachable_gen3',
    'Desolate Land and primal weather do not exist in Gen 3.'),
  'test/sim/abilities/cloudnine.js:84': notApplicable('mechanic_unreachable_gen3',
    'Primordial Sea and primal weather do not exist in Gen 3.'),
  'test/sim/abilities/cloudnine.js:93': notApplicable('mechanic_unreachable_gen3',
    'Delta Stream and strong winds do not exist in Gen 3.'),
  'test/sim/abilities/cloudnine.js:102': notApplicable('outside_native_observable_contract',
    'The assertion is specifically about Showdown protocol weather-upkeep display. Canonical weather persistence is covered separately; protocol rendering is outside the native observable contract.'),
  'test/sim/abilities/cloudnine.js:118': notApplicable('mechanic_unreachable_gen3',
    'Hydration and the modern faint-order interaction were introduced after Gen 3.'),
  'test/sim/abilities/colorchange.js:13': complete(
    'Pinned Gen 3 inherits Color Change after a damaging hit; exact fixtures prove effective-type replacement and its damage consequences.',
    ['color-change-flying-ground', 'color-change-steel-stab-control', 'color-change-steel-toxic-immunity', 'color-change-steel-sand-immunity', 'color-change-switch-restoration'],
    ['native/test_pokemon.c#test_color_change_effective_type_product']),
  'test/sim/abilities/colorchange.js:24': complete(
    'Pinned Gen 3 Color Change runs after move secondary resolution and does not activate when Substitute receives the hit.',
    ['color-change-substitute-no-activation', 'color-change-multihit-substitute'],
    ['native/test_pokemon.c#test_color_change_effective_type_product']),
  'test/sim/abilities/damp.js:13': complete(
    'Pinned Gen 3 Damp blocks Explosion and Self-Destruct before their self-faint transaction.',
    ['damp-explosion', 'damp-self-destruct', 'damp-ordinary-pass'],
    ['native/test_pokemon.c#test_global_try_move_handler_blocks_self_faint_family']),
  'test/sim/abilities/damp.js:25': notApplicable('mechanic_unreachable_gen3',
    'Aftermath was introduced in Gen 4.'),
  'test/sim/abilities/flashfire.js:13': complete(
    'Gen 3 Flash Fire grants Fire immunity and a persistent 1.5x Fire modifier after activation; the exact activation, repeat-hit, and downstream damage fixtures prove the assertion.',
    ['flash-fire-activation-repeat-boost', 'flash-fire-willowisp-fire-holder'],
    ['native/test_pokemon.c#test_flash_fire_generated_lifecycle']),
  'test/sim/abilities/flashfire.js:26': notApplicable('generation_semantics_differ',
    'Effective Gen 3 Flash Fire returns before immunity when the holder is frozen; the Fire hit instead damages and thaws it. The dedicated explicit Gen 3 regression records that behavior.'),
  'test/sim/abilities/flashfire.js:46': complete(
    'Skill Swap is legal in Gen 3; ending Flash Fire removes its activation state before subsequent Fire damage.',
    ['skill-swap-flash-fire-end'],
    ['native/test_pokemon.c#test_flash_fire_generated_lifecycle',
      'native/test_pokemon.c#test_skill_swap_transaction']),
  'test/sim/abilities/intimidate.js:22': complete(
    'The Gen 3 override explicitly skips each opposing target behind Substitute and emits no activation if every target is protected.',
    [], ['native/test_pokemon.c#test_generated_intimidate_start_family']),
  'test/sim/abilities/intimidate.js:75': notApplicable('format_unreachable_gen3ou_singles',
    'The assertion requires ordering multiple simultaneous active switch-ins; Gen 3 OU singles has one active slot per side.'),
  'test/sim/abilities/intimidate.js:109': notApplicable('format_unreachable_gen3ou_singles',
    'The assertion requires multiple simultaneous double-KO replacements; Gen 3 OU singles has one active slot per side.'),
  'test/sim/abilities/liquidooze.js:13': complete(
    'Liquid Ooze and draining moves exist in Gen 3; the exact Giga Drain fixture proves the effective handler reverses drain healing into damage.',
    ['leech-seed-liquid-ooze-drain']),
  'test/sim/abilities/liquidooze.js:23': complete(
    'Liquid Ooze and Leech Seed exist in Gen 3; exact differential and focused evidence prove the residual drain owner and reversed transfer staging.',
    ['leech-seed-liquid-ooze-drain'],
    ['native/test_pokemon.c#test_source_linked_residual_transfer_family']),
  'test/sim/abilities/magnetpull.js:13': complete(
    'The Gen 3 override traps adjacent Steel types regardless of Flying type. Exact Steel/Flying and non-Steel fixtures prove the legal-choice boundary.',
    ['magnet-pull-steel-flying-block', 'magnet-pull-nonsteel-escape'],
    ['native/test_pokemon.c#test_hidden_trap_rejection_updates_only_request']),
  'test/sim/abilities/magnetpull.js:32': complete(
	'Gen 3 trapping restricts normal switch choices but does not cancel move-driven switching; the exact legal Baton Pass fixture proves the forced recipient request and escape.',
	['magnet-pull-baton-pass-escape']),
  'test/sim/abilities/magnetpull.js:44': notApplicable('generation_semantics_differ',
    'The default assertion relies on modern generic trapping immunity. Gen 3 Magnet Pull instead unconditionally traps adjacent Steel types.'),
  'test/sim/abilities/naturalcure.js:9': partial(
    'Pinned Gen 3 Natural Cure runs on switch-out. Existing evidence proves voluntary switching, but not the upstream phazing order.',
    'natural-cure-roar-drag-out', ['natural-cure-switch-out'], ['native/test_pokemon.c#test_natural_cure_switch_out']),
  'test/sim/abilities/owntempo.js:13': notApplicable('generation_semantics_differ',
    'Own Tempo only prevents confusion in Gen 3. Its Intimidate immunity was added in Gen 8.'),
  'test/sim/abilities/pickup.js:13': notApplicable('generation_semantics_differ',
    'Effective Gen 3 Pickup has no in-battle residual callback; its generation-appropriate effect occurs outside battle.'),
  'test/sim/abilities/pickup.js:29': notApplicable('generation_semantics_differ',
    'Effective Gen 3 Pickup has no in-battle residual callback, so Knock Off retrieval is not a Gen 3 battle assertion.'),
  'test/sim/abilities/pickup.js:37': notApplicable('mechanic_unreachable_gen3',
    'Air Balloon and in-battle Pickup do not exist in Gen 3.'),
  'test/sim/abilities/pickup.js:62': notApplicable('generation_semantics_differ',
    'Effective Gen 3 Pickup has no in-battle residual callback; switched-out item provenance is a later-generation mechanic.'),
  'test/sim/abilities/pickup.js:77': notApplicable('generation_semantics_differ',
    'Effective Gen 3 Pickup has no in-battle residual callback; retrieved-item provenance is a later-generation mechanic.'),
  'test/sim/abilities/pressure.js:45': complete(
    'Gen 3 Pressure deducts PP at targeting before success, accuracy, Protect, or type-immunity resolution.',
    ['pressure-protect', 'pressure-immunity', 'pressure-miss'],
    ['native/test_pokemon.c#test_pressure_generic_pp_deduction_stage']),
  'test/sim/abilities/pressure.js:129': notApplicable('generation_semantics_differ',
	'Pinned Gen 3 scripts run Pressure only when sourceEffect is absent (or Pursuit), so delegated submoves deliberately do not deduct extra caller PP. The modern callerMoveForPressure behavior is not inherited.'),
  'test/sim/abilities/pressure.js:141': notApplicable('mechanic_unreachable_gen3',
    'Sticky Web was introduced after Gen 3.'),
  'test/sim/abilities/pressure.js:172': complete(
	'Magic Coat exists in Gen 3. The exact fixture proves its reflected condition-source invocation does not perform a second Pressure deduction after the selected move paid PP.',
	['pressure-magic-coat-no-double-deduction']),
  'test/sim/abilities/roughskin.js:14': partial(
    'The Gen 3 override dispatches one onDamagingHit callback per connected contact hit. Existing evidence proves contact damage but not the upstream secondary-effect no-redispatch regression.',
    'rough-skin-secondary-single-dispatch', ['rough-skin-contact'], ['native/test_pokemon.c#test_source_base_max_hp_fraction_contact_damage']),
  'test/sim/abilities/stickyhold.js:15': partial(
    'Gen 3 Sticky Hold rejects opponent item-taking at the generic TakeItem boundary. Existing evidence proves Knock Off and Trick, but not every legal stealing path represented by the upstream assertion.',
    'sticky-hold-thief-covet-basis',
    ['item-knock-off-sticky-hold', 'item-trick-sticky-preaccuracy'],
    ['native/test_pokemon.c#test_generic_item_mutation_family']),
  'test/sim/abilities/sturdy.js:13': complete(
    'Effective Gen 3 Sturdy retains only OHKO immunity; the exact legal Sheer Cold fixture proves cancellation at TryHit.',
    ['ohko-sheer-cold-sturdy'], ['native/test_pokemon.c#test_typed_ohko_pipeline']),
  'test/sim/abilities/sturdy.js:20': notApplicable('generation_semantics_differ',
    'The full-HP survival effect was introduced in Gen 5; effective Gen 3 Sturdy has no onDamage handler.'),
  'test/sim/abilities/sturdy.js:28': notApplicable('generation_semantics_differ',
    'The full-HP survival effect was introduced in Gen 5; effective Gen 3 Sturdy has no onDamage handler.'),
  'test/sim/abilities/sturdy.js:36': notApplicable('generation_semantics_differ',
    'The assertion distinguishes modern full-HP survival from recoil. Gen 3 Sturdy has only OHKO immunity.'),
  'test/sim/abilities/sturdy.js:44': notApplicable('generation_semantics_differ',
    'The assertion distinguishes modern full-HP survival from residual damage. Gen 3 Sturdy has only OHKO immunity.'),
  'test/sim/abilities/sturdy.js:60': notApplicable('mechanic_unreachable_gen3',
    'Focus Sash was introduced in Gen 4, and Gen 3 Sturdy has no full-HP survival effect.'),
  'test/sim/abilities/sturdy.js:71': notApplicable('generation_semantics_differ',
    'Gen 3 Sturdy has no full-HP survival activation to order against Endure.'),
  'test/sim/abilities/sturdy.js:83': notApplicable('generation_semantics_differ',
    'Gen 3 Sturdy has no full-HP survival activation to suppress when False Swipe leaves 1 HP.'),
  'test/sim/abilities/synchronize.js:13': complete(
    'The exact legal fixture proves Synchronize reflection completes before either holder consumes Lum Berry, leaving both cured and both items consumed.',
    ['synchronize-before-lum-berry'], []),
  'test/sim/abilities/thickfat.js:13': complete(
    'Pinned Gen 3 Thick Fat halves Fire and Ice source base power; exact Fire Punch, Ice Punch, and control fixtures prove the type gate.',
    ['thick-fat-firepunch', 'thick-fat-icepunch', 'thick-fat-psychic'],
    ['native/test_pokemon.c#test_thick_fat_source_base_power']),
  'test/sim/abilities/trace.js:13': complete(
    'The Gen 3 override copies a random foe ability on start. The re-entry fixture proves replacement and subsequent copied-ability behavior.',
    ['trace-reentry-intimidate'], ['native/test_pokemon.c#test_trace_replaces_ability_without_starting_copy']),
  'test/sim/abilities/trace.js:25': notApplicable('generation_semantics_differ',
    'The Gen 3 Trace override clears modern `notrace` flags and has no delayed onUpdate retry; it copies the selected foe ability immediately.'),
  'test/sim/abilities/trace.js:87': complete(
    'Gen 3 Trace has only onStart and does not retain modern onUpdate rediscovery; the focused test proves replacement does not recursively start the copied ability.',
    ['trace-reentry-intimidate'], ['native/test_pokemon.c#test_trace_replaces_ability_without_starting_copy']),
  'test/sim/abilities/truant.js:13': complete(
    'The Gen 3 override toggles explicit truantTurn state at residual and blocks BeforeMove on loafing turns.',
    ['truant-basic-alternation'], ['native/test_pokemon.c#test_generated_truant_pokemon_owned_phase']),
  'test/sim/abilities/truant.js:23': complete(
    'Recharge and Truant coexist in Gen 3; verify the recharge action owns one turn while residual Truant state advances once.',
    ['truant-recharge-staging'], ['native/test_pokemon.c#test_generated_truant_pokemon_owned_phase']),
  'test/sim/abilities/truant.js:36': complete(
    'Gen 3 sleep checks and Truant BeforeMove ordering determine whether waking consumes an acting or loafing turn.',
    ['truant-wake-after-acting-turn'], ['native/test_pokemon.c#test_generated_truant_pokemon_owned_phase']),
  'test/sim/abilities/truant.js:48': complete(
    'Gen 3 sleep checks and Truant BeforeMove ordering determine whether waking after a loafing turn permits action.',
    ['truant-wake-after-loafing-turn'], ['native/test_pokemon.c#test_generated_truant_pokemon_owned_phase']),
  'test/sim/abilities/truant.js:65': complete(
    'Two-turn moves and Gen 3 Truant coexist; verify charge state does not bypass the following loafing turn.',
    ['truant-two-turn-move-failure'], ['native/test_pokemon.c#test_generated_truant_pokemon_owned_phase']),
  'test/sim/abilities/wonderguard.js:13': complete(
    'Pinned Gen 3 Wonder Guard permits only super-effective damaging hits after ordinary type immunity.',
    ['wonder-guard-effectiveness'], ['native/test_pokemon.c#test_wonder_guard_generic_effectiveness_gate']),
  'test/sim/abilities/wonderguard.js:25': complete(
    'The effective Gen 3 handler explicitly permits status moves; the exact Growl fixture proves the status-category action reaches and changes a Wonder Guard holder.',
    ['wonder-guard-bypass-and-order'],
    ['native/test_pokemon.c#test_wonder_guard_generic_effectiveness_gate']),
  'test/sim/abilities/wonderguard.js:47': notApplicable('generation_semantics_differ',
    'For Gen 3, battle-actions resolves ordinary type immunity before TryHit, so Wonder Guard never emits its own immunity for an already type-immune target. The modern assertion expects the opposite event owner.'),
  'test/sim/abilities/wonderguard.js:57': complete(
    'The effective handler explicitly exempts Struggle, and focused forced-Struggle evidence proves the typeless hit bypass.',
    ['recoil-rock-head-struggle'], ['native/test_pokemon.c#test_empty_pp_projects_and_executes_struggle', 'native/test_pokemon.c#test_wonder_guard_generic_effectiveness_gate']),
  'test/sim/abilities/wonderguard.js:67': notApplicable('generation_semantics_differ',
    'Gen 3 inherits the Gen 4 Wonder Guard callback which explicitly permits typeless moves before effectiveness gating; the modern assertion expects typeless non-Struggle moves to be blocked.'),
  'test/sim/items/lansatberry.js:13': complete(
    'Gen 3 Lansat Berry establishes Focus Energy when consumed at its one-quarter residual threshold.',
    ['berry-lansat-threshold', 'berry-lansat-focus-energy-duplicate'],
    ['native/test_pokemon.c#test_lansat_berry_volatile_transaction']),
  'test/sim/items/lansatberry.js:23': notApplicable('generation_semantics_differ',
    'The Gen 3 override removes onUpdate and checks Lansat Berry only at residual order 10; it cannot activate in the middle of a multihit attack.'),
  'test/sim/items/leppaberry.js:13': notApplicable('mechanic_unreachable_gen3',
    'The assertion requires forcing another Pokemon to eat a berry. Its Fling setup and equivalent forced-eating moves do not exist in Gen 3.'),
  'test/sim/items/lumberry.js:13': complete(
    'Gen 3 Lum Berry cures primary nonvolatile status; exact primary and secondary status fixtures cover the transaction.',
    ['berry-lum-primary-status', 'berry-lum-secondary-status'],
    ['native/test_pokemon.c#test_combined_cure_berry_transaction']),
  'test/sim/items/lumberry.js:21': complete(
    'Gen 3 Lum Berry cures confusion; exact update and status-then-confusion fixtures prove volatile removal and single consumption.',
    ['berry-lum-confusion-update', 'berry-lum-status-then-confusion'],
    ['native/test_pokemon.c#test_combined_cure_berry_transaction']),
  'test/sim/items/lumberry.js:29': complete(
    'Pinned Gen 3 Lum Berry observes newly applied status through the item update boundary and consumes exactly once.',
    ['berry-lum-primary-status', 'berry-lum-secondary-status', 'berry-lum-status-mismatch-no-double-eat'],
    ['native/test_pokemon.c#test_combined_cure_berry_transaction']),
  'test/sim/items/mail.js:13': complete(
    'Gen 3 Mail rejects Trick and ordinary generic item transfer; the exact rollback fixture proves item identity remains with the holder.',
    ['item-trick-mail-rollback'], ['native/test_pokemon.c#test_generic_item_mutation_family']),
  'test/sim/items/mail.js:29': notApplicable('mechanic_unreachable_gen3',
    'Fling was introduced in Gen 4.'),
  'test/sim/items/mail.js:37': complete(
    'A legal Sableye Knock Off removes Mail from Tyrogue; exact item ownership and event evidence proves the Gen 3 exception to Mail transfer restrictions.',
    ['mail-knock-off-removal'], []),
  'test/sim/items/mail.js:45': partial(
    'Gen 3 Thief is allowed to steal Mail. Existing Covet evidence shares the generic steal transaction but does not execute Thief itself.',
    'mail-thief-transfer', ['item-covet-mail-transfer'], ['native/test_pokemon.c#test_generic_item_mutation_family']),
  'test/sim/items/shellbell.js:27': complete(
    'Shell Bell uses accumulated move.totalDamage after all Gen 3 multihit strikes and heals once from the aggregate.',
    ['shell-bell-multihit-aggregate', 'shell-bell-overkill-cap'],
    []),
  'test/sim/items/sitrusberry.js:13': notApplicable('generation_semantics_differ',
    'Effective Gen 3 Sitrus Berry heals a fixed 30 HP, not one quarter of maximum HP.'),
  'test/sim/items/sitrusberry.js:23': notApplicable('generation_semantics_differ',
    'The modern assertion depends on immediate onUpdate consumption before Recycle. Gen 3 deletes onUpdate: Recycle sees the still-held berry and fails, then Sitrus consumes once at residual for a fixed 30 HP.'),
  'test/sim/items/sitrusberry.js:35': complete(
    'The exact legal fixture removes a below-half holder\'s Sitrus Berry with Knock Off before residual and proves no 30-HP heal occurs.',
    ['sitrus-knock-off-before-residual'], []),
  'test/sim/items/sitrusberry.js:44': notApplicable('generation_semantics_differ',
    'This skipped default-generation assertion concerns immediate onUpdate behavior. Gen 3 removes onUpdate and checks Sitrus Berry only during residual.'),
  'test/sim/items/sitrusberry.js:56': notApplicable('generation_semantics_differ',
    'This skipped default-generation assertion expects activation after any end-of-turn effect. Gen 3 uses one ordered residual check and can defer activation after later status damage.'),
	'test/sim/moves/camouflage.js:13': complete(
		'Gen 3 inherits the Gen 4 Camouflage callback unchanged: it replaces the user type with Normal.',
		['camouflage-normal-switch-reset'],
		['native/test_pokemon.c#test_current_move_slot_type_overlays']),
	'test/sim/moves/camouflage.js:75': complete(
		'Gen 3 inherits the Gen 4 callback; a constructed Normal/Flying holder proves the callback fails without collapsing the type product.',
		['camouflage-already-normal-dual-type'],
		['native/test_pokemon.c#test_current_move_slot_type_overlays']),
	'test/sim/moves/focuspunch.js:89': complete(
		'Gen 3 inherits the Gen 4 Focus Punch onTry cancellation, which runs after ordinary PP deduction.',
		['focus-punch-interrupted-pp-spent'],
		['native/test_pokemon.c#test_focus_punch_prepared_action_lifecycle']),
	'test/sim/moves/focuspunch.js:142': complete(
		'Gen 3 uses the inherited order-5 beforeTurnCallback action, so preparation precedes ordinary switch actions.',
		['focus-punch-preparation-before-switch'],
		['native/test_pokemon.c#test_focus_punch_prepared_action_lifecycle']),
	'test/sim/moves/painsplit.js:13': complete(
		'The upstream fixture uses later-generation Shedinja scaffolding, but its assertion is the inherited floor-average assignment. Legal Gen 3 fixtures prove the same assertion plus independent source/target maximum-HP clamps.',
		['pain-split-odd-floor', 'pain-split-source-max-clamp', 'pain-split-shedinja-target-clamp'],
		['native/test_pokemon.c#test_pain_split_atomic_bilateral_hp_assignment']),
	'test/sim/moves/sleeptalk.js:25': complete(
		'Gen 3 composes the inherited Gen 4 choice-lock onTryHit rejection with its own Sleep Talk delegation and pre-Gen-5 PP staging; the exact fixture proves the subsequent rejection and parent PP spend.',
		['sleep-talk-choice-lock-subsequent-rejection']),
  'test/sim/items/whiteherb.js:13': notApplicable('mechanic_unreachable_gen3',
    'Parting Shot and move-driven switching combined with target stat drops do not exist in Gen 3.'),
  'test/sim/items/whiteherb.js:47': notApplicable('mechanic_unreachable_gen3',
    'Abilities that raise stats after scoring a knockout were introduced after Gen 3.'),
  'test/sim/moves/sheercold.js:13': {
    applicability: 'different_generation_not_direct_evidence', coverage: 'not_applicable', needed_case: '',
    evidence: 'The default-generation assertion tests the later Ice-type immunity (`ohko: "Ice"`). Effective Gen 3 Sheer Cold has `ohko: true`, so the assertion is not a Gen 3 semantic requirement. Sheer Cold remains runtime-reachable through legal Metronome and is covered separately by the Gen 3 OHKO family.',
  },
  'test/sim/moves/struggle.js:13': {
    applicability: 'g3_source_applicable', coverage: 'complete', needed_case: '',
    evidence: 'Although the upstream body executes Gen 4, its stated assertion is generation-independent and pinned Gen 3 retains typeless Struggle plus one-quarter recoil.',
    differential: ['recoil-rock-head-struggle', 'choice-torment-cycle', 'regressions/gen3ou/cases/seed42-battle04-complete-struggle.json'],
    unit: [
      'native/test_pokemon.c#test_empty_pp_projects_and_executes_struggle',
      'native/test_pokemon.c#test_wonder_guard_generic_effectiveness_gate',
      'native/test_pokemon.c#test_damage_relative_recoil_and_rock_head',
    ],
    note: 'Focused evidence composes forced Struggle execution, typeless Wonder Guard bypass, recoil, and terminal resolution. An exact Shedinja fixture would be redundant strengthening.',
  },
  'test/sim/abilities/flashfire.js:65': {
    coverage: 'complete', needed_case: '',
    differential: ['flash-fire-frozen-fallthrough'],
    unit: ['native/test_pokemon.c#test_flash_fire_generated_lifecycle'],
    note: 'Pinned assertion proves a frozen Gen 3 holder is damaged; the exact fixture preserves that behavior despite the misleading upstream title.',
  },
  'test/sim/abilities/magnetpull.js:56': {
    applicability: 'format_unreachable_gen3ou_singles', coverage: 'not_applicable', needed_case: '',
    evidence: 'The test constructs gameType doubles and traps an allied Steel-type active slot.',
  },
  'test/sim/abilities/thickfat.js:27': {
    coverage: 'complete', needed_case: '',
    differential: ['thick-fat-type-item-composition'], unit: [],
    note: 'The exact legal Never-Melt Ice plus Ice Punch fixture proves the source type-item modifier composes with target-side Thick Fat.',
  },
  'test/sim/items/quickclaw.js:30': {
    coverage: 'complete', needed_case: '',
    differential: ['quick-claw-induced-speed-tie'], unit: [],
    note: 'The exact fixture activates two unequal-Speed Quick Claw holders from one shared turn roll and proves the resulting queue tie draw.',
  },
  'test/sim/items/sitrusberry.js:69': {
    coverage: 'complete', needed_case: '',
    differential: ['sitrus-status-residual-deferral'], unit: [],
    note: 'The five-turn exact fixture proves Toxic damage crossing half HP after the item check defers Sitrus consumption to the next residual pass.',
  },
  'test/sim/moves/brickbreak.js:97': {
    applicability: 'format_unreachable_gen3ou_singles', coverage: 'not_applicable', needed_case: '',
    evidence: 'The test constructs gameType doubles and targets an ally to remove the opposing side screen.',
  },
  'test/sim/moves/brickbreak.js:41': notApplicable('generation_semantics_differ',
    'The skipped assertion expects a Gen 4-or-earlier ordering that the pinned engine does not implement for Gen 3. sim/battle-actions.ts swaps type immunity before TryHit for generations through 6, so a Ghost immunity prevents the Gen 3 Brick Break onTryHit screen removal. The exact brick-break-type-immune oracle fixture proves the resolved Gen 3 behavior.'),
  'test/sim/moves/conversion2.js:67': complete(
    'Pinned Gen 3 explicitly permits selecting a resistant type the user already has. The singleton Dragon-to-Steel fixture and focused constructed-state test prove that rule.',
    ['conversion2-dragon-singleton'],
    ['native/test_pokemon.c#test_conversion_2_resolved_last_move_response',
      'native/test_pokemon.c#test_type_response_policy_validation_is_atomic']),
  'test/sim/moves/followme.js:88': {
    applicability: 'format_unreachable_gen3ou_singles', coverage: 'not_applicable', needed_case: '',
    evidence: 'Follow Me redirection requires multiple active slots; the test constructs gameType doubles.',
  },
  'test/sim/moves/furycutter.js:34': {
    coverage: 'complete', needed_case: '',
    differential: ['fury-cutter-ramp-cap'],
    unit: ['native/test_pokemon.c#test_fury_cutter_generated_ramping_power_lifecycle'],
    note: 'Six exact connected hits prove Gen 3 doubling and the 160-power cap.',
  },
  'test/sim/moves/glare.js:27': {
    coverage: 'complete', needed_case: '',
    differential: ['glare-natural-type-immunity'],
    unit: ['native/test_pokemon.c#test_primary_major_status_family'],
    note: 'The exact Gen 3 fixture proves that Glare discovers Ghost type immunity, still consumes the Gen 3 accuracy draw, suppresses status admission, and reports immunity after the draw.',
  },
  'test/sim/moves/haze.js:202': {
    coverage: 'complete', needed_case: '',
    differential: ['haze-preserves-focus-energy'],
    unit: ['native/test_pokemon.c#test_haze_hit_field_boundary'],
    note: 'The two-turn exact fixture installs Focus Energy, then proves Haze clears boosts without removing that independent volatile.',
  },
  'test/sim/moves/pursuit.js:240': {
    coverage: 'complete', needed_case: '',
    differential: ['pursuit-switch-survives', 'pursuit-switch-ko-continues'],
    unit: ['native/test_pokemon.c#test_generic_queued_move_interception'],
    note: 'The two exact fixtures prove both the upstream surviving-target assertion and Gen 3 continued-switch behavior after a lethal interception.',
  },
  'test/sim/moves/pursuit.js:251': {
    applicability: 'format_unreachable_gen3ou_singles', coverage: 'not_applicable', needed_case: '',
    evidence: 'Target identity among two opposing active slots requires Doubles.',
  },
  'test/sim/moves/pursuit.js:269': {
    applicability: 'format_unreachable_gen3ou_singles', coverage: 'not_applicable', needed_case: '',
    evidence: 'Ally targeting and simultaneous opposing switch require Doubles.',
  },
  'test/sim/moves/charge.js:13': complete(
    'The resolved pinned Gen 3 ModdedDex keeps Charge\'s Electric-only BasePower handler while removing the modern Special Defense boost. The next Electric attack therefore receives the twofold base-power modifier.',
    ['charge-gen3-electric-base-power'],
    ['native/test_pokemon.c#test_generic_charge_lifecycle']),
  'test/sim/moves/charge.js:25': notApplicable('different_generation_not_direct_evidence',
    'The assertion is false for the resolved pinned Gen 3 ModdedDex. Gen 3 recursively inherits through gen4..gen8, whose Charge condition removes the volatile after any non-Charge move; direct Dex.forGen(3) inspection and the pinned oracle both confirm that effective callback.'),
  'test/sim/moves/charge.js:44': complete(
    'The resolved pinned Gen 3 Charge cleanup applies after any non-Charge move. Thunder Wave is legal in Gen 3 and proves that status-move cleanup still occurs after completion.',
    ['charge-gen3-any-move-and-electric-status'],
    ['native/test_pokemon.c#test_generic_charge_lifecycle']),
  'test/sim/moves/charge.js:64': complete(
    'Although the upstream test explicitly selects Gen 8, the resolved pinned Gen 3 ModdedDex recursively inherits that exact Charge condition override. A legal Gen 3 Charge then Tackle scenario must therefore prove the same any-non-Charge-move cleanup.',
    ['charge-gen3-any-move-and-electric-status'],
    ['native/test_pokemon.c#test_generic_charge_lifecycle']),
  'test/sim/moves/weatherball.js:50': {coverage: 'complete', needed_case: '', differential: ['retaliation-weather-ball-rain-counter']},
  'test/sim/moves/weatherball.js:58': {coverage: 'complete', needed_case: '', differential: ['retaliation-weather-ball-rain-mirror-coat']},
  'test/sim/moves/weatherball.js:66': {coverage: 'complete', needed_case: '', differential: ['retaliation-weather-ball-clear-mirror-coat']},
  'test/sim/moves/weatherball.js:74': {coverage: 'complete', needed_case: '', differential: ['retaliation-weather-ball-clear-counter']},
}));

function disposition(source, fullName, body, generations, selectedGenerations) {
  const key = `${source.file}:${source.line}`;
  if (DIRECT.has(key)) return {...DIRECT.get(key)};
  if (/gameType\s*:\s*['"](?:doubles|triples|freeforall|multi)['"]/i.test(body)) {
    return {
      applicability: 'format_unreachable_gen3ou_singles', coverage: 'not_applicable', needed_case: '',
      evidence: 'The upstream test explicitly constructs a multi-active-slot game type.',
    };
  }
  if (selectedGenerations.length && !selectedGenerations.includes(3)) {
    return {
      applicability: 'different_generation_not_direct_evidence', coverage: 'not_direct',
      needed_case: `adjudicate-${source.entity}-${source.line}`,
      evidence: `The battle body selects generation(s) ${selectedGenerations.join(', ')}, not Gen 3; generation words in the title are not execution evidence.`,
    };
  }
  // A later-generation token in the body is not, by itself, evidence that the
  // assertion is unreachable in Gen 3. Upstream tests commonly use modern
  // species, moves, or abilities as convenient scaffolding for an older
  // semantic assertion (for example, Protean in the Intimidate/Substitute
  // regression). Only make the terminal unreachable claim when the test name
  // identifies the later mechanic. Body-only matches remain visible source-
  // adjudication debt.
  const post = POST_GEN3.filter(([, pattern]) => pattern.test(fullName)).map(([name]) => name);
  if (post.length) {
    return {
      applicability: 'mechanic_unreachable_gen3', coverage: 'not_applicable', needed_case: '',
      evidence: `Scenario depends on post-Gen-3 mechanic(s): ${post.join(', ')}.`,
    };
  }
  if (generations.includes(3)) {
    return {
      applicability: 'g3_explicit', coverage: 'unmapped', needed_case: `port-${source.entity}-${source.line}`,
      evidence: 'The test body or enclosing test name explicitly selects Generation 3.',
    };
  }
  if (generations.length) {
    return {
      applicability: 'different_generation_not_direct_evidence', coverage: 'not_direct',
      needed_case: `adjudicate-${source.entity}-${source.line}`,
      evidence: `The test selects generation(s) ${generations.join(', ')}, not Gen 3; compare pinned Gen 3 source before porting.`,
    };
  }
  return {
    applicability: 'candidate_requires_gen3_source_adjudication', coverage: 'not_direct',
    needed_case: `adjudicate-${source.entity}-${source.line}`,
    evidence: 'The entity is in the frozen Gen 3 OU inventory, but this upstream test runs Showdown\'s default generation.',
  };
}

function extractTests(ts, filePath, relative, kind, entity, descriptor) {
  const text = fs.readFileSync(filePath, 'utf8');
  const sourceFile = ts.createSourceFile(filePath, text, ts.ScriptTarget.Latest, true, ts.ScriptKind.JS);
  const records = [];
  function visit(node, describeStack) {
    let nextStack = describeStack;
    if (ts.isCallExpression(node) && /^describe(?:\.|$)/.test(callName(ts, node))) {
      nextStack = [...describeStack, literalName(ts, node)];
    }
    if (ts.isCallExpression(node) && /^(?:it|test)(?:\.|$)/.test(callName(ts, node))) {
      const testName = literalName(ts, node);
      const body = node.arguments[1] ? node.arguments[1].getText(sourceFile) : '';
      const line = sourceFile.getLineAndCharacterOfPosition(node.getStart(sourceFile)).line + 1;
      const fullName = [...describeStack, testName].join(' > ');
      const generations = declaredGenerations(`${fullName}\n${body}`);
      const selectedGenerations = [...body.matchAll(/common\.gen\((\d+)\)/g)].map(match => Number(match[1]));
      const source = {file: relative, line, entity};
      const decision = disposition(source, fullName, body, generations, selectedGenerations);
      const tags = semanticTags(`${fullName}\n${body}`, descriptor);
      const direct = DIRECT.get(`${relative}:${line}`);
      records.push({
        oracle_revision: REVISION,
        source_file: relative,
        source_line: line,
        describe_path: describeStack,
        test_name: testName,
        full_name: fullName,
        descriptor_kind: kind,
        descriptor_id: entity,
        declared_generations: generations,
        selected_generations: selectedGenerations,
        applicability: decision.applicability || 'g3_explicit',
        applicability_evidence: decision.evidence || 'The test explicitly constructs common.gen(3).',
        mechanics: tags,
        semantic_boundaries: boundaries(tags),
        native_unit_tests: direct?.unit || (decision.coverage === 'not_applicable' ? [] : (descriptor.focused_tests || [])),
        differential_cases: direct?.differential || (decision.coverage === 'not_applicable' ? [] : (descriptor.differential_cases || [])),
        invariant_ids: [],
        randomized_scenario_ids: [],
        coverage: decision.coverage,
        coverage_evidence_scope: decision.coverage === 'not_applicable' ? 'none' :
          (direct?.differential || direct?.unit) ? 'assertion_specific' :
          (descriptor.focused_tests?.length || descriptor.differential_cases?.length ? 'entity_level_candidates_only' : 'none'),
        needed_case: decision.needed_case,
        note: decision.note || '',
        showdown_semantic_sources: (descriptor.showdown_sources || []).map(entry => `${entry.path}#${entry.symbol}`),
      });
      return;
    }
    ts.forEachChild(node, child => visit(child, nextStack));
  }
  visit(sourceFile, []);
  return records;
}

function tsvCell(value) {
  const text = Array.isArray(value) ? value.join('|') : String(value ?? '');
  return text.replace(/[\t\r\n]+/g, ' ');
}

function main() {
  const showdown = arg('--showdown');
  const descriptorMapPath = arg('--descriptor-map');
  const output = arg('--output');
  const revision = require('child_process').execFileSync('git', ['rev-parse', 'HEAD'], {cwd: showdown, encoding: 'utf8'}).trim();
  if (revision !== REVISION) fail(`oracle revision ${revision}, expected ${REVISION}`);
  const ts = require(path.join(showdown, 'node_modules/typescript'));
  const map = JSON.parse(fs.readFileSync(descriptorMapPath, 'utf8'));
  if (map.oracle_revision !== REVISION) fail('descriptor map and oracle revisions differ');

  const corpus = [];
  const records = [];
  for (const [kind, directory] of KINDS) {
    const inventory = map.inventories.find(entry => entry.kind === kind);
    if (!inventory) fail(`descriptor inventory missing ${kind}`);
    for (const descriptor of inventory.entries) {
      const relative = `test/sim/${directory}/${descriptor.id}.js`;
      const filePath = path.join(showdown, relative);
      if (!fs.existsSync(filePath)) continue;
      const tests = extractTests(ts, filePath, relative, kind, descriptor.id, descriptor);
      corpus.push({kind, id: descriptor.id, source_file: relative, test_count: tests.length});
      records.push(...tests);
    }
  }
  records.sort((a, b) => a.source_file.localeCompare(b.source_file) || a.source_line - b.source_line);
  if (!records.length) fail('empty inherited test corpus');
  const keys = new Set();
  for (const record of records) {
    const key = `${record.source_file}:${record.source_line}`;
    if (keys.has(key)) fail(`duplicate ${key}`);
    keys.add(key);
    for (const required of ['applicability', 'applicability_evidence', 'coverage']) {
      if (!record[required]) fail(`${key} lacks ${required}`);
    }
    if (!record.mechanics.length || !record.semantic_boundaries.length) fail(`${key} lacks semantic mapping`);
    if (!record.needed_case && !['complete', 'not_applicable'].includes(record.coverage)) {
      fail(`${key} needs a case or terminal coverage disposition`);
    }
  }
  fs.mkdirSync(output, {recursive: true});
  fs.writeFileSync(path.join(output, 'inherited-corpus.json'), `${JSON.stringify({oracle_revision: REVISION, corpus}, null, 2)}\n`);
  fs.writeFileSync(path.join(output, 'gen3ou-inherited-test-map.json'), `${JSON.stringify({
    schema: 'pokemon-gen3ou-upstream-test-map-v1', oracle_revision: REVISION,
    scope: 'One record for every upstream test in move, ability, or item files whose entity is present in the frozen Gen 3 OU descriptor inventory.',
    records,
  }, null, 2)}\n`);
  const columns = ['oracle_revision', 'source_file', 'source_line', 'full_name', 'descriptor_kind', 'descriptor_id',
    'declared_generations', 'selected_generations', 'applicability', 'applicability_evidence', 'mechanics', 'semantic_boundaries',
    'native_unit_tests', 'differential_cases', 'invariant_ids', 'randomized_scenario_ids', 'coverage',
    'coverage_evidence_scope', 'needed_case', 'note', 'showdown_semantic_sources'];
  const rows = [columns.join('\t'), ...records.map(record => columns.map(column => tsvCell(record[column])).join('\t'))];
  fs.writeFileSync(path.join(output, 'gen3ou-inherited-test-map.tsv'), `${rows.join('\n')}\n`);
  const counts = records.reduce((result, record) => {
    result[record.applicability] = (result[record.applicability] || 0) + 1;
    return result;
  }, {});
  process.stdout.write(`${records.length} tests in ${corpus.length} files\n${JSON.stringify(counts, null, 2)}\n`);
}

main();
