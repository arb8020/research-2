'use strict';

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const ORACLE_REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';

function nativeAction(choice) {
	if (choice === null) return -1;
	let match = /^move ([1-4])$/.exec(choice);
	if (match) return Number(match[1]) - 1;
	match = /^switch ([2-6])$/.exec(choice);
	if (match) return Number(match[1]) + 2;
	throw new Error(`choice has no native action encoding: ${choice}`);
}

function fixturePath(casePath, reference) {
	if (!/^[A-Za-z0-9][A-Za-z0-9._-]*\.txt$/.test(reference)) {
		throw new Error(`unsafe team fixture reference: ${reference}`);
	}
	const base = path.resolve(path.dirname(casePath));
	const resolved = path.resolve(base, reference);
	if (path.dirname(resolved) !== base) throw new Error(`team fixture escapes case directory: ${reference}`);
	return resolved;
}

function loadCase(casePath) {
	const value = JSON.parse(fs.readFileSync(casePath, 'utf8'));
	if (value.schema_version !== 2 || value.format !== 'gen3ou') throw new Error('unsupported case schema or format');
	if (!/^[a-z0-9][a-z0-9._-]+$/.test(value.id)) throw new Error('invalid case id');
	if (value.provenance.oracle_revision !== ORACLE_REVISION) throw new Error('case oracle revision is not pinned');
	if (value.teams.kind !== 'verifier-showdown-export-files' || value.teams.values.length !== 2) {
		throw new Error('case requires two verifier-owned Showdown export files');
	}
	const teams = value.teams.values.map(reference => fixturePath(casePath, reference));
	const digest = crypto.createHash('sha256')
		.update(fs.readFileSync(teams[0])).update(Buffer.from([0])).update(fs.readFileSync(teams[1])).digest('hex');
	if (digest !== value.teams.normalization_digest) throw new Error('team normalization digest mismatch');
	if (value.choices.kind !== 'explicit' || !value.choices.turns.length) throw new Error('boundary driver requires explicit choices');
	const showdownChoices = value.choices.turns.map(turn => turn.map(choice => choice || ''));
	const nativeChoices = value.choices.turns.map(turn => turn.map(nativeAction));
	return {id: value.id, format: value.format, seed: value.battle_seed, teams, nativeChoices, showdownChoices};
}

function writeNativeProjection(casePath, outputPath) {
	const value = loadCase(casePath);
	const lines = [
		'schema=gen3ou-native-projection-v1',
		`id=${value.id}`,
		`seed=${value.seed.join(',')}`,
		...value.nativeChoices.map(turn => `decision=${turn.join(',')}`),
	];
	fs.writeFileSync(outputPath, `${lines.join('\n')}\n`, {mode: 0o600});
}

if (require.main === module) {
	if (process.argv.length !== 4) throw new Error('usage: shared_case.js CASE NATIVE_PROJECTION');
	writeNativeProjection(process.argv[2], process.argv[3]);
}

module.exports = {loadCase, writeNativeProjection};
