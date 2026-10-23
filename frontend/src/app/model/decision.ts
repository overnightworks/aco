/**
 * The decision wire contract, free of any state or transport: building the
 * request a card as shown sends (`specs/serve.spec.md` ABRD-09/21), and
 * reading its `DecisionResult` into what the stage shows next. Holding no
 * state of its own, this is `DecisionStore`'s (`../state/decision.svelte.ts`)
 * only source for "what just happened" (issue #649).
 */

import type { DecisionRequest, DecisionResult, ExpectationLine, Outcome } from '../../types';

export const UNDO_SECONDS = 8;
/** The operator's window to change their mind before a decision writes; the
 * SPA is this value's one owner. */

export const NOTE_MAX_LENGTH = 280;
/** Mirrors `NOTE_MAX_LENGTH` in `src/aco/board/ports.py` (ABRD-05); the
 * server stays the authority, this only keeps the field from inviting a
 * refusal. */

export const ALREADY_RULED_MESSAGE =
	'Schon entschieden: diese Zeile wurde inzwischen woanders entschieden.';
/** `aco rule`'s own already-ruled sentence (RULE-04) is written for a command
 * line; this is the SPA's own operator-facing copy for the identical case. */

export const LINE_CHANGED_MESSAGE = 'Diese Zeile hat sich geändert, bitte neu laden';
/** The exact refusal `board.py`'s `LINE_CHANGED` sends for ABRD-02: a public
 * contract sentence (`specs/serve.spec.md`), not an adapter detail, so
 * recognising it here to tell "changed" from any other failure is reading
 * the contract, not duplicating an implementation value. */

export const BOARD_UNREACHABLE_MESSAGE = 'Das Board ist nicht erreichbar.';

export function lineKey(repo: string, item: number, line: ExpectationLine): string {
	return `${repo}:${item}:${line.index}`;
}

export function decisionRequest(
	repo: string,
	item: number,
	line: ExpectationLine,
	outcome: Outcome,
	note: string | null
): DecisionRequest {
	return { repo, item, line: line.index, fingerprint: line.fingerprint, outcome, note };
}

/** A blank note, trimmed, is no note (mirrors `aco.board.api._note`). */
export function noteOrNull(raw: string): string | null {
	const trimmed = raw.trim();
	return trimmed === '' ? null : trimmed;
}

export type DecisionOutcome =
	| { kind: 'ruled' }
	| { kind: 'already-ruled'; message: string }
	| { kind: 'changed'; message: string }
	| { kind: 'failed'; message: string };

export function readDecisionResult(result: DecisionResult): DecisionOutcome {
	switch (result.status) {
		case 'ruled':
			return { kind: 'ruled' };
		case 'already_ruled':
			return { kind: 'already-ruled', message: ALREADY_RULED_MESSAGE };
		case 'failed':
			return result.message === LINE_CHANGED_MESSAGE
				? { kind: 'changed', message: result.message }
				: { kind: 'failed', message: result.message ?? 'unbekannter Fehler' };
	}
}
