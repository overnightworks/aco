import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import type { Pick } from '../app/model/card';
import { LINE_CHANGED_MESSAGE } from '../app/model/decision';
import { STATE_LABEL } from '../app/model/boardSummary';
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
		waiting?: boolean;
		saving?: boolean;
		banner?: DecisionBanner | null;
		points?: (typeof songCard)[];
		picks?: Pick[];
		escapes?: typeof escapes;
	} = {}
) {
	const onPick = vi.fn();
	const onAcceptAll = vi.fn();
	const onReload = vi.fn();
	const { container, component } = render(DecideRow, {
		points: [songCard],
		picks: [],
		pending: false,
		waiting: false,
		saving: false,
		banner: null,
		onPick,
		onAcceptAll,
		onReload,
		...overrides
	});
	return { container, component, onPick, onAcceptAll, onReload };
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
	const { onPick } = renderRow();

	await fireEvent.click(screen.getByRole('button', { name: /^Decide B:/ }));

	expect(onPick).toHaveBeenCalledTimes(1);
	expect(onPick).toHaveBeenCalledWith([songCard], { shown: songCard, option: songCard.options[1] });
});

test('[ABRD-44] a pending decision disables every pick', () => {
	renderRow({ pending: true });

	for (const pick of screen.getAllByRole('button')) {
		expect(pick).toBeDisabled();
	}
});

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
	renderRow({ points: [finalCard] });

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
] as const)(
	'[ABRD-65] Other… and Unclear hide with the picks once the card is %s',
	(_name, banner) => {
		renderRow({ escapes, banner });

		expect(screen.queryByRole('button', { name: 'Other…' })).toBeNull();
		expect(screen.queryByRole('button', { name: 'Unclear' })).toBeNull();
	}
);

test('[ABRD-65] a failed post keeps Other… and Unclear for a retry', () => {
	renderRow({ escapes, banner: { kind: 'failed', message: 'aco unavailable' } });

	expect(screen.getByRole('button', { name: 'Other…' })).toBeTruthy();
	expect(screen.getByRole('button', { name: 'Unclear' })).toBeTruthy();
});

test('[ABRD-72] a card with its head keeps its picks and Other… but offers no Unclear', () => {
	renderRow({
		escapes,
		points: [
			optionLine({
				options: songCard.options,
				returned_on: '2026-10-27',
				returned_note: 'Why?'
			})
		]
	});

	expect(screen.getByRole('button', { name: 'Other…' })).toBeTruthy();
	expect(screen.queryByRole('button', { name: 'Unclear' })).toBeNull();
	expect(within(screen.getByRole('group', { name: 'Decide' })).getAllByRole('button')).toHaveLength(
		3
	);
});

const optionA = cardOption({ name: 'Keep it open' });
const finalB = cardOption({
	letter: 'B',
	name: 'Delete it',
	undo: 'final',
	undo_how: 'nicht rückholbar.'
});

function groupPoint(index: number, overrides: Partial<typeof songCard> = {}) {
	return optionLine({
		index,
		recommended: 'A',
		options: [optionA, cardOption({ letter: 'B', name: 'As today' })],
		...overrides
	});
}

const groupPoints = [groupPoint(2), groupPoint(3), groupPoint(5)];

beforeEach(() => {
	HTMLDialogElement.prototype.showModal = function showModal() {
		this.setAttribute('open', '');
	};
	HTMLDialogElement.prototype.close = function close() {
		this.removeAttribute('open');
		this.dispatchEvent(new Event('close'));
	};
});

afterEach(() => {
	Reflect.deleteProperty(HTMLDialogElement.prototype, 'showModal');
	Reflect.deleteProperty(HTMLDialogElement.prototype, 'close');
});

test('[ABRD-89] a card of points leads its Decide row with Accept all in the accent, then the count, then the escapes', () => {
	renderRow({
		points: groupPoints,
		picks: [{ shown: groupPoints[0] as typeof songCard, option: optionA }],
		escapes
	});

	const names = screen.getAllByRole('button').map((button) => button.textContent?.trim());
	expect(names).toEqual(['Accept all', 'Other…', 'Unclear']);
	expect(screen.getByRole('button', { name: 'Accept all recommendations' })).toHaveClass(
		'recommended'
	);
	expect(screen.getByText('1 of 3 chosen')).toBeInTheDocument();
	expect(screen.queryByRole('group', { name: 'Decide' })).not.toBeInTheDocument();
});

test('[ABRD-89] Accept all with nothing final asks nothing and accepts the card as shown', async () => {
	const { onAcceptAll } = renderRow({ points: groupPoints });

	await fireEvent.click(screen.getByRole('button', { name: 'Accept all recommendations' }));

	expect(onAcceptAll).toHaveBeenCalledWith(groupPoints);
	expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});

test('[ABRD-90] Accept all with a final recommendation first asks, listing the points, and posts nothing on Cancel', async () => {
	const finalPoint = groupPoint(3, { options: [optionA, finalB], recommended: 'B' });
	const { onAcceptAll } = renderRow({ points: [groupPoint(2), finalPoint] });

	await fireEvent.click(screen.getByRole('button', { name: 'Accept all recommendations' }));

	const dialog = screen.getByRole('dialog');
	expect(within(dialog).getByRole('heading')).toHaveTextContent('Accept all recommendations?');
	expect(dialog).toHaveTextContent('Point 2: Nicht rückholbar.');
	await fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }));
	expect(onAcceptAll).not.toHaveBeenCalled();
	expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});

test('[ABRD-90] confirming Accept all accepts the card as it was shown when the confirm opened', async () => {
	const finalPoint = groupPoint(3, { options: [optionA, finalB], recommended: 'B' });
	const shown = [groupPoint(2), finalPoint];
	const { onAcceptAll } = renderRow({ points: shown });

	await fireEvent.click(screen.getByRole('button', { name: 'Accept all recommendations' }));
	await fireEvent.click(
		within(screen.getByRole('dialog')).getByRole('button', { name: 'Accept all' })
	);

	expect(onAcceptAll).toHaveBeenCalledWith(shown);
	expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});

test('[ABRD-88] a final pick on a card of points asks with its point, and Cancel leaves it unchosen', async () => {
	const finalPoint = groupPoint(3, { options: [optionA, finalB] });
	const shown = [groupPoint(2), finalPoint];
	const { component, onPick } = renderRow({ points: shown });

	await component.choose({ shown: finalPoint, option: finalB });

	const dialog = screen.getByRole('dialog');
	expect(within(dialog).getByRole('heading')).toHaveTextContent('Decide B?');
	expect(dialog).toHaveTextContent('Point 2: Nicht rückholbar.');
	await fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }));
	expect(onPick).not.toHaveBeenCalled();
});

test('[ABRD-47] confirming a final pick picks the option on the card as shown', async () => {
	const finalPoint = groupPoint(3, { options: [optionA, finalB] });
	const shown = [groupPoint(2), finalPoint];
	const { component, onPick } = renderRow({ points: shown });

	await component.choose({ shown: finalPoint, option: finalB });
	await fireEvent.click(
		within(screen.getByRole('dialog')).getByRole('button', { name: 'Decide B' })
	);

	expect(onPick).toHaveBeenCalledWith(shown, { shown: finalPoint, option: finalB });
});

test('[ABRD-65] a pending card disables Accept all', () => {
	renderRow({ points: groupPoints, pending: true, escapes });

	expect(screen.getByRole('button', { name: 'Accept all recommendations' })).toBeDisabled();
});

test.each([
	['changed', { kind: 'changed', message: LINE_CHANGED_MESSAGE }],
	['already ruled', { kind: 'already-ruled', message: 'Schon entschieden' }]
] as const)('[ABRD-45] Accept all and the escapes hide once the card is %s', (_name, banner) => {
	renderRow({ points: groupPoints, escapes, banner });

	expect(screen.queryByRole('button', { name: 'Accept all recommendations' })).toBeNull();
	expect(screen.queryByRole('button', { name: 'Other…' })).toBeNull();
	expect(screen.getByRole('button', { name: 'Neu laden' })).toBeInTheDocument();
});

test('[ABRD-63] Other… sits beside Accept all on a card of points', () => {
	renderRow({ points: groupPoints, escapes });

	expect(screen.getByRole('button', { name: 'Other…' })).toBeInTheDocument();
});

test('[ABRD-97] a pick, Accept all and a pick of a point during a board re-read reach their handlers', async () => {
	const { component, onAcceptAll, onPick } = renderRow({ points: groupPoints, escapes });

	await fireEvent.click(screen.getByRole('button', { name: 'Accept all recommendations' }));
	await component.choose({ shown: groupPoints[0] as typeof songCard, option: optionA });

	expect(onAcceptAll).toHaveBeenCalledWith(groupPoints);
	expect(onPick).toHaveBeenCalledWith(groupPoints, {
		shown: groupPoints[0],
		option: optionA
	});
});

test('[ABRD-99] a pick on a one-point row reaches its handler', async () => {
	const { onPick } = renderRow();

	await fireEvent.click(screen.getByRole('button', { name: /^Decide B:/ }));

	expect(onPick).toHaveBeenCalledWith([songCard], { shown: songCard, option: songCard.options[1] });
});

test('[ABRD-99] outside waiting no letter of a one-point row carries aria-pressed', () => {
	renderRow();

	const picks = within(screen.getByRole('group', { name: 'Decide' })).getAllByRole('button');
	for (const pick of picks) {
		expect(pick).not.toHaveAttribute('aria-pressed');
	}
});

test('[ABRD-99] a waiting one-point row presses the held letter and disables the rest, without the accent', () => {
	const held = songCard.options[0] as (typeof songCard.options)[number];
	renderRow({ waiting: true, pending: true, picks: [{ shown: songCard, option: held }] });

	const picks = within(screen.getByRole('group', { name: 'Decide' })).getAllByRole('button');
	expect(picks.map((pick) => pick.getAttribute('aria-pressed'))).toEqual([
		'true',
		'false',
		'false'
	]);
	for (const pick of picks) {
		expect(pick).toBeDisabled();
		expect(pick).not.toHaveClass('recommended');
	}
	expect(picks[0]).toHaveClass('chosen');
	expect(picks[1]).not.toHaveClass('chosen');
});

test('[ABRD-99] a waiting row after an Other answer presses no letter', () => {
	renderRow({ waiting: true, pending: true, picks: [], escapes });

	const picks = within(screen.getByRole('group', { name: 'Decide' })).getAllByRole('button');
	expect(picks.map((pick) => pick.getAttribute('aria-pressed'))).toEqual([
		'false',
		'false',
		'false'
	]);
});

test('[ABRD-100] a saving one-point row shows Saving in place of Other… and Unclear', () => {
	renderRow({ waiting: true, saving: true, pending: true, escapes });

	expect(screen.getByText(STATE_LABEL.saving)).toBeInTheDocument();
	expect(screen.queryByRole('button', { name: 'Other…' })).toBeNull();
	expect(screen.queryByRole('button', { name: 'Unclear' })).toBeNull();
});

test('[ABRD-100] a saving card of points locks Accept all, keeps its count and shows Saving', () => {
	renderRow({
		points: groupPoints,
		waiting: true,
		saving: true,
		pending: true,
		picks: groupPoints.map((point) => ({ shown: point, option: optionA })),
		escapes
	});

	expect(screen.getByRole('button', { name: 'Accept all recommendations' })).toBeDisabled();
	expect(screen.getByText('3 of 3 chosen')).toBeInTheDocument();
	expect(screen.getByText(STATE_LABEL.saving)).toBeInTheDocument();
	expect(screen.queryByRole('button', { name: 'Other…' })).toBeNull();
});
