'use strict';

const childProcess = require('child_process');
const fs = require('fs');
const path = require('path');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const oracle = path.resolve(process.argv[2] || '');
const mapFile = path.resolve(process.argv[3] || path.join(__dirname, 'gen3ou-test-map.json'));
const outputFile = path.resolve(process.argv[4] || path.join(__dirname, 'all-test-census.json'));
if (!process.argv[2]) {
	throw new Error('usage: node build-all-test-census.js SHOWDOWN_DIR [CANONICAL_MAP] [OUTPUT_FILE]');
}
const revision = childProcess.execFileSync('git', ['rev-parse', 'HEAD'], {cwd: oracle, encoding: 'utf8'}).trim();
if (revision !== REVISION) throw new Error(`oracle revision ${revision}; expected ${REVISION}`);
const ts = require(path.join(oracle, 'node_modules/typescript'));
const canonical = JSON.parse(fs.readFileSync(mapFile, 'utf8'));
if (canonical.pinned_revision !== REVISION) throw new Error('canonical map revision mismatch');
const overlayFiles = [
	'ability-unadjudicated-overlay.json',
	'gen3ou-item-test-overlay.json',
	'move-declaration-overlay.json',
	'scope-test-overlay.json',
];
const overlays = overlayFiles.map(file => ({
	file,
	data: JSON.parse(fs.readFileSync(path.join(__dirname, file), 'utf8')),
}));
for (const {file, data} of overlays) {
	if (data.pinned_revision !== REVISION) throw new Error(`${file} revision mismatch`);
}

function walk(directory) {
	return fs.readdirSync(directory, {withFileTypes: true}).flatMap(entry => {
		const file = path.join(directory, entry.name);
		return entry.isDirectory() ? walk(file) : entry.name.endsWith('.js') ? [file] : [];
	});
}
function callInfo(node) {
	if (!ts.isCallExpression(node)) return {kind: '', skipped: false};
	if (ts.isIdentifier(node.expression)) return {kind: node.expression.text, skipped: false};
	if (ts.isPropertyAccessExpression(node.expression) && ts.isIdentifier(node.expression.expression)) {
		return {kind: node.expression.expression.text, skipped: node.expression.name.text === 'skip'};
	}
	return {kind: '', skipped: false};
}
function staticName(node, source) {
	const value = node.arguments[0];
	if (value && ts.isStringLiteralLike(value)) return value.text;
	return value ? value.getText(source).replace(/\s+/g, ' ') : '<missing name>';
}
function extract(file) {
	const relative = path.relative(oracle, file);
	const text = fs.readFileSync(file, 'utf8');
	const source = ts.createSourceFile(relative, text, ts.ScriptTarget.Latest, true, ts.ScriptKind.JS);
	const records = [];
	function visit(node, suites, ancestorSkipped = false) {
		const {kind, skipped} = callInfo(node) || {kind: '', skipped: false};
		if (kind === 'describe') {
			const callback = node.arguments[1];
			if (callback && (ts.isArrowFunction(callback) || ts.isFunctionExpression(callback))) {
				ts.forEachChild(callback.body, child => visit(child, [...suites, staticName(node, source)], ancestorSkipped || skipped));
				return;
			}
		}
		if (kind === 'it' || kind === 'test') {
			records.push({
				source_file: relative,
				source_line: source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1,
				full_test_name: [...suites, staticName(node, source)].join(' > '),
				execution_status: ancestorSkipped || skipped ? 'pending' : 'active',
			});
			return;
		}
		ts.forEachChild(node, child => visit(child, suites, ancestorSkipped));
	}
	visit(source, []);
	return records;
}

const mapped = new Map(canonical.records.map(record => [
	`${record.source.file}:${record.source.line}`,
	{
		audit_status: 'canonical',
		adjudication_source: path.basename(mapFile),
		partition: record.partition,
		disposition: record.applicability.disposition,
		required_case: record.required_case || null,
	},
]));
for (const {file, data} of overlays) {
	for (const record of data.records) {
		const key = record.identity && typeof record.identity === 'object' ?
			`${record.identity.source_file}:${record.identity.source_line}` :
			(record.identity || `${record.source_file}:${record.source_line}`);
		if (mapped.has(key)) throw new Error(`duplicate adjudication ${key} in ${file}`);
		mapped.set(key, {
			audit_status: 'overlay_adjudicated',
			adjudication_source: file,
			disposition: record.disposition,
			required_case: record.required_case !== undefined ? record.required_case :
				record.required_native_or_differential_case || null,
		});
	}
}
const records = walk(path.join(oracle, 'test/sim')).sort().flatMap(extract).map(record => {
	const mapping = mapped.get(`${record.source_file}:${record.source_line}`);
	return {
		...record,
		...(mapping || {audit_status: 'unadjudicated'}),
	};
});
const summary = {
	declarations: records.length,
	active: records.filter(record => record.execution_status === 'active').length,
	pending: records.filter(record => record.execution_status === 'pending').length,
	canonical: records.filter(record => record.audit_status === 'canonical').length,
	overlay_adjudicated: records.filter(record => record.audit_status === 'overlay_adjudicated').length,
	unadjudicated: records.filter(record => record.audit_status === 'unadjudicated').length,
};
fs.writeFileSync(outputFile, `${JSON.stringify({
	schema: 'pokemon-showdown-all-sim-test-census-v1',
	pinned_revision: REVISION,
	scope: 'Every statically declared it() or test() below test/sim, partitioned exactly between the canonical Gen 3 OU map and explicit adjudication overlays.',
	summary,
	records,
}, null, 2)}\n`);
console.log(JSON.stringify(summary));
