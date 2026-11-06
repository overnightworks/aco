import { fireEvent, render, screen } from '@testing-library/svelte';
import { expect, test } from 'vitest';
import { PICTURE, picturelessOptionLine, resultlessOption } from '../test-support/board';
import OptionRows from './OptionRows.svelte';

function picturelessCard() {
	return picturelessOptionLine({
		options: [
			resultlessOption({ name: 'Song stays open', effect: 'The app jumps itself.' }),
			resultlessOption({ letter: 'B', name: 'As today', effect: 'The browser jumps.' })
		]
	});
}

test('a card without a Today picture shows no Today row and no picture', () => {
	render(OptionRows, { repo: 'songmaker', item: 1843, line: picturelessCard() });

	const labels = screen.getAllByRole('term').map((term) => term.textContent);
	expect(labels).toContain('Problem');
	expect(labels).not.toContain('Today');
	expect(screen.queryByRole('img')).not.toBeInTheDocument();
	expect(screen.queryByRole('button', { name: 'Enlarge picture' })).not.toBeInTheDocument();
});

test('an option with neither a result picture nor the same-as-today mark shows its effect alone', async () => {
	render(OptionRows, { repo: 'songmaker', item: 1843, line: picturelessCard() });

	const option = screen.getByRole('button', { name: /Song stays open/ });
	expect(option).toHaveTextContent('The app jumps itself.');
	await fireEvent.click(option);

	expect(option.getAttribute('aria-expanded')).toBe('true');
	expect(screen.queryByText('Result', { selector: 'dt' })).not.toBeInTheDocument();
	expect(screen.getByText('You notice', { selector: 'dt' })).toBeInTheDocument();
});

test('a Today picture without a caption still shows, labelled Today', () => {
	const line = { ...picturelessCard(), picture: PICTURE };

	render(OptionRows, { repo: 'songmaker', item: 1843, line });

	expect(screen.getByRole('img', { name: 'Today' })).toBeInTheDocument();
});
