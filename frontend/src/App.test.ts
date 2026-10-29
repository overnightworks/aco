import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { afterEach, expect, test, vi } from 'vitest';
import App from './App.svelte';
import { item, line, optionLine, repo } from './test-support/board';

function fakeFetch(status: number, body: unknown) {
	return vi.fn(async () => ({
		ok: status >= 200 && status < 300,
		status,
		json: async () => body
	}));
}

afterEach(() => {
	vi.unstubAllGlobals();
});

test('the shell names the board in its heading, whatever the state', () => {
	render(App, { token: null });

	expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Entscheidungs-Board');
});

test('[ABRD-51] a ready board offers the Open and Decided tabs with their counts, the current one marked', async () => {
	const repos = [
		repo({
			items: [
				item({
					number: 42,
					lines: [
						optionLine({ index: 1 }),
						line({ index: 3, ruling: 'yes', ruled_on: '2026-10-01' })
					]
				}),
				item({ number: 43, lines: [optionLine({ topic: 'Zweiter' })] })
			]
		})
	];
	vi.stubGlobal('fetch', fakeFetch(200, { repos }));

	render(App, { token: 'a-token' });
	const views = await screen.findByRole('navigation', { name: 'Views' });
	const open = within(views).getByRole('button', { name: 'Open 2' });
	const decided = within(views).getByRole('button', { name: 'Decided 1' });

	expect(within(views).getAllByRole('button')).toHaveLength(2);
	expect(open).toHaveAttribute('aria-current', 'page');
	expect(decided).not.toHaveAttribute('aria-current');

	await fireEvent.click(decided);

	expect(decided).toHaveAttribute('aria-current', 'page');
	expect(open).not.toHaveAttribute('aria-current');
});

test('without a token in this tab, the shell shows access is missing and makes no request', () => {
	const fetchImpl = fakeFetch(200, { repos: [] });
	vi.stubGlobal('fetch', fetchImpl);

	render(App, { token: null });

	expect(screen.getByRole('alert')).toHaveTextContent('Zugang fehlt');
	expect(fetchImpl).not.toHaveBeenCalled();
});

test('while the board is loading, the shell shows it is waiting on aco', () => {
	vi.stubGlobal(
		'fetch',
		vi.fn(() => new Promise(() => {}))
	);

	render(App, { token: 'a-token' });

	expect(screen.getByRole('status')).toHaveTextContent('Lädt');
});

test('once aco cannot be reached, the shell says so', async () => {
	vi.stubGlobal('fetch', fakeFetch(502, { error: 'aco rulings failed' }));

	render(App, { token: 'a-token' });

	expect(await screen.findByRole('alert')).toHaveTextContent('aco antwortet nicht');
});

test('a board with no open or ruled lines shows the empty message', async () => {
	vi.stubGlobal('fetch', fakeFetch(200, { repos: [repo({ items: [] })] }));

	render(App, { token: 'a-token' });

	expect(await screen.findByText('All decided')).toBeInTheDocument();
});

test('a board with lines shows the track list', async () => {
	const repos = [repo({ items: [item({ number: 42, title: 'Share page', lines: [optionLine()] })] })];
	vi.stubGlobal('fetch', fakeFetch(200, { repos }));

	render(App, { token: 'a-token' });

	expect(await screen.findByRole('heading', { name: 'repo 1' })).toBeInTheDocument();
});

test('selecting an open line opens it in the stage', async () => {
	const openLine = optionLine({ index: 1, topic: 'Gäste', question: 'Guests allowed?' });
	const repos = [repo({ items: [item({ number: 42, title: 'Share page', lines: [openLine] })] })];
	vi.stubGlobal('fetch', fakeFetch(200, { repos }));

	render(App, { token: 'a-token' });
	(await screen.findByRole('button', { name: /Gäste/ })).click();

	expect(await screen.findByRole('heading', { name: 'Guests allowed?' })).toBeInTheDocument();
});

test('an empty successful repository does not hide another repository error', async () => {
	vi.stubGlobal(
		'fetch',
		fakeFetch(200, {
			repos: [repo({ items: [] }), repo({ name: 'broken', error: 'Read failed', items: [] })]
		})
	);
	render(App, { token: 'a-token' });
	expect(await screen.findByRole('alert')).toHaveTextContent('broken: Read failed');
});
