import { render, screen, within } from '@testing-library/svelte';
import { tick } from 'svelte';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { DecisionStore } from '../app/state/decision.svelte';
import { LINE_CHANGED_MESSAGE, UNDO_SECONDS, lineKey } from '../app/model/decision';
import { item, line, optionLine, repo } from '../test-support/board';
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

test('with nothing selected, the stage says no question is selected', () => {
	render(Stage, {
		repos: [],
		selectedKey: null,
		decisions: storeAnswering({ status: 'ruled', message: null })
	});

	expect(screen.getByText('Keine Frage ausgewählt.')).toBeInTheDocument();
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

test('[ABRD-44] a selected option line shows its card and offers the Decide picks, no outcome', () => {
	const card = optionLine({ index: 2, question: 'Keep the song open?' });
	const repos = [repo({ items: [item({ number: 42, lines: [card] })] })];

	render(Stage, {
		repos,
		selectedKey: lineKey('repo', 42, card),
		decisions: storeAnswering({ status: 'ruled', message: null })
	});

	expect(screen.getByRole('heading', { name: 'Keep the song open?' })).toBeInTheDocument();
	expect(screen.getByText('Problem')).toBeInTheDocument();
	expect(screen.queryByRole('group', { name: 'Entscheidung' })).not.toBeInTheDocument();
	expect(screen.queryByText('Notiz')).not.toBeInTheDocument();
	const picks = within(screen.getByRole('group', { name: 'Decide' })).getAllByRole('button');
	expect(picks.map((pick) => pick.textContent?.trim())).toEqual(['A', 'B']);
	const buttons = screen.getAllByRole('button');
	const disclosures = buttons.filter((button) => button.hasAttribute('aria-expanded'));
	expect(disclosures.length).toBeGreaterThan(0);
	for (const button of disclosures) {
		expect(button).toHaveAttribute('aria-expanded', 'false');
	}
	expect(buttons.length - disclosures.length - picks.length).toBe(1);
	expect(screen.getByRole('button', { name: 'Enlarge picture' })).toBeInTheDocument();
});

test('[ABRD-44] a ruled option line offers no Decide group', () => {
	const card = optionLine({ index: 2, ruling: 'A', ruled_on: '2026-10-01' });
	const repos = [repo({ items: [item({ number: 42, lines: [card] })] })];

	render(Stage, {
		repos,
		selectedKey: lineKey('repo', 42, card),
		decisions: storeAnswering({ status: 'ruled', message: null })
	});

	expect(screen.queryByRole('group', { name: 'Decide' })).not.toBeInTheDocument();
});

test('[ABRD-44] picking an option disables the picks, then posts exactly that letter', async () => {
	const card = optionLine({ index: 2, fingerprint: 'fp-option' });
	const repos = [repo({ items: [item({ number: 42, lines: [card] })] })];
	const send = vi.fn(async () => ({ status: 'ruled', message: null }) as DecisionResult);
	const decisions = new DecisionStore('token', async () => {}, send as never);

	render(Stage, { repos, selectedKey: lineKey('repo', 42, card), decisions });
	screen.getByRole('button', { name: /^Decide B:/ }).click();
	await tick();

	for (const pick of within(screen.getByRole('group', { name: 'Decide' })).getAllByRole('button')) {
		expect(pick).toBeDisabled();
	}
	expect(send).not.toHaveBeenCalled();
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);
	expect(send).toHaveBeenCalledWith('token', {
		repo: 'repo',
		item: 42,
		line: 2,
		fingerprint: 'fp-option',
		option: 'B'
	});
});

test('[ABRD-45] a changed option card hides the picks until Neu laden reloads it', async () => {
	const card = optionLine({ index: 2 });
	const repos = [repo({ items: [item({ number: 42, lines: [card] })] })];
	const reload = vi.fn(async () => {});
	const decisions = storeAnswering({ status: 'failed', message: LINE_CHANGED_MESSAGE }, reload);

	render(Stage, { repos, selectedKey: lineKey('repo', 42, card), decisions });
	screen.getByRole('button', { name: /^Decide A:/ }).click();
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

	expect(screen.getByRole('alert')).toHaveTextContent(LINE_CHANGED_MESSAGE);
	expect(screen.queryByRole('group', { name: 'Decide' })).not.toBeInTheDocument();
	screen.getByRole('button', { name: 'Neu laden' }).click();
	expect(reload).toHaveBeenCalledTimes(1);
});

test('a selected yes/no line still offers Ja, Nein and Später', () => {
	const card = line({ index: 2, question: 'Guests allowed?' });
	const repos = [repo({ items: [item({ number: 42, lines: [card] })] })];

	render(Stage, {
		repos,
		selectedKey: lineKey('repo', 42, card),
		decisions: storeAnswering({ status: 'ruled', message: null })
	});

	const choices = screen.getByRole('group', { name: 'Entscheidung' });
	expect(
		within(choices)
			.getAllByRole('button')
			.map((button) => button.textContent?.trim())
	).toEqual(['Ja', 'Nein', 'Später']);
	expect(screen.queryByText('Problem')).not.toBeInTheDocument();
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

test('hostile question, sentence, example and item title render as text, never as markup', () => {
	const hostileQuestion = '"><img src=x onerror=alert(1)>';
	const hostileSentence = '<script>alert(2)</script>';
	const hostileExample = '<svg onload=alert(3)>';
	const hostileTitle = '<img src=x onerror=alert(4)>';
	const card = line({
		index: 1,
		question: hostileQuestion,
		text: hostileSentence,
		example: hostileExample
	});
	const repos = [repo({ items: [item({ number: 42, title: hostileTitle, lines: [card] })] })];

	const { container } = render(Stage, {
		repos,
		selectedKey: lineKey('repo', 42, card),
		decisions: storeAnswering({ status: 'ruled', message: null })
	});

	expect(screen.getByRole('heading', { name: hostileQuestion })).toBeInTheDocument();
	expect(screen.getByText(hostileSentence)).toBeInTheDocument();
	expect(screen.getByText(hostileExample)).toBeInTheDocument();
	expect(screen.getByText(`#42 · ${hostileTitle} · Zeile 1`)).toBeInTheDocument();
	expect(container.querySelectorAll('script, svg, img')).toHaveLength(0);
	expect(container.querySelector('[onerror], [onload]')).toBeNull();
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
