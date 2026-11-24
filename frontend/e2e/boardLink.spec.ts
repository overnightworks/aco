import type { Page } from '@playwright/test';
import { expect, test } from './consoleGuard';
import { readBoardRuntime } from './runtime';
import { item, line, optionLine, repo, stepRead } from '../src/test-support/board';

const BOARD = {
	repos: [
		repo({
			name: 'acme/songmaker',
			items: [
				item({
					number: 42,
					title: 'Song-Seite',
					lines: [
						optionLine({ index: 1, question: 'Soll der Song offen bleiben?', topic: 'Sprung' }),
						line({ index: 3, text: 'Gespräch beenden?', ruling: 'yes', ruled_on: '2026-10-01' })
					]
				}),
				item({
					number: 43,
					title: 'Gäste',
					lines: [optionLine({ index: 1, question: 'Gäste einladen?', topic: 'Gäste' })]
				})
			],
			steps: [stepRead({ number: 44, title: 'Release the build' })]
		})
	]
};

async function openLink(page: Page, selection: string) {
	const { appUrl, token } = readBoardRuntime();
	await page.route('**/api/board', (route) => route.fulfill({ json: BOARD }));
	await page.goto(`${appUrl}#t=${token}&${selection}`);
}

for (const viewport of [
	{ width: 1280, height: 900 },
	{ width: 390, height: 844 }
]) {
	test.describe(`${viewport.width}px board link`, () => {
		test.use({ viewport });

		test('ABRD-188: a card link opens that card, and the address bar holds no fragment', async ({
			page
		}, testInfo) => {
			await openLink(page, 'c=acme/songmaker/43/1');

			await expect(page.locator('.option-card')).toContainText('Gäste einladen?');
			await expect(page.getByRole('status')).toHaveCount(0);
			expect(await page.evaluate(() => window.location.hash)).toBe('');
			await page.screenshot({ path: testInfo.outputPath(`card-${viewport.width}.png`) });
		});

		test('ABRD-189: a step link opens the Steps view with that step marked', async ({
			page
		}, testInfo) => {
			await openLink(page, 's=acme/songmaker/44');

			await expect(page.getByRole('article', { name: /Release the build/ })).toHaveAttribute(
				'aria-current',
				'true'
			);
			await expect(
				page.getByRole('navigation', { name: 'Views' }).getByRole('button', { name: /^Steps/ })
			).toHaveAttribute('aria-current', 'page');
			await page.screenshot({ path: testInfo.outputPath(`step-${viewport.width}.png`) });
		});

		for (const [name, selection, note] of [
			['a ruled card', 'c=acme/songmaker/42/3', 'Diese Karte ist schon entschieden.'],
			['an unknown card', 'c=acme/songmaker/99/1', 'Diese Karte gibt es nicht mehr.']
		]) {
			test(`ABRD-191: ${name} shows one line over the open list`, async ({ page }, testInfo) => {
				await openLink(page, selection);

				await expect(page.getByRole('status')).toHaveText(note);
				await expect(page.locator('.tracks')).toContainText('Sprung');
				await page.screenshot({
					path: testInfo.outputPath(`note-${viewport.width}.png`)
				});
			});
		}

		test('ABRD-192: a step no longer waiting shows one line over the open list', async ({
			page
		}) => {
			await openLink(page, 's=acme/songmaker/43');

			await expect(page.getByRole('status')).toHaveText('Dieser Schritt wartet nicht mehr.');
			await expect(page.locator('.tracks')).toContainText('Gäste');
		});
	});
}
