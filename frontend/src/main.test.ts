import { screen } from '@testing-library/svelte';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { TOKEN_STORAGE_KEY } from './app/state/session';

beforeEach(() => {
	vi.resetModules();
	window.sessionStorage.clear();
	window.history.replaceState(null, '', '/');
});

afterEach(() => {
	document.body.replaceChildren();
	window.sessionStorage.clear();
	window.history.replaceState(null, '', '/');
});

test('starting the page mounts the board shell into #app', async () => {
	document.body.innerHTML = '<div id="app"></div>';

	await import('./main');

	expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('aco-board');
});

test('starting a page without #app fails loud', async () => {
	await expect(import('./main')).rejects.toThrow('#app');
});

test('a hash token is carried into session storage and the URL fragment is gone before mount', async () => {
	document.body.innerHTML = '<div id="app"></div>';
	window.history.replaceState(null, '', '/?x=1#t=my-token');

	await import('./main');

	expect(window.location.hash).toBe('');
	expect(window.sessionStorage.getItem(TOKEN_STORAGE_KEY)).toBe('my-token');
});
