#!/usr/bin/env node
'use strict';

// Persistent JSON-lines adapter around Pokemon Showdown's team APIs.
// Showdown is deliberately an injected dependency: this repository does not
// duplicate its parser, defaults, or evolving format legality rules.

const readline = require('readline');
const fs = require('fs');
const path = require('path');

const showdownDir = process.argv[2];
if (!showdownDir) {
  throw new Error('usage: showdown_teams.js POKEMON_SHOWDOWN_DIR');
}

const {Battle, Teams, TeamValidator} = require(path.resolve(showdownDir));
const validator = TeamValidator.get('gen3ou');
const battle = new Battle({formatid: 'gen3ou'});
const idsPath = path.resolve(__dirname, '..', 'data', 'gen3_ids.json');
const generatedIDs = JSON.parse(fs.readFileSync(idsPath, 'utf8'));

if (generatedIDs.schema !== 1 || generatedIDs.showdown_gen !== 3) {
  throw new Error(`unsupported generated ID schema: ${idsPath}`);
}

function requireNumericID(effect, kind, name) {
  if (!effect.exists || effect.num <= 0) {
    throw new Error(`gen3 Dex has no numeric ${kind} ID for: ${name}`);
  }
  return effect.num;
}

function requireSpeciesID(species) {
  const id = generatedIDs.species[species.id];
  if (!Number.isSafeInteger(id) || id <= 0) {
    throw new Error(`generated Gen 3 data has no species ID for: ${species.name}`);
  }
  return id;
}

function buildPokemon(set) {
  const dex = validator.dex;
  const species = dex.species.get(set.species);
  const ability = dex.abilities.get(set.ability);
  const item = set.item ? dex.items.get(set.item) : null;
  const moves = set.moves.map(name => dex.moves.get(name));
  const stats = battle.spreadModify(species.baseStats, set);
  if (species.maxHP) stats.hp = species.maxHP;

  return {
    species_id: requireSpeciesID(species),
    item_id: item ? requireNumericID(item, 'item', set.item) : 0,
    ability_id: requireNumericID(ability, 'ability', set.ability),
    move_ids: moves.map(move => requireNumericID(move, 'move', move.name)),
    move_max_pp: moves.map(move => battle.calculatePP(move, 3)),
    level: set.level,
    // Empty means Showdown will draw M/F during battle initialization. It is
    // intentionally not replaced with a fake deterministic default here.
    gender: set.gender || species.gender || '',
    happiness: typeof set.happiness === 'number' ?
      battle.clampIntRange(set.happiness, 0, 255) : 255,
    shiny: Boolean(set.shiny),
    stats,
  };
}

function buildBattleTeam(team) {
  return {pokemon: team.map(buildPokemon)};
}

function unresolvedGenderProblems(team) {
  const problems = [];
  for (const set of team) {
    const species = validator.dex.species.get(set.species);
    if (!set.gender && !species.gender) {
      problems.push(
        `${species.name} must specify M or F so Showdown and C do not ` +
        `consume different gender RNG during initialization.`
      );
    }
  }
  return problems;
}

function validate(message) {
  if (message.format !== 'gen3ou') {
    throw new Error(`unsupported format: ${message.format}`);
  }
  if (typeof message.team !== 'string') {
    throw new Error('team must be an export, packed team, or JSON string');
  }

  const team = Teams.import(message.team);
  if (!team) return {ok: false, problems: ['Could not parse team.']};
  if (team.length !== 6) {
    const problem = `A complete gen3ou team must contain exactly 6 Pokemon (found ${team.length}).`;
    return {ok: false, problems: [problem]};
  }

  const problems = validator.validateTeam(team);
  if (problems) return {ok: false, problems};
  const genderProblems = unresolvedGenderProblems(team);
  if (genderProblems.length) return {ok: false, problems: genderProblems};
  return {
    ok: true,
    packed: Teams.pack(team),
    exported: Teams.export(team),
    team,
    battle_team: buildBattleTeam(team),
  };
}

const lines = readline.createInterface({input: process.stdin, crlfDelay: Infinity});
lines.on('line', line => {
  if (!line.trim()) return;
  let message;
  try {
    message = JSON.parse(line);
    const result = validate(message);
    process.stdout.write(`${JSON.stringify({id: message.id, ...result})}\n`);
  } catch (error) {
    process.stdout.write(`${JSON.stringify({
      id: message && message.id,
      ok: false,
      error: error instanceof Error ? error.message : String(error),
    })}\n`);
  }
});
