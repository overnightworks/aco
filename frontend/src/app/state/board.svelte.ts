/**
 * The board's runtime state: what `App.svelte` reads to choose which of its
 * four states (no access, loading, unavailable, ready) to show.
 */

import { untrack } from 'svelte';
import { SvelteDate } from 'svelte/reactivity';
import { BoardApiError, fetchBoard } from '../../client';
import type { BoardItem, RepoReading } from '../../types';
import { SERVER_SILENT_SENTENCE, type ShownRepo } from '../model/boardSummary';

export type BoardStatus = 'no-access' | 'loading' | 'unavailable' | 'ready';

/** The item a stored answer carried, with the count of reads sent when it arrived. */
interface StoredAnswer {
	repo: string;
	item: BoardItem;
	after: number;
}

/** An item the page keeps as shown against a read. */
interface StandingItem {
	repo: string;
	item: BoardItem;
}

/** Whether the card of `item` waits for its answer, so a read must leave it as shown. */
export type WaitsPredicate = (repo: string, item: BoardItem) => boolean;

/** The items a read may not replace: a stored answer's item, when the read was
 * sent before the answer arrived (ABRD-98). */
function storedItems(answers: StoredAnswer[], sent: number): StandingItem[] {
	return answers.filter(({ after }) => sent <= after).map(({ repo, item }) => ({ repo, item }));
}

/** Those, and the items of cards that wait, as shown (ABRD-105); a waiting
 * card's item is the newer of the two. */
function standingItems(
	current: ShownRepo[],
	answers: StoredAnswer[],
	sent: number,
	waits: WaitsPredicate
): StandingItem[] {
	const waiting = current.flatMap((reading) =>
		reading.items
			.filter((item) => waits(reading.name, item))
			.map((item) => ({ repo: reading.name, item }))
	);
	const answered = storedItems(answers, sent).filter(
		(stored) =>
			!waiting.some(({ repo, item }) => repo === stored.repo && item.number === stored.item.number)
	);
	return [...answered, ...waiting];
}

/** A read's rows for an item that stands apply only as the standing item
 * allows: it takes the item's place, appended when the read omits it. */
function withStandingItems(repos: ShownRepo[], standing: StandingItem[]): ShownRepo[] {
	return repos.map((reading) => {
		const own = standing.filter(({ repo }) => repo === reading.name);
		if (own.length === 0) return reading;
		const replaced = reading.items.map(
			(item) => own.find((kept) => kept.item.number === item.number)?.item ?? item
		);
		const omitted = own
			.map(({ item }) => item)
			.filter(({ number }) => !reading.items.some((item) => item.number === number));
		return { ...reading, items: [...replaced, ...omitted] };
	});
}

/** The page's reading of a read's answer: a repository that read takes the
 * arrival time; one that failed keeps the items and time of its last reading. */
function shownRepos(answered: RepoReading[], current: ShownRepo[], arrived: Date): ShownRepo[] {
	return answered.map((reading) => {
		if (reading.error === null) return { ...reading, readAt: arrived };
		const kept = current.find(({ name }) => name === reading.name);
		return { ...reading, items: kept?.items ?? [], readAt: kept?.readAt ?? null };
	});
}

interface ReadRequest {
	token: string;
	fetchImpl: typeof fetch;
}

/** The one read that waits for the running one; later callers join it and the
 * last caller's request is the one it sends. */
interface QueuedRead {
	request: ReadRequest;
	done: Promise<void>;
}

export class BoardStore {
	#readsSent = 0;
	/** The number of the read that produced `repos`. */
	#readingSent = 0;
	#answers: Record<string, StoredAnswer> = {};
	#running: Promise<void> | null = null;
	#queued: QueuedRead | null = null;

	status: BoardStatus = $state('no-access');
	repos: ShownRepo[] = $state([]);
	error: string | null = $state(null);
	/** Whether a read runs or waits for the running one. */
	reading = $state(false);

	constructor(private readonly waits: WaitsPredicate = () => false) {}

	setNoAccess(): void {
		// A read still in flight answers a token that is gone: it is older than
		// the reading now shown, and so ignored.
		this.#readingSent = this.#readsSent;
		this.#running = null;
		this.#queued = null;
		this.reading = false;
		this.status = 'no-access';
		this.repos = [];
		this.error = null;
	}

	/** Reads the board, one read at a time: a call during a read settles with the
	 * one read that starts after it, however many calls wait. */
	load(token: string, fetchImpl: typeof fetch = fetch): Promise<void> {
		const request = { token, fetchImpl };
		if (this.#running === null) return this.#start(request);
		this.#queued ??= this.#queue(this.#running, request);
		this.#queued.request = request;
		return this.#queued.done;
	}

	#queue(after: Promise<void>, request: ReadRequest): QueuedRead {
		const queued: QueuedRead = { request, done: Promise.resolve() };
		queued.done = after.then(() => {
			// Cleared by `setNoAccess`: the token went, so this settles without reading.
			if (this.#queued !== queued) return;
			this.#queued = null;
			return this.#start(queued.request);
		});
		return queued;
	}

	#start(request: ReadRequest): Promise<void> {
		this.reading = true;
		const run: Promise<void> = this.#read(request).finally(() => {
			if (this.#running !== run) return;
			this.#running = null;
			this.reading = this.#queued !== null;
		});
		this.#running = run;
		return run;
	}

	async #read({ token, fetchImpl }: ReadRequest): Promise<void> {
		// A ready board stays on screen while it is re-read: replacing it with a
		// loading state would tear down what the person is working in, such as
		// an open confirmation.
		// Untracked: the caller's effect must not subscribe to the status it triggers.
		const wasReady = untrack(() => this.status) === 'ready';
		if (!wasReady) this.status = 'loading';
		this.error = null;
		const sent = ++this.#readsSent;
		try {
			const board = await fetchBoard(token, fetchImpl);
			if (sent <= this.#readingSent) return;
			this.#readingSent = sent;
			const shown = shownRepos(board.repos, this.repos, new SvelteDate(Date.now()));
			const standing = standingItems(this.repos, Object.values(this.#answers), sent, this.waits);
			this.repos = withStandingItems(shown, standing);
			this.status = 'ready';
		} catch (error) {
			if (sent <= this.#readingSent) return;
			if (wasReady) {
				this.repos = this.repos.map((reading) => ({ ...reading, error: SERVER_SILENT_SENTENCE }));
				return;
			}
			this.repos = [];
			this.error = error instanceof BoardApiError ? error.message : 'network error';
			this.status = 'unavailable';
		}
	}

	/** Shows the item a stored answer carried in place, without a read, and keeps
	 * it against any read sent before this answer arrived. */
	applyItem(repo: string, item: BoardItem): void {
		this.#answers[`${repo}:${item.number}`] = { repo, item, after: this.#readsSent };
		this.repos = withStandingItems(
			this.repos,
			storedItems(Object.values(this.#answers), this.#readingSent)
		);
	}
}
