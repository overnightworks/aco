import { render, screen } from '@testing-library/svelte';
import { expect, test, vi } from 'vitest';
import UndoStrip from './UndoStrip.svelte';

test('[ABRD-58] shows the pick made with the Decided shape and offers to undo it', () => {
	const onUndo = vi.fn();
	render(UndoStrip, { message: 'B — Browser-Sprung bleibt · Sprung', kind: 'done', onUndo });

	expect(screen.getByRole('img', { name: 'Decided' })).toBeInTheDocument();
	expect(screen.getByText('Decided: B — Browser-Sprung bleibt · Sprung')).toBeInTheDocument();

	screen.getByRole('button', { name: /^Undo$/ }).click();

	expect(onUndo).toHaveBeenCalledTimes(1);
});

test('[ABRD-74] a card on its way to its head shows the With head shape, grey, and offers Undo', () => {
	const { container } = render(UndoStrip, { message: 'Jump', kind: 'back', onUndo: vi.fn() });

	expect(screen.getByRole('img', { name: 'With head' })).toBeInTheDocument();
	expect(screen.getByText('With head: Jump')).toBeInTheDocument();
	expect(container.querySelector('.strip')).toHaveClass('back');
	expect(screen.getByRole('button', { name: /^Undo$/ })).toHaveFocus();
});
