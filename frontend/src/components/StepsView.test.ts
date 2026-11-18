import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { afterEach, expect, test, vi } from 'vitest';
import { repo, stepRead } from '../test-support/board';
import StepsView from './StepsView.svelte';

afterEach(() => vi.unstubAllGlobals());

function stubClipboard(writeText: (text: string) => Promise<void>) {
	vi.stubGlobal('navigator', { clipboard: { writeText } });
}

test('[ABRD-159] a step shows its title, purpose, actions in a block, expected result and the yes or no answer', () => {
	render(StepsView, { repos: [repo({ steps: [stepRead()] })] });

	const card = screen.getByRole('article', { name: /Release/ });
	expect(within(card).getByText('Release the build.')).toBeInTheDocument();
	expect(card.querySelector('pre')?.textContent).toBe('open https://example.test/run\nclick Run');
	expect(within(card).getByText('The page shows green.')).toBeInTheDocument();
	expect(within(card).getByText('Antwort: Ja / Nein')).toBeInTheDocument();
});

test('[ABRD-159] a step that names an answer shows that report', () => {
	render(StepsView, { repos: [repo({ steps: [stepRead({ answer: 'the green run id' })] })] });

	expect(screen.getByText('Antwort: the green run id')).toBeInTheDocument();
	expect(screen.queryByText('Antwort: Ja / Nein')).toBeNull();
});

test('[ABRD-160] Copy puts exactly the block text on the clipboard and says so', async () => {
	const writeText = vi.fn(() => Promise.resolve());
	stubClipboard(writeText);
	render(StepsView, { repos: [repo({ steps: [stepRead()] })] });

	await fireEvent.click(screen.getByRole('button', { name: 'Copy' }));

	expect(writeText).toHaveBeenCalledWith('open https://example.test/run\nclick Run');
	expect(await screen.findByRole('button', { name: 'Copied' })).toBeInTheDocument();
});

test('[ABRD-160] a refused copy says so and offers the copy again', async () => {
	stubClipboard(() => Promise.reject(new Error('denied')));
	render(StepsView, { repos: [repo({ steps: [stepRead()] })] });

	await fireEvent.click(screen.getByRole('button', { name: 'Copy' }));

	expect(await screen.findByRole('button', { name: 'Copy failed, try again' })).toBeInTheDocument();
});

test('[ABRD-161] a step without the fields shows its one line only and no button', () => {
	render(StepsView, {
		repos: [
			repo({
				steps: [
					stepRead({
						purpose: null,
						actions: null,
						expected: null,
						answer: null,
						step: 'Run the release dispatch.'
					})
				]
			})
		]
	});

	expect(screen.getByText('Run the release dispatch.')).toBeInTheDocument();
	expect(screen.queryByRole('button')).toBeNull();
	expect(screen.queryByText(/Antwort/)).toBeNull();
});

test('[ABRD-162] no step anywhere says nothing waits', () => {
	render(StepsView, { repos: [repo({ steps: [] })] });

	expect(screen.getByText('No step is waiting for you.')).toBeInTheDocument();
});

test('[ABRD-162] a repo that could not be read says so instead of an empty list', () => {
	render(StepsView, { repos: [repo({ name: 'songmaker', error: 'GitHub is down', steps: [] })] });

	expect(screen.getByRole('alert')).toHaveTextContent('Not read');
	expect(screen.getByRole('alert')).toHaveTextContent('GitHub is down');
	expect(screen.queryByText('No step is waiting for you.')).toBeNull();
});
