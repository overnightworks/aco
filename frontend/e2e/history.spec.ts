import { expect, test } from './consoleGuard';
import { line, row, writeRulings } from './rulingsFixture';
import { readBoardRuntime } from './runtime';
import { UNDO_SECONDS } from '../src/app/model/decision';

for (const viewport of [
	{ width: 1280, height: 900 },
	{ width: 390, height: 844 }
]) {
	test.describe(`${viewport.width}px history`, () => {
		test.use({ viewport });
		test('repository failures remain visible beside an empty decision list and empty history', async ({
			page
		}, testInfo) => {
			const { appUrl, token } = readBoardRuntime();
			await page.route('**/api/board', (route) =>
				route.fulfill({
					json: {
						repos: [
							{ name: 'available', error: null, items: [] },
							{ name: 'unavailable', error: 'Repository konnte nicht gelesen werden.', items: [] }
						]
					}
				})
			);
			await page.goto(`${appUrl}#t=${token}`);
			await expect(page.getByRole('alert')).toContainText('unavailable');
			await expect(page.getByText(/Nichts offen/)).toBeVisible();
			await page.screenshot({ path: testInfo.outputPath('empty-repo-error.png') });
			await page.getByRole('button', { name: 'Verlauf', exact: true }).click();
			await expect(page.getByRole('alert')).toContainText('unavailable');
			await expect(
				page.getByText('Noch keine Entscheidungen in den offenen Board-Items.')
			).toBeVisible();
			await page.screenshot({ path: testInfo.outputPath('empty-history-error.png') });
		});
		test('first visit selects a short question and history preserves the list and phone state', async ({
			page
		}, testInfo) => {
			const { appUrl, token, repoDirectory } = readBoardRuntime();
			writeRulings(repoDirectory, [
				row(
					42,
					'Gäste im Gespräch',
					line(
						1,
						'Gäste dürfen über einen geteilten Einladungslink am Gespräch teilnehmen. Der Gastgeber kann sie vor dem Beitritt bestätigen.',
						{
							question: 'Gäste einladen?',
							example: 'Anna schickt Ben den Link. Er wartet, bis sie ihn einlässt.',
							default: 'yes'
						}
					),
					line(2, 'Der Gastgeber kann das Gespräch für alle Teilnehmer beenden.', {
						question: 'Gespräch beenden?',
						default: 'no'
					}),
					line(3, 'Gastzugänge bleiben bis zur nächsten Runde unverändert.', {
						question: 'Gastzugänge ändern?',
						ruling: 'later',
						ruled_on: '2026-10-03'
					})
				),
				row(
					41,
					'Aufzeichnung',
					line(1, 'Die Aufzeichnung bleibt ausgeschaltet.', {
						question: 'Aufzeichnen?',
						ruling: 'no',
						ruled_on: '2026-10-02'
					})
				)
			]);
			await page.route('**/api/board', async (route) => {
				const response = await route.fetch();
				const board = await response.json();
				await route.fulfill({
					json: {
						repos: Array.from({ length: 8 }, (_, index) => ({
							...board.repos[0],
							name: `Projekt ${index + 1}`
						}))
					}
				});
			});
			let writes = 0;
			page.on('request', (request) => {
				if (request.method() === 'POST') writes += 1;
			});
			await page.goto(`${appUrl}#t=${token}`);
			const tracks = page.locator('.tracks');
			const first = tracks.getByRole('button').first();
			await expect(first).toHaveAttribute('aria-current', 'true');
			await expect(first).toHaveAccessibleName('Gäste einladen? Empfohlen: Ja');
			await expect(first).toBeInViewport();
			await expect(tracks.getByText('Gastzugänge ändern?')).toHaveCount(0);
			await expect(page.locator('.question-pane')).toBeVisible({ visible: viewport.width > 760 });
			await page.screenshot({ path: testInfo.outputPath('first-visit.png') });
			await page.evaluate(() => {
				document.body.style.filter = 'blur(4px) grayscale(1)';
			});
			await page.screenshot({ path: testInfo.outputPath('first-visit-shapes.png') });
			await page.evaluate(() => {
				document.body.style.filter = '';
			});
			await first.press('Enter');
			await expect(
				page.getByRole('heading', { name: 'Gäste einladen?', exact: true })
			).toBeVisible();
			await expect(page.locator('.stage')).toBeFocused();
			if (viewport.width === 390) await page.getByRole('button', { name: '← Liste' }).click();
			const last = tracks.getByRole('button').last();
			await last.scrollIntoViewIfNeeded();
			const position = await tracks.evaluate((element) => element.scrollTop);
			await last.click();
			await page.getByRole('button', { name: 'Verlauf', exact: true }).click();
			const history = page.getByRole('region', { name: 'Verlauf' });
			await expect(history.locator('summary')).toHaveCount(16);
			await expect(history.locator('summary').first()).toContainText('Projekt 1 · #42');
			await history.locator('summary').first().press('Enter');
			await expect(
				history.getByText('Gastzugänge bleiben bis zur nächsten Runde unverändert.').first()
			).toBeVisible();
			await expect(page.getByRole('group', { name: 'Entscheidung' })).toHaveCount(0);
			await expect(page.getByRole('button', { name: 'Rückgängig' })).toHaveCount(0);
			await page.screenshot({ path: testInfo.outputPath('history.png') });
			await expect
				.poll(() => page.evaluate(() => document.documentElement.scrollWidth))
				.toBeLessThanOrEqual(viewport.width);
			await page.getByRole('button', { name: 'Entscheiden', exact: true }).click();
			await expect(
				page.getByRole('heading', { name: 'Gespräch beenden?', exact: true })
			).toBeVisible();
			if (viewport.width === 390) await page.getByRole('button', { name: '← Liste' }).click();
			await expect(last).toHaveAttribute('aria-current', 'true');
			await expect.poll(() => tracks.evaluate((element) => element.scrollTop)).toBe(position);
			expect(writes).toBe(0);
		});

		test('history reveals additional sentences and keeps sentence fallbacks free of empty disclosures', async ({
			page
		}, testInfo) => {
			const { appUrl, token, repoDirectory } = readBoardRuntime();
			writeRulings(repoDirectory, [
				row(
					42,
					'Gastzugang',
					line(1, 'Gäste dürfen teilnehmen.', {
						question: 'Gäste zulassen?',
						ruling: 'yes',
						ruled_on: '2026-10-03'
					}),
					line(2, 'Die Aufzeichnung bleibt ausgeschaltet.', {
						ruling: 'no',
						ruled_on: '2026-10-02'
					}),
					line(3, 'Die nächste Runde bleibt unverändert.', {
						question: 'Runde ändern?',
						ruling: 'later',
						ruled_on: '2026-10-01'
					})
				)
			]);
			let writes = 0;
			await page.route('**/api/rule', (route) => {
				writes += 1;
				return route.abort();
			});
			await page.goto(`${appUrl}#t=${token}`);
			await page.getByRole('button', { name: 'Verlauf', exact: true }).click();
			const history = page.getByRole('region', { name: 'Verlauf' });
			await expect(history.locator('summary')).toHaveCount(2);
			const fallback = history.getByRole('article');
			await expect(fallback).toContainText('Die Aufzeichnung bleibt ausgeschaltet.');
			await expect(fallback.locator('summary, button, details')).toHaveCount(0);
			await expect(
				history.getByText('Die Aufzeichnung bleibt ausgeschaltet.', { exact: true })
			).toHaveCount(1);
			await expect(history.getByText('Gäste dürfen teilnehmen.', { exact: true })).toBeHidden();
			await history.locator('summary').first().press('Enter');
			await expect(history.getByText('Gäste dürfen teilnehmen.', { exact: true })).toBeVisible();
			await expect(history.getByRole('button')).toHaveCount(0);
			await page.screenshot({ path: testInfo.outputPath('history-outcomes.png') });
			await page.evaluate(() => {
				document.body.style.filter = 'grayscale(1)';
			});
			await page.screenshot({ path: testInfo.outputPath('history-outcomes-grayscale.png') });
			await page.evaluate(() => {
				document.body.style.filter = 'blur(4px) grayscale(1)';
			});
			await page.screenshot({ path: testInfo.outputPath('history-outcomes-shapes.png') });
			expect(writes).toBe(0);
		});

		test('a pending ruling does not displace history and appears only after successful reload', async ({
			page
		}) => {
			const { appUrl, token, repoDirectory } = readBoardRuntime();
			writeRulings(repoDirectory, [
				row(
					60,
					'Eine Frage',
					line(1, 'Die Gäste dürfen teilnehmen.', { question: 'Gäste zulassen?' })
				)
			]);
			await page.clock.install();
			await page.goto(`${appUrl}#t=${token}`);
			await page.getByRole('button', { name: /Gäste zulassen/ }).click();
			await page.getByRole('button', { name: 'Ja', exact: true }).click();
			await page.getByRole('button', { name: 'Verlauf', exact: true }).click();
			await expect(
				page.getByText('Noch keine Entscheidungen in den offenen Board-Items.')
			).toBeVisible();
			await page.clock.runFor(UNDO_SECONDS * 1000 + 500);
			await expect(page.getByRole('region', { name: 'Verlauf' }).locator('summary')).toContainText(
				'Ja · 2026-10-03'
			);
			await expect(page.getByRole('button', { name: 'Verlauf', exact: true })).toBeFocused();
			await expect(page.getByRole('group', { name: 'Entscheidung' })).toHaveCount(0);
			await page.getByRole('button', { name: 'Entscheiden', exact: true }).click();
			if (viewport.width === 390) await page.getByRole('button', { name: '← Liste' }).click();
			await expect(page.getByText(/Nichts offen/)).toBeVisible();
		});
	});
}
