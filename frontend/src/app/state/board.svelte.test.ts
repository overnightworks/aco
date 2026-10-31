import { expect, test, vi } from 'vitest';
import { repo } from '../../test-support/board';
import { BoardStore } from './board.svelte';

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
	expect(store.repos).toEqual(repos);
	expect(store.error).toBeNull();
});

test('a failed load reaches the unavailable state with the failure message', async () => {
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
	expect(store.repos).toEqual(first);
	release();
	await reloading;
	expect(store.repos).toEqual([]);
});
