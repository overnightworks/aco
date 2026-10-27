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
import { cardHeading, outcomeLabel, type StripState } from '../model/boardSummary';
import {
	BOARD_UNREACHABLE_MESSAGE,
	decisionRequest,
	lineKey,
	optionDecisionRequest,
	otherDecisionRequest,
	readDecisionResult,
	UNDO_SECONDS,
	unclearDecisionRequest,
	type DecisionOutcome
} from '../model/decision';
import {
	pendingOptionText,
	pendingOtherText,
	type EscapeKind,
	type EscapePanel
} from '../model/optionCard';

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
	state: StripState;
}

interface PendingEntry {
	request: DecisionRequest;
	message: string;
	state: StripState;
	timer: ReturnType<typeof setTimeout>;
	/** The panel `Undo` reopens, for an escape answer only. */
	reopens: EscapePanel | null;
}

function draftKey(key: string, kind: EscapeKind): string {
	return `${kind}:${key}`;
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
	/** The key this store itself just sent back to its head, reported once
	 * (`acknowledgeReturned`) so selecting the card later never moves the stage. */
	#justReturned: string | null = $state(null);
	/** The text typed per card and escape kind, kept until its decision is stored. */
	#drafts: Record<string, string> = $state({});
	/** The one open escape panel per card, with the card as shown when it opened. */
	#panels: Record<string, EscapePanel> = $state({});

	constructor(
		private readonly token: string,
		private readonly reload: () => Promise<void>,
		private readonly send: typeof postDecision = postDecision,
		private readonly undoSeconds: number = UNDO_SECONDS
	) {}

	get pendingEntries(): PendingDecision[] {
		return Object.entries(this.#pending).map(([key, entry]) => ({
			key,
			message: entry.message,
			state: entry.state
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

	get justReturned(): string | null {
		return this.#justReturned;
	}

	acknowledgeReturned(): void {
		this.#justReturned = null;
	}

	draft(key: string, kind: EscapeKind): string {
		return this.#drafts[draftKey(key, kind)] ?? '';
	}

	setDraft(key: string, kind: EscapeKind, text: string): void {
		this.#drafts = { ...this.#drafts, [draftKey(key, kind)]: text };
	}

	/** The open escape panel and the card it snapshotted, or null while closed. */
	panel(key: string): EscapePanel | null {
		return this.#panels[key] ?? null;
	}

	/** Opening one kind closes the other: a card has one panel at a time. */
	openPanel(key: string, panel: EscapePanel): void {
		this.#panels = { ...this.#panels, [key]: panel };
	}

	closePanel(key: string): void {
		this.#panels = withoutKey(this.#panels, key);
	}

	/** Starts the undo window for one card as shown; never sends before it elapses. */
	decide(repo: string, item: number, line: YesNoLine, outcome: Outcome, note: string | null): void {
		this.#startUndoWindow(
			lineKey(repo, item, line),
			decisionRequest(repo, item, line, outcome, note),
			`${outcomeLabel(outcome)}: ${cardHeading(line)}`,
			'done'
		);
	}

	/** The same window for the letter picked on an option card. */
	decideOption(repo: string, item: number, line: OptionLine, option: CardOption): void {
		this.#startUndoWindow(
			lineKey(repo, item, line),
			optionDecisionRequest(repo, item, line, option),
			pendingOptionText(line, option),
			'done'
		);
	}

	/** The same window for the operator's own answer; the panel closes and the draft stays. */
	decideOther(repo: string, item: number, shown: OptionLine, answer: string): void {
		const key = lineKey(repo, item, shown);
		this.closePanel(key);
		this.#startUndoWindow(
			key,
			otherDecisionRequest(repo, item, shown, answer),
			pendingOtherText(shown),
			'done',
			{ kind: 'other', shown }
		);
	}

	/** The same window for sending the card back to its head; the note may be blank. */
	decideUnclear(repo: string, item: number, shown: OptionLine, note: string): void {
		const key = lineKey(repo, item, shown);
		this.closePanel(key);
		this.#startUndoWindow(
			key,
			unclearDecisionRequest(repo, item, shown, note),
			shown.topic,
			'back',
			{ kind: 'unclear', shown }
		);
	}

	#startUndoWindow(
		key: string,
		request: DecisionRequest,
		message: string,
		state: StripState,
		reopens: EscapePanel | null = null
	): void {
		this.#banners = withoutKey(this.#banners, key);
		const timer = setTimeout(() => void this.#commit(key, request), this.undoSeconds * 1000);
		this.#pending = { ...this.#pending, [key]: { request, message, state, timer, reopens } };
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
			this.openPanel(key, entry.reopens);
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
			this.#dropDrafts(key, ['other', 'unclear']);
			await this.reload();
			this.#justRuled = key;
			return;
		}
		if (outcome.kind === 'returned') {
			this.#dropDrafts(key, ['unclear']);
			await this.reload();
			this.#justReturned = key;
			return;
		}
		this.#banners = { ...this.#banners, [key]: outcome };
	}

	#dropDrafts(key: string, kinds: EscapeKind[]): void {
		const dropped = new Set(kinds.map((kind) => draftKey(key, kind)));
		this.#drafts = Object.fromEntries(
			Object.entries(this.#drafts).filter(([draft]) => !dropped.has(draft))
		);
	}
}
