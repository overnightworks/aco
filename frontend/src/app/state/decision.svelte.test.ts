import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import type { postDecision } from '../../client';
import { line } from '../../test-support/board';
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

test('pendingEntries names what is waiting, for the toast to show', () => {
	const store = new DecisionStore(
		'token',
		vi.fn(async () => {}),
		sender({ status: 'ruled', message: null })
	);

	store.decide('repo', 42, card, 'no', null);

	expect(store.pendingEntries).toEqual([{ key, outcome: 'no', message: 'Nein: Guests allowed?' }]);
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
