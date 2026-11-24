import { expect, test } from './consoleGuard';
import { arrange, item, stepTable } from './itemFixture';
import { readBoardRuntime } from './runtime';

test.describe.configure({ mode: 'serial' });

const ACTIONS =
	'open https://example.test/release/with/a/very/long/path/that/must/wrap/somewhere\nclick Run';

/** The step table the arranged item stores, listed as its card. */
const STEP_TABLE = stepTable({ actions: ACTIONS, answer: 'the green run id' });

for (const viewport of [
	{ width: 1280, height: 900 },
	{ width: 390, height: 844 }
]) {
	test.describe(`${viewport.width}px steps view`, () => {
		test.use({ viewport, permissions: ['clipboard-read', 'clipboard-write'] });

		test('ABRD-159, ABRD-160: the step card shows purpose, block, expected and answer; Copy copies the block', async ({
			page
		}, testInfo) => {
			await arrange([
				{ ...item(8, 'Old step'), waiting: true },
				{ ...item(7, 'Release the build'), step: STEP_TABLE }
			]);
			const { appUrl, token } = readBoardRuntime();
			await page.goto(`${appUrl}#t=${token}`);

			await page
				.getByRole('navigation', { name: 'Views' })
				.getByRole('button', { name: /^Steps/ })
				.click();

			const card = page.getByRole('article', { name: /Release the build/ });
			await expect(card.getByText('Release the build.', { exact: true })).toBeVisible();
			await expect(card.locator('pre')).toHaveText(ACTIONS);
			await expect(card.getByText('The page shows green.')).toBeVisible();
			await expect(card.getByText('Antwort: the green run id')).toBeVisible();
			const old = page.getByRole('article', { name: /Old step/ });
			await expect(old.getByRole('button')).toHaveCount(0);

			await card.getByRole('button', { name: 'Copy' }).click();
			await expect(card.getByRole('button', { name: 'Copied' })).toBeVisible();
			expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(ACTIONS);

			expect(
				await page.evaluate(
					() => document.documentElement.scrollWidth <= document.documentElement.clientWidth
				)
			).toBe(true);
			await page.screenshot({ path: testInfo.outputPath(`steps-${viewport.width}.png`) });
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
