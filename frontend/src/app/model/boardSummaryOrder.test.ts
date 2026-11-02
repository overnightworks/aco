import { describe, expect, test } from 'vitest';
import { item, line, optionLine, repo } from '../../test-support/board';
import {
	decidedList,
	firstDecidedKey,
	firstOpenKey,
	nextOpenAfter,
	openList
} from './boardSummary';

function openCard(
	number: number,
	askedOn: string,
	overrides: Parameters<typeof optionLine>[0] = {}
) {
	return item({ number, lines: [optionLine({ asked_on: askedOn, ...overrides })] });
}

function groupNames(list: { groups: { repo: string }[] }): string[] {
	return list.groups.map((group) => group.repo);
}

describe('open groups stand by their first row', () => {
	test('[ABRD-107] the repository with the newest card leads, whatever the configured order', () => {
		const list = openList([
			repo({ name: 'older', items: [openCard(1, '2026-10-01')] }),
			repo({ name: 'newer', items: [openCard(1, '2026-10-20')] })
		]);

		expect(groupNames(list)).toEqual(['newer', 'older']);
	});

	test('[ABRD-107] an open card leads over a newer card with its head', () => {
		const list = openList([
			repo({
				name: 'with-head',
				items: [openCard(1, '2026-10-20', { returned_on: '2026-10-27' })]
			}),
			repo({ name: 'open', items: [openCard(1, '2026-10-01')] })
		]);

		expect(groupNames(list)).toEqual(['open', 'with-head']);
	});

	test('[ABRD-107] on the same day the higher item leads, and on the same item the configured order stays', () => {
		const sameDay = openList([
			repo({ name: 'low', items: [openCard(3, '2026-10-20')] }),
			repo({ name: 'high', items: [openCard(9, '2026-10-20')] })
		]);
		const sameItem = openList([
			repo({ name: 'first', items: [openCard(3, '2026-10-20')] }),
			repo({ name: 'second', items: [openCard(3, '2026-10-20')] })
		]);

		expect(groupNames(sameDay)).toEqual(['high', 'low']);
		expect(groupNames(sameItem)).toEqual(['first', 'second']);
	});

	test('[ABRD-107] a group stands by its first row, which is aco order, not its newest card', () => {
		const list = openList([
			repo({ name: 'a', items: [openCard(1, '2026-10-02'), openCard(2, '2026-10-30')] }),
			repo({ name: 'b', items: [openCard(1, '2026-10-10')] })
		]);

		expect(groupNames(list)).toEqual(['b', 'a']);
		expect(list.groups[1]?.rows.map((row) => row.itemNumber)).toEqual([1, 2]);
	});

	test('[ABRD-107] [ABRD-49] a failed repository with kept cards stands by them, one without cards after every group, and the quiet line keeps configured order', () => {
		const list = openList([
			repo({ name: 'never-read', error: 'down', items: [] }),
			repo({ name: 'quiet-b', items: [] }),
			repo({ name: 'old', items: [openCard(1, '2026-10-01')] }),
			repo({ name: 'kept', error: 'down', items: [openCard(1, '2026-10-20')] }),
			repo({ name: 'quiet-a', items: [] })
		]);

		expect(groupNames(list)).toEqual(['kept', 'old', 'never-read']);
		expect(list.quiet).toEqual(['quiet-b', 'quiet-a']);
	});
});

describe('decided groups stand by their decision day', () => {
	const decided = (ruledOn: string) =>
		item({ number: 5, lines: [line({ ruling: 'yes', ruled_on: ruledOn })] });

	test('[ABRD-106] [ABRD-107] the group with the newest decision leads and its rows carry that day', () => {
		const list = decidedList([
			repo({ name: 'older', items: [decided('2026-10-01')] }),
			repo({ name: 'newer', items: [decided('2026-10-20')] })
		]);

		expect(groupNames(list)).toEqual(['newer', 'older']);
		expect(list.groups[0]?.rows.map((row) => row.day)).toEqual(['2026-10-20']);
	});
});

describe('the selection helpers follow the shown order', () => {
	const repos = [
		repo({
			name: 'older',
			items: [openCard(1, '2026-10-01'), openCard(2, '2026-10-02', { returned_on: '2026-10-03' })]
		}),
		repo({ name: 'newer', items: [openCard(1, '2026-10-20')] })
	];

	test('[ABRD-29] the first open key is the first row of the leading group', () => {
		expect(firstOpenKey(repos)).toBe('newer:1:card');
	});

	test('[ABRD-29] after a decision the next card is the first open one in shown order', () => {
		const spanning = [
			repo({ name: 'older', items: [openCard(1, '2026-10-01')] }),
			repo({ name: 'newer', items: [openCard(1, '2026-10-20'), openCard(2, '2026-10-21')] })
		];

		expect(nextOpenAfter(spanning, 'newer:2:card')).toBe('newer:1:card');
	});

	test('[ABRD-31] the first decided key is the first row of the leading group', () => {
		const decided = [
			repo({
				name: 'older',
				items: [item({ number: 1, lines: [line({ index: 1, ruled_on: '2026-10-01' })] })]
			}),
			repo({
				name: 'newer',
				items: [item({ number: 1, lines: [line({ index: 1, ruled_on: '2026-10-20' })] })]
			})
		];

		expect(firstDecidedKey(decided)).toBe('newer:1:1');
	});
});
