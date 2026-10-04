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

test('an already-ruled selected line shows a read-only box, never live choice buttons', () => {
	const card = line({
		index: 1,
		question: 'Guests allowed?',
		ruling: 'yes',
		ruled_on: '2026-10-01'
	});
	const repos = [repo({ items: [item({ number: 42, lines: [card] })] })];

	render(Stage, {
		repos,
		selectedKey: lineKey('repo', 42, card),
		decisions: storeAnswering({ status: 'ruled', message: null })
	});

	expect(screen.getByRole('heading', { name: 'Guests allowed?' })).toBeInTheDocument();
	expect(screen.getByText('Ja · 2026-10-01')).toBeInTheDocument();
	expect(screen.queryByRole('group', { name: 'Entscheidung' })).not.toBeInTheDocument();
	expect(screen.queryByText('Notiz')).not.toBeInTheDocument();
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

test('a hostile picture is embedded only as an image, never as markup', () => {
	const hostile =
		'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)">' +
		'<script>alert(2)</script><foreignObject><iframe/></foreignObject></svg>';
	const card = line({ index: 1, question: 'Guests allowed?', picture: hostile });
	const repos = [repo({ items: [item({ number: 42, lines: [card] })] })];

	const { container } = render(Stage, {
		repos,
		selectedKey: lineKey('repo', 42, card),
		decisions: storeAnswering({ status: 'ruled', message: null })
	});

	const image = screen.getByAltText('Bild zur Frage');
	expect(image.tagName).toBe('IMG');
	const source = image.getAttribute('src') ?? '';
	expect(source.startsWith('data:image/svg+xml;base64,')).toBe(true);
	const encoded = source.slice(source.indexOf(',') + 1);
	expect(Buffer.from(encoded, 'base64').toString('utf-8')).toBe(hostile);
	expect(container.querySelectorAll('svg, script, foreignObject, iframe')).toHaveLength(0);
});

test('hostile question, sentence and example text render as text, never as markup', () => {
	const hostileQuestion = '"><img src=x onerror=alert(1)>';
	const hostileExample = '<script>alert(2)</script>';
	const card = line({
		index: 1,
		question: hostileQuestion,
		text: 'Guests may join the call.',
		example: hostileExample
	});
	const repos = [repo({ items: [item({ number: 42, lines: [card] })] })];

	const { container } = render(Stage, {
		repos,
		selectedKey: lineKey('repo', 42, card),
		decisions: storeAnswering({ status: 'ruled', message: null })
	});

	expect(screen.getByRole('heading', { name: hostileQuestion })).toBeInTheDocument();
	expect(screen.getByText(hostileExample)).toBeInTheDocument();
	expect(container.querySelectorAll('script, svg, img')).toHaveLength(0);
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
