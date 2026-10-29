import type { Page } from '@playwright/test';
import { expect, test } from './consoleGuard';
import { decidedCard, expectDecidedAnswer, openDecidedLine } from './decidedView';
import {
	line,
	optionLine,
	row,
	writeRulings,
	type OptionRulingLine,
	type RulingOption
} from './rulingsFixture';
import { readBoardRuntime } from './runtime';
import { UNDO_SECONDS } from '../src/app/model/decision';

// One shared board server backs every test in this file (see
// global-setup.ts); each test overwrites the whole of rulings.json, so
// tests stay isolated from one another despite the shared process.
test.describe.configure({ mode: 'serial' });

// Just past the app's undo window; the page clock is driven, never waited.
const PAST_UNDO_WINDOW_MS = UNDO_SECONDS * 1000 + 500;

function choices(page: Page) {
	return page.getByRole('group', { name: 'Entscheidung' });
}

// The fake aco stores every board pick as `--via board` on this date
// (`aco_board_fixtures`); the decided card's How row reads it back.
const BOARD_PICK_HOW = 'Board · 03.10.2026';

const OPTIONS: RulingOption[] = [
	{
		letter: 'A',
		name: 'Erster Weg',
		effect: 'Der erste Weg gilt.',
		same_as_today: true,
		notice: 'Du merkst nichts.',
		cost: 'Mehr Code.',
		undo: 'reversible',
		undo_how: 'jederzeit',
		contract: 'Der erste Weg gilt.'
	},
	{
		letter: 'B',
		name: 'Zweiter Weg',
		effect: 'Der zweite Weg gilt.',
		same_as_today: true,
		notice: 'Du merkst es.',
		cost: 'Weniger Code.',
		undo: 'reversible',
		undo_how: 'jederzeit',
		contract: 'Der zweite Weg gilt.'
	}
];

function card(index: number, question: string, overrides: Partial<OptionRulingLine> = {}) {
	return optionLine(index, `Satz ${index}`, { question, options: OPTIONS, ...overrides });
}

function picks(page: Page) {
	return page.getByRole('group', { name: 'Decide' });
}

function pick(page: Page, letter: 'A' | 'B') {
	return picks(page).getByRole('button', { name: new RegExp(`^Decide ${letter}:`) });
}

function listRow(page: Page, question: string) {
	return page.locator('.tracks').getByTitle(question);
}

function countPosts(page: Page): { count(): number } {
	let posts = 0;
	page.on('request', (request) => {
		if (request.method() === 'POST') posts += 1;
	});
	return { count: () => posts };
}

async function arrangeLongRepositoryLists(page: Page, directory: string, longWord: string) {
	writeRulings(
		directory,
		Array.from({ length: 12 }, (_, index) =>
			row(
				700 + index,
				`Vorhaben ${index} ${longWord}`,
				card(1, `Frage ${index}?`, {
					text: `Satz ${index} ${longWord}`,
					problem: `${longWord}\n${'Vollständiges Problem. '.repeat(80)}`,
					options: OPTIONS.map((option) => ({ ...option, effect: longWord })),
					picture:
						'<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="120"><rect width="1200" height="120" fill="#8a2a63"/></svg>'
				})
			)
		)
	);
	await page.route('**/api/board', async (route) => {
		const response = await route.fetch();
		const board = await response.json();
		await route.fulfill({
			json: {
				repos: Array.from({ length: 8 }, (_, index) => ({
					...board.repos[0],
					name: `repo-${index}`
				}))
			}
		});
	});
}

async function expectReturnAndResizeFocus(
	page: Page,
	viewport: { width: number; height: number },
	scrollPosition: number
) {
	const tracks = page.locator('.tracks');
	const selected = tracks.getByRole('button').last();
	if (viewport.width === 390) {
		await page.getByRole('button', { name: '‹ Open' }).click();
		await expect(selected).toBeFocused();
		await expect.poll(() => tracks.evaluate((element) => element.scrollTop)).toBe(scrollPosition);
		await expect(selected).toHaveAttribute('aria-current', 'true');
		await page.setViewportSize({ width: 1280, height: 900 });
		await page.getByRole('button', { name: 'Other…' }).focus();
		await page.setViewportSize(viewport);
		await expect(tracks).toBeFocused();
	} else {
		await selected.focus();
		await page.setViewportSize({ width: 390, height: 844 });
		await expect(page.locator('.stage')).toBeFocused();
	}
}

test('reactivating the selected desktop row restores the question heading and focus', async ({
	page
}, testInfo) => {
	const { appUrl, token, repoDirectory } = readBoardRuntime();
	await page.setViewportSize({ width: 1280, height: 900 });
	writeRulings(repoDirectory, [
		row(950, 'Reselection', card(1, 'First?', { problem: 'Long problem. '.repeat(500) }))
	]);
	await page.goto(`${appUrl}#t=${token}`);
	const selected = listRow(page, 'First?');
	await selected.click();
	await expect(page.locator('.stage')).toBeFocused();
	// The stage's tab stops before the first pick: the picture, then the two option disclosures.
	for (let stop = 0; stop < 4; stop += 1) await page.keyboard.press('Tab');
	await expect(pick(page, 'A')).toBeFocused();
	await expect
		.poll(() => page.locator('.question-pane').evaluate((pane) => pane.scrollTop))
		.toBeGreaterThan(0);
	await selected.focus();
	await page.keyboard.press('Enter');
	await expect(page.locator('.stage')).toBeFocused();
	await expect(page.getByRole('heading', { name: 'First?', exact: true })).toBeInViewport();
	await expect
		.poll(() => page.locator('.question-pane').evaluate((pane) => pane.scrollTop))
		.toBe(0);
	await page.screenshot({ path: testInfo.outputPath('reselected.png') });
});

test('advancing after phone list return and desktop resize focuses the next question', async ({
	page
}, testInfo) => {
	const { appUrl, token, repoDirectory } = readBoardRuntime();
	await page.setViewportSize({ width: 390, height: 844 });
	writeRulings(repoDirectory, [
		row(951, 'Resize', card(1, 'First?', { problem: 'Long problem. '.repeat(500) })),
		row(961, 'Resize second', card(1, 'Second?', { problem: 'Long problem. '.repeat(500) }))
	]);
	await page.clock.install();
	await page.goto(`${appUrl}#t=${token}`);
	await listRow(page, 'First?').click();
	await page.getByRole('button', { name: '‹ Open' }).click();
	await page.screenshot({ path: testInfo.outputPath('phone-return.png') });
	await page.setViewportSize({ width: 1280, height: 900 });
	await pick(page, 'A').click();
	await page.clock.runFor(PAST_UNDO_WINDOW_MS);
	await expect(page.getByRole('heading', { name: 'Second?', exact: true })).toBeInViewport();
	await expect(page.locator('.stage')).toBeFocused();
	await page.screenshot({ path: testInfo.outputPath('resized-advance.png') });
});

test('desktop completion preserves deliberately focused other list row', async ({
	page
}, testInfo) => {
	const { appUrl, token, repoDirectory } = readBoardRuntime();
	await page.setViewportSize({ width: 1280, height: 900 });
	writeRulings(repoDirectory, [
		row(954, 'Desktop completion', card(1, 'First?', { problem: 'Long problem. '.repeat(500) })),
		row(
			964,
			'Desktop completion second',
			card(1, 'Second?', { problem: 'Long problem. '.repeat(500) })
		),
		row(974, 'Desktop completion third', card(1, 'Third?'))
	]);
	await page.clock.install();
	await page.goto(`${appUrl}#t=${token}`);
	await listRow(page, 'First?').click();
	await page.locator('.question-pane').evaluate((pane) => {
		pane.scrollTop = pane.scrollHeight;
	});
	await pick(page, 'A').click();
	await expect
		.poll(() => page.locator('.question-pane').evaluate((pane) => pane.scrollTop))
		.toBeGreaterThan(0);
	const third = listRow(page, 'Third?');
	await third.focus();
	await expect(third).toBeFocused();
	await page.clock.runFor(PAST_UNDO_WINDOW_MS);
	await expect(listRow(page, 'Second?')).toHaveAttribute('aria-current', 'true');
	await expect(listRow(page, 'First?')).toHaveCount(0);
	await expect(third).toBeFocused();
	await expect(third).toBeInViewport();
	await expect(page.getByRole('heading', { name: 'Second?', exact: true })).toBeInViewport();
	await expect
		.poll(() => page.locator('.question-pane').evaluate((pane) => pane.scrollTop))
		.toBe(0);
	await page.screenshot({ path: testInfo.outputPath('desktop-other-focus.png') });
});

for (const scenario of ['next question', 'exhausted list', 'focus elsewhere']) {
	test(`phone list completion keeps visible focus: ${scenario}`, async ({ page }, testInfo) => {
		const { appUrl, token, repoDirectory } = readBoardRuntime();
		await page.setViewportSize({ width: 390, height: 844 });
		const rows = [row(952, 'List completion', card(1, 'First?'))];
		if (scenario !== 'exhausted list') {
			rows.push(row(962, 'List completion second', card(1, 'Second?')));
		}
		writeRulings(repoDirectory, rows);
		await page.clock.install();
		await page.goto(`${appUrl}#t=${token}`);
		const first = listRow(page, 'First?');
		await first.click();
		await pick(page, 'A').click();
		await page.getByRole('button', { name: '‹ Open' }).click();
		await expect(first).toBeFocused();
		const target =
			scenario === 'focus elsewhere' ? listRow(page, 'Second?') : page.locator('.tracks');
		if (scenario === 'focus elsewhere') await target.focus();
		await page.clock.runFor(PAST_UNDO_WINDOW_MS);
		await expect(first).toHaveCount(0);
		await expect(page.locator('.question-pane')).not.toBeVisible();
		await expect(target).toBeFocused();
		await expect(target).toBeInViewport();
		await page.screenshot({ path: testInfo.outputPath('list-completed.png') });
	});
}

for (const viewport of [
	{ width: 1280, height: 900 },
	{ width: 390, height: 844 }
]) {
	test.describe(`${viewport.width}px selection flow`, () => {
		test.use({ viewport });

		test('selection during a background reload reaches the question without stale actions', async ({
			page
		}, testInfo) => {
			const { appUrl, token, repoDirectory } = readBoardRuntime();
			writeRulings(repoDirectory, [
				row(953, 'Background reload', card(1, 'First?')),
				row(963, 'Background reload second', card(1, 'Second?'))
			]);
			await page.clock.install();
			await page.goto(`${appUrl}#t=${token}`);
			await listRow(page, 'First?').click();
			let release: (() => void) | undefined;
			const held = new Promise<void>((resolve) => {
				release = resolve;
			});
			await page.route('**/api/board', async (route) => {
				await held;
				await route.continue();
			});
			try {
				await pick(page, 'A').click();
				if (viewport.width === 390) await page.getByRole('button', { name: '‹ Open' }).click();
				const second = listRow(page, 'Second?');
				await second.focus();
				const reload = page.waitForRequest('**/api/board');
				await page.clock.runFor(PAST_UNDO_WINDOW_MS);
				await reload;
				await expect(second).toBeFocused();
				await second.press('Enter');
				await expect(page.getByRole('heading', { name: 'Second?', exact: true })).toBeVisible();
				await expect(picks(page).getByRole('button')).toHaveText(['A', 'B']);
				await expect(pick(page, 'A')).toHaveAttribute('aria-disabled', 'true');
				await expect(pick(page, 'B')).toHaveAttribute('aria-disabled', 'true');
				await page.screenshot({ path: testInfo.outputPath('background-loading.png') });
			} finally {
				release?.();
			}
			await expect(page.getByRole('heading', { name: 'Second?', exact: true })).toBeVisible();
			await expect(page.locator('.stage')).toBeFocused();
			await page.screenshot({ path: testInfo.outputPath('background-selected.png') });
		});

		test('access, loading, empty and error messages remain readable', async ({
			page
		}, testInfo) => {
			const { appUrl, token } = readBoardRuntime();
			await page.goto(appUrl);
			await expect(page.getByRole('alert')).toContainText('Zugang fehlt');
			await page.screenshot({ path: testInfo.outputPath('no-access.png') });
			let finishLoading: (() => void) | undefined;
			const loading = new Promise<void>((resolve) => {
				finishLoading = resolve;
			});
			await page.route('**/api/board', async (route) => {
				await loading;
				await route.fulfill({ json: { repos: [] } });
			});
			await page.goto(`${appUrl}#t=${token}`);
			await page.reload();
			await expect(page.getByRole('status')).toHaveText('Lädt…');
			await page.screenshot({ path: testInfo.outputPath('loading.png') });
			finishLoading?.();
			await expect(page.getByText('All decided')).toBeVisible();
			await page.screenshot({ path: testInfo.outputPath('empty.png') });
			await page.unroute('**/api/board');
			await page.route('**/api/board', (route) =>
				route.fulfill({ status: 503, body: 'Unavailable' })
			);
			await page.reload();
			await expect(page.getByRole('alert')).toContainText('aco antwortet nicht');
			await page.screenshot({ path: testInfo.outputPath('error.png') });
			await expect
				.poll(() => page.evaluate(() => document.documentElement.scrollWidth))
				.toBeLessThanOrEqual(viewport.width);
		});

		test('undoing within the 8 s window writes nothing, ever', async ({ page }) => {
			const { appUrl, token, repoDirectory } = readBoardRuntime();
			writeRulings(repoDirectory, [
				row(
					601,
					'Guests',
					line(1, 'Guests may join the call.', { question: 'Guests allowed?', default: 'yes' })
				)
			]);
			let ruleRequests = 0;
			page.on('request', (request) => {
				if (request.url().endsWith('/api/rule')) {
					ruleRequests += 1;
				}
			});

			await page.clock.install();
			await page.goto(`${appUrl}#t=${token}`);
			await page.getByRole('button', { name: /Guests allowed\?/ }).click();
			await choices(page).getByRole('button', { name: /Ja/ }).click();
			await page.getByRole('button', { name: 'Undo', exact: true }).click();

			// The page clock runs past the window: the undo must have cancelled the
			// write, not merely delayed it, and no real waiting is needed to prove it.
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);

			expect(ruleRequests).toBe(0);
			await expect(choices(page).getByRole('button', { name: /Ja/ })).toBeEnabled();
		});

		test('once the window elapses, exactly one decision is written', async ({ page }, testInfo) => {
			const { appUrl, token, repoDirectory } = readBoardRuntime();
			writeRulings(repoDirectory, [row(602, 'Hosts', card(1, 'Hosts allowed?'))]);
			const posts = countPosts(page);

			await page.clock.install();
			await page.goto(`${appUrl}#t=${token}`);
			await listRow(page, 'Hosts allowed?').click();
			await pick(page, 'B').click();
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);

			await expect(page.getByText('Keine Frage ausgewählt.')).toBeVisible();
			await expect(page.locator('.stage')).toBeFocused();
			await page.screenshot({ path: testInfo.outputPath('unselected.png') });
			if (viewport.width === 390) await page.getByRole('button', { name: '‹ Open' }).click();
			await openDecidedLine(page, 'Hosts allowed?');
			await expectDecidedAnswer(page, 'B — Zweiter Weg', BOARD_PICK_HOW);
			expect(posts.count()).toBe(1);
		});

		test('deciding moves the stage to the next open card, and the ruled one keeps no buttons', async ({
			page
		}) => {
			const { appUrl, token, repoDirectory } = readBoardRuntime();
			writeRulings(repoDirectory, [
				row(
					605,
					'Access',
					line(1, 'Guests may join the call.', {
						question: 'Guests allowed?',
						default: 'yes',
						example: 'Ein langes Beispiel. '.repeat(300)
					}),
					line(2, 'Hosts may close the room.', { question: 'Hosts allowed?', default: 'no' })
				)
			]);

			await page.goto(`${appUrl}#t=${token}`);
			await page.getByRole('button', { name: /Guests allowed\?/ }).click();
			await choices(page).getByRole('button', { name: /Ja/ }).click();

			await expect(page.getByRole('heading', { name: 'Hosts allowed?' })).toBeVisible({
				timeout: 10_000
			});
			await expect(choices(page).getByRole('button', { name: /Nein/ })).toBeVisible();
			await expect(page.getByRole('heading', { name: 'Hosts allowed?' })).toBeInViewport();
			await expect(page.locator('.stage')).toBeFocused();

			// The completed question is available only in the read-only Decided card.
			if (viewport.width === 390) await page.getByRole('button', { name: '‹ Open' }).click();
			await expect(page.getByRole('button', { name: /Guests allowed\?/ })).not.toBeVisible();
			await openDecidedLine(page, 'Guests allowed?');
			await expectDecidedAnswer(page, 'Ja', 'not recorded · 03.10.2026');
			await decidedCard(page).getByText('Show', { exact: true }).click();
			await expect(page.getByText('Guests may join the call.')).toBeVisible();
		});

		test('a question changed mid-undo refuses to save and asks for a reload', async ({ page }) => {
			const { appUrl, token, repoDirectory } = readBoardRuntime();
			writeRulings(repoDirectory, [
				row(
					603,
					'Changed line',
					line(1, 'Original sentence.', { question: 'Original question?', default: 'yes' })
				)
			]);

			await page.goto(`${appUrl}#t=${token}`);
			await page.getByRole('button', { name: /Original question\?/ }).click();
			await choices(page).getByRole('button', { name: /Ja/ }).click();

			// An agent reformulates the line while the operator's undo window is
			// still open; the board must refuse the stale choice once it writes.
			writeRulings(repoDirectory, [
				row(
					603,
					'Changed line',
					line(1, 'A different sentence now.', { question: 'Original question?', default: 'yes' })
				)
			]);

			await expect(page.getByText('Diese Zeile hat sich geändert, bitte neu laden')).toBeVisible({
				timeout: 10_000
			});
		});

		test('"Später" is a real, writable outcome, recommended when it is the default', async ({
			page
		}) => {
			const { appUrl, token, repoDirectory } = readBoardRuntime();
			writeRulings(repoDirectory, [
				row(
					604,
					'Deferred',
					line(1, 'This can wait a cycle.', { question: 'Deferred question?', default: 'later' })
				)
			]);

			await page.goto(`${appUrl}#t=${token}`);
			await page.getByRole('button', { name: /Deferred question\?/ }).click();
			const recommended = choices(page).getByRole('button', { name: /Später/ });
			await expect(recommended).toContainText('Empfohlen');
			await recommended.click();

			await expect(page.getByText('Keine Frage ausgewählt.')).toBeVisible({ timeout: 10_000 });
			if (viewport.width === 390) await page.getByRole('button', { name: '‹ Open' }).click();
			await openDecidedLine(page, 'Deferred question?');
			await expectDecidedAnswer(page, 'Später', 'not recorded · 03.10.2026');
		});

		test('eight long repository lists keep selection, focus and all content inside the viewport', async ({
			page
		}, testInfo) => {
			const { appUrl, token, repoDirectory } = readBoardRuntime();
			const longWord = 'Entscheidungsgrundlage'.repeat(12);
			await arrangeLongRepositoryLists(page, repoDirectory, longWord);
			const posts = countPosts(page);
			await page.goto(`${appUrl}#t=${token}`);
			if (viewport.width > 760) {
				await expect(page.getByRole('heading', { name: 'Frage 0?', exact: true })).toBeVisible();
				await page.screenshot({ path: testInfo.outputPath('initial-long.png') });
			}
			const tracks = page.locator('.tracks');
			const selected = tracks.getByRole('button').last();
			await selected.scrollIntoViewIfNeeded();
			const scrollPosition = await tracks.evaluate((element) => element.scrollTop);
			await selected.focus();
			await page.keyboard.press('Enter');
			await expect(page.getByRole('heading', { name: 'Frage 11?' })).toBeInViewport();
			await expect(page.locator('.stage')).toBeFocused();
			await pick(page, 'B').focus();
			await page.keyboard.press('Tab');
			await expect(page.getByRole('button', { name: 'Other…' })).toBeFocused();
			await page.keyboard.press('Enter');
			await expect(page.getByRole('textbox')).toBeFocused();
			await page.getByRole('textbox').fill(longWord);
			await expect(page.locator('.option-card').getByAltText('Heute').first()).toBeVisible();
			await expect
				.poll(() => page.evaluate(() => document.documentElement.scrollWidth))
				.toBeLessThanOrEqual(viewport.width);
			if (viewport.width > 760) {
				await expect
					.poll(() => tracks.evaluate((element) => element.scrollTop))
					.toBe(scrollPosition);
			}
			await page.locator('.question-pane').evaluate((element) => {
				element.scrollTop = 0;
			});
			await page.screenshot({ path: testInfo.outputPath('selected.png') });
			await pick(page, 'B').scrollIntoViewIfNeeded();
			await expect(picks(page)).toBeInViewport();
			await page.screenshot({ path: testInfo.outputPath('note.png') });
			await expectReturnAndResizeFocus(page, viewport, scrollPosition);
			expect(posts.count()).toBe(0);
		});

		test('separate undo notices stay reachable and cancel every pending write', async ({
			page
		}, testInfo) => {
			const { appUrl, token, repoDirectory } = readBoardRuntime();
			writeRulings(repoDirectory, [
				row(720, 'Erste Karte', card(1, 'Erste Frage')),
				row(721, 'Zweite Karte', card(1, 'Zweite Frage'))
			]);
			const posts = countPosts(page);
			await page.clock.install();
			await page.goto(`${appUrl}#t=${token}`);
			for (const name of ['Erste Frage', 'Zweite Frage']) {
				await listRow(page, name).click();
				await pick(page, 'A').click();
				if (viewport.width === 390) await page.getByRole('button', { name: '‹ Open' }).click();
			}
			await expect(page.getByRole('button', { name: 'Undo', exact: true })).toHaveCount(2);
			await page.screenshot({ path: testInfo.outputPath('undo.png') });
			await page.getByRole('button', { name: 'Undo', exact: true }).last().click();
			await page.getByRole('button', { name: 'Undo', exact: true }).click();
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);
			expect(posts.count()).toBe(0);
		});
	});
}
