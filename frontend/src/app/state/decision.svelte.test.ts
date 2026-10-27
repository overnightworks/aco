import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import type { postDecision } from '../../client';
import { line, optionLine } from '../../test-support/board';
import type { DecisionResult } from '../../types';
import { LINE_CHANGED_MESSAGE, UNDO_SECONDS, lineKey } from '../model/decision';
import { DecisionStore } from './decision.svelte';

const card = line({ index: 3, text: 'Guests?', question: 'Guests allowed?', fingerprint: 'fp' });
const key = lineKey('repo', 42, card);

function sender(result: DecisionResult): typeof postDecision {
	return vi.fn(async () => result) as unknown as typeof postDecision;
}

beforeEach(() => {
	vi.useFakeTimers();
});

afterEach(() => {
	vi.useRealTimers();
});

test('undoing within the window sends nothing, ever', async () => {
	const send = sender({ status: 'ruled', message: null });
	const reload = vi.fn(async () => {});
	const store = new DecisionStore('token', reload, send);

	store.decide('repo', 42, card, 'no', null);
	expect(store.isPending(key)).toBe(true);
	store.undo(key);
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

	expect(store.isPending(key)).toBe(false);
	expect(send).not.toHaveBeenCalled();
	expect(reload).not.toHaveBeenCalled();
});

test('undoing a key with nothing pending is a no-op', () => {
	const store = new DecisionStore(
		'token',
		vi.fn(async () => {})
	);

	expect(() => store.undo(key)).not.toThrow();
});

test('once the window elapses, exactly one request is sent and the board reloads', async () => {
	const send = sender({ status: 'ruled', message: null });
	const reload = vi.fn(async () => {});
	const store = new DecisionStore('token', reload, send);

	store.decide('repo', 42, card, 'yes', 'a note');
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

	expect(send).toHaveBeenCalledTimes(1);
	expect(send).toHaveBeenCalledWith('token', {
		repo: 'repo',
		item: 42,
		line: 3,
		fingerprint: 'fp',
		outcome: 'yes',
		note: 'a note'
	});
	expect(reload).toHaveBeenCalledTimes(1);
	expect(store.isPending(key)).toBe(false);

	// Nothing fires again later: the timer was consumed, not merely delayed.
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);
	expect(send).toHaveBeenCalledTimes(1);
});

test('an already-ruled answer becomes a banner, and reloads nothing on its own', async () => {
	const send = sender({ status: 'already_ruled', message: 'line 3 is already ruled' });
	const reload = vi.fn(async () => {});
	const store = new DecisionStore('token', reload, send);

	store.decide('repo', 42, card, 'yes', null);
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

	expect(store.banner(key)).toEqual({
		kind: 'already-ruled',
		message: 'Schon entschieden: diese Zeile wurde inzwischen woanders entschieden.'
	});
	expect(reload).not.toHaveBeenCalled();
});

test('a changed-line answer becomes a "changed" banner carrying the server’s own sentence', async () => {
	const send = sender({ status: 'failed', message: LINE_CHANGED_MESSAGE });
	const store = new DecisionStore(
		'token',
		vi.fn(async () => {}),
		send
	);

	store.decide('repo', 42, card, 'yes', null);
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

	expect(store.banner(key)).toEqual({ kind: 'changed', message: LINE_CHANGED_MESSAGE });
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

	store.decide('repo', 42, card, 'yes', null);
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

	expect(store.banner(key)).toEqual({ kind: 'failed', message: 'Das Board ist nicht erreichbar.' });
});

test('deciding again clears a stale banner before the new window starts', async () => {
	const send = sender({ status: 'already_ruled', message: null });
	const store = new DecisionStore(
		'token',
		vi.fn(async () => {}),
		send
	);
	store.decide('repo', 42, card, 'yes', null);
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);
	expect(store.banner(key)).not.toBeNull();

	store.decide('repo', 42, card, 'no', null);

	expect(store.banner(key)).toBeNull();
});

test('"Neu laden" after a refusal drops the banner and reloads', async () => {
	const send = sender({ status: 'already_ruled', message: null });
	const reload = vi.fn(async () => {});
	const store = new DecisionStore('token', reload, send);
	store.decide('repo', 42, card, 'yes', null);
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

	await store.reloadAfterBanner(key);

	expect(store.banner(key)).toBeNull();
	expect(reload).toHaveBeenCalledTimes(1);
});

test('pendingEntries names what is waiting, for the strip to show', () => {
	const store = new DecisionStore(
		'token',
		vi.fn(async () => {}),
		sender({ status: 'ruled', message: null })
	);

	store.decide('repo', 42, card, 'no', null);

	expect(store.pendingEntries).toEqual([{ key, message: 'Nein: Guests allowed?', state: 'done' }]);
});

test('justRuled names the key a successful write just resolved, for the stage to move on from', async () => {
	const send = sender({ status: 'ruled', message: null });
	const store = new DecisionStore(
		'token',
		vi.fn(async () => {}),
		send
	);

	expect(store.justRuled).toBeNull();
	store.decide('repo', 42, card, 'yes', null);
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

	expect(store.justRuled).toBe(key);
});

test('two lines pending at once each write exactly once, and undoing one leaves the other untouched', async () => {
	const otherCard = line({
		index: 5,
		text: 'Hosts?',
		question: 'Hosts allowed?',
		fingerprint: 'fp2'
	});
	const otherKey = lineKey('repo', 42, otherCard);
	const send = sender({ status: 'ruled', message: null });
	const store = new DecisionStore(
		'token',
		vi.fn(async () => {}),
		send
	);

	store.decide('repo', 42, card, 'yes', null);
	store.decide('repo', 42, otherCard, 'no', null);
	expect(store.isPending(key)).toBe(true);
	expect(store.isPending(otherKey)).toBe(true);

	store.undo(key);
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

	expect(store.isPending(key)).toBe(false);
	expect(store.isPending(otherKey)).toBe(false);
	expect(send).toHaveBeenCalledTimes(1);
	expect(send).toHaveBeenCalledWith(
		'token',
		expect.objectContaining({ line: otherCard.index, outcome: 'no' })
	);
});

const songCard = optionLine({ index: 4, fingerprint: 'fp-shown', topic: 'Jump' });
const songKey = lineKey('repo', 42, songCard);

function otherStore(result: DecisionResult = { status: 'ruled', message: null }) {
	const send = sender(result);
	return { send, store: new DecisionStore('token', async () => {}, send) };
}

test('[ABRD-67] an Other answer waits out the window, names Other and the topic, then posts once', async () => {
	const { send, store } = otherStore();

	store.decideOther('repo', 42, songCard, '  Only on desktop ');
	expect(store.pendingEntries).toEqual([{ key: songKey, message: 'Other · Jump', state: 'done' }]);
	expect(send).not.toHaveBeenCalled();
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

	expect(send).toHaveBeenCalledTimes(1);
	expect(send).toHaveBeenCalledWith('token', {
		repo: 'repo',
		item: 42,
		line: 4,
		fingerprint: 'fp-shown',
		other: 'Only on desktop'
	});
});

test('[ABRD-68] Send posts the card the panel opened with, though the board shows a revised one', async () => {
	const { send, store } = otherStore();
	store.openPanel(songKey, { kind: 'other', shown: songCard });

	const opened = store.panel(songKey);
	if (opened === null) throw new Error('the panel should be open');
	store.decideOther('repo', 42, opened.shown, 'x');
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

	expect(send).toHaveBeenCalledWith('token', expect.objectContaining({ fingerprint: 'fp-shown' }));
});

test('[ABRD-67] sending closes the panel and undoing posts nothing and reopens it with the draft', async () => {
	const { send, store } = otherStore();
	store.openPanel(songKey, { kind: 'other', shown: songCard });
	store.setDraft(songKey, 'other', 'Only on desktop');

	store.decideOther('repo', 42, songCard, store.draft(songKey, 'other'));
	expect(store.panel(songKey)).toBeNull();
	store.undo(songKey);
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

	expect(send).not.toHaveBeenCalled();
	expect(store.panel(songKey)).toEqual({ kind: 'other', shown: songCard });
	expect(store.draft(songKey, 'other')).toBe('Only on desktop');
});

test('[ABRD-66] the draft is kept per card and survives a failed post, and a stored decision drops it', async () => {
	const failing = otherStore({ status: 'failed', message: 'aco unavailable' });
	failing.store.setDraft(songKey, 'other', 'Only on desktop');
	failing.store.decideOther('repo', 42, songCard, 'Only on desktop');
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);
	expect(failing.store.draft(songKey, 'other')).toBe('Only on desktop');
	expect(failing.store.draft('repo:42:5', 'other')).toBe('');

	const ruling = otherStore();
	ruling.store.setDraft(songKey, 'other', 'Only on desktop');
	ruling.store.decideOther('repo', 42, songCard, 'Only on desktop');
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);
	expect(ruling.store.draft(songKey, 'other')).toBe('');
});

test('[ABRD-65] a pending Other answer marks the card pending so no pick can join it', () => {
	const { store } = otherStore();

	store.decideOther('repo', 42, songCard, 'x');

	expect(store.isPending(songKey)).toBe(true);
});
