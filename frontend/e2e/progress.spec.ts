import { expect, test } from './consoleGuard';
import { arrange, container, item } from './itemFixture';
import { readBoardRuntime } from './runtime';

// One shared board server backs every test in this file (see
// global-setup.ts); each test arranges the whole board.
test.describe.configure({ mode: 'serial' });

for (const viewport of [
	{ width: 1280, height: 900 },
	{ width: 390, height: 844 }
]) {
	test.describe(`${viewport.width}px progress view`, () => {
		test.use({ viewport });

		test('[ABRD-135] the Progress tab shows the repository line and each top-level container, never a nested one', async ({
			page
		}, testInfo) => {
			await arrange([
				container(10, 'Song jump', { closed: 3, total: 4 }),
				container(11, 'Nested part', { closed: 1, total: 9 }, { parent: 10 }),
				container(12, 'Share page', { closed: 0, total: 2 }),
				{ ...item(20, 'Pick a key'), waiting: true }
			]);
			const { appUrl, token } = readBoardRuntime();
			await page.goto(`${appUrl}#t=${token}`);

			await page
				.getByRole('navigation', { name: 'Views' })
				.getByRole('button', { name: 'Progress' })
				.click();

			const region = page.getByRole('region', { name: 'Progress per repository' });
			await expect(region.getByText('3/6 · 50 %')).toBeVisible();
			await expect(region.getByText('3/4 · 75 %')).toBeVisible();
			await expect(region.getByText('0/2 · 0 %')).toBeVisible();
			await expect(region.getByText('Nested part')).toHaveCount(0);
			await expect(region.getByText(/^Waiting/)).toHaveText('Waiting 1');
			expect(
				await page.evaluate(
					() => document.documentElement.scrollWidth <= document.documentElement.clientWidth
				)
			).toBe(true);
			await page.screenshot({ path: testInfo.outputPath('progress.png') });
		});

		test('[ABRD-135] a repository without containers shows 0/0 and says so', async ({ page }) => {
			await arrange([item(20, 'Pick a key')]);
			const { appUrl, token } = readBoardRuntime();
			await page.goto(`${appUrl}#t=${token}`);

			await page
				.getByRole('navigation', { name: 'Views' })
				.getByRole('button', { name: 'Progress' })
				.click();

			await expect(page.getByText('0/0', { exact: true }).first()).toBeVisible();
			await expect(page.getByText('No container is open.')).toBeVisible();
		});
	});
}
