import type { Page } from '@playwright/test';
import { expect, test } from './consoleGuard';
import { line, row, writeRulings } from './rulingsFixture';
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

async function arrangeLongRepositoryLists(page: Page, directory: string, longWord: string) {
	writeRulings(
		directory,
		Array.from({ length: 12 }, (_, index) =>
			row(
				700 + index,
				`Vorhaben ${index} ${longWord}`,
				line(1, `Satz ${index} ${longWord}`, {
					question: `Frage ${index}?`,
					example: `${longWord}\n${'Vollständiges Beispiel. '.repeat(80)}`,
					picture:
						'<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="120"><rect width="1200" height="120" fill="#8a2a63"/></svg>',
					default: 'yes'
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
		await page.getByRole('button', { name: '← Liste' }).click();
		await expect(selected).toBeFocused();
		await expect.poll(() => tracks.evaluate((element) => element.scrollTop)).toBe(scrollPosition);
		await expect(selected).toHaveAttribute('aria-current', 'true');
		await page.setViewportSize({ width: 1280, height: 900 });
		await page.getByText('Notiz', { exact: true }).focus();
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
		row(
			950,
			'Reselection',
			line(1, 'First sentence', {
				question: 'First?',
				example: 'Long example. '.repeat(500),
				default: 'yes'
			})
		)
	]);
	await page.goto(`${appUrl}#t=${token}`);
	const selected = page.getByRole('button', { name: /First sentence/ });
	await selected.click();
	await expect(page.locator('.stage')).toBeFocused();
	await page.keyboard.press('Tab');
	await page.keyboard.press('Tab');
	await expect(choices(page).getByRole('button', { name: /Ja/ })).toBeFocused();
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
		row(
			951,
			'Resize',
			line(1, 'First sentence', {
				question: 'First?',
				example: 'Long example. '.repeat(500),
				default: 'yes'
			}),
			line(2, 'Second sentence', {
				question: 'Second?',
				example: 'Long example. '.repeat(500),
				default: 'yes'
			})
		)
	]);
	await page.clock.install();
	await page.goto(`${appUrl}#t=${token}`);
	await page.getByRole('button', { name: /First sentence/ }).click();
	await page.getByRole('button', { name: '← Liste' }).click();
	await page.screenshot({ path: testInfo.outputPath('phone-return.png') });
	await page.setViewportSize({ width: 1280, height: 900 });
	await choices(page).getByRole('button', { name: /Ja/ }).click();
	await page.clock.runFor(PAST_UNDO_WINDOW_MS);
	await expect(page.getByRole('heading', { name: 'Second?', exact: true })).toBeInViewport();
	await expect(page.locator('.stage')).toBeFocused();
	await page.screenshot({ path: testInfo.outputPath('resized-advance.png') });
});

for (const viewport of [
	{ width: 1280, height: 900 },
	{ width: 390, height: 844 }
]) {
	test.describe(`${viewport.width}px selection flow`, () => {
		test.use({ viewport });

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
			await expect(page.getByText(/Nichts offen/)).toBeVisible();
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
			await page.getByRole('button', { name: /Guests may join the call\./ }).click();
			await choices(page).getByRole('button', { name: /Ja/ }).click();
			await page.getByRole('button', { name: 'Rückgängig' }).click();

			// The page clock runs past the window: the undo must have cancelled the
			// write, not merely delayed it, and no real waiting is needed to prove it.
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);

			expect(ruleRequests).toBe(0);
			await expect(choices(page).getByRole('button', { name: /Ja/ })).toBeEnabled();
		});

		test('once the window elapses, exactly one decision is written', async ({ page }, testInfo) => {
			const { appUrl, token, repoDirectory } = readBoardRuntime();
			writeRulings(repoDirectory, [
				row(
					602,
					'Hosts',
					line(1, 'Hosts may close the room.', { question: 'Hosts allowed?', default: 'no' })
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
			await page.getByRole('button', { name: /Hosts may close the room\./ }).click();
			await choices(page).getByRole('button', { name: /Nein/ }).click();
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);

			await expect(page.getByText('Keine Frage ausgewählt.')).toBeVisible();
			await expect(page.locator('.stage')).toBeFocused();
			await page.screenshot({ path: testInfo.outputPath('unselected.png') });
			if (viewport.width === 390) await page.getByRole('button', { name: '← Liste' }).click();
			await expect(page.getByText('Nein · 2026-10-03')).toBeVisible();
			expect(ruleRequests).toBe(1);
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
			await page.getByRole('button', { name: /Guests may join the call\./ }).click();
			await choices(page).getByRole('button', { name: /Ja/ }).click();

			await expect(page.getByRole('heading', { name: 'Hosts allowed?' })).toBeVisible({
				timeout: 10_000
			});
			await expect(choices(page).getByRole('button', { name: /Nein/ })).toBeVisible();
			await expect(page.getByRole('heading', { name: 'Hosts allowed?' })).toBeInViewport();
			await expect(page.locator('.stage')).toBeFocused();

			// The just-ruled line stays visible in the list, but as read-only text.
			if (viewport.width === 390) await page.getByRole('button', { name: '← Liste' }).click();
			await expect(
				page.getByRole('button', { name: /Guests may join the call\./ })
			).not.toBeVisible();
			await expect(page.getByText('Guests may join the call.')).toBeVisible();
			await expect(page.getByText('Ja · 2026-10-03')).toBeVisible();
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
			await page.getByRole('button', { name: /Original sentence\./ }).click();
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
			await page.getByRole('button', { name: /This can wait a cycle\./ }).click();
			const recommended = choices(page).getByRole('button', { name: /Später/ });
			await expect(recommended).toContainText('Empfohlen');
			await recommended.click();

			await expect(page.getByText('Keine Frage ausgewählt.')).toBeVisible({ timeout: 10_000 });
			if (viewport.width === 390) await page.getByRole('button', { name: '← Liste' }).click();
			await expect(page.getByText('Später · 2026-10-03')).toBeVisible();
		});

		test('eight long repository lists keep selection, focus and all content inside the viewport', async ({
			page
		}, testInfo) => {
			const { appUrl, token, repoDirectory } = readBoardRuntime();
			const longWord = 'Entscheidungsgrundlage'.repeat(12);
			await arrangeLongRepositoryLists(page, repoDirectory, longWord);
			let writes = 0;
			page.on('request', (request) => {
				if (request.method() === 'POST') writes += 1;
			});
			await page.goto(`${appUrl}#t=${token}`);
			if (viewport.width > 760) {
				await expect(page.getByText('Keine Frage ausgewählt.')).toBeVisible();
				await page.screenshot({ path: testInfo.outputPath('unselected.png') });
			}
			const tracks = page.locator('.tracks');
			const selected = tracks.getByRole('button').last();
			await selected.scrollIntoViewIfNeeded();
			const scrollPosition = await tracks.evaluate((element) => element.scrollTop);
			await selected.focus();
			await page.keyboard.press('Enter');
			await expect(page.getByRole('heading', { name: 'Frage 11?' })).toBeInViewport();
			await expect(page.locator('.stage')).toBeFocused();
			await page.keyboard.press('Tab');
			await expect(page.getByText('Notiz', { exact: true })).toBeFocused();
			await page.keyboard.press('Enter');
			await page.keyboard.press('Tab');
			await expect(page.getByRole('textbox')).toBeFocused();
			await page.getByRole('textbox').fill(longWord);
			await expect(page.getByAltText('Bild zur Frage')).toBeVisible();
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
			await choices(page)
				.getByRole('button', { name: 'Nein', exact: true })
				.scrollIntoViewIfNeeded();
			await expect(choices(page)).toBeInViewport();
			await page.screenshot({ path: testInfo.outputPath('note.png') });
			await expectReturnAndResizeFocus(page, viewport, scrollPosition);
			expect(writes).toBe(0);
		});

		test('separate undo notices stay reachable and cancel every pending write', async ({
			page
		}, testInfo) => {
			const { appUrl, token, repoDirectory } = readBoardRuntime();
			writeRulings(repoDirectory, [
				row(720, 'Mehrere Fragen', line(1, 'Erste Frage'), line(2, 'Zweite Frage'))
			]);
			let writes = 0;
			page.on('request', (request) => {
				if (request.method() === 'POST') writes += 1;
			});
			await page.clock.install();
			await page.goto(`${appUrl}#t=${token}`);
			for (const name of ['Erste Frage', 'Zweite Frage']) {
				await page.getByRole('button', { name: new RegExp(name) }).click();
				await choices(page).getByRole('button', { name: 'Ja', exact: true }).click();
				if (viewport.width === 390) await page.getByRole('button', { name: '← Liste' }).click();
			}
			await expect(page.getByRole('button', { name: 'Rückgängig' })).toHaveCount(2);
			await page.screenshot({ path: testInfo.outputPath('undo.png') });
			await page.getByRole('button', { name: 'Rückgängig' }).last().click();
			await page.getByRole('button', { name: 'Rückgängig' }).click();
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);
			expect(writes).toBe(0);
		});
	});
}
