import type { Locator, Page } from '@playwright/test';
import { expect, test } from './consoleGuard';
import { readBoardRuntime } from './runtime';
import { item, line, optionLine, repo } from '../src/test-support/board';

const REPOSITORY = 'Songmaker-App';

const WAITING = {
	repos: [
		repo({
			name: REPOSITORY,
			items: [
				item({
					number: 42,
					title: 'Song-Seite',
					lines: [
						optionLine({ question: 'Soll der Song beim Sprung offen bleiben?', topic: 'Sprung' }),
						line({ index: 3, text: 'Gespräch beenden?', ruling: 'yes', ruled_on: '2026-10-01' })
					]
				}),
				item({
					number: 43,
					title: 'Gäste',
					lines: [
						optionLine({
							question: 'Sollen Gäste am Gespräch teilnehmen dürfen und wenn ja ab wann?'
						})
					]
				})
			]
		})
	]
};

const NOTHING_WAITING = {
	repos: [
		repo({
			name: REPOSITORY,
			items: [
				item({
					number: 42,
					title: 'Song-Seite',
					lines: [
						line({ index: 3, text: 'Gespräch beenden?', ruling: 'yes', ruled_on: '2026-10-01' })
					]
				})
			]
		})
	]
};

async function openBoard(page: Page, board: object) {
	const { appUrl, token } = readBoardRuntime();
	await page.route('**/api/board', (route) => route.fulfill({ json: board }));
	await page.goto(`${appUrl}#t=${token}`);
	await expect(page.getByRole('navigation', { name: 'Views' })).toBeVisible();
}

/** The computed colour a custom property resolves to, as the browser prints it. */
async function tokenColor(page: Page, token: string) {
	return page.evaluate((name) => {
		const probe = document.createElement('i');
		probe.style.color = `var(${name})`;
		document.body.append(probe);
		const resolved = getComputedStyle(probe).color;
		probe.remove();
		return resolved;
	}, token);
}

async function height(locator: Locator) {
	return (await locator.boundingBox())?.height;
}

for (const scheme of ['light', 'dark'] as const) {
	test.describe(`the list and the count badge, device set to ${scheme}`, () => {
		test.use({ colorScheme: scheme, viewport: { width: 1280, height: 900 } });

		test('[ABRD-125] the count of open decisions is an accent badge that goes quiet at zero', async ({
			page
		}) => {
			await openBoard(page, WAITING);
			const badge = page.getByRole('navigation', { name: 'Views' }).locator('.n').first();
			const accent = await tokenColor(page, '--accent');

			await expect(badge).toHaveText('2');
			await expect(badge).toHaveCSS('background-color', accent);

			await page.unroute('**/api/board');
			await page.route('**/api/board', (route) => route.fulfill({ json: NOTHING_WAITING }));
			await page.getByRole('button', { name: /^Refresh/ }).click();

			await expect(badge).toHaveText('0');
			await expect(badge).not.toHaveCSS('background-color', accent);
		});

		test('[ABRD-126] the selected row carries an accent bar on a light accent ground without hover, and rows share one height', async ({
			page
		}) => {
			await openBoard(page, WAITING);
			const rows = page.locator('.tracks .row');
			const selected = rows.first();
			const other = rows.nth(1);
			await page.mouse.move(0, 0);

			await expect(selected).toHaveAttribute('aria-current', 'true');
			await expect(selected).toHaveCSS('background-color', await tokenColor(page, '--accent-soft'));
			const accent = await tokenColor(page, '--accent');
			expect(await selected.evaluate((row) => getComputedStyle(row).boxShadow)).toContain(accent);
			await expect(other).not.toHaveCSS(
				'background-color',
				await tokenColor(page, '--accent-soft')
			);

			await other.hover();
			await expect(other).toHaveCSS('background-color', await tokenColor(page, '--surface-2'));
			await expect(selected).not.toHaveCSS(
				'background-color',
				await tokenColor(page, '--surface-2')
			);
			expect(await height(selected)).toBe(await height(other));
		});

		test('[ABRD-126] a repository heading keeps the case it is typed in', async ({ page }) => {
			await openBoard(page, WAITING);
			const name = page.locator('.tracks .group').first().locator('span').first();

			await expect(name).toHaveCSS('text-transform', 'none');
			expect(await name.evaluate((span) => (span as HTMLElement).innerText)).toBe(REPOSITORY);
		});
	});
}

for (const viewport of [
	{ width: 1280, height: 900 },
	{ width: 390, height: 844 }
]) {
	const isPhone = viewport.width < 760;
	test.describe(`${viewport.width}px head`, () => {
		test.use({ viewport });

		test('[ABRD-125] the head shows the pill tabs with the count badge and starts the tabs at the left on phones', async ({
			page
		}) => {
			await openBoard(page, WAITING);
			const views = page.getByRole('navigation', { name: 'Views' });
			const open = views.getByRole('button', { name: 'Open 2' });
			const brand = page.getByRole('heading', { level: 1 });

			await expect(views.getByRole('button')).toHaveCount(2);
			await expect(open.locator('.n')).toHaveText('2');
			const radius = await open.evaluate((tab) => parseFloat(getComputedStyle(tab).borderRadius));
			expect(radius).toBeGreaterThanOrEqual((await height(open)) ?? Infinity);
			if (isPhone) {
				const box = await views.boundingBox();
				expect(box?.x).toBeLessThan(viewport.width / 4);
				await expect(page.getByRole('button', { name: /^Refresh/ })).toBeVisible();
			} else {
				await expect(brand).toBeVisible();
				await expect(brand).toHaveCSS('text-transform', 'uppercase');
			}
		});

		for (const state of ['without access', 'while loading']) {
			test(`[ABRD-125] the wordmark is visible ${state}`, async ({ page }) => {
				const { appUrl, token } = readBoardRuntime();
				if (state === 'while loading') {
					await page.route('**/api/board', () => new Promise(() => undefined));
					await page.goto(`${appUrl}#t=${token}`);
					await expect(page.getByRole('status')).toBeVisible();
				} else {
					await page.goto(appUrl);
					await expect(page.getByRole('alert')).toBeVisible();
				}

				await expect(page.getByRole('navigation', { name: 'Views' })).toHaveCount(0);
				await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
			});
		}
	});
}
