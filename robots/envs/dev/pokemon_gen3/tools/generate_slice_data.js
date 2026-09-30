#!/usr/bin/env node
'use strict';

/* Showdown is a build-time source only; generated C has no Node dependency. */
const childProcess = require('child_process');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const EXPECTED_REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const EXPECTED_INVENTORY_DIGEST =
  '28d99d314cdeab1ed4b46daa2842636f15533ef2d8065a1c82b3157cf2915244';
const showdownDir = process.argv[2];
const output = process.argv[3];
if (!showdownDir || !['header', 'source', 'id-map'].includes(output)) {
  throw new Error('usage: generate_slice_data.js POKEMON_SHOWDOWN_DIR header|source|id-map');
}
const revision = childProcess.execFileSync(
  'git', ['-C', showdownDir, 'rev-parse', 'HEAD'], {encoding: 'utf8'}
).trim();
if (revision !== EXPECTED_REVISION) {
  throw new Error(`expected Pokémon Showdown ${EXPECTED_REVISION}, got ${revision}`);
}
const {Dex} = require(path.resolve(showdownDir));
const dex = Dex.forGen(3);
const inventoryPath = path.resolve(__dirname, '../verify/inventory/gen3ou-inventory.json');
const inventoryBytes = fs.readFileSync(inventoryPath);
const inventoryDigest = crypto.createHash('sha256').update(inventoryBytes).digest('hex');
if (inventoryDigest !== EXPECTED_INVENTORY_DIGEST) {
  throw new Error(`expected frozen inventory ${EXPECTED_INVENTORY_DIGEST}, got ${inventoryDigest}`);
}
const inventory = JSON.parse(inventoryBytes);
const eventVocabulary = JSON.parse(fs.readFileSync(path.resolve(
  __dirname, '../verify/inventory/event-vocabulary.json')));
if (eventVocabulary.schema !== 'pokemon-gen3ou-event-vocabulary-v2' ||
    eventVocabulary.oracle_revision !== EXPECTED_REVISION ||
    eventVocabulary.unique_events !== 71 || eventVocabulary.hook_derived_events !== 70 ||
    eventVocabulary.frozen_hook_records !== 514 ||
    eventVocabulary.events.length !== 71) {
  throw new Error('frozen event vocabulary changed');
}
const eventID = new Map(eventVocabulary.events.map((event, index) =>
  [event.event, index + 1]));
/* Literal-false CriticalHit was always an explicit interpreter boundary at
 * ID 72; its newly audited vocabulary row is appended without renumbering
 * the original 69 hook-derived IDs or runtime ChangeBoost ID 70. */
eventID.set('CriticalHit', 72);
if (eventID.get('Damage') !== 12 || eventID.get('ModifyAtk') !== 28 ||
    eventID.get('ModifySpA') !== 36 ||
    eventID.get('TryBoost') !== 57 || eventID.get('TryHit') !== 60 ||
    eventID.get('ChangeBoost') !== 70) throw new Error('event ID ordering changed');
if (inventory.schema !== 'pokemon-gen3ou-authoritative-inventory-v2' ||
    inventory.oracle?.revision !== EXPECTED_REVISION) {
  throw new Error('frozen inventory schema or oracle revision changed');
}
const thawTargetMoves = inventory.moves
  .map(entry => dex.moves.get(entry.id))
  .filter(move => move.thawsTarget)
  .map(move => move.id);
if (thawTargetMoves.length !== 0) {
  throw new Error(`Gen 3 unexpectedly reaches thawsTarget: ${thawTargetMoves.join(',')}`);
}
const inventoryKinds = [
  ['species', 369], ['moves', 354], ['abilities', 70], ['items', 104],
];
for (const [kind, count] of inventoryKinds) {
  const values = inventory[kind];
  if (!Array.isArray(values) || values.length !== count ||
      inventory.counts?.[kind] !== count) {
    throw new Error(`frozen ${kind} count changed`);
  }
  for (let i = 0; i < values.length; i++) {
    const value = values[i];
    if (!value || typeof value.id !== 'string' || typeof value.name !== 'string' ||
        (i !== 0 && values[i - 1].id.localeCompare(value.id) >= 0)) {
      throw new Error(`invalid or unsorted frozen ${kind} entry at ${i}`);
    }
  }
}
const conditionKinds = [
  ['statuses', 6, 'STATUS', 'POKEMON_CONDITION_DOMAIN_STATUS'],
  ['volatiles', 62, 'VOLATILE', 'POKEMON_CONDITION_DOMAIN_VOLATILE'],
  ['side_conditions', 5, 'SIDE', 'POKEMON_CONDITION_DOMAIN_SIDE'],
  ['weather', 4, 'WEATHER', 'POKEMON_CONDITION_DOMAIN_WEATHER'],
  ['pseudo_weather', 2, 'PSEUDO_WEATHER', 'POKEMON_CONDITION_DOMAIN_PSEUDO_WEATHER'],
  ['slot_conditions', 3, 'SLOT', 'POKEMON_CONDITION_DOMAIN_SLOT'],
];
const conditions = [];
const conditionIDs = new Set();
for (const [kind, count, token, ownerKind] of conditionKinds) {
  const values = inventory[kind];
  if (!Array.isArray(values) || values.length !== count ||
      inventory.counts?.[kind] !== count) {
    throw new Error(`frozen ${kind} count changed`);
  }
  for (let i = 0; i < values.length; i++) {
    const value = values[i];
    if (!value || typeof value.id !== 'string' || typeof value.name !== 'string' ||
        (i !== 0 && values[i - 1].id.localeCompare(value.id) >= 0) ||
        conditionIDs.has(value.id)) {
      throw new Error(`invalid, duplicate, or unsorted frozen ${kind} entry at ${i}`);
    }
    conditionIDs.add(value.id);
    conditions.push({...value, token, domain: ownerKind});
  }
}
if (conditions.length !== 82) throw new Error('frozen condition count changed');
const TYPES = [
  'Normal', 'Ghost', 'Psychic', 'Fighting', 'Dark',
  'Grass', 'Poison', 'Fire', 'Flying',
  'Ground', 'Water',
  'Rock', 'Steel',
  'Bug',
  'Ice', 'Electric', 'Dragon', '???',
];
const TYPE_RESPONSE_ORDER = [
  'Electric', 'Ghost', 'Grass', 'Steel', 'Dark', 'Bug', 'Dragon',
  'Fighting', 'Fire', 'Flying', 'Ground', 'Ice', 'Normal', 'Poison',
  'Psychic', 'Rock', 'Water',
];
const SPECIES = [
  'persian', 'alakazam', 'banette', 'machop',
  'bulbasaur', 'ivysaur', 'venusaur',
  'charmander', 'charmeleon', 'charizard',
  'gengar', 'vaporeon', 'starmie',
  'marowak',
  'tyrogue', 'hitmonchan',
  'skarmory',
  'blissey',
  'magikarp', 'snorlax', 'heracross',
  'metagross', 'torkoal', 'kingler',
  'dusclops',
  /* Legal holders for the ordinary constant-power move rotation. Their
   * selected abilities already belong to the executable capability surface. */
  'spearow', 'golem', 'poliwrath',
  'golduck',
  'tyranitar',
  /* Legal holders covering the callback-free damaging-secondary rotation. */
  'aggron', 'tentacool', 'corsola', 'raikou', 'cyndaquil', 'horsea',
  'koffing', 'articuno', 'gastly', 'kabuto', 'mawile', 'regice',
  /* Legal universal-move holder and Own Tempo witness for confusion. */
  'smeargle',
  'dustox',
  /* Thick Club's resolved predicate names both legal species. */
  'cubone',
  /* Species-guard witnesses for generation-flattened critical items. */
  'chansey', 'farfetchd',
  'squirtle',
  'magcargo',
  'electrike', 'roselia',
  'diglett', 'magneton',
  'breloom',
  'sharpedo',
  'seviper',
  'lanturn',
  'milotic',
  /* Legal grouped-secondary + Serene Grace witness. */
  'jirachi',
  /* Legal Early Bird witness for generated sleep lifecycle programs. */
  'xatu',
  /* Speed Boost lifecycle witnesses. */
  'ninjask',
  /* Intimidate lifecycle and tied entry-order witnesses. */
  'salamence', 'gyarados',
  /* Dynamic ability replacement witness. */
  'porygon2',
  /* Mutable effective-type witness. Appended to preserve native IDs. */
  'kecleon',
  /* Source-bound attraction witness. Appended to preserve native IDs. */
  'delcatty',
  /* Legal Hydro Cannon producer. Appended to preserve native IDs. */
  'blastoise',
  /* Legal holders for resolved callback-free ability identities. */
  'zigzagoon', 'ponyta', 'muk',
  /* Legal holders for species-conditioned stat-item handlers. */
  'clamperl', 'pikachu',
  /* Legal Gen 3 Oblivious witness. */
  'slowpoke',
  /* Metal Powder's generation-owned species predicate. */
  'ditto',
	/* Wonder Guard's legal Gen 3 owner; appended to preserve native IDs. */
	'shedinja',
	/* Suction Cups' legal Gen 3 owner. Appended to preserve native IDs. */
	'cradily',
	/* Legal owners for relational Plus/Minus ability handlers. */
	'plusle', 'minun',
	/* Legal Perish Song fixture holders. */
	'jynx', 'lapras', 'misdreavus',
	/* Legal Vital Spirit origin for Trace-to-Update differential evidence. */
	'vigoroth',
	/* Legal bulky witnesses for the locked-ramp descriptor rotation. */
	'steelix', 'cloyster',
	/* Legal Truant owner; appended to preserve all established native IDs. */
	'slaking',
	/* Forecast form family; appended to preserve all established native IDs. */
	'castform', 'castformsunny', 'castformrainy', 'castformsnowy',
];
/* Existing executable IDs are a replay-file ABI. Extend the table from the
 * frozen Gen 3 OU inventory without renumbering that established prefix. */
const executableSpeciesIDs = new Set(SPECIES);
for (const entry of inventory.species) {
  if (!executableSpeciesIDs.has(entry.id)) {
    SPECIES.push(entry.id);
    executableSpeciesIDs.add(entry.id);
  }
}
if (SPECIES.length !== inventory.species.length) {
  throw new Error(`executable species closure changed: ${SPECIES.length}`);
}
const MOVES = [
  'quickattack', 'thief', 'tackle', 'scratch', 'strength', 'megapunch',
  'earthquake', 'surf',
  'bonerush', 'machpunch',
  'toxic', 'sandstorm', 'protect', 'reflect',
  'bulkup', 'growl', 'splash', 'ember', 'steelwing', 'bodyslam',
  'doubleedge', 'gigadrain',
  'seismictoss', 'nightshade', 'reversal',
  'helpinghand', 'wingattack', 'substitute', 'tickle', 'magiccoat',
  'mirrormove',
  'snatch', 'howl', 'calmmind',
  'acidarmor', 'agility', 'amnesia', 'barrier',
  'charm', 'cosmicpower', 'cottonspore', 'dragondance',
  'faketears', 'featherdance', 'flash', 'growth',
  'harden', 'irondefense', 'kinesis', 'leer',
  'meditate', 'metalsound', 'sandattack', 'scaryface',
  'screech', 'sharpen', 'smokescreen', 'stringshot',
  'sweetscent', 'swordsdance', 'tailglow', 'tailwhip',
  'withdraw',
  /* Callback-free Gen 3 attacks. Hyper Voice is deliberately absent: every
   * legal Gen 3 learner would require admitting an unsupported ability. */
  'cut', 'dragonclaw', 'drillpeck', 'eggbomb', 'hornattack', 'hydropump',
  'megahorn', 'megakick', 'peck', 'pound', 'rockthrow', 'slam', 'vinewhip',
  'visegrip', 'waterfall', 'watergun',
  /* Ordinary primary major-status moves. Status semantics belong to the
   * generic transaction; these descriptors contribute only data. Appending
   * preserves the established executable IDs used by regression artifacts. */
  'glare', 'grasswhistle', 'hypnosis', 'lovelykiss', 'poisongas',
  'poisonpowder', 'sing', 'sleeppowder', 'spore', 'stunspore',
  'thunderwave', 'willowisp',
  'hail', 'raindance', 'sunnyday',
  /* Callback-free damaging moves whose only effect is one status or one-stat
   * secondary.  Their semantics are generated into the ordinary after-hit
   * effect program; generic control flow never branches on these IDs. */
  'blizzard', 'dragonbreath', 'fireblast', 'firepunch', 'flamethrower',
  'flamewheel', 'heatwave', 'icebeam', 'icepunch', 'lick', 'poisonfang',
  'poisonsting', 'powdersnow', 'sacredfire', 'sludge', 'sludgebomb', 'smog',
  'spark', 'thunderbolt', 'thunderpunch', 'thundershock', 'zapcannon',
  'acid', 'aurorabeam', 'bubble', 'bubblebeam', 'constrict', 'crunch',
  'crushclaw', 'icywind', 'irontail', 'lusterpurge', 'metalclaw',
  'meteormash', 'mistball', 'muddywater', 'mudshot', 'mudslap', 'octazooka',
  'psychic', 'rocksmash', 'rocktomb', 'shadowball',
  /* Callback-free declarative self recovery. */
  'recover', 'milkdrink', 'slackoff', 'softboiled',
  /* Plain primary confusion producers. */
  'confuseray', 'supersonic', 'sweetkiss', 'flatter',
  /* Damaging moves whose sole secondary is confusion. */
  'confusion', 'psybeam', 'signalbeam', 'dizzypunch', 'waterpulse',
  'dynamicpunch',
  /* Multi-target primary effects use the generic target iterator.  The
   * current Ocean format admits one active per side, so allAdjacent
   * degenerates to the opposing active without changing the descriptor. */
  'teeterdance',
  /* Fatigue moves share the generated lockedmove condition policy. */
  'outrage', 'petaldance', 'thrash',
  'moonlight', 'morningsun', 'synthesis',
  'weatherball',
  'thunder',
  'solarbeam',
  'recycle', 'knockoff', 'covet', 'trick',
  /* Callback-free fixed and ranged multi-hit moves.  Numeric counts are
   * preserved as [n,n]; Gen 3's ranged probability law belongs to its rules. */
  'armthrust', 'barrage', 'bonemerang', 'bulletseed', 'cometpunch',
  'doublekick', 'doubleslap', 'furyattack', 'furyswipes', 'iciclespear',
  'pinmissile', 'rockblast', 'spikecannon',
  /* High-critical attacks use only their generated base critical stage; the
   * generic kernel owns event staging and the generation owns probabilities. */
  'leafblade', 'crabhammer', 'aircutter', 'karatechop', 'aeroblast',
  'blazekick', 'crosschop', 'poisontail', 'razorleaf', 'slash',
  /* Ordinary damaging moves whose sole secondary is flinch.  Fake Out,
   * Snore, and Sky Attack retain independent move callbacks and are not part
   * of this declarative family. */
  'astonish', 'extrasensory', 'needlearm', 'boneclub', 'hyperfang',
  'rollingkick', 'bite', 'headbutt', 'rockslide', 'stomp', 'twister',
  /* Self volatile whose handlers compose with the generic critical event. */
  'focusenergy',
  /* Side-owned screen using the same lifecycle as Reflect. */
  'lightscreen',
  /* Showdown's boolean accuracy is semantically distinct from numeric 100. */
  'aerialace', 'feintattack', 'magicalleaf', 'shadowpunch', 'shockwave', 'swift',
  /* One generated volatile product; trapping behavior belongs to its
   * condition handlers rather than to any move identity. */
  'bind', 'clamp', 'firespin', 'whirlpool', 'wrap',
  /* Descriptor-selected pre-hit self-faint with a generation-owned defense
   * policy. The kernel does not branch on either move identity. */
  'explosion', 'selfdestruct',
  /* Generation-selected fallback move used only when choice reduction leaves
   * no ordinary move. */
  'struggle',
  /* First descriptor in the generic choice-control condition family. */
  'taunt', 'torment', 'disable', 'encore',
  /* Side-owned stat-drop filter; behavior belongs to its TryBoost handler. */
  'mist', 'safeguard',
  /* Generic delayed volatile: expiry owns its status effect program. */
  'yawn',
  /* Durationless layered side condition; switch entry owns its damage. */
  'spikes',
  /* Callback-free half-drain moves share one generated after-damage effect. */
  'absorb', 'megadrain', 'leechlife',
  /* Literal fixed damage is descriptor data, not base power. */
  'sonicboom', 'dragonrage',
  /* Target-relative fixed damage shares the formula interpreter; Endeavor's
   * earlier failure predicate is a generated TryMove program. */
  'superfang', 'endeavor',
  /* Generation-owned random-level-percent damage formula. */
  'psywave',
  /* Recharge is a synthetic request action named by the condition policy. */
  'hyperbeam', 'recharge',
  /* Appended to preserve all frozen native IDs while completing the existing
   * generated partial-trapping product. */
  'sandtomb',
  /* Move-owned TryHit program removes generation-selected side conditions. */
  'brickbreak',
  /* Generic two-turn marker plus generated Invulnerability callback. */
  'fly',
  /* Move-owned BasePower handler over a generated holder-status mask. */
  'facade',
  /* Move-owned boolean Hit callback over the shared status transaction. */
  'refresh',
  /* Atomic seven-stage product copy through the same typed Hit callback. */
  'psychup',
  /* Move-owned post-hit self drops are one atomic sparse boost product. */
  'overheat', 'psychoboost', 'superpower',
  /* Callback-free recoil moves share the generic damage-relative effect. */
  'submission', 'takedown', 'volttackle',
  /* Move-owned field Hit callback clears all living active boost products. */
  'haze',
  /* Direct status replacement plus healing is expressed by generated
   * admission and Hit programs over generic status operations. */
  'rest',
  /* One probabilistic self-boost product, not five independent effects. */
  'ancientpower', 'silverwind',
  /* Sleep-usable ordinary damage plus one generated admission predicate and
   * the shared flinch secondary product. */
  'snore',
  /* Shared live-source-HP base-power descriptor family. */
  'eruption', 'waterspout',
  /* Status-linked persistent volatile with generated lifecycle handlers. */
  'nightmare',
  /* Source-bound volatile shared by the move and Cute Charm. */
  'attract',
  /* Damaging self cleanup through the generic remove-volatile effect. */
  'rapidspin',
  /* Additional producers of the shared recharge condition. */
  'blastburn', 'frenzyplant', 'hydrocannon',
  /* Callback-free priority attack; priority remains descriptor data. */
  'extremespeed',
  /* Appended admission-only rows; preserve established executable IDs. */
  'flail', 'hypervoice', 'vitalthrow',
  /* First generated witness for the generic real-HP Damage relay. */
  'falseswipe',
  /* Move-owned team products over the generic major-status transaction. */
  'aromatherapy', 'healbell',
  /* Generic ability-transfer admission and mutation. */
  'roleplay',
	/* Source-owned indefinite trapping through one generated Hit program. */
	'block', 'meanlook', 'spiderweb',
	/* Remaining Gen 3 two-turn family; append to preserve established IDs. */
	'bounce', 'dig', 'dive', 'razorwind', 'skullbash', 'skyattack',
	/* Reachable airborne bypass moves used by the marker policy. */
	'gust', 'skyuppercut',
	/* Weighted base-power selection is a generated ModifyMove program. */
	'magnitude',
	/* Persistent holder conditions with ambient BasePower handlers. */
	'mudsport', 'watersport',
	/* Shared stalling-move interpreter operation. */
	'detect', 'endure',
	/* Shared source-bound targeting condition. */
	'lockon', 'mindreader',
	/* First selected-action gate; behavior is a generated move-owned Try. */
	'fakeout',
	/* Happiness-backed power formulas over immutable normalized set data. */
	'return', 'frustration',
	/* Ordinary damage; its inherited callback is protocol text only. */
	'payday',
	/* Singles rejection through a generated move-owned Try program. */
	'followme',
	/* Turn-local damage provenance plus state-derived fixed retaliation. */
	'counter', 'mirrorcoat',
	/* Per-Pokemon move construction from generation-owned normalized set data. */
	'hiddenpower',
	/* Battlefield-position-owned delayed work. Appended to preserve IDs. */
	'futuresight', 'doomdesire', 'wish',
	/* Descriptor-only forced displacement; the generic kernel owns DragOut. */
	'roar', 'whirlwind',
	/* Persistent self condition; behavior is generated owner handlers. */
	'ingrain',
	/* Target-bound queued selected-action interception. */
	'pursuit',
	/* Persistent self condition consumed by the next non-Charge move. */
	'charge',
	/* Position-linked residual damage transfer. */
	'leechseed',
	/* Resolved Gen 3 constant rejection through a move-owned Try program. */
	'teleport',
	/* Runtime-reachable through legal move delegation; direct OU submission is
	 * still rejected by the format oracle. */
	'fissure', 'guillotine', 'horndrill', 'sheercold',
	/* Legal parent for the generated called-move capability. */
	'metronome',
	/* Transactional two-holder ability exchange. Append-only: native move IDs
	 * are part of the stable fixture/ABI contract. */
	'skillswap',
	/* Field-wide per-target admission plus descriptor-owned countdown expiry. */
	'perishsong',
	/* Direct submission is OU-banned, but legal Metronome delegation reaches
	 * the ordinary ordered boost-plus-confusion product. */
	'swagger',
	/* Shared target volatile: raw immunity and evasion are handler semantics. */
	'foresight', 'odorsleuth',
	/* Deterministic fixed delegation through the generic called-move path. */
	'naturepower',
	/* Current-slot selection through the same called-move path. */
	'sleeptalk',
	/* Mutable move-slot replacement through one generated copy policy. */
	'mimic', 'sketch',
	/* Stored-damage lifecycle with a generated non-selectable release hit. */
	'bide',
	/* Success-only bounded power ramp through generic condition state. */
	'furycutter',
	/* Shared five-step locked ramp plus its independent power marker. */
	'rollout', 'iceball', 'defensecurl',
	/* Counter-backed persistent state consumed by generic power/heal paths. */
	'stockpile', 'spitup', 'swallow',
	/* Move-driven switch continuation with descriptor-owned transfer policy. */
	'batonpass',
	/* Reactive type selection from canonical resolved last-used-move state. */
	'conversion2',
	/* Reactive holder condition: ordinary per-hit response plus pre-action teardown. */
	'rage',
	/* Persistent evasion marker: ordinary boost plus flagged incoming damage modifier. */
	'minimize',
	/* Targeted mutation of the canonical last selected move's current PP. */
	'spite',
	/* Mutable type overlays from a literal or the holder's current move slots. */
	'camouflage', 'conversion',
	/* Order-5 preparation plus condition-owned action invalidation. */
	'focuspunch',
	/* Source-sensitive Faint responses over the generic volatile lifecycle. */
	'destinybond', 'grudge',
	/* Global sleep wake/prevention plus a generated random-duration move lock. */
	'uproar',
	/* Foe-scoped shared-move restriction through ordinary request/action events. */
	'imprison',
	/* Fixed-count per-hit accuracy/power and per-hit secondary composition. */
	'triplekick', 'twineedle',
	/* Gen 3's resolved terrain-free form is an ordinary paralysis secondary. */
	'secretpower',
	/* Generated weighted damage-or-heal active-move outcome. */
	'present',
	/* Invocation-local target/effect profiles selected from effective typing. */
	'curse',
	/* Atomic bilateral direct-HP assignment; appended to preserve native IDs. */
	'painsplit',
	/* Banned from submitted sets but runtime-reachable through Metronome. */
	'doubleteam',
	/* Successful target hit queues the user faint before Update/faint drain. */
	'memento',
	/* Shared MoveFail callback: hypothetical connected damage becomes bounded
	 * ordinary self-damage through generated failure policy. */
	'jumpkick', 'highjumpkick',
	/* Current-turn damage provenance drives a generic conditional multiplier. */
	'revenge',
	/* Move-owned TryImmunity composes sleep and Substitute predicates with the
	 * ordinary damage-relative drain effect. */
	'dreameater',
	/* Generated sampled-status secondary distribution. */
	'triattack',
	/* Target-current-species weight selects generated base-power brackets. */
	'lowkick',
	/* Mutable battle-profile replacement through a generated policy. */
	'transform',
	/* Status-conditioned power/cure and thresholded self-cost/max-stage
	 * transactions. Appended to preserve frozen executable move IDs. */
	'smellingsalts', 'bellydrum',
	/* Direct submission is banned, but Metronome can legally delegate to it. */
	'assist',
	/* Dynamic party-hit plan over current mutable party order. */
	'beatup',
];
const MULTIHIT_MOVES = new Map([
  ['armthrust', [2, 5]], ['barrage', [2, 5]], ['bonemerang', [2, 2]],
  ['bulletseed', [2, 5]], ['cometpunch', [2, 5]], ['doublekick', [2, 2]],
  ['doubleslap', [2, 5]], ['furyattack', [2, 5]], ['furyswipes', [2, 5]],
  ['iciclespear', [2, 5]], ['pinmissile', [2, 5]], ['rockblast', [2, 5]],
  ['spikecannon', [2, 5]],
]);
const DIRECT_HEAL_MOVES = new Set([
  'recover', 'milkdrink', 'slackoff', 'softboiled',
]);
const WEATHER_HEAL_MOVES = new Set(['moonlight', 'morningsun', 'synthesis']);
const DRAIN_MOVES = new Set([
  'absorb', 'dreameater', 'megadrain', 'gigadrain', 'leechlife',
]);
const STATUS_SECONDARY_MOVES = new Set([
  'blizzard', 'dragonbreath', 'fireblast', 'firepunch', 'flamethrower',
  'flamewheel', 'heatwave', 'icebeam', 'icepunch', 'lick', 'poisonfang',
  'poisonsting', 'powdersnow', 'sacredfire', 'sludge', 'sludgebomb', 'smog',
  'spark', 'thunderbolt', 'thunderpunch', 'thundershock', 'zapcannon', 'thunder',
  'blazekick', 'poisontail', 'twineedle', 'secretpower',
]);
const BOOST_SECONDARY_MOVES = new Set([
  'acid', 'aurorabeam', 'bubble', 'bubblebeam', 'constrict', 'crunch',
  'crushclaw', 'icywind', 'irontail', 'lusterpurge', 'metalclaw',
  'meteormash', 'mistball', 'muddywater', 'mudshot', 'mudslap', 'octazooka',
  'psychic', 'rocksmash', 'rocktomb', 'shadowball',
]);
const CONFUSION_SECONDARY_MOVES = new Set([
  'confusion', 'psybeam', 'signalbeam', 'dizzypunch', 'waterpulse',
  'dynamicpunch',
]);
const FLINCH_SECONDARY_MOVES = new Set([
  'astonish', 'extrasensory', 'needlearm', 'boneclub', 'hyperfang',
  'rollingkick', 'bite', 'headbutt', 'rockslide', 'stomp', 'twister', 'snore',
]);
/* Gen 3 replaces the inherited BasePower hooks for these held items with
 * category-specific attack-stat hooks.  Keep this as one generated product:
 * item identity, event, guarded move type, and exact Q12 chain modifier. */
const TYPE_BOOST_ITEMS = [
  ['blackbelt', 'ModifyAtk', 'Fighting', 4505, '1.1'],
  ['hardstone', 'ModifyAtk', 'Rock', 4505, '1.1'],
  ['metalcoat', 'ModifyAtk', 'Steel', 4505, '1.1'],
  ['poisonbarb', 'ModifyAtk', 'Poison', 4505, '1.1'],
  ['sharpbeak', 'ModifyAtk', 'Flying', 4505, '1.1'],
  ['silkscarf', 'ModifyAtk', 'Normal', 4505, '1.1'],
  ['silverpowder', 'ModifyAtk', 'Bug', 4505, '1.1'],
  ['softsand', 'ModifyAtk', 'Ground', 4505, '1.1'],
  ['spelltag', 'ModifyAtk', 'Ghost', 4505, '1.1'],
  ['blackglasses', 'ModifySpA', 'Dark', 4505, '1.1'],
  ['charcoal', 'ModifySpA', 'Fire', 4505, '1.1'],
  ['dragonfang', 'ModifySpA', 'Dragon', 4505, '1.1'],
  ['magnet', 'ModifySpA', 'Electric', 4505, '1.1'],
  ['miracleseed', 'ModifySpA', 'Grass', 4505, '1.1'],
  ['mysticwater', 'ModifySpA', 'Water', 4505, '1.1'],
  ['nevermeltice', 'ModifySpA', 'Ice', 4505, '1.1'],
  ['seaincense', 'ModifySpA', 'Water', 4300, '1.05'],
  ['twistedspoon', 'ModifySpA', 'Psychic', 4505, '1.1'],
];
const FIXED_HEAL_BERRIES = [['oranberry', 10], ['sitrusberry', 30]];
const FLAVOR_BERRIES = [
  ['aguavberry', 'BITTER'], ['figyberry', 'SPICY'],
  ['iapapaberry', 'SOUR'], ['magoberry', 'SWEET'],
  ['wikiberry', 'DRY'],
];
const PINCH_BOOST_BERRIES = [
  ['liechiberry', 'ATK'], ['ganlonberry', 'DEF'], ['salacberry', 'SPE'],
  ['petayaberry', 'SPA'], ['apicotberry', 'SPD'],
];
const VOLATILE_PINCH_BERRIES = [['lansatberry', 'FOCUS_ENERGY']];
const RANDOM_PINCH_BERRIES = [
  ['starfberry', ['ATK', 'DEF', 'SPA', 'SPD', 'SPE'], 2],
];
const UPDATE_CURE_ITEMS = [['mentalherb', 'ATTRACT']];
const STATUS_CURE_BERRIES = [
  ['cheriberry', ['PARALYSIS']], ['chestoberry', ['SLEEP']],
  ['pechaberry', ['POISON', 'TOXIC']], ['rawstberry', ['BURN']],
  ['aspearberry', ['FREEZE']],
];
const VOLATILE_CURE_BERRIES = [['persimberry', 'CONFUSION']];
const COMBINED_CURE_BERRIES = [['lumberry', 'CONFUSION']];
const kingsRockSource = String(dex.items.get('kingsrock').onModifyMove);
const kingsRockArraySource = kingsRockSource.slice(
  kingsRockSource.indexOf('[') + 1, kingsRockSource.indexOf('];'));
const KINGS_ROCK_MOVES = new Set(
  [...kingsRockArraySource.matchAll(/["']([a-z0-9]+)["']/g)].map(match => match[1]));
if (KINGS_ROCK_MOVES.size !== 130 || !KINGS_ROCK_MOVES.has('tackle') ||
    !KINGS_ROCK_MOVES.has('armthrust') || KINGS_ROCK_MOVES.has('bite') ||
    KINGS_ROCK_MOVES.has('tickle')) {
  throw new Error('resolved Gen 3 King\'s Rock move eligibility changed');
}
const lightningRod = dex.abilities.get('lightningrod');
const lightningRodRedirect = String(lightningRod.onFoeRedirectTarget);
if (lightningRod.onTryHit !== undefined ||
    lightningRod.onAnyRedirectTarget !== undefined ||
    typeof lightningRod.onFoeRedirectTarget !== 'function' ||
    !lightningRodRedirect.includes('this.dex.moves.get(move.id).type') ||
    !lightningRodRedirect.includes("!== 'Electric'") &&
      !lightningRodRedirect.includes('!== "Electric"') ||
    !lightningRodRedirect.includes('this.validTarget') ||
    !lightningRodRedirect.includes('return this.effectState.target')) {
  throw new Error('resolved Gen 3 Lightning Rod redirect shape changed');
}
/*
 * Legal Gen 3 OU held-item identities whose recursively resolved descriptors
 * have no effective callbacks. They still need executable identities because
 * generic item transactions (Trick, Thief, Knock Off, Recycle) observe and
 * move them. Keep this closure asserted below; callback-bearing items belong
 * in a semantic family, not this table.
 */
const PASSIVE_ITEMS = [
  'masterball', 'ultraball', 'greatball', 'pokeball', 'netball', 'diveball',
  'nestball', 'repeatball', 'timerball', 'luxuryball', 'premierball',
  'sunstone', 'moonstone', 'firestone', 'thunderstone', 'waterstone',
  'leafstone', 'rootfossil', 'clawfossil', 'helixfossil', 'domefossil',
  'oldamber', 'razzberry', 'blukberry', 'nanabberry', 'wepearberry',
  'pinapberry', 'pomegberry', 'kelpsyberry', 'qualotberry', 'hondewberry',
  'grepaberry', 'tamatoberry', 'cornnberry', 'magostberry', 'rabutaberry',
  'nomelberry', 'spelonberry', 'pamtreberry', 'watmelberry', 'durinberry',
  'belueberry', 'dragonscale', 'upgrade', 'friendball',
];
const STAT_ITEMS = [
  'deepseascale', 'deepseatooth', 'lightball', 'machobrace', 'souldew',
  'metalpowder',
];
const ITEMS = [...TYPE_BOOST_ITEMS.map(([id]) => id),
  ...FIXED_HEAL_BERRIES.map(([id]) => id), ...FLAVOR_BERRIES.map(([id]) => id),
  ...PINCH_BOOST_BERRIES.map(([id]) => id),
  ...VOLATILE_PINCH_BERRIES.map(([id]) => id),
  ...RANDOM_PINCH_BERRIES.map(([id]) => id),
  ...STATUS_CURE_BERRIES.map(([id]) => id), ...VOLATILE_CURE_BERRIES.map(([id]) => id),
  ...COMBINED_CURE_BERRIES.map(([id]) => id),
  ...UPDATE_CURE_ITEMS.map(([id]) => id), 'whiteherb', 'choiceband', 'mail', 'thickclub',
  'scopelens', 'luckypunch', 'stick', 'leftovers', 'quickclaw', 'focusband',
  'leppaberry', 'kingsrock', 'shellbell',
  ...PASSIVE_ITEMS, ...STAT_ITEMS];
const eventToken = event => event === 'ModifyAtk' ? 'MODIFY_ATK' : 'MODIFY_SPA';
const BASE_HANDLER_IDS = [
  'WATER_ABSORB', 'GUTS', 'BLACK_BELT', 'ROCK_HEAD', 'CLEAR_BODY',
  'HYPER_CUTTER', 'KEEN_EYE', 'WHITE_SMOKE', 'PROTECT', 'MAGIC_COAT',
  'SUBSTITUTE_TRY_PRIMARY_HIT', 'SNATCH', 'VOLT_ABSORB',
  'THICK_FAT', 'MARVEL_SCALE', 'FACADE_BASE_POWER', 'REFRESH_HIT',
  'PSYCH_UP_HIT',
];
const SCALAR_HANDLER_IDS = [
  'COMPOUND_EYES_ACCURACY', 'HUGE_POWER', 'HUSTLE_ATTACK',
  'HUSTLE_ACCURACY', 'PURE_POWER', 'THICK_CLUB',
];
const CONFUSION_HANDLER_IDS = [
  'CONFUSION_START', 'CONFUSION_BEFORE_MOVE', 'CONFUSION_END',
  'OWN_TEMPO_TRY_ADD_VOLATILE', 'OWN_TEMPO_HIT', 'OWN_TEMPO_UPDATE',
];
const CONFUSION_SECONDARY_HANDLER_IDS = ['SHIELD_DUST_MODIFY_SECONDARIES'];
const LOCKED_MOVE_HANDLER_IDS = [
  'LOCKED_MOVE_START', 'LOCKED_MOVE_RESTART', 'LOCKED_MOVE_RESIDUAL',
  'LOCKED_MOVE_END', 'LOCKED_MOVE_SELECTOR',
];
const WEATHER_BALL_HANDLER_IDS = [
  'WEATHER_BALL_MODIFY_TYPE', 'WEATHER_BALL_MODIFY_MOVE',
];
const TYPE_RESPONSE_HANDLER_IDS = ['CONVERSION_2_HIT'];
const RAGE_HANDLER_IDS = ['RAGE_START', 'RAGE_HIT', 'RAGE_BEFORE_MOVE'];
const MINIMIZE_HANDLER_IDS = ['MINIMIZE_RESTART', 'MINIMIZE_SOURCE_MODIFY_DAMAGE'];
const SPITE_HANDLER_IDS = ['SPITE_HIT'];
const TYPE_OVERLAY_HANDLER_IDS = ['CAMOUFLAGE_HIT', 'CONVERSION_HIT'];
const PREPARED_ACTION_HANDLER_IDS = [
	'FOCUS_PUNCH_START', 'FOCUS_PUNCH_HIT',
	'FOCUS_PUNCH_TRY_ADD_VOLATILE', 'FOCUS_PUNCH_TRY',
];
const FAINT_RESPONSE_HANDLER_IDS = [
	'DESTINY_BOND_PREPARE_HIT', 'DESTINY_BOND_START', 'DESTINY_BOND_BEFORE_MOVE',
	'DESTINY_BOND_MOVE_ABORTED', 'DESTINY_BOND_FAINT',
	'GRUDGE_START', 'GRUDGE_BEFORE_MOVE', 'GRUDGE_FAINT',
];
const UPROAR_HANDLER_IDS = [
	'UPROAR_TRY_HIT', 'UPROAR_START', 'UPROAR_RESIDUAL',
	'UPROAR_END', 'UPROAR_LOCK_MOVE', 'UPROAR_SET_STATUS',
];
const IMPRISON_HANDLER_IDS = [
	'IMPRISON_TRY_HIT', 'IMPRISON_DISABLE_MOVE',
	'IMPRISON_BEFORE_MOVE',
];
const SECRET_POWER_HANDLER_IDS = ['SECRET_POWER_MODIFY_MOVE'];
const PRESENT_HANDLER_IDS = ['PRESENT_MODIFY_MOVE'];
const FORMAT_STATUS_CLAUSE_HANDLER_IDS = [
	'SLEEP_CLAUSE_SET_STATUS', 'FREEZE_CLAUSE_SET_STATUS',
];
const THUNDER_HANDLER_IDS = ['THUNDER_MODIFY_MOVE'];
const MAGNITUDE_HANDLER_IDS = [
  'MAGNITUDE_MODIFY_MOVE', 'MAGNITUDE_USE_MOVE_MESSAGE',
];
const SPORT_HANDLER_IDS = [
  'MUD_SPORT_ANY_BASE_POWER', 'WATER_SPORT_ANY_BASE_POWER',
];
const PROTECTION_HANDLER_IDS = ['ENDURE_DAMAGE'];
const FOCUS_BAND_HANDLER_IDS = ['FOCUS_BAND_DAMAGE'];
const MAJOR_STATUS_LIFECYCLE_HANDLER_IDS = [
	'BURN_START', 'POISON_START', 'TOXIC_START', 'TOXIC_SWITCH_IN',
];
const LEPPA_BERRY_HANDLER_IDS = ['LEPPA_BERRY_UPDATE', 'LEPPA_BERRY_EAT'];
const KINGS_ROCK_HANDLER_IDS = ['KINGS_ROCK_MODIFY_MOVE'];
const SHELL_BELL_HANDLER_IDS = ['SHELL_BELL_AFTER_MOVE_SECONDARY_SELF'];
const FAKE_OUT_HANDLER_IDS = ['FAKE_OUT_TRY'];
const FOLLOW_ME_HANDLER_IDS = ['FOLLOW_ME_TRY'];
const RETALIATION_HANDLER_IDS = [
	'COUNTER_START', 'COUNTER_DAMAGE', 'COUNTER_TRY',
	'MIRROR_COAT_START', 'MIRROR_COAT_DAMAGE', 'MIRROR_COAT_TRY',
	'HIDDEN_POWER_MODIFY_MOVE',
];
const BIDE_HANDLER_IDS = [
	'BIDE_START', 'BIDE_DAMAGE', 'BIDE_BEFORE_MOVE',
	'BIDE_MOVE_ABORTED', 'BIDE_END', 'BIDE_RESIDUAL',
];
const RAMPING_POWER_HANDLER_IDS = [
	'FURY_CUTTER_BASE_POWER', 'FURY_CUTTER_START',
	'FURY_CUTTER_RESTART', 'FURY_CUTTER_HIT',
];
const LOCKED_RAMP_HANDLER_IDS = [
	'ROLLOUT_MODIFY_MOVE', 'ROLLOUT_BASE_POWER', 'ROLLOUT_START', 'ROLLOUT_LOCK_MOVE',
	'ROLLOUT_RESIDUAL', 'ICE_BALL_MODIFY_MOVE', 'ICE_BALL_BASE_POWER',
	'ICE_BALL_START', 'ICE_BALL_LOCK_MOVE', 'ICE_BALL_RESIDUAL',
];
const COUNTER_STACK_HANDLER_IDS = [
  'STOCKPILE_TRY', 'STOCKPILE_START', 'STOCKPILE_RESTART', 'STOCKPILE_END',
  'SPIT_UP_TRY', 'SPIT_UP_BASE_POWER', 'SPIT_UP_AFTER_MOVE',
  'SWALLOW_TRY', 'SWALLOW_HIT',
];
const DRAG_BLOCKER_HANDLER_IDS = [
	'SUCTION_CUPS_DRAG_OUT', 'INGRAIN_START', 'INGRAIN_RESIDUAL',
	'INGRAIN_TRAP_POKEMON', 'INGRAIN_DRAG_OUT',
];
const QUEUED_INTERCEPT_HANDLER_IDS = [
  'PURSUIT_MODIFY_MOVE', 'PURSUIT_BEFORE_SWITCH_OUT',
];
const CHARGE_HANDLER_IDS = [
  'CHARGE_START', 'CHARGE_RESTART', 'CHARGE_BASE_POWER',
  'CHARGE_MOVE_ABORTED', 'CHARGE_AFTER_MOVE', 'CHARGE_END',
];
const SOURCE_LINKED_RESIDUAL_HANDLER_IDS = [
  'LEECH_SEED_TRY_IMMUNITY', 'LEECH_SEED_START', 'LEECH_SEED_RESIDUAL',
  'LIQUID_OOZE_SOURCE_TRY_HEAL', 'RAPID_SPIN_AFTER_SUB_DAMAGE',
];
const FLASH_FIRE_HANDLER_IDS = [
  'FLASH_FIRE_TRY_HIT', 'FLASH_FIRE_ABILITY_END',
  'FLASH_FIRE_CONDITION_START', 'FLASH_FIRE_MODIFY_DAMAGE_PHASE1',
  'FLASH_FIRE_CONDITION_END',
];
const DECLARATIVE_REJECTION_HANDLER_IDS = ['TELEPORT_TRY'];
const RELATIONAL_ABILITY_HANDLER_IDS = ['MINUS_MODIFY_SPA', 'PLUS_MODIFY_SPA'];
const OHKO_HANDLER_IDS = ['STURDY_TRY_HIT'];
const MOVE_DELEGATION_HANDLER_IDS = [
  'METRONOME_HIT', 'NATURE_POWER_HIT', 'SLEEP_TALK_TRY',
  'SLEEP_TALK_TRY_HIT', 'SLEEP_TALK_HIT',
  'MIMIC_HIT', 'SKETCH_HIT', 'ASSIST_HIT',
];
const CONDITION_PROTOCOL_HANDLER_IDS = ['MUST_RECHARGE_START'];
const CURSE_HANDLER_IDS = [
  'CURSE_MODIFY_MOVE', 'CURSE_TRY_HIT', 'CURSE_HIT',
  'CURSE_START', 'CURSE_RESIDUAL',
];
const LOCK_ON_HANDLER_IDS = [
  'LOCK_ON_TRY_HIT', 'MIND_READER_TRY_HIT',
  'LOCK_ON_ACCURACY', 'LOCK_ON_INVULNERABILITY',
];
const WONDER_GUARD_HANDLER_IDS = ['WONDER_GUARD_TRY_HIT'];
const TWO_TURN_HANDLER_IDS = [
  'TWO_TURN_START', 'TWO_TURN_RESIDUAL', 'TWO_TURN_LOCK_MOVE',
  'TWO_TURN_MOVE_ABORTED', 'TWO_TURN_END',
];
const SOLAR_BEAM_HANDLER_IDS = ['SOLAR_BEAM_TRY_MOVE', 'SOLAR_BEAM_BASE_POWER'];
const FLINCH_HANDLER_IDS = ['FLINCH_BEFORE_MOVE', 'INNER_FOCUS_TRY_ADD_VOLATILE'];
const CRITICAL_HANDLER_IDS = [
  'FOCUS_ENERGY_START', 'FOCUS_ENERGY_MODIFY_CRIT_RATIO',
  'SCOPE_LENS_MODIFY_CRIT_RATIO', 'LUCKY_PUNCH_MODIFY_CRIT_RATIO',
  'STICK_MODIFY_CRIT_RATIO', 'BATTLE_ARMOR_CRITICAL_HIT',
  'SHELL_ARMOR_CRITICAL_HIT',
];
const PARTIAL_TRAP_HANDLER_IDS = [
  'PARTIALLY_TRAPPED_TRAP_POKEMON', 'PARTIALLY_TRAPPED_RESIDUAL',
];
const TAUNT_LIFECYCLE_HANDLER_IDS = ['TAUNT_START', 'TAUNT_END'];
const TORMENT_LIFECYCLE_HANDLER_IDS = ['TORMENT_START', 'TORMENT_END'];
const DISABLE_LIFECYCLE_HANDLER_IDS = ['DISABLE_END'];
const ENCORE_LIFECYCLE_HANDLER_IDS = ['ENCORE_END'];
const STRUGGLE_HANDLER_IDS = ['STRUGGLE_MODIFY_MOVE'];
const DISABLE_MOVE_HANDLER_IDS = ['DISABLE_TRY_HIT'];
const MIST_HANDLER_IDS = ['MIST_TRY_BOOST'];
const SAFEGUARD_HANDLER_IDS = ['SAFEGUARD_SET_STATUS', 'SAFEGUARD_TRY_ADD_VOLATILE'];
const YAWN_HANDLER_IDS = [
  'INSOMNIA_TRY_ADD_YAWN', 'VITAL_SPIRIT_TRY_ADD_YAWN',
  'YAWN_TRY_HIT', 'YAWN_START', 'YAWN_END',
  'IMMUNITY_UPDATE', 'INSOMNIA_UPDATE', 'VITAL_SPIRIT_UPDATE',
  'LIMBER_UPDATE', 'WATER_VEIL_UPDATE', 'MAGMA_ARMOR_UPDATE',
];
const STATUS_ABILITY_UPDATE_HANDLERS = [
  ['immunity', 'IMMUNITY', '(UINT32_C(1) << POKEMON_STATUS_POISON) | (UINT32_C(1) << POKEMON_STATUS_TOXIC)'],
  ['insomnia', 'INSOMNIA', '(UINT32_C(1) << POKEMON_STATUS_SLEEP)'],
  ['vitalspirit', 'VITAL_SPIRIT', '(UINT32_C(1) << POKEMON_STATUS_SLEEP)'],
  ['limber', 'LIMBER', '(UINT32_C(1) << POKEMON_STATUS_PARALYSIS)'],
  ['waterveil', 'WATER_VEIL', '(UINT32_C(1) << POKEMON_STATUS_BURN)'],
  ['magmaarmor', 'MAGMA_ARMOR', '(UINT32_C(1) << POKEMON_STATUS_FREEZE)'],
];
const SPIKES_HANDLER_IDS = ['SPIKES_START', 'SPIKES_RESTART', 'SPIKES_ENTRY_HAZARD'];
const SCREEN_HANDLER_IDS = [
  'REFLECT_MODIFY_DAMAGE_PHASE1', 'LIGHT_SCREEN_MODIFY_DAMAGE_PHASE1',
];
const TARGET_RELATIVE_HANDLER_IDS = ['ENDEAVOR_TRY_MOVE'];
const BRICK_BREAK_HANDLER_IDS = ['BRICK_BREAK_TRY_HIT'];
const LEFTOVERS_HANDLER_IDS = ['LEFTOVERS_RESIDUAL'];
const NATURAL_CURE_HANDLER_IDS = ['NATURAL_CURE_SWITCH_OUT'];
const SHED_SKIN_HANDLER_IDS = ['SHED_SKIN_RESIDUAL'];
const SPEED_BOOST_HANDLER_IDS = ['SPEED_BOOST_RESIDUAL'];
const TRUANT_HANDLER_IDS = [
  'TRUANT_SWITCH_IN', 'TRUANT_BEFORE_MOVE', 'TRUANT_RESIDUAL',
];
const FORECAST_HANDLER_IDS = ['FORECAST_START', 'FORECAST_WEATHER_CHANGE'];
const TRANSFORM_HANDLER_IDS = ['TRANSFORM_HIT'];
const ATOMIC_FORMULA_HANDLER_IDS = [
  'SMELLING_SALTS_HIT', 'BELLY_DRUM_HIT',
];
const PARTY_HIT_HANDLER_IDS = [
  'BEAT_UP_MODIFY_MOVE', 'BEAT_UP_BASE_POWER',
  'BEAT_UP_MODIFY_SPA', 'BEAT_UP_MODIFY_SPD',
];
const DIRECT_HP_ASSIGNMENT_HANDLER_IDS = ['PAIN_SPLIT_HIT'];
const MOVE_FAILURE_HANDLER_IDS = [
  'JUMP_KICK_MOVE_FAIL', 'HIGH_JUMP_KICK_MOVE_FAIL',
];
const RECENT_DAMAGE_HANDLER_IDS = ['REVENGE_BASE_POWER'];
const MOVE_IMMUNITY_HANDLER_IDS = ['DREAM_EATER_TRY_IMMUNITY'];
const NIGHTMARE_HANDLER_IDS = ['NIGHTMARE_START', 'NIGHTMARE_RESIDUAL'];
const INTIMIDATE_HANDLER_IDS = ['INTIMIDATE_START'];
const TRACE_HANDLER_IDS = ['TRACE_START'];
const COLOR_CHANGE_HANDLER_IDS = ['COLOR_CHANGE_DAMAGING_HIT'];
const ATTRACTION_HANDLER_IDS = [
  'CUTE_CHARM_DAMAGING_HIT', 'ATTRACT_TRY_IMMUNITY', 'ATTRACT_START',
  'ATTRACT_BEFORE_MOVE', 'ATTRACT_UPDATE', 'ATTRACT_END',
];
const PRESSURE_HANDLER_IDS = ['PRESSURE_DEDUCT_PP', 'PRESSURE_START'];
const DAMP_HANDLER_IDS = ['DAMP_TRY_MOVE'];
const CONTACT_RESPONSE_HANDLER_IDS = [
  'FLAME_BODY_DAMAGING_HIT', 'STATIC_DAMAGING_HIT',
  'POISON_POINT_DAMAGING_HIT', 'EFFECT_SPORE_DAMAGING_HIT',
  'ROUGH_SKIN_DAMAGING_HIT',
];
const DEFINITIVE_TRAP_HANDLER_IDS = [
  'ARENA_TRAP_TRAP_POKEMON', 'MAGNET_PULL_TRAP_POKEMON',
];
const FLY_HANDLER_IDS = ['FLY_TRY_MOVE', 'FLY_INVULNERABILITY'];
const HAZE_HANDLER_IDS = ['HAZE_HIT_FIELD'];
const PERISH_SONG_HANDLER_IDS = [
  'PERISH_SONG_HIT_FIELD', 'PERISH_SONG_RESIDUAL', 'PERISH_SONG_END',
];
const FORESIGHT_HANDLER_IDS = [
  'FORESIGHT_TRY_HIT', 'ODOR_SLEUTH_TRY_HIT', 'FORESIGHT_START',
  'FORESIGHT_NEGATE_IMMUNITY', 'FORESIGHT_MODIFY_BOOST',
];
const STATUS_START_HANDLER_IDS = ['SLEEP_START'];
const REST_HANDLER_IDS = ['REST_TRY', 'REST_HIT'];
const SYNCHRONIZE_HANDLER_IDS = ['SYNCHRONIZE_AFTER_SET_STATUS'];
const SLEEP_LIFECYCLE_HANDLER_IDS = ['SLEEP_BEFORE_MOVE', 'SLEEP_SWITCH_IN'];
const STATUS_ACTION_HANDLER_IDS = ['PARALYSIS_BEFORE_MOVE', 'PARALYSIS_START'];
const STAT_ITEM_HANDLER_IDS = [
  'DEEP_SEA_SCALE_SPD', 'DEEP_SEA_TOOTH_SPA',
  'LIGHT_BALL_SPA', 'MACHO_BRACE_SPEED',
  'SOUL_DEW_SPA', 'SOUL_DEW_SPD',
];
const DAMAGE_RELAY_HANDLER_IDS = ['FALSE_SWIPE_DAMAGE'];
const UPDATE_CURE_HANDLER_IDS = ['MENTAL_HERB_UPDATE'];
const WHITE_HERB_HANDLER_IDS = [
  'WHITE_HERB_START', 'WHITE_HERB_ANY_SWITCH_IN',
  'WHITE_HERB_ANY_AFTER_MOVE', 'WHITE_HERB_RESIDUAL',
];
const CHOICE_BAND_HANDLER_IDS = [
  'CHOICE_BAND_MODIFY_ATK', 'CHOICE_BAND_AFTER_MOVE',
];
const TEAM_STATUS_CURE_HANDLER_IDS = [
  'AROMATHERAPY_HIT', 'HEAL_BELL_HIT',
];
const FREEZE_LIFECYCLE_HANDLER_IDS = [
  'FREEZE_START', 'FREEZE_BEFORE_MOVE', 'FREEZE_MODIFY_MOVE',
  'FREEZE_DAMAGING_HIT',
];
const OBLIVIOUS_HANDLER_IDS = [
  'OBLIVIOUS_IMMUNITY', 'OBLIVIOUS_TRY_HIT', 'OBLIVIOUS_UPDATE',
];
const ROLE_PLAY_HANDLER_IDS = ['ROLE_PLAY_TRY_HIT', 'ROLE_PLAY_HIT'];
const SKILL_SWAP_HANDLER_IDS = ['SKILL_SWAP_HIT'];
const SOURCE_TRAP_HANDLER_IDS = [
	'BLOCK_HIT', 'MEAN_LOOK_HIT', 'SPIDER_WEB_HIT',
	'TRAPPED_START', 'TRAPPED_TRAP_POKEMON',
];
const METAL_POWDER_HANDLER_IDS = ['METAL_POWDER_MODIFY_DEF'];
const TWO_TURN_FAMILY_HANDLER_IDS = [
  'BOUNCE_TRY_MOVE', 'DIG_TRY_MOVE', 'DIVE_TRY_MOVE',
  'RAZOR_WIND_TRY_MOVE', 'SKULL_BASH_TRY_MOVE', 'SKY_ATTACK_TRY_MOVE',
  'BOUNCE_INVULNERABILITY', 'BOUNCE_SOURCE_BASE_POWER',
  'DIG_INVULNERABILITY', 'DIG_SOURCE_MODIFY_DAMAGE',
  'DIVE_INVULNERABILITY', 'DIVE_SOURCE_MODIFY_DAMAGE',
  'DIG_IMMUNITY', 'DIVE_IMMUNITY',
  'FLY_SOURCE_MODIFY_DAMAGE',
];
const SNORE_HANDLER_IDS = ['SNORE_TRY'];
const STARTER_ABILITY_HANDLERS = [
  ['blaze', 'Fire'], ['overgrow', 'Grass'], ['swarm', 'Bug'], ['torrent', 'Water'],
];
const WEATHER_HANDLER_IDS = ['RAIN_DAMAGE', 'SUN_DAMAGE'];
const WEATHER_SPEED_HANDLER_IDS = ['CHLOROPHYLL_SPEED', 'SWIFT_SWIM_SPEED', 'PARALYSIS_SPEED'];
const WEATHER_RESIDUAL_HANDLER_IDS = ['RAIN_DISH_RESIDUAL'];
const LIFECYCLE_HANDLER_IDS = [
  'CLOUD_NINE_START', 'CLOUD_NINE_END', 'SAND_STREAM_START',
];
const BERRY_HANDLER_IDS = [
  'ORANBERRY_RESIDUAL', 'ORANBERRY_TRY_EAT', 'ORANBERRY_EAT',
  'SITRUSBERRY_RESIDUAL', 'SITRUSBERRY_TRY_EAT', 'SITRUSBERRY_EAT',
];
const FLAVOR_BERRY_HANDLER_IDS = FLAVOR_BERRIES.flatMap(([id]) => [
  `${id.toUpperCase()}_RESIDUAL`, `${id.toUpperCase()}_TRY_EAT`,
  `${id.toUpperCase()}_EAT`,
]);
const PINCH_BERRY_HANDLER_IDS = [
  'LIECHIBERRY_RESIDUAL', 'LIECHIBERRY_EAT',
  'GANLONBERRY_RESIDUAL', 'GANLONBERRY_EAT',
  'SALACBERRY_RESIDUAL', 'SALACBERRY_EAT',
  'PETAYABERRY_RESIDUAL', 'PETAYABERRY_EAT',
  'APICOTBERRY_RESIDUAL', 'APICOTBERRY_EAT',
  'LANSATBERRY_RESIDUAL', 'LANSATBERRY_EAT',
  'STARFBERRY_RESIDUAL', 'STARFBERRY_EAT',
];
const STATUS_CURE_BERRY_HANDLER_IDS = STATUS_CURE_BERRIES.flatMap(([id]) => [
  `${id.toUpperCase()}_UPDATE`, `${id.toUpperCase()}_EAT`,
]);
const VOLATILE_CURE_BERRY_HANDLER_IDS = VOLATILE_CURE_BERRIES.flatMap(([id]) => [
  `${id.toUpperCase()}_UPDATE`, `${id.toUpperCase()}_EAT`,
]);
const COMBINED_CURE_BERRY_HANDLER_IDS = COMBINED_CURE_BERRIES.flatMap(([id]) => [
  `${id.toUpperCase()}_AFTER_SET_STATUS`, `${id.toUpperCase()}_UPDATE`,
  `${id.toUpperCase()}_EAT`,
]);
const ABILITIES = [
  'limber', 'synchronize', 'insomnia', 'guts', 'overgrow', 'blaze',
  'rockhead', 'naturalcure', 'levitate', 'waterabsorb', 'voltabsorb',
  'thickfat',
  'clearbody', 'hypercutter', 'keeneye', 'whitesmoke',
  'immunity', 'swiftswim', 'lightningrod',
  'pressure',
  'damp',
  'vitalspirit', 'waterveil', 'magmaarmor',
  'cloudnine',
  'sandstream',
  'chlorophyll', 'raindish',
  'owntempo',
  'shielddust',
  'stickyhold', 'compoundeyes', 'hugepower', 'hustle', 'purepower',
  'innerfocus',
  'battlearmor', 'shellarmor',
  'swarm', 'torrent', 'flamebody', 'static', 'poisonpoint', 'effectspore',
  'roughskin',
  'shedskin', 'marvelscale',
  'arenatrap', 'magnetpull',
  'serenegrace',
  'earlybird',
  /* Appended to preserve all established native ability IDs. */
  'speedboost',
  'intimidate',
  'trace',
  'colorchange',
  'cutecharm',
  /* Resolved inheritance leaves these legal identities callback-free. */
  'illuminate', 'pickup', 'runaway', 'stench',
  /* Appended to preserve all established native ability IDs. */
  'oblivious',
	'wonderguard',
	'suctioncups',
	'liquidooze',
	'flashfire',
	/* Relational special-attack modifiers; appended to preserve executable IDs. */
	'minus', 'plus',
	/* Appended independently so previous ability IDs remain stable. */
	'sturdy',
	/* Pokémon-owned alternating phase; appended to preserve prior table order. */
	'truant',
	/* Weather-projected form identity; appended to preserve prior ability IDs. */
	'forecast',
];
const metronome = dex.moves.get('metronome');
const metronomeSource = String(metronome.onHit);
const METRONOME_POOL = dex.moves.all().filter(move =>
  (!move.isNonstandard || move.isNonstandard === 'Unobtainable') &&
  move.flags?.metronome
).sort((left, right) => left.num - right.num);
if (typeof metronome.onHit !== 'function' ||
    !/move\.flags\[["']metronome["']\]/.test(metronomeSource) ||
    !metronomeSource.includes('moves.sort((a, b) => a.num - b.num)') ||
    !metronomeSource.includes('this.sample(moves)') ||
    !metronomeSource.includes('this.actions.useMove(randomMove, pokemon)') ||
    METRONOME_POOL.length !== 336 ||
    new Set(METRONOME_POOL.map(move => move.id)).size !== 336) {
  throw new Error('resolved Gen 3 Metronome call pool changed');
}
const moveCatalogID = new Map(
  inventory.moves.map((entry, index) => [entry.id, index + 1]));
for (let index = 0; index < METRONOME_POOL.length; index++) {
  const move = METRONOME_POOL[index];
  if (!moveCatalogID.has(move.id) ||
      (index && METRONOME_POOL[index - 1].num > move.num) ||
      move.id === 'metronome') {
    throw new Error(`invalid Metronome pool candidate: ${move.id}`);
  }
}
const MOVE_FLAGS = [
  'allyanim', 'bite', 'bullet', 'bypasssub', 'charge', 'contact', 'dance',
  'defrost', 'distance', 'failcopycat', 'failencore', 'failinstruct',
  'failmefirst', 'failmimic', 'futuremove', 'gravity', 'heal', 'metronome',
  'minimize', 'mirror', 'mustpressure', 'noassist', 'nonsky',
  'noparentalbond', 'nosketch', 'nosleeptalk', 'powder', 'protect', 'pulse',
  'punch', 'recharge', 'reflectable', 'slicing', 'snatch', 'sound', 'wind',
];
const MOVE_TARGETS = new Map([
  ['adjacentAlly', 'POKEMON_TARGET_ADJACENT_ALLY'],
  ['all', 'POKEMON_TARGET_ALL'],
  ['allAdjacent', 'POKEMON_TARGET_ALL_ADJACENT'],
  ['allAdjacentFoes', 'POKEMON_TARGET_ALL_ADJACENT_FOES'],
  ['allySide', 'POKEMON_TARGET_ALLY_SIDE'],
  ['allyTeam', 'POKEMON_TARGET_ALLY_TEAM'],
  ['any', 'POKEMON_TARGET_ANY'],
  ['foeSide', 'POKEMON_TARGET_FOE_SIDE'],
  ['normal', 'POKEMON_TARGET_NORMAL'],
  ['randomNormal', 'POKEMON_TARGET_RANDOM_NORMAL'],
  ['scripted', 'POKEMON_TARGET_SCRIPTED'],
  ['self', 'POKEMON_TARGET_SELF'],
]);
const executableSpecies = new Map(SPECIES.map((id, index) => [id, index + 1]));
const executableMoves = new Map(MOVES.map((id, index) => [id, index + 1]));
const catalogMaps = new Map(inventoryKinds.map(([kind]) => [
  kind,
  new Map(inventory[kind].map((entry, index) => [entry.id, index + 1])),
]));
const resolvedFormat = dex.formats.get('gen3ou');
const resolvedRuleTable = dex.formats.getRuleTable(resolvedFormat);
const constraints = inventory.format_constraints;
if (resolvedFormat.gameType !== 'singles' ||
    resolvedRuleTable.minTeamSize !== constraints.team.min_size ||
    resolvedRuleTable.maxTeamSize !== constraints.team.max_size ||
    resolvedRuleTable.maxMoveCount !== constraints.team.max_moves ||
    resolvedRuleTable.minLevel !== constraints.team.min_level ||
    resolvedRuleTable.maxLevel !== constraints.team.max_level ||
    resolvedRuleTable.defaultLevel !== constraints.team.default_level ||
    resolvedRuleTable.evLimit !== constraints.team.ev_limit ||
    inventory.format_rules.length !== 42) {
  throw new Error('resolved Gen 3 OU format constraints changed');
}

function formatOperand(component) {
  const split = component.indexOf(':');
  if (split < 0) return null;
  const kind = component.slice(0, split);
  const id = component.slice(split + 1);
  const inventoryKind = {
    pokemon: 'species', move: 'moves', ability: 'abilities', item: 'items',
  }[kind];
  if (!inventoryKind) return null;
  const catalogID = catalogMaps.get(inventoryKind).get(id);
  if (!catalogID) return null;
  return {
    kind: `POKEMON_FORMAT_OPERAND_${kind === 'pokemon' ? 'SPECIES' : cName(kind)}`,
    catalogID,
  };
}

function classifyFormatRule(rule) {
  if (rule.kind === 'ban') {
    if (rule.id === '-pokemontag:uber') {
      // The frozen battle catalog contains the Gen 3 OU legal/reachable
      // identities, not every illegal Gen 3 species.  Retain this rule in the
      // manifest, but do not pretend it can decide admission until a distinct
      // validation-universe catalog exists.
      return {kind: 'POKEMON_FORMAT_RULE_UNSUPPORTED_ADMISSION_UNIVERSE', operands: []};
    }
    const operand = formatOperand(rule.id.startsWith('-') ? rule.id.slice(1) : rule.id);
    return operand ? {kind: 'POKEMON_FORMAT_RULE_BAN', operands: [operand]} :
      {kind: 'POKEMON_FORMAT_RULE_UNSUPPORTED_ADMISSION_UNIVERSE', operands: []};
  }
  if (rule.kind === 'complex-ban') {
    const operands = rule.components.map(formatOperand);
    return operands.every(Boolean) && operands.length <= 3 ?
      {kind: 'POKEMON_FORMAT_RULE_COMPLEX_SET_BAN', operands} :
      {kind: 'POKEMON_FORMAT_RULE_UNSUPPORTED_SET_FIELDS', operands: []};
  }
  if (rule.id === 'speciesclause') {
    return {kind: 'POKEMON_FORMAT_RULE_SPECIES_CLAUSE', operands: []};
  }
  if (['evlimit', 'nicknameclause', 'obtainable', 'obtainableabilities',
    'obtainableformes', 'obtainablemisc', 'obtainablemoves',
    'oneboostpasserclause', 'accuracytrapclause', 'speedpassclause'].includes(rule.id)) {
    return {kind: 'POKEMON_FORMAT_RULE_UNSUPPORTED_SET_FIELDS', operands: []};
  }
  if (rule.id === 'switchpriorityclausemod') {
    return {kind: 'POKEMON_FORMAT_RULE_ASSERTION', operands: []};
  }
  if (rule.id === 'cancelmod') {
    return {kind: 'POKEMON_FORMAT_RULE_REQUEST_PROTOCOL', operands: []};
  }
  if (['hppercentagemod', 'beatupnicknamesmod'].includes(rule.id)) {
    return {kind: 'POKEMON_FORMAT_RULE_PRESENTATION', operands: []};
  }
  if (['sleepclausemod', 'freezeclausemod',
    'endlessbattleclause'].includes(rule.id)) {
    return {kind: 'POKEMON_FORMAT_RULE_RUNTIME_ONLY', operands: []};
  }
  return {kind: 'POKEMON_FORMAT_RULE_METADATA', operands: []};
}
const cName = value => value.toUpperCase().replace(/[^A-Z0-9]+/g, '_');
const typeToken = value => value === '???' ? 'TYPELESS' : cName(value);
if (output === 'id-map') {
  const numericIDs = (ids, lookup) => Object.fromEntries(ids.map((id, index) =>
    [id, lookup ? lookup(id) : index + 1]));
  process.stdout.write(`${JSON.stringify({
    data_symbol: 'POKEMON_GEN3_SLICE_DATA',
    generation_symbol: 'POKEMON_GEN3_RULES',
    format_symbols: {
      1: 'POKEMON_SINGLES_1_FORMAT',
      2: 'POKEMON_SINGLES_2_FORMAT',
      3: 'POKEMON_SINGLES_3_FORMAT',
      6: 'POKEMON_SINGLES_6_FORMAT',
    },
    species: numericIDs(SPECIES),
    moves: numericIDs(MOVES),
    abilities: {'': 0, ...numericIDs(ABILITIES, id => dex.abilities.get(id).num)},
    items: {'': 0, ...numericIDs(ITEMS, id => dex.items.get(id).num)},
  }, null, 2)}\n`);
  process.exit(0);
}

const cString = value => JSON.stringify(value);
function typeID(name) {
  const index = TYPES.indexOf(name);
  if (index < 0) throw new Error(`type outside slice: ${name}`);
  return `POKEMON_GEN3_TYPE_${typeToken(name)}`;
}
function effectiveness(attack, defense) {
  // Showdown damageTaken: 0=neutral, 1=weak, 2=resist, 3=immune.
  return [4, 8, 2, 0][dex.types.get(defense).damageTaken[attack] || 0];
}
const lines = [
  '/* Generated by tools/generate_slice_data.js; do not edit. */',
  `/* Pokémon Showdown source revision: ${revision}. */`,
];
if (output === 'header') {
  lines.push('#ifndef GEN3_SLICE_DATA_H', '#define GEN3_SLICE_DATA_H', '', '#include "pokemon.h"', '');
  lines.push('enum {');
  TYPES.forEach((name, index) => lines.push(`    POKEMON_GEN3_TYPE_${typeToken(name)} = ${index},`));
  lines.push(`    POKEMON_GEN3_TYPE_COUNT = ${TYPES.length}`, '};', '', 'enum {');
  SPECIES.forEach((id, index) => lines.push(`    POKEMON_GEN3_SPECIES_${cName(id)} = ${index + 1},`));
  lines.push(`    POKEMON_GEN3_SPECIES_COUNT = ${SPECIES.length},`);
  lines.push('};', '', 'enum {');
  MOVES.forEach((id, index) => lines.push(`    POKEMON_GEN3_MOVE_${cName(id)} = ${index + 1},`));
  lines.push(`    POKEMON_GEN3_MOVE_COUNT = ${MOVES.length},`);
  lines.push('};', '', 'enum {');
  for (const id of ABILITIES) {
    const ability = dex.abilities.get(id);
    lines.push(`    POKEMON_GEN3_ABILITY_${cName(id)} = ${ability.num},`);
  }
  lines.push('};', '', 'enum {');
  for (const id of ITEMS) {
    const item = dex.items.get(id);
    lines.push(`    POKEMON_GEN3_ITEM_${cName(id)} = ${item.num},`);
  }
  lines.push('};', '', 'enum {');
  conditions.forEach((entry, index) => lines.push(
    `    POKEMON_GEN3_CONDITION_${entry.token}_${cName(entry.id)} = ${index + 1},`));
  lines.push('    POKEMON_GEN3_CONDITION_SIMULATOR_TRAPPER = POKEMON_GEN3_CONDITION_VOLATILE_TRAPPER,');
  lines.push('};', '', 'enum {',
    ...BASE_HANDLER_IDS.map((id, index) =>
      `    POKEMON_GEN3_HANDLER_${id}${index === 0 ? ' = 1' : ''},`),
    ...SCALAR_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...TYPE_BOOST_ITEMS.slice(1).map(([id]) =>
      `    POKEMON_GEN3_HANDLER_${cName(id)},`),
    ...WEATHER_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...WEATHER_SPEED_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...WEATHER_RESIDUAL_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...LIFECYCLE_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...BERRY_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...FLAVOR_BERRY_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...PINCH_BERRY_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...STATUS_CURE_BERRY_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...VOLATILE_CURE_BERRY_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...COMBINED_CURE_BERRY_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...CONFUSION_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...CONFUSION_SECONDARY_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...LOCKED_MOVE_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...WEATHER_BALL_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...THUNDER_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...MAGNITUDE_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...TWO_TURN_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...SOLAR_BEAM_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...FLINCH_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...CRITICAL_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...PARTIAL_TRAP_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...TAUNT_LIFECYCLE_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...TORMENT_LIFECYCLE_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...DISABLE_LIFECYCLE_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...ENCORE_LIFECYCLE_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...STRUGGLE_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...DISABLE_MOVE_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...MIST_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...SAFEGUARD_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...STARTER_ABILITY_HANDLERS.map(([id]) =>
      `    POKEMON_GEN3_HANDLER_${cName(id)}_BASE_POWER,`),
    ...YAWN_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...SPIKES_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...SCREEN_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...TARGET_RELATIVE_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...BRICK_BREAK_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...LEFTOVERS_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...NATURAL_CURE_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...SHED_SKIN_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...PRESSURE_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...DAMP_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...CONTACT_RESPONSE_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...DEFINITIVE_TRAP_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...FLY_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...HAZE_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...STATUS_START_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...REST_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...SYNCHRONIZE_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...SLEEP_LIFECYCLE_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...SNORE_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...SPEED_BOOST_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...NIGHTMARE_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...INTIMIDATE_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...TRACE_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...COLOR_CHANGE_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...ATTRACTION_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...STATUS_ACTION_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...STAT_ITEM_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...WHITE_HERB_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...UPDATE_CURE_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...DAMAGE_RELAY_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...CHOICE_BAND_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...TEAM_STATUS_CURE_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...FREEZE_LIFECYCLE_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...OBLIVIOUS_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
    ...ROLE_PLAY_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
	...SKILL_SWAP_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
	...SOURCE_TRAP_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
	...METAL_POWDER_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
	...TWO_TURN_FAMILY_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
	...SPORT_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
	...PROTECTION_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
	...LOCK_ON_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
	...WONDER_GUARD_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
	...FOCUS_BAND_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
	...MAJOR_STATUS_LIFECYCLE_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
	...LEPPA_BERRY_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
	...KINGS_ROCK_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
	...SHELL_BELL_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
	...FAKE_OUT_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
	...FOLLOW_ME_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
	...RETALIATION_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
	...DRAG_BLOCKER_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
	...QUEUED_INTERCEPT_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
	...CHARGE_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
	...SOURCE_LINKED_RESIDUAL_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
	...FLASH_FIRE_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
	...DECLARATIVE_REJECTION_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
	...RELATIONAL_ABILITY_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
	...OHKO_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
	...MOVE_DELEGATION_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
	...PERISH_SONG_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
	...FORESIGHT_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
	...BIDE_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
	...RAMPING_POWER_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
	...LOCKED_RAMP_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
	...COUNTER_STACK_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
	...TYPE_RESPONSE_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
	...RAGE_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
	...MINIMIZE_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
	...SPITE_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
	...TYPE_OVERLAY_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
	...PREPARED_ACTION_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
	...FAINT_RESPONSE_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
	...UPROAR_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
	...IMPRISON_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
	...SECRET_POWER_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
	...PRESENT_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
	...FORMAT_STATUS_CLAUSE_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
	...CURSE_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
	...CONDITION_PROTOCOL_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
	...TRUANT_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
	...DIRECT_HP_ASSIGNMENT_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
	...MOVE_FAILURE_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
	...RECENT_DAMAGE_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
	...MOVE_IMMUNITY_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
	...FORECAST_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
	...TRANSFORM_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
	...ATOMIC_FORMULA_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
	...PARTY_HIT_HANDLER_IDS.map(id => `    POKEMON_GEN3_HANDLER_${id},`),
	'    POKEMON_GEN3_HANDLER_DESCRIPTOR_COUNT = POKEMON_GEN3_HANDLER_BEAT_UP_MODIFY_SPD,',
    '};', '', 'enum {',
    '    POKEMON_GEN3_SPECIES_CATALOG_COUNT = 369,',
    '    POKEMON_GEN3_MOVE_CATALOG_COUNT = 354,',
    '    POKEMON_GEN3_ABILITY_CATALOG_COUNT = 70,',
    '    POKEMON_GEN3_ITEM_CATALOG_COUNT = 104,',
    '    POKEMON_GEN3_CONDITION_CATALOG_COUNT = 82,',
    '};', '', `extern const uint8_t POKEMON_GEN3_SLICE_BASE_STATS[${SPECIES.length}][6];`);
  lines.push('extern const PokemonData POKEMON_GEN3_SLICE_DATA;',
    'extern const PokemonFormatManifest POKEMON_GEN3_OU_FORMAT;',
    'extern const PokemonFormatManifest POKEMON_GEN3_OU_POMEG_FORMAT;', '', '#endif');
} else {
  lines.push('#include "gen3_slice_data.h"', '',
    'static const PokemonSpeciesIdentity SPECIES_CATALOG[] = {');
  inventory.species.forEach((entry, index) => {
    const species = dex.species.get(entry.id);
    if (!species.exists || species.gen > 3 || species.name !== entry.name ||
        species.num !== entry.num) {
      throw new Error(`frozen species does not resolve: ${entry.id}`);
    }
    const types = species.types.map(typeID);
    const typeCount = types.length;
    while (types.length < 2) types.push('0');
    const s = species.baseStats;
    const weightHg = Math.round(species.weightkg * 10);
    if (!Number.isInteger(weightHg) || weightHg <= 0) {
      throw new Error(`invalid species weight: ${entry.id}`);
    }
    lines.push(`    {${index + 1}, ${species.num}, ${executableSpecies.get(entry.id) || 0}, ` +
      `${cString(entry.id)}, ${cString(entry.name)}, ${cString(entry.tier)}, ` +
      `{${types.join(', ')}}, ${typeCount}, ` +
      `{${s.hp}, ${s.atk}, ${s.def}, ${s.spa}, ${s.spd}, ${s.spe}}, ` +
      `${species.maxHP || 0}, ${weightHg}},`);
  });
  lines.push('};', '', 'static const PokemonMoveIdentity MOVE_CATALOG[] = {');
  inventory.moves.forEach((entry, index) => {
    const move = dex.moves.get(entry.id);
    if (!move.exists || move.gen > 3 || move.name !== entry.name ||
        move.type !== entry.type || move.category !== entry.category ||
        move.target !== entry.target || !MOVE_TARGETS.has(move.target)) {
      throw new Error(`frozen move does not resolve: ${entry.id}`);
    }
    let flags = 0n;
    for (const flag of Object.keys(move.flags || {})) {
      const flagIndex = MOVE_FLAGS.indexOf(flag);
      if (flagIndex < 0) throw new Error(`unmapped move flag ${flag} on ${entry.id}`);
      flags |= 1n << BigInt(flagIndex);
    }
    const accuracy = move.accuracy === true ?
      '{POKEMON_ACCURACY_ALWAYS, 0}' :
      `{POKEMON_ACCURACY_PERCENT, ${move.accuracy}}`;
    lines.push(`    {${index + 1}, ${move.num}, ${executableMoves.get(entry.id) || 0}, ` +
      `${cString(entry.id)}, ${cString(entry.name)}, ${typeID(move.type)}, ` +
      `POKEMON_CATEGORY_${cName(move.category)}, ${move.basePower}, ${accuracy}, ` +
      `${move.priority}, ${move.pp}, ${MOVE_TARGETS.get(move.target)}, ` +
      `UINT64_C(${flags})},`);
  });
  lines.push('};', '', 'static const uint16_t MOVE_CALL_POOL_CANDIDATES[] = {');
  for (const move of METRONOME_POOL) {
    lines.push(`    ${moveCatalogID.get(move.id)}, /* ${move.id} (${move.num}) */`);
  }
  lines.push('};', '', 'static const PokemonMoveCallPool MOVE_CALL_POOLS[] = {',
    '    {1, POKEMON_GEN3_MOVE_METRONOME, 0, 336},',
    '};', '', 'static const PokemonNamedIdentity ABILITY_CATALOG[] = {');
  inventory.abilities.forEach((entry, index) => {
    const ability = dex.abilities.get(entry.id);
    if (!ability.exists || ability.gen > 3 || ability.name !== entry.name) {
      throw new Error(`frozen ability does not resolve: ${entry.id}`);
    }
    const executable = ABILITIES.includes(entry.id) ? ability.num : 0;
    lines.push(`    {${index + 1}, ${ability.num}, ${executable}, ` +
      `${cString(entry.id)}, ${cString(entry.name)}},`);
  });
  lines.push('};', '', 'static const PokemonNamedIdentity ITEM_CATALOG[] = {');
  inventory.items.forEach((entry, index) => {
    const item = dex.items.get(entry.id);
    if (!item.exists || item.gen > 3 || item.name !== entry.name) {
      throw new Error(`frozen item does not resolve: ${entry.id}`);
    }
    const executable = ITEMS.includes(entry.id) ? item.num : 0;
    lines.push(`    {${index + 1}, ${item.num}, ${executable}, ` +
      `${cString(entry.id)}, ${cString(entry.name)}},`);
  });
  const semanticConditions = new Map([
    ['statuses:brn', 'POKEMON_STATUS_BURN'],
    ['statuses:frz', 'POKEMON_STATUS_FREEZE'],
    ['statuses:par', 'POKEMON_STATUS_PARALYSIS'],
    ['statuses:psn', 'POKEMON_STATUS_POISON'],
    ['statuses:slp', 'POKEMON_STATUS_SLEEP'],
    ['statuses:tox', 'POKEMON_STATUS_TOXIC'],
    ['volatiles:protect', 'POKEMON_VOLATILE_PROTECT'],
    ['volatiles:endure', 'POKEMON_VOLATILE_ENDURE'],
    ['volatiles:stall', 'POKEMON_VOLATILE_STALL'],
    ['volatiles:magiccoat', 'POKEMON_VOLATILE_MAGIC_COAT'],
    ['volatiles:snatch', 'POKEMON_VOLATILE_SNATCH'],
    ['volatiles:confusion', 'POKEMON_VOLATILE_CONFUSION'],
    ['volatiles:flinch', 'POKEMON_VOLATILE_FLINCH'],
    ['volatiles:focusenergy', 'POKEMON_VOLATILE_FOCUS_ENERGY'],
    ['volatiles:lockedmove', 'POKEMON_VOLATILE_LOCKED_MOVE'],
    ['volatiles:partiallytrapped', 'POKEMON_VOLATILE_PARTIALLY_TRAPPED'],
    ['volatiles:twoturnmove', 'POKEMON_VOLATILE_TWO_TURN_MOVE'],
    ['volatiles:fly', 'POKEMON_VOLATILE_TWO_TURN_MARKER'],
    ['volatiles:solarbeam', 'POKEMON_VOLATILE_TWO_TURN_MARKER'],
    ['volatiles:bounce', 'POKEMON_VOLATILE_TWO_TURN_MARKER'],
    ['volatiles:dig', 'POKEMON_VOLATILE_TWO_TURN_MARKER'],
    ['volatiles:dive', 'POKEMON_VOLATILE_TWO_TURN_MARKER'],
    ['volatiles:razorwind', 'POKEMON_VOLATILE_TWO_TURN_MARKER'],
    ['volatiles:skullbash', 'POKEMON_VOLATILE_TWO_TURN_MARKER'],
    ['volatiles:skyattack', 'POKEMON_VOLATILE_TWO_TURN_MARKER'],
    ['volatiles:taunt', 'POKEMON_VOLATILE_TAUNT'],
    ['volatiles:torment', 'POKEMON_VOLATILE_TORMENT'],
    ['volatiles:disable', 'POKEMON_VOLATILE_DISABLE'],
    ['volatiles:encore', 'POKEMON_VOLATILE_ENCORE'],
    ['volatiles:yawn', 'POKEMON_VOLATILE_YAWN'],
    ['volatiles:mudsport', 'POKEMON_VOLATILE_MUD_SPORT'],
    ['volatiles:watersport', 'POKEMON_VOLATILE_WATER_SPORT'],
    ['volatiles:mustrecharge', 'POKEMON_VOLATILE_MUST_RECHARGE'],
    ['volatiles:nightmare', 'POKEMON_VOLATILE_NIGHTMARE'],
    ['volatiles:attract', 'POKEMON_VOLATILE_ATTRACT'],
    ['volatiles:choicelock', 'POKEMON_VOLATILE_CHOICE_LOCK'],
	['volatiles:bide', 'POKEMON_VOLATILE_STORED_DAMAGE'],
	['volatiles:furycutter', 'POKEMON_VOLATILE_FURY_CUTTER'],
	['volatiles:rollout', 'POKEMON_VOLATILE_ROLLOUT'],
	['volatiles:iceball', 'POKEMON_VOLATILE_ICE_BALL'],
	['volatiles:defensecurl', 'POKEMON_VOLATILE_DEFENSE_CURL'],
	['volatiles:stockpile', 'POKEMON_VOLATILE_STOCKPILE'],
	['volatiles:trapped', 'POKEMON_VOLATILE_TRAPPED'],
	['volatiles:trapper', 'POKEMON_VOLATILE_TRAPPER'],
	['volatiles:lockon', 'POKEMON_VOLATILE_LOCK_ON'],
	['volatiles:counter', 'POKEMON_VOLATILE_PREPARED_RETALIATION'],
	['volatiles:mirrorcoat', 'POKEMON_VOLATILE_PREPARED_RETALIATION'],
	['volatiles:ingrain', 'POKEMON_VOLATILE_INGRAIN'],
	['volatiles:pursuit', 'POKEMON_VOLATILE_QUEUED_MOVE_INTERCEPT'],
	['volatiles:charge', 'POKEMON_VOLATILE_CHARGE'],
	['volatiles:leechseed', 'POKEMON_VOLATILE_LEECH_SEED'],
	['volatiles:perishsong', 'POKEMON_VOLATILE_COUNTDOWN_FAINT'],
	['volatiles:foresight', 'POKEMON_VOLATILE_FORESIGHT'],
	['volatiles:rage', 'POKEMON_VOLATILE_RAGE'],
	['volatiles:minimize', 'POKEMON_VOLATILE_MINIMIZE'],
	['volatiles:focuspunch', 'POKEMON_VOLATILE_PREPARED_ACTION'],
	['volatiles:destinybond', 'POKEMON_VOLATILE_SOURCE_FAINT_RESPONSE'],
	['volatiles:grudge', 'POKEMON_VOLATILE_SOURCE_PP_ZERO_RESPONSE'],
	['volatiles:uproar', 'POKEMON_VOLATILE_UPROAR'],
	['volatiles:imprison', 'POKEMON_VOLATILE_IMPRISON'],
	['volatiles:curse', 'POKEMON_VOLATILE_CURSE'],
	['volatiles:beatup', 'POKEMON_VOLATILE_PARTY_HIT'],
    ['side_conditions:reflect', 'POKEMON_SIDE_CONDITION_REFLECT'],
    ['side_conditions:lightscreen', 'POKEMON_SIDE_CONDITION_SPECIAL_SCREEN'],
    ['side_conditions:mist', 'POKEMON_SIDE_CONDITION_MIST'],
    ['side_conditions:safeguard', 'POKEMON_SIDE_CONDITION_SAFEGUARD'],
    ['side_conditions:spikes', 'POKEMON_SIDE_CONDITION_SPIKES'],
    ['weather:sandstorm', 'POKEMON_WEATHER_SANDSTORM'],
    ['weather:hail', 'POKEMON_WEATHER_HAIL'],
    ['weather:raindance', 'POKEMON_WEATHER_RAIN'],
    ['weather:sunnyday', 'POKEMON_WEATHER_SUN'],
    ['slot_conditions:futuremove', 'POKEMON_SLOT_CONDITION_FUTURE_MOVE'],
    ['slot_conditions:wish', 'POKEMON_SLOT_CONDITION_WISH'],
  ]);
  lines.push('};', '', 'static const PokemonConditionIdentity CONDITION_CATALOG[] = {');
  let conditionIndex = 0;
  for (const [kind, , token, domain] of conditionKinds) {
    for (const entry of inventory[kind]) {
      conditionIndex++;
      const semantic = semanticConditions.get(`${kind}:${entry.id}`) || 0;
      lines.push(`    {${conditionIndex}, ${domain}, ${semantic}, ` +
        `${cString(entry.id)}, ${cString(entry.name)}},`);
    }
  }
  lines.push('};', '');
  const weatherRows = [
    ['sandstorm', 'POKEMON_WEATHER_SANDSTORM', 'POKEMON_RESIDUAL_FORMULA_SAND'],
    ['hail', 'POKEMON_WEATHER_HAIL', 'POKEMON_RESIDUAL_FORMULA_SAND'],
    ['raindance', 'POKEMON_WEATHER_RAIN', 'POKEMON_RESIDUAL_FORMULA_NONE'],
    ['sunnyday', 'POKEMON_WEATHER_SUN', 'POKEMON_RESIDUAL_FORMULA_NONE'],
  ];
  lines.push('static const PokemonWeatherPolicy WEATHER_POLICIES[] = {');
  for (const [id, kind, formula] of weatherRows) {
    const weather = dex.conditions.get(id);
    if (!weather.exists || weather.effectType !== 'Weather' ||
        weather.duration !== 5 || typeof weather.onFieldStart !== 'function' ||
        typeof weather.onFieldResidual !== 'function' ||
        weather.onFieldResidualOrder !== 8 ||
        typeof weather.onFieldEnd !== 'function') {
      throw new Error(`resolved Gen 3 ${id} lifecycle changed`);
    }
    const damaging = formula !== 'POKEMON_RESIDUAL_FORMULA_NONE';
    const weatherSource = String(weather.onWeather);
    if (damaging !== (typeof weather.onWeather === 'function') ||
        (damaging && !weatherSource.includes('this.damage(target.baseMaxhp / 16)'))) {
      throw new Error(`resolved Gen 3 ${id} onWeather changed`);
    }
    const immuneTypes = TYPES.filter(type => !dex.getImmunity(id, type));
    const immuneMask = immuneTypes.length ? immuneTypes
      .map(type => `(UINT32_C(1) << ${typeID(type)})`).join(' | ') : '0';
    let blockedStatusMask = '0';
    if (id === 'sunnyday') {
      const immunitySource = String(weather.onImmunity);
      if (typeof weather.onImmunity !== 'function' ||
          !/type === ["']frz["']/.test(immunitySource) ||
          !/effectiveWeather\(\) !== ["']sunnyday["']/.test(immunitySource)) {
        throw new Error('resolved Gen 3 Sunny Day freeze immunity changed');
      }
      blockedStatusMask = '(UINT32_C(1) << POKEMON_STATUS_FREEZE)';
    } else if (weather.onImmunity !== undefined) {
      throw new Error(`resolved Gen 3 ${id} unexpectedly defines onImmunity`);
    }
    lines.push(`    {${kind}, POKEMON_GEN3_CONDITION_WEATHER_${cName(id)}, ` +
      `${formula}, ${immuneMask}, ${blockedStatusMask}},`);
  }
  lines.push('};', '', 'static const PokemonSpeciesData SPECIES[] = {');
  for (const id of SPECIES) {
    const species = dex.species.get(id);
    if (!species.exists || species.gen > 3) throw new Error(`invalid Gen 3 species: ${id}`);
    const types = species.types.map(typeID);
    const typeCount = types.length;
    while (types.length < 2) types.push('0');
    const weightHg = Math.round(species.weightkg * 10);
    if (!Number.isInteger(weightHg) || weightHg <= 0) {
      throw new Error(`invalid executable species weight: ${id}`);
    }
    lines.push(`    {POKEMON_GEN3_SPECIES_${cName(id)}, {${types.join(', ')}}, ${typeCount}, ${weightHg}},`);
  }
  lines.push('};', '', 'const uint8_t POKEMON_GEN3_SLICE_BASE_STATS[][6] = {');
  for (const id of SPECIES) {
    const s = dex.species.get(id).baseStats;
    lines.push(`    {${s.hp}, ${s.atk}, ${s.def}, ${s.spa}, ${s.spd}, ${s.spe}},`);
  }
  const effectSpecs = {
    bide: [['POKEMON_EFFECT_ADD_VOLATILE', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_USER', 100, 'POKEMON_VOLATILE_STORED_DAMAGE', 0]],
    destinybond: [['POKEMON_EFFECT_ADD_VOLATILE', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_USER', 100, 'POKEMON_VOLATILE_SOURCE_FAINT_RESPONSE', 0]],
    grudge: [['POKEMON_EFFECT_ADD_VOLATILE', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_USER', 100, 'POKEMON_VOLATILE_SOURCE_PP_ZERO_RESPONSE', 0]],
    uproar: [['POKEMON_EFFECT_ADD_VOLATILE', 'POKEMON_EFFECT_PHASE_AFTER_HIT_CALLBACK', 'POKEMON_EFFECT_TARGET_USER', 100, 'POKEMON_VOLATILE_UPROAR', 0]],
    imprison: [['POKEMON_EFFECT_ADD_VOLATILE', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_USER', 100, 'POKEMON_VOLATILE_IMPRISON', 0]],
    toxic: [['POKEMON_EFFECT_SET_STATUS', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_MOVE_TARGET', 100, 'POKEMON_STATUS_TOXIC', 0]],
    glare: [['POKEMON_EFFECT_SET_STATUS', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_MOVE_TARGET', 100, 'POKEMON_STATUS_PARALYSIS', 0]],
    grasswhistle: [['POKEMON_EFFECT_SET_STATUS', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_MOVE_TARGET', 100, 'POKEMON_STATUS_SLEEP', 0]],
    hypnosis: [['POKEMON_EFFECT_SET_STATUS', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_MOVE_TARGET', 100, 'POKEMON_STATUS_SLEEP', 0]],
    lovelykiss: [['POKEMON_EFFECT_SET_STATUS', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_MOVE_TARGET', 100, 'POKEMON_STATUS_SLEEP', 0]],
    poisongas: [['POKEMON_EFFECT_SET_STATUS', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_MOVE_TARGET', 100, 'POKEMON_STATUS_POISON', 0]],
    poisonpowder: [['POKEMON_EFFECT_SET_STATUS', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_MOVE_TARGET', 100, 'POKEMON_STATUS_POISON', 0]],
    sing: [['POKEMON_EFFECT_SET_STATUS', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_MOVE_TARGET', 100, 'POKEMON_STATUS_SLEEP', 0]],
    sleeppowder: [['POKEMON_EFFECT_SET_STATUS', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_MOVE_TARGET', 100, 'POKEMON_STATUS_SLEEP', 0]],
    spore: [['POKEMON_EFFECT_SET_STATUS', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_MOVE_TARGET', 100, 'POKEMON_STATUS_SLEEP', 0]],
    stunspore: [['POKEMON_EFFECT_SET_STATUS', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_MOVE_TARGET', 100, 'POKEMON_STATUS_PARALYSIS', 0]],
    thunderwave: [['POKEMON_EFFECT_SET_STATUS', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_MOVE_TARGET', 100, 'POKEMON_STATUS_PARALYSIS', 0]],
    willowisp: [['POKEMON_EFFECT_SET_STATUS', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_MOVE_TARGET', 100, 'POKEMON_STATUS_BURN', 0]],
    sandstorm: [['POKEMON_EFFECT_ADD_WEATHER', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_USER', 100, 'POKEMON_WEATHER_SANDSTORM', 0]],
    hail: [['POKEMON_EFFECT_ADD_WEATHER', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_USER', 100, 'POKEMON_WEATHER_HAIL', 0]],
    raindance: [['POKEMON_EFFECT_ADD_WEATHER', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_USER', 100, 'POKEMON_WEATHER_RAIN', 0]],
    sunnyday: [['POKEMON_EFFECT_ADD_WEATHER', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_USER', 100, 'POKEMON_WEATHER_SUN', 0]],
    protect: [['POKEMON_EFFECT_INSTALL_STALLING_GUARD', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_USER', 100, 'POKEMON_VOLATILE_PROTECT', 0]],
    detect: [['POKEMON_EFFECT_INSTALL_STALLING_GUARD', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_USER', 100, 'POKEMON_VOLATILE_PROTECT', 0]],
    endure: [['POKEMON_EFFECT_INSTALL_STALLING_GUARD', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_USER', 100, 'POKEMON_VOLATILE_ENDURE', 0]],
    mudsport: [['POKEMON_EFFECT_ADD_VOLATILE', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_USER', 100, 'POKEMON_VOLATILE_MUD_SPORT', 0]],
    watersport: [['POKEMON_EFFECT_ADD_VOLATILE', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_USER', 100, 'POKEMON_VOLATILE_WATER_SPORT', 0]],
    reflect: [['POKEMON_EFFECT_ADD_SIDE_CONDITION', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_USER', 100, 'POKEMON_SIDE_CONDITION_REFLECT', 0]],
    lightscreen: [['POKEMON_EFFECT_ADD_SIDE_CONDITION', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_USER', 100, 'POKEMON_SIDE_CONDITION_SPECIAL_SCREEN', 0]],
    mist: [['POKEMON_EFFECT_ADD_SIDE_CONDITION', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_USER', 100, 'POKEMON_SIDE_CONDITION_MIST', 0]],
    safeguard: [['POKEMON_EFFECT_ADD_SIDE_CONDITION', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_USER', 100, 'POKEMON_SIDE_CONDITION_SAFEGUARD', 0]],
    spikes: [['POKEMON_EFFECT_ADD_SIDE_CONDITION', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_MOVE_TARGET', 100, 'POKEMON_SIDE_CONDITION_SPIKES', 0]],
    yawn: [['POKEMON_EFFECT_ADD_VOLATILE', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_MOVE_TARGET', 100, 'POKEMON_VOLATILE_YAWN', 0]],
    nightmare: [['POKEMON_EFFECT_ADD_VOLATILE', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_MOVE_TARGET', 100, 'POKEMON_VOLATILE_NIGHTMARE', 0]],
    attract: [['POKEMON_EFFECT_ADD_VOLATILE', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_MOVE_TARGET', 100, 'POKEMON_VOLATILE_ATTRACT', 0]],
    growl: [['POKEMON_EFFECT_BOOST', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_MOVE_TARGET', 100, 'POKEMON_STAT_ATK', -1]],
    bulkup: [
      ['POKEMON_EFFECT_BOOST', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_USER', 100, 'POKEMON_STAT_ATK', 1],
      ['POKEMON_EFFECT_BOOST', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_USER', 100, 'POKEMON_STAT_DEF', 1],
    ],
    ember: [['POKEMON_EFFECT_SET_STATUS', 'POKEMON_EFFECT_PHASE_AFTER_HIT', 'POKEMON_EFFECT_TARGET_MOVE_TARGET', 10, 'POKEMON_STATUS_BURN', 0]],
    steelwing: [['POKEMON_EFFECT_BOOST', 'POKEMON_EFFECT_PHASE_AFTER_HIT', 'POKEMON_EFFECT_TARGET_USER', 10, 'POKEMON_STAT_DEF', 1]],
    bodyslam: [['POKEMON_EFFECT_SET_STATUS', 'POKEMON_EFFECT_PHASE_AFTER_HIT', 'POKEMON_EFFECT_TARGET_MOVE_TARGET', 30, 'POKEMON_STATUS_PARALYSIS', 0]],
    doubleedge: [['POKEMON_EFFECT_DAMAGE_RELATIVE', 'POKEMON_EFFECT_PHASE_AFTER_MOVE', 'POKEMON_EFFECT_TARGET_USER', 100, 'POKEMON_DAMAGE_RELATIVE_RECOIL', 0, 1, 3, 'POKEMON_DAMAGE_PREVENTABLE']],
    submission: [['POKEMON_EFFECT_DAMAGE_RELATIVE', 'POKEMON_EFFECT_PHASE_AFTER_MOVE', 'POKEMON_EFFECT_TARGET_USER', 100, 'POKEMON_DAMAGE_RELATIVE_RECOIL', 0, 1, 4, 'POKEMON_DAMAGE_PREVENTABLE']],
    takedown: [['POKEMON_EFFECT_DAMAGE_RELATIVE', 'POKEMON_EFFECT_PHASE_AFTER_MOVE', 'POKEMON_EFFECT_TARGET_USER', 100, 'POKEMON_DAMAGE_RELATIVE_RECOIL', 0, 1, 4, 'POKEMON_DAMAGE_PREVENTABLE']],
    volttackle: [['POKEMON_EFFECT_DAMAGE_RELATIVE', 'POKEMON_EFFECT_PHASE_AFTER_MOVE', 'POKEMON_EFFECT_TARGET_USER', 100, 'POKEMON_DAMAGE_RELATIVE_RECOIL', 0, 1, 3, 'POKEMON_DAMAGE_PREVENTABLE']],
    struggle: [['POKEMON_EFFECT_DAMAGE_RELATIVE', 'POKEMON_EFFECT_PHASE_AFTER_MOVE', 'POKEMON_EFFECT_TARGET_USER', 100, 'POKEMON_DAMAGE_RELATIVE_RECOIL', 0, 1, 4, 'POKEMON_DAMAGE_UNPREVENTABLE']],
    taunt: [['POKEMON_EFFECT_ADD_VOLATILE', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_MOVE_TARGET', 100, 'POKEMON_VOLATILE_TAUNT', 0]],
    torment: [['POKEMON_EFFECT_ADD_VOLATILE', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_MOVE_TARGET', 100, 'POKEMON_VOLATILE_TORMENT', 0]],
    disable: [['POKEMON_EFFECT_ADD_VOLATILE', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_MOVE_TARGET', 100, 'POKEMON_VOLATILE_DISABLE', 0]],
    encore: [['POKEMON_EFFECT_ADD_VOLATILE', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_MOVE_TARGET', 100, 'POKEMON_VOLATILE_ENCORE', 0]],
    substitute: [['POKEMON_EFFECT_CREATE_SUBSTITUTE', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_USER', 100, 0, 0]],
    magiccoat: [['POKEMON_EFFECT_ADD_TIMED_VOLATILE', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_USER', 100, 'POKEMON_VOLATILE_MAGIC_COAT', 0]],
    mirrormove: [['POKEMON_EFFECT_CALL_LAST_ATTACK_MOVE', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_USER', 100, 0, 0]],
    snatch: [['POKEMON_EFFECT_ADD_TIMED_VOLATILE', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_USER', 100, 'POKEMON_VOLATILE_SNATCH', 0]],
    howl: [['POKEMON_EFFECT_BOOST', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_USER', 100, 'POKEMON_STAT_ATK', 1]],
    calmmind: [
      ['POKEMON_EFFECT_BOOST', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_USER', 100, 'POKEMON_STAT_SPA', 1],
      ['POKEMON_EFFECT_BOOST', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_USER', 100, 'POKEMON_STAT_SPD', 1],
    ],
    tickle: [
      ['POKEMON_EFFECT_BOOST', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_MOVE_TARGET', 100, 'POKEMON_STAT_ATK', -1],
      ['POKEMON_EFFECT_BOOST', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_MOVE_TARGET', 100, 'POKEMON_STAT_DEF', -1],
    ],
    confuseray: [['POKEMON_EFFECT_ADD_VOLATILE', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_MOVE_TARGET', 100, 'POKEMON_VOLATILE_CONFUSION', 0]],
    supersonic: [['POKEMON_EFFECT_ADD_VOLATILE', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_MOVE_TARGET', 100, 'POKEMON_VOLATILE_CONFUSION', 0]],
    sweetkiss: [['POKEMON_EFFECT_ADD_VOLATILE', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_MOVE_TARGET', 100, 'POKEMON_VOLATILE_CONFUSION', 0]],
    flatter: [
      ['POKEMON_EFFECT_BOOST', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_MOVE_TARGET', 100, 'POKEMON_STAT_SPA', 1],
      ['POKEMON_EFFECT_ADD_VOLATILE', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_MOVE_TARGET', 100, 'POKEMON_VOLATILE_CONFUSION', 0],
    ],
    swagger: [
      ['POKEMON_EFFECT_BOOST', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_MOVE_TARGET', 100, 'POKEMON_STAT_ATK', 2],
      ['POKEMON_EFFECT_ADD_VOLATILE', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_MOVE_TARGET', 100, 'POKEMON_VOLATILE_CONFUSION', 0],
    ],
    teeterdance: [['POKEMON_EFFECT_ADD_VOLATILE', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_MOVE_TARGET', 100, 'POKEMON_VOLATILE_CONFUSION', 0]],
    /* Showdown models these as `self.volatileStatus`: the self hit runs inside
     * spreadMoveHit, before secondaries and that hit's Update event.
     * AFTER_HIT_CALLBACK is the guaranteed (no chance draw) native phase with
     * that ownership; AFTER_MOVE is recoil-like work after the hit loop. */
    outrage: [['POKEMON_EFFECT_ADD_VOLATILE', 'POKEMON_EFFECT_PHASE_AFTER_HIT_CALLBACK', 'POKEMON_EFFECT_TARGET_USER', 100, 'POKEMON_VOLATILE_LOCKED_MOVE', 0]],
    petaldance: [['POKEMON_EFFECT_ADD_VOLATILE', 'POKEMON_EFFECT_PHASE_AFTER_HIT_CALLBACK', 'POKEMON_EFFECT_TARGET_USER', 100, 'POKEMON_VOLATILE_LOCKED_MOVE', 0]],
    thrash: [['POKEMON_EFFECT_ADD_VOLATILE', 'POKEMON_EFFECT_PHASE_AFTER_HIT_CALLBACK', 'POKEMON_EFFECT_TARGET_USER', 100, 'POKEMON_VOLATILE_LOCKED_MOVE', 0]],
    recycle: [['POKEMON_EFFECT_RECYCLE_ITEM', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_USER', 100, 0, 0]],
    thief: [['POKEMON_EFFECT_STEAL_ITEM', 'POKEMON_EFFECT_PHASE_AFTER_HIT', 'POKEMON_EFFECT_TARGET_MOVE_TARGET', 100, 0, 0]],
    covet: [['POKEMON_EFFECT_STEAL_ITEM', 'POKEMON_EFFECT_PHASE_AFTER_HIT', 'POKEMON_EFFECT_TARGET_MOVE_TARGET', 100, 0, 0]],
    knockoff: [['POKEMON_EFFECT_KNOCK_OFF_ITEM', 'POKEMON_EFFECT_PHASE_AFTER_HIT', 'POKEMON_EFFECT_TARGET_MOVE_TARGET', 100, 0, 0]],
    trick: [['POKEMON_EFFECT_SWAP_ITEMS', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_MOVE_TARGET', 100, 0, 0]],
    focusenergy: [['POKEMON_EFFECT_ADD_VOLATILE', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_USER', 100, 'POKEMON_VOLATILE_FOCUS_ENERGY', 0]],
    lockon: [['POKEMON_EFFECT_ADD_SOURCE_BOUND_VOLATILE', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_USER', 100, 'POKEMON_VOLATILE_LOCK_ON', 0]],
    mindreader: [['POKEMON_EFFECT_ADD_SOURCE_BOUND_VOLATILE', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_USER', 100, 'POKEMON_VOLATILE_LOCK_ON', 0]],
    ingrain: [['POKEMON_EFFECT_ADD_VOLATILE', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_USER', 100, 'POKEMON_VOLATILE_INGRAIN', 0]],
    charge: [['POKEMON_EFFECT_ADD_VOLATILE', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_USER', 100, 'POKEMON_VOLATILE_CHARGE', 0]],
    stockpile: [['POKEMON_EFFECT_ADD_VOLATILE', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_USER', 100, 'POKEMON_VOLATILE_STOCKPILE', 0]],
    leechseed: [['POKEMON_EFFECT_ADD_VOLATILE', 'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_MOVE_TARGET', 100, 'POKEMON_VOLATILE_LEECH_SEED', 0]],
	/* `self.volatileStatus` is installed only after Rage connects. */
	rage: [['POKEMON_EFFECT_ADD_VOLATILE', 'POKEMON_EFFECT_PHASE_AFTER_HIT_CALLBACK', 'POKEMON_EFFECT_TARGET_USER', 100, 'POKEMON_VOLATILE_RAGE', 0]],
    curse: [
      ['POKEMON_EFFECT_ADD_VOLATILE', 'POKEMON_EFFECT_PHASE_PRIMARY',
        'POKEMON_EFFECT_TARGET_MOVE_TARGET', 100, 'POKEMON_VOLATILE_CURSE', 0],
      ['POKEMON_EFFECT_BOOST', 'POKEMON_EFFECT_PHASE_SELF_DROP',
        'POKEMON_EFFECT_TARGET_USER', 100, 'POKEMON_STAT_ATK', 1],
      ['POKEMON_EFFECT_BOOST', 'POKEMON_EFFECT_PHASE_SELF_DROP',
        'POKEMON_EFFECT_TARGET_USER', 100, 'POKEMON_STAT_DEF', 1],
      ['POKEMON_EFFECT_BOOST', 'POKEMON_EFFECT_PHASE_SELF_DROP',
        'POKEMON_EFFECT_TARGET_USER', 100, 'POKEMON_STAT_SPE', -1],
    ],
  };
  const effectGroupSpecs = {};
  effectSpecs.bounce = [['POKEMON_EFFECT_SET_STATUS',
    'POKEMON_EFFECT_PHASE_AFTER_HIT', 'POKEMON_EFFECT_TARGET_MOVE_TARGET',
    30, 'POKEMON_STATUS_PARALYSIS', 0]];
  effectSpecs.skyattack = [['POKEMON_EFFECT_ADD_VOLATILE',
    'POKEMON_EFFECT_PHASE_AFTER_HIT', 'POKEMON_EFFECT_TARGET_MOVE_TARGET',
    30, 'POKEMON_VOLATILE_FLINCH', 0]];
  for (const id of ['hyperbeam', 'blastburn', 'frenzyplant', 'hydrocannon']) {
    const move = dex.moves.get(id);
    if (!move.exists || move.gen > 3 || !move.basePower ||
        !move.flags?.recharge || move.self?.volatileStatus !== 'mustrecharge') {
      throw new Error(`resolved Gen 3 recharge producer changed: ${id}`);
    }
    effectSpecs[id] = [['POKEMON_EFFECT_ADD_VOLATILE',
      'POKEMON_EFFECT_PHASE_AFTER_MOVE', 'POKEMON_EFFECT_TARGET_USER', 100,
      'POKEMON_VOLATILE_MUST_RECHARGE', 0]];
  }
  {
    const rapidSpin = dex.moves.get('rapidspin');
    const afterHit = String(rapidSpin.onAfterHit);
    const afterSubDamage = String(rapidSpin.onAfterSubDamage);
    if (!rapidSpin.exists || rapidSpin.gen > 3 || rapidSpin.basePower !== 20 ||
        typeof rapidSpin.onAfterHit !== 'function' ||
        typeof rapidSpin.onAfterSubDamage !== 'function' ||
        !/removeVolatile\(["']partiallytrapped["']\)/.test(afterHit) ||
        !/removeVolatile\(["']partiallytrapped["']\)/.test(afterSubDamage)) {
      throw new Error('resolved Gen 3 Rapid Spin cleanup changed');
    }
    effectSpecs.rapidspin = [
      ['POKEMON_EFFECT_REMOVE_VOLATILE',
       'POKEMON_EFFECT_PHASE_AFTER_HIT_CALLBACK', 'POKEMON_EFFECT_TARGET_USER', 100,
       'POKEMON_VOLATILE_LEECH_SEED', 0],
      ['POKEMON_EFFECT_REMOVE_SIDE_CONDITION',
       'POKEMON_EFFECT_PHASE_AFTER_HIT_CALLBACK', 'POKEMON_EFFECT_TARGET_USER', 100,
       'POKEMON_GEN3_CONDITION_SIDE_SPIKES', 0],
      ['POKEMON_EFFECT_REMOVE_VOLATILE',
      'POKEMON_EFFECT_PHASE_AFTER_HIT_CALLBACK', 'POKEMON_EFFECT_TARGET_USER', 100,
      'POKEMON_VOLATILE_PARTIALLY_TRAPPED', 0],
    ];
  }
  for (const id of ['bind', 'clamp', 'firespin', 'whirlpool', 'wrap', 'sandtomb']) {
    const move = dex.moves.get(id);
    if (!move.exists || move.gen > 3 || !move.basePower ||
        move.volatileStatus !== 'partiallytrapped' ||
        typeof move.onTry === 'function' || typeof move.onTryMove === 'function') {
      throw new Error(`resolved Gen 3 partial-trapping move changed: ${id}`);
    }
    effectSpecs[id] = [['POKEMON_EFFECT_ADD_VOLATILE',
      'POKEMON_EFFECT_PHASE_PRIMARY_HIT', 'POKEMON_EFFECT_TARGET_MOVE_TARGET', 100,
      'POKEMON_VOLATILE_PARTIALLY_TRAPPED', 0]];
  }
  for (const id of FLINCH_SECONDARY_MOVES) {
    const move = dex.moves.get(id);
    const secondary = move.secondary;
    const isSnore = id === 'snore';
    const trySource = String(move.onTry);
    if (!move.exists || move.gen > 3 ||
        (isSnore ? (typeof move.onTry !== 'function' ||
          !trySource.includes('source.status === "slp"')) :
          typeof move.onTry === 'function') ||
        typeof move.onTryMove === 'function' || move.secondaries?.length !== 1 ||
        !secondary || secondary.volatileStatus !== 'flinch' ||
        !Number.isInteger(secondary.chance) ||
        (isSnore && move.sleepUsable !== true)) {
      throw new Error(`invalid ordinary flinch secondary: ${id}`);
    }
    effectSpecs[id] = [[
      'POKEMON_EFFECT_ADD_VOLATILE', 'POKEMON_EFFECT_PHASE_AFTER_HIT',
      'POKEMON_EFFECT_TARGET_MOVE_TARGET', secondary.chance,
      'POKEMON_VOLATILE_FLINCH', 0,
    ]];
  }
  {
    const move = dex.moves.get('fakeout');
    const secondary = move.secondary;
    const callback = String(move.onTry);
    if (typeof move.onTry !== 'function' ||
        !callback.includes('source.activeMoveActions > 1') ||
        move.priority !== 1 || !secondary || secondary.chance !== 100 ||
        secondary.volatileStatus !== 'flinch') {
      throw new Error('resolved Gen 3 Fake Out shape changed');
    }
    effectSpecs.fakeout = [['POKEMON_EFFECT_ADD_VOLATILE',
      'POKEMON_EFFECT_PHASE_AFTER_HIT', 'POKEMON_EFFECT_TARGET_MOVE_TARGET',
      100, 'POKEMON_VOLATILE_FLINCH', 0]];
  }
  {
    const returnMove = dex.moves.get('return');
    const frustration = dex.moves.get('frustration');
    if (!String(returnMove.basePowerCallback).includes('pokemon.happiness * 10') ||
        !String(returnMove.basePowerCallback).includes('/ 25') ||
        !String(frustration.basePowerCallback).includes('255 - pokemon.happiness') ||
        !String(frustration.basePowerCallback).includes('/ 25')) {
      throw new Error('resolved happiness power callbacks changed');
    }
  }
  {
    const helpingHand = dex.moves.get('helpinghand');
    if (helpingHand.target !== 'adjacentAlly' ||
        typeof helpingHand.onTryHit !== 'function') {
      throw new Error('resolved Gen 3 Helping Hand reachability shape changed');
    }
    const toxic = dex.moves.get('toxic');
    const toxicCallbacks = [toxic.onTry, toxic.onTryHit, toxic.onHit,
      toxic.onPrepareHit].filter(callback => typeof callback === 'function')
      .map(String).join('\n');
    if (!toxic.condition?.onSourceAccuracy ||
        !toxic.condition?.onSourceInvulnerability ||
        toxic.onPrepareHit !== undefined || toxic.volatileStatus !== undefined ||
        /addVolatile\(["']toxic["']/.test(toxicCallbacks)) {
      throw new Error('resolved Gen 3 orphaned Toxic condition shape changed');
    }
    const splash = dex.moves.get('splash');
    if (!/getPseudoWeather\(["']Gravity["']\)/.test(String(splash.onTry)) ||
        !/["']-nothing["']/.test(String(splash.onTryHit))) {
      throw new Error('resolved Gen 3 Splash callback shape changed');
    }
    const gravityReachable = dex.moves.all().some(move => move.gen <= 3 &&
      (move.pseudoWeather === 'gravity' ||
       Object.values(move).some(value => typeof value === 'function' &&
         String(value).includes("addPseudoWeather('gravity'"))));
    if (gravityReachable) throw new Error('Gravity became reachable in Gen 3');
    const payDay = dex.moves.get('payday');
    if (payDay.basePower !== 40 || payDay.type !== 'Normal' ||
        payDay.category !== 'Physical' || typeof payDay.onHit !== 'function' ||
        !/["']-fieldactivate["']/.test(String(payDay.onHit))) {
      throw new Error('resolved Gen 3 Pay Day shape changed');
    }
  }
  /* Unconditional primary boosts are one sparse product in Showdown. Keep
   * their generated operations adjacent so the generic runtime normalizes
   * the complete product before ChangeBoost/TryBoost. Descriptor fields
   * (target, accuracy:true, PP, flags, bypasssub) remain on PokemonMoveData. */
  const directBoostMoves = new Set([
    'acidarmor', 'agility', 'amnesia', 'barrier', 'bulkup', 'calmmind',
    'charm', 'cosmicpower', 'cottonspore', 'dragondance', 'faketears',
    'featherdance', 'flash', 'growl', 'growth', 'harden', 'howl',
    'irondefense', 'kinesis', 'leer', 'meditate', 'metalsound',
	'doubleteam', 'memento', 'sandattack', 'scaryface', 'screech', 'sharpen', 'smokescreen', 'defensecurl',
	'minimize', 'stringshot', 'sweetscent', 'swordsdance', 'tailglow', 'tailwhip',
    'tickle', 'withdraw',
  ]);
  for (const id of directBoostMoves) {
    const move = dex.moves.get(id);
    if (!move.exists || move.gen > 3 || !move.boosts ||
        Object.keys(move.boosts).length === 0) {
      throw new Error(`invalid direct-boost move: ${id}`);
    }
    const target = move.target === 'self' ?
      'POKEMON_EFFECT_TARGET_USER' : 'POKEMON_EFFECT_TARGET_MOVE_TARGET';
    effectSpecs[id] = Object.entries(move.boosts).map(([stat, delta]) => {
      const statToken = {
        atk: 'POKEMON_STAT_ATK', def: 'POKEMON_STAT_DEF',
        spa: 'POKEMON_STAT_SPA', spd: 'POKEMON_STAT_SPD',
        spe: 'POKEMON_STAT_SPE', accuracy: 'POKEMON_STAT_ACCURACY',
        evasion: 'POKEMON_STAT_EVASION',
      }[stat];
      if (!statToken || !Number.isInteger(delta) || delta < -6 || delta > 6) {
        throw new Error(`invalid boost product on ${id}: ${stat} ${delta}`);
      }
      return ['POKEMON_EFFECT_BOOST', 'POKEMON_EFFECT_PHASE_PRIMARY',
        target, 100, statToken, delta];
    });
  }
	{
		const move = dex.moves.get('defensecurl');
		if (move.target !== 'self' || move.accuracy !== true ||
			move.boosts?.def !== 1 || move.volatileStatus !== 'defensecurl' ||
			typeof move.condition?.onRestart !== 'function' ||
			String(move.condition.onRestart) !== '() => null') {
			throw new Error('resolved Gen 3 Defense Curl marker changed');
		}
		effectSpecs.defensecurl.push([
			'POKEMON_EFFECT_ADD_VOLATILE', 'POKEMON_EFFECT_PHASE_PRIMARY',
			'POKEMON_EFFECT_TARGET_USER', 100,
			'POKEMON_VOLATILE_DEFENSE_CURL', 0,
		]);
	}
	{
		const move = dex.moves.get('minimize');
		if (move.target !== 'self' || move.accuracy !== true ||
			move.boosts?.evasion !== 1 || move.volatileStatus !== 'minimize' ||
			!move.condition?.noCopy || move.condition.onAccuracy !== undefined ||
			typeof move.condition?.onRestart !== 'function' ||
			String(move.condition.onRestart) !== '() => null' ||
			typeof move.condition?.onSourceModifyDamage !== 'function') {
			throw new Error('resolved Gen 3 Minimize marker changed');
		}
		effectSpecs.minimize.push([
			'POKEMON_EFFECT_ADD_VOLATILE', 'POKEMON_EFFECT_PHASE_PRIMARY',
			'POKEMON_EFFECT_TARGET_USER', 100,
			'POKEMON_VOLATILE_MINIMIZE', 0,
		]);
	}
  for (const id of ['overheat', 'psychoboost', 'superpower']) {
    const move = dex.moves.get(id);
    const entries = Object.entries(move.self?.boosts || {});
    const selfDropStatTokens = {
      atk: 'POKEMON_STAT_ATK', def: 'POKEMON_STAT_DEF',
      spa: 'POKEMON_STAT_SPA', spd: 'POKEMON_STAT_SPD',
      spe: 'POKEMON_STAT_SPE', accuracy: 'POKEMON_STAT_ACCURACY',
      evasion: 'POKEMON_STAT_EVASION',
    };
    const callbacks = Object.keys(move).filter(key =>
      key.startsWith('on') && typeof move[key] === 'function');
    if (!move.exists || move.gen > 3 || !move.basePower ||
        typeof move.accuracy !== 'number' || move.target !== 'normal' ||
        callbacks.length !== 0 || entries.length === 0 || move.multihit ||
        move.secondary || move.secondaries?.length) {
      throw new Error(`invalid post-hit self-drop move: ${id}`);
    }
    effectSpecs[id] = entries.map(([stat, delta]) => {
      const statToken = selfDropStatTokens[stat];
      if (!statToken || !Number.isInteger(delta) || delta >= 0 || delta < -6) {
        throw new Error(`invalid self-drop product on ${id}: ${stat} ${delta}`);
      }
      return ['POKEMON_EFFECT_BOOST', 'POKEMON_EFFECT_PHASE_SELF_DROP',
        'POKEMON_EFFECT_TARGET_USER', 100, statToken, delta];
    });
  }
  for (const id of DIRECT_HEAL_MOVES) {
    const move = dex.moves.get(id);
    const callbacks = Object.keys(move).filter(key =>
      key.startsWith('on') && typeof move[key] === 'function');
    if (!move.exists || move.gen > 3 || move.target !== 'self' ||
        move.category !== 'Status' || move.basePower !== 0 ||
        move.accuracy !== true || callbacks.length !== 0 ||
        !Array.isArray(move.heal) || move.heal.length !== 2 ||
        move.heal[0] !== 1 || move.heal[1] !== 2) {
      throw new Error(`invalid callback-free direct heal: ${id}`);
    }
    effectSpecs[id] = [['POKEMON_EFFECT_HEAL_FRACTION',
      'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_USER',
      100, 0, 0, move.heal[0], move.heal[1]]];
  }
  for (const id of WEATHER_HEAL_MOVES) {
    const move = dex.moves.get(id);
    const callbacks = Object.keys(move).filter(key =>
      key.startsWith('on') && typeof move[key] === 'function');
    if (!move.exists || move.gen > 3 || move.target !== 'self' ||
        move.category !== 'Status' || move.accuracy !== true ||
        callbacks.length !== 1 || callbacks[0] !== 'onHit' ||
        !move.flags.snatch || !move.flags.heal) {
      throw new Error(`invalid weather recovery move: ${id}`);
    }
    effectSpecs[id] = [['POKEMON_EFFECT_HEAL_WEATHER_FRACTION',
      'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_USER',
      100, 0, 0, 1, 2]];
  }
  for (const id of DRAIN_MOVES) {
    const move = dex.moves.get(id);
    const callbacks = Object.keys(move).filter(key =>
      key.startsWith('on') && typeof move[key] === 'function');
    if (!move.basePower || move.accuracy !== 100 || move.target !== 'normal' ||
        (id === 'dreameater' ?
          callbacks.length !== 1 || callbacks[0] !== 'onTryImmunity' :
          callbacks.length !== 0) || move.drain?.[0] !== 1 ||
        move.drain?.[1] !== 2 || move.recoil || move.multihit ||
        move.secondary || move.secondaries?.length || move.selfSwitch) {
      throw new Error(`invalid generated half-drain move: ${id}`);
    }
    effectSpecs[id] = [['POKEMON_EFFECT_DAMAGE_RELATIVE',
      'POKEMON_EFFECT_PHASE_AFTER_DAMAGE', 'POKEMON_EFFECT_TARGET_USER',
      100, 'POKEMON_DAMAGE_RELATIVE_DRAIN', 0, 1, 2]];
  }
  const statusTokens = {
    brn: 'POKEMON_STATUS_BURN', frz: 'POKEMON_STATUS_FREEZE',
    par: 'POKEMON_STATUS_PARALYSIS', psn: 'POKEMON_STATUS_POISON',
    tox: 'POKEMON_STATUS_TOXIC',
  };
  const statTokens = {
    atk: 'POKEMON_STAT_ATK', def: 'POKEMON_STAT_DEF',
    spa: 'POKEMON_STAT_SPA', spd: 'POKEMON_STAT_SPD',
    spe: 'POKEMON_STAT_SPE', accuracy: 'POKEMON_STAT_ACCURACY',
    evasion: 'POKEMON_STAT_EVASION',
  };
  for (const id of STATUS_SECONDARY_MOVES) {
    const move = dex.moves.get(id);
    const secondary = move.secondary;
    const callbacks = Object.keys(move).filter(key =>
      key.startsWith('on') && typeof move[key] === 'function');
    const secondaryKeys = Object.keys(secondary || {}).sort().join(',');
    const permittedModifyMove = id === 'thunder' || id === 'secretpower' ||
      id === 'present';
    if (!move.basePower || (permittedModifyMove ?
        callbacks.join(',') !== 'onModifyMove' : callbacks.length !== 0) ||
        (move.secondaries && move.secondaries.length !== 1) ||
        !secondary || !Number.isInteger(secondary.chance) ||
        secondary.chance < 1 || secondary.chance > 100 ||
        secondaryKeys !== 'chance,status' ||
        !statusTokens[secondary.status] || secondary.self || secondary.boosts ||
        (move.multihit && id !== 'twineedle') || move.recoil || move.drain ||
        move.selfSwitch) {
      throw new Error(`invalid status secondary move: ${id}`);
    }
    if (id === 'twineedle' &&
        (move.multihit !== 2 || move.basePower !== 25 ||
         move.accuracy !== 100 || secondary.chance !== 20 ||
         secondary.status !== 'psn')) {
      throw new Error('resolved Gen 3 Twineedle per-hit shape changed');
    }
    if (id === 'secretpower' &&
        (move.basePower !== 70 || move.accuracy !== 100 ||
         secondary.chance !== 30 || secondary.status !== 'par' ||
         !String(move.onModifyMove).includes('this.field.isTerrain("")'))) {
      throw new Error('resolved Gen 3 Secret Power terrain-free shape changed');
    }
    effectSpecs[id] = [['POKEMON_EFFECT_SET_STATUS',
      'POKEMON_EFFECT_PHASE_AFTER_HIT', 'POKEMON_EFFECT_TARGET_MOVE_TARGET',
      secondary.chance, statusTokens[secondary.status], 0]];
  }
  {
    const move = dex.moves.get('triattack');
    const secondary = move.secondary;
    const hit = String(secondary?.onHit);
    if (move.basePower !== 80 || move.accuracy !== 100 ||
        move.category !== 'Physical' || move.type !== 'Normal' ||
        move.target !== 'normal' || !secondary || secondary.chance !== 20 ||
        Object.keys(secondary).sort().join(',') !== 'chance,onHit' ||
        !/this\.sample\(\[["']brn["'], ["']par["'], ["']frz["']\]\)/.test(hit) ||
        !/target\.trySetStatus\(status, source\)/.test(hit)) {
      throw new Error('resolved Gen 3 Tri Attack sampled-status shape changed');
    }
    effectSpecs.triattack = [[
      'POKEMON_EFFECT_SET_STATUS_FROM_DISTRIBUTION',
      'POKEMON_EFFECT_PHASE_AFTER_HIT', 'POKEMON_EFFECT_TARGET_MOVE_TARGET',
      secondary.chance, 1, 0,
    ]];
  }
  for (const id of BOOST_SECONDARY_MOVES) {
    const move = dex.moves.get(id);
    const secondary = move.secondary;
    const callbacks = Object.keys(move).filter(key =>
      key.startsWith('on') && typeof move[key] === 'function');
    const boosts = secondary?.self?.boosts || secondary?.boosts;
    const entries = Object.entries(boosts || {});
    const secondaryKeys = Object.keys(secondary || {}).sort().join(',');
    const expectedSecondaryKeys = secondary?.self ? 'chance,self' : 'boosts,chance';
    const selfKeys = Object.keys(secondary?.self || {}).sort().join(',');
    if (!move.basePower || callbacks.length !== 0 ||
        (move.secondaries && move.secondaries.length !== 1) ||
        !secondary || !Number.isInteger(secondary.chance) ||
        secondary.chance < 1 || secondary.chance > 100 ||
        secondaryKeys !== expectedSecondaryKeys ||
        (secondary.self && selfKeys !== 'boosts') ||
        secondary.status || entries.length !== 1 || move.multihit ||
        move.recoil || move.drain || move.selfSwitch) {
      throw new Error(`invalid callback-free single-stat secondary: ${id}`);
    }
    const [stat, delta] = entries[0];
    if (!statTokens[stat] || !Number.isInteger(delta) || delta < -6 || delta > 6) {
      throw new Error(`invalid secondary boost product on ${id}: ${stat} ${delta}`);
    }
    effectSpecs[id] = [['POKEMON_EFFECT_BOOST',
      'POKEMON_EFFECT_PHASE_AFTER_HIT', secondary.self ?
        'POKEMON_EFFECT_TARGET_USER' : 'POKEMON_EFFECT_TARGET_MOVE_TARGET',
      secondary.chance, statTokens[stat], delta]];
  }
  for (const id of ['ancientpower', 'silverwind']) {
    const move = dex.moves.get(id);
    const secondary = move.secondary;
    const callbacks = Object.keys(move).filter(key =>
      key.startsWith('on') && typeof move[key] === 'function');
    const boosts = secondary?.self?.boosts;
    const entries = Object.entries(boosts || {});
    const expectedStats = ['atk', 'def', 'spa', 'spd', 'spe'];
    if (!move.basePower || callbacks.length !== 0 || move.multihit ||
        move.recoil || move.drain || move.selfSwitch ||
        (move.secondaries && move.secondaries.length !== 1) ||
        !secondary || secondary.chance !== 10 ||
        Object.keys(secondary).sort().join(',') !== 'chance,self' ||
        Object.keys(secondary.self || {}).join(',') !== 'boosts' ||
        entries.length !== expectedStats.length ||
        entries.some(([stat, delta], index) =>
          stat !== expectedStats[index] || delta !== 1)) {
      throw new Error(`invalid grouped self-secondary: ${id}`);
    }
    effectSpecs[id] = entries.map(([stat, delta]) => [
      'POKEMON_EFFECT_BOOST', 'POKEMON_EFFECT_PHASE_AFTER_HIT',
      'POKEMON_EFFECT_TARGET_USER', secondary.chance, statTokens[stat], delta,
    ]);
    effectGroupSpecs[id] = entries.map(() => 1);
  }
  for (const id of CONFUSION_SECONDARY_MOVES) {
    const move = dex.moves.get(id);
    const secondary = move.secondary;
    const callbacks = Object.keys(move).filter(key =>
      key.startsWith('on') && typeof move[key] === 'function');
    const secondaryKeys = Object.keys(secondary || {}).sort().join(',');
    if (!move.basePower || callbacks.length !== 0 || move.multihit ||
        move.recoil || move.drain || move.selfSwitch ||
        (move.secondaries && move.secondaries.length !== 1) ||
        !secondary || secondaryKeys !== 'chance,volatileStatus' ||
        secondary.volatileStatus !== 'confusion' ||
        !Number.isInteger(secondary.chance) || secondary.chance < 1 ||
        secondary.chance > 100) {
      throw new Error(`invalid callback-free confusion secondary: ${id}`);
    }
    effectSpecs[id] = [['POKEMON_EFFECT_ADD_VOLATILE',
      'POKEMON_EFFECT_PHASE_AFTER_HIT', 'POKEMON_EFFECT_TARGET_MOVE_TARGET',
      secondary.chance, 'POKEMON_VOLATILE_CONFUSION', 0]];
  }
  for (const id of ['roar', 'whirlwind']) {
    effectSpecs[id] = [['POKEMON_EFFECT_FORCE_SWITCH',
      'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_MOVE_TARGET',
      100, 0, 0]];
  }
  for (const id of ['foresight', 'odorsleuth']) {
    const move = dex.moves.get(id);
    if (move.accuracy !== 100 || move.basePower !== 0 ||
        move.category !== 'Status' || move.target !== 'normal' ||
        move.volatileStatus !== 'foresight' ||
        typeof move.onTryHit !== 'function' ||
        !/target\.volatiles\[["']miracleeye["']\]/.test(String(move.onTryHit))) {
      throw new Error(`resolved Gen 3 ${id} shape changed`);
    }
    effectSpecs[id] = [['POKEMON_EFFECT_ADD_VOLATILE',
      'POKEMON_EFFECT_PHASE_PRIMARY', 'POKEMON_EFFECT_TARGET_MOVE_TARGET',
      100, 'POKEMON_VOLATILE_FORESIGHT', 0]];
  }
  {
    const move = dex.moves.get('ingrain');
    const condition = move.condition;
    if (move.accuracy !== true || move.target !== 'self' ||
        move.volatileStatus !== 'ingrain' ||
        typeof condition?.onStart !== 'function' ||
        typeof condition?.onResidual !== 'function' ||
        condition.onResidualOrder !== 10 || condition.onResidualSubOrder !== 1 ||
        typeof condition?.onTrapPokemon !== 'function' ||
        typeof condition?.onDragOut !== 'function' ||
        !/pokemon\.baseMaxhp\s*\/\s*16/.test(String(condition.onResidual)) ||
        !String(condition.onDragOut).includes('return null')) {
      throw new Error('resolved Gen 3 Ingrain shape changed');
    }
  }
  {
    const move = dex.moves.get('curse');
    const modify = String(move.onModifyMove);
    const tryHit = String(move.onTryHit);
    const hit = String(move.onHit);
    const residual = String(move.condition?.onResidual);
    if (!move.exists || move.gen > 3 || move.accuracy !== true ||
        move.basePower !== 0 || move.category !== 'Status' ||
        move.target !== 'normal' || move.nonGhostTarget !== 'self' ||
        move.type !== '???' || move.volatileStatus !== 'curse' ||
        Object.keys(move.flags || {}).sort().join(',') !== 'metronome' ||
        !/!source\.hasType\(["']Ghost["']\)/.test(modify) ||
        !/delete move\.volatileStatus/.test(modify) ||
        !/delete move\.onHit/.test(modify) ||
        !/target\?\.volatiles\[["']substitute["']\]/.test(modify) ||
        !/target\.volatiles\[["']curse["']\]/.test(tryHit) ||
        !/return false/.test(tryHit) ||
        !/directDamage\(source\.maxhp \/ 2/.test(hit) ||
        move.condition?.onResidualOrder !== 10 ||
        move.condition?.onResidualSubOrder !== 8 ||
        !/pokemon\.baseMaxhp \/ 4/.test(residual)) {
      throw new Error('resolved Gen 3 Curse profile/lifecycle changed');
    }
  }
  const effectOffsets = new Map();
  const effects = [];
  const effectSecondaryGroups = [];
  for (const id of MOVES) {
    const specs = effectSpecs[id] || [];
    const groups = effectGroupSpecs[id] || specs.map(() => 0);
    if (groups.length !== specs.length) {
      throw new Error(`secondary group shape mismatch: ${id}`);
    }
    effectOffsets.set(id, effects.length);
    effects.push(...specs);
    effectSecondaryGroups.push(...groups);
  }
  lines.push('};', '', 'static const PokemonEffectOp EFFECTS[] = {');
  for (const [kind, phase, target, chance, argument, amount, numerator = 0,
    denominator = 0, preventability = 'POKEMON_DAMAGE_PREVENTABILITY_NONE'] of effects) {
    lines.push(`    {${kind}, ${phase}, ${target}, ${chance}, ${argument}, ${amount}, ${numerator}, ${denominator}, ${preventability}},`);
  }
  lines.push('};', '', 'static const uint8_t EFFECT_SECONDARY_GROUPS[] = {');
  for (const group of effectSecondaryGroups) lines.push(`    ${group},`);
  const curseEffectOffset = effectOffsets.get('curse');
  lines.push('};', '', 'static const PokemonMoveInvocationProfile MOVE_INVOCATION_PROFILES[] = {',
    `    {1, POKEMON_GEN3_MOVE_CURSE, POKEMON_TARGET_NORMAL, ${curseEffectOffset}, 1, 1},`,
    `    {2, POKEMON_GEN3_MOVE_CURSE, POKEMON_TARGET_SELF, ${curseEffectOffset + 1}, 3, 2},`,
    '};', '', 'static const PokemonMoveProfileSelection MOVE_PROFILE_SELECTIONS[] = {',
    '    {1, UINT32_C(1) << POKEMON_GEN3_TYPE_GHOST, 1, 2},',
    '};');
  lines.push('', 'static const PokemonMoveData MOVES[] = {');
  for (const id of MOVES) {
    const move = id === 'recharge' ? {
      exists: true, gen: 3, id: 'recharge', name: 'Recharge', type: 'Normal',
      category: 'Status', basePower: 0, accuracy: true, priority: 0, pp: 1,
      target: 'self', flags: {},
    } : dex.moves.get(id);
    if (!move.exists || move.gen > 3) throw new Error(`move outside slice shape: ${id}`);
    if (id === 'bulkup' && (move.boosts?.atk !== 1 || move.boosts?.def !== 1)) {
      throw new Error('resolved Gen 3 Bulk Up boosts changed');
    }
    if (id === 'growl' && move.boosts?.atk !== -1) {
      throw new Error('resolved Gen 3 Growl boost changed');
    }
    if (id === 'swagger' &&
        (move.accuracy !== 90 || move.category !== 'Status' ||
         move.target !== 'normal' || move.boosts?.atk !== 2 ||
         move.volatileStatus !== 'confusion' || !move.flags?.metronome ||
         !move.flags?.protect || !move.flags?.reflectable)) {
      throw new Error('resolved Gen 3 Swagger product changed');
    }
    if (id === 'ember' && (move.secondary?.chance !== 10 || move.secondary?.status !== 'brn')) {
      throw new Error('resolved Gen 3 Ember secondary changed');
    }
    if (id === 'steelwing' &&
        (move.secondary?.chance !== 10 || move.secondary?.self?.boosts?.def !== 1)) {
      throw new Error('resolved Gen 3 Steel Wing secondary changed');
    }
    const ohkoKind = move.ohko === true ? 'POKEMON_OHKO_ANY' :
      typeof move.ohko === 'string' ? 'POKEMON_OHKO_EXCLUDED_TYPE' :
      'POKEMON_OHKO_NONE';
    const ohkoType = typeof move.ohko === 'string' ? typeID(move.ohko) : 0;
    if (['fissure', 'guillotine', 'horndrill', 'sheercold'].includes(id) &&
        (move.basePower !== 0 || move.accuracy !== 30 ||
         ohkoKind !== 'POKEMON_OHKO_ANY' || ohkoType !== 0 ||
         move.target !== 'normal')) {
      throw new Error(`resolved Gen 3 ${move.name} OHKO shape changed`);
    }
    if (id === 'bodyslam' &&
        (move.secondary?.chance !== 30 || move.secondary?.status !== 'par')) {
      throw new Error('resolved Gen 3 Body Slam secondary changed');
    }
    const recoilShape = {
      doubleedge: [120, 1, 3], submission: [80, 1, 4],
      takedown: [90, 1, 4], volttackle: [120, 1, 3],
    }[id];
    if (recoilShape &&
        (move.basePower !== recoilShape[0] || move.recoil?.[0] !== recoilShape[1] ||
         move.recoil?.[1] !== recoilShape[2] || move.target !== 'normal' ||
         move.multihit || move.secondary || move.secondaries?.length ||
         Object.keys(move).some(key => key.startsWith('on') &&
           typeof move[key] === 'function'))) {
      throw new Error(`resolved Gen 3 ${move.name} recoil shape changed`);
    }
    const expectedMultihit = id === 'bonerush' ? [2, 5] : MULTIHIT_MOVES.get(id);
    if (expectedMultihit) {
      const actualMultihit = Array.isArray(move.multihit) ? move.multihit :
        Number.isInteger(move.multihit) ? [move.multihit, move.multihit] : [0, 0];
      if (actualMultihit[0] !== expectedMultihit[0] ||
          actualMultihit[1] !== expectedMultihit[1] ||
          move.damage || move.damageCallback || move.basePowerCallback ||
          move.multiaccuracy || move.secondary || move.secondaries?.length) {
        throw new Error(`resolved Gen 3 ${move.name} multi-hit shape changed`);
      }
    }
    if ((id === 'seismictoss' || id === 'nightshade') &&
        (move.damage !== 'level' || move.accuracy !== 100)) {
      throw new Error(`resolved Gen 3 ${move.name} fixed damage changed`);
    }
    const literalDamage = id === 'sonicboom' ? 20 : id === 'dragonrage' ? 40 : 0;
    if (literalDamage &&
        (move.damage !== literalDamage || move.basePower !== 0 ||
         typeof move.accuracy !== 'number' || move.multihit ||
         move.damageCallback || move.basePowerCallback ||
         Object.keys(move).some(key => key.startsWith('on') &&
           typeof move[key] === 'function'))) {
      throw new Error(`resolved Gen 3 ${move.name} literal damage changed`);
    }
    if (id === 'superfang' &&
        (move.basePower !== 0 || move.accuracy !== 90 || move.type !== 'Normal' ||
         move.category !== 'Physical' || typeof move.damageCallback !== 'function')) {
      throw new Error('resolved Gen 3 Super Fang target-relative damage changed');
    }
    if (id === 'endeavor' &&
        (move.basePower !== 0 || move.accuracy !== 100 || move.type !== 'Normal' ||
         move.category !== 'Physical' || typeof move.damageCallback !== 'function' ||
         typeof move.onTry !== 'function' || typeof move.onTryImmunity !== 'function')) {
      throw new Error('resolved Gen 3 Endeavor target-relative damage changed');
    }
    if (id === 'psywave' &&
        (move.basePower !== 0 || move.accuracy !== 80 ||
         move.type !== 'Psychic' || move.category !== 'Special' ||
         typeof move.damageCallback !== 'function')) {
      throw new Error('resolved Gen 3 Psywave random damage changed');
    }
    if (id === 'counter' || id === 'mirrorcoat') {
      const accepted = id === 'counter' ? 'Physical' : 'Special';
      const startSource = String(move.condition?.onStart);
      const damageSource = String(move.condition?.onDamage);
      const trySource = String(move.onTry);
      if (move.target !== 'scripted' || move.accuracy !== 100 ||
          typeof move.beforeTurnCallback !== 'function' ||
          typeof move.damageCallback !== 'function' ||
          typeof move.onTry !== 'function' || move.condition?.duration !== 1 ||
          move.condition?.noCopy !== true ||
          typeof move.condition?.onStart !== 'function' ||
          typeof move.condition?.onDamage !== 'function' ||
          move.condition?.onDamagePriority !== -101 ||
          !startSource.includes('slot = null') ||
          !new RegExp(`effect\\.category === ["']${accepted}["']`).test(damageSource) ||
          !damageSource.includes('2 * damage') ||
          !trySource.includes('slot === null')) {
        throw new Error(`resolved Gen 3 ${move.name} retaliation shape changed`);
      }
    }
    if (id === 'hiddenpower') {
      const modifySource = String(move.onModifyMove);
      if (move.basePower !== 0 || move.accuracy !== 100 ||
          typeof move.basePowerCallback !== 'function' ||
          typeof move.onModifyMove !== 'function' ||
          !modifySource.includes('move.type = pokemon.hpType') ||
          !modifySource.includes('move.category =')) {
        throw new Error('resolved Gen 3 Hidden Power construction changed');
      }
    }
    if ((id === 'futuresight' || id === 'doomdesire') &&
        (typeof move.onTry !== 'function' || move.target !== 'normal' ||
         move.accuracy !== (id === 'futuresight' ? 90 : 85) ||
         move.basePower !== (id === 'futuresight' ? 80 : 120) ||
         move.category !== (id === 'futuresight' ? 'Special' : 'Physical') ||
         !/addSlotCondition\(target, ["']futuremove["']\)/.test(String(move.onTry)) ||
         !/type: ["']\?\?\?["']/.test(String(move.onTry)) ||
         !String(move.onTry).includes('willCrit: false'))) {
      throw new Error(`resolved Gen 3 ${move.name} delayed-slot shape changed`);
    }
    if ((id === 'roar' || id === 'whirlwind') &&
        (move.accuracy !== 100 || move.basePower !== 0 ||
         move.category !== 'Status' || move.target !== 'normal' ||
         move.forceSwitch !== true || move.priority !== -6 ||
         Object.keys(move).some(key => key.startsWith('on') &&
           typeof move[key] === 'function'))) {
      throw new Error(`resolved Gen 3 ${move.name} forced-switch shape changed`);
    }
    if (id === 'pursuit') {
      const before = String(move.beforeTurnCallback);
      const modify = String(move.onModifyMove);
      const intercept = String(move.condition?.onBeforeSwitchOut);
      if (move.basePower !== 40 || move.accuracy !== 100 ||
          move.target !== 'normal' || move.condition?.duration !== 1 ||
          typeof move.beforeTurnCallback !== 'function' ||
          typeof move.onModifyMove !== 'function' ||
          typeof move.condition?.onBeforeSwitchOut !== 'function' ||
          !/\[["']frz["'], ["']slp["']\]/.test(before) ||
          !/target\.addVolatile\(["']pursuit["']\)/.test(before) ||
          !modify.includes('move.accuracy = true') ||
          !intercept.includes('this.queue.cancelMove(source)') ||
          !intercept.includes('source.deductPP(move.id)') ||
          !intercept.includes('source.moveUsed(move, pokemon.position)') ||
          !intercept.includes('this.actions.useMove(move, source')) {
        throw new Error('resolved Gen 3 Pursuit interception shape changed');
      }
    }
    if (id === 'batonpass') {
      const hit = String(move.onHit);
      const selfHit = String(move.self?.onHit);
      if (move.accuracy !== true || move.basePower !== 0 ||
          move.category !== 'Status' || move.target !== 'self' ||
          move.selfSwitch !== 'copyvolatile' ||
          typeof move.onHit !== 'function' ||
          typeof move.self?.onHit !== 'function' ||
          !hit.includes('this.canSwitch(target.side)') ||
          !selfHit.includes('skipBeforeSwitchOutEventFlag = true')) {
        throw new Error('resolved Gen 3 Baton Pass switch shape changed');
      }
    }
    if (id === 'wish' &&
        (move.slotCondition !== 'Wish' || move.target !== 'self' ||
         move.accuracy !== true || move.condition?.duration !== 2 ||
         move.condition?.onResidualOrder !== 7 ||
         typeof move.condition?.onEnd !== 'function')) {
      throw new Error('resolved Gen 3 Wish delayed-slot shape changed');
    }
    if (id === 'hyperbeam') {
      const recharge = dex.conditions.get('mustrecharge');
      if (move.basePower !== 150 || move.accuracy !== 90 ||
          move.category !== 'Physical' || move.type !== 'Normal' ||
          !move.flags?.recharge || move.self?.volatileStatus !== 'mustrecharge' ||
          recharge.duration !== 2 || recharge.onLockMove !== 'recharge' ||
          typeof recharge.onBeforeMove !== 'function' ||
          recharge.onBeforeMovePriority !== 11 ||
          typeof recharge.onStart !== 'function' ||
          !/["']-mustrecharge["']/.test(String(recharge.onStart))) {
        throw new Error('resolved Gen 3 recharge lifecycle changed');
      }
    }
    if ((id === 'reversal' || id === 'flail') &&
        (move.basePower !== 0 || move.accuracy !== 100 ||
         move.type !== (id === 'reversal' ? 'Fighting' : 'Normal') ||
         typeof move.basePowerCallback !== 'function' ||
         !String(move.basePowerCallback).includes('pokemon.hp * 48 / pokemon.maxhp'))) {
      throw new Error(`resolved Gen 3 ${move.name} formula shape changed`);
    }
    if (id === 'hypervoice' &&
        (move.basePower !== 90 || move.accuracy !== 100 ||
         move.category !== 'Physical' || move.type !== 'Normal' ||
         move.target !== 'allAdjacentFoes' || move.flags?.bypasssub ||
         Object.keys(move).some(key => key.startsWith('on') &&
           typeof move[key] === 'function'))) {
      throw new Error('resolved Gen 3 Hyper Voice ordinary shape changed');
    }
    if (id === 'vitalthrow' &&
        (move.basePower !== 70 || move.accuracy !== true || move.priority !== -1 ||
         move.category !== 'Physical' || move.type !== 'Fighting' ||
         move.target !== 'normal' || Object.keys(move).some(key =>
           key.startsWith('on') && typeof move[key] === 'function'))) {
      throw new Error('resolved Gen 3 Vital Throw always-hit shape changed');
    }
    if ((id === 'eruption' || id === 'waterspout') &&
        (move.basePower !== 150 || move.accuracy !== 100 ||
         move.category !== 'Special' || move.target !== 'allAdjacentFoes' ||
         typeof move.basePowerCallback !== 'function' ||
         !String(move.basePowerCallback).includes(
           'move.basePower * pokemon.hp / pokemon.maxhp'))) {
      throw new Error(`resolved Gen 3 ${move.name} live-HP power shape changed`);
    }
    if ((id === 'explosion' || id === 'selfdestruct') &&
        (move.selfdestruct !== 'always' || move.category !== 'Physical' ||
         move.basePower !== (id === 'explosion' ? 250 : 200) ||
         move.multihit || Object.keys(move).some(key =>
           key.startsWith('on') && typeof move[key] === 'function'))) {
      throw new Error(`resolved Gen 3 ${move.name} self-faint shape changed`);
    }
    if (id === 'memento' &&
        (move.selfdestruct !== 'ifHit' || move.accuracy !== true ||
         move.category !== 'Status' || move.target !== 'normal' ||
         move.boosts?.atk !== -2 || move.boosts?.spa !== -2 ||
         move.multihit || Object.keys(move).some(key =>
           key.startsWith('on') && typeof move[key] === 'function'))) {
      throw new Error('resolved Gen 3 Memento ifHit self-faint shape changed');
    }
    if ((id === 'jumpkick' || id === 'highjumpkick') &&
        (move.category !== 'Physical' || move.type !== 'Fighting' ||
         move.target !== 'normal' || move.basePower !==
           (id === 'jumpkick' ? 70 : 85) ||
         move.accuracy !== (id === 'jumpkick' ? 95 : 90) ||
         typeof move.onMoveFail !== 'function' ||
         !String(move.onMoveFail).includes('target.runImmunity("Fighting")') ||
         !String(move.onMoveFail).includes('this.actions.getDamage') ||
         !String(move.onMoveFail).includes('damage / 2'))) {
      throw new Error(`resolved Gen 3 ${move.name} failure policy changed`);
    }
    if (id === 'revenge' &&
        (move.category !== 'Physical' || move.type !== 'Fighting' ||
         move.target !== 'normal' || move.basePower !== 60 ||
         move.accuracy !== 100 || move.priority !== -4 ||
         typeof move.basePowerCallback !== 'function' ||
         !String(move.basePowerCallback).includes('p.source === target') ||
         !String(move.basePowerCallback).includes('p.damage > 0') ||
         !String(move.basePowerCallback).includes('p.thisTurn') ||
         !String(move.basePowerCallback).includes('move.basePower * 2'))) {
      throw new Error('resolved Gen 3 Revenge provenance policy changed');
    }
    if (id === 'struggle' &&
        (move.basePower !== 50 || move.accuracy !== 100 ||
         move.category !== 'Physical' || move.type !== 'Normal' ||
         move.target !== 'randomNormal' || move.recoil?.[0] !== 1 ||
         move.recoil?.[1] !== 4 || move.struggleRecoil !== false)) {
      throw new Error('resolved Gen 3 Struggle fallback shape changed');
    }
  if (id === 'taunt' &&
        (move.accuracy !== 100 || move.category !== 'Status' ||
         move.volatileStatus !== 'taunt' || move.condition?.duration !== 2 ||
         typeof move.condition?.onDisableMove !== 'function' ||
         typeof move.condition?.onBeforeMove !== 'function' ||
         move.condition?.onBeforeMovePriority !== undefined ||
         !move.flags?.protect || !move.flags?.bypasssub)) {
      throw new Error('resolved Gen 3 Taunt choice-control shape changed');
    }
    if (id === 'torment' &&
        (move.accuracy !== 100 || move.category !== 'Status' ||
         move.volatileStatus !== 'torment' || move.condition?.duration !== undefined ||
         typeof move.condition?.onStart !== 'function' ||
         typeof move.condition?.onEnd !== 'function' ||
         typeof move.condition?.onDisableMove !== 'function' ||
         move.condition?.onBeforeMove !== undefined ||
         !move.flags?.protect || !move.flags?.bypasssub)) {
      throw new Error('resolved Gen 3 Torment choice-control shape changed');
    }
    if (id === 'disable' &&
        (move.accuracy !== 55 || move.category !== 'Status' ||
         move.volatileStatus !== 'disable' ||
         typeof move.onTryHit !== 'function' ||
         typeof move.condition?.durationCallback !== 'function' ||
         typeof move.condition?.onStart !== 'function' ||
         typeof move.condition?.onEnd !== 'function' ||
         typeof move.condition?.onDisableMove !== 'function' ||
         typeof move.condition?.onBeforeMove !== 'function' ||
         move.condition?.onBeforeMovePriority !== 7 ||
         !move.flags?.protect || !move.flags?.bypasssub)) {
      throw new Error('resolved Gen 3 Disable choice-control shape changed');
    }
    if (id === 'encore' &&
        (move.accuracy !== 100 || move.category !== 'Status' ||
         move.volatileStatus !== 'encore' ||
         typeof move.condition?.durationCallback !== 'function' ||
         typeof move.condition?.onStart !== 'function' ||
         typeof move.condition?.onEnd !== 'function' ||
         typeof move.condition?.onDisableMove !== 'function' ||
         typeof move.condition?.onOverrideAction !== 'function' ||
         typeof move.condition?.onResidual !== 'function' ||
         move.condition?.onResidualOrder !== 10 ||
         move.condition?.onResidualSubOrder !== 14 ||
         !move.flags?.protect || !move.flags?.bypasssub)) {
      throw new Error('resolved Gen 3 Encore choice-control shape changed');
    }
    if (id === 'nightmare' &&
        (move.accuracy !== true || move.category !== 'Status' ||
         move.target !== 'normal' || move.volatileStatus !== 'nightmare' ||
         move.condition?.noCopy !== true ||
         typeof move.condition?.onStart !== 'function' ||
         typeof move.condition?.onResidual !== 'function' ||
         move.condition?.onResidualOrder !== 10 ||
         move.condition?.onResidualSubOrder !== 7)) {
      throw new Error('resolved Gen 3 Nightmare lifecycle shape changed');
    }
    const maxPP = move.noPPBoosts ? move.pp : Math.floor(move.pp * 8 / 5);
    const criticalStage = move.critRatio || 1;
    if (!Number.isInteger(criticalStage) || criticalStage < 1 ||
        criticalStage > 255) {
      throw new Error(`invalid critical stage on ${id}: ${criticalStage}`);
    }
    const target = MOVE_TARGETS.get(move.target);
    if (!target) throw new Error(`unsupported target ${move.target} for ${id}`);
    const moveEffects = id === 'curse' ? [] : (effectSpecs[id] || []);
    const accuracy = move.accuracy === true ?
      '{POKEMON_ACCURACY_ALWAYS, 0}' :
      `{POKEMON_ACCURACY_PERCENT, ${move.accuracy}}`;
    const ignoreAccuracy = move.ignoreAccuracy ? 1 : 0;
    const ignoreEvasion = move.ignoreEvasion ? 1 : 0;
    const multihit = Array.isArray(move.multihit) ? move.multihit :
      Number.isInteger(move.multihit) ? [move.multihit, move.multihit] : [0, 0];
    let flags = 0n;
    for (const flag of Object.keys(move.flags || {})) {
      const flagIndex = MOVE_FLAGS.indexOf(flag);
      if (flagIndex < 0) throw new Error(`unmapped move flag ${flag} on ${id}`);
      flags |= 1n << BigInt(flagIndex);
    }
    const airborneHits = new Set(['gust', 'twister', 'skyuppercut', 'thunder']);
    const undergroundHits = new Set(['earthquake', 'magnitude']);
    const underwaterHits = new Set(['surf', 'whirlpool']);
    const airborneDouble = new Set(['gust', 'twister']);
    const semiMask = (sets) => {
      const parts = [];
      if (sets[0].has(id)) parts.push('POKEMON_SEMI_INVULNERABLE_AIRBORNE');
      if (sets[1].has(id)) parts.push('POKEMON_SEMI_INVULNERABLE_UNDERGROUND');
      if (sets[2].has(id)) parts.push('POKEMON_SEMI_INVULNERABLE_UNDERWATER');
      return parts.length ? parts.join(' | ') : '0';
    };
    const semiHitMask = semiMask([airborneHits, undergroundHits, underwaterHits]);
    const semiDoubleMask = semiMask([
      airborneDouble, undergroundHits, underwaterHits,
    ]);
    const retaliationDescriptor = id === 'counter' ?
      'POKEMON_GEN3_CONDITION_VOLATILE_COUNTER' : id === 'mirrorcoat' ?
        'POKEMON_GEN3_CONDITION_VOLATILE_MIRRORCOAT' : '0';
    const retaliationClass = id === 'hiddenpower' || move.category === 'Physical' ?
      'POKEMON_RETALIATION_PHYSICAL' : move.category === 'Special' ?
        'POKEMON_RETALIATION_SPECIAL' : '0';
    const retaliationClassPolicy = id === 'hiddenpower' ?
      'POKEMON_RETALIATION_FIXED_CLASS' :
      'POKEMON_RETALIATION_FROM_ACTIVE_CATEGORY';
    const damageFormula = retaliationDescriptor !== '0' ?
      'POKEMON_DAMAGE_OWNER_CONDITION_VALUE' :
      id === 'seismictoss' || id === 'nightshade' ?
      'POKEMON_DAMAGE_FIXED_LEVEL' : literalDamage ?
        'POKEMON_DAMAGE_FIXED_LITERAL' : id === 'superfang' ?
        'POKEMON_DAMAGE_TARGET_HP_FRACTION' : id === 'endeavor' ?
        'POKEMON_DAMAGE_TARGET_SOURCE_HP_DIFFERENCE' : id === 'psywave' ?
        'POKEMON_DAMAGE_RANDOM_LEVEL_PERCENT' : move.ohko ?
        'POKEMON_DAMAGE_TARGET_CURRENT_HP' :
        (id === 'reversal' || id === 'flail') ?
        'POKEMON_DAMAGE_HP_BRACKET' : 'POKEMON_DAMAGE_STANDARD';
    const damageParameter = retaliationDescriptor !== '0' ?
      retaliationDescriptor : id === 'superfang' ? 2 : literalDamage;
    const basePowerPolicy = id === 'eruption' || id === 'waterspout' ?
      'POKEMON_BASE_POWER_SOURCE_HP_RATIO' : id === 'return' ?
        'POKEMON_BASE_POWER_SOURCE_HAPPINESS' : id === 'frustration' ?
          'POKEMON_BASE_POWER_SOURCE_UNHAPPINESS' : id === 'hiddenpower' ?
            'POKEMON_BASE_POWER_PERSONAL_MOVE_PROFILE' :
            id === 'triplekick' ? 'POKEMON_BASE_POWER_HIT_INDEX' :
            id === 'lowkick' ? 'POKEMON_BASE_POWER_TARGET_WEIGHT' :
            'POKEMON_BASE_POWER_STANDARD';
    if (id === 'lowkick') {
      const callback = String(move.basePowerCallback);
      for (const fragment of ['targetWeight >= 2e3', 'targetWeight >= 1e3',
          'targetWeight >= 500', 'targetWeight >= 250',
          'targetWeight >= 100']) {
        if (!callback.includes(fragment)) {
          throw new Error(`resolved Gen 3 Low Kick callback changed: ${fragment}`);
        }
      }
    }
    const multihitAccuracy = move.multiaccuracy ?
      'POKEMON_MULTIHIT_ACCURACY_EACH_HIT' :
      'POKEMON_MULTIHIT_ACCURACY_ONCE';
    const personalMoveProfileKind = id === 'hiddenpower' ? 1 : 0;
    const slotConditionDescriptor = id === 'futuresight' || id === 'doomdesire' ?
      'POKEMON_GEN3_CONDITION_SLOT_FUTUREMOVE' : id === 'wish' ?
        'POKEMON_GEN3_CONDITION_SLOT_WISH' : '0';
    const preTurnDescriptor = id === 'pursuit' ?
      'POKEMON_GEN3_CONDITION_VOLATILE_PURSUIT' : id === 'focuspunch' ?
        'POKEMON_GEN3_CONDITION_VOLATILE_FOCUSPUNCH' : retaliationDescriptor;
    const preTurnTarget = id === 'pursuit' ?
      'POKEMON_PRE_TURN_TARGET_MOVE_TARGET' : id === 'focuspunch' ?
        'POKEMON_PRE_TURN_TARGET_USER' : '0';
    const preTurnBlockedStatuses = id === 'pursuit' ?
      '(UINT16_C(1) << POKEMON_STATUS_SLEEP) | (UINT16_C(1) << POKEMON_STATUS_FREEZE)' : '0';
    const noMirror = new Set([
      'assist', 'curse', 'doomdesire', 'focuspunch', 'futuresight', 'magiccoat',
      'metronome', 'mimic', 'mirrormove', 'naturepower', 'psychup', 'roleplay',
      'sketch', 'sleeptalk', 'spikes', 'spitup', 'taunt', 'teeterdance', 'transform',
    ]);
    const mirrorEligible = noMirror.has(id) ? 0 : 1;
    const selfFaintTiming = move.selfdestruct === 'always' ?
      'POKEMON_SELF_FAINT_PRE_HIT' : move.selfdestruct === 'ifHit' ?
        'POKEMON_SELF_FAINT_IF_HIT' : 'POKEMON_SELF_FAINT_NONE';
    const defensePolicy = move.selfdestruct === 'always' ?
      'POKEMON_DEFENSE_POLICY_SELF_DESTRUCT' :
      'POKEMON_DEFENSE_POLICY_STANDARD';
    const failurePolicy = id === 'jumpkick' || id === 'highjumpkick' ?
      '{POKEMON_MOVE_FAILURE_HYPOTHETICAL_DAMAGE_TO_SOURCE, 1, 2, 1, 2, 1, 1}' :
      '{POKEMON_MOVE_FAILURE_NONE, 0, 0, 0, 0, 0, 0}';
    const selfSwitchTransfer = move.selfSwitch === 'copyvolatile' ?
      'POKEMON_SWITCH_TRANSFER_BOOSTS_AND_VOLATILES' :
      'POKEMON_SWITCH_TRANSFER_NONE';
    const selfSwitchSkipBeforeSwitchOut =
      id === 'batonpass' ? 1 : 0;
    const emptyWeather = '{0, 0, 0, {0, 0}, 0}';
    let weatherPolicy = Array(5).fill(emptyWeather);
    if (id === 'weatherball') {
      const weatherTypes = ['Normal', 'Rock', 'Ice', 'Water', 'Fire'];
      const weatherCategories = ['Physical', 'Physical', 'Special', 'Special', 'Special'];
      weatherPolicy = weatherTypes.map((type, index) =>
        `{POKEMON_WEATHER_MOVE_TYPE | POKEMON_WEATHER_MOVE_CATEGORY | POKEMON_WEATHER_MOVE_POWER, ` +
        `${typeID(type)}, POKEMON_CATEGORY_${cName(weatherCategories[index])}, {0, 0}, ${index ? 8192 : 4096}}`);
    } else if (id === 'thunder') {
      const accuracies = [70, 70, 70, true, 50];
      weatherPolicy = accuracies.map(accuracyValue =>
        `{POKEMON_WEATHER_MOVE_ACCURACY, 0, 0, ${accuracyValue === true ?
          '{POKEMON_ACCURACY_ALWAYS, 0}' :
          `{POKEMON_ACCURACY_PERCENT, ${accuracyValue}}`}, 0}`);
    } else if (id === 'solarbeam') {
      weatherPolicy = [4096, 2048, 2048, 2048, 4096].map((power, index) =>
        `{POKEMON_WEATHER_MOVE_POWER${index === 4 ? ' | POKEMON_WEATHER_MOVE_SKIP_CHARGE | POKEMON_WEATHER_MOVE_SUPPRESS_TARGET' : ''}, ` +
        `0, 0, {0, 0}, ${power}}`);
    }
    const modifierTags =
      (KINGS_ROCK_MOVES.has(id) ? 1 : 0) | (id === 'willowisp' ? 2 : 0);
    const resolution = id === 'bide' || move.category === 'Status' ?
      'POKEMON_MOVE_RESOLUTION_NONE' : 'POKEMON_MOVE_RESOLUTION_DAMAGE';
    lines.push(`    {POKEMON_GEN3_MOVE_${cName(id)}, ${moveCatalogID.get(id) || 0}, ${typeID(move.type)}, ` +
      `POKEMON_CATEGORY_${cName(move.category)}, ${move.basePower}, ${accuracy}, ` +
      `${ignoreAccuracy}, ${ignoreEvasion}, ` +
      `${move.priority}, ${move.pp}, ${maxPP}, ${move.noPPBoosts ? 1 : 0}, ${target}, UINT64_C(${flags}), UINT64_C(${modifierTags}), ${semiHitMask}, ${semiDoubleMask}, ${effectOffsets.get(id)}, ${moveEffects.length}, ` +
      `${multihit[0]}, ${multihit[1]}, ${multihitAccuracy}, ${damageFormula}, ${damageParameter}, ${basePowerPolicy}, ` +
      `${id === 'smellingsalts' ? 'UINT16_C(1) << POKEMON_STATUS_PARALYSIS' : 0}, ${id === 'smellingsalts' ? 2 : 0}, ${move.ignoreImmunity === false ? 1 : 0}, ${move.flags?.bypasssub ? 1 : 0}, ` +
      `${move.flags?.defrost ? 1 : 0}, ${move.thawsTarget ? 1 : 0}, ${criticalStage}, ${mirrorEligible}, ` +
      `{${weatherPolicy.join(', ')}}, ${selfFaintTiming}, ${defensePolicy}, ` +
      `${move.flags?.failencore ? 0 : 1}, ${[
        !move.flags?.nosleeptalk && !move.flags?.charge ? 'POKEMON_MOVE_CALL_ELIGIBLE_SLEEP_TALK' : 0,
        !move.flags?.noassist ? 'POKEMON_MOVE_CALL_ELIGIBLE_ASSIST' : 0,
      ].filter(Boolean).join(' | ') || 0}, ` +
      `${[move.flags?.failmimic ? 0 : 'POKEMON_MOVE_COPY_ELIGIBLE_MIMIC', move.flags?.nosketch ? 0 : 'POKEMON_MOVE_COPY_ELIGIBLE_SKETCH'].filter(Boolean).join(' | ') || 0}, ` +
      `${move.sleepUsable ? 1 : 0}, ${preTurnDescriptor}, ${retaliationClass}, ${retaliationClassPolicy}, ${personalMoveProfileKind}, ${slotConditionDescriptor}, ` +
      `${preTurnTarget}, ${preTurnBlockedStatuses}, ${id === 'pursuit' ? 1 : 0}, ${id === 'pursuit' ? 2 : 0}, ` +
      `${selfSwitchTransfer}, ${selfSwitchSkipBeforeSwitchOut}, ` +
      `{${ohkoKind}, ${ohkoType}}, ${id === 'metronome' ? 1 : 0}, ${resolution}, ` +
      `${retaliationDescriptor !== '0' ? 1 : 0}, ${failurePolicy}, ${id === 'lowkick' ? 1 : 0}},`);
  }
  {
    const bide = dex.moves.get('bide');
    const flagNames = ['contact', 'protect'];
    if (!String(bide.condition.onBeforeMove).includes('flags: { contact: 1, protect: 1 }')) {
      throw new Error('resolved Gen 3 Bide constructed-hit flags changed');
    }
    let flags = 0n;
    for (const flag of flagNames) flags |= 1n << BigInt(MOVE_FLAGS.indexOf(flag));
    const maxPP = bide.noPPBoosts ? bide.pp : Math.floor(bide.pp * 8 / 5);
    lines.push('};', '', 'static const PokemonConstructedHitTemplate CONSTRUCTED_HIT_TEMPLATES[] = {',
      '    {',
      '        .id = 1,',
      '        .owner_condition_descriptor = POKEMON_GEN3_CONDITION_VOLATILE_BIDE,',
      '        .target_policy = POKEMON_CONSTRUCTED_TARGET_LAST_SOURCE_OR_CURRENT_FOE,',
      '        .move = {',
      '            .id = POKEMON_GEN3_MOVE_BIDE,',
      `            .catalog_id = ${moveCatalogID.get('bide')},`,
      '            .type = POKEMON_GEN3_TYPE_NORMAL,',
      '            .category = POKEMON_CATEGORY_PHYSICAL,',
      '            .power = 0,',
      '            .accuracy = {POKEMON_ACCURACY_PERCENT, 100},',
      '            .priority = 0,',
      `            .raw_pp = ${bide.pp}, .pp = ${maxPP},`,
      '            .target = POKEMON_TARGET_NORMAL,',
      `            .flags = UINT64_C(${flags}),`,
      '            .damage_formula = POKEMON_DAMAGE_OWNER_CONDITION_VALUE,',
      '            .damage_parameter = POKEMON_GEN3_CONDITION_VOLATILE_BIDE,',
      '            .critical_stage = 1,',
      '            .defense_policy = POKEMON_DEFENSE_POLICY_STANDARD,',
      '            .retaliation_class_mask = POKEMON_RETALIATION_PHYSICAL,',
      '            .retaliation_class_policy = POKEMON_RETALIATION_FROM_ACTIVE_CATEGORY,',
      '            .resolution = POKEMON_MOVE_RESOLUTION_DAMAGE,',
      '            .owner_condition_damage_multiplier = 2,',
      '        },',
      '    },',
      '};', '', 'static const PokemonMovePreUseProgram MOVE_PRE_USE_PROGRAMS[] = {',
      '    {POKEMON_GEN3_MOVE_BIDE, POKEMON_MOVE_PRE_USE_CANCEL_IF_VOLATILE_KIND, POKEMON_VOLATILE_STORED_DAMAGE},',
      '};', '', 'static const PokemonLockedRampPolicy LOCKED_RAMP_POLICIES[] = {',
      '    {1, POKEMON_GEN3_MOVE_ROLLOUT, POKEMON_VOLATILE_ROLLOUT, POKEMON_GEN3_CONDITION_VOLATILE_ROLLOUT, POKEMON_VOLATILE_DEFENSE_CURL, POKEMON_GEN3_CONDITION_VOLATILE_DEFENSECURL, 5, 2, 2},',
      '    {2, POKEMON_GEN3_MOVE_ICEBALL, POKEMON_VOLATILE_ICE_BALL, POKEMON_GEN3_CONDITION_VOLATILE_ICEBALL, POKEMON_VOLATILE_DEFENSE_CURL, POKEMON_GEN3_CONDITION_VOLATILE_DEFENSECURL, 5, 2, 2},',
      '};', '', 'static const PokemonCounterHealPolicy COUNTER_HEAL_POLICIES[] = {',
      '    {1, POKEMON_VOLATILE_STOCKPILE, POKEMON_GEN3_CONDITION_VOLATILE_STOCKPILE, 1, 3, {1024, 2048, 4096}},',
      '};', '', 'static const uint8_t TYPE_RESPONSE_CANDIDATES[] = {',
      `    ${TYPE_RESPONSE_ORDER.map(typeID).join(', ')},`,
      '};', '', 'static const PokemonTypeResponsePolicy TYPE_RESPONSE_POLICIES[] = {',
      `    {1, TYPE_RESPONSE_CANDIDATES, sizeof(TYPE_RESPONSE_CANDIDATES), 2, 0, 0, ${moveCatalogID.get('struggle')}, POKEMON_GEN3_TYPE_NORMAL},`,
      '};', '', 'static const uint8_t TYPE_CHART[] = {');
  }
  const resolvedTypeOrder = dex.types.names();
  if (resolvedTypeOrder.length !== TYPE_RESPONSE_ORDER.length ||
      resolvedTypeOrder.some((type, index) => type !== TYPE_RESPONSE_ORDER[index])) {
    throw new Error('resolved Gen 3 standard type iteration order changed');
  }
  for (const attack of TYPES) {
    lines.push(`    ${TYPES.map(defense => effectiveness(attack, defense)).join(', ')}, /* ${attack} */`);
  }
  const baseHandlerPrograms = [
    '    {POKEMON_HANDLER_OP_GUARD_MOVE_TYPE, POKEMON_GEN3_TYPE_WATER},',
    '    {POKEMON_HANDLER_OP_GUARD_SOURCE_NOT_TARGET, 0},',
    '    {POKEMON_HANDLER_OP_TRY_HEAL_HOLDER_MAX_HP_FRACTION, (1u << 16) | 4u},',
    '    {POKEMON_HANDLER_OP_RETURN_NULL, 0},',
    '    {POKEMON_HANDLER_OP_GUARD_STATUS_PRESENT, 0},',
    '    {POKEMON_HANDLER_OP_CHAIN_Q12, 6144},',
    '    {POKEMON_HANDLER_OP_GUARD_MOVE_TYPE, POKEMON_GEN3_TYPE_FIGHTING},',
    '    {POKEMON_HANDLER_OP_CHAIN_Q12, 4505},',
    '    {POKEMON_HANDLER_OP_GUARD_DAMAGE_KIND, POKEMON_DAMAGE_RELATIVE_RECOIL},',
    '    {POKEMON_HANDLER_OP_RETURN_NULL, 0},',
    '    {POKEMON_HANDLER_OP_GUARD_SOURCE_NOT_TARGET, 0},',
    '    {POKEMON_HANDLER_OP_DROP_ALL_NEGATIVE_BOOSTS, 0},',
    '    {POKEMON_HANDLER_OP_GUARD_SOURCE_NOT_TARGET, 0},',
    '    {POKEMON_HANDLER_OP_DROP_NEGATIVE_BOOST_STAT, POKEMON_STAT_ATK},',
    '    {POKEMON_HANDLER_OP_GUARD_SOURCE_NOT_TARGET, 0},',
    '    {POKEMON_HANDLER_OP_DROP_NEGATIVE_BOOST_STAT, POKEMON_STAT_ACCURACY},',
    '    {POKEMON_HANDLER_OP_GUARD_SOURCE_NOT_TARGET, 0},',
    '    {POKEMON_HANDLER_OP_DROP_ALL_NEGATIVE_BOOSTS, 0},',
    `    {POKEMON_HANDLER_OP_GUARD_MOVE_FLAG, ${MOVE_FLAGS.indexOf('protect')}},`,
    '    {POKEMON_HANDLER_OP_RETURN_NOT_FAIL, 0},',
    `    {POKEMON_HANDLER_OP_GUARD_MOVE_FLAG, ${MOVE_FLAGS.indexOf('reflectable')}},`,
    '    {POKEMON_HANDLER_OP_GUARD_SOURCE_NOT_TARGET, 0},',
    '    {POKEMON_HANDLER_OP_GUARD_ACTIVE_MOVE_NOT_BOUNCED, 0},',
    '    {POKEMON_HANDLER_OP_REMOVE_OWNER_VOLATILE, 0},',
    '    {POKEMON_HANDLER_OP_REFLECT_ACTIVE_MOVE, 0},',
    '    {POKEMON_HANDLER_OP_RETURN_NULL, 0},',
    `    {POKEMON_HANDLER_OP_GUARD_MOVE_FLAG, ${MOVE_FLAGS.indexOf('snatch')}},`,
    '    {POKEMON_HANDLER_OP_REMOVE_OWNER_VOLATILE, 0},',
    '    {POKEMON_HANDLER_OP_DEDUCT_OWNER_MOVE_PP_FROM_TARGET_EVENT, 0},',
    '    {POKEMON_HANDLER_OP_CALL_ACTIVE_MOVE_AS_OWNER, 0},',
    '    {POKEMON_HANDLER_OP_RETURN_NULL, 0},',
    '    {POKEMON_HANDLER_OP_CHAIN_Q12, 5324},',
    '    {POKEMON_HANDLER_OP_CHAIN_Q12, 8192},',
    '    {POKEMON_HANDLER_OP_MODIFY_RELAY_Q12, 6144},',
    '    {POKEMON_HANDLER_OP_GUARD_MOVE_TYPE_MASK, ' +
      '((UINT32_C(1) << POKEMON_GEN3_TYPE_NORMAL) | ' +
      '(UINT32_C(1) << POKEMON_GEN3_TYPE_FIGHTING) | ' +
      '(UINT32_C(1) << POKEMON_GEN3_TYPE_FLYING) | ' +
      '(UINT32_C(1) << POKEMON_GEN3_TYPE_POISON) | ' +
      '(UINT32_C(1) << POKEMON_GEN3_TYPE_GROUND) | ' +
      '(UINT32_C(1) << POKEMON_GEN3_TYPE_ROCK) | ' +
      '(UINT32_C(1) << POKEMON_GEN3_TYPE_BUG) | ' +
      '(UINT32_C(1) << POKEMON_GEN3_TYPE_GHOST) | ' +
      '(UINT32_C(1) << POKEMON_GEN3_TYPE_STEEL))},',
    '    {POKEMON_HANDLER_OP_CHAIN_Q12, 3277},',
    '    {POKEMON_HANDLER_OP_CHAIN_Q12, 8192},',
    '    {POKEMON_HANDLER_OP_GUARD_HOLDER_SPECIES_PAIR, ' +
      '(POKEMON_GEN3_SPECIES_CUBONE << 16) | POKEMON_GEN3_SPECIES_MAROWAK},',
    '    {POKEMON_HANDLER_OP_CHAIN_Q12, 8192},',
  ];
  const flinchProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_RETURN_FALSE, 0},',
    '    {POKEMON_HANDLER_OP_GUARD_VOLATILE_KIND, POKEMON_VOLATILE_FLINCH},',
    '    {POKEMON_HANDLER_OP_RETURN_NULL, 0},',
  );
  const criticalProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_RETURN_UNDEFINED, 0},',
    '    {POKEMON_HANDLER_OP_ADD_RELAY_U32, 2},',
    '    {POKEMON_HANDLER_OP_ADD_RELAY_U32, 1},',
    '    {POKEMON_HANDLER_OP_GUARD_HOLDER_SPECIES_PAIR, (POKEMON_GEN3_SPECIES_CHANSEY << 16) | POKEMON_GEN3_SPECIES_CHANSEY},',
    '    {POKEMON_HANDLER_OP_ADD_RELAY_U32, 2},',
    '    {POKEMON_HANDLER_OP_GUARD_HOLDER_SPECIES_PAIR, (POKEMON_GEN3_SPECIES_FARFETCHD << 16) | POKEMON_GEN3_SPECIES_FARFETCHD},',
    '    {POKEMON_HANDLER_OP_ADD_RELAY_U32, 2},',
    '    {POKEMON_HANDLER_OP_RETURN_FALSE, 0},',
    '    {POKEMON_HANDLER_OP_RETURN_FALSE, 0},',
  );
  const partialTrapProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_GUARD_OWNER_SOURCE_ACTIVE, 0},',
    '    {POKEMON_HANDLER_OP_DISALLOW_TARGET_SWITCHES, 0},',
    '    {POKEMON_HANDLER_OP_SOURCE_BOUND_MAX_HP_DAMAGE, (1u << 16) | 16u},',
  );
  const struggleProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_SET_ACTIVE_MOVE_TYPE, POKEMON_GEN3_TYPE_TYPELESS},',
  );
  const magnitudeProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_SAMPLE_ACTIVE_MOVE_OUTCOME_WEIGHTED, 1},',
  );
  const presentProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_SAMPLE_ACTIVE_MOVE_OUTCOME_WEIGHTED, 2},',
  );
  const disableTryHitProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_REQUIRE_TARGET_LAST_NONFALLBACK, 0},',
  );
  const endeavorTryProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_RETURN_SOURCE_HP_BELOW_TARGET, 0},',
  );
  const brickBreakProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_REMOVE_SIDE_CONDITION, (POKEMON_SIDE_SELECTOR_SOURCE_OPPOSING << 24) | POKEMON_GEN3_CONDITION_SIDE_REFLECT},',
    '    {POKEMON_HANDLER_OP_REMOVE_SIDE_CONDITION, (POKEMON_SIDE_SELECTOR_SOURCE_OPPOSING << 24) | POKEMON_GEN3_CONDITION_SIDE_LIGHTSCREEN},',
  );
  const starterAbilityProgramOffset = baseHandlerPrograms.length;
  for (const [, type] of STARTER_ABILITY_HANDLERS) {
    baseHandlerPrograms.push(
      '    {POKEMON_HANDLER_OP_GUARD_HOLDER_HP_AT_MOST_FRACTION, (1u << 16) | 3u},',
      `    {POKEMON_HANDLER_OP_GUARD_MOVE_TYPE, POKEMON_GEN3_TYPE_${cName(type)}},`,
      '    {POKEMON_HANDLER_OP_CHAIN_Q12, 6144},',
    );
  }
  const safeguardProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_GUARD_SOURCE_NOT_TARGET, 0},',
    '    {POKEMON_HANDLER_OP_GUARD_SOURCE_EFFECT_NOT, (POKEMON_SOURCE_EFFECT_CONDITION << 24) | POKEMON_GEN3_CONDITION_VOLATILE_YAWN},',
    '    {POKEMON_HANDLER_OP_RETURN_NULL, 0},',
    '    {POKEMON_HANDLER_OP_GUARD_SOURCE_NOT_TARGET, 0},',
    '    {POKEMON_HANDLER_OP_GUARD_VOLATILE_KIND_MASK, (UINT32_C(1) << POKEMON_VOLATILE_CONFUSION) | (UINT32_C(1) << POKEMON_VOLATILE_YAWN)},',
    '    {POKEMON_HANDLER_OP_RETURN_NULL, 0},',
  );
  const yawnProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_REQUIRE_TARGET_STATUS_NONE, 0},',
    '    {POKEMON_HANDLER_OP_SET_STATUS_FROM_OWNER_SOURCE, POKEMON_STATUS_SLEEP},',
    '    {POKEMON_HANDLER_OP_GUARD_VOLATILE_KIND, POKEMON_VOLATILE_YAWN},',
    '    {POKEMON_HANDLER_OP_EMIT_HANDLER_IMMUNITY, 0},',
    '    {POKEMON_HANDLER_OP_RETURN_NULL, 0},',
    '    {POKEMON_HANDLER_OP_RETURN_UNDEFINED, 0},',
  );
  const sleepImmunityUpdateProgramOffset = baseHandlerPrograms.length;
  for (const [, , statusMask] of STATUS_ABILITY_UPDATE_HANDLERS) {
    baseHandlerPrograms.push(
      `    {POKEMON_HANDLER_OP_GUARD_HOLDER_STATUS_MASK, ${statusMask}},`,
      '    {POKEMON_HANDLER_OP_CLEAR_MAJOR_STATUS, 0},',
    );
  }
  const spikesProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_SET_OWNER_SIDE_COUNTER, 1},',
    '    {POKEMON_HANDLER_OP_INCREMENT_OWNER_SIDE_COUNTER_UP_TO, 3},',
    '    {POKEMON_HANDLER_OP_GUARD_TARGET_GROUNDED, POKEMON_GEN3_TYPE_GROUND},',
    '    {POKEMON_HANDLER_OP_DAMAGE_TARGET_MAX_HP_BY_OWNER_COUNTER_FRACTIONS, (24u << 24) | (3u << 16) | (4u << 8) | 6u},',
  );
  const screenProgramOffset = baseHandlerPrograms.length;
  for (const category of ['PHYSICAL', 'SPECIAL']) {
    baseHandlerPrograms.push(
      '    {POKEMON_HANDLER_OP_GUARD_SOURCE_NOT_TARGET, 0},',
      '    {POKEMON_HANDLER_OP_GUARD_HOLDER_SIDE_CONTAINS_TARGET, 0},',
      `    {POKEMON_HANDLER_OP_GUARD_MOVE_CATEGORY, POKEMON_CATEGORY_${category}},`,
      '    {POKEMON_HANDLER_OP_GUARD_MOVE_HIT_NOT_CRITICAL, 0},',
      '    {POKEMON_HANDLER_OP_CHAIN_Q12, 2048},',
    );
  }
  const leftoversProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_HEAL_MAX_HP_FRACTION, 16},',
  );
  const naturalCureProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_CLEAR_MAJOR_STATUS, 0},',
  );
  const shedSkinProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_GUARD_HOLDER_ALIVE, 0},',
    '    {POKEMON_HANDLER_OP_GUARD_STATUS_PRESENT, 0},',
    '    {POKEMON_HANDLER_OP_GUARD_RANDOM_CHANCE, (POKEMON_DRAW_RESIDUAL_STATUS_CURE << 24) | (33 << 16) | 100},',
    '    {POKEMON_HANDLER_OP_CLEAR_MAJOR_STATUS, 0},',
  );
  const speedBoostProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_GUARD_HOLDER_ALIVE, 0},',
    '    {POKEMON_HANDLER_OP_GUARD_HOLDER_ACTIVE_TURNS, 0},',
    '    {POKEMON_HANDLER_OP_BOOST_HOLDER_STAT, (POKEMON_STAT_SPE << 8) | UINT8_C(1)},',
  );
  const truantSwitchInProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_SET_HOLDER_BOOLEAN_FROM_BATTLE_STARTED, POKEMON_BOOLEAN_STATE_ALTERNATING_ACTION_PHASE},',
  );
  const truantBeforeMoveProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_RETURN_FALSE_IF_HOLDER_BOOLEAN, POKEMON_BOOLEAN_STATE_ALTERNATING_ACTION_PHASE},',
  );
  const truantResidualProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_TOGGLE_HOLDER_BOOLEAN, POKEMON_BOOLEAN_STATE_ALTERNATING_ACTION_PHASE},',
  );
  const forecastStartProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_NEST_EVENT, POKEMON_HANDLER_EVENT_WEATHER_CHANGE},',
  );
  const forecastWeatherChangeProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_PROJECT_HOLDER_WEATHER_FORM, 1},',
  );
  const transformHitProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_COPY_EVENT_TARGET_BATTLE_PROFILE, 1},',
  );
  const smellingSaltsHitProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_GUARD_ACTIVE_MOVE_TARGET_STATUS_MASK, UINT32_C(1) << POKEMON_STATUS_PARALYSIS},',
    '    {POKEMON_HANDLER_OP_CLEAR_ACTIVE_MOVE_TARGET_MAJOR_STATUS, 0},',
  );
  const bellyDrumHitProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_PAY_MAX_HP_FRACTION_AND_MAXIMIZE_HOLDER_STAT, (POKEMON_STAT_ATK << 16) | (1u << 8) | 2u},',
  );
  const beatUpModifyMoveProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_TRY_ADD_OR_RESTART_SOURCE_VOLATILE, POKEMON_VOLATILE_PARTY_HIT},',
    '    {POKEMON_HANDLER_OP_SET_ACTIVE_MOVE_TYPE, POKEMON_GEN3_TYPE_TYPELESS},',
    '    {POKEMON_HANDLER_OP_SET_ACTIVE_MOVE_CATEGORY, POKEMON_CATEGORY_SPECIAL},',
    '    {POKEMON_HANDLER_OP_SNAPSHOT_ACTIVE_MOVE_PARTY_HITS, 0},',
  );
  const beatUpBasePowerProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_RETURN_NULL_IF_NO_ACTIVE_PARTY_HITS, 0},',
  );
  const beatUpModifySpAProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_SET_RELAY_FROM_NEXT_PARTY_HIT_BASE_STAT, POKEMON_STAT_ATK},',
  );
  const beatUpModifySpDProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_SET_RELAY_FROM_EVENT_TARGET_BASE_SPECIES_STAT, POKEMON_STAT_DEF},',
  );
  const painSplitHitProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_SET_SOURCE_TARGET_HP_TO_FLOOR_AVERAGE, 0},',
  );
  const revengeBasePowerProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_GUARD_HOLDER_ATTACKED_BY_TARGET_THIS_TURN, 0},',
    '    {POKEMON_HANDLER_OP_MULTIPLY_RELAY_U32, 2},',
  );
  const dreamEaterTryImmunityProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_REQUIRE_HOLDER_STATUS_MASK, UINT32_C(1) << POKEMON_STATUS_SLEEP},',
    '    {POKEMON_HANDLER_OP_REQUIRE_HOLDER_WITHOUT_VOLATILE_KIND, POKEMON_VOLATILE_SUBSTITUTE},',
  );
  const nightmareProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_REQUIRE_HOLDER_STATUS_MASK, UINT32_C(1) << POKEMON_STATUS_SLEEP},',
    '    {POKEMON_HANDLER_OP_DAMAGE_HOLDER_BASE_MAX_HP_FRACTION, (1u << 16) | 4u},',
  );
  const pressureProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_GUARD_SOURCE_OPPOSES_HOLDER, 0},',
    '    {POKEMON_HANDLER_OP_ADD_RELAY_U32, 1},',
  );
  const dampProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_GUARD_MOVE_SELF_FAINT_TIMING, POKEMON_SELF_FAINT_PRE_HIT},',
    '    {POKEMON_HANDLER_OP_RETURN_FALSE, 0},',
  );
  const flameBodyProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    `    {POKEMON_HANDLER_OP_GUARD_MOVE_FLAG, ${MOVE_FLAGS.indexOf('contact')}},`,
    '    {POKEMON_HANDLER_OP_GUARD_RANDOM_CHANCE, (POKEMON_DRAW_CONTACT_RESPONSE << 24) | (1 << 16) | 3},',
    '    {POKEMON_HANDLER_OP_SET_EVENT_SOURCE_STATUS_FROM_HOLDER, POKEMON_STATUS_BURN},',
  );
  const staticProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    `    {POKEMON_HANDLER_OP_GUARD_MOVE_FLAG, ${MOVE_FLAGS.indexOf('contact')}},`,
    '    {POKEMON_HANDLER_OP_GUARD_RANDOM_CHANCE, (POKEMON_DRAW_CONTACT_RESPONSE << 24) | (1 << 16) | 3},',
    '    {POKEMON_HANDLER_OP_SET_EVENT_SOURCE_STATUS_FROM_HOLDER, POKEMON_STATUS_PARALYSIS},',
  );
  const poisonPointProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    `    {POKEMON_HANDLER_OP_GUARD_MOVE_FLAG, ${MOVE_FLAGS.indexOf('contact')}},`,
    '    {POKEMON_HANDLER_OP_GUARD_RANDOM_CHANCE, (POKEMON_DRAW_CONTACT_RESPONSE << 24) | (1 << 16) | 3},',
    '    {POKEMON_HANDLER_OP_SET_EVENT_SOURCE_STATUS_FROM_HOLDER, POKEMON_STATUS_POISON},',
  );
  const effectSporeProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    `    {POKEMON_HANDLER_OP_GUARD_MOVE_FLAG, ${MOVE_FLAGS.indexOf('contact')}},`,
    '    {POKEMON_HANDLER_OP_GUARD_RANDOM_CHANCE, (POKEMON_DRAW_CONTACT_RESPONSE << 24) | (1 << 16) | 10},',
    '    {POKEMON_HANDLER_OP_SET_EVENT_SOURCE_STATUS_FROM_HOLDER_UNIFORM_3, (POKEMON_DRAW_CONTACT_STATUS_SELECTION << 24) | (POKEMON_STATUS_SLEEP << 16) | (POKEMON_STATUS_PARALYSIS << 8) | POKEMON_STATUS_POISON},',
  );
  const roughSkinProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    `    {POKEMON_HANDLER_OP_GUARD_MOVE_FLAG, ${MOVE_FLAGS.indexOf('contact')}},`,
    '    {POKEMON_HANDLER_OP_DAMAGE_EVENT_SOURCE_BASE_MAX_HP_FRACTION, (1 << 16) | 16},',
  );
  const arenaTrapProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_GUARD_OWNER_ADJACENT_TO_TARGET, 0},',
    '    {POKEMON_HANDLER_OP_GUARD_TARGET_GROUNDED, POKEMON_GEN3_TYPE_GROUND},',
    '    {POKEMON_HANDLER_OP_DISALLOW_TARGET_SWITCHES, 1},',
  );
  const magnetPullProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_GUARD_OWNER_ADJACENT_TO_TARGET, 0},',
    '    {POKEMON_HANDLER_OP_GUARD_TARGET_CURRENT_TYPE, POKEMON_GEN3_TYPE_STEEL},',
    '    {POKEMON_HANDLER_OP_DISALLOW_TARGET_SWITCHES, 1},',
  );
  const flyInvulnerabilityProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_GUARD_MOVE_LACKS_SEMI_INVULNERABLE_BYPASS, POKEMON_SEMI_INVULNERABLE_AIRBORNE},',
    '    {POKEMON_HANDLER_OP_RETURN_FALSE, 0},',
  );
  const airborneDoubleProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_GUARD_MOVE_HAS_SEMI_INVULNERABLE_DOUBLE, POKEMON_SEMI_INVULNERABLE_AIRBORNE},',
    '    {POKEMON_HANDLER_OP_CHAIN_Q12, 8192},',
  );
  const undergroundInvulnerabilityProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_GUARD_MOVE_LACKS_SEMI_INVULNERABLE_BYPASS, POKEMON_SEMI_INVULNERABLE_UNDERGROUND},',
    '    {POKEMON_HANDLER_OP_RETURN_FALSE, 0},',
  );
  const undergroundDoubleProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_GUARD_MOVE_HAS_SEMI_INVULNERABLE_DOUBLE, POKEMON_SEMI_INVULNERABLE_UNDERGROUND},',
    '    {POKEMON_HANDLER_OP_CHAIN_Q12, 8192},',
  );
  const underwaterInvulnerabilityProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_GUARD_MOVE_LACKS_SEMI_INVULNERABLE_BYPASS, POKEMON_SEMI_INVULNERABLE_UNDERWATER},',
    '    {POKEMON_HANDLER_OP_RETURN_FALSE, 0},',
  );
  const underwaterDoubleProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_GUARD_MOVE_HAS_SEMI_INVULNERABLE_DOUBLE, POKEMON_SEMI_INVULNERABLE_UNDERWATER},',
    '    {POKEMON_HANDLER_OP_CHAIN_Q12, 8192},',
  );
  const hiddenWeatherImmunityProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_GUARD_IMMUNITY_WEATHER_MASK, ' +
      '(UINT32_C(1) << POKEMON_WEATHER_SANDSTORM) | ' +
      '(UINT32_C(1) << POKEMON_WEATHER_HAIL)},',
    '    {POKEMON_HANDLER_OP_RETURN_FALSE, 0},',
  );
  const voltAbsorbProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_GUARD_MOVE_TYPE, POKEMON_GEN3_TYPE_ELECTRIC},',
    '    {POKEMON_HANDLER_OP_GUARD_SOURCE_NOT_TARGET, 0},',
    '    {POKEMON_HANDLER_OP_GUARD_SOURCE_EFFECT_NOT, (POKEMON_SOURCE_EFFECT_MOVE << 24) | POKEMON_GEN3_MOVE_THUNDERWAVE},',
    '    {POKEMON_HANDLER_OP_TRY_HEAL_HOLDER_MAX_HP_FRACTION, (1u << 16) | 4u},',
    '    {POKEMON_HANDLER_OP_RETURN_NULL, 0},',
  );
  const thickFatProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_GUARD_MOVE_TYPE_MASK, ' +
      '((UINT32_C(1) << POKEMON_GEN3_TYPE_FIRE) | ' +
      '(UINT32_C(1) << POKEMON_GEN3_TYPE_ICE))},',
    '    {POKEMON_HANDLER_OP_CHAIN_Q12, 2048},',
  );
  const marvelScaleProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_GUARD_STATUS_PRESENT, 0},',
    '    {POKEMON_HANDLER_OP_CHAIN_Q12, 6144},',
  );
  const sturdy = dex.abilities.get('sturdy');
  const sturdyTryHitSource = String(sturdy.onTryHit);
  if (typeof sturdy.onTryHit !== 'function' ||
      !/move\.ohko/.test(sturdyTryHitSource) ||
      !/return null/.test(sturdyTryHitSource) || sturdy.onDamage !== undefined) {
    throw new Error('resolved Gen 3 Sturdy must be OHKO-only TryHit cancellation');
  }
  const sturdyTryHitProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_GUARD_MOVE_OHKO, 0},',
    '    {POKEMON_HANDLER_OP_RETURN_NULL, 0},',
  );
  const metronomeHitProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_CALL_MOVE_FROM_POOL, 1},',
  );
  const naturePowerHitProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_CALL_FIXED_MOVE, POKEMON_GEN3_MOVE_SWIFT},',
  );
  const sleepTalkTryProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_REQUIRE_HOLDER_STATUS_MASK, UINT32_C(1) << POKEMON_STATUS_SLEEP},',
  );
  const sleepTalkTryHitProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_RETURN_FALSE_IF_HOLDER_VOLATILE_MASK, ' +
      '(UINT32_C(1) << POKEMON_VOLATILE_CHOICE_LOCK) | ' +
      '(UINT32_C(1) << POKEMON_VOLATILE_ENCORE)},',
  );
  const sleepTalkHitProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_CALL_MOVE_FROM_USER_SLOTS, POKEMON_MOVE_CALL_ELIGIBLE_SLEEP_TALK},',
  );
  const assistHitProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_CALL_MOVE_FROM_PARTY_SLOTS, POKEMON_MOVE_CALL_ELIGIBLE_ASSIST},',
  );
  const curseModifyMoveProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_SELECT_ACTIVE_MOVE_PROFILE_BY_USER_TYPE, 1},',
    '    {POKEMON_HANDLER_OP_GUARD_ACTIVE_MOVE_PROFILE_TAG, 1},',
    '    {POKEMON_HANDLER_OP_CLEAR_ACTIVE_MOVE_EFFECTS_IF_TARGET_VOLATILE, POKEMON_VOLATILE_SUBSTITUTE},',
  );
  const curseTryHitProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_GUARD_ACTIVE_MOVE_PROFILE_TAG, 1},',
    '    {POKEMON_HANDLER_OP_RETURN_FALSE_IF_EVENT_TARGET_VOLATILE, POKEMON_VOLATILE_CURSE},',
  );
  const curseHitProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_DAMAGE_EVENT_SOURCE_BASE_MAX_HP_FRACTION, (1u << 16) | 2u},',
  );
  const curseResidualProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_DAMAGE_HOLDER_BASE_MAX_HP_FRACTION, (1u << 16) | 4u},',
  );
  const mimicHitProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_COPY_TARGET_LAST_MOVE_TO_SOURCE_SLOT, POKEMON_MOVE_COPY_ELIGIBLE_MIMIC | POKEMON_MOVE_COPY_INITIAL_PP_CAP(5)},',
  );
  const sketchHitProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_COPY_TARGET_LAST_MOVE_TO_SOURCE_SLOT, POKEMON_MOVE_COPY_ELIGIBLE_SKETCH | POKEMON_MOVE_COPY_PERSIST_BASE},',
  );
  const perishSongHitFieldProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_APPLY_VOLATILE_TO_ADMITTED_ACTIVES, POKEMON_VOLATILE_COUNTDOWN_FAINT},',
  );
  const perishSongResidualProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_RETURN_UNDEFINED, 0},',
    '    {POKEMON_HANDLER_OP_FAINT_HOLDER, 0},',
  );
  const facadeProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_GUARD_HOLDER_STATUS_MASK, ' +
      '((UINT32_C(1) << POKEMON_STATUS_BURN) | ' +
      '(UINT32_C(1) << POKEMON_STATUS_TOXIC) | ' +
      '(UINT32_C(1) << POKEMON_STATUS_PARALYSIS) | ' +
      '(UINT32_C(1) << POKEMON_STATUS_POISON) | ' +
      '(UINT32_C(1) << POKEMON_STATUS_FREEZE))},',
    '    {POKEMON_HANDLER_OP_CHAIN_Q12, 8192},',
  );
  const refreshProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_REQUIRE_HOLDER_STATUS_MASK, ' +
      '((UINT32_C(1) << POKEMON_STATUS_BURN) | ' +
      '(UINT32_C(1) << POKEMON_STATUS_TOXIC) | ' +
      '(UINT32_C(1) << POKEMON_STATUS_PARALYSIS) | ' +
      '(UINT32_C(1) << POKEMON_STATUS_POISON))},',
    '    {POKEMON_HANDLER_OP_CLEAR_MAJOR_STATUS, 0},',
  );
  const aromatherapyProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_CLEAR_USER_TEAM_MAJOR_STATUS, 0},',
  );
  const healBellProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_CLEAR_USER_TEAM_MAJOR_STATUS, ' +
      '(1u << 16)},',
  );
  const freezeBeforeMoveProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_RANDOM_CURE_OR_REQUIRE_DEFROST, ' +
      '(POKEMON_DRAW_FREEZE_THAW << 24) | (1u << 16) | (5u << 8)},',
  );
  const freezeModifyMoveProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_GUARD_HOLDER_ALIVE, 0},',
    '    {POKEMON_HANDLER_OP_GUARD_MOVE_DEFROST, 0},',
    '    {POKEMON_HANDLER_OP_CLEAR_MAJOR_STATUS, 0},',
  );
  const freezeDamagingHitProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_GUARD_BASE_MOVE_TYPE, POKEMON_GEN3_TYPE_FIRE},',
    '    {POKEMON_HANDLER_OP_GUARD_HOLDER_ALIVE, 0},',
    '    {POKEMON_HANDLER_OP_CLEAR_MAJOR_STATUS, 0},',
  );
  const obliviousImmunityProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_GUARD_VOLATILE_KIND, POKEMON_VOLATILE_ATTRACT},',
    '    {POKEMON_HANDLER_OP_RETURN_FALSE, 0},',
  );
  const obliviousUpdateProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_GUARD_HOLDER_VOLATILE_KIND, POKEMON_VOLATILE_ATTRACT},',
    '    {POKEMON_HANDLER_OP_REMOVE_HOLDER_VOLATILE_KIND, POKEMON_VOLATILE_ATTRACT},',
  );
  const rolePlayTryHitProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_REQUIRE_ABILITY_TRANSFER_ALLOWED, ' +
      '(POKEMON_ABILITY_SEMANTIC_CANT_SUPPRESS << 16) | ' +
      'POKEMON_ABILITY_SEMANTIC_FAIL_ROLE_PLAY},',
  );
  const rolePlayHitProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_REPLACE_SOURCE_ABILITY_FROM_EVENT_TARGET, 0},',
  );
	const skillSwapHitProgramOffset = baseHandlerPrograms.length;
	baseHandlerPrograms.push(
		'    {POKEMON_HANDLER_OP_SWAP_SOURCE_TARGET_ABILITIES, 0},',
	);
	const sourceTrapHitProgramOffset = baseHandlerPrograms.length;
	baseHandlerPrograms.push(
		'    {POKEMON_HANDLER_OP_TRY_ADD_EVENT_TARGET_VOLATILE_FROM_SOURCE, POKEMON_VOLATILE_TRAPPED},',
	);
	const trappedTrapPokemonProgramOffset = baseHandlerPrograms.length;
	baseHandlerPrograms.push(
		'    {POKEMON_HANDLER_OP_GUARD_OWNER_SOURCE_ACTIVE, 0},',
		'    {POKEMON_HANDLER_OP_DISALLOW_TARGET_SWITCHES, 0},',
	);
  const psychUpProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_COPY_EVENT_TARGET_BOOST_STAGES_TO_SOURCE, 0},',
  );
  const hazeProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_CLEAR_LIVING_ACTIVE_BOOST_STAGES, 0},',
  );
  const sleepStartProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_INITIALIZE_OWNER_SLEEP_UNIFORM, (POKEMON_DRAW_SLEEP_DURATION << 24) | (2u << 16) | (6u << 8)},',
  );
  const restTryProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_RETURN_FALSE_IF_HOLDER_STATUS_MASK, (UINT32_C(1) << POKEMON_STATUS_SLEEP)},',
    '    {POKEMON_HANDLER_OP_RETURN_NULL_IF_HOLDER_HP_FULL, 0},',
    '    {POKEMON_HANDLER_OP_RETURN_NULL_IF_HOLDER_ABILITY_BLOCKS_STATUS, POKEMON_STATUS_SLEEP},',
  );
  const restHitProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_REPLACE_HOLDER_MAJOR_STATUS, POKEMON_STATUS_SLEEP},',
    '    {POKEMON_HANDLER_OP_SET_HOLDER_STATUS_COUNTER, (POKEMON_STATUS_COUNTER_SLEEP_TIME << 16) | 3u},',
    '    {POKEMON_HANDLER_OP_HEAL_MAX_HP_FRACTION, 1},',
  );
  const synchronizeProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_GUARD_SOURCE_NOT_TARGET, 0},',
    '    {POKEMON_HANDLER_OP_GUARD_EVENT_STATUS_MASK, (UINT32_C(1) << POKEMON_STATUS_BURN) | (UINT32_C(1) << POKEMON_STATUS_TOXIC) | (UINT32_C(1) << POKEMON_STATUS_PARALYSIS) | (UINT32_C(1) << POKEMON_STATUS_POISON)},',
    '    {POKEMON_HANDLER_OP_REFLECT_EVENT_STATUS_TO_SOURCE, (POKEMON_STATUS_TOXIC << 8) | POKEMON_STATUS_POISON},',
  );
  const sleepBeforeMoveProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_ADVANCE_OWNER_SLEEP, POKEMON_GEN3_ABILITY_EARLYBIRD},',
  );
  const sleepSwitchInProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_RESTORE_OWNER_SLEEP_SKIPPED, 0},',
  );
  const snoreTryProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_REQUIRE_HOLDER_STATUS_MASK, (UINT32_C(1) << POKEMON_STATUS_SLEEP)},',
  );
  const intimidateProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_BOOST_OPPOSING_ACTIVES_EXCEPT_VOLATILE, (POKEMON_VOLATILE_SUBSTITUTE << 16) | (POKEMON_STAT_ATK << 8) | UINT8_MAX},',
  );
  const traceProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_REPLACE_HOLDER_ABILITY_FROM_TARGET, POKEMON_HANDLER_TARGET_RANDOM_ACTIVE_FOE},',
  );
  const colorChangeProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_SET_HOLDER_EFFECTIVE_TYPE_FROM_MOVE, 0},',
  );
  const conversion2ProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_SAMPLE_SOURCE_TYPE_RESPONSE, 1},',
  );
  const camouflageProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_SET_HOLDER_EFFECTIVE_TYPE_LITERAL, POKEMON_GEN3_TYPE_NORMAL},',
  );
  const conversionProgramOffset = baseHandlerPrograms.length;
  const curseCatalogId = dex.moves.get('curse').num;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_SAMPLE_HOLDER_MOVE_SLOT_TYPE, ' +
      `(POKEMON_DRAW_MOVE_TYPE_SELECTION << 24) | ${curseCatalogId}u},`,
  );
  const focusPunchHitProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_GUARD_MOVE_CATEGORY_MASK, (UINT32_C(1) << POKEMON_CATEGORY_PHYSICAL) | (UINT32_C(1) << POKEMON_CATEGORY_SPECIAL)},',
    '    {POKEMON_HANDLER_OP_SET_OWNER_VOLATILE_COUNTER, 1},',
  );
  const focusPunchTryAddVolatileProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_GUARD_VOLATILE_KIND, POKEMON_VOLATILE_FLINCH},',
    '    {POKEMON_HANDLER_OP_RETURN_NULL, 0},',
  );
  const focusPunchTryProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_GUARD_HOLDER_VOLATILE_COUNTER_AT_LEAST, (POKEMON_VOLATILE_PREPARED_ACTION << 16) | 1u},',
    '    {POKEMON_HANDLER_OP_SUPPRESS_ACTIVE_MOVE_PROTOCOL_TARGET, 0},',
    '    {POKEMON_HANDLER_OP_RETURN_NULL, 0},',
  );
  const destinyBondPrepareHitProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_REMOVE_HOLDER_VOLATILE_KIND, POKEMON_VOLATILE_SOURCE_FAINT_RESPONSE},',
  );
  const destinyBondBeforeMoveProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_GUARD_SOURCE_EFFECT_NOT, (POKEMON_SOURCE_EFFECT_MOVE << 24) | POKEMON_GEN3_MOVE_DESTINYBOND},',
    '    {POKEMON_HANDLER_OP_REMOVE_OWNER_VOLATILE, 0},',
  );
  const destinyBondRemoveProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_REMOVE_OWNER_VOLATILE, 0},',
  );
  const destinyBondFaintProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_GUARD_DAMAGE_FROM_MOVE_SOURCE, 0},',
    '    {POKEMON_HANDLER_OP_GUARD_SOURCE_EFFECT_NOT, (POKEMON_SOURCE_EFFECT_MOVE << 24) | POKEMON_GEN3_MOVE_FUTURESIGHT},',
    '    {POKEMON_HANDLER_OP_GUARD_SOURCE_EFFECT_NOT, (POKEMON_SOURCE_EFFECT_MOVE << 24) | POKEMON_GEN3_MOVE_DOOMDESIRE},',
    '    {POKEMON_HANDLER_OP_GUARD_SOURCE_OPPOSES_HOLDER, 0},',
    '    {POKEMON_HANDLER_OP_FAINT_EVENT_SOURCE, 0},',
  );
  const grudgeRemoveProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_REMOVE_OWNER_VOLATILE, 0},',
  );
  const grudgeFaintProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_GUARD_DAMAGE_FROM_MOVE_SOURCE, 0},',
    '    {POKEMON_HANDLER_OP_GUARD_SOURCE_EFFECT_NOT, (POKEMON_SOURCE_EFFECT_MOVE << 24) | POKEMON_GEN3_MOVE_FUTURESIGHT},',
    '    {POKEMON_HANDLER_OP_GUARD_SOURCE_EFFECT_NOT, (POKEMON_SOURCE_EFFECT_MOVE << 24) | POKEMON_GEN3_MOVE_DOOMDESIRE},',
    '    {POKEMON_HANDLER_OP_ZERO_LIVING_EVENT_SOURCE_LAST_MOVE_PP, 0},',
  );
  const uproarTryHitProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_CLEAR_LIVING_ACTIVE_STATUS_MASK, UINT32_C(1) << POKEMON_STATUS_SLEEP},',
  );
  const uproarResidualProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_REMOVE_OWNER_IF_LAST_MOVE_FALLBACK, 0},',
  );
  const uproarLockMoveProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_RETURN_OWNER_SOURCE_MOVE_SELECTOR, 0},',
  );
  const uproarSetStatusProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_GUARD_EVENT_STATUS_MASK, UINT32_C(1) << POKEMON_STATUS_SLEEP},',
    '    {POKEMON_HANDLER_OP_RETURN_NULL, 0},',
  );
  const imprisonTryHitProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_REQUIRE_ACTIVE_FOE_SHARES_HOLDER_MOVE, 0},',
  );
  const imprisonDisableMoveProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_APPEND_HOLDER_MOVES_TO_EVENT_RESTRICTIONS, 0},',
  );
  const imprisonBeforeMoveProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_REJECT_EVENT_MOVE_SHARED_WITH_HOLDER, 0},',
  );
  const paralysisBeforeMoveProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_GUARD_RANDOM_CHANCE, (POKEMON_DRAW_PARALYSIS << 24) | (1u << 16) | 4u},',
    '    {POKEMON_HANDLER_OP_RETURN_FALSE, 0},',
  );
  const deepSeaScaleProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_GUARD_HOLDER_SPECIES_PAIR, (POKEMON_GEN3_SPECIES_CLAMPERL << 16) | POKEMON_GEN3_SPECIES_CLAMPERL},',
    '    {POKEMON_HANDLER_OP_CHAIN_Q12, 8192},',
  );
  const deepSeaToothProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_GUARD_HOLDER_SPECIES_PAIR, (POKEMON_GEN3_SPECIES_CLAMPERL << 16) | POKEMON_GEN3_SPECIES_CLAMPERL},',
    '    {POKEMON_HANDLER_OP_CHAIN_Q12, 8192},',
  );
  const lightBallProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_GUARD_HOLDER_SPECIES_PAIR, (POKEMON_GEN3_SPECIES_PIKACHU << 16) | POKEMON_GEN3_SPECIES_PIKACHU},',
    '    {POKEMON_HANDLER_OP_CHAIN_Q12, 8192},',
  );
  const machoBraceProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_CHAIN_Q12, 2048},',
  );
  /* The resolved Gen 3 OU format bans both predicate-positive base species.
   * Keep the observable callbacks, but specialize their legal-domain branch. */
  const soulDewProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_RETURN_UNDEFINED, 0},',
  );
  const metalPowderProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_GUARD_HOLDER_SPECIES_PAIR, (POKEMON_GEN3_SPECIES_DITTO << 16) | POKEMON_GEN3_SPECIES_DITTO},',
    '    {POKEMON_HANDLER_OP_CHAIN_Q12, 8192},',
  );
  const whiteHerbProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_GUARD_HOLDER_HAS_NEGATIVE_BOOST, 0},',
    '    {POKEMON_HANDLER_OP_USE_HANDLER_OWNED_HELD_ITEM, 0},',
    '    {POKEMON_HANDLER_OP_CLEAR_HOLDER_NEGATIVE_BOOST_STAGES, 0},',
  );
  const mentalHerbProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_GUARD_HOLDER_VOLATILE_KIND, POKEMON_VOLATILE_ATTRACT},',
    '    {POKEMON_HANDLER_OP_USE_HANDLER_OWNED_HELD_ITEM, 0},',
    '    {POKEMON_HANDLER_OP_REMOVE_HOLDER_VOLATILE_KIND, POKEMON_VOLATILE_ATTRACT},',
  );
  const falseSwipeDamageProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_CAP_DAMAGE_TO_HOLDER_HP_MINUS_ONE, 0},',
  );
  const endureDamageProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_GUARD_DAMAGE_KIND_ANY, POKEMON_DAMAGE_EVENT_ORDINARY_MOVE},',
    '    {POKEMON_HANDLER_OP_CAP_DAMAGE_TO_HOLDER_HP_MINUS_ONE, 0},',
  );
	const focusBandDamageProgramOffset = baseHandlerPrograms.length;
	baseHandlerPrograms.push(
		'    {POKEMON_HANDLER_OP_GUARD_RANDOM_CHANCE, (POKEMON_DRAW_FOCUS_BAND << 24) | (1 << 16) | 10},',
		'    {POKEMON_HANDLER_OP_GUARD_DAMAGE_KIND_ANY, POKEMON_DAMAGE_EVENT_ORDINARY_MOVE},',
		'    {POKEMON_HANDLER_OP_CAP_DAMAGE_TO_HOLDER_HP_MINUS_ONE, 0},',
	);
	const toxicStageResetProgramOffset = baseHandlerPrograms.length;
	baseHandlerPrograms.push(
		'    {POKEMON_HANDLER_OP_SET_HOLDER_STATUS_COUNTER, (POKEMON_STATUS_COUNTER_TOXIC_STAGE << 16)},',
	);
	const leppaBerryProgramOffset = baseHandlerPrograms.length;
	baseHandlerPrograms.push(
		'    {POKEMON_HANDLER_OP_GUARD_HOLDER_HAS_ZERO_MOVE_PP, 0},',
		'    {POKEMON_HANDLER_OP_EAT_HELD_BERRY, 0},',
		'    {POKEMON_HANDLER_OP_RESTORE_FIRST_HOLDER_MOVE_PP, 10},',
	);
	const kingsRockProgramOffset = baseHandlerPrograms.length;
	baseHandlerPrograms.push(
		'    {POKEMON_HANDLER_OP_GUARD_MOVE_MODIFIER_TAG, 0},',
		'    {POKEMON_HANDLER_OP_APPEND_ACTIVE_MOVE_VOLATILE_SECONDARY, (10u << 16) | POKEMON_VOLATILE_FLINCH},',
	);
	const shellBellProgramOffset = baseHandlerPrograms.length;
	baseHandlerPrograms.push(
		'    {POKEMON_HANDLER_OP_HEAL_HOLDER_FROM_MOVE_DAMAGE_FRACTION, (1u << 16) | 8u},',
	);
	const fakeOutProgramOffset = baseHandlerPrograms.length;
	baseHandlerPrograms.push(
		'    {POKEMON_HANDLER_OP_RETURN_FALSE_IF_HOLDER_MOVE_ACTIONS_ABOVE, 1},',
	);
	const followMeProgramOffset = baseHandlerPrograms.length;
	baseHandlerPrograms.push(
		'    {POKEMON_HANDLER_OP_RETURN_FALSE, 0},',
	);
	const counterStartProgramOffset = baseHandlerPrograms.length;
	baseHandlerPrograms.push(
		'    {POKEMON_HANDLER_OP_INITIALIZE_OWNER_RETALIATION, 0},',
	);
	const counterDamageProgramOffset = baseHandlerPrograms.length;
	baseHandlerPrograms.push(
		'    {POKEMON_HANDLER_OP_GUARD_DAMAGE_RETALIATION_CLASS, POKEMON_RETALIATION_PHYSICAL},',
		'    {POKEMON_HANDLER_OP_CAPTURE_OWNER_RETALIATION_X2, 0},',
	);
	const counterTryProgramOffset = baseHandlerPrograms.length;
	baseHandlerPrograms.push(
		'    {POKEMON_HANDLER_OP_REQUIRE_OWNER_RETALIATION_CAPTURE, POKEMON_GEN3_CONDITION_VOLATILE_COUNTER},',
	);
	const mirrorCoatStartProgramOffset = baseHandlerPrograms.length;
	baseHandlerPrograms.push(
		'    {POKEMON_HANDLER_OP_INITIALIZE_OWNER_RETALIATION, 0},',
	);
	const mirrorCoatDamageProgramOffset = baseHandlerPrograms.length;
	baseHandlerPrograms.push(
		'    {POKEMON_HANDLER_OP_GUARD_DAMAGE_RETALIATION_CLASS, POKEMON_RETALIATION_SPECIAL},',
		'    {POKEMON_HANDLER_OP_CAPTURE_OWNER_RETALIATION_X2, 0},',
	);
	const mirrorCoatTryProgramOffset = baseHandlerPrograms.length;
	baseHandlerPrograms.push(
		'    {POKEMON_HANDLER_OP_REQUIRE_OWNER_RETALIATION_CAPTURE, POKEMON_GEN3_CONDITION_VOLATILE_MIRRORCOAT},',
	);
	const bideStartProgramOffset = baseHandlerPrograms.length;
	baseHandlerPrograms.push(
		'    {POKEMON_HANDLER_OP_INITIALIZE_OWNER_STORED_DAMAGE, 0},',
	);
	const bideDamageProgramOffset = baseHandlerPrograms.length;
	baseHandlerPrograms.push(
		'    {POKEMON_HANDLER_OP_GUARD_DAMAGE_FROM_MOVE_SOURCE, 0},',
		'    {POKEMON_HANDLER_OP_ACCUMULATE_OWNER_STORED_DAMAGE, 0},',
	);
	const bideReleaseProgramOffset = baseHandlerPrograms.length;
	baseHandlerPrograms.push(
		'    {POKEMON_HANDLER_OP_RELEASE_OWNER_STORED_DAMAGE_HIT, 1},',
	);
	const bideCleanupProgramOffset = baseHandlerPrograms.length;
	baseHandlerPrograms.push(
		'    {POKEMON_HANDLER_OP_REMOVE_OWNER_VOLATILE, 0},',
	);
	const rageHitProgramOffset = baseHandlerPrograms.length;
	baseHandlerPrograms.push(
		'    {POKEMON_HANDLER_OP_GUARD_SOURCE_NOT_TARGET, 0},',
		'    {POKEMON_HANDLER_OP_GUARD_MOVE_CATEGORY_MASK, (UINT32_C(1) << POKEMON_CATEGORY_PHYSICAL) | (UINT32_C(1) << POKEMON_CATEGORY_SPECIAL)},',
		'    {POKEMON_HANDLER_OP_BOOST_HOLDER_STAT, (POKEMON_STAT_ATK << 8) | UINT8_C(1)},',
	);
	const rageBeforeMoveProgramOffset = baseHandlerPrograms.length;
	baseHandlerPrograms.push(
		'    {POKEMON_HANDLER_OP_REMOVE_OWNER_VOLATILE, 0},',
	);
	const minimizeDamageProgramOffset = baseHandlerPrograms.length;
	baseHandlerPrograms.push(
		`    {POKEMON_HANDLER_OP_GUARD_MOVE_FLAG, ${MOVE_FLAGS.indexOf('minimize')}},`,
		'    {POKEMON_HANDLER_OP_CHAIN_Q12, 8192},',
	);
	const furyCutterBasePowerProgramOffset = baseHandlerPrograms.length;
	baseHandlerPrograms.push(
		'    {POKEMON_HANDLER_OP_ENSURE_HOLDER_VOLATILE, POKEMON_VOLATILE_FURY_CUTTER},',
		'    {POKEMON_HANDLER_OP_MULTIPLY_RELAY_BY_HOLDER_VOLATILE_COUNTER, POKEMON_VOLATILE_FURY_CUTTER},',
	);
	const furyCutterStartProgramOffset = baseHandlerPrograms.length;
	baseHandlerPrograms.push(
		'    {POKEMON_HANDLER_OP_SET_OWNER_VOLATILE_COUNTER, 1},',
	);
	const furyCutterRestartProgramOffset = baseHandlerPrograms.length;
	baseHandlerPrograms.push(
		'    {POKEMON_HANDLER_OP_ADVANCE_OWNER_VOLATILE_COUNTER, (2u << 16) | 16u},',
	);
	const furyCutterHitProgramOffset = baseHandlerPrograms.length;
	baseHandlerPrograms.push(
		'    {POKEMON_HANDLER_OP_TRY_ADD_OR_RESTART_SOURCE_VOLATILE, POKEMON_VOLATILE_FURY_CUTTER},',
	);
	const rolloutModifyMoveProgramOffset = baseHandlerPrograms.length;
	baseHandlerPrograms.push(
		'    {POKEMON_HANDLER_OP_INSTALL_LOCKED_RAMP_IF_TARGET_AWAKE, 1},',
	);
	const rolloutBasePowerProgramOffset = baseHandlerPrograms.length;
	baseHandlerPrograms.push(
		'    {POKEMON_HANDLER_OP_APPLY_LOCKED_RAMP_BASE_POWER, 1},',
	);
	const rolloutLockMoveProgramOffset = baseHandlerPrograms.length;
	baseHandlerPrograms.push(
		'    {POKEMON_HANDLER_OP_RETURN_OWNER_SOURCE_MOVE_SELECTOR, 0},',
	);
	const rolloutResidualProgramOffset = baseHandlerPrograms.length;
	baseHandlerPrograms.push(
		'    {POKEMON_HANDLER_OP_REMOVE_OWNER_IF_LAST_MOVE_FALLBACK, 0},',
	);
	const iceBallModifyMoveProgramOffset = baseHandlerPrograms.length;
	baseHandlerPrograms.push(
		'    {POKEMON_HANDLER_OP_INSTALL_LOCKED_RAMP_IF_TARGET_AWAKE, 2},',
	);
	const iceBallBasePowerProgramOffset = baseHandlerPrograms.length;
	baseHandlerPrograms.push(
		'    {POKEMON_HANDLER_OP_APPLY_LOCKED_RAMP_BASE_POWER, 2},',
	);
	const iceBallLockMoveProgramOffset = baseHandlerPrograms.length;
	baseHandlerPrograms.push(
		'    {POKEMON_HANDLER_OP_RETURN_OWNER_SOURCE_MOVE_SELECTOR, 0},',
	);
	const iceBallResidualProgramOffset = baseHandlerPrograms.length;
	baseHandlerPrograms.push(
		'    {POKEMON_HANDLER_OP_REMOVE_OWNER_IF_LAST_MOVE_FALLBACK, 0},',
	);
	const stockpileTryProgramOffset = baseHandlerPrograms.length;
	baseHandlerPrograms.push(
		'    {POKEMON_HANDLER_OP_RETURN_FALSE_IF_HOLDER_VOLATILE_COUNTER_AT_LEAST, (POKEMON_VOLATILE_STOCKPILE << 16) | 3u},',
	);
	const stockpileStartProgramOffset = baseHandlerPrograms.length;
	baseHandlerPrograms.push(
		'    {POKEMON_HANDLER_OP_SET_OWNER_VOLATILE_COUNTER, 1},',
	);
	const stockpileRestartProgramOffset = baseHandlerPrograms.length;
	baseHandlerPrograms.push(
		'    {POKEMON_HANDLER_OP_INCREMENT_OWNER_VOLATILE_COUNTER_UP_TO, 3},',
	);
	const spitUpTryProgramOffset = baseHandlerPrograms.length;
	baseHandlerPrograms.push(
		'    {POKEMON_HANDLER_OP_RETURN_FALSE_UNLESS_HOLDER_VOLATILE, (POKEMON_VOLATILE_STOCKPILE << 16)},',
	);
	const spitUpBasePowerProgramOffset = baseHandlerPrograms.length;
	baseHandlerPrograms.push(
		'    {POKEMON_HANDLER_OP_SET_RELAY_FROM_HOLDER_VOLATILE_COUNTER_TIMES, (POKEMON_VOLATILE_STOCKPILE << 16) | 100u},',
	);
	const removeStockpileProgramOffset = baseHandlerPrograms.length;
	baseHandlerPrograms.push(
		'    {POKEMON_HANDLER_OP_REMOVE_HOLDER_VOLATILE_KIND, POKEMON_VOLATILE_STOCKPILE},',
	);
	const swallowTryProgramOffset = baseHandlerPrograms.length;
	baseHandlerPrograms.push(
		'    {POKEMON_HANDLER_OP_RETURN_FALSE_UNLESS_HOLDER_VOLATILE, (POKEMON_VOLATILE_STOCKPILE << 16)},',
	);
	const swallowHitProgramOffset = baseHandlerPrograms.length;
	baseHandlerPrograms.push(
		'    {POKEMON_HANDLER_OP_HEAL_HOLDER_BY_COUNTER_POLICY, 1},',
		'    {POKEMON_HANDLER_OP_REMOVE_HOLDER_VOLATILE_KIND, POKEMON_VOLATILE_STOCKPILE},',
		'    {POKEMON_HANDLER_OP_RETURN_NOT_FAIL, 0},',
	);
	const hiddenPowerModifyMoveProgramOffset = baseHandlerPrograms.length;
	baseHandlerPrograms.push(
		'    {POKEMON_HANDLER_OP_APPLY_ACTIVE_MOVE_PERSONAL_PROFILE, 1},',
	);
  const lockOnTryHitProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_GUARD_HOLDER_VOLATILE_KIND, POKEMON_VOLATILE_LOCK_ON},',
    '    {POKEMON_HANDLER_OP_RETURN_FALSE, 0},',
  );
  const lockOnAccuracyProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_GUARD_OWNER_SOURCE_IS_EVENT_TARGET, 0},',
    '    {POKEMON_HANDLER_OP_RETURN_TRUE, 0},',
  );
  const lockOnInvulnerabilityProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_GUARD_OWNER_SOURCE_IS_EVENT_TARGET, 0},',
    '    {POKEMON_HANDLER_OP_RETURN_NUMBER_ZERO, 0},',
  );
	const wonderGuardProgramOffset = baseHandlerPrograms.length;
	const typedMoveMask = TYPES.filter(type => type !== '???').map(type =>
		`(UINT32_C(1) << POKEMON_GEN3_TYPE_${cName(type)})`).join(' | ');
	baseHandlerPrograms.push(
		'    {POKEMON_HANDLER_OP_GUARD_SOURCE_NOT_TARGET, 0},',
		'    {POKEMON_HANDLER_OP_GUARD_MOVE_CATEGORY_MASK, ' +
			'(UINT32_C(1) << POKEMON_CATEGORY_PHYSICAL) | ' +
			'(UINT32_C(1) << POKEMON_CATEGORY_SPECIAL)},',
		`    {POKEMON_HANDLER_OP_GUARD_MOVE_TYPE_MASK, ${typedMoveMask}},`,
		'    {POKEMON_HANDLER_OP_REQUIRE_HOLDER_TYPE_EFFECTIVENESS_ABOVE, 4},',
	);
  const choiceBandModifyAtkProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push('    {POKEMON_HANDLER_OP_CHAIN_Q12, 6144},');
  const choiceBandAfterMoveProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_TRY_ADD_OR_RESTART_HOLDER_VOLATILE, POKEMON_VOLATILE_CHOICE_LOCK},',
  );
  const cuteCharmProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    `    {POKEMON_HANDLER_OP_GUARD_MOVE_FLAG, ${MOVE_FLAGS.indexOf('contact')}},`,
    '    {POKEMON_HANDLER_OP_GUARD_RANDOM_CHANCE, (POKEMON_DRAW_CONTACT_RESPONSE << 24) | (1 << 16) | 3},',
    '    {POKEMON_HANDLER_OP_TRY_ADD_EVENT_SOURCE_VOLATILE_FROM_HOLDER, POKEMON_VOLATILE_ATTRACT},',
  );
  const attractStartProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_REQUIRE_SOURCE_OPPOSITE_GENDER_TO_HOLDER, 0},',
  );
  const attractBeforeMoveProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_GUARD_RANDOM_CHANCE, (POKEMON_DRAW_ATTRACTION_ACTION << 24) | (1 << 16) | 2},',
    '    {POKEMON_HANDLER_OP_RETURN_FALSE, 0},',
  );
  const attractUpdateProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_REMOVE_OWNER_VOLATILE_IF_SOURCE_INACTIVE, 0},',
  );
  const sportProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_GUARD_MOVE_TYPE, POKEMON_GEN3_TYPE_ELECTRIC},',
    '    {POKEMON_HANDLER_OP_CHAIN_Q12, 2048},',
    '    {POKEMON_HANDLER_OP_GUARD_MOVE_TYPE, POKEMON_GEN3_TYPE_FIRE},',
    '    {POKEMON_HANDLER_OP_CHAIN_Q12, 2048},',
  );
  const suctionCupsDragOutProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push('    {POKEMON_HANDLER_OP_RETURN_NULL, 0},');
  const ingrainResidualProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_HEAL_MAX_HP_FRACTION, 16},',
    '    {POKEMON_HANDLER_OP_DISALLOW_TARGET_SWITCHES, 0},',
    '    {POKEMON_HANDLER_OP_RETURN_NULL, 0},',
  );
  const pursuitBeforeSwitchOutProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_CLAIM_QUEUED_SELECTED_MOVE, 0},',
  );
  const chargeBasePowerProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_GUARD_MOVE_TYPE, POKEMON_GEN3_TYPE_ELECTRIC},',
    '    {POKEMON_HANDLER_OP_CHAIN_Q12, 8192},',
  );
  const chargeCleanupProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_GUARD_SOURCE_EFFECT_NOT, (POKEMON_SOURCE_EFFECT_MOVE << 24) | POKEMON_GEN3_MOVE_CHARGE},',
    '    {POKEMON_HANDLER_OP_REMOVE_OWNER_VOLATILE, 0},',
  );
  const leechSeedTryImmunityProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_GUARD_TARGET_CURRENT_TYPE, POKEMON_GEN3_TYPE_GRASS},',
    '    {POKEMON_HANDLER_OP_RETURN_FALSE, 0},',
  );
  const leechSeedResidualProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_TRANSFER_HOLDER_MAX_HP_FRACTION_TO_SOURCE_POSITION, (1u << 16) | 8u},',
  );
  const liquidOozeTryHealProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_GUARD_SOURCE_EFFECT_NOT, (POKEMON_SOURCE_EFFECT_MOVE << 24) | POKEMON_GEN3_MOVE_DREAMEATER},',
    '    {POKEMON_HANDLER_OP_DAMAGE_EVENT_TARGET_BY_RELAY_IMMEDIATE, 0},',
    '    {POKEMON_HANDLER_OP_RETURN_NUMBER_ZERO, 0},',
  );
  const rapidSpinAfterSubDamageProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_GUARD_HOLDER_ALIVE, 0},',
    '    {POKEMON_HANDLER_OP_REMOVE_HOLDER_VOLATILE_KIND, POKEMON_VOLATILE_LEECH_SEED},',
    '    {POKEMON_HANDLER_OP_REMOVE_SIDE_CONDITION, (POKEMON_SIDE_SELECTOR_SOURCE << 24) | POKEMON_GEN3_CONDITION_SIDE_SPIKES},',
    '    {POKEMON_HANDLER_OP_REMOVE_HOLDER_VOLATILE_KIND, POKEMON_VOLATILE_PARTIALLY_TRAPPED},',
  );
  const flashFire = dex.abilities.get('flashfire');
  const flashFireTryHitSource = String(flashFire.onTryHit);
  const flashFireEndSource = String(flashFire.onEnd);
  const flashFireStartSource = String(flashFire.condition?.onStart);
  const flashFireModifyDamageSource =
    String(flashFire.condition?.onModifyDamagePhase1);
  const flashFireConditionEndSource = String(flashFire.condition?.onEnd);
  if (typeof flashFire.onTryHit !== 'function' ||
      !/move\.type === ["']Fire["']/.test(flashFireTryHitSource) ||
      !/move\.id === ["']willowisp["']/.test(flashFireTryHitSource) ||
      !/target\.hasType\(["']Fire["']\)/.test(flashFireTryHitSource) ||
      !/target\.volatiles\[["']substitute["']\]/.test(flashFireTryHitSource) ||
      !/target\.status === ["']frz["']/.test(flashFireTryHitSource) ||
      !/target\.addVolatile\(["']flashfire["']\)/.test(flashFireTryHitSource) ||
      typeof flashFire.onEnd !== 'function' ||
      !/removeVolatile\(["']flashfire["']\)/.test(flashFireEndSource) ||
      flashFire.condition?.noCopy !== true ||
      typeof flashFire.condition.onStart !== 'function' ||
      !flashFireStartSource.includes("ability: Flash Fire") ||
      typeof flashFire.condition.onModifyDamagePhase1 !== 'function' ||
      !/move\.type === ["']Fire["']/.test(flashFireModifyDamageSource) ||
      !flashFireModifyDamageSource.includes('chainModify(1.5)') ||
      typeof flashFire.condition.onEnd !== 'function' ||
      !flashFireConditionEndSource.includes("ability: Flash Fire")) {
    throw new Error('resolved Gen 3 Flash Fire family changed');
  }
  const flashFireTryHitProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_GUARD_SOURCE_NOT_TARGET, 0},',
    '    {POKEMON_HANDLER_OP_GUARD_MOVE_TYPE, POKEMON_GEN3_TYPE_FIRE},',
    '    {POKEMON_HANDLER_OP_GUARD_TAGGED_STATUS_MOVE_TARGET_ELIGIBLE, (1u << 16) | POKEMON_GEN3_TYPE_FIRE},',
    '    {POKEMON_HANDLER_OP_GUARD_HOLDER_STATUS_NOT_MASK, UINT32_C(1) << POKEMON_STATUS_FREEZE},',
    '    {POKEMON_HANDLER_OP_TRY_ADD_OR_RESTART_HOLDER_VOLATILE, POKEMON_VOLATILE_FLASH_FIRE},',
    '    {POKEMON_HANDLER_OP_RETURN_NULL, 0},',
  );
  const flashFireAbilityEndProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_REMOVE_HOLDER_VOLATILE_KIND, POKEMON_VOLATILE_FLASH_FIRE},',
  );
  const flashFireModifyDamageProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_GUARD_OWNER_SOURCE_ABILITY_ACTIVE, 0},',
    '    {POKEMON_HANDLER_OP_GUARD_MOVE_TYPE, POKEMON_GEN3_TYPE_FIRE},',
    '    {POKEMON_HANDLER_OP_CHAIN_Q12, 6144},',
  );
  const teleport = dex.moves.get('teleport');
  if (teleport.onTry !== false || teleport.basePower !== 0 ||
      teleport.category !== 'Status' || teleport.target !== 'self' ||
      teleport.priority !== 0 || teleport.selfSwitch) {
    throw new Error('resolved Gen 3 Teleport rejection changed');
  }
  const teleportTryProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push('    {POKEMON_HANDLER_OP_RETURN_FALSE, 0},');
  const minus = dex.abilities.get('minus');
  const plus = dex.abilities.get('plus');
  if (!String(minus.onModifySpA).includes('this.getAllActive()') ||
      (!String(minus.onModifySpA).includes("active.hasAbility('plus')") &&
        !String(minus.onModifySpA).includes('active.hasAbility("plus")')) ||
      !String(plus.onModifySpA).includes('this.getAllActive()') ||
      (!String(plus.onModifySpA).includes("active.hasAbility('minus')") &&
        !String(plus.onModifySpA).includes('active.hasAbility("minus")'))) {
    throw new Error('resolved Gen 3 Plus/Minus relation changed');
  }
  const minusModifySpAProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_GUARD_ANY_LIVING_ACTIVE_ABILITY, POKEMON_GEN3_ABILITY_PLUS},',
    '    {POKEMON_HANDLER_OP_CHAIN_Q12, 6144},',
    '    {POKEMON_HANDLER_OP_GUARD_ANY_LIVING_ACTIVE_ABILITY, POKEMON_GEN3_ABILITY_MINUS},',
    '    {POKEMON_HANDLER_OP_CHAIN_Q12, 6144},',
  );
  const foresightTryHitProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_RETURN_UNDEFINED, 0},',
  );
  const foresightNegateImmunityProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_GUARD_TARGET_CURRENT_TYPE, POKEMON_GEN3_TYPE_GHOST},',
    '    {POKEMON_HANDLER_OP_GUARD_MOVE_TYPE_MASK, ' +
      '((UINT32_C(1) << POKEMON_GEN3_TYPE_NORMAL) | ' +
      '(UINT32_C(1) << POKEMON_GEN3_TYPE_FIGHTING))},',
    '    {POKEMON_HANDLER_OP_RETURN_FALSE, 0},',
  );
  const foresightModifyBoostProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_ZERO_POSITIVE_BOOST_STAT, POKEMON_STAT_EVASION},',
  );
  const spiteHitProgramOffset = baseHandlerPrograms.length;
  baseHandlerPrograms.push(
    '    {POKEMON_HANDLER_OP_DEDUCT_TARGET_LAST_MOVE_PP_UNIFORM, ' +
      '(POKEMON_DRAW_MOVE_PP_REDUCTION << 24) | (2u << 16) | (6u << 8)},',
  );
  const typeBoostProgramOffset = baseHandlerPrograms.length;
  {
    const burn = dex.conditions.get('brn');
    const poison = dex.conditions.get('psn');
    const toxic = dex.conditions.get('tox');
    const burnSource = String(burn.onResidual);
    const poisonSource = String(poison.onResidual);
    const toxicSource = String(toxic.onResidual);
    if (burn.onResidualOrder !== 10 || burn.onResidualSubOrder !== 6 ||
        poison.onResidualOrder !== 10 || poison.onResidualSubOrder !== 6 ||
        toxic.onResidualOrder !== 10 || toxic.onResidualSubOrder !== 6 ||
        !burnSource.includes('pokemon.baseMaxhp / 8') ||
        !poisonSource.includes('pokemon.baseMaxhp / 8') ||
        !toxicSource.includes('this.effectState.stage < 15') ||
        !toxicSource.includes('this.effectState.stage++') ||
        !toxicSource.includes('pokemon.baseMaxhp / 16') ||
        !toxicSource.includes('this.effectState.stage')) {
      throw new Error('resolved Gen 3 residual major-status family changed');
    }
  }
  lines.push('};', '',
    'static const PokemonStatusResidualPolicy STATUS_RESIDUAL_POLICIES[] = {',
    '    {POKEMON_GEN3_CONDITION_STATUS_BRN, POKEMON_STATUS_BURN, POKEMON_RESIDUAL_FORMULA_BURN, POKEMON_STATUS_RESIDUAL_STATELESS},',
    '    {POKEMON_GEN3_CONDITION_STATUS_PSN, POKEMON_STATUS_POISON, POKEMON_RESIDUAL_FORMULA_POISON, POKEMON_STATUS_RESIDUAL_TICK},',
    '    {POKEMON_GEN3_CONDITION_STATUS_TOX, POKEMON_STATUS_TOXIC, POKEMON_RESIDUAL_FORMULA_TOXIC, POKEMON_STATUS_RESIDUAL_ESCALATE},',
    '};', '', 'static const PokemonHandlerDescriptor HANDLERS[] = {');
  lines.push('    {POKEMON_HANDLER_EVENT_TRY_HIT, POKEMON_GEN3_HANDLER_WATER_ABSORB,');
  lines.push('        POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_WATERABSORB, 0, 0, 7,');
  lines.push('        POKEMON_GEN3_TYPE_WATER, 0, 0, 0, 0, 4, 0, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onTryHit"},');
  lines.push('    {POKEMON_HANDLER_EVENT_MODIFY_ATK, POKEMON_GEN3_HANDLER_GUTS,');
  lines.push('        POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_GUTS, 0, 5, 7,');
  lines.push('        0, 6144, 1, 0, 4, 2, 0, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onModifyAtk"},');
  lines.push('    {POKEMON_HANDLER_EVENT_MODIFY_ATK, POKEMON_GEN3_HANDLER_BLACK_BELT,');
  {
    const item = dex.items.get('blackbelt');
    const source = String(item.onModifyAtk);
    if (typeof item.onModifyAtk !== 'function' || item.onModifyAtkPriority !== 1 ||
        item.onBasePower !== undefined ||
        !source.includes('move?.type === "Fighting"') ||
        !source.includes('this.chainModify(1.1)')) {
      throw new Error('resolved Gen 3 blackbelt.onModifyAtk changed');
    }
  }
  lines.push('        POKEMON_HANDLER_SOURCE_ITEM, POKEMON_GEN3_ITEM_BLACKBELT, 0, 1, 8,');
  lines.push('        POKEMON_GEN3_TYPE_FIGHTING, 4505, 0, 1, 6, 2, 0, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onModifyAtk"},');
  lines.push('    {POKEMON_HANDLER_EVENT_DAMAGE, POKEMON_GEN3_HANDLER_ROCK_HEAD,');
  lines.push('        POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_ROCKHEAD, 0, 0, 7,');
  lines.push('        POKEMON_DAMAGE_RELATIVE_RECOIL, 0, 0, 0, 8, 2, 0, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onDamage"},');
  lines.push('    {POKEMON_HANDLER_EVENT_TRY_BOOST, POKEMON_GEN3_HANDLER_CLEAR_BODY,');
  lines.push('        POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_CLEARBODY, 0, 0, 7,');
  lines.push('        0, 0, 0, 0, 10, 2, 0, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onTryBoost"},');
  lines.push('    {POKEMON_HANDLER_EVENT_TRY_BOOST, POKEMON_GEN3_HANDLER_HYPER_CUTTER,');
  lines.push('        POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_HYPERCUTTER, 0, 0, 7,');
  lines.push('        0, 0, 0, 0, 12, 2, 0, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onTryBoost"},');
  lines.push('    {POKEMON_HANDLER_EVENT_TRY_BOOST, POKEMON_GEN3_HANDLER_KEEN_EYE,');
  lines.push('        POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_KEENEYE, 0, 0, 7,');
  lines.push('        0, 0, 0, 0, 14, 2, 0, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onTryBoost"},');
  lines.push('    {POKEMON_HANDLER_EVENT_TRY_BOOST, POKEMON_GEN3_HANDLER_WHITE_SMOKE,');
  lines.push('        POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_WHITESMOKE, 0, 0, 7,');
  lines.push('        0, 0, 0, 0, 16, 2, 0, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onTryBoost"},');
  lines.push('    {POKEMON_HANDLER_EVENT_TRY_HIT, POKEMON_GEN3_HANDLER_PROTECT,');
  lines.push('        POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_PROTECT, 0, 3, 2,');
  lines.push('        0, 0, 0, 0, 18, 2, 0, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onTryHit"},');
  lines.push('    {POKEMON_HANDLER_EVENT_TRY_HIT, POKEMON_GEN3_HANDLER_MAGIC_COAT,');
  lines.push('        POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_MAGICCOAT, 0, 2, 2,');
  lines.push('        0, 0, 0, 0, 20, 6, 0, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onTryHit"},');
  lines.push('    {POKEMON_HANDLER_EVENT_TRY_PRIMARY_HIT, POKEMON_GEN3_HANDLER_SUBSTITUTE_TRY_PRIMARY_HIT,');
  lines.push('        POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_SUBSTITUTE, 0, -1, 2,');
  lines.push('        0, 0, 0, 0, 20, 0, POKEMON_EXCEPTION_SUBSTITUTE_TRY_PRIMARY_HIT, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "condition.onTryPrimaryHit"},');
  lines.push('    {POKEMON_HANDLER_EVENT_PREPARE_HIT, POKEMON_GEN3_HANDLER_SNATCH,');
  lines.push('        POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_SNATCH, 0, -1, 2,');
  lines.push('        0, 0, 0, 0, 26, 5, 0, POKEMON_HANDLER_SCOPE_ANY, POKEMON_HANDLER_ROUTE_OWNER, 0, "condition.onAnyPrepareHit"},');
  {
    const ability = dex.abilities.get('voltabsorb');
    const source = String(ability.onTryHit);
    if (typeof ability.onTryHit !== 'function' ||
        !source.includes('move.type === "Electric"') ||
        !source.includes('move.id !== "thunderwave"') ||
        !source.includes('target.baseMaxhp / 4') ||
        !source.includes('return null')) {
      throw new Error('resolved Gen 3 voltabsorb.onTryHit changed');
    }
  }
  lines.push('    {POKEMON_HANDLER_EVENT_TRY_HIT, POKEMON_GEN3_HANDLER_VOLT_ABSORB,');
  lines.push('        POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_VOLTABSORB, 0, 0, 7,');
  lines.push(`        POKEMON_GEN3_TYPE_ELECTRIC, 0, 0, 0, ${voltAbsorbProgramOffset}, 5, 0, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onTryHit"},`);
  {
    const ability = dex.abilities.get('thickfat');
    const source = String(ability.onSourceBasePower);
    if (typeof ability.onSourceBasePower !== 'function' ||
        ability.onSourceBasePowerPriority !== 1 ||
        typeof ability.onModifyAtk === 'function' ||
        typeof ability.onModifySpA === 'function' ||
        !source.includes('move.type === "Ice"') ||
        !source.includes('move.type === "Fire"') ||
        !source.includes('this.chainModify(0.5)')) {
      throw new Error('resolved Gen 3 thickfat.onSourceBasePower changed');
    }
  }
  lines.push('    {POKEMON_HANDLER_EVENT_BASE_POWER, POKEMON_GEN3_HANDLER_THICK_FAT,');
  lines.push('        POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_THICKFAT, 0, 1, 7,');
  lines.push(`        0, 2048, 0, 0, ${thickFatProgramOffset}, 2, 0, POKEMON_HANDLER_SCOPE_FOE, POKEMON_HANDLER_ROUTE_OWNER, 0, "onSourceBasePower"},`);
  {
    const ability = dex.abilities.get('marvelscale');
    const source = String(ability.onModifyDef);
    if (typeof ability.onModifyDef !== 'function' ||
        ability.onModifyDefPriority !== 6 ||
        !source.includes('pokemon.status') ||
        !source.includes('this.chainModify(1.5)')) {
      throw new Error('resolved Gen 3 marvelscale.onModifyDef changed');
    }
  }
  lines.push('    {POKEMON_HANDLER_EVENT_MODIFY_DEF, POKEMON_GEN3_HANDLER_MARVEL_SCALE,');
  lines.push('        POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_MARVELSCALE, 0, 6, 7,');
  lines.push(`        0, 6144, 1, 0, ${marvelScaleProgramOffset}, 2, 0, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onModifyDef"},`);
  {
    const move = dex.moves.get('facade');
    const source = String(move.onBasePower);
    if (move.basePower !== 70 || move.type !== 'Normal' ||
        typeof move.onBasePower !== 'function' ||
        !source.includes('pokemon.status') ||
        !source.includes('pokemon.status !== "slp"') ||
        !source.includes('this.chainModify(2)')) {
      throw new Error('resolved Gen 3 facade.onBasePower changed');
    }
  }
  lines.push('    {POKEMON_HANDLER_EVENT_BASE_POWER, POKEMON_GEN3_HANDLER_FACADE_BASE_POWER,');
  lines.push('        POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_FACADE, 0, 0, 0,');
  lines.push(`        0, 8192, 0, 0, ${facadeProgramOffset}, 2, 0, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onBasePower"},`);
  {
    const move = dex.moves.get('refresh');
    const source = String(move.onHit);
    if (move.accuracy !== true || move.target !== 'self' ||
        typeof move.onHit !== 'function' ||
        !source.includes('["", "slp", "frz"].includes(pokemon.status)') ||
        !source.includes('return false') ||
        !source.includes('pokemon.cureStatus()')) {
      throw new Error('resolved Gen 3 refresh.onHit changed');
    }
  }
  lines.push('    {POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK, POKEMON_GEN3_HANDLER_REFRESH_HIT,');
  lines.push('        POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_REFRESH, 0, 0, 0,');
  lines.push(`        0, 0, 0, 0, ${refreshProgramOffset}, 2, 0, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onHit"},`);
  {
    const move = dex.moves.get('psychup');
    const source = String(move.onHit);
    if (move.accuracy !== true || move.target !== 'normal' ||
        !move.flags.bypasssub || move.flags.protect || !move.flags.snatch ||
        typeof move.onHit !== 'function' ||
        !source.includes('for (i in target.boosts)') ||
        !source.includes('source.boosts[i] = target.boosts[i]') ||
        source.includes('focusenergy')) {
      throw new Error('resolved Gen 3 psychup.onHit changed');
    }
  }
  lines.push('    {POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK, POKEMON_GEN3_HANDLER_PSYCH_UP_HIT,');
  lines.push('        POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_PSYCHUP, 0, 0, 0,');
  lines.push(`        0, 0, 0, 0, ${psychUpProgramOffset}, 1, 0, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onHit"},`);
  const scalarProgramOffset = 31;
  {
    const checks = [
      ['compoundeyes', 'onSourceModifyAccuracy', 9, 'this.chainModify(1.3)'],
      ['hugepower', 'onModifyAtk', 5, 'this.chainModify(2)'],
      ['hustle', 'onModifyAtk', 5, 'this.modify(atk, 1.5)'],
      ['hustle', 'onSourceModifyAccuracy', 7, 'physicalTypes.includes(move.type)'],
      ['purepower', 'onModifyAtk', 5, 'this.chainModify(2)'],
    ];
    for (const [id, hook, priority, witness] of checks) {
      const owner = dex.abilities.get(id);
      if (typeof owner[hook] !== 'function' || owner[`${hook}Priority`] !== priority ||
          !String(owner[hook]).includes(witness)) {
        throw new Error(`resolved Gen 3 ${id}.${hook} changed`);
      }
    }
    const club = dex.items.get('thickclub');
    if (typeof club.onModifyAtk !== 'function' || club.onModifyAtkPriority !== 1 ||
        !String(club.onModifyAtk).includes('pokemon.species.name === "Cubone"') ||
        !String(club.onModifyAtk).includes('this.chainModify(2)')) {
      throw new Error('resolved Gen 3 thickclub.onModifyAtk changed');
    }
  }
  lines.push('    {POKEMON_HANDLER_EVENT_MODIFY_ACCURACY, POKEMON_GEN3_HANDLER_COMPOUND_EYES_ACCURACY,');
  lines.push('        POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_COMPOUNDEYES, 0, 9, 7,');
  lines.push(`        0, 5324, 0, 0, ${scalarProgramOffset}, 1, 0, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_OWNER, 0, "onSourceModifyAccuracy"},`);
  lines.push('    {POKEMON_HANDLER_EVENT_MODIFY_ATK, POKEMON_GEN3_HANDLER_HUGE_POWER,');
  lines.push('        POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_HUGEPOWER, 0, 5, 7,');
  lines.push(`        0, 8192, 0, 0, ${scalarProgramOffset + 1}, 1, 0, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onModifyAtk"},`);
  lines.push('    {POKEMON_HANDLER_EVENT_MODIFY_ATK, POKEMON_GEN3_HANDLER_HUSTLE_ATTACK,');
  lines.push('        POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_HUSTLE, 0, 5, 7,');
  lines.push(`        0, 4096, 0, 0, ${scalarProgramOffset + 2}, 1, 0, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onModifyAtk"},`);
  lines.push('    {POKEMON_HANDLER_EVENT_MODIFY_ACCURACY, POKEMON_GEN3_HANDLER_HUSTLE_ACCURACY,');
  lines.push('        POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_HUSTLE, 0, 7, 7,');
  lines.push(`        0, 3277, 0, 0, ${scalarProgramOffset + 3}, 2, 0, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_OWNER, 0, "onSourceModifyAccuracy"},`);
  lines.push('    {POKEMON_HANDLER_EVENT_MODIFY_ATK, POKEMON_GEN3_HANDLER_PURE_POWER,');
  lines.push('        POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_PUREPOWER, 0, 5, 7,');
  lines.push(`        0, 8192, 0, 0, ${scalarProgramOffset + 5}, 1, 0, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onModifyAtk"},`);
  lines.push('    {POKEMON_HANDLER_EVENT_MODIFY_ATK, POKEMON_GEN3_HANDLER_THICK_CLUB,');
  lines.push('        POKEMON_HANDLER_SOURCE_ITEM, POKEMON_GEN3_ITEM_THICKCLUB, 0, 1, 8,');
  lines.push(`        0, 8192, 0, 0, ${scalarProgramOffset + 6}, 2, 0, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onModifyAtk"},`);
  TYPE_BOOST_ITEMS.slice(1).forEach(([id, event, type, modifierQ12, multiplier], index) => {
    const item = dex.items.get(id);
    if (!item.exists || item.gen > 3) throw new Error(`invalid type-boost item: ${id}`);
    const hook = event === 'ModifyAtk' ? 'onModifyAtk' : 'onModifySpA';
    const source = String(item[hook]);
    if (typeof item[hook] !== 'function' || item[`${hook}Priority`] !== 1 ||
        item.onBasePower !== undefined ||
        !source.includes(`move?.type === "${type}"`) ||
        !source.includes(`this.chainModify(${multiplier})`)) {
      throw new Error(`resolved Gen 3 ${id}.${hook} changed`);
    }
    lines.push(`    {POKEMON_HANDLER_EVENT_${eventToken(event)}, POKEMON_GEN3_HANDLER_${cName(id)},`);
    lines.push(`        POKEMON_HANDLER_SOURCE_ITEM, POKEMON_GEN3_ITEM_${cName(id)}, 0, 1, 8,`);
    lines.push(`        POKEMON_GEN3_TYPE_${cName(type)}, ${modifierQ12}, 0, 1, ${typeBoostProgramOffset + index * 2}, 2, 0, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "${hook}"},`);
  });
  const weatherProgramOffset = typeBoostProgramOffset +
    (TYPE_BOOST_ITEMS.length - 1) * 2;
  const scalarHandlerOffset = BASE_HANDLER_IDS.length;
  const typeBoostHandlerOffset = scalarHandlerOffset + SCALAR_HANDLER_IDS.length;
  const weatherHandlerOffset = typeBoostHandlerOffset +
    TYPE_BOOST_ITEMS.length - 1;
  lines.push('    {POKEMON_HANDLER_EVENT_WEATHER_MODIFY_DAMAGE, POKEMON_GEN3_HANDLER_RAIN_DAMAGE,');
  lines.push('        POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_WEATHER_RAINDANCE, 0, 0, 5,');
  lines.push(`        0, 0, 0, 0, ${weatherProgramOffset}, 2, 0, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onWeatherModifyDamage"},`);
  lines.push('    {POKEMON_HANDLER_EVENT_WEATHER_MODIFY_DAMAGE, POKEMON_GEN3_HANDLER_SUN_DAMAGE,');
  lines.push('        POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_WEATHER_SUNNYDAY, 0, 0, 5,');
  lines.push(`        0, 0, 0, 0, ${weatherProgramOffset + 2}, 2, 0, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onWeatherModifyDamage"},`);
  const speedHandlerOffset = weatherHandlerOffset + WEATHER_HANDLER_IDS.length;
  const speedProgramOffset = weatherProgramOffset + 4;
  lines.push('    {POKEMON_HANDLER_EVENT_MODIFY_SPE, POKEMON_GEN3_HANDLER_CHLOROPHYLL_SPEED,');
  lines.push('        POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_CHLOROPHYLL, 0, 0, 7,');
  lines.push(`        0, 0, 0, 0, ${speedProgramOffset}, 2, 0, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onModifySpe"},`);
  lines.push('    {POKEMON_HANDLER_EVENT_MODIFY_SPE, POKEMON_GEN3_HANDLER_SWIFT_SWIM_SPEED,');
  lines.push('        POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_SWIFTSWIM, 0, 0, 7,');
  lines.push(`        0, 0, 0, 0, ${speedProgramOffset + 2}, 2, 0, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onModifySpe"},`);
  lines.push('    {POKEMON_HANDLER_EVENT_MODIFY_SPE, POKEMON_GEN3_HANDLER_PARALYSIS_SPEED,');
  lines.push('        POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_STATUS_PAR, 0, -101, 0,');
  lines.push(`        0, 0, 0, 0, ${speedProgramOffset + 4}, 1, 0, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onModifySpe"},`);
  const residualHandlerOffset = speedHandlerOffset + WEATHER_SPEED_HANDLER_IDS.length;
  const residualProgramOffset = speedProgramOffset + 5;
  lines.push('    {POKEMON_HANDLER_EVENT_RESIDUAL, POKEMON_GEN3_HANDLER_RAIN_DISH_RESIDUAL,');
  lines.push('        POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_RAINDISH, 10, 0, 3,');
  lines.push(`        0, 0, 0, 0, ${residualProgramOffset}, 2, 0, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onResidual"},`);
  const lifecycleHandlerOffset = residualHandlerOffset + WEATHER_RESIDUAL_HANDLER_IDS.length;
  const lifecycleProgramOffset = residualProgramOffset + 2;
  lines.push('    {POKEMON_HANDLER_EVENT_START, POKEMON_GEN3_HANDLER_CLOUD_NINE_START,');
  lines.push('        POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_CLOUDNINE, 0, 0, 0,');
  lines.push(`        0, 0, 0, 0, ${lifecycleProgramOffset}, 1, 0, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onStart"},`);
  lines.push('    {POKEMON_HANDLER_EVENT_END, POKEMON_GEN3_HANDLER_CLOUD_NINE_END,');
  lines.push('        POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_CLOUDNINE, 0, 0, 0,');
  lines.push(`        0, 0, 0, 0, ${lifecycleProgramOffset + 1}, 2, 0, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onEnd"},`);
  lines.push('    {POKEMON_HANDLER_EVENT_START, POKEMON_GEN3_HANDLER_SAND_STREAM_START,');
  lines.push('        POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_SANDSTREAM, 0, 0, 0,');
  lines.push(`        0, 0, 0, 0, ${lifecycleProgramOffset + 3}, 1, 0, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onStart"},`);
  const berryHandlerOffset = lifecycleHandlerOffset + LIFECYCLE_HANDLER_IDS.length;
  const berryProgramOffset = lifecycleProgramOffset + 4;
  FIXED_HEAL_BERRIES.forEach(([id], index) => {
    const item = dex.items.get(id);
    if (typeof item.onEat !== 'function' || typeof item.onTryEatItem !== 'function' ||
        typeof item.onResidual !== 'function' || item.onResidualOrder !== 10 ||
        item.onResidualSubOrder !== 4) throw new Error(`resolved Gen 3 ${id} berry hooks changed`);
    const handler = berryHandlerOffset + index * 3;
    const program = berryProgramOffset + index * 3;
    lines.push(`    {POKEMON_HANDLER_EVENT_RESIDUAL, POKEMON_GEN3_HANDLER_${cName(id)}_RESIDUAL, POKEMON_HANDLER_SOURCE_ITEM, POKEMON_GEN3_ITEM_${cName(id)}, 10, 0, 4, 0, 0, 0, 0, ${program}, 1, 0, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onResidual"},`);
    lines.push(`    {POKEMON_HANDLER_EVENT_TRY_EAT_ITEM, POKEMON_GEN3_HANDLER_${cName(id)}_TRY_EAT, POKEMON_HANDLER_SOURCE_ITEM, POKEMON_GEN3_ITEM_${cName(id)}, 0, 0, 8, 0, 0, 0, 0, ${program + 1}, 1, 0, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onTryEatItem"},`);
    lines.push(`    {POKEMON_HANDLER_EVENT_ITEM_EAT, POKEMON_GEN3_HANDLER_${cName(id)}_EAT, POKEMON_HANDLER_SOURCE_ITEM, POKEMON_GEN3_ITEM_${cName(id)}, 0, 0, 0, 0, 0, 0, 0, ${program + 2}, 1, 0, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onEat"},`);
  });
  const flavorHandlerOffset = berryHandlerOffset + FIXED_HEAL_BERRIES.length * 3;
  const flavorProgramOffset = berryProgramOffset + FIXED_HEAL_BERRIES.length * 3;
  FLAVOR_BERRIES.forEach(([id], index) => {
    const item = dex.items.get(id);
    if (typeof item.onEat !== 'function' || typeof item.onTryEatItem !== 'function' ||
        typeof item.onResidual !== 'function' || item.onUpdate !== undefined ||
        item.onResidualOrder !== 10 || item.onResidualSubOrder !== 4) {
      throw new Error(`resolved Gen 3 ${id} flavor berry hooks changed`);
    }
    const handler = flavorHandlerOffset + index * 3;
    const program = flavorProgramOffset + index * 4;
    lines.push(`    {POKEMON_HANDLER_EVENT_RESIDUAL, POKEMON_GEN3_HANDLER_${cName(id)}_RESIDUAL, POKEMON_HANDLER_SOURCE_ITEM, POKEMON_GEN3_ITEM_${cName(id)}, 10, 0, 4, 0, 0, 0, 0, ${program}, 1, 0, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onResidual"},`);
    lines.push(`    {POKEMON_HANDLER_EVENT_TRY_EAT_ITEM, POKEMON_GEN3_HANDLER_${cName(id)}_TRY_EAT, POKEMON_HANDLER_SOURCE_ITEM, POKEMON_GEN3_ITEM_${cName(id)}, 0, 0, 8, 0, 0, 0, 0, ${program + 1}, 1, 0, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onTryEatItem"},`);
    lines.push(`    {POKEMON_HANDLER_EVENT_ITEM_EAT, POKEMON_GEN3_HANDLER_${cName(id)}_EAT, POKEMON_HANDLER_SOURCE_ITEM, POKEMON_GEN3_ITEM_${cName(id)}, 0, 0, 0, 0, 0, 0, 0, ${program + 2}, 2, 0, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onEat"},`);
  });
  const pinchHandlerOffset = flavorHandlerOffset + FLAVOR_BERRIES.length * 3;
  const pinchProgramOffset = flavorProgramOffset + FLAVOR_BERRIES.length * 4;
  PINCH_BOOST_BERRIES.forEach(([id], index) => {
    const item = dex.items.get(id);
    if (typeof item.onEat !== 'function' || typeof item.onResidual !== 'function' ||
        item.onUpdate !== undefined || item.onResidualOrder !== 10 ||
        item.onResidualSubOrder !== 4) {
      throw new Error(`resolved Gen 3 ${id} pinch berry hooks changed`);
    }
    const handler = pinchHandlerOffset + index * 2;
    const program = pinchProgramOffset + index * 2;
    lines.push(`    {POKEMON_HANDLER_EVENT_RESIDUAL, POKEMON_GEN3_HANDLER_${cName(id)}_RESIDUAL, POKEMON_HANDLER_SOURCE_ITEM, POKEMON_GEN3_ITEM_${cName(id)}, 10, 0, 4, 0, 0, 0, 0, ${program}, 1, 0, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onResidual"},`);
    lines.push(`    {POKEMON_HANDLER_EVENT_ITEM_EAT, POKEMON_GEN3_HANDLER_${cName(id)}_EAT, POKEMON_HANDLER_SOURCE_ITEM, POKEMON_GEN3_ITEM_${cName(id)}, 0, 0, 0, 0, 0, 0, 0, ${program + 1}, 1, 0, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onEat"},`);
  });
  const volatilePinchHandlerOffset =
    pinchHandlerOffset + PINCH_BOOST_BERRIES.length * 2;
  const volatilePinchProgramOffset =
    pinchProgramOffset + PINCH_BOOST_BERRIES.length * 2;
  VOLATILE_PINCH_BERRIES.forEach(([id], index) => {
    const item = dex.items.get(id);
    if (typeof item.onEat !== 'function' || typeof item.onResidual !== 'function' ||
        item.onUpdate !== undefined || item.onTryEatItem !== undefined ||
        item.onResidualOrder !== 10 || item.onResidualSubOrder !== 4 ||
        !/addVolatile\(["']focusenergy["']\)/.test(String(item.onEat))) {
      throw new Error(`resolved Gen 3 ${id} volatile pinch berry hooks changed`);
    }
    const program = volatilePinchProgramOffset + index * 2;
    lines.push(`    {POKEMON_HANDLER_EVENT_RESIDUAL, POKEMON_GEN3_HANDLER_${cName(id)}_RESIDUAL, POKEMON_HANDLER_SOURCE_ITEM, POKEMON_GEN3_ITEM_${cName(id)}, 10, 0, 4, 0, 0, 0, 0, ${program}, 1, 0, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onResidual"},`);
    lines.push(`    {POKEMON_HANDLER_EVENT_ITEM_EAT, POKEMON_GEN3_HANDLER_${cName(id)}_EAT, POKEMON_HANDLER_SOURCE_ITEM, POKEMON_GEN3_ITEM_${cName(id)}, 0, 0, 0, 0, 0, 0, 0, ${program + 1}, 1, 0, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onEat"},`);
  });
  const randomPinchHandlerOffset =
    volatilePinchHandlerOffset + VOLATILE_PINCH_BERRIES.length * 2;
  const randomPinchProgramOffset =
    volatilePinchProgramOffset + VOLATILE_PINCH_BERRIES.length * 2;
  RANDOM_PINCH_BERRIES.forEach(([id]) => {
    const item = dex.items.get(id);
    const eat = String(item.onEat);
    if (typeof item.onEat !== 'function' || typeof item.onResidual !== 'function' ||
        item.onUpdate !== undefined || item.onTryEatItem !== undefined ||
        item.onResidualOrder !== 10 || item.onResidualSubOrder !== 4 ||
        !/stat !== ["']accuracy["']/.test(eat) ||
        !/stat !== ["']evasion["']/.test(eat) ||
        !eat.includes('pokemon.boosts[stat] < 6') ||
        !eat.includes('this.sample(stats)') ||
        !eat.includes('boost[randomStat] = 2')) {
      throw new Error(`resolved Gen 3 ${id} random pinch berry hooks changed`);
    }
    lines.push(`    {POKEMON_HANDLER_EVENT_RESIDUAL, POKEMON_GEN3_HANDLER_${cName(id)}_RESIDUAL, POKEMON_HANDLER_SOURCE_ITEM, POKEMON_GEN3_ITEM_${cName(id)}, 10, 0, 4, 0, 0, 0, 0, ${randomPinchProgramOffset}, 1, 0, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onResidual"},`);
    lines.push(`    {POKEMON_HANDLER_EVENT_ITEM_EAT, POKEMON_GEN3_HANDLER_${cName(id)}_EAT, POKEMON_HANDLER_SOURCE_ITEM, POKEMON_GEN3_ITEM_${cName(id)}, 0, 0, 0, 0, 0, 0, 0, ${randomPinchProgramOffset + 1}, 1, 0, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onEat"},`);
  });
  const cureHandlerOffset =
    randomPinchHandlerOffset + RANDOM_PINCH_BERRIES.length * 2;
  const cureProgramOffset =
    randomPinchProgramOffset + RANDOM_PINCH_BERRIES.length * 2;
  STATUS_CURE_BERRIES.forEach(([id], index) => {
    const item = dex.items.get(id);
    if (typeof item.onUpdate !== 'function' || typeof item.onEat !== 'function' ||
        item.onResidual !== undefined || item.onTryEatItem !== undefined) {
      throw new Error(`resolved Gen 3 ${id} cure berry hooks changed`);
    }
    const handler = cureHandlerOffset + index * 2;
    const program = cureProgramOffset + index * 2;
    lines.push(`    {POKEMON_HANDLER_EVENT_UPDATE, POKEMON_GEN3_HANDLER_${cName(id)}_UPDATE, POKEMON_HANDLER_SOURCE_ITEM, POKEMON_GEN3_ITEM_${cName(id)}, 0, 0, 8, 0, 0, 0, 0, ${program}, 1, 0, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onUpdate"},`);
    lines.push(`    {POKEMON_HANDLER_EVENT_ITEM_EAT, POKEMON_GEN3_HANDLER_${cName(id)}_EAT, POKEMON_HANDLER_SOURCE_ITEM, POKEMON_GEN3_ITEM_${cName(id)}, 0, 0, 0, 0, 0, 0, 0, ${program + 1}, 1, 0, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onEat"},`);
  });
  const volatileCureHandlerOffset = cureHandlerOffset + STATUS_CURE_BERRIES.length * 2;
  const volatileCureProgramOffset = cureProgramOffset + STATUS_CURE_BERRIES.length * 2;
  VOLATILE_CURE_BERRIES.forEach(([id], index) => {
    const item = dex.items.get(id);
    if (typeof item.onUpdate !== 'function' || typeof item.onEat !== 'function' ||
        item.onResidual !== undefined || item.onTryEatItem !== undefined) {
      throw new Error(`resolved Gen 3 ${id} volatile cure berry hooks changed`);
    }
    const handler = volatileCureHandlerOffset + index * 2;
    const program = volatileCureProgramOffset + index * 2;
    lines.push(`    {POKEMON_HANDLER_EVENT_UPDATE, POKEMON_GEN3_HANDLER_${cName(id)}_UPDATE, POKEMON_HANDLER_SOURCE_ITEM, POKEMON_GEN3_ITEM_${cName(id)}, 0, 0, 8, 0, 0, 0, 0, ${program}, 1, 0, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onUpdate"},`);
    lines.push(`    {POKEMON_HANDLER_EVENT_ITEM_EAT, POKEMON_GEN3_HANDLER_${cName(id)}_EAT, POKEMON_HANDLER_SOURCE_ITEM, POKEMON_GEN3_ITEM_${cName(id)}, 0, 0, 0, 0, 0, 0, 0, ${program + 1}, 1, 0, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onEat"},`);
  });
  const combinedCureHandlerOffset = volatileCureHandlerOffset + VOLATILE_CURE_BERRIES.length * 2;
  const combinedCureProgramOffset = volatileCureProgramOffset + VOLATILE_CURE_BERRIES.length * 2;
  COMBINED_CURE_BERRIES.forEach(([id], index) => {
    const item = dex.items.get(id);
    if (typeof item.onAfterSetStatus !== 'function' ||
        item.onAfterSetStatusPriority !== -1 || typeof item.onUpdate !== 'function' ||
        typeof item.onEat !== 'function' || item.onResidual !== undefined ||
        item.onTryEatItem !== undefined) {
      throw new Error(`resolved Gen 3 ${id} combined cure berry hooks changed`);
    }
    const handler = combinedCureHandlerOffset + index * 3;
    const program = combinedCureProgramOffset + index * 4;
    lines.push(`    {POKEMON_HANDLER_EVENT_AFTER_SET_STATUS, POKEMON_GEN3_HANDLER_${cName(id)}_AFTER_SET_STATUS, POKEMON_HANDLER_SOURCE_ITEM, POKEMON_GEN3_ITEM_${cName(id)}, 0, -1, 8, 0, 0, 0, 0, ${program}, 1, 0, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onAfterSetStatus"},`);
    lines.push(`    {POKEMON_HANDLER_EVENT_UPDATE, POKEMON_GEN3_HANDLER_${cName(id)}_UPDATE, POKEMON_HANDLER_SOURCE_ITEM, POKEMON_GEN3_ITEM_${cName(id)}, 0, 0, 8, 0, 0, 0, 0, ${program + 1}, 1, 0, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onUpdate"},`);
    lines.push(`    {POKEMON_HANDLER_EVENT_ITEM_EAT, POKEMON_GEN3_HANDLER_${cName(id)}_EAT, POKEMON_HANDLER_SOURCE_ITEM, POKEMON_GEN3_ITEM_${cName(id)}, 0, 0, 0, 0, 0, 0, 0, ${program + 2}, 2, 0, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onEat"},`);
  });
  const confusionHandlerOffset = combinedCureHandlerOffset + COMBINED_CURE_BERRIES.length * 3;
  {
    const condition = dex.conditions.get('confusion');
    const ability = dex.abilities.get('owntempo');
    if (typeof condition.onStart !== 'function' ||
        typeof condition.onBeforeMove !== 'function' ||
        condition.onBeforeMovePriority !== 3 ||
        typeof condition.onEnd !== 'function') {
      throw new Error('resolved Gen 3 confusion hooks changed');
    }
    if (typeof ability.onTryAddVolatile !== 'function' ||
        typeof ability.onHit !== 'function' || typeof ability.onUpdate !== 'function') {
      throw new Error('resolved Gen 3 Own Tempo hooks changed');
    }
  }
  /* Discovered Condition callbacks receive resolvePriority's source-kind
   * default subOrder 2. Direct singleEvent Start/End callbacks do not. */
  lines.push(`    {POKEMON_HANDLER_EVENT_START, POKEMON_GEN3_HANDLER_CONFUSION_START, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_CONFUSION, 0, 0, 0, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_CONFUSION_START, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onStart"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_BEFORE_MOVE, POKEMON_GEN3_HANDLER_CONFUSION_BEFORE_MOVE, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_CONFUSION, 0, 3, 2, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_CONFUSION_BEFORE_MOVE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onBeforeMove"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_END, POKEMON_GEN3_HANDLER_CONFUSION_END, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_CONFUSION, 0, 0, 0, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_CONFUSION_END, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onEnd"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_TRY_ADD_VOLATILE, POKEMON_GEN3_HANDLER_OWN_TEMPO_TRY_ADD_VOLATILE, POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_OWNTEMPO, 0, 0, 7, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_OWN_TEMPO_TRY_ADD, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onTryAddVolatile"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_HIT, POKEMON_GEN3_HANDLER_OWN_TEMPO_HIT, POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_OWNTEMPO, 0, 0, 7, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_OWN_TEMPO_HIT, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onHit"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_UPDATE, POKEMON_GEN3_HANDLER_OWN_TEMPO_UPDATE, POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_OWNTEMPO, 0, 0, 7, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_OWN_TEMPO_UPDATE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onUpdate"},`);
  {
    const ability = dex.abilities.get('shielddust');
    if (typeof ability.onModifySecondaries !== 'function') {
      throw new Error('resolved Gen 3 Shield Dust hook changed');
    }
  }
  lines.push(`    {POKEMON_HANDLER_EVENT_MODIFY_SECONDARIES, POKEMON_GEN3_HANDLER_SHIELD_DUST_MODIFY_SECONDARIES, POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_SHIELDDUST, 0, 0, 7, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_SHIELD_DUST_MODIFY_SECONDARIES, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onModifySecondaries"},`);
  const lockedMoveHandlerOffset = confusionHandlerOffset + 7;
  {
    const condition = dex.conditions.get('lockedmove');
    if (typeof condition.onStart !== 'function' ||
        typeof condition.onRestart !== 'function' ||
        typeof condition.onResidual !== 'function' ||
        typeof condition.onEnd !== 'function' ||
        typeof condition.onLockMove !== 'function' ||
        condition.onAfterMove !== undefined) {
      throw new Error('resolved Gen 3 lockedmove hooks changed');
    }
  }
  lines.push(`    {POKEMON_HANDLER_EVENT_START, POKEMON_GEN3_HANDLER_LOCKED_MOVE_START, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_LOCKEDMOVE, 0, 0, 0, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_LOCKED_MOVE_START, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onStart"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_RESTART, POKEMON_GEN3_HANDLER_LOCKED_MOVE_RESTART, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_LOCKEDMOVE, 0, 0, 0, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_LOCKED_MOVE_RESTART, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onRestart"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_RESIDUAL, POKEMON_GEN3_HANDLER_LOCKED_MOVE_RESIDUAL, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_LOCKEDMOVE, 0, 0, 2, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_LOCKED_MOVE_RESIDUAL, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onResidual"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_END, POKEMON_GEN3_HANDLER_LOCKED_MOVE_END, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_LOCKEDMOVE, 0, 0, 0, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_LOCKED_MOVE_END, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onEnd"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_LOCK_MOVE, POKEMON_GEN3_HANDLER_LOCKED_MOVE_SELECTOR, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_LOCKEDMOVE, 0, 0, 2, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_LOCKED_MOVE_SELECTOR, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onLockMove"},`);
  {
    const move = dex.moves.get('weatherball');
    if (typeof move.onModifyType !== 'function' ||
        typeof move.onModifyMove !== 'function' || move.basePower !== 50 ||
        move.type !== 'Normal') {
      throw new Error('resolved Gen 3 Weather Ball hooks changed');
    }
  }
  lines.push(`    {POKEMON_HANDLER_EVENT_MODIFY_TYPE, POKEMON_GEN3_HANDLER_WEATHER_BALL_MODIFY_TYPE, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_WEATHERBALL, 0, 0, 0, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_WEATHER_BALL_MODIFY_TYPE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onModifyType"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_MODIFY_MOVE, POKEMON_GEN3_HANDLER_WEATHER_BALL_MODIFY_MOVE, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_WEATHERBALL, 0, 0, 0, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_WEATHER_BALL_MODIFY_MOVE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onModifyMove"},`);
  {
    const move = dex.moves.get('conversion2');
    const source = String(move.onHit);
    if (typeof move.onHit !== 'function' || move.target !== 'normal' ||
        !source.includes('target.lastMoveUsed') ||
        !/lastMoveUsed\.id === ["']struggle["'] \? ["']Normal["']/.test(source) ||
        !source.includes('this.dex.types.names()') ||
        !source.includes('typeCheck === 2 || typeCheck === 3') ||
        !source.includes('this.sample(possibleTypes)') ||
        !source.includes('source.setType(randomType)')) {
      throw new Error('resolved Gen 3 Conversion 2 hook changed');
    }
  }
  {
    const move = dex.moves.get('thunder');
    if (typeof move.onModifyMove !== 'function' || move.accuracy !== 70 ||
        move.basePower !== 120 || move.secondary?.chance !== 30 ||
        move.secondary?.status !== 'par') {
      throw new Error('resolved Gen 3 Thunder hooks changed');
    }
  }
  lines.push(`    {POKEMON_HANDLER_EVENT_MODIFY_MOVE, POKEMON_GEN3_HANDLER_THUNDER_MODIFY_MOVE, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_THUNDER, 0, 0, 0, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_THUNDER_MODIFY_MOVE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onModifyMove"},`);
  {
    const move = dex.moves.get('magnitude');
    const modifySource = String(move.onModifyMove);
    if (!move.exists || move.gen > 3 || move.basePower !== 0 ||
        move.type !== 'Ground' || move.category !== 'Physical' ||
        typeof move.onModifyMove !== 'function' ||
        typeof move.onUseMoveMessage !== 'function' ||
        !modifySource.includes('this.random(100)')) {
      throw new Error('resolved Gen 3 Magnitude shape changed');
    }
  }
  lines.push(`    {POKEMON_HANDLER_EVENT_MODIFY_MOVE, POKEMON_GEN3_HANDLER_MAGNITUDE_MODIFY_MOVE, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_MAGNITUDE, 0, 0, 0, 0, 0, 0, 0, ${magnitudeProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onModifyMove"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_USE_MOVE_MESSAGE, POKEMON_GEN3_HANDLER_MAGNITUDE_USE_MOVE_MESSAGE, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_MAGNITUDE, 0, 0, 0, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onUseMoveMessage"},`);
  {
    const move = dex.moves.get('struggle');
    if (typeof move.onModifyMove !== 'function' || move.type !== 'Normal' ||
        move.basePower !== 50 || move.recoil?.[0] !== 1 ||
        move.recoil?.[1] !== 4) {
      throw new Error('resolved Gen 3 Struggle ModifyMove shape changed');
    }
  }
  {
    const condition = dex.conditions.get('twoturnmove');
    const move = dex.moves.get('solarbeam');
    if (condition.duration !== 2 || typeof condition.onStart !== 'function' ||
        typeof condition.onEnd !== 'function' || typeof condition.onLockMove !== 'function' ||
        typeof condition.onMoveAborted !== 'function' ||
        typeof move.onTryMove !== 'function' || typeof move.onBasePower !== 'function' ||
        move.basePower !== 120 || move.type !== 'Grass' || !move.flags.charge) {
      throw new Error('resolved Gen 3 two-turn Solar Beam shape changed');
    }
  }
  lines.push(`    {POKEMON_HANDLER_EVENT_START, POKEMON_GEN3_HANDLER_TWO_TURN_START, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_TWOTURNMOVE, 0, 0, 0, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onStart"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_RESIDUAL, POKEMON_GEN3_HANDLER_TWO_TURN_RESIDUAL, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_TWOTURNMOVE, 0, 0, 2, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "duration"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_LOCK_MOVE, POKEMON_GEN3_HANDLER_TWO_TURN_LOCK_MOVE, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_TWOTURNMOVE, 0, 0, 2, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_TWO_TURN_LOCK_MOVE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onLockMove"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_MOVE_ABORTED, POKEMON_GEN3_HANDLER_TWO_TURN_MOVE_ABORTED, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_TWOTURNMOVE, 0, 0, 2, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_TWO_TURN_MOVE_ABORTED, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onMoveAborted"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_END, POKEMON_GEN3_HANDLER_TWO_TURN_END, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_TWOTURNMOVE, 0, 0, 0, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_TWO_TURN_END, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onEnd"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_TRY_MOVE, POKEMON_GEN3_HANDLER_SOLAR_BEAM_TRY_MOVE, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_SOLARBEAM, 0, 0, 0, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_SOLAR_BEAM_TRY_MOVE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onTryMove"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_BASE_POWER, POKEMON_GEN3_HANDLER_SOLAR_BEAM_BASE_POWER, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_SOLARBEAM, 0, 0, 0, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_SOLAR_BEAM_BASE_POWER, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onBasePower"},`);
  const flinchHandlerOffset = lockedMoveHandlerOffset + 17;
  {
    const condition = dex.conditions.get('flinch');
    const ability = dex.abilities.get('innerfocus');
    if (condition.duration !== 1 || typeof condition.onBeforeMove !== 'function' ||
        condition.onBeforeMovePriority !== 8 ||
        typeof ability.onTryAddVolatile !== 'function' ||
        ability.onTryBoost !== undefined) {
      throw new Error('resolved Gen 3 flinch/Inner Focus shape changed');
    }
  }
  lines.push(`    {POKEMON_HANDLER_EVENT_BEFORE_MOVE, POKEMON_GEN3_HANDLER_FLINCH_BEFORE_MOVE, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_FLINCH, 0, 8, 2, 0, 0, 0, 0, ${flinchProgramOffset}, 1, 0, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onBeforeMove"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_TRY_ADD_VOLATILE, POKEMON_GEN3_HANDLER_INNER_FOCUS_TRY_ADD_VOLATILE, POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_INNERFOCUS, 0, 0, 7, 0, 0, 0, 0, ${flinchProgramOffset + 1}, 2, 0, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onTryAddVolatile"},`);
  const criticalHandlerOffset = flinchHandlerOffset + 2;
  {
    const move = dex.moves.get('focusenergy');
    const condition = move.condition;
    const scope = dex.items.get('scopelens');
    const lucky = dex.items.get('luckypunch');
    const stick = dex.items.get('stick');
    const battleArmor = dex.abilities.get('battlearmor');
    const shellArmor = dex.abilities.get('shellarmor');
    if (move.volatileStatus !== 'focusenergy' || typeof condition?.onStart !== 'function' ||
        typeof condition?.onModifyCritRatio !== 'function' ||
        typeof scope.onModifyCritRatio !== 'function' ||
        typeof lucky.onModifyCritRatio !== 'function' ||
        typeof stick.onModifyCritRatio !== 'function' ||
        battleArmor.onCriticalHit !== false || shellArmor.onCriticalHit !== false) {
      throw new Error('resolved critical ecosystem shape changed');
    }
  }
  lines.push(`    {POKEMON_HANDLER_EVENT_START, POKEMON_GEN3_HANDLER_FOCUS_ENERGY_START, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_FOCUSENERGY, 0, 0, 0, 0, 0, 0, 0, ${criticalProgramOffset}, 1, 0, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onStart"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_MODIFY_CRIT_RATIO, POKEMON_GEN3_HANDLER_FOCUS_ENERGY_MODIFY_CRIT_RATIO, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_FOCUSENERGY, 0, 0, 2, 0, 0, 0, 0, ${criticalProgramOffset + 1}, 1, 0, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onModifyCritRatio"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_MODIFY_CRIT_RATIO, POKEMON_GEN3_HANDLER_SCOPE_LENS_MODIFY_CRIT_RATIO, POKEMON_HANDLER_SOURCE_ITEM, POKEMON_GEN3_ITEM_SCOPELENS, 0, 0, 8, 0, 0, 0, 0, ${criticalProgramOffset + 2}, 1, 0, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onModifyCritRatio"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_MODIFY_CRIT_RATIO, POKEMON_GEN3_HANDLER_LUCKY_PUNCH_MODIFY_CRIT_RATIO, POKEMON_HANDLER_SOURCE_ITEM, POKEMON_GEN3_ITEM_LUCKYPUNCH, 0, 0, 8, 0, 0, 0, 0, ${criticalProgramOffset + 3}, 2, 0, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onModifyCritRatio"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_MODIFY_CRIT_RATIO, POKEMON_GEN3_HANDLER_STICK_MODIFY_CRIT_RATIO, POKEMON_HANDLER_SOURCE_ITEM, POKEMON_GEN3_ITEM_STICK, 0, 0, 8, 0, 0, 0, 0, ${criticalProgramOffset + 5}, 2, 0, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onModifyCritRatio"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_CRITICAL_HIT, POKEMON_GEN3_HANDLER_BATTLE_ARMOR_CRITICAL_HIT, POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_BATTLEARMOR, 0, 0, 7, 0, 0, 0, 0, ${criticalProgramOffset + 7}, 1, 0, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onCriticalHit"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_CRITICAL_HIT, POKEMON_GEN3_HANDLER_SHELL_ARMOR_CRITICAL_HIT, POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_SHELLARMOR, 0, 0, 7, 0, 0, 0, 0, ${criticalProgramOffset + 8}, 1, 0, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onCriticalHit"},`);
  {
    const condition = dex.conditions.get('partiallytrapped');
    if (typeof condition.onTrapPokemon !== 'function' ||
        typeof condition.onResidual !== 'function' ||
        condition.onResidualOrder !== 10 || condition.onResidualSubOrder !== 9) {
      throw new Error('resolved Gen 3 partial-trap hooks changed');
    }
  }
  lines.push(`    {POKEMON_HANDLER_EVENT_TRAP_POKEMON, POKEMON_GEN3_HANDLER_PARTIALLY_TRAPPED_TRAP_POKEMON, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_PARTIALLYTRAPPED, 0, 0, 2, 0, 0, 0, 0, ${partialTrapProgramOffset}, 2, 0, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onTrapPokemon"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_RESIDUAL, POKEMON_GEN3_HANDLER_PARTIALLY_TRAPPED_RESIDUAL, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_PARTIALLYTRAPPED, 10, 0, 9, 0, 0, 0, 0, ${partialTrapProgramOffset + 2}, 1, 0, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onResidual"},`);
  const tauntHandlerOffset = criticalHandlerOffset + PARTIAL_TRAP_HANDLER_IDS.length + 7;
  {
    const condition = dex.conditions.get('taunt');
    if (condition.duration !== 2 || typeof condition.onStart !== 'function' ||
        typeof condition.onEnd !== 'function' ||
        typeof condition.onDisableMove !== 'function' ||
        typeof condition.onBeforeMove !== 'function' ||
        condition.onBeforeMovePriority !== undefined ||
        condition.onResidualOrder !== 10 || condition.onResidualSubOrder !== 15) {
      throw new Error('resolved Gen 3 Taunt lifecycle hooks changed');
    }
  }
  lines.push(`    {POKEMON_HANDLER_EVENT_START, POKEMON_GEN3_HANDLER_TAUNT_START, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_TAUNT, 0, 0, 0, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onStart"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_END, POKEMON_GEN3_HANDLER_TAUNT_END, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_TAUNT, 0, 0, 0, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onEnd"},`);
  const tormentHandlerOffset = tauntHandlerOffset + TAUNT_LIFECYCLE_HANDLER_IDS.length;
  {
    const condition = dex.conditions.get('torment');
    if (condition.duration !== undefined || condition.noCopy !== true ||
        typeof condition.onStart !== 'function' ||
        typeof condition.onEnd !== 'function' ||
        typeof condition.onDisableMove !== 'function' ||
        condition.onResidual !== undefined || condition.onBeforeMove !== undefined) {
      throw new Error('resolved Gen 3 Torment lifecycle hooks changed');
    }
  }
  lines.push(`    {POKEMON_HANDLER_EVENT_START, POKEMON_GEN3_HANDLER_TORMENT_START, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_TORMENT, 0, 0, 0, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onStart"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_END, POKEMON_GEN3_HANDLER_TORMENT_END, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_TORMENT, 0, 0, 0, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onEnd"},`);
  const disableHandlerOffset = tormentHandlerOffset +
    TORMENT_LIFECYCLE_HANDLER_IDS.length;
  {
    const condition = dex.conditions.get('disable');
    if (typeof condition.durationCallback !== 'function' ||
        typeof condition.onStart !== 'function' ||
        typeof condition.onEnd !== 'function' ||
        typeof condition.onDisableMove !== 'function' ||
        typeof condition.onBeforeMove !== 'function' ||
        condition.onBeforeMovePriority !== 7 ||
        condition.onResidualOrder !== undefined ||
        condition.onResidualSubOrder !== undefined) {
      throw new Error('resolved Gen 3 Disable lifecycle hooks changed');
    }
  }
  lines.push(`    {POKEMON_HANDLER_EVENT_END, POKEMON_GEN3_HANDLER_DISABLE_END, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_DISABLE, 0, 0, 0, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onEnd"},`);
  const encoreHandlerOffset = disableHandlerOffset +
    DISABLE_LIFECYCLE_HANDLER_IDS.length;
  {
    const condition = dex.conditions.get('encore');
    if (typeof condition.durationCallback !== 'function' ||
        typeof condition.onStart !== 'function' ||
        typeof condition.onEnd !== 'function' ||
        typeof condition.onDisableMove !== 'function' ||
        typeof condition.onOverrideAction !== 'function' ||
        typeof condition.onResidual !== 'function' ||
        condition.onResidualOrder !== 10 || condition.onResidualSubOrder !== 14) {
      throw new Error('resolved Gen 3 Encore lifecycle hooks changed');
    }
  }
  lines.push(`    {POKEMON_HANDLER_EVENT_END, POKEMON_GEN3_HANDLER_ENCORE_END, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_ENCORE, 0, 0, 0, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onEnd"},`);
  /* Append move-self descriptors after owner-bound handlers so adding one
   * cannot silently shift the generated owner-binding index table. */
  lines.push(`    {POKEMON_HANDLER_EVENT_MODIFY_MOVE, POKEMON_GEN3_HANDLER_STRUGGLE_MODIFY_MOVE, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_STRUGGLE, 0, 0, 0, 0, 0, 0, 0, ${struggleProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onModifyMove"},`);
  {
    const move = dex.moves.get('disable');
    const source = String(move.onTryHit);
    if (typeof move.onTryHit !== 'function' ||
        !source.includes('!target.lastMove') ||
        !source.includes('target.lastMove.id') ||
        !source.includes('struggle')) {
      throw new Error('resolved Gen 3 disable.onTryHit changed');
    }
  }
  lines.push(`    {POKEMON_HANDLER_EVENT_TRY_HIT, POKEMON_GEN3_HANDLER_DISABLE_TRY_HIT, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_DISABLE, 0, 0, 0, 0, 0, 0, 0, ${disableTryHitProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onTryHit"},`);
  {
    const move = dex.moves.get('brickbreak');
    const source = String(move.onTryHit);
    if (!move.exists || move.gen > 3 || move.basePower !== 75 ||
        move.type !== 'Fighting' || move.category !== 'Physical' ||
        typeof move.onTryHit !== 'function' ||
        !source.includes('source.side.foe') ||
        !source.includes('foe.removeSideCondition("reflect")') ||
        !source.includes('foe.removeSideCondition("lightscreen")')) {
      throw new Error('resolved Gen 3 Brick Break shape changed');
    }
  }
  lines.push(`    {POKEMON_HANDLER_EVENT_TRY_HIT, POKEMON_GEN3_HANDLER_BRICK_BREAK_TRY_HIT, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_BRICKBREAK, 0, 0, 0, 0, 0, 0, 0, ${brickBreakProgramOffset}, 2, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onTryHit"},`);
  {
    const move = dex.moves.get('mist');
    const condition = dex.conditions.get('mist');
    const source = String(condition.onTryBoost);
    if (move.sideCondition !== 'mist' || condition.duration !== 5 ||
        typeof condition.onTryBoost !== 'function' ||
        condition.onSideResidualOrder !== 3 ||
        condition.onSideResidualSubOrder !== undefined ||
        !source.includes('target !== source') || !source.includes('boost[i] < 0')) {
      throw new Error('resolved Gen 3 Mist shape changed');
    }
  }
  /* Reuse the same two-op stat-drop filter as Clear Body. Its owner binding
   * gives it side scope; the source/target guard preserves self drops. */
  lines.push(`    {POKEMON_HANDLER_EVENT_TRY_BOOST, POKEMON_GEN3_HANDLER_MIST_TRY_BOOST, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_SIDE_MIST, 0, 0, 4, 0, 0, 0, 0, 10, 2, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onTryBoost"},`);
  {
    const move = dex.moves.get('safeguard');
    const condition = dex.conditions.get('safeguard');
    const setStatus = String(condition.onSetStatus);
    const tryAddVolatile = String(condition.onTryAddVolatile);
    if (move.sideCondition !== 'safeguard' || condition.duration !== 5 ||
        condition.onSideResidualOrder !== 4 ||
        condition.onSideResidualSubOrder !== undefined ||
        !setStatus.includes('effect.id === "yawn"') ||
        !setStatus.includes('target !== source') ||
        !tryAddVolatile.includes('status.id === "confusion"') ||
        !tryAddVolatile.includes('status.id === "yawn"')) {
      throw new Error('resolved Gen 3 Safeguard shape changed');
    }
  }
  lines.push(`    {POKEMON_HANDLER_EVENT_SET_STATUS, POKEMON_GEN3_HANDLER_SAFEGUARD_SET_STATUS, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_SIDE_SAFEGUARD, 0, 0, 4, 0, 0, 0, 0, ${safeguardProgramOffset}, 3, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onSetStatus"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_TRY_ADD_VOLATILE, POKEMON_GEN3_HANDLER_SAFEGUARD_TRY_ADD_VOLATILE, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_SIDE_SAFEGUARD, 0, 0, 4, 0, 0, 0, 0, ${safeguardProgramOffset + 3}, 3, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onTryAddVolatile"},`);
  for (const [id, type] of STARTER_ABILITY_HANDLERS) {
    const ability = dex.abilities.get(id);
    const source = String(ability.onBasePower);
    if (typeof ability.onBasePower !== 'function' ||
        ability.onBasePowerPriority !== 2 || ability.onModifyAtk !== undefined ||
        ability.onModifySpA !== undefined ||
        !source.includes(`move.type === "${type}"`) ||
        !source.includes('attacker.hp <= attacker.maxhp / 3') ||
        !source.includes('this.chainModify(1.5)')) {
      throw new Error(`resolved Gen 3 ${id}.onBasePower changed`);
    }
    const index = STARTER_ABILITY_HANDLERS.findIndex(([candidate]) => candidate === id);
    lines.push(`    {POKEMON_HANDLER_EVENT_BASE_POWER, POKEMON_GEN3_HANDLER_${cName(id)}_BASE_POWER, POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_${cName(id)}, 0, 2, 7, POKEMON_GEN3_TYPE_${cName(type)}, 6144, 0, 1, ${starterAbilityProgramOffset + index * 3}, 3, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onBasePower"},`);
  }
  {
    const move = dex.moves.get('yawn');
    const condition = dex.conditions.get('yawn');
    const tryHit = String(move.onTryHit);
    const start = String(condition.onStart);
    const end = String(condition.onEnd);
    if (move.volatileStatus !== 'yawn' || move.accuracy !== true ||
        typeof move.onTryHit !== 'function' ||
        !tryHit.includes('target.status') ||
        !tryHit.includes('runStatusImmunity') || !tryHit.includes('slp') ||
        condition.duration !== 2 || condition.onResidualOrder !== 10 ||
        condition.onResidualSubOrder !== 19 ||
        typeof condition.onStart !== 'function' ||
        !start.includes('-start') || !start.includes('move: Yawn') ||
        typeof condition.onEnd !== 'function' ||
        !end.includes('trySetStatus') || !end.includes('slp')) {
      throw new Error('resolved Gen 3 Yawn shape changed');
    }
    for (const abilityID of ['insomnia', 'vitalspirit']) {
      const ability = dex.abilities.get(abilityID);
      const tryAdd = String(ability.onTryAddVolatile);
      const update = String(ability.onUpdate);
      if (typeof ability.onTryAddVolatile !== 'function' ||
          !tryAdd.includes('yawn') || !tryAdd.includes('return null') ||
          typeof ability.onUpdate !== 'function' ||
          !/pokemon\.status === ["']slp["']/.test(update) ||
          !update.includes('pokemon.cureStatus()')) {
        throw new Error(`resolved Gen 3 ${abilityID} sleep policy changed`);
      }
    }
    for (const [abilityID] of STATUS_ABILITY_UPDATE_HANDLERS) {
      const update = String(dex.abilities.get(abilityID).onUpdate);
      if (typeof dex.abilities.get(abilityID).onUpdate !== 'function' ||
          !update.includes('pokemon.cureStatus()')) {
        throw new Error(`resolved Gen 3 ${abilityID}.onUpdate changed`);
      }
    }
  }
  lines.push(`    {POKEMON_HANDLER_EVENT_TRY_ADD_VOLATILE, POKEMON_GEN3_HANDLER_INSOMNIA_TRY_ADD_YAWN, POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_INSOMNIA, 0, 0, 7, 0, 0, 0, 0, ${yawnProgramOffset + 2}, 3, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onTryAddVolatile"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_TRY_ADD_VOLATILE, POKEMON_GEN3_HANDLER_VITAL_SPIRIT_TRY_ADD_YAWN, POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_VITALSPIRIT, 0, 0, 7, 0, 0, 0, 0, ${yawnProgramOffset + 2}, 3, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onTryAddVolatile"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_TRY_HIT, POKEMON_GEN3_HANDLER_YAWN_TRY_HIT, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_YAWN, 0, 0, 0, 0, 0, 0, 0, ${yawnProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onTryHit"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_START, POKEMON_GEN3_HANDLER_YAWN_START, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_YAWN, 0, 0, 0, 0, 0, 0, 0, ${yawnProgramOffset + 5}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onStart"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_END, POKEMON_GEN3_HANDLER_YAWN_END, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_YAWN, 0, 0, 0, 0, 0, 0, 0, ${yawnProgramOffset + 1}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onEnd"},`);
  STATUS_ABILITY_UPDATE_HANDLERS.forEach(([abilityID, handlerToken], index) => {
    lines.push(`    {POKEMON_HANDLER_EVENT_UPDATE, POKEMON_GEN3_HANDLER_${handlerToken}_UPDATE, POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_${cName(abilityID)}, 0, 0, 7, 0, 0, 0, 0, ${sleepImmunityUpdateProgramOffset + index * 2}, 2, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onUpdate"},`);
  });
  {
    const move = dex.moves.get('spikes');
    const condition = move.condition;
    const start = String(condition.onSideStart);
    const restart = String(condition.onSideRestart);
    const entryHazard = String(condition.onEntryHazard);
    if (move.sideCondition !== 'spikes' || move.accuracy !== true ||
        move.target !== 'foeSide' || typeof condition.onSideStart !== 'function' ||
        !start.includes('layers = 1') ||
        typeof condition.onSideRestart !== 'function' ||
        !restart.includes('layers >= 3') || !restart.includes('layers++') ||
        typeof condition.onEntryHazard !== 'function' ||
        !entryHazard.includes('isGrounded') ||
        !entryHazard.includes('[0, 3, 4, 6]') ||
        !entryHazard.includes('/ 24')) {
      throw new Error('resolved Gen 3 Spikes shape changed');
    }
  }
  lines.push(`    {POKEMON_HANDLER_EVENT_START, POKEMON_GEN3_HANDLER_SPIKES_START, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_SIDE_SPIKES, 0, 0, 0, 0, 0, 0, 0, ${spikesProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onSideStart"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_RESTART, POKEMON_GEN3_HANDLER_SPIKES_RESTART, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_SIDE_SPIKES, 0, 0, 0, 0, 0, 0, 0, ${spikesProgramOffset + 1}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onSideRestart"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_ENTRY_HAZARD, POKEMON_GEN3_HANDLER_SPIKES_ENTRY_HAZARD, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_SIDE_SPIKES, 0, 0, 4, 0, 0, 0, 0, ${spikesProgramOffset + 2}, 2, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onEntryHazard"},`);
  for (const [index, id] of ['reflect', 'lightscreen'].entries()) {
    const condition = dex.moves.get(id).condition;
    const source = String(condition?.onAnyModifyDamagePhase1);
    const category = index === 0 ? 'Physical' : 'Special';
    if (typeof condition?.onAnyModifyDamagePhase1 !== 'function' ||
        !source.includes('target !== source') ||
        !source.includes('this.effectState.target.hasAlly(target)') ||
        !source.includes(`this.getCategory(move) === "${category}"`) ||
        !source.includes('!target.getMoveHitData(move).crit') ||
        !source.includes('!move.infiltrates') ||
        !source.includes('this.chainModify(0.5)')) {
      throw new Error(`resolved Gen 3 ${id}.onAnyModifyDamagePhase1 changed`);
    }
    const handler = index === 0 ? 'REFLECT' : 'LIGHT_SCREEN';
    const conditionToken = index === 0 ? 'REFLECT' : 'LIGHTSCREEN';
    lines.push(`    {POKEMON_HANDLER_EVENT_MODIFY_DAMAGE_PHASE1, POKEMON_GEN3_HANDLER_${handler}_MODIFY_DAMAGE_PHASE1, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_SIDE_${conditionToken}, 0, 0, 4, 0, 2048, 0, 1, ${screenProgramOffset + index * 5}, 5, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_ANY, POKEMON_HANDLER_ROUTE_OWNER, 0, "onAnyModifyDamagePhase1"},`);
  }
  lines.push(`    {POKEMON_HANDLER_EVENT_TRY, POKEMON_GEN3_HANDLER_ENDEAVOR_TRY_MOVE, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_ENDEAVOR, 0, 0, 0, 0, 0, 0, 0, ${endeavorTryProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onTry"},`);
  {
    const item = dex.items.get('leftovers');
    const source = String(item.onResidual);
    if (!item.exists || item.gen > 3 || typeof item.onResidual !== 'function' ||
        item.onResidualOrder !== 10 || item.onResidualSubOrder !== 4 ||
        !source.includes('pokemon.baseMaxhp / 16')) {
      throw new Error('resolved Gen 3 Leftovers shape changed');
    }
  }
  lines.push(`    {POKEMON_HANDLER_EVENT_RESIDUAL, POKEMON_GEN3_HANDLER_LEFTOVERS_RESIDUAL, POKEMON_HANDLER_SOURCE_ITEM, POKEMON_GEN3_ITEM_LEFTOVERS, 10, 0, 4, 0, 0, 0, 0, ${leftoversProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onResidual"},`);
  {
    const ability = dex.abilities.get('naturalcure');
    const source = String(ability.onSwitchOut);
    if (!ability.exists || ability.gen > 3 ||
        typeof ability.onSwitchOut !== 'function' ||
        ability.onCheckShow !== undefined ||
        !source.includes('pokemon.status ===') || !source.includes('fnt') ||
        !source.includes('pokemon.clearStatus()')) {
      throw new Error('resolved Gen 3 Natural Cure shape changed');
    }
  }
  lines.push(`    {POKEMON_HANDLER_EVENT_SWITCH_OUT, POKEMON_GEN3_HANDLER_NATURAL_CURE_SWITCH_OUT, POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_NATURALCURE, 0, 0, 7, 0, 0, 0, 0, ${naturalCureProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onSwitchOut"},`);
  {
    const ability = dex.abilities.get('shedskin');
    const source = String(ability.onResidual);
    if (!ability.exists || ability.gen > 3 ||
        typeof ability.onResidual !== 'function' ||
        ability.onResidualOrder !== 10 || ability.onResidualSubOrder !== 3 ||
        !source.includes('pokemon.hp && pokemon.status') ||
        !(source.includes('this.randomChance(33, 100)') ||
          (source.includes('verificationRandomChance') &&
           source.includes('ability.residual_status_cure'))) ||
        !source.includes('pokemon.cureStatus()')) {
      throw new Error('resolved Gen 3 Shed Skin shape changed');
    }
  }
  lines.push(`    {POKEMON_HANDLER_EVENT_RESIDUAL, POKEMON_GEN3_HANDLER_SHED_SKIN_RESIDUAL, POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_SHEDSKIN, 10, 0, 3, 0, 0, 0, 0, ${shedSkinProgramOffset}, 4, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onResidual"},`);
  {
    const ability = dex.abilities.get('speedboost');
    const source = String(ability.onResidual);
    if (!ability.exists || ability.gen > 3 ||
        typeof ability.onResidual !== 'function' ||
        ability.onResidualOrder !== 10 || ability.onResidualSubOrder !== 3 ||
        !source.includes('pokemon.activeTurns') ||
        !source.includes("this.boost({ spe: 1 })")) {
      throw new Error('resolved Gen 3 Speed Boost shape changed');
    }
  }
  {
    const ability = dex.abilities.get('pressure');
    const deduct = String(ability.onDeductPP);
    const start = String(ability.onStart);
    if (!ability.exists || ability.gen > 3 ||
        typeof ability.onDeductPP !== 'function' ||
        !deduct.includes('target === source') || !deduct.includes('return 1') ||
        typeof ability.onStart !== 'function' || !start.includes('Pressure')) {
      throw new Error('resolved Gen 3 Pressure shape changed');
    }
  }
  lines.push(`    {POKEMON_HANDLER_EVENT_DEDUCT_PP, POKEMON_GEN3_HANDLER_PRESSURE_DEDUCT_PP, POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_PRESSURE, 0, 0, 7, 0, 0, 0, 0, ${pressureProgramOffset}, 2, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onDeductPP"},`);
  lines.push('    {POKEMON_HANDLER_EVENT_START, POKEMON_GEN3_HANDLER_PRESSURE_START, POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_PRESSURE, 0, 0, 0, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onStart"},');
  {
    const ability = dex.abilities.get('damp');
    const source = String(ability.onAnyTryMove);
    if (!ability.exists || ability.gen > 3 ||
        typeof ability.onAnyTryMove !== 'function' ||
        !source.includes('"explosion"') || !source.includes('"selfdestruct"') ||
        !source.includes('return false')) {
      throw new Error('resolved Gen 3 Damp shape changed');
    }
  }
  lines.push(`    {POKEMON_HANDLER_EVENT_TRY_MOVE, POKEMON_GEN3_HANDLER_DAMP_TRY_MOVE, POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_DAMP, 0, 0, 7, 0, 0, 0, 0, ${dampProgramOffset}, 2, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_ANY, POKEMON_HANDLER_ROUTE_OWNER, 0, "onAnyTryMove"},`);
  {
    const ability = dex.abilities.get('flamebody');
    const source = String(ability.onDamagingHit);
    if (!ability.exists || ability.gen > 3 ||
        typeof ability.onDamagingHit !== 'function' ||
        !source.includes('damage &&') || !source.includes('move.flags["contact"]') ||
        !(source.includes('this.randomChance(1, 3)') ||
          source.includes('this.verificationRandomChance("ability.contact_response.activation", 1, 3)')) ||
        !source.includes('source.trySetStatus("brn"')) {
      throw new Error('resolved Gen 3 Flame Body shape changed');
    }
  }
  lines.push(`    {POKEMON_HANDLER_EVENT_DAMAGING_HIT, POKEMON_GEN3_HANDLER_FLAME_BODY_DAMAGING_HIT, POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_FLAMEBODY, 0, 0, 7, 0, 0, 0, 0, ${flameBodyProgramOffset}, 3, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onDamagingHit"},`);
  for (const [id, handler, programOffset, status] of [
    ['static', 'STATIC_DAMAGING_HIT', staticProgramOffset, 'par'],
    ['poisonpoint', 'POISON_POINT_DAMAGING_HIT', poisonPointProgramOffset, 'psn'],
  ]) {
    const ability = dex.abilities.get(id);
    const source = String(ability.onDamagingHit);
    if (!ability.exists || ability.gen > 3 ||
        typeof ability.onDamagingHit !== 'function' ||
        !source.includes('damage &&') || !source.includes('move.flags["contact"]') ||
        !(source.includes('this.randomChance(1, 3)') ||
          source.includes('this.verificationRandomChance("ability.contact_response.activation", 1, 3)')) ||
        !source.includes(`source.trySetStatus("${status}"`)) {
      throw new Error(`resolved Gen 3 ${id} shape changed`);
    }
    lines.push(`    {POKEMON_HANDLER_EVENT_DAMAGING_HIT, POKEMON_GEN3_HANDLER_${handler}, POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_${cName(id)}, 0, 0, 7, 0, 0, 0, 0, ${programOffset}, 3, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onDamagingHit"},`);
  }
  {
    const ability = dex.abilities.get('effectspore');
    const source = String(ability.onDamagingHit);
    if (!ability.exists || ability.gen > 3 ||
        typeof ability.onDamagingHit !== 'function' ||
        !source.includes('damage &&') || !source.includes('move.flags["contact"]') ||
        !(source.includes('this.randomChance(1, 10)') ||
          source.includes('this.verificationRandomChance("ability.contact_response.activation", 1, 10)')) ||
        !(source.includes('this.sample(["slp", "par", "psn"])') ||
          source.includes('this.verificationRandom(\n          "ability.contact_response.status"')) ||
        !source.includes('source.trySetStatus(status')) {
      throw new Error('resolved Gen 3 Effect Spore shape changed');
    }
  }
  lines.push(`    {POKEMON_HANDLER_EVENT_DAMAGING_HIT, POKEMON_GEN3_HANDLER_EFFECT_SPORE_DAMAGING_HIT, POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_EFFECTSPORE, 0, 0, 7, 0, 0, 0, 0, ${effectSporeProgramOffset}, 3, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onDamagingHit"},`);
  {
    const ability = dex.abilities.get('roughskin');
    const source = String(ability.onDamagingHit);
    if (!ability.exists || ability.gen > 3 ||
        typeof ability.onDamagingHit !== 'function' ||
        ability.onDamagingHitOrder !== 1 ||
        !source.includes('damage &&') || !source.includes('move.flags["contact"]') ||
        !source.includes('source.baseMaxhp / 16')) {
      throw new Error('resolved Gen 3 Rough Skin shape changed');
    }
  }
  lines.push(`    {POKEMON_HANDLER_EVENT_DAMAGING_HIT, POKEMON_GEN3_HANDLER_ROUGH_SKIN_DAMAGING_HIT, POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_ROUGHSKIN, 1, 0, 7, 0, 0, 0, 0, ${roughSkinProgramOffset}, 2, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onDamagingHit"},`);
  {
    const ability = dex.abilities.get('arenatrap');
    const source = String(ability.onFoeTrapPokemon);
    if (!ability.exists || ability.gen > 3 ||
        typeof ability.onFoeTrapPokemon !== 'function' ||
        typeof ability.onAnyTrapPokemon === 'function' ||
        !source.includes('pokemon.isAdjacent') ||
        !source.includes('pokemon.isGrounded()') ||
        !source.includes('pokemon.tryTrap(true)')) {
      throw new Error('resolved Gen 3 Arena Trap shape changed');
    }
  }
  lines.push(`    {POKEMON_HANDLER_EVENT_TRAP_POKEMON, POKEMON_GEN3_HANDLER_ARENA_TRAP_TRAP_POKEMON, POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_ARENATRAP, 0, 0, 7, 0, 0, 0, 0, ${arenaTrapProgramOffset}, 3, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_FOE, POKEMON_HANDLER_ROUTE_OWNER, 0, "onFoeTrapPokemon"},`);
  {
    const ability = dex.abilities.get('magnetpull');
    const source = String(ability.onAnyTrapPokemon);
    if (!ability.exists || ability.gen > 3 ||
        typeof ability.onFoeTrapPokemon === 'function' ||
        typeof ability.onAnyTrapPokemon !== 'function' ||
        !source.includes('pokemon.hasType("Steel")') ||
        !source.includes('pokemon.isAdjacent') ||
        !source.includes('pokemon.tryTrap(true)')) {
      throw new Error('resolved Gen 3 Magnet Pull shape changed');
    }
  }
  lines.push(`    {POKEMON_HANDLER_EVENT_TRAP_POKEMON, POKEMON_GEN3_HANDLER_MAGNET_PULL_TRAP_POKEMON, POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_MAGNETPULL, 0, 0, 7, 0, 0, 0, 0, ${magnetPullProgramOffset}, 3, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_ANY, POKEMON_HANDLER_ROUTE_OWNER, 0, "onAnyTrapPokemon"},`);
  {
    const move = dex.moves.get('fly');
    const invulnerability = String(move.condition?.onInvulnerability);
    if (move.basePower !== 70 || move.accuracy !== 95 ||
        move.type !== 'Flying' || !move.flags.charge ||
        typeof move.onTryMove !== 'function' ||
        typeof move.condition?.onInvulnerability !== 'function' ||
        !invulnerability.includes('"thunder"') ||
        !invulnerability.includes('return false')) {
      throw new Error('resolved Gen 3 Fly/Thunder invulnerability shape changed');
    }
  }
  lines.push(`    {POKEMON_HANDLER_EVENT_TRY_MOVE, POKEMON_GEN3_HANDLER_FLY_TRY_MOVE, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_FLY, 0, 0, 0, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_TWO_TURN_TRY_MOVE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onTryMove"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_INVULNERABILITY, POKEMON_GEN3_HANDLER_FLY_INVULNERABILITY, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_FLY, 0, 0, 2, 0, 0, 0, 0, ${flyInvulnerabilityProgramOffset}, 2, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onInvulnerability"},`);
  {
    const move = dex.moves.get('haze');
    const source = String(move.onHitField);
    if (move.accuracy !== true || move.target !== 'all' ||
        typeof move.onHitField !== 'function' ||
        !source.includes('this.getAllActive()') ||
        !source.includes('pokemon.clearBoosts()')) {
      throw new Error('resolved Gen 3 haze.onHitField changed');
    }
  }
  lines.push(`    {POKEMON_HANDLER_EVENT_MOVE_HIT_FIELD_CALLBACK, POKEMON_GEN3_HANDLER_HAZE_HIT_FIELD, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_HAZE, 0, 0, 0, 0, 0, 0, 0, ${hazeProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_FIELD, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onHitField"},`);
  {
    const sleep = dex.conditions.get('slp');
    const source = String(sleep.onStart);
    if (typeof sleep.onStart !== 'function' ||
        !source.includes('this.random(2, 6)') ||
        !source.includes('this.effectState.time') ||
        !source.includes('this.effectState.skippedTime = 0')) {
      throw new Error('resolved Gen 3 sleep.onStart changed');
    }
  }
  lines.push(`    {POKEMON_HANDLER_EVENT_START, POKEMON_GEN3_HANDLER_SLEEP_START, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_STATUS_SLP, 0, 0, 0, 0, 0, 0, 0, ${sleepStartProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onStart"},`);
  {
    const move = dex.moves.get('rest');
    const trySource = String(move.onTry);
    const hitSource = String(move.onHit);
    if (move.accuracy !== true || move.target !== 'self' ||
        !move.flags.snatch || !move.flags.heal ||
        typeof move.onTry !== 'function' || typeof move.onHit !== 'function' ||
        !trySource.includes('source.status === "slp"') ||
        !trySource.includes('source.hp === source.maxhp') ||
        !trySource.includes('source.hasAbility("insomnia")') ||
        !trySource.includes('source.hasAbility("vitalspirit")') ||
        !hitSource.includes('target.setStatus("slp"') ||
        !hitSource.includes('statusState.time = 3') ||
        !hitSource.includes('this.heal(target.maxhp)')) {
      throw new Error('resolved Gen 3 Rest callbacks changed');
    }
  }
  lines.push(`    {POKEMON_HANDLER_EVENT_TRY, POKEMON_GEN3_HANDLER_REST_TRY, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_REST, 0, 0, 0, 0, 0, 0, 0, ${restTryProgramOffset}, 3, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onTry"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK, POKEMON_GEN3_HANDLER_REST_HIT, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_REST, 0, 0, 0, 0, 0, 0, 0, ${restHitProgramOffset}, 3, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onHit"},`);
  {
    const ability = dex.abilities.get('synchronize');
    const source = String(ability.onAfterSetStatus);
    if (typeof ability.onAfterSetStatus !== 'function' ||
        !source.includes('source === target') ||
        !source.includes('id === "slp" || id === "frz"') ||
        !source.includes('if (id === "tox") id = "psn"') ||
        !source.includes('source.trySetStatus')) {
      throw new Error('resolved Gen 3 Synchronize callback changed');
    }
  }
  lines.push(`    {POKEMON_HANDLER_EVENT_AFTER_SET_STATUS, POKEMON_GEN3_HANDLER_SYNCHRONIZE_AFTER_SET_STATUS, POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_SYNCHRONIZE, 0, 0, 7, 0, 0, 0, 0, ${synchronizeProgramOffset}, 3, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onAfterSetStatus"},`);
  {
    const sleep = dex.conditions.get('slp');
    const beforeMoveSource = String(sleep.onBeforeMove);
    const switchInSource = String(sleep.onSwitchIn);
    if (sleep.onBeforeMovePriority !== 10 ||
        typeof sleep.onBeforeMove !== 'function' ||
        !beforeMoveSource.includes('pokemon.hasAbility("earlybird")') ||
        !beforeMoveSource.includes('pokemon.statusState.time--') ||
        !beforeMoveSource.includes('move.sleepUsable') ||
        !beforeMoveSource.includes('this.effectState.skippedTime++') ||
        !beforeMoveSource.includes('return false') ||
        typeof sleep.onSwitchIn !== 'function' ||
        !switchInSource.includes('this.effectState.time += this.effectState.skippedTime') ||
        !switchInSource.includes('this.effectState.skippedTime = 0')) {
      throw new Error('resolved Gen 3 sleep lifecycle callbacks changed');
    }
  }
  lines.push(`    {POKEMON_HANDLER_EVENT_BEFORE_MOVE, POKEMON_GEN3_HANDLER_SLEEP_BEFORE_MOVE, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_STATUS_SLP, 0, 10, 0, 0, 0, 0, 0, ${sleepBeforeMoveProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onBeforeMove"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_SWITCH_IN, POKEMON_GEN3_HANDLER_SLEEP_SWITCH_IN, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_STATUS_SLP, 0, 0, 0, 0, 0, 0, 0, ${sleepSwitchInProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onSwitchIn"},`);
  {
    const move = dex.moves.get('snore');
    const source = String(move.onTry);
    if (move.sleepUsable !== true || move.basePower !== 40 ||
        move.accuracy !== 100 || move.type !== 'Normal' ||
        move.category !== 'Physical' || move.target !== 'normal' ||
        move.secondary?.chance !== 30 ||
        move.secondary?.volatileStatus !== 'flinch' ||
        typeof move.onTry !== 'function' ||
        !source.includes('source.status === "slp"')) {
      throw new Error('resolved Gen 3 Snore shape changed');
    }
  }
  lines.push(`    {POKEMON_HANDLER_EVENT_TRY, POKEMON_GEN3_HANDLER_SNORE_TRY, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_SNORE, 0, 0, 0, 0, 0, 0, 0, ${snoreTryProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onTry"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_RESIDUAL, POKEMON_GEN3_HANDLER_SPEED_BOOST_RESIDUAL, POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_SPEEDBOOST, 10, 0, 3, 0, 0, 0, 0, ${speedBoostProgramOffset}, 3, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onResidual"},`);
  {
    const move = dex.moves.get('nightmare');
    const start = String(move.condition?.onStart);
    const residual = String(move.condition?.onResidual);
    if (!start.includes('pokemon.status !== "slp"') ||
        !residual.includes('pokemon.baseMaxhp / 4')) {
      throw new Error('resolved Gen 3 Nightmare handler bodies changed');
    }
  }
  lines.push(`    {POKEMON_HANDLER_EVENT_START, POKEMON_GEN3_HANDLER_NIGHTMARE_START, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_NIGHTMARE, 0, 0, 0, 0, 0, 0, 0, ${nightmareProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onStart"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_RESIDUAL, POKEMON_GEN3_HANDLER_NIGHTMARE_RESIDUAL, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_NIGHTMARE, 10, 0, 7, 0, 0, 0, 0, ${nightmareProgramOffset + 1}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onResidual"},`);
  {
    const ability = dex.abilities.get('intimidate');
    const source = String(ability.onStart);
    if (typeof ability.onStart !== 'function' ||
        !source.includes('pokemon.adjacentFoes()') ||
        !source.includes('target.volatiles["substitute"]') ||
        !source.includes('this.boost({ atk: -1 }, target, pokemon, null, true)')) {
      throw new Error('resolved Gen 3 Intimidate callback changed');
    }
  }
  lines.push(`    {POKEMON_HANDLER_EVENT_START, POKEMON_GEN3_HANDLER_INTIMIDATE_START, POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_INTIMIDATE, 0, 0, 0, 0, 0, 0, 0, ${intimidateProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onStart"},`);
  {
    const ability = dex.abilities.get('trace');
    const source = String(ability.onStart);
    if (ability.onUpdate !== undefined || !source.includes('side.randomFoe()') ||
        !source.includes('pokemon.setAbility(ability, target)')) {
      throw new Error('resolved Gen 3 Trace boundary changed');
    }
  }
  lines.push(`    {POKEMON_HANDLER_EVENT_START, POKEMON_GEN3_HANDLER_TRACE_START, POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_TRACE, 0, 0, 0, 0, 0, 0, 0, ${traceProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onStart"},`);
  {
    const ability = dex.abilities.get('colorchange');
    const source = String(ability.onDamagingHit);
    if (typeof ability.onDamagingHit !== 'function' ||
        ability.onAfterMoveSecondary !== undefined ||
        !source.includes('move.category !== "Status"') ||
        !source.includes('type !== "???"') ||
        !source.includes('!target.hasType(type)') ||
        !source.includes('target.setType(type)')) {
      throw new Error('resolved Gen 3 Color Change boundary changed');
    }
  }
  lines.push(`    {POKEMON_HANDLER_EVENT_DAMAGING_HIT, POKEMON_GEN3_HANDLER_COLOR_CHANGE_DAMAGING_HIT, POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_COLORCHANGE, 0, 0, 7, 0, 0, 0, 0, ${colorChangeProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onDamagingHit"},`);
  {
    const ability = dex.abilities.get('cutecharm');
    const damagingHit = String(ability.onDamagingHit);
    const condition = dex.moves.get('attract').condition;
    const tryImmunity = String(dex.moves.get('attract').onTryImmunity);
    const start = String(condition?.onStart);
    const beforeMove = String(condition?.onBeforeMove);
    const update = String(condition?.onUpdate);
    const end = String(condition?.onEnd);
    if (typeof ability.onDamagingHit !== 'function' ||
        !damagingHit.includes('damage && move.flags["contact"]') ||
        !damagingHit.includes('this.randomChance(1, 3)') ||
        !damagingHit.includes('source.addVolatile("attract", target)') ||
        !tryImmunity.includes('target.gender === "M"') ||
        !tryImmunity.includes('source.gender === "F"') ||
        condition?.noCopy !== true || condition?.onBeforeMovePriority !== 2 ||
        !start.includes('pokemon.gender === "M"') ||
        !start.includes('source.gender === "F"') ||
        !start.includes('this.runEvent("Attract", pokemon, source)') ||
        !beforeMove.includes('this.randomChance(1, 2)') ||
        !beforeMove.includes('return false') ||
        !update.includes('!this.effectState.source.isActive') ||
        !update.includes('pokemon.removeVolatile("attract")') ||
        !end.includes('this.add("-end", pokemon, "Attract", "[silent]")')) {
      throw new Error('resolved Gen 3 Cute Charm/Attract boundary changed');
    }
  }
  lines.push(`    {POKEMON_HANDLER_EVENT_DAMAGING_HIT, POKEMON_GEN3_HANDLER_CUTE_CHARM_DAMAGING_HIT, POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_CUTECHARM, 0, 0, 7, 0, 0, 0, 0, ${cuteCharmProgramOffset}, 3, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onDamagingHit"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_TRY_IMMUNITY, POKEMON_GEN3_HANDLER_ATTRACT_TRY_IMMUNITY, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_ATTRACT, 0, 0, 0, 0, 0, 0, 0, ${attractStartProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onTryImmunity"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_START, POKEMON_GEN3_HANDLER_ATTRACT_START, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_ATTRACT, 0, 0, 0, 0, 0, 0, 0, ${attractStartProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onStart"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_BEFORE_MOVE, POKEMON_GEN3_HANDLER_ATTRACT_BEFORE_MOVE, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_ATTRACT, 0, 2, 2, 0, 0, 0, 0, ${attractBeforeMoveProgramOffset}, 2, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onBeforeMove"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_UPDATE, POKEMON_GEN3_HANDLER_ATTRACT_UPDATE, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_ATTRACT, 0, 0, 0, 0, 0, 0, 0, ${attractUpdateProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onUpdate"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_END, POKEMON_GEN3_HANDLER_ATTRACT_END, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_ATTRACT, 0, 0, 0, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onEnd"},`);
  {
    const paralysis = dex.conditions.get('par');
    const beforeMoveSource = String(paralysis.onBeforeMove);
    const startSource = String(paralysis.onStart);
    if (typeof paralysis.onStart !== 'function' ||
        !startSource.includes('sourceEffect.effectType === "Ability"') ||
        !startSource.includes('this.add("-status", target, "par"') ||
        paralysis.onBeforeMovePriority !== 1 ||
        typeof paralysis.onBeforeMove !== 'function' ||
        !/(?:randomChance\(1, 4\)|RandomChance\([^,]+, 1, 4\))/.test(beforeMoveSource) ||
        !/this\.add\(["']cant["'], pokemon, ["']par["']\)/.test(beforeMoveSource) ||
        !beforeMoveSource.includes('return false')) {
      throw new Error('resolved Gen 3 paralysis action callback changed');
    }
  }
  lines.push(`    {POKEMON_HANDLER_EVENT_BEFORE_MOVE, POKEMON_GEN3_HANDLER_PARALYSIS_BEFORE_MOVE, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_STATUS_PAR, 0, 1, 0, 0, 0, 0, 0, ${paralysisBeforeMoveProgramOffset}, 2, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onBeforeMove"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_START, POKEMON_GEN3_HANDLER_PARALYSIS_START, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_STATUS_PAR, 0, 0, 0, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onStart"},`);
  {
    const scale = dex.items.get('deepseascale');
    const tooth = dex.items.get('deepseatooth');
    const lightBall = dex.items.get('lightball');
    const machoBrace = dex.items.get('machobrace');
    const soulDew = dex.items.get('souldew');
    const callbackNames = item => Object.keys(item).filter(key =>
      /^on[A-Z]/.test(key) && !/(?:Order|Priority|SubOrder)$/.test(key) &&
      typeof item[key] === 'function');
    if (scale.num !== 227 || scale.onModifySpDPriority !== 2 ||
        JSON.stringify(callbackNames(scale)) !== JSON.stringify(['onModifySpD']) ||
        typeof scale.onModifySpD !== 'function' ||
        !String(scale.onModifySpD).includes('pokemon.species.name === "Clamperl"') ||
        !String(scale.onModifySpD).includes('this.chainModify(2)') ||
        tooth.num !== 226 || tooth.onModifySpAPriority !== 1 ||
        JSON.stringify(callbackNames(tooth)) !== JSON.stringify(['onModifySpA']) ||
        typeof tooth.onModifySpA !== 'function' ||
        !String(tooth.onModifySpA).includes('pokemon.species.name === "Clamperl"') ||
        !String(tooth.onModifySpA).includes('this.chainModify(2)') ||
        lightBall.num !== 236 || lightBall.onModifySpAPriority !== 1 ||
        JSON.stringify(callbackNames(lightBall)) !== JSON.stringify(['onModifySpA']) ||
        typeof lightBall.onModifySpA !== 'function' ||
        lightBall.onModifyAtk !== undefined || lightBall.onBasePower !== undefined ||
        !String(lightBall.onModifySpA).includes('pokemon.species.name === "Pikachu"') ||
        !String(lightBall.onModifySpA).includes('this.chainModify(2)') ||
        machoBrace.num !== 215 || typeof machoBrace.onModifySpe !== 'function' ||
        machoBrace.onModifySpePriority !== undefined ||
        machoBrace.onModifySpeOrder !== undefined ||
        machoBrace.onModifySpeSubOrder !== undefined ||
        JSON.stringify(callbackNames(machoBrace)) !== JSON.stringify(['onModifySpe']) ||
        !String(machoBrace.onModifySpe).includes('this.chainModify(0.5)') ||
        soulDew.num !== 225 || soulDew.onModifySpAPriority !== 1 ||
        soulDew.onModifySpDPriority !== 2 ||
        soulDew.onBasePower !== undefined ||
        JSON.stringify(callbackNames(soulDew)) !==
          JSON.stringify(['onModifySpA', 'onModifySpD']) ||
        typeof soulDew.onModifySpA !== 'function' ||
        typeof soulDew.onModifySpD !== 'function' ||
        !String(soulDew.onModifySpA).includes('pokemon.baseSpecies.num === 380') ||
        !String(soulDew.onModifySpA).includes('pokemon.baseSpecies.num === 381') ||
        !String(soulDew.onModifySpA).includes('this.chainModify(1.5)') ||
        !String(soulDew.onModifySpD).includes('pokemon.baseSpecies.num === 380') ||
        !String(soulDew.onModifySpD).includes('pokemon.baseSpecies.num === 381') ||
        !String(soulDew.onModifySpD).includes('this.chainModify(1.5)')) {
      throw new Error('resolved Gen 3 species-conditioned stat-item shape changed');
    }
  }
  lines.push(`    {POKEMON_HANDLER_EVENT_MODIFY_SPD, POKEMON_GEN3_HANDLER_DEEP_SEA_SCALE_SPD, POKEMON_HANDLER_SOURCE_ITEM, POKEMON_GEN3_ITEM_DEEPSEASCALE, 0, 2, 8, 0, 8192, 0, 0, ${deepSeaScaleProgramOffset}, 2, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onModifySpD"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_MODIFY_SPA, POKEMON_GEN3_HANDLER_DEEP_SEA_TOOTH_SPA, POKEMON_HANDLER_SOURCE_ITEM, POKEMON_GEN3_ITEM_DEEPSEATOOTH, 0, 1, 8, 0, 8192, 0, 0, ${deepSeaToothProgramOffset}, 2, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onModifySpA"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_MODIFY_SPA, POKEMON_GEN3_HANDLER_LIGHT_BALL_SPA, POKEMON_HANDLER_SOURCE_ITEM, POKEMON_GEN3_ITEM_LIGHTBALL, 0, 1, 8, 0, 8192, 0, 0, ${lightBallProgramOffset}, 2, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onModifySpA"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_MODIFY_SPE, POKEMON_GEN3_HANDLER_MACHO_BRACE_SPEED, POKEMON_HANDLER_SOURCE_ITEM, POKEMON_GEN3_ITEM_MACHOBRACE, 0, 0, 8, 0, 2048, 0, 0, ${machoBraceProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onModifySpe"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_MODIFY_SPA, POKEMON_GEN3_HANDLER_SOUL_DEW_SPA, POKEMON_HANDLER_SOURCE_ITEM, POKEMON_GEN3_ITEM_SOULDEW, 0, 1, 8, 0, 6144, 0, 0, ${soulDewProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onModifySpA"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_MODIFY_SPD, POKEMON_GEN3_HANDLER_SOUL_DEW_SPD, POKEMON_HANDLER_SOURCE_ITEM, POKEMON_GEN3_ITEM_SOULDEW, 0, 2, 8, 0, 6144, 0, 0, ${soulDewProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onModifySpD"},`);
  {
    const item = dex.items.get('whiteherb');
    const start = String(item.onStart);
    const anySwitchIn = String(item.onAnySwitchIn);
    const anyAfterMove = String(item.onAnyAfterMove);
    const residual = String(item.onResidual);
    const use = String(item.onUse);
    if (typeof item.onStart !== 'function' ||
        !start.includes('pokemon.boosts[i] < 0') ||
        !start.includes('this.effectState.boosts[i] = 0') ||
        !start.includes('useItem()') ||
        typeof item.onAnySwitchIn !== 'function' ||
        item.onAnySwitchInPriority !== -2 || !anySwitchIn.includes('onStart') ||
        typeof item.onAnyAfterMove !== 'function' ||
        !anyAfterMove.includes('onStart') ||
        typeof item.onResidual !== 'function' || item.onResidualOrder !== 29 ||
        !residual.includes('onStart') || typeof item.onUse !== 'function' ||
        !use.includes('setBoost(this.effectState.boosts)') ||
        item.onUpdate !== undefined) {
      throw new Error('resolved Gen 3 whiteherb lifecycle changed');
    }
  }
  lines.push(`    {POKEMON_HANDLER_EVENT_START, POKEMON_GEN3_HANDLER_WHITE_HERB_START, POKEMON_HANDLER_SOURCE_ITEM, POKEMON_GEN3_ITEM_WHITEHERB, 0, 0, 0, 0, 0, 0, 0, ${whiteHerbProgramOffset}, 3, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onStart"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_SWITCH_IN, POKEMON_GEN3_HANDLER_WHITE_HERB_ANY_SWITCH_IN, POKEMON_HANDLER_SOURCE_ITEM, POKEMON_GEN3_ITEM_WHITEHERB, 0, -2, 8, 0, 0, 0, 0, ${whiteHerbProgramOffset}, 3, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_ANY, POKEMON_HANDLER_ROUTE_OWNER, 0, "onAnySwitchIn"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_AFTER_MOVE, POKEMON_GEN3_HANDLER_WHITE_HERB_ANY_AFTER_MOVE, POKEMON_HANDLER_SOURCE_ITEM, POKEMON_GEN3_ITEM_WHITEHERB, 0, 0, 8, 0, 0, 0, 0, ${whiteHerbProgramOffset}, 3, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_ANY, POKEMON_HANDLER_ROUTE_OWNER, 0, "onAnyAfterMove"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_RESIDUAL, POKEMON_GEN3_HANDLER_WHITE_HERB_RESIDUAL, POKEMON_HANDLER_SOURCE_ITEM, POKEMON_GEN3_ITEM_WHITEHERB, 29, 0, 8, 0, 0, 0, 0, ${whiteHerbProgramOffset}, 3, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onResidual"},`);
  {
    const item = dex.items.get('mentalherb');
    const source = String(item.onUpdate);
    if (typeof item.onUpdate !== 'function' ||
        !/volatiles\[["']attract["']\]/.test(source) ||
        !source.includes('pokemon.useItem()') ||
        !/removeVolatile\(["']attract["']\)/.test(source) ||
        source.includes('taunt') || source.includes('encore') ||
        source.includes('torment') || source.includes('disable')) {
      throw new Error('resolved Gen 3 mentalherb.onUpdate changed');
    }
  }
  lines.push(`    {POKEMON_HANDLER_EVENT_UPDATE, POKEMON_GEN3_HANDLER_MENTAL_HERB_UPDATE, POKEMON_HANDLER_SOURCE_ITEM, POKEMON_GEN3_ITEM_MENTALHERB, 0, 0, 8, 0, 0, 0, 0, ${mentalHerbProgramOffset}, 3, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onUpdate"},`);
  {
    const move = dex.moves.get('falseswipe');
    const source = String(move.onDamage);
    if (move.basePower !== 40 || move.accuracy !== 100 ||
        move.category !== 'Physical' || move.type !== 'Normal' ||
        move.onDamagePriority !== -20 ||
        typeof move.onDamage !== 'function' ||
        !source.includes('damage >= target.hp') ||
        !source.includes('target.hp - 1')) {
      throw new Error('resolved Gen 3 False Swipe Damage callback changed');
    }
  }
  lines.push(`    {POKEMON_HANDLER_EVENT_DAMAGE, POKEMON_GEN3_HANDLER_FALSE_SWIPE_DAMAGE, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_FALSESWIPE, 0, -20, 0, 0, 0, 0, 0, ${falseSwipeDamageProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_SOURCE_EFFECT, 0, "onDamage"},`);
  {
    const item = dex.items.get('choiceband');
    const attack = String(item.onModifyAtk);
    const afterMove = String(item.onAfterMove);
    if (item.onModifyAtkPriority !== 1 || typeof item.onModifyAtk !== 'function' ||
        !attack.includes('this.chainModify(1.5)') ||
        typeof item.onAfterMove !== 'function' ||
        !/addVolatile\(["']choicelock["']\)/.test(afterMove) ||
        item.onStart !== undefined || item.onModifyMove !== undefined) {
      throw new Error('resolved Gen 3 Choice Band lifecycle changed');
    }
    const lock = dex.conditions.get('choicelock');
    if (typeof lock.onStart !== 'function' ||
        !String(lock.onStart).includes('pokemon.lastMove') ||
        typeof lock.onDisableMove !== 'function' ||
        lock.onBeforeMove !== undefined) {
      throw new Error('resolved Gen 3 choice-lock condition changed');
    }
  }
  lines.push(`    {POKEMON_HANDLER_EVENT_MODIFY_ATK, POKEMON_GEN3_HANDLER_CHOICE_BAND_MODIFY_ATK, POKEMON_HANDLER_SOURCE_ITEM, POKEMON_GEN3_ITEM_CHOICEBAND, 0, 1, 8, 0, 6144, 0, 0, ${choiceBandModifyAtkProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onModifyAtk"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_AFTER_MOVE, POKEMON_GEN3_HANDLER_CHOICE_BAND_AFTER_MOVE, POKEMON_HANDLER_SOURCE_ITEM, POKEMON_GEN3_ITEM_CHOICEBAND, 0, 0, 8, 0, 0, 0, 0, ${choiceBandAfterMoveProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_OWNER, 0, "onAfterMove"},`);
  {
    const aromatherapy = dex.moves.get('aromatherapy');
    const healBell = dex.moves.get('healbell');
    const aromaSource = String(aromatherapy.onHit);
    const bellSource = String(healBell.onHit);
    if (aromatherapy.accuracy !== true || aromatherapy.target !== 'allyTeam' ||
        typeof aromatherapy.onHit !== 'function' ||
        !aromaSource.includes('target.side.pokemon') ||
        !aromaSource.includes('ally.clearStatus()') ||
        healBell.accuracy !== true || healBell.target !== 'allyTeam' ||
        typeof healBell.onHit !== 'function' ||
        !bellSource.includes('ally.hasAbility("soundproof")') ||
        !bellSource.includes('ally.cureStatus(true)') ||
        !constraints.banlist.includes('Soundproof')) {
      throw new Error('resolved Gen 3 team status-cure callbacks changed');
    }
  }
  lines.push(`    {POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK, POKEMON_GEN3_HANDLER_AROMATHERAPY_HIT, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_AROMATHERAPY, 0, 0, 0, 0, 0, 0, 0, ${aromatherapyProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onHit"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK, POKEMON_GEN3_HANDLER_HEAL_BELL_HIT, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_HEALBELL, 0, 0, 0, 0, 0, 0, 0, ${healBellProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onHit"},`);
  {
    const freeze = dex.conditions.get('frz');
    const start = String(freeze.onStart);
    const beforeMove = String(freeze.onBeforeMove);
    const modifyMove = String(freeze.onModifyMove);
    const damagingHit = String(freeze.onDamagingHit);
    if (freeze.effectType !== 'Status' ||
        freeze.onBeforeMovePriority !== 10 ||
        typeof freeze.onStart !== 'function' || !start.includes('"-status"') ||
        typeof freeze.onBeforeMove !== 'function' ||
        !beforeMove.includes('randomChance(1, 5)') ||
        !beforeMove.includes('move.flags["defrost"]') ||
        typeof freeze.onModifyMove !== 'function' ||
        !modifyMove.includes('move.flags["defrost"]') ||
        !modifyMove.includes('pokemon.clearStatus()') ||
        typeof freeze.onDamagingHit !== 'function' ||
        !damagingHit.includes('this.dex.moves.get(move.id).type') ||
        !damagingHit.includes('=== "Fire"') ||
        !damagingHit.includes('move.category !== "Status"')) {
      throw new Error('resolved Gen 3 freeze lifecycle changed');
    }
  }
  lines.push(`    {POKEMON_HANDLER_EVENT_START, POKEMON_GEN3_HANDLER_FREEZE_START, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_STATUS_FRZ, 0, 0, 0, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onStart"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_BEFORE_MOVE, POKEMON_GEN3_HANDLER_FREEZE_BEFORE_MOVE, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_STATUS_FRZ, 0, 10, 0, 0, 0, 0, 0, ${freezeBeforeMoveProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onBeforeMove"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_MODIFY_MOVE, POKEMON_GEN3_HANDLER_FREEZE_MODIFY_MOVE, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_STATUS_FRZ, 0, 0, 0, 0, 0, 0, 0, ${freezeModifyMoveProgramOffset}, 3, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onModifyMove"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_DAMAGING_HIT, POKEMON_GEN3_HANDLER_FREEZE_DAMAGING_HIT, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_STATUS_FRZ, 0, 0, 0, 0, 0, 0, 0, ${freezeDamagingHitProgramOffset}, 3, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onDamagingHit"},`);
  {
    const oblivious = dex.abilities.get('oblivious');
    const immunity = String(oblivious.onImmunity);
    const tryHit = String(oblivious.onTryHit);
    const update = String(oblivious.onUpdate);
    if (typeof oblivious.onImmunity !== 'function' ||
        !immunity.includes('type === "attract"') ||
        typeof oblivious.onTryHit !== 'function' ||
        !tryHit.includes('move.id === "captivate"') ||
        typeof oblivious.onUpdate !== 'function' ||
        !update.includes('removeVolatile("attract")') ||
        oblivious.onTryBoost !== undefined) {
      throw new Error('resolved Gen 3 Oblivious lifecycle changed');
    }
  }
  lines.push(`    {POKEMON_HANDLER_EVENT_IMMUNITY, POKEMON_GEN3_HANDLER_OBLIVIOUS_IMMUNITY, POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_OBLIVIOUS, 0, 0, 7, 0, 0, 0, 0, ${obliviousImmunityProgramOffset}, 2, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onImmunity"},`);
  /* Captivate is absent from the legal Gen 3 move inventory.  Keep the
   * inherited callback structurally visible without adding a later-gen ID. */
  lines.push(`    {POKEMON_HANDLER_EVENT_TRY_HIT, POKEMON_GEN3_HANDLER_OBLIVIOUS_TRY_HIT, POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_OBLIVIOUS, 0, 0, 7, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onTryHit"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_UPDATE, POKEMON_GEN3_HANDLER_OBLIVIOUS_UPDATE, POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_OBLIVIOUS, 0, 0, 7, 0, 0, 0, 0, ${obliviousUpdateProgramOffset}, 2, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onUpdate"},`);
  {
    const rolePlay = dex.moves.get('roleplay');
    const tryHit = String(rolePlay.onTryHit);
    const hit = String(rolePlay.onHit);
    if (rolePlay.accuracy !== true || rolePlay.target !== 'normal' ||
        !rolePlay.flags?.bypasssub || typeof rolePlay.onTryHit !== 'function' ||
        !tryHit.includes('target.ability === source.ability') ||
        !tryHit.includes('flags["failroleplay"]') ||
        !tryHit.includes('flags["cantsuppress"]') ||
        typeof rolePlay.onHit !== 'function' ||
        !hit.includes('source.setAbility(target.ability, target)')) {
      throw new Error('resolved Gen 3 Role Play ability-transfer shape changed');
    }
  }
  lines.push(`    {POKEMON_HANDLER_EVENT_TRY_HIT, POKEMON_GEN3_HANDLER_ROLE_PLAY_TRY_HIT, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_ROLEPLAY, 0, 0, 0, 0, 0, 0, 0, ${rolePlayTryHitProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onTryHit"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK, POKEMON_GEN3_HANDLER_ROLE_PLAY_HIT, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_ROLEPLAY, 0, 0, 0, 0, 0, 0, 0, ${rolePlayHitProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onHit"},`);
	{
		const skillSwap = dex.moves.get('skillswap');
		const hit = String(skillSwap.onHit);
		if (skillSwap.accuracy !== true || skillSwap.target !== 'normal' ||
			!skillSwap.flags?.bypasssub || typeof skillSwap.onHit !== 'function' ||
			!hit.includes('this.skillSwap(source, target)')) {
			throw new Error('resolved Gen 3 Skill Swap transaction changed');
		}
	}
	lines.push(`    {POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK, POKEMON_GEN3_HANDLER_SKILL_SWAP_HIT, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_SKILLSWAP, 0, 0, 0, 0, 0, 0, 0, ${skillSwapHitProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onHit"},`);
	for (const id of ['block', 'meanlook', 'spiderweb']) {
		const move = dex.moves.get(id);
		const hit = String(move.onHit);
		if (move.accuracy !== true || move.target !== 'normal' ||
			!move.flags?.protect || typeof move.onHit !== 'function' ||
			!/addVolatile\(["']trapped["']/.test(hit) ||
			!/["']trapper["']/.test(hit)) {
			throw new Error(`resolved Gen 3 source-trap move changed: ${id}`);
		}
	}
	{
		const trapped = dex.conditions.get('trapped');
		const trapper = dex.conditions.get('trapper');
		if (trapped.noCopy !== false || trapper.noCopy !== false ||
			typeof trapped.onStart !== 'function' ||
			!/["']trapped["']/.test(String(trapped.onStart)) ||
			typeof trapped.onTrapPokemon !== 'function' ||
			!String(trapped.onTrapPokemon).includes('tryTrap()')) {
			throw new Error('resolved Gen 3 linked trapped condition changed');
		}
	}
	lines.push(`    {POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK, POKEMON_GEN3_HANDLER_BLOCK_HIT, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_BLOCK, 0, 0, 0, 0, 0, 0, 0, ${sourceTrapHitProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onHit"},`);
	lines.push(`    {POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK, POKEMON_GEN3_HANDLER_MEAN_LOOK_HIT, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_MEANLOOK, 0, 0, 0, 0, 0, 0, 0, ${sourceTrapHitProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onHit"},`);
	lines.push(`    {POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK, POKEMON_GEN3_HANDLER_SPIDER_WEB_HIT, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_SPIDERWEB, 0, 0, 0, 0, 0, 0, 0, ${sourceTrapHitProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onHit"},`);
	lines.push(`    {POKEMON_HANDLER_EVENT_START, POKEMON_GEN3_HANDLER_TRAPPED_START, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_TRAPPED, 0, 0, 0, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onStart"},`);
	lines.push(`    {POKEMON_HANDLER_EVENT_TRAP_POKEMON, POKEMON_GEN3_HANDLER_TRAPPED_TRAP_POKEMON, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_TRAPPED, 0, 0, 2, 0, 0, 0, 0, ${trappedTrapPokemonProgramOffset}, 2, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onTrapPokemon"},`);
	{
		const metalPowder = dex.items.get('metalpowder');
		const source = String(metalPowder.onModifyDef);
		if (metalPowder.num !== 257 || metalPowder.onModifyDefPriority !== 2 ||
			typeof metalPowder.onModifyDef !== 'function' ||
			!/pokemon\.species\.name === ["']Ditto["']/.test(source) ||
			!source.includes('!pokemon.transformed') ||
			!source.includes('this.chainModify(2)')) {
			throw new Error('resolved Gen 3 metalpowder.onModifyDef changed');
		}
	}
	lines.push(`    {POKEMON_HANDLER_EVENT_MODIFY_DEF, POKEMON_GEN3_HANDLER_METAL_POWDER_MODIFY_DEF, POKEMON_HANDLER_SOURCE_ITEM, POKEMON_GEN3_ITEM_METALPOWDER, 0, 2, 8, 0, 8192, 0, 0, ${metalPowderProgramOffset}, 2, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onModifyDef"},`);
	for (const [id, handler] of [
		['bounce', 'BOUNCE'], ['dig', 'DIG'], ['dive', 'DIVE'],
		['razorwind', 'RAZOR_WIND'], ['skullbash', 'SKULL_BASH'],
		['skyattack', 'SKY_ATTACK'],
	]) {
		const move = dex.moves.get(id);
		if (!move.exists || move.gen > 3 || !move.flags?.charge ||
			typeof move.onTryMove !== 'function' ||
			!String(move.onTryMove).includes("addVolatile('twoturnmove'") &&
			!String(move.onTryMove).includes('addVolatile("twoturnmove"')) {
			throw new Error(`resolved Gen 3 ${id}.onTryMove changed`);
		}
		lines.push(`    {POKEMON_HANDLER_EVENT_TRY_MOVE, POKEMON_GEN3_HANDLER_${handler}_TRY_MOVE, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_${cName(id)}, 0, 0, 0, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_TWO_TURN_TRY_MOVE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onTryMove"},`);
	}
	for (const [id, state, bypasses, doubles] of [
		['bounce', 'AIRBORNE', ['gust', 'twister', 'skyuppercut', 'thunder'], ['gust', 'twister']],
		['dig', 'UNDERGROUND', ['earthquake', 'magnitude'], ['earthquake', 'magnitude']],
		['dive', 'UNDERWATER', ['surf', 'whirlpool'], ['surf', 'whirlpool']],
	]) {
		const condition = dex.moves.get(id).condition;
		const invulnerability = String(condition?.onInvulnerability);
		const damage = String(condition?.onSourceBasePower || condition?.onSourceModifyDamage);
		const immunity = String(condition?.onImmunity);
		if (typeof condition?.onInvulnerability !== 'function' ||
			!bypasses.every(move => invulnerability.includes(`"${move}"`)) ||
			!doubles.every(move => damage.includes(`"${move}"`)) ||
			!damage.includes('chainModify(2)') ||
			((id === 'dig' || id === 'dive') &&
			 (typeof condition?.onImmunity !== 'function' ||
			  !/type === ["']sandstorm["']/.test(immunity) ||
			  !/type === ["']hail["']/.test(immunity) ||
			  !immunity.includes('return false')))) {
			throw new Error(`resolved Gen 3 ${id} hidden-target policy changed`);
		}
	}
	lines.push(`    {POKEMON_HANDLER_EVENT_INVULNERABILITY, POKEMON_GEN3_HANDLER_BOUNCE_INVULNERABILITY, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_BOUNCE, 0, 0, 2, 0, 0, 0, 0, ${flyInvulnerabilityProgramOffset}, 2, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onInvulnerability"},`);
	lines.push(`    {POKEMON_HANDLER_EVENT_BASE_POWER, POKEMON_GEN3_HANDLER_BOUNCE_SOURCE_BASE_POWER, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_BOUNCE, 0, 0, 2, 0, 8192, 0, 1, ${airborneDoubleProgramOffset}, 2, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_FOE, POKEMON_HANDLER_ROUTE_OWNER, 0, "onSourceBasePower"},`);
	lines.push(`    {POKEMON_HANDLER_EVENT_INVULNERABILITY, POKEMON_GEN3_HANDLER_DIG_INVULNERABILITY, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_DIG, 0, 0, 2, 0, 0, 0, 0, ${undergroundInvulnerabilityProgramOffset}, 2, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onInvulnerability"},`);
	lines.push(`    {POKEMON_HANDLER_EVENT_MODIFY_DAMAGE, POKEMON_GEN3_HANDLER_DIG_SOURCE_MODIFY_DAMAGE, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_DIG, 0, 0, 2, 0, 8192, 0, 1, ${undergroundDoubleProgramOffset}, 2, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_OWNER, 0, "onSourceModifyDamage"},`);
	lines.push(`    {POKEMON_HANDLER_EVENT_INVULNERABILITY, POKEMON_GEN3_HANDLER_DIVE_INVULNERABILITY, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_DIVE, 0, 0, 2, 0, 0, 0, 0, ${underwaterInvulnerabilityProgramOffset}, 2, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onInvulnerability"},`);
	lines.push(`    {POKEMON_HANDLER_EVENT_MODIFY_DAMAGE, POKEMON_GEN3_HANDLER_DIVE_SOURCE_MODIFY_DAMAGE, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_DIVE, 0, 0, 2, 0, 8192, 0, 1, ${underwaterDoubleProgramOffset}, 2, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_OWNER, 0, "onSourceModifyDamage"},`);
	lines.push(`    {POKEMON_HANDLER_EVENT_IMMUNITY, POKEMON_GEN3_HANDLER_DIG_IMMUNITY, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_DIG, 0, 0, 2, 0, 0, 0, 0, ${hiddenWeatherImmunityProgramOffset}, 2, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onImmunity"},`);
	lines.push(`    {POKEMON_HANDLER_EVENT_IMMUNITY, POKEMON_GEN3_HANDLER_DIVE_IMMUNITY, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_DIVE, 0, 0, 2, 0, 0, 0, 0, ${hiddenWeatherImmunityProgramOffset}, 2, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onImmunity"},`);
	lines.push(`    {POKEMON_HANDLER_EVENT_MODIFY_DAMAGE, POKEMON_GEN3_HANDLER_FLY_SOURCE_MODIFY_DAMAGE, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_FLY, 0, 0, 2, 0, 8192, 0, 1, ${airborneDoubleProgramOffset}, 2, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_OWNER, 0, "onSourceModifyDamage"},`);
  for (const [id, type, handler, program] of [
    ['mudsport', 'Electric', 'MUD_SPORT', sportProgramOffset],
    ['watersport', 'Fire', 'WATER_SPORT', sportProgramOffset + 2],
  ]) {
    const condition = dex.moves.get(id).condition;
    const source = String(condition?.onAnyBasePower);
    if (typeof condition?.onStart !== 'function' ||
        typeof condition?.onAnyBasePower !== 'function' ||
        condition.onAnyBasePowerPriority !== 3 ||
        (!source.includes(`move.type === '${type}'`) &&
         !source.includes(`move.type === "${type}"`)) ||
        !source.includes('this.chainModify(0.5)')) {
      throw new Error(`resolved Gen 3 ${id} condition shape changed`);
    }
    lines.push(`    {POKEMON_HANDLER_EVENT_BASE_POWER, POKEMON_GEN3_HANDLER_${handler}_ANY_BASE_POWER, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_${cName(id)}, 0, 3, 2, POKEMON_GEN3_TYPE_${cName(type)}, 2048, 0, 1, ${program}, 2, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_ANY, POKEMON_HANDLER_ROUTE_OWNER, 0, "onAnyBasePower"},`);
  }
  {
    const protect = dex.moves.get('protect');
    const detect = dex.moves.get('detect');
    const endure = dex.moves.get('endure');
    for (const move of [protect, detect, endure]) {
      const prepare = String(move.onPrepareHit);
      const hit = String(move.onHit);
      if (!move.stallingMove || typeof move.onPrepareHit !== 'function' ||
          !prepare.includes('queue.willAct()') || !/runEvent\(["']StallMove["']/.test(prepare) ||
          typeof move.onHit !== 'function' || !/addVolatile\(["']stall["']\)/.test(hit)) {
        throw new Error(`resolved Gen 3 ${move.id} stalling callbacks changed`);
      }
    }
    const endureDamage = String(endure.condition?.onDamage);
    if (protect.priority !== 3 || detect.priority !== 3 || endure.priority !== 4 ||
        protect.volatileStatus !== 'protect' || detect.volatileStatus !== 'protect' ||
        endure.volatileStatus !== 'endure' || endure.condition?.duration !== 1 ||
        endure.condition?.onDamagePriority !== -10 ||
        typeof endure.condition?.onDamage !== 'function' ||
        !/effect\?\.effectType === ["']Move["']/.test(endureDamage) ||
        !endureDamage.includes('damage >= target.hp') ||
        !endureDamage.includes('target.hp - 1')) {
      throw new Error('resolved Gen 3 Protect/Detect/Endure shape changed');
    }
  }
  lines.push(`    {POKEMON_HANDLER_EVENT_DAMAGE, POKEMON_GEN3_HANDLER_ENDURE_DAMAGE, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_ENDURE, 0, -10, 2, 0, 0, 0, 0, ${endureDamageProgramOffset}, 2, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "condition.onDamage"},`);
  {
    const lockOn = dex.moves.get('lockon');
    const mindReader = dex.moves.get('mindreader');
    const condition = lockOn.condition;
    const tryHitSources = [lockOn, mindReader].map(move =>
      String(move.onTryHit));
    const hitSources = [lockOn, mindReader].map(move => String(move.onHit));
    const invulnerability = String(condition?.onSourceInvulnerability);
    const accuracy = String(condition?.onSourceAccuracy);
    if (lockOn.accuracy !== 100 || mindReader.accuracy !== 100 ||
        lockOn.category !== 'Status' || mindReader.category !== 'Status' ||
        lockOn.target !== 'normal' || mindReader.target !== 'normal' ||
        tryHitSources.some(source =>
          !/source\.volatiles\[["']lockon["']\]/.test(source) ||
          !source.includes('return false')) ||
        hitSources.some(source => !/addVolatile\(["']lockon["'], target\)/.test(source)) ||
        condition?.duration !== 2 ||
        condition?.onSourceInvulnerabilityPriority !== 1 ||
        typeof condition?.onSourceInvulnerability !== 'function' ||
        typeof condition?.onSourceAccuracy !== 'function' ||
        !invulnerability.includes('source === this.effectState.target') ||
        !invulnerability.includes('target === this.effectState.source') ||
        !invulnerability.includes('return 0') ||
        !accuracy.includes('source === this.effectState.target') ||
        !accuracy.includes('target === this.effectState.source') ||
        !accuracy.includes('return true')) {
      throw new Error('resolved Gen 3 Lock-On family shape changed');
    }
  }
  lines.push(`    {POKEMON_HANDLER_EVENT_TRY_HIT, POKEMON_GEN3_HANDLER_LOCK_ON_TRY_HIT, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_LOCKON, 0, 0, 0, 0, 0, 0, 0, ${lockOnTryHitProgramOffset}, 2, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onTryHit"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_TRY_HIT, POKEMON_GEN3_HANDLER_MIND_READER_TRY_HIT, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_MINDREADER, 0, 0, 0, 0, 0, 0, 0, ${lockOnTryHitProgramOffset}, 2, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onTryHit"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_ACCURACY, POKEMON_GEN3_HANDLER_LOCK_ON_ACCURACY, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_LOCKON, 0, 0, 2, 0, 0, 0, 0, ${lockOnAccuracyProgramOffset}, 2, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_OWNER, 0, "onSourceAccuracy"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_INVULNERABILITY, POKEMON_GEN3_HANDLER_LOCK_ON_INVULNERABILITY, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_LOCKON, 0, 1, 2, 0, 0, 0, 0, ${lockOnInvulnerabilityProgramOffset}, 2, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_OWNER, 0, "onSourceInvulnerability"},`);
	{
		const wonderGuard = dex.abilities.get('wonderguard');
		const source = String(wonderGuard.onTryHit);
		if (typeof wonderGuard.onTryHit !== 'function' ||
			!/move\.category === ["']Status["']/.test(source) ||
			!/move\.type === ["']\?\?\?["']/.test(source) ||
			!source.includes('target.runEffectiveness(move) <= 0') ||
			!source.includes('return null') || !wonderGuard.flags?.failroleplay) {
			throw new Error('resolved Gen 3 Wonder Guard shape changed');
		}
	}
	lines.push(`    {POKEMON_HANDLER_EVENT_TRY_HIT, POKEMON_GEN3_HANDLER_WONDER_GUARD_TRY_HIT, POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_WONDERGUARD, 0, 0, 7, 0, 0, 0, 0, ${wonderGuardProgramOffset}, 4, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onTryHit"},`);
	{
		const focusBand = dex.items.get('focusband');
		const source = String(focusBand.onDamage);
		if (typeof focusBand.onDamage !== 'function' ||
			focusBand.onDamagePriority !== -40 ||
			!source.includes('randomChance(1, 10)') ||
			!source.includes('damage >= target.hp') ||
			!/effect\.effectType === ["']Move["']/.test(source) ||
			!source.includes('target.hp - 1')) {
			throw new Error('resolved Gen 3 Focus Band shape changed');
		}
	}
	lines.push(`    {POKEMON_HANDLER_EVENT_DAMAGE, POKEMON_GEN3_HANDLER_FOCUS_BAND_DAMAGE, POKEMON_HANDLER_SOURCE_ITEM, POKEMON_GEN3_ITEM_FOCUSBAND, 0, -40, 8, 0, 0, 0, 0, ${focusBandDamageProgramOffset}, 3, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onDamage"},`);
	{
		const burn = dex.conditions.get('brn');
		const poison = dex.conditions.get('psn');
		const toxic = dex.conditions.get('tox');
		if (typeof burn.onStart !== 'function' ||
			!String(burn.onStart).includes('this.add("-status", target, "brn"') ||
			typeof poison.onStart !== 'function' ||
			!String(poison.onStart).includes('this.add("-status", target, "psn"') ||
			typeof toxic.onStart !== 'function' ||
			!String(toxic.onStart).includes('this.effectState.stage = 0') ||
			typeof toxic.onSwitchIn !== 'function' ||
			!String(toxic.onSwitchIn).includes('this.effectState.stage = 0')) {
			throw new Error('resolved Gen 3 major-status lifecycle shape changed');
		}
	}
	lines.push('    {POKEMON_HANDLER_EVENT_START, POKEMON_GEN3_HANDLER_BURN_START, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_STATUS_BRN, 0, 0, 0, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onStart"},');
	lines.push('    {POKEMON_HANDLER_EVENT_START, POKEMON_GEN3_HANDLER_POISON_START, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_STATUS_PSN, 0, 0, 0, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onStart"},');
	lines.push(`    {POKEMON_HANDLER_EVENT_START, POKEMON_GEN3_HANDLER_TOXIC_START, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_STATUS_TOX, 0, 0, 0, 0, 0, 0, 0, ${toxicStageResetProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onStart"},`);
	lines.push(`    {POKEMON_HANDLER_EVENT_SWITCH_IN, POKEMON_GEN3_HANDLER_TOXIC_SWITCH_IN, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_STATUS_TOX, 0, 0, 0, 0, 0, 0, 0, ${toxicStageResetProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onSwitchIn"},`);
	{
		const leppa = dex.items.get('leppaberry');
		const update = String(leppa.onUpdate);
		const eat = String(leppa.onEat);
		if (typeof leppa.onUpdate !== 'function' ||
			typeof leppa.onEat !== 'function' ||
			!update.includes('move.pp === 0') ||
			!update.includes('pokemon.eatItem()') ||
			!eat.includes('move.pp === 0') ||
			!eat.includes('move.pp < move.maxpp') ||
			!eat.includes('Math.min(moveSlot.pp + addedPP, moveSlot.maxpp)')) {
			throw new Error('resolved Gen 3 Leppa Berry shape changed');
		}
	}
	lines.push(`    {POKEMON_HANDLER_EVENT_UPDATE, POKEMON_GEN3_HANDLER_LEPPA_BERRY_UPDATE, POKEMON_HANDLER_SOURCE_ITEM, POKEMON_GEN3_ITEM_LEPPABERRY, 0, 0, 8, 0, 0, 0, 0, ${leppaBerryProgramOffset}, 2, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onUpdate"},`);
	lines.push(`    {POKEMON_HANDLER_EVENT_ITEM_EAT, POKEMON_GEN3_HANDLER_LEPPA_BERRY_EAT, POKEMON_HANDLER_SOURCE_ITEM, POKEMON_GEN3_ITEM_LEPPABERRY, 0, 0, 0, 0, 0, 0, 0, ${leppaBerryProgramOffset + 2}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onEat"},`);
	{
		const kingsRock = dex.items.get('kingsrock');
		if (typeof kingsRock.onModifyMove !== 'function' ||
			kingsRock.onModifyMovePriority !== -1 ||
			!/["']flinch["']/.test(kingsRockSource) ||
			!kingsRockSource.includes('chance: 10')) {
			throw new Error('resolved Gen 3 King\'s Rock callback changed');
		}
	}
	lines.push(`    {POKEMON_HANDLER_EVENT_MODIFY_MOVE, POKEMON_GEN3_HANDLER_KINGS_ROCK_MODIFY_MOVE, POKEMON_HANDLER_SOURCE_ITEM, POKEMON_GEN3_ITEM_KINGSROCK, 0, -1, 8, 0, 0, 0, 0, ${kingsRockProgramOffset}, 2, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onModifyMove"},`);
	{
		const shellBell = dex.items.get('shellbell');
		const callback = String(shellBell.onAfterMoveSecondarySelf);
		if (typeof shellBell.onAfterMoveSecondarySelf !== 'function' ||
			shellBell.onAfterMoveSecondarySelfPriority !== -1 ||
			!callback.includes('move.totalDamage') ||
			!callback.includes('!pokemon.forceSwitchFlag') ||
			!callback.includes('/ 8')) {
			throw new Error('resolved Gen 3 Shell Bell callback changed');
		}
	}
	lines.push(`    {POKEMON_HANDLER_EVENT_AFTER_MOVE_SECONDARY_SELF, POKEMON_GEN3_HANDLER_SHELL_BELL_AFTER_MOVE_SECONDARY_SELF, POKEMON_HANDLER_SOURCE_ITEM, POKEMON_GEN3_ITEM_SHELLBELL, 0, -1, 8, 0, 0, 0, 0, ${shellBellProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onAfterMoveSecondarySelf"},`);
	lines.push(`    {POKEMON_HANDLER_EVENT_TRY, POKEMON_GEN3_HANDLER_FAKE_OUT_TRY, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_FAKEOUT, 0, 0, 0, 0, 0, 0, 0, ${fakeOutProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onTry"},`);
	{
		const move = dex.moves.get('followme');
		const source = String(move.onTry);
		if (move.target !== 'self' || move.accuracy !== true || move.priority !== 3 ||
			move.volatileStatus || move.slotCondition !== 'followme' ||
			typeof move.onTry !== 'function' ||
			!source.includes('this.activePerHalf > 1')) {
			throw new Error('resolved Gen 3 Follow Me shape changed');
		}
	}
	lines.push(`    {POKEMON_HANDLER_EVENT_TRY, POKEMON_GEN3_HANDLER_FOLLOW_ME_TRY, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_FOLLOWME, 0, 0, 0, 0, 0, 0, 0, ${followMeProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onTry"},`);
	lines.push(`    {POKEMON_HANDLER_EVENT_START, POKEMON_GEN3_HANDLER_COUNTER_START, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_COUNTER, 0, 0, 0, 0, 0, 0, 0, ${counterStartProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onStart"},`);
	lines.push(`    {POKEMON_HANDLER_EVENT_DAMAGE, POKEMON_GEN3_HANDLER_COUNTER_DAMAGE, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_COUNTER, 0, -101, 2, 0, 0, 0, 0, ${counterDamageProgramOffset}, 2, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onDamage"},`);
	lines.push(`    {POKEMON_HANDLER_EVENT_TRY, POKEMON_GEN3_HANDLER_COUNTER_TRY, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_COUNTER, 0, 0, 0, 0, 0, 0, 0, ${counterTryProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onTry"},`);
	lines.push(`    {POKEMON_HANDLER_EVENT_START, POKEMON_GEN3_HANDLER_MIRROR_COAT_START, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_MIRRORCOAT, 0, 0, 0, 0, 0, 0, 0, ${mirrorCoatStartProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onStart"},`);
	lines.push(`    {POKEMON_HANDLER_EVENT_DAMAGE, POKEMON_GEN3_HANDLER_MIRROR_COAT_DAMAGE, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_MIRRORCOAT, 0, -101, 2, 0, 0, 0, 0, ${mirrorCoatDamageProgramOffset}, 2, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onDamage"},`);
	lines.push(`    {POKEMON_HANDLER_EVENT_TRY, POKEMON_GEN3_HANDLER_MIRROR_COAT_TRY, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_MIRRORCOAT, 0, 0, 0, 0, 0, 0, 0, ${mirrorCoatTryProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onTry"},`);
	lines.push(`    {POKEMON_HANDLER_EVENT_MODIFY_MOVE, POKEMON_GEN3_HANDLER_HIDDEN_POWER_MODIFY_MOVE, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_HIDDENPOWER, 0, 0, 0, 0, 0, 0, 0, ${hiddenPowerModifyMoveProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onModifyMove"},`);
  {
    const ability = dex.abilities.get('suctioncups');
    const source = String(ability.onDragOut);
    if (typeof ability.onDragOut !== 'function' ||
        ability.onDragOutPriority !== 1 || !source.includes('return null')) {
      throw new Error('resolved Gen 3 Suction Cups shape changed');
    }
  }
  lines.push(`    {POKEMON_HANDLER_EVENT_DRAG_OUT, POKEMON_GEN3_HANDLER_SUCTION_CUPS_DRAG_OUT, POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_SUCTIONCUPS, 0, 1, 7, 0, 0, 0, 0, ${suctionCupsDragOutProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onDragOut"},`);
  lines.push('    {POKEMON_HANDLER_EVENT_START, POKEMON_GEN3_HANDLER_INGRAIN_START, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_INGRAIN, 0, 0, 0, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onStart"},');
  lines.push(`    {POKEMON_HANDLER_EVENT_RESIDUAL, POKEMON_GEN3_HANDLER_INGRAIN_RESIDUAL, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_INGRAIN, 10, 0, 1, 0, 0, 0, 0, ${ingrainResidualProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onResidual"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_TRAP_POKEMON, POKEMON_GEN3_HANDLER_INGRAIN_TRAP_POKEMON, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_INGRAIN, 0, 0, 2, 0, 0, 0, 0, ${ingrainResidualProgramOffset + 1}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onTrapPokemon"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_DRAG_OUT, POKEMON_GEN3_HANDLER_INGRAIN_DRAG_OUT, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_INGRAIN, 0, 0, 2, 0, 0, 0, 0, ${ingrainResidualProgramOffset + 2}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onDragOut"},`);
  lines.push('    {POKEMON_HANDLER_EVENT_MODIFY_MOVE, POKEMON_GEN3_HANDLER_PURSUIT_MODIFY_MOVE, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_PURSUIT, 0, 0, 0, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onModifyMove"},');
  lines.push(`    {POKEMON_HANDLER_EVENT_BEFORE_SWITCH_OUT, POKEMON_GEN3_HANDLER_PURSUIT_BEFORE_SWITCH_OUT, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_PURSUIT, 0, 0, 2, 0, 0, 0, 0, ${pursuitBeforeSwitchOutProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onBeforeSwitchOut"},`);
  {
    const move = dex.moves.get('charge');
    const condition = move.condition;
    const afterMoveSource = String(condition?.onAfterMove);
    const basePowerSource = String(condition?.onBasePower);
    if (move.boosts !== undefined || move.volatileStatus !== 'charge' ||
        typeof condition?.onStart !== 'function' ||
        typeof condition?.onRestart !== 'function' ||
        typeof condition?.onBasePower !== 'function' ||
        condition.onBasePowerPriority !== 9 ||
        typeof condition?.onMoveAborted !== 'function' ||
        typeof condition?.onAfterMove !== 'function' ||
        !/move\.id !== ["']charge["']/.test(afterMoveSource) ||
        /move\.type === ["']Electric["']/.test(afterMoveSource) ||
        !/move\.type === ["']Electric["']/.test(basePowerSource) ||
        typeof condition?.onEnd !== 'function') {
      throw new Error('resolved Gen 3 Charge lifecycle changed');
    }
  }
  lines.push('    {POKEMON_HANDLER_EVENT_START, POKEMON_GEN3_HANDLER_CHARGE_START, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_CHARGE, 0, 0, 0, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onStart"},');
  lines.push('    {POKEMON_HANDLER_EVENT_RESTART, POKEMON_GEN3_HANDLER_CHARGE_RESTART, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_CHARGE, 0, 0, 0, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onRestart"},');
  lines.push(`    {POKEMON_HANDLER_EVENT_BASE_POWER, POKEMON_GEN3_HANDLER_CHARGE_BASE_POWER, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_CHARGE, 0, 9, 2, 0, 0, 0, 0, ${chargeBasePowerProgramOffset}, 2, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_OWNER, 0, "onBasePower"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_MOVE_ABORTED, POKEMON_GEN3_HANDLER_CHARGE_MOVE_ABORTED, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_CHARGE, 0, 0, 2, 0, 0, 0, 0, ${chargeCleanupProgramOffset}, 2, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_OWNER, 0, "onMoveAborted"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_AFTER_MOVE, POKEMON_GEN3_HANDLER_CHARGE_AFTER_MOVE, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_CHARGE, 0, 0, 2, 0, 0, 0, 0, ${chargeCleanupProgramOffset}, 2, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_OWNER, 0, "onAfterMove"},`);
  lines.push('    {POKEMON_HANDLER_EVENT_END, POKEMON_GEN3_HANDLER_CHARGE_END, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_CHARGE, 0, 0, 0, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onEnd"},');
  {
    const leechSeed = dex.moves.get('leechseed');
    const condition = leechSeed.condition;
    const immunitySource = String(leechSeed.onTryImmunity);
    const residualSource = String(condition?.onResidual);
    const liquidOoze = dex.abilities.get('liquidooze');
    const oozeSource = String(liquidOoze.onSourceTryHeal);
    const rapidSpin = dex.moves.get('rapidspin');
    const afterHitSource = String(rapidSpin.onAfterHit);
    const afterSubDamageSource = String(rapidSpin.onAfterSubDamage);
    if (leechSeed.volatileStatus !== 'leechseed' ||
        typeof leechSeed.onTryImmunity !== 'function' ||
        !/hasType\(["']Grass["']\)/.test(immunitySource) ||
        typeof condition?.onStart !== 'function' ||
        condition.onResidualOrder !== 10 ||
        condition.onResidualSubOrder !== 5 ||
        !/volatiles\[["']leechseed["']\]\.sourceSlot/.test(residualSource) ||
        !residualSource.includes('pokemon.baseMaxhp / 8') ||
        !residualSource.includes('this.heal(damage, target, pokemon)') ||
        typeof liquidOoze.onSourceTryHeal !== 'function' ||
        !/\[["']drain["'],\s*["']leechseed["']\]/.test(oozeSource) ||
        !oozeSource.includes('activeMove?.id !== "dreameater"') ||
        !oozeSource.includes('this.damage(damage') ||
        !oozeSource.includes('return 0') ||
        typeof rapidSpin.onAfterHit !== 'function' ||
        typeof rapidSpin.onAfterSubDamage !== 'function' ||
        !/removeVolatile\(["']leechseed["']\)/.test(afterHitSource) ||
        !afterHitSource.includes('removeSideCondition(condition)') ||
        !/removeVolatile\(["']partiallytrapped["']\)/.test(afterHitSource) ||
        !/pokemon\.hp && pokemon\.removeVolatile\(["']leechseed["']\)/.test(afterSubDamageSource) ||
        !afterSubDamageSource.includes('pokemon.hp && pokemon.side.removeSideCondition(condition)')) {
      throw new Error('resolved Gen 3 source-linked residual family changed');
    }
  }
  lines.push(`    {POKEMON_HANDLER_EVENT_TRY_IMMUNITY, POKEMON_GEN3_HANDLER_LEECH_SEED_TRY_IMMUNITY, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_LEECHSEED, 0, 0, 0, 0, 0, 0, 0, ${leechSeedTryImmunityProgramOffset}, 2, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onTryImmunity"},`);
  lines.push('    {POKEMON_HANDLER_EVENT_START, POKEMON_GEN3_HANDLER_LEECH_SEED_START, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_LEECHSEED, 0, 0, 0, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onStart"},');
  lines.push(`    {POKEMON_HANDLER_EVENT_RESIDUAL, POKEMON_GEN3_HANDLER_LEECH_SEED_RESIDUAL, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_LEECHSEED, 10, 0, 5, 0, 0, 0, 0, ${leechSeedResidualProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onResidual"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_TRY_HEAL, POKEMON_GEN3_HANDLER_LIQUID_OOZE_SOURCE_TRY_HEAL, POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_LIQUIDOOZE, 0, 0, 7, 0, 0, 0, 0, ${liquidOozeTryHealProgramOffset}, 3, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_OWNER, 0, "onSourceTryHeal"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_AFTER_SUB_DAMAGE, POKEMON_GEN3_HANDLER_RAPID_SPIN_AFTER_SUB_DAMAGE, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_RAPIDSPIN, 0, 0, 0, 0, 0, 0, 0, ${rapidSpinAfterSubDamageProgramOffset}, 4, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onAfterSubDamage"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_TRY_HIT, POKEMON_GEN3_HANDLER_FLASH_FIRE_TRY_HIT, POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_FLASHFIRE, 0, 0, 7, 0, 0, 0, 0, ${flashFireTryHitProgramOffset}, 6, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onTryHit"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_END, POKEMON_GEN3_HANDLER_FLASH_FIRE_ABILITY_END, POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_FLASHFIRE, 0, 0, 0, 0, 0, 0, 0, ${flashFireAbilityEndProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onEnd"},`);
  lines.push('    {POKEMON_HANDLER_EVENT_START, POKEMON_GEN3_HANDLER_FLASH_FIRE_CONDITION_START, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_FLASHFIRE, 0, 0, 0, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onStart"},');
  lines.push(`    {POKEMON_HANDLER_EVENT_MODIFY_DAMAGE_PHASE1, POKEMON_GEN3_HANDLER_FLASH_FIRE_MODIFY_DAMAGE_PHASE1, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_FLASHFIRE, 0, 0, 2, 0, 0, 0, 0, ${flashFireModifyDamageProgramOffset}, 3, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_OWNER, 0, "onModifyDamagePhase1"},`);
  lines.push('    {POKEMON_HANDLER_EVENT_END, POKEMON_GEN3_HANDLER_FLASH_FIRE_CONDITION_END, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_FLASHFIRE, 0, 0, 0, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onEnd"},');
  lines.push(`    {POKEMON_HANDLER_EVENT_TRY, POKEMON_GEN3_HANDLER_TELEPORT_TRY, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_TELEPORT, 0, 0, 0, 0, 0, 0, 0, ${teleportTryProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onTry"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_MODIFY_SPA, POKEMON_GEN3_HANDLER_MINUS_MODIFY_SPA, POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_MINUS, 0, 0, 7, 0, 6144, 0, 0, ${minusModifySpAProgramOffset}, 2, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onModifySpA"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_MODIFY_SPA, POKEMON_GEN3_HANDLER_PLUS_MODIFY_SPA, POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_PLUS, 0, 0, 7, 0, 6144, 0, 0, ${minusModifySpAProgramOffset + 2}, 2, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onModifySpA"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_TRY_HIT, POKEMON_GEN3_HANDLER_STURDY_TRY_HIT, POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_STURDY, 0, 0, 7, 0, 0, 0, 0, ${sturdyTryHitProgramOffset}, 2, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onTryHit"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK, POKEMON_GEN3_HANDLER_METRONOME_HIT, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_METRONOME, 0, 0, 0, 0, 0, 0, 0, ${metronomeHitProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onHit"},`);
  {
    const move = dex.moves.get('naturepower');
    const hitSource = String(move.onHit);
    if (move.accuracy !== 95 || move.target !== 'self' ||
        typeof move.onHit !== 'function' ||
        !/useMove\(["']swift["'], target\)/.test(hitSource)) {
      throw new Error('resolved Gen 3 Nature Power fixed-call semantics changed');
    }
  }
  lines.push(`    {POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK, POKEMON_GEN3_HANDLER_NATURE_POWER_HIT, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_NATUREPOWER, 0, 0, 0, 0, 0, 0, 0, ${naturePowerHitProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onHit"},`);
  {
    const move = dex.moves.get('sleeptalk');
    const trySource = String(move.onTry);
    const tryHitSource = String(move.onTryHit);
    const hitSource = String(move.onHit);
    if (move.accuracy !== true || move.target !== 'self' ||
        move.sleepUsable !== true || typeof move.onTry !== 'function' ||
        typeof move.onTryHit !== 'function' ||
        typeof move.onHit !== 'function' ||
        !/source\.status === ["']slp["']/.test(trySource) ||
        !/volatiles\[["']choicelock["']\]/.test(tryHitSource) ||
        !/volatiles\[["']encore["']\]/.test(tryHitSource) ||
        !/move\.flags\[["']nosleeptalk["']\]/.test(hitSource) ||
        !/move\.flags\[["']charge["']\]/.test(hitSource) ||
        !hitSource.includes('this.sample(moves)') ||
        !hitSource.includes('this.actions.useMove(randomMove.move, pokemon)')) {
      throw new Error('resolved Gen 3 Sleep Talk current-slot semantics changed');
    }
  }
  lines.push(`    {POKEMON_HANDLER_EVENT_TRY, POKEMON_GEN3_HANDLER_SLEEP_TALK_TRY, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_SLEEPTALK, 0, 0, 0, 0, 0, 0, 0, ${sleepTalkTryProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onTry"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_TRY_HIT, POKEMON_GEN3_HANDLER_SLEEP_TALK_TRY_HIT, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_SLEEPTALK, 0, 0, 0, 0, 0, 0, 0, ${sleepTalkTryHitProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onTryHit"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK, POKEMON_GEN3_HANDLER_SLEEP_TALK_HIT, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_SLEEPTALK, 0, 0, 0, 0, 0, 0, 0, ${sleepTalkHitProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onHit"},`);
  for (const [id, token, programOffset, forbiddenFlag] of [
    ['mimic', 'MIMIC', mimicHitProgramOffset, 'failmimic'],
    ['sketch', 'SKETCH', sketchHitProgramOffset, 'nosketch'],
  ]) {
    const move = dex.moves.get(id);
    const hitSource = String(move.onHit);
    if (typeof move.onHit !== 'function' ||
        !/target\.volatiles\[["']substitute["']\]/.test(hitSource) ||
        !new RegExp(`target\\.lastMove\\.flags\\[["']${forbiddenFlag}["']\\]`).test(hitSource) ||
        !hitSource.includes('source.moves.includes(target.lastMove.id)') ||
        !new RegExp(`source\\.moves\\.indexOf\\(["']${id}["']\\)`).test(hitSource)) {
      throw new Error(`resolved Gen 3 ${id} copy semantics changed`);
    }
    lines.push(`    {POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK, POKEMON_GEN3_HANDLER_${token}_HIT, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_${token}, 0, 0, 0, 0, 0, 0, 0, ${programOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onHit"},`);
  }
  {
    const move = dex.moves.get('assist');
    const hitSource = String(move.onHit);
    const effectiveFlags = Object.keys(move.flags || {}).sort().join(',');
    if (move.accuracy !== true || move.target !== 'self' ||
        effectiveFlags !== 'metronome,noassist,nosleeptalk' ||
        typeof move.onHit !== 'function' ||
        !hitSource.includes('for (const pokemon of target.side.pokemon)') ||
        !hitSource.includes('if (pokemon === target) continue') ||
        !/move\.flags\[['"]noassist['"]\]/.test(hitSource) ||
        !/field\.pseudoWeather\[['"]gravity['"]\]/.test(hitSource) ||
        !/target\.volatiles\[['"]healblock['"]\]/.test(hitSource) ||
        !hitSource.includes('this.sample(moves)') ||
        !hitSource.includes('this.actions.useMove(randomMove, target)')) {
      throw new Error('resolved Gen 3 Assist party-slot semantics changed');
    }
  }
  lines.push(`    {POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK, POKEMON_GEN3_HANDLER_ASSIST_HIT, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_ASSIST, 0, 0, 0, 0, 0, 0, 0, ${assistHitProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onHit"},`);
  {
    const move = dex.moves.get('perishsong');
    const hitSource = String(move.onHitField);
    const endSource = String(move.condition?.onEnd);
    const residualSource = String(move.condition?.onResidual);
    if (move.accuracy !== true || move.target !== 'all' ||
        !move.flags?.sound || move.flags?.bypasssub ||
        typeof move.onHitField !== 'function' ||
        !hitSource.includes('this.getAllActive()') ||
        !/this\.runEvent\(["']Invulnerability["']/.test(hitSource) ||
        !/this\.runEvent\(["']TryHit["']/.test(hitSource) ||
        !/!pokemon\.volatiles\[["']perishsong["']\]/.test(hitSource) ||
        move.condition?.duration !== 4 ||
        move.condition?.onResidualOrder !== 12 ||
        typeof move.condition?.onEnd !== 'function' ||
        !endSource.includes('target.faint()') ||
        typeof move.condition?.onResidual !== 'function' ||
        !/volatiles\[["']perishsong["']\]\.duration/.test(residualSource)) {
      throw new Error('resolved Gen 3 Perish Song lifecycle changed');
    }
  }
  lines.push(`    {POKEMON_HANDLER_EVENT_MOVE_HIT_FIELD_CALLBACK, POKEMON_GEN3_HANDLER_PERISH_SONG_HIT_FIELD, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_PERISHSONG, 0, 0, 0, 0, 0, 0, 0, ${perishSongHitFieldProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_FIELD, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onHitField"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_RESIDUAL, POKEMON_GEN3_HANDLER_PERISH_SONG_RESIDUAL, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_PERISHSONG, 12, 0, 2, 0, 0, 0, 0, ${perishSongResidualProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onResidual"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_END, POKEMON_GEN3_HANDLER_PERISH_SONG_END, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_PERISHSONG, 0, 0, 0, 0, 0, 0, 0, ${perishSongResidualProgramOffset + 1}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onEnd"},`);
  {
    const condition = dex.conditions.get('foresight');
    const start = String(condition.onStart);
    const negate = String(condition.onNegateImmunity);
    const modify = String(condition.onModifyBoost);
    if (!condition.noCopy || typeof condition.onStart !== 'function' ||
        !/["']Foresight["']/.test(start) ||
        typeof condition.onNegateImmunity !== 'function' ||
        !/pokemon\.hasType\(["']Ghost["']\)/.test(negate) ||
        !/\[["']Normal["'], ["']Fighting["']\]\.includes\(type\)/.test(negate) ||
        typeof condition.onModifyBoost !== 'function' ||
        !modify.includes('boosts.evasion > 0') ||
        !modify.includes('boosts.evasion = 0')) {
      throw new Error('resolved Gen 3 Foresight condition changed');
    }
  }
  lines.push(`    {POKEMON_HANDLER_EVENT_TRY_HIT, POKEMON_GEN3_HANDLER_FORESIGHT_TRY_HIT, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_FORESIGHT, 0, 0, 0, 0, 0, 0, 0, ${foresightTryHitProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onTryHit"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_TRY_HIT, POKEMON_GEN3_HANDLER_ODOR_SLEUTH_TRY_HIT, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_ODORSLEUTH, 0, 0, 0, 0, 0, 0, 0, ${foresightTryHitProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onTryHit"},`);
  lines.push('    {POKEMON_HANDLER_EVENT_START, POKEMON_GEN3_HANDLER_FORESIGHT_START, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_FORESIGHT, 0, 0, 0, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onStart"},');
  lines.push(`    {POKEMON_HANDLER_EVENT_NEGATE_IMMUNITY, POKEMON_GEN3_HANDLER_FORESIGHT_NEGATE_IMMUNITY, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_FORESIGHT, 0, 0, 2, 0, 0, 0, 0, ${foresightNegateImmunityProgramOffset}, 3, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onNegateImmunity"},`);
  lines.push(`    {POKEMON_HANDLER_EVENT_MODIFY_BOOST, POKEMON_GEN3_HANDLER_FORESIGHT_MODIFY_BOOST, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_FORESIGHT, 0, 0, 2, 0, 0, 0, 0, ${foresightModifyBoostProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onModifyBoost"},`);
	{
		const move = dex.moves.get('bide');
		const condition = move.condition;
		if (move.volatileStatus !== 'bide' || move.target !== 'self' ||
			move.category !== 'Physical' || move.basePower !== 0 ||
			move.accuracy !== 100 || move.priority !== 0 ||
			typeof move.beforeMoveCallback !== 'function' ||
			condition?.duration !== 3 || typeof condition.onStart !== 'function' ||
			typeof condition.onDamage !== 'function' || condition.onDamagePriority !== -101 ||
			typeof condition.onBeforeMove !== 'function' ||
			typeof condition.onMoveAborted !== 'function' ||
			typeof condition.onEnd !== 'function' ||
			condition.onLockMove !== 'bide' ||
			condition.onAfterSetStatus !== undefined) {
			throw new Error('resolved Gen 3 Bide lifecycle shape changed');
		}
	}
	lines.push(`    {POKEMON_HANDLER_EVENT_START, POKEMON_GEN3_HANDLER_BIDE_START, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_BIDE, 0, 0, 0, 0, 0, 0, 0, ${bideStartProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onStart"},`);
	lines.push(`    {POKEMON_HANDLER_EVENT_DAMAGE, POKEMON_GEN3_HANDLER_BIDE_DAMAGE, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_BIDE, 0, -101, 2, 0, 0, 0, 0, ${bideDamageProgramOffset}, 2, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onDamage"},`);
	lines.push(`    {POKEMON_HANDLER_EVENT_BEFORE_MOVE, POKEMON_GEN3_HANDLER_BIDE_BEFORE_MOVE, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_BIDE, 0, 0, 2, 0, 0, 0, 0, ${bideReleaseProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onBeforeMove"},`);
	lines.push(`    {POKEMON_HANDLER_EVENT_MOVE_ABORTED, POKEMON_GEN3_HANDLER_BIDE_MOVE_ABORTED, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_BIDE, 0, 0, 2, 0, 0, 0, 0, ${bideCleanupProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onMoveAborted"},`);
	lines.push('    {POKEMON_HANDLER_EVENT_END, POKEMON_GEN3_HANDLER_BIDE_END, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_BIDE, 0, 0, 0, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onEnd"},');
	lines.push('    {POKEMON_HANDLER_EVENT_RESIDUAL, POKEMON_GEN3_HANDLER_BIDE_RESIDUAL, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_BIDE, 0, 0, 2, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "duration"},');
	{
		const move = dex.moves.get('furycutter');
		const basePower = String(move.basePowerCallback);
		const hit = String(move.onHit);
		const start = String(move.condition?.onStart);
		const restart = String(move.condition?.onRestart);
		if (move.basePower !== 10 || move.accuracy !== 95 ||
			move.category !== 'Physical' || move.target !== 'normal' ||
			typeof move.basePowerCallback !== 'function' ||
			!/addVolatile\(["']furycutter["']\)/.test(basePower) ||
			!/volatiles\[["']furycutter["']\]\.multiplier/.test(basePower) ||
			typeof move.onHit !== 'function' ||
			!/addVolatile\(["']furycutter["']\)/.test(hit) ||
			move.condition?.duration !== 2 ||
			typeof move.condition?.onStart !== 'function' ||
			!start.includes('multiplier = 1') ||
			typeof move.condition?.onRestart !== 'function' ||
			!restart.includes('multiplier < 16') ||
			!restart.includes('multiplier <<= 1') ||
			!restart.includes('duration = 2')) {
			throw new Error('resolved Gen 3 Fury Cutter ramp changed');
		}
	}
	lines.push(`    {POKEMON_HANDLER_EVENT_BASE_POWER, POKEMON_GEN3_HANDLER_FURY_CUTTER_BASE_POWER, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_FURYCUTTER, 0, 0, 0, 0, 0, 0, 0, ${furyCutterBasePowerProgramOffset}, 2, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "basePowerCallback"},`);
	lines.push(`    {POKEMON_HANDLER_EVENT_START, POKEMON_GEN3_HANDLER_FURY_CUTTER_START, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_FURYCUTTER, 0, 0, 0, 0, 0, 0, 0, ${furyCutterStartProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onStart"},`);
	lines.push(`    {POKEMON_HANDLER_EVENT_RESTART, POKEMON_GEN3_HANDLER_FURY_CUTTER_RESTART, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_FURYCUTTER, 0, 0, 0, 0, 0, 0, 0, ${furyCutterRestartProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onRestart"},`);
	lines.push(`    {POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK, POKEMON_GEN3_HANDLER_FURY_CUTTER_HIT, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_FURYCUTTER, 0, 0, 0, 0, 0, 0, 0, ${furyCutterHitProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onHit"},`);
	for (const id of ['rollout', 'iceball']) {
		const move = dex.moves.get(id);
		const basePower = String(move.basePowerCallback);
		const modify = String(move.onModifyMove);
		const residual = String(move.condition?.onResidual);
		if (move.basePower !== 30 || move.accuracy !== 90 ||
			move.category !== (id === 'rollout' ? 'Physical' : 'Special') ||
			move.target !== 'normal' ||
			typeof move.basePowerCallback !== 'function' ||
			!basePower.includes('hitCount++') ||
			!basePower.includes('contactHitCount++') ||
			!basePower.includes('hitCount < 5') ||
			!/volatiles\[["']defensecurl["']\]/.test(basePower) ||
			typeof move.onModifyMove !== 'function' ||
			!/pokemon\.status === ["']slp["']/.test(modify) ||
			!modify.includes('!target') ||
			move.condition?.duration !== 1 ||
			typeof move.condition?.onStart !== 'function' ||
			!String(move.condition.onStart).includes('hitCount = 0') ||
			!String(move.condition.onStart).includes('contactHitCount = 0') ||
			move.condition?.onLockMove !== id ||
			typeof move.condition?.onResidual !== 'function' ||
			!/lastMove\.id === ["']struggle["']/.test(residual)) {
			throw new Error(`resolved Gen 3 ${id} locked ramp changed`);
		}
		/* onAfterMove/rolloutstorage requires hitCount===5 with fewer than five
		 * contact hits. Gen 3 has no Disguise/Ice Face-style connected
		 * non-contact result, so the branch is unreachable in this plugin. */
		const after = String(move.onAfterMove);
		if (typeof move.onAfterMove !== 'function' ||
			!after.includes('hitCount === 5') ||
			!after.includes('contactHitCount < 5') ||
			!after.includes('rolloutstorage')) {
			throw new Error(`resolved ${id} rolloutstorage proof changed`);
		}
	}
	lines.push(`    {POKEMON_HANDLER_EVENT_MODIFY_MOVE, POKEMON_GEN3_HANDLER_ROLLOUT_MODIFY_MOVE, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_ROLLOUT, 0, 0, 0, 0, 0, 0, 0, ${rolloutModifyMoveProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onModifyMove"},`);
	lines.push(`    {POKEMON_HANDLER_EVENT_BASE_POWER, POKEMON_GEN3_HANDLER_ROLLOUT_BASE_POWER, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_ROLLOUT, 0, 0, 0, 0, 0, 0, 0, ${rolloutBasePowerProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "basePowerCallback"},`);
	lines.push(`    {POKEMON_HANDLER_EVENT_START, POKEMON_GEN3_HANDLER_ROLLOUT_START, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_ROLLOUT, 0, 0, 0, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onStart"},`);
	lines.push(`    {POKEMON_HANDLER_EVENT_LOCK_MOVE, POKEMON_GEN3_HANDLER_ROLLOUT_LOCK_MOVE, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_ROLLOUT, 0, 0, 2, 0, 0, 0, 0, ${rolloutLockMoveProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onLockMove"},`);
	lines.push(`    {POKEMON_HANDLER_EVENT_RESIDUAL, POKEMON_GEN3_HANDLER_ROLLOUT_RESIDUAL, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_ROLLOUT, 0, 0, 2, 0, 0, 0, 0, ${rolloutResidualProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onResidual"},`);
	lines.push(`    {POKEMON_HANDLER_EVENT_MODIFY_MOVE, POKEMON_GEN3_HANDLER_ICE_BALL_MODIFY_MOVE, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_ICEBALL, 0, 0, 0, 0, 0, 0, 0, ${iceBallModifyMoveProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onModifyMove"},`);
	lines.push(`    {POKEMON_HANDLER_EVENT_BASE_POWER, POKEMON_GEN3_HANDLER_ICE_BALL_BASE_POWER, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_ICEBALL, 0, 0, 0, 0, 0, 0, 0, ${iceBallBasePowerProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "basePowerCallback"},`);
	lines.push(`    {POKEMON_HANDLER_EVENT_START, POKEMON_GEN3_HANDLER_ICE_BALL_START, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_ICEBALL, 0, 0, 0, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onStart"},`);
	lines.push(`    {POKEMON_HANDLER_EVENT_LOCK_MOVE, POKEMON_GEN3_HANDLER_ICE_BALL_LOCK_MOVE, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_ICEBALL, 0, 0, 2, 0, 0, 0, 0, ${iceBallLockMoveProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onLockMove"},`);
	lines.push(`    {POKEMON_HANDLER_EVENT_RESIDUAL, POKEMON_GEN3_HANDLER_ICE_BALL_RESIDUAL, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_ICEBALL, 0, 0, 2, 0, 0, 0, 0, ${iceBallResidualProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onResidual"},`);
	{
		const stockpile = dex.moves.get('stockpile');
		const spitup = dex.moves.get('spitup');
		const swallow = dex.moves.get('swallow');
		if (stockpile.pp !== 10 || stockpile.volatileStatus !== 'stockpile' ||
			!stockpile.condition?.noCopy ||
			!String(stockpile.onTry).includes('volatiles["stockpile"]') ||
			!String(stockpile.onTry).includes('layers >= 3') ||
			!String(stockpile.condition.onStart).includes('layers = 1') ||
			!String(stockpile.condition.onRestart).includes('layers++') ||
			!String(stockpile.condition.onEnd).includes('layers = 0') ||
			String(stockpile.condition.onStart).includes('this.boost') ||
			spitup.basePower !== 0 || spitup.category !== 'Physical' ||
			!String(spitup.basePowerCallback).includes('layers * 100') ||
			!String(spitup.onAfterMove).includes('removeVolatile("stockpile")') ||
			!String(swallow.onTry).includes('volatiles["stockpile"]') ||
			!String(swallow.onHit).includes('[0.25, 0.5, 1]') ||
			!String(swallow.onHit).includes('removeVolatile("stockpile")')) {
			throw new Error('resolved Gen 3 Stockpile family changed');
		}
	}
	lines.push(
		`    {POKEMON_HANDLER_EVENT_TRY, POKEMON_GEN3_HANDLER_STOCKPILE_TRY, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_STOCKPILE, 0, 0, 0, 0, 0, 0, 0, ${stockpileTryProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onTry"},`,
		`    {POKEMON_HANDLER_EVENT_START, POKEMON_GEN3_HANDLER_STOCKPILE_START, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_STOCKPILE, 0, 0, 0, 0, 0, 0, 0, ${stockpileStartProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onStart"},`,
		`    {POKEMON_HANDLER_EVENT_RESTART, POKEMON_GEN3_HANDLER_STOCKPILE_RESTART, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_STOCKPILE, 0, 0, 0, 0, 0, 0, 0, ${stockpileRestartProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onRestart"},`,
		'    {POKEMON_HANDLER_EVENT_END, POKEMON_GEN3_HANDLER_STOCKPILE_END, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_STOCKPILE, 0, 0, 0, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onEnd"},',
		`    {POKEMON_HANDLER_EVENT_TRY, POKEMON_GEN3_HANDLER_SPIT_UP_TRY, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_SPITUP, 0, 0, 0, 0, 0, 0, 0, ${spitUpTryProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onTry"},`,
		`    {POKEMON_HANDLER_EVENT_BASE_POWER, POKEMON_GEN3_HANDLER_SPIT_UP_BASE_POWER, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_SPITUP, 0, 0, 0, 0, 0, 0, 0, ${spitUpBasePowerProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "basePowerCallback"},`,
		`    {POKEMON_HANDLER_EVENT_AFTER_MOVE, POKEMON_GEN3_HANDLER_SPIT_UP_AFTER_MOVE, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_SPITUP, 0, 0, 0, 0, 0, 0, 0, ${removeStockpileProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onAfterMove"},`,
		`    {POKEMON_HANDLER_EVENT_TRY, POKEMON_GEN3_HANDLER_SWALLOW_TRY, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_SWALLOW, 0, 0, 0, 0, 0, 0, 0, ${swallowTryProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onTry"},`,
		`    {POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK, POKEMON_GEN3_HANDLER_SWALLOW_HIT, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_SWALLOW, 0, 0, 0, 0, 0, 0, 0, ${swallowHitProgramOffset}, 3, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onHit"},`,
	);
  lines.push(`    {POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK, POKEMON_GEN3_HANDLER_CONVERSION_2_HIT, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_CONVERSION2, 0, 0, 0, 0, 0, 0, 0, ${conversion2ProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onHit"},`);
	{
		const move = dex.moves.get('rage');
		const condition = move.condition;
		if (move.basePower !== 20 || move.accuracy !== 100 ||
			move.category !== 'Physical' || move.target !== 'normal' ||
			move.self?.volatileStatus !== 'rage' ||
			typeof condition?.onStart !== 'function' ||
			typeof condition?.onHit !== 'function' ||
			condition.onBeforeMovePriority !== 100 ||
			typeof condition.onBeforeMove !== 'function' ||
			!/move\.category !== ["']Status["']/.test(String(condition.onHit)) ||
			!/removeVolatile\(["']rage["']\)/.test(String(condition.onBeforeMove))) {
			throw new Error('resolved Gen 3 Rage lifecycle changed');
		}
	}
	lines.push('    {POKEMON_HANDLER_EVENT_START, POKEMON_GEN3_HANDLER_RAGE_START, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_RAGE, 0, 0, 0, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onStart"},');
	lines.push(`    {POKEMON_HANDLER_EVENT_HIT, POKEMON_GEN3_HANDLER_RAGE_HIT, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_RAGE, 0, 0, 2, 0, 0, 0, 0, ${rageHitProgramOffset}, 3, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onHit"},`);
	lines.push(`    {POKEMON_HANDLER_EVENT_BEFORE_MOVE, POKEMON_GEN3_HANDLER_RAGE_BEFORE_MOVE, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_RAGE, 0, 100, 2, 0, 0, 0, 0, ${rageBeforeMoveProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onBeforeMove"},`);
	{
		const condition = dex.moves.get('minimize').condition;
		const modify = String(condition.onSourceModifyDamage);
		if (!/move\.flags\[["']minimize["']\]/.test(modify) ||
			!modify.includes('this.chainModify(2)')) {
			throw new Error('resolved Gen 3 Minimize damage modifier changed');
		}
	}
	lines.push('    {POKEMON_HANDLER_EVENT_RESTART, POKEMON_GEN3_HANDLER_MINIMIZE_RESTART, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_MINIMIZE, 0, 0, 2, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onRestart"},');
	lines.push(`    {POKEMON_HANDLER_EVENT_MODIFY_DAMAGE, POKEMON_GEN3_HANDLER_MINIMIZE_SOURCE_MODIFY_DAMAGE, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_MINIMIZE, 0, 0, 2, 0, 8192, 0, 1, ${minimizeDamageProgramOffset}, 2, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_OWNER, 0, "onSourceModifyDamage"},`);
	{
		const move = dex.moves.get('spite');
		const hit = String(move.onHit);
		if (move.accuracy !== 100 || move.category !== 'Status' ||
			move.target !== 'normal' || move.ignoreImmunity !== true ||
			move.flags?.protect !== 1 || move.flags?.bypasssub !== 1 ||
			move.flags?.mirror !== 1 ||
			move.flags?.metronome !== 1 || typeof move.onHit !== 'function' ||
			!hit.includes('this.random(2, 6)') ||
			!hit.includes('target.lastMove') || !hit.includes('target.deductPP')) {
			throw new Error('resolved Gen 3 Spite hit callback changed');
		}
	}
	lines.push(`    {POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK, POKEMON_GEN3_HANDLER_SPITE_HIT, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_SPITE, 0, 0, 0, 0, 0, 0, 0, ${spiteHitProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onHit"},`);
	{
		const camouflage = dex.moves.get('camouflage');
		const conversion = dex.moves.get('conversion');
		const camouflageHit = String(camouflage.onHit);
		const conversionHit = String(conversion.onHit);
		if (camouflage.accuracy !== true || camouflage.target !== 'self' ||
			!/hasType\(["']Normal["']\)/.test(camouflageHit) ||
			!/setType\(["']Normal["']\)/.test(camouflageHit) ||
			conversion.accuracy !== true || conversion.target !== 'self' ||
			!conversionHit.includes('target.moveSlots.map') ||
			!/move\.id !== ["']curse["']/.test(conversionHit) ||
			!conversionHit.includes('!target.hasType(move.type)') ||
			!conversionHit.includes('this.sample(possibleTypes)') ||
			!conversionHit.includes('target.setType(type)')) {
			throw new Error('resolved Gen 3 current-slot type overlay changed');
		}
	}
	lines.push(`    {POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK, POKEMON_GEN3_HANDLER_CAMOUFLAGE_HIT, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_CAMOUFLAGE, 0, 0, 0, 0, 0, 0, 0, ${camouflageProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onHit"},`);
	lines.push(`    {POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK, POKEMON_GEN3_HANDLER_CONVERSION_HIT, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_CONVERSION, 0, 0, 0, 0, 0, 0, 0, ${conversionProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onHit"},`);
	{
		const move = dex.moves.get('focuspunch');
		const condition = move.condition;
		if (move.basePower !== 150 || move.accuracy !== 100 ||
			move.category !== 'Physical' || move.priority !== -3 ||
			move.target !== 'normal' || typeof move.beforeTurnCallback !== 'function' ||
			move.priorityChargeCallback !== undefined ||
			move.beforeMoveCallback !== undefined || typeof move.onTry !== 'function' ||
			condition?.duration !== 1 || typeof condition.onStart !== 'function' ||
			typeof condition.onHit !== 'function' ||
			typeof condition.onTryAddVolatile !== 'function' ||
			!/addVolatile\(["']focuspunch["']\)/.test(String(move.beforeTurnCallback)) ||
			!/volatiles\[["']focuspunch["']\]\?\.lostFocus/.test(String(move.onTry)) ||
			!/move\.category !== ["']Status["']/.test(String(condition.onHit)) ||
			!/status\.id === ["']flinch["']/.test(String(condition.onTryAddVolatile))) {
			throw new Error('resolved Gen 3 Focus Punch lifecycle changed');
		}
	}
	lines.push('    {POKEMON_HANDLER_EVENT_START, POKEMON_GEN3_HANDLER_FOCUS_PUNCH_START, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_FOCUSPUNCH, 0, 0, 0, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onStart"},');
	lines.push(`    {POKEMON_HANDLER_EVENT_HIT, POKEMON_GEN3_HANDLER_FOCUS_PUNCH_HIT, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_FOCUSPUNCH, 0, 0, 2, 0, 0, 0, 0, ${focusPunchHitProgramOffset}, 2, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onHit"},`);
	lines.push(`    {POKEMON_HANDLER_EVENT_TRY_ADD_VOLATILE, POKEMON_GEN3_HANDLER_FOCUS_PUNCH_TRY_ADD_VOLATILE, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_FOCUSPUNCH, 0, 0, 2, 0, 0, 0, 0, ${focusPunchTryAddVolatileProgramOffset}, 2, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onTryAddVolatile"},`);
	lines.push(`    {POKEMON_HANDLER_EVENT_TRY, POKEMON_GEN3_HANDLER_FOCUS_PUNCH_TRY, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_FOCUSPUNCH, 0, 0, 0, 0, 0, 0, 0, ${focusPunchTryProgramOffset}, 3, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onTry"},`);
	{
		const destinyBond = dex.moves.get('destinybond');
		const grudge = dex.moves.get('grudge');
		if (destinyBond.accuracy !== true || destinyBond.target !== 'self' ||
			destinyBond.volatileStatus !== 'destinybond' ||
			typeof destinyBond.onPrepareHit !== 'function' ||
			!/removeVolatile\(["']destinybond["']\)/.test(String(destinyBond.onPrepareHit)) ||
			destinyBond.condition?.noCopy !== true ||
			typeof destinyBond.condition?.onStart !== 'function' ||
			typeof destinyBond.condition?.onFaint !== 'function' ||
			destinyBond.condition?.onBeforeMovePriority !== -1 ||
			typeof destinyBond.condition?.onBeforeMove !== 'function' ||
			typeof destinyBond.condition?.onMoveAborted !== 'function' ||
			grudge.accuracy !== true || grudge.target !== 'self' ||
			grudge.volatileStatus !== 'grudge' ||
			typeof grudge.condition?.onStart !== 'function' ||
			typeof grudge.condition?.onFaint !== 'function' ||
			grudge.condition?.onBeforeMovePriority !== 100 ||
			typeof grudge.condition?.onBeforeMove !== 'function') {
			throw new Error('resolved Gen 3 Destiny Bond / Grudge lifecycle changed');
		}
	}
	lines.push(`    {POKEMON_HANDLER_EVENT_PREPARE_HIT, POKEMON_GEN3_HANDLER_DESTINY_BOND_PREPARE_HIT, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_DESTINYBOND, 0, 0, 0, 0, 0, 0, 0, ${destinyBondPrepareHitProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onPrepareHit"},`);
	lines.push('    {POKEMON_HANDLER_EVENT_START, POKEMON_GEN3_HANDLER_DESTINY_BOND_START, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_DESTINYBOND, 0, 0, 0, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onStart"},');
	lines.push(`    {POKEMON_HANDLER_EVENT_BEFORE_MOVE, POKEMON_GEN3_HANDLER_DESTINY_BOND_BEFORE_MOVE, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_DESTINYBOND, 0, -1, 2, 0, 0, 0, 0, ${destinyBondBeforeMoveProgramOffset}, 2, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onBeforeMove"},`);
	lines.push(`    {POKEMON_HANDLER_EVENT_MOVE_ABORTED, POKEMON_GEN3_HANDLER_DESTINY_BOND_MOVE_ABORTED, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_DESTINYBOND, 0, 0, 2, 0, 0, 0, 0, ${destinyBondRemoveProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onMoveAborted"},`);
	lines.push(`    {POKEMON_HANDLER_EVENT_FAINT, POKEMON_GEN3_HANDLER_DESTINY_BOND_FAINT, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_DESTINYBOND, 0, 0, 2, 0, 0, 0, 0, ${destinyBondFaintProgramOffset}, 5, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onFaint"},`);
	lines.push('    {POKEMON_HANDLER_EVENT_START, POKEMON_GEN3_HANDLER_GRUDGE_START, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_GRUDGE, 0, 0, 0, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onStart"},');
	lines.push(`    {POKEMON_HANDLER_EVENT_BEFORE_MOVE, POKEMON_GEN3_HANDLER_GRUDGE_BEFORE_MOVE, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_GRUDGE, 0, 100, 2, 0, 0, 0, 0, ${grudgeRemoveProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onBeforeMove"},`);
	lines.push(`    {POKEMON_HANDLER_EVENT_FAINT, POKEMON_GEN3_HANDLER_GRUDGE_FAINT, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_GRUDGE, 0, 0, 2, 0, 0, 0, 0, ${grudgeFaintProgramOffset}, 4, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onFaint"},`);
	{
		const move = dex.moves.get('uproar');
		const condition = move.condition;
		const tryHit = String(move.onTryHit);
		const duration = String(condition?.durationCallback);
		const residual = String(condition?.onResidual);
		const setStatus = String(condition?.onAnySetStatus);
		if (move.accuracy !== 100 || move.basePower !== 50 ||
			move.category !== 'Physical' || move.target !== 'randomNormal' ||
			move.self?.volatileStatus !== 'uproar' || !move.flags?.sound ||
			!move.flags?.nosleeptalk || typeof move.onTryHit !== 'function' ||
			!/status === ["']slp["']/.test(tryHit) ||
			!tryHit.includes('cureStatus()') ||
			typeof condition?.durationCallback !== 'function' ||
			!duration.includes('this.random(2, 6)') ||
			typeof condition?.onStart !== 'function' ||
			typeof condition?.onResidual !== 'function' ||
			condition.onResidualOrder !== 10 ||
			condition.onResidualSubOrder !== 11 ||
			!/lastMove\.id === ["']struggle["']/.test(residual) ||
			typeof condition?.onEnd !== 'function' ||
			condition.onLockMove !== 'uproar' ||
			typeof condition?.onAnySetStatus !== 'function' ||
			!/status\.id === ["']slp["']/.test(setStatus) ||
			!setStatus.includes('return null')) {
			throw new Error('resolved Gen 3 Uproar lifecycle changed');
		}
	}
	lines.push(`    {POKEMON_HANDLER_EVENT_TRY_HIT, POKEMON_GEN3_HANDLER_UPROAR_TRY_HIT, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_UPROAR, 0, 0, 0, 0, 0, 0, 0, ${uproarTryHitProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onTryHit"},`);
	lines.push('    {POKEMON_HANDLER_EVENT_START, POKEMON_GEN3_HANDLER_UPROAR_START, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_UPROAR, 0, 0, 0, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onStart"},');
	lines.push(`    {POKEMON_HANDLER_EVENT_RESIDUAL, POKEMON_GEN3_HANDLER_UPROAR_RESIDUAL, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_UPROAR, 10, 0, 11, 0, 0, 0, 0, ${uproarResidualProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onResidual"},`);
	lines.push('    {POKEMON_HANDLER_EVENT_END, POKEMON_GEN3_HANDLER_UPROAR_END, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_UPROAR, 0, 0, 0, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onEnd"},');
	lines.push(`    {POKEMON_HANDLER_EVENT_LOCK_MOVE, POKEMON_GEN3_HANDLER_UPROAR_LOCK_MOVE, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_UPROAR, 0, 0, 2, 0, 0, 0, 0, ${uproarLockMoveProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onLockMove"},`);
	lines.push(`    {POKEMON_HANDLER_EVENT_SET_STATUS, POKEMON_GEN3_HANDLER_UPROAR_SET_STATUS, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_UPROAR, 0, 0, 2, 0, 0, 0, 0, ${uproarSetStatusProgramOffset}, 2, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_ANY, POKEMON_HANDLER_ROUTE_OWNER, 0, "onAnySetStatus"},`);
	{
		const move = dex.moves.get('imprison');
		const condition = move.condition;
		const tryHit = String(move.onTryHit);
		const disableMove = String(condition?.onFoeDisableMove);
		const beforeMove = String(condition?.onFoeBeforeMove);
		if (move.accuracy !== true || move.target !== 'self' ||
			move.volatileStatus !== 'imprison' || !move.flags?.bypasssub ||
			typeof move.onTryHit !== 'function' ||
			!tryHit.includes('target.moves.includes(move)') ||
			typeof condition?.onStart !== 'function' ||
			typeof condition?.onFoeDisableMove !== 'function' ||
			!disableMove.includes('this.effectState.source.moveSlots') ||
			!disableMove.includes('pokemon.disableMove(moveSlot.id, true)') ||
			condition.onFoeBeforeMovePriority !== 4 ||
			typeof condition?.onFoeBeforeMove !== 'function' ||
			!beforeMove.includes('this.effectState.source.hasMove(move.id)')) {
			throw new Error('resolved Gen 3 Imprison lifecycle changed');
		}
	}
	lines.push(`    {POKEMON_HANDLER_EVENT_TRY_HIT, POKEMON_GEN3_HANDLER_IMPRISON_TRY_HIT, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_IMPRISON, 0, 0, 0, 0, 0, 0, 0, ${imprisonTryHitProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onTryHit"},`);
	lines.push(`    {POKEMON_HANDLER_EVENT_DISABLE_MOVE, POKEMON_GEN3_HANDLER_IMPRISON_DISABLE_MOVE, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_IMPRISON, 0, 0, 2, 0, 0, 0, 0, ${imprisonDisableMoveProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_FOE, POKEMON_HANDLER_ROUTE_OWNER, 0, "onFoeDisableMove"},`);
	lines.push(`    {POKEMON_HANDLER_EVENT_BEFORE_MOVE, POKEMON_GEN3_HANDLER_IMPRISON_BEFORE_MOVE, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_IMPRISON, 0, 4, 2, 0, 0, 0, 0, ${imprisonBeforeMoveProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_FOE, POKEMON_HANDLER_ROUTE_OWNER, 0, "onFoeBeforeMove"},`);
	lines.push('    {POKEMON_HANDLER_EVENT_MODIFY_MOVE, POKEMON_GEN3_HANDLER_SECRET_POWER_MODIFY_MOVE, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_SECRETPOWER, 0, 0, 0, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onModifyMove"},');
	{
		const move = dex.moves.get('present');
		const source = String(move.onModifyMove);
		if (!move.exists || move.gen > 3 || move.basePower !== 0 ||
			move.accuracy !== 90 || move.type !== 'Normal' ||
			move.category !== 'Physical' ||
			typeof move.onModifyMove !== 'function' ||
			!source.includes('this.random(10)') ||
			!source.includes('move.heal = [1, 4]') ||
			!source.includes('move.infiltrates = true')) {
			throw new Error('resolved Gen 3 Present shape changed');
		}
	}
	lines.push(`    {POKEMON_HANDLER_EVENT_MODIFY_MOVE, POKEMON_GEN3_HANDLER_PRESENT_MODIFY_MOVE, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_PRESENT, 0, 0, 0, 0, 0, 0, 0, ${presentProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onModifyMove"},`);
	lines.push('    {POKEMON_HANDLER_EVENT_SET_STATUS, POKEMON_GEN3_HANDLER_SLEEP_CLAUSE_SET_STATUS, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_PSEUDO_WEATHER_SLEEPCLAUSEMOD, 0, 0, 5, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_STATUS_CLAUSE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onSetStatus"},');
	lines.push('    {POKEMON_HANDLER_EVENT_SET_STATUS, POKEMON_GEN3_HANDLER_FREEZE_CLAUSE_SET_STATUS, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_PSEUDO_WEATHER_FREEZECLAUSEMOD, 0, 0, 5, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_STATUS_CLAUSE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onSetStatus"},');
	lines.push(`    {POKEMON_HANDLER_EVENT_MODIFY_MOVE, POKEMON_GEN3_HANDLER_CURSE_MODIFY_MOVE, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_CURSE, 0, 0, 0, 0, 0, 0, 0, ${curseModifyMoveProgramOffset}, 3, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onModifyMove", 0},`);
	lines.push(`    {POKEMON_HANDLER_EVENT_TRY_HIT, POKEMON_GEN3_HANDLER_CURSE_TRY_HIT, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_CURSE, 0, 0, 0, 0, 0, 0, 0, ${curseTryHitProgramOffset}, 2, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onTryHit", 0},`);
	lines.push(`    {POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK, POKEMON_GEN3_HANDLER_CURSE_HIT, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_CURSE, 0, 0, 0, 0, 0, 0, 0, ${curseHitProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onHit", 1},`);
	lines.push('    {POKEMON_HANDLER_EVENT_START, POKEMON_GEN3_HANDLER_CURSE_START, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_CURSE, 0, 0, 0, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onStart", 0},');
	lines.push(`    {POKEMON_HANDLER_EVENT_RESIDUAL, POKEMON_GEN3_HANDLER_CURSE_RESIDUAL, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_CURSE, 10, 0, 8, 0, 0, 0, 0, ${curseResidualProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onResidual", 0},`);
	lines.push('    {POKEMON_HANDLER_EVENT_START, POKEMON_GEN3_HANDLER_MUST_RECHARGE_START, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_MUSTRECHARGE, 0, 0, 2, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onStart"},');
	{
		const ability = dex.abilities.get('truant');
		const switchIn = String(ability.onSwitchIn);
		const beforeMove = String(ability.onBeforeMove);
		const residual = String(ability.onResidual);
		if (ability.onStart !== undefined ||
			typeof ability.onSwitchIn !== 'function' ||
			!switchIn.includes('pokemon.truantTurn = this.turn !== 0') ||
			typeof ability.onBeforeMove !== 'function' ||
			!beforeMove.includes('if (pokemon.truantTurn)') ||
			!beforeMove.includes('return false') ||
			ability.onResidualOrder !== 27 ||
			typeof ability.onResidual !== 'function' ||
			!residual.includes('pokemon.truantTurn = !pokemon.truantTurn')) {
			throw new Error('resolved Gen 3 Truant lifecycle changed');
		}
	}
	lines.push(`    {POKEMON_HANDLER_EVENT_SWITCH_IN, POKEMON_GEN3_HANDLER_TRUANT_SWITCH_IN, POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_TRUANT, 0, 0, 7, 0, 0, 0, 0, ${truantSwitchInProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onSwitchIn"},`);
	lines.push(`    {POKEMON_HANDLER_EVENT_BEFORE_MOVE, POKEMON_GEN3_HANDLER_TRUANT_BEFORE_MOVE, POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_TRUANT, 0, 9, 7, 0, 0, 0, 0, ${truantBeforeMoveProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onBeforeMove"},`);
	lines.push(`    {POKEMON_HANDLER_EVENT_RESIDUAL, POKEMON_GEN3_HANDLER_TRUANT_RESIDUAL, POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_TRUANT, 27, 0, 7, 0, 0, 0, 0, ${truantResidualProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onResidual"},`);
	{
		const move = dex.moves.get('painsplit');
		const hit = String(move.onHit);
		if (!move.exists || move.gen > 3 || move.accuracy !== true ||
			move.basePower !== 0 || move.category !== 'Status' ||
			move.target !== 'normal' || typeof move.onHit !== 'function' ||
			!hit.includes('Math.floor((targetHP + pokemon.hp) / 2) || 1') ||
			!hit.includes('target.sethp(target.hp - targetChange)') ||
			!hit.includes('pokemon.sethp(averagehp)')) {
			throw new Error('resolved Gen 3 Pain Split assignment changed');
		}
	}
	lines.push(`    {POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK, POKEMON_GEN3_HANDLER_PAIN_SPLIT_HIT, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_PAINSPLIT, 0, 0, 0, 0, 0, 0, 0, ${painSplitHitProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onHit"},`);
	lines.push('    {POKEMON_HANDLER_EVENT_MOVE_FAIL, POKEMON_GEN3_HANDLER_JUMP_KICK_MOVE_FAIL, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_JUMPKICK, 0, 0, 0, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onMoveFail"},');
	lines.push('    {POKEMON_HANDLER_EVENT_MOVE_FAIL, POKEMON_GEN3_HANDLER_HIGH_JUMP_KICK_MOVE_FAIL, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_HIGHJUMPKICK, 0, 0, 0, 0, 0, 0, 0, 0, 0, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onMoveFail"},');
	lines.push(`    {POKEMON_HANDLER_EVENT_BASE_POWER, POKEMON_GEN3_HANDLER_REVENGE_BASE_POWER, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_REVENGE, 0, 0, 0, 0, 0, 0, 0, ${revengeBasePowerProgramOffset}, 2, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "basePowerCallback"},`);
	{
		const move = dex.moves.get('dreameater');
		const source = String(move.onTryImmunity);
		if (!move.exists || move.gen > 3 || move.basePower !== 100 ||
			move.accuracy !== 100 || move.type !== 'Psychic' ||
			move.category !== 'Special' || move.drain?.[0] !== 1 ||
			move.drain?.[1] !== 2 || typeof move.onTryImmunity !== 'function' ||
			!/target\.status === ["']slp["']/.test(source) ||
			!/!target\.volatiles\[["']substitute["']\]/.test(source)) {
			throw new Error('resolved Gen 3 Dream Eater shape changed');
		}
	}
	lines.push(`    {POKEMON_HANDLER_EVENT_TRY_IMMUNITY, POKEMON_GEN3_HANDLER_DREAM_EATER_TRY_IMMUNITY, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_DREAMEATER, 0, 0, 0, 0, 0, 0, 0, ${dreamEaterTryImmunityProgramOffset}, 2, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onTryImmunity"},`);
	{
		const ability = dex.abilities.get('forecast');
		const start = String(ability.onStart);
		const weatherChange = String(ability.onWeatherChange);
		if (!ability.exists || ability.gen > 3 || ability.onSwitchInPriority !== -2 ||
			typeof ability.onStart !== 'function' ||
			!/this\.singleEvent\(["']WeatherChange["']/.test(start) ||
			typeof ability.onWeatherChange !== 'function' ||
			!/pokemon\.baseSpecies\.baseSpecies !== ["']Castform["']/.test(weatherChange) ||
			!weatherChange.includes('pokemon.transformed') ||
			!weatherChange.includes('pokemon.effectiveWeather()') ||
			!/forme = ["']Castform-Sunny["']/.test(weatherChange) ||
			!/forme = ["']Castform-Rainy["']/.test(weatherChange) ||
			!/forme = ["']Castform-Snowy["']/.test(weatherChange) ||
			!/forme = ["']Castform["']/.test(weatherChange) ||
			!weatherChange.includes('pokemon.isActive && forme') ||
			!weatherChange.includes('pokemon.formeChange(forme')) {
			throw new Error('resolved Gen 3 Forecast lifecycle changed');
		}
	}
	lines.push(`    {POKEMON_HANDLER_EVENT_START, POKEMON_GEN3_HANDLER_FORECAST_START, POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_FORECAST, 0, 0, 0, 0, 0, 0, 0, ${forecastStartProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onStart"},`);
	lines.push(`    {POKEMON_HANDLER_EVENT_WEATHER_CHANGE, POKEMON_GEN3_HANDLER_FORECAST_WEATHER_CHANGE, POKEMON_HANDLER_SOURCE_ABILITY, POKEMON_GEN3_ABILITY_FORECAST, 0, 0, 7, 0, 0, 0, 0, ${forecastWeatherChangeProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onWeatherChange"},`);
	{
		const move = dex.moves.get('transform');
		const hit = String(move.onHit);
		if (!move.exists || move.gen > 3 || move.accuracy !== true ||
			move.target !== 'normal' || typeof move.onHit !== 'function' ||
			!hit.includes('pokemon.transformInto(target)')) {
			throw new Error('resolved Gen 3 Transform delegation changed');
		}
	}
	lines.push(`    {POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK, POKEMON_GEN3_HANDLER_TRANSFORM_HIT, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_TRANSFORM, 0, 0, 0, 0, 0, 0, 0, ${transformHitProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onHit"},`);
	{
		const move = dex.moves.get('smellingsalts');
		const basePower = String(move.basePowerCallback);
		const hit = String(move.onHit);
		if (!move.exists || move.gen > 3 || move.basePower !== 60 ||
			move.accuracy !== 100 || move.category !== 'Physical' ||
			move.target !== 'normal' ||
			typeof move.basePowerCallback !== 'function' ||
			!basePower.includes("target.status === 'par'") &&
				!basePower.includes('target.status === "par"') ||
			!basePower.includes('move.basePower * 2') ||
			typeof move.onHit !== 'function' ||
			!hit.includes("target.status === 'par'") &&
				!hit.includes('target.status === "par"') ||
			!hit.includes('target.cureStatus()')) {
			throw new Error('resolved Gen 3 Smelling Salts callbacks changed');
		}
	}
	lines.push(`    {POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK, POKEMON_GEN3_HANDLER_SMELLING_SALTS_HIT, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_SMELLINGSALTS, 0, 0, 0, 0, 0, 0, 0, ${smellingSaltsHitProgramOffset}, 2, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onHit"},`);
	{
		const move = dex.moves.get('bellydrum');
		const hit = String(move.onHit);
		if (!move.exists || move.gen > 3 || move.accuracy !== true ||
			move.basePower !== 0 || move.category !== 'Status' ||
			move.target !== 'self' || typeof move.onHit !== 'function' ||
			!hit.includes('target.hp <= target.maxhp / 2') ||
			!hit.includes('target.boosts.atk >= 6') ||
			!hit.includes('target.maxhp === 1') ||
			!hit.includes('this.directDamage(target.maxhp / 2)') ||
			!hit.includes('this.boost({ atk: 12 }, target)')) {
			throw new Error('resolved Gen 3 Belly Drum callback changed');
		}
	}
	lines.push(`    {POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK, POKEMON_GEN3_HANDLER_BELLY_DRUM_HIT, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_BELLYDRUM, 0, 0, 0, 0, 0, 0, 0, ${bellyDrumHitProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onHit"},`);
	{
		const move = dex.moves.get('beatup');
		const modify = String(move.onModifyMove);
		const basePower = String(move.basePowerCallback);
		const modifySpA = String(move.condition?.onModifySpA);
		const modifySpD = String(move.condition?.onFoeModifySpD);
		if (!move.exists || move.gen > 3 || move.basePower !== 10 ||
			move.accuracy !== 100 || move.category !== 'Special' ||
			move.target !== 'normal' || typeof move.onModifyMove !== 'function' ||
			!modify.includes('pokemon.addVolatile("beatup")') ||
			!modify.includes('move.type = "???"') ||
			!modify.includes('move.category = "Special"') ||
			!modify.includes('!ally.fainted && !ally.status') ||
			!modify.includes('move.multihit = move.allies.length') ||
			typeof move.basePowerCallback !== 'function' ||
			!basePower.includes('!move.allies?.length') ||
			move.condition?.duration !== 1 ||
			move.condition?.onModifySpAPriority !== -101 ||
			move.condition?.onFoeModifySpDPriority !== -101 ||
			!modifySpA.includes('move.allies.shift()') ||
			!modifySpA.includes('baseStats.atk') ||
			!modifySpD.includes('pokemon.set.species') ||
			!modifySpD.includes('baseStats.def')) {
			throw new Error('resolved Gen 3 Beat Up party-hit semantics changed');
		}
	}
	lines.push(`    {POKEMON_HANDLER_EVENT_MODIFY_MOVE, POKEMON_GEN3_HANDLER_BEAT_UP_MODIFY_MOVE, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_BEATUP, 0, 0, 0, 0, 0, 0, 0, ${beatUpModifyMoveProgramOffset}, 4, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "onModifyMove"},`);
	lines.push(`    {POKEMON_HANDLER_EVENT_BASE_POWER, POKEMON_GEN3_HANDLER_BEAT_UP_BASE_POWER, POKEMON_HANDLER_SOURCE_MOVE, POKEMON_GEN3_MOVE_BEATUP, 0, 0, 0, 0, 0, 0, 0, ${beatUpBasePowerProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 0, "basePowerCallback"},`);
	lines.push(`    {POKEMON_HANDLER_EVENT_MODIFY_SPA, POKEMON_GEN3_HANDLER_BEAT_UP_MODIFY_SPA, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_BEATUP, 0, -101, 2, 0, 0, 0, 0, ${beatUpModifySpAProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, "onModifySpA"},`);
	lines.push(`    {POKEMON_HANDLER_EVENT_MODIFY_SPD, POKEMON_GEN3_HANDLER_BEAT_UP_MODIFY_SPD, POKEMON_HANDLER_SOURCE_CONDITION, POKEMON_GEN3_CONDITION_VOLATILE_BEATUP, 0, -101, 2, 0, 0, 0, 0, ${beatUpModifySpDProgramOffset}, 1, POKEMON_EXCEPTION_NONE, POKEMON_HANDLER_SCOPE_FOE, POKEMON_HANDLER_ROUTE_OWNER, 0, "onFoeModifySpD"},`);
  const mistHandlerOffset = encoreHandlerOffset +
    ENCORE_LIFECYCLE_HANDLER_IDS.length + STRUGGLE_HANDLER_IDS.length +
    DISABLE_MOVE_HANDLER_IDS.length + BRICK_BREAK_HANDLER_IDS.length;
  const safeguardHandlerOffset = mistHandlerOffset + MIST_HANDLER_IDS.length;
  const starterAbilityHandlerOffset = safeguardHandlerOffset + SAFEGUARD_HANDLER_IDS.length;
  const yawnHandlerOffset = starterAbilityHandlerOffset + STARTER_ABILITY_HANDLERS.length;
  const spikesHandlerOffset = yawnHandlerOffset + YAWN_HANDLER_IDS.length;
  const screenHandlerOffset = spikesHandlerOffset + SPIKES_HANDLER_IDS.length;
  lines.push('};', '', 'static const PokemonOwnerBindingIndex OWNER_BINDING_INDEX[] = {',
	'    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_FURYCUTTER, POKEMON_HANDLER_EVENT_BASE_POWER, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_FURY_CUTTER_BASE_POWER - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_FURYCUTTER, POKEMON_HANDLER_EVENT_START, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_FURY_CUTTER_START - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_FURYCUTTER, POKEMON_HANDLER_EVENT_RESTART, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_FURY_CUTTER_RESTART - 1, 1},',
	'    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_FURYCUTTER, POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_FURY_CUTTER_HIT - 1, 1},',
	'    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_ROLLOUT, POKEMON_HANDLER_EVENT_MODIFY_MOVE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_ROLLOUT_MODIFY_MOVE - 1, 1},',
	'    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_ROLLOUT, POKEMON_HANDLER_EVENT_BASE_POWER, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_ROLLOUT_BASE_POWER - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_ROLLOUT, POKEMON_HANDLER_EVENT_START, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_ROLLOUT_START - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_ROLLOUT, POKEMON_HANDLER_EVENT_LOCK_MOVE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_ROLLOUT_LOCK_MOVE - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_ROLLOUT, POKEMON_HANDLER_EVENT_RESIDUAL, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_ROLLOUT_RESIDUAL - 1, 1},',
	'    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_ICEBALL, POKEMON_HANDLER_EVENT_MODIFY_MOVE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_ICE_BALL_MODIFY_MOVE - 1, 1},',
	'    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_ICEBALL, POKEMON_HANDLER_EVENT_BASE_POWER, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_ICE_BALL_BASE_POWER - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_ICEBALL, POKEMON_HANDLER_EVENT_START, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_ICE_BALL_START - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_ICEBALL, POKEMON_HANDLER_EVENT_LOCK_MOVE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_ICE_BALL_LOCK_MOVE - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_ICEBALL, POKEMON_HANDLER_EVENT_RESIDUAL, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_ICE_BALL_RESIDUAL - 1, 1},',
	'    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_STOCKPILE, POKEMON_HANDLER_EVENT_TRY, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_STOCKPILE_TRY - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_STOCKPILE, POKEMON_HANDLER_EVENT_START, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_STOCKPILE_START - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_STOCKPILE, POKEMON_HANDLER_EVENT_RESTART, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_STOCKPILE_RESTART - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_STOCKPILE, POKEMON_HANDLER_EVENT_END, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_STOCKPILE_END - 1, 1},',
	'    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_SPITUP, POKEMON_HANDLER_EVENT_TRY, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_SPIT_UP_TRY - 1, 1},',
	'    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_SPITUP, POKEMON_HANDLER_EVENT_BASE_POWER, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_SPIT_UP_BASE_POWER - 1, 1},',
	'    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_SPITUP, POKEMON_HANDLER_EVENT_AFTER_MOVE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_SPIT_UP_AFTER_MOVE - 1, 1},',
	'    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_SWALLOW, POKEMON_HANDLER_EVENT_TRY, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_SWALLOW_TRY - 1, 1},',
	'    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_SWALLOW, POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_SWALLOW_HIT - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_BIDE, POKEMON_HANDLER_EVENT_START, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_BIDE_START - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_BIDE, POKEMON_HANDLER_EVENT_DAMAGE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_BIDE_DAMAGE - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_BIDE, POKEMON_HANDLER_EVENT_BEFORE_MOVE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_BIDE_BEFORE_MOVE - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_BIDE, POKEMON_HANDLER_EVENT_MOVE_ABORTED, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_BIDE_MOVE_ABORTED - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_BIDE, POKEMON_HANDLER_EVENT_END, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_BIDE_END - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_BIDE, POKEMON_HANDLER_EVENT_RESIDUAL, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_BIDE_RESIDUAL - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_RAGE, POKEMON_HANDLER_EVENT_START, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_RAGE_START - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_RAGE, POKEMON_HANDLER_EVENT_HIT, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_RAGE_HIT - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_RAGE, POKEMON_HANDLER_EVENT_BEFORE_MOVE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_RAGE_BEFORE_MOVE - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_MINIMIZE, POKEMON_HANDLER_EVENT_RESTART, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_MINIMIZE_RESTART - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_MINIMIZE, POKEMON_HANDLER_EVENT_MODIFY_DAMAGE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_MINIMIZE_SOURCE_MODIFY_DAMAGE - 1, 1},',
	'    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_SPITE, POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_SPITE_HIT - 1, 1},',
	'    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_CAMOUFLAGE, POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_CAMOUFLAGE_HIT - 1, 1},',
	'    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_CONVERSION, POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_CONVERSION_HIT - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_FOCUSPUNCH, POKEMON_HANDLER_EVENT_START, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_FOCUS_PUNCH_START - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_FOCUSPUNCH, POKEMON_HANDLER_EVENT_HIT, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_FOCUS_PUNCH_HIT - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_FOCUSPUNCH, POKEMON_HANDLER_EVENT_TRY_ADD_VOLATILE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_FOCUS_PUNCH_TRY_ADD_VOLATILE - 1, 1},',
	'    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_FOCUSPUNCH, POKEMON_HANDLER_EVENT_TRY, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_FOCUS_PUNCH_TRY - 1, 1},',
	'    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_DESTINYBOND, POKEMON_HANDLER_EVENT_PREPARE_HIT, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_DESTINY_BOND_PREPARE_HIT - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_DESTINYBOND, POKEMON_HANDLER_EVENT_START, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_DESTINY_BOND_START - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_DESTINYBOND, POKEMON_HANDLER_EVENT_BEFORE_MOVE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_DESTINY_BOND_BEFORE_MOVE - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_DESTINYBOND, POKEMON_HANDLER_EVENT_MOVE_ABORTED, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_DESTINY_BOND_MOVE_ABORTED - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_DESTINYBOND, POKEMON_HANDLER_EVENT_FAINT, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_DESTINY_BOND_FAINT - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_GRUDGE, POKEMON_HANDLER_EVENT_START, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_GRUDGE_START - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_GRUDGE, POKEMON_HANDLER_EVENT_BEFORE_MOVE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_GRUDGE_BEFORE_MOVE - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_GRUDGE, POKEMON_HANDLER_EVENT_FAINT, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_GRUDGE_FAINT - 1, 1},',
	'    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_UPROAR, POKEMON_HANDLER_EVENT_TRY_HIT, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_UPROAR_TRY_HIT - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_UPROAR, POKEMON_HANDLER_EVENT_START, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_UPROAR_START - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_UPROAR, POKEMON_HANDLER_EVENT_RESIDUAL, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_UPROAR_RESIDUAL - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_UPROAR, POKEMON_HANDLER_EVENT_END, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_UPROAR_END - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_UPROAR, POKEMON_HANDLER_EVENT_LOCK_MOVE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_UPROAR_LOCK_MOVE - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_UPROAR, POKEMON_HANDLER_EVENT_SET_STATUS, POKEMON_HANDLER_SCOPE_ANY, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_UPROAR_SET_STATUS - 1, 1},',
	'    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_IMPRISON, POKEMON_HANDLER_EVENT_TRY_HIT, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_IMPRISON_TRY_HIT - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_IMPRISON, POKEMON_HANDLER_EVENT_DISABLE_MOVE, POKEMON_HANDLER_SCOPE_FOE, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_IMPRISON_DISABLE_MOVE - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_IMPRISON, POKEMON_HANDLER_EVENT_BEFORE_MOVE, POKEMON_HANDLER_SCOPE_FOE, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_IMPRISON_BEFORE_MOVE - 1, 1},',
	'    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_SECRETPOWER, POKEMON_HANDLER_EVENT_MODIFY_MOVE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_SECRET_POWER_MODIFY_MOVE - 1, 1},',
	'    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_PRESENT, POKEMON_HANDLER_EVENT_MODIFY_MOVE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_PRESENT_MODIFY_MOVE - 1, 1},',
    '    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_TRACE, POKEMON_HANDLER_EVENT_START, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_TRACE_START - 1, 1},',
    '    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_STURDY, POKEMON_HANDLER_EVENT_TRY_HIT, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_STURDY_TRY_HIT - 1, 1},',
    '    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_METRONOME, POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_METRONOME_HIT - 1, 1},',
    '    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_ASSIST, POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_ASSIST_HIT - 1, 1},',
    '    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_NATUREPOWER, POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_NATURE_POWER_HIT - 1, 1},',
    '    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_SLEEPTALK, POKEMON_HANDLER_EVENT_TRY, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_SLEEP_TALK_TRY - 1, 1},',
    '    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_SLEEPTALK, POKEMON_HANDLER_EVENT_TRY_HIT, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_SLEEP_TALK_TRY_HIT - 1, 1},',
    '    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_SLEEPTALK, POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_SLEEP_TALK_HIT - 1, 1},',
    '    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_MIMIC, POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_MIMIC_HIT - 1, 1},',
    '    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_SKETCH, POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_SKETCH_HIT - 1, 1},',
    '    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_PERISHSONG, POKEMON_HANDLER_EVENT_MOVE_HIT_FIELD_CALLBACK, POKEMON_HANDLER_SCOPE_FIELD, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_PERISH_SONG_HIT_FIELD - 1, 1},',
    '    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_PERISHSONG, POKEMON_HANDLER_EVENT_RESIDUAL, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_PERISH_SONG_RESIDUAL - 1, 1},',
    '    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_PERISHSONG, POKEMON_HANDLER_EVENT_END, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_PERISH_SONG_END - 1, 1},',
    '    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_FORESIGHT, POKEMON_HANDLER_EVENT_TRY_HIT, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_FORESIGHT_TRY_HIT - 1, 1},',
    '    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_ODORSLEUTH, POKEMON_HANDLER_EVENT_TRY_HIT, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_ODOR_SLEUTH_TRY_HIT - 1, 1},',
    '    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_FORESIGHT, POKEMON_HANDLER_EVENT_START, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_FORESIGHT_START - 1, 1},',
    '    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_FORESIGHT, POKEMON_HANDLER_EVENT_NEGATE_IMMUNITY, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_FORESIGHT_NEGATE_IMMUNITY - 1, 1},',
    '    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_FORESIGHT, POKEMON_HANDLER_EVENT_MODIFY_BOOST, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_FORESIGHT_MODIFY_BOOST - 1, 1},',
    '    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_COLORCHANGE, POKEMON_HANDLER_EVENT_DAMAGING_HIT, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_COLOR_CHANGE_DAMAGING_HIT - 1, 1},',
    '    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_CUTECHARM, POKEMON_HANDLER_EVENT_DAMAGING_HIT, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_CUTE_CHARM_DAMAGING_HIT - 1, 1},',
    '    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_ATTRACT, POKEMON_HANDLER_EVENT_TRY_IMMUNITY, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_ATTRACT_TRY_IMMUNITY - 1, 1},',
    '    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_ATTRACT, POKEMON_HANDLER_EVENT_START, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_ATTRACT_START - 1, 1},',
    '    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_ATTRACT, POKEMON_HANDLER_EVENT_BEFORE_MOVE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_ATTRACT_BEFORE_MOVE - 1, 1},',
    '    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_ATTRACT, POKEMON_HANDLER_EVENT_UPDATE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_ATTRACT_UPDATE - 1, 1},',
    '    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_ATTRACT, POKEMON_HANDLER_EVENT_END, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_ATTRACT_END - 1, 1},',
    '    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_INTIMIDATE, POKEMON_HANDLER_EVENT_START, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_INTIMIDATE_START - 1, 1},',
    '    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_NIGHTMARE, POKEMON_HANDLER_EVENT_START, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_NIGHTMARE_START - 1, 1},',
    '    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_NIGHTMARE, POKEMON_HANDLER_EVENT_RESIDUAL, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_NIGHTMARE_RESIDUAL - 1, 1},',
    '    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_WATERABSORB, POKEMON_HANDLER_EVENT_TRY_HIT, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 0, 1},',
    '    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_VOLTABSORB, POKEMON_HANDLER_EVENT_TRY_HIT, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 12, 1},',
    '    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_THICKFAT, POKEMON_HANDLER_EVENT_BASE_POWER, POKEMON_HANDLER_SCOPE_FOE, POKEMON_HANDLER_ROUTE_OWNER, 13, 1},',
    '    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_MARVELSCALE, POKEMON_HANDLER_EVENT_MODIFY_DEF, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 14, 1},',
    '    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_FACADE, POKEMON_HANDLER_EVENT_BASE_POWER, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 15, 1},',
    '    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_REFRESH, POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 16, 1},',
    '    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_AROMATHERAPY, POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_AROMATHERAPY_HIT - 1, 1},',
    '    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_HEALBELL, POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_HEAL_BELL_HIT - 1, 1},',
    '    {POKEMON_OWNER_STATUS, POKEMON_GEN3_CONDITION_STATUS_FRZ, POKEMON_HANDLER_EVENT_START, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_FREEZE_START - 1, 1},',
    '    {POKEMON_OWNER_STATUS, POKEMON_GEN3_CONDITION_STATUS_FRZ, POKEMON_HANDLER_EVENT_BEFORE_MOVE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_FREEZE_BEFORE_MOVE - 1, 1},',
    '    {POKEMON_OWNER_STATUS, POKEMON_GEN3_CONDITION_STATUS_FRZ, POKEMON_HANDLER_EVENT_MODIFY_MOVE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_FREEZE_MODIFY_MOVE - 1, 1},',
    '    {POKEMON_OWNER_STATUS, POKEMON_GEN3_CONDITION_STATUS_FRZ, POKEMON_HANDLER_EVENT_DAMAGING_HIT, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_FREEZE_DAMAGING_HIT - 1, 1},',
    '    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_OBLIVIOUS, POKEMON_HANDLER_EVENT_IMMUNITY, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_OBLIVIOUS_IMMUNITY - 1, 1},',
    '    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_OBLIVIOUS, POKEMON_HANDLER_EVENT_TRY_HIT, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_OBLIVIOUS_TRY_HIT - 1, 1},',
    '    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_OBLIVIOUS, POKEMON_HANDLER_EVENT_UPDATE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_OBLIVIOUS_UPDATE - 1, 1},',
    '    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_ROLEPLAY, POKEMON_HANDLER_EVENT_TRY_HIT, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_ROLE_PLAY_TRY_HIT - 1, 1},',
    '    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_ROLEPLAY, POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_ROLE_PLAY_HIT - 1, 1},',
	'    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_SKILLSWAP, POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_SKILL_SWAP_HIT - 1, 1},',
	'    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_BLOCK, POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_BLOCK_HIT - 1, 1},',
	'    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_MEANLOOK, POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_MEAN_LOOK_HIT - 1, 1},',
	'    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_SPIDERWEB, POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_SPIDER_WEB_HIT - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_TRAPPED, POKEMON_HANDLER_EVENT_START, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_TRAPPED_START - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_TRAPPED, POKEMON_HANDLER_EVENT_TRAP_POKEMON, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_TRAPPED_TRAP_POKEMON - 1, 1},',
    '    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_PSYCHUP, POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, 17, 1},',
    '    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_GUTS, POKEMON_HANDLER_EVENT_MODIFY_ATK, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 1, 1},',
    '    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_ROCKHEAD, POKEMON_HANDLER_EVENT_DAMAGE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 3, 1},',
    '    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_CLEARBODY, POKEMON_HANDLER_EVENT_TRY_BOOST, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 4, 1},',
    '    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_HYPERCUTTER, POKEMON_HANDLER_EVENT_TRY_BOOST, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 5, 1},',
    '    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_KEENEYE, POKEMON_HANDLER_EVENT_TRY_BOOST, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 6, 1},',
    '    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_WHITESMOKE, POKEMON_HANDLER_EVENT_TRY_BOOST, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 7, 1},',
    '    {POKEMON_OWNER_ITEM, POKEMON_GEN3_ITEM_BLACKBELT, POKEMON_HANDLER_EVENT_MODIFY_ATK, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 2, 1},',
    ...TYPE_BOOST_ITEMS.slice(1).map(([id, event], index) =>
      `    {POKEMON_OWNER_ITEM, POKEMON_GEN3_ITEM_${cName(id)}, POKEMON_HANDLER_EVENT_${eventToken(event)}, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${typeBoostHandlerOffset + index}, 1},`),
    `    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_COMPOUNDEYES, POKEMON_HANDLER_EVENT_MODIFY_ACCURACY, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_OWNER, ${scalarHandlerOffset}, 1},`,
    `    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_HUGEPOWER, POKEMON_HANDLER_EVENT_MODIFY_ATK, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${scalarHandlerOffset + 1}, 1},`,
    `    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_HUSTLE, POKEMON_HANDLER_EVENT_MODIFY_ATK, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${scalarHandlerOffset + 2}, 1},`,
    `    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_HUSTLE, POKEMON_HANDLER_EVENT_MODIFY_ACCURACY, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_OWNER, ${scalarHandlerOffset + 3}, 1},`,
    `    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_PUREPOWER, POKEMON_HANDLER_EVENT_MODIFY_ATK, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${scalarHandlerOffset + 4}, 1},`,
    `    {POKEMON_OWNER_ITEM, POKEMON_GEN3_ITEM_THICKCLUB, POKEMON_HANDLER_EVENT_MODIFY_ATK, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${scalarHandlerOffset + 5}, 1},`,
    `    {POKEMON_OWNER_FIELD, POKEMON_GEN3_CONDITION_WEATHER_RAINDANCE, POKEMON_HANDLER_EVENT_WEATHER_MODIFY_DAMAGE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${weatherHandlerOffset}, 1},`,
    `    {POKEMON_OWNER_FIELD, POKEMON_GEN3_CONDITION_WEATHER_SUNNYDAY, POKEMON_HANDLER_EVENT_WEATHER_MODIFY_DAMAGE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${weatherHandlerOffset + 1}, 1},`,
    `    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_CHLOROPHYLL, POKEMON_HANDLER_EVENT_MODIFY_SPE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${speedHandlerOffset}, 1},`,
    `    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_SWIFTSWIM, POKEMON_HANDLER_EVENT_MODIFY_SPE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${speedHandlerOffset + 1}, 1},`,
    `    {POKEMON_OWNER_STATUS, POKEMON_GEN3_CONDITION_STATUS_PAR, POKEMON_HANDLER_EVENT_MODIFY_SPE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${speedHandlerOffset + 2}, 1},`,
    `    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_RAINDISH, POKEMON_HANDLER_EVENT_RESIDUAL, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${residualHandlerOffset}, 1},`,
    '    {POKEMON_OWNER_ITEM, POKEMON_GEN3_ITEM_LEFTOVERS, POKEMON_HANDLER_EVENT_RESIDUAL, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_LEFTOVERS_RESIDUAL - 1, 1},',
    '    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_NATURALCURE, POKEMON_HANDLER_EVENT_SWITCH_OUT, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_NATURAL_CURE_SWITCH_OUT - 1, 1},',
    '    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_SHEDSKIN, POKEMON_HANDLER_EVENT_RESIDUAL, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_SHED_SKIN_RESIDUAL - 1, 1},',
    '    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_SPEEDBOOST, POKEMON_HANDLER_EVENT_RESIDUAL, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_SPEED_BOOST_RESIDUAL - 1, 1},',
    '    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_TRUANT, POKEMON_HANDLER_EVENT_SWITCH_IN, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_TRUANT_SWITCH_IN - 1, 1},',
    '    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_TRUANT, POKEMON_HANDLER_EVENT_BEFORE_MOVE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_TRUANT_BEFORE_MOVE - 1, 1},',
    '    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_TRUANT, POKEMON_HANDLER_EVENT_RESIDUAL, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_TRUANT_RESIDUAL - 1, 1},',
	'    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_FORECAST, POKEMON_HANDLER_EVENT_START, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_FORECAST_START - 1, 1},',
	'    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_FORECAST, POKEMON_HANDLER_EVENT_WEATHER_CHANGE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_FORECAST_WEATHER_CHANGE - 1, 1},',
	'    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_TRANSFORM, POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_TRANSFORM_HIT - 1, 1},',
	'    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_SMELLINGSALTS, POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_SMELLING_SALTS_HIT - 1, 1},',
	'    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_BELLYDRUM, POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_BELLY_DRUM_HIT - 1, 1},',
	'    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_BEATUP, POKEMON_HANDLER_EVENT_MODIFY_MOVE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_BEAT_UP_MODIFY_MOVE - 1, 1},',
	'    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_BEATUP, POKEMON_HANDLER_EVENT_BASE_POWER, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_BEAT_UP_BASE_POWER - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_BEATUP, POKEMON_HANDLER_EVENT_MODIFY_SPA, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_BEAT_UP_MODIFY_SPA - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_BEATUP, POKEMON_HANDLER_EVENT_MODIFY_SPD, POKEMON_HANDLER_SCOPE_FOE, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_BEAT_UP_MODIFY_SPD - 1, 1},',
	'    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_PAINSPLIT, POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_PAIN_SPLIT_HIT - 1, 1},',
    '    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_PRESSURE, POKEMON_HANDLER_EVENT_DEDUCT_PP, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_PRESSURE_DEDUCT_PP - 1, 1},',
    '    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_PRESSURE, POKEMON_HANDLER_EVENT_START, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_PRESSURE_START - 1, 1},',
    '    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_DAMP, POKEMON_HANDLER_EVENT_TRY_MOVE, POKEMON_HANDLER_SCOPE_ANY, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_DAMP_TRY_MOVE - 1, 1},',
    '    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_FLAMEBODY, POKEMON_HANDLER_EVENT_DAMAGING_HIT, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_FLAME_BODY_DAMAGING_HIT - 1, 1},',
    '    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_STATIC, POKEMON_HANDLER_EVENT_DAMAGING_HIT, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_STATIC_DAMAGING_HIT - 1, 1},',
    '    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_POISONPOINT, POKEMON_HANDLER_EVENT_DAMAGING_HIT, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_POISON_POINT_DAMAGING_HIT - 1, 1},',
    '    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_EFFECTSPORE, POKEMON_HANDLER_EVENT_DAMAGING_HIT, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_EFFECT_SPORE_DAMAGING_HIT - 1, 1},',
    '    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_ROUGHSKIN, POKEMON_HANDLER_EVENT_DAMAGING_HIT, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_ROUGH_SKIN_DAMAGING_HIT - 1, 1},',
    '    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_ARENATRAP, POKEMON_HANDLER_EVENT_TRAP_POKEMON, POKEMON_HANDLER_SCOPE_FOE, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_ARENA_TRAP_TRAP_POKEMON - 1, 1},',
    '    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_MAGNETPULL, POKEMON_HANDLER_EVENT_TRAP_POKEMON, POKEMON_HANDLER_SCOPE_ANY, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_MAGNET_PULL_TRAP_POKEMON - 1, 1},',
    '    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_FLY, POKEMON_HANDLER_EVENT_TRY_MOVE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_FLY_TRY_MOVE - 1, 1},',
    '    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_FLY, POKEMON_HANDLER_EVENT_INVULNERABILITY, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_FLY_INVULNERABILITY - 1, 1},',
    '    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_HAZE, POKEMON_HANDLER_EVENT_MOVE_HIT_FIELD_CALLBACK, POKEMON_HANDLER_SCOPE_FIELD, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_HAZE_HIT_FIELD - 1, 1},',
    '    {POKEMON_OWNER_STATUS, POKEMON_GEN3_CONDITION_STATUS_SLP, POKEMON_HANDLER_EVENT_START, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_SLEEP_START - 1, 1},',
    '    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_REST, POKEMON_HANDLER_EVENT_TRY, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_REST_TRY - 1, 1},',
    '    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_REST, POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_REST_HIT - 1, 1},',
    '    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_SYNCHRONIZE, POKEMON_HANDLER_EVENT_AFTER_SET_STATUS, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_SYNCHRONIZE_AFTER_SET_STATUS - 1, 1},',
    '    {POKEMON_OWNER_STATUS, POKEMON_GEN3_CONDITION_STATUS_SLP, POKEMON_HANDLER_EVENT_BEFORE_MOVE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_SLEEP_BEFORE_MOVE - 1, 1},',
    '    {POKEMON_OWNER_STATUS, POKEMON_GEN3_CONDITION_STATUS_PAR, POKEMON_HANDLER_EVENT_BEFORE_MOVE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_PARALYSIS_BEFORE_MOVE - 1, 1},',
    '    {POKEMON_OWNER_STATUS, POKEMON_GEN3_CONDITION_STATUS_PAR, POKEMON_HANDLER_EVENT_START, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_PARALYSIS_START - 1, 1},',
    '    {POKEMON_OWNER_ITEM, POKEMON_GEN3_ITEM_DEEPSEASCALE, POKEMON_HANDLER_EVENT_MODIFY_SPD, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_DEEP_SEA_SCALE_SPD - 1, 1},',
    '    {POKEMON_OWNER_ITEM, POKEMON_GEN3_ITEM_DEEPSEATOOTH, POKEMON_HANDLER_EVENT_MODIFY_SPA, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_DEEP_SEA_TOOTH_SPA - 1, 1},',
    '    {POKEMON_OWNER_ITEM, POKEMON_GEN3_ITEM_LIGHTBALL, POKEMON_HANDLER_EVENT_MODIFY_SPA, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_LIGHT_BALL_SPA - 1, 1},',
    '    {POKEMON_OWNER_ITEM, POKEMON_GEN3_ITEM_MACHOBRACE, POKEMON_HANDLER_EVENT_MODIFY_SPE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_MACHO_BRACE_SPEED - 1, 1},',
    '    {POKEMON_OWNER_ITEM, POKEMON_GEN3_ITEM_SOULDEW, POKEMON_HANDLER_EVENT_MODIFY_SPA, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_SOUL_DEW_SPA - 1, 1},',
    '    {POKEMON_OWNER_ITEM, POKEMON_GEN3_ITEM_SOULDEW, POKEMON_HANDLER_EVENT_MODIFY_SPD, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_SOUL_DEW_SPD - 1, 1},',
    '    {POKEMON_OWNER_STATUS, POKEMON_GEN3_CONDITION_STATUS_SLP, POKEMON_HANDLER_EVENT_SWITCH_IN, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_SLEEP_SWITCH_IN - 1, 1},',
    '    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_SNORE, POKEMON_HANDLER_EVENT_TRY, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_SNORE_TRY - 1, 1},',
    `    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_CLOUDNINE, POKEMON_HANDLER_EVENT_START, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${lifecycleHandlerOffset}, 1},`,
    `    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_CLOUDNINE, POKEMON_HANDLER_EVENT_END, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${lifecycleHandlerOffset + 1}, 1},`,
    `    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_SANDSTREAM, POKEMON_HANDLER_EVENT_START, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${lifecycleHandlerOffset + 2}, 1},`,
    ...FIXED_HEAL_BERRIES.flatMap(([id], index) => {
      const offset = berryHandlerOffset + index * 3;
      return [
        `    {POKEMON_OWNER_ITEM, POKEMON_GEN3_ITEM_${cName(id)}, POKEMON_HANDLER_EVENT_RESIDUAL, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${offset}, 1},`,
        `    {POKEMON_OWNER_ITEM, POKEMON_GEN3_ITEM_${cName(id)}, POKEMON_HANDLER_EVENT_TRY_EAT_ITEM, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${offset + 1}, 1},`,
        `    {POKEMON_OWNER_ITEM, POKEMON_GEN3_ITEM_${cName(id)}, POKEMON_HANDLER_EVENT_ITEM_EAT, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${offset + 2}, 1},`,
      ];
    }),
    ...FLAVOR_BERRIES.flatMap(([id], index) => {
      const offset = flavorHandlerOffset + index * 3;
      return [
        `    {POKEMON_OWNER_ITEM, POKEMON_GEN3_ITEM_${cName(id)}, POKEMON_HANDLER_EVENT_RESIDUAL, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${offset}, 1},`,
        `    {POKEMON_OWNER_ITEM, POKEMON_GEN3_ITEM_${cName(id)}, POKEMON_HANDLER_EVENT_TRY_EAT_ITEM, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${offset + 1}, 1},`,
        `    {POKEMON_OWNER_ITEM, POKEMON_GEN3_ITEM_${cName(id)}, POKEMON_HANDLER_EVENT_ITEM_EAT, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${offset + 2}, 1},`,
      ];
    }),
    ...PINCH_BOOST_BERRIES.flatMap(([id], index) => {
      const offset = pinchHandlerOffset + index * 2;
      return [
        `    {POKEMON_OWNER_ITEM, POKEMON_GEN3_ITEM_${cName(id)}, POKEMON_HANDLER_EVENT_RESIDUAL, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${offset}, 1},`,
        `    {POKEMON_OWNER_ITEM, POKEMON_GEN3_ITEM_${cName(id)}, POKEMON_HANDLER_EVENT_ITEM_EAT, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${offset + 1}, 1},`,
      ];
    }),
    ...VOLATILE_PINCH_BERRIES.flatMap(([id], index) => {
      const offset = volatilePinchHandlerOffset + index * 2;
      return [
        `    {POKEMON_OWNER_ITEM, POKEMON_GEN3_ITEM_${cName(id)}, POKEMON_HANDLER_EVENT_RESIDUAL, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${offset}, 1},`,
        `    {POKEMON_OWNER_ITEM, POKEMON_GEN3_ITEM_${cName(id)}, POKEMON_HANDLER_EVENT_ITEM_EAT, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${offset + 1}, 1},`,
      ];
    }),
    ...RANDOM_PINCH_BERRIES.flatMap(([id], index) => {
      const offset = randomPinchHandlerOffset + index * 2;
      return [
        `    {POKEMON_OWNER_ITEM, POKEMON_GEN3_ITEM_${cName(id)}, POKEMON_HANDLER_EVENT_RESIDUAL, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${offset}, 1},`,
        `    {POKEMON_OWNER_ITEM, POKEMON_GEN3_ITEM_${cName(id)}, POKEMON_HANDLER_EVENT_ITEM_EAT, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${offset + 1}, 1},`,
      ];
    }),
    ...STATUS_CURE_BERRIES.flatMap(([id], index) => {
      const offset = cureHandlerOffset + index * 2;
      return [
        `    {POKEMON_OWNER_ITEM, POKEMON_GEN3_ITEM_${cName(id)}, POKEMON_HANDLER_EVENT_UPDATE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${offset}, 1},`,
        `    {POKEMON_OWNER_ITEM, POKEMON_GEN3_ITEM_${cName(id)}, POKEMON_HANDLER_EVENT_ITEM_EAT, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${offset + 1}, 1},`,
      ];
    }),
    ...VOLATILE_CURE_BERRIES.flatMap(([id], index) => {
      const offset = volatileCureHandlerOffset + index * 2;
      return [
        `    {POKEMON_OWNER_ITEM, POKEMON_GEN3_ITEM_${cName(id)}, POKEMON_HANDLER_EVENT_UPDATE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${offset}, 1},`,
        `    {POKEMON_OWNER_ITEM, POKEMON_GEN3_ITEM_${cName(id)}, POKEMON_HANDLER_EVENT_ITEM_EAT, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${offset + 1}, 1},`,
      ];
    }),
    ...COMBINED_CURE_BERRIES.flatMap(([id], index) => {
      const offset = combinedCureHandlerOffset + index * 3;
      return [
        `    {POKEMON_OWNER_ITEM, POKEMON_GEN3_ITEM_${cName(id)}, POKEMON_HANDLER_EVENT_AFTER_SET_STATUS, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${offset}, 1},`,
        `    {POKEMON_OWNER_ITEM, POKEMON_GEN3_ITEM_${cName(id)}, POKEMON_HANDLER_EVENT_UPDATE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${offset + 1}, 1},`,
        `    {POKEMON_OWNER_ITEM, POKEMON_GEN3_ITEM_${cName(id)}, POKEMON_HANDLER_EVENT_ITEM_EAT, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${offset + 2}, 1},`,
      ];
    }),
    `    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_CONFUSION, POKEMON_HANDLER_EVENT_START, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${confusionHandlerOffset}, 1},`,
    `    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_CONFUSION, POKEMON_HANDLER_EVENT_BEFORE_MOVE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${confusionHandlerOffset + 1}, 1},`,
    `    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_CONFUSION, POKEMON_HANDLER_EVENT_END, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${confusionHandlerOffset + 2}, 1},`,
    `    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_OWNTEMPO, POKEMON_HANDLER_EVENT_TRY_ADD_VOLATILE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${confusionHandlerOffset + 3}, 1},`,
    `    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_OWNTEMPO, POKEMON_HANDLER_EVENT_HIT, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${confusionHandlerOffset + 4}, 1},`,
    `    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_OWNTEMPO, POKEMON_HANDLER_EVENT_UPDATE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${confusionHandlerOffset + 5}, 1},`,
    `    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_SHIELDDUST, POKEMON_HANDLER_EVENT_MODIFY_SECONDARIES, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${confusionHandlerOffset + 6}, 1},`,
    `    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_LOCKEDMOVE, POKEMON_HANDLER_EVENT_START, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${confusionHandlerOffset + 7}, 1},`,
    `    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_LOCKEDMOVE, POKEMON_HANDLER_EVENT_RESTART, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${confusionHandlerOffset + 8}, 1},`,
    `    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_LOCKEDMOVE, POKEMON_HANDLER_EVENT_RESIDUAL, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${confusionHandlerOffset + 9}, 1},`,
    `    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_LOCKEDMOVE, POKEMON_HANDLER_EVENT_END, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${confusionHandlerOffset + 10}, 1},`,
    `    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_LOCKEDMOVE, POKEMON_HANDLER_EVENT_LOCK_MOVE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${confusionHandlerOffset + 11}, 1},`,
    '    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_TWOTURNMOVE, POKEMON_HANDLER_EVENT_START, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_TWO_TURN_START - 1, 1},',
    '    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_TWOTURNMOVE, POKEMON_HANDLER_EVENT_RESIDUAL, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_TWO_TURN_RESIDUAL - 1, 1},',
    '    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_TWOTURNMOVE, POKEMON_HANDLER_EVENT_LOCK_MOVE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_TWO_TURN_LOCK_MOVE - 1, 1},',
    '    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_TWOTURNMOVE, POKEMON_HANDLER_EVENT_MOVE_ABORTED, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_TWO_TURN_MOVE_ABORTED - 1, 1},',
    '    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_TWOTURNMOVE, POKEMON_HANDLER_EVENT_END, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_TWO_TURN_END - 1, 1},',
    `    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_FLINCH, POKEMON_HANDLER_EVENT_BEFORE_MOVE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${flinchHandlerOffset}, 1},`,
    `    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_INNERFOCUS, POKEMON_HANDLER_EVENT_TRY_ADD_VOLATILE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${flinchHandlerOffset + 1}, 1},`,
    `    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_FOCUSENERGY, POKEMON_HANDLER_EVENT_START, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${criticalHandlerOffset}, 1},`,
    `    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_FOCUSENERGY, POKEMON_HANDLER_EVENT_MODIFY_CRIT_RATIO, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${criticalHandlerOffset + 1}, 1},`,
    `    {POKEMON_OWNER_ITEM, POKEMON_GEN3_ITEM_SCOPELENS, POKEMON_HANDLER_EVENT_MODIFY_CRIT_RATIO, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${criticalHandlerOffset + 2}, 1},`,
    `    {POKEMON_OWNER_ITEM, POKEMON_GEN3_ITEM_LUCKYPUNCH, POKEMON_HANDLER_EVENT_MODIFY_CRIT_RATIO, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${criticalHandlerOffset + 3}, 1},`,
    `    {POKEMON_OWNER_ITEM, POKEMON_GEN3_ITEM_STICK, POKEMON_HANDLER_EVENT_MODIFY_CRIT_RATIO, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${criticalHandlerOffset + 4}, 1},`,
    `    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_BATTLEARMOR, POKEMON_HANDLER_EVENT_CRITICAL_HIT, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${criticalHandlerOffset + 5}, 1},`,
    `    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_SHELLARMOR, POKEMON_HANDLER_EVENT_CRITICAL_HIT, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${criticalHandlerOffset + 6}, 1},`,
    `    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_PARTIALLYTRAPPED, POKEMON_HANDLER_EVENT_TRAP_POKEMON, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${criticalHandlerOffset + 7}, 1},`,
    `    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_PARTIALLYTRAPPED, POKEMON_HANDLER_EVENT_RESIDUAL, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${criticalHandlerOffset + 8}, 1},`,
    `    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_TAUNT, POKEMON_HANDLER_EVENT_START, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${tauntHandlerOffset}, 1},`,
    `    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_TAUNT, POKEMON_HANDLER_EVENT_END, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${tauntHandlerOffset + 1}, 1},`,
    `    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_TORMENT, POKEMON_HANDLER_EVENT_START, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${tormentHandlerOffset}, 1},`,
    `    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_TORMENT, POKEMON_HANDLER_EVENT_END, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${tormentHandlerOffset + 1}, 1},`,
    `    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_DISABLE, POKEMON_HANDLER_EVENT_END, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${disableHandlerOffset}, 1},`,
    `    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_ENCORE, POKEMON_HANDLER_EVENT_END, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${encoreHandlerOffset}, 1},`,
    `    {POKEMON_OWNER_SIDE, POKEMON_GEN3_CONDITION_SIDE_MIST, POKEMON_HANDLER_EVENT_TRY_BOOST, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${mistHandlerOffset}, 1},`,
    `    {POKEMON_OWNER_SIDE, POKEMON_GEN3_CONDITION_SIDE_SAFEGUARD, POKEMON_HANDLER_EVENT_SET_STATUS, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${safeguardHandlerOffset}, 1},`,
    `    {POKEMON_OWNER_SIDE, POKEMON_GEN3_CONDITION_SIDE_SAFEGUARD, POKEMON_HANDLER_EVENT_TRY_ADD_VOLATILE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${safeguardHandlerOffset + 1}, 1},`,
    ...STARTER_ABILITY_HANDLERS.map(([id], index) =>
      `    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_${cName(id)}, POKEMON_HANDLER_EVENT_BASE_POWER, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${starterAbilityHandlerOffset + index}, 1},`),
    `    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_INSOMNIA, POKEMON_HANDLER_EVENT_TRY_ADD_VOLATILE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${yawnHandlerOffset}, 1},`,
    `    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_VITALSPIRIT, POKEMON_HANDLER_EVENT_TRY_ADD_VOLATILE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${yawnHandlerOffset + 1}, 1},`,
    `    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_YAWN, POKEMON_HANDLER_EVENT_START, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${yawnHandlerOffset + 3}, 1},`,
    `    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_YAWN, POKEMON_HANDLER_EVENT_END, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${yawnHandlerOffset + 4}, 1},`,
    ...STATUS_ABILITY_UPDATE_HANDLERS.map(([abilityID], index) =>
      `    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_${cName(abilityID)}, POKEMON_HANDLER_EVENT_UPDATE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${yawnHandlerOffset + 5 + index}, 1},`),
    `    {POKEMON_OWNER_SIDE, POKEMON_GEN3_CONDITION_SIDE_SPIKES, POKEMON_HANDLER_EVENT_START, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${spikesHandlerOffset}, 1},`,
    `    {POKEMON_OWNER_SIDE, POKEMON_GEN3_CONDITION_SIDE_SPIKES, POKEMON_HANDLER_EVENT_RESTART, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${spikesHandlerOffset + 1}, 1},`,
    `    {POKEMON_OWNER_SIDE, POKEMON_GEN3_CONDITION_SIDE_SPIKES, POKEMON_HANDLER_EVENT_ENTRY_HAZARD, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, ${spikesHandlerOffset + 2}, 1},`,
    `    {POKEMON_OWNER_SIDE, POKEMON_GEN3_CONDITION_SIDE_REFLECT, POKEMON_HANDLER_EVENT_MODIFY_DAMAGE_PHASE1, POKEMON_HANDLER_SCOPE_ANY, POKEMON_HANDLER_ROUTE_OWNER, ${screenHandlerOffset}, 1},`,
    `    {POKEMON_OWNER_SIDE, POKEMON_GEN3_CONDITION_SIDE_LIGHTSCREEN, POKEMON_HANDLER_EVENT_MODIFY_DAMAGE_PHASE1, POKEMON_HANDLER_SCOPE_ANY, POKEMON_HANDLER_ROUTE_OWNER, ${screenHandlerOffset + 1}, 1},`,
    '    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_MAGICCOAT, POKEMON_HANDLER_EVENT_TRY_HIT, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 9, 1},',
    '    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_PROTECT, POKEMON_HANDLER_EVENT_TRY_HIT, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 8, 1},',
    '    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_SUBSTITUTE, POKEMON_HANDLER_EVENT_TRY_PRIMARY_HIT, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, 10, 1},',
    '    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_SNATCH, POKEMON_HANDLER_EVENT_PREPARE_HIT, POKEMON_HANDLER_SCOPE_ANY, POKEMON_HANDLER_ROUTE_OWNER, 11, 1},',
    '    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_MUDSPORT, POKEMON_HANDLER_EVENT_BASE_POWER, POKEMON_HANDLER_SCOPE_ANY, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_MUD_SPORT_ANY_BASE_POWER - 1, 1},',
    '    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_WATERSPORT, POKEMON_HANDLER_EVENT_BASE_POWER, POKEMON_HANDLER_SCOPE_ANY, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_WATER_SPORT_ANY_BASE_POWER - 1, 1},',
    '    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_ENDURE, POKEMON_HANDLER_EVENT_DAMAGE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_ENDURE_DAMAGE - 1, 1},',
    '    {POKEMON_OWNER_ITEM, POKEMON_GEN3_ITEM_WHITEHERB, POKEMON_HANDLER_EVENT_START, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_WHITE_HERB_START - 1, 1},',
    '    {POKEMON_OWNER_ITEM, POKEMON_GEN3_ITEM_WHITEHERB, POKEMON_HANDLER_EVENT_SWITCH_IN, POKEMON_HANDLER_SCOPE_ANY, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_WHITE_HERB_ANY_SWITCH_IN - 1, 1},',
    '    {POKEMON_OWNER_ITEM, POKEMON_GEN3_ITEM_WHITEHERB, POKEMON_HANDLER_EVENT_AFTER_MOVE, POKEMON_HANDLER_SCOPE_ANY, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_WHITE_HERB_ANY_AFTER_MOVE - 1, 1},',
    '    {POKEMON_OWNER_ITEM, POKEMON_GEN3_ITEM_WHITEHERB, POKEMON_HANDLER_EVENT_RESIDUAL, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_WHITE_HERB_RESIDUAL - 1, 1},',
    '    {POKEMON_OWNER_ITEM, POKEMON_GEN3_ITEM_MENTALHERB, POKEMON_HANDLER_EVENT_UPDATE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_MENTAL_HERB_UPDATE - 1, 1},',
    '    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_FALSESWIPE, POKEMON_HANDLER_EVENT_DAMAGE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_SOURCE_EFFECT, POKEMON_GEN3_HANDLER_FALSE_SWIPE_DAMAGE - 1, 1},',
    '    {POKEMON_OWNER_ITEM, POKEMON_GEN3_ITEM_CHOICEBAND, POKEMON_HANDLER_EVENT_MODIFY_ATK, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_CHOICE_BAND_MODIFY_ATK - 1, 1},',
    '    {POKEMON_OWNER_ITEM, POKEMON_GEN3_ITEM_CHOICEBAND, POKEMON_HANDLER_EVENT_AFTER_MOVE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_CHOICE_BAND_AFTER_MOVE - 1, 1},',
	'    {POKEMON_OWNER_ITEM, POKEMON_GEN3_ITEM_METALPOWDER, POKEMON_HANDLER_EVENT_MODIFY_DEF, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_METAL_POWDER_MODIFY_DEF - 1, 1},',
	'    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_BOUNCE, POKEMON_HANDLER_EVENT_TRY_MOVE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_BOUNCE_TRY_MOVE - 1, 1},',
	'    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_DIG, POKEMON_HANDLER_EVENT_TRY_MOVE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_DIG_TRY_MOVE - 1, 1},',
	'    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_DIVE, POKEMON_HANDLER_EVENT_TRY_MOVE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_DIVE_TRY_MOVE - 1, 1},',
	'    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_RAZORWIND, POKEMON_HANDLER_EVENT_TRY_MOVE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_RAZOR_WIND_TRY_MOVE - 1, 1},',
	'    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_SKULLBASH, POKEMON_HANDLER_EVENT_TRY_MOVE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_SKULL_BASH_TRY_MOVE - 1, 1},',
	'    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_SKYATTACK, POKEMON_HANDLER_EVENT_TRY_MOVE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_SKY_ATTACK_TRY_MOVE - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_BOUNCE, POKEMON_HANDLER_EVENT_INVULNERABILITY, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_BOUNCE_INVULNERABILITY - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_BOUNCE, POKEMON_HANDLER_EVENT_BASE_POWER, POKEMON_HANDLER_SCOPE_FOE, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_BOUNCE_SOURCE_BASE_POWER - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_DIG, POKEMON_HANDLER_EVENT_INVULNERABILITY, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_DIG_INVULNERABILITY - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_DIG, POKEMON_HANDLER_EVENT_MODIFY_DAMAGE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_DIG_SOURCE_MODIFY_DAMAGE - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_DIVE, POKEMON_HANDLER_EVENT_INVULNERABILITY, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_DIVE_INVULNERABILITY - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_DIVE, POKEMON_HANDLER_EVENT_MODIFY_DAMAGE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_DIVE_SOURCE_MODIFY_DAMAGE - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_DIG, POKEMON_HANDLER_EVENT_IMMUNITY, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_DIG_IMMUNITY - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_DIVE, POKEMON_HANDLER_EVENT_IMMUNITY, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_DIVE_IMMUNITY - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_FLY, POKEMON_HANDLER_EVENT_MODIFY_DAMAGE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_FLY_SOURCE_MODIFY_DAMAGE - 1, 1},',
	'    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_LOCKON, POKEMON_HANDLER_EVENT_TRY_HIT, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_LOCK_ON_TRY_HIT - 1, 1},',
	'    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_MINDREADER, POKEMON_HANDLER_EVENT_TRY_HIT, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_MIND_READER_TRY_HIT - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_LOCKON, POKEMON_HANDLER_EVENT_ACCURACY, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_LOCK_ON_ACCURACY - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_LOCKON, POKEMON_HANDLER_EVENT_INVULNERABILITY, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_LOCK_ON_INVULNERABILITY - 1, 1},',
	'    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_WONDERGUARD, POKEMON_HANDLER_EVENT_TRY_HIT, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_WONDER_GUARD_TRY_HIT - 1, 1},',
	'    {POKEMON_OWNER_ITEM, POKEMON_GEN3_ITEM_FOCUSBAND, POKEMON_HANDLER_EVENT_DAMAGE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_FOCUS_BAND_DAMAGE - 1, 1},',
	'    {POKEMON_OWNER_STATUS, POKEMON_GEN3_CONDITION_STATUS_BRN, POKEMON_HANDLER_EVENT_START, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_BURN_START - 1, 1},',
	'    {POKEMON_OWNER_STATUS, POKEMON_GEN3_CONDITION_STATUS_PSN, POKEMON_HANDLER_EVENT_START, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_POISON_START - 1, 1},',
	'    {POKEMON_OWNER_STATUS, POKEMON_GEN3_CONDITION_STATUS_TOX, POKEMON_HANDLER_EVENT_START, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_TOXIC_START - 1, 1},',
	'    {POKEMON_OWNER_STATUS, POKEMON_GEN3_CONDITION_STATUS_TOX, POKEMON_HANDLER_EVENT_SWITCH_IN, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_TOXIC_SWITCH_IN - 1, 1},',
	'    {POKEMON_OWNER_ITEM, POKEMON_GEN3_ITEM_LEPPABERRY, POKEMON_HANDLER_EVENT_UPDATE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_LEPPA_BERRY_UPDATE - 1, 1},',
	'    {POKEMON_OWNER_ITEM, POKEMON_GEN3_ITEM_LEPPABERRY, POKEMON_HANDLER_EVENT_ITEM_EAT, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_LEPPA_BERRY_EAT - 1, 1},',
	'    {POKEMON_OWNER_ITEM, POKEMON_GEN3_ITEM_KINGSROCK, POKEMON_HANDLER_EVENT_MODIFY_MOVE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_KINGS_ROCK_MODIFY_MOVE - 1, 1},',
	'    {POKEMON_OWNER_ITEM, POKEMON_GEN3_ITEM_SHELLBELL, POKEMON_HANDLER_EVENT_AFTER_MOVE_SECONDARY_SELF, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_SHELL_BELL_AFTER_MOVE_SECONDARY_SELF - 1, 1},',
	'    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_FAKEOUT, POKEMON_HANDLER_EVENT_TRY, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_FAKE_OUT_TRY - 1, 1},',
	'    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_FOLLOWME, POKEMON_HANDLER_EVENT_TRY, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_FOLLOW_ME_TRY - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_COUNTER, POKEMON_HANDLER_EVENT_START, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_COUNTER_START - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_COUNTER, POKEMON_HANDLER_EVENT_DAMAGE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_COUNTER_DAMAGE - 1, 1},',
	'    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_COUNTER, POKEMON_HANDLER_EVENT_TRY, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_COUNTER_TRY - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_MIRRORCOAT, POKEMON_HANDLER_EVENT_START, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_MIRROR_COAT_START - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_MIRRORCOAT, POKEMON_HANDLER_EVENT_DAMAGE, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_MIRROR_COAT_DAMAGE - 1, 1},',
	'    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_MIRRORCOAT, POKEMON_HANDLER_EVENT_TRY, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_MIRROR_COAT_TRY - 1, 1},',
	'    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_HIDDENPOWER, POKEMON_HANDLER_EVENT_MODIFY_MOVE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_HIDDEN_POWER_MODIFY_MOVE - 1, 1},',
	'    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_SUCTIONCUPS, POKEMON_HANDLER_EVENT_DRAG_OUT, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_SUCTION_CUPS_DRAG_OUT - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_INGRAIN, POKEMON_HANDLER_EVENT_START, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_INGRAIN_START - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_INGRAIN, POKEMON_HANDLER_EVENT_RESIDUAL, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_INGRAIN_RESIDUAL - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_INGRAIN, POKEMON_HANDLER_EVENT_TRAP_POKEMON, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_INGRAIN_TRAP_POKEMON - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_INGRAIN, POKEMON_HANDLER_EVENT_DRAG_OUT, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_INGRAIN_DRAG_OUT - 1, 1},',
	'    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_PURSUIT, POKEMON_HANDLER_EVENT_MODIFY_MOVE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_PURSUIT_MODIFY_MOVE - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_PURSUIT, POKEMON_HANDLER_EVENT_BEFORE_SWITCH_OUT, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_PURSUIT_BEFORE_SWITCH_OUT - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_CHARGE, POKEMON_HANDLER_EVENT_START, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_CHARGE_START - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_CHARGE, POKEMON_HANDLER_EVENT_RESTART, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_CHARGE_RESTART - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_CHARGE, POKEMON_HANDLER_EVENT_BASE_POWER, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_CHARGE_BASE_POWER - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_CHARGE, POKEMON_HANDLER_EVENT_MOVE_ABORTED, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_CHARGE_MOVE_ABORTED - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_CHARGE, POKEMON_HANDLER_EVENT_AFTER_MOVE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_CHARGE_AFTER_MOVE - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_CHARGE, POKEMON_HANDLER_EVENT_END, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_CHARGE_END - 1, 1},',
	'    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_LEECHSEED, POKEMON_HANDLER_EVENT_TRY_IMMUNITY, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_LEECH_SEED_TRY_IMMUNITY - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_LEECHSEED, POKEMON_HANDLER_EVENT_START, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_LEECH_SEED_START - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_LEECHSEED, POKEMON_HANDLER_EVENT_RESIDUAL, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_LEECH_SEED_RESIDUAL - 1, 1},',
	'    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_LIQUIDOOZE, POKEMON_HANDLER_EVENT_TRY_HEAL, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_LIQUID_OOZE_SOURCE_TRY_HEAL - 1, 1},',
	'    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_RAPIDSPIN, POKEMON_HANDLER_EVENT_AFTER_SUB_DAMAGE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_RAPID_SPIN_AFTER_SUB_DAMAGE - 1, 1},',
	'    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_FLASHFIRE, POKEMON_HANDLER_EVENT_TRY_HIT, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_FLASH_FIRE_TRY_HIT - 1, 1},',
	'    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_FLASHFIRE, POKEMON_HANDLER_EVENT_END, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_FLASH_FIRE_ABILITY_END - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_FLASHFIRE, POKEMON_HANDLER_EVENT_START, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_FLASH_FIRE_CONDITION_START - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_FLASHFIRE, POKEMON_HANDLER_EVENT_MODIFY_DAMAGE_PHASE1, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_FLASH_FIRE_MODIFY_DAMAGE_PHASE1 - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_FLASHFIRE, POKEMON_HANDLER_EVENT_END, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_FLASH_FIRE_CONDITION_END - 1, 1},',
	'    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_TELEPORT, POKEMON_HANDLER_EVENT_TRY, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_TELEPORT_TRY - 1, 1},',
	'    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_MINUS, POKEMON_HANDLER_EVENT_MODIFY_SPA, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_MINUS_MODIFY_SPA - 1, 1},',
	'    {POKEMON_OWNER_ABILITY, POKEMON_GEN3_ABILITY_PLUS, POKEMON_HANDLER_EVENT_MODIFY_SPA, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_PLUS_MODIFY_SPA - 1, 1},',
	'    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_CURSE, POKEMON_HANDLER_EVENT_MODIFY_MOVE, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_CURSE_MODIFY_MOVE - 1, 1},',
	'    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_CURSE, POKEMON_HANDLER_EVENT_TRY_HIT, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_CURSE_TRY_HIT - 1, 1},',
	'    {POKEMON_OWNER_MOVE, POKEMON_GEN3_MOVE_CURSE, POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK, POKEMON_HANDLER_SCOPE_SOURCE, POKEMON_HANDLER_ROUTE_MOVE_SELF, POKEMON_GEN3_HANDLER_CURSE_HIT - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_CURSE, POKEMON_HANDLER_EVENT_START, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_CURSE_START - 1, 1},',
	'    {POKEMON_OWNER_VOLATILE, POKEMON_GEN3_CONDITION_VOLATILE_CURSE, POKEMON_HANDLER_EVENT_RESIDUAL, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_HANDLER_ROUTE_OWNER, POKEMON_GEN3_HANDLER_CURSE_RESIDUAL - 1, 1},',
    '};', '', 'static const PokemonHandlerOp HANDLER_PROGRAMS[] = {',
    ...baseHandlerPrograms,
    ...TYPE_BOOST_ITEMS.slice(1).flatMap(([, , type, modifierQ12]) => [
      `    {POKEMON_HANDLER_OP_GUARD_MOVE_TYPE, POKEMON_GEN3_TYPE_${cName(type)}},`,
      `    {POKEMON_HANDLER_OP_CHAIN_Q12, ${modifierQ12}},`,
    ]),
    '    {POKEMON_HANDLER_OP_CHAIN_Q12_IF_MOVE_TYPE, (POKEMON_GEN3_TYPE_WATER << 24) | 6144},',
    '    {POKEMON_HANDLER_OP_CHAIN_Q12_IF_MOVE_TYPE, (POKEMON_GEN3_TYPE_FIRE << 24) | 2048},',
    '    {POKEMON_HANDLER_OP_CHAIN_Q12_IF_MOVE_TYPE, (POKEMON_GEN3_TYPE_FIRE << 24) | 6144},',
    '    {POKEMON_HANDLER_OP_CHAIN_Q12_IF_MOVE_TYPE, (POKEMON_GEN3_TYPE_WATER << 24) | 2048},',
    '    {POKEMON_HANDLER_OP_GUARD_EFFECTIVE_WEATHER, POKEMON_WEATHER_SUN},',
    '    {POKEMON_HANDLER_OP_CHAIN_Q12, 8192},',
    '    {POKEMON_HANDLER_OP_GUARD_EFFECTIVE_WEATHER, POKEMON_WEATHER_RAIN},',
    '    {POKEMON_HANDLER_OP_CHAIN_Q12, 8192},',
    '    {POKEMON_HANDLER_OP_CHAIN_Q12, 1024},',
    '    {POKEMON_HANDLER_OP_GUARD_EFFECTIVE_WEATHER, POKEMON_WEATHER_RAIN},',
    '    {POKEMON_HANDLER_OP_HEAL_MAX_HP_FRACTION, 16},',
    '    {POKEMON_HANDLER_OP_SET_OWNER_ENDING, 0},',
    '    {POKEMON_HANDLER_OP_SET_OWNER_ENDING, 1},',
    '    {POKEMON_HANDLER_OP_EACH_EVENT, POKEMON_HANDLER_EVENT_WEATHER_CHANGE},',
    '    {POKEMON_HANDLER_OP_SET_WEATHER, POKEMON_WEATHER_SANDSTORM},',
    ...FIXED_HEAL_BERRIES.flatMap(() => [
      '    {POKEMON_HANDLER_OP_EAT_FIXED_HEAL_BERRY, 0},',
      '    {POKEMON_HANDLER_OP_TRY_HEAL_BERRY_GATE, 0},',
      '    {POKEMON_HANDLER_OP_HEAL_FIXED_BERRY, 0},',
    ]),
    ...FLAVOR_BERRIES.flatMap(() => [
      '    {POKEMON_HANDLER_OP_EAT_FIXED_HEAL_BERRY, 0},',
      '    {POKEMON_HANDLER_OP_TRY_HEAL_BERRY_GATE, 0},',
      '    {POKEMON_HANDLER_OP_HEAL_FRACTION_BERRY, 0},',
      '    {POKEMON_HANDLER_OP_CONFUSE_DISLIKED_FLAVOR, 0},',
    ]),
    ...PINCH_BOOST_BERRIES.flatMap(() => [
      '    {POKEMON_HANDLER_OP_EAT_PINCH_BOOST_BERRY, 0},',
      '    {POKEMON_HANDLER_OP_BOOST_PINCH_BERRY, 0},',
    ]),
    ...VOLATILE_PINCH_BERRIES.flatMap(([, volatile]) => [
      '    {POKEMON_HANDLER_OP_EAT_PINCH_BOOST_BERRY, 0},',
      `    {POKEMON_HANDLER_OP_TRY_ADD_OR_RESTART_HOLDER_VOLATILE, POKEMON_VOLATILE_${volatile}},`,
    ]),
    ...RANDOM_PINCH_BERRIES.flatMap(() => [
      '    {POKEMON_HANDLER_OP_EAT_PINCH_BOOST_BERRY, 0},',
      '    {POKEMON_HANDLER_OP_BOOST_RANDOM_ELIGIBLE_HOLDER_STAT, 0},',
    ]),
    ...STATUS_CURE_BERRIES.flatMap(() => [
      '    {POKEMON_HANDLER_OP_EAT_STATUS_CURE_BERRY, 0},',
      '    {POKEMON_HANDLER_OP_CURE_STATUS_BERRY, 0},',
    ]),
    ...VOLATILE_CURE_BERRIES.flatMap(() => [
      '    {POKEMON_HANDLER_OP_EAT_VOLATILE_CURE_BERRY, 0},',
      '    {POKEMON_HANDLER_OP_CURE_VOLATILE_BERRY, 0},',
    ]),
    ...COMBINED_CURE_BERRIES.flatMap(() => [
      '    {POKEMON_HANDLER_OP_EAT_HELD_BERRY, 0},',
      '    {POKEMON_HANDLER_OP_EAT_CONDITION_CURE_BERRY, 0},',
      '    {POKEMON_HANDLER_OP_CURE_STATUS_BERRY, 0},',
      '    {POKEMON_HANDLER_OP_CURE_VOLATILE_BERRY, 0},',
    ]),
    '};', '', 'static const PokemonEventSpec EVENT_SPECS[] = {');
  const algebraNames = {
    'numeric-or-cancel-relay': 'POKEMON_EVENT_ALGEBRA_NUMERIC_OR_CANCEL',
    'mutable-value-relay': 'POKEMON_EVENT_ALGEBRA_MUTABLE_VALUE',
    'mutable-boost-table-relay': 'POKEMON_EVENT_ALGEBRA_MUTABLE_BOOST_TABLE',
    'boolean-or-null-gate': 'POKEMON_EVENT_ALGEBRA_BOOLEAN_OR_NULL',
    'target-redirect-relay': 'POKEMON_EVENT_ALGEBRA_TARGET_REDIRECT',
    'selector-or-replacement-relay': 'POKEMON_EVENT_ALGEBRA_SELECTOR_REPLACEMENT',
    'state-mutation-notification': 'POKEMON_EVENT_ALGEBRA_STATE_NOTIFICATION',
    'void-notification': 'POKEMON_EVENT_ALGEBRA_VOID_NOTIFICATION',
  };
  for (const [index, event] of eventVocabulary.events.entries()) {
    if (event.event === 'CriticalHit') continue;
    const ordering = ['Invulnerability', 'TryHit', 'DamagingHit', 'EntryHazard'].includes(event.event) ?
      'POKEMON_EVENT_ORDER_LEFT_TO_RIGHT' : event.event === 'RedirectTarget' ?
        'POKEMON_EVENT_ORDER_REDIRECT' : 'POKEMON_EVENT_ORDER_ORDINARY';
    const supported = ['Accuracy', 'AfterMove', 'AfterMoveSecondarySelf', 'AfterSetStatus', 'AfterSubDamage', 'BasePower', 'BeforeMove', 'BeforeSwitchOut', 'ChangeBoost', 'Damage', 'DeductPP', 'DisableMove', 'Hit', 'LockMove', 'MoveAborted', 'ModifyAtk', 'ModifyBoost', 'ModifyCritRatio', 'ModifyDef', 'ModifyMove', 'ModifySpA', 'ModifySpD', 'ModifySpe', 'ModifyType', 'ModifySecondaries', 'OverrideAction',
      'PrepareHit', 'TryBoost', 'TryHit', 'TryPrimaryHit', 'DamagingHit', 'Residual', 'ModifyAccuracy', 'Invulnerability', 'Immunity', 'NegateImmunity', 'MoveFail',
      'DragOut', 'EntryHazard', 'Faint', 'ModifyDamage', 'ModifyDamagePhase1', 'Restart', 'SetStatus', 'SwitchIn', 'SwitchOut', 'TrapPokemon', 'Try', 'TryAddVolatile', 'TryImmunity', 'TryMove', 'UseMoveMessage', 'Update', 'WeatherModifyDamage', 'TryHeal', 'TryEatItem', 'Start', 'End', 'WeatherChange'].includes(event.event) ? 1 : 0;
    const algebra = event.event === 'ModifyBoost' ?
      'POKEMON_EVENT_ALGEBRA_MUTABLE_BOOST_TABLE' :
      event.event === 'ModifyAccuracy' ?
      'POKEMON_EVENT_ALGEBRA_NUMERIC_OR_CANCEL' :
      (event.event === 'Accuracy' || event.event === 'Invulnerability') ?
        'POKEMON_EVENT_ALGEBRA_BOOLEAN_OR_NUMBER' : algebraNames[event.algebra];
    lines.push(`    {${index + 1}, ${cString(event.event)}, ${algebra}, ` +
      `${ordering}, ${event.frozen_handler_count}, ${supported}},`);
  }
  lines.push('    {POKEMON_HANDLER_EVENT_ITEM_EAT, "ItemEat", POKEMON_EVENT_ALGEBRA_VOID_NOTIFICATION, POKEMON_EVENT_ORDER_ORDINARY, 2, 1},');
  lines.push('    {POKEMON_HANDLER_EVENT_CRITICAL_HIT, "CriticalHit", POKEMON_EVENT_ALGEBRA_BOOLEAN_OR_NULL, POKEMON_EVENT_ORDER_ORDINARY, 2, 1},');
  lines.push('    {POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK, "MoveHitCallback", POKEMON_EVENT_ALGEBRA_BOOLEAN_OR_NULL, POKEMON_EVENT_ORDER_ORDINARY, 1, 1},');
  lines.push('    {POKEMON_HANDLER_EVENT_MOVE_HIT_FIELD_CALLBACK, "MoveHitFieldCallback", POKEMON_EVENT_ALGEBRA_BOOLEAN_OR_NULL, POKEMON_EVENT_ORDER_ORDINARY, 1, 1},');
  lines.push('    {POKEMON_HANDLER_EVENT_SET_ABILITY, "SetAbility", POKEMON_EVENT_ALGEBRA_BOOLEAN_OR_NULL, POKEMON_EVENT_ORDER_ORDINARY, 0, 1},');
  const sereneGrace = dex.abilities.get('serenegrace');
  const sereneGraceSource = String(sereneGrace.onModifyMove);
  if (typeof sereneGrace.onModifyMove !== 'function' ||
      !sereneGraceSource.includes('secondary.chance *= 2')) {
    throw new Error('resolved Gen 3 Serene Grace secondary policy changed');
  }
  lines.push('};', '', 'static const PokemonAbilityData ABILITIES[] = {');
  for (const id of ABILITIES) {
    if (id === 'rockhead') {
      lines.push('    {POKEMON_GEN3_ABILITY_ROCKHEAD, 3, 1, 0, 0, 0, 0, 0, 0},');
    } else if (id === 'levitate') {
      lines.push('    {POKEMON_GEN3_ABILITY_LEVITATE, 0, 0, 1, POKEMON_GEN3_TYPE_GROUND, 0, 0, 0, 0},');
    } else if (id === 'waterabsorb') {
      lines.push('    {POKEMON_GEN3_ABILITY_WATERABSORB, 0, 1, 0, 0, 0, 0, 0, 0},');
    } else if (id === 'voltabsorb') {
      lines.push('    {POKEMON_GEN3_ABILITY_VOLTABSORB, POKEMON_GEN3_HANDLER_VOLT_ABSORB - 1, 1, 0, 0, 0, 0, 0, 0},');
    } else if (id === 'thickfat') {
      lines.push('    {POKEMON_GEN3_ABILITY_THICKFAT, POKEMON_GEN3_HANDLER_THICK_FAT - 1, 1, 0, 0, 0, 0, 0, 0},');
    } else if (id === 'marvelscale') {
      lines.push('    {POKEMON_GEN3_ABILITY_MARVELSCALE, POKEMON_GEN3_HANDLER_MARVEL_SCALE - 1, 1, 0, 0, 0, 0, 0, 0},');
    } else if (id === 'guts') {
      lines.push('    {POKEMON_GEN3_ABILITY_GUTS, 1, 1, 0, 0, 1, 0, 0, 0},');
    } else if (id === 'naturalcure') {
      lines.push('    {POKEMON_GEN3_ABILITY_NATURALCURE, POKEMON_GEN3_HANDLER_NATURAL_CURE_SWITCH_OUT - 1, 1, 0, 0, 0, 0, 0, 0},');
    } else if (id === 'shedskin') {
      lines.push('    {POKEMON_GEN3_ABILITY_SHEDSKIN, POKEMON_GEN3_HANDLER_SHED_SKIN_RESIDUAL - 1, 1, 0, 0, 0, 0, 0, 0},');
    } else if (id === 'speedboost') {
      lines.push('    {POKEMON_GEN3_ABILITY_SPEEDBOOST, POKEMON_GEN3_HANDLER_SPEED_BOOST_RESIDUAL - 1, 1, 0, 0, 0, 0, 0, 0},');
    } else if (id === 'truant') {
      lines.push('    {POKEMON_GEN3_ABILITY_TRUANT, POKEMON_GEN3_HANDLER_TRUANT_SWITCH_IN - 1, 3, 0, 0, 0, 0, 0, 0},');
    } else if (id === 'forecast') {
      lines.push('    {POKEMON_GEN3_ABILITY_FORECAST, POKEMON_GEN3_HANDLER_FORECAST_START - 1, 2, 0, 0, 0, 0, 0, 0},');
    } else if (id === 'intimidate') {
      lines.push('    {POKEMON_GEN3_ABILITY_INTIMIDATE, POKEMON_GEN3_HANDLER_INTIMIDATE_START - 1, 1, 0, 0, 0, 0, 0, 0},');
    } else if (id === 'trace') {
      lines.push('    {POKEMON_GEN3_ABILITY_TRACE, POKEMON_GEN3_HANDLER_TRACE_START - 1, 1, 0, 0, 0, 0, 0, 0},');
    } else if (id === 'pressure') {
      lines.push('    {POKEMON_GEN3_ABILITY_PRESSURE, POKEMON_GEN3_HANDLER_PRESSURE_DEDUCT_PP - 1, 2, 0, 0, 0, 1, 0, 0},');
    } else if (id === 'damp') {
      lines.push('    {POKEMON_GEN3_ABILITY_DAMP, POKEMON_GEN3_HANDLER_DAMP_TRY_MOVE - 1, 1, 0, 0, 0, 0, 0, 0},');
    } else if (id === 'flamebody') {
      lines.push('    {POKEMON_GEN3_ABILITY_FLAMEBODY, POKEMON_GEN3_HANDLER_FLAME_BODY_DAMAGING_HIT - 1, 1, 0, 0, 0, 0, 0, 0},');
    } else if (id === 'static') {
      lines.push('    {POKEMON_GEN3_ABILITY_STATIC, POKEMON_GEN3_HANDLER_STATIC_DAMAGING_HIT - 1, 1, 0, 0, 0, 0, 0, 0},');
    } else if (id === 'poisonpoint') {
      lines.push('    {POKEMON_GEN3_ABILITY_POISONPOINT, POKEMON_GEN3_HANDLER_POISON_POINT_DAMAGING_HIT - 1, 1, 0, 0, 0, 0, 0, 0},');
    } else if (id === 'effectspore') {
      lines.push('    {POKEMON_GEN3_ABILITY_EFFECTSPORE, POKEMON_GEN3_HANDLER_EFFECT_SPORE_DAMAGING_HIT - 1, 1, 0, 0, 0, 0, 0, 0},');
    } else if (id === 'roughskin') {
      lines.push('    {POKEMON_GEN3_ABILITY_ROUGHSKIN, POKEMON_GEN3_HANDLER_ROUGH_SKIN_DAMAGING_HIT - 1, 1, 0, 0, 0, 0, 0, 0},');
    } else if (id === 'arenatrap') {
      lines.push('    {POKEMON_GEN3_ABILITY_ARENATRAP, POKEMON_GEN3_HANDLER_ARENA_TRAP_TRAP_POKEMON - 1, 1, 0, 0, 0, 0, 0, 0},');
    } else if (id === 'magnetpull') {
      lines.push('    {POKEMON_GEN3_ABILITY_MAGNETPULL, POKEMON_GEN3_HANDLER_MAGNET_PULL_TRAP_POKEMON - 1, 1, 0, 0, 0, 0, 0, 0},');
    } else if (id === 'cloudnine') {
      const ability = dex.abilities.get(id);
      if (!ability.suppressWeather) throw new Error('resolved Cloud Nine must suppress weather');
      lines.push(`    {POKEMON_GEN3_ABILITY_CLOUDNINE, ${lifecycleHandlerOffset}, 2, 0, 0, 0, 0, 1, 0},`);
    } else if (id === 'sandstream') {
      lines.push(`    {POKEMON_GEN3_ABILITY_SANDSTREAM, ${lifecycleHandlerOffset + 2}, 1, 0, 0, 0, 0, 0, 0},`);
    } else if (id === 'chlorophyll') {
      lines.push(`    {POKEMON_GEN3_ABILITY_CHLOROPHYLL, ${speedHandlerOffset}, 1, 0, 0, 0, 0, 0, 0},`);
    } else if (id === 'swiftswim') {
      lines.push(`    {POKEMON_GEN3_ABILITY_SWIFTSWIM, ${speedHandlerOffset + 1}, 1, 0, 0, 0, 0, 0, 0},`);
    } else if (id === 'raindish') {
      lines.push(`    {POKEMON_GEN3_ABILITY_RAINDISH, ${residualHandlerOffset}, 1, 0, 0, 0, 0, 0, 0},`);
    } else if (id === 'owntempo') {
      lines.push(`    {POKEMON_GEN3_ABILITY_OWNTEMPO, ${confusionHandlerOffset + 3}, 3, 0, 0, 0, 0, 0, 0},`);
    } else if (id === 'shielddust') {
      lines.push(`    {POKEMON_GEN3_ABILITY_SHIELDDUST, ${confusionHandlerOffset + 6}, 1, 0, 0, 0, 0, 0, 0},`);
    } else if (id === 'stickyhold') {
      lines.push('    {POKEMON_GEN3_ABILITY_STICKYHOLD, 0, 0, 0, 0, 0, 0, 0, 1},');
    } else if (id === 'compoundeyes') {
      lines.push(`    {POKEMON_GEN3_ABILITY_COMPOUNDEYES, ${scalarHandlerOffset}, 1, 0, 0, 0, 0, 0, 0},`);
    } else if (id === 'hugepower') {
      lines.push(`    {POKEMON_GEN3_ABILITY_HUGEPOWER, ${scalarHandlerOffset + 1}, 1, 0, 0, 0, 0, 0, 0},`);
    } else if (id === 'hustle') {
      lines.push(`    {POKEMON_GEN3_ABILITY_HUSTLE, ${scalarHandlerOffset + 2}, 2, 0, 0, 0, 0, 0, 0},`);
    } else if (id === 'purepower') {
      lines.push(`    {POKEMON_GEN3_ABILITY_PUREPOWER, ${scalarHandlerOffset + 4}, 1, 0, 0, 0, 0, 0, 0},`);
    } else if (id === 'innerfocus') {
      lines.push(`    {POKEMON_GEN3_ABILITY_INNERFOCUS, ${flinchHandlerOffset + 1}, 1, 0, 0, 0, 0, 0, 0},`);
    } else if (id === 'battlearmor') {
      lines.push(`    {POKEMON_GEN3_ABILITY_BATTLEARMOR, ${criticalHandlerOffset + 5}, 1, 0, 0, 0, 0, 0, 0},`);
    } else if (id === 'shellarmor') {
      lines.push(`    {POKEMON_GEN3_ABILITY_SHELLARMOR, ${criticalHandlerOffset + 6}, 1, 0, 0, 0, 0, 0, 0},`);
    } else if (id === 'oblivious') {
      lines.push('    {POKEMON_GEN3_ABILITY_OBLIVIOUS, POKEMON_GEN3_HANDLER_OBLIVIOUS_IMMUNITY - 1, 3, 0, 0, 0, 0, 0, 0},');
	} else if (id === 'wonderguard') {
		lines.push('    {POKEMON_GEN3_ABILITY_WONDERGUARD, POKEMON_GEN3_HANDLER_WONDER_GUARD_TRY_HIT - 1, 1, 0, 0, 0, 0, 0, POKEMON_ABILITY_SEMANTIC_FAIL_ROLE_PLAY | POKEMON_ABILITY_SEMANTIC_FAIL_SKILL_SWAP},');
    } else if (id === 'suctioncups') {
      lines.push('    {POKEMON_GEN3_ABILITY_SUCTIONCUPS, POKEMON_GEN3_HANDLER_SUCTION_CUPS_DRAG_OUT - 1, 1, 0, 0, 0, 0, 0, 0},');
    } else if (id === 'liquidooze') {
      lines.push('    {POKEMON_GEN3_ABILITY_LIQUIDOOZE, POKEMON_GEN3_HANDLER_LIQUID_OOZE_SOURCE_TRY_HEAL - 1, 1, 0, 0, 0, 0, 0, 0},');
    } else if (id === 'flashfire') {
      lines.push('    {POKEMON_GEN3_ABILITY_FLASHFIRE, POKEMON_GEN3_HANDLER_FLASH_FIRE_TRY_HIT - 1, 2, 0, 0, 0, 0, 0, 0},');
    } else if (id === 'minus') {
      lines.push('    {POKEMON_GEN3_ABILITY_MINUS, POKEMON_GEN3_HANDLER_MINUS_MODIFY_SPA - 1, 1, 0, 0, 0, 0, 0, 0},');
    } else if (id === 'plus') {
      lines.push('    {POKEMON_GEN3_ABILITY_PLUS, POKEMON_GEN3_HANDLER_PLUS_MODIFY_SPA - 1, 1, 0, 0, 0, 0, 0, 0},');
    } else if (id === 'sturdy') {
      lines.push('    {POKEMON_GEN3_ABILITY_STURDY, POKEMON_GEN3_HANDLER_STURDY_TRY_HIT - 1, 1, 0, 0, 0, 0, 0, 0},');
    } else if (id === 'pickup') {
      lines.push('    {POKEMON_GEN3_ABILITY_PICKUP, 0, 0, 0, 0, 0, 0, 0, POKEMON_ABILITY_SEMANTIC_CYCLES_RESTORATIVE_ITEM},');
    } else {
      lines.push(`    {POKEMON_GEN3_ABILITY_${cName(id)}, 0, 0, 0, 0, 0, 0, 0, 0},`);
    }
  }
  lines.push('};', '',
    'static const PokemonSecondaryChancePolicy SECONDARY_CHANCE_POLICIES[] = {',
    '    {POKEMON_GEN3_ABILITY_SERENEGRACE, 2, 1},',
    '};', '', 'static const PokemonItemData ITEMS[] = {');
  TYPE_BOOST_ITEMS.forEach(([id], index) => {
    const handlerOffset = index === 0 ? 2 : typeBoostHandlerOffset + index - 1;
    lines.push(`    {POKEMON_GEN3_ITEM_${cName(id)}, ${handlerOffset}, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0},`);
  });
  FIXED_HEAL_BERRIES.forEach(([id, heal], index) => {
    lines.push(`    {POKEMON_GEN3_ITEM_${cName(id)}, ${berryHandlerOffset + index * 3}, 3, 2, ${heal}, ${id === 'oranberry' ? 10 : 0}, ${id === 'sitrusberry' ? 4 : 0}, 0, 0, 0, 0, 0, 0, POKEMON_ITEM_FLAG_RESTORATIVE},`);
  });
  FLAVOR_BERRIES.forEach(([id, flavor], index) => {
    lines.push(`    {POKEMON_GEN3_ITEM_${cName(id)}, ${flavorHandlerOffset + index * 3}, 3, 2, 0, 0, 3, 0, 0, 0, 0, 8, POKEMON_FLAVOR_${flavor}, POKEMON_ITEM_FLAG_RESTORATIVE},`);
  });
  PINCH_BOOST_BERRIES.forEach(([id, stat], index) => {
    lines.push(`    {POKEMON_GEN3_ITEM_${cName(id)}, ${pinchHandlerOffset + index * 2}, 2, 4, 0, 0, 0, POKEMON_STAT_${stat}, 1, 0, 0, 0, 0, 0},`);
  });
  VOLATILE_PINCH_BERRIES.forEach(([id, volatile], index) => {
    lines.push(`    {POKEMON_GEN3_ITEM_${cName(id)}, ${volatilePinchHandlerOffset + index * 2}, 2, 4, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, POKEMON_VOLATILE_${volatile}},`);
  });
  RANDOM_PINCH_BERRIES.forEach(([id, stats, delta], index) => {
    const mask = stats.map(stat => `(UINT8_C(1) << POKEMON_STAT_${stat})`).join(' | ');
    lines.push(`    {POKEMON_GEN3_ITEM_${cName(id)}, ${randomPinchHandlerOffset + index * 2}, 2, 4, 0, 0, 0, 0, ${delta}, 0, 0, 0, 0, 0, 0, ${mask}},`);
  });
  STATUS_CURE_BERRIES.forEach(([id, statuses], index) => {
    const mask = statuses.map(status => `(UINT16_C(1) << POKEMON_STATUS_${status})`).join(' | ');
    lines.push(`    {POKEMON_GEN3_ITEM_${cName(id)}, ${cureHandlerOffset + index * 2}, 2, 0, 0, 0, 0, 0, 0, ${mask}, 0, 0, 0, 0},`);
  });
  VOLATILE_CURE_BERRIES.forEach(([id, volatile], index) => {
    lines.push(`    {POKEMON_GEN3_ITEM_${cName(id)}, ${volatileCureHandlerOffset + index * 2}, 2, 0, 0, 0, 0, 0, 0, 0, POKEMON_VOLATILE_${volatile}, 0, 0, 0},`);
  });
  COMBINED_CURE_BERRIES.forEach(([id, volatile], index) => {
    const mask = ['SLEEP', 'POISON', 'TOXIC', 'BURN', 'PARALYSIS', 'FREEZE']
      .map(status => `(UINT16_C(1) << POKEMON_STATUS_${status})`).join(' | ');
    lines.push(`    {POKEMON_GEN3_ITEM_${cName(id)}, ${combinedCureHandlerOffset + index * 3}, 3, 0, 0, 0, 0, 0, 0, ${mask}, POKEMON_VOLATILE_${volatile}, 0, 0, 0},`);
  });
  UPDATE_CURE_ITEMS.forEach(([id, volatile]) => {
    lines.push(`    {POKEMON_GEN3_ITEM_${cName(id)}, POKEMON_GEN3_HANDLER_MENTAL_HERB_UPDATE - 1, 1, 0, 0, 0, 0, 0, 0, 0, POKEMON_VOLATILE_${volatile}, 0, 0, 0},`);
  });
  lines.push('    {POKEMON_GEN3_ITEM_WHITEHERB, POKEMON_GEN3_HANDLER_WHITE_HERB_START - 1, 4, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0},');
  lines.push('    {POKEMON_GEN3_ITEM_CHOICEBAND, POKEMON_GEN3_HANDLER_CHOICE_BAND_MODIFY_ATK - 1, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0},');
  lines.push('    {POKEMON_GEN3_ITEM_MAIL, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0},');
  lines.push(`    {POKEMON_GEN3_ITEM_THICKCLUB, ${scalarHandlerOffset + 5}, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0},`);
  lines.push(`    {POKEMON_GEN3_ITEM_SCOPELENS, ${criticalHandlerOffset + 2}, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0},`);
  lines.push(`    {POKEMON_GEN3_ITEM_LUCKYPUNCH, ${criticalHandlerOffset + 3}, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0},`);
  lines.push(`    {POKEMON_GEN3_ITEM_STICK, ${criticalHandlerOffset + 4}, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0},`);
  lines.push('    {POKEMON_GEN3_ITEM_LEFTOVERS, POKEMON_GEN3_HANDLER_LEFTOVERS_RESIDUAL - 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0},');
  const quickClaw = dex.items.get('quickclaw');
  const gen3Scripts = fs.readFileSync(
    path.resolve(showdownDir, 'data/mods/gen3/scripts.ts'), 'utf8');
  const battleSource = fs.readFileSync(
    path.resolve(showdownDir, 'sim/battle.ts'), 'utf8');
  if (!quickClaw.exists || quickClaw.gen > 3 ||
      quickClaw.onFractionalPriority !== undefined ||
      !(battleSource.includes("verificationRandomChance('turn.quick_claw', 1, 5)") ||
        battleSource.includes('this.randomChance(1, 5)')) ||
      !gen3Scripts.includes("this.hasItem('quickclaw')") ||
      !gen3Scripts.includes('speed = 65535')) {
    throw new Error('resolved Gen 3 Quick Claw shared-speed shape changed');
  }
  lines.push('    {POKEMON_GEN3_ITEM_QUICKCLAW, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, POKEMON_ITEM_FLAG_SHARED_TURN_SPEED_SENTINEL, 0},');
	lines.push('    {POKEMON_GEN3_ITEM_FOCUSBAND, POKEMON_GEN3_HANDLER_FOCUS_BAND_DAMAGE - 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0},');
	lines.push('    {POKEMON_GEN3_ITEM_LEPPABERRY, POKEMON_GEN3_HANDLER_LEPPA_BERRY_UPDATE - 1, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, POKEMON_ITEM_FLAG_RESTORATIVE},');
	lines.push('    {POKEMON_GEN3_ITEM_KINGSROCK, POKEMON_GEN3_HANDLER_KINGS_ROCK_MODIFY_MOVE - 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0},');
	lines.push('    {POKEMON_GEN3_ITEM_SHELLBELL, POKEMON_GEN3_HANDLER_SHELL_BELL_AFTER_MOVE_SECONDARY_SELF - 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0},');
  lines.push('    {POKEMON_GEN3_ITEM_DEEPSEASCALE, POKEMON_GEN3_HANDLER_DEEP_SEA_SCALE_SPD - 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0},');
  lines.push('    {POKEMON_GEN3_ITEM_DEEPSEATOOTH, POKEMON_GEN3_HANDLER_DEEP_SEA_TOOTH_SPA - 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0},');
  lines.push('    {POKEMON_GEN3_ITEM_LIGHTBALL, POKEMON_GEN3_HANDLER_LIGHT_BALL_SPA - 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0},');
  lines.push('    {POKEMON_GEN3_ITEM_MACHOBRACE, POKEMON_GEN3_HANDLER_MACHO_BRACE_SPEED - 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0},');
  lines.push('    {POKEMON_GEN3_ITEM_SOULDEW, POKEMON_GEN3_HANDLER_SOUL_DEW_SPA - 1, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0},');
  lines.push('    {POKEMON_GEN3_ITEM_METALPOWDER, POKEMON_GEN3_HANDLER_METAL_POWDER_MODIFY_DEF - 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0},');
  const passiveClosure = inventory.items
    .map(entry => dex.items.get(entry.id))
    .filter(item => item.id !== 'quickclaw')
    .filter(item => !Object.keys(item).some(key =>
      /^on[A-Z]/.test(key) &&
      !/(?:Order|Priority|SubOrder)$/.test(key) &&
      typeof item[key] === 'function'))
    .sort((left, right) => left.num - right.num || left.id.localeCompare(right.id))
    .map(item => item.id);
  if (JSON.stringify(passiveClosure) !== JSON.stringify(PASSIVE_ITEMS)) {
    throw new Error(`resolved Gen 3 passive item closure changed: ${passiveClosure.join(',')}`);
  }
  for (const id of PASSIVE_ITEMS) {
    const item = dex.items.get(id);
    const callbacks = Object.keys(item).filter(key =>
      /^on[A-Z]/.test(key) &&
      !/(?:Order|Priority|SubOrder)$/.test(key) &&
      typeof item[key] === 'function');
    if (!item.exists || item.gen > 3 || callbacks.length !== 0 ||
        !inventory.items.some(entry => entry.id === id)) {
      throw new Error(`resolved Gen 3 passive item closure changed for ${id}`);
    }
    const flags = id === 'enigmaberry' ? 'POKEMON_ITEM_FLAG_RESTORATIVE' : '0';
    lines.push(`    {POKEMON_GEN3_ITEM_${cName(id)}, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, ${flags}},`);
  }
  lines.push('};', '', 'static const PokemonStatusImmunity STATUS_IMMUNITIES[] = {',
    '    {POKEMON_GEN3_ABILITY_IMMUNITY, POKEMON_STATUS_POISON, POKEMON_HANDLER_EVENT_SET_STATUS, 1, 0},',
    '    {POKEMON_GEN3_ABILITY_IMMUNITY, POKEMON_STATUS_TOXIC, POKEMON_HANDLER_EVENT_SET_STATUS, 1, 0},',
    '    {POKEMON_GEN3_ABILITY_INSOMNIA, POKEMON_STATUS_SLEEP, POKEMON_HANDLER_EVENT_SET_STATUS, 1, 1},',
    '    {POKEMON_GEN3_ABILITY_VITALSPIRIT, POKEMON_STATUS_SLEEP, POKEMON_HANDLER_EVENT_SET_STATUS, 1, 1},',
    '    {POKEMON_GEN3_ABILITY_LIMBER, POKEMON_STATUS_PARALYSIS, POKEMON_HANDLER_EVENT_SET_STATUS, 1, 0},',
    '    {POKEMON_GEN3_ABILITY_WATERVEIL, POKEMON_STATUS_BURN, POKEMON_HANDLER_EVENT_SET_STATUS, 1, 0},',
    '    {POKEMON_GEN3_ABILITY_MAGMAARMOR, POKEMON_STATUS_FREEZE, POKEMON_HANDLER_EVENT_IMMUNITY, 1, 0},');
  const futuremove = dex.conditions.get('futuremove');
  const wishCondition = dex.moves.get('wish').condition;
  if (futuremove.onResidualOrder !== 11 || typeof futuremove.onEnd !== 'function' ||
      wishCondition?.duration !== 2 || wishCondition?.onResidualOrder !== 7 ||
      typeof wishCondition?.onEnd !== 'function') {
    throw new Error('resolved Gen 3 slot-condition lifecycle changed');
  }
  lines.push('};', '', 'static const PokemonSlotConditionPolicy SLOT_CONDITION_POLICIES[] = {',
    '    {POKEMON_GEN3_CONDITION_SLOT_FUTUREMOVE, POKEMON_SLOT_CONDITION_FUTURE_MOVE, POKEMON_SLOT_EFFECT_DELAYED_FIXED_DAMAGE, 3, 11, 3, 0, 0},',
    '    {POKEMON_GEN3_CONDITION_SLOT_WISH, POKEMON_SLOT_CONDITION_WISH, POKEMON_SLOT_EFFECT_HEAL_ACTIVE_MAX_HP_FRACTION, 2, 7, 3, 1, 2},',
    '};', '', 'static const PokemonTwoTurnMoveDescriptor TWO_TURN_MOVES[] = {',
	'    {POKEMON_GEN3_MOVE_SOLARBEAM, POKEMON_GEN3_CONDITION_VOLATILE_SOLARBEAM, 0, 0, 0},',
	'    {POKEMON_GEN3_MOVE_FLY, POKEMON_GEN3_CONDITION_VOLATILE_FLY, 2, 0, 0},',
	'    {POKEMON_GEN3_MOVE_BOUNCE, POKEMON_GEN3_CONDITION_VOLATILE_BOUNCE, 2, 0, 0},',
	'    {POKEMON_GEN3_MOVE_DIG, POKEMON_GEN3_CONDITION_VOLATILE_DIG, 2, 0, 0},',
	'    {POKEMON_GEN3_MOVE_DIVE, POKEMON_GEN3_CONDITION_VOLATILE_DIVE, 2, 0, 0},',
	'    {POKEMON_GEN3_MOVE_RAZORWIND, POKEMON_GEN3_CONDITION_VOLATILE_RAZORWIND, 0, 0, 0},',
	'    {POKEMON_GEN3_MOVE_SKULLBASH, POKEMON_GEN3_CONDITION_VOLATILE_SKULLBASH, 0, POKEMON_STAT_DEF, 1},',
	'    {POKEMON_GEN3_MOVE_SKYATTACK, POKEMON_GEN3_CONDITION_VOLATILE_SKYATTACK, 0, 0, 0},',
  '};', '',
  'static const PokemonWeightedMoveOutcome WEIGHTED_MOVE_OUTCOMES[] = {',
  '    {.weight = 5, .kind = POKEMON_WEIGHTED_MOVE_OUTCOME_DAMAGE, .value.damage = {10, 4}},',
  '    {.weight = 10, .kind = POKEMON_WEIGHTED_MOVE_OUTCOME_DAMAGE, .value.damage = {30, 5}},',
  '    {.weight = 20, .kind = POKEMON_WEIGHTED_MOVE_OUTCOME_DAMAGE, .value.damage = {50, 6}},',
  '    {.weight = 30, .kind = POKEMON_WEIGHTED_MOVE_OUTCOME_DAMAGE, .value.damage = {70, 7}},',
  '    {.weight = 20, .kind = POKEMON_WEIGHTED_MOVE_OUTCOME_DAMAGE, .value.damage = {90, 8}},',
  '    {.weight = 10, .kind = POKEMON_WEIGHTED_MOVE_OUTCOME_DAMAGE, .value.damage = {110, 9}},',
  '    {.weight = 5, .kind = POKEMON_WEIGHTED_MOVE_OUTCOME_DAMAGE, .value.damage = {150, 10}},',
  '    {.weight = 2, .kind = POKEMON_WEIGHTED_MOVE_OUTCOME_TARGET_MAX_HP_HEAL, .value.heal = {1, 4}},',
  '    {.weight = 4, .kind = POKEMON_WEIGHTED_MOVE_OUTCOME_DAMAGE, .value.damage = {40, 0}},',
  '    {.weight = 3, .kind = POKEMON_WEIGHTED_MOVE_OUTCOME_DAMAGE, .value.damage = {80, 0}},',
  '    {.weight = 1, .kind = POKEMON_WEIGHTED_MOVE_OUTCOME_DAMAGE, .value.damage = {120, 0}},',
  '};', '',
  'static const PokemonWeightedMoveOutcomeDistribution WEIGHTED_MOVE_DISTRIBUTIONS[] = {',
  '    {1, 0, 7, POKEMON_DRAW_MOVE_POWER_DISTRIBUTION},',
  '    {2, 7, 4, POKEMON_DRAW_MOVE_RESOLUTION_DISTRIBUTION},',
  '};', '',
  'static const uint8_t STATUS_DISTRIBUTION_CANDIDATES[] = {',
  '    POKEMON_STATUS_BURN, POKEMON_STATUS_PARALYSIS, POKEMON_STATUS_FREEZE,',
  '};', '',
  'static const PokemonStatusDistribution STATUS_DISTRIBUTIONS[] = {',
  '    {1, 0, 3, POKEMON_DRAW_MOVE_STATUS_SELECTION},',
  '};', '',
  'static const PokemonWeatherFormPolicy WEATHER_FORM_POLICIES[] = {',
  '    {1, POKEMON_GEN3_SPECIES_CASTFORM, POKEMON_GEN3_SPECIES_CASTFORM,',
  '     POKEMON_GEN3_SPECIES_CASTFORMSUNNY, POKEMON_GEN3_SPECIES_CASTFORMRAINY,',
  '     POKEMON_GEN3_SPECIES_CASTFORMSNOWY},',
  '};', '',
  'static const PokemonWeightPowerPolicy WEIGHT_POWER_POLICIES[] = {',
  '    {1, 6, {100, 250, 500, 1000, 2000}, {20, 40, 60, 80, 100, 120}},',
  '};', '',
  'static const PokemonTransformPolicy TRANSFORM_POLICIES[] = {',
  '    {1, 1, 5, 0, 1, 0, 0},',
  '};', '', 'static const PokemonFormatRule GEN3_OU_RULES[] = {');
  for (const rule of inventory.format_rules) {
    const classification = classifyFormatRule(rule);
    const operands = [...classification.operands];
    while (operands.length < 3) operands.push({kind: 0, catalogID: 0});
    lines.push(`    {${classification.kind}, ${cString(rule.id)}, ` +
      `${classification.operands.length}, {{${operands[0].kind}, ${operands[0].catalogID}}, ` +
      `{${operands[1].kind}, ${operands[1].catalogID}}, ` +
      `{${operands[2].kind}, ${operands[2].catalogID}}}},`);
  }
  lines.push('};', '', 'static const PokemonFormatRule GEN3_OU_POMEG_RULES[] = {');
  for (const rule of inventory.format_rules) {
    const classification = classifyFormatRule(rule);
    const operands = [...classification.operands];
    while (operands.length < 3) operands.push({kind: 0, catalogID: 0});
    lines.push(`    {${classification.kind}, ${cString(rule.id)}, ` +
      `${classification.operands.length}, {{${operands[0].kind}, ${operands[0].catalogID}}, ` +
      `{${operands[1].kind}, ${operands[1].catalogID}}, ` +
      `{${operands[2].kind}, ${operands[2].catalogID}}}},`);
  }
  lines.push('    {POKEMON_FORMAT_RULE_METADATA, "pomegglitchclause", 0, {{0, 0}, {0, 0}, {0, 0}}},',
    '};', '', 'const PokemonFormatManifest POKEMON_GEN3_OU_FORMAT = {',
    '    .plugin_fingerprint = UINT64_C(0x503347454e334f55),',
    '    .capability_version = POKEMON_KERNEL_PLUGIN_ABI_VERSION,',
    '    .capabilities = POKEMON_CAP_GEN3,',
    '    .id = "gen3ou", .name = "[Gen 3] OU",',
    '    .generation = 3,',
    '    .game_type = POKEMON_GAME_TYPE_SINGLES,',
    `    .min_team_size = ${constraints.team.min_size},`,
    `    .max_team_size = ${constraints.team.max_size},`,
    `    .max_move_count = ${constraints.team.max_moves},`,
    `    .min_level = ${constraints.team.min_level},`,
    `    .max_level = ${constraints.team.max_level},`,
    `    .default_level = ${constraints.team.default_level},`,
    '    .ev_limit_enabled = 1,',
    `    .ev_limit = ${constraints.team.ev_limit},`,
    '    .rules = GEN3_OU_RULES,',
    '    .rule_count = sizeof(GEN3_OU_RULES) / sizeof(GEN3_OU_RULES[0]),',
    '};', '', 'const PokemonFormatManifest POKEMON_GEN3_OU_POMEG_FORMAT = {',
    '    .plugin_fingerprint = UINT64_C(0x503347454e334f55),',
    '    .capability_version = POKEMON_KERNEL_PLUGIN_ABI_VERSION,',
    '    .capabilities = POKEMON_CAP_GEN3,',
    '    .id = "gen3oupomeg", .name = "[Gen 3] OU + Pomeg Glitch Clause",',
    '    .generation = 3,',
    '    .game_type = POKEMON_GAME_TYPE_SINGLES,',
    `    .min_team_size = ${constraints.team.min_size},`,
    `    .max_team_size = ${constraints.team.max_size},`,
    `    .max_move_count = ${constraints.team.max_moves},`,
    `    .min_level = ${constraints.team.min_level},`,
    `    .max_level = ${constraints.team.max_level},`,
    `    .default_level = ${constraints.team.default_level},`,
    '    .ev_limit_enabled = 1,',
    `    .ev_limit = ${constraints.team.ev_limit},`,
    '    .rules = GEN3_OU_POMEG_RULES,',
    '    .rule_count = sizeof(GEN3_OU_POMEG_RULES) / sizeof(GEN3_OU_POMEG_RULES[0]),',
    '};', '', 'const PokemonData POKEMON_GEN3_SLICE_DATA = {',
    '    .plugin_fingerprint = UINT64_C(0x503347454e334f55),',
    '    .capability_version = POKEMON_KERNEL_PLUGIN_ABI_VERSION,',
    '    .capabilities = POKEMON_CAP_GEN3,',
    '    .generation = 3,');
  lines.push('    .species = SPECIES,', `    .species_count = ${SPECIES.length},`, '    .moves = MOVES,');
  lines.push(`    .move_count = ${MOVES.length},`, '    .abilities = ABILITIES,');
  lines.push('    .move_invocation_profiles = MOVE_INVOCATION_PROFILES,',
    '    .move_invocation_profile_count = sizeof(MOVE_INVOCATION_PROFILES) / sizeof(MOVE_INVOCATION_PROFILES[0]),',
    '    .move_profile_selections = MOVE_PROFILE_SELECTIONS,',
    '    .move_profile_selection_count = sizeof(MOVE_PROFILE_SELECTIONS) / sizeof(MOVE_PROFILE_SELECTIONS[0]),');
  lines.push('    .effects = EFFECTS,', `    .effect_count = ${effects.length},`);
  lines.push('    .effect_secondary_groups = EFFECT_SECONDARY_GROUPS,',
    '    .effect_secondary_group_count = sizeof(EFFECT_SECONDARY_GROUPS) / sizeof(EFFECT_SECONDARY_GROUPS[0]),',
    '    .secondary_chance_policies = SECONDARY_CHANCE_POLICIES,',
    '    .secondary_chance_policy_count = sizeof(SECONDARY_CHANCE_POLICIES) / sizeof(SECONDARY_CHANCE_POLICIES[0]),');
  lines.push(`    .ability_count = ${ABILITIES.length},`, '    .handlers = HANDLERS,');
  lines.push('    .items = ITEMS,', `    .item_count = ${ITEMS.length},`);
  lines.push('    .status_immunities = STATUS_IMMUNITIES,',
    '    .status_immunity_count = sizeof(STATUS_IMMUNITIES) / sizeof(STATUS_IMMUNITIES[0]),');
  lines.push('    .weather_policies = WEATHER_POLICIES,',
    '    .weather_policy_count = sizeof(WEATHER_POLICIES) / sizeof(WEATHER_POLICIES[0]),');
  lines.push('    .slot_condition_policies = SLOT_CONDITION_POLICIES,',
    '    .slot_condition_policy_count = sizeof(SLOT_CONDITION_POLICIES) / sizeof(SLOT_CONDITION_POLICIES[0]),');
  lines.push('    .status_residual_policies = STATUS_RESIDUAL_POLICIES,',
    '    .status_residual_policy_count = sizeof(STATUS_RESIDUAL_POLICIES) / sizeof(STATUS_RESIDUAL_POLICIES[0]),');
  lines.push('    .handler_count = sizeof(HANDLERS) / sizeof(HANDLERS[0]),', '    .type_chart = TYPE_CHART,');
  lines.splice(lines.length - 1, 0,
    '    .owner_binding_index = OWNER_BINDING_INDEX,',
    '    .owner_binding_index_count = sizeof(OWNER_BINDING_INDEX) / sizeof(OWNER_BINDING_INDEX[0]),',
    '    .handler_programs = HANDLER_PROGRAMS,',
    '    .handler_program_count = sizeof(HANDLER_PROGRAMS) / sizeof(HANDLER_PROGRAMS[0]),',
    '    .event_specs = EVENT_SPECS,',
    '    .event_spec_count = sizeof(EVENT_SPECS) / sizeof(EVENT_SPECS[0]),');
  lines.splice(lines.length - 1, 0,
    '    .two_turn_moves = TWO_TURN_MOVES,',
    '    .two_turn_move_count = sizeof(TWO_TURN_MOVES) / sizeof(TWO_TURN_MOVES[0]),',
    '    .weighted_move_outcomes = WEIGHTED_MOVE_OUTCOMES,',
    '    .weighted_move_outcome_count = sizeof(WEIGHTED_MOVE_OUTCOMES) / sizeof(WEIGHTED_MOVE_OUTCOMES[0]),',
    '    .weighted_move_distributions = WEIGHTED_MOVE_DISTRIBUTIONS,',
    '    .weighted_move_distribution_count = sizeof(WEIGHTED_MOVE_DISTRIBUTIONS) / sizeof(WEIGHTED_MOVE_DISTRIBUTIONS[0]),',
    '    .status_distributions = STATUS_DISTRIBUTIONS,',
    '    .status_distribution_count = sizeof(STATUS_DISTRIBUTIONS) / sizeof(STATUS_DISTRIBUTIONS[0]),',
    '    .status_distribution_candidates = STATUS_DISTRIBUTION_CANDIDATES,',
    '    .status_distribution_candidate_count = sizeof(STATUS_DISTRIBUTION_CANDIDATES) / sizeof(STATUS_DISTRIBUTION_CANDIDATES[0]),',
    '    .weather_form_policies = WEATHER_FORM_POLICIES,',
    '    .weather_form_policy_count = sizeof(WEATHER_FORM_POLICIES) / sizeof(WEATHER_FORM_POLICIES[0]),',
    '    .weight_power_policies = WEIGHT_POWER_POLICIES,',
    '    .weight_power_policy_count = sizeof(WEIGHT_POWER_POLICIES) / sizeof(WEIGHT_POWER_POLICIES[0]),',
    '    .transform_policies = TRANSFORM_POLICIES,',
    '    .transform_policy_count = sizeof(TRANSFORM_POLICIES) / sizeof(TRANSFORM_POLICIES[0]),',
    '    .move_call_pools = MOVE_CALL_POOLS,',
    '    .constructed_hit_templates = CONSTRUCTED_HIT_TEMPLATES,',
    '    .constructed_hit_template_count = sizeof(CONSTRUCTED_HIT_TEMPLATES) / sizeof(CONSTRUCTED_HIT_TEMPLATES[0]),',
    '    .move_pre_use_programs = MOVE_PRE_USE_PROGRAMS,',
    '    .move_pre_use_program_count = sizeof(MOVE_PRE_USE_PROGRAMS) / sizeof(MOVE_PRE_USE_PROGRAMS[0]),',
	'    .locked_ramp_policies = LOCKED_RAMP_POLICIES,',
	'    .locked_ramp_policy_count = sizeof(LOCKED_RAMP_POLICIES) / sizeof(LOCKED_RAMP_POLICIES[0]),',
    '    .counter_heal_policies = COUNTER_HEAL_POLICIES,',
    '    .counter_heal_policy_count = sizeof(COUNTER_HEAL_POLICIES) / sizeof(COUNTER_HEAL_POLICIES[0]),',
    '    .type_response_policies = TYPE_RESPONSE_POLICIES,',
    '    .type_response_policy_count = sizeof(TYPE_RESPONSE_POLICIES) / sizeof(TYPE_RESPONSE_POLICIES[0]),',
    '    .move_call_pool_count = sizeof(MOVE_CALL_POOLS) / sizeof(MOVE_CALL_POOLS[0]),',
    '    .move_call_pool_candidates = MOVE_CALL_POOL_CANDIDATES,',
    '    .move_call_pool_candidate_count = sizeof(MOVE_CALL_POOL_CANDIDATES) / sizeof(MOVE_CALL_POOL_CANDIDATES[0]),');
  lines.push('    .type_count = POKEMON_GEN3_TYPE_COUNT,');
  lines.push('    .has_non_interacting_type = 1,');
  lines.push('    .non_interacting_type = POKEMON_GEN3_TYPE_TYPELESS,', '};');
  lines.splice(lines.length - 1, 0,
    '    .species_catalog = SPECIES_CATALOG,',
    '    .species_catalog_count = sizeof(SPECIES_CATALOG) / sizeof(SPECIES_CATALOG[0]),',
    '    .move_catalog = MOVE_CATALOG,',
    '    .move_catalog_count = sizeof(MOVE_CATALOG) / sizeof(MOVE_CATALOG[0]),',
    '    .ability_catalog = ABILITY_CATALOG,',
    '    .ability_catalog_count = sizeof(ABILITY_CATALOG) / sizeof(ABILITY_CATALOG[0]),',
    '    .item_catalog = ITEM_CATALOG,',
    '    .item_catalog_count = sizeof(ITEM_CATALOG) / sizeof(ITEM_CATALOG[0]),',
    '    .condition_catalog = CONDITION_CATALOG,',
    '    .condition_catalog_count = sizeof(CONDITION_CATALOG) / sizeof(CONDITION_CATALOG[0]),',
    '    .poison_type = POKEMON_GEN3_TYPE_POISON,',
    '    .fire_type = POKEMON_GEN3_TYPE_FIRE,',
    '    .ice_type = POKEMON_GEN3_TYPE_ICE,',
    '    .ground_type = POKEMON_GEN3_TYPE_GROUND,',
    '    .rock_type = POKEMON_GEN3_TYPE_ROCK,',
    '    .steel_type = POKEMON_GEN3_TYPE_STEEL,');
}
/* Holder capability fields are append-only ABI data. Keep the older compact
 * initializer construction above readable, then complete omitted trailing
 * fields here. */
if (output === 'source') {
  let section = '';
  for (let i = 0; i < lines.length; i++) {
    if (lines[i] === 'static const PokemonAbilityData ABILITIES[] = {') section = 'ability';
    else if (lines[i] === 'static const PokemonItemData ITEMS[] = {') section = 'item';
    else if (section && lines[i] === '};') section = '';
    else if (section === 'item' && lines[i].startsWith('    {') &&
        !lines[i].includes('ITEM_MAIL') && !lines[i].includes('ITEM_QUICKCLAW') &&
        !lines[i].includes('ITEM_LANSATBERRY') &&
        !lines[i].includes('ITEM_STARFBERRY')) {
      lines[i] = lines[i].replace('},', ', 0},');
    }
  }
  section = '';
  for (let i = 0; i < lines.length; i++) {
    if (lines[i] === 'static const PokemonItemData ITEMS[] = {') section = 'item';
    else if (section && lines[i] === '};') section = '';
    else if (section === 'item' && lines[i].startsWith('    {') &&
        !lines[i].includes('ITEM_STARFBERRY')) {
      lines[i] = lines[i].replace('},', ', 0},');
    }
  }
  section = '';
  for (let i = 0; i < lines.length; i++) {
    if (lines[i] === 'static const PokemonHandlerDescriptor HANDLERS[] = {') {
      section = 'handler';
    } else if (section && lines[i] === '};') {
      section = '';
    } else if (section === 'handler' && /"[^"\n]*"},$/.test(lines[i])) {
      lines[i] = lines[i].replace(/},$/, ', 0},');
    }
  }
}
process.stdout.write(`${lines.join('\n')}\n`);
