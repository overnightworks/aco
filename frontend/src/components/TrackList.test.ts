import { render, screen } from '@testing-library/svelte';
import { expect, test } from 'vitest';
import { item, line, repo } from '../test-support/board';
import TrackList from './TrackList.svelte';

test('an item title stands once as a group header, its lines below it', () => {
	render(TrackList, {
		repos: [
			repo({
				items: [item({ number: 42, title: 'Share page', lines: [line({ text: 'Guests?' })] })]
			})
		]
	});

	expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('#42 Share page');
	expect(screen.getByText('Guests?')).toBeInTheDocument();
});

test('a newly open line shows its recommendation under its item', () => {
	render(TrackList, {
		repos: [
			repo({
				items: [item({ lines: [line({ ruling: null, default: 'yes' })] })]
			})
		]
	});

	expect(screen.getByText('Empfohlen: Ja')).toBeInTheDocument();
});

test('a ruled line shows its outcome and date instead of a recommendation', () => {
	render(TrackList, {
		repos: [
			repo({
				items: [item({ lines: [line({ ruling: 'no', ruled_on: '2026-10-01', default: null })] })]
			})
		]
	});

	expect(screen.getByText('Nein · 2026-10-01')).toBeInTheDocument();
});

test('a failed repo shows its error sentence instead of its items', () => {
	render(TrackList, {
		repos: [repo({ name: 'b', error: 'aco rulings failed: ERROR: no forge adapter', items: [] })]
	});

	expect(screen.getByRole('alert')).toHaveTextContent('b: aco rulings failed');
	expect(screen.queryByRole('heading', { level: 2 })).not.toBeInTheDocument();
});

test('each repo keeps its own items grouped separately, even with matching item numbers', () => {
	render(TrackList, {
		repos: [
			repo({ name: 'a', items: [item({ number: 42, title: 'In a' })] }),
			repo({ name: 'b', items: [item({ number: 42, title: 'In b' })] })
		]
	});

	const headings = screen.getAllByRole('heading', { level: 2 });
	expect(headings.map((heading) => heading.textContent)).toEqual(['#42 In a', '#42 In b']);
});
