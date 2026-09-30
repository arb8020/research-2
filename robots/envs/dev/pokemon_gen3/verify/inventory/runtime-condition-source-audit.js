'use strict';

const fs = require('fs');
const path = require('path');

const API_NAMES = new Set([
	'addVolatile', 'removeVolatile', 'addSideCondition', 'removeSideCondition',
	'addSlotCondition', 'removeSlotCondition', 'setWeather', 'clearWeather',
	'addPseudoWeather', 'removePseudoWeather', 'setStatus', 'forceStatus',
	'trySetStatus', 'cureStatus', 'clearStatus',
]);
const CONTAINERS = new Set(['volatiles', 'sideConditions', 'slotConditions', 'pseudoWeather']);
const DESCRIPTOR_CONSTRUCTION_FILES = new Set(['sim/dex-data.ts']);

function walkFiles(root) {
	const result = [];
	for (const entry of fs.readdirSync(root, {withFileTypes: true})) {
		const absolute = path.join(root, entry.name);
		if (entry.isDirectory()) result.push(...walkFiles(absolute));
		else if (entry.isFile() && entry.name.endsWith('.ts') && !entry.name.endsWith('.d.ts')) result.push(absolute);
	}
	return result;
}

function normalizeSnippet(node, sourceFile) {
	return node.getText(sourceFile).replace(/\s+/g, ' ').trim();
}

function position(node, sourceFile) {
	const start = sourceFile.getLineAndCharacterOfPosition(node.getStart(sourceFile));
	return {line: start.line + 1, column: start.character + 1};
}

function propertyName(expression, ts) {
	if (ts.isPropertyAccessExpression(expression)) return expression.name.text;
	if (ts.isElementAccessExpression(expression) && expression.argumentExpression) {
		const argument = expression.argumentExpression;
		if (ts.isStringLiteralLike(argument)) return argument.text;
	}
	return null;
}

function isInvokedProperty(node, ts) {
	return ts.isCallExpression(node.parent) && node.parent.expression === node;
}

function containerAccess(expression, ts) {
	const segments = [];
	let cursor = expression;
	while (ts.isPropertyAccessExpression(cursor) || ts.isElementAccessExpression(cursor)) {
		segments.unshift(propertyName(cursor, ts) || '[]');
		cursor = cursor.expression;
	}
	const index = segments.findIndex(segment => CONTAINERS.has(segment));
	return index < 0 ? null : {container: segments[index], depth: segments.length - index - 1};
}

function directScalar(expression, ts) {
	if (!ts.isPropertyAccessExpression(expression) && !ts.isElementAccessExpression(expression)) return null;
	const name = propertyName(expression, ts);
	return name === 'status' || name === 'weather' || name === 'volatiles' ? name : null;
}

function isLifecycleDepth(access) {
	return access && access.depth <= (access.container === 'slotConditions' ? 2 : 1);
}

function scanFunctionDirectConditionMutations(source, ts) {
	const wrapped = `({${source}})`;
	const sourceFile = ts.createSourceFile('effective-callback.ts', wrapped,
		ts.ScriptTarget.Latest, true, ts.ScriptKind.TS);
	const result = [];
	function visit(node) {
		if (ts.isDeleteExpression(node)) {
			const access = containerAccess(node.expression, ts);
			if (access) result.push({kind: 'direct-delete', ...access,
				mutation_role: isLifecycleDepth(access) ? 'lifecycle-owning' : 'payload-only'});
		}
		if (ts.isBinaryExpression(node) &&
			node.operatorToken.kind >= ts.SyntaxKind.FirstAssignment &&
			node.operatorToken.kind <= ts.SyntaxKind.LastAssignment) {
			const access = containerAccess(node.left, ts);
			const scalar = directScalar(node.left, ts);
			if (access || scalar) result.push({kind: 'direct-assignment', ...(access || {}),
				...(scalar ? {scalar} : {}),
				mutation_role: access && !isLifecycleDepth(access) ? 'payload-only' : 'lifecycle-owning'});
		}
		ts.forEachChild(node, visit);
	}
	visit(sourceFile);
	return result;
}

function scanFunctionConditionCalls(source, ts) {
	const wrapped = `({${source}})`;
	const sourceFile = ts.createSourceFile('effective-callback.ts', wrapped,
		ts.ScriptTarget.Latest, true, ts.ScriptKind.TS);
	const result = [];
	function visit(node) {
		if (ts.isCallExpression(node)) {
			const api = propertyName(node.expression, ts);
			if (API_NAMES.has(api)) result.push({
				api,
				arguments: node.arguments.map(argument => argument.getText(sourceFile)),
			});
		}
		ts.forEachChild(node, visit);
	}
	visit(sourceFile);
	return result;
}

function scanFunctionConditionReferences(source, ts) {
	const wrapped = `({${source}})`;
	const sourceFile = ts.createSourceFile('effective-callback.ts', wrapped,
		ts.ScriptTarget.Latest, true, ts.ScriptKind.TS);
	const result = [];
	function visit(node) {
		if ((ts.isPropertyAccessExpression(node) || ts.isElementAccessExpression(node)) &&
			API_NAMES.has(propertyName(node, ts)) && !isInvokedProperty(node, ts)) {
			result.push({api: propertyName(node, ts), snippet: normalizeSnippet(node, sourceFile)});
		}
		ts.forEachChild(node, visit);
	}
	visit(sourceFile);
	return result;
}

function scan(showdownDir) {
	const ts = require(path.join(showdownDir, 'node_modules/typescript'));
	const simDir = path.join(showdownDir, 'sim');
	const records = [];
	for (const absolute of walkFiles(simDir).sort()) {
		const relative = path.relative(showdownDir, absolute).split(path.sep).join('/');
		const text = fs.readFileSync(absolute, 'utf8');
		const sourceFile = ts.createSourceFile(absolute, text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS);
		function append(kind, node, extra = {}) {
			const at = position(node, sourceFile);
			records.push({kind, path: relative, ...at, ...extra, snippet: normalizeSnippet(node, sourceFile)});
		}
		function visit(node) {
			if (ts.isCallExpression(node)) {
				const api = propertyName(node.expression, ts);
				if (API_NAMES.has(api)) append('api-call', node, {
					api, arguments: node.arguments.map(argument => normalizeSnippet(argument, sourceFile)),
					mutation_role: relative === 'sim/battle-stream.ts' ? 'debug/test-only' : 'lifecycle-owning',
				});
			}
			if ((ts.isPropertyAccessExpression(node) || ts.isElementAccessExpression(node)) &&
				API_NAMES.has(propertyName(node, ts)) && !isInvokedProperty(node, ts)) {
				append('method-reference', node, {
					api: propertyName(node, ts),
					mutation_role: relative === 'sim/battle-stream.ts' ? 'debug/test-only' : 'lifecycle-owning',
				});
			}
			if (ts.isDeleteExpression(node)) {
				const access = containerAccess(node.expression, ts);
				if (access) append('direct-delete', node, {...access,
					mutation_role: isLifecycleDepth(access) ? 'lifecycle-owning' : 'payload-only'});
			}
			if (ts.isBinaryExpression(node) &&
				node.operatorToken.kind >= ts.SyntaxKind.FirstAssignment &&
				node.operatorToken.kind <= ts.SyntaxKind.LastAssignment) {
				const access = containerAccess(node.left, ts);
				const scalar = directScalar(node.left, ts);
				if (access || scalar) append('direct-assignment', node, {
					...(access || {}), ...(scalar ? {scalar} : {}),
					mutation_role: DESCRIPTOR_CONSTRUCTION_FILES.has(relative) ||
						(access && !isLifecycleDepth(access)) ? 'payload-only' : 'lifecycle-owning',
					operator: node.operatorToken.getText(sourceFile),
				});
			}
			ts.forEachChild(node, visit);
		}
		visit(sourceFile);
	}
	return records.sort((left, right) =>
		`${left.path}:${String(left.line).padStart(6, '0')}:${String(left.column).padStart(4, '0')}:${left.kind}`
			.localeCompare(`${right.path}:${String(right.line).padStart(6, '0')}:${String(right.column).padStart(4, '0')}:${right.kind}`));
}

function identity(record) {
	return [record.kind, record.path, record.line, record.column,
		record.api || record.container || record.scalar || '', record.snippet].join('|');
}

module.exports = {
	API_NAMES, DESCRIPTOR_CONSTRUCTION_FILES, identity, scan, scanFunctionConditionCalls,
	scanFunctionConditionReferences, scanFunctionDirectConditionMutations,
};

if (require.main === module) {
	const showdownDir = process.env.POKEMON_SHOWDOWN_DIR || process.argv[2];
	if (!showdownDir) throw new Error('POKEMON_SHOWDOWN_DIR or argv[2] must name pinned Showdown');
	process.stdout.write(`${JSON.stringify(scan(path.resolve(showdownDir)), null, 2)}\n`);
}
