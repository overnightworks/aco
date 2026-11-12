import type { Page } from '@playwright/test';
import { expect, test } from './consoleGuard';
import { readBoardRuntime } from './runtime';
import { cardOption, item, optionLine, repo } from '../src/test-support/board';

const BOARD = {
	repos: [
		repo({
			name: 'songmaker',
			items: [
				item({
					number: 42,
					title: 'Song-Seite',
					lines: [
						optionLine({
							question: 'Soll der Song beim Sprung offen bleiben?',
							options: [cardOption({ letter: 'A', name: 'Song bleibt offen' })]
						})
					]
				})
			]
		})
	]
};

async function openBoard(page: Page) {
	const { appUrl, token } = readBoardRuntime();
	await page.route('**/api/board', (route) => route.fulfill({ json: BOARD }));
	await page.goto(`${appUrl}#t=${token}`);
	await expect(page.getByRole('navigation').getByRole('button').first()).toBeVisible();
	return new URL(appUrl).origin;
}

/** The family the browser really painted with: the first one of the element's font stack. */
function firstFamily(page: Page, selector: string) {
	return page
		.locator(selector)
		.first()
		.evaluate((element) =>
			getComputedStyle(element).fontFamily.split(',')[0].replaceAll(/["']/g, '')
		);
}

for (const scheme of ['light', 'dark'] as const) {
	for (const width of [390, 1280]) {
		test.describe(`the device set to ${scheme} at ${width} px`, () => {
			test.use({ colorScheme: scheme, viewport: { width, height: 800 } });

			test('the house fonts load from the board and no request leaves its origin', async ({
				page
			}) => {
				const requestedOrigins = new Set<string>();
				page.on('request', (request) => requestedOrigins.add(new URL(request.url()).origin));

				const boardOrigin = await openBoard(page);
				await page.evaluate(() => document.fonts.ready);

				expect(await firstFamily(page, 'body')).toBe('Open Sans');
				expect(await firstFamily(page, 'nav button')).toBe('Oswald');
				expect(
					await page.evaluate(() => [
						document.fonts.check("15px 'Open Sans'"),
						document.fonts.check("15px 'Oswald'")
					])
				).toEqual([true, true]);
				expect([...requestedOrigins].filter((origin) => origin !== boardOrigin)).toEqual([]);
			});
		});
	}
}
