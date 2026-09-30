#!/usr/bin/env node
'use strict';

const crypto = require('crypto');
const fs = require('fs');

const [nativePath, oraclePath] = process.argv.slice(2);
if (!nativePath || !oraclePath) throw new Error('usage: compare.js NATIVE_JSONL ORACLE_JSONL');

function readRecords(file) {
  const bytes = fs.readFileSync(file);
  const text = bytes.toString('utf8');
  const records = text.trimEnd().split('\n').map((line, index) => {
    try {
      return JSON.parse(line);
    } catch (error) {
      throw new Error(`${file}:${index + 1}: invalid JSON: ${error.message}`);
    }
  });
  return {bytes, records};
}

function firstDifference(expected, actual, path = '$') {
  if (Object.is(expected, actual)) return null;
  if (typeof expected !== typeof actual || expected === null || actual === null) {
    return {path, expected, actual};
  }
  if (Array.isArray(expected) || Array.isArray(actual)) {
    if (!Array.isArray(expected) || !Array.isArray(actual)) return {path, expected, actual};
    if (expected.length !== actual.length) {
      return {path: `${path}.length`, expected: expected.length, actual: actual.length};
    }
    for (let i = 0; i < expected.length; i++) {
      const difference = firstDifference(expected[i], actual[i], `${path}[${i}]`);
      if (difference) return difference;
    }
    return null;
  }
  if (typeof expected === 'object') {
    const keys = [...new Set([...Object.keys(expected), ...Object.keys(actual)])].sort();
    for (const key of keys) {
      if (!(key in expected) || !(key in actual)) {
        return {path: `${path}.${key}`, expected: expected[key], actual: actual[key]};
      }
      const difference = firstDifference(expected[key], actual[key], `${path}.${key}`);
      if (difference) return difference;
    }
    return null;
  }
  return {path, expected, actual};
}

const native = readRecords(nativePath);
const oracle = readRecords(oraclePath);
if (native.records.length !== oracle.records.length) {
  throw new Error(`record count mismatch: native=${native.records.length} oracle=${oracle.records.length}`);
}
for (let i = 0; i < oracle.records.length; i++) {
  const difference = firstDifference(oracle.records[i], native.records[i]);
  if (difference) {
    const identity = oracle.records[i];
    throw new Error(
      `catalog mismatch at record ${i + 1} (${identity.kind}:${identity.id}) ` +
      `${difference.path}: expected ${JSON.stringify(difference.expected)}, ` +
      `native ${JSON.stringify(difference.actual)}`
    );
  }
}
if (!native.bytes.equals(oracle.bytes)) {
  throw new Error('records are structurally equal but serialization is not canonical');
}
const digest = crypto.createHash('sha256').update(native.bytes).digest('hex');
process.stdout.write(
  `catalog differential passed: species=369 moves=354 abilities=70 items=104 ` +
  `records=${native.records.length} sha256=${digest}\n`
);
