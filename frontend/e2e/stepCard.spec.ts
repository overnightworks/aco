import type { Page } from '@playwright/test';
import { expect, test } from './consoleGuard';
import { arrange, item, oldStepTable, openSteps, stepTable } from './itemFixture';
import { readBoardRuntime } from './runtime';

test.describe.configure({ mode: 'serial' });

const COMMAND = 'cd ~/repo && make release TARGET=production';
const LINK = 'http://127.0.0.1:8765/run';

for (const viewport of [
	{ width: 1280, height: 900 },
	{ width: 390, height: 844 }
]) {
	test.describe(`${viewport.width}px steps view`, () => {
		test.use({ viewport, permissions: ['clipboard-read', 'clipboard-write'] });

		async function fitsTheWidth(page: Page): Promise<boolean> {
			return page.evaluate(
				() => document.documentElement.scrollWidth <= document.documentElement.clientWidth
			);
		}

		test('ABRD-159, ABRD-160, ABRD-195: a command shows in a box and Copy copies exactly it', async ({
			page
		}, testInfo) => {
			await arrange([{ ...item(7, 'Release the build'), step: stepTable({ paste: COMMAND }) }]);
			await openSteps(page);

			const card = page.getByRole('article', { name: /Release the build/ });
			await expect(card.getByText('Release the build.', { exact: true })).toBeVisible();
			await expect(card.locator('pre')).toHaveText(COMMAND);
			await expect(card.getByText('The page shows green.')).toBeVisible();
			await expect(card.getByText('Antwort: Ja / Nein')).toBeVisible();
			await expect(card.getByRole('link', { name: 'Öffnen' })).toHaveCount(0);

			await card.getByRole('button', { name: 'Copy' }).click();
			await expect(card.getByRole('button', { name: 'Copied' })).toBeVisible();
			expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(COMMAND);

			expect(await fitsTheWidth(page)).toBe(true);
			await page.screenshot({ path: testInfo.outputPath(`steps-command-${viewport.width}.png`) });
		});

		test('ABRD-195, ABRD-196: a link shows as Öffnen that opens a new tab', async ({
			page
		}, testInfo) => {
			await arrange([{ ...item(7, 'Release the build'), step: stepTable({ paste: LINK }) }]);
			await openSteps(page);

			const card = page.getByRole('article', { name: /Release the build/ });
			const open = card.getByRole('link', { name: 'Öffnen' });
			await expect(open).toHaveAttribute('href', LINK);
			await expect(open).toHaveAttribute('target', '_blank');
			await expect(open).toHaveAttribute('rel', 'noopener noreferrer');
			await expect(card.locator('pre')).toHaveCount(0);
			await expect(card.getByRole('button', { name: 'Copy' })).toHaveCount(0);

			expect(await fitsTheWidth(page)).toBe(true);
			await page.screenshot({ path: testInfo.outputPath(`steps-link-${viewport.width}.png`) });
		});

		test('ABRD-161, ABRD-197: an old step shows alte Form and its stored text without Copy or Öffnen', async ({
			page
		}, testInfo) => {
			await arrange([
				{ ...item(8, 'Old step'), waiting: true },
				{ ...item(7, 'Release the build'), step: oldStepTable({ answer: 'the green run id' }) },
				{
					...item(6, 'Foreign link'),
					step: stepTable({ paste: 'javascript://x' })
				}
			]);
			await openSteps(page);

			const stored = page.getByRole('article', { name: /Release the build/ });
			await expect(stored.getByText('alte Form')).toBeVisible();
			await expect(stored.getByText('click Run')).toBeVisible();
			await expect(stored.getByLabel('Bericht')).toBeVisible();
			const tableless = page.getByRole('article', { name: /Old step/ });
			await expect(tableless.getByText('alte Form')).toBeVisible();
			await expect(tableless.getByRole('button', { name: 'Erfolgreich' })).toBeVisible();
			const foreign = page.getByRole('article', { name: /Foreign link/ });
			await expect(foreign.getByText('alte Form')).toBeVisible();
			await expect(foreign.getByText('javascript://x')).toBeVisible();
			await expect(page.getByRole('button', { name: 'Copy' })).toHaveCount(0);
			await expect(page.getByRole('link', { name: 'Öffnen' })).toHaveCount(0);

			expect(await fitsTheWidth(page)).toBe(true);
			await page.screenshot({ path: testInfo.outputPath(`steps-old-${viewport.width}.png`) });
		});

		test('ABRD-162: with no step the view says nothing waits', async ({ page }) => {
			await arrange([item(8, 'Quiet')]);
			const { appUrl, token } = readBoardRuntime();
			await page.goto(`${appUrl}#t=${token}`);

			await page
				.getByRole('navigation', { name: 'Views' })
				.getByRole('button', { name: /^Steps/ })
				.click();

			await expect(page.getByText('No step is waiting for you.')).toBeVisible();
		});
	});
}
