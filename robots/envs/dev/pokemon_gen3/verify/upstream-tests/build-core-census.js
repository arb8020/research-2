'use strict';

const fs = require('fs');
const path = require('path');
const childProcess = require('child_process');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const oracle = process.argv[2];
if (!oracle) throw new Error('usage: node build-core-census.js SHOWDOWN_DIR [OUTPUT_DIR]');
const ts = require(path.join(oracle, 'node_modules/typescript'));
const outputDir = process.argv[3] || __dirname;
const project = process.argv[4];
const actualRevision = childProcess.execFileSync('git', ['rev-parse', 'HEAD'], {cwd: oracle, encoding: 'utf8'}).trim();
if (actualRevision !== REVISION) {
  throw new Error(`oracle revision ${actualRevision}; expected ${REVISION}`);
}

const exactFiles = [
  'test/sim/choice-parser.js',
  'test/sim/data.js',
  'test/sim/decisions.js',
  'test/sim/dex.js',
  'test/sim/events.js',
];
const suiteDirs = ['test/sim/misc', 'test/sim/rulesets', 'test/sim/team-validator'];

function walk(dir) {
  return fs.readdirSync(dir, {withFileTypes: true}).flatMap(entry => {
    const file = path.join(dir, entry.name);
    return entry.isDirectory() ? walk(file) : entry.name.endsWith('.js') ? [file] : [];
  });
}

const files = [
  ...exactFiles.map(file => path.join(oracle, file)),
  ...suiteDirs.flatMap(dir => walk(path.join(oracle, dir))),
].sort();

function staticName(node, source) {
  if (!node) return null;
  if (ts.isStringLiteralLike(node)) return node.text;
  if (ts.isNoSubstitutionTemplateLiteral(node)) return node.text;
  return source.text.slice(node.pos, node.end).trim().replace(/\s+/g, ' ');
}

function callName(node) {
  if (!ts.isCallExpression(node)) return null;
  if (ts.isIdentifier(node.expression)) return node.expression.text;
  if (ts.isPropertyAccessExpression(node.expression)) {
    const left = node.expression.expression;
    if (ts.isIdentifier(left) && ['it', 'test', 'describe'].includes(left.text)) return left.text;
  }
  return null;
}

function extract(file) {
  const text = fs.readFileSync(file, 'utf8');
  const rel = path.relative(oracle, file);
  const source = ts.createSourceFile(rel, text, ts.ScriptTarget.Latest, true, ts.ScriptKind.JS);
  const out = [];

  function visit(node, describes) {
    const kind = callName(node);
    if (kind === 'describe') {
      const name = staticName(node.arguments[0], source);
      const callback = node.arguments[1];
      if (callback && (ts.isArrowFunction(callback) || ts.isFunctionExpression(callback))) {
        ts.forEachChild(callback.body, child => visit(child, [...describes, name]));
        return;
      }
    }
    if (kind === 'it' || kind === 'test') {
      const name = staticName(node.arguments[0], source);
      const callback = node.arguments[1];
      const body = callback ? text.slice(callback.pos, callback.end) : text.slice(node.pos, node.end);
      const line = source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1;
      out.push({source_file: rel, source_line: line, full_test_name: [...describes, name].join(' > '), source_body: body});
      return;
    }
    ts.forEachChild(node, child => visit(child, describes));
  }
  visit(source, []);
  return out;
}

function generations(body) {
  const gens = new Set();
  for (const match of body.matchAll(/(?:common\.gen\(|['"]gen)(\d)/gi)) gens.add(Number(match[1]));
  return [...gens].sort();
}

function classify(record) {
  const text = `${record.full_test_name}\n${record.source_body}`;
  const lower = text.toLowerCase();
  const gens = generations(text);
  const explicitGen3 = gens.includes(3) || /\bgen(?:eration)?\s*3\b/i.test(text);

  let applicability = 'requires-source-adjudication';
  let rationale = 'No explicit generation anchor; requires semantic review before claiming applicability or irrelevance.';
  if (explicitGen3) {
    applicability = record.source_file.includes('/team-validator/') ? 'verifier-admission' : 'gen3-explicit';
    rationale = 'The upstream test explicitly constructs or validates a Generation 3 format/scenario.';
  } else if (gens.length && !gens.includes(3)) {
    applicability = 'different-generation';
    rationale = `The test explicitly exercises only generation(s) ${gens.join(', ')}; it supplies no Generation 3 assertion.`;
  } else if (/dynamax|terastal|tera\b|mega evolution|z-move|zmove|gen[4-9]|fairy|paldea|galar|alola/i.test(record.full_test_name)) {
    applicability = 'post-gen3-unreachable';
    rationale = 'The named mechanic or format postdates Generation 3 and is unreachable in Gen 3 OU.';
  }

  const boundaries = [];
  const tags = [
    ['choice normalization/legal choices', /choice|choose|legal|request|cant/],
    ['action queue/order', /priority|speed|order|queue|tie/],
    ['event dispatch/order', /event|handler|callback|on[A-Z]/],
    ['phase/request transition', /turn|request|teampreview|team preview/],
    ['canonical battle state', /state|hp|status|boost|volatile|weather|side condition/],
    ['PRNG staging', /random|prng|seed|chance|accuracy|critical/],
    ['faint/switch/forced replacement', /faint|switch|replace|drag|trap/],
    ['terminal result/winner', /winner|tie|win\b|end battle/],
    ['admission/rule validation', /valid|legalteam|rule|ban|clause|format/],
  ];
  for (const [name, pattern] of tags) if (pattern.test(text)) boundaries.push(name);
  if (!boundaries.length) boundaries.push('data/mod resolution or mechanic-specific state transition');

  const evidence = [];

  return {
    ...record,
    pinned_revision: REVISION,
    applicability,
    applicability_evidence: rationale,
    semantic_boundaries: boundaries,
    existing_evidence_ids: evidence,
    needs_new_case: ['gen3-explicit', 'verifier-admission'].includes(applicability) && evidence.length === 0,
    proposed_case: ['gen3-explicit', 'verifier-admission'].includes(applicability) && evidence.length === 0 ?
      `Port the semantic assertion of ${record.full_test_name} as a focused native test or observable differential fixture.` : '',
  };
}

function readJson(file) {
  try { return JSON.parse(fs.readFileSync(file, 'utf8')); } catch { return null; }
}

function collectProjectEvidence(root) {
  if (!root) return new Map();
  const bySource = new Map();
  const add = (source, testName, value) => {
    if (!source) return;
    if (!bySource.has(source)) bySource.set(source, []);
    bySource.get(source).push({testName, value});
  };
  const inventory = readJson(path.join(root, 'verify/cases/inventory.json'));
  for (const entry of inventory?.entries || []) {
    if (entry.disposition === 'accepted') add(entry.source_file, entry.test_name, `case:${entry.case}`);
  }
  const derived = path.join(root, 'verify/cases/derived');
  if (fs.existsSync(derived)) {
    for (const entry of fs.readdirSync(derived, {withFileTypes: true})) {
      if (!entry.isFile() || !entry.name.endsWith('.json')) continue;
      const file = path.join(derived, entry.name);
      const value = readJson(file);
      if (value?.provenance?.source_file) {
        add(value.provenance.source_file, value.provenance.test_name, `differential:${value.id}`);
      }
    }
  }
  return bySource;
}

const projectEvidence = collectProjectEvidence(project);
const verifierOverrides = new Map(Object.entries({
  'test/sim/team-validator/breeding.js:8': {
    evidence: ['case:legal-shedinja-gust-regression'],
  },
  'test/sim/team-validator/breeding.js:54': {
    evidence: ['case:ban-source-egg-pair', 'case:ban-skarmory-whirlwind-drill-peck',
      'case:ban-armaldo-knock-off-rapid-spin'],
  },
  'test/sim/team-validator/breeding.js:81': {
    evidence: ['case:legal-source-chainbreed', 'case:legal-hitmontop-shared-father-source'],
  },
  'test/sim/team-validator/breeding.js:107': {
    applicability: 'different-generation',
    rationale: 'The sole assertion submits Gluttony Snorlax to gen5ou. It is not a Gen 3 admission obligation.',
  },
  'test/sim/team-validator/breeding.js:200': {
    evidence: ['case:ban-pomeg-event-egg-without-clause',
      'case:legal-pomeg-event-egg-with-clause'],
  },
  'test/sim/team-validator/breeding.js:257': {
    evidence: ['case:ban-source-egg-underlevel'],
  },
  'test/sim/team-validator/misc.js:6': {
    evidence: ['case:legal-source-restricted', 'case:ban-source-two-restricted'],
  },
  'test/sim/team-validator/misc.js:101': {
    applicability: 'different-generation',
    rationale: 'Both assertions submit gen4ou teams and test Gen 4 abilities combined with Gen 3 tutor moves. No equivalent state exists in Gen 3 admission.',
  },
}));
const records = files.flatMap(extract).map(classify).map(record => {
  const discovered = (projectEvidence.get(record.source_file) || [])
    .filter(entry => entry.testName === record.full_test_name)
    .map(entry => entry.value).sort();
  record.existing_evidence_ids = [...new Set([...record.existing_evidence_ids, ...discovered])];
  if (record.applicability === 'gen3-explicit' && record.source_file.endsWith('/ohko.js')) {
    record.applicability_evidence = 'The test constructs common.gen(3). OHKO Clause rejects directly submitted OHKO moves, but legal Metronome can select all four effective Gen 3 OHKO descriptors, so the runtime assertion remains reachable.';
    const ohkoEvidence = [
      'test_typed_ohko_pipeline',
      'differential:ohko-fissure-forced-replacement',
      'differential:ohko-guillotine-miss',
      'differential:ohko-horn-drill-substitute',
      'differential:ohko-sheer-cold-level-gate',
      'differential:ohko-sheer-cold-sturdy',
      'differential:metronome-fissure-flying',
    ];
    record.existing_evidence_ids = ohkoEvidence;
    record.needs_new_case = false;
    record.proposed_case = '';
  }
  if (record.applicability === 'gen3-explicit' && record.source_file.endsWith('/faint-order.js')) {
    record.semantic_boundaries = ['action queue/order', 'phase/request transition', 'faint/switch/forced replacement', 'canonical battle state'];
    record.applicability_evidence = 'The test constructs common.gen(3): Explosion self-faints, forced replacement suspends the turn, and the foe\'s queued Substitute must not execute.';
    record.needs_new_case = true;
    record.proposed_case = 'Add a legal differential Explosion + queued Substitute + forced replacement scenario, plus a focused queue-drain assertion that the remaining move is discarded.';
  }
  if (record.applicability === 'verifier-admission') {
    record.applicability_evidence += ' This is a verifier/team-admission obligation, not a battle-kernel transition.';
    record.proposed_case = `Add a hermetic verifier/admission assertion for ${record.full_test_name}; do not place learnset legality in the battle kernel.`;
  }
  const override = verifierOverrides.get(`${record.source_file}:${record.source_line}`);
  if (override) {
    if (override.applicability) {
      record.applicability = override.applicability;
      record.applicability_evidence = override.rationale;
      record.existing_evidence_ids = [];
      record.needs_new_case = false;
      record.proposed_case = '';
    } else {
      record.existing_evidence_ids = override.evidence;
      record.needs_new_case = false;
      record.proposed_case = '';
    }
  }
  if (record.applicability === 'gen3-explicit' && discovered.length) {
    record.needs_new_case = false;
    record.proposed_case = '';
  }
  const {source_body, ...clean} = record;
  return clean;
});
records.forEach((record, index) => record.id = `core-${String(index + 1).padStart(4, '0')}`);

const summary = records.reduce((acc, record) => {
  acc.total++;
  acc[record.applicability] = (acc[record.applicability] || 0) + 1;
  if (record.needs_new_case) acc.needs_new_case++;
  return acc;
}, {total: 0, needs_new_case: 0});

fs.mkdirSync(outputDir, {recursive: true});
fs.writeFileSync(path.join(outputDir, 'core-test-census.json'), JSON.stringify({revision: REVISION, scope: {exactFiles, suiteDirs}, summary, records}, null, 2) + '\n');
const columns = ['id', 'source_file', 'source_line', 'full_test_name', 'pinned_revision', 'applicability', 'applicability_evidence', 'semantic_boundaries', 'existing_evidence_ids', 'needs_new_case', 'proposed_case'];
const cell = value => {
  const rendered = Array.isArray(value) ? value.join('; ') : String(value);
  return (rendered || 'none').replace(/[\t\r\n]+/g, ' ');
};
fs.writeFileSync(path.join(outputDir, 'core-test-census.tsv'), [columns.join('\t'), ...records.map(r => columns.map(c => cell(r[c])).join('\t'))].join('\n') + '\n');
console.log(JSON.stringify(summary));
