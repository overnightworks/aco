import { render, screen, within } from '@testing-library/svelte';
import { expect, test } from 'vitest';
import { cardOption, optionLine, PICTURE, sameAsTodayOption } from '../test-support/board';
import type { CardOption } from '../types';
import OptionDetails from './OptionDetails.svelte';

function renderDetails(option: CardOption, text = 'The song stays open on the jump.') {
	return render(OptionDetails, {
		repo: 'songmaker',
		item: 1843,
		line: optionLine({ index: 1, text }),
		option
	});
}

function value(label: string): HTMLElement {
	return screen.getByText(label, { selector: 'dt' }).nextElementSibling as HTMLElement;
}

test('the rows come in the order Result, You notice, Cost, Undo, Contract', () => {
	renderDetails(cardOption());

	const labels = screen.getAllByRole('term').map((term) => term.textContent);
	expect(labels).toEqual(['Result', 'You notice', 'Cost', 'Undo', 'Contract']);
});

test('a picture option shows an image from a data URI with the fallback alt and no caption', () => {
	const { container } = renderDetails(cardOption());

	const picture = within(value('Result')).getByRole('img', {
		name: 'A · Keep the song open: The app jumps itself.'
	});
	const source = picture.getAttribute('src') ?? '';
	expect(source.startsWith('data:image/svg+xml;base64,')).toBe(true);
	expect(Buffer.from(source.slice(source.indexOf(',') + 1), 'base64').toString('utf-8')).toBe(
		PICTURE
	);
	expect(container.querySelector('p.caption')).toBeNull();
});

test('a captioned option shows the caption below its picture', () => {
	renderDetails(cardOption({ caption: 'The song stays open.' }));

	const button = within(value('Result')).getByRole('button', { name: 'Enlarge picture' });
	expect(button.nextElementSibling).toHaveTextContent('The song stays open.');
});

test('an option that is the same as today shows the mark and no image', () => {
	renderDetails(sameAsTodayOption());

	expect(value('Result')).toHaveTextContent('= TODAY');
	expect(screen.queryByRole('img')).not.toBeInTheDocument();
});

test('notice and cost show their texts', () => {
	renderDetails(cardOption({ notice: 'You stay in your song.', cost: 'More code.' }));

	expect(value('You notice')).toHaveTextContent('You stay in your song.');
	expect(value('Cost')).toHaveTextContent('More code.');
});

test('a reversible option reads the word and how to undo it', () => {
	const { container } = renderDetails(cardOption({ undo: 'reversible', undo_how: 'Any time.' }));

	expect(value('Undo')).toHaveTextContent('reversible — Any time.');
	expect(container.querySelector('dd svg')).toBeNull();
});

test('a final option puts the warn mark before the word', () => {
	renderDetails(cardOption({ undo: 'final', undo_how: 'nie' }));

	const undo = value('Undo');
	expect(undo).toHaveTextContent('final — nie');
	const mark = undo.querySelector('svg') as SVGElement;
	expect(mark.getAttribute('aria-hidden')).toBe('true');
	expect(mark.parentElement?.tagName).toBe('B');
	expect(mark.parentElement?.firstElementChild).toBe(mark);
	expect(mark.parentElement).toHaveTextContent('final');
});

test('the contract is folded behind Show and names both sentences and their source', () => {
	renderDetails(cardOption({ contract: 'Rule 10 changes.' }));

	const fold = value('Contract').querySelector('details') as HTMLDetailsElement;
	expect(fold.open).toBe(false);
	expect(fold.querySelector('summary')).toHaveTextContent('Show');
	expect(fold).toHaveTextContent('Rule 10 changes.');
	expect(fold).toHaveTextContent('The song stays open on the jump.');
	expect(fold).toHaveTextContent('songmaker · Item 1843 · Line 1');
});

test('a line text equal to the contract appears once', () => {
	renderDetails(cardOption({ contract: 'Same sentence.' }), 'Same sentence.');

	expect(screen.getAllByText('Same sentence.')).toHaveLength(1);
});

test('hostile texts and a hostile picture render as text and one image', () => {
	const hostile = '<img src=x onerror=alert(1)>';
	const { container } = renderDetails(
		cardOption({
			notice: hostile,
			cost: hostile,
			contract: hostile,
			undo_how: hostile,
			caption: hostile,
			picture: '<svg onload="alert(1)"><script>alert(2)</script></svg>'
		})
	);

	expect(container.querySelectorAll('script, svg')).toHaveLength(0);
	expect(container.querySelectorAll('img')).toHaveLength(1);
	expect(container.querySelector('[onerror], [onload]')).toBeNull();
	expect(value('You notice')).toHaveTextContent(hostile);
});
