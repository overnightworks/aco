import type { Locator, Page } from '@playwright/test';
import { expect, test } from './consoleGuard';
import {
	optionLine,
	row,
	writeRulings,
	type OptionRulingLine,
	type RulingOption
} from './rulingsFixture';
import { readBoardRuntime } from './runtime';
import {
	ALREADY_RULED_MESSAGE,
	LINE_CHANGED_MESSAGE,
	UNDO_SECONDS
} from '../src/app/model/decision';

// One shared board server backs every test in this file (see
// global-setup.ts); each test overwrites the whole of rulings.json.
test.describe.configure({ mode: 'serial' });

// Just past the app's undo window; the page clock is driven, never waited.
const PAST_UNDO_WINDOW_MS = UNDO_SECONDS * 1000 + 500;

// The fake aco stamps every ruling with this date (`aco_board_fixtures`).
const FAKE_RULING_DATE = '2026-10-03';

const SONG_QUESTION = 'Soll der Song beim Sprung offen bleiben?';
const OTHER_QUESTION = 'Welcher Weg für die Altdaten?';

const SONG_OPTIONS: RulingOption[] = [
	{
		letter: 'A',
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
		letter: 'B',
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

function songCard(overrides: Partial<OptionRulingLine> = {}): OptionRulingLine {
	return optionLine(1, 'Der Song bleibt beim Sprung offen.', {
		question: SONG_QUESTION,
		problem: 'Der Link schließt den Song.',
		caption: 'Der Browser springt selbst.',
		area: 'Song-Seite',
		topic: 'Sprung',
		recommended: 'A',
		reason: 'Behebt den Verlust.',
		options: SONG_OPTIONS,
		...overrides
	});
}

function arrange(directory: string, song: Partial<OptionRulingLine> = {}): void {
	writeRulings(directory, [
		row(
			2001,
			'Sprung',
			songCard(song),
			optionLine(2, 'Eine zweite offene Frage.', {
				question: OTHER_QUESTION,
				recommended: 'B',
				options: SONG_OPTIONS
			})
		)
	]);
}

const FINAL_OPTIONS: RulingOption[] = [
	SONG_OPTIONS[0],
	{ ...SONG_OPTIONS[1], undo: 'final', undo_how: 'nicht rückholbar.' }
];

function arrangeFinal(directory: string, song: Partial<OptionRulingLine> = {}): void {
	arrange(directory, { options: FINAL_OPTIONS, ...song });
}

function confirm(page: Page): Locator {
	return page.getByRole('dialog', { name: 'Decide B?' });
}

function countPosts(page: Page): { count(): number } {
	let posts = 0;
	page.on('request', (request) => {
		if (request.method() === 'POST') posts += 1;
	});
	return { count: () => posts };
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

async function open(page: Page, phone: boolean, question = SONG_QUESTION): Promise<void> {
	const { appUrl, token } = readBoardRuntime();
	await page.clock.install();
	await page.goto(`${appUrl}#t=${token}`);
	await page.locator('.tracks').getByTitle(question).click();
	if (phone) await expect(page.locator('.question-pane')).toBeVisible();
}

function picks(page: Page): Locator {
	return page.getByRole('group', { name: 'Decide' });
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

		test('[ABRD-44] a pick waits out the undo window, then the card moves to Verlauf', async ({
			page
		}, testInfo) => {
			const { repoDirectory } = readBoardRuntime();
			arrange(repoDirectory);
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
			await expect(page.locator('.toasts')).toContainText('B — Browser-Sprung bleibt · Sprung');
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
			await page.getByRole('button', { name: 'Verlauf', exact: true }).click();
			const entry = page.getByRole('region', { name: 'Verlauf' }).locator('summary');
			await expect(entry).toHaveCount(1);
			await expect(entry).toContainText(SONG_QUESTION);
			await expect(entry).toContainText('B · Browser-Sprung bleibt');
			await expect(entry).toContainText(FAKE_RULING_DATE);
			expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
				viewport.width
			);
		});

		test('[ABRD-33] Rückgängig inside the window posts nothing and leaves the picks usable', async ({
			page
		}) => {
			const { repoDirectory } = readBoardRuntime();
			arrange(repoDirectory);
			let writes = 0;
			page.on('request', (request) => {
				if (request.method() === 'POST') writes += 1;
			});
			await open(page, phone);

			await picks(page)
				.getByRole('button', { name: /^Decide A:/ })
				.click();
			await page.getByRole('button', { name: 'Rückgängig' }).click();
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);

			expect(writes).toBe(0);
			await expect(
				page.locator('.option-card').getByRole('heading', { name: SONG_QUESTION })
			).toBeVisible();
			await expect(picks(page).getByRole('button')).toHaveText(['A', 'B']);
			await expect(picks(page).getByRole('button', { name: /^Decide A:/ })).toBeEnabled();
			await page.getByRole('button', { name: 'Verlauf', exact: true }).click();
			await expect(page.getByRole('region', { name: 'Verlauf' }).locator('summary')).toHaveCount(0);
		});

		test('[ABRD-45] a card changed before the post shows the changed sentence and decides only after Neu laden', async ({
			page
		}, testInfo) => {
			const { repoDirectory } = readBoardRuntime();
			arrange(repoDirectory);
			await open(page, phone);

			await picks(page)
				.getByRole('button', { name: /^Decide A:/ })
				.click();
			arrange(repoDirectory, { card_hash: 'card-hash-changed' });
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
			const { repoDirectory } = readBoardRuntime();
			arrange(repoDirectory);
			await open(page, phone);

			await picks(page)
				.getByRole('button', { name: /^Decide A:/ })
				.click();
			arrange(repoDirectory, { ruling: 'B', ruled_on: '2026-10-01' });
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);

			await expect(page.getByRole('alert')).toHaveText(ALREADY_RULED_MESSAGE);
			await expect(picks(page)).toHaveCount(0);
			await expect(page.getByRole('button', { name: 'Neu laden' })).toBeVisible();
		});

		test('[ABRD-44] the Decide row stays in view above a card taller than the pane', async ({
			page
		}) => {
			const { repoDirectory } = readBoardRuntime();
			arrange(repoDirectory);
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

		test('[ABRD-44] Tab reaches the picks in letter order after the options and Enter starts the window', async ({
			page
		}) => {
			const { repoDirectory } = readBoardRuntime();
			arrange(repoDirectory);
			await open(page, phone);

			await page
				.locator('.option-card button[aria-expanded]')
				.filter({ hasText: /Browser-Sprung bleibt/ })
				.focus();
			await page.keyboard.press('Tab');
			await expect(picks(page).getByRole('button', { name: /^Decide A:/ })).toBeFocused();
			await page.keyboard.press('Tab');
			await expect(picks(page).getByRole('button', { name: /^Decide B:/ })).toBeFocused();
			await page.keyboard.press('Enter');
			await expect(page.getByRole('button', { name: 'Rückgängig' })).toBeVisible();
			await expect(picks(page).getByRole('button', { name: /^Decide B:/ })).toBeDisabled();
		});

		test('[ABRD-44] a ruled card inside an open picture dialog leaves the stage focused', async ({
			page
		}) => {
			const { repoDirectory } = readBoardRuntime();
			arrange(repoDirectory);
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
			const { repoDirectory } = readBoardRuntime();
			arrangeFinal(repoDirectory);
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
			await expect(page.getByRole('button', { name: 'Rückgängig' })).toHaveCount(0);
			await shoot(page, testInfo, 'confirm');
			await dialogInsideViewport(page, viewport.width);

			await confirm(page).getByRole('button', { name: 'Decide B' }).click();
			await expect(confirm(page)).toHaveCount(0);
			await expect(page.locator('.toasts')).toContainText('B — Browser-Sprung bleibt · Sprung');
			await expect(picks(page).getByRole('button', { name: /^Decide A:/ })).toBeDisabled();
			await expect(picks(page).getByRole('button', { name: /^Decide B:/ })).toBeDisabled();
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);

			await page.getByRole('button', { name: 'Verlauf', exact: true }).click();
			const entry = page.getByRole('region', { name: 'Verlauf' }).locator('summary');
			await expect(entry).toHaveCount(1);
			await expect(entry).toContainText(SONG_QUESTION);
			await expect(entry).toContainText('B · Browser-Sprung bleibt');
		});

		for (const [key, close] of [
			['Cancel', (page: Page) => confirm(page).getByRole('button', { name: 'Cancel' }).click()],
			['Esc', (page: Page) => page.keyboard.press('Escape')]
		] as const) {
			test(`[ABRD-47] ${key} closes the confirm, posts nothing and returns focus to the pick`, async ({
				page
			}) => {
				const { repoDirectory } = readBoardRuntime();
				arrangeFinal(repoDirectory);
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
			const { repoDirectory } = readBoardRuntime();
			arrangeFinal(repoDirectory);
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
			const { repoDirectory } = readBoardRuntime();
			arrangeFinal(repoDirectory);
			await open(page, phone);

			await picks(page)
				.getByRole('button', { name: /^Decide A:/ })
				.click();

			await expect(page.getByRole('dialog')).toHaveCount(0);
			await expect(page.locator('.toasts')).toContainText('A — Song bleibt offen · Sprung');
		});
	});
}

test.describe('1280px confirm over a changing board', () => {
	test.use({ viewport: { width: 1280, height: 900 } });

	test('[ABRD-47] a card changed under the open confirm is refused as changed, not decided', async ({
		page
	}) => {
		const { repoDirectory } = readBoardRuntime();
		arrangeFinal(repoDirectory);
		await open(page, false, OTHER_QUESTION);
		await picks(page)
			.getByRole('button', { name: /^Decide B:/ })
			.click();
		await page.locator('.tracks').getByTitle(SONG_QUESTION).click();
		await picks(page)
			.getByRole('button', { name: /^Decide B:/ })
			.click();
		await expect(confirm(page)).toBeVisible();

		arrangeFinal(repoDirectory, { card_hash: 'card-hash-changed' });
		const reloaded = page.waitForResponse(
			(response) => response.url().endsWith('/api/board') && response.request().method() === 'GET'
		);
		await page.clock.runFor(PAST_UNDO_WINDOW_MS);
		await reloaded;
		// The modal makes the page inert, so the board is read by CSS, not by role.
		await expect(page.locator('.tracks').getByTitle(OTHER_QUESTION)).toHaveCount(0);
		await expect(confirm(page)).toBeVisible();
		await confirm(page).getByRole('button', { name: 'Decide B' }).click();
		await page.clock.runFor(PAST_UNDO_WINDOW_MS);

		await expect(page.getByRole('alert')).toContainText(LINE_CHANGED_MESSAGE);
		await expect(page.getByRole('button', { name: 'Neu laden' })).toBeVisible();
		await page.getByRole('button', { name: 'Verlauf', exact: true }).click();
		const entries = page.getByRole('region', { name: 'Verlauf' }).locator('summary');
		await expect(entries).toHaveCount(1);
		await expect(entries).not.toContainText(SONG_QUESTION);
	});

	test('[ABRD-47] a slow background reload leaves the open confirm usable: Cancel keeps focus and Escape returns it to the pick', async ({
		page
	}) => {
		const { repoDirectory } = readBoardRuntime();
		arrangeFinal(repoDirectory);
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
		await page.route('**/api/board', async (route) => {
			if (route.request().method() !== 'GET') return route.continue();
			await held;
			return route.continue();
		});
		try {
			const reload = page.waitForRequest(
				(request) => request.url().endsWith('/api/board') && request.method() === 'GET'
			);
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);
			await reload;

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
