import { render, screen } from '@testing-library/svelte';
import { expect, test, vi } from 'vitest';
import UndoStrip from './UndoStrip.svelte';

test('[ABRD-58] shows the pick made with the Decided shape and offers to undo it', () => {
	const onUndo = vi.fn();
	render(UndoStrip, { message: 'B — Browser-Sprung bleibt · Sprung', onUndo });

	expect(screen.getByRole('img', { name: 'Decided' })).toBeInTheDocument();
	expect(screen.getByText('Decided: B — Browser-Sprung bleibt · Sprung')).toBeInTheDocument();

	screen.getByRole('button', { name: /^Undo$/ }).click();

	expect(onUndo).toHaveBeenCalledTimes(1);
});
