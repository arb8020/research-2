'use strict';

const fs = require('fs');
const path = require('path');

const ROOT = __dirname;
const CENSUS_PATH = path.join(ROOT, 'all-test-census.json');
const OUTPUT_PATH = path.join(ROOT, 'gen3ou-item-test-overlay.json');
const PINNED_REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';

const policies = {
  'abilityshield.js': [9, 'Ability Shield', 'data/items.ts:2', 'ability replacement, suppression, bypass, acquisition, and item/ability event ordering'],
  'adrenalineorb.js': [7, 'Adrenaline Orb', 'data/items.ts:111', 'Intimidate-triggered item activation, effective boosts, stat caps, Contrary, Mist, and Substitute'],
  'assaultvest.js': [6, 'Assault Vest', 'data/items.ts:313', 'legal move choice restriction and Klutz item suppression'],
  'boosterenergy.js': [9, 'Booster Energy', 'data/items.ts:622', 'switch-in item activation ordering relative to entry hazards'],
  'drives.js': [5, 'Drives and Genesect', 'data/items.ts:716', 'species-bound item removal, theft, transfer, Fling, and generated parameterized cases'],
  'ejectpack.js': [8, 'Eject Pack', 'data/items.ts:1704', 'stat-drop-triggered switching, deferred switches, queue ordering, doubles slot replacement, and item acquisition timing'],
  'eviolite.js': [5, 'Eviolite', 'data/items.ts:1863', 'evolution eligibility and defense modifiers'],
  'flameorb.js': [4, 'Flame Orb', 'data/items.ts:2137', 'residual item activation timing and burn application'],
  'focussash.js': [4, 'Focus Sash', 'data/items.ts:2264', 'full-HP survival, item consumption, and direct versus confusion/recoil/residual damage provenance'],
  'griseousorb.js': [4, 'Griseous Orb', 'data/items.ts:2675', 'species-bound item interaction with ability-changing effects'],
  'heavydutyboots.js': [8, 'Heavy-Duty Boots', 'data/items.ts:2852', 'entry-hazard suppression during switching'],
  'ironball.js': [4, 'Iron Ball', 'data/items.ts:3045', 'speed modification, grounding, natural and artificial Ground immunity, Gravity interaction, and type effectiveness'],
  'jabocaberry.js': [4, 'Jaboca Berry', 'data/items.ts:3083', 'physical-hit retaliation, post-faint event timing, and Magic Guard'],
  'keeberry.js': [6, 'Kee Berry', 'data/items.ts:3172', 'reactive berry activation during multi-hit moves'],
  'lifeorb.js': [4, 'Life Orb', 'data/items.ts:3399', 'successful-attack recoil timing after switching moves'],
  'metronome.js': [4, 'Metronome item', 'data/items.ts:3988', 'consecutive-use damage scaling, reset rules, Protect, charge moves, and delegated moves'],
  'mirrorherb.js': [9, 'Mirror Herb', 'data/items.ts:4145', 'copying effective boosts, simultaneous boosts, caps, and entrance ordering'],
  'plates.js': [4, 'Plates and Arceus', 'data/items.ts:1449', 'species-bound item removal, theft, transfer, Fling, and generated parameterized cases'],
  'protectivepads.js': [7, 'Protective Pads', 'data/items.ts:4849', 'contact suppression across ability, item, protection, and forme-trigger event families'],
  'punchingglove.js': [9, 'Punching Glove', 'data/items.ts:4933', 'move-flag-conditioned contact suppression and contact-trigger ownership'],
  'redcard.js': [5, 'Red Card', 'data/items.ts:5141', 'reactive forced switching relative to fainting and Destiny Bond'],
  'ringtarget.js': [5, 'Ring Target', 'data/items.ts:5222', 'natural type-immunity negation versus ability and volatile immunities'],
  'rockyhelmet.js': [5, 'Rocky Helmet', 'data/items.ts:5290', 'contact-triggered retaliation damage'],
  'roomservice.js': [8, 'Room Service', 'data/items.ts:5305', 'pseudo-weather-triggered stat loss and event ordering'],
  'safetygoggles.js': [6, 'Safety Goggles', 'data/items.ts:5453', 'powder immunity, item revelation, terrain, and accuracy ordering'],
  'seeds.js': [7, 'Terrain Seeds', 'data/items.ts:1794', 'terrain-triggered activation, switch-in ordering, Magic Room, Primal Reversion, and Symbiosis'],
  'shedshell.js': [4, 'Shed Shell', 'data/items.ts:5628', 'legal switch choices under ability, volatile, self-trap, and Sky Drop trapping'],
  'weaknesspolicy.js': [6, 'Weakness Policy', 'data/items.ts:7591', 'type-effectiveness-triggered boosts, fixed damage, doubles targeting, and forced-switch ordering'],
};

const census = JSON.parse(fs.readFileSync(CENSUS_PATH, 'utf8'));
if (census.pinned_revision !== PINNED_REVISION) {
  throw new Error(`unexpected census revision ${census.pinned_revision}`);
}

const declarations = census.records.filter(record =>
  record.audit_status === 'unadjudicated' && record.source_file.startsWith('test/sim/items/')
);

const records = declarations.map(record => {
  const basename = path.basename(record.source_file);
  if (basename === 'choiceitem.js') {
    return {
      identity: {
        source_file: record.source_file,
        source_line: record.source_line,
        full_test_name: record.full_test_name,
        pinned_revision: PINNED_REVISION,
      },
      disposition: 'different_generation_not_direct_evidence',
      evidence: [
        'test/sim/items/choiceitem.js:14 constructs common.gen(8), and lines 20-24 exercise Dynamax ending and restoration of its prior Choice lock.',
        'data/items.ts:959 defines Choice Band as a Gen 3 item, so the suite name is an umbrella; this declaration is specifically a Gen 8 transition and does not adjudicate ordinary Gen 3 Choice Band locking.',
      ],
      mechanics_and_boundaries: [
        'Choice-lock persistence across Dynamax suppression and restoration',
        'legal move choice after a generation-specific battle-mode transition',
      ],
      native_coverage: {
        status: 'different_generation_assertion_not_covered',
        channels: {
          native_unit: [],
          differential_fixture: [
            'item-choice-band-connected-lock',
            'item-choice-band-miss-lock',
            'item-choice-band-status-lock',
            'item-choice-band-switch-reset',
          ],
          invariant: [],
          randomized_scenario: [],
        },
        evidence: 'The native Gen 3 contract has no Dynamax state or transition. The listed fixtures cover ordinary Gen 3 Choice Band locking, but cannot cover or be credited for this Gen 8 assertion.',
      },
      required_case: null,
      uncertainty: null,
    };
  }

  const policy = policies[basename];
  if (!policy) throw new Error(`missing item policy for ${record.source_file}`);
  const [introducedGeneration, subject, itemSource, mechanics] = policy;
  return {
    identity: {
      source_file: record.source_file,
      source_line: record.source_line,
      full_test_name: record.full_test_name,
      pinned_revision: PINNED_REVISION,
    },
    disposition: 'mechanic_unreachable_gen3',
    evidence: [
      `${itemSource} defines ${subject}; sim/dex-items.ts:123-145 assigns item generations from explicit gen or item-number bands, resolving it to Gen ${introducedGeneration}.`,
      `${record.source_file}:${record.source_line} asserts behavior owned by that post-Gen-3 item; the item cannot be present in a legal Gen 3 OU battle.`,
    ],
    mechanics_and_boundaries: [mechanics, `Upstream assertion: ${record.full_test_name}`],
    native_coverage: {
      status: 'not_required_for_gen3ou',
      channels: {
        native_unit: [],
        differential_fixture: [],
        invariant: [],
        randomized_scenario: [],
      },
      evidence: `The tested owner is introduced in Gen ${introducedGeneration}, so no native or differential Gen 3 OU case is required from this declaration.`,
    },
    required_case: null,
    uncertainty: null,
  };
});

records.sort((a, b) =>
  a.identity.source_file.localeCompare(b.identity.source_file) ||
  a.identity.source_line - b.identity.source_line ||
  a.identity.full_test_name.localeCompare(b.identity.full_test_name)
);

const output = {
  schema: 'pokemon-gen3ou-upstream-item-test-overlay-v1',
  pinned_revision: PINNED_REVISION,
  scope: {
    census: 'all-test-census.json',
    selection: 'Every unadjudicated declaration under test/sim/items at generation time.',
    claim_boundary: 'Audit overlay only. It neither changes native support claims nor substitutes for Gen 3-specific tests of similarly named mechanics.',
  },
  summary: {
    declarations: records.length,
    by_disposition: Object.fromEntries([...new Set(records.map(record => record.disposition))].sort().map(
      disposition => [disposition, records.filter(record => record.disposition === disposition).length]
    )),
    requiring_new_case: records.filter(record => record.required_case !== null).length,
    unresolved: records.filter(record => record.uncertainty !== null).length,
  },
  records,
};

fs.writeFileSync(OUTPUT_PATH, `${JSON.stringify(output, null, 2)}\n`);
console.log(`wrote ${records.length} item-test adjudications to ${path.basename(OUTPUT_PATH)}`);
