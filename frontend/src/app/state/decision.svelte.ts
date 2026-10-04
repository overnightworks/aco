/**
 * Owns the 8 s undo window and the one write it allows: a chosen outcome
 * waits here, cancellable, until `UNDO_SECONDS` elapse, then becomes exactly
 * one `POST /api/rule`. `Stage.svelte` reads whether a line is mid-undo or
 * refused; `App.svelte` renders one `UndoToast` per still-pending entry.
 * `reload` is `BoardStore.load` (`board.svelte.ts`): the one source of
 * truth this re-reads from after a write, rather than mutating a copy
 * (issue #649).
 */

import { postDecision } from '../../client';
import type { DecisionRequest, ExpectationLine, Outcome } from '../../types';
import { cardHeading, outcomeLabel } from '../model/boardSummary';
import {
	BOARD_UNREACHABLE_MESSAGE,
	decisionRequest,
	lineKey,
	readDecisionResult,
	UNDO_SECONDS,
	type DecisionOutcome
} from '../model/decision';

export interface DecisionBanner {
	kind: 'already-ruled' | 'changed' | 'failed';
	message: string;
}

export interface PendingDecision {
	key: string;
	outcome: Outcome;
	message: string;
}

interface PendingEntry {
	request: DecisionRequest;
	message: string;
	timer: ReturnType<typeof setTimeout>;
}

function withoutKey<Value>(record: Record<string, Value>, key: string): Record<string, Value> {
	return Object.fromEntries(Object.entries(record).filter(([entryKey]) => entryKey !== key));
}

export class DecisionStore {
	#pending: Record<string, PendingEntry> = $state({});
	#banners: Record<string, DecisionBanner> = $state({});

	constructor(
		private readonly token: string,
		private readonly reload: () => Promise<void>,
		private readonly send: typeof postDecision = postDecision,
		private readonly undoSeconds: number = UNDO_SECONDS
	) {}

	get pendingEntries(): PendingDecision[] {
		return Object.entries(this.#pending).map(([key, entry]) => ({
			key,
			outcome: entry.request.outcome,
			message: entry.message
		}));
	}

	isPending(key: string): boolean {
		return key in this.#pending;
	}

	banner(key: string): DecisionBanner | null {
		return this.#banners[key] ?? null;
	}

	/** Starts the undo window for one card as shown; never sends before it elapses. */
	decide(
		repo: string,
		item: number,
		line: ExpectationLine,
		outcome: Outcome,
		note: string | null
	): void {
		const key = lineKey(repo, item, line);
		this.#banners = withoutKey(this.#banners, key);
		const request = decisionRequest(repo, item, line, outcome, note);
		const message = `${outcomeLabel(outcome)}: ${cardHeading(line)}`;
		const timer = setTimeout(() => void this.#commit(key, request), this.undoSeconds * 1000);
		this.#pending = { ...this.#pending, [key]: { request, message, timer } };
	}

	/** Cancels a still-pending decision; a no-op once it already wrote or was undone. */
	undo(key: string): void {
		const entry = this.#pending[key];
		if (entry === undefined) {
			return;
		}
		clearTimeout(entry.timer);
		this.#pending = withoutKey(this.#pending, key);
	}

	/** The operator's own "Neu laden" after a refusal: drop it and re-read afresh. */
	async reloadAfterBanner(key: string): Promise<void> {
		this.#banners = withoutKey(this.#banners, key);
		await this.reload();
	}

	async #commit(key: string, request: DecisionRequest): Promise<void> {
		this.#pending = withoutKey(this.#pending, key);
		let outcome: DecisionOutcome;
		try {
			outcome = readDecisionResult(await this.send(this.token, request));
		} catch {
			outcome = { kind: 'failed', message: BOARD_UNREACHABLE_MESSAGE };
		}
		if (outcome.kind === 'ruled') {
			await this.reload();
			return;
		}
		this.#banners = { ...this.#banners, [key]: outcome };
	}
}
