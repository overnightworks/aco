import { expect, test } from './consoleGuard';
import { decidedList, expectDecidedAnswer } from './decidedView';
import {
	PAST_UNDO_WINDOW_MS,
	BOARD_PICK_HOW,
	CARD_NAME,
	ANSWER,
	NOTE,
	FINAL_OPTIONS,
	point,
	withdrawn,
	threePoints,
	sprung,
	arrangeCards,
	expectRuled,
	send,
	logPosts,
	visit,
	showCard,
	open,
	card,
	toggle,
	pointPicks,
	pick,
	acceptAll,
	strip,
	undo,
	otherAt,
	picks,
	decideBar,
	shoot,
	fits,
	cardPost
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
		test.use({ viewport });

		test('[ABRD-82] [ABRD-106] an item’s open option lines are one Open row named by area and count, beside another open row, and the tab counts rows', async ({
			page
		}, testInfo) => {
			await arrangeCards();
			await visit(page);

			const rows = page.locator('.tracks').getByRole('button');
			await expect(rows).toHaveCount(2);
			await expect(rows.nth(0)).toHaveAccessibleName(
				new RegExp(`^Open ${CARD_NAME} \\d{2}\\.\\d{2}\\.$`)
			);
			await expect(rows.nth(0)).toHaveAttribute('title', CARD_NAME);
			await expect(rows.nth(1)).toHaveAccessibleName(/^Open Thema 1 \d{2}\.\d{2}\.$/);
			await expect(page.getByRole('button', { name: 'Open 2', exact: true })).toBeVisible();
			await shoot(page, testInfo, 'list');
		});

		test('[ABRD-83] [ABRD-106] [ABRD-154] the card is titled by its name, carries the meta of its points, has no Problem row and offers Accept all and Unclear, with an Other… at every point', async ({
			page
		}, testInfo) => {
			const { repository } = readBoardRuntime();
			await arrangeCards();
			await open(page, phone);

			await expect(card(page).locator('.meta')).toHaveText(
				new RegExp(
					`^\\s*${repository} › Song-Seite\\s*·\\s*Product\\s*·\\s*reversible\\s*·\\s*Asked \\d{2}\\.\\d{2}\\.\\d{4}\\s*$`
				)
			);
			await expect(card(page).getByRole('heading', { name: CARD_NAME, exact: true })).toBeVisible();
			await expect(card(page).getByText('Problem', { exact: true })).toHaveCount(0);
			await expect(card(page).getByText('Points', { exact: true })).toHaveCount(1);
			await expect(card(page).locator('button.toggle')).toHaveText([
				/^\s*1\s+Frage 2\?/,
				/^\s*2\s+Frage 3\?/,
				/^\s*3\s+Frage 4\?/
			]);
			for (const number of [1, 2, 3]) {
				await expect(toggle(page, number)).toHaveAttribute('aria-expanded', 'false');
				await expect(pointPicks(page, number).getByRole('button')).toHaveText(['A', 'B']);
				await expect(pick(page, number, 'A')).toHaveClass(/recommended/);
				await expect(pick(page, number, 'A')).toHaveAttribute('aria-pressed', 'false');
				await expect(otherAt(page, number)).toBeVisible();
				await expect(otherAt(page, number)).toBeInViewport();
			}
			await expect(decideBar(page).getByRole('button')).toHaveText(['Accept all', 'Unclear']);
			await expect(acceptAll(page)).toHaveClass(/recommended/);
			await expect(page.getByText(/of 3 chosen/)).toHaveCount(0);
			await shoot(page, testInfo, 'card');
			await fits(page, viewport.width);
		});

		if (phone)
			test('[ABRD-83] every point’s picks stand at least 44 px high on a phone', async ({
				page
			}) => {
				await arrangeCards();
				await open(page, phone);

				const heights = await card(page)
					.locator('.point button.pick')
					.evaluateAll((buttons) => buttons.map((button) => button.getBoundingClientRect().height));

				expect(heights).toHaveLength(6);
				for (const height of heights) expect(height).toBeGreaterThanOrEqual(44);
			});

		test('[ABRD-85] one point is open at a time, with its rows and a Today that enlarges, and a phone keeps the Decide row in view', async ({
			page
		}, testInfo) => {
			await arrangeCards();
			await open(page, phone);

			await toggle(page, 1).click();
			await expect(toggle(page, 1)).toHaveAttribute('aria-expanded', 'true');
			await expect(card(page).getByText('Problem 2.')).toBeVisible();
			await expect(card(page).getByRole('term')).toHaveText([
				'Points',
				'Problem',
				'Today',
				'Options',
				'Recommendation',
				'',
				'',
				'Decide'
			]);
			await shoot(page, testInfo, 'point-open');

			await toggle(page, 2).click();
			await expect(toggle(page, 1)).toHaveAttribute('aria-expanded', 'false');
			await expect(toggle(page, 2)).toHaveAttribute('aria-expanded', 'true');
			await expect(card(page).getByText('Problem', { exact: true })).toHaveCount(1);
			await expect(card(page).getByText('Problem 3.')).toBeVisible();

			await card(page).getByRole('button', { name: 'Enlarge picture' }).click();
			const dialog = page.getByRole('dialog', { name: 'Picture at full width' });
			await expect(dialog).toBeVisible();
			await dialog.getByRole('button', { name: 'Close' }).click();
			await expect(dialog).toHaveCount(0);

			await toggle(page, 2).click();
			await expect(toggle(page, 2)).toHaveAttribute('aria-expanded', 'false');
			await expect(card(page).getByText('Problem', { exact: true })).toHaveCount(0);

			if (phone) {
				await toggle(page, 1).click();
				await expect(page.locator('.decide-row')).toHaveCSS('position', 'sticky');
				await expect(page.locator('.decide-row')).toBeInViewport();
				await expect(acceptAll(page)).toBeInViewport();
				await expect(otherAt(page, 1)).toBeInViewport();
				await expect(page.getByRole('button', { name: 'Unclear' })).toBeInViewport();
				await fits(page, viewport.width);
			}
		});

		test('[ABRD-84] the points, their picks, Other… and Accept all are reachable by keyboard with the right state', async ({
			page
		}) => {
			await arrangeCards();
			await open(page, phone);

			await toggle(page, 1).focus();
			await page.keyboard.press('Enter');
			await expect(toggle(page, 1)).toHaveAttribute('aria-expanded', 'true');
			await page.keyboard.press('Enter');
			await expect(toggle(page, 1)).toHaveAttribute('aria-expanded', 'false');
			await page.keyboard.press('Tab');
			await expect(pick(page, 1, 'A')).toBeFocused();
			await page.keyboard.press('Tab');
			await expect(pick(page, 1, 'B')).toBeFocused();
			await page.keyboard.press('Tab');
			await expect(otherAt(page, 1)).toBeFocused();
			await pick(page, 1, 'B').focus();
			await page.keyboard.press('Space');
			await expect(pick(page, 1, 'B')).toHaveAttribute('aria-pressed', 'true');
			await expect(pick(page, 1, 'A')).toHaveAttribute('aria-pressed', 'false');
			await expect(undo(page)).toBeFocused();

			await acceptAll(page).focus();
			await page.keyboard.press('Enter');
			await expect(strip(page)).toHaveCount(2);
			await expect(undo(page).last()).toBeFocused();
		});

		test('[ABRD-86] a pick answers its point alone: it waits, the other points stay open, and the card stays with the points left, renumbered', async ({
			page
		}, testInfo) => {
			await arrangeCards();
			const posts = logPosts(page);
			await open(page, phone);

			await pick(page, 1, 'B').click();

			await expect(strip(page)).toHaveCount(1);
			await expect(strip(page)).toContainText(`Saves shortly: 1B · ${CARD_NAME}`);
			await expect(pick(page, 1, 'B')).toHaveAttribute('aria-pressed', 'true');
			await expect(pick(page, 1, 'B')).toBeDisabled();
			await expect(pick(page, 1, 'A')).toBeDisabled();
			await expect(pick(page, 2, 'A')).toBeEnabled();
			await expect(otherAt(page, 2)).toBeEnabled();
			await expect(acceptAll(page)).toBeEnabled();
			await shoot(page, testInfo, 'one-waiting');
			await page.clock.runFor(PAST_UNDO_WINDOW_MS - 1000);
			expect(posts).toEqual([]);
			await page.clock.runFor(1000);

			await expect
				.poll(() => posts)
				.toEqual([cardPost(7, [{ line: 2, fingerprint: expect.any(String), option: 'B' }])]);
			await expectRuled(['B']);
			expect((await storedLine(7, 3)).ruling).toBeNull();
			await expect(
				card(page).getByRole('heading', { name: 'Song-Seite · 2 points' })
			).toBeVisible();
			await expect(card(page).locator('button.toggle')).toHaveText([
				/^\s*1\s+Frage 3\?/,
				/^\s*2\s+Frage 4\?/
			]);
			await expect(strip(page)).toHaveCount(0);
			await shoot(page, testInfo, 'two-left');
		});

		test('[ABRD-87] picks on two points are two strips and two posts, Undo frees one point alone, and Decided lists each stored point', async ({
			page
		}, testInfo) => {
			await arrangeCards();
			const posts = logPosts(page);
			await open(page, phone);

			await pick(page, 1, 'B').click();
			await pick(page, 2, 'A').click();
			await pick(page, 3, 'A').click();

			await expect(strip(page)).toHaveCount(3);
			await expect(strip(page).nth(1)).toContainText(`Saves shortly: 2A · ${CARD_NAME}`);
			await shoot(page, testInfo, 'strips');
			await undo(page).nth(2).click();
			await expect(strip(page)).toHaveCount(2);
			await expect(pick(page, 3, 'A')).toBeEnabled();
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);

			await expect.poll(() => posts.length).toBe(2);
			await expectRuled(['B', 'A']);
			expect((await storedLine(7, 4)).ruling).toBeNull();
			await expect(
				card(page).getByRole('heading', { name: 'Frage 4?', exact: true })
			).toBeVisible();
			if (phone) await page.getByRole('button', { name: '‹ Open' }).click();
			await page.getByRole('button', { name: /^Decided \d+$/ }).click();
			const rows = decidedList(page).getByRole('button');
			await expect(rows).toHaveCount(2);
			await expect(rows).toContainText(['Thema 3', 'Thema 2']);
			await decidedList(page).getByTitle('Frage 2?', { exact: true }).click();
			await expectDecidedAnswer(page, 'B — Weg B', BOARD_PICK_HOW);
		});

		test('[ABRD-155] the stage stays on the card until its last point is stored, then leaves it, the third point alone showing the one-point layout', async ({
			page
		}) => {
			await arrangeCards();
			await open(page, phone);

			await pick(page, 1, 'B').click();
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);
			await pick(page, 1, 'A').click();
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);

			await expectRuled(['B', 'A']);
			await expect(
				card(page).getByRole('heading', { name: 'Frage 4?', exact: true })
			).toBeVisible();
			await expect(card(page).locator('button.toggle')).toHaveCount(0);
			await expect(acceptAll(page)).toHaveCount(0);
			await expect(picks(page)).toBeVisible();
			await picks(page)
				.getByRole('button', { name: /^Decide B:/ })
				.click();
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);
			await expectRuled(['B', 'A', 'B']);
			await expect(
				card(page).getByRole('heading', { name: 'Frage 1?', exact: true })
			).toBeVisible();
		});

		test('[ABRD-87] leaving the page inside the windows stores every waiting point', async ({
			page
		}) => {
			await arrangeCards();
			await open(page, phone);

			await pick(page, 1, 'B').click();
			await pick(page, 3, 'A').click();
			await page.goto('about:blank');

			await expectRuled(['B']);
			await expect.poll(() => storedLine(7, 4)).toMatchObject({ ruling: 'A', via: 'board' });
			expect((await storedLine(7, 3)).ruling).toBeNull();
		});

		test('[ABRD-88] a final pick asks first with its point, Cancel leaves the point open, and confirming starts its window', async ({
			page
		}) => {
			await arrangeCards([point(2), point(3, { option: FINAL_OPTIONS }), point(4)]);
			const posts = logPosts(page);
			await open(page, phone);

			await pick(page, 2, 'B').click();
			const dialog = page.getByRole('dialog', { name: 'Decide B?' });
			await expect(dialog).toContainText('Point 2: Nicht rückholbar.');
			await expect(dialog.getByRole('button', { name: 'Cancel' })).toBeFocused();
			await dialog.getByRole('button', { name: 'Cancel' }).click();

			await expect(dialog).toHaveCount(0);
			await expect(pick(page, 2, 'B')).toHaveAttribute('aria-pressed', 'false');
			await expect(pick(page, 2, 'B')).toBeFocused();
			await expect(strip(page)).toHaveCount(0);

			await pick(page, 2, 'B').click();
			await page
				.getByRole('dialog', { name: 'Decide B?' })
				.getByRole('button', { name: 'Decide B', exact: true })
				.click();
			await expect(pick(page, 2, 'B')).toHaveAttribute('aria-pressed', 'true');
			await expect(strip(page)).toContainText(`Saves shortly: 2B · ${CARD_NAME}`);
			expect(posts).toEqual([]);
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);
			await expect.poll(() => storedLine(7, 3)).toMatchObject({ ruling: 'B', via: 'board' });
		});

		test('[ABRD-89] Accept all picks the recommendation for the points still open only, after one pick waits', async ({
			page
		}) => {
			await arrangeCards([point(2), point(3, { recommended: 'B' }), point(4)]);
			const posts = logPosts(page);
			await open(page, phone);
			await pick(page, 1, 'B').click();

			await acceptAll(page).click();

			await expect(page.getByRole('dialog')).toHaveCount(0);
			await expect(strip(page)).toHaveCount(2);
			await expect(strip(page).last()).toContainText(`Saves shortly: 2B 3A · ${CARD_NAME}`);
			await expect(acceptAll(page)).toBeDisabled();
			await expect(page.getByRole('button', { name: 'Unclear' })).toBeDisabled();
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);
			await expect.poll(() => posts.length).toBe(2);
			await expectRuled(['B', 'B', 'A']);
		});

		test('[ABRD-90] Accept all with a final recommendation asks first, Cancel or Esc post nothing, and confirming stores the recommendations of the open points', async ({
			page
		}, testInfo) => {
			await arrangeCards([
				point(2),
				point(3, { option: FINAL_OPTIONS, recommended: 'B' }),
				point(4)
			]);
			const posts = logPosts(page);
			await open(page, phone);
			const dialog = page.getByRole('dialog', { name: 'Accept all recommendations?' });

			await acceptAll(page).click();
			await expect(dialog).toContainText('Point 2: Nicht rückholbar.');
			await expect(dialog.getByRole('button', { name: 'Cancel' })).toBeFocused();
			await shoot(page, testInfo, 'accept-all-confirm');
			await page.keyboard.press('Escape');
			await expect(dialog).toHaveCount(0);
			await acceptAll(page).click();
			await dialog.getByRole('button', { name: 'Cancel' }).click();
			await expect(dialog).toHaveCount(0);
			await expect(strip(page)).toHaveCount(0);
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);
			expect(posts).toEqual([]);

			await acceptAll(page).click();
			await dialog.getByRole('button', { name: 'Accept all', exact: true }).click();
			await expect(strip(page)).toContainText(`Saves shortly: 1A 2B 3A · ${CARD_NAME}`);
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);
			await expect.poll(() => posts.length).toBe(1);
			await expectRuled(['A', 'B', 'A']);
		});

		test('[ABRD-154] Other… at a point answers that point alone with its own text, after its own strip', async ({
			page
		}, testInfo) => {
			await arrangeCards();
			const posts = logPosts(page);
			await open(page, phone);

			await send(page, 'other', 2);

			await expect(strip(page)).toContainText('Saves shortly: Other · Thema 3');
			await expect(otherAt(page, 2)).toBeDisabled();
			await expect(otherAt(page, 1)).toBeEnabled();
			await shoot(page, testInfo, 'other-waiting');
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);
			await expect
				.poll(() => posts)
				.toEqual([cardPost(7, [{ line: 3, fingerprint: expect.any(String) }], { other: ANSWER })]);
			await expect.poll(() => storedLine(7, 3)).toMatchObject({ ruling: 'other', other: ANSWER });
			expect((await storedLine(7, 2)).ruling).toBeNull();
			expect((await storedLine(7, 4)).ruling).toBeNull();
			await expect(
				card(page).getByRole('heading', { name: 'Song-Seite · 2 points' })
			).toBeVisible();
		});

		test('[ABRD-154] the Other panels of two points hold their own text', async ({ page }) => {
			await arrangeCards();
			await open(page, phone);

			await otherAt(page, 1).click();
			await page.getByRole('textbox', { name: 'Point 1: Your answer', exact: true }).fill('Eins');
			await otherAt(page, 3).click();
			await page.getByRole('textbox', { name: 'Point 3: Your answer', exact: true }).fill('Drei');

			await expect(page.getByRole('textbox', { name: 'Point 1: Your answer' })).toHaveValue('Eins');
			await expect(page.getByRole('textbox', { name: 'Point 3: Your answer' })).toHaveValue('Drei');
		});

		test('[ABRD-92] Unclear sends the whole card back with its note, and the card is then with its head without Unclear', async ({
			page
		}, testInfo) => {
			await arrangeCards();
			const posts = logPosts(page);
			await open(page, phone);

			await send(page, 'unclear');

			await expect(strip(page)).toContainText(`With head: ${CARD_NAME}`);
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);
			await expect
				.poll(() => posts)
				.toEqual([
					cardPost(
						7,
						[2, 3, 4].map((index) => ({ line: index, fingerprint: expect.any(String) })),
						{ unclear: true, note: NOTE }
					)
				]);
			for (const index of [2, 3, 4]) {
				await expect.poll(async () => (await storedLine(7, index)).returned_on).not.toBeNull();
			}
			if (phone) await page.getByRole('button', { name: '‹ Open' }).click();
			await expect(page.locator('.tracks').getByTitle(CARD_NAME)).toHaveAccessibleName(
				new RegExp(`^With head ${CARD_NAME} \\d{2}\\.\\d{2}\\.$`)
			);
			await showCard(page, phone, CARD_NAME);
			await expect(card(page).locator('.meta')).toContainText('with head');
			await expect(page.getByRole('button', { name: 'Unclear' })).toHaveCount(0);
			await expect(acceptAll(page)).toBeVisible();
			await shoot(page, testInfo, 'with-head');
		});

		test('[ABRD-61] [ABRD-106] points in different areas join their areas, and a card with one point with its head lists muted after the open cards and offers no Unclear', async ({
			page
		}, testInfo) => {
			const { repository } = readBoardRuntime();
			await arrange([
				sprung(
					point(2),
					point(3, { area: 'Bibliothek', returned_on: '2026-10-27', returned_note: 'Warum?' })
				),
				item(8, 'Offen', point(1, { topic: 'Offen', question: 'Offene Frage?' }))
			]);
			await visit(page);

			const name = 'Song-Seite / Bibliothek · 2 points';
			const rows = page.locator('.tracks').getByRole('button');
			await expect(rows.nth(0)).toHaveAccessibleName(/^Open Offen \d{2}\.\d{2}\.$/);
			await expect(rows.nth(1)).toHaveAccessibleName(
				new RegExp(`^With head ${name} \\d{2}\\.\\d{2}\\.$`)
			);
			await expect(rows.nth(1).getByRole('img', { name: 'With head' })).toBeVisible();
			await showCard(page, phone, name);
			await expect(card(page).locator('.meta')).toHaveText(
				new RegExp(
					`^\\s*${repository} › Song-Seite / Bibliothek\\s*·\\s*Product\\s*·\\s*with head\\s*·\\s*reversible\\s*·\\s*Asked \\d{2}\\.\\d{2}\\.\\d{4}\\s*$`
				)
			);
			await expect(card(page).getByRole('heading', { name, exact: true })).toBeVisible();
			await expect(page.getByRole('button', { name: 'Unclear' })).toHaveCount(0);
			await expect(otherAt(page, 1)).toBeVisible();
			await expect(acceptAll(page)).toBeVisible();
			await expect(pointPicks(page, 1).getByRole('button')).toHaveText(['A', 'B']);
			await shoot(page, testInfo, 'with-head-card');
			await fits(page, viewport.width);
		});

		test('[ABRD-154] Other… at a point with its head stores that point alone and drops its sent-back marks', async ({
			page
		}) => {
			await arrange([
				sprung(point(2), point(3, { returned_on: '2026-10-27', returned_note: 'Warum?' }))
			]);
			await open(page, phone, 'Song-Seite · 2 points');

			await send(page, 'other', 2);
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);

			await expect
				.poll(() => storedLine(7, 3))
				.toMatchObject({ ruling: 'other', other: ANSWER, returned_on: null });
			await expect.poll(async () => (await storedLine(7, 2)).ruling).toBeNull();
		});

		test('[ABRD-36] [ABRD-106] a one-point card looks as before, has no Accept all and posts the card form with one entry', async ({
			page
		}) => {
			await arrange([item(8, 'Offen', point(1, { topic: 'Einzel', question: 'Eine Frage?' }))]);
			const posts = logPosts(page);
			await visit(page);

			await expect(page.locator('.tracks').getByTitle('Eine Frage?')).toHaveAccessibleName(
				/^Open Einzel \d{2}\.\d{2}\.$/
			);
			await showCard(page, phone, 'Eine Frage?');
			await expect(
				card(page).getByRole('heading', { name: 'Eine Frage?', exact: true })
			).toBeVisible();
			await expect(card(page).getByRole('term')).toHaveText([
				'Problem',
				'Today',
				'Options',
				'Recommendation',
				'Decide'
			]);
			await expect(acceptAll(page)).toHaveCount(0);
			await page
				.getByRole('group', { name: 'Decide' })
				.getByRole('button', { name: /^Decide B:/ })
				.click();
			await expect(strip(page)).toContainText('Saves shortly: B — Weg B · Einzel');
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);

			await expect
				.poll(() => posts)
				.toEqual([cardPost(8, [{ line: 1, fingerprint: expect.any(String), option: 'B' }])]);
			await expect.poll(() => storedLine(8, 1)).toMatchObject({ ruling: 'B', via: 'board' });
		});

		for (const kind of ['other', 'unclear'] as const) {
			test(`[ABRD-75] ${kind} on a one-point card posts one entry`, async ({ page }) => {
				await arrange([item(8, 'Offen', point(1, { topic: 'Einzel' }))]);
				const posts = logPosts(page);
				await open(page, phone, 'Frage 1?');

				await send(page, kind);
				await page.clock.runFor(PAST_UNDO_WINDOW_MS);

				const entry = [{ line: 1, fingerprint: expect.any(String) }];
				await expect
					.poll(() => posts)
					.toEqual([
						cardPost(8, entry, kind === 'other' ? { other: ANSWER } : { unclear: true, note: NOTE })
					]);
				await expect
					.poll(() => storedLine(8, 1))
					.toMatchObject(
						kind === 'other' ? { ruling: 'other' } : { returned_on: expect.any(String) }
					);
			});
		}

		for (const how of ['the pick', 'Accept all'] as const) {
			test(`[ABRD-91] ${how} on a card that gained a point after the page read stores the points posted and leaves the new point open`, async ({
				page
			}) => {
				await arrangeCards();
				await open(page, phone);
				await arrangeCards([...threePoints(), withdrawn(), point(6)]);

				if (how === 'Accept all') await acceptAll(page).click();
				else await pick(page, 1, 'B').click();
				await page.clock.runFor(PAST_UNDO_WINDOW_MS);

				await expect(page.getByRole('alert')).toHaveCount(0);
				await expectRuled(how === 'Accept all' ? ['A', 'A', 'A'] : ['B']);
				for (const index of how === 'Accept all' ? [6] : [3, 4, 6]) {
					expect((await storedLine(7, index)).ruling).toBeNull();
				}
			});
		}
	});
}
