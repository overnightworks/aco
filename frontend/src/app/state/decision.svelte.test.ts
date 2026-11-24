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
import { cardKey, entryKey, pointKey, UNDO_SECONDS } from '../model/decision';
import { DecisionStore } from './decision.svelte';

const optionA = cardOption();
const optionB = cardOption({ letter: 'B', name: 'As today' });
const songCard = optionLine({
	index: 4,
	fingerprint: 'fp-shown',
	topic: 'Jump',
	options: [optionA, optionB]
});
const songKey = cardKey('repo', 42);
const songPoints = [songCard];
const songEntry = entryKey(songKey, [4]);
const songPanel = pointKey('repo', 42, 4);

function sender(result: DecisionResult): typeof postDecision {
	return vi.fn(async () => result) as unknown as typeof postDecision;
}

beforeEach(() => {
	vi.useFakeTimers();
});

afterEach(() => {
	vi.useRealTimers();
});

const storedSong = item({ number: 42, lines: [ruledOptionLine({ index: 4 })] });

test('undoing a key with nothing pending is a no-op', () => {
	const { wiring } = readyBoard();
	const store = new DecisionStore('token', wiring);

	expect(() => store.undo(songEntry)).not.toThrow();
});

test('once the window elapses, exactly one request is sent and the stored item shows in place', async () => {
	const send = sender(storedAnswer(storedSong));
	const { store: board, wiring, reads } = readyBoard([repo({ items: [item({ number: 42 })] })]);
	const store = new DecisionStore('token', wiring, send);

	store.choose('repo', 42, songPoints, { shown: songCard, option: optionB });
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

	expect(send).toHaveBeenCalledTimes(1);
	expect(send).toHaveBeenCalledWith('token', {
		repo: 'repo',
		item: 42,
		lines: [{ line: 4, fingerprint: 'fp-shown', option: 'B' }]
	});
	expect(board.repos[0]?.items).toEqual([storedSong]);
	expect(reads()).toBe(0);
	expect(store.held(songKey)).toBeNull();

	// Nothing fires again later: the timer was consumed, not merely delayed.
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);
	expect(send).toHaveBeenCalledTimes(1);
});

test('ABRD-130: a stored answer with a note shows its item, keeps the note and raises no banner', async () => {
	const send = sender(storedAnswer(storedSong, 'ruled', 'Written over a change.'));
	const { store: board, wiring } = readyBoard([repo({ items: [item({ number: 42 })] })]);
	const store = new DecisionStore('token', wiring, send);

	store.choose('repo', 42, songPoints, { shown: songCard, option: optionB });
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

	expect(board.repos[0]?.items).toEqual([storedSong]);
	expect(store.note(songKey)).toBe('Written over a change.');
	expect(store.banner(songKey)).toBeNull();
	expect(store.justRuled).toBe(songKey);
});

test('a stored answer without a note leaves its card without one', async () => {
	const { wiring } = readyBoard([repo({ items: [item({ number: 42 })] })]);
	const store = new DecisionStore('token', wiring, sender(storedAnswer(storedSong)));

	store.choose('repo', 42, songPoints, { shown: songCard, option: optionB });
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

	expect(store.note(songKey)).toBeNull();
});

test('an already-ruled answer becomes a banner, and reads nothing on its own', async () => {
	const send = sender({ status: 'already_ruled', message: 'line 3 is already ruled' });
	const { wiring, reads } = readyBoard();
	const store = new DecisionStore('token', wiring, send);

	store.choose('repo', 42, songPoints, { shown: songCard, option: optionA });
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

	expect(store.banner(songKey)).toEqual({
		kind: 'already-ruled',
		message: 'Schon entschieden: diese Zeile wurde inzwischen woanders entschieden.'
	});
	expect(reads()).toBe(0);
});

test('a network failure during the write becomes its own failed banner and frees the card', async () => {
	const send = vi.fn(async () => {
		throw new Error('network down');
	});
	const { wiring } = readyBoard();
	const store = new DecisionStore('token', wiring, send);

	store.choose('repo', 42, songPoints, { shown: songCard, option: optionA });
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

	expect(store.banner(songKey)).toEqual({
		kind: 'failed',
		message: 'Das Board ist nicht erreichbar.'
	});
	expect(store.held(songKey)).toBeNull();
});

test('deciding again clears a stale banner before the new window starts', async () => {
	const send = sender({ status: 'already_ruled', message: null });
	const { wiring } = readyBoard();
	const store = new DecisionStore('token', wiring, send);
	store.choose('repo', 42, songPoints, { shown: songCard, option: optionA });
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);
	expect(store.banner(songKey)).not.toBeNull();

	store.choose('repo', 42, songPoints, { shown: songCard, option: optionB });

	expect(store.banner(songKey)).toBeNull();
});

test('two cards pending at once each write exactly once, and undoing one leaves the other untouched', async () => {
	const otherCard = optionLine({
		index: 5,
		fingerprint: 'fp2',
		topic: 'Hosts',
		options: [optionA, optionB]
	});
	const otherKey = cardKey('repo', 43);
	const send = sender(storedAnswer(storedSong));
	const { wiring } = readyBoard();
	const store = new DecisionStore('token', wiring, send);

	store.choose('repo', 42, songPoints, { shown: songCard, option: optionA });
	store.choose('repo', 43, [otherCard], { shown: otherCard, option: optionB });
	expect(store.held(songKey)).not.toBeNull();
	expect(store.held(otherKey)).not.toBeNull();

	store.undo(songEntry);
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

	expect(store.held(songKey)).toBeNull();
	expect(store.held(otherKey)).toBeNull();
	expect(send).toHaveBeenCalledTimes(1);
	expect(send).toHaveBeenCalledWith('token', {
		repo: 'repo',
		item: 43,
		lines: [{ line: 5, fingerprint: 'fp2', option: 'B' }]
	});
});

function otherStore(result: DecisionResult = storedAnswer(storedSong)) {
	const send = sender(result);
	const { wiring } = readyBoard();
	return { send, store: new DecisionStore('token', wiring, send) };
}

test('ABRD-67: an Other answer waits out the window, names Other and the point’s topic, then posts once', async () => {
	const { send, store } = otherStore();

	store.decideOther('repo', 42, songCard, '  Only on desktop ');
	expect(store.pendingEntries).toEqual([
		{ key: songEntry, message: 'Other · Jump', state: 'done' }
	]);
	expect(send).not.toHaveBeenCalled();
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

	expect(send).toHaveBeenCalledTimes(1);
	expect(send).toHaveBeenCalledWith('token', {
		repo: 'repo',
		item: 42,
		lines: [{ line: 4, fingerprint: 'fp-shown' }],
		other: 'Only on desktop'
	});
});

test('ABRD-68: Send posts the card the panel opened with, though the board shows a revised one', async () => {
	const { send, store } = otherStore();
	store.openPanel(songPanel, { kind: 'other', shown: songPoints });

	const opened = store.panel(songPanel);
	const [shown] = opened?.shown ?? [];
	if (shown === undefined) throw new Error('the panel should be open');
	store.decideOther('repo', 42, shown, 'x');
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

	expect(send).toHaveBeenCalledWith(
		'token',
		expect.objectContaining({ lines: [{ line: 4, fingerprint: 'fp-shown' }] })
	);
});

test('ABRD-67: sending closes the panel and undoing posts nothing and reopens it with the draft', async () => {
	const { send, store } = otherStore();
	store.openPanel(songPanel, { kind: 'other', shown: songPoints });
	store.setDraft(songPanel, 'other', 'Only on desktop');

	store.decideOther('repo', 42, songCard, store.draft(songPanel, 'other'));
	expect(store.panel(songPanel)).toBeNull();
	store.undo(songEntry);
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

	expect(send).not.toHaveBeenCalled();
	expect(store.panel(songPanel)).toEqual({ kind: 'other', shown: songPoints });
	expect(store.draft(songPanel, 'other')).toBe('Only on desktop');
});

test('ABRD-66: the draft is kept per card and survives a failed post, and a stored decision drops it', async () => {
	const failing = otherStore({ status: 'failed', message: 'aco unavailable' });
	failing.store.setDraft(songPanel, 'other', 'Only on desktop');
	failing.store.decideOther('repo', 42, songCard, 'Only on desktop');
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);
	expect(failing.store.draft(songPanel, 'other')).toBe('Only on desktop');
	expect(failing.store.draft(cardKey('repo', 43), 'other')).toBe('');

	const ruling = otherStore();
	ruling.store.setDraft(songPanel, 'other', 'Only on desktop');
	ruling.store.decideOther('repo', 42, songCard, 'Only on desktop');
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);
	expect(ruling.store.draft(songPanel, 'other')).toBe('');
});

test('ABRD-65: a pending Other answer marks its point waiting so no pick can join it', () => {
	const { store } = otherStore();

	store.decideOther('repo', 42, songCard, 'x');

	expect([...store.waitingIndexes(songKey)]).toEqual([4]);
});

test('ABRD-97: a card saves from the end of its window until its answer is applied, and Undo then does nothing', async () => {
	let answer: (result: DecisionResult) => void = () => {};
	const held = new Promise<DecisionResult>((resolve) => {
		answer = resolve;
	});
	const send = vi.fn(() => held) as unknown as typeof postDecision;
	const { store: board, wiring } = readyBoard([repo({ items: [item({ number: 42 })] })]);
	const store = new DecisionStore('token', wiring, send);

	store.choose('repo', 42, songPoints, { shown: songCard, option: optionA });
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

	expect(store.pendingEntries).toEqual([]);
	expect(store.isSaving(songKey)).toBe(true);
	expect(store.held(songKey)).not.toBeNull();
	store.undo(songEntry);
	expect(store.held(songKey)).not.toBeNull();
	expect(send).toHaveBeenCalledTimes(1);
	answer(storedAnswer(storedSong));
	await vi.advanceTimersByTimeAsync(0);
	expect(store.isSaving(songKey)).toBe(false);
	expect(store.held(songKey)).toBeNull();
	expect(board.repos[0]?.items).toEqual([storedSong]);
});

test.each([
	['a refused', { status: 'already_ruled', message: 'line 3 is already ruled' } as DecisionResult],
	['a failed', { status: 'failed', message: 'aco unavailable' } as DecisionResult]
])('ABRD-97: %s answer releases the saving card', async (_name, refusal) => {
	const { wiring } = readyBoard();
	const store = new DecisionStore('token', wiring, sender(refusal));

	store.choose('repo', 42, songPoints, { shown: songCard, option: optionA });
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

	expect(store.held(songKey)).toBeNull();
});

const secondCard = optionLine({
	index: 5,
	fingerprint: 'fp-second',
	options: [optionA, optionB]
});
const twoPoints = [songCard, secondCard];

function heldSend() {
	const held = new Promise<DecisionResult>(() => {});
	return { send: vi.fn(() => held) as unknown as typeof postDecision };
}

test.each([
	[
		'a pick',
		(store: DecisionStore) =>
			store.choose('repo', 42, twoPoints, { shown: songCard, option: optionB }),
		1
	],
	['Accept all', (store: DecisionStore) => store.acceptAll('repo', 42, twoPoints), 2]
])('ABRD-99: %s holds its picks in the window and while saving', async (_name, decide, count) => {
	const { wiring } = readyBoard([repo({ items: [item({ number: 42 })] })]);
	const { send } = heldSend();
	const store = new DecisionStore('token', wiring, send);
	expect(store.held(songKey)).toBeNull();

	decide(store);
	expect(store.held(songKey)).toHaveLength(count);

	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);
	expect(store.isSaving(songKey)).toBe(true);
	expect(store.held(songKey)).toHaveLength(count);
});

test.each([
	['Other', (store: DecisionStore) => store.decideOther('repo', 42, songCard, 'my own answer')],
	['Unclear', (store: DecisionStore) => store.decideUnclear('repo', 42, twoPoints, 'a note')]
])('ABRD-99: an %s answer holds no picks', async (_name, decide) => {
	const { wiring } = readyBoard([repo({ items: [item({ number: 42 })] })]);
	const { send } = heldSend();
	const store = new DecisionStore('token', wiring, send);

	decide(store);
	expect(store.held(songKey)).toEqual([]);

	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);
	expect(store.isSaving(songKey)).toBe(true);
	expect(store.held(songKey)).toEqual([]);
});

test.each([
	['answers', false],
	['fails', true]
])(
	'ABRD-45: a card is pending from Neu laden until the read %s, and free after it',
	async (_name, fails) => {
		let finish: () => void = () => {};
		const read = new Promise<void>((resolve, reject) => {
			finish = fails ? () => reject(new Error('unreachable')) : resolve;
		});
		const { wiring } = readyBoard();
		const store = new DecisionStore('token', { ...wiring, reload: () => read });
		expect(store.isReading(songKey)).toBe(false);

		const reloading = store.reloadAfterBanner(songKey).catch(() => {});
		expect(store.isReading(songKey)).toBe(true);
		expect(store.isReading(cardKey('repo', 43))).toBe(false);

		finish();
		await reloading;
		expect(store.isReading(songKey)).toBe(false);
	}
);

const otherCard = optionLine({
	index: 5,
	fingerprint: 'fp2',
	topic: 'Hosts',
	options: [optionA, optionB]
});
const otherKey = cardKey('repo', 43);

test('ABRD-152: flush posts every decision in its window at once, each card as its own write, and no timer posts again', async () => {
	const send = sender(storedAnswer(storedSong));
	const { wiring } = readyBoard();
	const store = new DecisionStore('token', wiring, send);
	store.choose('repo', 42, songPoints, { shown: songCard, option: optionB });
	store.choose('repo', 43, [otherCard], { shown: otherCard, option: optionA });

	store.flush();

	expect(send).toHaveBeenCalledTimes(2);
	expect(send).toHaveBeenCalledWith('token', {
		repo: 'repo',
		item: 42,
		lines: [{ line: 4, fingerprint: 'fp-shown', option: 'B' }]
	});
	expect(send).toHaveBeenCalledWith('token', {
		repo: 'repo',
		item: 43,
		lines: [{ line: 5, fingerprint: 'fp2', option: 'A' }]
	});
	expect(store.pendingEntries).toEqual([]);
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);
	expect(send).toHaveBeenCalledTimes(2);
});

test('ABRD-152: a second flush posts nothing more', () => {
	const send = sender(storedAnswer(storedSong));
	const { wiring } = readyBoard();
	const store = new DecisionStore('token', wiring, send);
	store.choose('repo', 42, songPoints, { shown: songCard, option: optionB });

	store.flush();
	store.flush();

	expect(send).toHaveBeenCalledTimes(1);
});

test('ABRD-152: flush posts nothing for an undone decision, and every other point of a card as its own write', () => {
	const send = sender(storedAnswer(storedSong));
	const { wiring } = readyBoard();
	const store = new DecisionStore('token', wiring, send);
	const second = optionLine({ index: 6, fingerprint: 'fp3', options: [optionA, optionB] });
	const third = optionLine({ index: 7, fingerprint: 'fp4', options: [optionA, optionB] });
	store.choose('repo', 42, songPoints, { shown: songCard, option: optionB });
	store.undo(songEntry);
	store.choose('repo', 43, [otherCard, second, third], { shown: second, option: optionA });
	store.choose('repo', 43, [otherCard, second, third], { shown: third, option: optionA });

	store.flush();

	expect(send).toHaveBeenCalledTimes(2);
	expect(send).not.toHaveBeenCalledWith('token', expect.objectContaining({ item: 42 }));
	expect(store.pendingEntries).toEqual([]);
});

test('ABRD-153: a refused post on a card not shown is an unseen failure naming it until the card is shown', async () => {
	const send = sender({ status: 'already_ruled', message: 'line 3 is already ruled' });
	const { wiring } = readyBoard();
	const store = new DecisionStore('token', wiring, send);
	store.showCard(otherKey);

	store.choose('repo', 42, songPoints, { shown: songCard, option: optionA });
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

	expect(store.unseenFailures).toEqual([
		{
			key: songKey,
			name: 'Jump',
			message: 'Schon entschieden: diese Zeile wurde inzwischen woanders entschieden.'
		}
	]);

	store.showCard(songKey);

	expect(store.unseenFailures).toEqual([]);
	expect(store.banner(songKey)).not.toBeNull();
});

test('ABRD-153: a failed post on a card not shown is an unseen failure too', async () => {
	const send = vi.fn(async () => {
		throw new Error('network down');
	});
	const { wiring } = readyBoard();
	const store = new DecisionStore('token', wiring, send);
	store.showCard(otherKey);

	store.choose('repo', 42, songPoints, { shown: songCard, option: optionA });
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

	expect(store.unseenFailures.map((failure) => failure.key)).toEqual([songKey]);
});

test.each([
	[
		'a new undo window starts on it',
		(store: DecisionStore) =>
			store.choose('repo', 42, songPoints, { shown: songCard, option: optionB })
	],
	[
		'its banner is dropped for a re-read',
		(store: DecisionStore) => store.reloadAfterBanner(songKey)
	]
])('ABRD-153: an unseen failure goes when %s', async (_name, clearBanner) => {
	const send = sender({ status: 'already_ruled', message: 'line 3 is already ruled' });
	const { wiring } = readyBoard();
	const store = new DecisionStore('token', wiring, send);
	store.showCard(otherKey);
	store.choose('repo', 42, songPoints, { shown: songCard, option: optionA });
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);
	expect(store.unseenFailures).toHaveLength(1);

	await clearBanner(store);

	expect(store.unseenFailures).toEqual([]);
});

test('ABRD-153: a refused post on the card shown raises no failure strip', async () => {
	const send = sender({ status: 'already_ruled', message: 'line 3 is already ruled' });
	const { wiring } = readyBoard();
	const store = new DecisionStore('token', wiring, send);
	store.showCard(songKey);

	store.choose('repo', 42, songPoints, { shown: songCard, option: optionA });
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

	expect(store.unseenFailures).toEqual([]);
	expect(store.banner(songKey)).not.toBeNull();
});
