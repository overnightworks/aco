import type { Page } from '@playwright/test';
import { UNDO_SECONDS } from '../src/app/model/decision';
import { expect, test } from './consoleGuard';
import { arrange, item, stepTable } from './itemFixture';
import { readBoardRuntime } from './runtime';

test.describe.configure({ mode: 'serial' });

const SAVED_WITHIN_MS = (UNDO_SECONDS + 7) * 1000;

async function openSteps(page: Page): Promise<void> {
	const { appUrl, token } = readBoardRuntime();
	await page.goto(`${appUrl}#t=${token}`);
	await page
		.getByRole('navigation', { name: 'Views' })
		.getByRole('button', { name: /^Steps/ })
		.click();
}

const stepCard = (page: Page) => page.getByRole('article', { name: /Release the build/ });

for (const viewport of [
	{ width: 1280, height: 900 },
	{ width: 390, height: 844 }
]) {
	test.describe(`${viewport.width}px step answers`, () => {
		test.use({ viewport });

		test('[ABRD-173] [ABRD-175] [ABRD-176] Erfolgreich stores after its window and the card leaves', async ({
			page
		}, testInfo) => {
			await arrange([{ ...item(7, 'Release the build'), step: stepTable() }]);
			await openSteps(page);

			await stepCard(page).getByRole('button', { name: 'Erfolgreich' }).click();
			await expect(page.getByText('Saves shortly: Erfolgreich · #7')).toBeVisible();
			await page.screenshot({ path: testInfo.outputPath(`step-strip-${viewport.width}.png`) });

			await expect(stepCard(page)).toHaveCount(0, { timeout: SAVED_WITHIN_MS });
			await expect(page.getByText('No step is waiting for you.')).toBeVisible();
			await page.reload();
			await page
				.getByRole('navigation', { name: 'Views' })
				.getByRole('button', { name: /^Steps/ })
				.click();
			await expect(page.getByText('No step is waiting for you.')).toBeVisible();
		});

		test('[ABRD-174] Fehlgeschlagen cannot send without a note and stores with one', async ({
			page
		}, testInfo) => {
			await arrange([{ ...item(7, 'Release the build'), step: stepTable() }]);
			await openSteps(page);

			await stepCard(page).getByRole('button', { name: 'Fehlgeschlagen' }).click();
			await expect(stepCard(page).getByRole('button', { name: 'Senden' })).toBeDisabled();
			await stepCard(page).getByLabel('Notiz').fill('Stayed red.');
			await page.screenshot({ path: testInfo.outputPath(`step-failed-${viewport.width}.png`) });
			await stepCard(page).getByRole('button', { name: 'Senden' }).click();
			await expect(page.getByText('Saves shortly: Fehlgeschlagen · #7')).toBeVisible();

			await expect(stepCard(page)).toHaveCount(0, { timeout: SAVED_WITHIN_MS });
		});

		test('[ABRD-173] a report step stores its report', async ({ page }, testInfo) => {
			await arrange([
				{ ...item(7, 'Release the build'), step: stepTable({ answer: 'the green run id' }) }
			]);
			await openSteps(page);

			await expect(stepCard(page).getByRole('button', { name: 'Erfolgreich' })).toHaveCount(0);
			await expect(stepCard(page).getByRole('button', { name: 'Senden' })).toBeDisabled();
			await stepCard(page).getByLabel('Bericht').fill('run 4711');
			await page.screenshot({ path: testInfo.outputPath(`step-report-${viewport.width}.png`) });
			await stepCard(page).getByRole('button', { name: 'Senden' }).click();

			await expect(stepCard(page)).toHaveCount(0, { timeout: SAVED_WITHIN_MS });
		});

		test('[ABRD-175] Undo inside the window posts nothing', async ({ page }) => {
			await arrange([{ ...item(7, 'Release the build'), step: stepTable() }]);
			let posts = 0;
			await page.route('**/api/step', (route) => {
				posts += 1;
				return route.continue();
			});
			await page.clock.install();
			await openSteps(page);

			await stepCard(page).getByRole('button', { name: 'Erfolgreich' }).click();
			await stepCard(page).getByRole('button', { name: 'Undo' }).click();
			await expect(stepCard(page).getByRole('button', { name: 'Erfolgreich' })).toBeVisible();
			await page.clock.runFor((UNDO_SECONDS + 1) * 1000);

			expect(posts).toBe(0);
			await expect(stepCard(page)).toBeVisible();
		});

		test('[ABRD-176] a refused answer shows its sentence with Neu laden', async ({
			page
		}, testInfo) => {
			await arrange([{ ...item(7, 'Release the build'), step: stepTable() }]);
			await openSteps(page);
			await arrange([
				{
					...item(7, 'Release the build'),
					step: stepTable({ expected: 'Something else is expected now.' })
				}
			]);

			await stepCard(page).getByRole('button', { name: 'Erfolgreich' }).click();

			await expect(page.getByRole('alert').filter({ hasText: 'This step changed' })).toBeVisible({
				timeout: SAVED_WITHIN_MS
			});
			await page.screenshot({ path: testInfo.outputPath(`step-refused-${viewport.width}.png`) });
			await expect(stepCard(page).getByRole('button', { name: 'Erfolgreich' })).toBeDisabled();
			await stepCard(page).getByRole('button', { name: 'Neu laden' }).click();
			await expect(stepCard(page).getByText('Something else is expected now.')).toBeVisible();
		});
	});
}
