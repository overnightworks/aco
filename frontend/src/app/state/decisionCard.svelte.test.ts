import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import type { postDecision } from '../../client';
import {
	cardOption,
	item,
	optionLine,
	readyBoard,
	repo,
	ruledOptionLine,
	storedAnswer
} from '../../test-support/board';
import type { DecisionResult, OptionLine } from '../../types';
import type { Pick } from '../model/card';
import { cardKey, LINE_CHANGED_MESSAGE, pointKey, UNDO_SECONDS } from '../model/decision';
import { DecisionStore } from './decision.svelte';

const optionA = cardOption({ name: 'Keep it open' });
const optionB = cardOption({ letter: 'B', name: 'As today' });

function point(index: number, overrides: Partial<OptionLine> = {}): OptionLine {
	return optionLine({
		index,
		fingerprint: `fp-${index}`,
		area: 'Song-Seite',
		options: [optionA, optionB],
		...overrides
	});
}

const points = [point(2), point(3), point(5)];
const key = cardKey('repo', 7);
const name = 'Song-Seite · 3 points';

function pickOf(shown: OptionLine | undefined, option = optionB): Pick {
	if (shown === undefined) throw new Error('no such point');
	return { shown, option };
}

function lineOf(index: number, option: string) {
	return { line: index, fingerprint: `fp-${index}`, option };
}

const storedCard = item({
	number: 7,
	lines: points.map(({ index }) => ruledOptionLine({ index }))
});
const oneStored = item({
	number: 7,
	lines: [ruledOptionLine({ index: 2 }), points[1] as OptionLine, points[2] as OptionLine]
});

function setup(result: DecisionResult = storedAnswer(storedCard)) {
	const send = vi.fn(async () => result) as unknown as typeof postDecision;
	const { store: board, wiring, reads } = readyBoard([repo({ items: [item({ number: 7 })] })]);
	return { send, board, reads, store: new DecisionStore('token', wiring, send) };
}

beforeEach(() => {
	vi.useFakeTimers();
});

afterEach(() => {
	vi.useRealTimers();
});

describe('picking on a card of points', () => {
	test('[ABRD-86] a pick answers its point alone: one strip, then one post naming only that line', async () => {
		const { send, store } = setup(storedAnswer(oneStored));

		store.choose('repo', 7, points, pickOf(points[0]));

		expect(store.pendingEntries).toEqual([
			{ key: `${key}:2`, message: `1B · ${name}`, state: 'done' }
		]);
		await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000 - 1);
		expect(send).not.toHaveBeenCalled();
		await vi.advanceTimersByTimeAsync(1);
		expect(send).toHaveBeenCalledTimes(1);
		expect(send).toHaveBeenCalledWith('token', {
			repo: 'repo',
			item: 7,
			lines: [lineOf(2, 'B')]
		});
	});

	test('[ABRD-86] two picks are two windows and two writes, each naming its own line', async () => {
		const { send, store } = setup(storedAnswer(oneStored));

		store.choose('repo', 7, points, pickOf(points[0], optionB));
		store.choose('repo', 7, points, pickOf(points[2], optionA));
		await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

		expect(send).toHaveBeenCalledTimes(2);
		expect(send).toHaveBeenCalledWith(
			'token',
			expect.objectContaining({ lines: [lineOf(2, 'B')] })
		);
		expect(send).toHaveBeenCalledWith(
			'token',
			expect.objectContaining({ lines: [lineOf(5, 'A')] })
		);
	});

	test('[ABRD-97] a waiting point is told from the others, and clears once its post is answered', async () => {
		const { store } = setup(storedAnswer(oneStored));

		store.choose('repo', 7, points, pickOf(points[1]));

		expect([...store.waitingIndexes(key)]).toEqual([3]);
		expect(store.waitingIndexes(cardKey('repo', 8)).size).toBe(0);
		await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);
		expect(store.waitingIndexes(key).size).toBe(0);
	});

	test('[ABRD-99] the card holds the picks of every waiting point, none while nothing waits', async () => {
		const { store } = setup(storedAnswer(oneStored));
		expect(store.held(key)).toBeNull();

		store.choose('repo', 7, points, pickOf(points[0], optionA));
		store.choose('repo', 7, points, pickOf(points[1], optionB));

		expect(store.held(key)?.map((held) => held.option.letter)).toEqual(['A', 'B']);
		await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);
		expect(store.held(key)).toBeNull();
	});

	test('[ABRD-100] the card saves from the end of the window until its post is answered', async () => {
		let answer: (result: DecisionResult) => void = () => undefined;
		const send = vi.fn(
			() =>
				new Promise<DecisionResult>((resolve) => {
					answer = resolve;
				})
		) as unknown as typeof postDecision;
		const { wiring } = readyBoard([repo({ items: [item({ number: 7 })] })]);
		const store = new DecisionStore('token', wiring, send);
		store.choose('repo', 7, points, pickOf(points[0]));
		expect(store.isSaving(key)).toBe(false);

		await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

		expect(store.isSaving(key)).toBe(true);
		expect([...store.waitingIndexes(key)]).toEqual([2]);
		answer(storedAnswer(oneStored));
		await vi.advanceTimersByTimeAsync(0);
		expect(store.isSaving(key)).toBe(false);
	});

	test('[ABRD-87] Undo of a pick posts nothing for it and frees its point, the others stay waiting', async () => {
		const { send, store } = setup(storedAnswer(oneStored));
		store.choose('repo', 7, points, pickOf(points[0]));
		store.choose('repo', 7, points, pickOf(points[1]));

		store.undo(`${key}:2`);
		await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

		expect(send).toHaveBeenCalledTimes(1);
		expect(send).toHaveBeenCalledWith(
			'token',
			expect.objectContaining({ lines: [lineOf(3, 'B')] })
		);
	});

	test('[ABRD-44] a stored point shows its item in place and names the card as just ruled', async () => {
		const { board, reads, store } = setup(storedAnswer(oneStored));
		store.choose('repo', 7, points, pickOf(points[0]));

		await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

		expect(board.repos[0]?.items).toEqual([oneStored]);
		expect(reads()).toBe(0);
		expect(store.justRuled).toBe(key);
		store.acknowledgeRuled();
		expect(store.justRuled).toBeNull();
	});

	test('[ABRD-98] a waiting point of one card leaves the other card’s points free', () => {
		const { store } = setup();
		store.choose('repo', 8, points, pickOf(points[0]));

		store.choose('repo', 7, points, pickOf(points[1]));

		expect([...store.waitingIndexes(cardKey('repo', 8))]).toEqual([2]);
		expect([...store.waitingIndexes(key)]).toEqual([3]);
	});

	test('[ABRD-85] a point opens when toggled, another toggle closes any other, the same one closes it', () => {
		const { store } = setup();

		expect(store.openPoint(key)).toBeNull();
		store.togglePoint(key, 3);
		store.togglePoint(key, 5);
		expect(store.openPoint(key)).toBe(5);
		store.togglePoint(key, 5);
		expect(store.openPoint(key)).toBeNull();
	});

	test('[ABRD-44] a one-point card starts its window with the pick itself, named by letter, option and topic', async () => {
		const { send, store } = setup();
		const only = point(4, { topic: 'Jump' });

		store.choose('repo', 7, [only], pickOf(only));

		expect(store.pendingEntries).toEqual([
			{ key: `${key}:4`, message: 'B — As today · Jump', state: 'done' }
		]);
		await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);
		expect(send).toHaveBeenCalledWith('token', {
			repo: 'repo',
			item: 7,
			lines: [lineOf(4, 'B')]
		});
	});
});

describe('Accept all', () => {
	const recommending = [
		point(2, { recommended: 'A' }),
		point(3, { recommended: 'B' }),
		point(5, { recommended: 'A' })
	];

	test('[ABRD-89] picks each recommended letter in one window and one write', async () => {
		const { send, store } = setup();

		store.acceptAll('repo', 7, recommending);

		expect(store.pendingEntries).toEqual([
			{ key: `${key}:2,3,5`, message: `1A 2B 3A · ${name}`, state: 'done' }
		]);
		await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);
		expect(send).toHaveBeenCalledTimes(1);
		expect(send).toHaveBeenCalledWith('token', {
			repo: 'repo',
			item: 7,
			lines: [lineOf(2, 'A'), lineOf(3, 'B'), lineOf(5, 'A')]
		});
	});

	test('[ABRD-89] after a pick is stored it posts the points still open, once', async () => {
		const { send, store } = setup(storedAnswer(oneStored));
		store.choose('repo', 7, recommending, pickOf(recommending[0], optionB));
		await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

		store.acceptAll('repo', 7, recommending.slice(1));
		await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

		expect(send).toHaveBeenCalledTimes(2);
		expect(send).toHaveBeenLastCalledWith('token', {
			repo: 'repo',
			item: 7,
			lines: [lineOf(3, 'B'), lineOf(5, 'A')]
		});
	});

	test('[ABRD-89] it skips the points that wait and numbers the strip among all the points', async () => {
		const { send, store } = setup(storedAnswer(oneStored));
		store.choose('repo', 7, recommending, pickOf(recommending[0], optionB));

		store.acceptAll('repo', 7, recommending);

		expect(store.pendingEntries.map((entry) => entry.message)).toEqual([
			`1B · ${name}`,
			`2B 3A · ${name}`
		]);
		await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);
		expect(send).toHaveBeenCalledWith(
			'token',
			expect.objectContaining({ lines: [lineOf(3, 'B'), lineOf(5, 'A')] })
		);
	});

	test('[ABRD-89] Undo after Accept all posts nothing', async () => {
		const { send, store } = setup();
		store.acceptAll('repo', 7, recommending);

		store.undo(`${key}:2,3,5`);
		await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

		expect(send).not.toHaveBeenCalled();
		expect(store.waitingIndexes(key).size).toBe(0);
	});

	test('[ABRD-89] a point whose recommendation names no option stays open, the others post', async () => {
		const { send, store } = setup();
		const broken = [point(2), point(3, { recommended: 'D' })];

		store.acceptAll('repo', 7, broken);
		await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

		expect(send).toHaveBeenCalledWith(
			'token',
			expect.objectContaining({ lines: [lineOf(2, 'A')] })
		);
	});

	test('[ABRD-89] with no valid recommendation, or every point waiting, nothing new waits', () => {
		const { store } = setup();
		store.acceptAll('repo', 7, [point(2, { recommended: 'D' })]);
		expect(store.pendingEntries).toEqual([]);

		store.acceptAll('repo', 7, recommending);
		store.acceptAll('repo', 7, recommending);

		expect(store.pendingEntries).toHaveLength(1);
	});
});

describe('a refused post', () => {
	test('[ABRD-45] "Neu laden" after a changed refusal drops the banner and re-reads', async () => {
		const { reads, store } = setup({ status: 'failed', message: LINE_CHANGED_MESSAGE });
		store.choose('repo', 7, points, pickOf(points[0]));
		await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);
		expect(store.banner(key)?.kind).toBe('changed');

		await store.reloadAfterBanner(key);

		expect(store.banner(key)).toBeNull();
		expect(reads()).toBe(1);
	});

	test('[ABRD-45] a failed point shows open again with the banner, and picking again posts again', async () => {
		const { send, store } = setup({ status: 'failed', message: 'aco unavailable' });
		store.choose('repo', 7, points, pickOf(points[0]));
		await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);
		expect(store.banner(key)).toEqual({ kind: 'failed', message: 'aco unavailable' });
		expect(store.waitingIndexes(key).size).toBe(0);

		store.choose('repo', 7, points, pickOf(points[0], optionA));
		await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

		expect(send).toHaveBeenCalledTimes(2);
		expect(send).toHaveBeenLastCalledWith(
			'token',
			expect.objectContaining({ lines: [lineOf(2, 'A')] })
		);
	});
});

describe('Other and Unclear on a card of points', () => {
	test('[ABRD-154] Other answers its point alone, with its own strip and the text it was given', async () => {
		const { send, store } = setup(storedAnswer(oneStored));
		const second = point(3, { topic: 'Library' });

		store.decideOther('repo', 7, second, '  Only on desktop ');

		expect(store.pendingEntries).toEqual([
			{ key: `${key}:3`, message: 'Other · Library', state: 'done' }
		]);
		await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);
		expect(send).toHaveBeenCalledWith('token', {
			repo: 'repo',
			item: 7,
			lines: [{ line: 3, fingerprint: 'fp-3' }],
			other: 'Only on desktop'
		});
	});

	test('[ABRD-92] Unclear covers the points not waiting and waits as a With head strip', async () => {
		const { send, store } = setup(storedAnswer(storedCard, 'returned'));
		store.choose('repo', 7, points, pickOf(points[0]));

		store.decideUnclear('repo', 7, points, ' Why? ');

		expect(store.pendingEntries.map(({ key: entry, state }) => [entry, state])).toEqual([
			[`${key}:2`, 'done'],
			[`${key}:3,5`, 'back']
		]);
		await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);
		expect(send).toHaveBeenCalledWith('token', {
			repo: 'repo',
			item: 7,
			lines: [
				{ line: 3, fingerprint: 'fp-3' },
				{ line: 5, fingerprint: 'fp-5' }
			],
			unclear: true,
			note: 'Why?'
		});
		expect(store.justReturned).toBe(key);
	});

	test('[ABRD-92] Unclear starts nothing while every point waits', () => {
		const { store } = setup();
		store.acceptAll('repo', 7, points);

		store.decideUnclear('repo', 7, points, '');

		expect(store.pendingEntries).toHaveLength(1);
	});

	test('[ABRD-154] Undo of an Other answer reopens its point’s panel and keeps its draft', async () => {
		const { send, store } = setup();
		const second = points[1] as OptionLine;
		const panelKey = pointKey('repo', 7, 3);
		store.setDraft(panelKey, 'other', 'x');

		store.decideOther('repo', 7, second, 'x');
		store.undo(`${key}:3`);
		await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

		expect(send).not.toHaveBeenCalled();
		expect(store.panel(panelKey)).toEqual({ kind: 'other', shown: [second] });
		expect(store.draft(panelKey, 'other')).toBe('x');
	});

	test('[ABRD-66] the Other draft is kept per point, and a stored point drops only its own', async () => {
		const { store } = setup(storedAnswer(oneStored));
		const first = pointKey('repo', 7, 2);
		const second = pointKey('repo', 7, 3);
		store.setDraft(first, 'other', 'one');
		store.setDraft(second, 'other', 'two');

		store.choose('repo', 7, points, pickOf(points[0]));
		await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

		expect(store.draft(first, 'other')).toBe('');
		expect(store.draft(second, 'other')).toBe('two');
	});
});
