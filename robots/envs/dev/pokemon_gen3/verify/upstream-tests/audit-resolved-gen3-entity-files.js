'use strict';

const childProcess = require('child_process');
const fs = require('fs');
const path = require('path');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const oracle = path.resolve(process.argv[2] || '');
const descriptorFile = path.resolve(process.argv[3] || '');
const output = path.resolve(process.argv[4] || __dirname);
if (!process.argv[2] || !process.argv[3]) {
  throw new Error('usage: node audit-resolved-gen3-entity-files.js SHOWDOWN_DIR DESCRIPTOR_MAP [OUTPUT_DIR]');
}
const revision = childProcess.execFileSync('git', ['rev-parse', 'HEAD'], {cwd: oracle, encoding: 'utf8'}).trim();
if (revision !== REVISION) throw new Error(`oracle revision ${revision}; expected ${REVISION}`);
const {Dex} = require(path.join(oracle, 'dist/sim/dex'));
const ts = require(path.join(oracle, 'node_modules/typescript'));
const descriptors = JSON.parse(fs.readFileSync(descriptorFile, 'utf8'));
if (descriptors.oracle_revision !== REVISION) throw new Error('descriptor map revision mismatch');

// Submitted-set validation is not the runtime reachability boundary. Assist,
// Sheer Cold, and Struggle are now present in the runtime-closed move
// inventory; only Shadow Tag remains absent because no legal initial ability
// or source-preserving copy operation can originate it.
const expected = new Set(['ability:shadowtag']);
const kinds = [
  ['move', 'moves', Dex.forGen(3).moves.all()],
  ['ability', 'abilities', Dex.forGen(3).abilities.all()],
  ['item', 'items', Dex.forGen(3).items.all()],
];

function callKind(node) {
  if (!ts.isCallExpression(node)) return '';
  if (ts.isIdentifier(node.expression)) return node.expression.text;
  if (ts.isPropertyAccessExpression(node.expression) && ts.isIdentifier(node.expression.expression)) return node.expression.expression.text;
  return '';
}

function extract(file, relative, kind, id) {
  const text = fs.readFileSync(file, 'utf8');
  const source = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, ts.ScriptKind.JS);
  const records = [];
  function visit(node, stack) {
    const call = callKind(node);
    const argument = node.arguments?.[0];
    const staticName = argument && ts.isStringLiteralLike(argument) ? argument.text : argument?.getText(source).replace(/\s+/g, ' ');
    if (call === 'describe') {
      const callback = node.arguments[1];
      if (callback && (ts.isArrowFunction(callback) || ts.isFunctionExpression(callback))) {
        ts.forEachChild(callback.body, child => visit(child, [...stack, staticName]));
        return;
      }
    }
    if (call === 'it' || call === 'test') {
      records.push({
        pinned_revision: REVISION,
        source_file: relative,
        source_line: source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1,
        full_test_name: [...stack, staticName].join(' > '),
        descriptor_kind: kind,
        descriptor_id: id,
        census_status: 'missing_because_descriptor_absent',
      });
      return;
    }
    ts.forEachChild(node, child => visit(child, stack));
  }
  visit(source, []);
  return records;
}

function assertionMap(record) {
  const common = {
    mechanics: [], semantic_boundaries: [],
    ou_reachability: '', ou_reachability_evidence: '',
    native_unit_tests: [], differential_cases: [], invariant_ids: [], randomized_scenario_ids: [],
    evidence_scope: 'none', coverage: '', needs_new_case: false, proposed_case: '',
    showdown_semantic_sources: [],
  };
  if (record.descriptor_id === 'shadowtag') return {...common,
    mechanics: record.source_line === 23 ? ['trapping', 'move-driven-switching'] : ['trapping', 'legal-choice-restriction', 'trap-immunity'],
    semantic_boundaries: ['request', 'choice', 'event-handlers', 'switch-lifecycle', 'canonical-state'],
    ou_reachability: 'format-unreachable',
    ou_reachability_evidence: 'Pinned [Gen 3] OU bans Uber; pinned Gen 3 formats data marks Wobbuffet and Wynaut Uber. They are the only standard Gen 3 Shadow Tag origins. Trace, Role Play, Skill Swap, and Transform only copy or transfer an already-present ability, so closure from legal initial abilities cannot create Shadow Tag.',
    evidence_scope: 'source-proven-reachability-closure', coverage: 'not-applicable-to-legal-gen3ou-runtime',
    needs_new_case: false,
    proposed_case: '',
    showdown_semantic_sources: ['data/mods/gen3/abilities.ts#shadowtag', 'data/mods/gen3/abilities.ts#trace', 'data/moves.ts#roleplay', 'data/moves.ts#skillswap', 'sim/pokemon.ts#transformInto', 'data/mods/gen3/formats-data.ts#wobbuffet', 'data/mods/gen3/formats-data.ts#wynaut', 'config/formats.ts#[Gen 3] OU'],
  };
  throw new Error(`missing assertion map for ${record.source_file}:${record.source_line}`);
}

const gaps = [];
for (const [kind, directory, resolved] of kinds) {
  const inventory = new Set(descriptors.inventories.find(entry => entry.kind === kind).entries.map(entry => entry.id));
  for (const entity of resolved.filter(entry => !entry.isNonstandard)) {
    const relative = `test/sim/${directory}/${entity.id}.js`;
    const file = path.join(oracle, relative);
    if (!inventory.has(entity.id) && fs.existsSync(file)) gaps.push({kind, id: entity.id, relative, file});
  }
}
const identities = new Set(gaps.map(gap => `${gap.kind}:${gap.id}`));
const missingExpected = [...expected].filter(identity => !identities.has(identity));
const unexpected = [...identities].filter(identity => !expected.has(identity));
if (missingExpected.length || unexpected.length) {
  throw new Error(`resolved gap set changed; missing=${missingExpected.join(',') || 'none'} unexpected=${unexpected.join(',') || 'none'}`);
}
const records = gaps.flatMap(gap => extract(gap.file, gap.relative, gap.kind, gap.id))
  .map(record => ({...record, ...assertionMap(record)}));
for (const record of records) {
  for (const field of ['mechanics', 'semantic_boundaries', 'ou_reachability', 'ou_reachability_evidence',
    'native_unit_tests', 'differential_cases', 'invariant_ids', 'randomized_scenario_ids', 'evidence_scope',
    'coverage', 'needs_new_case', 'proposed_case', 'showdown_semantic_sources']) {
    if (!(field in record)) throw new Error(`${record.source_file}:${record.source_line} missing ${field}`);
  }
  if (!record.mechanics.length || !record.semantic_boundaries.length || !record.showdown_semantic_sources.length) {
    throw new Error(`${record.source_file}:${record.source_line} has an empty semantic mapping`);
  }
  for (const field of ['mechanics', 'semantic_boundaries', 'native_unit_tests', 'differential_cases',
    'invariant_ids', 'randomized_scenario_ids', 'showdown_semantic_sources']) {
    if (!Array.isArray(record[field])) throw new Error(`${record.source_file}:${record.source_line} ${field} is not an array`);
  }
  if (typeof record.needs_new_case !== 'boolean') throw new Error(`${record.source_file}:${record.source_line} needs_new_case is not boolean`);
  if (record.needs_new_case && !record.proposed_case) throw new Error(`${record.source_file}:${record.source_line} lacks a proposed case`);
}
const result = {
  schema: 'pokemon-gen3ou-resolved-entity-test-gaps-v2',
  pinned_revision: REVISION,
  scope: 'Standard entities in pinned Dex.forGen(3) with an upstream entity test file but no frozen descriptor-map entry.',
  entity_count: gaps.length,
  test_count: records.length,
  records,
};
fs.writeFileSync(path.join(output, 'resolved-gen3-entity-test-gaps.json'), `${JSON.stringify(result, null, 2)}\n`);
console.log(`found ${gaps.length} omitted tested Gen 3 entities and ${records.length} omitted tests`);
