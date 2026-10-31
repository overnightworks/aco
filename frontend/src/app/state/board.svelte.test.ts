import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { item, repo } from '../../test-support/board';
import type { BoardItem } from '../../types';
import { SERVER_SILENT_SENTENCE } from '../model/boardSummary';
import { BoardStore } from './board.svelte';

beforeEach(() => {
	vi.useFakeTimers({ toFake: ['Date'] });
});

afterEach(() => {
	vi.useRealTimers();
});

function readingsOf(store: BoardStore) {
	return store.repos.map(({ name, error, items }) => ({ name, error, items }));
}

function throwingFetch(): typeof fetch {
	return vi.fn(async () => {
		throw new TypeError('no network');
	}) as unknown as typeof fetch;
}

function fakeFetch(status: number, body: unknown): typeof fetch {
	return vi.fn(async () => ({
		ok: status >= 200 && status < 300,
		status,
		json: async () => body
	})) as unknown as typeof fetch;
}

test('starts as no-access with no repos', () => {
	const store = new BoardStore();

	expect(store.status).toBe('no-access');
	expect(store.repos).toEqual([]);
});

test('loading the board succeeds into the ready state', async () => {
	const store = new BoardStore();
	const repos = [repo()];

	await store.load('secret', fakeFetch(200, { repos }));

	expect(store.status).toBe('ready');
	expect(readingsOf(store)).toEqual(repos);
	expect(store.error).toBeNull();
});

test('a failed first load reaches the unavailable state with the failure message', async () => {
	const store = new BoardStore();

	await store.load('secret', fakeFetch(502, { error: 'aco rulings failed' }));

	expect(store.status).toBe('unavailable');
	expect(store.repos).toEqual([]);
	expect(store.error).toContain('502');
});

test('setNoAccess resets a previously loaded board', async () => {
	const store = new BoardStore();
	await store.load('secret', fakeFetch(200, { repos: [repo()] }));

	store.setNoAccess();

	expect(store.status).toBe('no-access');
	expect(store.repos).toEqual([]);
	expect(store.error).toBeNull();
});

test('[ABRD-47] a ready board stays ready and readable while it is re-read', async () => {
	const store = new BoardStore();
	const first = [repo()];
	await store.load('secret', fakeFetch(200, { repos: first }));
	let release: () => void = () => {};
	const held = new Promise<void>((resolve) => {
		release = resolve;
	});
	const slowFetch = (async () => {
		await held;
		return { ok: true, status: 200, json: async () => ({ repos: [] }) };
	}) as unknown as typeof fetch;

	const reloading = store.load('secret', slowFetch);

	expect(store.status).toBe('ready');
	expect(readingsOf(store)).toEqual(first);
	release();
	await reloading;
	expect(store.repos).toEqual([]);
});

const flawed = (name: string, sentence: string) => repo({ name, error: sentence, items: [] });

test('[ABRD-101] a repository that fails inside an answer keeps its items and read time and takes the sentence', async () => {
	const store = new BoardStore();
	const keptItems = [item({ number: 7 })];
	vi.setSystemTime(new Date(2026, 9, 31, 9, 41));
	await store.load(
		't',
		fakeFetch(200, { repos: [repo({ name: 'a' }), repo({ name: 'b', items: keptItems })] })
	);
	const firstReadAt = store.repos[1]?.readAt?.getTime();
	const newItems = [item({ number: 8 })];
	vi.setSystemTime(new Date(2026, 9, 31, 10, 5));

	await store.load(
		't',
		fakeFetch(200, { repos: [repo({ name: 'a', items: newItems }), flawed('b', 'gh down')] })
	);

	expect(readingsOf(store)[1]).toEqual({ name: 'b', error: 'gh down', items: keptItems });
	expect(store.repos[1]?.readAt?.getTime()).toBe(firstReadAt);
	expect(store.repos[0]?.items).toEqual(newItems);
	expect(store.repos[0]?.readAt?.getTime()).toBe(new Date(2026, 9, 31, 10, 5).getTime());
});

test('[ABRD-101] a repository that fails on its first read has the sentence, no items and no read time', async () => {
	const store = new BoardStore();

	await store.load('t', fakeFetch(200, { repos: [repo({ name: 'a' }), flawed('b', 'gh down')] }));

	expect(readingsOf(store)[1]).toEqual({ name: 'b', error: 'gh down', items: [] });
	expect(store.repos[1]?.readAt).toBeNull();
});

test('[ABRD-101] a repository that reads again replaces its kept items, sentence and time', async () => {
	const store = new BoardStore();
	await store.load('t', fakeFetch(200, { repos: [repo({ name: 'b' })] }));
	await store.load('t', fakeFetch(200, { repos: [flawed('b', 'gh down')] }));
	const fresh = [item({ number: 9 })];
	vi.setSystemTime(new Date(2026, 9, 31, 11, 30));

	await store.load('t', fakeFetch(200, { repos: [repo({ name: 'b', items: fresh })] }));

	expect(readingsOf(store)[0]).toEqual({ name: 'b', error: null, items: fresh });
	expect(store.repos[0]?.readAt?.getTime()).toBe(new Date(2026, 9, 31, 11, 30).getTime());
});

test.each([
	['an answer of 502', fakeFetch(502, { error: 'aco rulings failed' })],
	['no network', throwingFetch()]
])(
	'[ABRD-102] a read that fails whole on a ready board (%s) keeps every repository with the page sentence',
	async (_name, failing) => {
		const store = new BoardStore();
		vi.setSystemTime(new Date(2026, 9, 31, 9, 41));
		await store.load('t', fakeFetch(200, { repos: [repo({ name: 'a' }), repo({ name: 'b' })] }));
		const before = store.repos.map(({ items, readAt }) => ({ items, readAt }));

		await store.load('t', failing);

		expect(store.status).toBe('ready');
		expect(store.error).toBeNull();
		expect(store.repos.map(({ error }) => error)).toEqual([
			SERVER_SILENT_SENTENCE,
			SERVER_SILENT_SENTENCE
		]);
		expect(store.repos.map(({ items, readAt }) => ({ items, readAt }))).toEqual(before);
	}
);

test('[ABRD-33] a stored answer for a kept card shows in place and a later failed read keeps it', async () => {
	const store = new BoardStore();
	await store.load(
		't',
		fakeFetch(200, { repos: [repo({ name: 'b', items: [item({ number: 7, title: 'old' })] })] })
	);
	await store.load('t', fakeFetch(200, { repos: [flawed('b', 'gh down')] }));
	const stored: BoardItem = item({ number: 7, title: 'stored' });

	store.applyItem('b', stored);
	await store.load('t', fakeFetch(200, { repos: [flawed('b', 'gh down')] }));

	expect(store.repos[0]?.items).toEqual([stored]);
});
