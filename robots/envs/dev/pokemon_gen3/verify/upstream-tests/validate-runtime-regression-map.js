'use strict';

const childProcess = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const showdown = path.resolve(process.argv[2] || '');
if (!process.argv[2]) throw new Error('usage: node validate-runtime-regression-map.js SHOWDOWN_DIR');
const checkedPath = path.join(__dirname, 'gen3ou-runtime-regression-map.json');
const temporary = path.join(os.tmpdir(), `gen3ou-runtime-regression-${process.pid}.json`);
const projectRoot = path.resolve(__dirname, '../..');

try {
	childProcess.execFileSync(process.execPath, [path.join(__dirname, 'build-runtime-regression-map.js'), showdown, temporary], {stdio: 'inherit'});
	const expected = JSON.parse(fs.readFileSync(checkedPath, 'utf8'));
	const actual = JSON.parse(fs.readFileSync(temporary, 'utf8'));
	if (JSON.stringify(actual) !== JSON.stringify(expected)) throw new Error('runtime regression map is stale');
	if (expected.schema !== 'pokemon-gen3ou-runtime-regression-map-v1' || expected.pinned_revision !== REVISION) {
		throw new Error('schema or pinned revision mismatch');
	}
	const summary = expected.summary;
	if (summary.registered !== 2172 || summary.active !== 2129 || summary.pending !== 43 ||
		summary.static_declarations !== 1976 || summary.dynamic_expansions !== 196 ||
		summary.applicable !== 276 || summary.assertion_specific !== 304 ||
		summary.requiring_case !== 0) {
		throw new Error(`registration parity mismatch: ${JSON.stringify(summary)}`);
	}
	const ids = new Set();
	let expanded = 0;
	const expandedParents = new Set();
	for (const record of expected.records) {
		if (ids.has(record.runtime_id)) throw new Error(`duplicate runtime_id ${record.runtime_id}`);
		ids.add(record.runtime_id);
		if (record.revision !== REVISION) throw new Error(`${record.runtime_id} revision mismatch`);
		if (record.expansion) {
			expanded++;
			expandedParents.add(record.parent_declaration_id);
		}
		if (!record.applicability?.disposition ||
			(record.applicability.applicable && (!record.mechanics.length || !record.boundaries.length))) {
			throw new Error(`${record.runtime_id} lacks semantic adjudication`);
		}
		if (record.applicability.applicable) {
			if (!record.applicability.semantic_sources.length) {
				throw new Error(`${record.runtime_id} lacks semantic sources`);
			}
			if (record.evidence_scope === 'assertion_specific') {
				if (!record.evidence.length || record.required_case) throw new Error(`${record.runtime_id} has inconsistent proof`);
			} else if (!record.required_case) {
				throw new Error(`${record.runtime_id} fails open without proof or required_case`);
			}
		} else if (!record.terminal_reason || record.required_case) {
			throw new Error(`${record.runtime_id} lacks terminal exclusion evidence`);
		}
		for (const evidence of record.evidence) {
			if (!evidence.kind || !evidence.path || !evidence.selector) throw new Error(`${record.runtime_id} has inexact evidence`);
			const target = path.join(projectRoot, evidence.path);
			if (!fs.existsSync(target)) throw new Error(`${record.runtime_id} evidence path does not exist: ${evidence.path}`);
			if (evidence.kind === 'native_unit' && !fs.readFileSync(target, 'utf8').includes(evidence.selector)) {
				throw new Error(`${record.runtime_id} native selector does not exist: ${evidence.selector}`);
			}
			if (evidence.kind === 'admission_case') {
				const cases = JSON.parse(fs.readFileSync(target, 'utf8'));
				if (!JSON.stringify(cases).includes(`\"${evidence.selector}\"`)) throw new Error(`${record.runtime_id} admission selector does not exist: ${evidence.selector}`);
			}
		}
	}
	if (expanded - expandedParents.size !== 196) {
		throw new Error(`expected 196 runtime expansions beyond ${expandedParents.size} parameterized declarations, got ${expanded}`);
	}
	console.log(JSON.stringify(summary));
} finally {
	if (fs.existsSync(temporary)) fs.unlinkSync(temporary);
}
