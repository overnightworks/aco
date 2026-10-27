/**
 * Owns the 8 s undo window and the one write it allows: a chosen outcome
 * waits here, cancellable, until `UNDO_SECONDS` elapse, then becomes exactly
 * one `POST /api/rule`. `Stage.svelte` reads whether a line is mid-undo or
 * refused; `App.svelte` renders one `UndoStrip` per still-pending entry.
 * `reload` is `BoardStore.load` (`board.svelte.ts`): the one source of
 * truth this re-reads from after a write, rather than mutating a copy.
 */

import { postDecision } from '../../client';
import type { CardOption, DecisionRequest, OptionLine, Outcome, YesNoLine } from '../../types';
import { cardHeading, outcomeLabel } from '../model/boardSummary';
import {
	BOARD_UNREACHABLE_MESSAGE,
	decisionRequest,
	lineKey,
	optionDecisionRequest,
	otherDecisionRequest,
	readDecisionResult,
	UNDO_SECONDS,
	type DecisionOutcome
} from '../model/decision';
import { pendingOptionText, pendingOtherText } from '../model/optionCard';

export interface DecisionBanner {
	kind: 'already-ruled' | 'changed' | 'failed';
	message: string;
}

/** A changed or already-ruled card is decided only after `Neu laden`; any
 * other refusal leaves the choices usable for a retry. */
export function locksCard(banner: DecisionBanner | null): boolean {
	return banner !== null && banner.kind !== 'failed';
}

export interface PendingDecision {
	key: string;
	message: string;
}

interface PendingEntry {
	request: DecisionRequest;
	message: string;
	timer: ReturnType<typeof setTimeout>;
	/** The card whose Other panel `Undo` reopens, for an Other answer only. */
	reopens: OptionLine | null;
}

function withoutKey<Value>(record: Record<string, Value>, key: string): Record<string, Value> {
	return Object.fromEntries(Object.entries(record).filter(([entryKey]) => entryKey !== key));
}

export class DecisionStore {
	#pending: Record<string, PendingEntry> = $state({});
	#banners: Record<string, DecisionBanner> = $state({});
	/** The key this store itself just wrote a ruling for, reread and reloaded
	 * -- `App.svelte` advances the stage off it (`boardSummary.nextOpenAfter`)
	 * when it is still the one shown, never for a manual reload after a
	 * refusal banner. */
	#justRuled: string | null = $state(null);
	/** The Other answer typed per card, kept until its decision is stored. */
	#drafts: Record<string, string> = $state({});
	/** The card as shown when its Other panel opened -- the card `Send` posts. */
	#otherPanels: Record<string, OptionLine> = $state({});

	constructor(
		private readonly token: string,
		private readonly reload: () => Promise<void>,
		private readonly send: typeof postDecision = postDecision,
		private readonly undoSeconds: number = UNDO_SECONDS
	) {}

	get pendingEntries(): PendingDecision[] {
		return Object.entries(this.#pending).map(([key, entry]) => ({
			key,
			message: entry.message
		}));
	}

	isPending(key: string): boolean {
		return key in this.#pending;
	}

	banner(key: string): DecisionBanner | null {
		return this.#banners[key] ?? null;
	}

	get justRuled(): string | null {
		return this.#justRuled;
	}

	draft(key: string): string {
		return this.#drafts[key] ?? '';
	}

	setDraft(key: string, text: string): void {
		this.#drafts = { ...this.#drafts, [key]: text };
	}

	/** The card an open Other panel snapshotted, or null while it is closed. */
	otherPanel(key: string): OptionLine | null {
		return this.#otherPanels[key] ?? null;
	}

	openOtherPanel(key: string, shown: OptionLine): void {
		this.#otherPanels = { ...this.#otherPanels, [key]: shown };
	}

	closeOtherPanel(key: string): void {
		this.#otherPanels = withoutKey(this.#otherPanels, key);
	}

	/** Starts the undo window for one card as shown; never sends before it elapses. */
	decide(repo: string, item: number, line: YesNoLine, outcome: Outcome, note: string | null): void {
		this.#startUndoWindow(
			lineKey(repo, item, line),
			decisionRequest(repo, item, line, outcome, note),
			`${outcomeLabel(outcome)}: ${cardHeading(line)}`
		);
	}

	/** The same window for the letter picked on an option card. */
	decideOption(repo: string, item: number, line: OptionLine, option: CardOption): void {
		this.#startUndoWindow(
			lineKey(repo, item, line),
			optionDecisionRequest(repo, item, line, option),
			pendingOptionText(line, option)
		);
	}

	/** The same window for the operator's own answer; the panel closes and the draft stays. */
	decideOther(repo: string, item: number, shown: OptionLine, answer: string): void {
		const key = lineKey(repo, item, shown);
		this.closeOtherPanel(key);
		this.#startUndoWindow(
			key,
			otherDecisionRequest(repo, item, shown, answer),
			pendingOtherText(shown),
			shown
		);
	}

	#startUndoWindow(
		key: string,
		request: DecisionRequest,
		message: string,
		reopens: OptionLine | null = null
	): void {
		this.#banners = withoutKey(this.#banners, key);
		const timer = setTimeout(() => void this.#commit(key, request), this.undoSeconds * 1000);
		this.#pending = { ...this.#pending, [key]: { request, message, timer, reopens } };
	}

	/** Cancels a still-pending decision; a no-op once it already wrote or was undone. */
	undo(key: string): void {
		const entry = this.#pending[key];
		if (entry === undefined) {
			return;
		}
		clearTimeout(entry.timer);
		this.#pending = withoutKey(this.#pending, key);
		if (entry.reopens !== null) {
			this.openOtherPanel(key, entry.reopens);
		}
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
			this.#drafts = withoutKey(this.#drafts, key);
			await this.reload();
			this.#justRuled = key;
			return;
		}
		this.#banners = { ...this.#banners, [key]: outcome };
	}
}
