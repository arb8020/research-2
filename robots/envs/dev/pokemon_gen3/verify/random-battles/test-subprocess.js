'use strict';

const assert = require('assert');
const {execute, timeoutFromEnvironment} = require('./subprocess');

assert.strictEqual(timeoutFromEnvironment({}), 120000);
assert.strictEqual(timeoutFromEnvironment({POKEMON_VERIFY_TIMEOUT_MS: '17'}), 17);
assert.throws(() => timeoutFromEnvironment({POKEMON_VERIFY_TIMEOUT_MS: '0'}), /positive integer/);
assert.throws(() => timeoutFromEnvironment({POKEMON_VERIFY_TIMEOUT_MS: 'wat'}), /positive integer/);
assert.strictEqual(execute(process.execPath, ['-e', 'process.stdout.write("ok")'], {timeout: 1000}), 'ok');

let timeout;
try {
	execute(process.execPath, ['-e', 'setInterval(() => {}, 1000)'], {timeout: 20});
} catch (error) {
	timeout = error;
}
assert.ok(timeout, 'nonterminating subprocess must time out');
assert.strictEqual(timeout.code, 'ETIMEDOUT');
assert.strictEqual(timeout.metadata.timeout_ms, 20);
assert.strictEqual(timeout.metadata.command, process.execPath);
assert.strictEqual(timeout.metadata.timed_out, true);
assert.strictEqual(timeout.metadata.status, null);
assert.strictEqual(timeout.metadata.signal, 'SIGKILL');
assert.strictEqual(typeof timeout.metadata.stdout, 'string');
assert.strictEqual(typeof timeout.metadata.stderr, 'string');
assert.match(timeout.message, /^timeout:/);

let nonzero;
try {
	execute(process.execPath, ['-e',
		'process.stdout.write("out"); process.stderr.write("err"); process.exit(7)'], {timeout: 1000});
} catch (error) {
	nonzero = error;
}
assert.ok(nonzero);
assert.match(nonzero.message, /subprocess-failure/);
assert.strictEqual(nonzero.metadata.status, 7);
assert.strictEqual(nonzero.metadata.timed_out, false);
assert.strictEqual(nonzero.metadata.stdout, 'out');
assert.strictEqual(nonzero.metadata.stderr, 'err');

console.log('bounded subprocess contract passed');
