import { render, screen } from '@testing-library/svelte';
import { expect, test, vi } from 'vitest';
import { item, line, repo } from '../test-support/board';
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

test('an item title stands once as a group header, its lines below it', () => {
	renderList([
		repo({
			items: [item({ number: 42, title: 'Share page', lines: [line({ text: 'Guests?' })] })]
		})
	]);

	expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('Share page repo · #42');
	expect(screen.getByText('Guests?')).toBeInTheDocument();
});

test('a newly open line shows its recommendation under its item', () => {
	renderList([repo({ items: [item({ lines: [line({ ruling: null, default: 'yes' })] })] })]);

	expect(screen.getByText('Empfohlen: Ja')).toBeInTheDocument();
});

test('a short question labels the control instead of repeating its full sentence', () => {
	renderList([
		repo({
			items: [
				item({ lines: [line({ question: 'Guests allowed?', text: 'Guests may join the call.' })] })
			]
		})
	]);
	expect(screen.getByRole('button', { name: /Guests allowed/ })).toBeInTheDocument();
	expect(screen.queryByText('Guests may join the call.')).not.toBeInTheDocument();
});

test('ruled lines and their otherwise empty groups leave the decision list', () => {
	renderList([
		repo({
			items: [item({ lines: [line({ ruling: 'no', ruled_on: '2026-10-01', default: null })] })]
		})
	]);

	expect(screen.queryByText('Nein · 2026-10-01')).not.toBeInTheDocument();
	expect(screen.queryByRole('heading')).not.toBeInTheDocument();
});

test('hostile item title, line text, repo label and error text is shown as text, never as markup', () => {
	const hostileTitle = '<script>alert(1)</script>';
	const hostileText = '"><img src=x onerror=alert(2)>';
	const hostileName = '<svg onload=alert(3)>';
	const hostileError = '<img src=x onerror=alert(4)>';
	const { container } = renderList([
		repo({ name: hostileName, error: hostileError, items: [] }),
		repo({
			name: 'clean',
			items: [item({ number: 42, title: hostileTitle, lines: [line({ text: hostileText })] })]
		})
	]);

	expect(screen.getByRole('alert')).toHaveTextContent(`${hostileName}: ${hostileError}`);
	expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent(hostileTitle);
	expect(screen.getByText(hostileText)).toBeInTheDocument();
	expect(container.querySelectorAll('script, img, svg')).toHaveLength(0);
	expect(container.querySelector('[onerror], [onload]')).toBeNull();
});

test('a failed repo shows its error sentence instead of its items', () => {
	renderList([
		repo({ name: 'b', error: 'aco rulings failed: ERROR: no forge adapter', items: [] })
	]);

	expect(screen.getByRole('alert')).toHaveTextContent('b: aco rulings failed');
	expect(screen.queryByRole('heading', { level: 2 })).not.toBeInTheDocument();
});

test('each repo keeps its own items grouped separately, even with matching item numbers', () => {
	renderList([
		repo({ name: 'a', items: [item({ number: 42, title: 'In a' })] }),
		repo({ name: 'b', items: [item({ number: 42, title: 'In b' })] })
	]);

	const headings = screen.getAllByRole('heading', { level: 2 });
	expect(headings.map((heading) => heading.textContent)).toEqual(['In a a · #42', 'In b b · #42']);
});

test('an open line is a button that selects it by its repo-bound key', () => {
	const { onSelect } = renderList([
		repo({ name: 'a', items: [item({ number: 42, lines: [line({ index: 3, ruling: null })] })] })
	]);

	screen.getByRole('button').click();

	expect(onSelect).toHaveBeenCalledWith('a:42:3');
});

test('a ruled line carries no button: its history is read-only', () => {
	renderList([
		repo({ items: [item({ lines: [line({ ruling: 'yes', ruled_on: '2026-10-01' })] })] })
	]);

	expect(screen.queryByRole('button')).not.toBeInTheDocument();
});

test('the selected line is marked current among several open ones', () => {
	renderList(
		[
			repo({
				items: [
					item({
						number: 42,
						lines: [line({ index: 1, ruling: null }), line({ index: 2, ruling: null })]
					})
				]
			})
		],
		{ selectedKey: 'repo:42:2' }
	);

	const [first, second] = screen.getAllByRole('button');
	expect(first).toHaveAttribute('aria-current', 'false');
	expect(second).toHaveAttribute('aria-current', 'true');
});
