import type { Locator, Page } from '@playwright/test';
import { expect, test } from './consoleGuard';
import { arrange, item, optionEntry, type CardOption, type OptionEntry } from './itemFixture';
import { decidedList, expectDecidedAnswer } from './decidedView';
import { countPosts, picks } from './decideRow';
import { readBoardRuntime } from './runtime';
import {
	ALREADY_RULED_MESSAGE,
	LINE_CHANGED_MESSAGE,
	UNDO_SECONDS
} from '../src/app/model/decision';

// One shared board server backs every test in this file (see
// global-setup.ts); each test arranges the whole board.
test.describe.configure({ mode: 'serial' });

// Just past the app's undo window; the page clock is driven, never waited.
const PAST_UNDO_WINDOW_MS = UNDO_SECONDS * 1000 + 500;

// aco rules every board pick `via board` on `board_forge.RULING_DAY`; the
// decided card's How row reads it back.
const BOARD_PICK_HOW = 'Board · 03.10.2026';

const SONG_QUESTION = 'Soll der Song beim Sprung offen bleiben?';
const OTHER_QUESTION = 'Welcher Weg für die Altdaten?';
// The song card's problem as an agent rewrites it while the operator decides.
const CHANGED_PROBLEM = 'Der Link schließt den Song sofort.';

const SONG_OPTIONS: CardOption[] = [
	{
		name: 'Song bleibt offen',
		effect: 'Die App springt selbst.',
		same_as_today: true,
		notice: 'Du bleibst im Song.',
		cost: 'Mehr Code.',
		undo: 'reversible',
		undo_how: 'jederzeit',
		contract: 'Der Song bleibt offen.'
	},
	{
		name: 'Browser-Sprung bleibt',
		effect: 'Der Browser springt weiter.',
		same_as_today: true,
		notice: 'Du klickst den Link.',
		cost: 'Der Fehler bleibt.',
		undo: 'reversible',
		undo_how: 'jederzeit',
		contract: 'Die Vorgabe bleibt.'
	}
];

function songCard(overrides: Partial<OptionEntry> = {}): OptionEntry {
	return optionEntry('Der Song bleibt beim Sprung offen.', {
		question: SONG_QUESTION,
		problem: 'Der Link schließt den Song.',
		caption: 'Der Browser springt selbst.',
		area: 'Song-Seite',
		topic: 'Sprung',
		recommended: 'A',
		reason: 'Behebt den Verlust.',
		option: SONG_OPTIONS,
		...overrides
	});
}

async function arrangeCards(song: Partial<OptionEntry> = {}): Promise<void> {
	await arrange([
		item(2001, 'Sprung', songCard(song)),
		item(
			2002,
			'Altdaten',
			optionEntry('Eine zweite offene Frage.', {
				question: OTHER_QUESTION,
				recommended: 'B',
				option: SONG_OPTIONS
			})
		)
	]);
}

const FINAL_OPTIONS: CardOption[] = [
	SONG_OPTIONS[0],
	{ ...SONG_OPTIONS[1], undo: 'final', undo_how: 'nicht rückholbar.' }
];

async function arrangeFinal(song: Partial<OptionEntry> = {}): Promise<void> {
	await arrangeCards({ option: FINAL_OPTIONS, ...song });
}

function confirm(page: Page): Locator {
	return page.getByRole('dialog', { name: 'Decide B?' });
}

async function dialogInsideViewport(page: Page, viewportWidth: number): Promise<void> {
	expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
		viewportWidth
	);
	const box = await confirm(page).evaluate((dialog) => {
		const { left, right } = dialog.getBoundingClientRect();
		return { left, right };
	});
	expect(box.left).toBeGreaterThanOrEqual(0);
	expect(box.right).toBeLessThanOrEqual(viewportWidth);
}

function expectNear(actual: number, wanted: number): void {
	expect(Math.abs(actual - wanted)).toBeLessThanOrEqual(1);
}

async function edges(
	locator: Locator
): Promise<{ left: number; right: number; top: number; bottom: number }> {
	return locator.evaluate((element) => {
		const { left, right, top, bottom } = element.getBoundingClientRect();
		return { left, right, top, bottom };
	});
}

async function open(page: Page, phone: boolean, question = SONG_QUESTION): Promise<void> {
	const { appUrl, token } = readBoardRuntime();
	await page.clock.install();
	await page.goto(`${appUrl}#t=${token}`);
	await page.locator('.tracks').getByTitle(question).click();
	if (phone) await expect(page.locator('.question-pane')).toBeVisible();
}

async function shoot(page: Page, testInfo: { outputPath(name: string): string }, name: string) {
	await page.screenshot({ path: testInfo.outputPath(`${name}.png`) });
	await page.evaluate(() => {
		document.body.style.filter = 'blur(4px) grayscale(1)';
	});
	await page.screenshot({ path: testInfo.outputPath(`${name}-shapes.png`) });
	await page.evaluate(() => {
		document.body.style.filter = '';
	});
}

for (const viewport of [
	{ width: 1280, height: 900 },
	{ width: 390, height: 844 }
]) {
	const phone = viewport.width === 390;
	test.describe(`${viewport.width}px Decide row`, () => {
		test.use({ viewport });

		test('[ABRD-44] a pick waits out the undo window, then the card moves to Decided', async ({
			page
		}, testInfo) => {
			await arrangeCards();
			await open(page, phone);

			await expect(page.locator('.decide-row dt')).toHaveText('Decide');
			await expect(picks(page).getByRole('button')).toHaveText(['A', 'B']);
			const first = picks(page).getByRole('button', { name: /^Decide A:/ });
			const second = picks(page).getByRole('button', { name: /^Decide B:/ });
			const accent = (button: Locator) =>
				button.evaluate((element) => getComputedStyle(element).borderTopColor);
			expect(await accent(first)).not.toBe(await accent(second));
			await shoot(page, testInfo, 'decide-row');

			await second.click();
			await expect(page.locator('.strip')).toContainText('B — Browser-Sprung bleibt · Sprung');
			await expect(first).toBeDisabled();
			await expect(second).toBeDisabled();
			await shoot(page, testInfo, 'pending');
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);

			await expect(page.locator('.option-card').getByText(SONG_QUESTION)).toHaveCount(0);
			if (phone) {
				await expect(page.locator('.tracks').getByTitle(OTHER_QUESTION)).toHaveCount(1);
			} else {
				await expect(page.getByRole('heading', { name: OTHER_QUESTION })).toBeVisible();
			}
			await expect(page.locator('.tracks').getByTitle(SONG_QUESTION)).toHaveCount(0);
			if (phone) await page.getByRole('button', { name: '‹ Open' }).click();
			await page.getByRole('button', { name: /^Decided \d+$/ }).click();
			const rows = decidedList(page).getByRole('button');
			await expect(rows).toHaveCount(1);
			await expect(rows).toHaveAttribute('title', SONG_QUESTION);
			await expect(rows).toContainText('Sprung');
			await rows.click();
			await expectDecidedAnswer(page, 'B — Browser-Sprung bleibt', BOARD_PICK_HOW);
			expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
				viewport.width
			);
		});

		test('[ABRD-33] Undo inside the window posts nothing and leaves the picks usable', async ({
			page
		}) => {
			await arrangeCards();
			let writes = 0;
			page.on('request', (request) => {
				if (request.method() === 'POST') writes += 1;
			});
			await open(page, phone);

			await picks(page)
				.getByRole('button', { name: /^Decide A:/ })
				.click();
			await page.getByRole('button', { name: 'Undo', exact: true }).click();
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);

			expect(writes).toBe(0);
			await expect(
				page.locator('.option-card').getByRole('heading', { name: SONG_QUESTION })
			).toBeVisible();
			await expect(picks(page).getByRole('button')).toHaveText(['A', 'B']);
			await expect(picks(page).getByRole('button', { name: /^Decide A:/ })).toBeEnabled();
			if (phone) await page.getByRole('button', { name: '‹ Open' }).click();
			await page.getByRole('button', { name: /^Decided \d+$/ }).click();
			await expect(page.getByText('Nothing decided yet')).toBeVisible();
			await expect(decidedList(page).getByRole('button')).toHaveCount(0);
		});

		test('[ABRD-58] a pick shows the strip with the Decided shape and Undo above the card, in view while the card scrolls and over a phone list', async ({
			page
		}, testInfo) => {
			await arrangeCards();
			const posts = countPosts(page);
			await open(page, phone);

			await picks(page)
				.getByRole('button', { name: /^Decide B:/ })
				.click();

			const strip = page.locator('.strip');
			await expect(strip).toHaveCount(1);
			await expect(strip).toContainText('B — Browser-Sprung bleibt · Sprung');
			await expect(strip.getByRole('img', { name: 'Decided' })).toBeVisible();
			await expect(strip.getByRole('button', { name: 'Undo', exact: true })).toBeVisible();
			await expect(strip).toHaveCSS('background-color', 'rgb(228, 242, 234)');
			await page.locator('.question-pane').evaluate((pane) => {
				pane.scrollTop = 0;
			});
			const stripEdges = await edges(strip);
			const frameEdges = await edges(page.locator('.option-card .frame'));
			const headerEdges = await edges(page.locator('.top'));
			expectNear(stripEdges.left, frameEdges.left);
			expectNear(frameEdges.top - stripEdges.bottom, 16);
			expectNear(stripEdges.top - headerEdges.bottom, phone ? 12 : 24);
			await shoot(page, testInfo, 'strip-card');

			await page
				.locator('.option-card button[aria-expanded]')
				.filter({ hasText: /Song bleibt offen/ })
				.click();
			await page.locator('.question-pane').evaluate((pane) => {
				pane.scrollTop = pane.scrollHeight;
			});
			await expect(strip).toBeInViewport({ ratio: 1 });

			if (phone) {
				await page.getByRole('button', { name: '‹ Open' }).click();
				await expect(strip).toBeVisible();
				const listEdges = await edges(page.locator('.tracks'));
				expect((await edges(strip)).bottom).toBeLessThanOrEqual(listEdges.top + 1);
				await shoot(page, testInfo, 'strip-list');
				expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
					viewport.width
				);
				await strip.getByRole('button', { name: 'Undo', exact: true }).click();
				await expect(strip).toHaveCount(0);
				await expect(page.locator('.tracks')).toBeFocused();
			} else {
				await strip.getByRole('button', { name: 'Undo', exact: true }).click();
				await expect(strip).toHaveCount(0);
			}
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);
			expect(posts.count()).toBe(0);
		});

		test('[ABRD-58] two picks on two option cards show two strips in pick order and Undo on the first cancels only the first', async ({
			page
		}) => {
			await arrangeCards();
			const posted: string[] = [];
			page.on('request', (request) => {
				if (request.method() === 'POST') posted.push(request.postDataJSON().lines[0].option);
			});
			await open(page, phone);

			await picks(page)
				.getByRole('button', { name: /^Decide A:/ })
				.click();
			if (phone) await page.getByRole('button', { name: '‹ Open' }).click();
			await page.locator('.tracks').getByTitle(OTHER_QUESTION).click();
			await picks(page)
				.getByRole('button', { name: /^Decide B:/ })
				.click();

			const strips = page.locator('.strip');
			await expect(strips).toHaveCount(2);
			await expect(strips.first()).toContainText('A — Song bleibt offen');
			await expect(strips.last()).toContainText('B — Browser-Sprung bleibt');
			const first = await edges(strips.first());
			const second = await edges(strips.last());
			expectNear(second.top - first.bottom, 8);
			if (phone) {
				await page.getByRole('button', { name: '‹ Open' }).click();
				expect((await edges(strips.last())).bottom).toBeLessThanOrEqual(
					(await edges(page.locator('.tracks'))).top + 1
				);
			}

			await strips.first().getByRole('button', { name: 'Undo', exact: true }).click();
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);

			expect(posted).toEqual(['B']);
		});

		if (phone) {
			for (const width of [390, 320]) {
				test(`[ABRD-58] Undo keeps its full width beside a long topic at ${width}px`, async ({
					page
				}) => {
					await arrangeCards({ topic: 'Ein sehr langes Thema '.repeat(8).trim() });
					await page.setViewportSize({ width, height: 844 });
					await open(page, phone);

					await picks(page)
						.getByRole('button', { name: /^Decide A:/ })
						.click();

					const undo = page.locator('.strip').getByRole('button', { name: 'Undo', exact: true });
					const undoEdges = await edges(undo);
					expect(undoEdges.right - undoEdges.left).toBeGreaterThanOrEqual(40);
					expect(undoEdges.right).toBeLessThanOrEqual(width);
					expect(
						await page.locator('.strip .tx').evaluate((text) => text.scrollWidth > text.clientWidth)
					).toBe(true);
					expect(
						await page.evaluate(() => document.documentElement.scrollWidth)
					).toBeLessThanOrEqual(width);
				});
			}
		}

		test('[ABRD-45] a card changed before the post shows the changed sentence and decides only after Neu laden', async ({
			page
		}, testInfo) => {
			await arrangeCards();
			await open(page, phone);

			await picks(page)
				.getByRole('button', { name: /^Decide A:/ })
				.click();
			await arrangeCards({ problem: CHANGED_PROBLEM });
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);

			await expect(page.getByRole('alert')).toHaveText(LINE_CHANGED_MESSAGE);
			await expect(picks(page)).toHaveCount(0);
			await shoot(page, testInfo, 'changed');
			await page.getByRole('button', { name: 'Neu laden' }).click();
			await expect(page.getByRole('alert')).toHaveCount(0);
			await expect(picks(page).getByRole('button', { name: /^Decide A:/ })).toBeEnabled();
			await expect(page.locator('.stage')).toBeFocused();
		});

		test('[ABRD-45] a card ruled elsewhere answers already ruled instead of a second write', async ({
			page
		}) => {
			await arrangeCards();
			await open(page, phone);

			await picks(page)
				.getByRole('button', { name: /^Decide A:/ })
				.click();
			await arrangeCards({ ruling: 'B', ruled_on: '2026-10-01', via: 'chat' });
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);

			await expect(page.getByRole('alert')).toHaveText(ALREADY_RULED_MESSAGE);
			await expect(picks(page)).toHaveCount(0);
			await expect(page.getByRole('button', { name: 'Neu laden' })).toBeVisible();
		});

		test('[ABRD-44] the Decide row stays in view above a card taller than the pane', async ({
			page
		}) => {
			await arrangeCards();
			await open(page, phone);

			await page
				.locator('.option-card button[aria-expanded]')
				.filter({ hasText: /Song bleibt offen/ })
				.click();
			await page.locator('.question-pane').evaluate((pane) => {
				pane.scrollTop = 0;
			});
			await expect(picks(page)).toBeInViewport({ ratio: 1 });
		});

		test('[ABRD-59] Tab reaches the picks in letter order, Enter on a pick focuses its Undo and Enter again undoes it', async ({
			page
		}) => {
			await arrangeCards();
			const posts = countPosts(page);
			await open(page, phone);
			const undo = page.getByRole('button', { name: 'Undo', exact: true });

			await page
				.locator('.option-card button[aria-expanded]')
				.filter({ hasText: /Browser-Sprung bleibt/ })
				.focus();
			await page.keyboard.press('Tab');
			await expect(picks(page).getByRole('button', { name: /^Decide A:/ })).toBeFocused();
			await page.keyboard.press('Tab');
			await expect(picks(page).getByRole('button', { name: /^Decide B:/ })).toBeFocused();
			await page.keyboard.press('Enter');
			await expect(undo).toBeFocused();
			await expect(picks(page).getByRole('button', { name: /^Decide B:/ })).toBeDisabled();

			await page.keyboard.press('Enter');
			await expect(page.locator('.strip')).toHaveCount(0);
			await expect(page.locator('.stage')).toBeFocused();
			await expect(picks(page).getByRole('button', { name: /^Decide B:/ })).toBeEnabled();
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);
			expect(posts.count()).toBe(0);
		});

		test('[ABRD-59] a window that ends in a refused post leaves focus on the stage, not on the page', async ({
			page
		}) => {
			await arrangeCards();
			await page.route('**/api/rule', (route) =>
				route.fulfill({ status: 503, body: 'Unavailable' })
			);
			await open(page, phone);

			await picks(page)
				.getByRole('button', { name: /^Decide B:/ })
				.focus();
			await page.keyboard.press('Enter');
			await expect(page.getByRole('button', { name: 'Undo', exact: true })).toBeFocused();
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);

			await expect(page.locator('.strip')).toHaveCount(0);
			await expect(page.locator('.stage')).toBeFocused();
		});

		test('[ABRD-59] an older window that ends in a refused post, while a newer pick stays pending, leaves focus on the stage', async ({
			page
		}) => {
			await arrangeCards();
			await page.route('**/api/rule', (route) =>
				route.fulfill({ status: 503, body: 'Unavailable' })
			);
			await open(page, phone);

			await picks(page)
				.getByRole('button', { name: /^Decide A:/ })
				.click();
			await page.clock.runFor(5000);
			if (phone) await page.getByRole('button', { name: '‹ Open' }).click();
			await page.locator('.tracks').getByTitle(OTHER_QUESTION).click();
			await picks(page)
				.getByRole('button', { name: /^Decide B:/ })
				.focus();
			await page.keyboard.press('Enter');
			const strips = page.locator('.strip');
			await expect(strips).toHaveCount(2);
			await expect(strips.last().getByRole('button', { name: 'Undo', exact: true })).toBeFocused();
			await page.keyboard.press('Shift+Tab');
			await expect(strips.first().getByRole('button', { name: 'Undo', exact: true })).toBeFocused();
			await page.clock.runFor((UNDO_SECONDS - 5) * 1000 + 500);

			await expect(strips).toHaveCount(1);
			await expect(strips.first()).toContainText('B — Browser-Sprung bleibt');
			// Short timeout: the newer window must still be open when focus is judged.
			await expect(page.locator('.stage')).toBeFocused({ timeout: 1000 });
		});

		test('[ABRD-59] a window that ends with focus on Undo leaves focus on the stage, not on the page', async ({
			page
		}) => {
			await arrangeCards();
			await open(page, phone);

			await picks(page)
				.getByRole('button', { name: /^Decide B:/ })
				.focus();
			await page.keyboard.press('Enter');
			await expect(page.getByRole('button', { name: 'Undo', exact: true })).toBeFocused();
			const ruled = page.waitForResponse('**/api/rule');
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);

			await expect(page.locator('.strip')).toHaveCount(0);
			await expect(page.locator('.stage')).toBeFocused();
			// The post outlives the strip; let it land before the next test arranges the board.
			await ruled;
		});

		test('[ABRD-44] a ruled card inside an open picture dialog leaves the stage focused', async ({
			page
		}) => {
			await arrangeCards();
			await open(page, phone);

			await picks(page)
				.getByRole('button', { name: /^Decide B:/ })
				.click();
			await page.locator('.option-card').getByRole('button', { name: 'Enlarge picture' }).click();
			await expect(page.getByRole('dialog')).toBeVisible();
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);

			await expect(page.getByRole('dialog')).toHaveCount(0);
			if (!phone) await expect(page.locator('.stage')).toBeFocused();
		});

		test('[ABRD-46] a final pick asks first and Decide B starts the undo window', async ({
			page
		}, testInfo) => {
			await arrangeFinal();
			const posts = countPosts(page);
			await open(page, phone);

			await picks(page)
				.getByRole('button', { name: /^Decide B:/ })
				.click();

			await expect(confirm(page)).toBeVisible();
			await expect(confirm(page).locator('.cline')).toHaveText('Nicht rückholbar.');
			await expect(confirm(page).locator('.cline svg')).toBeVisible();
			await expect(confirm(page).getByRole('button')).toHaveText(['Cancel', 'Decide B']);
			await expect(confirm(page).getByRole('button', { name: 'Cancel' })).toBeFocused();
			expect(posts.count()).toBe(0);
			await expect(page.getByRole('button', { name: 'Undo', exact: true })).toHaveCount(0);
			await shoot(page, testInfo, 'confirm');
			await dialogInsideViewport(page, viewport.width);

			await confirm(page).getByRole('button', { name: 'Decide B' }).click();
			await expect(confirm(page)).toHaveCount(0);
			await expect(page.locator('.strip')).toContainText('B — Browser-Sprung bleibt · Sprung');
			await expect(page.getByRole('button', { name: 'Undo', exact: true })).toBeFocused();
			await expect(picks(page).getByRole('button', { name: /^Decide A:/ })).toBeDisabled();
			await expect(picks(page).getByRole('button', { name: /^Decide B:/ })).toBeDisabled();
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);

			if (phone) await page.getByRole('button', { name: '‹ Open' }).click();
			await page.getByRole('button', { name: /^Decided \d+$/ }).click();
			await expect(decidedList(page).getByRole('button')).toHaveCount(1);
			await decidedList(page).getByTitle(SONG_QUESTION, { exact: true }).click();
			await expectDecidedAnswer(page, 'B — Browser-Sprung bleibt', BOARD_PICK_HOW);
		});

		for (const [key, close] of [
			['Cancel', (page: Page) => confirm(page).getByRole('button', { name: 'Cancel' }).click()],
			['Esc', (page: Page) => page.keyboard.press('Escape')]
		] as const) {
			test(`[ABRD-47] ${key} closes the confirm, posts nothing and returns focus to the pick`, async ({
				page
			}) => {
				await arrangeFinal();
				const posts = countPosts(page);
				await open(page, phone);
				const pickB = picks(page).getByRole('button', { name: /^Decide B:/ });

				await pickB.click();
				await expect(confirm(page)).toBeVisible();
				await close(page);

				await expect(confirm(page)).toHaveCount(0);
				await expect(pickB).toBeFocused();
				await expect(pickB).toBeEnabled();
				await expect(picks(page).getByRole('button', { name: /^Decide A:/ })).toBeEnabled();
				await page.clock.runFor(PAST_UNDO_WINDOW_MS);
				expect(posts.count()).toBe(0);
				await expect(
					page.locator('.option-card').getByRole('heading', { name: SONG_QUESTION })
				).toBeVisible();
			});
		}

		test('[ABRD-46] Enter on the pick opens the confirm on Cancel and a second Enter cancels', async ({
			page
		}) => {
			await arrangeFinal();
			const posts = countPosts(page);
			await open(page, phone);
			const pickB = picks(page).getByRole('button', { name: /^Decide B:/ });

			await pickB.focus();
			await page.keyboard.press('Enter');
			await expect(confirm(page).getByRole('button', { name: 'Cancel' })).toBeFocused();
			await page.keyboard.press('Enter');

			await expect(confirm(page)).toHaveCount(0);
			await expect(pickB).toBeFocused();
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);
			expect(posts.count()).toBe(0);
		});

		test('[ABRD-44] a reversible pick on a card with a final option opens no confirm', async ({
			page
		}) => {
			await arrangeFinal();
			await open(page, phone);

			await picks(page)
				.getByRole('button', { name: /^Decide A:/ })
				.click();

			await expect(page.getByRole('dialog')).toHaveCount(0);
			await expect(page.locator('.strip')).toContainText('A — Song bleibt offen · Sprung');
		});
	});
}

test.describe('1280px confirm over a changing board', () => {
	test.use({ viewport: { width: 1280, height: 900 } });

	test('[ABRD-47] a card changed under the open confirm is refused as changed, not decided', async ({
		page
	}) => {
		await arrangeFinal();
		await open(page, false, OTHER_QUESTION);
		await picks(page)
			.getByRole('button', { name: /^Decide B:/ })
			.click();
		await page.locator('.tracks').getByTitle(SONG_QUESTION).click();
		await picks(page)
			.getByRole('button', { name: /^Decide B:/ })
			.click();
		await expect(confirm(page)).toBeVisible();

		await arrangeFinal({ problem: CHANGED_PROBLEM });
		const answered = page.waitForResponse(
			(response) => response.url().endsWith('/api/rule') && response.request().method() === 'POST'
		);
		await page.clock.runFor(PAST_UNDO_WINDOW_MS);
		await answered;
		// The modal makes the page inert, so the board is read by CSS, not by role.
		await expect(page.locator('.tracks').getByTitle(OTHER_QUESTION)).toHaveCount(0);
		await expect(confirm(page)).toBeVisible();
		await confirm(page).getByRole('button', { name: 'Decide B' }).click();
		await page.clock.runFor(PAST_UNDO_WINDOW_MS);

		await expect(page.getByRole('alert')).toContainText(LINE_CHANGED_MESSAGE);
		await expect(page.getByRole('button', { name: 'Neu laden' })).toBeVisible();
		await page.getByRole('button', { name: /^Decided \d+$/ }).click();
		const rows = decidedList(page).getByRole('button');
		await expect(rows).toHaveCount(1);
		await expect(decidedList(page).getByTitle(SONG_QUESTION, { exact: true })).toHaveCount(0);
	});

	test('[ABRD-47] a slow POST leaves the open confirm usable: Cancel keeps focus and Escape returns it to the pick', async ({
		page
	}) => {
		await arrangeFinal();
		await open(page, false, OTHER_QUESTION);
		await picks(page)
			.getByRole('button', { name: /^Decide B:/ })
			.click();
		await page.locator('.tracks').getByTitle(SONG_QUESTION).click();
		const pickB = picks(page).getByRole('button', { name: /^Decide B:/ });
		await pickB.click();
		await expect(confirm(page)).toBeVisible();

		let release: (() => void) | undefined;
		const held = new Promise<void>((resolve) => {
			release = resolve;
		});
		await page.route('**/api/rule', async (route) => {
			await held;
			return route.continue();
		});
		try {
			const posted = page.waitForRequest(
				(request) => request.url().endsWith('/api/rule') && request.method() === 'POST'
			);
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);
			await posted;

			await expect(confirm(page)).toBeVisible();
			await expect(confirm(page).getByRole('button', { name: 'Cancel' })).toBeFocused();
			await page.keyboard.press('Escape');
			await expect(page.getByRole('dialog')).toHaveCount(0);
			await expect(pickB).toBeFocused();
		} finally {
			release?.();
		}
	});
});
