import { expect, test } from 'vitest';
import { heldReads, item, line, repo } from '../../test-support/board';
import type { RepoReading } from '../../types';
import { BoardStore } from './board.svelte';

const open = item({ number: 42, title: 'Open' });
const stored = item({ number: 42, title: 'Stored', lines: [line({ text: 'Stored?' })] });
const neighbour = item({ number: 43, title: 'Neighbour' });

async function loaded(repos: RepoReading[]) {
	const store = new BoardStore();
	await store.load(
		'token',
		async () => ({ ok: true, status: 200, json: async () => ({ repos }) }) as Response
	);
	return store;
}

test('[ABRD-98] applying an item replaces only that item', async () => {
	const store = await loaded([repo({ items: [open, neighbour] })]);

	store.applyItem('repo', stored);

	expect(store.repos[0]?.items).toEqual([stored, neighbour]);
});

test('[ABRD-98] a read sent before the answer and answered after keeps the stored item', async () => {
	const store = await loaded([repo({ items: [open] })]);
	const reads = heldReads();

	const reading = store.load('token', reads.fetchImpl);
	store.applyItem('repo', stored);
	reads.answer(0, [repo({ items: [open] })]);
	await reading;

	expect(store.repos[0]?.items).toEqual([stored]);
});

test('[ABRD-98] such a read that omits the item still shows it, appended to its repository', async () => {
	const store = await loaded([repo({ items: [open, neighbour] })]);
	const reads = heldReads();

	const reading = store.load('token', reads.fetchImpl);
	store.applyItem('repo', stored);
	reads.answer(0, [repo({ items: [neighbour] })]);
	await reading;

	expect(store.repos[0]?.items).toEqual([neighbour, stored]);
});

test('[ABRD-98] an older read that omits the item and answers first shows it once the answer is applied', async () => {
	const store = await loaded([repo({ items: [open, neighbour] })]);
	const reads = heldReads();

	const reading = store.load('token', reads.fetchImpl);
	reads.answer(0, [repo({ items: [neighbour] })]);
	await reading;
	store.applyItem('repo', stored);

	expect(store.repos[0]?.items).toEqual([neighbour, stored]);
});

test.each([
	['readable with the old item', () => repo({ items: [open] })],
	['failed', () => repo({ error: 'forge down', items: [] })]
])(
	'[ABRD-98] a read sent before the answer to a kept card and answered after it, %s, keeps the stored item',
	async (_case, answered) => {
		const store = await loaded([repo({ items: [open] })]);
		await store.load(
			'token',
			async () =>
				({
					ok: true,
					status: 200,
					json: async () => ({ repos: [repo({ error: 'forge down', items: [] })] })
				}) as Response
		);
		const reads = heldReads();

		const reading = store.load('token', reads.fetchImpl);
		store.applyItem('repo', stored);
		reads.answer(0, [answered()]);
		await reading;

		expect(store.repos[0]?.items).toEqual([stored]);
	}
);

test('[ABRD-98] a read sent after the answer applies its own row', async () => {
	const store = await loaded([repo({ items: [open] })]);
	store.applyItem('repo', stored);
	const reads = heldReads();
	const newer = item({ number: 42, title: 'Reopened' });

	const reading = store.load('token', reads.fetchImpl);
	reads.answer(0, [repo({ items: [newer] })]);
	await reading;

	expect(store.repos[0]?.items).toEqual([newer]);
});

test('[ABRD-15] a repository an older read reports as failed keeps its error and its items, and the answer reaches them', async () => {
	const store = await loaded([repo({ items: [open] })]);
	const reads = heldReads();

	const reading = store.load('token', reads.fetchImpl);
	reads.answer(0, [repo({ error: 'forge down', items: [] })]);
	await reading;
	store.applyItem('repo', stored);

	expect(store.repos[0]).toMatchObject({ name: 'repo', error: 'forge down', items: [stored] });
});

test.each([
	['answers', (reads: ReturnType<typeof heldReads>) => reads.answer(0, [repo({ items: [open] })])],
	['fails', (reads: ReturnType<typeof heldReads>) => reads.fail(0)]
])(
	'[ABRD-103] a read of a token that went, which %s after a newer read answered, leaves the newer reading',
	async (_case, settleOld) => {
		const store = new BoardStore();
		const reads = heldReads();
		const older = store.load('old', reads.fetchImpl);
		store.setNoAccess();
		const newer = store.load('new', reads.fetchImpl);
		reads.answer(1, [repo({ items: [neighbour] })]);
		await newer;

		settleOld(reads);
		await older;

		expect(store.repos[0]?.items).toEqual([neighbour]);
		expect(store.status).toBe('ready');
	}
);

test('[ABRD-98] a read that starts after the answer applies its row once the answer no longer stands', async () => {
	const store = await loaded([repo({ items: [open] })]);
	store.applyItem('repo', stored);
	const reads = heldReads();
	const newer = item({ number: 42, title: 'Reopened' });

	const reading = store.load('token', reads.fetchImpl);
	reads.answer(0, [repo({ items: [newer] })]);
	await reading;
	const following = store.load('token', reads.fetchImpl);
	reads.answer(1, [repo({ items: [open] })]);
	await following;

	expect(store.repos[0]?.items).toEqual([open]);
});

test('[ABRD-105] a stored answer stands once beside the same card that waits again', async () => {
	let waiting = false;
	const store = new BoardStore(() => waiting);
	await store.load(
		'token',
		async () =>
			({
				ok: true,
				status: 200,
				json: async () => ({ repos: [repo({ items: [open] })] })
			}) as Response
	);
	const reads = heldReads();

	const reading = store.load('token', reads.fetchImpl);
	store.applyItem('repo', stored);
	waiting = true;
	reads.answer(0, [repo({ items: [neighbour] })]);
	await reading;

	expect(store.repos[0]?.items).toEqual([neighbour, stored]);
});
