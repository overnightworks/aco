import { expect, test } from './consoleGuard';
import { arrange, container, item, type FinishedItem } from './itemFixture';
import { readBoardRuntime } from './runtime';

// One shared board server backs every test in this file (see
// global-setup.ts); each test arranges the whole board.
test.describe.configure({ mode: 'serial' });

/** Six finished items whose lanes took 1 to 6 hours: pooled median 3.5 h, 80th percentile 5 h. */
const FINISHED: FinishedItem[] = [1, 2, 3, 4, 5, 6].map((hours) => ({
	issue: hours,
	wall_seconds: hours * 3600
}));

for (const viewport of [
	{ width: 1280, height: 900 },
	{ width: 390, height: 844 }
]) {
	test.describe(`${viewport.width}px progress view`, () => {
		test.use({ viewport });

		test('ABRD-135: the Progress tab shows the repository line and each top-level container, never a nested one', async ({
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

		test('ABRD-135: a bar shows landed apart from other closes', async ({ page }) => {
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

		test('ABRD-135: a container with nothing planned shows the text and no progressbar', async ({
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

		test('ABRD-135: a repository without containers shows 0/0 and says so', async ({ page }) => {
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

		test('ABRD-146: a container shows its lanes left and the agent-work range from the lane records', async ({
			page
		}, testInfo) => {
			await arrange(
				[
					container(10, 'Song jump', { closed: [101], open: [20, 21] }),
					container(12, 'Share page', { closed: [301] }),
					{ ...item(21, 'Pick a key'), waiting: true }
				],
				{ laneRecords: FINISHED }
			);
			const { appUrl, token } = readBoardRuntime();
			await page.goto(`${appUrl}#t=${token}`);
			await page
				.getByRole('navigation', { name: 'Views' })
				.getByRole('button', { name: 'Progress' })
				.click();

			const region = page.getByRole('region', { name: 'Progress per repository' });
			await expect(
				region.getByText('1 lane left · about 4 to 5 h agent work · from 6 finished items')
			).toBeVisible();
			await expect(region.getByText(/lanes? left/)).toHaveCount(1);
			await expect(region.locator('.chip')).toHaveText(['Waiting 1']);
			expect(
				await page.evaluate(
					() => document.documentElement.scrollWidth <= document.documentElement.clientWidth
				)
			).toBe(true);
			await page.screenshot({ path: testInfo.outputPath('progress-range.png') });
		});

		test('ABRD-144: a container without enough lane records says so beside its lanes left', async ({
			page
		}) => {
			await arrange([container(10, 'Song jump', { closed: [101], open: [20, 21] })], {
				laneRecords: FINISHED.slice(0, 3)
			});
			const { appUrl, token } = readBoardRuntime();
			await page.goto(`${appUrl}#t=${token}`);
			await page
				.getByRole('navigation', { name: 'Views' })
				.getByRole('button', { name: 'Progress' })
				.click();

			await expect(page.getByText('2 lanes left · not enough lane records yet')).toBeVisible();
		});

		test('ABRD-144: a container with no lane records at all says so', async ({ page }) => {
			await arrange([container(10, 'Song jump', { closed: [101], open: [20] })]);
			const { appUrl, token } = readBoardRuntime();
			await page.goto(`${appUrl}#t=${token}`);
			await page
				.getByRole('navigation', { name: 'Views' })
				.getByRole('button', { name: 'Progress' })
				.click();

			await expect(page.getByText('1 lane left · no lane records')).toBeVisible();
		});

		test('ABRD-151: a container lists its closed children with their lane time and fix rounds', async ({
			page
		}, testInfo) => {
			await arrange([container(10, 'Song jump', { closed: [101, 102, 103, 104], open: [20] })], {
				laneRecords: [
					{ issue: 101, wall_seconds: 5400, fix_rounds: 2 },
					{ issue: 101, wall_seconds: 1800, fix_rounds: 1 },
					{ issue: 102, wall_seconds: 600 }
				]
			});
			const { appUrl, token } = readBoardRuntime();
			await page.goto(`${appUrl}#t=${token}`);
			await page
				.getByRole('navigation', { name: 'Views' })
				.getByRole('button', { name: 'Progress' })
				.click();

			const closed = page.getByRole('list', { name: 'Closed children' });
			await expect(closed.getByRole('listitem')).toHaveText([
				'#101 Child 101 · 2 h · 3 fix rounds',
				'#102 Child 102 · 10 min · fix rounds unknown',
				'#103 Child 103 · no record',
				'#104 Child 104 · no record'
			]);
			expect(
				await page.evaluate(
					() => document.documentElement.scrollWidth <= document.documentElement.clientWidth
				)
			).toBe(true);
			await page.screenshot({ path: testInfo.outputPath('progress-closed-children.png') });
		});
	});
}
