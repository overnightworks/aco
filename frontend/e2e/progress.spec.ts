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
			await arrange(
				[
					container(10, 'Song jump', { closed: [101, 102, 103], open: [20] }),
					container(11, 'Nested part', { closed: [201], open: [202, 203] }, { parent: 10 }),
					container(12, 'Share page', { open: [301, 302] }),
					{ ...item(20, 'Pick a key'), waiting: true }
				],
				{ landed: [101, 102] }
			);
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
			await expect(region.getByRole('listitem').filter({ hasText: /^Waiting/ })).toHaveText(
				'Waiting 1'
			);
			await expect(region.getByRole('listitem').filter({ hasText: /^Landed/ })).toHaveText(
				'Landed 2'
			);
			await expect(
				region.getByRole('listitem').filter({ hasText: /^Closed otherwise/ })
			).toHaveText('Closed otherwise 1');
			await expect(region.locator('.chip')).toHaveText(['Waiting 1']);
			expect(
				await page.evaluate(
					() => document.documentElement.scrollWidth <= document.documentElement.clientWidth
				)
			).toBe(true);
			await page.screenshot({ path: testInfo.outputPath('progress.png') });
		});

		test('[ABRD-135] a bar shows landed apart from other closes', async ({ page }) => {
			await arrange([container(10, 'Song jump', { closed: [101, 102, 103], open: [104] })], {
				landed: [101, 102]
			});
			const { appUrl, token } = readBoardRuntime();
			await page.goto(`${appUrl}#t=${token}`);
			await page
				.getByRole('navigation', { name: 'Views' })
				.getByRole('button', { name: 'Progress' })
				.click();

			const bar = page.getByRole('progressbar', { name: 'Song jump' });
			const landed = await bar.locator('.landed').boundingBox();
			const other = await bar.locator('.other').boundingBox();
			expect(landed?.width).toBeGreaterThan(0);
			expect(other?.width).toBeGreaterThan(0);
			expect(landed?.width).toBeGreaterThan(other?.width ?? Infinity);
		});

		test('[ABRD-135] a container with nothing planned shows the text and no progressbar', async ({
			page
		}) => {
			await arrange([container(10, 'Empty', {})]);
			const { appUrl, token } = readBoardRuntime();
			await page.goto(`${appUrl}#t=${token}`);
			await page
				.getByRole('navigation', { name: 'Views' })
				.getByRole('button', { name: 'Progress' })
				.click();

			const region = page.getByRole('region', { name: 'Progress per repository' });
			await expect(region.getByText('Nothing planned')).toHaveCount(2);
			await expect(region.getByRole('progressbar')).toHaveCount(0);
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
