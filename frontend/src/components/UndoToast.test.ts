import { render, screen } from '@testing-library/svelte';
import { expect, test, vi } from 'vitest';
import UndoToast from './UndoToast.svelte';

test('shows the decision made and offers to undo it', () => {
	const onUndo = vi.fn();
	render(UndoToast, { message: 'Ja: Guests allowed?', onUndo });

	expect(screen.getByRole('status')).toHaveTextContent('Ja: Guests allowed?');

	screen.getByRole('button', { name: 'Rückgängig' }).click();

	expect(onUndo).toHaveBeenCalledTimes(1);
});
