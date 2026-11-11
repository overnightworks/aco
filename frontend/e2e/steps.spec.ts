import type { Page } from '@playwright/test';
import { expect, test } from './consoleGuard';
import { arrange, item, optionEntry, stepItem, type CardOption } from './itemFixture';
import { readBoardRuntime } from './runtime';

// One shared board server backs every test in this file (see
// global-setup.ts); each test arranges the whole board.
test.describe.configure({ mode: 'serial' });

const OPTIONS: CardOption[] = (['A', 'B'] as const).map((letter) => ({
	name: `Weg ${letter}`,
	effect: `Wirkung ${letter}.`,
	same_as_today: true,
	notice: 'Merkbar.',
	cost: 'Aufwand.',
	undo: 'reversible',
	undo_how: 'jederzeit',
	contract: `Vertrag ${letter}.`
}));

const LONG_STEP = `Open the console and rotate the key ${'verylongwordwithoutanybreak'.repeat(6)} then say done.`;

const card = () =>
	item(7, 'Sprung', optionEntry('Der Song bleibt offen.', { topic: 'Sprung', option: OPTIONS }));

async function show(page: Page): Promise<void> {
	const { appUrl, token } = readBoardRuntime();
	await page.goto(`${appUrl}#t=${token}`);
}

async function shoot(page: Page, outputPath: (name: string) => string, name: string) {
	await page.screenshot({ path: outputPath(`${name}.png`) });
	await page.evaluate(() => {
		document.body.style.filter = 'blur(4px) grayscale(1)';
	});
	await page.screenshot({ path: outputPath(`${name}-blur-grayscale.png`) });
	await page.evaluate(() => {
		document.body.style.filter = '';
	});
}

for (const viewport of [
	{ width: 1280, height: 800 },
	{ width: 390, height: 844 },
	{ width: 320, height: 640 }
]) {
	test.describe(`${viewport.width}px steps`, () => {
		test.use({ viewport });

		test('[ABRD-117] [ABRD-123] the board opens on the open question, no step shown and the header tabs fit', async ({
			page
		}, testInfo) => {
			await arrange([
				card(),
				stepItem(9, 'Rotate the key', LONG_STEP),
				stepItem(3, 'Pay the invoice', 'Pay it.')
			]);
			await show(page);

			const views = page.getByRole('navigation', { name: 'Views' });
			await expect(views.getByRole('button', { name: 'Open 1' })).toHaveAttribute(
				'aria-current',
				'page'
			);
			await expect(views.getByRole('button', { name: 'Steps 2' })).toBeVisible();
			await expect(page.getByRole('region', { name: 'Steps' })).toHaveCount(0);
			await expect(page.getByText(LONG_STEP)).toHaveCount(0);
			const firstQuestion = page
				.locator('.tracks')
				.getByRole('button', { name: /Sprung/ })
				.first();
			await expect(firstQuestion).toBeInViewport();
			const overflow = await page.evaluate(
				() => document.documentElement.scrollWidth - document.documentElement.clientWidth
			);
			expect(overflow).toBe(0);
			await shoot(page, (name) => testInfo.outputPath(name), `open-${viewport.width}`);
		});

		test('[ABRD-117] [ABRD-118] the Steps tab shows the steps in full under its count, and no question row', async ({
			page
		}, testInfo) => {
			await arrange([
				card(),
				stepItem(9, 'Rotate the key', LONG_STEP),
				stepItem(3, 'Pay the invoice', 'Pay it.')
			]);
			await show(page);

			const views = page.getByRole('navigation', { name: 'Views' });
			await views.getByRole('button', { name: 'Steps 2' }).click();

			await expect(views.getByRole('button', { name: 'Steps 2' })).toHaveAttribute(
				'aria-current',
				'page'
			);
			const region = page.getByRole('region', { name: 'Steps' });
			await expect(region).toBeVisible();
			const rows = region.getByRole('listitem');
			await expect(rows).toHaveCount(2);
			await expect(rows.nth(0)).toContainText('#9');
			await expect(rows.nth(0)).toContainText('Rotate the key');
			await expect(rows.nth(0)).toContainText(LONG_STEP);
			await expect(rows.nth(1)).toContainText('#3');
			await expect(page.locator('.tracks')).toBeHidden();
			const overflow = await page.evaluate(() => ({
				page: document.documentElement.scrollWidth - document.documentElement.clientWidth,
				region: [...document.querySelectorAll('[aria-labelledby="steps-heading"] .step')].map(
					(step) => step.scrollWidth - step.clientWidth
				)
			}));
			expect(overflow).toEqual({ page: 0, region: [0, 0] });
			await shoot(page, (name) => testInfo.outputPath(name), `steps-${viewport.width}`);
		});

		test('[ABRD-119] a step row holds no control and the Steps view sends no request', async ({
			page
		}) => {
			await arrange([card(), stepItem(9, 'Rotate the key', 'Rotate it.')]);
			await show(page);
			await page
				.getByRole('navigation', { name: 'Views' })
				.getByRole('button', { name: 'Steps 1' })
				.click();
			const region = page.getByRole('region', { name: 'Steps' });
			await expect(region).toBeVisible();
			const requests: string[] = [];
			page.on('request', (request) => requests.push(request.url()));

			await region.getByRole('listitem').click();

			await expect(region.locator('a, button, input, [tabindex]')).toHaveCount(0);
			expect(requests).toEqual([]);
		});

		test('[ABRD-117] the steps are no question and no part of the Open count, and Decided shows no steps', async ({
			page
		}) => {
			await arrange([card(), stepItem(9, 'Rotate the key', 'Rotate it.')]);
			await show(page);
			const views = page.getByRole('navigation', { name: 'Views' });
			await expect(views.getByRole('button', { name: 'Open 1' })).toBeVisible();

			await expect(page.locator('.tracks').getByRole('heading', { name: 'repo 1' })).toBeVisible();
			await views.getByRole('button', { name: /^Decided/ }).click();

			await expect(page.getByRole('region', { name: /^Steps/ })).toHaveCount(0);
		});

		test('[ABRD-120] with no step the Steps view stays and says no step waits', async ({
			page
		}, testInfo) => {
			await arrange([card()]);
			await show(page);

			await page
				.getByRole('navigation', { name: 'Views' })
				.getByRole('button', { name: 'Steps 0' })
				.click();
			const region = page.getByRole('region', { name: 'Steps' });
			await expect(region).toContainText('No step waits for you.');
			await shoot(page, (name) => testInfo.outputPath(name), `no-steps-${viewport.width}`);
		});

		test('[ABRD-123] a reload returns the board to its Open view, the Steps view is not kept', async ({
			page
		}) => {
			await arrange([card(), stepItem(9, 'Rotate the key', 'Rotate it.')]);
			await show(page);
			const views = page.getByRole('navigation', { name: 'Views' });
			await views.getByRole('button', { name: 'Steps 1' }).click();
			await expect(page.getByRole('region', { name: 'Steps' })).toBeVisible();

			await page.reload();

			await expect(views.getByRole('button', { name: 'Open 1' })).toHaveAttribute(
				'aria-current',
				'page'
			);
			await expect(page.getByRole('region', { name: 'Steps' })).toHaveCount(0);
		});
	});
}
