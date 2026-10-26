import { render, screen, within } from '@testing-library/svelte';
import { expect, test } from 'vitest';
import { cardOption, optionLine, PICTURE } from '../test-support/board';
import OptionCard from './OptionCard.svelte';

function openCard() {
	return optionLine({
		question: 'Keep the song open?',
		problem: 'The jump closes your song.',
		caption: 'Today the song is lost.',
		recommended: 'A',
		reason: 'Ends the loss.',
		options: [
			cardOption({ name: 'Song stays open', effect: 'The app jumps itself.' }),
			cardOption({ letter: 'B', name: 'As today', effect: 'The browser jumps.' })
		]
	});
}

test('an open card shows the meta line, question and rows in the order of the picture', () => {
	render(OptionCard, { repo: 'songmaker', line: openCard() });

	expect(screen.getByText('songmaker › Song page')).toBeInTheDocument();
	expect(screen.getByText('Product')).toBeInTheDocument();
	expect(screen.getByText('reversible')).toBeInTheDocument();
	expect(screen.getByRole('heading', { name: 'Keep the song open?' })).toBeInTheDocument();
	const labels = screen.getAllByRole('term').map((term) => term.textContent);
	expect(labels).toEqual(['Problem', 'Today', 'Options', 'Recommendation']);
	expect(screen.getByText('The jump closes your song.')).toBeInTheDocument();
});

test('Today is an image with a data URI source, its caption as alt text and below it', () => {
	render(OptionCard, { repo: 'songmaker', line: openCard() });

	const picture = screen.getByRole('img', { name: 'Today the song is lost.' });
	expect(picture.tagName).toBe('IMG');
	const source = picture.getAttribute('src') ?? '';
	expect(source.startsWith('data:image/svg+xml;base64,')).toBe(true);
	expect(Buffer.from(source.slice(source.indexOf(',') + 1), 'base64').toString('utf-8')).toBe(
		PICTURE
	);
	expect(screen.getByText('Today the song is lost.', { selector: 'p' })).toBeInTheDocument();
});

test('options appear in letter order with name and effect, the recommendation beside its reason', () => {
	render(OptionCard, { repo: 'songmaker', line: openCard() });

	const options = within(screen.getByRole('list', { name: 'Options' })).getAllByRole('listitem');
	expect(options.map((option) => option.textContent?.replace(/\s+/g, ' ').trim())).toEqual([
		'A Song stays open The app jumps itself.',
		'B As today The browser jumps.'
	]);
	const recommendation = screen.getByText('Ends the loss.').parentElement as HTMLElement;
	expect(recommendation).toHaveTextContent('A Ends the loss.');
});

test('an open card offers no outcome', () => {
	const { container } = render(OptionCard, { repo: 'songmaker', line: openCard() });

	expect(screen.queryAllByRole('button')).toHaveLength(0);
	expect(container.querySelectorAll('textarea, input, summary, a')).toHaveLength(0);
	expect(screen.queryByText('Decided')).not.toBeInTheDocument();
});

test('a final option marks the meta line final', () => {
	const line = optionLine({
		options: [cardOption(), cardOption({ letter: 'B', name: 'Delete it', undo: 'final' })]
	});

	render(OptionCard, { repo: 'songmaker', line });

	expect(screen.getByText('final')).toBeInTheDocument();
	expect(screen.queryByText('reversible')).not.toBeInTheDocument();
});

test('a ruled card fills the chosen letter and adds the Decided row with name and date', () => {
	const line = { ...openCard(), ruling: 'B' as const, ruled_on: '2026-10-26' };

	render(OptionCard, { repo: 'songmaker', line });

	const options = within(screen.getByRole('list', { name: 'Options' })).getAllByRole('listitem');
	expect(options.map((option) => option.getAttribute('aria-current'))).toEqual([null, 'true']);
	const decided = screen.getByText('Decided').closest('div') as HTMLElement;
	expect(decided).toHaveTextContent('B — As today');
	expect(decided).toHaveTextContent('2026-10-26');
	expect(screen.queryAllByRole('button')).toHaveLength(0);
});

test('hostile texts render as text and the picture stays out of the DOM tree', () => {
	const hostile = '<img src=x onerror=alert(1)>';
	const line = optionLine({
		question: hostile,
		problem: hostile,
		reason: hostile,
		picture: '<svg onload="alert(1)"><script>alert(2)</script></svg>'
	});

	const { container } = render(OptionCard, { repo: 'songmaker', line });

	expect(container.querySelectorAll('script, svg')).toHaveLength(0);
	expect(container.querySelectorAll('img')).toHaveLength(1);
	expect(container.querySelector('[onerror], [onload]')).toBeNull();
});
