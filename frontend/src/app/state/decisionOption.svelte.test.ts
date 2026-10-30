import { afterEach, beforeEach, expect, test, vi } from 'vitest';
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
import type { DecisionResult } from '../../types';
import {
	ALREADY_RULED_MESSAGE,
	cardKey,
	LINE_CHANGED_MESSAGE,
	UNDO_SECONDS
} from '../model/decision';
import { DecisionStore } from './decision.svelte';

const optionA = cardOption({ name: 'Song stays open' });
const optionB = cardOption({ letter: 'B', name: 'As today' });
const card = optionLine({
	index: 3,
	fingerprint: 'fp-option',
	topic: 'Jump',
	options: [optionA, optionB]
});
const key = cardKey('repo', 42);
const points = [card];
const storedCard = item({ number: 42, lines: [ruledOptionLine({ index: 3 })] });

function sender(result: DecisionResult): typeof postDecision {
	return vi.fn(async () => result) as unknown as typeof postDecision;
}

beforeEach(() => {
	vi.useFakeTimers();
});

afterEach(() => {
	vi.useRealTimers();
});

test('[ABRD-44] a one-point card’s pick sends nothing before the window ends, then exactly the card with the picked letter', async () => {
	const send = sender(storedAnswer(storedCard));
	const store = new DecisionStore('token', readyBoard().wiring, send);

	store.choose('repo', 42, points, { shown: card, option: optionB });
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000 - 1);
	expect(send).not.toHaveBeenCalled();
	await vi.advanceTimersByTimeAsync(1);

	expect(send).toHaveBeenCalledTimes(1);
	expect(send).toHaveBeenCalledWith('token', {
		repo: 'repo',
		item: 42,
		lines: [{ line: 3, fingerprint: 'fp-option', option: 'B' }]
	});
});

test('[ABRD-33] undoing a pick inside the window sends nothing, and the card is no longer pending', async () => {
	const send = sender(storedAnswer(storedCard));
	const { wiring, reads } = readyBoard();
	const store = new DecisionStore('token', wiring, send);

	store.choose('repo', 42, points, { shown: card, option: optionA });
	expect(store.isPending(key)).toBe(true);
	store.undo(key);
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

	expect(store.isPending(key)).toBe(false);
	expect(send).not.toHaveBeenCalled();
	expect(reads()).toBe(0);
});

test('[ABRD-44] a stored pick shows its item in place and names the card as just ruled', async () => {
	const { store: board, wiring, reads } = readyBoard([repo({ items: [item({ number: 42 })] })]);
	const store = new DecisionStore('token', wiring, sender(storedAnswer(storedCard)));

	store.choose('repo', 42, points, { shown: card, option: optionA });
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

	expect(board.repos[0]?.items).toEqual([storedCard]);
	expect(reads()).toBe(0);
	expect(store.justRuled).toBe(key);
});

test.each([
	[{ status: 'failed', message: LINE_CHANGED_MESSAGE }, 'changed', LINE_CHANGED_MESSAGE],
	[
		{ status: 'already_ruled', message: 'line 3 is already ruled' },
		'already-ruled',
		ALREADY_RULED_MESSAGE
	],
	[{ status: 'failed', message: 'aco unavailable' }, 'failed', 'aco unavailable']
] as const)('a refused pick (%j) shows a %s banner', async (result, kind, message) => {
	const store = new DecisionStore('token', readyBoard().wiring, sender(result));

	store.choose('repo', 42, points, { shown: card, option: optionA });
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

	expect(store.banner(key)).toEqual({ kind, message });
	expect(store.justRuled).toBeNull();
});

test('[ABRD-44] a pending pick names its letter, option and topic for the strip', () => {
	const store = new DecisionStore('token', readyBoard().wiring, sender(storedAnswer(storedCard)));

	store.choose('repo', 42, points, { shown: card, option: optionB });

	expect(store.pendingEntries).toEqual([{ key, message: 'B — As today · Jump', state: 'done' }]);
});
