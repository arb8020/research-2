#!/usr/bin/env node
'use strict';

const childProcess = require('child_process');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const showdownDir = process.argv[2];
const output = process.argv[3];
if (!showdownDir || !['header', 'source'].includes(output)) {
  throw new Error('usage: generate_gen3_admission.js POKEMON_SHOWDOWN_DIR header|source');
}
const revision = childProcess.execFileSync('git', ['-C', showdownDir, 'rev-parse', 'HEAD'], {encoding: 'utf8'}).trim();
if (revision !== REVISION) throw new Error(`expected Pokémon Showdown ${REVISION}, got ${revision}`);
const dirty = childProcess.execFileSync('git', ['-C', showdownDir, 'status', '--porcelain', '--untracked-files=no'], {encoding: 'utf8'}).trim();
if (dirty) throw new Error('admission generation requires a clean pinned Showdown checkout');

const {Dex, TeamValidator} = require(path.resolve(showdownDir));
const dex = Dex.forFormat('gen3ou');
const validator = new TeamValidator('gen3ou');
function identities(table) {
  /* Use the normalized set-input name, not descriptor.id: the effective Dex
   * exposes all seventeen Hidden Power inputs as descriptors sharing the
   * runtime id `hiddenpower`.  Admission must retain those distinct inputs. */
  return [...new Set(dex[table].all()
    .filter(value => value.exists && value.gen <= 3)
    .map(value => Dex.toID(value.name)))].sort();
}
const universe = {
  species: identities('species'),
  move: identities('moves'),
  ability: identities('abilities'),
  item: identities('items'),
};
/* Rule operands are part of the known admission vocabulary even when their
 * descriptors are later-generation and therefore absent from the Gen 3 Dex. */
const explicitRuleInputs = {move: ['acupressure']};
for (const [kind, ids] of Object.entries(explicitRuleInputs)) {
  universe[kind] = [...new Set([...universe[kind], ...ids])].sort();
}
const expectedCounts = {species: 393, move: 374, ability: 80, item: 129};
for (const [kind, expected] of Object.entries(expectedCounts)) {
  if (universe[kind].length !== expected) {
    throw new Error(`expected ${expected} Gen 3 ${kind} identities, got ${universe[kind].length}`);
  }
}
const speciesMetadata = universe.species.map(id => {
  const species = dex.species.get(id);
  const baseID = Dex.toID(species.baseSpecies);
  const baseIndex = universe.species.indexOf(baseID);
  if (!species.exists || !species.name || baseIndex < 0) {
    throw new Error(`cannot resolve nickname metadata for ${id}`);
  }
  return {name: species.name, baseSpeciesID: baseIndex + 1};
});
const eggGroups = [...new Set(universe.species.flatMap(id => {
  const species = dex.species.get(id);
  return species.exists && species.num > 0 ? species.eggGroups : [];
}))].sort();
if (eggGroups.length > 16) throw new Error(`too many Gen 3 egg groups: ${eggGroups.length}`);
const eggGroupIndex = new Map(eggGroups.map((group, index) => [group, index]));
const acquisitionLevels = [];
const acquisitionEventRefs = [];
const acquisitionEvents = [];
const eventBySpeciesAndLocal = new Map();
let maxEventsPerSpecies = 0;
for (const speciesID of universe.species) {
  const species = dex.species.get(speciesID);
  const localEvents = new Map();
  if (species.exists && species.num > 0) {
    const eventData = dex.species.getLearnsetData(species.id).eventData || [];
    eventData.forEach((event, localIndex) => {
      if (event.generation !== 3) return;
      const unknown = Object.keys(event).filter(key => ![
        'generation', 'level', 'moves', 'pokeball', 'gender', 'abilities',
        'shiny', 'emeraldEventEgg', 'nature', 'ivs',
      ].includes(key));
      if (unknown.length) throw new Error(`${species.id} event ${localIndex}: unencoded ${unknown}`);
      const moves = (event.moves || []).map(move => {
        const moveID = universe.move.indexOf(move) + 1;
        if (!moveID) throw new Error(`${species.id} event ${localIndex}: unknown move ${move}`);
        return moveID;
      });
      if (moves.length > 4 || (event.abilities || []).length > 1) {
        throw new Error(`${species.id} event ${localIndex}: capacity exceeded`);
      }
      const globalID = acquisitionEvents.length + 1;
      localEvents.set(localIndex, globalID);
      acquisitionEvents.push({
        speciesID: universe.species.indexOf(species.id) + 1,
        abilityID: universe.ability.indexOf(Dex.toID((event.abilities || [])[0] || '')) + 1,
        abilitySlot: event.abilities?.length && species.abilities['1'] &&
          dex.abilities.get(species.abilities['1']).gen <= event.generation ?
          (Dex.toID(event.abilities[0]) === Dex.toID(species.abilities['1']) ? 2 : 1) : 0,
        localIndex, level: event.level || 0, gender: event.gender || '',
        shiny: event.shiny === true, shinyOptional: event.shiny === 1,
        emeraldEventEgg: !!event.emeraldEventEgg,
        nature: Dex.toID(event.nature || ''),
        ability: Dex.toID((event.abilities || [])[0] || ''),
        ivs: ['hp', 'atk', 'def', 'spa', 'spd', 'spe'].map(stat => event.ivs?.[stat] ?? 255),
        moves,
      });
    });
  }
  maxEventsPerSpecies = Math.max(maxEventsPerSpecies, localEvents.size);
  eventBySpeciesAndLocal.set(speciesID, localEvents);
}
const acquisitionMoveRows = [];
const acquisitionSpecies = [];
const acquisitionEventOnlyRefs = [];
let maxSourcesPerMove = 0;
for (const speciesID of universe.species) {
  const species = dex.species.get(speciesID);
  const firstMoveRow = acquisitionMoveRows.length;
  if (species.exists && species.num > 0) {
    const learnset = dex.species.getLearnsetData(species.id).learnset || {};
    for (const moveID of Object.keys(learnset).sort()) {
      const admissionMoveID = universe.move.indexOf(moveID) + 1;
      if (!admissionMoveID) continue;
      const sources = learnset[moveID].filter(source => Number(source[0]) <= dex.gen);
      if (sources.some(source => source[0] !== '3')) {
        throw new Error(`${speciesID}/${moveID}: unexpected pre-Gen-3 source ${sources}`);
      }
      if (!sources.length) continue;
      let flags = 0;
      const levels = [];
      const events = [];
      for (const source of sources) {
        const kind = source[1];
        if (kind === 'L') levels.push(Number(source.slice(2)));
        else if (kind === 'S') {
          const eventID = eventBySpeciesAndLocal.get(speciesID).get(Number(source.slice(2)));
          if (!eventID) throw new Error(`${speciesID}/${moveID}: dangling ${source}`);
          events.push(eventID);
        } else if (kind === 'M') flags |= 1;
        else if (kind === 'T') flags |= 2;
        else if (kind === 'E') flags |= 4;
        else if (kind === 'R') flags |= 8;
        else throw new Error(`${speciesID}/${moveID}: unsupported source ${source}`);
      }
      if (levels.length && species.canHatch && species.gender !== 'N') {
        const motherCanLearn = species.gender !== 'M' || (species.mother &&
          dex.species.getFullLearnset(Dex.toID(species.mother)).some(
            entry => entry.learnset[moveID]));
        if (motherCanLearn) flags |= 16;
      }
      levels.sort((a, b) => a - b);
      events.sort((a, b) => a - b);
      maxSourcesPerMove = Math.max(maxSourcesPerMove,
        levels.length + events.length + ['1', '2', '4', '8'].filter(bit => flags & Number(bit)).length);
      const levelOffset = acquisitionLevels.length;
      const eventOffset = acquisitionEventRefs.length;
      acquisitionLevels.push(...levels);
      acquisitionEventRefs.push(...events);
      acquisitionMoveRows.push({
        moveID: admissionMoveID, levelOffset, eventOffset, flags,
        levelCount: levels.length, eventCount: events.length,
      });
    }
  }
  const parent = species.exists && species.num > 0 ? dex.species.learnsetParent(species, true) : null;
  let effectiveEggGroups = species.exists && species.num > 0 ? species.eggGroups : [];
  if (effectiveEggGroups[0] === 'Undiscovered' && species.evos?.length) {
    effectiveEggGroups = dex.species.get(species.evos[0]).eggGroups;
  }
  const eggMask = effectiveEggGroups.reduce(
    (mask, group) => mask | (1 << eggGroupIndex.get(group)), 0);
  const fixedGender = species.gender === 'M' ? 1 : species.gender === 'F' ? 2 : species.gender === 'N' ? 3 : 0;
  const eventOnlyOffset = acquisitionEventOnlyRefs.length;
  if (species.exists && species.num > 0) {
    const eventOnly = validator.getEventOnlyData(species);
    if (eventOnly) {
      eventOnly.eventData.forEach((event, localIndex) => {
        if (event.generation !== 3) return;
        const eventID = eventBySpeciesAndLocal.get(eventOnly.species.id)?.get(localIndex);
        if (!eventID) throw new Error(`${species.id}: dangling event-only source ${localIndex}`);
        acquisitionEventOnlyRefs.push(eventID);
      });
    }
  }
  acquisitionSpecies.push({
    firstMoveRow, moveRowCount: acquisitionMoveRows.length - firstMoveRow,
    eventOnlyOffset, eventOnlyCount: acquisitionEventOnlyRefs.length - eventOnlyOffset,
    parentSpeciesID: parent ? universe.species.indexOf(parent.id) + 1 : 0,
    abilityIDs: ['0', '1'].map(slot =>
      universe.ability.indexOf(Dex.toID(species.abilities?.[slot] || '')) + 1),
    eggMask, evolutionLevel: species.evoLevel || 0, fixedGender,
    canHatch: species.canHatch ? 1 : 0,
  });
}
const moveSourceIDs = universe.move.map(id => {
  const sourceID = id.startsWith('hiddenpower') && id !== 'hiddenpower' ? 'hiddenpower' : id;
  const move = dex.moves.get(sourceID);
  return move.exists && move.num > 0 && move.gen <= 3 ? universe.move.indexOf(sourceID) + 1 : 0;
});
const moveSketchable = universe.move.map((id, index) => {
  const sourceID = moveSourceIDs[index];
  if (!sourceID) return 0;
  const move = dex.moves.get(universe.move[sourceID - 1]);
  return move.exists && !move.noSketch ? 1 : 0;
});
const natureIDs = dex.natures.all().filter(nature => nature.exists)
  .map(nature => nature.id).sort();
const hiddenPowerTypeIDs = [
  'fighting', 'flying', 'poison', 'ground', 'rock', 'bug', 'ghost', 'steel',
  'fire', 'water', 'grass', 'electric', 'psychic', 'ice', 'dragon', 'dark',
];
const hiddenPowerIVs = hiddenPowerTypeIDs.map(id => {
  const values = dex.types.get(id).HPivs || {};
  return ['hp', 'atk', 'def', 'spa', 'spd', 'spe'].map(stat => values[stat] ?? 31);
});
const moveHiddenPowerType = universe.move.map(id => {
  if (!id.startsWith('hiddenpower') || id === 'hiddenpower') return 0;
  return hiddenPowerTypeIDs.indexOf(id.slice('hiddenpower'.length)) + 1;
});
const acquisitionData = {
  eggGroups, species: acquisitionSpecies, moveRows: acquisitionMoveRows,
  levels: acquisitionLevels, eventRefs: acquisitionEventRefs,
  eventOnlyRefs: acquisitionEventOnlyRefs,
  events: acquisitionEvents, moveSourceIDs, moveSketchable, natureIDs,
  hiddenPowerTypeIDs, hiddenPowerIVs, moveHiddenPowerType, maxEventsPerSpecies,
  maxSourcesPerMove, maxLineageDepth: 3,
};

const ruleTable = dex.formats.getRuleTable(dex.formats.get('gen3ou'));
const nicknameClause = dex.formats.get('nicknameclause');
if (!ruleTable.has('nicknameclause') || typeof nicknameClause.onValidateTeam !== 'function') {
  throw new Error('resolved Gen 3 OU rules lack Nickname Clause');
}
const banOperands = [
  ['ability', 'sandveil'], ['ability', 'soundproof'],
  ['item', 'brightpowder'], ['item', 'laxincense'],
  ['move', 'acupressure'], ['move', 'assist'], ['move', 'doubleteam'],
  ['move', 'minimize'], ['move', 'swagger'],
];
const bans = banOperands.map(([kind, id]) => {
  const source = ruleTable.get(`-${kind}:${id}`);
  if (typeof source !== 'string') throw new Error(`missing resolved atomic ban -${kind}:${id}`);
  return [kind, id, Dex.toID(source || 'gen3ou')];
});
const expectedParents = {
  brightpowder: 'evasionitemsclause', laxincense: 'evasionitemsclause',
  acupressure: 'evasionmovesclause', doubleteam: 'evasionmovesclause',
  minimize: 'evasionmovesclause',
};
for (const [, id, parent] of bans) {
  if (parent !== (expectedParents[id] || 'gen3ou')) {
    throw new Error(`unexpected resolved parent for ${id}: ${parent}`);
  }
}
function tags(kind, id) {
  const table = {species: 'species', move: 'moves', ability: 'abilities', item: 'items'}[kind];
  let descriptor = dex[table].get(id);
  let tier = '';
  if (kind === 'species') {
    const set = {
      species: descriptor.name,
      ability: Object.values(descriptor.abilities)[0] || '',
      item: '', moves: ['Splash'], level: 100, nature: 'Serious',
      evs: {hp: 1, atk: 0, def: 0, spa: 0, spd: 0, spe: 0},
    };
    descriptor = validator.getValidationSpecies(set).tierSpecies;
    tier = descriptor.tier;
  }
  const values = [];
  if (kind === 'species' && ['Uber', '(Uber)', 'AG'].includes(tier)) values.push('UBER');
  if (descriptor.isNonstandard === 'Unobtainable') values.push('UNOBTAINABLE');
  else if (descriptor.isNonstandard) values.push('NONEXISTENT');
  return values;
}
const identityTags = Object.fromEntries(Object.entries(universe).map(([kind, ids]) => [
  kind, Object.fromEntries(ids.map(id => [id, tags(kind, id)])),
]));
const ohkoMoves = universe.move.filter(id => !!dex.moves.get(id).ohko);
const expectedOhkoMoves = ['fissure', 'guillotine', 'horndrill', 'sheercold'];
if (JSON.stringify(ohkoMoves) !== JSON.stringify(expectedOhkoMoves)) {
  throw new Error(`unexpected Gen 3 OHKO move closure: ${ohkoMoves.join(', ')}`);
}
for (const id of ohkoMoves) {
  if (dex.moves.get(id).ohko !== true) throw new Error(`${id} has a non-boolean OHKO descriptor`);
}
if (ohkoMoves.includes('metronome')) throw new Error('Metronome must not inherit delegated OHKO identity');
const accuracyTrapRule = dex.formats.get('accuracytrapclause');
if (typeof accuracyTrapRule.onValidateSet !== 'function') {
  throw new Error('resolved Accuracy Trap Clause lacks onValidateSet');
}
function accuracyTrapRejects(ability, moves) {
  return !!accuracyTrapRule.onValidateSet.call(
    {dex, toID: Dex.toID}, {species: 'smeargle', ability, moves}, null, null, null);
}
const guaranteedAccuracyDropMoves = universe.move.filter(id =>
  accuracyTrapRejects('arenatrap', [id]));
const structurallyGuaranteedAccuracyDropMoves = universe.move.filter(id => {
  const move = dex.moves.get(id);
  if (move.boosts?.accuracy) return move.boosts.accuracy < 0;
  return move.secondaries?.some(effect =>
    effect.chance === 100 && effect.boosts?.accuracy && effect.boosts.accuracy < 0);
});
const expectedAccuracyDropMoves = ['flash', 'kinesis', 'mudslap', 'sandattack', 'smokescreen'];
if (JSON.stringify(guaranteedAccuracyDropMoves) !== JSON.stringify(expectedAccuracyDropMoves)) {
  throw new Error(`unexpected guaranteed accuracy-drop closure: ${guaranteedAccuracyDropMoves.join(', ')}`);
}
if (JSON.stringify(structurallyGuaranteedAccuracyDropMoves) !==
    JSON.stringify(guaranteedAccuracyDropMoves)) {
  throw new Error('Accuracy Trap callback and resolved move descriptors disagree');
}
const trappingMoves = universe.move.filter(id => accuracyTrapRejects('static', ['flash', id]));
const trappingAbilities = universe.ability.filter(id => accuracyTrapRejects(id, ['flash']));
if (JSON.stringify(trappingMoves) !== JSON.stringify(['block', 'meanlook', 'spiderweb']) ||
    JSON.stringify(trappingAbilities) !== JSON.stringify(['arenatrap', 'magnetpull', 'shadowtag'])) {
  throw new Error(`unexpected Gen 3 trapping closure: ${trappingMoves}; ${trappingAbilities}`);
}
const oneBoostRule = dex.formats.get('oneboostpasserclause');
const speedPassRule = dex.formats.get('speedpassclause');
if (typeof oneBoostRule.onValidateTeam !== 'function' ||
    typeof speedPassRule.onValidateTeam !== 'function') {
  throw new Error('resolved boost-pass clauses lack onValidateTeam');
}
const validationContext = {toID: Dex.toID};
const oneBoostRejects = set => !!oneBoostRule.onValidateTeam.call(validationContext, [set]);
const speedPassRejects = set => !!speedPassRule.onValidateTeam.call(validationContext, [set]);
const basePasser = {species: 'Smeargle', ability: 'Own Tempo', item: '', moves: ['Baton Pass']};
const boostMoves = universe.move.filter(id => oneBoostRejects({
  ...basePasser, moves: ['Baton Pass', id, id],
}));
const boostItems = universe.item.filter(id => oneBoostRejects({
  ...basePasser, item: id, moves: ['Baton Pass', 'acidarmor'],
}));
const boostAbilities = universe.ability.filter(id => oneBoostRejects({
  ...basePasser, ability: id, moves: ['Baton Pass', 'acidarmor'],
}));
const speedBoostMoves = universe.move.filter(id => speedPassRejects({
  ...basePasser, moves: ['Baton Pass', id],
}));
const speedBoostItems = universe.item.filter(id => speedPassRejects({...basePasser, item: id}));
const speedBoostAbilities = universe.ability.filter(id => speedPassRejects({...basePasser, ability: id}));
const expectedBoostMoves = [
  'acidarmor', 'agility', 'amnesia', 'barrier', 'bellydrum', 'bulkup', 'calmmind',
  'cosmicpower', 'curse', 'defensecurl', 'dragondance', 'growth', 'harden', 'howl',
  'irondefense', 'meditate', 'sharpen', 'swordsdance', 'tailglow', 'withdraw',
];
const expectedBoostItems = [
  'apicotberry', 'ganlonberry', 'liechiberry', 'petayaberry', 'salacberry', 'starfberry',
];
if (JSON.stringify(boostMoves) !== JSON.stringify(expectedBoostMoves) ||
    JSON.stringify(boostItems) !== JSON.stringify(expectedBoostItems) ||
    JSON.stringify(boostAbilities) !== JSON.stringify(['speedboost']) ||
    JSON.stringify(speedBoostMoves) !== JSON.stringify(['agility', 'ancientpower', 'dragondance', 'silverwind']) ||
    JSON.stringify(speedBoostItems) !== JSON.stringify(['salacberry', 'starfberry']) ||
    JSON.stringify(speedBoostAbilities) !== JSON.stringify(['speedboost'])) {
  throw new Error('unexpected Gen 3 boost-pass predicate closure');
}
const identityPredicates = Object.fromEntries(Object.entries(universe).map(([kind, ids]) => [
  kind, Object.fromEntries(ids.map(id => {
    const predicates = [];
    if (kind === 'move' && ohkoMoves.includes(id)) predicates.push('OHKO');
    if (kind === 'move' && guaranteedAccuracyDropMoves.includes(id)) {
      predicates.push('GUARANTEED_ACCURACY_DROP');
    }
    if ((kind === 'move' && trappingMoves.includes(id)) ||
        (kind === 'ability' && trappingAbilities.includes(id))) predicates.push('TRAPPING');
    if (kind === 'move' && id === 'batonpass') predicates.push('BATON_PASS');
    if ((kind === 'move' && boostMoves.includes(id)) ||
        (kind === 'item' && boostItems.includes(id)) ||
        (kind === 'ability' && boostAbilities.includes(id))) predicates.push('BOOST_SOURCE');
    if ((kind === 'move' && speedBoostMoves.includes(id)) ||
        (kind === 'item' && speedBoostItems.includes(id)) ||
        (kind === 'ability' && speedBoostAbilities.includes(id))) {
      predicates.push('SPEED_BOOST_SOURCE');
    }
    return [id, predicates];
  })),
]));
const tagBans = [
  ['uber', 'UBER', ['species'], '-pokemontag:uber'],
  ['unobtainable', 'UNOBTAINABLE', ['species', 'move', 'ability', 'item'], '-pokemontag:unobtainable'],
  ['nonexistent', 'NONEXISTENT', ['species', 'move', 'ability', 'item'], '-nonexistent'],
].map(([id, tag, kinds, rule]) => {
  const source = ruleTable.get(rule);
  if (typeof source !== 'string') throw new Error(`missing resolved tag ban ${rule}`);
  return {id, tag, kinds, sourceRuleID: Dex.toID(source || 'gen3ou')};
});
const hiddenAbilitySpecies = universe.species.filter(id => !!dex.species.get(id).abilities.H);
if (hiddenAbilitySpecies.length) {
  throw new Error(`Gen 3 admission unexpectedly has hidden ability slots: ${hiddenAbilitySpecies.join(', ')}`);
}
if (ruleTable.get('obtainableabilities') !== 'Obtainable') {
  throw new Error('unexpected resolved Gen 3 OU Obtainable Abilities policy');
}
const speciesAbilityRows = universe.species.map(id => {
  const species = dex.species.get(id);
  const abilities = [...new Set(Object.values(species.abilities)
    .map(name => Dex.toID(name)).filter(Boolean))].sort();
  if (abilities.length > 2) throw new Error(`${id} has more than two resolved Gen 3 abilities`);
  const set = {
    species: species.name, ability: abilities[0] || '', item: '', moves: ['Splash'],
    level: 100, nature: 'Serious', evs: {hp: 1, atk: 0, def: 0, spa: 0, spd: 0, spe: 0},
  };
  const tierSpecies = validator.getValidationSpecies(set).tierSpecies;
  const tierAbilities = [...new Set(Object.values(tierSpecies.abilities)
    .map(name => Dex.toID(name)).filter(Boolean))].sort();
  if (JSON.stringify(abilities) !== JSON.stringify(tierAbilities)) {
    throw new Error(`${id} resolved species and tier species abilities disagree`);
  }
  return abilities.map(ability => {
    const index = universe.ability.indexOf(ability);
    if (index < 0) throw new Error(`${id} ability is outside the admission universe: ${ability}`);
    return index + 1;
  }).sort((a, b) => a - b);
});
const speciesAbilityMembers = speciesAbilityRows.flat();
if (speciesAbilityMembers.length !== 517) {
  throw new Error(`expected 517 resolved species/ability pairs, got ${speciesAbilityMembers.length}`);
}
const speciesAbilityOffsets = [0];
for (const row of speciesAbilityRows) {
  speciesAbilityOffsets.push(speciesAbilityOffsets.at(-1) + row.length);
}
const allowedRelations = [{
  id: 'speciesabilities', ownerKind: 'species', memberKind: 'ability',
  offsets: speciesAbilityOffsets, members: speciesAbilityMembers,
}];
const impossibleComplexRules = [
  'Huntail + Shell Smash + Sucker Punch',
  'Hypnosis + Gengarite',
].map(name => {
  const record = ruleTable.complexBans.find(([ruleName]) => ruleName === name);
  if (!record) throw new Error(`missing resolved complex ban ${name}`);
  const absent = record[3].filter(operand => {
    const [rawKind, id] = operand.split(':');
    const kind = rawKind === 'pokemon' ? 'species' : rawKind;
    return !universe[kind]?.includes(id);
  });
  if (!absent.length) throw new Error(`complex ban is no longer statically unmatchable: ${name}`);
  return {name, sourceRuleID: Dex.toID(record[1]), absent};
});
const staticProofs = {
  unreleased_hidden_ability_species: hiddenAbilitySpecies,
  impossible_complex_rules: impossibleComplexRules,
};
const allOfBans = [{
  id: 'ohkoclause', sourceRuleID: 'standard', scope: 'SET',
  requirements: [{predicate: 'OHKO', kinds: ['move']}],
}, {
  id: 'accuracytrapclause', sourceRuleID: 'gen3ou', scope: 'SET',
  requirements: [
    {predicate: 'GUARANTEED_ACCURACY_DROP', kinds: ['move']},
    {predicate: 'TRAPPING', kinds: ['move', 'ability']},
  ],
}, {
  id: 'speedpassclause', sourceRuleID: 'gen3ou', scope: 'TEAM',
  requirements: [
    {predicate: 'BATON_PASS', kinds: ['move']},
    {predicate: 'SPEED_BOOST_SOURCE', kinds: ['move', 'ability', 'item']},
  ],
}];
const anchoredCardinalityBans = [{
  id: 'oneboostpasserclause', sourceRuleID: 'gen3ou', scope: 'TEAM',
  anchor: {predicate: 'BATON_PASS', kinds: ['move']},
  counted: {predicate: 'BOOST_SOURCE', kinds: ['move', 'ability', 'item']},
  maxSourcesPerSet: 1, maxMatchingSets: 1,
}];
if (ruleTable.evLimit !== 510 || ruleTable.valueRules.get('evlimit') !== 'Auto' ||
    ruleTable.get('evlimit') !== 'Obtainable') {
  throw new Error('unexpected resolved Gen 3 OU EV Limit policy');
}
const statVectorRules = [{
  id: 'evlimit', sourceRuleID: 'obtainable', scope: 'SET',
  componentMin: 0, componentMax: 255, expectedTotalLimit: 510,
  rejectZeroAboveLevel: 1,
}];
const allowedRelationRules = [{
  id: 'obtainableabilities', sourceRuleID: 'obtainableabilities', scope: 'SET', relationID: 1,
}];
const nicknameRules = [{
  id: 'nicknameclause', sourceRuleID: 'nicknameclause', scope: 'TEAM',
}];
if (ruleTable.get('obtainablemisc') !== 'Obtainable') {
  throw new Error('unexpected resolved Gen 3 OU Obtainable Misc policy');
}
const uniqueMoveRules = [{
  id: 'obtainablemisc', sourceRuleID: 'obtainablemisc', scope: 'SET',
}];
if (ruleTable.get('obtainablemoves') !== 'Obtainable') {
  throw new Error('unexpected resolved Gen 3 OU Obtainable Moves policy');
}
const obtainableMoveRules = [{
  id: 'obtainablemoves', sourceRuleID: 'obtainablemoves', scope: 'SET',
}];
const setFieldRules = [{
  id: 'obtainablemisc', sourceRuleID: 'obtainablemisc', scope: 'SET',
}];
if (ruleTable.get('obtainableformes') !== 'Obtainable') {
  throw new Error('unexpected resolved Gen 3 OU Obtainable Formes policy');
}
const battleOnlySpecies = universe.species.filter(id => !!dex.species.get(id).battleOnly);
const expectedBattleOnlySpecies = ['castformrainy', 'castformsnowy', 'castformsunny'];
if (JSON.stringify(battleOnlySpecies) !== JSON.stringify(expectedBattleOnlySpecies)) {
  throw new Error(`unexpected resolved Gen 3 battle-only formes: ${battleOnlySpecies.join(', ')}`);
}
const runtimeSpecies = new Set(JSON.parse(fs.readFileSync(path.resolve(
  __dirname, '../verify/inventory/gen3ou-inventory.json'))).species.map(species => species.id));
const speciesRewriteRules = [{
  id: 'obtainableformes', sourceRuleID: 'obtainableformes', scope: 'SET',
  rewrites: battleOnlySpecies.map(id => {
    const species = dex.species.get(id);
    const output = Dex.toID(species.battleOnly);
    const ability = Dex.toID(species.requiredAbility);
    if (output !== 'castform' || ability !== 'forecast' || !runtimeSpecies.has(output)) {
      throw new Error(`unexpected or non-runnable Gen 3 forme rewrite: ${id}`);
    }
    return {
      inputSpeciesID: universe.species.indexOf(id) + 1,
      outputSpeciesID: universe.species.indexOf(output) + 1,
      requiredAbilityID: universe.ability.indexOf(ability) + 1,
    };
  }),
}];
const model = {
  revision: REVISION, universe, identityTags, identityPredicates, bans, tagBans,
  allOfBans, anchoredCardinalityBans, statVectorRules, allowedRelations,
  allowedRelationRules, speciesRewriteRules, nicknameRules, uniqueMoveRules,
  obtainableMoveRules,
  setFieldRules,
  speciesMetadata, acquisitionData,
  staticProofs,
};
const fingerprint = crypto.createHash('sha256').update(JSON.stringify(model)).digest('hex').slice(0, 16).toUpperCase();
const cFingerprint = `UINT64_C(0x${fingerprint})`;
const token = value => value.toUpperCase();

if (output === 'header') {
  process.stdout.write(`/* Generated by tools/generate_gen3_admission.js; do not edit. */\n` +
`/* Pokémon Showdown source revision: ${REVISION}. */\n` +
`#ifndef GEN3_ADMISSION_DATA_H\n#define GEN3_ADMISSION_DATA_H\n\n` +
`#include "pokemon_admission.h"\n` +
`#include "pokemon_acquisition.h"\n` +
`#include "gen3_rules.h"\n\n` +
`#define POKEMON_GEN3_ADMISSION_FINGERPRINT ${cFingerprint}\n` +
`#define POKEMON_GEN3_ADMISSION_SPECIES_COUNT 393\n` +
`#define POKEMON_GEN3_ADMISSION_MOVE_COUNT 374\n` +
`#define POKEMON_GEN3_ADMISSION_ABILITY_COUNT 80\n` +
`#define POKEMON_GEN3_ADMISSION_ITEM_COUNT 129\n` +
`#define POKEMON_GEN3_ACQUISITION_MOVE_ROW_COUNT ${acquisitionMoveRows.length}\n` +
`#define POKEMON_GEN3_ACQUISITION_LEVEL_COUNT ${acquisitionLevels.length}\n` +
`#define POKEMON_GEN3_ACQUISITION_EVENT_REF_COUNT ${acquisitionEventRefs.length}\n` +
`#define POKEMON_GEN3_ACQUISITION_EVENT_ONLY_REF_COUNT ${acquisitionEventOnlyRefs.length}\n` +
`#define POKEMON_GEN3_ACQUISITION_EVENT_COUNT ${acquisitionEvents.length}\n` +
`#define POKEMON_GEN3_ACQUISITION_MAX_SOURCES_PER_MOVE ${maxSourcesPerMove}\n` +
`#define POKEMON_GEN3_ADMISSION_ATOMIC_BAN_COUNT 9\n\n` +
`#define POKEMON_GEN3_ADMISSION_TAG_BAN_COUNT 3\n` +
`#define POKEMON_GEN3_ADMISSION_ALL_OF_BAN_COUNT 3\n` +
`#define POKEMON_GEN3_ADMISSION_ANCHORED_CARDINALITY_BAN_COUNT 1\n` +
`#define POKEMON_GEN3_ADMISSION_STAT_VECTOR_RULE_COUNT 1\n` +
`#define POKEMON_GEN3_ADMISSION_ALLOWED_RELATION_COUNT 1\n` +
`#define POKEMON_GEN3_ADMISSION_SPECIES_ABILITY_PAIR_COUNT 517\n` +
`#define POKEMON_GEN3_ADMISSION_SPECIES_REWRITE_COUNT 3\n` +
`#define POKEMON_GEN3_ADMISSION_OHKO_MATCH_COUNT 4\n` +
`#define POKEMON_GEN3_ADMISSION_ACCURACY_DROP_MATCH_COUNT 5\n` +
`#define POKEMON_GEN3_ADMISSION_TRAPPING_MOVE_MATCH_COUNT 3\n` +
`#define POKEMON_GEN3_ADMISSION_TRAPPING_ABILITY_MATCH_COUNT 3\n` +
`#define POKEMON_GEN3_ADMISSION_BOOST_MOVE_MATCH_COUNT 20\n` +
`#define POKEMON_GEN3_ADMISSION_BOOST_ITEM_MATCH_COUNT 6\n` +
`#define POKEMON_GEN3_ADMISSION_BOOST_ABILITY_MATCH_COUNT 1\n` +
`#define POKEMON_GEN3_ADMISSION_SPEED_BOOST_MOVE_MATCH_COUNT 4\n` +
`#define POKEMON_GEN3_ADMISSION_SPEED_BOOST_ITEM_MATCH_COUNT 2\n` +
`#define POKEMON_GEN3_ADMISSION_SPEED_BOOST_ABILITY_MATCH_COUNT 1\n` +
`#define POKEMON_GEN3_ADMISSION_RULE_COUNT 23\n\n` +
`#define POKEMON_GEN3_ADMISSION_UNRELEASED_MATCH_COUNT 0\n` +
`#define POKEMON_GEN3_ADMISSION_UNMATCHABLE_COMPLEX_RULE_COUNT 2\n\n` +
`extern const PokemonAdmissionBundle POKEMON_GEN3_OU_ADMISSION;\n` +
`extern const PokemonAdmissionBundle POKEMON_GEN3_OU_POMEG_ADMISSION;\n\n#endif\n`);
  process.exit(0);
}

const lines = [
  '/* Generated by tools/generate_gen3_admission.js; do not edit. */',
  `/* Pokémon Showdown source revision: ${REVISION}. */`,
  '#include "gen3_admission_data.h"', '',
];
for (const [kind, values] of Object.entries(universe)) {
  lines.push(`static const PokemonAdmissionIdentity ${kind}_identities[] = {`);
  for (const id of values) {
    const valuesForID = identityTags[kind][id];
    const tagExpression = valuesForID.length ? valuesForID
      .map(tag => `POKEMON_ADMISSION_TAG_${tag}`).join(' | ') : '0';
    const predicatesForID = identityPredicates[kind][id];
    const predicateExpression = predicatesForID.length ? predicatesForID
      .map(predicate => `POKEMON_ADMISSION_PREDICATE_${predicate}`).join(' | ') : '0';
    lines.push(`    {${JSON.stringify(id)}, ${tagExpression}, ${predicateExpression}},`);
  }
  lines.push('};', '');
}
lines.push('static const PokemonAdmissionSpeciesMetadata species_metadata[] = {');
for (const metadata of speciesMetadata) {
  lines.push(`    {${JSON.stringify(metadata.name)}, ${metadata.baseSpeciesID}},`);
}
lines.push('};', '');
lines.push('static const PokemonAcquisitionSpecies acquisition_species[] = {');
for (const row of acquisitionSpecies) {
  lines.push(`    {${row.firstMoveRow}, ${row.moveRowCount}, ${row.eventOnlyOffset}, ` +
    `${row.parentSpeciesID}, ${row.eggMask}, {${row.abilityIDs.join(', ')}}, ` +
    `${row.evolutionLevel}, ${row.fixedGender}, ` +
    `${row.canHatch}, ${row.eventOnlyCount}},`);
}
lines.push('};', '', 'static const PokemonAcquisitionMoveRow acquisition_move_rows[] = {');
for (const row of acquisitionMoveRows) {
  lines.push(`    {${row.moveID}, ${row.levelOffset}, ${row.eventOffset}, ${row.flags}, ` +
    `${row.levelCount}, ${row.eventCount}},`);
}
lines.push('};', '', 'static const uint16_t acquisition_move_source_ids[] = {');
for (let index = 0; index < moveSourceIDs.length; index += 16) {
  lines.push(`    ${moveSourceIDs.slice(index, index + 16).join(', ')},`);
}
lines.push('};', '', 'static const uint8_t acquisition_move_sketchable[] = {');
for (let index = 0; index < moveSketchable.length; index += 24) {
  lines.push(`    ${moveSketchable.slice(index, index + 24).join(', ')},`);
}
lines.push('};', '', 'static const char *const acquisition_nature_ids[] = {');
for (const id of natureIDs) lines.push(`    ${JSON.stringify(id)},`);
lines.push('};', '', 'static const char *const acquisition_hidden_power_type_ids[] = {');
for (const id of hiddenPowerTypeIDs) lines.push(`    ${JSON.stringify(id)},`);
lines.push('};', '', 'static const uint8_t acquisition_hidden_power_ivs[][POKEMON_ADMISSION_STAT_COUNT] = {');
for (const values of hiddenPowerIVs) lines.push(`    {${values.join(', ')}},`);
lines.push('};', '', 'static const uint8_t acquisition_move_hidden_power_type[] = {');
for (let index = 0; index < moveHiddenPowerType.length; index += 24) {
  lines.push(`    ${moveHiddenPowerType.slice(index, index + 24).join(', ')},`);
}
lines.push('};', '', 'static const uint8_t acquisition_levels[] = {');
for (let index = 0; index < acquisitionLevels.length; index += 24) {
  lines.push(`    ${acquisitionLevels.slice(index, index + 24).join(', ')},`);
}
lines.push('};', '', 'static const uint16_t acquisition_event_refs[] = {');
for (let index = 0; index < acquisitionEventRefs.length; index += 16) {
  lines.push(`    ${acquisitionEventRefs.slice(index, index + 16).join(', ')},`);
}
lines.push('};', '', 'static const PokemonAcquisitionEvent acquisition_events[] = {');
for (const event of acquisitionEvents) {
  const moves = [...event.moves]; while (moves.length < 4) moves.push(0);
  const gender = event.gender === 'M' ? 1 : event.gender === 'F' ? 2 : 0;
  const flags = (event.shiny ? 1 : 0) | (event.emeraldEventEgg ? 2 : 0) |
    (event.shinyOptional ? 4 : 0);
  lines.push(`    {${event.speciesID}, ${event.abilityID}, ${event.localIndex}, ${event.level}, ${gender}, ${flags}, ` +
    `${event.abilitySlot}, ${JSON.stringify(event.nature)}, ` +
    `{${event.ivs.join(', ')}}, ` +
    `{${moves.join(', ')}}, ${event.moves.length}},`);
}
lines.push('};', '', 'static const uint16_t acquisition_event_only_refs[] = {');
for (let index = 0; index < acquisitionEventOnlyRefs.length; index += 16) {
  lines.push(`    ${acquisitionEventOnlyRefs.slice(index, index + 16).join(', ')},`);
}
lines.push('};', '', 'static const PokemonAcquisitionData acquisition = {',
  `    .plugin_fingerprint = ${cFingerprint},`,
  '    .species = acquisition_species,',
  '    .species_count = POKEMON_GEN3_ADMISSION_SPECIES_COUNT,',
  '    .move_rows = acquisition_move_rows,',
  '    .move_row_count = POKEMON_GEN3_ACQUISITION_MOVE_ROW_COUNT,',
  '    .move_source_ids = acquisition_move_source_ids,',
  '    .move_source_id_count = POKEMON_GEN3_ADMISSION_MOVE_COUNT,',
  '    .move_sketchable = acquisition_move_sketchable,',
  '    .move_sketchable_count = POKEMON_GEN3_ADMISSION_MOVE_COUNT,',
  `    .sketch_move_id = ${universe.move.indexOf('sketch') + 1},`,
  `    .hidden_power_move_id = ${universe.move.indexOf('hiddenpower') + 1},`,
  '    .levels = acquisition_levels,',
  '    .level_count = POKEMON_GEN3_ACQUISITION_LEVEL_COUNT,',
  '    .event_refs = acquisition_event_refs,',
  '    .event_ref_count = POKEMON_GEN3_ACQUISITION_EVENT_REF_COUNT,',
  '    .events = acquisition_events,',
  '    .event_count = POKEMON_GEN3_ACQUISITION_EVENT_COUNT,',
  '    .event_only_refs = acquisition_event_only_refs,',
  '    .event_only_ref_count = POKEMON_GEN3_ACQUISITION_EVENT_ONLY_REF_COUNT,',
  '    .nature_ids = acquisition_nature_ids,',
  `    .nature_count = ${natureIDs.length},`,
  '    .hidden_power_type_ids = acquisition_hidden_power_type_ids,',
  '    .hidden_power_ivs = acquisition_hidden_power_ivs,',
  `    .hidden_power_type_count = ${hiddenPowerTypeIDs.length},`,
  '    .move_hidden_power_type = acquisition_move_hidden_power_type,',
  `    .max_lineage_depth = ${acquisitionData.maxLineageDepth},`,
  '    .max_sources_per_move = POKEMON_GEN3_ACQUISITION_MAX_SOURCES_PER_MOVE,',
  `    .ditto_group_mask = ${1 << eggGroupIndex.get('Ditto')},`,
  `    .undiscovered_group_mask = ${1 << eggGroupIndex.get('Undiscovered')},`,
  `    .breeding_group_mask = ${(1 << eggGroups.length) - 1 - (1 << eggGroupIndex.get('Ditto')) - (1 << eggGroupIndex.get('Undiscovered'))},`,
  `    .unrestricted_egg_group_mask = ${1 << eggGroupIndex.get('Field')},`,
  '};', '');
lines.push('static const uint16_t species_ability_offsets[] = {');
for (let index = 0; index < speciesAbilityOffsets.length; index += 16) {
  lines.push(`    ${speciesAbilityOffsets.slice(index, index + 16).join(', ')},`);
}
lines.push('};', '', 'static const uint16_t species_ability_members[] = {');
for (let index = 0; index < speciesAbilityMembers.length; index += 16) {
  lines.push(`    ${speciesAbilityMembers.slice(index, index + 16).join(', ')},`);
}
lines.push('};', '', 'static const PokemonAdmissionAllowedRelation allowed_relations[] = {',
  '    {POKEMON_ADMISSION_SPECIES, POKEMON_ADMISSION_ABILITY,',
  '        species_ability_offsets, POKEMON_GEN3_ADMISSION_SPECIES_COUNT + 1,',
  '        species_ability_members, POKEMON_GEN3_ADMISSION_SPECIES_ABILITY_PAIR_COUNT,',
  '        "speciesabilities"},',
  '};', '');
lines.push('static const PokemonAdmissionGuardedSpeciesRewrite species_rewrites[] = {');
for (const rewrite of speciesRewriteRules[0].rewrites) {
  lines.push(`    {${rewrite.inputSpeciesID}, ${rewrite.outputSpeciesID}, ` +
    `${rewrite.requiredAbilityID}},`);
}
lines.push('};', '');
lines.push('static const PokemonAdmissionRule admission_rules[] = {');
for (const [kind, id, sourceRuleID] of bans) {
  const index = universe[kind].indexOf(id);
  const disposition = index < 0 ? 'POKEMON_ADMISSION_OPERAND_STATICALLY_UNMATCHABLE' : 'POKEMON_ADMISSION_OPERAND_MATCHABLE';
  lines.push('    {POKEMON_ADMISSION_ATOMIC_BAN, ' +
    `POKEMON_ADMISSION_SCOPE_SET, ${JSON.stringify(sourceRuleID)}, {.atomic_ban = {` +
    `POKEMON_ADMISSION_${token(kind)}, ${index < 0 ? 0 : index + 1}, ${JSON.stringify(id)}, ${disposition}}}},`);
}
for (const tagBan of tagBans) {
  const mask = tagBan.kinds.map(kind => `(UINT8_C(1) << POKEMON_ADMISSION_${token(kind)})`).join(' | ');
  lines.push('    {POKEMON_ADMISSION_TAG_BAN, ' +
    `POKEMON_ADMISSION_SCOPE_SET, ${JSON.stringify(tagBan.sourceRuleID)}, {.tag_ban = {` +
    `POKEMON_ADMISSION_TAG_${tagBan.tag}, ${mask}, ${JSON.stringify(tagBan.id)}}}},`);
}
function emitAllOfBan(allOfBan) {
  const requirements = allOfBan.requirements.map(requirement => {
    const mask = requirement.kinds
      .map(kind => `(UINT8_C(1) << POKEMON_ADMISSION_${token(kind)})`).join(' | ');
    return `{POKEMON_ADMISSION_PREDICATE_${requirement.predicate}, ${mask}}`;
  });
  while (requirements.length < 2) requirements.push('{0, 0}');
  lines.push('    {POKEMON_ADMISSION_ALL_OF_BAN, ' +
    `POKEMON_ADMISSION_SCOPE_${allOfBan.scope}, ${JSON.stringify(allOfBan.sourceRuleID)}, {.all_of_ban = {{` +
    `${requirements.join(', ')}}, ${allOfBan.requirements.length}, ${JSON.stringify(allOfBan.id)}}}},`);
}
for (const allOfBan of allOfBans.filter(ban => ban.scope === 'SET')) emitAllOfBan(allOfBan);
for (const ban of anchoredCardinalityBans) {
  const requirement = value => {
    const mask = value.kinds
      .map(kind => `(UINT8_C(1) << POKEMON_ADMISSION_${token(kind)})`).join(' | ');
    return `{POKEMON_ADMISSION_PREDICATE_${value.predicate}, ${mask}}`;
  };
  lines.push('    {POKEMON_ADMISSION_ANCHORED_CARDINALITY_BAN, ' +
    `POKEMON_ADMISSION_SCOPE_${ban.scope}, ${JSON.stringify(ban.sourceRuleID)}, ` +
    `{.anchored_cardinality_ban = {${requirement(ban.anchor)}, ${requirement(ban.counted)}, ` +
    `${ban.maxSourcesPerSet}, ${ban.maxMatchingSets}, ${JSON.stringify(ban.id)}}}},`);
}
for (const allOfBan of allOfBans.filter(ban => ban.scope === 'TEAM')) emitAllOfBan(allOfBan);
for (const rule of statVectorRules) {
  lines.push('    {POKEMON_ADMISSION_STAT_VECTOR_RULE, ' +
    `POKEMON_ADMISSION_SCOPE_${rule.scope}, ${JSON.stringify(rule.sourceRuleID)}, ` +
    `{.stat_vector_rule = {${rule.componentMin}, ${rule.componentMax}, ` +
    `${rule.expectedTotalLimit}, ${rule.rejectZeroAboveLevel}, ${JSON.stringify(rule.id)}}}},`);
}
for (const rule of speciesRewriteRules) {
  lines.push('    {POKEMON_ADMISSION_SPECIES_REWRITE_RULE, ' +
    `POKEMON_ADMISSION_SCOPE_${rule.scope}, ${JSON.stringify(rule.sourceRuleID)}, ` +
    `{.species_rewrite_rule = {species_rewrites, ` +
    `POKEMON_GEN3_ADMISSION_SPECIES_REWRITE_COUNT, ${JSON.stringify(rule.id)}}}},`);
}
for (const rule of allowedRelationRules) {
  lines.push('    {POKEMON_ADMISSION_ALLOWED_RELATION_RULE, ' +
    `POKEMON_ADMISSION_SCOPE_${rule.scope}, ${JSON.stringify(rule.sourceRuleID)}, ` +
    `{.allowed_relation_rule = {${rule.relationID}}}},`);
}
for (const rule of nicknameRules) {
  lines.push('    {POKEMON_ADMISSION_NICKNAME_CLAUSE_RULE, ' +
    `POKEMON_ADMISSION_SCOPE_${rule.scope}, ${JSON.stringify(rule.sourceRuleID)}, {0}},`);
}
for (const rule of obtainableMoveRules) {
  lines.push('    {POKEMON_ADMISSION_OBTAINABLE_MOVES_RULE, ' +
    `POKEMON_ADMISSION_SCOPE_${rule.scope}, ${JSON.stringify(rule.sourceRuleID)}, {0}},`);
}
for (const rule of setFieldRules) {
  lines.push('    {POKEMON_ADMISSION_SET_FIELDS_RULE, ' +
    `POKEMON_ADMISSION_SCOPE_${rule.scope}, ${JSON.stringify(rule.sourceRuleID)}, {0}},`);
}
for (const rule of uniqueMoveRules) {
  lines.push('    {POKEMON_ADMISSION_UNIQUE_MOVES_RULE, ' +
    `POKEMON_ADMISSION_SCOPE_${rule.scope}, ${JSON.stringify(rule.sourceRuleID)}, {0}},`);
}
lines.push('};', '',
  'static const PokemonAdmissionUniverse universe = {',
  `    .plugin_fingerprint = ${cFingerprint},`,
  '    .identities = {',
  '        [POKEMON_ADMISSION_SPECIES] = {species_identities, POKEMON_GEN3_ADMISSION_SPECIES_COUNT},',
  '        [POKEMON_ADMISSION_MOVE] = {move_identities, POKEMON_GEN3_ADMISSION_MOVE_COUNT},',
  '        [POKEMON_ADMISSION_ABILITY] = {ability_identities, POKEMON_GEN3_ADMISSION_ABILITY_COUNT},',
  '        [POKEMON_ADMISSION_ITEM] = {item_identities, POKEMON_GEN3_ADMISSION_ITEM_COUNT},',
  '    },',
  '    .species_metadata = species_metadata,',
  '    .acquisition = &acquisition,',
  '    .relations = allowed_relations,',
  '    .relation_count = POKEMON_GEN3_ADMISSION_ALLOWED_RELATION_COUNT,',
  '};', '',
  'static const PokemonAdmissionProgram program = {',
  `    .plugin_fingerprint = ${cFingerprint},`,
  '    .rules = admission_rules,',
  '    .rule_count = POKEMON_GEN3_ADMISSION_RULE_COUNT,',
  '};', '',
  'static const PokemonAdmissionFormatPolicy base_format_policy = {',
  '    .format_id = "gen3ou",',
  '    .level_up_policy = POKEMON_ACQUISITION_LEVEL_UP_STANDARD,',
  '    .pomeg_minimum_level = 0,',
  '};', '',
  'static const PokemonAdmissionFormatPolicy pomeg_format_policy = {',
  '    .format_id = "gen3oupomeg",',
  '    .level_up_policy = POKEMON_ACQUISITION_LEVEL_UP_GEN3_POMEG,',
  '    .pomeg_minimum_level = 5,',
  '};', '',
  'const PokemonAdmissionBundle POKEMON_GEN3_OU_ADMISSION = {',
  `    .plugin_fingerprint = ${cFingerprint},`,
  '    .runtime_plugin_fingerprint = POKEMON_GEN3_PLUGIN_FINGERPRINT,',
  '    .abi_version = POKEMON_ADMISSION_ABI_VERSION,',
  '    .generation = 3,',
  '    .format_id = "gen3ou",',
  `    .oracle_revision = "${REVISION}",`,
  '    .universe = &universe,',
  '    .program = &program,',
  '    .format_policy = &base_format_policy,',
  '};', '',
  'const PokemonAdmissionBundle POKEMON_GEN3_OU_POMEG_ADMISSION = {',
  `    .plugin_fingerprint = ${cFingerprint},`,
  '    .runtime_plugin_fingerprint = POKEMON_GEN3_PLUGIN_FINGERPRINT,',
  '    .abi_version = POKEMON_ADMISSION_ABI_VERSION,',
  '    .generation = 3,',
  '    .format_id = "gen3oupomeg",',
  `    .oracle_revision = "${REVISION}",`,
  '    .universe = &universe,',
  '    .program = &program,',
  '    .format_policy = &pomeg_format_policy,',
  '};', '');
process.stdout.write(lines.join('\n'));
