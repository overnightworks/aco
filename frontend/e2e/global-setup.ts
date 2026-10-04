/**
 * The E2E launcher: starts the fake board server
 * (`tests/aco_board/e2e_server.py`, the real `aco_board.server` behind a
 * fake `aco`), then a Vite dev server whose `/api` proxy targets it
 * (`frontend/vite.config.ts`'s `VITE_BOARD_API_TARGET`). Returning a
 * teardown closure -- Playwright's own pattern -- needs no separate
 * `global-teardown.ts`: both processes are already in scope here.
 */

import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import { writeFileSync } from 'node:fs';
import path from 'node:path';
import readline from 'node:readline';
import { createServer, type ViteDevServer } from 'vite';
import { RUNTIME_FILE } from './runtime';

const REPO_ROOT = path.resolve(import.meta.dirname, '../..');
const FRONTEND_ROOT = path.resolve(import.meta.dirname, '..');

interface FakeBoardReady {
	host: string;
	port: number;
	token: string;
	repo_directory: string;
}

function startFakeBoardServer(): Promise<{
	process: ChildProcessWithoutNullStreams;
	ready: FakeBoardReady;
}> {
	return new Promise((resolve, reject) => {
		const child = spawn('uv', ['run', 'python', 'tests/aco_board/e2e_server.py'], {
			cwd: REPO_ROOT
		});
		let stderr = '';
		child.stderr.on('data', (chunk: Buffer) => {
			stderr += chunk.toString();
		});
		child.once('error', reject);
		child.once('exit', (code) => {
			if (code !== null && code !== 0) {
				reject(new Error(`tests/aco_board/e2e_server.py exited ${code}: ${stderr}`));
			}
		});
		const lines = readline.createInterface({ input: child.stdout });
		lines.once('line', (readyLine) => {
			resolve({ process: child, ready: JSON.parse(readyLine) as FakeBoardReady });
		});
	});
}

function resolvedAppUrl(vite: ViteDevServer): string {
	const url = vite.resolvedUrls?.local[0];
	if (url === undefined) {
		throw new Error('the dev server did not report a local listening URL');
	}
	return url;
}

export default async function globalSetup(): Promise<() => Promise<void>> {
	const { process: boardProcess, ready } = await startFakeBoardServer();

	process.env.VITE_BOARD_API_TARGET = `http://${ready.host}:${ready.port}`;
	const vite = await createServer({
		configFile: path.join(FRONTEND_ROOT, 'vite.config.ts'),
		root: FRONTEND_ROOT,
		server: { host: '127.0.0.1', port: 0, strictPort: false }
	});
	await vite.listen();
	const appUrl = resolvedAppUrl(vite);

	writeFileSync(
		RUNTIME_FILE,
		JSON.stringify({ appUrl, token: ready.token, repoDirectory: ready.repo_directory })
	);

	return async () => {
		await vite.close();
		boardProcess.kill('SIGTERM');
		await new Promise((resolveExit) => boardProcess.once('exit', resolveExit));
	};
}
