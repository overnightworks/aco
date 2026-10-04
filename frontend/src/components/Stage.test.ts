import { render, screen } from '@testing-library/svelte';
import { tick } from 'svelte';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { DecisionStore } from '../app/state/decision.svelte';
import { UNDO_SECONDS, lineKey } from '../app/model/decision';
import { item, line, repo } from '../test-support/board';
import type { DecisionResult } from '../types';
import Stage from './Stage.svelte';

beforeEach(() => {
	vi.useFakeTimers();
});

afterEach(() => {
	vi.useRealTimers();
});

function storeAnswering(result: DecisionResult, reload: () => Promise<void> = async () => {}) {
	return new DecisionStore(
		'token',
		reload,
		vi.fn(async () => result)
	);
}

test('with nothing selected, the stage says everything is decided', () => {
	render(Stage, {
		repos: [],
		selectedKey: null,
		decisions: storeAnswering({ status: 'ruled', message: null })
	});

	expect(screen.getByText(/Alles entschieden/)).toBeInTheDocument();
});

test('a selected line shows only its own question, example, sentence and recommendation', () => {
	const card = line({
		index: 1,
		text: 'Guests may join the call.',
		question: 'Guests allowed?',
		example: 'Anna invites a guest.',
		default: 'yes'
	});
	const repos = [repo({ items: [item({ number: 42, lines: [card] })] })];

	render(Stage, {
		repos,
		selectedKey: lineKey('repo', 42, card),
		decisions: storeAnswering({ status: 'ruled', message: null })
	});

	expect(screen.getByRole('heading', { name: 'Guests allowed?' })).toBeInTheDocument();
	expect(screen.getByText('Guests may join the call.')).toBeInTheDocument();
	expect(screen.getByText('Anna invites a guest.')).toBeInTheDocument();
	expect(screen.getByRole('button', { name: /Empfohlen/ })).toHaveTextContent('Ja');
	// The note stays collapsed: its textarea is present but not shown open.
	expect(screen.getByText('Notiz').closest('details')).not.toHaveAttribute('open');
});

test('choosing an outcome starts the undo window and disables the buttons', async () => {
	const card = line({ index: 1 });
	const repos = [repo({ items: [item({ number: 42, lines: [card] })] })];
	const decisions = storeAnswering({ status: 'ruled', message: null });

	render(Stage, { repos, selectedKey: lineKey('repo', 42, card), decisions });
	screen.getByRole('button', { name: 'Ja' }).click();
	await tick();

	expect(screen.getByRole('button', { name: 'Ja' })).toBeDisabled();
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);
});

test('an already-ruled refusal hides the choices and offers a reload', async () => {
	const card = line({ index: 1 });
	const repos = [repo({ items: [item({ number: 42, lines: [card] })] })];
	const reload = vi.fn(async () => {});
	const decisions = storeAnswering({ status: 'already_ruled', message: null }, reload);

	render(Stage, { repos, selectedKey: lineKey('repo', 42, card), decisions });
	screen.getByRole('button', { name: 'Ja' }).click();
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

	expect(screen.getByRole('alert')).toHaveTextContent('Schon entschieden');
	expect(screen.queryByRole('group', { name: 'Entscheidung' })).not.toBeInTheDocument();

	screen.getByRole('button', { name: 'Neu laden' }).click();
	expect(reload).toHaveBeenCalledTimes(1);
});

test('a plain failure keeps the choices usable for a retry', async () => {
	const card = line({ index: 1 });
	const repos = [repo({ items: [item({ number: 42, lines: [card] })] })];
	const decisions = storeAnswering({ status: 'failed', message: 'aco rule failed: boom' });

	render(Stage, { repos, selectedKey: lineKey('repo', 42, card), decisions });
	screen.getByRole('button', { name: 'Ja' }).click();
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

	expect(screen.getByRole('alert')).toHaveTextContent('aco rule failed: boom');
	expect(screen.getByRole('group', { name: 'Entscheidung' })).toBeInTheDocument();
});
