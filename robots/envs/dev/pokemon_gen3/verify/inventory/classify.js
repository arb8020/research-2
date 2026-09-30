'use strict';

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const root = path.resolve(__dirname, '../..');
const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const sourcePath = 'verify/inventory/gen3ou-inventory.json';
const artifactBytes = fs.readFileSync(path.join(root, sourcePath));
const artifact = JSON.parse(artifactBytes);
const artifactDigest = crypto.createHash('sha256').update(artifactBytes).digest('hex');
const callbackHookSources = new Map();
for (const hook of artifact.callback_hooks) {
	const id = `${hook.owner_kind}.${hook.owner_id}.${hook.hook}`;
	if (callbackHookSources.has(id)) throw new Error(`duplicate callback hook provenance: ${id}`);
	if (!hook.showdown_source?.path || !hook.showdown_source?.symbol) {
		throw new Error(`callback hook lacks physical Showdown provenance: ${id}`);
	}
	callbackHookSources.set(id, hook.showdown_source);
}
const nativeIDs = JSON.parse(fs.readFileSync(path.join(root, 'verify/cases/native-id-map.json'), 'utf8'));
const template = JSON.parse(fs.readFileSync(path.join(__dirname, 'descriptor-map.json'), 'utf8'));
if (template.schema !== 'pokemon-native-descriptor-map-v1' ||
	template.oracle_revision !== revision || template.format !== 'gen3ou' ||
	!Array.isArray(template.inventories) || template.inventories.length !== 9 ||
	!template.coverage_contract) {
	throw new Error('descriptor-map template is missing or structurally invalid');
}

function jsonFiles(directory) {
	return fs.readdirSync(directory, {withFileTypes: true}).flatMap(entry => {
		const filename = path.join(directory, entry.name);
		return entry.isDirectory() ? jsonFiles(filename) : entry.name.endsWith('.json') ? [filename] : [];
	});
}

const usage = {species_form: new Map(), move: new Map(), ability: new Map(), item: new Map()};
const caseFeatures = new Map();
function note(kind, id, battleCase) {
	if (!id) return;
	const record = usage[kind].get(id) || {cases: new Set(), features: new Set()};
	record.cases.add(battleCase.id);
	for (const feature of battleCase.features) record.features.add(feature);
	usage[kind].set(id, record);
}
for (const filename of jsonFiles(path.join(root, 'verify/cases'))) {
	const battleCase = JSON.parse(fs.readFileSync(filename, 'utf8'));
	if (battleCase.schema !== 'pokemon-native-differential-case-v1') continue;
	caseFeatures.set(battleCase.id, battleCase.features);
	for (const team of battleCase.teams) for (const member of team.normalized) {
		note('species_form', member.species, battleCase);
		note('ability', member.ability, battleCase);
		note('item', member.item, battleCase);
		for (const move of member.moves) note('move', move, battleCase);
	}
}

const truantCases = [
	'truant-basic-alternation', 'truant-opening-alternation',
	'truant-voluntary-switch-entry', 'truant-post-residual-replacement',
	'truant-recharge-staging', 'truant-wake-after-acting-turn',
	'truant-wake-after-loafing-turn', 'truant-two-turn-move-failure',
];
const forecastCases = [
	'forecast-weather-cycle-expiry', 'forecast-switch-start-reset',
	'forecast-cloud-nine-suppression', 'forecast-weatherchange-order',
];
const abilityCases = {
	truant: truantCases,
	forecast: forecastCases,
	sturdy: [
		'ohko-sheer-cold-sturdy', 'ohko-sheer-cold-ice-target',
	],
	plus: [
		'plus-minus-opponent-boost', 'plus-minus-reverse-opponent-boost',
		'plus-minus-same-no-boost', 'plus-minus-physical-control',
	],
	minus: [
		'plus-minus-opponent-boost', 'plus-minus-reverse-opponent-boost',
		'plus-minus-same-no-boost', 'plus-minus-physical-control',
	],
	flashfire: [
		'flash-fire-activation-repeat-boost', 'flash-fire-frozen-fallthrough',
		'flash-fire-willowisp-fire-holder', 'flash-fire-protect-before-activation',
		'flash-fire-substitute-activation', 'flash-fire-switch-cleanup',
	],
	liquidooze: ['leech-seed-liquid-ooze-drain'],
	suctioncups: ['drag-suction-cups-block'],
	wonderguard: ['wonder-guard-effectiveness', 'wonder-guard-bypass-and-order'],
	illuminate: ['inert-ability-illuminate'],
	pickup: ['inert-ability-pickup'],
	runaway: ['inert-ability-runaway'],
	stench: ['inert-ability-stench'],
	lightningrod: ['lightning-rod-electric-single-target',
		'lightning-rod-nonelectric-single-target'],
	arenatrap: ['arena-trap-grounded-block', 'arena-trap-flying-escape'],
	magnetpull: ['magnet-pull-steel-flying-block', 'magnet-pull-nonsteel-escape'],
	damp: ['damp-explosion', 'damp-self-destruct', 'damp-ordinary-pass'],
	flamebody: [
		'flame-body-contact', 'flame-body-contact-success',
		'flame-body-substitute-no-activation',
	],
	static: ['static-contact-success'],
	poisonpoint: [
		'poison-point-contact-success', 'poison-point-steel-immunity',
	],
	effectspore: [
		'effect-spore-contact-failure', 'effect-spore-sleep',
		'effect-spore-paralysis', 'effect-spore-poison',
	],
	roughskin: ['rough-skin-contact'],
	blaze: ['starter-blaze-threshold', 'starter-blaze-above-threshold', 'starter-blaze-type-mismatch'],
	overgrow: ['starter-overgrow-threshold'],
	swarm: ['starter-swarm-threshold'],
	torrent: ['starter-torrent-threshold'],
	clearbody: [
		'try-boost-clear-body', 'boost-positive-filter-clear-white',
	],
	whitesmoke: [
		'try-boost-white-smoke', 'boost-positive-filter-clear-white',
	],
	hypercutter: [
		'try-boost-hyper-cutter', 'boost-tickle-hyper-cutter',
		'boost-positive-filter-hyper-keen',
	],
	keeneye: [
		'boost-flash-keen-eye', 'try-boost-keen-eye-nonaccuracy',
		'boost-positive-filter-hyper-keen',
	],
	compoundeyes: ['scalar-compound-integral', 'scalar-compound-fractional', 'scalar-compound-always-hit'],
	guts: [
		'scalar-guts-poison', 'guts-closure-paralysis-strength',
		'guts-closure-sleep-snore', 'guts-closure-freeze-immobilized',
		'guts-closure-special-fire-blast', 'guts-closure-poison-black-belt',
	],
	hugepower: ['scalar-huge-power'],
	hustle: ['scalar-hustle'],
	purepower: ['scalar-pure-power'],
	stickyhold: ['item-knock-off-sticky-hold', 'item-trick-sticky-preaccuracy'],
	owntempo: ['confusion-own-tempo'],
	shielddust: ['confusion-secondary-shield-dust'],
	chlorophyll: ['weather-chlorophyll-order'],
	cloudnine: ['weather-cloud-nine-switch'],
	raindish: [
		'weather-rain-dish-order', 'weather-rain-dish-clamp-full',
		'weather-rain-dish-suppressed', 'weather-rain-dish-switch',
	],
	sandstream: ['weather-sand-stream-start'],
	swiftswim: [
		'weather-swift-swim-order', 'weather-swift-swim-tie',
		'weather-swift-swim-suppressed',
	],
	levitate: ['derived-levitate-bone-rush-immunity', 'derived-levitate-earthquake-immunity'],
	waterabsorb: ['derived-water-absorb-try-hit', 'derived-water-absorb-heal'],
	voltabsorb: [
		'volt-absorb-thunderbolt-heal', 'volt-absorb-thunderbolt-full',
		'volt-absorb-thunder-wave-exclusion',
	],
	thickfat: ['thick-fat-firepunch', 'thick-fat-icepunch', 'thick-fat-psychic'],
	marvelscale: [
		'marvel-scale-physical-control', 'marvel-scale-physical-paralyzed',
		'marvel-scale-special-paralyzed', 'marvel-scale-critical-paralyzed',
		'marvel-scale-switch-persistence',
	],
	immunity: ['status-ability-rotation'],
	insomnia: ['status-ability-rotation', 'yawn-insomnia-block',
		'insomnia-update-skill-swap'],
	vitalspirit: ['status-ability-rotation', 'yawn-vital-spirit-block',
		'vital-spirit-trace-update'],
	limber: ['status-ability-rotation'],
	waterveil: ['status-ability-rotation'],
	magmaarmor: ['status-ability-rotation'],
	synchronize: [
		'synchronize-burn-reflection', 'synchronize-sleep-excluded',
		'synchronize-toxic-normalizes-poison', 'synchronize-source-immunity',
		'synchronize-source-occupied',
	],
	serenegrace: ['grouped-ancient-power-serene-grace'],
	innerfocus: ['flinch-inner-focus'],
	battlearmor: ['critical-battle-armor-cancel'],
	shellarmor: ['critical-shell-armor-cancel'],
	naturalcure: ['natural-cure-switch-out'],
	earlybird: ['sleep-lifecycle-early-bird'],
	rockhead: [
		'recoil-rock-head-prevention', 'recoil-rock-head-struggle',
	],
	shedskin: [
		'shed-skin-brn-cure', 'shed-skin-brn-preserve',
		'shed-skin-par-cure', 'shed-skin-par-preserve',
		'shed-skin-psn-cure', 'shed-skin-psn-preserve',
		'shed-skin-tox-cure', 'shed-skin-tox-preserve',
		'shed-skin-frz-cure', 'shed-skin-frz-preserve',
		'shed-skin-no-status', 'shed-skin-ko-before-residual',
	],
	speedboost: [
		'speed-boost-initial-active', 'speed-boost-switch-delay',
		'speed-boost-before-toxic-ko', 'speed-boost-stage-cap',
	],
	intimidate: [
		'intimidate-initial-faster', 'intimidate-initial-slower',
		'intimidate-initial-tie', 'intimidate-initial-tie-flipped',
	],
	trace: ['trace-reentry-intimidate'],
	oblivious: [
		'attract-oblivious-immunity', 'attract-oblivious-taunt-negative',
		'attract-oblivious-role-play-update',
	],
	colorchange: [
		'color-change-flying-ground', 'color-change-steel-stab-control',
		'color-change-steel-toxic-immunity', 'color-change-steel-sand-immunity',
		'color-change-switch-restoration', 'color-change-substitute-no-activation',
		'color-change-multihit-substitute',
	],
	cutecharm: ['cute-charm-contact'],
	pressure: [
		'pressure-basic', 'pressure-protect', 'pressure-immunity',
		'pressure-miss', 'pressure-spikes', 'snatch-pressure-howl',
		'berry-cure-switch-persistence',
	],
};
const passiveItemIDs = [
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
const inertAbilityIDs = ['illuminate', 'pickup', 'runaway', 'stench', 'lightningrod'];
const itemCases = {
	...Object.fromEntries(passiveItemIDs.map(id => [id, [`passive-item-${id}`]])),
	quickclaw: ['quick-claw-activation', 'quick-claw-failure'],
	focusband: ['focus-band-lethal-success', 'focus-band-lethal-failure',
		'focus-band-nonlethal-draw'],
	leppaberry: ['leppa-exact-ten-nonfirst', 'leppa-delayed-acquisition-first-zero'],
	kingsrock: ['kings-rock-tackle-success', 'kings-rock-tackle-failure',
		'kings-rock-shield-dust', 'kings-rock-arm-thrust-per-hit',
		'kings-rock-serene-grace-order'],
	shellbell: ['shell-bell-single-hit', 'shell-bell-multihit-aggregate',
		'shell-bell-overkill-cap', 'shell-bell-substitute-zero'],
	poisonbarb: ['type-boost-poison-barb-sludge'],
	spelltag: ['type-boost-spell-tag-shadow-ball'],
	magnet: ['type-boost-magnet-thunderbolt'],
	nevermeltice: ['type-boost-never-melt-ice-ice-beam'],
	twistedspoon: ['type-boost-twisted-spoon-psychic'],
	scopelens: ['critical-scope-lens'],
	luckypunch: ['critical-lucky-punch-chansey', 'critical-lucky-punch-mismatch'],
	stick: ['critical-stick-farfetchd', 'critical-stick-mismatch'],
	thickclub: ['scalar-thick-club-marowak', 'scalar-thick-club-cubone'],
	deepseascale: ['stat-item-deep-sea-scale', 'stat-item-deep-sea-scale-guard'],
	deepseatooth: ['stat-item-deep-sea-tooth', 'stat-item-deep-sea-tooth-guard'],
	lightball: ['stat-item-light-ball-special', 'stat-item-light-ball-physical-control'],
	machobrace: ['stat-item-macho-brace', 'stat-item-macho-brace-control'],
	metalpowder: ['stat-item-metal-powder', 'stat-item-metal-powder-guard'],
	souldew: ['stat-item-soul-dew-legal-noop'],
	mail: ['item-covet-mail-transfer', 'item-trick-mail-rollback'],
	aguavberry: ['berry-flavor-aguav-disliked', 'berry-flavor-aguav-neutral',
		'berry-flavor-dual-holder-order'],
	figyberry: ['berry-flavor-figy-disliked', 'berry-flavor-figy-neutral',
		'berry-flavor-own-tempo', 'berry-flavor-substitute-irrelevant',
		'berry-flavor-switch-item-state'],
	iapapaberry: ['berry-flavor-iapapa-disliked', 'berry-flavor-iapapa-neutral'],
	magoberry: ['berry-flavor-mago-disliked', 'berry-flavor-mago-neutral',
		'berry-flavor-dual-holder-order'],
	wikiberry: ['berry-flavor-wiki-disliked', 'berry-flavor-wiki-neutral'],
	lumberry: [
		'berry-lum-primary-status', 'berry-lum-secondary-status',
		'berry-lum-status-then-confusion', 'berry-lum-confusion-update',
		'berry-lum-status-mismatch-no-double-eat', 'berry-lum-own-tempo',
		'berry-lum-status-prevention', 'berry-lum-switch-persistence',
	],
	persimberry: [
		'berry-persim-primary-update', 'berry-persim-secondary-delayed-update',
		'berry-persim-status-mismatch', 'berry-persim-switch-persistence',
		'berry-persim-own-tempo', 'berry-persim-substitute',
	],
	cheriberry: ['berry-cure-post-move-rotation', 'berry-cure-toxic-mismatch'],
	chestoberry: ['berry-cure-post-move-rotation'],
	pechaberry: ['berry-cure-post-move-rotation', 'berry-cure-toxic-mismatch'],
	rawstberry: ['berry-cure-switch-persistence'],
	aspearberry: ['berry-cure-switch-persistence'],
	oranberry: ['berry-oran-threshold', 'berry-oran-above-threshold', 'berry-oran-consume-switch'],
	sitrusberry: ['berry-sitrus-threshold', 'berry-sitrus-rain-dish-order'],
	liechiberry: ['berry-liechi-threshold', 'berry-pinch-dual-holder-order', 'berry-pinch-clear-body-positive'],
	ganlonberry: ['berry-ganlon-threshold', 'berry-pinch-dual-holder-order'],
	salacberry: ['berry-salac-threshold'],
	petayaberry: ['berry-petaya-threshold'],
	apicotberry: ['berry-apicot-threshold'],
	lansatberry: [
		'berry-lansat-threshold', 'berry-lansat-above-threshold',
		'berry-lansat-focus-energy-duplicate',
	],
	starfberry: [
		'berry-starf-stat-0', 'berry-starf-stat-1', 'berry-starf-stat-2',
		'berry-starf-stat-3', 'berry-starf-stat-4',
		'berry-starf-above-threshold',
	],
	mentalherb: [
		'item-mental-herb-attract', 'item-mental-herb-no-attract',
		'item-mental-herb-same-gender-immunity',
		'item-mental-herb-encore-not-cured', 'item-mental-herb-cute-charm',
		'item-mental-herb-recycle',
	],
	whiteherb: [
		'item-white-herb-after-move', 'item-white-herb-miss-control',
		'item-white-herb-start-consumes', 'item-white-herb-start-order-control',
		'item-white-herb-any-switch-in', 'item-white-herb-residual',
	],
	choiceband: [
		'item-choice-band-connected-lock', 'item-choice-band-miss-lock',
		'item-choice-band-status-lock', 'item-choice-band-switch-reset',
	],
	leftovers: ['leftovers-basic-clamp', 'leftovers-burn-order'],
	blackbelt: ['black-belt-mach-punch'],
	hardstone: ['ordinary-attack-rockthrow'],
	metalcoat: ['type-boost-metal-coat-steel-wing'],
	sharpbeak: ['type-boost-sharp-beak-wing-attack'],
	silkscarf: ['type-boost-silk-scarf-scratch'],
	silverpowder: ['ordinary-attack-megahorn'],
	softsand: ['type-boost-soft-sand-earthquake'],
	blackglasses: ['type-boost-black-glasses-thief'],
	charcoal: ['type-boost-charcoal-ember'],
	dragonfang: ['ordinary-attack-dragonclaw'],
	miracleseed: ['type-boost-miracle-seed-giga-drain'],
	mysticwater: ['type-boost-mystic-water-surf'],
	seaincense: ['type-boost-sea-incense-surf'],
};
/* Executable IDs are only an ABI/catalog fact.  This allow-list is the
 * descriptor-level semantic claim, with the differential cases that exercise
 * the move's supported families.  In particular, a newly generated native ID
 * must remain unsupported until it is added here deliberately. */
const lockOnCases = [
	'lock-on-alias-repeat-accuracy', 'lock-on-semi-invulnerable',
	'lock-on-protect-and-immunity', 'lock-on-switch-relations',
];
const fakeOutCases = [
	'fake-out-pressure-ghost-repeat', 'fake-out-flinched-action-counts',
	'fake-out-switch-reset',
];
const happinessPowerCases = [
	'happiness-return-default', 'happiness-frustration-import-default',
	'happiness-return-zero', 'happiness-frustration-max',
	'happiness-return-midpoint', 'happiness-frustration-midpoint',
];
const delayedFutureMoveCases = [
	'future-sight-shared-collision-switch-protect-hit',
	'doom-desire-endure-expiry-miss',
	'wish-futuremove-coexist-switch-residual-order',
	'futuremove-fainted-occupant-no-accuracy',
	'futuremove-terminal-winner',
	'doom-desire-lethal-forced-replacement',
];
const futureSightCases = [
	'future-sight-shared-collision-switch-protect-hit',
	'wish-futuremove-coexist-switch-residual-order',
	'futuremove-fainted-occupant-no-accuracy',
	'futuremove-terminal-winner',
];
const doomDesireCases = [
	'future-sight-shared-collision-switch-protect-hit',
	'doom-desire-endure-expiry-miss',
	'doom-desire-lethal-forced-replacement',
];
const delayedWishCases = ['wish-futuremove-coexist-switch-residual-order'];
const snatchCases = [
	'snatch-howl-steal', 'snatch-calm-mind', 'snatch-pressure-howl',
	'snatch-ineligible-expiry', 'direct-heal-snatch-steal',
	'critical-focus-energy-snatched',
	'weather-recovery-moonlight-snatch',
	'weather-recovery-morningsun-snatch',
	'weather-recovery-synthesis-snatch',
];
const counterCases = [
	'retaliation-counter-fixed-physical',
	'retaliation-wrong-class-failure',
	'retaliation-miss-no-history',
	'retaliation-substitute-no-history',
	'retaliation-multihit-last-hit',
	'retaliation-response-type-immunity',
	'retaliation-source-faint-cancels-action',
	'retaliation-weather-ball-clear-counter',
	'retaliation-weather-ball-rain-counter',
	'retaliation-overkill-requested-damage',
	'hidden-power-counter-special-type',
];
const mirrorCoatCases = [
	'retaliation-mirror-coat-fixed-special',
	'retaliation-wrong-class-failure',
	'retaliation-incoming-type-immunity',
	'retaliation-weather-ball-clear-mirror-coat',
	'retaliation-weather-ball-rain-mirror-coat',
	'retaliation-delayed-future-sight-provenance',
	'hidden-power-mirror-coat-rejects',
];
const retaliationCases = [...new Set([...counterCases, ...mirrorCoatCases])];
const ohkoCases = [
	'ohko-fissure-forced-replacement', 'ohko-guillotine-miss',
	'ohko-horn-drill-substitute', 'ohko-lock-on-guillotine',
	'ohko-sheer-cold-ice-target', 'ohko-sheer-cold-level-gate',
	'ohko-sheer-cold-sturdy', 'metronome-fissure-flying',
];
const skillSwapCases = [
	'skill-swap-flash-fire-end', 'skill-swap-intimidate-no-start',
	'skill-swap-protect-block', 'skill-swap-same-ability-failure',
	'skill-swap-substitute-bypass', 'skill-swap-switch-restores-base',
	'skill-swap-wonder-guard-failure',
];
const bideCases = [
	'bide-core-additive', 'bide-no-damage', 'bide-protect-release',
	'bide-substitute-release', 'bide-ghost-immunity',
	'bide-source-switch-retarget', 'bide-forced-drag-cleanup',
	'bide-source-faint-retarget', 'bide-paralysis-abort',
];
const furyCutterCases = [
	'fury-cutter-ramp-cap', 'fury-cutter-miss-expires',
	'fury-cutter-protect-expires', 'fury-cutter-wonder-guard-expires',
	'fury-cutter-source-switch-reset',
];
const lockedRampCases = [
	'rollout-defense-curl-cycle', 'rollout-miss-immobilize-reset',
	'rollout-protect-ko-replace-roar-reset', 'ice-ball-defense-curl-cycle',
	'ice-ball-miss-immobilize-reset', 'ice-ball-wonder-guard-reset',
];
const stockpileCases = [
	'stockpile-cap-spit-up', 'stockpile-switch-clears',
	'spit-up-immune-consumes', 'spit-up-without-stockpile',
	'swallow-layer-1', 'swallow-layer-2', 'swallow-layer-3',
	'swallow-full-hp-cleanup',
	'swallow-without-stockpile', 'metronome-spit-up-after-move',
	'snatch-stockpile-transfer', 'snatch-swallow-gen3-rejection',
];
const rageCases = ['rage-lifecycle-basis', 'rage-no-install-on-miss'];
const minimizeCases = ['metronome-minimize-flagged-damage'];
const destinyBondCases = [
	'destiny-bond-direct-move-ko', 'destiny-bond-before-move-cleanup',
	'destiny-bond-consecutive-refresh', 'destiny-bond-move-aborted-cleanup',
	'destiny-bond-indirect-faint-exclusion',
	'destiny-bond-future-sight-exclusion',
	'destiny-bond-doom-desire-exclusion',
];
const grudgeCases = [
	'grudge-direct-move-ko', 'grudge-before-move-cleanup',
	'grudge-source-fainted-exclusion', 'grudge-indirect-faint-exclusion',
	'grudge-future-sight-exclusion', 'grudge-doom-desire-exclusion',
];
const uproarCases = [
	'uproar-wake-rest-duration2-expiry', 'uproar-duration5-rest-block',
	'uproar-protect-no-install', 'uproar-ghost-sleeper-immunity',
	'uproar-holder-sleep-nonsleep-recombination',
	'uproar-forced-drag-silent-cleanup',
	'uproar-poison-faint-residual-order', 'uproar-accuracy-miss-no-wake',
	'uproar-substitute-wakes-before-intercept',
	'metronome-uproar-absent-slot-lock', 'sleep-talk-excludes-uproar',
];
const imprisonCases = [
	'imprison-queued-shared-move-cancel', 'imprison-no-shared-move-fails',
	'imprison-all-shared-forces-struggle', 'imprison-source-switch-clears',
	'imprison-foe-switch-reprojects',
];
const specializedMultihitCases = [
	'triple-kick-per-hit-complete', 'triple-kick-per-hit-stop',
	'twineedle-per-hit-poison', 'twineedle-poison-immunity',
];
const secretPowerCases = [
	'secret-power-secondary-a', 'secret-power-secondary-b',
];
const presentCases = [
	'present-accuracy-miss', 'present-damage-120', 'present-damage-40',
	'present-damage-80', 'present-damage-substitute',
	'present-ghost-immunity', 'present-heal-full-hp-failure',
	'present-heal-substitute-blocked', 'present-protect',
	'present-weighted-heal',
];
const freezeClauseCases = [
	'freeze-clause-first-foe-freeze',
	'freeze-clause-frozen-bench-rejects',
	'freeze-clause-cure-readmits',
];
const curseCases = [
	'curse-nonghost-self-profile', 'curse-ghost-lifecycle',
	'curse-ghost-duplicate-rejects', 'curse-ghost-substitute-block',
	'curse-ghost-protect-nonblock', 'curse-source-switch-independent',
	'curse-target-switch-teardown',
];
const painSplitCases = [
	'pain-split-odd-floor', 'pain-split-source-max-clamp',
	'pain-split-shedinja-target-clamp', 'pain-split-protect-block',
	'pain-split-substitute-block', 'pain-split-equal-hp',
];
const mementoCases = [
	'memento-standard-force-replacement', 'memento-clear-body-still-faints',
	'memento-protect-no-faint', 'memento-substitute-no-faint',
	'memento-white-herb-before-faint', 'memento-terminal-loss',
];
const jumpKickCases = [
	'jump-kick-miss-cap-lethal', 'jump-kick-protect',
	'jump-kick-ghost-foresight', 'jump-kick-dig',
	'jump-kick-target-gone-cancel',
];
const revengeCases = [
	'revenge-no-history', 'revenge-same-turn-damage',
	'revenge-fixed-damage', 'revenge-substitute-zero-damage',
	'revenge-stale-damage', 'revenge-replacement-target',
];
const lowKickCases = [
	'low-kick-pikachu', 'low-kick-magikarp', 'low-kick-persian',
	'low-kick-skarmory', 'low-kick-slaking', 'low-kick-snorlax',
	'low-kick-gastly',
];
const transformCases = [
	'transform-substitute-hidden-power', 'transform-source-retransform',
	'transform-target-rejection', 'transform-ability-start-switch-reset',
	'transform-forecast-freeze',
];
const smellingSaltsCases = [
	'smelling-salts-clean-baseline',
	'smelling-salts-paralyzed-double-cure',
	'smelling-salts-substitute-preserves-paralysis',
];
const bellyDrumCases = [
	'belly-drum-odd-max-hp-success', 'belly-drum-even-max-hp-success',
	'belly-drum-half-hp-failure', 'belly-drum-plus-six-failure',
];
const dreamEaterCases = [
	'dream-eater-awake-rejection', 'dream-eater-sleeping-target',
	'dream-eater-full-hp-user', 'dream-eater-liquid-ooze-exception',
	'dream-eater-dark-immunity', 'dream-eater-protect',
	'dream-eater-substitute',
];
const triAttackCases = [
	'tri-attack-burn', 'tri-attack-paralysis', 'tri-attack-freeze',
	'tri-attack-secondary-fails', 'tri-attack-serene-grace',
	'tri-attack-shield-dust', 'tri-attack-substitute', 'tri-attack-protect',
	'tri-attack-ghost-immunity', 'tri-attack-status-rejected',
	'tri-attack-lethal',
];
const assistCases = [
	'assist-metronome-party-order-duplicate-weight',
	'assist-metronome-empty-noassist-pool',
];
const beatUpCases = [
	'beat-up-party-order',
	'beat-up-status-filter',
	'beat-up-typeless-ghost',
	'beat-up-zero-contributors',
];
const metronomeCases = [
	'metronome-swagger-success-selfhit', 'metronome-swagger-miss',
	'metronome-swagger-own-tempo', 'metronome-swagger-safeguard',
	...assistCases,
];
const moveCases = {
	assist: assistCases,
	beatup: beatUpCases,
	metronome: metronomeCases,
	curse: curseCases,
	painsplit: painSplitCases,
	doubleteam: ['metronome-double-team-evasion'],
	memento: mementoCases,
	jumpkick: jumpKickCases,
	highjumpkick: jumpKickCases,
	revenge: revengeCases,
	lowkick: lowKickCases,
	transform: transformCases,
	smellingsalts: smellingSaltsCases,
	bellydrum: bellyDrumCases,
	dreameater: dreamEaterCases,
	triattack: triAttackCases,
	secretpower: secretPowerCases,
	present: presentCases,
	perishsong: [
		'perish-song-duplicate-simultaneous-terminal',
		'perish-song-switch-cleanup-forced-replacement',
	],
	swagger: metronomeCases.slice(0, 4),
	fissure: ohkoCases,
	guillotine: ohkoCases,
	horndrill: ohkoCases,
	sheercold: ohkoCases,
	teleport: ['teleport-declarative-rejection'],
	leechseed: [
		'leech-seed-grass-immunity',
		'leech-seed-liquid-ooze-drain',
		'leech-seed-source-slot-and-target-switch',
		'rapid-spin-leech-seed-combined-cleanup',
		'rapid-spin-leech-seed-substitute-and-protect',
	],
	futuresight: futureSightCases,
	doomdesire: doomDesireCases,
	wish: delayedWishCases,
	bide: bideCases,
	furycutter: furyCutterCases,
	rollout: lockedRampCases,
	iceball: lockedRampCases,
	defensecurl: lockedRampCases,
	stockpile: stockpileCases,
	spitup: stockpileCases,
	swallow: stockpileCases,
	rage: rageCases,
	minimize: minimizeCases,
	snatch: snatchCases,
	counter: counterCases,
	mirrorcoat: mirrorCoatCases,
	hiddenpower: [
		'hidden-power-dark70-special-effective',
		'hidden-power-dark30-power-floor',
		'hidden-power-ground70-physical-stab-effective',
		'hidden-power-electric-ground-immunity',
		'hidden-power-counter-special-type',
		'hidden-power-mirror-coat-rejects',
	],
	fakeout: fakeOutCases,
	return: happinessPowerCases,
	frustration: happinessPowerCases,
	lockon: lockOnCases,
	mindreader: lockOnCases,
	foresight: ['foresight-immunity-core', 'foresight-wonder-guard-independent'],
	odorsleuth: ['odor-sleuth-immunity-alias', 'foresight-wonder-guard-independent'],
	naturepower: ['nature-power-fixed-swift-protect'],
	mimic: ['mimic-copy-switch-reset'],
	sketch: ['sketch-copy-switch-persistence'],
	sleeptalk: [
		'sleep-talk-current-slot-call', 'sleep-talk-awake-rejection',
		'sleep-talk-no-eligible-slot',
		'sleep-talk-choice-lock-subsequent-rejection',
		'sleep-talk-encore-subsequent-rejection',
	],
	nightmare: [
		'nightmare-awake-rejection', 'nightmare-sleep-residual',
		'nightmare-wake-cleanup', 'nightmare-switch-cleanup',
		'nightmare-shed-skin-order',
	],
	snore: [
		'sleep-lifecycle-snore', 'sleep-lifecycle-snore-awake-fail',
	],
	taunt: ['choice-taunt-filter'],
	disable: [
		'choice-disable-fast', 'choice-disable-slow', 'choice-disable-switch',
		'choice-disable-no-last-move', 'choice-disable-zero-pp-start',
		'choice-disable-duplicate', 'choice-disable-protect',
		'choice-disable-substitute', 'choice-disable-immune-last-move',
	],
	encore: [
		'choice-encore-preaction', 'choice-encore-postaction-switch',
		'choice-encore-pp-zero', 'choice-encore-duplicate',
	],
	torment: ['choice-torment-cycle', 'choice-torment-switch'],
	aerialace: ['always-hit-rotation-1'],
	bind: ['partial-trap-bind-source-switch', 'partial-trap-duplicate-no-redraw'],
	clamp: ['partial-trap-clamp-rotation'],
	firespin: ['partial-trap-fire-spin-rotation'],
	whirlpool: ['partial-trap-whirlpool-rotation'],
	sandtomb: ['partial-trap-sand-tomb-rotation'],
	rapidspin: [
		'partial-trap-rapid-spin-cleanup',
		'rapid-spin-leech-seed-combined-cleanup',
		'rapid-spin-leech-seed-substitute-and-protect',
	],
	brickbreak: ['brick-break-both-screens', 'brick-break-miss',
		'brick-break-protect', 'brick-break-substitute',
		'brick-break-type-immune'],
	wrap: ['partial-trap-wrap-rotation'],
	explosion: [
		'self-destruct-protect', 'self-destruct-miss',
		'self-destruct-substitute', 'self-destruct-terminal-tie',
		'self-destruct-double-replacement',
	],
	selfdestruct: [
		'self-destruct-connected', 'self-destruct-ghost-immunity',
	],
	focusenergy: [
		'critical-focus-energy', 'critical-focus-energy-duplicate',
		'critical-focus-energy-switch-cleanup', 'critical-focus-energy-snatched',
	],
	thief: ['item-thief-transfer'],
	covet: ['item-covet-mail-transfer'],
	knockoff: ['item-knock-off-lockout', 'item-knock-off-sticky-hold'],
	recycle: ['item-recycle-consumed-berry'],
	trick: ['item-trick-swap', 'item-trick-source-empty',
		'item-trick-empty-fail', 'item-trick-sticky-preaccuracy',
		'item-trick-mail-rollback', 'item-trick-protect', 'item-trick-miss',
		'item-trick-source-knocked-off', 'item-trick-target-knocked-off'],
	solarbeam: [
		'solar-beam-clear-charge-release', 'solar-beam-sun-immediate',
		'solar-beam-rain-half', 'solar-beam-sand-half', 'solar-beam-hail-half',
		'solar-beam-clear-to-rain', 'solar-beam-cloud-nine-sun',
		'solar-beam-release-protect', 'solar-beam-release-paralysis',
	],
	bounce: ['two-turn-bounce-release', 'bounce-gust-double',
		'bounce-sky-uppercut-bypass'],
	dig: ['two-turn-dig-release', 'dig-earthquake-double',
		'dig-sandstorm-immunity', 'dig-hail-immunity',
		'magnitude-dig-double'],
	dive: ['two-turn-dive-release', 'dive-surf-double',
		'dive-sandstorm-immunity', 'dive-hail-immunity'],
	fly: ['fly-airborne-miss-release', 'fly-release-protect',
		'fly-release-switch', 'fly-thunder-paralysis-abort',
		'fly-twister-double', 'fly-sandstorm-not-immune'],
	gust: ['bounce-gust-double'],
	razorwind: ['two-turn-razorwind-release'],
	skullbash: ['two-turn-skullbash-release'],
	skyattack: ['two-turn-skyattack-release'],
	skyuppercut: ['bounce-sky-uppercut-bypass'],
	magnitude: [
		'magnitude-level-4', 'magnitude-level-5', 'magnitude-level-6',
		'magnitude-level-7', 'magnitude-level-8', 'magnitude-level-9',
		'magnitude-level-10', 'magnitude-dig-double',
	],
	mudsport: [
		'sport-mud-own-match-mismatch', 'sport-mud-duplicate-stack',
		'sport-mud-switch-cleanup',
	],
	watersport: ['sport-water-opposing-match-mismatch'],
	thunder: [
		'thunder-clear-hit-secondary-success', 'thunder-clear-miss',
		'thunder-secondary-failure', 'thunder-rain', 'thunder-sun',
		'thunder-sand', 'thunder-hail', 'thunder-cloud-nine',
		'thunder-replacement-expiry', 'thunder-protect',
		'thunder-substitute', 'thunder-limber-prevention',
	],
	weatherball: [
		'weather-ball-clear', 'weather-ball-sun', 'weather-ball-rain',
		'weather-ball-sand', 'weather-ball-hail', 'weather-ball-cloud-nine',
		'weather-ball-replacement-expiry', 'weather-ball-stab-effectiveness',
		'weather-ball-category', 'weather-ball-protect',
		'weather-ball-substitute', 'weather-ball-type-item',
	],
	moonlight: ['weather-recovery-moonlight-neutral', 'weather-recovery-moonlight-sun', 'weather-recovery-moonlight-rain', 'weather-recovery-moonlight-sand', 'weather-recovery-moonlight-hail', 'weather-recovery-moonlight-full', 'weather-recovery-moonlight-snatch'],
	morningsun: ['weather-recovery-morningsun-neutral', 'weather-recovery-morningsun-sun', 'weather-recovery-morningsun-rain', 'weather-recovery-morningsun-sand', 'weather-recovery-morningsun-hail', 'weather-recovery-morningsun-full', 'weather-recovery-morningsun-snatch'],
	synthesis: ['weather-recovery-synthesis-neutral', 'weather-recovery-synthesis-sun', 'weather-recovery-synthesis-rain', 'weather-recovery-synthesis-sand', 'weather-recovery-synthesis-hail', 'weather-recovery-synthesis-full', 'weather-recovery-synthesis-snatch', 'weather-recovery-cloud-nine-suppression', 'weather-recovery-replacement-expiry'],
	outrage: [
		'locked-outrage-duration2', 'locked-outrage-duration3',
		'locked-outrage-protect', 'locked-outrage-ko-replacement',
		'locked-outrage-opponent-switch',
	],
	petaldance: ['locked-petal-dance-duration2'],
	thrash: ['locked-thrash-duration2', 'locked-thrash-immunity'],
	teeterdance: [
		'teeterdance-success-duration-action', 'teeterdance-own-tempo-cancel',
		'teeterdance-substitute-block', 'teeterdance-protect-block',
		'teeterdance-switch-clear-reapply',
	],
	flatter: [
		'flatter-success-order-duration', 'flatter-own-tempo-partial-success',
		'flatter-substitute-block', 'flatter-protect-block',
		'flatter-boost-cap', 'flatter-clear-body-positive',
	],
	confuseray: [
		'confusion-primary-self-hit', 'confusion-protect-block',
		'confusion-substitute-block', 'confusion-own-tempo',
		'confusion-switch-clear',
	],
	supersonic: ['confusion-supersonic-miss'],
	sweetkiss: ['confusion-sweet-kiss-action-success'],
	confusion: [
		'confusion-secondary-confusion-success',
		'confusion-secondary-chance-failure',
	],
	psybeam: ['confusion-secondary-psybeam-success'],
	signalbeam: ['confusion-secondary-signalbeam-success'],
	dizzypunch: ['confusion-secondary-dizzypunch-success'],
	waterpulse: [
		'confusion-secondary-waterpulse-success',
		'confusion-secondary-protect', 'confusion-secondary-substitute',
		'confusion-secondary-immunity', 'confusion-secondary-own-tempo',
	],
	dynamicpunch: [
		'confusion-secondary-dynamicpunch-success',
		'confusion-secondary-dynamic-punch-miss',
		'confusion-secondary-shield-dust',
	],
	acid: ['secondary-acid'],
	aurorabeam: ['secondary-aurorabeam'],
	blizzard: ['secondary-blizzard'],
	bubble: ['secondary-bubble'],
	bubblebeam: ['secondary-bubblebeam'],
	constrict: ['secondary-constrict'],
	crunch: ['secondary-crunch'],
	crushclaw: ['secondary-crushclaw'],
	dragonbreath: ['secondary-dragonbreath'],
	fireblast: ['secondary-fireblast'],
	firepunch: ['secondary-firepunch'],
	flamethrower: ['secondary-flamethrower'],
	flamewheel: ['secondary-flamewheel'],
	heatwave: ['secondary-heatwave'],
	icebeam: ['secondary-icebeam'],
	icepunch: ['secondary-icepunch'],
	icywind: ['secondary-icywind', 'secondary-icywind-substitute'],
	irontail: ['secondary-irontail'],
	lick: ['secondary-lick'],
	metalclaw: ['secondary-metalclaw', 'secondary-metalclaw-substitute'],
	meteormash: ['secondary-meteormash'],
	mudshot: ['secondary-mudshot'],
	mudslap: ['secondary-mudslap'],
	octazooka: ['secondary-octazooka'],
	poisonfang: ['secondary-poisonfang'],
	poisonsting: ['secondary-poisonsting'],
	powdersnow: ['secondary-powdersnow'],
	sacredfire: ['secondary-sacredfire'],
	psychic: ['secondary-psychic'],
	rocksmash: ['secondary-rocksmash'],
	rocktomb: ['secondary-rocktomb'],
	recover: [
		'direct-heal-recover-odd', 'direct-heal-recover-clamp',
		'direct-heal-recover-full', 'direct-heal-protect-irrelevant',
		'direct-heal-substitute-irrelevant', 'direct-heal-burn-residual',
		'direct-heal-switch-persistence', 'direct-heal-snatch-steal',
	],
	milkdrink: [
		'direct-heal-milk-drink-odd', 'direct-heal-milk-drink-clamp',
		'direct-heal-milk-drink-full',
	],
	slackoff: [
		'direct-heal-slack-off-odd', 'direct-heal-slack-off-clamp',
		'direct-heal-slack-off-full',
	],
	softboiled: [
		'direct-heal-soft-boiled-odd', 'direct-heal-soft-boiled-clamp',
		'direct-heal-soft-boiled-full',
	],
	shadowball: ['secondary-shadowball'],
	lusterpurge: ['secondary-lusterpurge'],
	mistball: ['secondary-mistball'],
	muddywater: ['secondary-muddywater'],
	sludge: ['secondary-sludge'],
	sludgebomb: ['secondary-sludgebomb'],
	smog: ['secondary-smog'],
	spark: ['secondary-spark'],
	thunderbolt: ['secondary-thunderbolt'],
	thunderpunch: ['secondary-thunderpunch'],
	thundershock: ['secondary-thundershock'],
	zapcannon: ['secondary-zapcannon'],
	glare: ['status-primary-rotation'],
	grasswhistle: ['status-primary-rotation'],
	hypnosis: ['status-primary-rotation'],
	lovelykiss: ['status-primary-rotation'],
	poisongas: ['status-primary-rotation'],
	poisonpowder: ['status-primary-rotation'],
	sing: ['status-primary-rotation-2'],
	sleeppowder: ['status-primary-rotation-2'],
	spore: ['status-primary-rotation-2'],
	stunspore: ['status-primary-rotation-2'],
	thunderwave: ['status-primary-rotation-2'],
	willowisp: ['status-primary-rotation-2'],
	acidarmor: ['boost-rotation-1'],
	agility: ['boost-rotation-1', 'boost-agility-queue-order'],
	amnesia: ['boost-rotation-1'],
	barrier: ['boost-rotation-1'],
	bodyslam: ['secondary-immunity-no-roll'],
	bonerush: ['multihit-bone-rush-two', 'multihit-bone-rush-five', 'multihit-bone-rush-early-ko'],
	armthrust: ['multihit-rotation-armthrust'],
	barrage: ['multihit-rotation-barrage'],
	bonemerang: ['multihit-rotation-bonemerang'],
	bulletseed: ['multihit-rotation-bulletseed'],
	cometpunch: ['multihit-rotation-cometpunch'],
	doublekick: ['multihit-rotation-doublekick'],
	doubleslap: ['multihit-rotation-doubleslap'],
	furyattack: ['multihit-rotation-furyattack'],
	furyswipes: ['multihit-rotation-furyswipes'],
	iciclespear: ['multihit-rotation-iciclespear'],
	pinmissile: ['multihit-rotation-pinmissile'],
	rockblast: ['multihit-rotation-rockblast'],
	spikecannon: ['multihit-rotation-spikecannon'],
	leafblade: ['high-crit-rotation-1'],
	crabhammer: ['high-crit-rotation-1'],
	aircutter: ['high-crit-rotation-1'],
	karatechop: ['high-crit-rotation-1'],
	aeroblast: ['high-crit-rotation-2'],
	blazekick: ['high-crit-rotation-2', 'secondary-blazekick'],
	crosschop: ['high-crit-rotation-2'],
	poisontail: ['high-crit-rotation-3', 'secondary-poisontail'],
	razorleaf: ['high-crit-rotation-3'],
	slash: ['high-crit-rotation-3'],
	astonish: ['flinch-rotation-1'],
	extrasensory: ['flinch-rotation-1'],
	needlearm: ['flinch-rotation-1'],
	boneclub: ['flinch-rotation-1'],
	hyperfang: ['flinch-rotation-2'],
	rollingkick: ['flinch-rotation-2'],
	bite: ['flinch-rotation-2'],
	headbutt: ['flinch-rotation-2'],
	rockslide: ['flinch-rotation-3'],
	stomp: ['flinch-rotation-3'],
	twister: ['flinch-rotation-3'],
	bulkup: ['boost-bulk-up-downstream', 'boost-cap-failure'],
	calmmind: ['boost-rotation-2', 'snatch-calm-mind'],
	charm: ['boost-rotation-5'],
	cut: ['ordinary-attack-cut'],
	cosmicpower: ['boost-rotation-2'],
	cottonspore: ['boost-rotation-5'],
	dragondance: ['boost-rotation-2'],
	doubleedge: ['recoil-double-edge-baseline', 'recoil-ko-forced-replacement', 'recoil-rock-head-prevention'],
	absorb: ['drain-family-rotation'],
	megadrain: ['drain-family-rotation'],
	leechlife: ['drain-family-rotation'],
	dragonclaw: ['ordinary-attack-dragonclaw'],
	drillpeck: ['ordinary-attack-drillpeck'],
	earthquake: ['derived-grounded-earthquake', 'derived-flying-earthquake-immunity', 'derived-levitate-earthquake-immunity'],
	eggbomb: ['ordinary-attack-eggbomb'],
	ember: ['secondary-ember-success', 'secondary-ember-failure', 'secondary-protect-block'],
	gigadrain: ['drain-giga-drain-exact', 'drain-giga-drain-clamp', 'drain-giga-drain-overkill'],
	sonicboom: ['fixed-literal-sonic-boom'],
	dragonrage: ['fixed-literal-dragon-rage'],
	superfang: ['target-relative-formulas', 'target-relative-substitute'],
	endeavor: ['target-relative-formulas', 'target-relative-substitute'],
	psywave: ['psywave-accuracy-miss', 'psywave-protect',
		'psywave-random-level-percent', 'psywave-substitute'],
	hyperbeam: ['recharge-connected'],
	blastburn: ['recharge-blast-burn'],
	frenzyplant: ['recharge-frenzy-plant'],
	hydrocannon: ['recharge-hydro-cannon'],
	extremespeed: ['priority-extreme-speed'],
	faketears: ['boost-rotation-5'],
	facade: ['facade-clean', 'facade-paralyzed'],
	refresh: ['refresh-clean-fail', 'refresh-burn', 'refresh-poison', 'refresh-toxic'],
	psychup: ['psych-up-mixed-replacement', 'psych-up-protect-ghost',
		'psych-up-substitute-bypass'],
	overheat: ['self-drop-connected-rotation'],
	psychoboost: ['self-drop-connected-rotation'],
	superpower: ['self-drop-connected-rotation'],
	submission: ['recoil-trio-rotation'],
	takedown: ['recoil-trio-rotation'],
	volttackle: ['recoil-trio-rotation'],
	haze: ['haze-both-products', 'haze-substitute-bypass',
		'haze-pressure-staging', 'haze-neutral-product'],
	rest: ['rest-clean-damaged', 'rest-full-hp-fail',
		'rest-insomnia-fail', 'rest-replace-toxic'],
	ancientpower: ['grouped-ancient-power-control',
		'grouped-ancient-power-serene-grace'],
	silverwind: ['grouped-silver-wind-success'],
	feintattack: ['always-hit-rotation-1'],
	featherdance: ['boost-rotation-6'],
	flash: ['boost-rotation-6', 'boost-flash-keen-eye', 'boost-accuracy-flash-below', 'boost-accuracy-flash-at'],
	growl: ['boost-growl-switch-reset'],
	growth: ['boost-rotation-3'],
	harden: ['boost-rotation-3'],
	helpinghand: ['target-adjacent-ally-no-target'],
	hornattack: ['ordinary-attack-hornattack'],
	hydropump: ['ordinary-attack-hydropump'],
	hail: ['weather-hail-lifecycle'],
	magiccoat: ['magic-coat-growl-reflection'],
	magicalleaf: ['always-hit-rotation-1'],
	howl: ['boost-rotation-3', 'snatch-howl-steal'],
	irondefense: ['boost-rotation-3'],
	kinesis: ['boost-rotation-6'],
	leer: ['boost-rotation-9'],
	meditate: ['boost-rotation-4'],
	metalsound: ['boost-rotation-6'],
	mirrormove: ['mirror-move-growl-called', 'mirror-move-no-history'],
	machpunch: ['modify-attack-baseline', 'black-belt-mach-punch'],
	megahorn: ['ordinary-attack-megahorn'],
	megakick: ['ordinary-attack-megakick'],
	megapunch: ['derived-accuracy-miss'],
	nightshade: ['fixed-night-shade-level', 'fixed-night-shade-normal-immunity'],
	protect: ['protect-stall-chain', 'protect-switch-reset',
		'protect-status-accuracy-staging',
		'detect-protect-endure-shared-stall-success'],
	detect: ['detect-protect-endure-shared-stall-success',
		'detect-endure-shared-stall-failure'],
	endure: ['detect-protect-endure-shared-stall-success',
		'detect-endure-shared-stall-failure', 'endure-fixed-move-damage',
		'endure-multihit-each-hit'],
	peck: ['ordinary-attack-peck'],
	pound: ['ordinary-attack-pound'],
	payday: ['pay-day-connected', 'pay-day-protect', 'pay-day-substitute'],
	quickattack: ['gen3-singles2-complete'],
	raindance: ['weather-rain-lifecycle', 'weather-sun-replacement', 'weather-rain-water-damage', 'weather-rain-fire-damage'],
	reflect: ['reflect-physical-half', 'reflect-critical-bypass',
		'reflect-duration-switch', 'screen-attacker-side-no-effect',
		'screen-dual-category-routing'],
	lightscreen: ['light-screen-special-half', 'screen-dual-category-routing'],
	mist: ['mist-lifecycle-filter'],
	safeguard: ['safeguard-lifecycle-status-confusion', 'yawn-safeguard-block',
		'yawn-lifecycle-safeguard-bypass'],
	yawn: ['yawn-lifecycle-safeguard-bypass', 'yawn-safeguard-block',
		'yawn-existing-status-block', 'yawn-insomnia-block'],
	spikes: ['spikes-layers-cap-immunity', 'spikes-switch-ko-forced-replacement'],
	reversal: ['reversal-bracket-20', 'reversal-bracket-40', 'reversal-bracket-80', 'reversal-bracket-100', 'reversal-bracket-150', 'reversal-bracket-200'],
	flail: ['flail-bracket-20', 'flail-bracket-40', 'flail-bracket-80',
		'flail-bracket-100', 'flail-bracket-150', 'flail-bracket-200'],
	followme: ['follow-me-singles-try-rejection'],
	hypervoice: ['admission-hyper-voice'],
	vitalthrow: ['admission-vital-throw'],
	eruption: ['live-hp-power-eruption-full', 'live-hp-power-eruption-half-floor'],
	waterspout: ['live-hp-power-waterspout-full', 'live-hp-power-waterspout-half-floor'],
	rockthrow: ['ordinary-attack-rockthrow'],
	sandstorm: ['sandstorm-lifecycle', 'sandstorm-ground-immunity', 'sandstorm-toxic-residual-ko'],
	sandattack: ['boost-rotation-7', 'boost-accuracy-sand-attack-below', 'boost-accuracy-sand-attack-at'],
	scaryface: ['boost-rotation-7'],
	screech: ['boost-rotation-7'],
	scratch: ['derived-accuracy-miss'],
	shadowpunch: ['always-hit-rotation-2'],
	shockwave: ['always-hit-rotation-1'],
	slam: ['ordinary-attack-slam'],
	seismictoss: ['fixed-seismic-toss-level', 'fixed-seismic-toss-ghost-immunity'],
	splash: ['secondary-ember-success'],
	sharpen: ['boost-rotation-4'],
	smokescreen: ['boost-rotation-7'],
	steelwing: ['secondary-steel-wing-success', 'secondary-steel-wing-failure'],
	stringshot: ['boost-rotation-8'],
	swift: ['always-hit-rotation-2'],
	strength: ['derived-critical-hit', 'boost-strength-baseline'],
	substitute: ['substitute-create-break', 'substitute-toxic-block', 'substitute-recoil-basis', 'substitute-drain-basis', 'substitute-multihit-breakthrough'],
	surf: ['derived-water-absorb-try-hit', 'derived-water-absorb-heal'],
	sunnyday: ['weather-sun-replacement', 'weather-sun-water-damage', 'weather-sun-fire-damage'],
	sweetscent: ['boost-rotation-8', 'boost-accuracy-sweet-scent-below', 'boost-accuracy-sweet-scent-at'],
	swordsdance: ['boost-rotation-4'],
	tailglow: ['boost-rotation-4'],
	tailwhip: ['boost-rotation-8'],
	tackle: ['decisions-switch-targets'],
	tickle: ['boost-rotation-8', 'substitute-tickle-bypass', 'boost-tickle-hyper-cutter'],
	toxic: ['toxic-ramp', 'toxic-poison-immunity', 'toxic-steel-immunity', 'toxic-switch-reset'],
	vinewhip: ['ordinary-attack-vinewhip'],
	visegrip: ['ordinary-attack-visegrip'],
	waterfall: ['ordinary-attack-waterfall'],
	watergun: ['ordinary-attack-watergun'],
	withdraw: ['boost-rotation-5'],
	wingattack: ['target-any-sole-foe'],
	attract: [
		'attract-direct-action', 'attract-same-gender-immunity',
		'attract-oblivious-immunity', 'attract-oblivious-role-play-update',
	],
	roleplay: ['attract-oblivious-role-play-update', 'role-play-same-ability-failure'],
	skillswap: skillSwapCases,
	block: ['source-trap-block-release'],
	meanlook: ['source-trap-mean-look-rotation'],
	spiderweb: ['source-trap-spider-web-rotation'],
	falseswipe: [
		'damage-relay-false-swipe-nonlethal',
		'damage-relay-false-swipe-lethal-to-one',
		'damage-relay-false-swipe-zero-repeat',
		'damage-relay-false-swipe-critical',
		'damage-relay-false-swipe-protect',
		'damage-relay-false-swipe-ghost-immunity',
	],
	aromatherapy: [
		'team-cure-aromatherapy-clean', 'team-cure-aromatherapy-mixed',
	],
	healbell: [
		'team-cure-heal-bell-clean', 'team-cure-heal-bell-mixed',
	],
	roar: [
		'drag-roar-one-eligible', 'drag-roar-no-eligible',
		'drag-cancels-queued-move', 'drag-entry-lifecycle-recombination',
	],
	whirlwind: [
		'drag-whirlwind-multiple-eligible', 'drag-cancels-queued-move',
	],
	ingrain: ['drag-ingrain-block'],
	pursuit: [
		'pursuit-gen3-paralysis-intercept', 'pursuit-no-switch-control',
		'pursuit-sleep-at-turn-start', 'pursuit-switch-ko-continues',
		'pursuit-switch-survives',
	],
	batonpass: [
		'baton-pass-boost-transfer', 'baton-pass-no-bench',
		'baton-pass-resume-queue', 'baton-pass-trap-bind',
		'baton-pass-trap-block', 'baton-pass-trap-clamp',
		'baton-pass-trap-firespin', 'baton-pass-trap-meanlook',
		'baton-pass-trap-sandtomb', 'baton-pass-trap-spiderweb',
		'baton-pass-trap-whirlpool', 'baton-pass-trap-wrap',
	],
	conversion2: [
		'conversion2-dragon-singleton',
		'conversion2-normal-ghost-switch-reset',
		'conversion2-normal-rock', 'conversion2-normal-steel',
		'conversion2-sleep-talk', 'conversion2-struggle-torment',
		'conversion2-weather-ball',
	],
	camouflage: ['camouflage-normal-switch-reset'],
	conversion: ['conversion-current-slot-types'],
	focuspunch: [
		'focus-punch-interrupted-pp-spent',
		'focus-punch-status-hit-succeeds',
		'focus-punch-substitute-interception',
		'focus-punch-preparation-before-switch',
		'focus-punch-fake-out-interruption',
	],
	charge: [
		'charge-gen3-any-move-and-electric-status',
		'charge-gen3-electric-base-power', 'charge-gen3-faint-silent-clear',
		'charge-gen3-move-aborted', 'charge-gen3-restart',
		'charge-gen3-switch-silent-clear',
	],
	destinybond: destinyBondCases,
	grudge: grudgeCases,
	uproar: uproarCases,
	imprison: imprisonCases,
	triplekick: specializedMultihitCases,
	twineedle: specializedMultihitCases,
	spite: ['spite-pressure-pp-lifecycle'],
	struggle: ['recoil-rock-head-struggle'],
};
const implementedMoves = new Set(Object.keys(moveCases));
const partialMoveEvidence = new Set();
const inertAbilities = new Set(inertAbilityIDs);
const implementedAbilities = new Set(
	Object.keys(abilityCases).filter(id => !inertAbilities.has(id)));
const inertItems = new Set(passiveItemIDs);
const implementedItems = new Set(Object.keys(itemCases).filter(id => !inertItems.has(id)));
const implementedConditions = new Set([
	'statuses.brn', 'statuses.psn', 'statuses.tox', 'statuses.slp', 'statuses.par',
	'statuses.frz',
	'volatiles.protect', 'volatiles.stall', 'volatiles.endure',
	'volatiles.substitute', 'side_conditions.reflect',
	'side_conditions.lightscreen', 'weather.sandstorm',
	'side_conditions.mist',
	'side_conditions.safeguard',
	'side_conditions.spikes',
	'volatiles.yawn',
	'weather.hail', 'weather.raindance', 'weather.sunnyday',
	'volatiles.magiccoat',
	'volatiles.confusion',
	'volatiles.flinch',
	'volatiles.lockedmove',
	'volatiles.twoturnmove',
	'volatiles.bounce', 'volatiles.dig', 'volatiles.dive', 'volatiles.fly',
	'volatiles.razorwind', 'volatiles.skullbash', 'volatiles.skyattack',
	'volatiles.solarbeam',
	'volatiles.focusenergy',
	'volatiles.truant',
	'volatiles.partiallytrapped',
	'volatiles.taunt',
	'volatiles.disable',
	'volatiles.encore',
	'volatiles.torment',
	'volatiles.mustrecharge',
	'volatiles.nightmare',
	'volatiles.attract',
	'volatiles.choicelock',
	'volatiles.trapped',
	'volatiles.beatup',
	'volatiles.trapper',
	'volatiles.mudsport',
	'volatiles.watersport',
	'volatiles.lockon',
	'volatiles.foresight',
	'volatiles.leechseed',
	'volatiles.flashfire',
	'volatiles.snatch',
	'volatiles.ingrain',
	'volatiles.pursuit',
	'volatiles.charge',
	'volatiles.counter', 'volatiles.mirrorcoat',
	'volatiles.perishsong',
	'volatiles.bide',
	'volatiles.furycutter',
	'volatiles.rollout', 'volatiles.iceball', 'volatiles.defensecurl',
	'volatiles.stockpile',
	'volatiles.rage',
	'volatiles.minimize',
	'volatiles.focuspunch',
	'volatiles.destinybond', 'volatiles.grudge', 'volatiles.uproar',
	'volatiles.imprison',
	'volatiles.curse',
	'slot_conditions.futuremove',
	'pseudo_weather.sleepclausemod',
	'pseudo_weather.freezeclausemod',
	'slot_conditions.wish',
]);
const inertConditions = new Set(['volatiles.substitutebroken']);
const unreachableConditions = new Set([
	'volatiles.helpinghand',
	'volatiles.rolloutstorage',
	'slot_conditions.followme',
]);
const eventHookCases = {
	'move.assist.onHit': assistCases,
	'move.metronome.onHit': metronomeCases,
	'move.beatup.onModifyMove': beatUpCases,
	'move.beatup.condition.onModifySpA': beatUpCases,
	'move.beatup.condition.onFoeModifySpD': beatUpCases,
	'move.transform.onHit': transformCases,
	'move.smellingsalts.onHit': smellingSaltsCases,
	'move.bellydrum.onHit': bellyDrumCases,
	'move.dreameater.onTryImmunity': dreamEaterCases,
	'move.triattack.secondary.onHit': triAttackCases,
	'move.painsplit.onHit': painSplitCases,
	'move.jumpkick.onMoveFail': jumpKickCases,
	'move.highjumpkick.onMoveFail': jumpKickCases,
	'ability.truant.onSwitchIn': truantCases,
	'ability.truant.onBeforeMove': truantCases,
	'ability.truant.onResidual': truantCases,
	'ability.forecast.onStart': forecastCases,
	'ability.forecast.onWeatherChange': forecastCases,
	'move.curse.onModifyMove': curseCases,
	'move.curse.onTryHit': curseCases,
	'move.curse.onHit': curseCases,
	'move.curse.condition.onStart': curseCases,
	'move.curse.condition.onResidual': curseCases,
	'move.uproar.onTryHit': uproarCases,
	'move.uproar.condition.onStart': uproarCases,
	'move.uproar.condition.onResidual': uproarCases,
	'move.uproar.condition.onEnd': uproarCases,
	'move.uproar.condition.onAnySetStatus': uproarCases,
	'move.imprison.onTryHit': imprisonCases,
	'move.imprison.condition.onStart': imprisonCases,
	'move.imprison.condition.onFoeDisableMove': imprisonCases,
	'move.imprison.condition.onFoeBeforeMove': imprisonCases,
	'move.stockpile.onTry': stockpileCases,
	'move.stockpile.condition.onStart': stockpileCases,
	'move.stockpile.condition.onRestart': stockpileCases,
	'move.stockpile.condition.onEnd': stockpileCases,
	'move.spitup.onTry': stockpileCases,
	'move.spitup.onAfterMove': stockpileCases,
	'move.swallow.onTry': stockpileCases,
	'move.swallow.onHit': stockpileCases,
	'move.furycutter.condition.onStart': furyCutterCases,
	'move.furycutter.condition.onRestart': furyCutterCases,
	'move.furycutter.onHit': furyCutterCases,
	'move.rage.condition.onStart': rageCases,
	'move.rage.condition.onHit': rageCases,
	'move.rage.condition.onBeforeMove': rageCases,
	'move.minimize.condition.onRestart': minimizeCases,
	'move.minimize.condition.onSourceModifyDamage': minimizeCases,
	'move.spite.onHit': ['spite-pressure-pp-lifecycle'],
	'move.camouflage.onHit': ['camouflage-normal-switch-reset'],
	'move.conversion.onHit': ['conversion-current-slot-types'],
	'move.focuspunch.condition.onStart': moveCases.focuspunch,
	'move.focuspunch.condition.onHit': moveCases.focuspunch,
	'move.focuspunch.condition.onTryAddVolatile': moveCases.focuspunch,
	'move.focuspunch.onTry': moveCases.focuspunch,
	'move.destinybond.onPrepareHit': destinyBondCases,
	'move.destinybond.condition.onStart': destinyBondCases,
	'move.destinybond.condition.onBeforeMove': [
		'destiny-bond-before-move-cleanup', 'destiny-bond-consecutive-refresh',
	],
	'move.destinybond.condition.onMoveAborted': [
		'destiny-bond-move-aborted-cleanup',
	],
	'move.destinybond.condition.onFaint': destinyBondCases,
	'move.grudge.condition.onStart': grudgeCases,
	'move.grudge.condition.onBeforeMove': ['grudge-before-move-cleanup'],
	'move.grudge.condition.onFaint': grudgeCases,
	'move.rollout.condition.onStart': lockedRampCases,
	'move.rollout.condition.onResidual': lockedRampCases,
	'move.rollout.onModifyMove': lockedRampCases,
	'move.iceball.condition.onStart': lockedRampCases,
	'move.iceball.condition.onResidual': lockedRampCases,
	'move.iceball.onModifyMove': lockedRampCases,
	'move.defensecurl.condition.onRestart': lockedRampCases,
	'move.bide.condition.onStart': bideCases,
	'move.bide.condition.onDamage': bideCases,
	'move.bide.condition.onBeforeMove': bideCases,
	'move.bide.condition.onMoveAborted': bideCases,
	'move.bide.condition.onEnd': bideCases,
	'move.perishsong.onHitField': moveCases.perishsong,
	'move.perishsong.condition.onResidual': moveCases.perishsong,
	'move.perishsong.condition.onEnd': moveCases.perishsong,
	'ability.sturdy.onTryHit': abilityCases.sturdy,
	'ability.plus.onModifySpA': abilityCases.plus,
	'ability.minus.onModifySpA': abilityCases.minus,
	'ability.flashfire.onTryHit': abilityCases.flashfire,
	'ability.flashfire.onEnd': abilityCases.flashfire,
	'ability.flashfire.condition.onStart': abilityCases.flashfire,
	'ability.flashfire.condition.onModifyDamagePhase1': abilityCases.flashfire,
	'ability.flashfire.condition.onEnd': abilityCases.flashfire,
	'condition.futuremove.onStart': delayedFutureMoveCases,
	'condition.futuremove.onResidual': delayedFutureMoveCases,
	'condition.futuremove.onEnd': delayedFutureMoveCases,
	'move.futuresight.onTry': futureSightCases,
	'move.doomdesire.onTry': doomDesireCases,
	'move.wish.condition.onEnd': delayedWishCases,
	'move.snatch.condition.onStart': snatchCases,
	'move.snatch.condition.onAnyPrepareHit': snatchCases,
	'move.hiddenpower.onModifyMove': [
		'hidden-power-dark70-special-effective',
		'hidden-power-ground70-physical-stab-effective',
		'hidden-power-electric-ground-immunity',
	],
	'move.counter.condition.onStart': [
		'retaliation-counter-fixed-physical', 'retaliation-wrong-class-failure',
		'retaliation-source-faint-cancels-action',
	],
	'move.counter.onTry': [
		'retaliation-counter-fixed-physical', 'retaliation-wrong-class-failure',
		'retaliation-miss-no-history', 'retaliation-substitute-no-history',
	],
	'move.counter.condition.onDamage': counterCases,
	'move.mirrorcoat.condition.onStart': [
		'retaliation-mirror-coat-fixed-special', 'retaliation-wrong-class-failure',
		'retaliation-incoming-type-immunity',
	],
	'move.mirrorcoat.onTry': [
		'retaliation-mirror-coat-fixed-special', 'retaliation-wrong-class-failure',
		'retaliation-incoming-type-immunity',
	],
	'move.mirrorcoat.condition.onDamage': mirrorCoatCases,
	'ability.wonderguard.onTryHit': abilityCases.wonderguard,
	'item.focusband.onDamage': itemCases.focusband,
	'item.leppaberry.onUpdate': itemCases.leppaberry,
	'item.leppaberry.onEat': itemCases.leppaberry,
	'item.kingsrock.onModifyMove': itemCases.kingsrock,
	'item.shellbell.onAfterMoveSecondarySelf': itemCases.shellbell,
	'condition.brn.onStart': ['status-primary-rotation'],
	'condition.psn.onStart': ['status-primary-rotation'],
	'condition.tox.onStart': ['toxic-switch-reset', 'toxic-switch-in-hazard-order'],
	'condition.tox.onSwitchIn': ['toxic-switch-reset', 'toxic-switch-in-hazard-order'],
	'move.lockon.onTryHit': lockOnCases,
	'move.fakeout.onTry': fakeOutCases,
	'move.followme.onTry': moveCases.followme,
	'move.lockon.onHit': lockOnCases,
	'move.lockon.condition.onSourceAccuracy': lockOnCases,
	'move.lockon.condition.onSourceInvulnerability': lockOnCases,
	'move.mindreader.onTryHit': lockOnCases,
	'move.mindreader.onHit': lockOnCases,
	'move.foresight.onTryHit': moveCases.foresight,
	'move.odorsleuth.onTryHit': moveCases.odorsleuth,
	'move.naturepower.onHit': moveCases.naturepower,
	'move.mimic.onHit': moveCases.mimic,
	'move.sketch.onHit': moveCases.sketch,
	'move.sleeptalk.onTry': moveCases.sleeptalk,
	'move.sleeptalk.onTryHit': [
		'sleep-talk-choice-lock-subsequent-rejection',
		'sleep-talk-encore-subsequent-rejection',
	],
	'move.sleeptalk.onHit': moveCases.sleeptalk,
	'move.foresight.condition.onStart': moveCases.foresight,
	'move.foresight.condition.onNegateImmunity': moveCases.foresight,
	'move.foresight.condition.onModifyBoost': moveCases.foresight,
	'move.detect.onPrepareHit': moveCases.detect,
	'move.detect.onHit': moveCases.detect,
	'move.endure.onPrepareHit': moveCases.endure,
	'move.endure.onHit': moveCases.endure,
	'move.endure.condition.onStart': moveCases.endure,
	'move.endure.condition.onDamage': moveCases.endure,
	'move.protect.onPrepareHit': moveCases.protect,
	'move.protect.onHit': moveCases.protect,
	'move.protect.condition.onStart': moveCases.protect,
	'move.protect.condition.onTryHit': moveCases.protect,
	'condition.stall.onStart': [...moveCases.protect, ...moveCases.detect,
		...moveCases.endure],
	'condition.stall.onRestart': [...moveCases.protect, ...moveCases.detect,
		...moveCases.endure],
	'condition.stall.onStallMove': [...moveCases.protect, ...moveCases.detect,
		...moveCases.endure],
	'ability.oblivious.onImmunity': abilityCases.oblivious,
	'ability.oblivious.onTryHit': abilityCases.oblivious,
	'ability.oblivious.onUpdate': abilityCases.oblivious,
	'move.roleplay.onTryHit': moveCases.roleplay,
	'move.roleplay.onHit': moveCases.roleplay,
	'move.skillswap.onHit': moveCases.skillswap,
	'move.block.onHit': moveCases.block,
	'move.meanlook.onHit': moveCases.meanlook,
	'move.spiderweb.onHit': moveCases.spiderweb,
	'condition.trapped.onStart': [
		...moveCases.block, ...moveCases.meanlook, ...moveCases.spiderweb,
	],
	'condition.trapped.onTrapPokemon': [
		...moveCases.block, ...moveCases.meanlook, ...moveCases.spiderweb,
	],
	'ability.arenatrap.onFoeMaybeTrapPokemon': abilityCases.arenatrap,
	'ability.arenatrap.onFoeTrapPokemon': abilityCases.arenatrap,
	'ability.magnetpull.onAnyMaybeTrapPokemon': abilityCases.magnetpull,
	'ability.magnetpull.onAnyTrapPokemon': abilityCases.magnetpull,
	'ability.waterabsorb.onTryHit': abilityCases.waterabsorb,
	'ability.voltabsorb.onTryHit': abilityCases.voltabsorb,
	'ability.thickfat.onSourceBasePower': abilityCases.thickfat,
	'ability.marvelscale.onModifyDef': abilityCases.marvelscale,
	'move.refresh.onHit': moveCases.refresh,
	'move.psychup.onHit': moveCases.psychup,
	'move.haze.onHitField': moveCases.haze,
	'move.falseswipe.onDamage': moveCases.falseswipe,
	'move.aromatherapy.onHit': moveCases.aromatherapy,
	'move.healbell.onHit': moveCases.healbell,
	'move.rest.onTry': moveCases.rest,
	'move.rest.onHit': moveCases.rest,
	'ability.synchronize.onAfterSetStatus': abilityCases.synchronize,
	'ability.serenegrace.onModifyMove': abilityCases.serenegrace,
	'ability.clearbody.onTryBoost': abilityCases.clearbody,
	'ability.whitesmoke.onTryBoost': abilityCases.whitesmoke,
	'ability.hypercutter.onTryBoost': abilityCases.hypercutter,
	'ability.keeneye.onTryBoost': abilityCases.keeneye,
	'move.focusenergy.condition.onStart': moveCases.focusenergy,
	'move.focusenergy.condition.onModifyCritRatio': moveCases.focusenergy,
	'item.scopelens.onModifyCritRatio': itemCases.scopelens,
	'item.luckypunch.onModifyCritRatio': itemCases.luckypunch,
	'item.stick.onModifyCritRatio': itemCases.stick,
	'ability.battlearmor.onCriticalHit': abilityCases.battlearmor,
	'ability.shellarmor.onCriticalHit': abilityCases.shellarmor,
	'ability.compoundeyes.onSourceModifyAccuracy': abilityCases.compoundeyes,
	'ability.guts.onModifyAtk': abilityCases.guts,
	'ability.hugepower.onModifyAtk': abilityCases.hugepower,
	'ability.hustle.onModifyAtk': abilityCases.hustle,
	'ability.hustle.onSourceModifyAccuracy': abilityCases.hustle,
	'ability.purepower.onModifyAtk': abilityCases.purepower,
	'item.thickclub.onModifyAtk': itemCases.thickclub,
	'item.deepseascale.onModifySpD': itemCases.deepseascale,
	'item.deepseatooth.onModifySpA': itemCases.deepseatooth,
	'item.lightball.onModifySpA': itemCases.lightball,
	'item.machobrace.onModifySpe': itemCases.machobrace,
	'item.metalpowder.onModifyDef': itemCases.metalpowder,
	'item.souldew.onModifySpA': itemCases.souldew,
	'item.souldew.onModifySpD': itemCases.souldew,
	'move.thief.onAfterHit': moveCases.thief,
	'move.covet.onAfterHit': moveCases.covet,
	'move.knockoff.onAfterHit': moveCases.knockoff,
	'move.recycle.onHit': moveCases.recycle,
	'move.trick.onTryImmunity': moveCases.trick,
	'move.trick.onHit': moveCases.trick,
	'ability.stickyhold.onTakeItem': abilityCases.stickyhold,
	'item.mail.onTakeItem': itemCases.mail,
	'move.solarbeam.onTryMove': moveCases.solarbeam,
	'move.solarbeam.onBasePower': moveCases.solarbeam,
	'move.bounce.onTryMove': moveCases.bounce,
	'move.bounce.condition.onInvulnerability': moveCases.bounce,
	'move.bounce.condition.onSourceBasePower': moveCases.bounce,
	'move.dig.onTryMove': moveCases.dig,
	'move.dig.condition.onImmunity': ['dig-sandstorm-immunity', 'dig-hail-immunity'],
	'move.dig.condition.onInvulnerability': ['dig-earthquake-double', 'magnitude-dig-double'],
	'move.dig.condition.onSourceModifyDamage': ['dig-earthquake-double', 'magnitude-dig-double'],
	'move.dive.onTryMove': moveCases.dive,
	'move.dive.condition.onImmunity': moveCases.dive,
	'move.dive.condition.onInvulnerability': moveCases.dive,
	'move.dive.condition.onSourceModifyDamage': moveCases.dive,
	'move.fly.onTryMove': moveCases.fly,
	'move.fly.condition.onInvulnerability': moveCases.fly,
	'move.fly.condition.onSourceModifyDamage': moveCases.fly,
	'move.razorwind.onTryMove': moveCases.razorwind,
	'move.skullbash.onTryMove': moveCases.skullbash,
	'move.skyattack.onTryMove': moveCases.skyattack,
	'condition.twoturnmove.onStart': moveCases.solarbeam,
	'condition.twoturnmove.onEnd': moveCases.solarbeam,
	'condition.twoturnmove.onLockMove': moveCases.solarbeam,
	'condition.twoturnmove.onMoveAborted': moveCases.solarbeam,
	'move.thunder.onModifyMove': moveCases.thunder,
	'move.magnitude.onModifyMove': moveCases.magnitude,
	'move.magnitude.onUseMoveMessage': moveCases.magnitude,
	'move.present.onModifyMove': moveCases.present,
	'move.mudsport.condition.onStart': moveCases.mudsport,
	'move.mudsport.condition.onAnyBasePower': moveCases.mudsport,
	'move.watersport.condition.onStart': moveCases.watersport,
	'move.watersport.condition.onAnyBasePower': moveCases.watersport,
	'move.weatherball.onModifyMove': moveCases.weatherball,
	'move.moonlight.onHit': moveCases.moonlight,
	'move.morningsun.onHit': moveCases.morningsun,
	'move.synthesis.onHit': moveCases.synthesis,
	...Object.fromEntries(['onStart', 'onRestart', 'onResidual', 'onEnd', 'onLockMove'].map(hook =>
		[`condition.lockedmove.${hook}`, [
			'locked-outrage-duration2', 'locked-outrage-duration3',
			'locked-petal-dance-duration2', 'locked-thrash-duration2',
			'locked-outrage-ko-replacement', 'locked-outrage-opponent-switch',
		]])),
	'condition.mustrecharge.onBeforeMove': moveCases.hyperbeam,
	'move.brickbreak.onTryHit': moveCases.brickbreak,
	...Object.fromEntries(['aguavberry', 'figyberry', 'iapapaberry', 'magoberry',
		'wikiberry'].flatMap(id => ['onResidual', 'onTryEatItem', 'onEat'].map(hook =>
			[`item.${id}.${hook}`, itemCases[id]]))),
	'item.lumberry.onAfterSetStatus': itemCases.lumberry,
	'item.lumberry.onUpdate': itemCases.lumberry,
	'item.lumberry.onEat': itemCases.lumberry,
	'item.persimberry.onUpdate': itemCases.persimberry,
	'item.persimberry.onEat': itemCases.persimberry,
	'condition.confusion.onStart': [
		'confusion-primary-self-hit', 'confusion-sweet-kiss-action-success',
	],
	'condition.confusion.onBeforeMove': [
		'confusion-primary-self-hit', 'confusion-sweet-kiss-action-success',
	],
	'condition.confusion.onEnd': ['confusion-switch-clear'],
	'ability.owntempo.onTryAddVolatile': ['confusion-own-tempo'],
	'ability.owntempo.onHit': ['confusion-own-tempo'],
	'ability.owntempo.onUpdate': ['confusion-own-tempo'],
	'ability.shielddust.onModifySecondaries': ['confusion-secondary-shield-dust'],
	'condition.flinch.onBeforeMove': [
		'flinch-rotation-1', 'flinch-rotation-2', 'flinch-rotation-3',
	],
	'ability.innerfocus.onTryAddVolatile': ['flinch-inner-focus'],
	'item.cheriberry.onUpdate': itemCases.cheriberry,
	'item.cheriberry.onEat': itemCases.cheriberry,
	'item.chestoberry.onUpdate': itemCases.chestoberry,
	'item.chestoberry.onEat': itemCases.chestoberry,
	'item.pechaberry.onUpdate': itemCases.pechaberry,
	'item.pechaberry.onEat': itemCases.pechaberry,
	'item.rawstberry.onUpdate': itemCases.rawstberry,
	'item.rawstberry.onEat': itemCases.rawstberry,
	'item.aspearberry.onUpdate': itemCases.aspearberry,
	'item.aspearberry.onEat': itemCases.aspearberry,
	'item.oranberry.onResidual': ['berry-oran-threshold', 'berry-oran-above-threshold'],
	'item.oranberry.onTryEatItem': ['berry-oran-threshold'],
	'item.oranberry.onEat': ['berry-oran-threshold'],
	'item.sitrusberry.onResidual': ['berry-sitrus-threshold', 'berry-sitrus-rain-dish-order'],
	'item.sitrusberry.onTryEatItem': ['berry-sitrus-threshold'],
	'item.sitrusberry.onEat': ['berry-sitrus-threshold'],
	'item.liechiberry.onResidual': ['berry-liechi-threshold', 'berry-pinch-dual-holder-order', 'berry-pinch-clear-body-positive'],
	'item.liechiberry.onEat': ['berry-liechi-threshold', 'berry-pinch-clear-body-positive'],
	'item.ganlonberry.onResidual': ['berry-ganlon-threshold', 'berry-pinch-dual-holder-order'],
	'item.ganlonberry.onEat': ['berry-ganlon-threshold'],
	'item.salacberry.onResidual': ['berry-salac-threshold'],
	'item.salacberry.onEat': ['berry-salac-threshold'],
	'item.petayaberry.onResidual': ['berry-petaya-threshold'],
	'item.petayaberry.onEat': ['berry-petaya-threshold'],
	'item.apicotberry.onResidual': ['berry-apicot-threshold'],
	'item.apicotberry.onEat': ['berry-apicot-threshold'],
	'item.lansatberry.onResidual': [
		'berry-lansat-threshold', 'berry-lansat-above-threshold',
		'berry-lansat-focus-energy-duplicate',
	],
	'item.lansatberry.onEat': [
		'berry-lansat-threshold', 'berry-lansat-focus-energy-duplicate',
	],
	'item.starfberry.onResidual': itemCases.starfberry,
	'item.starfberry.onEat': itemCases.starfberry.filter(
		caseID => caseID !== 'berry-starf-above-threshold'),
	'item.mentalherb.onUpdate': itemCases.mentalherb,
	'item.whiteherb.onStart': [
		'item-white-herb-start-consumes', 'item-white-herb-start-order-control',
	],
	'item.whiteherb.onAnySwitchIn': ['item-white-herb-any-switch-in'],
	'item.whiteherb.onAnyAfterMove': [
		'item-white-herb-after-move', 'item-white-herb-miss-control',
	],
	'item.whiteherb.onResidual': ['item-white-herb-residual'],
	'item.whiteherb.onUse': [
		'item-white-herb-after-move', 'item-white-herb-start-consumes',
		'item-white-herb-any-switch-in', 'item-white-herb-residual',
	],
	'item.choiceband.onModifyAtk': itemCases.choiceband,
	'item.choiceband.onAfterMove': itemCases.choiceband,
	'condition.choicelock.onStart': itemCases.choiceband,
	'condition.choicelock.onDisableMove': itemCases.choiceband,
	'item.leftovers.onResidual': itemCases.leftovers,
	'ability.chlorophyll.onModifySpe': ['weather-chlorophyll-order'],
	'ability.cloudnine.onStart': ['weather-cloud-nine-switch'],
	'ability.cloudnine.onEnd': ['weather-cloud-nine-switch'],
	'ability.raindish.onResidual': [
		'weather-rain-dish-order', 'weather-rain-dish-clamp-full',
		'weather-rain-dish-suppressed', 'weather-rain-dish-switch',
	],
	'ability.sandstream.onStart': ['weather-sand-stream-start'],
	'ability.swiftswim.onModifySpe': [
		'weather-swift-swim-order', 'weather-swift-swim-tie',
		'weather-swift-swim-suppressed',
	],
	'ability.blaze.onBasePower': abilityCases.blaze,
	'ability.overgrow.onBasePower': abilityCases.overgrow,
	'ability.swarm.onBasePower': abilityCases.swarm,
	'ability.torrent.onBasePower': abilityCases.torrent,
	'ability.naturalcure.onSwitchOut': abilityCases.naturalcure,
	'ability.pressure.onDeductPP': [
		'pressure-basic', 'pressure-protect', 'pressure-immunity',
		'pressure-miss', 'pressure-spikes', 'snatch-pressure-howl',
	],
	'ability.pressure.onStart': [
		'pressure-basic', 'berry-cure-switch-persistence',
	],
	'ability.damp.onAnyTryMove': [
		'damp-explosion', 'damp-self-destruct', 'damp-ordinary-pass',
	],
	'ability.flamebody.onDamagingHit': abilityCases.flamebody,
	'ability.static.onDamagingHit': abilityCases.static,
	'ability.poisonpoint.onDamagingHit': abilityCases.poisonpoint,
	'ability.effectspore.onDamagingHit': abilityCases.effectspore,
	'ability.roughskin.onDamagingHit': abilityCases.roughskin,
	'ability.rockhead.onDamage': abilityCases.rockhead,
	'ability.shedskin.onResidual': abilityCases.shedskin,
	'ability.speedboost.onResidual': abilityCases.speedboost,
	'ability.intimidate.onStart': abilityCases.intimidate,
	'ability.trace.onStart': abilityCases.trace,
	'ability.colorchange.onDamagingHit': abilityCases.colorchange,
	'ability.cutecharm.onDamagingHit': abilityCases.cutecharm,
	'move.attract.onTryImmunity': moveCases.attract,
	'move.attract.condition.onStart': moveCases.attract,
	'move.attract.condition.onBeforeMove': [
		'attract-direct-action', 'cute-charm-contact',
	],
	'move.attract.condition.onUpdate': moveCases.attract,
	'move.attract.condition.onEnd': [
		'item-mental-herb-attract', 'item-mental-herb-cute-charm',
	],
	'condition.par.onBeforeMove': ['status-paralysis-action'],
	'condition.par.onModifySpe': ['status-paralysis-action'],
	'condition.par.onStart': ['status-primary-rotation', 'paralysis-start-static'],
	'condition.frz.onStart': [
		'freeze-lifecycle-random-thaw', 'freeze-lifecycle-defrost',
		'freeze-lifecycle-fire-hit',
	],
	'condition.frz.onBeforeMove': [
		'freeze-lifecycle-random-thaw', 'freeze-lifecycle-defrost',
	],
	'condition.frz.onModifyMove': ['freeze-lifecycle-defrost'],
	'condition.frz.onDamagingHit': ['freeze-lifecycle-fire-hit'],
	'condition.brn.onResidual': ['direct-heal-burn-residual'],
	'condition.psn.onResidual': ['status-primary-rotation'],
	'condition.tox.onResidual': ['toxic-ramp', 'toxic-switch-reset'],
	'condition.raindance.onWeatherModifyDamage': ['weather-rain-water-damage', 'weather-rain-fire-damage'],
	'condition.sunnyday.onWeatherModifyDamage': ['weather-sun-water-damage', 'weather-sun-fire-damage'],
	...Object.fromEntries(['onFieldStart', 'onFieldResidual', 'onFieldEnd'].map(hook =>
		[`condition.hail.${hook}`, ['weather-hail-lifecycle']])),
	...Object.fromEntries(['onFieldStart', 'onFieldResidual', 'onFieldEnd'].map(hook =>
		[`condition.raindance.${hook}`, ['weather-rain-lifecycle']])),
	...Object.fromEntries(['onFieldStart', 'onFieldResidual', 'onFieldEnd'].map(hook =>
		[`condition.sandstorm.${hook}`, ['sandstorm-lifecycle']])),
	...Object.fromEntries(['onFieldStart', 'onFieldResidual', 'onFieldEnd'].map(hook =>
		[`condition.sunnyday.${hook}`, ['weather-recovery-replacement-expiry']])),
	'condition.hail.onWeather': ['weather-hail-lifecycle'],
	'condition.sandstorm.onWeather': ['sandstorm-lifecycle'],
	'condition.sunnyday.onImmunity': ['weather-sun-freeze-immunity'],
	'ability.magmaarmor.onImmunity': ['status-ability-rotation'],
	'ability.immunity.onSetStatus': ['status-ability-rotation'],
	'ability.insomnia.onSetStatus': ['status-ability-rotation'],
	'ability.insomnia.onTryAddVolatile': ['yawn-insomnia-block'],
	'ability.insomnia.onUpdate': ['status-ability-rotation',
		'insomnia-update-skill-swap'],
	'ability.limber.onSetStatus': ['status-ability-rotation'],
	'ability.vitalspirit.onSetStatus': ['status-ability-rotation'],
	'ability.vitalspirit.onTryAddVolatile': ['yawn-vital-spirit-block'],
	'ability.vitalspirit.onUpdate': ['vital-spirit-trace-update'],
	'ability.waterveil.onSetStatus': ['status-ability-rotation'],
	'ability.magmaarmor.onUpdate': ['status-ability-rotation'],
	'ability.immunity.onUpdate': ['status-ability-rotation'],
	'ability.limber.onUpdate': ['status-ability-rotation'],
	'ability.waterveil.onUpdate': ['status-ability-rotation'],
	'condition.slp.onStart': [
		'status-primary-rotation', 'sleep-lifecycle-prevent',
		'sleep-lifecycle-wake', 'sleep-lifecycle-snore',
		'sleep-lifecycle-early-bird', 'sleep-lifecycle-switch-restore',
	],
	'condition.slp.onBeforeMove': [
		'sleep-lifecycle-prevent', 'sleep-lifecycle-wake',
		'sleep-lifecycle-snore', 'sleep-lifecycle-early-bird',
	],
	'condition.slp.onSwitchIn': ['sleep-lifecycle-switch-restore'],
	'move.snore.onTry': [
		'sleep-lifecycle-snore', 'sleep-lifecycle-snore-awake-fail',
	],
	'item.blackbelt.onModifyAtk': itemCases.blackbelt,
	'item.hardstone.onModifyAtk': itemCases.hardstone,
	'item.metalcoat.onModifyAtk': itemCases.metalcoat,
	'item.sharpbeak.onModifyAtk': itemCases.sharpbeak,
	'item.silkscarf.onModifyAtk': itemCases.silkscarf,
	'item.silverpowder.onModifyAtk': itemCases.silverpowder,
	'item.softsand.onModifyAtk': itemCases.softsand,
	'item.blackglasses.onModifySpA': itemCases.blackglasses,
	'item.charcoal.onModifySpA': itemCases.charcoal,
	'item.dragonfang.onModifySpA': itemCases.dragonfang,
	'item.miracleseed.onModifySpA': itemCases.miracleseed,
	'item.mysticwater.onModifySpA': itemCases.mysticwater,
	'item.seaincense.onModifySpA': itemCases.seaincense,
	'item.poisonbarb.onModifyAtk': itemCases.poisonbarb,
	'item.spelltag.onModifyAtk': itemCases.spelltag,
	'item.magnet.onModifySpA': itemCases.magnet,
	'item.nevermeltice.onModifySpA': itemCases.nevermeltice,
	'item.twistedspoon.onModifySpA': itemCases.twistedspoon,
	'move.substitute.onTryHit': ['substitute-create-break'],
	'move.substitute.onHit': ['substitute-create-break'],
	'move.substitute.condition.onStart': ['substitute-create-break'],
	'move.substitute.condition.onTryPrimaryHit': ['substitute-create-break', 'substitute-toxic-block', 'substitute-multihit-breakthrough'],
	'move.substitute.condition.onEnd': ['substitute-create-break'],
	'move.magiccoat.condition.onStart': ['magic-coat-growl-reflection'],
	'move.magiccoat.condition.onTryHit': ['magic-coat-growl-reflection'],
	'move.mirrormove.onHit': ['mirror-move-growl-called', 'mirror-move-no-history'],
	'move.lightscreen.condition.onAnyModifyDamagePhase1': moveCases.lightscreen,
	'move.lightscreen.condition.onSideStart': moveCases.lightscreen,
	'move.lightscreen.condition.onSideResidual': moveCases.lightscreen,
	'move.lightscreen.condition.onSideEnd': moveCases.lightscreen,
	'move.reflect.condition.onAnyModifyDamagePhase1': moveCases.reflect,
	'move.reflect.condition.onSideStart': moveCases.reflect,
	'move.reflect.condition.onSideEnd': moveCases.reflect,
	'move.mist.condition.onTryBoost': moveCases.mist,
	'move.mist.condition.onSideStart': moveCases.mist,
	'move.mist.condition.onSideResidual': moveCases.mist,
	'move.mist.condition.onSideEnd': moveCases.mist,
	'move.safeguard.condition.onSetStatus': moveCases.safeguard,
	'move.safeguard.condition.onTryAddVolatile': moveCases.safeguard,
	'move.safeguard.condition.onSideStart': moveCases.safeguard,
	'move.safeguard.condition.onSideEnd': moveCases.safeguard,
	'move.yawn.onTryHit': moveCases.yawn,
	'move.yawn.condition.onStart': moveCases.yawn,
	'move.yawn.condition.onEnd': moveCases.yawn,
	'move.nightmare.condition.onStart': moveCases.nightmare,
	'move.nightmare.condition.onResidual': moveCases.nightmare,
	'move.endeavor.onTry': moveCases.endeavor,
	'move.endeavor.onTryImmunity': moveCases.endeavor,
	'move.facade.onBasePower': moveCases.facade,
	'condition.partiallytrapped.onStart': moveCases.bind,
	'condition.partiallytrapped.onResidual': moveCases.bind,
	'condition.partiallytrapped.onEnd': moveCases.bind,
	'condition.partiallytrapped.onTrapPokemon': moveCases.bind,
	'move.rapidspin.self.onHit': moveCases.rapidspin,
	'move.rapidspin.onAfterHit': [
		'rapid-spin-leech-seed-combined-cleanup',
	],
	'move.rapidspin.onAfterSubDamage': [
		'rapid-spin-leech-seed-substitute-and-protect',
	],
	'move.leechseed.onTryImmunity': moveCases.leechseed,
	'move.leechseed.condition.onStart': moveCases.leechseed,
	'move.leechseed.condition.onResidual': moveCases.leechseed,
	'ability.liquidooze.onSourceTryHeal': abilityCases.liquidooze,
	'move.taunt.condition.onStart': moveCases.taunt,
	'move.taunt.condition.onBeforeMove': moveCases.taunt,
	'move.taunt.condition.onDisableMove': moveCases.taunt,
	'move.taunt.condition.onEnd': moveCases.taunt,
	'move.disable.onTryHit': [
		'choice-disable-no-last-move', 'choice-disable-substitute',
		'choice-disable-immune-last-move',
	],
	'move.disable.condition.onStart': [
		'choice-disable-fast', 'choice-disable-zero-pp-start',
		'choice-disable-substitute', 'choice-disable-immune-last-move',
	],
	'move.disable.condition.onBeforeMove': [
		'choice-disable-fast', 'choice-disable-slow',
	],
	'move.disable.condition.onDisableMove': [
		'choice-disable-fast', 'choice-disable-slow',
	],
	'move.disable.condition.onEnd': ['choice-disable-fast'],
	'move.encore.condition.onStart': [
		'choice-encore-preaction', 'choice-encore-postaction-switch',
	],
	'move.encore.condition.onDisableMove': [
		'choice-encore-preaction', 'choice-encore-pp-zero',
	],
	'move.encore.condition.onOverrideAction': ['choice-encore-preaction'],
	'move.encore.condition.onResidual': ['choice-encore-pp-zero'],
	'move.encore.condition.onEnd': ['choice-encore-pp-zero'],
	'move.torment.condition.onStart': ['choice-torment-cycle'],
	'move.torment.condition.onDisableMove': ['choice-torment-cycle'],
	/* Torment is indefinite and has no reachable ordinary End dispatch.
	 * Switching bulk-clears it; this negative trace is the End evidence. */
	'move.torment.condition.onEnd': ['choice-torment-switch'],
	'move.spikes.condition.onSideStart': moveCases.spikes,
	'move.spikes.condition.onSideRestart': moveCases.spikes,
	'move.spikes.condition.onEntryHazard': moveCases.spikes,
	'move.ingrain.condition.onStart': moveCases.ingrain,
	'move.ingrain.condition.onResidual': moveCases.ingrain,
	'move.ingrain.condition.onTrapPokemon': moveCases.ingrain,
	'move.ingrain.condition.onDragOut': moveCases.ingrain,
	'ability.suctioncups.onDragOut': abilityCases.suctioncups,
	'move.pursuit.condition.onBeforeSwitchOut': moveCases.pursuit,
	'move.pursuit.onModifyMove': moveCases.pursuit,
	'move.batonpass.onHit': moveCases.batonpass,
	'move.batonpass.self.onHit': moveCases.batonpass,
	'move.conversion2.onHit': moveCases.conversion2,
	'move.charge.condition.onStart': moveCases.charge,
	'move.charge.condition.onRestart': moveCases.charge,
	'move.charge.condition.onBasePower': moveCases.charge,
	'move.charge.condition.onMoveAborted': moveCases.charge,
	'move.charge.condition.onAfterMove': moveCases.charge,
	'move.charge.condition.onEnd': moveCases.charge,
	'move.struggle.onModifyMove': moveCases.struggle,
	'format.sleepclausemod.onSetStatus': [
		'status-sleep-clause', 'sleep-clause-rest-self-sleep',
	],
	'format.freezeclausemod.onSetStatus': freezeClauseCases,
};
const implementedEventHooks = new Set(Object.keys(eventHookCases));
/* Flattened Gen 3 retains the inherited hook in data, but its overridden
 * move runner has no separate ModifyType singleEvent phase. Weather Ball's
 * executable onModifyMove therefore repeats the type mutation. */
const inertEventHooks = new Set([
	'move.weatherball.onModifyType',
	'move.secretpower.onModifyMove',
	'move.splash.onTry', 'move.splash.onTryHit',
	'move.payday.onHit',
	'condition.mustrecharge.onStart',
]);
/* Damp's inherited Aftermath guard cannot run in Gen 3 because that source
 * effect does not exist in the generation. */
const unreachableEventHooks = new Set([
	'ability.damp.onAnyDamage',
	'condition.frz.onAfterMoveSecondary',
	'item.whiteherb.onAnyAfterMega',
	/* Neither installed condition is reachable in a singles battle. */
	'move.helpinghand.condition.onStart',
	'move.helpinghand.condition.onRestart',
	'move.helpinghand.condition.onBasePower',
	'move.helpinghand.onTryHit',
	'move.toxic.condition.onSourceAccuracy',
	'move.toxic.condition.onSourceInvulnerability',
	'move.followme.condition.onStart',
	'move.followme.condition.onFoeRedirectTarget',
	'ability.lightningrod.onFoeRedirectTarget',
	/* getMoveTargets only dispatches RedirectTarget for multi-active formats;
	 * Gen 3 OU singles has exactly one active position per side. */
	'move.counter.condition.onRedirectTarget',
	'move.mirrorcoat.condition.onRedirectTarget',
	/* Gen 3's overridden move executor dispatches the move-local ModifyMove
	 * callback and has no separate ModifyType single-event phase. */
	'move.hiddenpower.onModifyType',
	/* Gen 3 has no connected hit which advances hitCount without advancing
	 * contactHitCount; rolloutstorage therefore cannot be installed. */
	'move.rollout.onAfterMove',
	'move.iceball.onAfterMove',
	'condition.rolloutstorage.onBasePower',
]);
const targetCases = {
	adjacentAlly: ['target-adjacent-ally-no-target'],
	all: ['sandstorm-lifecycle'],
	allAdjacent: ['derived-grounded-earthquake'],
	allAdjacentFoes: ['derived-water-absorb-try-hit'],
	allySide: ['reflect-physical-half', 'light-screen-special-half', 'mist-lifecycle-filter'],
	allyTeam: [
		'team-cure-aromatherapy-clean', 'team-cure-aromatherapy-mixed',
		'team-cure-heal-bell-clean', 'team-cure-heal-bell-mixed',
	],
	foeSide: moveCases.spikes,
	any: ['target-any-sole-foe'],
	normal: ['derived-accuracy-miss'],
	randomNormal: ['locked-outrage-duration2', 'locked-petal-dance-duration2',
		'locked-thrash-duration2'],
	scripted: retaliationCases,
	self: ['boost-bulk-up-downstream'],
};
const implementedTargets = new Set(Object.keys(targetCases));
const formatRuleCases = {
	sleepclausemod: ['status-sleep-clause', 'sleep-clause-rest-self-sleep'],
	freezeclausemod: freezeClauseCases,
	switchpriorityclausemod: ['decisions-switch-targets'],
	endlessbattleclause: ['endless-battle-recycle-skill-swap-winner'],
	standardag: ['endless-battle-recycle-skill-swap-winner'],
	standard: ['endless-battle-recycle-skill-swap-winner'],
};
const atomicAdmissionRuleCases = {
	'-ability:sandveil': 'ban-ability-sand-veil',
	'-ability:soundproof': 'ban-ability-soundproof',
	'-item:brightpowder': 'ban-item-bright-powder',
	'-item:laxincense': 'ban-item-lax-incense',
	'-move:acupressure': 'ban-move-acupressure',
	'-move:assist': 'ban-move-assist',
	'-move:doubleteam': 'ban-move-double-team',
	'-move:minimize': 'ban-move-minimize',
	'-move:swagger': 'ban-move-swagger',
};
const aggregateAdmissionRuleCases = {
	evasionitemsclause: [
		'legal-control', 'ban-item-bright-powder', 'ban-item-lax-incense',
	],
	evasionmovesclause: [
		'legal-control', 'ban-move-acupressure', 'ban-move-double-team',
		'ban-move-minimize',
	],
};
const tagAdmissionRuleCases = {
	'-pokemontag:uber': ['ban-tag-uber-mewtwo', 'ban-tag-uber-deoxys-attack'],
	'-pokemontag:unobtainable': [
		'ban-tag-unobtainable-berry-juice', 'ban-tag-unobtainable-fast-ball',
	],
	'-nonexistent': [
		'ban-tag-nonexistent-species', 'ban-tag-nonexistent-move',
		'ban-tag-nonexistent-ability', 'ban-tag-nonexistent-item',
	],
};
const allOfAdmissionRuleCases = {
	ohkoclause: [
		'ban-ohko-fissure', 'ban-ohko-guillotine', 'ban-ohko-horn-drill',
		'ban-ohko-sheer-cold', 'legal-metronome-not-ohko', 'legal-donphan-earthquake',
	],
	accuracytrapclause: [
		'ban-accuracy-trap-arena-trap', 'ban-accuracy-trap-magnet-pull',
		'ban-accuracy-trap-mean-look', 'ban-accuracy-trap-spider-web',
		'legal-accuracy-trap-trap-only', 'legal-accuracy-trap-accuracy-only',
		'legal-accuracy-trap-move-only', 'legal-accuracy-trap-probabilistic',
		'legal-accuracy-trap-partial-trap',
	],
};
const teamAdmissionRuleCases = {
	oneboostpasserclause: [
		'legal-one-boost-move-source', 'legal-one-boost-item-source',
		'ban-one-boost-same-set', 'ban-one-boost-two-passers',
		'legal-one-boost-one-qualified-passer', 'ban-boost-pass-order',
		'legal-boost-sources-without-pass',
	],
	speedpassclause: [
		'ban-speed-pass-move', 'ban-speed-pass-item', 'ban-speed-pass-ability',
		'ban-speed-pass-ancient-power', 'legal-boost-sources-without-pass',
	],
};
const statAdmissionRuleCases = {
	evlimit: [
		'ban-ev-omitted', 'ban-ev-zero', 'legal-ev-one', 'legal-ev-509',
		'legal-ev-510', 'ban-ev-511', 'legal-ev-stat-255',
		'ban-ev-stat-256', 'legal-ev-zero-level-one', 'ban-ev-second-team-member',
	],
};
const relationAdmissionRuleCases = {
	obtainableabilities: [
		'legal-ability-primary-slot', 'legal-ability-secondary-slot',
		'legal-ability-dual-slot-a', 'legal-ability-dual-slot-b',
		'ban-ability-modern-slot', 'ban-ability-cross-species',
		'ban-ability-second-team-member',
	],
};
const normalizationAdmissionRuleCases = {
	obtainableformes: [
		'legal-forme-base-castform', 'legal-forme-castform-sunny',
		'legal-forme-castform-rainy', 'legal-forme-castform-snowy',
		'ban-forme-required-ability', 'legal-forme-second-team-member',
	],
};
const nicknameAdmissionRuleCases = {
	nicknameclause: [
		'legal-nickname-distinct', 'ban-nickname-duplicate',
		'legal-nickname-case-sensitive', 'legal-nickname-own-species',
		'ban-nickname-species-impersonation', 'legal-nickname-normalization',
		'legal-nickname-same-form-family', 'legal-nickname-eighteen-units',
		'legal-nickname-nine-astral', 'ban-nickname-ten-astral',
		'legal-nickname-unicode-space-normalization',
	],
};
const obtainableMoveCases = [
	'legal-source-level', 'legal-source-machine', 'legal-source-tutor',
	'legal-source-prevo', 'legal-source-egg', 'legal-source-chainbreed',
	'ban-source-egg-pair', 'legal-source-event', 'ban-source-event-intersection',
	'legal-source-event-level', 'ban-source-event-level', 'legal-source-restricted',
	'ban-source-two-restricted', 'legal-source-sketch', 'ban-source-egg-underlevel',
	'legal-level-up-egg-source', 'ban-genderless-level-up-egg-source',
	'legal-event-plus-unrestricted-source', 'ban-future-virtual-console-source',
	'legal-current-generation-tutor-source', 'legal-male-level-up-egg-source',
	'ban-male-level-up-egg-without-mother-source', 'legal-shedinja-gust-regression',
	'ban-skarmory-whirlwind-drill-peck', 'ban-armaldo-knock-off-rapid-spin',
	'legal-female-level-up-egg-source', 'ban-female-level-up-egg-combination',
	'legal-stock-zigzagoon-event-egg-combination',
	'legal-hitmontop-shared-father-source', 'legal-field-sketch-egg-combination',
	'legal-evolved-event-ability-reroll',
];
const obtainableMiscCases = [
	'ban-duplicate-move', 'legal-distinct-moves', 'legal-hidden-power-ice-explicit',
	'legal-hidden-power-ice-default-rewrite', 'ban-hidden-power-alias-conflict',
	'ban-hidden-power-iv-conflict', 'ban-hidden-power-invalid-type',
	'legal-hidden-power-derived-from-ivs', 'legal-hidden-power-alias-derives-type',
	'legal-event-optional-shiny-false', 'legal-event-optional-shiny-true',
	'ban-underlevel-evolution', 'legal-underlevel-event-evolution',
	'ban-underlevel-event-gender-mismatch', 'ban-lineage-underlevel-evolution',
	'legal-event-only-species-minimum', 'ban-event-only-species-underlevel',
	'legal-underlevel-event-exact-fields', 'ban-underlevel-event-wrong-nature',
	'ban-underlevel-event-wrong-iv', 'ban-underlevel-event-wrong-gender',
];
const obtainabilityAdmissionRuleCases = {
	obtainablemoves: obtainableMoveCases,
	obtainablemisc: obtainableMiscCases,
	obtainable: [...new Set([
		...obtainableMoveCases, ...obtainableMiscCases,
		...relationAdmissionRuleCases.obtainableabilities,
		...normalizationAdmissionRuleCases.obtainableformes,
		...statAdmissionRuleCases.evlimit,
	])],
};
const implementedFormatRules = new Set([
	'Baton Pass + Block', 'Baton Pass + Mean Look',
	'Baton Pass + Spider Web', 'Smeargle + Ingrain', 'speciesclause',
	...Object.keys(formatRuleCases), ...Object.keys(atomicAdmissionRuleCases),
	...Object.keys(aggregateAdmissionRuleCases),
	...Object.keys(tagAdmissionRuleCases),
	...Object.keys(allOfAdmissionRuleCases),
	...Object.keys(teamAdmissionRuleCases),
	...Object.keys(statAdmissionRuleCases),
	...Object.keys(relationAdmissionRuleCases),
	...Object.keys(normalizationAdmissionRuleCases),
	...Object.keys(nicknameAdmissionRuleCases),
	...Object.keys(obtainabilityAdmissionRuleCases),
]);
const unreachableFormatRules = new Set([
	'-unreleased',
	'Huntail + Shell Smash + Sucker Punch',
	'Hypnosis + Gengarite',
]);
/* Resolved server-protocol policies which are semantically active in
 * Showdown but inert with respect to the canonical atomic Ocean battle
 * contract. The bundle retains and validates their typed values. */
const inertFormatRules = new Set([
	'beatupnicknamesmod', 'cancelmod', 'hppercentagemod',
]);
const conditionCases = {
	'volatiles.beatup': beatUpCases,
	'volatiles.truant': truantCases,
	'volatiles.curse': curseCases,
	'pseudo_weather.sleepclausemod': [
		'status-sleep-clause', 'sleep-clause-rest-self-sleep',
	],
	'pseudo_weather.freezeclausemod': freezeClauseCases,
	'volatiles.furycutter': furyCutterCases,
	'volatiles.rollout': lockedRampCases,
	'volatiles.iceball': lockedRampCases,
	'volatiles.defensecurl': lockedRampCases,
	'volatiles.stockpile': stockpileCases,
	'volatiles.rage': rageCases,
	'volatiles.minimize': minimizeCases,
	'volatiles.focuspunch': moveCases.focuspunch,
	'volatiles.destinybond': destinyBondCases,
	'volatiles.grudge': grudgeCases,
	'volatiles.uproar': uproarCases,
	'volatiles.imprison': imprisonCases,
	'volatiles.bide': bideCases,
	'volatiles.perishsong': moveCases.perishsong,
	'volatiles.flashfire': abilityCases.flashfire,
	'volatiles.ingrain': moveCases.ingrain,
	'volatiles.pursuit': moveCases.pursuit,
	'volatiles.charge': moveCases.charge,
	'volatiles.leechseed': moveCases.leechseed,
	'slot_conditions.futuremove': delayedFutureMoveCases,
	'slot_conditions.wish': delayedWishCases,
	'volatiles.snatch': snatchCases,
	'volatiles.counter': counterCases,
	'volatiles.mirrorcoat': mirrorCoatCases,
	'volatiles.lockon': lockOnCases,
	'volatiles.foresight': [
		...moveCases.foresight, ...moveCases.odorsleuth,
	],
	'statuses.frz': [
		'freeze-lifecycle-random-thaw', 'freeze-lifecycle-defrost',
		'freeze-lifecycle-fire-hit',
	],
	'statuses.par': ['status-paralysis-action', 'status-primary-rotation',
		'paralysis-start-static'],
	'side_conditions.spikes': moveCases.spikes,
	'volatiles.taunt': moveCases.taunt,
	'volatiles.disable': moveCases.disable,
	'volatiles.encore': moveCases.encore,
	'volatiles.torment': moveCases.torment,
	'volatiles.focusenergy': moveCases.focusenergy,
	'volatiles.partiallytrapped': [
		...moveCases.bind, ...moveCases.clamp, ...moveCases.firespin,
		...moveCases.whirlpool, ...moveCases.wrap,
		...moveCases.sandtomb,
	],
	'volatiles.flinch': [
		'flinch-rotation-1', 'flinch-rotation-2', 'flinch-rotation-3',
		'flinch-inner-focus',
	],
	'volatiles.twoturnmove': moveCases.solarbeam,
	'volatiles.bounce': moveCases.bounce,
	'volatiles.dig': moveCases.dig,
	'volatiles.dive': moveCases.dive,
	'volatiles.fly': moveCases.fly,
	'volatiles.razorwind': moveCases.razorwind,
	'volatiles.skullbash': moveCases.skullbash,
	'volatiles.skyattack': moveCases.skyattack,
	'volatiles.solarbeam': moveCases.solarbeam,
	'volatiles.lockedmove': [
		'locked-outrage-duration2', 'locked-outrage-duration3',
		'locked-petal-dance-duration2', 'locked-thrash-duration2',
		'locked-thrash-immunity', 'locked-outrage-protect',
		'locked-outrage-ko-replacement', 'locked-outrage-opponent-switch',
	],
	'volatiles.mustrecharge': moveCases.hyperbeam,
	'volatiles.confusion': [
		'confusion-primary-self-hit', 'confusion-sweet-kiss-action-success',
		'confusion-protect-block', 'confusion-substitute-block',
		'confusion-own-tempo', 'confusion-switch-clear',
	],
	'statuses.brn': ['secondary-ember-success'],
	'statuses.psn': ['status-primary-rotation', 'secondary-sludge'],
	'statuses.tox': ['toxic-ramp'],
	'statuses.slp': [
		'sleep-lifecycle-prevent', 'sleep-lifecycle-wake',
		'sleep-lifecycle-snore', 'sleep-lifecycle-early-bird',
		'sleep-lifecycle-switch-restore',
	],
	'volatiles.protect': ['protect-switch-reset',
		'detect-protect-endure-shared-stall-success'],
	'volatiles.stall': ['protect-stall-chain',
		'detect-protect-endure-shared-stall-success',
		'detect-endure-shared-stall-failure'],
	'volatiles.endure': ['endure-fixed-move-damage',
		'endure-multihit-each-hit'],
	'volatiles.substitute': moveCases.substitute,
	'volatiles.magiccoat': moveCases.magiccoat,
	'volatiles.substitutebroken': ['substitute-create-break'],
	'side_conditions.reflect': ['reflect-physical-half'],
	'side_conditions.lightscreen': ['light-screen-special-half'],
	'side_conditions.mist': ['mist-lifecycle-filter'],
	'side_conditions.safeguard': moveCases.safeguard,
	'volatiles.yawn': moveCases.yawn,
	'volatiles.nightmare': moveCases.nightmare,
	'volatiles.attract': [
		'attract-direct-action', 'attract-same-gender-immunity',
		'cute-charm-contact',
	],
	'volatiles.choicelock': itemCases.choiceband,
	'volatiles.trapped': [
		...moveCases.block, ...moveCases.meanlook, ...moveCases.spiderweb,
	],
	'volatiles.trapper': [
		...moveCases.block, ...moveCases.meanlook, ...moveCases.spiderweb,
	],
	'volatiles.mudsport': moveCases.mudsport,
	'volatiles.watersport': moveCases.watersport,
	'weather.sandstorm': ['sandstorm-lifecycle'],
	'weather.hail': ['weather-hail-lifecycle'],
	'weather.raindance': ['weather-rain-lifecycle', 'weather-sun-replacement'],
	'weather.sunnyday': ['weather-sun-replacement'],
};

function refs(paths, symbol) { return paths.map(source => ({path: source, symbol})); }
function nativeBoundary(kind, id) {
	if (kind === 'format_rule' && [
		'beatupnicknamesmod', 'cancelmod', 'hppercentagemod',
		'switchpriorityclausemod',
	].includes(id)) {
		return [
			{path: 'native/singles2.c', symbol: 'resolved PokemonFormatPolicy protocol and voluntary-switch-order policies'},
			{path: 'native/pokemon.c', symbol: 'fail-closed resolved policy validation and generic speed-ordered action queue'},
		];
	}
	const partyDelegationRecord =
		(kind === 'move' && ['assist', 'beatup', 'metronome'].includes(id)) ||
		(kind === 'condition' && id === 'volatiles.beatup') ||
		(kind === 'event_hook' && [
			'move.assist.onHit', 'move.metronome.onHit',
			'move.beatup.onModifyMove',
			'move.beatup.condition.onModifySpA',
			'move.beatup.condition.onFoeModifySpD',
		].includes(id));
	if (partyDelegationRecord) {
		return [
			{path: 'native/gen3_slice_data.c', symbol: 'generated move-call pools, Beat Up programs, owner bindings, and non-interacting type policy'},
			{path: 'native/pokemon.c', symbol: 'generic mutable-party-order choice pool, atomic move delegation, party-hit plan, and dynamic multihit execution'},
		];
	}
	if ((kind === 'move' && id === 'smellingsalts') ||
		(kind === 'event_hook' && id === 'move.smellingsalts.onHit')) {
		return [
			{path: 'native/gen3_slice_data.c', symbol: 'generated target-status power predicate and Smelling Salts Hit program'},
			{path: 'native/pokemon.c', symbol: 'generic pre-BasePower target-status adjustment, Substitute-null target staging, and major-status clear transaction'},
		];
	}
	if ((kind === 'move' && id === 'bellydrum') ||
		(kind === 'event_hook' && id === 'move.bellydrum.onHit')) {
		return [
			{path: 'native/gen3_slice_data.c', symbol: 'generated Belly Drum atomic transaction program'},
			{path: 'native/pokemon.c', symbol: 'generic thresholded direct-HP cost and maximum-stage boost transaction'},
		];
	}
	if ((kind === 'move' && id === 'transform') ||
		(kind === 'event_hook' && id === 'move.transform.onHit')) {
		return [
			{path: 'native/gen3_slice_data.c', symbol: 'generated Transform descriptor, profile-copy policy, handler program, and owner binding'},
			{path: 'native/pokemon.c', symbol: 'generic mutable battle-profile copy and base-profile restoration transaction'},
			{path: 'native/gen3_rules.c', symbol: 'typed generation stat-recalculation policy for current-turn speed staging'},
		];
	}
	if (kind === 'move' && id === 'lowkick') {
		return [
			{path: 'native/gen3_slice_data.c', symbol: 'generated species weights, Low Kick descriptor, and Gen 3 weight-power bracket policy'},
			{path: 'native/pokemon.c', symbol: 'generic current-species target-weight base-power resolution and fail-closed bundle validation'},
		];
	}
	if ((kind === 'move' && id === 'triattack') ||
		(kind === 'event_hook' && id === 'move.triattack.secondary.onHit')) {
		return [
			{path: 'native/gen3_slice_data.c', symbol: 'generated Tri Attack descriptor and immutable status distribution'},
			{path: 'native/pokemon.c', symbol: 'generic secondary-chance policy, sampled-status effect, and ordinary status admission'},
		];
	}
	if ((kind === 'move' && id === 'dreameater') ||
		(kind === 'event_hook' && id === 'move.dreameater.onTryImmunity')) {
		return [
			{path: 'native/gen3_slice_data.c', symbol: 'generated Dream Eater descriptor, TryImmunity predicate program, and owner binding'},
			{path: 'native/pokemon.c', symbol: 'generic deferred-immunity hit staging, status and volatile predicate operations, and damage-relative drain'},
			{path: 'native/gen3_slice_data.c', symbol: 'generated Liquid Ooze source-effect exclusion guard'},
		];
	}
	if (kind === 'move' && id === 'revenge') {
		return [
			{path: 'native/gen3_slice_data.c', symbol: 'generated Revenge BasePower handler program and owner binding'},
			{path: 'native/pokemon.c', symbol: 'generic attacked-by provenance guard and direct unsigned relay multiplication'},
		];
	}
	if ((kind === 'move' && (id === 'jumpkick' || id === 'highjumpkick')) ||
		(kind === 'event_hook' &&
			(id === 'move.jumpkick.onMoveFail' || id === 'move.highjumpkick.onMoveFail'))) {
		return [
			{path: 'native/gen3_slice_data.c', symbol: 'generated move failure policy and MoveFail owner binding'},
			{path: 'native/pokemon.c', symbol: 'generic failed-attempt dispatch and hypothetical-damage-to-source policy'},
		];
	}
	if (kind === 'move' && id === 'memento') {
		return [
			{path: 'native/gen3_slice_data.c', symbol: 'generated Memento boost product and IF_HIT self-faint timing'},
			{path: 'native/pokemon.c', symbol: 'generic successful-hit self-faint queueing before selected-action AfterMove and faint drain'},
		];
	}
	if ((kind === 'move' && id === 'painsplit') ||
		(kind === 'event_hook' && id === 'move.painsplit.onHit')) {
		return [
			{path: 'native/gen3_slice_data.c', symbol: 'generated Pain Split move, Hit callback program, and owner binding'},
			{path: 'native/pokemon.c', symbol: 'generic atomic bilateral direct-HP assignment with independent maximum-HP clamps'},
		];
	}
	if ((kind === 'ability' && id === 'truant') ||
		(kind === 'condition' && id === 'volatiles.truant') ||
		(kind === 'event_hook' && id.startsWith('ability.truant.'))) {
		return [
			{path: 'native/gen3_slice_data.c', symbol: 'generated Truant ability handlers, programs, owner bindings, and empty inherited condition descriptor'},
			{path: 'native/pokemon.c', symbol: 'generic Pokemon-owned Boolean state, initial-setup normalization, BeforeMove cancellation, and ordered residual dispatch'},
		];
	}
	if ((kind === 'ability' && id === 'forecast') ||
		(kind === 'event_hook' && id.startsWith('ability.forecast.'))) {
		return [
			{path: 'native/gen3_slice_data.c', symbol: 'generated Forecast Start and WeatherChange handlers, immutable form policy, and owner bindings'},
			{path: 'native/pokemon.c', symbol: 'generic current-species overlay, single-owner event delegation, ordered each-event dispatch, and weather-form projection'},
		];
	}
	if ((kind === 'move' && id === 'curse') ||
		(kind === 'condition' && id === 'volatiles.curse') ||
		(kind === 'event_hook' && id.startsWith('move.curse.'))) {
		return [
			{path: 'native/gen3_slice_data.c', symbol: 'generated Curse invocation profiles, selector, move and condition handlers, programs, and owner bindings'},
			{path: 'native/pokemon.c', symbol: 'generic profile selection, target normalization, guarded move effects, persistent condition lifecycle, and maximum-HP fraction operations'},
		];
	}
	if ((kind === 'move' && id === 'focuspunch') ||
		(kind === 'condition' && id === 'volatiles.focuspunch') ||
		(kind === 'event_hook' && id.startsWith('move.focuspunch.'))) {
		return [
			{path: 'native/gen3_slice_data.c', symbol: 'generated Focus Punch preparation condition, ordered handlers, programs, and owner bindings'},
			{path: 'native/pokemon.c', symbol: 'generic pre-turn action, condition payload guard, target-owned Hit dispatch, volatile admission, and action cancellation'},
		];
	}
	if ((kind === 'move' && ['camouflage', 'conversion'].includes(id)) ||
		(kind === 'event_hook' &&
		 ['move.camouflage.onHit', 'move.conversion.onHit'].includes(id))) {
		return [
			{path: 'native/gen3_slice_data.c', symbol: 'generated Camouflage literal-type and Conversion current-slot type-selection programs'},
			{path: 'native/pokemon.c', symbol: 'generic effective-type replacement and current mutable move-slot type sampler'},
		];
	}
	if ((kind === 'move' && id === 'spite') ||
		(kind === 'event_hook' && id === 'move.spite.onHit')) {
		return [
			{path: 'native/gen3_slice_data.c', symbol: 'generated Spite move, Hit handler program, and owner binding'},
			{path: 'native/pokemon.c', symbol: 'generic target-last-move uniform PP deduction with labeled draw and clamping'},
		];
	}
	if ((kind === 'move' && id === 'minimize') ||
		(kind === 'condition' && id === 'volatiles.minimize') ||
		(kind === 'event_hook' && id.startsWith('move.minimize.condition.'))) {
		return [
			{path: 'native/gen3_slice_data.c', symbol: 'generated Minimize boost, persistent condition handlers, move-flag guard, and owner bindings'},
			{path: 'native/pokemon.c', symbol: 'generic boost, volatile Restart, reversed ModifyDamage discovery, and switch cleanup'},
		];
	}
	if ((kind === 'move' && id === 'rage') ||
		(kind === 'condition' && id === 'volatiles.rage') ||
		(kind === 'event_hook' && id.startsWith('move.rage.condition.'))) {
		return [
			{path: 'native/gen3_slice_data.c', symbol: 'generated Rage move effect, persistent condition handlers, programs, and owner bindings'},
			{path: 'native/pokemon.c', symbol: 'generic connected-hit installation, category guard, holder boost, handler ordering, and pre-move removal'},
		];
	}
	if ((kind === 'move' && id === 'conversion2') ||
		(kind === 'event_hook' && id === 'move.conversion2.onHit')) {
		return [
			{path: 'native/gen3_slice_data.c', symbol: 'generated Conversion 2 descriptor, ordered type-response policy, Struggle override, handler program, and owner binding'},
			{path: 'native/pokemon.c', symbol: 'generic resolved invoked-move history and sampled source type-response operation'},
		];
	}
	if ((kind === 'move' && ['stockpile', 'spitup', 'swallow'].includes(id)) ||
		(kind === 'condition' && id === 'volatiles.stockpile') ||
		(kind === 'event_hook' && /^move\.(stockpile|spitup|swallow)\./.test(id))) {
		return [
			{path: 'native/gen3_slice_data.c', symbol: 'generated Stockpile bounded-counter condition, move descriptors, heal policy, handler programs, and owner bindings'},
			{path: 'native/pokemon.c', symbol: 'generic bounded-counter lifecycle, dynamic BasePower relay, counter-indexed heal, called-move AfterMove ownership, and volatile removal'},
		];
	}
	if ((kind === 'move' && ['rollout', 'iceball', 'defensecurl'].includes(id)) ||
		(kind === 'condition' && ['volatiles.rollout', 'volatiles.iceball',
			'volatiles.defensecurl'].includes(id)) ||
		(kind === 'event_hook' && implementedEventHooks.has(id) &&
			/^move\.(rollout|iceball|defensecurl)\./.test(id))) {
		return [
			{path: 'native/gen3_slice_data.c', symbol: 'generated locked-ramp policies, move/condition descriptors, handler programs, and owner bindings'},
			{path: 'native/pokemon.c', symbol: 'generic locked-ramp installation, base-power advancement, forced selection, residual expiry, and marker lookup'},
		];
	}
	if ((kind === 'move' && id === 'furycutter') ||
		(kind === 'condition' && id === 'volatiles.furycutter') ||
		(kind === 'event_hook' && id.startsWith('move.furycutter.'))) {
		return [
			{path: 'native/gen3_slice_data.c', symbol: 'generated Fury Cutter move descriptor, BasePower/Hit programs, condition Start/Restart programs, and owner bindings'},
			{path: 'native/pokemon.c', symbol: 'generic source-owned condition installation, counter advancement, relay multiplication, residual expiry, and switch cleanup'},
		];
	}
	if ((kind === 'move' && id === 'bide') ||
		(kind === 'condition' && id === 'volatiles.bide') ||
		(kind === 'event_hook' && id.startsWith('move.bide.condition.'))) {
		return [
			{path: 'native/gen3_slice_data.c', symbol: 'generated Bide descriptor, stored-damage lifecycle programs, direct pre-use program, and constructed-hit template'},
			{path: 'native/pokemon.c', symbol: 'generic stored-damage accumulation, pre-use cancellation stage, constructed-hit pipeline, targeting, and condition cleanup'},
		];
	}
	if ((kind === 'move' && id === 'perishsong') ||
		(kind === 'condition' && id === 'volatiles.perishsong') ||
		(kind === 'event_hook' && id.startsWith('move.perishsong.'))) {
		return [
			{path: 'native/gen3_slice_data.c', symbol: 'generated Perish Song HitField, Residual, and End programs and owner bindings'},
			{path: 'native/pokemon.c', symbol: 'generic field-active admission, countdown lifecycle, queued faint drain, switch cleanup, and terminal resolution'},
		];
	}
	if ((kind === 'move' && id === 'skillswap') ||
		(kind === 'event_hook' && id === 'move.skillswap.onHit')) {
		return [
			{path: 'native/gen3_slice_data.c', symbol: 'generated Skill Swap move-owned Hit program and ability semantic admission flags'},
			{path: 'native/pokemon.c', symbol: 'two-gate SetAbility transaction and generic ordered ability End/replacement lifecycle'},
		];
	}
	if ((kind === 'move' && ['fissure', 'guillotine', 'horndrill', 'sheercold'].includes(id)) ||
		(kind === 'ability' && id === 'sturdy') ||
		(kind === 'event_hook' && id === 'ability.sturdy.onTryHit')) {
		return [
			{path: 'native/gen3_slice_data.c', symbol: 'generated OHKO descriptors and Sturdy TryHit handler program'},
			{path: 'native/pokemon.c', symbol: 'typed OHKO accuracy gate, current-HP damage formula, and generic ordered TryHit dispatch'},
		];
	}
	if ((kind === 'ability' && ['plus', 'minus'].includes(id)) ||
		(kind === 'event_hook' && /^ability\.(plus|minus)\.onModifySpA$/.test(id))) {
		return [
			{path: 'native/gen3_slice_data.c', symbol: 'generated Plus/Minus relational ability handlers and owner bindings'},
			{path: 'native/pokemon.c', symbol: 'generic any-living-active-ability guard and ordered scalar modifier relay'},
		];
	}
	if (kind === 'move' && id === 'teleport') return [
		{path: 'native/gen3_slice_data.c', symbol: 'generated move-owned constant-false Try program'},
		{path: 'native/pokemon.c', symbol: 'generic cancellable move-owned Try dispatch'},
	];
	if ((kind === 'move' && id === 'naturepower') ||
		(kind === 'event_hook' && id === 'move.naturepower.onHit')) return [
		{path: 'native/gen3_slice_data.c', symbol: 'generated Nature Power fixed-call handler and Swift operand'},
		{path: 'native/pokemon.c', symbol: 'generic CALL_FIXED_MOVE operation and called-move reentry'},
	];
	if ((kind === 'move' && ['mimic', 'sketch'].includes(id)) ||
		(kind === 'event_hook' && /^move\.(mimic|sketch)\.onHit$/.test(id))) return [
		{path: 'native/gen3_slice_data.c', symbol: 'generated Mimic/Sketch copy eligibility and move-owned Hit programs'},
		{path: 'native/pokemon.c', symbol: 'generic current/base move-slot copy operation and switch restoration'},
	];
	if ((kind === 'move' && id === 'sleeptalk') ||
		(kind === 'event_hook' && id.startsWith('move.sleeptalk.'))) return [
		{path: 'native/gen3_slice_data.c', symbol: 'generated Sleep Talk Try, TryHit volatile-set guard, and current-slot call handlers'},
		{path: 'native/pokemon.c', symbol: 'generic move-owned admission, current-slot eligibility selection, and called-move reentry'},
	];
	if ((kind === 'ability' && id === 'flashfire') ||
		(kind === 'condition' && id === 'volatiles.flashfire') ||
		(kind === 'event_hook' && id.startsWith('ability.flashfire.'))) {
		return [
			{path: 'native/gen3_slice_data.c', symbol: 'generated Flash Fire ability/condition handlers, owner bindings, and programs'},
			{path: 'native/pokemon.c', symbol: 'generic TryHit cancellation, volatile lifecycle, ability-end cleanup, and ordered damage relay'},
		];
	}
	if (kind === 'species_form') return [{path: 'native/gen3_slice_data.c', symbol: 'SPECIES_CATALOG'}];
	if ((kind === 'move' && id === 'leechseed') ||
		(kind === 'ability' && id === 'liquidooze') ||
		(kind === 'condition' && id === 'volatiles.leechseed') ||
		(kind === 'event_hook' && (id.startsWith('move.leechseed.') ||
			id === 'ability.liquidooze.onSourceTryHeal' ||
			id === 'move.rapidspin.onAfterHit' ||
			id === 'move.rapidspin.onAfterSubDamage'))) {
		return [
			{path: 'native/gen3_slice_data.c', symbol: 'generated Leech Seed, Liquid Ooze, and Rapid Spin handler/effect programs'},
			{path: 'native/pokemon.c', symbol: 'generic source-position residual transfer, TryHeal relay, and guaranteed post-hit cleanup'},
		];
	}
	if ((kind === 'move' && ['roar', 'whirlwind', 'ingrain'].includes(id)) ||
		(kind === 'ability' && id === 'suctioncups') ||
		(kind === 'condition' && id === 'volatiles.ingrain') ||
		(kind === 'event_hook' && (/^move\.ingrain\.condition\./.test(id) ||
			id === 'ability.suctioncups.onDragOut'))) {
		return [
			{path: 'native/gen3_slice_data.c', symbol: 'generated force-switch effects, Ingrain/Suction Cups handlers, owner bindings, and programs'},
			{path: 'native/pokemon.c', symbol: 'generic DragOut dispatch, forced-switch transaction, volatile lifecycle, trapping, and residual healing'},
		];
	}
	if ((kind === 'move' && id === 'charge') ||
		(kind === 'condition' && id === 'volatiles.charge') ||
		(kind === 'event_hook' && id.startsWith('move.charge.condition.'))) {
		return [
			{path: 'native/gen3_slice_data.c', symbol: 'generated Charge move, volatile owner bindings, and handler programs'},
			{path: 'native/pokemon.c', symbol: 'generic volatile lifecycle, BasePower relay, MoveAborted/AfterMove dispatch, and silent switch/faint cleanup'},
		];
	}
	if ((kind === 'move' && ['destinybond', 'grudge'].includes(id)) ||
		(kind === 'condition' && ['volatiles.destinybond',
			'volatiles.grudge'].includes(id)) ||
		(kind === 'event_hook' && /^move\.(destinybond|grudge)\./.test(id))) {
		return [
			{path: 'native/gen3_slice_data.c', symbol: 'generated Destiny Bond and Grudge volatile descriptors, Faint handlers, owner bindings, and guard programs'},
			{path: 'native/pokemon.c', symbol: 'generic move provenance, Faint dispatch, queued faint transaction, PP-zero operation, and volatile lifecycle'},
		];
	}
	if ((kind === 'move' && id === 'uproar') ||
		(kind === 'condition' && id === 'volatiles.uproar') ||
		(kind === 'event_hook' && id.startsWith('move.uproar.'))) {
		return [
			{path: 'native/gen3_slice_data.c', symbol: 'generated Uproar move and volatile descriptors, duration policy, handler programs, and owner bindings'},
			{path: 'native/pokemon.c', symbol: 'generic global handler discovery, active-status clearing, lock lifecycle, target Hit-before-self staging, and forced called-move execution'},
		];
	}
	if ((kind === 'move' && id === 'imprison') ||
		(kind === 'condition' && id === 'volatiles.imprison') ||
		(kind === 'event_hook' && id.startsWith('move.imprison.'))) {
		return [
			{path: 'native/gen3_slice_data.c', symbol: 'generated Imprison move, persistent volatile, foe-scoped programs, and owner bindings'},
			{path: 'native/pokemon.c', symbol: 'generic self-target TryHit, foe-scoped choice discovery, request reduction, queued BeforeMove cancellation, and switch cleanup'},
		];
	}
	if (kind === 'move' && ['triplekick', 'twineedle'].includes(id)) {
		return [
			{path: 'native/gen3_slice_data.c', symbol: 'generated fixed-count multihit, repeat-accuracy, hit-index power, and per-hit secondary descriptors'},
			{path: 'native/pokemon.c', symbol: 'generic per-hit accuracy, power, damage, secondary, Update, early-stop, and labeled-PRNG pipeline'},
		];
	}
	if ((kind === 'move' && ['futuresight', 'doomdesire', 'wish'].includes(id)) ||
		(kind === 'condition' && ['slot_conditions.futuremove',
			'slot_conditions.wish'].includes(id)) ||
		(kind === 'event_hook' && /^(condition\.futuremove\.|move\.(futuresight|doomdesire)\.onTry$|move\.wish\.condition\.onEnd$)/.test(id))) {
		return [
			{path: 'native/gen3_slice_data.c', symbol: 'SLOT_CONDITION_POLICIES'},
			{path: 'native/pokemon.c', symbol: 'install_move_slot_condition, execute_delayed_fixed_damage, and residual slot-condition execution'},
		];
	}
	if ((kind === 'move' && id === 'snatch') ||
		(kind === 'condition' && id === 'volatiles.snatch') ||
		(kind === 'event_hook' && id.startsWith('move.snatch.condition.'))) {
		return [
			{path: 'native/gen3_slice_data.c', symbol: 'generated Snatch condition, PrepareHit handler, owner binding, and effect program'},
			{path: 'native/pokemon.c', symbol: 'generic condition installation, ordered PrepareHit dispatch, and called-move reentry'},
		];
	}
	if ((kind === 'move' && ['counter', 'mirrorcoat'].includes(id)) ||
		(kind === 'condition' && ['volatiles.counter',
			'volatiles.mirrorcoat'].includes(id)) ||
		(kind === 'event_hook' && /^move\.(counter|mirrorcoat)\.(condition\.onDamage|condition\.onStart|onTry)$/.test(id)) ||
		(kind === 'target_mode' && id === 'scripted')) {
		return [
			{path: 'native/gen3_slice_data.c', symbol: 'generated retaliation descriptors, handler programs, owner bindings, and target policy'},
			{path: 'native/pokemon.c', symbol: 'generic pre-turn action expansion, requested-damage relay capture, fixed-damage response, and source-provenance target resolution'},
		];
	}
	if (kind === 'move' && nativeIDs.moves[id] !== undefined) return [{path: 'native/gen3_slice_data.c', symbol: 'POKEMON_GEN3_MOVES'}];
	if (kind === 'ability' && nativeIDs.abilities[id] !== undefined) return [{path: 'native/gen3_slice_data.c', symbol: 'POKEMON_GEN3_ABILITIES'}];
	if (kind === 'item' && nativeIDs.items[id] !== undefined) return [{path: 'native/gen3_slice_data.c', symbol: 'POKEMON_GEN3_ITEMS'}];
	if (kind === 'condition' && ['pseudo_weather.sleepclausemod',
		'pseudo_weather.freezeclausemod'].includes(id)) return [
		{path: 'native/pokemon.c', symbol: 'generated status-clause handler discovery and admission'},
		{path: 'native/singles2.c', symbol: 'resolved Gen 3 OU status-clause policies'},
	];
	if (kind === 'condition' && implementedConditions.has(id)) return [{path: 'native/pokemon.c', symbol: 'condition execution'}];
	if (kind === 'condition' && inertConditions.has(id)) return [{path: 'native/pokemon.c', symbol: 'intercept_substitute'}];
	if ((kind === 'simulator_only_condition' && id === 'trapper') ||
		(kind === 'condition' && id === 'volatiles.trapper')) return [
		{path: 'native/pokemon.c', symbol: 'ensure_hidden_source_link_marker and remove_source_linked_volatiles'},
		{path: 'native/gen3_rules.c', symbol: 'source_linked_kind condition policy'},
	];
	if (kind === 'event_hook' && ['format.sleepclausemod.onSetStatus',
		'format.freezeclausemod.onSetStatus'].includes(id)) {
		return [{path: 'native/pokemon.c', symbol: 'generated status-clause handler discovery and admission'}];
	}
	if (kind === 'event_hook' && implementedEventHooks.has(id) &&
		(/^(move\.(detect|endure|protect)\.|condition\.stall\.)/.test(id))) {
		return [{path: 'native/pokemon.c', symbol: 'generic stalling-guard installation, shared stall lifecycle, and condition-owned Damage relay'}];
	}
	if ((kind === 'condition' && id === 'volatiles.lockon') ||
		(kind === 'event_hook' && /^move\.(lockon|mindreader)\./.test(id))) {
		return [{path: 'native/pokemon.c', symbol: 'generic source-bound volatile installation and ordered Accuracy/Invulnerability dispatch'}];
	}
	if ((kind === 'move' && ['foresight', 'odorsleuth'].includes(id)) ||
		(kind === 'condition' && id === 'volatiles.foresight') ||
		(kind === 'event_hook' && /^move\.(foresight|odorsleuth)\./.test(id))) {
		return [
			{path: 'native/pokemon.c', symbol: 'generic raw-immunity admission, sparse ModifyBoost staging, and volatile lifecycle'},
			{path: 'native/gen3_slice_data.c', symbol: 'generated Foresight descriptors, programs, and owner bindings'},
		];
	}
	if (kind === 'event_hook' && id === 'move.followme.onTry') return [{
		path: 'native/pokemon.c',
		symbol: 'generic move-owned Try dispatch and post-PP cancellation',
	}];
	if (kind === 'event_hook' && implementedEventHooks.has(id) &&
		/^condition\.(hail|raindance|sandstorm|sunnyday)\.(onFieldStart|onFieldResidual|onFieldEnd|onWeather|onImmunity)$/.test(id)) {
		return [{path: 'native/pokemon.c', symbol: 'generic weather lifecycle and generated PokemonWeatherPolicy'}];
	}
	if (kind === 'event_hook' && implementedEventHooks.has(id) &&
		id.startsWith('item.whiteherb.')) {
		return [{path: 'native/pokemon.c', symbol: 'generated lifecycle dispatch, captured negative-stage mask, and held-item use transaction'}];
	}
	if (kind === 'event_hook' && implementedEventHooks.has(id) &&
		(id.startsWith('item.choiceband.') || id.startsWith('condition.choicelock.'))) {
		return [{path: 'native/pokemon.c', symbol: 'generated item relay/AfterMove program and descriptor-keyed indefinite choice-control lifecycle'}];
	}
	if (kind === 'event_hook' && implementedEventHooks.has(id) && id.startsWith('ability.oblivious.')) {
		return [{path: 'native/pokemon.c', symbol: 'generic volatile Immunity admission and generated ability Update lifecycle'}];
	}
	if (kind === 'event_hook' && id === 'ability.wonderguard.onTryHit') {
		return [{path: 'native/pokemon.c', symbol: 'generated TryHit category/type predicates and generic target-effectiveness gate'}];
	}
	if ((kind === 'item' && id === 'focusband') ||
		(kind === 'event_hook' && id === 'item.focusband.onDamage')) {
		return [{path: 'native/pokemon.c', symbol: 'ordered Damage relay with generated probability, damage-kind, and real-HP cap operations'}];
	}
	if ((kind === 'item' && id === 'leppaberry') ||
		(kind === 'event_hook' && id.startsWith('item.leppaberry.'))) {
		return [{path: 'native/pokemon.c', symbol: 'generated Update/Eat programs over generic stable PP-slot selection and restoration'}];
	}
	if ((kind === 'item' && id === 'kingsrock') ||
		(kind === 'event_hook' && id === 'item.kingsrock.onModifyMove')) {
		return [{path: 'native/pokemon.c', symbol: 'generated move-tag guard and generic active-move appended-secondary pipeline'}];
	}
	if (kind === 'event_hook' &&
		/^condition\.(brn|psn|tox)\.(onStart|onSwitchIn)$/.test(id)) {
		return [{path: 'native/pokemon.c', symbol: 'generated status-owner lifecycle dispatch and typed status-counter mutation'}];
	}
	if (kind === 'event_hook' && implementedEventHooks.has(id) && id.startsWith('move.roleplay.')) {
		return [{path: 'native/pokemon.c', symbol: 'generated ability-transfer admission and generic ability-replacement lifecycle'}];
	}
	if (kind === 'event_hook' && implementedEventHooks.has(id) && id.startsWith('move.magnitude.')) {
		return [{path: 'native/pokemon.c', symbol: 'generated weighted active-move power program and generic move-self event dispatch'}];
	}
	if ((kind === 'move' && id === 'present') ||
		(kind === 'event_hook' && id === 'move.present.onModifyMove')) {
		return [{path: 'native/pokemon.c', symbol: 'generated weighted damage-or-heal active-move outcome and shared hit-admission/heal pipeline'}];
	}
	if ((kind === 'move' && id === 'hiddenpower') ||
		(kind === 'event_hook' && id === 'move.hiddenpower.onModifyMove')) {
		return [{path: 'native/pokemon.c', symbol: 'generation-normalized personal move profile, generated ModifyMove program, and ordinary hit pipeline'}];
	}
	if (kind === 'event_hook' && implementedEventHooks.has(id) &&
		/^move\.(mudsport|watersport)\.condition\./.test(id)) {
		return [{path: 'native/pokemon.c', symbol: 'generic volatile installation and AnyBasePower handler discovery/relay'}];
	}
	if (kind === 'event_hook' && implementedEventHooks.has(id)) return [{path: 'native/pokemon.c', symbol: /^condition\.(brn|psn|tox)\.onResidual$/.test(id) ? 'generated status-residual policy discovery and generic residual executor' : id.startsWith('condition.frz.') ? 'generic status-owner lifecycle dispatch and generated freeze handler programs' : /^move\.(bounce|dig|dive|fly|razorwind|skullbash|skyattack)\./.test(id) ? 'generic two-turn lifecycle, descriptor-driven semi-invulnerability, ordered damage relay, and weather Immunity dispatch' : id === 'move.falseswipe.onDamage' ? 'generic real-HP Damage relay and generated cap program' : id === 'condition.par.onBeforeMove' ? 'generic status-owner BeforeMove dispatch and generated action-gate program' : id.includes('serenegrace') ? 'generated secondary-chance policy over explicit effect-product ownership' : id.startsWith('condition.slp.') || id === 'move.snore.onTry' ? 'generic status-owner lifecycle and generated sleep/Snore programs' : id.includes('haze') ? 'typed move-owned HitField callback and living-active boost-product clear' : /ability\.(flamebody|static|poisonpoint|effectspore|roughskin)\./.test(id) ? 'generic DamagingHit dispatch and generated contact-response program' : id.includes('damp') ? 'generic global TryMove dispatch and generated self-faint-timing guard' : id.includes('pressure') ? 'generic target-resolved DeductPP relay and owner lifecycle dispatch' : id.includes('naturalcure') ? 'generic SwitchOut event and generated holder-status clear program' : id.includes('refresh') ? 'typed move-owned Hit callback and shared status-clear transaction' : id.includes('psychup') ? 'typed move-owned Hit callback and atomic boost-stage product copy' : id.includes('brickbreak') ? 'generated move-owned TryHit program and generic selected-side condition removal transaction' : id.includes('ModifyDamagePhase1') ? 'generic ordered ModifyDamagePhase1 relay and generated side-condition programs' : id.includes('mist') ? 'generic side-condition lifecycle and generated TryBoost filter program' : /^(move\.focusenergy\.condition|item\.(scopelens|luckypunch|stick)|ability\.(battlearmor|shellarmor))\./.test(id) ? 'generated critical-stage relay, declarative species guard, and cancellable CriticalHit programs' : /^item\.(deepseascale|deepseatooth|lightball|machobrace|metalpowder|souldew)\./.test(id) ? 'generic ordered stat relay and generated item-owned species guard program' : /^(ability\.(compoundeyes|guts|hugepower|hustle|purepower)|item\.thickclub)\./.test(id) ? 'generated scalar relay program and declarative holder guards' : /^(move\.(thief|covet|knockoff|recycle|trick)|ability\.stickyhold|item\.mail)\./.test(id) ? 'generic item mutation transaction and generated holder gates' : id.includes('solarbeam') || id.includes('twoturnmove') ? 'generic two-turn lifecycle and weather-parameterized active move frame mutation' : id.includes('weatherball') || id.includes('thunder') ? 'generation-parameterized active move frame mutation' : id.includes('lockedmove') ? 'generic forced-choice selector and installed-condition lifecycle dispatcher' : /move\.(taunt|disable|encore|torment)\./.test(id) ? 'generated lifecycle handlers plus descriptor-keyed choice-control request and action events' : id.includes('ModifySecondaries') ? 'generic ModifySecondaries filter and generated exceptional handler' : id.includes('confusion') || id.includes('owntempo') ? 'generic volatile lifecycle, BeforeMove dispatcher, and post-effects Hit' : id.startsWith('item.') ? 'generic eat-item transaction and captured residual owner dispatch' : id.includes('WeatherModifyDamage') ? 'apply_weather_damage_event and generated conditional Q12 handler program' : id.startsWith('ability.') ? 'generated status immunity policy and ordered status transaction' : id.includes('mirrormove') ? 'attackedBy provenance and called-move effect program' : id.includes('magiccoat') ? 'active-move invocation and reflection handler program' : 'Substitute lifecycle and TryPrimaryHit interception'}];
	if (kind === 'event_hook' && inertEventHooks.has(id)) return [{
		path: id === 'move.secretpower.onModifyMove' || id === 'condition.mustrecharge.onStart' ? 'native/gen3_slice_data.c' :
			id.startsWith('move.splash.') || id === 'move.payday.onHit' ? 'native/pokemon.c' :
			'native/gen3_slice_data.c',
		symbol: id === 'move.payday.onHit' ?
			'generic damaging-move execution; protocol-only callback denotation omitted' :
			id === 'condition.mustrecharge.onStart' ?
				'generated unbound zero-program descriptor; protocol-only callback denotation omitted' :
			id.startsWith('move.splash.') ?
				'generic status-move execution; protocol-only callback denotation omitted' :
			id === 'move.secretpower.onModifyMove' ?
				'generated zero-program ModifyMove handler for the reachable terrain-free identity transformation' :
			'POKEMON_GEN3_HANDLER_WEATHER_BALL_MODIFY_TYPE dormant flattened descriptor',
	}];
	if (kind === 'target_mode' && implementedTargets.has(id)) return [{path: 'native/pokemon.c', symbol: 'target resolution'}];
	if (kind === 'format_rule' && ['sleepclausemod', 'freezeclausemod'].includes(id)) return [
		{path: 'native/singles2.c', symbol: 'GEN3_OU_STATUS_CLAUSES'},
		{path: 'native/pokemon.c', symbol: 'generated status-clause handler discovery and admission'},
	];
	if (kind === 'format_rule' &&
		['endlessbattleclause', 'standardag', 'standard'].includes(id)) return [
		{path: 'native/singles2.c', symbol: 'POKEMON_GEN3_OU_POLICY terminal policy'},
		{path: 'native/pokemon.c', symbol: 'generic post-turn terminal policy'},
	];
	if (kind === 'format_rule' && atomicAdmissionRuleCases[id]) return [
		{path: 'native/pokemon_admission.c', symbol: 'pokemon_admission_check_set'},
		{path: 'native/gen3_admission_data.c', symbol: 'admission_rules'},
	];
	if (kind === 'format_rule' && aggregateAdmissionRuleCases[id]) return [{
		path: 'native/gen3_admission_data.c',
		symbol: 'admission_rules source_rule_id flattened parent provenance',
	}];
	if (kind === 'format_rule' && tagAdmissionRuleCases[id]) return [
		{path: 'native/pokemon_admission.c', symbol: 'generic generated identity-tag ban dispatch'},
		{path: 'native/gen3_admission_data.c', symbol: 'generated identity tags and tag-ban rules'},
	];
	if (kind === 'format_rule' && allOfAdmissionRuleCases[id]) return [
		{path: 'native/pokemon_admission.c', symbol: 'generic fixed-capacity all-of predicate dispatch'},
		{path: 'native/gen3_admission_data.c', symbol: 'generated identity predicates and all-of rules'},
	];
	if (kind === 'format_rule' && teamAdmissionRuleCases[id]) return [
		{path: 'native/pokemon_admission.c', symbol: 'pokemon_admission_check_team'},
		{path: 'native/gen3_admission_data.c', symbol: 'generated team-scoped predicate rules'},
	];
	if (kind === 'format_rule' && statAdmissionRuleCases[id]) return [
		{path: 'native/pokemon_admission.c', symbol: 'generated set stat-vector validation'},
		{path: 'native/gen3_admission_data.c', symbol: 'resolved EV vector policy'},
	];
	if (kind === 'format_rule' && relationAdmissionRuleCases[id]) return [
		{path: 'native/pokemon_admission.c', symbol: 'generic allowed-relation interpreter'},
		{path: 'native/gen3_admission_data.c', symbol: 'generated species-to-ability relation'},
	];
	if (kind === 'format_rule' && normalizationAdmissionRuleCases[id]) return [
		{path: 'native/pokemon_admission.c', symbol: 'transactional normalized set/team admission'},
		{path: 'native/gen3_admission_data.c', symbol: 'generated guarded species rewrites'},
	];
	if (kind === 'format_rule' && nicknameAdmissionRuleCases[id]) return [
		{path: 'native/pokemon_admission.c', symbol: 'transactional nickname normalization, impersonation, and team uniqueness'},
		{path: 'native/gen3_admission_data.c', symbol: 'generated species display/base metadata and Nickname Clause rule'},
	];
	if (kind === 'format_rule' && obtainabilityAdmissionRuleCases[id]) return [
		{path: 'native/pokemon_admission.c', symbol: 'transactional normalized set and generated rule dispatch'},
		{path: 'native/pokemon_acquisition.c', symbol: 'bounded acquisition provenance interpreter'},
		{path: 'native/gen3_admission_data.c', symbol: 'flattened Gen 3 acquisition and event tables'},
	];
	if (kind === 'format_rule' && implementedFormatRules.has(id)) return [{path: 'native/pokemon.c', symbol: 'pokemon_validate_catalog_team'}];
	return [];
}
function evidence(kind, id) {
	if (kind === 'move' && moveCases[id]) {
		return {
			cases: moveCases[id],
			features: [...new Set(moveCases[id].flatMap(caseID => caseFeatures.get(caseID) || []))].sort(),
		};
	}
	if (kind === 'ability' && abilityCases[id]) {
		return {
			cases: abilityCases[id],
			features: [...new Set(abilityCases[id].flatMap(caseID => caseFeatures.get(caseID) || []))].sort(),
		};
	}
	if (kind === 'item' && itemCases[id]) {
		return {
			cases: itemCases[id],
			features: [...new Set(itemCases[id].flatMap(caseID => caseFeatures.get(caseID) || []))].sort(),
		};
	}
	if (kind === 'format_rule' && formatRuleCases[id]) {
		return {
			cases: formatRuleCases[id],
			features: [...new Set(formatRuleCases[id].flatMap(caseID => caseFeatures.get(caseID) || []))].sort(),
		};
	}
	if (kind === 'format_rule' && obtainabilityAdmissionRuleCases[id]) {
		return {cases: obtainabilityAdmissionRuleCases[id], features: [
			'admission.obtainability', 'format.validation',
		]};
	}
	if (kind === 'condition') {
		const cases = conditionCases[id] || [];
		const features = new Set(cases.flatMap(caseID => caseFeatures.get(caseID) || []));
		return {cases, features: [...features].sort()};
	}
	if (kind === 'simulator_only_condition' && id === 'trapper') {
		const cases = [
			...moveCases.block, ...moveCases.meanlook, ...moveCases.spiderweb,
		];
		return {
			cases,
			features: [...new Set(cases.flatMap(
				caseID => caseFeatures.get(caseID) || []))].sort(),
		};
	}
	if (kind === 'event_hook' && eventHookCases[id]) {
		return {
			cases: eventHookCases[id],
			features: [...new Set(eventHookCases[id].flatMap(caseID => caseFeatures.get(caseID) || []))].sort(),
		};
	}
	if (kind === 'event_hook' && unreachableEventHooks.has(id)) {
		return {cases: [], features: []};
	}
	if (kind === 'event_hook' && inertEventHooks.has(id)) {
		const cases = id === 'move.payday.onHit' ? moveCases.payday :
			id === 'condition.mustrecharge.onStart' ? [
				...moveCases.hyperbeam, ...moveCases.blastburn,
				...moveCases.frenzyplant, ...moveCases.hydrocannon,
			] :
			id.startsWith('move.splash.') ? moveCases.splash :
			id === 'move.secretpower.onModifyMove' ? moveCases.secretpower :
			moveCases.weatherball;
		return {cases, features: ['state.canonical']};
	}
	if (kind === 'target_mode') {
		return {
			cases: targetCases[id] || [],
			features: targetCases[id] ? ['choice.move', 'state.canonical', 'target.singles-normalization'] : [],
		};
	}
	const found = usage[kind]?.get(id);
	return {cases: found ? [...found.cases].sort() : [], features: found ? [...found.features].sort() : []};
}
function classify(kind, id) {
	const proof = evidence(kind, id);
	if (kind === 'simulator_only_condition') return id === 'trapper' ?
		'implemented' : 'unreachable';
	if (kind === 'species_form') return 'inert';
	if (kind === 'move' && implementedMoves.has(id) && proof.cases.length) return 'implemented';
	if (kind === 'ability' && implementedAbilities.has(id) && proof.cases.length) return 'implemented';
	if (kind === 'ability' && inertAbilities.has(id) && proof.cases.length) return 'inert';
	if (kind === 'item' && implementedItems.has(id) && proof.cases.length) return 'implemented';
	if (kind === 'item' && inertItems.has(id) && proof.cases.length) return 'inert';
	if (kind === 'condition' && implementedConditions.has(id)) return 'implemented';
	if (kind === 'condition' && inertConditions.has(id)) return 'inert';
	if (kind === 'condition' && unreachableConditions.has(id)) return 'unreachable';
	if (kind === 'event_hook' && implementedEventHooks.has(id)) return 'implemented';
	if (kind === 'event_hook' && inertEventHooks.has(id)) return 'inert';
	if (kind === 'event_hook' && unreachableEventHooks.has(id)) return 'unreachable';
	if (kind === 'target_mode' && implementedTargets.has(id)) return 'implemented';
	if (kind === 'format_rule' && inertFormatRules.has(id)) return 'inert';
	if (kind === 'format_rule' && unreachableFormatRules.has(id)) return 'unreachable';
	if (kind === 'format_rule' && implementedFormatRules.has(id)) return 'implemented';
	return 'unsupported';
}
function sourcePaths(kind) {
	if (kind === 'species_form') return artifact.sources.species;
	if (kind === 'move') return artifact.sources.moves;
	if (kind === 'ability') return artifact.sources.abilities;
	if (kind === 'item') return artifact.sources.items;
	if (['condition', 'simulator_only_condition'].includes(kind)) return artifact.sources.conditions;
	if (kind === 'format_rule') return artifact.sources.format;
	return artifact.sources.runtime;
}
function withDefiningHookSource(kind, id, sources) {
	if (kind !== 'event_hook') return sources;
	const source = callbackHookSources.get(id);
	if (!source) throw new Error(`event hook lacks frozen defining source: ${id}`);
	return [source, ...sources.filter(candidate =>
		candidate.path !== source.path || candidate.symbol !== source.symbol)];
}
function entry(kind, id, numericID = null) {
	const classification = classify(kind, id);
	const proof = evidence(kind, id);
	const native = nativeBoundary(kind, id);
	const reachable = classification === 'unreachable'
		? kind === 'format_rule' && id === '-unreleased'
			? ['The generated Gen 3 admission universe contains zero hidden-ability slots, so this hidden-ability release rule has no submitted-set match']
			: kind === 'format_rule' && id === 'Huntail + Shell Smash + Sucker Punch'
				? ['The resolved inherited complex ban requires Shell Smash and Sucker Punch, whose Gen 5 and Gen 4 identities are absent from the normalized Gen 3 move universe']
				: kind === 'format_rule' && id === 'Hypnosis + Gengarite'
					? ['The resolved inherited complex ban requires Gengarite, whose Gen 6 identity is absent from the normalized Gen 3 item universe']
		: id === 'item.whiteherb.onAnyAfterMega'
			? ['Mega Evolution does not exist in Gen 3, so this inherited callback cannot be dispatched']
			: id === 'volatiles.helpinghand' || id.startsWith('move.helpinghand.condition.') ||
				id === 'move.helpinghand.onTryHit'
				? ['Gen 3 OU singles has no adjacent ally target, so Helping Hand cannot install or dispatch its condition']
				: id.startsWith('move.toxic.condition.')
					? ['Effective Gen 3 Toxic has no PrepareHit or volatile installer, so its inherited nested callbacks have no owner state to dispatch']
				: id === 'ability.lightningrod.onFoeRedirectTarget'
					? ['RedirectTarget dispatch is gated to activePerHalf above one, so this foe-redirection callback cannot run in Gen 3 OU singles']
				: id === 'slot_conditions.followme' || id.startsWith('move.followme.condition.')
					? ['Follow Me onTry rejects when activePerHalf is one, so its slot condition cannot be installed or dispatched in Gen 3 OU singles']
					: id === 'move.hiddenpower.onModifyType'
						? ['Gen 3 scripts omit the separate ModifyType phase and execute Hidden Power construction through onModifyMove']
						: ['generated simulator-only condition has no reachable descriptor reference']
		: kind === 'simulator_only_condition' && id === 'trapper'
			? ['Block, Mean Look, and Spider Web pass trapper as linkedStatus; native normalizes that reachable source-side marker into the visible source-linked relation']
			: ['present in pinned generated Gen3OU inventory'];
	const gap = classification !== 'unsupported' ? []
		: kind === 'ability' && id === 'guts' ? ['interaction-gap:ability:guts:psn-slp-frz']
		: [`semantics-unverified:${kind}:${id}`];
	const verification = kind === 'species_form' ? [{
		kind: 'catalog-differential', path: 'verify/catalog/test.js', symbol: 'all 369 species static records',
	}] : kind === 'format_rule' && inertFormatRules.has(id) ? [{
		kind: 'focused-native', path: 'native/test_pokemon.c',
		symbol: 'test_gen3_ou_format_manifest_and_bounded_legality',
	}] : kind === 'format_rule' && aggregateAdmissionRuleCases[id] ?
		aggregateAdmissionRuleCases[id].map(symbol => ({
			kind: 'admission-differential', path: 'verify/admission/cases.json', symbol,
		}))
	: kind === 'format_rule' && tagAdmissionRuleCases[id] ?
		tagAdmissionRuleCases[id].map(symbol => ({
			kind: 'admission-differential', path: 'verify/admission/cases.json', symbol,
		}))
	: kind === 'format_rule' && allOfAdmissionRuleCases[id] ?
		allOfAdmissionRuleCases[id].map(symbol => ({
			kind: 'admission-differential', path: 'verify/admission/cases.json', symbol,
		}))
	: kind === 'format_rule' && teamAdmissionRuleCases[id] ?
		teamAdmissionRuleCases[id].map(symbol => ({
			kind: 'admission-differential', path: 'verify/admission/cases.json', symbol,
		}))
	: kind === 'format_rule' && statAdmissionRuleCases[id] ?
		statAdmissionRuleCases[id].map(symbol => ({
			kind: 'admission-differential', path: 'verify/admission/cases.json', symbol,
		}))
	: kind === 'format_rule' && relationAdmissionRuleCases[id] ?
		relationAdmissionRuleCases[id].map(symbol => ({
			kind: 'admission-differential', path: 'verify/admission/cases.json', symbol,
		}))
	: kind === 'format_rule' && normalizationAdmissionRuleCases[id] ?
		normalizationAdmissionRuleCases[id].map(symbol => ({
			kind: 'admission-differential', path: 'verify/admission/cases.json', symbol,
		}))
	: kind === 'format_rule' && nicknameAdmissionRuleCases[id] ?
		nicknameAdmissionRuleCases[id].map(symbol => ({
			kind: 'admission-differential', path: 'verify/admission/cases.json', symbol,
		}))
	: kind === 'format_rule' && obtainabilityAdmissionRuleCases[id] ? [
		...obtainabilityAdmissionRuleCases[id].map(symbol => ({
			kind: 'admission-differential', path: 'verify/admission/cases.json', symbol,
		})),
		{kind: 'randomized-differential', path: 'verify/admission/randomized-obtainability-report.json', symbol: 'zero current divergences'},
	]
	: kind === 'format_rule' && atomicAdmissionRuleCases[id] ? [{
		kind: 'admission-differential', path: 'verify/admission/cases.json',
		symbol: atomicAdmissionRuleCases[id],
	}] : kind === 'format_rule' && implementedFormatRules.has(id) && !formatRuleCases[id] ? [{
		kind: 'focused-native', path: 'native/test_pokemon.c', symbol: 'test_gen3_ou_format_manifest_and_bounded_legality',
	}] : [];
	const semanticFeatures = kind === 'species_form' ? ['catalog.species-static']
		: kind === 'format_rule' && inertFormatRules.has(id) ?
			['format.protocol-policy', 'state.canonical']
		: kind === 'format_rule' && obtainabilityAdmissionRuleCases[id] ?
			['admission.obtainability', 'format.validation']
		: kind === 'format_rule' && implementedFormatRules.has(id) && !formatRuleCases[id] ? ['format.validation'] : proof.features;
	const focusedTests = classification === 'unreachable' ? []
		: kind === 'format_rule' && inertFormatRules.has(id) ?
			['native/test_pokemon.c#test_gen3_ou_format_manifest_and_bounded_legality']
		: (kind === 'move' && id === 'assist') ||
			(kind === 'event_hook' && id === 'move.assist.onHit') ?
			['native/test_pokemon.c#test_assist_current_party_slot_delegation']
		: (kind === 'move' && id === 'beatup') ||
			(kind === 'condition' && id === 'volatiles.beatup') ||
			(kind === 'event_hook' && id.startsWith('move.beatup.')) ?
			['native/test_pokemon.c#test_beat_up_party_hit_plan']
		: (kind === 'move' && id === 'metronome') ||
			(kind === 'event_hook' && id === 'move.metronome.onHit') ?
			['native/test_pokemon.c#test_generated_move_call_pool_and_atomic_delegation']
		: ((kind === 'format_rule' && ['sleepclausemod', 'freezeclausemod'].includes(id)) ||
			(kind === 'condition' && ['pseudo_weather.sleepclausemod', 'pseudo_weather.freezeclausemod'].includes(id)) ||
			(kind === 'event_hook' && ['format.sleepclausemod.onSetStatus', 'format.freezeclausemod.onSetStatus'].includes(id))) ?
			['native/test_pokemon.c#test_status_ability_hooks_and_clauses',
				'native/test_pokemon.c#test_generated_rest_programs']
		: kind === 'species_form' ? ['native/test_pokemon.c#test_complete_identity_catalog_is_not_executable_support']
		: (kind === 'ability' && id === 'truant') ||
			(kind === 'condition' && id === 'volatiles.truant') ||
			(kind === 'event_hook' && id.startsWith('ability.truant.')) ?
			['native/test_pokemon.c#test_generated_truant_pokemon_owned_phase']
		: (kind === 'ability' && id === 'forecast') ||
			(kind === 'event_hook' && id.startsWith('ability.forecast.')) ?
			['native/test_pokemon.c#test_generated_weather_form_projection']
		: (kind === 'move' && id === 'curse') ||
			(kind === 'condition' && id === 'volatiles.curse') ||
			(kind === 'event_hook' && id.startsWith('move.curse.')) ?
			['native/test_pokemon.c#test_curse_invocation_profiles_and_lifecycle']
		: (kind === 'move' && id === 'rage') ||
			(kind === 'condition' && id === 'volatiles.rage') ||
			(kind === 'event_hook' && id.startsWith('move.rage.condition.')) ?
			['native/test_pokemon.c#test_rage_generated_reactive_lifecycle']
		: (kind === 'move' && id === 'focuspunch') ||
			(kind === 'condition' && id === 'volatiles.focuspunch') ||
			(kind === 'event_hook' && id.startsWith('move.focuspunch.')) ?
			['native/test_pokemon.c#test_focus_punch_prepared_action_lifecycle']
		: (kind === 'move' && id === 'minimize') ||
			(kind === 'condition' && id === 'volatiles.minimize') ||
			(kind === 'event_hook' && id.startsWith('move.minimize.condition.')) ?
			['native/test_pokemon.c#test_minimize_generated_marker_and_damage_modifier']
		: (kind === 'move' && id === 'spite') ||
			(kind === 'event_hook' && id === 'move.spite.onHit') ?
			['native/test_pokemon.c#test_spite_target_last_move_pp_transaction']
		: (kind === 'move' && ['camouflage', 'conversion'].includes(id)) ||
			(kind === 'event_hook' &&
			 ['move.camouflage.onHit', 'move.conversion.onHit'].includes(id)) ?
			['native/test_pokemon.c#test_current_move_slot_type_overlays']
		: (kind === 'move' && id === 'conversion2') ||
			(kind === 'event_hook' && id === 'move.conversion2.onHit') ?
			['native/test_pokemon.c#test_conversion_2_resolved_last_move_response',
				'native/test_pokemon.c#test_type_response_policy_validation_is_atomic']
		: (kind === 'move' && ['stockpile', 'spitup', 'swallow'].includes(id)) ||
			(kind === 'condition' && id === 'volatiles.stockpile') ||
			(kind === 'event_hook' && /^move\.(stockpile|spitup|swallow)\./.test(id)) ?
			['native/test_pokemon.c#test_stockpile_counter_power_and_heal_family',
				'native/test_pokemon.c#test_counter_heal_policy_validation_is_atomic']
		: (kind === 'move' && id === 'furycutter') ||
			(kind === 'condition' && id === 'volatiles.furycutter') ||
			(kind === 'event_hook' && id.startsWith('move.furycutter.')) ?
			['native/test_pokemon.c#test_fury_cutter_generated_ramping_power_lifecycle']
		: (kind === 'move' && ['rollout', 'iceball', 'defensecurl'].includes(id)) ||
			(kind === 'condition' && ['volatiles.rollout', 'volatiles.iceball',
				'volatiles.defensecurl'].includes(id)) ||
			(kind === 'event_hook' && /^move\.(rollout|iceball|defensecurl)\./.test(id)) ?
			['native/test_pokemon.c#test_locked_ramp_rollout_ice_ball_and_defense_curl']
		: (kind === 'move' && id === 'bide') ||
			(kind === 'condition' && id === 'volatiles.bide') ||
			(kind === 'event_hook' && id.startsWith('move.bide.condition.')) ?
			['native/test_pokemon.c#test_bide_stored_damage_and_direct_pre_use_stage',
				'native/test_pokemon.c#test_move_pre_use_program_bundle_validation_is_atomic']
		: (kind === 'move' && id === 'perishsong') ||
			(kind === 'condition' && id === 'volatiles.perishsong') ||
			(kind === 'event_hook' && id.startsWith('move.perishsong.')) ?
			['native/test_pokemon.c#test_perish_song_generated_lifecycle']
		: (kind === 'move' && ['fissure', 'guillotine', 'horndrill', 'sheercold'].includes(id)) ||
			(kind === 'ability' && id === 'sturdy') ||
			(kind === 'event_hook' && id === 'ability.sturdy.onTryHit') ?
			['native/test_pokemon.c#test_typed_ohko_pipeline']
		: (kind === 'ability' && ['plus', 'minus'].includes(id)) ||
			(kind === 'event_hook' && /^ability\.(plus|minus)\.onModifySpA$/.test(id)) ?
			['native/test_pokemon.c#test_relational_active_ability_modifier']
		: kind === 'move' && id === 'teleport' ?
			['native/test_pokemon.c#test_declarative_move_try_rejection']
		: (kind === 'move' && id === 'naturepower') ||
			(kind === 'event_hook' && id === 'move.naturepower.onHit') ?
			['native/test_pokemon.c#test_generated_fixed_move_delegation']
		: (kind === 'move' && ['mimic', 'sketch'].includes(id)) ||
			(kind === 'event_hook' && /^move\.(mimic|sketch)\.onHit$/.test(id)) ?
			['native/test_pokemon.c#test_generated_move_slot_copy_family']
		: (kind === 'move' && id === 'sleeptalk') ||
			(kind === 'event_hook' && id.startsWith('move.sleeptalk.')) ?
			['native/test_pokemon.c#test_generated_current_slot_move_delegation']
		: (kind === 'ability' && id === 'flashfire') ||
			(kind === 'condition' && id === 'volatiles.flashfire') ||
			(kind === 'event_hook' && id.startsWith('ability.flashfire.')) ?
			['native/test_pokemon.c#test_flash_fire_generated_lifecycle']
		: (kind === 'move' && id === 'leechseed') ||
			(kind === 'ability' && id === 'liquidooze') ||
			(kind === 'condition' && id === 'volatiles.leechseed') ||
			(kind === 'event_hook' && (id.startsWith('move.leechseed.') ||
				id === 'ability.liquidooze.onSourceTryHeal' ||
				id === 'move.rapidspin.onAfterHit' ||
				id === 'move.rapidspin.onAfterSubDamage')) ?
			['native/test_pokemon.c#test_source_linked_residual_transfer_family']
		: (kind === 'move' && id === 'pursuit') ||
			(kind === 'condition' && id === 'volatiles.pursuit') ||
			(kind === 'event_hook' && id.startsWith('move.pursuit.')) ?
			['native/test_pokemon.c#test_generic_queued_move_interception']
		: (kind === 'move' && id === 'struggle') ||
			(kind === 'event_hook' && id === 'move.struggle.onModifyMove') ?
			['native/test_pokemon.c#test_empty_pp_projects_and_executes_struggle']
		: (kind === 'move' && id === 'charge') ||
			(kind === 'condition' && id === 'volatiles.charge') ||
			(kind === 'event_hook' && id.startsWith('move.charge.condition.')) ?
			['native/test_pokemon.c#test_generic_charge_lifecycle']
		: (kind === 'move' && ['destinybond', 'grudge'].includes(id)) ||
			(kind === 'condition' && ['volatiles.destinybond',
				'volatiles.grudge'].includes(id)) ||
			(kind === 'event_hook' && /^move\.(destinybond|grudge)\./.test(id)) ?
			['native/test_pokemon.c#test_faint_response_condition_family']
		: (kind === 'move' && id === 'uproar') ||
			(kind === 'condition' && id === 'volatiles.uproar') ||
			(kind === 'event_hook' && id.startsWith('move.uproar.')) ?
			['native/test_pokemon.c#test_uproar_global_status_and_lock_lifecycle']
		: (kind === 'move' && id === 'imprison') ||
			(kind === 'condition' && id === 'volatiles.imprison') ||
			(kind === 'event_hook' && id.startsWith('move.imprison.')) ?
			['native/test_pokemon.c#test_imprison_foe_scoped_choice_lifecycle']
		: (kind === 'move' && ['triplekick', 'twineedle'].includes(id)) ?
			['native/test_pokemon.c#test_specialized_per_hit_composition']
		: (kind === 'move' && ['roar', 'whirlwind'].includes(id)) ?
			['native/test_pokemon.c#test_generic_forced_drag_transaction']
		: (kind === 'move' && id === 'ingrain') ||
			(kind === 'ability' && id === 'suctioncups') ||
			(kind === 'condition' && id === 'volatiles.ingrain') ||
			(kind === 'event_hook' && (/^move\.ingrain\.condition\./.test(id) ||
				id === 'ability.suctioncups.onDragOut')) ?
			['native/test_pokemon.c#test_generated_drag_blockers']
		: (kind === 'move' && ['futuresight', 'doomdesire', 'wish'].includes(id)) ||
			(kind === 'condition' && ['slot_conditions.futuremove',
				'slot_conditions.wish'].includes(id)) ||
			(kind === 'event_hook' && /^(condition\.futuremove\.|move\.(futuresight|doomdesire)\.onTry$|move\.wish\.condition\.onEnd$)/.test(id)) ?
			['native/test_pokemon.c#test_delayed_slot_condition_family']
		: (kind === 'move' && id === 'snatch') ||
			(kind === 'condition' && id === 'volatiles.snatch') ||
			(kind === 'event_hook' && id.startsWith('move.snatch.condition.')) ?
			['native/test_pokemon.c#test_snatch_reenters_active_move_as_handler_owner']
		: (kind === 'move' && ['counter', 'mirrorcoat'].includes(id)) ||
			(kind === 'condition' && ['volatiles.counter',
				'volatiles.mirrorcoat'].includes(id)) ||
			(kind === 'event_hook' && /^move\.(counter|mirrorcoat)\./.test(id)) ||
			(kind === 'target_mode' && id === 'scripted') ?
			['native/test_pokemon.c#test_prepared_retaliation_damage_provenance']
		: (kind === 'item' && id === 'focusband') ||
			(kind === 'event_hook' && id === 'item.focusband.onDamage') ?
			['native/test_pokemon.c#test_focus_band_generated_damage_gate']
		: (kind === 'item' && id === 'leppaberry') ||
			(kind === 'event_hook' && id.startsWith('item.leppaberry.')) ?
			['native/test_pokemon.c#test_leppa_berry_pp_transaction']
		: (kind === 'item' && id === 'kingsrock') ||
			(kind === 'event_hook' && id === 'item.kingsrock.onModifyMove') ?
			['native/test_pokemon.c#test_kings_rock_appended_secondary_pipeline']
		: kind === 'event_hook' && /^condition\.(brn|psn|tox)\.(onStart|onSwitchIn)$/.test(id) ?
			['native/test_pokemon.c#test_primary_major_status_family',
			 'native/test_pokemon.c#test_toxic_lifecycle_and_immunity',
			 'native/test_pokemon.c#test_initial_toxic_stage_payload']
		: (kind === 'ability' && id === 'wonderguard') ||
			(kind === 'event_hook' && id === 'ability.wonderguard.onTryHit') ?
			['native/test_pokemon.c#test_wonder_guard_generic_effectiveness_gate']
		: (kind === 'move' && ['lockon', 'mindreader'].includes(id)) ||
			(kind === 'condition' && id === 'volatiles.lockon') ||
			(kind === 'event_hook' && /^move\.(lockon|mindreader)\./.test(id)) ?
			['native/test_pokemon.c#test_lock_on_source_bound_accuracy_and_invulnerability']
		: (kind === 'move' && ['foresight', 'odorsleuth'].includes(id)) ||
			(kind === 'condition' && id === 'volatiles.foresight') ||
			(kind === 'event_hook' && /^move\.(foresight|odorsleuth)\./.test(id)) ?
			['native/test_pokemon.c#test_foresight_generic_immunity_and_boost_staging']
		: (kind === 'move' && ['detect', 'endure', 'protect'].includes(id)) ||
			(kind === 'condition' && ['volatiles.endure', 'volatiles.protect',
				'volatiles.stall'].includes(id)) ||
			(kind === 'event_hook' && /^(move\.(detect|endure|protect)\.|condition\.stall\.)/.test(id)) ?
			['native/test_pokemon.c#test_generic_stalling_guard_and_endure_damage_relay',
				'native/test_pokemon.c#test_protect_stall_and_expiry']
		: kind === 'move' && id === 'extremespeed' ? ['native/test_pokemon.c#test_priority_immunity_and_prng_staging']
		: kind === 'event_hook' && /^condition\.(hail|raindance|sandstorm|sunnyday)\.(onFieldStart|onFieldResidual|onFieldEnd|onWeather|onImmunity)$/.test(id) ? ['native/test_pokemon.c#test_generic_weather_install_replace_and_expire', 'native/test_pokemon.c#test_sandstorm_damage_and_expiry', 'native/test_pokemon.c#test_weather_status_immunity_is_generated_and_suppressible']
		: (kind === 'move' && id === 'rapidspin') ||
			(kind === 'event_hook' && id === 'move.rapidspin.self.onHit') ? ['native/test_pokemon.c#test_partial_trap_condition_programs']
		: kind === 'condition' && id === 'statuses.psn' ? ['native/test_pokemon.c#test_generated_status_residual_policy_family', 'native/test_pokemon.c#test_primary_major_status_family']
		: kind === 'event_hook' && /^condition\.(brn|psn|tox)\.onResidual$/.test(id) ? ['native/test_pokemon.c#test_generated_status_residual_policy_family']
		: kind === 'event_hook' && id === 'condition.par.onBeforeMove' ? ['native/test_pokemon.c#test_generated_paralysis_action_owner']
		: kind === 'event_hook' && id === 'move.attract.condition.onEnd' ? ['native/test_pokemon.c#test_mental_herb_use_item_transaction']
		: (kind === 'move' && id === 'attract') ||
			(kind === 'ability' && id === 'cutecharm') ||
			(kind === 'condition' && id === 'volatiles.attract') ||
			(kind === 'event_hook' && (id === 'ability.cutecharm.onDamagingHit' ||
				id === 'move.attract.onTryImmunity' ||
				['move.attract.condition.onStart', 'move.attract.condition.onBeforeMove',
					'move.attract.condition.onUpdate'].includes(id))) ? ['native/test_pokemon.c#test_generated_attraction_family']
		: (kind === 'ability' && id === 'oblivious') ||
			(kind === 'event_hook' && id.startsWith('ability.oblivious.')) ? ['native/test_pokemon.c#test_generated_attraction_family']
		: (kind === 'move' && id === 'roleplay') ||
			(kind === 'event_hook' && id.startsWith('move.roleplay.')) ? ['native/test_pokemon.c#test_role_play_generic_ability_transfer']
		: (kind === 'move' && id === 'skillswap') ||
			(kind === 'event_hook' && id === 'move.skillswap.onHit') ? ['native/test_pokemon.c#test_skill_swap_transaction']
		: (kind === 'move' && ['block', 'meanlook', 'spiderweb'].includes(id)) ||
			(kind === 'condition' && ['volatiles.trapped',
				'volatiles.trapper'].includes(id)) ||
			(kind === 'simulator_only_condition' && id === 'trapper') ||
			(kind === 'event_hook' && (id.startsWith('move.block.') ||
				id.startsWith('move.meanlook.') || id.startsWith('move.spiderweb.') ||
				id.startsWith('condition.trapped.'))) ?
			['native/test_pokemon.c#test_source_linked_trap_family']
		: (kind === 'ability' && id === 'colorchange') ||
			(kind === 'event_hook' && id === 'ability.colorchange.onDamagingHit') ? ['native/test_pokemon.c#test_color_change_effective_type_product']
		: (kind === 'ability' && ['arenatrap', 'magnetpull'].includes(id)) ||
			(kind === 'event_hook' && /^ability\.(arenatrap|magnetpull)\./.test(id)) ? ['native/test_pokemon.c#test_hidden_trap_rejection_updates_only_request']
		: ((kind === 'ability' && ['compoundeyes', 'guts', 'hugepower', 'hustle', 'purepower'].includes(id)) ||
			(kind === 'item' && id === 'thickclub') ||
			(kind === 'event_hook' && /^(ability\.(compoundeyes|guts|hugepower|hustle|purepower)|item\.thickclub)\./.test(id))) ? ['native/test_pokemon.c#test_generated_scalar_owner_handlers']
		: kind === 'format_rule' && ['sleepclausemod', 'freezeclausemod'].includes(id) ? ['native/test_pokemon.c#test_status_ability_hooks_and_clauses']
		: kind === 'format_rule' && ['endlessbattleclause', 'standardag', 'standard'].includes(id) ? ['native/test_pokemon.c#test_endless_battle_terminal_policy']
		: kind === 'format_rule' && tagAdmissionRuleCases[id] ? ['native/test_admission.c#test_generated_tag_bans']
		: kind === 'format_rule' && id === 'ohkoclause' ? ['native/test_admission.c#test_generated_ohko_predicate']
		: kind === 'format_rule' && id === 'accuracytrapclause' ? ['native/test_admission.c#test_generated_accuracy_trap_conjunction']
		: kind === 'format_rule' && teamAdmissionRuleCases[id] ? ['native/test_admission.c#test_team_admission']
		: kind === 'format_rule' && statAdmissionRuleCases[id] ? ['native/test_admission.c#test_ev_stat_vector_policy']
		: kind === 'format_rule' && relationAdmissionRuleCases[id] ? ['native/test_admission.c#test_species_ability_relation']
		: kind === 'format_rule' && normalizationAdmissionRuleCases[id] ? ['native/test_admission.c#test_species_rewrite_normalization']
		: kind === 'format_rule' && nicknameAdmissionRuleCases[id] ? ['native/test_admission.c#test_nickname_clause_transaction']
		: kind === 'format_rule' && obtainabilityAdmissionRuleCases[id] ? ['native/test_admission.c#test_acquisition_boundary']
		: kind === 'format_rule' && aggregateAdmissionRuleCases[id] ? ['native/test_admission.c#test_rule_source_provenance']
		: kind === 'format_rule' && atomicAdmissionRuleCases[id] ? ['native/test_admission.c#test_atomic_bans']
		: kind === 'format_rule' && implementedFormatRules.has(id) ? ['native/test_pokemon.c#test_gen3_ou_format_manifest_and_bounded_legality']
		: kind === 'target_mode' && implementedTargets.has(id) ? ['native/test_pokemon.c#test_singles_target_algebra']
		: (kind === 'move' && ['reflect', 'lightscreen'].includes(id)) ||
			(kind === 'condition' && ['side_conditions.reflect', 'side_conditions.lightscreen'].includes(id)) ||
			(kind === 'event_hook' && /move\.(reflect|lightscreen)\.condition\./.test(id)) ?
			['native/test_pokemon.c#test_reflect_duration_and_damage_handler',
				'native/test_pokemon.c#test_light_screen_uses_generic_side_condition_lifecycle']
		: (kind === 'move' && id === 'mist') ||
			(kind === 'condition' && id === 'side_conditions.mist') ||
			(kind === 'event_hook' && id.includes('mist')) ? ['native/test_pokemon.c#test_negative_boost_filter_programs']
		: (kind === 'move' && id === 'substitute') || (kind === 'condition' && ['volatiles.substitute', 'volatiles.substitutebroken'].includes(id)) || (kind === 'event_hook' && id.includes('substitute')) ? ['native/test_pokemon.c#test_substitute_family']
		: (kind === 'move' && id === 'falseswipe') || (kind === 'event_hook' && id === 'move.falseswipe.onDamage') ? ['native/test_pokemon.c#test_false_swipe_generic_damage_relay']
		: (kind === 'move' && ['aromatherapy', 'healbell'].includes(id)) ||
			(kind === 'event_hook' && /^move\.(aromatherapy|healbell)\.onHit$/.test(id)) ||
			(kind === 'target_mode' && id === 'allyTeam') ? ['native/test_pokemon.c#test_team_major_status_cure_handlers']
		: kind === 'move' && ['helpinghand', 'wingattack'].includes(id) ? ['native/test_pokemon.c#test_singles_target_algebra']
		: (kind === 'move' && id === 'magiccoat') || (kind === 'condition' && id === 'volatiles.magiccoat') || (kind === 'event_hook' && id.includes('magiccoat')) ? ['native/test_pokemon.c#test_magic_coat_reflects_through_called_move_entry']
		: kind === 'move' && id === 'teeterdance' ? ['native/test_pokemon.c#test_teeter_dance_target_iteration']
		: kind === 'move' && ['flatter', 'swagger'].includes(id) ? ['native/test_pokemon.c#test_flatter_ordered_primary_effects']
		: (kind === 'move' && ['moonlight', 'morningsun', 'synthesis'].includes(id)) ||
			(kind === 'event_hook' && /^move\.(moonlight|morningsun|synthesis)\.onHit$/.test(id)) ? ['native/test_pokemon.c#test_generated_weather_recovery_family']
		: (kind === 'move' && id === 'weatherball') ||
			(kind === 'event_hook' && id.startsWith('move.weatherball.')) ? ['native/test_pokemon.c#test_weather_ball_active_frame_mutation']
		: (kind === 'move' && id === 'thunder') ||
			(kind === 'event_hook' && id === 'move.thunder.onModifyMove') ? ['native/test_pokemon.c#test_thunder_weather_accuracy_pipeline']
		: (kind === 'move' && id === 'magnitude') ||
			(kind === 'event_hook' && id.startsWith('move.magnitude.')) ? ['native/test_pokemon.c#test_weighted_active_move_power_distribution']
		: (kind === 'move' && id === 'present') ||
			(kind === 'event_hook' && id === 'move.present.onModifyMove') ? ['native/test_pokemon.c#test_weighted_move_resolution_outcomes']
		: (kind === 'move' && id === 'hiddenpower') ||
			(kind === 'event_hook' && id === 'move.hiddenpower.onModifyMove') ? ['native/test_pokemon.c#test_personal_move_profile_hidden_power']
		: (kind === 'move' && ['mudsport', 'watersport'].includes(id)) ||
			(kind === 'condition' && ['volatiles.mudsport', 'volatiles.watersport'].includes(id)) ||
			(kind === 'event_hook' && /^move\.(mudsport|watersport)\.condition\./.test(id)) ? ['native/test_pokemon.c#test_sport_ambient_base_power_family']
		: (kind === 'move' && ['bounce', 'dig', 'dive', 'fly', 'gust', 'razorwind',
			'skullbash', 'skyattack', 'skyuppercut'].includes(id)) ||
			(kind === 'condition' && /^volatiles\.(bounce|dive|fly|razorwind|skullbash|skyattack|solarbeam)$/.test(id)) ||
			(kind === 'event_hook' && /^move\.(bounce|dig|dive|fly|razorwind|skullbash|skyattack)\./.test(id)) ? [
			'native/test_pokemon.c#test_generated_two_turn_descriptor_rotation',
			'native/test_pokemon.c#test_fly_two_turn_invulnerability_family',
			'native/test_pokemon.c#test_semi_invulnerable_descriptor_masks_and_validation',
		]
		: (kind === 'move' && id === 'solarbeam') ||
			(kind === 'condition' && id === 'volatiles.twoturnmove') ||
			(kind === 'event_hook' && (id.includes('solarbeam') || id.includes('twoturnmove'))) ? ['native/test_pokemon.c#test_solar_beam_two_turn_lifecycle']
		: (kind === 'move' && id === 'taunt') ||
			(kind === 'condition' && id === 'volatiles.taunt') ||
			(kind === 'event_hook' && id.includes('taunt')) ? ['native/test_pokemon.c#test_taunt_choice_control_lifecycle']
		: (kind === 'move' && ['disable', 'encore', 'torment'].includes(id)) ||
			(kind === 'condition' && ['volatiles.disable', 'volatiles.encore', 'volatiles.torment'].includes(id)) ||
			(kind === 'event_hook' && /^move\.(disable|encore|torment)\./.test(id)) ? ['native/test_pokemon.c#choice-control-family-tests']
		: (kind === 'move' && ['outrage', 'petaldance', 'thrash'].includes(id)) ||
			(kind === 'condition' && id === 'volatiles.lockedmove') ||
			(kind === 'event_hook' && id.startsWith('condition.lockedmove.')) ? ['native/test_pokemon.c#test_locked_move_action_lock_and_fatigue']
		: (kind === 'move' && ['confuseray', 'supersonic', 'sweetkiss'].includes(id)) || (kind === 'ability' && id === 'owntempo') || (kind === 'condition' && id === 'volatiles.confusion') || (kind === 'event_hook' && (id.includes('confusion') || id.includes('owntempo'))) ? ['native/test_pokemon.c#test_confusion_primary_lifecycle_and_own_tempo']
		: (kind === 'move' && ['confusion', 'psybeam', 'signalbeam', 'dizzypunch', 'waterpulse', 'dynamicpunch'].includes(id)) || (kind === 'ability' && id === 'shielddust') || (kind === 'event_hook' && id === 'ability.shielddust.onModifySecondaries') ? ['native/test_pokemon.c#test_confusion_damaging_secondaries_and_shield_dust']
		: (kind === 'move' && ['astonish', 'extrasensory', 'needlearm', 'boneclub', 'hyperfang', 'rollingkick', 'bite', 'headbutt', 'rockslide', 'stomp', 'twister'].includes(id)) ||
			(kind === 'ability' && id === 'innerfocus') ||
			(kind === 'condition' && id === 'volatiles.flinch') ||
			(kind === 'event_hook' && (id === 'condition.flinch.onBeforeMove' || id === 'ability.innerfocus.onTryAddVolatile')) ? ['native/test_pokemon.c#test_flinch_secondary_family_and_inner_focus']
		: (kind === 'move' && ['thief', 'covet', 'knockoff', 'recycle'].includes(id)) ||
			(kind === 'ability' && id === 'stickyhold') || (kind === 'item' && id === 'mail') ||
			(kind === 'event_hook' && /^(move\.(thief|covet|knockoff|recycle)|ability\.stickyhold|item\.mail)\./.test(id)) ? ['native/test_pokemon.c#test_generic_item_mutation_family']
		: (kind === 'move' && id === 'trick') ||
			(kind === 'event_hook' && /^move\.trick\./.test(id)) ? ['native/test_pokemon.c#test_trick_item_swap_family']
		: (kind === 'move' && id === 'mirrormove') || (kind === 'event_hook' && id.includes('mirrormove')) ? ['native/test_pokemon.c#test_mirror_move_provenance_and_called_move_entry']
		: (kind === 'ability' && id === 'waterabsorb') ||
			(kind === 'event_hook' && id === 'ability.waterabsorb.onTryHit') ? ['native/test_pokemon.c#test_event_interpreter_contract_and_water_absorb_heal']
		: (kind === 'ability' && id === 'voltabsorb') ||
			(kind === 'event_hook' && id === 'ability.voltabsorb.onTryHit') ? ['native/test_pokemon.c#test_volt_absorb_generated_interception']
		: (kind === 'ability' && id === 'thickfat') ||
			(kind === 'event_hook' && id === 'ability.thickfat.onSourceBasePower') ? ['native/test_pokemon.c#test_thick_fat_source_base_power']
		: (kind === 'ability' && id === 'marvelscale') ||
			(kind === 'event_hook' && id === 'ability.marvelscale.onModifyDef') ? ['native/test_pokemon.c#test_marvel_scale_modify_defense_staging']
		: (kind === 'item' && ['deepseascale', 'deepseatooth', 'lightball', 'machobrace', 'metalpowder', 'souldew'].includes(id)) ||
			(kind === 'event_hook' && /^item\.(deepseascale|deepseatooth|lightball|machobrace|metalpowder|souldew)\./.test(id)) ? ['native/test_pokemon.c#test_generated_species_stat_item_handlers']
		: (kind === 'move' && id === 'facade') ||
			(kind === 'event_hook' && id === 'move.facade.onBasePower') ? ['native/test_pokemon.c#test_holder_status_mask_base_power_predicate']
		: (kind === 'move' && id === 'refresh') ||
			(kind === 'event_hook' && id === 'move.refresh.onHit') ? ['native/test_pokemon.c#test_refresh_move_hit_callback_boundary']
		: (kind === 'move' && id === 'psychup') ||
			(kind === 'event_hook' && id === 'move.psychup.onHit') ? ['native/test_pokemon.c#test_atomic_copy_boost_stage_product']
		: (kind === 'move' && id === 'haze') ||
			(kind === 'event_hook' && id === 'move.haze.onHitField') ? ['native/test_pokemon.c#test_haze_field_hit_and_pressure_targeting']
		: (kind === 'move' && id === 'rest') ||
			(kind === 'event_hook' && /^move\.rest\./.test(id)) ? ['native/test_pokemon.c#test_generated_rest_programs']
		: (kind === 'ability' && id === 'synchronize') ||
			(kind === 'event_hook' && id === 'ability.synchronize.onAfterSetStatus') ? ['native/test_pokemon.c#test_generated_synchronize_after_set_status']
		: (kind === 'move' && id === 'snore') ||
			(kind === 'ability' && id === 'earlybird') ||
			(kind === 'condition' && id === 'statuses.slp') ||
			(kind === 'event_hook' && (id.startsWith('condition.slp.') || id === 'move.snore.onTry')) ? ['native/test_pokemon.c#test_generated_sleep_lifecycle_programs']
		: (kind === 'condition' && id === 'statuses.frz') ||
			(kind === 'event_hook' && id.startsWith('condition.frz.')) ? ['native/test_pokemon.c#test_freeze_thaw_boundaries', 'native/test_pokemon.c#test_weather_ball_active_frame_mutation']
		: (kind === 'move' && ['ancientpower', 'silverwind'].includes(id)) ||
			(kind === 'ability' && id === 'serenegrace') ||
			(kind === 'event_hook' && id === 'ability.serenegrace.onModifyMove') ? ['native/test_pokemon.c#test_generated_grouped_secondary_products']
		: kind === 'event_hook' &&
			['ability.insomnia.onTryAddVolatile',
			 'ability.vitalspirit.onTryAddVolatile'].includes(id) ?
			['native/test_pokemon.c#test_yawn_delayed_status_lifecycle']
		: (kind === 'ability' && abilityCases[id]?.includes('status-ability-rotation')) ||
			(kind === 'event_hook' && id.startsWith('ability.') && eventHookCases[id]?.includes('status-ability-rotation')) ? ['native/test_pokemon.c#test_status_ability_hooks_and_clauses']
		: (kind === 'move' && ['superfang', 'endeavor'].includes(id)) ||
			(kind === 'event_hook' && /^move\.endeavor\.onTry/.test(id)) ? ['native/test_pokemon.c#test_target_relative_damage_and_early_predicate']
		: kind === 'move' && id === 'psywave' ? ['native/test_pokemon.c#test_random_level_percent_damage_and_owned_prng']
		: (kind === 'move' && ['hyperbeam', 'blastburn', 'frenzyplant', 'hydrocannon'].includes(id)) ||
			(kind === 'condition' && id === 'volatiles.mustrecharge') ||
			(kind === 'event_hook' && ['condition.mustrecharge.onStart',
				'condition.mustrecharge.onBeforeMove'].includes(id)) ? ['native/test_pokemon.c#test_recharge_synthetic_hard_lock_lifecycle']
		: (kind === 'move' && id === 'brickbreak') ||
			(kind === 'event_hook' && id === 'move.brickbreak.onTryHit') ? ['native/test_pokemon.c#test_move_owned_try_hit_removes_selected_side_conditions']
		: (kind === 'item' && id === 'leftovers') ||
			(kind === 'event_hook' && id === 'item.leftovers.onResidual') ? ['native/test_pokemon.c#test_leftovers_residual_healing']
		: (kind === 'ability' && id === 'naturalcure') ||
			(kind === 'event_hook' && id === 'ability.naturalcure.onSwitchOut') ? ['native/test_pokemon.c#test_natural_cure_switch_out']
		: (kind === 'ability' && id === 'pressure') ||
			(kind === 'event_hook' && id.startsWith('ability.pressure.')) ? ['native/test_pokemon.c#test_pressure_generic_pp_deduction_stage', 'native/test_pokemon.c#test_snatch_reenters_active_move_as_handler_owner']
		: (kind === 'ability' && id === 'damp') ||
			(kind === 'event_hook' && id === 'ability.damp.onAnyTryMove') ? ['native/test_pokemon.c#test_global_try_move_handler_blocks_self_faint_family']
		: (kind === 'ability' && id === 'flamebody') ||
			(kind === 'event_hook' && id === 'ability.flamebody.onDamagingHit') ? ['native/test_pokemon.c#test_damaging_hit_contact_response_boundary']
		: (kind === 'ability' && ['static', 'poisonpoint'].includes(id)) ||
			(kind === 'event_hook' && /^ability\.(static|poisonpoint)\.onDamagingHit$/.test(id)) ? ['native/test_pokemon.c#test_damaging_hit_contact_response_boundary']
		: (kind === 'ability' && id === 'effectspore') ||
			(kind === 'event_hook' && id === 'ability.effectspore.onDamagingHit') ? ['native/test_pokemon.c#test_effect_spore_uniform_status_selection']
		: (kind === 'ability' && id === 'roughskin') ||
			(kind === 'event_hook' && id === 'ability.roughskin.onDamagingHit') ? ['native/test_pokemon.c#test_source_base_max_hp_fraction_contact_damage']
		: (kind === 'ability' && id === 'rockhead') ||
			(kind === 'event_hook' && id === 'ability.rockhead.onDamage') ? ['native/test_pokemon.c#test_damage_relative_recoil_and_rock_head', 'native/test_pokemon.c#test_empty_pp_projects_and_executes_struggle']
		: (kind === 'ability' && id === 'shedskin') ||
			(kind === 'event_hook' && id === 'ability.shedskin.onResidual') ? ['native/test_pokemon.c#test_residual_status_cure_family']
		: (kind === 'ability' && id === 'speedboost') ||
			(kind === 'event_hook' && id === 'ability.speedboost.onResidual') ? ['native/test_pokemon.c#test_residual_active_turn_boost_family']
		: (kind === 'ability' && id === 'intimidate') ||
			(kind === 'event_hook' && id === 'ability.intimidate.onStart') ? ['native/test_pokemon.c#test_generated_intimidate_start_family']
		: (kind === 'ability' && id === 'trace') ||
			(kind === 'event_hook' && id === 'ability.trace.onStart') ? ['native/test_pokemon.c#test_trace_replaces_ability_without_starting_copy']
		: kind === 'item' && inertItems.has(id) ? ['native/test_pokemon.c#test_trick_item_swap_family']
		: kind === 'item' && id === 'quickclaw' ? ['native/test_pokemon.c#test_shared_turn_speed_item_policy']
		: kind === 'move' && ['sonicboom', 'dragonrage'].includes(id) ? ['native/test_pokemon.c#test_fixed_literal_damage_and_type_boundary']
		: (kind === 'move' && id === 'payday') ||
			(kind === 'event_hook' && id === 'move.payday.onHit') ? ['native/test_pokemon.c#test_generated_ordinary_attack_family']
		: (kind === 'move' && id === 'followme') ||
			(kind === 'event_hook' && id === 'move.followme.onTry') ? ['native/test_pokemon.c#test_follow_me_singles_try_rejection']
		: kind === 'move' && ['eruption', 'waterspout'].includes(id) ? ['native/test_pokemon.c#test_live_hp_scaled_base_power_family']
		: (kind === 'move' && id === 'secretpower') ||
			(kind === 'event_hook' && id === 'move.secretpower.onModifyMove') ? ['native/test_pokemon.c#test_secret_power_resolved_terrain_free_descriptor']
		: (kind === 'move' && id === 'painsplit') ||
			(kind === 'event_hook' && id === 'move.painsplit.onHit') ? ['native/test_pokemon.c#test_pain_split_atomic_bilateral_hp_assignment']
		: kind === 'move' && id === 'doubleteam' ? ['native/test_pokemon.c#test_generated_effect_program_boosts_and_reset']
		: kind === 'move' && id === 'memento' ? ['native/test_pokemon.c#test_if_hit_self_faint_family']
		: (kind === 'move' && (id === 'jumpkick' || id === 'highjumpkick')) ||
			(kind === 'event_hook' &&
				(id === 'move.jumpkick.onMoveFail' || id === 'move.highjumpkick.onMoveFail')) ?
			['native/test_pokemon.c#test_move_fail_hypothetical_damage_family']
		: kind === 'move' && id === 'revenge' ?
			['native/test_pokemon.c#test_recent_damage_from_resolved_target_base_power_guard']
		: kind === 'move' && id === 'lowkick' ?
			['native/test_pokemon.c#test_target_weight_base_power_policy']
		: (kind === 'move' && id === 'transform') ||
			(kind === 'event_hook' && id === 'move.transform.onHit') ?
			['native/test_pokemon.c#test_transform_generic_profile_copy_policy']
		: (kind === 'move' && ['smellingsalts', 'bellydrum'].includes(id)) ||
			(kind === 'event_hook' && ['move.smellingsalts.onHit',
				'move.bellydrum.onHit'].includes(id)) ?
			['native/test_pokemon.c#test_generated_atomic_formula_moves']
		: (kind === 'move' && id === 'dreameater') ||
			(kind === 'event_hook' && id === 'move.dreameater.onTryImmunity') ?
			['native/test_pokemon.c#test_dream_eater_move_immunity_is_deferred_after_accuracy']
		: (kind === 'move' && id === 'triattack') ||
			(kind === 'event_hook' && id === 'move.triattack.secondary.onHit') ?
			['native/test_pokemon.c#test_sampled_status_secondary_distribution']
		: (kind === 'move' && id === 'nightmare') ||
			(kind === 'condition' && id === 'volatiles.nightmare') ||
			(kind === 'event_hook' && id.startsWith('move.nightmare.condition.')) ? ['native/test_pokemon.c#test_nightmare_generated_lifecycle']
		: kind === 'move' && ['absorb', 'megadrain', 'gigadrain', 'leechlife'].includes(id) ? ['native/test_pokemon.c#test_damage_relative_drain_and_nonhit_gates']
		: kind === 'move' && moveCases[id]?.some(caseID => caseID.startsWith('status-primary-rotation')) ? ['native/test_pokemon.c#test_primary_major_status_family']
		: kind === 'move' && moveCases[id]?.includes(`secondary-${id}`) ? ['native/test_pokemon.c#test_damage_secondaries_and_owned_prng']
		: kind === 'item' && ['oranberry', 'sitrusberry'].includes(id) ? ['native/test_pokemon.c#test_fixed_heal_berry_transaction']
		: kind === 'item' && ['liechiberry', 'ganlonberry', 'salacberry', 'petayaberry', 'apicotberry'].includes(id) ? ['native/test_pokemon.c#test_pinch_boost_berry_transaction']
		: (kind === 'item' && id === 'lansatberry') || (kind === 'event_hook' && id.startsWith('item.lansatberry.')) ? ['native/test_pokemon.c#test_lansat_berry_volatile_transaction']
		: (kind === 'item' && id === 'starfberry') || (kind === 'event_hook' && id.startsWith('item.starfberry.')) ? ['native/test_pokemon.c#test_starf_berry_random_eligible_boost_transaction']
		: (kind === 'item' && id === 'mentalherb') || (kind === 'event_hook' && id === 'item.mentalherb.onUpdate') ? ['native/test_pokemon.c#test_mental_herb_use_item_transaction']
		: (kind === 'item' && id === 'whiteherb') || (kind === 'event_hook' && id.startsWith('item.whiteherb.')) ? ['native/test_pokemon.c#test_white_herb_after_move_transaction']
		: (kind === 'item' && id === 'choiceband') ||
			(kind === 'condition' && id === 'volatiles.choicelock') ||
			(kind === 'event_hook' && (id.startsWith('item.choiceband.') ||
				id.startsWith('condition.choicelock.'))) ? ['native/test_pokemon.c#test_choice_band_choice_lock_lifecycle']
		: (kind === 'item' && ['aguavberry', 'figyberry', 'iapapaberry', 'magoberry', 'wikiberry'].includes(id)) ||
			(kind === 'event_hook' && /^item\.(aguavberry|figyberry|iapapaberry|magoberry|wikiberry)\./.test(id)) ? ['native/test_pokemon.c#test_flavor_berry_nature_transaction']
		: (kind === 'item' && id === 'lumberry') || (kind === 'event_hook' && id.startsWith('item.lumberry.')) ? ['native/test_pokemon.c#test_combined_cure_berry_transaction']
		: (kind === 'item' && id === 'persimberry') || (kind === 'event_hook' && id.startsWith('item.persimberry.')) ? ['native/test_pokemon.c#test_volatile_cure_berry_transaction']
		: kind === 'event_hook' && id.startsWith('item.') && eventHookCases[id]?.some(caseID => caseID.includes('pinch') || /berry-(liechi|ganlon|salac|petaya|apicot)-/.test(caseID)) ? ['native/test_pokemon.c#test_pinch_boost_berry_transaction']
		: kind === 'event_hook' && id.startsWith('item.') ? ['native/test_pokemon.c#test_fixed_heal_berry_transaction']
		: (kind === 'event_hook' && id.includes('WeatherModifyDamage')) ? ['native/test_pokemon.c#test_weather_modify_damage_event_and_gen3_stage']
		: classification === 'implemented' || classification === 'inert' ? ['native/test_pokemon.c#generated-descriptor-evidence'] : [];
	const isBideFamily = (kind === 'move' && id === 'bide') ||
		(kind === 'condition' && id === 'volatiles.bide') ||
		(kind === 'event_hook' && id.startsWith('move.bide.condition.'));
	const isFuryCutterFamily = (kind === 'move' && id === 'furycutter') ||
		(kind === 'condition' && id === 'volatiles.furycutter') ||
		(kind === 'event_hook' && id.startsWith('move.furycutter.'));
	const isStockpileFamily =
		(kind === 'move' && ['stockpile', 'spitup', 'swallow'].includes(id)) ||
		(kind === 'condition' && id === 'volatiles.stockpile') ||
		(kind === 'event_hook' && /^move\.(stockpile|spitup|swallow)\./.test(id));
	const isConversion2Family = (kind === 'move' && id === 'conversion2') ||
		(kind === 'event_hook' && id === 'move.conversion2.onHit');
	const isRageFamily = (kind === 'move' && id === 'rage') ||
		(kind === 'condition' && id === 'volatiles.rage') ||
		(kind === 'event_hook' && id.startsWith('move.rage.condition.'));
	const isFocusPunchFamily = (kind === 'move' && id === 'focuspunch') ||
		(kind === 'condition' && id === 'volatiles.focuspunch') ||
		(kind === 'event_hook' && id.startsWith('move.focuspunch.'));
	const isMinimizeFamily = (kind === 'move' && id === 'minimize') ||
		(kind === 'condition' && id === 'volatiles.minimize') ||
		(kind === 'event_hook' && id.startsWith('move.minimize.condition.'));
	const isSpiteFamily = (kind === 'move' && id === 'spite') ||
		(kind === 'event_hook' && id === 'move.spite.onHit');
	const isCurrentSlotTypeOverlayFamily =
		(kind === 'move' && ['camouflage', 'conversion'].includes(id)) ||
		(kind === 'event_hook' &&
		 ['move.camouflage.onHit', 'move.conversion.onHit'].includes(id));
	const isLockedRampFamily =
		(kind === 'move' && ['rollout', 'iceball', 'defensecurl'].includes(id)) ||
		(kind === 'condition' && ['volatiles.rollout', 'volatiles.iceball',
			'volatiles.defensecurl', 'volatiles.rolloutstorage'].includes(id)) ||
		(kind === 'event_hook' && (/^move\.(rollout|iceball|defensecurl)\./.test(id) ||
			id === 'condition.rolloutstorage.onBasePower'));
	const isStatusClauseFamily = (kind === 'format_rule' && ['sleepclausemod', 'freezeclausemod'].includes(id)) ||
		(kind === 'condition' && ['pseudo_weather.sleepclausemod', 'pseudo_weather.freezeclausemod'].includes(id)) ||
		(kind === 'event_hook' && ['format.sleepclausemod.onSetStatus', 'format.freezeclausemod.onSetStatus'].includes(id));
	return {
		id, numeric_id: numericID, classification, oracle_revision: revision,
		showdown_sources: withDefiningHookSource(kind, id, isCurrentSlotTypeOverlayFamily ? refs([
			'data/mods/gen3/moves.ts', 'data/mods/gen4/moves.ts',
			'sim/pokemon.ts', 'test/sim/moves/camouflage.js',
		], id.includes('camouflage') ? 'camouflage' : 'conversion') : isSpiteFamily ? refs([
			'data/mods/gen3/moves.ts', 'sim/pokemon.ts', 'sim/battle-actions.ts',
		], 'spite') : isMinimizeFamily ? refs([
			'data/moves.ts', 'data/mods/gen4/moves.ts', 'data/mods/gen5/moves.ts',
			'sim/battle.ts', 'sim/pokemon.ts',
		], 'minimize') : isFocusPunchFamily ? refs([
			'data/moves.ts', 'data/mods/gen4/moves.ts',
			'sim/battle.ts', 'sim/battle-actions.ts',
			'test/sim/moves/focuspunch.js',
		], 'focuspunch') : isRageFamily ? refs([
			'data/moves.ts', 'sim/battle.ts', 'sim/battle-actions.ts', 'sim/pokemon.ts',
		], 'rage') : isConversion2Family ? refs([
			'data/mods/gen3/moves.ts', 'data/mods/gen3/scripts.ts',
			'sim/battle-actions.ts', 'sim/pokemon.ts',
			'test/sim/moves/conversion2.js',
		], 'conversion2') : isStatusClauseFamily ? refs([
			'data/rulesets.ts', 'sim/battle.ts', 'sim/pokemon.ts',
			...(id.includes('sleepclause') ? ['test/sim/rulesets/sleepclausemod.js'] : []),
		], id.includes('freezeclause') ? 'freezeclausemod' : 'sleepclausemod') : isStockpileFamily ? refs([
			'data/moves.ts', 'data/mods/gen4/moves.ts',
			'data/mods/gen3/moves.ts', 'test/sim/moves/stockpile.js',
			'test/sim/moves/snatch.js',
		], /spitup/.test(id) ? 'spitup' : /swallow/.test(id) ? 'swallow' : 'stockpile') : isLockedRampFamily ? refs([
			'data/moves.ts', 'test/sim/moves/rollout.js',
		], /iceball/.test(id) ? 'iceball' : /defensecurl/.test(id) ? 'defensecurl' :
			/rolloutstorage/.test(id) ? 'rolloutstorage' : 'rollout') : isFuryCutterFamily ? refs([
			'data/moves.ts', 'data/mods/gen4/moves.ts',
			'data/mods/gen3/moves.ts', 'test/sim/moves/furycutter.js',
		], 'furycutter') : isBideFamily ? refs([
			'data/moves.ts', 'data/mods/gen4/moves.ts',
			'data/mods/gen3/moves.ts',
		], 'bide') : refs(sourcePaths(kind), id)),
		generation_boundaries: [{path: sourcePath, symbol: id}, {path: 'verify/inventory/generate.js', symbol: 'authoritative extraction'}],
		native_boundaries: native,
		semantic_features: classification === 'implemented' || classification === 'inert' ? semanticFeatures : [],
		focused_tests: focusedTests,
		differential_cases: classification === 'implemented' || classification === 'inert' || (kind === 'move' && partialMoveEvidence.has(id)) ? proof.cases : [],
		verification_artifacts: verification,
		reachability_evidence: reachable, gap_witnesses: gap,
		rationale: classification === 'unreachable' && kind === 'format_rule' ? 'The pinned resolved RuleTable retains this rule, but generated admission-universe invariants prove no normalized Gen 3 submitted set can match it.'
			: classification === 'unreachable' && id === 'item.whiteherb.onAnyAfterMega' ? 'The flattened item retains a later-generation callback, but Gen 3 has no Mega Evolution phase that can dispatch it.'
			: classification === 'implemented' && kind === 'simulator_only_condition' && id === 'trapper' ? 'Showdown materializes this reachable linkedStatus helper. Native preserves its admission, effect ordering, provenance, and teardown in a normalized source-linked relation without exposing duplicate canonical volatile state.'
			: classification === 'implemented' && (id === 'souldew' || id.startsWith('item.souldew.')) ? 'The resolved Gen 3 OU bundle preserves both observable Soul Dew callbacks and specializes their positive Lati-only branches to undefined because Latias and Latios are format-banned.'
			: classification === 'unsupported' && kind === 'move' && id === 'tickle' ? 'The differential case proves Tickle bypasses Substitute, but does not prove the complete move descriptor; Tickle remains unsupported.'
			: classification === 'unsupported' && kind === 'ability' && id === 'guts' ? 'Guts lacks recombination evidence for reachable poison, sleep, and freeze status interactions.'
			: classification === 'unsupported' && kind === 'ability' && id === 'rockhead' ? 'Rock Head lacks the reachable Struggle-recoil exception and its evidence.'
			: classification === 'implemented' && kind === 'format_rule' && tagAdmissionRuleCases[id] ? 'The immutable admission universe carries the effective resolved descriptor tag and the generic tag-ban interpreter rejects every matching identity kind. Nonmatching inputs remain fail-closed as incomplete.'
			: classification === 'implemented' && kind === 'format_rule' && id === 'ohkoclause' ? 'The generated move descriptors carry the resolved OHKO predicate and the generic all-of interpreter rejects exactly the four literal submitted OHKO moves. Delegating moves such as Metronome remain unflagged, and nonmatching inputs remain fail-closed as incomplete.'
			: classification === 'implemented' && kind === 'format_rule' && id === 'accuracytrapclause' ? 'The generated identity descriptors carry exact guaranteed-accuracy-drop and trapping predicates. The generic all-of interpreter rejects their same-set conjunction across move and ability owners; probabilistic accuracy drops and partial trapping remain legal controls.'
			: classification === 'implemented' && kind === 'format_rule' && id === 'speedpassclause' ? 'The team admission phase applies a generated all-of rule requiring Baton Pass and a speed-boost source on the same set. Exact move, item, and ability closures and no-anchor controls are proven against TeamValidator.'
			: classification === 'implemented' && kind === 'format_rule' && id === 'oneboostpasserclause' ? 'The generated anchored-cardinality rule counts boost-source occurrences per Baton Pass set and then qualifying sets across the fixed-capacity team, matching Showdown callback order and limits.'
			: classification === 'implemented' && kind === 'format_rule' && id === 'evlimit' ? 'A generated stat-vector policy is bound to the resolved format manifest and proves the inclusive 510 total-EV cap. The same normalized boundary separately proves omission, zero-total, level-one, and 0..255 component behavior without treating those checks as the meaning of EV Limit itself.'
			: classification === 'implemented' && kind === 'format_rule' && id === 'obtainableabilities' ? 'A generated compressed-row relation maps every resolved Gen 3 species identity to its legal ability IDs. The generic allowed-relation interpreter proves primary and secondary slots, rejects known cross-species and modern-slot mismatches, preserves earlier ban ordering, and diagnoses later team members without species-specific control flow.'
			: classification === 'implemented' && kind === 'format_rule' && id === 'obtainableformes' ? 'A generated guarded-rewrite program normalizes the three resolved Gen 3 battle-only Castform formes to base Castform after requiring Forecast. Transactional normalized set/team outputs prove the mutation while remaining unchanged on rejection; selectable Deoxys identities are not rewritten and retain their existing OU ban classification.'
			: classification === 'implemented' && kind === 'format_rule' && id === 'nicknameclause' ? 'Generated species display/base metadata drives bounded UTF-8 nickname normalization, same-family canonicalization, cross-species impersonation rejection, and exact case-sensitive team uniqueness. Focused transactional tests and pinned TeamValidator differential cases cover ASCII, Unicode UTF-16 length, sanitation, forms, defaults, and duplicate ordering.'
			: classification === 'implemented' && kind === 'format_rule' && obtainabilityAdmissionRuleCases[id] ? 'A fingerprinted generated Gen 3 source/event bundle drives the fixed-capacity acquisition interpreter. Focused malformed-bundle and transaction tests, 136 pinned TeamValidator fixtures, 1,925 exhaustive legal single-egg pairs, and 1,250 seeded recombinations prove source intersection, breeding, events, evolution levels, set fields, and Hidden Power without identity-specific runtime branches.'
			: classification === 'implemented' && kind === 'format_rule' && aggregateAdmissionRuleCases[id] ? 'This RuleTable alias contributes only the generated flattened atomic children named by source_rule_id. Exact child closure, a legal control, and every child rejection are proven without adding an alias-specific runtime branch.'
			: classification === 'implemented' && kind === 'format_rule' && atomicAdmissionRuleCases[id] ? 'The generated admission universe and generic atomic-ban evaluator reject this resolved Gen 3 OU rule; focused native and pinned TeamValidator differential evidence agree, while all other admission checks remain fail-closed as incomplete.'
			: classification === 'implemented' ? 'Native descriptor semantics have focused and differential evidence.'
			: classification === 'inert' && kind === 'item' ? 'Callback-free item identity is generated natively and observed through the generic item transaction.'
			: classification === 'inert' && kind === 'ability' ? 'Resolved ability identity has no executable callbacks and is observed without handlers or PRNG.'
			: classification === 'inert' ? 'Immutable species data are constructed natively and observed in differential state.'
			: classification === 'unreachable' ? 'Effective simulator condition is not referenced by any reachable Gen 3 OU descriptor.'
			: 'Reachable descriptor lacks complete native semantic evidence and remains fail-closed.',
	};
}

const bySelector = {
	species: artifact.species.map(value => entry('species_form', value.id, value.num)),
	moves: artifact.moves.map(value => entry('move', value.id)),
	abilities: artifact.abilities.map(value => entry('ability', value.id)),
	items: artifact.items.map(value => entry('item', value.id)),
	'statuses + volatiles + side_conditions + weather + pseudo_weather + slot_conditions':
		['statuses', 'volatiles', 'side_conditions', 'weather', 'pseudo_weather', 'slot_conditions']
			.flatMap(group => artifact[group].map(value => entry('condition', `${group}.${value.id}`))),
	format_rules: artifact.format_rules.map(value => entry('format_rule', value.id)),
	target_modes: artifact.target_modes.map(id => entry('target_mode', id)),
	callback_hooks: artifact.callback_hooks.map(value => entry('event_hook', `${value.owner_kind}.${value.owner_id}.${value.hook}`)),
	simulator_only_conditions: artifact.simulator_only_conditions.map(value => entry('simulator_only_condition', value.id)),
};

template.freeze_status = 'frozen';
for (const inventory of template.inventories) {
	inventory.entries = bySelector[inventory.selector];
	inventory.expected_count = inventory.entries.length;
	inventory.frozen_digest = artifactDigest;
}
const outputPath = path.join(__dirname, 'descriptor-map.json');
const temporaryPath = `${outputPath}.tmp`;
fs.writeFileSync(temporaryPath, `${JSON.stringify(template, null, 2)}\n`);
fs.renameSync(temporaryPath, outputPath);
