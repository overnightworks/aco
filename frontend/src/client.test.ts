import { expect, test, vi } from 'vitest';
import {
	BOARD_PATH,
	BoardApiError,
	RULE_PATH,
	TOKEN_HEADER,
	fetchBoard,
	postDecision
} from './client';
import type { DecisionRequest } from './types';

const NOT_JSON = Symbol('a body that is no JSON');

function fakeFetch(status: number, body: unknown) {
	return vi.fn(async () => ({
		ok: status >= 200 && status < 300,
		status,
		json: async () => {
			if (body === NOT_JSON) throw new SyntaxError('Unexpected token');
			return body;
		}
	})) as unknown as typeof fetch;
}

test('reads the board from GET /api/board with the token only in the header', async () => {
	const fetchImpl = fakeFetch(200, { repos: [] });

	const board = await fetchBoard('secret-token', fetchImpl);

	expect(board).toEqual({ repos: [] });
	expect(fetchImpl).toHaveBeenCalledTimes(1);
	const call = vi.mocked(fetchImpl).mock.calls.at(0);
	if (call === undefined) {
		throw new Error('fetch was not called');
	}
	const [path, init] = call;
	expect(path).toBe(BOARD_PATH);
	expect(String(path)).not.toContain('secret-token');
	expect((init?.headers as Record<string, string>)[TOKEN_HEADER]).toBe('secret-token');
});

test('a refused read raises BoardApiError carrying the sentence of its body', async () => {
	const sentence = 'no repository tracking .aco/board.toml under /work';
	const fetchImpl = fakeFetch(502, { error: sentence });

	await expect(fetchBoard('token', fetchImpl)).rejects.toThrow(BoardApiError);
	await expect(fetchBoard('token', fetchImpl)).rejects.toThrow(sentence);
});

test('a refused read whose body holds the readings is read as the board', async () => {
	const readings = {
		repos: [{ name: 'owner/a', error: 'git refused the read', items: [] }]
	};

	expect(await fetchBoard('token', fakeFetch(502, readings))).toEqual(readings);
});

test.each([
	['a body that is no JSON', NOT_JSON],
	['a JSON body without a sentence', { detail: 'x' }],
	['a blank sentence', { error: '' }],
	['a sentence that is no string', { error: 502 }],
	['a JSON body that is no object', null]
])('a refused read with %s raises BoardApiError naming the status', async (_name, body) => {
	const fetchImpl = fakeFetch(503, body);

	await expect(fetchBoard('token', fetchImpl)).rejects.toThrow(BoardApiError);
	await expect(fetchBoard('token', fetchImpl)).rejects.toThrow('GET /api/board answered 503');
});

test('posts a decision to POST /api/rule with the token only in the header', async () => {
	const decision: DecisionRequest = {
		repo: 'repo',
		item: 42,
		lines: [{ line: 1, fingerprint: 'fp', option: 'A' }]
	};
	const fetchImpl = fakeFetch(200, { status: 'ruled', message: null });

	const result = await postDecision('secret-token', decision, fetchImpl);

	expect(result).toEqual({ status: 'ruled', message: null });
	const call = vi.mocked(fetchImpl).mock.calls.at(0);
	if (call === undefined) {
		throw new Error('fetch was not called');
	}
	const [path, init] = call;
	expect(path).toBe(RULE_PATH);
	expect((init?.headers as Record<string, string>)[TOKEN_HEADER]).toBe('secret-token');
	expect(JSON.parse(init?.body as string)).toEqual(decision);
});

test('a non-OK answer to a decision raises BoardApiError naming the status', async () => {
	const decision: DecisionRequest = {
		repo: 'repo',
		item: 42,
		lines: [{ line: 1, fingerprint: 'fp' }],
		unclear: true,
		note: null
	};
	const fetchImpl = fakeFetch(403, { error: 'forbidden: missing or wrong token' });

	await expect(postDecision('wrong-token', decision, fetchImpl)).rejects.toThrow(BoardApiError);
});
