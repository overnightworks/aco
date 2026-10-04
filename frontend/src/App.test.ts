import { render, screen } from '@testing-library/svelte';
import { expect, test } from 'vitest';
import App from './App.svelte';

test('the shell names the board in its heading', () => {
	render(App);

	expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('aco-board');
});
