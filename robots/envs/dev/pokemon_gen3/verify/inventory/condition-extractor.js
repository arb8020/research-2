'use strict';

const API_SPECS = Object.freeze({
	addVolatile: {ids: [{kind: 'volatile', argument: 0}, {kind: 'volatile', argument: 3, optional: true, role: 'linkedStatus'}]},
	removeVolatile: {ids: [{kind: 'volatile', argument: 0}]},
	addSideCondition: {ids: [{kind: 'side', argument: 0}]},
	removeSideCondition: {ids: [{kind: 'side', argument: 0}]},
	addSlotCondition: {ids: [{kind: 'slot', argument: 1}]},
	removeSlotCondition: {ids: [{kind: 'slot', argument: 1}]},
	setWeather: {ids: [{kind: 'weather', argument: 0}]},
	clearWeather: {ids: []},
	addPseudoWeather: {ids: [{kind: 'pseudoWeather', argument: 0}]},
	removePseudoWeather: {ids: [{kind: 'pseudoWeather', argument: 0}]},
	setStatus: {ids: [{kind: 'status', argument: 0}]},
	forceStatus: {ids: [{kind: 'status', argument: 0}]},
	trySetStatus: {ids: [{kind: 'status', argument: 0}]},
	cureStatus: {ids: []},
	clearStatus: {ids: []},
});

function splitArguments(source) {
	const result = [];
	let start = 0;
	let depth = 0;
	let quote = '';
	let escaped = false;
	for (let index = 0; index < source.length; index++) {
		const character = source[index];
		if (quote) {
			if (escaped) escaped = false;
			else if (character === '\\') escaped = true;
			else if (character === quote) quote = '';
			continue;
		}
		if (character === '"' || character === "'" || character === '`') {
			quote = character;
			continue;
		}
		if ('([{'.includes(character)) depth++;
		else if (')]}'.includes(character)) depth--;
		else if (character === ',' && depth === 0) {
			result.push(source.slice(start, index).trim());
			start = index + 1;
		}
	}
	if (quote || depth !== 0) throw new Error('unbalanced condition call arguments');
	result.push(source.slice(start).trim());
	return result;
}

function maskNonCode(source) {
	const characters = [...source];
	let mode = 'code';
	const returnModes = [];
	let sourceStringQuote = '';
	let escaped = false;
	const templateExpressionDepth = [];
	for (let index = 0; index < source.length; index++) {
		const character = source[index];
		const next = source[index + 1];
		if (mode === 'line-comment') {
			if (character === '\n') mode = returnModes.pop();
			else characters[index] = ' ';
			continue;
		}
		if (mode === 'block-comment') {
			characters[index] = ' ';
			if (character === '*' && next === '/') {
				characters[index + 1] = ' ';
				index++;
				mode = returnModes.pop();
			}
			continue;
		}
		if (mode === 'string') {
			characters[index] = ' ';
			if (escaped) escaped = false;
			else if (character === '\\') escaped = true;
			else if (character === sourceStringQuote) mode = returnModes.pop();
			continue;
		}
		if (mode === 'template') {
			characters[index] = ' ';
			if (escaped) {
				escaped = false;
			} else if (character === '\\') {
				escaped = true;
			} else if (character === '`') {
				mode = returnModes.pop();
			} else if (character === '$' && next === '{') {
				characters[index + 1] = ' ';
				index++;
				templateExpressionDepth.push(1);
				mode = 'template-expression';
			}
			continue;
		}
		if (mode === 'template-expression') {
			if (character === '{') templateExpressionDepth[templateExpressionDepth.length - 1]++;
			if (character === '}') {
				const last = templateExpressionDepth.length - 1;
				templateExpressionDepth[last]--;
				if (templateExpressionDepth[last] === 0) {
					characters[index] = ' ';
					templateExpressionDepth.pop();
					mode = 'template';
					continue;
				}
			}
		}
		if (character === '/' && next === '/') {
			characters[index] = characters[index + 1] = ' ';
			index++;
			returnModes.push(mode);
			mode = 'line-comment';
		} else if (character === '/' && next === '*') {
			characters[index] = characters[index + 1] = ' ';
			index++;
			returnModes.push(mode);
			mode = 'block-comment';
		} else if (character === '"' || character === "'") {
			characters[index] = ' ';
			returnModes.push(mode);
			sourceStringQuote = character;
			mode = 'string';
		} else if (character === '`') {
			characters[index] = ' ';
			returnModes.push(mode);
			mode = 'template';
		}
	}
	if (!['code', 'line-comment'].includes(mode) || templateExpressionDepth.length ||
		(mode === 'line-comment' && returnModes.length !== 1)) {
		throw new Error('unbalanced source while scanning condition mutations');
	}
	return characters.join('');
}

function extractCalls(source) {
	const names = Object.keys(API_SPECS);
	const pattern = new RegExp(`\\b(${names.join('|')})\\s*\\(`, 'g');
	const result = [];
	for (const match of maskNonCode(source).matchAll(pattern)) {
		const bodyStart = match.index + match[0].length;
		let index = bodyStart;
		let depth = 1;
		let quote = '';
		let escaped = false;
		for (; index < source.length && depth !== 0; index++) {
			const character = source[index];
			if (quote) {
				if (escaped) escaped = false;
				else if (character === '\\') escaped = true;
				else if (character === quote) quote = '';
				continue;
			}
			if (character === '"' || character === "'" || character === '`') {
				quote = character;
				continue;
			}
			if (character === '(') depth++;
			else if (character === ')') depth--;
		}
		if (depth !== 0 || quote) throw new Error(`unbalanced ${match[1]} call`);
		result.push({
			api: match[1],
			arguments: splitArguments(source.slice(bodyStart, index - 1)),
			index: match.index,
			text: source.slice(match.index, index),
		});
	}
	return result;
}

function literalID(expression, toID) {
	const match = /^(['"])([^'"]+)\1$/.exec(expression || '');
	return match ? toID(match[2]) : null;
}

function extractDirectDeletes(source, toID) {
	const result = [];
	const deletion = /delete\s+[^;\n]*?\b(volatiles|sideConditions|slotConditions|pseudoWeather)((?:\s*\[[^\]]+\])+)/g;
	for (const match of maskNonCode(source).matchAll(deletion)) {
		const original = source.slice(match.index, match.index + match[0].length);
		const accessors = [...original.matchAll(/\[([^\]]+)\]/g)];
		const expression = accessors.at(-1)?.[1].trim();
		const id = literalID(expression, toID);
		result.push({container: match[1], id, expression: id ? original : expression});
	}
	return result;
}

module.exports = {API_SPECS, extractCalls, extractDirectDeletes, literalID, splitArguments};
