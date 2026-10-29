'use strict';

const childProcess = require('child_process');

const DEFAULT_TIMEOUT_MS = 120000;

function timeoutFromEnvironment(environment = process.env) {
	const raw = environment.POKEMON_VERIFY_TIMEOUT_MS;
	if (raw === undefined || raw === '') return DEFAULT_TIMEOUT_MS;
	const value = Number(raw);
	if (!Number.isSafeInteger(value) || value < 1) {
		throw new Error('POKEMON_VERIFY_TIMEOUT_MS must be a positive integer');
	}
	return value;
}

function execute(command, args, options = {}) {
	const timeout = options.timeout === undefined ? timeoutFromEnvironment(options.env) : options.timeout;
	const result = childProcess.spawnSync(command, args, {
		encoding: options.encoding === undefined ? 'utf8' : options.encoding,
		cwd: options.cwd,
		env: options.env || process.env,
		maxBuffer: options.maxBuffer || 256 * 1024 * 1024,
		timeout,
		killSignal: 'SIGKILL',
	});
	const metadata = {
		command, args, timeout_ms: timeout, status: result.status,
		signal: result.signal || null,
		timed_out: Boolean(result.error && result.error.code === 'ETIMEDOUT'),
		stdout: result.stdout === undefined ? '' : result.stdout,
		stderr: result.stderr === undefined ? '' : result.stderr,
	};
	if (result.error) {
		const kind = result.error.code === 'ETIMEDOUT' ? 'timeout' : 'spawn-error';
		const error = new Error(`${kind}: ${JSON.stringify(metadata)}: ${result.error.message}`);
		error.code = result.error.code;
		error.metadata = metadata;
		throw error;
	}
	if (result.status !== 0) {
		const error = new Error(`subprocess-failure: ${JSON.stringify(metadata)}:\n${result.stderr}`);
		error.metadata = metadata;
		throw error;
	}
	return result.stdout;
}

module.exports = {DEFAULT_TIMEOUT_MS, execute, timeoutFromEnvironment};
