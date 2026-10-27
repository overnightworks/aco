import type { Locator, Page } from '@playwright/test';
import { expect, test } from './consoleGuard';
import { optionLine, row, writeRulings, type RulingOption } from './rulingsFixture';
import { readBoardRuntime } from './runtime';
import { UNDO_SECONDS } from '../src/app/model/decision';

// One shared board server backs every test in this file (see
// global-setup.ts); each test overwrites the whole of rulings.json.
test.describe.configure({ mode: 'serial' });

// Just past the app's undo window; the page clock is driven, never waited.
const PAST_UNDO_WINDOW_MS = UNDO_SECONDS * 1000 + 500;

const QUESTION = 'Soll der Song beim Sprung offen bleiben?';
const OTHER_QUESTION = 'Welcher Weg für die Altdaten?';
const NOTE = 'Welcher Sprung ist gemeint?';

const OPTIONS: RulingOption[] = ['A', 'B'].map((letter) => ({
	letter,
	name: `Weg ${letter}`,
	effect: 'Die App springt selbst.',
	same_as_today: true,
	notice: 'Du bleibst im Song.',
	cost: 'Mehr Code.',
	undo: 'reversible',
	undo_how: 'jederzeit',
	contract: 'Der Song bleibt offen.'
}));

function arrange(directory: string, withSecondCard: boolean): void {
	writeRulings(directory, [
		row(
			2002,
			'Sprung',
			optionLine(1, 'Der Song bleibt beim Sprung offen.', {
				question: QUESTION,
				problem: 'Der Link schließt den Song.',
				area: 'Song-Seite',
				topic: 'Sprung',
				options: OPTIONS
			}),
			...(withSecondCard
				? [
						optionLine(2, 'Eine zweite offene Frage.', {
							question: OTHER_QUESTION,
							topic: 'Altdaten',
							options: OPTIONS
						})
					]
				: [])
		)
	]);
}

async function open(page: Page, phone: boolean): Promise<void> {
	const { appUrl, token } = readBoardRuntime();
	await page.clock.install();
	await page.goto(`${appUrl}#t=${token}`);
	await page.locator('.tracks').getByTitle(QUESTION).click();
	if (phone) await expect(page.locator('.question-pane')).toBeVisible();
}

function noteField(page: Page): Locator {
	return page.getByRole('textbox', { name: 'What is unclear? (optional)' });
}

async function sendNote(page: Page): Promise<void> {
	await page.getByRole('button', { name: 'Unclear' }).click();
	await noteField(page).fill(NOTE);
	await page.getByRole('button', { name: 'Send' }).click();
}

for (const viewport of [
	{ width: 1280, height: 900 },
	{ width: 390, height: 844 }
]) {
	const phone = viewport.width === 390;
	test.describe(`${viewport.width}px Unclear`, () => {
		test.use({ viewport });

		test('[ABRD-73] Unclear opens a focused optional note panel whose Send is enabled while blank', async ({
			page
		}, testInfo) => {
			arrange(readBoardRuntime().repoDirectory, true);
			await open(page, phone);

			await expect(page.getByRole('button', { name: 'Other…' })).toBeVisible();
			await page.getByRole('button', { name: 'Unclear' }).click();

			await expect(noteField(page)).toBeFocused();
			await expect(noteField(page)).toHaveAttribute('placeholder', 'Optional: what is unclear?');
			await expect(noteField(page)).toHaveAttribute('maxlength', '280');
			await expect(page.getByRole('button', { name: 'Send' })).toBeEnabled();
			await page.screenshot({ path: testInfo.outputPath('unclear-panel.png') });
			await expect(page.getByRole('heading', { name: QUESTION })).toBeVisible();
			expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
				viewport.width
			);

			await page.getByRole('button', { name: 'Other…' }).click();
			await expect(noteField(page)).toHaveCount(0);
			await expect(page.getByRole('textbox', { name: 'Your answer' })).toBeVisible();
		});

		test('[ABRD-74] Send shows the grey With head strip with focus on Undo, and Undo posts nothing and reopens the note', async ({
			page
		}, testInfo) => {
			arrange(readBoardRuntime().repoDirectory, true);
			let writes = 0;
			page.on('request', (request) => {
				if (request.method() === 'POST') writes += 1;
			});
			await open(page, phone);

			await sendNote(page);

			const strip = page.locator('.strip');
			await expect(strip).toContainText('With head: Sprung');
			await expect(strip.getByRole('img', { name: 'With head' })).toBeVisible();
			await expect(strip.getByRole('button', { name: 'Undo' })).toBeFocused();
			await expect(noteField(page)).toHaveCount(0);
			await page.screenshot({ path: testInfo.outputPath('with-head-strip.png') });

			await strip.getByRole('button', { name: 'Undo' }).click();
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);
			expect(writes).toBe(0);
			await expect(noteField(page)).toHaveValue(NOTE);
		});

		test('[ABRD-75, ABRD-76] after the window the stage moves to the next open card, and the sent card lists with its head', async ({
			page
		}) => {
			arrange(readBoardRuntime().repoDirectory, true);
			await open(page, phone);

			await sendNote(page);
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);

			await expect(page.getByRole('heading', { name: OTHER_QUESTION })).toBeVisible();
			// The phone shows the question alone once a card is open.
			if (!phone) {
				await expect(
					page.locator('.tracks').getByRole('button', { name: /^With head/ })
				).toHaveCount(1);
			}
		});

		test('[ABRD-72, ABRD-76] with no other open card the stage stays, and the card reads with head, offers no Unclear and keeps its picks and Other…', async ({
			page
		}, testInfo) => {
			arrange(readBoardRuntime().repoDirectory, false);
			await open(page, phone);

			await sendNote(page);
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);

			await expect(page.getByRole('heading', { name: QUESTION })).toBeVisible();
			await expect(page.locator('.option-card .meta')).toContainText('with head');
			await expect(page.getByRole('button', { name: 'Unclear' })).toHaveCount(0);
			await expect(page.getByRole('button', { name: 'Other…' })).toBeVisible();
			await expect(page.getByRole('group', { name: 'Decide' }).getByRole('button')).toHaveCount(2);
			await page.screenshot({ path: testInfo.outputPath('with-head-card.png') });
		});
	});
}
