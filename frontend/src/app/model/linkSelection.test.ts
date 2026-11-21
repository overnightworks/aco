import { expect, test } from 'vitest';
import { item, line, optionLine, repo, ruledOptionLine, stepRead } from '../../test-support/board';
import { linkFromHash, resolveLink, stepKey } from './linkSelection';

test.each([
	['#t=secret&c=acme/widgets/12/3', { kind: 'card', repo: 'acme/widgets', item: 12, line: 3 }],
	['#c=acme/widgets/12/3&t=secret', { kind: 'card', repo: 'acme/widgets', item: 12, line: 3 }],
	['#t=secret&s=acme/widgets/12', { kind: 'step', repo: 'acme/widgets', item: 12 }]
])('the fragment %s names its card or step', (hash, expected) => {
	expect(linkFromHash(hash)).toEqual(expected);
});

test.each([
	'',
	'#t=secret',
	'#c=acme/widgets/12',
	'#c=acme/widgets/x/3',
	'#s=widgets',
	'#s=a/b/-1'
])('the fragment %s names no card or step', (hash) => {
	expect(linkFromHash(hash)).toBeNull();
});

const OPEN = repo({
	name: 'acme/widgets',
	items: [
		item({ number: 12, lines: [optionLine({ index: 3 }), ruledOptionLine({ index: 4 })] }),
		item({ number: 13, lines: [line({ index: 1 })] })
	],
	steps: [stepRead({ number: 14 })]
});

test('an open card resolves to its card key', () => {
	expect(resolveLink([OPEN], { kind: 'card', repo: 'acme/widgets', item: 12, line: 3 })).toEqual({
		kind: 'card',
		key: 'acme/widgets:12:card'
	});
});

test.each([
	['a ruled option line', { item: 12, line: 4 }, 'Diese Karte ist schon entschieden.'],
	['a ruled yes/no line', { item: 13, line: 1 }, 'Diese Karte ist schon entschieden.'],
	['a line the item does not hold', { item: 12, line: 9 }, 'Diese Karte gibt es nicht mehr.'],
	['an item the board does not list', { item: 99, line: 1 }, 'Diese Karte gibt es nicht mehr.']
])('%s resolves to a note', (_name, target, note) => {
	expect(resolveLink([OPEN], { kind: 'card', repo: 'acme/widgets', ...target })).toEqual({
		kind: 'note',
		note
	});
});

test('a repository that could not be read resolves to the unreadable note', () => {
	const failed = repo({ name: 'acme/widgets', error: 'HTTP 502', items: [], steps: [] });

	expect(resolveLink([failed], { kind: 'card', repo: 'acme/widgets', item: 12, line: 3 })).toEqual({
		kind: 'note',
		note: 'Dieses Repo ist gerade nicht lesbar.'
	});
});

test('a repository the board does not serve resolves to the gone note', () => {
	expect(resolveLink([OPEN], { kind: 'step', repo: 'acme/other', item: 14 })).toEqual({
		kind: 'note',
		note: 'Dieser Schritt wartet nicht mehr.'
	});
});

test('a waiting step resolves to the step, one no longer waiting to a note', () => {
	expect(resolveLink([OPEN], { kind: 'step', repo: 'acme/widgets', item: 14 })).toEqual({
		kind: 'step',
		repo: 'acme/widgets',
		item: 14
	});
	expect(resolveLink([OPEN], { kind: 'step', repo: 'acme/widgets', item: 12 })).toEqual({
		kind: 'note',
		note: 'Dieser Schritt wartet nicht mehr.'
	});
});

test('a step is keyed by its repository and item', () => {
	expect(stepKey('acme/widgets', 14)).toBe('acme/widgets#14');
});
