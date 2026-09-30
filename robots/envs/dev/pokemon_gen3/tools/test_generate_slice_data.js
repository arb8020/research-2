#!/usr/bin/env node
'use strict';

const assert = require('assert');
const childProcess = require('child_process');
const fs = require('fs');
const path = require('path');

const showdownDir = process.argv[2];
const nativeDir = process.argv[3] || path.resolve(__dirname, '../native');
if (!showdownDir) {
  throw new Error('usage: test_generate_slice_data.js POKEMON_SHOWDOWN_DIR [NATIVE_DIR]');
}

function generate(kind) {
  return childProcess.execFileSync(
    process.execPath,
    [path.resolve(__dirname, 'generate_slice_data.js'), showdownDir, kind],
    {encoding: 'utf8'}
  );
}

for (const kind of ['header', 'source', 'id-map']) {
  const first = generate(kind);
  const second = generate(kind);
  assert.strictEqual(first, second, `${kind} generation is nondeterministic`);
  const filename = kind === 'header' ? 'gen3_slice_data.h' :
    kind === 'source' ? 'gen3_slice_data.c' : '../verify/cases/native-id-map.json';
  assert.strictEqual(
    first,
    fs.readFileSync(path.join(nativeDir, filename), 'utf8'),
    `${filename} is stale`
  );
}

const source = generate('source');
for (const marker of [
  'static const PokemonSpeciesIdentity SPECIES_CATALOG[]',
  'static const PokemonMoveIdentity MOVE_CATALOG[]',
  'static const PokemonNamedIdentity ABILITY_CATALOG[]',
  'static const PokemonNamedIdentity ITEM_CATALOG[]',
  'static const PokemonConditionIdentity CONDITION_CATALOG[]',
  'static const PokemonWeatherPolicy WEATHER_POLICIES[]',
  'static const PokemonStatusResidualPolicy STATUS_RESIDUAL_POLICIES[]',
  'static const PokemonHandlerOp HANDLER_PROGRAMS[]',
  'static const PokemonEventSpec EVENT_SPECS[]',
  'static const PokemonFormatRule GEN3_OU_RULES[]',
  'const PokemonFormatManifest POKEMON_GEN3_OU_FORMAT',
  '.species_catalog_count = sizeof(SPECIES_CATALOG)',
  '.move_catalog_count = sizeof(MOVE_CATALOG)',
  '.condition_catalog_count = sizeof(CONDITION_CATALOG)',
  '.weather_policy_count = sizeof(WEATHER_POLICIES)',
  '.status_residual_policy_count = sizeof(STATUS_RESIDUAL_POLICIES)',
  '.handler_program_count = sizeof(HANDLER_PROGRAMS)',
  '.event_spec_count = sizeof(EVENT_SPECS)',
]) {
  assert(source.includes(marker), `missing generated catalog marker: ${marker}`);
}

/* Showdown's boolean `true` accuracy is semantically different from numeric
 * 100: it skips accuracy/evasion staging and the ordinary accuracy draw. */
for (const alwaysMove of ['aerialace', 'feintattack', 'swift']) {
  const pattern = new RegExp(
    `"${alwaysMove}", "[^"]+",[^\\n]+\\{POKEMON_ACCURACY_ALWAYS, 0\\}`
  );
  assert(pattern.test(source), `${alwaysMove} lost boolean accuracy`);
}
/* Gen 3 deliberately overrides these inherited always-hit descriptors. */
for (const percentMove of ['lockon', 'mindreader']) {
  const pattern = new RegExp(
    `"${percentMove}", "[^"]+",[^\\n]+\\{POKEMON_ACCURACY_PERCENT, 100\\}`
  );
  assert(pattern.test(source), `${percentMove} lost Gen 3 numeric accuracy`);
}

process.stdout.write('Gen 3 catalog generation is deterministic and current\n');
