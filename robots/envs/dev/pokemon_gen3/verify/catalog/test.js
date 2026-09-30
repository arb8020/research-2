#!/usr/bin/env node
'use strict';

const childProcess = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const root = path.resolve(__dirname, '../..');
const showdownDir = process.env.POKEMON_SHOWDOWN_DIR || process.argv[2];
if (!showdownDir) {
  throw new Error('set POKEMON_SHOWDOWN_DIR to the pinned Pokemon Showdown checkout');
}
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'gen3-catalog-diff-'));
try {
  const binary = path.join(temporary, 'native-catalog');
  const nativeOutput = path.join(temporary, 'native.jsonl');
  const oracleOutput = path.join(temporary, 'oracle.jsonl');
  childProcess.execFileSync(process.env.CC || 'cc', [
    '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-O2',
    '-I', path.join(root, 'native'), path.join(__dirname, 'native_catalog.c'),
    path.join(root, 'native/gen3_slice_data.c'), '-o', binary,
  ], {stdio: 'inherit'});
  const nativeBytes = childProcess.execFileSync(binary);
  const repeatedNativeBytes = childProcess.execFileSync(binary);
  if (!nativeBytes.equals(repeatedNativeBytes)) throw new Error('native catalog output is nondeterministic');
  const oracleBytes = childProcess.execFileSync(
    process.execPath, [path.join(__dirname, 'oracle.js'), showdownDir]
  );
  const repeatedOracleBytes = childProcess.execFileSync(
    process.execPath, [path.join(__dirname, 'oracle.js'), showdownDir]
  );
  if (!oracleBytes.equals(repeatedOracleBytes)) throw new Error('oracle catalog output is nondeterministic');
  fs.writeFileSync(nativeOutput, nativeBytes);
  fs.writeFileSync(oracleOutput, oracleBytes);
  childProcess.execFileSync(
    process.execPath, [path.join(__dirname, 'compare.js'), nativeOutput, oracleOutput],
    {stdio: 'inherit'}
  );

  const corruptedOutput = path.join(temporary, 'corrupted.jsonl');
  const corrupted = nativeBytes.toString('utf8').replace('"base_stats":[25,', '"base_stats":[26,');
  if (corrupted === nativeBytes.toString('utf8')) throw new Error('negative-test mutation did not apply');
  fs.writeFileSync(corruptedOutput, corrupted);
  const mismatch = childProcess.spawnSync(
    process.execPath, [path.join(__dirname, 'compare.js'), corruptedOutput, oracleOutput],
    {encoding: 'utf8'}
  );
  const diagnostic = `${mismatch.stdout || ''}${mismatch.stderr || ''}`;
  if (mismatch.status === 0 || !diagnostic.includes(
    'catalog mismatch at record 1 (species:abra) $.base_stats[0]'
  )) {
    throw new Error(`mismatch localization self-test failed:\n${diagnostic}`);
  }
} finally {
  fs.rmSync(temporary, {recursive: true, force: true});
}
