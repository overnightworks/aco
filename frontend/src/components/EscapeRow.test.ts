import { fireEvent, render, screen } from '@testing-library/svelte';
import { expect, test, vi } from 'vitest';
import { optionLine } from '../test-support/board';
import EscapeRow from './EscapeRow.svelte';

const shown = optionLine({ fingerprint: 'fp-shown' });

function renderRow(
	overrides: Partial<{
		line: typeof shown;
		panel: typeof shown | null;
		draft: string;
		pending: boolean;
		refreshing: boolean;
	}> = {}
) {
	const handlers = {
		onOpen: vi.fn(),
		onClose: vi.fn(),
		onDraft: vi.fn(),
		onSend: vi.fn()
	};
	render(EscapeRow, {
		line: shown,
		panel: null,
		draft: '',
		pending: false,
		refreshing: false,
		...handlers,
		...overrides
	});
	return handlers;
}

test('[ABRD-63] Other… opens the panel with the card as shown now', async () => {
	const { onOpen } = renderRow();

	await fireEvent.click(screen.getByRole('button', { name: 'Other…' }));

	expect(onOpen).toHaveBeenCalledWith(shown);
});

test('[ABRD-63] an open panel has a focusable answer field named Your answer, and Other… closes it', async () => {
	const { onClose } = renderRow({ panel: shown });

	const field = screen.getByRole('textbox', { name: 'Your answer' });
	expect(field.getAttribute('placeholder')).toBe('What should apply instead?');
	expect(field.getAttribute('maxlength')).toBe('280');
	expect(screen.getByRole('button', { name: 'Other…' }).getAttribute('aria-expanded')).toBe('true');
	await fireEvent.click(screen.getByRole('button', { name: 'Other…' }));
	expect(onClose).toHaveBeenCalled();
});

test.each(['', '   \n'])('[ABRD-63] Send stays disabled while the answer %j is blank', (draft) => {
	renderRow({ panel: shown, draft });

	expect((screen.getByRole('button', { name: 'Send' }) as HTMLButtonElement).disabled).toBe(true);
});

test('[ABRD-66] typing reports the text for the draft', async () => {
	const { onDraft } = renderRow({ panel: shown });

	await fireEvent.input(screen.getByRole('textbox', { name: 'Your answer' }), {
		target: { value: 'Only on desktop' }
	});

	expect(onDraft).toHaveBeenCalledWith('Only on desktop');
});

test('[ABRD-68] Send posts the card the panel opened with, not the one shown now', async () => {
	const { onSend } = renderRow({
		line: optionLine({ fingerprint: 'fp-revised' }),
		panel: shown,
		draft: 'Only on desktop'
	});

	await fireEvent.click(screen.getByRole('button', { name: 'Send' }));

	expect(onSend).toHaveBeenCalledWith(shown, 'Only on desktop');
});

test('[ABRD-65] a pending decision disables Other… and Send', () => {
	renderRow({ panel: shown, draft: 'x', pending: true });

	expect((screen.getByRole('button', { name: 'Other…' }) as HTMLButtonElement).disabled).toBe(true);
	expect((screen.getByRole('button', { name: 'Send' }) as HTMLButtonElement).disabled).toBe(true);
});

test('[ABRD-65] while the board refreshes Other… and Send do nothing', async () => {
	const { onOpen, onSend } = renderRow({ panel: shown, draft: 'x', refreshing: true });

	await fireEvent.click(screen.getByRole('button', { name: 'Send' }));
	await fireEvent.click(screen.getByRole('button', { name: 'Other…' }));

	expect(onSend).not.toHaveBeenCalled();
	expect(onOpen).not.toHaveBeenCalled();
});
