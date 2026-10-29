import type { Locator, Page } from '@playwright/test';

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
