/**
 * The board's HTTP client. The access token travels only as the
 * `X-Board-Token` header (`specs/serve.spec.md` ABRD-10): never appended
 * to the request path, never logged.
 */

import type { BoardResponse, DecisionRequest, DecisionResult } from './types';

export const BOARD_PATH = '/api/board';
export const RULE_PATH = '/api/rule';
export const TOKEN_HEADER = 'X-Board-Token';

export class BoardApiError extends Error {}

export async function fetchBoard(
	token: string,
	fetchImpl: typeof fetch = fetch
): Promise<BoardResponse> {
	const response = await fetchImpl(BOARD_PATH, { headers: { [TOKEN_HEADER]: token } });
	if (!response.ok) {
		throw new BoardApiError(`GET ${BOARD_PATH} answered ${response.status}`);
	}
	return (await response.json()) as BoardResponse;
}

export async function postDecision(
	token: string,
	decision: DecisionRequest,
	fetchImpl: typeof fetch = fetch
): Promise<DecisionResult> {
	const response = await fetchImpl(RULE_PATH, {
		method: 'POST',
		headers: { [TOKEN_HEADER]: token, 'Content-Type': 'application/json' },
		body: JSON.stringify(decision)
	});
	if (!response.ok) {
		throw new BoardApiError(`POST ${RULE_PATH} answered ${response.status}`);
	}
	return (await response.json()) as DecisionResult;
}
