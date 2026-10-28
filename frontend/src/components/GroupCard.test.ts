import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { expect, test, vi } from 'vitest';
import { cardOption, optionLine } from '../test-support/board';
import type { OptionLine } from '../types';
import GroupCard from './GroupCard.svelte';

const optionA = cardOption({ name: 'Keep it open' });
const optionB = cardOption({ letter: 'B', name: 'As today' });

function point(index: number, overrides: Partial<OptionLine> = {}): OptionLine {
	return optionLine({
		index,
		question: `Question ${index}?`,
		area: 'Song-Seite',
		recommended: 'A',
		options: [optionA, optionB],
		...overrides
	});
}

const points = [point(2), point(3), point(5)];

function renderCard(
	overrides: Partial<{
		points: OptionLine[];
		open: number | null;
		picks: { shown: OptionLine; option: ReturnType<typeof cardOption> }[];
		locked: boolean;
		pending: boolean;
		refreshing: boolean;
	}> = {}
) {
	const handlers = { onToggle: vi.fn(), onPick: vi.fn() };
	render(GroupCard, {
		repo: 'songmaker',
		item: 7,
		points,
		open: null,
		picks: [],
		locked: false,
		pending: false,
		refreshing: false,
		...handlers,
		...overrides
	});
	return handlers;
}

test('[ABRD-83] the card is titled by its name, carries the meta of its points and has no Problem row of its own', () => {
	renderCard();

	expect(screen.getByRole('heading', { name: 'Song-Seite · 3 points' })).toBeInTheDocument();
	expect(screen.getByText('songmaker › Song-Seite')).toBeInTheDocument();
	expect(screen.getByText('Product')).toBeInTheDocument();
	expect(screen.getByText('reversible')).toBeInTheDocument();
	expect(screen.queryByText('Problem')).not.toBeInTheDocument();
});

test('[ABRD-83] points in different areas and with their head show both in the meta', () => {
	renderCard({
		points: [
			point(2, { area: 'Song-Seite' }),
			point(3, { area: 'Bibliothek', returned_on: '2026-10-27' })
		]
	});

	expect(screen.getByText('songmaker › Song-Seite / Bibliothek')).toBeInTheDocument();
	expect(screen.getByText('with head')).toBeInTheDocument();
	expect(
		screen.getByRole('heading', { name: 'Song-Seite / Bibliothek · 2 points' })
	).toBeInTheDocument();
});

test('[ABRD-84] each point is a numbered row with its question, none open at first', () => {
	renderCard();

	const toggles = screen.getAllByRole('button', { expanded: false, name: /^\d/ });
	expect(toggles.map((toggle) => toggle.textContent?.replace(/\s+/g, ' ').trim())).toEqual([
		'1 Question 2?',
		'2 Question 3?',
		'3 Question 5?'
	]);
	expect(screen.getByText('Points', { selector: 'dt' })).toBeInTheDocument();
});

test('[ABRD-84] each point offers one pick per option, named by point, letter and option, the recommended one in the accent', () => {
	renderCard();

	const second = within(screen.getByRole('group', { name: 'Point 2' })).getAllByRole('button');
	expect(second.map((pick) => pick.getAttribute('aria-label'))).toEqual([
		'Point 2: A – Keep it open',
		'Point 2: B – As today'
	]);
	expect(second.map((pick) => pick.classList.contains('recommended'))).toEqual([true, false]);
});

test('[ABRD-84] a point with a final option carries the warn mark', () => {
	renderCard({
		points: [point(2), point(3, { options: [optionA, cardOption({ letter: 'B', undo: 'final' })] })]
	});

	const toggles = screen.getAllByRole('button', { name: /^\d/ });
	expect(toggles[0]?.querySelector('.final')).toBeNull();
	expect(toggles[1]?.querySelector('.final')).not.toBeNull();
});

test('[ABRD-85] activating a point’s question reports its line', async () => {
	const { onToggle } = renderCard();

	await fireEvent.click(screen.getByRole('button', { name: /Question 3\?/ }));

	expect(onToggle).toHaveBeenCalledWith(3);
});

test('[ABRD-85] the open point shows its Problem, Today, Options and Recommendation below its row', () => {
	renderCard({ open: 3 });

	const labels = screen.getAllByRole('term').map((term) => term.textContent);
	expect(labels).toEqual(['Points', '', 'Problem', 'Today', 'Options', 'Recommendation', '']);
	expect(screen.getByRole('button', { name: /Question 3\?/ })).toHaveAttribute(
		'aria-expanded',
		'true'
	);
	expect(screen.getByRole('button', { name: /Question 2\?/ })).toHaveAttribute(
		'aria-expanded',
		'false'
	);
});

test('[ABRD-86] a pick reports its point as shown and its option', async () => {
	const { onPick } = renderCard();

	await fireEvent.click(screen.getByRole('button', { name: 'Point 3: B – As today' }));

	expect(onPick).toHaveBeenCalledTimes(1);
	expect(onPick).toHaveBeenCalledWith(points[2], optionB);
});

test('[ABRD-86] a chosen point shows its pick pressed and the others not', () => {
	renderCard({ picks: [{ shown: points[0] as OptionLine, option: optionB }] });

	const pressed = screen
		.getAllByRole('button', { pressed: true })
		.map((pick) => pick.getAttribute('aria-label'));
	expect(pressed).toEqual(['Point 1: B – As today']);
	expect(screen.getAllByRole('button', { pressed: false })).toHaveLength(5);
});

test('[ABRD-65] a pending decision disables every pick', () => {
	renderCard({ pending: true });

	for (const pick of screen.getAllByRole('button', { name: /^Point \d: / })) {
		expect(pick).toBeDisabled();
	}
});

test('defect:#398 picks shown during a board re-read answer nothing', async () => {
	const { onPick } = renderCard({ refreshing: true });

	await fireEvent.click(screen.getByRole('button', { name: 'Point 1: A – Keep it open' }));

	expect(onPick).not.toHaveBeenCalled();
});

test('[ABRD-45] a card that needs Neu laden hides its picks and keeps its rows', () => {
	renderCard({ locked: true });

	expect(screen.queryByRole('group', { name: /^Point/ })).not.toBeInTheDocument();
	expect(screen.getAllByRole('button', { name: /^\d/ })).toHaveLength(3);
});

test('[ABRD-84] hostile texts render as text, never as markup', () => {
	const hostile = '<img src=x onerror=alert(1)>';
	const { container } = render(GroupCard, {
		repo: 'songmaker',
		item: 7,
		points: [point(2, { question: hostile, area: hostile }), point(3)],
		open: null,
		picks: [],
		locked: false,
		pending: false,
		refreshing: false,
		onToggle: vi.fn(),
		onPick: vi.fn()
	});

	expect(container.querySelector('img')).toBeNull();
	expect(screen.getByText(hostile, { exact: false, selector: '.question' })).toBeInTheDocument();
});
