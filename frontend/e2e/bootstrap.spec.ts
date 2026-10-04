import { rmSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { expect, test } from '@playwright/test';
import { readBoardRuntime } from './runtime';

const EMPTY_BOARD_MESSAGE =
	'Nichts offen. Neue Fragen erscheinen hier nach Neuladen, sobald ein Agent eine stellt.';

// One shared board server backs every test in this file (see
// global-setup.ts); a run toggling its fake `aco` must not race another.
test.describe.configure({ mode: 'serial' });

test('a fresh tab with no link shows access is missing', async ({ page }) => {
	const { appUrl } = readBoardRuntime();

	await page.goto(appUrl);

	await expect(page.getByRole('alert')).toContainText('Zugang fehlt');
});

test('the token bootstraps from the URL fragment, never reaches a request, and the fragment is gone before the app mounts', async ({
	page
}) => {
	const { appUrl, token } = readBoardRuntime();
	const requestedUrls: string[] = [];
	page.on('request', (request) => requestedUrls.push(request.url()));

	const boardRequest = page.waitForRequest((request) => request.url().endsWith('/api/board'));
	await page.goto(`${appUrl}#t=${token}`);
	const apiRequest = await boardRequest;

	await expect(page.getByText(EMPTY_BOARD_MESSAGE)).toBeVisible();
	await expect(page).toHaveURL(appUrl);
	expect(requestedUrls.some((url) => url.includes(token))).toBe(false);
	expect(apiRequest.headers()['x-board-token']).toBe(token);
});

test('aco being unreachable shows the unavailable state', async ({ page }) => {
	const { appUrl, token, repoDirectory } = readBoardRuntime();
	const failureFile = path.join(repoDirectory, 'rulings-failure.txt');
	writeFileSync(failureFile, 'ERROR: no forge adapter for host');

	try {
		await page.goto(`${appUrl}#t=${token}`);
		await expect(page.getByRole('alert')).toContainText('aco antwortet nicht');
	} finally {
		rmSync(failureFile);
	}
});
