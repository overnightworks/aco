import { screen } from '@testing-library/svelte';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

beforeEach(() => {
	vi.resetModules();
});

afterEach(() => {
	document.body.replaceChildren();
});

test('starting the page mounts the board shell into #app', async () => {
	document.body.innerHTML = '<div id="app"></div>';

	await import('./main');

	expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('aco-board');
});

test('starting a page without #app fails loud', async () => {
	await expect(import('./main')).rejects.toThrow('#app');
});
