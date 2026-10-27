import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { expect, test, vi } from 'vitest';
import { LINE_CHANGED_MESSAGE } from '../app/model/decision';
import type { DecisionBanner } from '../app/state/decision.svelte';
import { cardOption, optionLine } from '../test-support/board';
import DecideRow from './DecideRow.svelte';

const songCard = optionLine({
	recommended: 'B',
	options: [
		cardOption({ name: 'Song stays open' }),
		cardOption({ letter: 'B', name: 'As today' }),
		cardOption({ letter: 'C', name: '<img src=x onerror=alert(1)>' })
	]
});

const escapes = {
	panel: null,
	draft: '',
	onOpen: vi.fn(),
	onClose: vi.fn(),
	onDraft: vi.fn(),
	onSend: vi.fn()
};

function renderRow(
	overrides: {
		pending?: boolean;
		refreshing?: boolean;
		banner?: DecisionBanner | null;
		line?: typeof songCard;
		escapes?: typeof escapes;
	} = {}
) {
	const onDecide = vi.fn();
	const onReload = vi.fn();
	const { container } = render(DecideRow, {
		line: songCard,
		pending: false,
		refreshing: false,
		banner: null,
		onDecide,
		onReload,
		...overrides
	});
	return { container, onDecide, onReload };
}

test('[ABRD-44] the Decide group holds one pick per option in letter order, named by letter and option', () => {
	renderRow();

	const picks = within(screen.getByRole('group', { name: 'Decide' })).getAllByRole('button');
	expect(picks.map((pick) => pick.getAttribute('aria-label'))).toEqual([
		'Decide A: Song stays open',
		'Decide B: As today',
		'Decide C: <img src=x onerror=alert(1)>'
	]);
	expect(picks.map((pick) => pick.textContent?.trim())).toEqual(['A', 'B', 'C']);
});

test('[ABRD-44] only the recommended pick carries the recommended look', () => {
	renderRow();

	const recommended = screen
		.getAllByRole('button')
		.filter((pick) => pick.classList.contains('recommended'));
	expect(recommended.map((pick) => pick.textContent?.trim())).toEqual(['B']);
});

test('[ABRD-44] clicking a pick decides exactly that option', async () => {
	const { onDecide } = renderRow();

	await fireEvent.click(screen.getByRole('button', { name: /^Decide B:/ }));

	expect(onDecide).toHaveBeenCalledTimes(1);
	expect(onDecide).toHaveBeenCalledWith(songCard, songCard.options[1]);
});

test('[ABRD-44] a pending decision disables every pick', () => {
	renderRow({ pending: true });

	for (const pick of screen.getAllByRole('button')) {
		expect(pick).toBeDisabled();
	}
});

test('defect:#398 picks shown during a board re-read answer nothing', async () => {
	const { onDecide } = renderRow({ refreshing: true });

	for (const pick of screen.getAllByRole('button')) {
		expect(pick).toHaveAttribute('aria-disabled', 'true');
	}
	await fireEvent.click(screen.getByRole('button', { name: /^Decide B:/ }));

	expect(onDecide).not.toHaveBeenCalled();
});

test.each([
	['changed', LINE_CHANGED_MESSAGE],
	['already-ruled', 'Schon entschieden: diese Zeile wurde inzwischen woanders entschieden.']
] as const)(
	'a %s refusal shows its sentence and Neu laden, with no pick',
	async (kind, message) => {
		const { onReload } = renderRow({ banner: { kind, message } });

		expect(screen.getByRole('alert')).toHaveTextContent(message);
		expect(screen.queryByRole('group', { name: 'Decide' })).not.toBeInTheDocument();
		await fireEvent.click(screen.getByRole('button', { name: 'Neu laden' }));
		expect(onReload).toHaveBeenCalledTimes(1);
	}
);

test('[ABRD-45] any other failure shows its sentence and keeps the picks usable', () => {
	renderRow({ banner: { kind: 'failed', message: 'Das Board ist nicht erreichbar.' } });

	expect(screen.getByRole('alert')).toHaveTextContent('Das Board ist nicht erreichbar.');
	expect(screen.queryByRole('button', { name: 'Neu laden' })).not.toBeInTheDocument();
	for (const pick of screen.getAllByRole('button')) {
		expect(pick).toBeEnabled();
	}
});

test('[ABRD-44] a hostile option name is text, never markup', () => {
	const { container } = renderRow();

	expect(container.querySelector('img')).toBeNull();
});

test('[ABRD-46] a closed confirm adds no button and no visible dialog to a row with a final option', () => {
	const finalCard = optionLine({
		options: [
			cardOption(),
			cardOption({ letter: 'B', undo: 'final', undo_how: 'nicht rückholbar.' })
		]
	});
	render(DecideRow, {
		line: finalCard,
		pending: false,
		refreshing: false,
		banner: null,
		onDecide: vi.fn(),
		onReload: vi.fn()
	});

	const picks = within(screen.getByRole('group', { name: 'Decide' })).getAllByRole('button');
	expect(screen.getAllByRole('button')).toHaveLength(picks.length);
	expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});

test('[ABRD-63] Other… sits beside the picks, outside the Decide group, so the pick count stays', () => {
	renderRow({ escapes });

	const picks = within(screen.getByRole('group', { name: 'Decide' })).getAllByRole('button');
	expect(picks).toHaveLength(3);
	expect(screen.getByRole('button', { name: 'Other…' })).toBeTruthy();
	expect(picks.map((pick) => pick.textContent?.trim())).not.toContain('Other…');
});

test('[ABRD-63] a row given no escapes offers no Other…', () => {
	renderRow();

	expect(screen.queryByRole('button', { name: 'Other…' })).toBeNull();
});

test.each([
	['changed', { kind: 'changed', message: LINE_CHANGED_MESSAGE }],
	['already ruled', { kind: 'already-ruled', message: 'Schon entschieden' }]
] as const)('[ABRD-65] Other… hides with the picks once the card is %s', (_name, banner) => {
	renderRow({ escapes, banner });

	expect(screen.queryByRole('button', { name: 'Other…' })).toBeNull();
	expect(screen.queryByRole('button', { name: 'Unclear' })).toBeNull();
});

test('[ABRD-65] a failed post keeps Other… and Unclear for a retry', () => {
	renderRow({ escapes, banner: { kind: 'failed', message: 'aco unavailable' } });

	expect(screen.getByRole('button', { name: 'Other…' })).toBeTruthy();
	expect(screen.getByRole('button', { name: 'Unclear' })).toBeTruthy();
});

test('[ABRD-72] a card with its head keeps its picks and Other… but offers no Unclear', () => {
	renderRow({
		escapes,
		line: optionLine({
			options: songCard.options,
			returned_on: '2026-10-27',
			returned_note: 'Why?'
		})
	});

	expect(screen.getByRole('button', { name: 'Other…' })).toBeTruthy();
	expect(screen.queryByRole('button', { name: 'Unclear' })).toBeNull();
	expect(within(screen.getByRole('group', { name: 'Decide' })).getAllByRole('button')).toHaveLength(
		3
	);
});
