/**
 * The board's runtime state: what `App.svelte` reads to choose which of its
 * four states (no access, loading, unavailable, ready) to show.
 */

import { untrack } from 'svelte';
import { BoardApiError, fetchBoard } from '../../client';
import type { RepoReading } from '../../types';

export type BoardStatus = 'no-access' | 'loading' | 'unavailable' | 'ready';

export class BoardStore {
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
		try {
			const board = await fetchBoard(token, fetchImpl);
			this.repos = board.repos;
			this.status = 'ready';
		} catch (error) {
			this.repos = [];
			this.error = error instanceof BoardApiError ? error.message : 'network error';
			this.status = 'unavailable';
		} finally {
			this.refreshing = false;
		}
	}
}
