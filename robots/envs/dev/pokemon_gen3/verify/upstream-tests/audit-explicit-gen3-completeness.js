'use strict';

const childProcess = require('child_process');
const fs = require('fs');
const path = require('path');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const oracle = path.resolve(process.argv[2] || '');
const output = path.resolve(process.argv[3] || __dirname);
if (!process.argv[2]) throw new Error('usage: node audit-explicit-gen3-completeness.js SHOWDOWN_DIR [OUTPUT_DIR]');
const revision = childProcess.execFileSync('git', ['rev-parse', 'HEAD'], {cwd: oracle, encoding: 'utf8'}).trim();
if (revision !== REVISION) throw new Error(`oracle revision ${revision}; expected ${REVISION}`);
const ts = require(path.join(oracle, 'node_modules/typescript'));

function walk(directory) {
  return fs.readdirSync(directory, {withFileTypes: true}).flatMap(entry => {
    const file = path.join(directory, entry.name);
    return entry.isDirectory() ? walk(file) : entry.name.endsWith('.js') ? [file] : [];
  });
}

function callKind(node) {
  if (!ts.isCallExpression(node)) return '';
  if (ts.isIdentifier(node.expression)) return node.expression.text;
  if (ts.isPropertyAccessExpression(node.expression) && ts.isIdentifier(node.expression.expression)) {
    return node.expression.expression.text;
  }
  return '';
}

function name(node, source) {
  const value = node.arguments[0];
  if (ts.isStringLiteralLike(value)) return value.text;
  return value ? value.getText(source).replace(/\s+/g, ' ') : '<dynamic name>';
}

function explicitGen3(text) {
  return /common\.gen\(3\)|['"]gen3(?:ou|ubers|1v1)?(?:@@@[^'"]*)?['"]|\bGen(?:eration)?\s*3\b/i.test(text);
}

function extract(file) {
  const relative = path.relative(oracle, file);
  const text = fs.readFileSync(file, 'utf8');
  const source = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, ts.ScriptKind.JS);
  const records = [];
  function visit(node, stack) {
    const kind = callKind(node);
    if (kind === 'describe') {
      const next = [...stack, name(node, source)];
      const callback = node.arguments[1];
      if (callback && (ts.isArrowFunction(callback) || ts.isFunctionExpression(callback))) {
        ts.forEachChild(callback.body, child => visit(child, next));
        return;
      }
    }
    if (kind === 'it' || kind === 'test') {
      const testName = name(node, source);
      const body = node.arguments[1]?.getText(source) || '';
      const fullName = [...stack, testName].join(' > ');
      if (explicitGen3(`${fullName}\n${body}`)) {
        records.push({
          source_file: relative,
          source_line: source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1,
          full_test_name: fullName,
        });
      }
      return;
    }
    ts.forEachChild(node, child => visit(child, stack));
  }
  visit(source, []);
  return records;
}

const inherited = JSON.parse(fs.readFileSync(path.join(output, 'gen3ou-inherited-test-map.json'), 'utf8'));
const core = JSON.parse(fs.readFileSync(path.join(output, 'core-test-census.json'), 'utf8'));
const mapped = new Map();
for (const record of inherited.records) mapped.set(`${record.source_file}:${record.source_line}`, `inherited:${record.applicability}`);
for (const record of core.records) mapped.set(`${record.source_file}:${record.source_line}`, `core:${record.applicability}`);

const explicit = walk(path.join(oracle, 'test/sim')).sort().flatMap(extract);
const records = explicit.map(record => ({
  ...record,
  map_record: mapped.get(`${record.source_file}:${record.source_line}`) || '',
}));
const missing = records.filter(record => !record.map_record);
if (missing.length) {
  throw new Error(`explicit Gen 3 upstream tests missing from maps:\n${missing.map(record => `${record.source_file}:${record.source_line} ${record.full_test_name}`).join('\n')}`);
}

const result = {
  schema: 'pokemon-gen3ou-explicit-upstream-completeness-v1',
  pinned_revision: REVISION,
  scope: 'Every statically declared test under test/sim whose name, enclosing describe, or body explicitly selects or names Gen 3.',
  limitation: 'This proves structural inclusion of explicit Gen 3 tests. It does not adjudicate default-generation inherited assertions.',
  count: records.length,
  records,
};
fs.writeFileSync(path.join(output, 'explicit-gen3-completeness.json'), `${JSON.stringify(result, null, 2)}\n`);
console.log(`mapped ${records.length} explicit Gen 3 tests at ${REVISION}`);
