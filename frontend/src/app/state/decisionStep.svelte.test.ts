import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import type { postStep } from '../../client';
import { readyBoard, repo, stepRead } from '../../test-support/board';
import type { StepResult } from '../../types';
import { BOARD_UNREACHABLE_MESSAGE, entryKey, stepKey, UNDO_SECONDS } from '../model/decision';
import { DecisionStore } from './decision.svelte';

const step = stepRead({ number: 7, title: 'Release', fingerprint: 'fp-shown' });
const card = stepKey('repo', 7);

function stepStore(result: StepResult | Error = { status: 'answered', message: null }) {
	const send = vi.fn(async () => {
		if (result instanceof Error) throw result;
		return result;
	}) as unknown as typeof postStep;
	const { store: board, wiring, reads } = readyBoard([repo({ steps: [step] })]);
	const store = new DecisionStore('token', wiring, vi.fn(), UNDO_SECONDS, send);
	return { send, board, reads, store };
}

beforeEach(() => {
	vi.useFakeTimers();
});

afterEach(() => {
	vi.useRealTimers();
});

test('ABRD-175: an Erfolgreich answer waits out the window, then posts yes once and re-reads', async () => {
	const { send, store, reads } = stepStore();

	store.answerStep('repo', step, 'yes', '');
	expect(store.pendingStep(card)).toEqual({
		key: entryKey(card, []),
		message: 'Erfolgreich · #7',
		state: 'done'
	});
	expect(send).not.toHaveBeenCalled();
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

	expect(send).toHaveBeenCalledWith('token', {
		repo: 'repo',
		item: 7,
		fingerprint: 'fp-shown',
		result: 'yes'
	});
	expect(reads()).toBe(1);
	expect(store.pendingStep(card)).toBeNull();
	expect(store.isSaving(card)).toBe(false);
});

test('ABRD-174: a failure posts no with its trimmed note', async () => {
	const { send, store } = stepStore();

	store.answerStep('repo', step, 'no', '  Stayed red. ');
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

	expect(send).toHaveBeenCalledWith('token', {
		repo: 'repo',
		item: 7,
		fingerprint: 'fp-shown',
		result: 'no',
		text: 'Stayed red.'
	});
});

test('ABRD-175: undo posts nothing', async () => {
	const { send, store } = stepStore();

	store.answerStep('repo', step, 'no', 'Stayed red.');
	store.undo(entryKey(card, []));
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

	expect(send).not.toHaveBeenCalled();
	expect(store.pendingStep(card)).toBeNull();
});

test('ABRD-175: leaving the page posts a waiting step answer at once, and a step answer is no option strip', async () => {
	const { send, store } = stepStore();

	store.answerStep('repo', step, 'yes', '');
	expect(store.pendingEntries).toEqual([]);
	store.flush();
	await vi.advanceTimersByTimeAsync(0);

	expect(send).toHaveBeenCalledTimes(1);
});

test('ABRD-176: a refusal keeps its sentence on the card and asks for a re-read', async () => {
	const { store, reads } = stepStore({ status: 'failed', message: 'This step changed; reload.' });

	store.answerStep('repo', step, 'yes', '');
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

	expect(store.banner(card)).toEqual({ kind: 'changed', message: 'This step changed; reload.' });
	expect(reads()).toBe(0);
	expect(store.unseenFailures).toEqual([]);
});

test('ABRD-176: an unreachable board shows its sentence and leaves the answer open to retry', async () => {
	const { store } = stepStore(new TypeError('no network'));

	store.answerStep('repo', step, 'yes', '');
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

	expect(store.banner(card)).toEqual({ kind: 'failed', message: BOARD_UNREACHABLE_MESSAGE });
});
