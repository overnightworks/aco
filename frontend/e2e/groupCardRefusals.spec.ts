import { expect, test } from './consoleGuard';
import { ALREADY_RULED_MESSAGE, LINE_CHANGED_MESSAGE } from '../src/app/model/decision';
import {
	PAST_UNDO_WINDOW_MS,
	point,
	threePoints,
	sprung,
	arrangeCards,
	expectRuled,
	logPosts,
	logBoards,
	fingerprintOf,
	open,
	pick
} from './groupCardFixture';

// One shared board server backs every test in this file (see
// global-setup.ts); each test arranges the whole board.
test.describe.configure({ mode: 'serial' });

for (const viewport of [
	{ width: 1280, height: 900 },
	{ width: 390, height: 844 }
]) {
	const phone = viewport.width === 390;
	test.describe(`${viewport.width}px card of points`, () => {
		test('[ABRD-80] a point ruled from chat meanwhile is refused as already ruled and nothing else is stored', async ({
			page
		}) => {
			await arrangeCards();
			await open(page, phone);
			await arrangeCards([
				point(2),
				point(3, { ruling: 'A', ruled_on: '2026-10-26', via: 'chat' }),
				point(4)
			]);

			await pick(page, 2, 'B').click();
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);

			await expect(page.getByRole('alert')).toContainText(ALREADY_RULED_MESSAGE);
			expect((await storedLine(7, 2)).ruling).toBeNull();
			expect((await storedLine(7, 4)).ruling).toBeNull();
		});

		test('[ABRD-45] any other failure shows its banner with the point open again, and picking again posts again', async ({
			page
		}) => {
			await arrangeCards();
			const posts = logPosts(page);
			let failFirst = true;
			await page.route('**/api/rule', async (route) => {
				if (failFirst) {
					failFirst = false;
					await route.fulfill({
						status: 200,
						contentType: 'application/json',
						body: JSON.stringify({ status: 'failed', message: 'aco unavailable' })
					});
				} else {
					await route.continue();
				}
			});
			await open(page, phone);

			await pick(page, 1, 'B').click();
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);

			await expect(page.getByRole('alert')).toContainText('aco unavailable');
			await expect(page.getByRole('button', { pressed: true })).toHaveCount(0);
			await expect(pick(page, 1, 'A')).toBeEnabled();
			await pick(page, 1, 'A').click();
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);

			await expect.poll(() => posts.length).toBe(2);
			await expect.poll(() => storedLine(7, 2)).toMatchObject({ ruling: 'A', via: 'board' });
		});

		test('[ABRD-91] a point changed after the page read is refused, Neu laden shows it fresh, and the next post names it', async ({
			page
		}) => {
			await arrange([sprung(...threePoints())]);
			const posts = logPosts(page);
			const boards = logBoards(page);
			await open(page, phone);

			await pick(page, 1, 'B').click();
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);
			await expectRuled(['B']);
			await arrange([
				sprung(
					point(2, { ruling: 'B', ruled_on: '2026-10-26', via: 'board' }),
					point(3, { problem: 'Problem 3 geändert.' }),
					point(4)
				)
			]);
			await pick(page, 1, 'A').click();
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);

			await expect(page.getByRole('alert')).toContainText(LINE_CHANGED_MESSAGE);
			expect((await storedLine(7, 3)).ruling).toBeNull();
			const readsBefore = boards.length;
			await page.getByRole('button', { name: 'Neu laden' }).click();
			await expect.poll(() => boards.length).toBeGreaterThan(readsBefore);
			const changed = await fingerprintOf(boards.at(-1), 3);
			await pick(page, 1, 'A').click();
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);

			await expect.poll(() => posts.length).toBe(3);
			const posted = posts.at(-1) as { lines: { line: number; fingerprint: string }[] };
			expect(posted.lines.find((entry) => entry.line === 3)?.fingerprint).toBe(changed);
			await expect.poll(() => storedLine(7, 3)).toMatchObject({ ruling: 'A', via: 'board' });
		});
	});
}
