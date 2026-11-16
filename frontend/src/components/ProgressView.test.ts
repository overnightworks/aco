import { render, screen, within } from '@testing-library/svelte';
import { expect, test } from 'vitest';
import { progressContainer, progressRead, repo } from '../test-support/board';
import ProgressView from './ProgressView.svelte';

test('[ABRD-135] a repo shows its figure, bar, counts and each top-level container', () => {
	render(ProgressView, {
		repos: [repo({ name: 'songmaker', progress: progressRead() })]
	});

	const article = screen.getByRole('article');
	expect(within(article).getAllByText('7/48 · 14 %')).toHaveLength(2);
	expect(within(article).getByText(/^Landed/)).toHaveTextContent('Landed 4');
	expect(within(article).getByText(/^Closed otherwise/)).toHaveTextContent('Closed otherwise 3');
	expect(within(article).getByText(/^Open/)).toHaveTextContent('Open 31');
	expect(within(article).getByText(/^Uncut/)).toHaveTextContent('Uncut 10');
	expect(within(article).getByText('Waiting')).toHaveTextContent('Waiting 2');
	expect(within(article).getByText('#10')).toBeInTheDocument();
	expect(screen.getAllByRole('progressbar')).toHaveLength(2);
	expect(screen.getAllByRole('progressbar')[1]).toHaveAttribute('aria-valuetext', '7/48 · 14 %');
});

test('[ABRD-135] a repo with no container says so and shows no percent', () => {
	render(ProgressView, {
		repos: [
			repo({
				progress: progressRead({
					closed: 0,
					landed: 0,
					planned: 0,
					open: 0,
					uncut: 0,
					percent: null,
					waiting: 0,
					containers: []
				})
			})
		]
	});

	expect(screen.getByText('0/0')).toBeInTheDocument();
	expect(screen.getByText('No container is open.')).toBeInTheDocument();
	expect(screen.getByText('Nothing planned')).toBeInTheDocument();
	expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
});

test('[ABRD-137] a container shows its waiting count only when it is not zero', () => {
	const quiet = progressContainer({ number: 11, title: 'Quiet', waiting: 0 });
	render(ProgressView, {
		repos: [repo({ progress: progressRead({ containers: [progressContainer(), quiet] }) })]
	});

	const [waiting, ...others] = within(screen.getByRole('article')).getAllByText(/^Waiting \d/);
	expect(waiting).toHaveTextContent('Waiting 1');
	expect(others).toHaveLength(0);
});

test('[ABRD-135] a container at one hundred percent is marked done', () => {
	const done = progressContainer({ closed: 5, planned: 5, open: 0, uncut: 0, percent: 100 });
	render(ProgressView, { repos: [repo({ progress: progressRead({ containers: [done] }) })] });

	expect(screen.getAllByRole('progressbar')[1]).toHaveClass('done');
});

test('[ABRD-134] a progress that could not be read shows its sentence and no figure', () => {
	render(ProgressView, { repos: [repo({ progress: { error: 'GitHub is down' } })] });

	expect(screen.getByRole('alert')).toHaveTextContent('Progress unknown');
	expect(screen.getByRole('alert')).toHaveTextContent('GitHub is down');
	expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
});

test('[ABRD-135] a repo that was not read shows its sentence', () => {
	render(ProgressView, { repos: [repo({ error: 'git refused the read', progress: null })] });

	expect(screen.getByRole('alert')).toHaveTextContent('Not read');
	expect(screen.getByRole('alert')).toHaveTextContent('git refused the read');
});

test('[ABRD-146] a container shows its lanes left and range under its bar, none without a lane left', () => {
	const ranged = progressContainer({
		number: 11,
		title: 'Ranged',
		lanes_left: 5,
		estimate: {
			error: null,
			low_seconds: 10800,
			high_seconds: 25200,
			samples: 31,
			classes: [{ size: null, lanes: 5, basis: 'pooled', samples: 31 }]
		}
	});
	const finished = progressContainer({
		number: 12,
		title: 'Finished',
		lanes_left: 0,
		estimate: null
	});
	render(ProgressView, {
		repos: [repo({ progress: progressRead({ containers: [ranged, finished] }) })]
	});

	const article = screen.getByRole('article');
	expect(
		within(article).getByText('5 lanes left · about 3 to 7 h agent work · from 31 finished items')
	).toBeInTheDocument();
	expect(within(article).queryAllByText(/lanes? left/)).toHaveLength(1);
});

test('[ABRD-146] a container whose range is unknown shows the sentence beside its lanes left', () => {
	render(ProgressView, {
		repos: [repo({ progress: progressRead({ containers: [progressContainer()] }) })]
	});

	expect(
		within(screen.getByRole('article')).getByText('40 lanes left · no lane records')
	).toBeInTheDocument();
});
