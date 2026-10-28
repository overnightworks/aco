import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import type { postDecision } from '../../client';
import { cardOption, item, optionLine, repo } from '../../test-support/board';
import type { DecisionResult, OptionLine } from '../../types';
import type { Pick } from '../model/card';
import { cardKey, LINE_CHANGED_MESSAGE, UNDO_SECONDS } from '../model/decision';
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

function setup(result: DecisionResult = { status: 'ruled', message: null }) {
	const send = vi.fn(async () => result) as unknown as typeof postDecision;
	const reload = vi.fn(async () => {});
	return { send, reload, store: new DecisionStore('token', reload, send) };
}

function chooseAll(store: DecisionStore, letters: Pick[] = points.map((shown) => pickOf(shown))) {
	for (const pick of letters) store.choose('repo', 7, points, pick);
}

beforeEach(() => {
	vi.useFakeTimers();
});

afterEach(() => {
	vi.useRealTimers();
});

describe('picking on a card of points', () => {
	test('[ABRD-86] a pick marks its point and posts nothing, however long it waits', async () => {
		const { send, store } = setup();

		store.choose('repo', 7, points, pickOf(points[0]));
		await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 2000);

		expect(store.picks(key, points).map((pick) => pick.shown.index)).toEqual([2]);
		expect(store.isPending(key)).toBe(false);
		expect(send).not.toHaveBeenCalled();
	});

	test('[ABRD-86] picking a point again changes its letter', () => {
		const { store } = setup();

		store.choose('repo', 7, points, pickOf(points[0], optionA));
		store.choose('repo', 7, points, pickOf(points[0], optionB));

		expect(store.picks(key, points).map((pick) => pick.option.letter)).toEqual(['B']);
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

	test('[ABRD-86] a pick on the open point opens the first unchosen point', () => {
		const { store } = setup();
		store.togglePoint(key, 2);

		store.choose('repo', 7, points, pickOf(points[0]));

		expect(store.openPoint(key)).toBe(3);
	});

	test('[ABRD-86] a pick on another point leaves the open point', () => {
		const { store } = setup();
		store.togglePoint(key, 3);

		store.choose('repo', 7, points, pickOf(points[0]));

		expect(store.openPoint(key)).toBe(3);
	});

	test('[ABRD-86] the picks of one card do not touch another card’s', () => {
		const { store } = setup();
		const otherKey = cardKey('repo', 8);

		store.choose('repo', 7, points, pickOf(points[0]));

		expect(store.picks(otherKey, points)).toEqual([]);
		expect(store.picks(key, points)).toHaveLength(1);
	});
});

describe('the last pick', () => {
	test('[ABRD-87] starts one window with one strip, then posts the card once with every pick', async () => {
		const { send, store } = setup();

		chooseAll(store, [
			pickOf(points[0], optionB),
			pickOf(points[1], optionA),
			pickOf(points[2], optionA)
		]);

		expect(store.pendingEntries).toEqual([{ key, message: `1B 2A 3A · ${name}`, state: 'done' }]);
		await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000 - 1);
		expect(send).not.toHaveBeenCalled();
		await vi.advanceTimersByTimeAsync(1);
		expect(send).toHaveBeenCalledTimes(1);
		expect(send).toHaveBeenCalledWith('token', {
			repo: 'repo',
			item: 7,
			lines: [
				{ line: 2, fingerprint: 'fp-2', option: 'B' },
				{ line: 3, fingerprint: 'fp-3', option: 'A' },
				{ line: 5, fingerprint: 'fp-5', option: 'A' }
			]
		});
	});

	test('[ABRD-87] Undo posts nothing and clears the picks', async () => {
		const { send, store } = setup();
		chooseAll(store);

		store.undo(key);
		await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

		expect(send).not.toHaveBeenCalled();
		expect(store.picks(key, points)).toEqual([]);
		expect(store.isPending(key)).toBe(false);
	});

	test('[ABRD-44] a stored card reloads the board, drops its picks and names the card as just ruled', async () => {
		const { reload, store } = setup();
		chooseAll(store);

		await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

		expect(reload).toHaveBeenCalledTimes(1);
		expect(store.justRuled).toBe(key);
		expect(store.picks(key, points)).toEqual([]);
	});

	test('[ABRD-44] a one-point card starts its window with the pick itself, named by letter, option and topic', async () => {
		const { send, store } = setup();
		const only = point(4, { topic: 'Jump' });

		store.choose('repo', 7, [only], pickOf(only));

		expect(store.pendingEntries).toEqual([{ key, message: 'B — As today · Jump', state: 'done' }]);
		await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);
		expect(send).toHaveBeenCalledWith('token', {
			repo: 'repo',
			item: 7,
			lines: [{ line: 4, fingerprint: 'fp-4', option: 'B' }]
		});
	});
});

describe('Accept all', () => {
	test('[ABRD-89] picks each recommended letter, replacing earlier picks, and starts the window', async () => {
		const { send, store } = setup();
		const recommending = [
			point(2, { recommended: 'A' }),
			point(3, { recommended: 'B' }),
			point(5, { recommended: 'A' })
		];
		store.choose('repo', 7, recommending, pickOf(recommending[0], optionB));

		store.acceptAll('repo', 7, recommending);

		expect(store.pendingEntries).toEqual([{ key, message: `1A 2B 3A · ${name}`, state: 'done' }]);
		expect(store.openPoint(key)).toBeNull();
		await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);
		expect(send).toHaveBeenCalledTimes(1);
	});

	test('[ABRD-89] Undo after Accept all posts nothing and clears the picks', async () => {
		const { send, store } = setup();
		store.acceptAll('repo', 7, points);

		store.undo(key);
		await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

		expect(send).not.toHaveBeenCalled();
		expect(store.picks(key, points)).toEqual([]);
	});

	test('[ABRD-89] a point whose recommendation names no option leaves the card incomplete, so nothing waits', () => {
		const { store } = setup();
		const broken = [point(2), point(3, { recommended: 'D' })];

		store.acceptAll('repo', 7, broken);

		expect(store.isPending(key)).toBe(false);
		expect(store.picks(key, broken)).toHaveLength(1);
	});
});

describe('the card as shown', () => {
	test('[ABRD-91] a re-read drops the pick of a changed point and keeps the others', () => {
		const { store } = setup();
		store.choose('repo', 7, points, pickOf(points[0]));
		store.choose('repo', 7, points, pickOf(points[1]));
		const reread = [
			points[0] as OptionLine,
			point(3, { fingerprint: 'fp-new' }),
			points[2] as OptionLine
		];

		const indexes = store.picks(key, reread).map((pick) => pick.shown.index);

		expect(indexes).toEqual([2]);
	});

	test('[ABRD-91] the next post names the fresh fingerprint of a point picked again', async () => {
		const { send, store } = setup();
		store.choose('repo', 7, points, pickOf(points[0]));
		store.choose('repo', 7, points, pickOf(points[1]));
		const fresh = point(3, { fingerprint: 'fp-new' });
		const reread = [points[0] as OptionLine, fresh, points[2] as OptionLine];

		store.choose('repo', 7, reread, pickOf(fresh));
		store.choose('repo', 7, reread, pickOf(points[2]));
		await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

		expect(send).toHaveBeenCalledWith(
			'token',
			expect.objectContaining({
				lines: [
					expect.objectContaining({ line: 2, fingerprint: 'fp-2' }),
					expect.objectContaining({ line: 3, fingerprint: 'fp-new' }),
					expect.objectContaining({ line: 5, fingerprint: 'fp-5' })
				]
			})
		);
	});

	test('[ABRD-91] a point added since shows unchosen, so the last old pick starts no window', () => {
		const { store } = setup();
		const grown = [...points, point(7)];

		for (const shown of points) store.choose('repo', 7, grown, pickOf(shown));

		expect(store.isPending(key)).toBe(false);
		expect(store.picks(key, grown)).toHaveLength(3);
	});

	test('[ABRD-91] a re-read during the window leaves it running with the card as picked', async () => {
		const { send, store } = setup();
		chooseAll(store);
		const reread = [point(2, { fingerprint: 'fp-new' })];

		expect(store.picks(key, reread)).toEqual([]);
		await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

		expect(send).toHaveBeenCalledWith(
			'token',
			expect.objectContaining({
				lines: [
					expect.objectContaining({ fingerprint: 'fp-2' }),
					expect.objectContaining({ fingerprint: 'fp-3' }),
					expect.objectContaining({ fingerprint: 'fp-5' })
				]
			})
		);
	});
});

function readingOf(shown: OptionLine[]) {
	return [repo({ name: 'repo', items: [item({ number: 7, lines: shown })] })];
}

describe('picks across re-reads', () => {
	test('[ABRD-91] a point that changed and returned to its old fingerprint does not revive its pick', () => {
		const { store } = setup();
		store.choose('repo', 7, points, pickOf(points[0]));
		store.choose('repo', 7, points, pickOf(points[1]));
		const changed = [
			points[0] as OptionLine,
			point(3, { fingerprint: 'fp-new' }),
			points[2] as OptionLine
		];

		store.reconcilePicks(readingOf(changed));
		store.reconcilePicks(readingOf([...points]));

		expect(store.picks(key, points).map((pick) => pick.shown.index)).toEqual([2]);
	});

	test('[ABRD-91] a card that disappears from a successful re-read does not revive its picks', () => {
		const { store } = setup();
		store.choose('repo', 7, points, pickOf(points[0]));

		store.reconcilePicks(readingOf([]));
		store.reconcilePicks(readingOf([...points]));

		expect(store.picks(key, points)).toHaveLength(0);
	});

	test('[ABRD-91] a repo that failed to read keeps the picks of its cards', () => {
		const { store } = setup();
		store.choose('repo', 7, points, pickOf(points[0]));

		store.reconcilePicks([repo({ name: 'repo', error: 'offline', items: [] })]);
		store.reconcilePicks(readingOf([...points]));

		expect(store.picks(key, points)).toHaveLength(1);
	});

	test('[ABRD-91] a repo whose name extends a readable repo name keeps its picks while it fails to read', () => {
		const { store } = setup();
		store.choose('repo:child', 7, points, pickOf(points[0]));

		store.reconcilePicks([
			repo({ name: 'repo', items: [] }),
			repo({ name: 'repo:child', error: 'offline', items: [] })
		]);

		expect(store.picks('repo:child:7:card', points)).toHaveLength(1);
	});

	test('[ABRD-91] a re-read keeps the picks of unchanged points', () => {
		const { store } = setup();
		store.choose('repo', 7, points, pickOf(points[0]));

		store.reconcilePicks(readingOf([...points]));

		expect(store.picks(key, points)).toHaveLength(1);
	});
});

describe('a refused card', () => {
	test('[ABRD-45] "Neu laden" after a changed refusal drops the banner and keeps the picks of unchanged points', async () => {
		const { reload, store } = setup({ status: 'failed', message: LINE_CHANGED_MESSAGE });
		chooseAll(store);
		await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);
		expect(store.banner(key)?.kind).toBe('changed');
		expect(store.picks(key, points)).toHaveLength(3);

		await store.reloadAfterBanner(key);

		expect(store.banner(key)).toBeNull();
		expect(store.picks(key, points)).toHaveLength(3);
		expect(reload).toHaveBeenCalledTimes(1);
	});

	test('[ABRD-45] any other failure keeps the picks, and picking again posts again', async () => {
		const { send, store } = setup({ status: 'failed', message: 'aco unavailable' });
		chooseAll(store);
		await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);
		expect(store.banner(key)).toEqual({ kind: 'failed', message: 'aco unavailable' });

		store.choose('repo', 7, points, pickOf(points[0], optionA));
		await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

		expect(send).toHaveBeenCalledTimes(2);
		expect(send).toHaveBeenLastCalledWith(
			'token',
			expect.objectContaining({
				lines: [
					expect.objectContaining({ line: 2, option: 'A' }),
					expect.objectContaining({ line: 3, option: 'B' }),
					expect.objectContaining({ line: 5, option: 'B' })
				]
			})
		);
	});
});

describe('Other and Unclear for the whole card', () => {
	test('[ABRD-92] Other waits out the window with one strip and posts every point with the same text', async () => {
		const { send, store } = setup();

		store.decideOther('repo', 7, points, '  Only on desktop ');

		expect(store.pendingEntries).toEqual([{ key, message: `Other · ${name}`, state: 'done' }]);
		await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);
		expect(send).toHaveBeenCalledWith('token', {
			repo: 'repo',
			item: 7,
			lines: [
				{ line: 2, fingerprint: 'fp-2' },
				{ line: 3, fingerprint: 'fp-3' },
				{ line: 5, fingerprint: 'fp-5' }
			],
			other: 'Only on desktop'
		});
	});

	test('[ABRD-92] Unclear waits as a With head strip and posts every point with the note', async () => {
		const { send, store } = setup({ status: 'returned', message: null });

		store.decideUnclear('repo', 7, points, ' Why? ');

		expect(store.pendingEntries).toEqual([{ key, message: name, state: 'back' }]);
		await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);
		expect(send).toHaveBeenCalledWith('token', {
			repo: 'repo',
			item: 7,
			lines: [
				{ line: 2, fingerprint: 'fp-2' },
				{ line: 3, fingerprint: 'fp-3' },
				{ line: 5, fingerprint: 'fp-5' }
			],
			unclear: true,
			note: 'Why?'
		});
		expect(store.justReturned).toBe(key);
	});

	test('[ABRD-92] Undo of an Other answer keeps the picks already made and reopens the panel', async () => {
		const { send, store } = setup();
		store.choose('repo', 7, points, pickOf(points[0]));

		store.decideOther('repo', 7, points, 'x');
		store.undo(key);
		await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

		expect(send).not.toHaveBeenCalled();
		expect(store.picks(key, points)).toHaveLength(1);
		expect(store.panel(key)).toEqual({ kind: 'other', shown: points });
	});

	test('[ABRD-66] the draft of a card of points is kept per card', () => {
		const { store } = setup();

		store.setDraft(key, 'other', 'Only on desktop');

		expect(store.draft(key, 'other')).toBe('Only on desktop');
		expect(store.draft(cardKey('repo', 8), 'other')).toBe('');
	});
});
