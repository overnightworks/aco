import { render, screen, within } from '@testing-library/svelte';
import { expect, test } from 'vitest';
import {
	clockTime,
	LAST_READ_LABEL,
	NO_STEP_READ_TEXT,
	NO_STEP_TEXT,
	NO_STEP_WAITING_TEXT,
	NOT_READ_LABEL,
	STEPS_HEADING
} from '../app/model/boardSummary';
import { repo } from '../test-support/board';
import StepsList from './StepsList.svelte';

type Reading = ReturnType<typeof repo> & { readAt?: Date | null };

function renderSteps(repos: Reading[]) {
	return render(StepsList, { repos: repos.map((reading) => ({ readAt: null, ...reading })) });
}

const rotate = {
	number: 9,
	title: 'Rotate the key',
	step: 'Run the rotate script, then say done.'
};

test('[ABRD-118] the section is a region headed Steps with the count of the rows it shows', () => {
	renderSteps([
		repo({ name: 'a', steps: [rotate] }),
		repo({ name: 'b', steps: [{ number: 3, title: 'Pay', step: 'Pay the invoice.' }] })
	]);

	const region = screen.getByRole('region', { name: `${STEPS_HEADING} 2` });
	expect(within(region).getAllByRole('listitem')).toHaveLength(2);
});

test('[ABRD-119] a row shows its repository, number, title and the step in full', () => {
	const long = 'Open the console and '.repeat(40);
	renderSteps([repo({ name: 'aco', steps: [{ ...rotate, step: long }] })]);

	expect(screen.getByRole('heading', { level: 3 })).toHaveTextContent('aco');
	const row = screen.getByRole('listitem');
	expect(row).toHaveTextContent('#9');
	expect(row).toHaveTextContent('Rotate the key');
	expect(row.querySelector('.step')?.textContent).toBe(long);
});

test('[ABRD-119] a row whose item names no step says so', () => {
	renderSteps([repo({ steps: [{ ...rotate, step: null }] })]);

	expect(screen.getByRole('listitem')).toHaveTextContent(NO_STEP_TEXT);
});

test('[ABRD-120] a row holds no control and takes no focus; its text is shown as text', () => {
	const markup = '<a href="https://example.test">x</a>';
	renderSteps([repo({ steps: [{ ...rotate, title: markup, step: markup }] })]);

	const region = screen.getByRole('region');
	expect(region.querySelectorAll('a, button, input, select, textarea, [tabindex]')).toHaveLength(0);
	expect(screen.getByRole('listitem')).toHaveTextContent(`${markup} ${markup}`);
});

test('[ABRD-121] with no step the heading stays and one sentence says no step waits', () => {
	renderSteps([repo({ steps: [] })]);

	expect(screen.getByRole('region')).toHaveTextContent(`${STEPS_HEADING} 0`);
	expect(screen.getByText(NO_STEP_WAITING_TEXT)).toBeInTheDocument();
	expect(screen.queryByRole('listitem')).toBeNull();
});

test('[ABRD-121] with no step and a repository not read the sentence claims only the projects read', () => {
	renderSteps([repo({ name: 'a', steps: [] }), repo({ name: 'b', error: 'gh down', steps: [] })]);

	expect(screen.getByText(NO_STEP_READ_TEXT)).toBeInTheDocument();
	expect(screen.queryByText(NO_STEP_WAITING_TEXT)).toBeNull();
});

test('[ABRD-122] the kept steps of a repository not read carry Not read and the last read time', () => {
	const readAt = new Date(2026, 9, 31, 9, 41);
	renderSteps([{ ...repo({ name: 'b', error: 'gh down', steps: [rotate] }), readAt }]);

	const alert = screen.getByRole('alert');
	expect(alert).toHaveTextContent(NOT_READ_LABEL);
	expect(alert).toHaveTextContent('gh down');
	expect(alert).toHaveTextContent(`${LAST_READ_LABEL} ${clockTime(readAt)}`);
	expect(screen.getByRole('listitem')).toHaveTextContent('Rotate the key');
});

test('[ABRD-122] a repository never read before it failed shows no last read time', () => {
	renderSteps([repo({ name: 'b', error: 'gh down', steps: [rotate] })]);

	expect(screen.getByRole('alert')).not.toHaveTextContent(LAST_READ_LABEL);
});
