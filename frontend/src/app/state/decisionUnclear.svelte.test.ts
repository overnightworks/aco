import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import type { postDecision } from '../../client';
import { optionLine } from '../../test-support/board';
import type { DecisionResult } from '../../types';
import { UNDO_SECONDS, lineKey } from '../model/decision';
import { DecisionStore } from './decision.svelte';

const card = optionLine({ index: 4, fingerprint: 'fp-shown', topic: 'Jump' });
const key = lineKey('repo', 42, card);

function unclearStore(result: DecisionResult = { status: 'returned', message: null }) {
	const send = vi.fn(async () => result) as unknown as typeof postDecision;
	const reload = vi.fn(async () => {});
	return { send, reload, store: new DecisionStore('token', reload, send) };
}

beforeEach(() => {
	vi.useFakeTimers();
});

afterEach(() => {
	vi.useRealTimers();
});

test('[ABRD-74] sending waits out the window as a With head strip named by the topic, then posts once', async () => {
	const { send, store } = unclearStore();

	store.decideUnclear('repo', 42, card, '  Why two? ');
	expect(store.pendingEntries).toEqual([{ key, message: 'Jump', state: 'back' }]);
	expect(send).not.toHaveBeenCalled();
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

	expect(send).toHaveBeenCalledTimes(1);
	expect(send).toHaveBeenCalledWith('token', {
		repo: 'repo',
		item: 42,
		line: 4,
		fingerprint: 'fp-shown',
		unclear: true,
		note: 'Why two?'
	});
});

test('[ABRD-74] undo posts nothing and reopens the Unclear panel with the note', async () => {
	const { send, store } = unclearStore();
	store.openPanel(key, { kind: 'unclear', shown: card });
	store.setDraft(key, 'unclear', 'Why two?');

	store.decideUnclear('repo', 42, card, store.draft(key, 'unclear'));
	expect(store.panel(key)).toBeNull();
	store.undo(key);
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

	expect(send).not.toHaveBeenCalled();
	expect(store.panel(key)).toEqual({ kind: 'unclear', shown: card });
	expect(store.draft(key, 'unclear')).toBe('Why two?');
});

test('[ABRD-75] one panel per card: opening Unclear closes Other, and each keeps its own draft', () => {
	const { store } = unclearStore();
	store.openPanel(key, { kind: 'other', shown: card });
	store.setDraft(key, 'other', 'Only on desktop');

	store.openPanel(key, { kind: 'unclear', shown: card });
	store.setDraft(key, 'unclear', 'Why?');

	expect(store.panel(key)?.kind).toBe('unclear');
	expect(store.draft(key, 'other')).toBe('Only on desktop');
	expect(store.draft(key, 'unclear')).toBe('Why?');
});

test('[ABRD-75] the card is pending while its answer waits, so no pick can join it', () => {
	const { store } = unclearStore();

	store.decideUnclear('repo', 42, card, '');

	expect(store.isPending(key)).toBe(true);
});

test('[ABRD-76] a returned answer reloads, drops the Unclear draft only and is reported once, never as a ruling', async () => {
	const { reload, store } = unclearStore();
	store.setDraft(key, 'unclear', 'Why?');
	store.setDraft(key, 'other', 'Only on desktop');

	store.decideUnclear('repo', 42, card, 'Why?');
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

	expect(reload).toHaveBeenCalledTimes(1);
	expect(store.banner(key)).toBeNull();
	expect(store.justRuled).toBeNull();
	expect(store.justReturned).toBe(key);
	expect(store.draft(key, 'unclear')).toBe('');
	expect(store.draft(key, 'other')).toBe('Only on desktop');
	store.acknowledgeReturned();
	expect(store.justReturned).toBeNull();
});

test('[ABRD-75] a refused answer keeps the note in the draft and shows aco’s sentence', async () => {
	const { store } = unclearStore({ status: 'failed', message: 'line 4 is with its head' });
	store.setDraft(key, 'unclear', 'Why?');

	store.decideUnclear('repo', 42, card, 'Why?');
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

	expect(store.banner(key)).toEqual({ kind: 'failed', message: 'line 4 is with its head' });
	expect(store.draft(key, 'unclear')).toBe('Why?');
	expect(store.justReturned).toBeNull();
});
