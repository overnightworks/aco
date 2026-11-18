import { expect, test } from './consoleGuard';
import { arrange, item } from './itemFixture';
import { readBoardRuntime } from './runtime';

test.describe.configure({ mode: 'serial' });

const ACTIONS =
	'open https://example.test/release/with/a/very/long/path/that/must/wrap/somewhere\nclick Run';

/** The step table the real read lists for an item that stores one; the arranging endpoint
 * stores only the old one-line step, so the board's own answer is completed with this card
 * (`tests/board/test_board_api_steps.py` proves the real wire form). */
const STEP_CARD = {
	number: 7,
	title: 'Release the build',
	step: 'Run the release.',
	purpose: 'Release the build.',
	actions: ACTIONS,
	expected: 'The page shows green.',
	answer: 'the green run id'
};

for (const viewport of [
	{ width: 1280, height: 900 },
	{ width: 390, height: 844 }
]) {
	test.describe(`${viewport.width}px steps view`, () => {
		test.use({ viewport, permissions: ['clipboard-read', 'clipboard-write'] });

		test('[ABRD-159] [ABRD-160] the step card shows purpose, block, expected and answer; Copy copies the block', async ({
			page
		}, testInfo) => {
			await arrange([{ ...item(8, 'Old step'), waiting: true }]);
			await page.route('**/api/board', async (route) => {
				const response = await route.fetch();
				const board = await response.json();
				board.repos[0].steps = [STEP_CARD, ...board.repos[0].steps];
				await route.fulfill({ response, json: board });
			});
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

		test('[ABRD-162] with no step the view says nothing waits', async ({ page }) => {
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
