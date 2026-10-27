import type { Locator, Page } from '@playwright/test';
import { expect, test } from './consoleGuard';
import { readBoardRuntime } from './runtime';
import { cardOption, item, line, optionLine, repo } from '../src/test-support/board';

const SENTENCE = 'Der Song bleibt beim Sprung offen und die App merkt sich die Stelle im Gespräch.';
const LONG_TEXT = Array.from({ length: 14 }, () => SENTENCE).join(' ');

// Four options with long contracts: the card runs on well beyond the pane once one is open.
const TALL_CARD = optionLine({
	topic: 'Sprung',
	question: 'Soll der Song beim Sprung offen bleiben?',
	problem: LONG_TEXT,
	options: ['A', 'B', 'C', 'D'].map((letter) =>
		cardOption({
			letter: letter as 'A',
			name: `Weg ${letter}`,
			effect: LONG_TEXT,
			notice: LONG_TEXT,
			cost: LONG_TEXT,
			contract: LONG_TEXT
		})
	)
});

const BOARD = {
	repos: [
		repo({
			name: 'songmaker',
			items: [
				item({
					number: 42,
					title: 'Song-Seite',
					lines: [
						TALL_CARD,
						line({ index: 2, text: 'Gäste einladen?' }),
						line({ index: 3, text: 'Gespräch beenden?', ruling: 'yes', ruled_on: '2026-10-01' })
					]
				})
			]
		}),
		repo({ name: 'quiet', items: [] })
	]
};

async function openBoard(page: Page) {
	const { appUrl, token } = readBoardRuntime();
	await page.route('**/api/board', (route) => route.fulfill({ json: BOARD }));
	await page.goto(`${appUrl}#t=${token}`);
	await expect(page.getByRole('navigation', { name: 'Views' })).toBeVisible();
}

async function openTheCard(page: Page, isPhone: boolean) {
	if (isPhone) await page.locator('.tracks').getByRole('button').first().click();
	await expect(page.locator('.option-card')).toBeVisible();
}

async function screenshots(page: Page, outputPath: (name: string) => string, name: string) {
	await page.screenshot({ path: outputPath(`${name}.png`) });
	await page.locator('body').evaluate((body) => {
		body.style.filter = 'blur(4px) grayscale(1)';
	});
	await page.screenshot({ path: outputPath(`${name}-blurred.png`) });
	await page.locator('body').evaluate((body) => {
		body.style.filter = '';
	});
}

async function height(locator: Locator) {
	return (await locator.boundingBox())?.height;
}

async function top(locator: Locator) {
	return (await locator.boundingBox())?.y ?? 0;
}

async function bottom(locator: Locator) {
	const box = await locator.boundingBox();
	return (box?.y ?? 0) + (box?.height ?? 0);
}

for (const viewport of [
	{ width: 1280, height: 900 },
	{ width: 390, height: 844 }
]) {
	const isPhone = viewport.width < 760;
	test.describe(`${viewport.width}px page frame`, () => {
		test.use({ viewport });

		test('[ABRD-51] the header holds the brand and the Open and Decided tabs', async ({
			page
		}, testInfo) => {
			await openBoard(page);
			const brand = page.getByRole('heading', { level: 1 });
			const views = page.getByRole('navigation', { name: 'Views' });
			const open = views.getByRole('button', { name: 'Open 2' });
			const decided = views.getByRole('button', { name: 'Decided 1' });

			expect(await height(page.locator('header'))).toBe(isPhone ? 52 : 56);
			await expect(brand).toHaveCount(1);
			await expect(brand).toHaveText('Entscheidungs-Board');
			if (isPhone) {
				const box = await brand.boundingBox();
				expect(box?.width).toBeLessThanOrEqual(1);
				expect(box?.height).toBeLessThanOrEqual(1);
			} else await expect(brand).toBeVisible();
			await expect(views.getByRole('button')).toHaveCount(2);
			await expect(open).toHaveAttribute('aria-current', 'page');
			await expect(open).toHaveCSS('background-color', 'rgb(24, 21, 31)');
			await expect(page.getByRole('button', { name: /^(Agent|Mitsprache)/ })).toHaveCount(0);
			await screenshots(page, testInfo.outputPath.bind(testInfo), 'header-open');

			await decided.click();

			await expect(decided).toHaveAttribute('aria-current', 'page');
			await expect(page.getByRole('region', { name: 'Decided', exact: true })).toBeVisible();
			await screenshots(page, testInfo.outputPath.bind(testInfo), 'header-decided');
		});

		test('[ABRD-52] the Decide row rests on the pane foot with a shadow, then in place without one', async ({
			page
		}, testInfo) => {
			await openBoard(page);
			await openTheCard(page, isPhone);
			const pane = page.locator('.question-pane');
			const decideRow = page.locator('.decide-row');
			await page.locator('.option-card button[aria-expanded]').first().click();
			await pane.evaluate((element) => {
				element.scrollTop = 0;
			});
			expect(
				await pane.evaluate((element) => element.scrollHeight - element.clientHeight)
			).toBeGreaterThan(0);

			expect(Math.abs((await bottom(decideRow)) - (await bottom(pane)))).toBeLessThanOrEqual(1);
			await expect(decideRow).not.toHaveCSS('box-shadow', 'none');
			await screenshots(page, testInfo.outputPath.bind(testInfo), 'decide-row-stuck');

			await pane.evaluate((element) => {
				element.scrollTop = element.scrollHeight;
			});

			await expect(decideRow).toHaveCSS('box-shadow', 'none');
			expect((await bottom(pane)) - (await bottom(decideRow))).toBeGreaterThanOrEqual(16);
			await screenshots(page, testInfo.outputPath.bind(testInfo), 'decide-row-at-rest');
		});

		test('[ABRD-55] on phones an opened card stands edge to edge under ‹ Open or ‹ Decided, which returns to its list', async ({
			page
		}, testInfo) => {
			await openBoard(page);
			const views = page.getByRole('navigation', { name: 'Views' });
			const back = page.getByRole('button', { name: /^‹ (Open|Decided)$/ });
			const card = page.locator('.option-card article');
			const where = page.locator('.option-card .meta .where');
			const props = page.locator('.option-card .meta .props');

			if (!isPhone) {
				await openTheCard(page, false);
				await expect(back).toBeHidden();
				await expect(views).toBeVisible();
				await expect(card).toHaveCSS('border-top-width', '1px');
				expect(await top(props)).toBeLessThan(await bottom(where));
				return;
			}

			await expect(back).toHaveCount(0);
			await expect(views.getByRole('button')).toHaveCount(2);
			const row = page.locator('.tracks').getByRole('button').first();
			await row.click();
			await expect(page.getByRole('button', { name: '‹ Open', exact: true })).toBeVisible();
			await expect(views).toBeHidden();
			expect(await height(page.locator('header'))).toBe(52);
			await expect(card).toHaveCSS('border-top-width', '0px');
			await expect(card).toHaveCSS('padding-left', '0px');
			expect((await card.boundingBox())?.x).toBe(16);
			await expect(page.locator('.question-pane')).toHaveCSS(
				'background-color',
				'rgb(255, 255, 255)'
			);
			expect(await top(props)).toBeGreaterThanOrEqual(await bottom(where));
			expect(
				await page.evaluate(
					() => document.documentElement.scrollWidth <= document.documentElement.clientWidth
				)
			).toBe(true);
			await page.screenshot({ path: testInfo.outputPath('phone-card-open.png') });

			await page.getByRole('button', { name: '‹ Open', exact: true }).click();

			await expect(row).toBeFocused();
			await expect(row).toHaveAttribute('aria-current', 'true');
			await expect(views).toBeVisible();
			await expect(back).toHaveCount(0);

			await views.getByRole('button', { name: 'Decided 1' }).click();
			const decidedRow = page
				.getByRole('region', { name: 'Decided', exact: true })
				.getByRole('button')
				.first();
			await decidedRow.click();

			await expect(page.getByRole('button', { name: '‹ Decided', exact: true })).toBeVisible();
			await expect(views).toBeHidden();
			await expect(page.locator('.decided-card article')).toHaveCSS('border-top-width', '0px');
			await page.screenshot({ path: testInfo.outputPath('phone-card-decided.png') });

			await page.getByRole('button', { name: '‹ Decided', exact: true }).click();

			await expect(decidedRow).toBeFocused();
			await expect(views).toBeVisible();
		});

		if (!isPhone) {
			test('[ABRD-28] the list measures the picture: group 42 px, row 36 px, quiet line 38 px, text --fg on --bg', async ({
				page
			}) => {
				await openBoard(page);
				const tracks = page.locator('.tracks');

				expect(await height(tracks.locator('.group'))).toBe(42);
				expect(await height(tracks.getByRole('button').first())).toBe(36);
				expect(await height(tracks.locator('.quiet'))).toBe(38);
				await expect(tracks.locator('.label').first()).toHaveCSS('color', 'rgb(24, 21, 31)');
				await expect(page.locator('body')).toHaveCSS('background-color', 'rgb(246, 245, 248)');
			});
		}
	});
}
