import { render, screen, within } from '@testing-library/svelte';
import { expect, test, vi } from 'vitest';
import { item, line, optionLine, repo } from '../test-support/board';
import TrackList from './TrackList.svelte';

function renderList(
	repos: ReturnType<typeof repo>[],
	overrides: { selectedKey?: string | null } = {}
) {
	const onSelect = vi.fn();
	const rendered = render(TrackList, {
		repos,
		selectedKey: overrides.selectedKey ?? null,
		onSelect
	});
	return { onSelect, container: rendered.container };
}

test('[ABRD-28] a repository is a heading with its name and open count', () => {
	renderList([
		repo({
			items: [item({ lines: [line({ index: 1 }), line({ index: 2, text: 'Second?' })] })]
		})
	]);

	expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('repo 2');
});

test('[ABRD-48] an option row shows its topic, the Open shape and its question as title', () => {
	renderList([
		repo({
			items: [item({ lines: [optionLine({ topic: 'Sprung', question: 'Keep the song open?' })] })]
		})
	]);

	const row = screen.getByRole('button', { name: 'Open Sprung' });
	expect(row).toHaveAttribute('title', 'Keep the song open?');
	expect(within(row).getByRole('img', { name: 'Open' })).toBeInTheDocument();
});

test('[ABRD-48] a yes/no row shows its question, the Not ready shape and a muted label', () => {
	renderList([repo({ items: [item({ lines: [line({ text: 'Guests?' })] })] })]);

	const row = screen.getByRole('button', { name: 'Not ready · head to fill Guests?' });
	expect(within(row).getByRole('img', { name: 'Not ready · head to fill' })).toBeInTheDocument();
	expect(within(row).getByText('Guests?')).toHaveClass('muted');
});

test('[ABRD-28] a short question labels the row instead of the full sentence', () => {
	renderList([
		repo({
			items: [
				item({ lines: [line({ question: 'Guests allowed?', text: 'Guests may join the call.' })] })
			]
		})
	]);

	expect(screen.getByText('Guests allowed?')).toBeInTheDocument();
	expect(screen.queryByText('Guests may join the call.')).not.toBeInTheDocument();
});

test('[ABRD-29] the option row comes before the yes/no row of its repository', () => {
	renderList([
		repo({
			items: [
				item({
					lines: [line({ index: 1, text: 'Guests?' }), optionLine({ index: 2, topic: 'Sprung' })]
				})
			]
		})
	]);

	const [first, second] = screen.getAllByRole('button');
	expect(first).toHaveAccessibleName('Open Sprung');
	expect(second).toHaveAccessibleName('Not ready · head to fill Guests?');
});

test('[ABRD-49] ruled lines and ruled-only repositories leave the groups and stand in the quiet line', () => {
	renderList([
		repo({ name: 'busy', items: [item({ lines: [line()] })] }),
		repo({
			name: 'done',
			items: [item({ lines: [line({ ruling: 'no', ruled_on: '2026-10-01' })] })]
		}),
		repo({ name: 'idle', items: [] })
	]);

	expect(screen.getAllByRole('heading', { level: 2 })).toHaveLength(1);
	expect(screen.getByText('Nothing open: done · idle')).toBeInTheDocument();
	expect(screen.queryByText('Nein · 2026-10-01')).not.toBeInTheDocument();
});

test('[ABRD-49] a failed repository shows its alert, and with no open line no All decided', () => {
	renderList([
		repo({ name: 'b', error: 'aco rulings failed: ERROR: no forge adapter', items: [] }),
		repo({ name: 'idle', items: [] })
	]);

	expect(screen.getByRole('alert')).toHaveTextContent('b: aco rulings failed');
	expect(screen.getByText('Nothing open: idle')).toBeInTheDocument();
	expect(screen.queryByText('All decided')).not.toBeInTheDocument();
});

test('[ABRD-49] with no open line and no failure the list reads All decided', () => {
	renderList([
		repo({ items: [item({ lines: [line({ ruling: 'yes', ruled_on: '2026-10-01' })] })] })
	]);

	expect(screen.getByText('All decided')).toBeInTheDocument();
	expect(screen.getByText('No project is waiting for you.')).toBeInTheDocument();
	expect(screen.queryByText(/Nothing open/)).not.toBeInTheDocument();
});

test('[ABRD-15] hostile titles, topics, repository names and errors are shown as text, never as markup', () => {
	const hostileTopic = '<script>alert(1)</script>';
	const hostileQuestion = '"><img src=x onerror=alert(2)>';
	const hostileName = '<svg onload=alert(3)>';
	const hostileError = '<img src=x onerror=alert(4)>';
	const { container } = renderList([
		repo({ name: hostileName, error: hostileError, items: [] }),
		repo({
			name: 'clean',
			items: [
				item({
					lines: [
						optionLine({ index: 1, topic: hostileTopic, question: hostileQuestion }),
						line({ index: 2, text: hostileQuestion })
					]
				})
			]
		})
	]);

	expect(screen.getByRole('alert')).toHaveTextContent(`${hostileName}: ${hostileError}`);
	expect(screen.getByText(hostileTopic)).toBeInTheDocument();
	expect(screen.getAllByTitle(hostileQuestion)).toHaveLength(2);
	expect(container.querySelectorAll('script, img')).toHaveLength(0);
	expect(container.querySelectorAll('svg')).toHaveLength(2);
	expect(container.querySelector('[onerror], [onload]')).toBeNull();
});

test('[ABRD-28] a row is a button that selects its line by the repository-bound key', () => {
	const { onSelect } = renderList([
		repo({ name: 'a', items: [item({ number: 42, lines: [line({ index: 3 })] })] })
	]);

	screen.getByRole('button').click();

	expect(onSelect).toHaveBeenCalledWith('a:42:3');
});

test('[ABRD-28] the selected row is marked current among several open ones', () => {
	renderList(
		[
			repo({
				items: [item({ number: 42, lines: [line({ index: 1 }), line({ index: 2 })] })]
			})
		],
		{ selectedKey: 'repo:42:2' }
	);

	const [first, second] = screen.getAllByRole('button');
	expect(first).toHaveAttribute('aria-current', 'false');
	expect(second).toHaveAttribute('aria-current', 'true');
});
