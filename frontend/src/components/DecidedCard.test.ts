import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { expect, test } from 'vitest';
import { cardOption, item, line, optionLine } from '../test-support/board';
import DecidedCard from './DecidedCard.svelte';

function ruledOption() {
	return optionLine({
		index: 1,
		question: 'Keep the song open?',
		text: 'Rule 10.',
		area: 'Song page',
		ruling: 'B',
		ruled_on: '2026-10-26',
		via: 'board',
		options: [
			cardOption({ name: 'Song stays open' }),
			cardOption({ letter: 'B', name: 'As today', contract: 'The browser keeps jumping.' })
		]
	});
}

function renderOption() {
	return render(DecidedCard, {
		repo: 'songmaker',
		item: item({ number: 1843, title: 'Song' }),
		line: ruledOption()
	});
}

test('[ABRD-37] an option line shows its meta, title and exactly Decided, How and Contract', () => {
	const { container } = renderOption();

	expect(container.querySelector('.decided-card')).not.toBeNull();
	expect(screen.getByText('songmaker › Song page')).toBeInTheDocument();
	expect(screen.getByText('Product')).toBeInTheDocument();
	expect(screen.queryByText('reversible')).not.toBeInTheDocument();
	expect(screen.queryByText('final')).not.toBeInTheDocument();
	expect(screen.getByRole('heading', { name: 'Keep the song open?' })).toBeInTheDocument();
	expect(screen.getAllByRole('term').map((term) => term.textContent)).toEqual([
		'Decided',
		'How',
		'Contract'
	]);
});

test('[ABRD-37] Decided holds the done shape and the answer, How the way and the date', () => {
	renderOption();

	const decided = screen.getByText('Decided', { selector: 'dt' }).closest('div') as HTMLElement;
	expect(within(decided).getByRole('img', { name: 'Decided' })).toBeInTheDocument();
	expect(decided).toHaveTextContent('B — As today');
	const how = screen.getByText('How', { selector: 'dt' }).closest('div') as HTMLElement;
	expect(how).toHaveTextContent('Board · 26.10.2026');
});

test('[ABRD-37] the contract is closed behind Show with its sentences and source', async () => {
	const { container } = renderOption();

	const fold = container.querySelector('details.contract') as HTMLDetailsElement;
	expect(fold.open).toBe(false);
	expect(within(fold).getByText('Show')).toBeInTheDocument();
	await fireEvent.click(within(fold).getByText('Show'));
	expect(fold.open).toBe(true);
	expect(fold).toHaveTextContent('The browser keeps jumping.');
	expect(fold).toHaveTextContent('Rule 10.');
	expect(fold).toHaveTextContent('songmaker · Item 1843 · Line 1');
	expect(screen.queryByRole('button')).not.toBeInTheDocument();
});

test('[ABRD-37] [ABRD-54] a yes/no line names its item, answers and reads not recorded', () => {
	render(DecidedCard, {
		repo: 'songmaker',
		item: item({ number: 42, title: 'Share page' }),
		line: line({ index: 2, text: 'Guests may join.', ruling: 'later', ruled_on: '2026-10-01' })
	});

	expect(screen.getByText('songmaker › Share page')).toBeInTheDocument();
	expect(screen.getByRole('heading', { name: 'Guests may join.' })).toBeInTheDocument();
	expect(screen.getByText('Später')).toBeInTheDocument();
	expect(screen.getByText('not recorded · 01.10.2026')).toBeInTheDocument();
	expect(screen.getAllByText('Guests may join.')).toHaveLength(2);
	expect(screen.getByText('songmaker · Item 42 · Line 2')).toBeInTheDocument();
});

test('[ABRD-37] hostile text renders as text', () => {
	const hostile = '<img src=x onerror=alert(1)>';
	const { container } = render(DecidedCard, {
		repo: 'songmaker',
		item: item(),
		line: { ...ruledOption(), question: hostile, text: hostile }
	});

	expect(screen.getByRole('heading', { name: hostile })).toBeInTheDocument();
	expect(container.querySelector('img[onerror]')).toBeNull();
});
