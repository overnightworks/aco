/**
 * The board's runtime state: what `App.svelte` reads to choose which of its
 * four states (no access, loading, unavailable, ready) to show.
 */

import { BoardApiError, fetchBoard } from '../../client';
import type { RepoReading } from '../../types';

export type BoardStatus = 'no-access' | 'loading' | 'unavailable' | 'ready';

export class BoardStore {
	status: BoardStatus = $state('no-access');
	repos: RepoReading[] = $state([]);
	error: string | null = $state(null);

	setNoAccess(): void {
		this.status = 'no-access';
		this.repos = [];
		this.error = null;
	}

	async load(token: string, fetchImpl: typeof fetch = fetch): Promise<void> {
		this.status = 'loading';
		this.error = null;
		try {
			const board = await fetchBoard(token, fetchImpl);
			this.repos = board.repos;
			this.status = 'ready';
		} catch (error) {
			this.repos = [];
			this.error = error instanceof BoardApiError ? error.message : 'network error';
			this.status = 'unavailable';
		}
	}
}
