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

		test('[ABRD-114] [ABRD-117] [ABRD-118] the steps stand in their own section above the questions, in full and within the first screen', async ({
			page
		}, testInfo) => {
			await arrange([
				card(),
				stepItem(9, 'Rotate the key', LONG_STEP),
				stepItem(3, 'Pay the invoice', 'Pay it.')
			]);
			await show(page);

			const region = page.getByRole('region', { name: 'Steps 2' });
			await expect(region).toBeVisible();
			const rows = region.getByRole('listitem');
			await expect(rows).toHaveCount(2);
			await expect(rows.nth(0)).toContainText('#9');
			await expect(rows.nth(0)).toContainText('Rotate the key');
			await expect(rows.nth(0)).toContainText(LONG_STEP);
			await expect(rows.nth(1)).toContainText('#3');
			const firstQuestion = page
				.locator('.tracks')
				.getByRole('button', { name: /Sprung/ })
				.first();
			await expect(firstQuestion).toBeInViewport();
			const stepsBox = await region.boundingBox();
			const questionBox = await firstQuestion.boundingBox();
			expect((stepsBox?.y ?? 0) + (stepsBox?.height ?? 0)).toBeLessThanOrEqual(
				questionBox?.y ?? -1
			);
			const overflow = await page.evaluate(() => ({
				page: document.documentElement.scrollWidth - document.documentElement.clientWidth,
				region: [...document.querySelectorAll('[aria-labelledby="steps-heading"] .step')].map(
					(step) => step.scrollWidth - step.clientWidth
				)
			}));
			expect(overflow).toEqual({ page: 0, region: [0, 0] });
			await shoot(page, (name) => testInfo.outputPath(name), `steps-${viewport.width}`);
		});

		test('[ABRD-114] the steps heading starts at the same x as the question list heading', async ({
			page
		}) => {
			await arrange([card(), stepItem(9, 'Rotate the key', 'Rotate it.')]);
			await show(page);

			const stepsHeading = page.locator('#steps-heading > span').first();
			const questionHeading = page.locator('.tracks h2.group > span').first();
			await expect(stepsHeading).toBeVisible();
			await expect(questionHeading).toBeVisible();
			const stepsBox = await stepsHeading.boundingBox();
			const questionBox = await questionHeading.boundingBox();
			expect(stepsBox?.x).toBe(questionBox?.x);
		});

		test('[ABRD-119] a step row holds no control and the section sends no request', async ({
			page
		}) => {
			await arrange([card(), stepItem(9, 'Rotate the key', 'Rotate it.')]);
			const requests: string[] = [];
			await show(page);
			await expect(page.getByRole('region', { name: 'Steps 1' })).toBeVisible();
			page.on('request', (request) => requests.push(request.url()));

			const region = page.getByRole('region', { name: 'Steps 1' });
			await region.getByRole('listitem').click();

			await expect(region.locator('a, button, input, [tabindex]')).toHaveCount(0);
			expect(requests).toEqual([]);
		});

		test('[ABRD-117] the steps never count among the questions and show only in the Open view', async ({
			page
		}) => {
			await arrange([card(), stepItem(9, 'Rotate the key', 'Rotate it.')]);
			await show(page);
			await expect(page.getByRole('region', { name: 'Steps 1' })).toBeVisible();

			await expect(page.locator('.tracks').getByRole('heading', { name: 'repo 1' })).toBeVisible();
			await page.getByRole('button', { name: /^Decided/ }).click();

			await expect(page.getByRole('region', { name: /^Steps/ })).toHaveCount(0);
		});

		test('[ABRD-120] with no step the section stays and says no step waits', async ({
			page
		}, testInfo) => {
			await arrange([card()]);
			await show(page);

			const region = page.getByRole('region', { name: 'Steps 0' });
			await expect(region).toContainText('No step waits for you.');
			await shoot(page, (name) => testInfo.outputPath(name), `no-steps-${viewport.width}`);
		});
	});
}
