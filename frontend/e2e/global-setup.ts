/**
 * The E2E launcher: starts the real board server
 * (`tests/aco_board/e2e_server.py`, the real `aco.board.server` behind a
 * fake `aco`) and points every spec straight at the port it prints -- it
 * serves the committed, built SPA itself, so no dev server and no proxy are
 * involved. Returning a teardown closure -- Playwright's own pattern --
 * needs no separate `global-teardown.ts`.
 */

import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import { writeFileSync } from 'node:fs';
import path from 'node:path';
import readline from 'node:readline';
import { RUNTIME_FILE } from './runtime';

const REPO_ROOT = path.resolve(import.meta.dirname, '../..');

interface BoardReady {
	host: string;
	port: number;
	token: string;
	repo_directory: string;
}

function startBoardServer(): Promise<{
	process: ChildProcessWithoutNullStreams;
	ready: BoardReady;
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
			resolve({ process: child, ready: JSON.parse(readyLine) as BoardReady });
		});
	});
}

export default async function globalSetup(): Promise<() => Promise<void>> {
	const { process: boardProcess, ready } = await startBoardServer();
	const appUrl = `http://${ready.host}:${ready.port}/`;

	writeFileSync(
		RUNTIME_FILE,
		JSON.stringify({ appUrl, token: ready.token, repoDirectory: ready.repo_directory })
	);

	return async () => {
		boardProcess.kill('SIGTERM');
		await new Promise((resolveExit) => boardProcess.once('exit', resolveExit));
	};
}
