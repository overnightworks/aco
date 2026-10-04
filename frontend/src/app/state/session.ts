/**
 * Carries the access token from the URL fragment into this tab's session
 * storage, then strips the fragment -- before anything else runs, so the
 * token never sits in browser history, a referrer, or a later log
 * (`specs/aco-board.spec.md` ABRD-10; issue #617 line 3).
 *
 * A reload in the same tab carries no fragment any more, so a missing hash
 * falls back to whatever this tab already stored; a tab that never saw the
 * link has neither and reads as "no access".
 */

import { tokenFromHash } from '../model/token';

export const TOKEN_STORAGE_KEY = 'aco-board-token';

export interface BootstrapEnvironment {
	hash: string;
	pathWithSearch: string;
	storage: Storage;
	replaceState: (path: string) => void;
}

export function bootstrapToken(env: BootstrapEnvironment): string | null {
	const fromHash = tokenFromHash(env.hash);
	if (fromHash === null) {
		return env.storage.getItem(TOKEN_STORAGE_KEY);
	}
	env.storage.setItem(TOKEN_STORAGE_KEY, fromHash);
	env.replaceState(env.pathWithSearch);
	return fromHash;
}

export function windowBootstrapEnvironment(target: Window): BootstrapEnvironment {
	return {
		hash: target.location.hash,
		pathWithSearch: target.location.pathname + target.location.search,
		storage: target.sessionStorage,
		replaceState: (path) => target.history.replaceState(null, '', path)
	};
}
