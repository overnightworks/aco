/**
 * Owns the 8 s undo window and the one write it allows: an answer waits here,
 * cancellable, until `UNDO_SECONDS` elapse, then becomes exactly one
 * `POST /api/rule`. Each point of an option card is answered on its own: a
 * pick starts a window for its point at once, Accept all and Unclear for the
 * points not waiting, and every window is one entry keyed by the lines it
 * posts, so other points stay open while one waits. `Stage.svelte` reads
 * which points of a card wait (in their undo window or saving), whether it is
 * reading again after a refusal or refused, and which picks the waiting
 * answers hold; `App.svelte` renders one `UndoStrip` per still-pending entry.
 * A stored answer carries the written item, which `BoardStore.applyItem`
 * (`board.svelte.ts`) shows in place; `reload` re-reads only for `Neu laden`.
 */

import { SvelteMap, SvelteSet } from 'svelte/reactivity';
import { postDecision, postStep } from '../../client';
import type { BoardItem, DecisionRequest, OptionLine, StepRead, StepRequest } from '../../types';
import type { StripState } from '../model/boardSummary';
import { cardName, openPoints, pickedText, recommendedPicks, type Pick } from '../model/card';
import {
	BOARD_UNREACHABLE_MESSAGE,
	cardKey,
	cardOtherRequest,
	cardPicksRequest,
	cardUnclearRequest,
	entryKey,
	isStepRequest,
	pointKey,
	readDecisionResult,
	readStepResult,
	stepKey,
	stepRequest,
	UNDO_SECONDS,
	type DecisionOutcome
} from '../model/decision';
import { stepStripText } from '../model/steps';
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

/** A post the board did not store on a card the operator is not looking at. */
export interface UnseenFailure {
	key: string;
	name: string;
	message: string;
}

export interface PendingDecision {
	key: string;
	message: string;
	state: StripState;
}

interface PendingEntry {
	/** The card the post belongs to. */
	card: string;
	/** The line indexes the post names. */
	indexes: readonly number[];
	request: DecisionRequest | StepRequest;
	message: string;
	state: StripState;
	/** The name of what the post answers, for a failure strip that outlives the card being shown. */
	name: string;
	timer: ReturnType<typeof setTimeout>;
	/** The picks this answer posts: a pick's or Accept all's, none for an escape answer. */
	held: readonly Pick[];
	/** The panel `Undo` reopens, for an escape answer only. */
	reopens: { key: string; panel: EscapePanel } | null;
}

type NewEntry = Omit<PendingEntry, 'timer'>;

function draftKey(key: string, kind: EscapeKind): string {
	return `${kind}:${key}`;
}

function withoutKey<Value>(record: Record<string, Value>, key: string): Record<string, Value> {
	return Object.fromEntries(Object.entries(record).filter(([entry]) => entry !== key));
}

export class DecisionStore {
	#pending: Record<string, PendingEntry> = $state({});
	#banners: Record<string, DecisionBanner> = $state({});
	/** The posts whose window ended and whose POST has not been answered yet. */
	readonly #saving = new SvelteMap<string, PendingEntry>();
	/** The cards whose own `Neu laden` read after a refusal has not been answered yet. */
	readonly #reading = new SvelteSet<string>();
	/** The key this store itself just wrote a ruling for, its item applied --
	 * `App.svelte` moves the stage off it (`boardSummary.stageAfterRuled`) when
	 * it is still the one shown, then acknowledges it, never for a manual
	 * reload after a refusal banner. */
	#justRuled: string | null = $state(null);
	/** The key this store itself just sent back to its head, reported once
	 * (`acknowledgeReturned`) so selecting the card later never moves the stage. */
	#justReturned: string | null = $state(null);
	/** The word an answer came with (ABRD-129), per card key, kept for the session
	 * because a later read lists the ruled item without it. */
	#notes: Record<string, string> = $state({});
	/** The text typed per panel key and escape kind, kept until its decision is stored. */
	#drafts: Record<string, string> = $state({});
	/** The open escape panel per key (a point's for Other, the card's for Unclear),
	 * with the points as shown when it opened. */
	#panels: Record<string, EscapePanel> = $state({});
	/** The one open point per card, by line index; none until one is activated. */
	#openPoints: Record<string, number | null> = $state({});
	/** The card the stage shows, so a failure on any other card is told apart. */
	#shownKey: string | null = null;
	/** The cards whose refused or failed post came while another card was shown,
	 * until the card is shown or its banner goes. */
	readonly #unseen = new SvelteMap<string, UnseenFailure>();

	constructor(
		private readonly token: string,
		private readonly board: DecisionBoard,
		private readonly send: typeof postDecision = postDecision,
		private readonly undoSeconds: number = UNDO_SECONDS,
		private readonly sendStep: typeof postStep = postStep
	) {}

	/** The option answers in their window; a step answer shows in its own card (`pendingStep`). */
	get pendingEntries(): PendingDecision[] {
		return Object.entries(this.#pending)
			.filter(([, entry]) => !isStepRequest(entry.request))
			.map(([key, entry]) => ({ key, message: entry.message, state: entry.state }));
	}

	/** The step answer in its undo window under `card`, or null. */
	pendingStep(card: string): PendingDecision | null {
		const key = entryKey(card, []);
		const entry = this.#pending[key];
		return entry === undefined ? null : { key, message: entry.message, state: entry.state };
	}

	#entriesOf(card: string): PendingEntry[] {
		return [...Object.values(this.#pending), ...this.#saving.values()].filter(
			(entry) => entry.card === card
		);
	}

	/** The line indexes of the card's points that wait: in their undo window or saving. */
	waitingIndexes(card: string): ReadonlySet<number> {
		return new SvelteSet(this.#entriesOf(card).flatMap((entry) => entry.indexes));
	}

	/** Whether the card's own `Neu laden` read after a refusal is still running. */
	isReading(card: string): boolean {
		return this.#reading.has(card);
	}

	/** Whether any post of the card's window ended and its POST has not been answered yet. */
	isSaving(card: string): boolean {
		return [...this.#saving.values()].some((entry) => entry.card === card);
	}

	/** The picks the card's waiting answers hold, or null while no point of it waits. */
	held(card: string): readonly Pick[] | null {
		const entries = this.#entriesOf(card);
		return entries.length === 0 ? null : entries.flatMap((entry) => entry.held);
	}

	banner(key: string): DecisionBanner | null {
		return this.#banners[key] ?? null;
	}

	/** The refused or failed posts of cards not shown, each naming its card. */
	get unseenFailures(): UnseenFailure[] {
		return [...this.#unseen.values()];
	}

	/** The card the stage now shows; its failure strip goes, its own banner stays. */
	showCard(key: string | null): void {
		this.#shownKey = key;
		if (key !== null) {
			this.#unseen.delete(key);
		}
	}

	get justRuled(): string | null {
		return this.#justRuled;
	}

	acknowledgeRuled(): void {
		this.#justRuled = null;
	}

	get justReturned(): string | null {
		return this.#justReturned;
	}

	/** The note the card's stored answer came with, or null. */
	note(key: string): string | null {
		return this.#notes[key] ?? null;
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

	/** The open escape panel under `key` and the points it snapshotted, or null while closed. */
	panel(key: string): EscapePanel | null {
		return this.#panels[key] ?? null;
	}

	openPanel(key: string, panel: EscapePanel): void {
		this.#panels = { ...this.#panels, [key]: panel };
	}

	closePanel(key: string): void {
		this.#panels = withoutKey(this.#panels, key);
	}

	/** The line index of the card's open point, or null while none is open. */
	openPoint(key: string): number | null {
		return this.#openPoints[key] ?? null;
	}

	/** Activating a point opens its detail and closes any other; activating it again closes it. */
	togglePoint(key: string, index: number): void {
		this.#openPoints = { ...this.#openPoints, [key]: nextOpen(this.openPoint(key), index) };
	}

	/** A pick answers its point alone: its window starts at once. */
	choose(repo: string, item: number, points: readonly OptionLine[], pick: Pick): void {
		this.#startPicks(repo, item, points, [pick]);
	}

	/** Each point not waiting picks its recommended option, in one window; a point
	 * whose recommendation names no option stays open. */
	acceptAll(repo: string, item: number, points: readonly OptionLine[]): void {
		const waiting = this.waitingIndexes(cardKey(repo, item));
		const picks = recommendedPicks(points.filter((point) => !waiting.has(point.index)));
		if (picks.length > 0) {
			this.#startPicks(repo, item, points, picks);
		}
	}

	#startPicks(repo: string, item: number, points: readonly OptionLine[], picks: Pick[]): void {
		this.#startUndoWindow({
			card: cardKey(repo, item),
			indexes: picks.map((pick) => pick.shown.index),
			request: cardPicksRequest(repo, item, picks),
			message: pickedText(points, picks),
			state: 'done',
			name: cardName(points),
			held: picks,
			reopens: null
		});
	}

	/** The same window for the operator's own answer to one point; its panel
	 * closes and its draft stays. */
	decideOther(repo: string, item: number, point: OptionLine, answer: string): void {
		const key = pointKey(repo, item, point.index);
		this.closePanel(key);
		this.#startUndoWindow({
			card: cardKey(repo, item),
			indexes: [point.index],
			request: cardOtherRequest(repo, item, [point], answer),
			message: pendingOtherText(point.topic),
			state: 'done',
			name: point.topic,
			held: [],
			reopens: { key, panel: { kind: 'other', shown: [point] } }
		});
	}

	/** The same window for sending the points not waiting back to their head; the
	 * note may be blank, and nothing starts while every point waits. */
	decideUnclear(repo: string, item: number, shown: readonly OptionLine[], note: string): void {
		const card = cardKey(repo, item);
		this.closePanel(card);
		const waiting = this.waitingIndexes(card);
		const covered = shown.filter((point) => !waiting.has(point.index));
		if (covered.length === 0) {
			return;
		}
		this.#startUndoWindow({
			card,
			indexes: covered.map((point) => point.index),
			request: cardUnclearRequest(repo, item, covered, note),
			message: cardName(covered),
			state: 'back',
			name: cardName(covered),
			held: [],
			reopens: { key: card, panel: { kind: 'unclear', shown } }
		});
	}

	/** The same window for the operator's answer to one step as listed; its post is `POST /api/step`. */
	answerStep(repo: string, step: StepRead, result: StepRequest['result'], text: string): void {
		this.#startUndoWindow({
			card: stepKey(repo, step.number),
			indexes: [],
			request: stepRequest(repo, step, result, text),
			message: stepStripText(result, step.number),
			state: 'done',
			name: step.title,
			held: [],
			reopens: null
		});
	}

	#startUndoWindow(init: NewEntry): void {
		this.#clearBanner(init.card);
		const key = entryKey(init.card, init.indexes);
		const entry: PendingEntry = {
			...init,
			timer: setTimeout(() => void this.#commit(key, entry), this.undoSeconds * 1000)
		};
		this.#pending = { ...this.#pending, [key]: entry };
	}

	/** Posts every answer in its undo window at once, each as its own write, and
	 * ends those windows. Runs synchronously so the requests start before the
	 * page is gone; a second call finds nothing to post. */
	flush(): void {
		for (const [key, entry] of Object.entries(this.#pending)) {
			clearTimeout(entry.timer);
			void this.#commit(key, entry);
		}
	}

	/** Cancels a still-pending answer; a no-op once it already wrote or was undone.
	 * Undoing an escape answer reopens its panel. */
	undo(key: string): void {
		const entry = this.#pending[key];
		if (entry === undefined) {
			return;
		}
		clearTimeout(entry.timer);
		this.#pending = withoutKey(this.#pending, key);
		if (entry.reopens !== null) {
			this.openPanel(entry.reopens.key, entry.reopens.panel);
		}
	}

	/** The operator's own "Neu laden" after a refusal: drop it and re-read.
	 * This card alone is disabled until the read answers, however it ends. */
	async reloadAfterBanner(key: string): Promise<void> {
		this.#clearBanner(key);
		this.#reading.add(key);
		try {
			await this.board.reload();
		} finally {
			this.#reading.delete(key);
		}
	}

	async #post(request: DecisionRequest | StepRequest): Promise<DecisionOutcome> {
		return isStepRequest(request)
			? readStepResult(await this.sendStep(this.token, request))
			: readDecisionResult(await this.send(this.token, request));
	}

	async #commit(key: string, entry: PendingEntry): Promise<void> {
		const { card, request, name } = entry;
		this.#pending = withoutKey(this.#pending, key);
		this.#saving.set(key, entry);
		let outcome: DecisionOutcome;
		try {
			outcome = await this.#post(request);
		} catch {
			outcome = { kind: 'failed', message: BOARD_UNREACHABLE_MESSAGE };
		}
		if (outcome.kind === 'answered') {
			// The answered step leaves with the re-read; until then its card stays saving.
			await this.board.reload();
		}
		// One synchronous step: the post stops saving as its answer is applied.
		this.#saving.delete(key);
		if (outcome.kind === 'ruled') {
			this.#dropStoredDrafts(entry, outcome.item);
			if (outcome.note !== undefined) {
				this.#notes = { ...this.#notes, [card]: outcome.note };
			}
			this.board.applyItem(request.repo, outcome.item);
			this.#justRuled = card;
		} else if (outcome.kind === 'returned') {
			this.#dropDraft(card, 'unclear');
			this.board.applyItem(request.repo, outcome.item);
			this.#justReturned = card;
		} else if (outcome.kind !== 'answered') {
			this.#banners = { ...this.#banners, [card]: outcome };
			if (isStepRequest(request) || card === this.#shownKey) {
				this.#unseen.delete(card);
			} else {
				this.#unseen.set(card, { key: card, name, message: outcome.message });
			}
		}
	}

	#clearBanner(key: string): void {
		this.#banners = withoutKey(this.#banners, key);
		this.#unseen.delete(key);
	}

	/** A stored post drops the Other drafts of its points, and the card's Unclear
	 * draft once no point is open. */
	#dropStoredDrafts({ card, indexes, request }: PendingEntry, stored: BoardItem): void {
		for (const index of indexes) {
			this.#dropDraft(pointKey(request.repo, request.item, index), 'other');
		}
		if (openPoints(stored).length === 0) {
			this.#dropDraft(card, 'unclear');
		}
	}

	#dropDraft(key: string, kind: EscapeKind): void {
		this.#drafts = withoutKey(this.#drafts, draftKey(key, kind));
	}
}
