/**
 * The board's runtime state: what `App.svelte` reads to choose which of its
 * four states (no access, loading, unavailable, ready) to show.
 */

import { untrack } from 'svelte';
import { BoardApiError, fetchBoard } from '../../client';
import type { BoardItem, RepoReading } from '../../types';

export type BoardStatus = 'no-access' | 'loading' | 'unavailable' | 'ready';

/** The item a stored answer carried, with the count of reads sent when it arrived. */
interface StoredAnswer {
	repo: string;
	item: BoardItem;
	after: number;
}

/** A read's rows for an item apply only if the read was sent after the item's
 * stored answer arrived (ABRD-98); otherwise the answer's item stands in its
 * place, appended when the read omits it. A repository showing an error keeps it. */
function withStoredAnswers(
	repos: RepoReading[],
	answers: StoredAnswer[],
	sent: number
): RepoReading[] {
	const standing = answers.filter(({ after }) => sent <= after);
	return repos.map((reading) => {
		const own = standing.filter(({ repo }) => repo === reading.name);
		if (reading.error !== null || own.length === 0) return reading;
		const replaced = reading.items.map(
			(item) => own.find((answer) => answer.item.number === item.number)?.item ?? item
		);
		const omitted = own
			.map(({ item }) => item)
			.filter(({ number }) => !reading.items.some((item) => item.number === number));
		return { ...reading, items: [...replaced, ...omitted] };
	});
}

export class BoardStore {
	#readsSent = 0;
	/** The number of the read that produced `repos`. */
	#readingSent = 0;
	#answers: Record<string, StoredAnswer> = {};

	status: BoardStatus = $state('no-access');
	repos: RepoReading[] = $state([]);
	error: string | null = $state(null);
	// True while a ready board is re-read: it stays shown, but what it says is
	// about to change, so its answer controls are unavailable.
	refreshing = $state(false);

	setNoAccess(): void {
		this.status = 'no-access';
		this.repos = [];
		this.error = null;
	}

	async load(token: string, fetchImpl: typeof fetch = fetch): Promise<void> {
		// A ready board stays on screen while it is re-read: replacing it with a
		// loading state would tear down what the person is working in, such as
		// an open confirmation.
		// Untracked: the caller's effect must not subscribe to the status it triggers.
		if (untrack(() => this.status) === 'ready') this.refreshing = true;
		else this.status = 'loading';
		this.error = null;
		const sent = ++this.#readsSent;
		try {
			const board = await fetchBoard(token, fetchImpl);
			this.#readingSent = sent;
			this.repos = withStoredAnswers(board.repos, Object.values(this.#answers), sent);
			this.status = 'ready';
		} catch (error) {
			this.repos = [];
			this.error = error instanceof BoardApiError ? error.message : 'network error';
			this.status = 'unavailable';
		} finally {
			this.refreshing = false;
		}
	}

	/** Shows the item a stored answer carried in place, without a read, and keeps
	 * it against any read sent before this answer arrived. */
	applyItem(repo: string, item: BoardItem): void {
		this.#answers[`${repo}:${item.number}`] = { repo, item, after: this.#readsSent };
		this.repos = withStoredAnswers(this.repos, Object.values(this.#answers), this.#readingSent);
	}
}
