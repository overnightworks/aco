import { fireEvent, render, screen, within } from '@testing-library/svelte';
import type { postStep } from '../client';
import { UNDO_SECONDS } from '../app/model/decision';
import { afterEach, expect, test, vi } from 'vitest';
import { inertBoard, oldStepRead, repo, stepRead } from '../test-support/board';
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

test('ABRD-159: a step of the paste form shows its title, step line, purpose, command in a box, expected result and the yes or no answer', () => {
	render(StepsView, { repos: [repo({ steps: [stepRead()] })], decisions: store() });

	const card = screen.getByRole('article', { name: /Release/ });
	expect(within(card).getByText('Run the release.')).toBeInTheDocument();
	expect(within(card).getByText('Release the build.')).toBeInTheDocument();
	expect(card.querySelector('pre')?.textContent).toBe('make release');
	expect(within(card).getByText('The page shows green.')).toBeInTheDocument();
	expect(within(card).getByText('Antwort: Ja / Nein')).toBeInTheDocument();
});

test('ABRD-160: Copy puts exactly the command on the clipboard and says so', async () => {
	const writeText = vi.fn(() => Promise.resolve());
	stubClipboard(writeText);
	render(StepsView, {
		repos: [repo({ steps: [stepRead({ paste: 'cd ~/repo && make release' })] })],
		decisions: store()
	});

	await fireEvent.click(screen.getByRole('button', { name: 'Copy' }));

	expect(writeText).toHaveBeenCalledWith('cd ~/repo && make release');
	expect(await screen.findByRole('button', { name: 'Copied' })).toBeInTheDocument();
});

test('ABRD-160: a refused copy says so and offers the copy again', async () => {
	stubClipboard(() => Promise.reject(new Error('denied')));
	render(StepsView, { repos: [repo({ steps: [stepRead()] })], decisions: store() });

	await fireEvent.click(screen.getByRole('button', { name: 'Copy' }));

	expect(await screen.findByRole('button', { name: 'Copy failed, try again' })).toBeInTheDocument();
});

test('ABRD-195: a link paste shows the button Öffnen and no box or Copy', () => {
	render(StepsView, {
		repos: [
			repo({
				steps: [stepRead({ paste: 'https://example.test/run', paste_kind: 'link' })]
			})
		],
		decisions: store()
	});

	expect(screen.getByRole('link', { name: 'Öffnen' })).toBeInTheDocument();
	expect(document.querySelector('pre')).toBeNull();
	expect(screen.queryByRole('button', { name: 'Copy' })).toBeNull();
});

test('ABRD-196: Öffnen opens the paste in a new tab without an opener', () => {
	render(StepsView, {
		repos: [
			repo({
				steps: [stepRead({ paste: 'http://127.0.0.1:8765/run', paste_kind: 'link' })]
			})
		],
		decisions: store()
	});

	const link = screen.getByRole('link', { name: 'Öffnen' });
	expect(link).toHaveAttribute('href', 'http://127.0.0.1:8765/run');
	expect(link).toHaveAttribute('target', '_blank');
	expect(link).toHaveAttribute('rel', 'noopener noreferrer');
});

test.each([
	['javascript:', 'javascript://x'],
	['ftp://', 'ftp://host/x']
])('ABRD-196: a stored %s paste of the old form is no link', (_name, paste) => {
	render(StepsView, {
		repos: [repo({ steps: [oldStepRead({ actions: null, paste, expected: 'Done.', url: null })] })],
		decisions: store()
	});

	expect(screen.queryByRole('link')).toBeNull();
	expect(screen.getByText(paste)).toBeInTheDocument();
});

test.each([
	['actions', oldStepRead({ actions: 'click Run' })],
	['an answer', oldStepRead({ actions: 'click Run', answer: 'the report' })],
	['a rule-breaking paste', oldStepRead({ actions: null, paste: 'make a; make b' })]
])(
	'ABRD-197: an old step with %s shows alte Form and its stored text, no Copy or Öffnen',
	(_name, step) => {
		render(StepsView, { repos: [repo({ steps: [step] })], decisions: store() });

		expect(screen.getByText('alte Form')).toBeInTheDocument();
		expect(screen.getByText(step.actions ?? step.paste ?? '')).toBeInTheDocument();
		expect(screen.getByText('The page shows green.')).toBeInTheDocument();
		expect(screen.queryByRole('button', { name: 'Copy' })).toBeNull();
		expect(screen.queryByRole('link', { name: 'Öffnen' })).toBeNull();
		expect(document.querySelector('pre')).toBeNull();
	}
);

test('ABRD-161: a step without a table shows its line and alte Form, with both answer buttons and no Copy', () => {
	render(StepsView, {
		repos: [
			repo({
				steps: [
					oldStepRead({
						purpose: null,
						actions: null,
						expected: null,
						step: 'Run the release dispatch.'
					})
				]
			})
		],
		decisions: store()
	});

	expect(screen.getByText('Run the release dispatch.')).toBeInTheDocument();
	expect(screen.getByText('alte Form')).toBeInTheDocument();
	expect(screen.getByRole('button', { name: 'Erfolgreich' })).toBeInTheDocument();
	expect(screen.getByRole('button', { name: 'Fehlgeschlagen' })).toBeInTheDocument();
	expect(screen.queryByRole('button', { name: 'Copy' })).toBeNull();
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

test('ABRD-173: an old step that stores an answer offers Erfolgreich and Fehlgeschlagen and no report field', () => {
	render(StepsView, {
		repos: [repo({ steps: [oldStepRead({ answer: 'the green run id' })] })],
		decisions: store()
	});

	expect(screen.getByRole('button', { name: 'Erfolgreich' })).toBeInTheDocument();
	expect(screen.getByRole('button', { name: 'Fehlgeschlagen' })).toBeInTheDocument();
	expect(screen.queryByLabelText('Bericht')).toBeNull();
	expect(screen.queryByRole('button', { name: 'Senden' })).toBeNull();
});

test('ABRD-197: an old step shows the answer it stored as plain text', () => {
	render(StepsView, {
		repos: [repo({ steps: [oldStepRead({ answer: 'the green run id' })] })],
		decisions: store()
	});

	expect(screen.getByText('the green run id')).toBeInTheDocument();
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
		repos: [repo({ steps: [stepRead({ fingerprint: 'two', paste: 'make stop' })] })],
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

test.each([
	['paste', stepRead()],
	['old', oldStepRead()],
	['without a table', oldStepRead({ purpose: null, actions: null, expected: null })]
])('ABRD-198: a step of the %s form shows wartet seit and its date', (_name, step) => {
	render(StepsView, { repos: [repo({ steps: [step] })], decisions: store() });

	expect(screen.getByText('wartet seit 01.11.2026')).toBeInTheDocument();
});

test('ABRD-198: #n links to the item in a new tab without an opener', () => {
	render(StepsView, { repos: [repo({ steps: [stepRead()] })], decisions: store() });

	const link = screen.getByRole('link', { name: '#7' });
	expect(link).toHaveAttribute('href', 'https://github.com/owner/repo/issues/7');
	expect(link).toHaveAttribute('target', '_blank');
	expect(link).toHaveAttribute('rel', 'noopener noreferrer');
});

test('ABRD-198: a step without a url shows #n as plain text', () => {
	render(StepsView, { repos: [repo({ steps: [stepRead({ url: null })] })], decisions: store() });

	expect(screen.getByText('#7')).toBeInTheDocument();
	expect(screen.queryByRole('link', { name: '#7' })).toBeNull();
});

test('ABRD-199: the group of the newer step stands first, and a failed repo stands last with its alert', () => {
	render(StepsView, {
		repos: [
			repo({ name: 'broken', error: 'GitHub is down', steps: [] }),
			repo({ name: 'older', steps: [stepRead({ since: '2026-10-01' })] }),
			repo({ name: 'newer', steps: [stepRead({ since: '2026-11-01' })] })
		],
		decisions: store()
	});

	expect(
		screen.getAllByRole('heading', { level: 2 }).map((heading) => heading.textContent)
	).toEqual(['newer', 'older', 'broken']);
	expect(screen.getByRole('alert')).toHaveTextContent('GitHub is down');
});
