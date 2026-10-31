/**
 * Owns the 8 s undo window and the one write it allows: a decided card
 * waits here, cancellable, until `UNDO_SECONDS` elapse, then becomes exactly
 * one `POST /api/rule`. An option card is decided as a whole: the store holds
 * its picks and its open point, and starts the window once every point is
 * chosen. `Stage.svelte` reads whether a card is waiting (in its undo window
 * or saving), reading again after a refusal, or refused, and which picks a
 * waiting answer holds; `App.svelte` renders one `UndoStrip` per still-pending entry.
 * A stored answer carries the written item, which `BoardStore.applyItem`
 * (`board.svelte.ts`) shows in place; `reload` re-reads only for `Neu laden`.
 */

import { untrack } from 'svelte';
import { SvelteMap, SvelteSet } from 'svelte/reactivity';
import { postDecision } from '../../client';
import type { BoardItem, DecisionRequest, OptionLine, RepoReading } from '../../types';
import { findSelection, type StripState } from '../model/boardSummary';
import {
	cardName,
	livePicks,
	nextOpenAfterPick,
	pickedText,
	recommendedPicks,
	withPick,
	type Pick
} from '../model/card';
import {
	BOARD_UNREACHABLE_MESSAGE,
	cardKey,
	cardOtherRequest,
	cardPicksRequest,
	cardUnclearRequest,
	readDecisionResult,
	UNDO_SECONDS,
	type DecisionOutcome
} from '../model/decision';
import { nextOpen, pendingOtherText, type EscapeKind, type EscapePanel } from '../model/optionCard';

export interface DecisionBanner {
	kind: 'already-ruled' | 'changed' | 'failed';
	message: string;
}

/** A changed or already-ruled card is decided only after `Neu laden`; any
 * other refusal leaves the choices usable for a retry. */
export function locksCard(banner: DecisionBanner | null): boolean {
	return banner !== null && banner.kind !== 'failed';
}

/** What the decisions need of the board: a re-read, and a stored item shown in place. */
export interface DecisionBoard {
	reload: () => Promise<void>;
	applyItem: (repo: string, item: BoardItem) => void;
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
	/** The picks this answer posts: a pick's or Accept all's, none for an escape answer. */
	held: readonly Pick[];
	/** The panel `Undo` reopens, for an escape answer only. */
	reopens: EscapePanel | null;
}

function draftKey(key: string, kind: EscapeKind): string {
	return `${kind}:${key}`;
}

/** The picks of a card the reading does not show: gone for good when its repo was
 * read without error (the card is ruled or removed), kept while that repo is unavailable. */
function unreadPicks(repos: RepoReading[], key: string, picks: Pick[]): Pick[] {
	const repoWasRead = repos.some(
		(reading) =>
			reading.error === null &&
			key.startsWith(`${reading.name}:`) &&
			/^\d+:card$/.test(key.slice(reading.name.length + 1))
	);
	return repoWasRead ? [] : picks;
}

function withoutKey<Value>(record: Record<string, Value>, key: string): Record<string, Value> {
	return Object.fromEntries(Object.entries(record).filter(([entryKey]) => entryKey !== key));
}

export class DecisionStore {
	#pending: Record<string, PendingEntry> = $state({});
	#banners: Record<string, DecisionBanner> = $state({});
	/** The cards whose window ended and whose POST has not been answered yet,
	 * each with the picks that POST holds. */
	readonly #saving = new SvelteMap<string, readonly Pick[]>();
	/** The cards whose own `Neu laden` read after a refusal has not been answered yet. */
	readonly #reading = new SvelteSet<string>();
	/** The key this store itself just wrote a ruling for, its item applied --
	 * `App.svelte` advances the stage off it (`boardSummary.nextOpenAfter`)
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
	/** The picks made per card, each with its point as shown when picked. */
	#picks: Record<string, Pick[]> = $state({});
	/** The one open point per card, by line index; none until one is activated. */
	#openPoints: Record<string, number | null> = $state({});

	constructor(
		private readonly token: string,
		private readonly board: DecisionBoard,
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

	/** Whether the card's controls are disabled: in its undo window, saving, or
	 * reading again after a refusal. */
	isPending(key: string): boolean {
		return key in this.#pending || this.#saving.has(key) || this.#reading.has(key);
	}

	/** Whether the card's window ended and its POST has not been answered yet. */
	isSaving(key: string): boolean {
		return this.#saving.has(key);
	}

	/** The picks the card's waiting answer holds (in its undo window or saving),
	 * or null while the card is not waiting. */
	held(key: string): readonly Pick[] | null {
		return this.#pending[key]?.held ?? this.#saving.get(key) ?? null;
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

	/** The picks that still count for the card's points as shown now. */
	picks(key: string, points: readonly OptionLine[]): Pick[] {
		return livePicks(this.#picks[key] ?? [], points);
	}

	/** Drops, for good, the picks of every shown card whose point changed or closed:
	 * a point that later returns to its old fingerprint does not revive its pick. */
	reconcilePicks(repos: RepoReading[]): void {
		const stored = untrack(() => this.#picks);
		const kept: Record<string, Pick[]> = {};
		let dropped = false;
		for (const [key, picks] of Object.entries(stored)) {
			const selection = findSelection(repos, key);
			const live =
				selection?.kind === 'card'
					? livePicks(picks, selection.points)
					: unreadPicks(repos, key, picks);
			dropped ||= live.length !== picks.length;
			kept[key] = live;
		}
		if (dropped) {
			this.#picks = kept;
		}
	}

	/** The line index of the card's open point, or null while none is open. */
	openPoint(key: string): number | null {
		return this.#openPoints[key] ?? null;
	}

	/** Activating a point opens it and closes any other; activating it again closes it. */
	togglePoint(key: string, index: number): void {
		this.#openPoints = { ...this.#openPoints, [key]: nextOpen(this.openPoint(key), index) };
	}

	/** Records a pick; once every point is chosen the undo window starts for the card. */
	choose(repo: string, item: number, points: readonly OptionLine[], pick: Pick): void {
		const key = cardKey(repo, item);
		this.#picks = { ...this.#picks, [key]: withPick(this.#picks[key] ?? [], pick) };
		const open = nextOpenAfterPick(
			this.openPoint(key),
			points,
			this.picks(key, points),
			pick.shown
		);
		this.#openPoints = { ...this.#openPoints, [key]: open };
		this.#decideWhenComplete(repo, item, points);
	}

	/** Every point picks its recommended option, replacing earlier picks. */
	acceptAll(repo: string, item: number, points: readonly OptionLine[]): void {
		const key = cardKey(repo, item);
		this.#picks = { ...this.#picks, [key]: recommendedPicks(points) };
		this.#openPoints = { ...this.#openPoints, [key]: null };
		this.#decideWhenComplete(repo, item, points);
	}

	#decideWhenComplete(repo: string, item: number, points: readonly OptionLine[]): void {
		const key = cardKey(repo, item);
		const picks = this.picks(key, points);
		if (picks.length === points.length) {
			this.#startUndoWindow(
				key,
				cardPicksRequest(repo, item, picks),
				pickedText(points, picks),
				'done',
				picks
			);
		}
	}

	/** The same window for the operator's own answer; the panel closes and the draft stays. */
	decideOther(repo: string, item: number, shown: readonly OptionLine[], answer: string): void {
		const key = cardKey(repo, item);
		this.closePanel(key);
		this.#startUndoWindow(
			key,
			cardOtherRequest(repo, item, shown, answer),
			pendingOtherText(cardName(shown)),
			'done',
			[],
			{ kind: 'other', shown }
		);
	}

	/** The same window for sending the card back to its head; the note may be blank. */
	decideUnclear(repo: string, item: number, shown: readonly OptionLine[], note: string): void {
		const key = cardKey(repo, item);
		this.closePanel(key);
		this.#startUndoWindow(
			key,
			cardUnclearRequest(repo, item, shown, note),
			cardName(shown),
			'back',
			[],
			{ kind: 'unclear', shown }
		);
	}

	#startUndoWindow(
		key: string,
		request: DecisionRequest,
		message: string,
		state: StripState,
		held: readonly Pick[],
		reopens: EscapePanel | null = null
	): void {
		this.#banners = withoutKey(this.#banners, key);
		const timer = setTimeout(() => void this.#commit(key, request, held), this.undoSeconds * 1000);
		this.#pending = { ...this.#pending, [key]: { request, message, state, timer, held, reopens } };
	}

	/** Cancels a still-pending decision; a no-op once it already wrote or was undone.
	 * Undoing a card's picks clears them; undoing an escape answer reopens its panel. */
	undo(key: string): void {
		const entry = this.#pending[key];
		if (entry === undefined) {
			return;
		}
		clearTimeout(entry.timer);
		this.#pending = withoutKey(this.#pending, key);
		if (entry.reopens === null) {
			this.#picks = withoutKey(this.#picks, key);
		} else {
			this.openPanel(key, entry.reopens);
		}
	}

	/** The operator's own "Neu laden" after a refusal: drop it and re-read; the
	 * picks of unchanged points stay, those of changed points go with the re-read.
	 * This card alone is disabled until the read answers, however it ends. */
	async reloadAfterBanner(key: string): Promise<void> {
		this.#banners = withoutKey(this.#banners, key);
		this.#reading.add(key);
		try {
			await this.board.reload();
		} finally {
			this.#reading.delete(key);
		}
	}

	async #commit(key: string, request: DecisionRequest, held: readonly Pick[]): Promise<void> {
		this.#pending = withoutKey(this.#pending, key);
		this.#saving.set(key, held);
		let outcome: DecisionOutcome;
		try {
			outcome = readDecisionResult(await this.send(this.token, request));
		} catch {
			outcome = { kind: 'failed', message: BOARD_UNREACHABLE_MESSAGE };
		}
		// One synchronous step: the card stops saving as its answer is applied.
		this.#saving.delete(key);
		if (outcome.kind === 'ruled') {
			this.#picks = withoutKey(this.#picks, key);
			this.#dropDrafts(key, ['other', 'unclear']);
			this.board.applyItem(request.repo, outcome.item);
			this.#justRuled = key;
		} else if (outcome.kind === 'returned') {
			this.#dropDrafts(key, ['unclear']);
			this.board.applyItem(request.repo, outcome.item);
			this.#justReturned = key;
		} else {
			this.#banners = { ...this.#banners, [key]: outcome };
		}
	}

	#dropDrafts(key: string, kinds: EscapeKind[]): void {
		const dropped = new SvelteSet(kinds.map((kind) => draftKey(key, kind)));
		this.#drafts = Object.fromEntries(
			Object.entries(this.#drafts).filter(([draft]) => !dropped.has(draft))
		);
	}
}
