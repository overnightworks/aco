import { fireEvent, render, screen } from '@testing-library/svelte';
import { expect, test, vi } from 'vitest';
import { optionLine } from '../test-support/board';
import EscapeRow from './EscapeRow.svelte';

const card = optionLine({ fingerprint: 'fp-shown' });
const shown = [card];
const otherPanel = { kind: 'other', shown } as const;
const unclearPanel = { kind: 'unclear', shown } as const;

function renderRow(
	overrides: Partial<{
		points: (typeof card)[];
		panel: typeof otherPanel | typeof unclearPanel | null;
		draft: string;
		pending: boolean;
	}> = {}
) {
	const handlers = {
		onOpen: vi.fn(),
		onClose: vi.fn(),
		onDraft: vi.fn(),
		onSend: vi.fn()
	};
	render(EscapeRow, {
		points: shown,
		panel: null,
		draft: '',
		pending: false,
		...handlers,
		...overrides
	});
	return handlers;
}

test('[ABRD-63] Other… opens the panel with the card as shown now', async () => {
	const { onOpen } = renderRow();

	await fireEvent.click(screen.getByRole('button', { name: 'Other…' }));

	expect(onOpen).toHaveBeenCalledWith('other', shown);
});

test('[ABRD-63] an open panel has a focusable answer field named Your answer, and Other… closes it', async () => {
	const { onClose } = renderRow({ panel: otherPanel });

	const field = screen.getByRole('textbox', { name: 'Your answer' });
	expect(field.getAttribute('placeholder')).toBe('What should apply instead?');
	expect(field.getAttribute('maxlength')).toBe('280');
	expect(screen.getByRole('button', { name: 'Other…' }).getAttribute('aria-expanded')).toBe('true');
	await fireEvent.click(screen.getByRole('button', { name: 'Other…' }));
	expect(onClose).toHaveBeenCalled();
});

test.each(['', '   \n'])('[ABRD-63] Send stays disabled while the answer %j is blank', (draft) => {
	renderRow({ panel: otherPanel, draft });

	expect((screen.getByRole('button', { name: 'Send' }) as HTMLButtonElement).disabled).toBe(true);
});

test('[ABRD-66] typing reports the text for the draft', async () => {
	const { onDraft } = renderRow({ panel: otherPanel });

	await fireEvent.input(screen.getByRole('textbox', { name: 'Your answer' }), {
		target: { value: 'Only on desktop' }
	});

	expect(onDraft).toHaveBeenCalledWith('Only on desktop');
});

test('[ABRD-68] Send posts the card the panel opened with, not the one shown now', async () => {
	const { onSend } = renderRow({
		points: [optionLine({ fingerprint: 'fp-revised' })],
		panel: otherPanel,
		draft: 'Only on desktop'
	});

	await fireEvent.click(screen.getByRole('button', { name: 'Send' }));

	expect(onSend).toHaveBeenCalledWith(otherPanel, 'Only on desktop');
});

test('[ABRD-65] a pending decision disables Other… and Send', () => {
	renderRow({ panel: otherPanel, draft: 'x', pending: true });

	expect((screen.getByRole('button', { name: 'Other…' }) as HTMLButtonElement).disabled).toBe(true);
	expect((screen.getByRole('button', { name: 'Send' }) as HTMLButtonElement).disabled).toBe(true);
});

test('[ABRD-72] an open card offers Other… then Unclear, and Unclear opens its panel with the card as shown', async () => {
	const { onOpen } = renderRow();

	const names = screen.getAllByRole('button').map((button) => button.textContent?.trim());
	await fireEvent.click(screen.getByRole('button', { name: 'Unclear' }));

	expect(names).toEqual(['Other…', 'Unclear']);
	expect(onOpen).toHaveBeenCalledWith('unclear', shown);
});

test('[ABRD-72] a card with its head offers no Unclear and no Unclear panel, and keeps Other…', () => {
	const withHead = [optionLine({ returned_on: '2026-10-26', returned_note: null })];
	renderRow({ points: withHead, panel: { kind: 'unclear', shown: withHead } });

	expect(screen.queryByRole('button', { name: 'Unclear' })).toBeNull();
	expect(screen.queryByRole('textbox')).toBeNull();
	expect(screen.getByRole('button', { name: 'Other…' })).toBeTruthy();
});

test('[ABRD-73] the Unclear panel has an optional note field and a Send that is enabled while blank', async () => {
	const { onSend, onClose } = renderRow({ panel: unclearPanel });

	const field = screen.getByRole('textbox', { name: 'What is unclear? (optional)' });
	expect(field.getAttribute('placeholder')).toBe('Optional: what is unclear?');
	expect(field.getAttribute('maxlength')).toBe('280');
	expect(screen.getByRole('button', { name: 'Unclear' }).getAttribute('aria-expanded')).toBe(
		'true'
	);
	expect(screen.getByRole('button', { name: 'Other…' }).getAttribute('aria-expanded')).toBe(
		'false'
	);
	await fireEvent.click(screen.getByRole('button', { name: 'Send' }));
	expect(onSend).toHaveBeenCalledWith(unclearPanel, '');
	await fireEvent.click(screen.getByRole('button', { name: 'Unclear' }));
	expect(onClose).toHaveBeenCalled();
});

test('[ABRD-75] a pending decision disables Unclear and its Send', () => {
	renderRow({ panel: unclearPanel, pending: true });

	expect((screen.getByRole('button', { name: 'Unclear' }) as HTMLButtonElement).disabled).toBe(
		true
	);
	expect((screen.getByRole('button', { name: 'Send' }) as HTMLButtonElement).disabled).toBe(true);
});

test('[ABRD-72] a card of points offers no Unclear once any point is with its head', () => {
	const points = [optionLine({ index: 2 }), optionLine({ index: 3, returned_on: '2026-10-26' })];
	renderRow({ points });

	expect(screen.queryByRole('button', { name: 'Unclear' })).toBeNull();
	expect(screen.getByRole('button', { name: 'Other…' })).toBeTruthy();
});
