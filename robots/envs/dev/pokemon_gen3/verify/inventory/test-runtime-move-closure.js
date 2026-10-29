'use strict';

const assert = require('assert');
const childProcess = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const showdownDir = process.env.POKEMON_SHOWDOWN_DIR;
if (!showdownDir) throw new Error('POKEMON_SHOWDOWN_DIR must name the pinned clean Showdown checkout');

const temporaryDir = fs.mkdtempSync(path.join(os.tmpdir(), 'pokemon-runtime-move-closure-'));
const generatedPath = path.join(temporaryDir, 'inventory.json');
try {
	childProcess.execFileSync(process.execPath, [path.join(__dirname, 'generate.js'), generatedPath], {
		env: {...process.env, POKEMON_SHOWDOWN_DIR: showdownDir}, stdio: 'inherit',
	});
	const generated = JSON.parse(fs.readFileSync(generatedPath, 'utf8'));
	const expectedMetronomeOnly = [
		'assist', 'doubleteam', 'fissure', 'guillotine', 'horndrill', 'minimize', 'sheercold', 'swagger',
	];

	assert.strictEqual(generated.counts.moves, 354, 'runtime move closure must contain exactly 354 moves');
	assert.strictEqual(generated.runtime_move_closure.submitted_set_count, 345);
	assert.strictEqual(generated.runtime_move_closure.metronome_submitted_set_reachable, true);
	assert.strictEqual(generated.runtime_move_closure.metronome_pool_count, 336);
	assert.deepStrictEqual(generated.runtime_move_closure.metronome_only_ids, expectedMetronomeOnly);
	assert.deepStrictEqual(generated.runtime_move_closure.simulator_forced_ids, ['struggle']);

	const moves = new Map(generated.moves.map(move => [move.id, move]));
	for (const id of expectedMetronomeOnly) {
		assert(moves.get(id)?.reachability.some(path => path.kind === 'move-delegation' && path.caller === 'metronome'),
			`${id} must retain Metronome reachability provenance`);
		assert(!moves.get(id).reachability.some(path => path.kind === 'submitted-set'),
			`${id} must not be mislabeled as submitted-set reachable`);
	}
	assert.deepStrictEqual(moves.get('struggle')?.reachability, [{
		kind: 'simulator-forced', source: 'sim/pokemon.ts:getMoves and sim/side.ts:chooseMove',
	}]);
	assert(generated.volatiles.some(condition => condition.id === 'minimize'),
		'Metronome-reachable Minimize must contribute its volatile');
	assert.strictEqual(generated.counts.callback_hooks, 514,
		'runtime-reachable descriptors must contribute exactly 514 callback ownership records');

	process.stdout.write('runtime move closure passed\n');
} finally {
	fs.rmSync(temporaryDir, {recursive: true, force: true});
}
