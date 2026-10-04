/**
 * Hands the server details `global-setup.ts` discovered across to the
 * worker process each spec file runs in. A file at a fixed path is the
 * simplest channel that survives Playwright forking workers after setup.
 */

import { readFileSync } from 'node:fs';
import path from 'node:path';

export interface BoardRuntime {
	/** The real board server's own origin, no path or fragment. */
	appUrl: string;
	/** The fake board's access token, as it belongs in a `#t=` fragment. */
	token: string;
	/** The fake `aco` repository's directory, for toggling its answers. */
	repoDirectory: string;
}

export const RUNTIME_FILE = path.join(import.meta.dirname, '.runtime.json');

export function readBoardRuntime(): BoardRuntime {
	return JSON.parse(readFileSync(RUNTIME_FILE, 'utf-8')) as BoardRuntime;
}
