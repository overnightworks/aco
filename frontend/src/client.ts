/**
 * The board's HTTP client. The access token travels only as the
 * `X-Board-Token` header (`specs/serve.spec.md` ABRD-10): never appended
 * to the request path, never logged.
 */

import type {
	BoardResponse,
	DecisionRequest,
	DecisionResult,
	StepRequest,
	StepResult
} from './types';

export const BOARD_PATH = '/api/board';
export const RULE_PATH = '/api/rule';
export const STEP_PATH = '/api/step';
export const TOKEN_HEADER = 'X-Board-Token';

export class BoardApiError extends Error {}

/** The body of a refused answer, or null when it is no JSON. */
async function refusalBody(response: Response): Promise<unknown> {
	try {
		return await response.json();
	} catch {
		return null;
	}
}

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === 'object' && value !== null;
}

function carriesReading(body: unknown): body is BoardResponse {
	return isRecord(body) && Array.isArray(body.repos);
}

function sentenceOf(body: unknown): string | null {
	return isRecord(body) && typeof body.error === 'string' && body.error !== '' ? body.error : null;
}

/** The board's reading. A refused read still answers with a reading when every
 * repository failed, and with the server's sentence otherwise; the status line
 * stands only when the body carries neither. */
export async function fetchBoard(
	token: string,
	fetchImpl: typeof fetch = fetch
): Promise<BoardResponse> {
	const response = await fetchImpl(BOARD_PATH, { headers: { [TOKEN_HEADER]: token } });
	if (response.ok) {
		return (await response.json()) as BoardResponse;
	}
	const body = await refusalBody(response);
	if (carriesReading(body)) {
		return body;
	}
	throw new BoardApiError(sentenceOf(body) ?? `GET ${BOARD_PATH} answered ${response.status}`);
}

export async function postDecision(
	token: string,
	decision: DecisionRequest,
	fetchImpl: typeof fetch = fetch
): Promise<DecisionResult> {
	return (await postJson(RULE_PATH, token, decision, fetchImpl)) as DecisionResult;
}

export async function postStep(
	token: string,
	step: StepRequest,
	fetchImpl: typeof fetch = fetch
): Promise<StepResult> {
	return (await postJson(STEP_PATH, token, step, fetchImpl)) as StepResult;
}

async function postJson(
	path: string,
	token: string,
	body: unknown,
	fetchImpl: typeof fetch
): Promise<unknown> {
	const response = await fetchImpl(path, {
		method: 'POST',
		keepalive: true,
		headers: { [TOKEN_HEADER]: token, 'Content-Type': 'application/json' },
		body: JSON.stringify(body)
	});
	if (!response.ok) {
		throw new BoardApiError(`POST ${path} answered ${response.status}`);
	}
	return response.json();
}
