#!/usr/bin/env node
'use strict';

const childProcess = require('child_process');
const fs = require('fs');
const path = require('path');

const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const showdownDir = process.argv[2];
if (!showdownDir) {
  throw new Error('usage: generate-flash-fire-cases.js POKEMON_SHOWDOWN_DIR');
}
const actual = childProcess.execFileSync(
  'git', ['-C', showdownDir, 'rev-parse', 'HEAD'], {encoding: 'utf8'}).trim();
if (actual !== revision) throw new Error(`expected ${revision}, got ${actual}`);

const {Dex, TeamValidator, Teams} = require(path.resolve(showdownDir));
const dex = Dex.forGen(3);
const validator = new TeamValidator('gen3ou');
const outputDir = path.resolve(__dirname, 'derived');

function stats(species) {
  const b = species.baseStats;
  return [2 * b.hp + 141, 2 * b.atk + 36, 2 * b.def + 36,
    2 * b.spa + 36, 2 * b.spd + 36, 2 * b.spe + 36];
}

function member(speciesID, ability, moves, status = null) {
  const species = dex.species.get(speciesID);
  return {
    species: species.id,
    level: 100,
    gender: species.gender === 'N' ? 'N' : species.gender === 'F' ? 'F' : 'M',
    ability,
    item: '',
    moves,
    stats: stats(species),
    status,
  };
}

function source(team) {
  return team.map(pokemon => {
    const species = dex.species.get(pokemon.species);
    const sex = pokemon.gender === 'N' ? '' : ` (${pokemon.gender})`;
    return `${species.name}${sex}\nAbility: ${dex.abilities.get(pokemon.ability).name}\n` +
      'Level: 100\nEVs: 1 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe\n' +
      `Hardy Nature\n${pokemon.moves.map(id => `- ${dex.moves.get(id).name}`).join('\n')}\n`;
  }).join('\n');
}

function writeCase(id, left, right, choices, testName) {
  const teamFiles = [`${id}-p1.txt`, `${id}-p2.txt`];
  const teams = [left, right];
  for (let side = 0; side < teams.length; side++) {
    const teamSource = source(teams[side]);
    const problems = validator.validateTeam(Teams.import(teamSource));
    if (problems) {
      throw new Error(`${id} p${side + 1} is not legal Gen 3 OU: ${problems.join('; ')}`);
    }
    fs.writeFileSync(path.join(outputDir, teamFiles[side]), teamSource);
  }
  const battleCase = {
    schema: 'pokemon-native-differential-case-v1',
    id,
    provenance: {
      kind: 'showdown-derived',
      source_file: 'data/abilities.ts; data/mods/gen4/abilities.ts; data/mods/gen3/abilities.ts; data/mods/gen3/scripts.ts',
      test_name: testName,
      oracle_revision: revision,
    },
    format: 'gen3ou',
    seed: [701, 193, 43, 11],
    teams: teams.map((team, side) => ({
      source: teamFiles[side], normalized: team,
    })),
    source_choices: choices,
    choices,
    forced_outcomes: [],
    features: [
      'choice.move', 'condition.volatile', 'handler.try-hit',
      'hit.accuracy', 'prng.labeled', 'state.canonical',
    ],
    boundaries: [
      'request', 'choice', 'queue', 'handlers', 'immunity', 'state',
      'events', 'prng',
    ],
    limits: {max_boundaries: choices.length + 1, max_actions: choices.length * 2},
  };
  fs.writeFileSync(path.join(outputDir, `${id}.json`),
    `${JSON.stringify(battleCase, null, 2)}\n`);
}

writeCase('flash-fire-activation-repeat-boost',
  [member('charizard', 'blaze', ['flamethrower', 'growl'])],
  [member('ponyta', 'flashfire', ['growl', 'flamethrower'])],
  [['move 1', 'move 1'], ['move 2', 'move 2']],
  'First Fire hit installs Flash Fire, repeat activation does not duplicate it, and its condition boosts the holder\'s Fire damage');

writeCase('flash-fire-frozen-fallthrough',
  [member('charizard', 'blaze', ['flamethrower'])],
  [member('ponyta', 'flashfire', ['growl'], 'frz')],
  [['move 1', 'move 1']],
  'Pinned upstream regression: a frozen Gen 3 Flash Fire holder takes the Fire hit and thaws instead of activating');

writeCase('flash-fire-willowisp-fire-holder',
  [member('dusclops', 'pressure', ['willowisp'])],
  [member('ponyta', 'flashfire', ['growl'])],
  [['move 1', 'move 1']],
  'Gen 3 Will-O-Wisp exception leaves an already ineligible Fire target to the ordinary status-immunity path');

writeCase('flash-fire-protect-before-activation',
  [member('dusclops', 'pressure', ['firepunch'])],
  [member('ponyta', 'flashfire', ['protect', 'growl'])],
  [['move 1', 'move 1'], ['move 1', 'move 2']],
  'Protect cancels before Flash Fire discovery on turn one; the unprotected turn installs Flash Fire');

writeCase('flash-fire-substitute-activation',
  [member('dusclops', 'pressure', ['firepunch'])],
  [member('ponyta', 'flashfire', ['substitute'])],
  [['move 1', 'move 1']],
  'Damaging Fire activates Flash Fire before Substitute interception and leaves the substitute intact');

writeCase('flash-fire-switch-cleanup',
  [member('charizard', 'blaze', ['flamethrower', 'growl'])],
  [
    member('ponyta', 'flashfire', ['growl']),
    member('blissey', 'naturalcure', ['softboiled']),
  ],
  [['move 1', 'move 1'], ['move 2', 'switch 2']],
  'Switching the holder clears the no-copy Flash Fire volatile through ordinary owner lifecycle teardown');

console.log('generated 6 Flash Fire differential cases');
