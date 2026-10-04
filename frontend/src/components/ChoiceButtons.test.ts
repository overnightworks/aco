import { render, screen } from '@testing-library/svelte';
import { expect, test, vi } from 'vitest';
import ChoiceButtons from './ChoiceButtons.svelte';

test('offers Ja, Nein and Später, in that order', () => {
	render(ChoiceButtons, { default: null, disabled: false, onChoose: vi.fn() });

	const buttons = screen.getAllByRole('button');
	expect(buttons.map((button) => button.textContent?.trim())).toEqual(['Ja', 'Nein', 'Später']);
});

test('the default outcome carries the "Empfohlen" tag, the others do not', () => {
	render(ChoiceButtons, { default: 'later', disabled: false, onChoose: vi.fn() });

	expect(screen.getByRole('button', { name: /Empfohlen/ })).toHaveTextContent('Später');
});

test('choosing an outcome reports exactly that outcome', () => {
	const onChoose = vi.fn();
	render(ChoiceButtons, { default: null, disabled: false, onChoose });

	screen.getByRole('button', { name: 'Nein' }).click();

	expect(onChoose).toHaveBeenCalledTimes(1);
	expect(onChoose).toHaveBeenCalledWith('no');
});

test('disabled buttons refuse a click', () => {
	const onChoose = vi.fn();
	render(ChoiceButtons, { default: null, disabled: true, onChoose });

	screen.getByRole('button', { name: 'Ja' }).click();

	expect(onChoose).not.toHaveBeenCalled();
});
