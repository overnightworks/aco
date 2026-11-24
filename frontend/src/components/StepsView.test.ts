import { fireEvent, render, screen, within } from '@testing-library/svelte';
import type { postStep } from '../client';
import { UNDO_SECONDS } from '../app/model/decision';
import { afterEach, expect, test, vi } from 'vitest';
import { inertBoard, repo, stepRead } from '../test-support/board';
import { DecisionStore } from '../app/state/decision.svelte';
import StepsView from './StepsView.svelte';

afterEach(() => {
	vi.unstubAllGlobals();
	vi.useRealTimers();
});

function store(
	send: typeof postStep = vi.fn(async () => ({ status: 'answered' as const, message: null }))
) {
	return new DecisionStore('token', inertBoard(), vi.fn(), UNDO_SECONDS, send);
}

function stubClipboard(writeText: (text: string) => Promise<void>) {
	vi.stubGlobal('navigator', { clipboard: { writeText } });
}

test('ABRD-159: a step shows its title, purpose, actions in a block, expected result and the yes or no answer', () => {
	render(StepsView, { repos: [repo({ steps: [stepRead()] })], decisions: store() });

	const card = screen.getByRole('article', { name: /Release/ });
	expect(within(card).getByText('Release the build.')).toBeInTheDocument();
	expect(card.querySelector('pre')?.textContent).toBe('open https://example.test/run\nclick Run');
	expect(within(card).getByText('The page shows green.')).toBeInTheDocument();
	expect(within(card).getByText('Antwort: Ja / Nein')).toBeInTheDocument();
});

test('ABRD-159: a step that names an answer shows that report', () => {
	render(StepsView, {
		repos: [repo({ steps: [stepRead({ answer: 'the green run id' })] })],
		decisions: store()
	});

	expect(screen.getByText('Antwort: the green run id')).toBeInTheDocument();
	expect(screen.queryByText('Antwort: Ja / Nein')).toBeNull();
});

test('ABRD-160: Copy puts exactly the block text on the clipboard and says so', async () => {
	const writeText = vi.fn(() => Promise.resolve());
	stubClipboard(writeText);
	render(StepsView, { repos: [repo({ steps: [stepRead()] })], decisions: store() });

	await fireEvent.click(screen.getByRole('button', { name: 'Copy' }));

	expect(writeText).toHaveBeenCalledWith('open https://example.test/run\nclick Run');
	expect(await screen.findByRole('button', { name: 'Copied' })).toBeInTheDocument();
});

test('ABRD-160: a refused copy says so and offers the copy again', async () => {
	stubClipboard(() => Promise.reject(new Error('denied')));
	render(StepsView, { repos: [repo({ steps: [stepRead()] })], decisions: store() });

	await fireEvent.click(screen.getByRole('button', { name: 'Copy' }));

	expect(await screen.findByRole('button', { name: 'Copy failed, try again' })).toBeInTheDocument();
});

test('ABRD-161: a step without the fields shows its one line only and no button', () => {
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
		],
		decisions: store()
	});

	expect(screen.getByText('Run the release dispatch.')).toBeInTheDocument();
	expect(screen.queryByRole('button')).toBeNull();
	expect(screen.queryByText(/Antwort/)).toBeNull();
});

test('ABRD-162: no step anywhere says nothing waits', () => {
	render(StepsView, { repos: [repo({ steps: [] })], decisions: store() });

	expect(screen.getByText('No step is waiting for you.')).toBeInTheDocument();
});

test('ABRD-162: a repo that could not be read says so instead of an empty list', () => {
	render(StepsView, {
		repos: [repo({ name: 'songmaker', error: 'GitHub is down', steps: [] })],
		decisions: store()
	});

	expect(screen.getByRole('alert')).toHaveTextContent('Not read');
	expect(screen.getByRole('alert')).toHaveTextContent('GitHub is down');
	expect(screen.queryByText('No step is waiting for you.')).toBeNull();
});

test('ABRD-173: a yes or no step offers Erfolgreich and Fehlgeschlagen, and Erfolgreich posts yes after its window', async () => {
	vi.useFakeTimers();
	const send = vi.fn(async () => ({ status: 'answered' as const, message: null }));
	render(StepsView, {
		repos: [repo({ steps: [stepRead({ fingerprint: 'fp' })] })],
		decisions: store(send)
	});
	expect(screen.getByRole('button', { name: 'Fehlgeschlagen' })).toBeInTheDocument();

	await fireEvent.click(screen.getByRole('button', { name: 'Erfolgreich' }));
	expect(screen.getByText(/Saves shortly: Erfolgreich · #7/)).toBeInTheDocument();
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

	expect(send).toHaveBeenCalledWith('token', {
		repo: 'repo',
		item: 7,
		fingerprint: 'fp',
		result: 'yes'
	});
});

test('ABRD-174: Fehlgeschlagen cannot send without a note', async () => {
	render(StepsView, { repos: [repo({ steps: [stepRead()] })], decisions: store() });

	await fireEvent.click(screen.getByRole('button', { name: 'Fehlgeschlagen' }));
	const send = screen.getByRole('button', { name: 'Senden' });
	expect(send).toBeDisabled();
	await fireEvent.input(screen.getByLabelText('Notiz'), { target: { value: 'Stayed red.' } });

	expect(send).toBeEnabled();
});

test('ABRD-173: a step that asks for a report offers a report field with Senden and no Erfolgreich', async () => {
	render(StepsView, {
		repos: [repo({ steps: [stepRead({ answer: 'the green run id' })] })],
		decisions: store()
	});

	expect(screen.queryByRole('button', { name: 'Erfolgreich' })).toBeNull();
	const send = screen.getByRole('button', { name: 'Senden' });
	expect(send).toBeDisabled();
	await fireEvent.input(screen.getByLabelText('Bericht'), { target: { value: 'run 4' } });

	expect(send).toBeEnabled();
});

test('ABRD-175: Undo inside the window removes the strip and brings the buttons back', async () => {
	render(StepsView, { repos: [repo({ steps: [stepRead()] })], decisions: store() });

	await fireEvent.click(screen.getByRole('button', { name: 'Erfolgreich' }));
	await fireEvent.click(screen.getByRole('button', { name: 'Undo' }));

	expect(screen.getByRole('button', { name: 'Erfolgreich' })).toBeInTheDocument();
});

test('ABRD-177: a step whose card changed offers Copy again instead of Copied', async () => {
	stubClipboard(() => Promise.resolve());
	const decisions = store();
	const { rerender } = render(StepsView, {
		repos: [repo({ steps: [stepRead({ fingerprint: 'one' })] })],
		decisions
	});
	await fireEvent.click(screen.getByRole('button', { name: 'Copy' }));
	expect(await screen.findByRole('button', { name: 'Copied' })).toBeInTheDocument();

	await rerender({
		repos: [repo({ steps: [stepRead({ fingerprint: 'two', actions: 'click Stop' })] })],
		decisions
	});

	expect(screen.getByRole('button', { name: 'Copy' })).toBeInTheDocument();
});

test('ABRD-176: a refused answer keeps every answer button disabled until Neu laden', async () => {
	vi.useFakeTimers();
	const send = vi.fn(async () => ({ status: 'failed' as const, message: 'This step changed' }));
	render(StepsView, {
		repos: [repo({ steps: [stepRead({ fingerprint: 'fp' })] })],
		decisions: store(send)
	});

	await fireEvent.click(screen.getByRole('button', { name: 'Erfolgreich' }));
	await vi.advanceTimersByTimeAsync(UNDO_SECONDS * 1000);

	expect(screen.getByRole('alert')).toHaveTextContent('This step changed');
	expect(screen.getByRole('button', { name: 'Erfolgreich' })).toBeDisabled();
	expect(screen.getByRole('button', { name: 'Fehlgeschlagen' })).toBeDisabled();
});
