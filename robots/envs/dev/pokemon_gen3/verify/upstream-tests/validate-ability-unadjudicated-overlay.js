'use strict';

const assert = require('assert');
const childProcess = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const PINNED_REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const root = __dirname;
const showdown = path.resolve(process.argv[2] || '/private/tmp/pokemon-lockon-clean');
const overlayPath = path.resolve(process.argv[3] || path.join(root, 'ability-unadjudicated-overlay.json'));
const regeneratedPath = path.join(os.tmpdir(), `ability-semantic-overlay-${process.pid}.json`);
try {
	childProcess.execFileSync(process.execPath, [
		path.join(root, 'build-ability-unadjudicated-overlay.js'), showdown, regeneratedPath,
	], {stdio: 'inherit'});
	assert.strictEqual(fs.readFileSync(regeneratedPath, 'utf8'), fs.readFileSync(overlayPath, 'utf8'),
		'checked ability semantic overlay is stale');
} finally {
	if (fs.existsSync(regeneratedPath)) fs.unlinkSync(regeneratedPath);
}
const census = JSON.parse(fs.readFileSync(path.join(root, 'all-test-census.json'), 'utf8'));
const overlay = JSON.parse(fs.readFileSync(overlayPath, 'utf8'));
const adjudications = JSON.parse(fs.readFileSync(path.join(root,
	'ability-semantic-transposition-adjudications.json'), 'utf8'));
const {Dex} = require(path.join(showdown, 'dist', 'sim'));
const resolved = Dex.forGen(3);

assert.strictEqual(require('child_process').execFileSync('git', ['-C', showdown, 'rev-parse', 'HEAD'], {encoding: 'utf8'}).trim(), PINNED_REVISION);
assert.strictEqual(overlay.pinned_revision, PINNED_REVISION);
assert.strictEqual(overlay.schema, 'pokemon-showdown-gen3ou-ability-semantic-overlay-v2');
assert.strictEqual(adjudications.schema,
	'pokemon-gen3ou-ability-semantic-transposition-adjudications-v1');
assert.strictEqual(adjudications.pinned_revision, PINNED_REVISION);
assert.strictEqual(Object.keys(adjudications.records).length, 43);

const expected = census.records.filter(record =>
	record.adjudication_source === 'ability-unadjudicated-overlay.json' &&
	record.source_file.startsWith('test/sim/abilities/'));
assert.strictEqual(expected.length, 411);
assert.strictEqual(overlay.records.length, expected.length);

const declarationKey = record => `${record.source_file}:${record.source_line}:${record.full_test_name}`;
assert.deepStrictEqual(overlay.records.map(declarationKey), expected.map(declarationKey));
assert.strictEqual(new Set(overlay.records.map(declarationKey)).size, overlay.records.length);

for (const record of overlay.records) {
	assert.ok(['applicable-transposed-alias', 'shared_operation_not_equivalent',
		'owner_specific_terminal'].includes(record.disposition));
	assert.ok(record.evidence.length > 80);
	assert.ok(record.mechanics.length >= 1);
	assert.ok(record.semantic_boundaries.length >= 2);
	assert.ok(record.semantic_sources.length >= 1);
	for (const reference of record.semantic_sources) {
		const located = reference.match(/^(.+?)(?::(\d+)(?:-(\d+))?|#([A-Za-z0-9_-]+))$/);
		const sourceFile = located ? located[1] : reference;
		const sourcePath = path.join(showdown, sourceFile);
		assert.ok(fs.existsSync(sourcePath), `${declarationKey(record)} missing semantic source ${reference}`);
		if (located?.[2]) {
			const lineCount = fs.readFileSync(sourcePath, 'utf8').split(/\r?\n/).length;
			assert.ok(Number(located[2]) >= 1 && Number(located[2]) <= lineCount, reference);
			if (located[3]) assert.ok(Number(located[3]) <= lineCount, reference);
		}
		if (located?.[4]) {
			assert.ok(fs.readFileSync(sourcePath, 'utf8').toLowerCase().includes(located[4].toLowerCase()),
				`${reference} symbol not found`);
		}
		}
		if (record.disposition === 'applicable-transposed-alias') {
			const proven = record.assertion_evidence_scope === 'assertion_specific' &&
				Object.values(record.assertion_evidence || {}).some(values => values.length);
			assert.ok(Boolean(record.required_native_or_differential_case) || proven);
			assert.ok(!(record.required_native_or_differential_case && proven));
			assert.ok(record.case_decision.startsWith(proven ?
				'Assertion-specific evidence' : 'Required case:'));
			assert.strictEqual(record.semantic_transposition_disposition, 'gen3_alias_applicable');
	} else {
		assert.strictEqual(record.required_native_or_differential_case, null);
		assert.ok(record.case_decision.startsWith('No case from this assertion:'));
	}
	assert.ok(record.resolved_gen3_source_references.length >= 3);
	for (const id of record.ability_ids) {
		const ability = resolved.abilities.get(id);
		assert.ok(ability.exists, `${id} must exist in the pinned Dex`);
		assert.ok(ability.gen > 3, `${id} must postdate Gen 3`);
		assert.strictEqual(ability.isNonstandard, 'Future');
		assert.ok(record.resolved_generations.includes(ability.gen));
	}
	const source = fs.readFileSync(path.join(showdown, record.source_file), 'utf8').split(/\r?\n/);
	assert.ok(/\b(?:it|test)(?:\.skip)?\(/.test(source[record.source_line - 1]), declarationKey(record));
	for (const reference of record.resolved_gen3_source_references) {
		const match = reference.match(/^(.+):(\d+)(?:-(\d+))?$/);
		assert.ok(match, `invalid source reference ${reference}`);
		const referencedLines = fs.readFileSync(path.join(showdown, match[1]), 'utf8').split(/\r?\n/);
		assert.ok(Number(match[2]) >= 1 && Number(match[2]) <= referencedLines.length, reference);
		if (match[3]) assert.ok(Number(match[3]) <= referencedLines.length, reference);
	}
}

assert.deepStrictEqual(overlay.summary, {
	declarations: 411,
	files: 77,
	applicable: 7,
	applicable_transposed_alias: 7,
	shared_operation_not_equivalent: 22,
	owner_specific_terminal: 382,
	semantic_exception_records: 43,
	default_terminal_records: 368,
	uncertain: 0,
	declarations_by_introduction_generation: {4: 77, 5: 71, 6: 71, 7: 66, 8: 67, 9: 59},
});

console.log(`ability overlay valid: ${overlay.records.length} declarations; ` +
	`${overlay.summary.applicable_transposed_alias} Gen 3 aliases, ` +
	`${overlay.summary.shared_operation_not_equivalent} shared non-equivalences, ` +
	`${overlay.summary.owner_specific_terminal} owner-specific terminal rows`);
