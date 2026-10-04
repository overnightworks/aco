/**
 * The board's HTTP client. The access token travels only as the
 * `X-Board-Token` header (`specs/aco-board.spec.md` ABRD-10): never appended
 * to the request path, never logged.
 */

import type { BoardResponse } from './types';

export const BOARD_PATH = '/api/board';
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
