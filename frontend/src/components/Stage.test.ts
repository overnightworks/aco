import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { tick } from 'svelte';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { DecisionStore } from '../app/state/decision.svelte';
import { cardKey, LINE_CHANGED_MESSAGE, UNDO_SECONDS, lineKey } from '../app/model/decision';
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
		decisions: storeAnswering({ status: 'ruled', message: null }),
		refreshing: false
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
		decisions: storeAnswering({ status: 'ruled', message: null }),
		refreshing: false
	});

	expect(screen.getByRole('heading', { name: 'Guests allowed?' })).toBeInTheDocument();
	expect(screen.getByText('Guests may join the call.')).toBeInTheDocument();
	expect(screen.getByText('Anna invites a guest.')).toBeInTheDocument();
	expect(screen.getByRole('button', { name: /Empfohlen/ })).toHaveTextContent('Ja');
	// The note stays collapsed: its textarea is present but not shown open.
	expect(screen.getByText('Notiz').closest('details')).not.toHaveAttribute('open');
});

test('[ABRD-44] a selected one-point card shows its card and offers the Decide picks, no outcome', () => {
	const card = optionLine({ index: 2, question: 'Keep the song open?' });
	const repos = [repo({ items: [item({ number: 42, lines: [card] })] })];

	render(Stage, {
		repos,
		selectedKey: cardKey('repo', 42),
		decisions: storeAnswering({ status: 'ruled', message: null }),
		refreshing: false
	});

	expect(screen.getByRole('heading', { name: 'Keep the song open?' })).toBeInTheDocument();
	expect(screen.getByText('Problem')).toBeInTheDocument();
	expect(screen.queryByRole('group', { name: 'Entscheidung' })).not.toBeInTheDocument();
	expect(screen.queryByText('Notiz')).not.toBeInTheDocument();
	expect(screen.queryByRole('button', { name: 'Accept all recommendations' })).toBeNull();
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
		decisions: storeAnswering({ status: 'ruled', message: null }),
		refreshing: false
	});

	expect(screen.queryByRole('group', { name: 'Decide' })).not.toBeInTheDocument();
});

test('[ABRD-44] picking an option disables the picks, then posts the card with exactly that letter', async () => {
	const card = optionLine({ index: 2, fingerprint: 'fp-option' });
	const repos = [repo({ items: [item({ number: 42, lines: [card] })] })];
	const send = vi.fn(async () => ({ status: 'ruled', message: null }) as DecisionResult);
	const decisions = new DecisionStore('token', async () => {}, send as never);

	render(Stage, { repos, selectedKey: cardKey('repo', 42), decisions, refreshing: false });
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
		lines: [{ line: 2, fingerprint: 'fp-option', option: 'B' }]
	});
});

test('[ABRD-45] a changed option card hides the picks until Neu laden reloads it', async () => {
	const card = optionLine({ index: 2 });
	const repos = [repo({ items: [item({ number: 42, lines: [card] })] })];
	const reload = vi.fn(async () => {});
	const decisions = storeAnswering({ status: 'failed', message: LINE_CHANGED_MESSAGE }, reload);

	render(Stage, { repos, selectedKey: cardKey('repo', 42), decisions, refreshing: false });
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
		decisions: storeAnswering({ status: 'ruled', message: null }),
		refreshing: false
	});

	const choices = screen.getByRole('group', { name: 'Entscheidung' });
	expect(
		within(choices)
			.getAllByRole('button')
			.map((button) => button.textContent?.trim())
	).toEqual(['Ja', 'Nein', 'Später']);
	expect(screen.queryByText('Problem')).not.toBeInTheDocument();
});

test('[ABRD-37] an already-ruled line of either form shows the decided card, never live choices', () => {
	const yesNo = line({
		index: 1,
		question: 'Guests allowed?',
		ruling: 'yes',
		ruled_on: '2026-10-01'
	});
	const option = optionLine({ index: 2, ruling: 'A', ruled_on: '2026-10-01', via: 'chat' });
	const repos = [repo({ items: [item({ number: 42, lines: [yesNo, option] })] })];
	const decisions = storeAnswering({ status: 'ruled', message: null });

	const view = render(Stage, {
		repos,
		selectedKey: lineKey('repo', 42, yesNo),
		decisions,
		refreshing: false
	});

	expect(screen.getByRole('heading', { name: 'Guests allowed?' })).toBeInTheDocument();
	expect(screen.getByText('Ja')).toBeInTheDocument();
	expect(screen.getByText('not recorded · 01.10.2026')).toBeInTheDocument();
	expect(screen.queryByRole('group', { name: 'Entscheidung' })).not.toBeInTheDocument();
	expect(screen.queryByText('Notiz')).not.toBeInTheDocument();

	view.rerender({ repos, selectedKey: lineKey('repo', 42, option), decisions, refreshing: false });

	expect(screen.getByText('How', { selector: 'dt' })).toBeInTheDocument();
	expect(screen.getByText('From chat · 01.10.2026')).toBeInTheDocument();
	expect(screen.queryByText('Problem')).not.toBeInTheDocument();
	expect(screen.queryByRole('group', { name: 'Decide' })).not.toBeInTheDocument();
});

test('choosing an outcome starts the undo window and disables the buttons', async () => {
	const card = line({ index: 1 });
	const repos = [repo({ items: [item({ number: 42, lines: [card] })] })];
	const decisions = storeAnswering({ status: 'ruled', message: null });

	render(Stage, { repos, selectedKey: lineKey('repo', 42, card), decisions, refreshing: false });
	screen.getByRole('button', { name: 'Ja' }).click();
	await tick();

	expect(screen.getByRole('button', { name: 'Ja' })).toBeDisabled();
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);
});

test('an already-ruled refusal hides the choices and offers a reload', async () => {
	const card = optionLine({ index: 2 });
	const repos = [repo({ items: [item({ number: 42, lines: [card] })] })];
	const reload = vi.fn(async () => {});
	const decisions = storeAnswering({ status: 'already_ruled', message: null }, reload);

	render(Stage, { repos, selectedKey: cardKey('repo', 42), decisions, refreshing: false });
	screen.getByRole('button', { name: /^Decide A:/ }).click();
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

	expect(screen.getByRole('alert')).toHaveTextContent('Schon entschieden');
	expect(screen.queryByRole('group', { name: 'Decide' })).not.toBeInTheDocument();

	screen.getByRole('button', { name: 'Neu laden' }).click();
	expect(reload).toHaveBeenCalledTimes(1);
});

test('a hostile picture is embedded only as an image, never as markup', () => {
	const hostile =
		'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)">' +
		'<script>alert(2)</script><foreignObject><iframe/></foreignObject></svg>';
	const card = optionLine({ index: 2, picture: hostile, caption: 'Today the song is lost.' });
	const repos = [repo({ items: [item({ number: 42, lines: [card] })] })];

	const { container } = render(Stage, {
		repos,
		selectedKey: cardKey('repo', 42),
		decisions: storeAnswering({ status: 'ruled', message: null }),
		refreshing: false
	});

	const image = screen.getByAltText('Today the song is lost.');
	expect(image.tagName).toBe('IMG');
	const source = image.getAttribute('src') ?? '';
	expect(source.startsWith('data:image/svg+xml;base64,')).toBe(true);
	const encoded = source.slice(source.indexOf(',') + 1);
	expect(Buffer.from(encoded, 'base64').toString('utf-8')).toBe(hostile);
	expect(container.querySelectorAll('script, foreignObject, iframe')).toHaveLength(0);
	expect(container.querySelectorAll('svg:not([aria-hidden="true"])')).toHaveLength(0);
});

test('hostile question, problem and reason render as text, never as markup', () => {
	const hostileQuestion = '"><img src=x onerror=alert(1)>';
	const hostileProblem = '<script>alert(2)</script>';
	const hostileReason = '<svg onload=alert(3)>';
	const card = optionLine({
		index: 2,
		question: hostileQuestion,
		problem: hostileProblem,
		reason: hostileReason
	});
	const repos = [repo({ items: [item({ number: 42, lines: [card] })] })];

	const { container } = render(Stage, {
		repos,
		selectedKey: cardKey('repo', 42),
		decisions: storeAnswering({ status: 'ruled', message: null }),
		refreshing: false
	});

	expect(screen.getByRole('heading', { name: hostileQuestion })).toBeInTheDocument();
	expect(screen.getByText(hostileProblem)).toBeInTheDocument();
	expect(screen.getByText(hostileReason)).toBeInTheDocument();
	expect(container.querySelectorAll('script, img[src="x"]')).toHaveLength(0);
	expect(container.querySelectorAll('svg:not([aria-hidden="true"])')).toHaveLength(0);
	expect(container.querySelector('[onerror], [onload]')).toBeNull();
});

test('a plain failure keeps the choices usable for a retry', async () => {
	const card = optionLine({ index: 2 });
	const repos = [repo({ items: [item({ number: 42, lines: [card] })] })];
	const decisions = storeAnswering({ status: 'failed', message: 'aco rule failed: boom' });

	render(Stage, { repos, selectedKey: cardKey('repo', 42), decisions, refreshing: false });
	screen.getByRole('button', { name: /^Decide A:/ }).click();
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

	expect(screen.getByRole('alert')).toHaveTextContent('aco rule failed: boom');
	expect(screen.getByRole('group', { name: 'Decide' })).toBeInTheDocument();
	expect(within(screen.getByRole('group', { name: 'Decide' })).getAllByRole('button')[0]).toBeEnabled();
});

function groupPoints() {
	return [2, 3, 5].map((index) =>
		optionLine({
			index,
			fingerprint: `fp-${index}`,
			question: `Question ${index}?`,
			area: 'Song-Seite',
			recommended: index === 3 ? 'B' : 'A'
		})
	);
}

function renderGroup(
	decisions: DecisionStore,
	points = groupPoints(),
	overrides: { refreshing?: boolean } = {}
) {
	const repos = [repo({ items: [item({ number: 7, lines: points })] })];
	return render(Stage, {
		repos,
		selectedKey: cardKey('repo', 7),
		decisions,
		refreshing: false,
		...overrides
	});
}

test('[ABRD-83] a card of points is titled by its name and offers Accept all, its count and the escapes, no pick of its own', () => {
	renderGroup(storeAnswering({ status: 'ruled', message: null }));

	expect(screen.getByRole('heading', { name: 'Song-Seite · 3 points' })).toBeInTheDocument();
	expect(screen.queryByRole('group', { name: 'Decide' })).not.toBeInTheDocument();
	expect(screen.getByRole('button', { name: 'Accept all recommendations' })).toHaveTextContent(
		'Accept all'
	);
	expect(screen.getByText('0 of 3 chosen')).toBeInTheDocument();
	expect(screen.getByRole('button', { name: 'Other…' })).toBeInTheDocument();
	expect(screen.getByRole('button', { name: 'Unclear' })).toBeInTheDocument();
});

test('[ABRD-85] activating a point opens it, and another point closes the first', async () => {
	renderGroup(storeAnswering({ status: 'ruled', message: null }));
	const first = screen.getByRole('button', { name: /Question 2\?/ });
	const second = screen.getByRole('button', { name: /Question 3\?/ });

	await fireEvent.click(first);
	expect(first).toHaveAttribute('aria-expanded', 'true');
	expect(screen.getAllByText('Problem', { selector: 'dt' })).toHaveLength(1);
	await fireEvent.click(second);

	expect(first).toHaveAttribute('aria-expanded', 'false');
	expect(second).toHaveAttribute('aria-expanded', 'true');
});

test('[ABRD-86] a pick marks its point and counts it, and posts nothing', async () => {
	const send = vi.fn(async () => ({ status: 'ruled', message: null }) as DecisionResult);
	renderGroup(new DecisionStore('token', async () => {}, send as never));

	screen.getByRole('button', { name: 'Point 1: B – As today' }).click();
	await tick();

	expect(screen.getByRole('button', { name: 'Point 1: B – As today' })).toHaveAttribute(
		'aria-pressed',
		'true'
	);
	expect(screen.getByText('1 of 3 chosen')).toBeInTheDocument();
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 2000);
	expect(send).not.toHaveBeenCalled();
});

test('[ABRD-87] the last pick waits out one window, then posts the whole card once', async () => {
	const send = vi.fn(async () => ({ status: 'ruled', message: null }) as DecisionResult);
	const decisions = new DecisionStore('token', async () => {}, send as never);
	renderGroup(decisions);

	for (const name of [
		'Point 1: B – As today',
		'Point 2: A – Keep the song open',
		'Point 3: B – As today'
	]) {
		screen.getByRole('button', { name }).click();
		await tick();
	}

	expect(decisions.pendingEntries.map((entry) => entry.message)).toEqual([
		'1B 2A 3B · Song-Seite · 3 points'
	]);
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);
	expect(send).toHaveBeenCalledTimes(1);
	expect(send).toHaveBeenCalledWith('token', {
		repo: 'repo',
		item: 7,
		lines: [
			{ line: 2, fingerprint: 'fp-2', option: 'B' },
			{ line: 3, fingerprint: 'fp-3', option: 'A' },
			{ line: 5, fingerprint: 'fp-5', option: 'B' }
		]
	});
});

test('[ABRD-89] Accept all picks each recommended letter and posts the card after the window', async () => {
	const send = vi.fn(async () => ({ status: 'ruled', message: null }) as DecisionResult);
	const decisions = new DecisionStore('token', async () => {}, send as never);
	renderGroup(decisions);

	screen.getByRole('button', { name: 'Accept all recommendations' }).click();
	await tick();

	expect(decisions.pendingEntries.map((entry) => entry.message)).toEqual([
		'1A 2B 3A · Song-Seite · 3 points'
	]);
	expect(screen.getByRole('button', { name: 'Accept all recommendations' })).toBeDisabled();
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);
	expect(send).toHaveBeenCalledWith('token', {
		repo: 'repo',
		item: 7,
		lines: [
			{ line: 2, fingerprint: 'fp-2', option: 'A' },
			{ line: 3, fingerprint: 'fp-3', option: 'B' },
			{ line: 5, fingerprint: 'fp-5', option: 'A' }
		]
	});
});

test('[ABRD-45] a changed card hides its picks and Accept all until Neu laden', async () => {
	const decisions = storeAnswering({ status: 'failed', message: LINE_CHANGED_MESSAGE });
	renderGroup(decisions);

	screen.getByRole('button', { name: 'Accept all recommendations' }).click();
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

	expect(screen.getByRole('alert')).toHaveTextContent(LINE_CHANGED_MESSAGE);
	expect(screen.queryByRole('group', { name: 'Point 1' })).not.toBeInTheDocument();
	expect(screen.queryByRole('button', { name: 'Accept all recommendations' })).toBeNull();
	expect(screen.getByRole('button', { name: 'Neu laden' })).toBeInTheDocument();
});

test('[ABRD-92] Other… answers the whole card', async () => {
	const send = vi.fn(async () => ({ status: 'ruled', message: null }) as DecisionResult);
	renderGroup(new DecisionStore('token', async () => {}, send as never));

	screen.getByRole('button', { name: 'Other…' }).click();
	await tick();
	const field = screen.getByRole('textbox', { name: 'Your answer' });
	field.focus();
	await fireEvent.input(field, { target: { value: 'Only on desktop' } });
	screen.getByRole('button', { name: 'Send' }).click();
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

	expect(send).toHaveBeenCalledWith('token', {
		repo: 'repo',
		item: 7,
		lines: [
			{ line: 2, fingerprint: 'fp-2' },
			{ line: 3, fingerprint: 'fp-3' },
			{ line: 5, fingerprint: 'fp-5' }
		],
		other: 'Only on desktop'
	});
});

test('[ABRD-61] a card of points with one point with its head offers no Unclear and keeps Accept all', () => {
	const points = groupPoints();
	points[1] = optionLine({ ...points[1], returned_on: '2026-10-27' });
	renderGroup(storeAnswering({ status: 'ruled', message: null }), points);

	expect(screen.queryByRole('button', { name: 'Unclear' })).toBeNull();
	expect(screen.getByRole('button', { name: 'Other…' })).toBeInTheDocument();
	expect(screen.getByRole('button', { name: 'Accept all recommendations' })).toBeInTheDocument();
});
