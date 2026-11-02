import { render, screen } from '@testing-library/svelte';
import { expect, test, vi } from 'vitest';
import { READING_LABEL, REFRESH_LABEL, clockTime } from '../app/model/boardSummary';
import RefreshButton from './RefreshButton.svelte';

const readAt = new Date(2026, 9, 31, 9, 41);
const time = clockTime(readAt);

test('[ABRD-104] an idle button shows Refresh and the read time and is named with both', () => {
	render(RefreshButton, { reading: false, readAt, onRefresh: vi.fn() });

	const button = screen.getByRole('button', { name: `${REFRESH_LABEL} · read ${time}` });
	expect(button).toHaveTextContent(REFRESH_LABEL);
	expect(button).toHaveTextContent(time);
	expect(button).toHaveAttribute('title', `${REFRESH_LABEL} · read ${time}`);
	expect(button).toHaveAttribute('aria-busy', 'false');
});

test('[ABRD-104] a reading button says Reading…, is busy, and is never disabled', () => {
	render(RefreshButton, { reading: true, readAt, onRefresh: vi.fn() });

	const button = screen.getByRole('button', { name: `${READING_LABEL} · read ${time}` });
	expect(button).toHaveAttribute('aria-busy', 'true');
	expect(button).toBeEnabled();
});

test('[ABRD-103] every click asks for a read, also while one runs', () => {
	const onRefresh = vi.fn();
	render(RefreshButton, { reading: true, readAt, onRefresh });
	const button = screen.getByRole('button');

	button.click();
	button.click();

	expect(onRefresh).toHaveBeenCalledTimes(2);
});

test('[ABRD-104] before any read the button shows no time', () => {
	render(RefreshButton, { reading: false, readAt: null, onRefresh: vi.fn() });

	expect(screen.getByRole('button', { name: REFRESH_LABEL })).toHaveTextContent(REFRESH_LABEL);
});
