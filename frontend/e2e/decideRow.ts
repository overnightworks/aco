import type { Locator, Page } from '@playwright/test';
import { TOKEN_HEADER } from '../src/client';
import { readBoardRuntime } from './runtime';

/** The Decide row's group of picks on the shown card. */
export function picks(page: Page): Locator {
	return page.getByRole('group', { name: 'Decide' });
}

/** The pick for `letter` in the Decide row. */
export function pick(page: Page, letter: 'A' | 'B'): Locator {
	return picks(page).getByRole('button', { name: new RegExp(`^Decide ${letter}:`) });
}

/** Counts every POST the page sends from now on; the board's only POST is a decision. */
export function countPosts(page: Page): { count(): number } {
	let posts = 0;
	page.on('request', (request) => {
		if (request.method() === 'POST') posts += 1;
	});
	return { count: () => posts };
}

/** Counts every `GET /api/board` the page sends from now on. */
export function countBoardReads(page: Page): { count(): number } {
	let reads = 0;
	page.on('request', (request) => {
		if (request.method() === 'GET' && request.url().endsWith('/api/board')) reads += 1;
	});
	return { count: () => reads };
}

/** The name the board server gives the one repository it serves. */
export async function servedRepository(): Promise<string> {
	const { appUrl, token } = readBoardRuntime();
	const response = await fetch(`${appUrl}/api/board`, { headers: { [TOKEN_HEADER]: token } });
	return ((await response.json()) as { repos: { name: string }[] }).repos[0].name;
}

/** Rewrites every `GET /api/board` to the served repository's reading under each of `names`.
 * `failing` names, by the number of the read (0 for the first), the repositories whose read
 * fails and the sentence each carries; they arrive with no items. */
export async function routeRepositories(
	page: Page,
	names: string[],
	failing: (read: number) => Record<string, string> = () => ({})
): Promise<void> {
	let reads = 0;
	await page.route('**/api/board', async (route) => {
		const failed = failing(reads++);
		const response = await route.fetch();
		const board = await response.json();
		await route.fulfill({
			json: {
				repos: names.map((name) =>
					name in failed ? { name, error: failed[name], items: [] } : { ...board.repos[0], name }
				)
			}
		});
	});
}
