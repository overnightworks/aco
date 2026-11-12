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

async function openBoardWithOpenCard(page: Page) {
	const { appUrl, token } = readBoardRuntime();
	await page.route('**/api/board', (route) => route.fulfill({ json: BOARD }));
	await page.goto(`${appUrl}#t=${token}`);
	await expect(page.locator('.option-card')).toBeVisible();
}

/** Relative luminance of the element's computed `property` colour, 0 (black) to 1 (white). */
async function luminance(page: Page, selector: string, property: 'color' | 'backgroundColor') {
	return page
		.locator(selector)
		.first()
		.evaluate((element, cssProperty) => {
			const channels = (getComputedStyle(element)[cssProperty].match(/[\d.]+/g) ?? [])
				.slice(0, 3)
				.map((channel) => {
					const value = Number(channel) / 255;
					return value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
				});
			return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
		}, property);
}

for (const scheme of ['light', 'dark'] as const) {
	test.describe(`the device set to ${scheme}`, () => {
		test.use({ colorScheme: scheme });

		test(`the page, the head and the decide row are ${scheme} with text of the other kind`, async ({
			page
		}) => {
			await openBoardWithOpenCard(page);

			const text = await luminance(page, 'body', 'color');
			const surfaces = await Promise.all(
				['body', 'header', '.decide-row'].map((selector) =>
					luminance(page, selector, 'backgroundColor')
				)
			);

			for (const surface of surfaces) {
				if (scheme === 'dark') expect(surface).toBeLessThan(text);
				else expect(surface).toBeGreaterThan(text);
			}
		});
	});
}
