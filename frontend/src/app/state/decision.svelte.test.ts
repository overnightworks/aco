import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import type { postDecision } from '../../client';
import { cardOption, optionLine } from '../../test-support/board';
import type { DecisionResult } from '../../types';
import { cardKey, UNDO_SECONDS } from '../model/decision';
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

function sender(result: DecisionResult): typeof postDecision {
	return vi.fn(async () => result) as unknown as typeof postDecision;
}

beforeEach(() => {
	vi.useFakeTimers();
});

afterEach(() => {
	vi.useRealTimers();
});

test('undoing a key with nothing pending is a no-op', () => {
	const store = new DecisionStore(
		'token',
		vi.fn(async () => {})
	);

	expect(() => store.undo(songKey)).not.toThrow();
});

test('once the window elapses, exactly one request is sent and the board reloads', async () => {
	const send = sender({ status: 'ruled', message: null });
	const reload = vi.fn(async () => {});
	const store = new DecisionStore('token', reload, send);

	store.choose('repo', 42, songPoints, { shown: songCard, option: optionB });
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

	expect(send).toHaveBeenCalledTimes(1);
	expect(send).toHaveBeenCalledWith('token', {
		repo: 'repo',
		item: 42,
		lines: [{ line: 4, fingerprint: 'fp-shown', option: 'B' }]
	});
	expect(reload).toHaveBeenCalledTimes(1);
	expect(store.isPending(songKey)).toBe(false);

	// Nothing fires again later: the timer was consumed, not merely delayed.
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);
	expect(send).toHaveBeenCalledTimes(1);
});

test('an already-ruled answer becomes a banner, and reloads nothing on its own', async () => {
	const send = sender({ status: 'already_ruled', message: 'line 3 is already ruled' });
	const reload = vi.fn(async () => {});
	const store = new DecisionStore('token', reload, send);

	store.choose('repo', 42, songPoints, { shown: songCard, option: optionA });
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

	expect(store.banner(songKey)).toEqual({
		kind: 'already-ruled',
		message: 'Schon entschieden: diese Zeile wurde inzwischen woanders entschieden.'
	});
	expect(reload).not.toHaveBeenCalled();
});

test('a network failure during the write becomes its own failed banner', async () => {
	const send = vi.fn(async () => {
		throw new Error('network down');
	});
	const store = new DecisionStore(
		'token',
		vi.fn(async () => {}),
		send
	);

	store.choose('repo', 42, songPoints, { shown: songCard, option: optionA });
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

	expect(store.banner(songKey)).toEqual({
		kind: 'failed',
		message: 'Das Board ist nicht erreichbar.'
	});
});

test('deciding again clears a stale banner before the new window starts', async () => {
	const send = sender({ status: 'already_ruled', message: null });
	const store = new DecisionStore(
		'token',
		vi.fn(async () => {}),
		send
	);
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
	const send = sender({ status: 'ruled', message: null });
	const store = new DecisionStore(
		'token',
		vi.fn(async () => {}),
		send
	);

	store.choose('repo', 42, songPoints, { shown: songCard, option: optionA });
	store.choose('repo', 43, [otherCard], { shown: otherCard, option: optionB });
	expect(store.isPending(songKey)).toBe(true);
	expect(store.isPending(otherKey)).toBe(true);

	store.undo(songKey);
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

	expect(store.isPending(songKey)).toBe(false);
	expect(store.isPending(otherKey)).toBe(false);
	expect(send).toHaveBeenCalledTimes(1);
	expect(send).toHaveBeenCalledWith('token', {
		repo: 'repo',
		item: 43,
		lines: [{ line: 5, fingerprint: 'fp2', option: 'B' }]
	});
});

function otherStore(result: DecisionResult = { status: 'ruled', message: null }) {
	const send = sender(result);
	return { send, store: new DecisionStore('token', async () => {}, send) };
}

test('[ABRD-67] an Other answer waits out the window, names Other and the card’s name, then posts once', async () => {
	const { send, store } = otherStore();

	store.decideOther('repo', 42, songPoints, '  Only on desktop ');
	expect(store.pendingEntries).toEqual([{ key: songKey, message: 'Other · Jump', state: 'done' }]);
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

test('[ABRD-68] Send posts the card the panel opened with, though the board shows a revised one', async () => {
	const { send, store } = otherStore();
	store.openPanel(songKey, { kind: 'other', shown: songPoints });

	const opened = store.panel(songKey);
	if (opened === null) throw new Error('the panel should be open');
	store.decideOther('repo', 42, opened.shown, 'x');
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

	expect(send).toHaveBeenCalledWith(
		'token',
		expect.objectContaining({ lines: [{ line: 4, fingerprint: 'fp-shown' }] })
	);
});

test('[ABRD-67] sending closes the panel and undoing posts nothing and reopens it with the draft', async () => {
	const { send, store } = otherStore();
	store.openPanel(songKey, { kind: 'other', shown: songPoints });
	store.setDraft(songKey, 'other', 'Only on desktop');

	store.decideOther('repo', 42, songPoints, store.draft(songKey, 'other'));
	expect(store.panel(songKey)).toBeNull();
	store.undo(songKey);
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

	expect(send).not.toHaveBeenCalled();
	expect(store.panel(songKey)).toEqual({ kind: 'other', shown: songPoints });
	expect(store.draft(songKey, 'other')).toBe('Only on desktop');
});

test('[ABRD-66] the draft is kept per card and survives a failed post, and a stored decision drops it', async () => {
	const failing = otherStore({ status: 'failed', message: 'aco unavailable' });
	failing.store.setDraft(songKey, 'other', 'Only on desktop');
	failing.store.decideOther('repo', 42, songPoints, 'Only on desktop');
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);
	expect(failing.store.draft(songKey, 'other')).toBe('Only on desktop');
	expect(failing.store.draft(cardKey('repo', 43), 'other')).toBe('');

	const ruling = otherStore();
	ruling.store.setDraft(songKey, 'other', 'Only on desktop');
	ruling.store.decideOther('repo', 42, songPoints, 'Only on desktop');
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);
	expect(ruling.store.draft(songKey, 'other')).toBe('');
});

test('[ABRD-65] a pending Other answer marks the card pending so no pick can join it', () => {
	const { store } = otherStore();

	store.decideOther('repo', 42, songPoints, 'x');

	expect(store.isPending(songKey)).toBe(true);
});
