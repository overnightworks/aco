import type { Locator, Page } from '@playwright/test';
import { expect, test } from './consoleGuard';
import { optionLine, row, writeRulings, type RulingOption } from './rulingsFixture';
import { decidedList, expectDecidedAnswer } from './decidedView';
import { readBoardRuntime } from './runtime';
import { UNDO_SECONDS } from '../src/app/model/decision';

// One shared board server backs every test in this file (see
// global-setup.ts); each test overwrites the whole of rulings.json.
test.describe.configure({ mode: 'serial' });

// Just past the app's undo window; the page clock is driven, never waited.
const PAST_UNDO_WINDOW_MS = UNDO_SECONDS * 1000 + 500;

// The fake aco stores every board answer as `--via board` on this date.
const BOARD_ANSWER_HOW = 'Board · 03.10.2026';

const QUESTION = 'Soll der Song beim Sprung offen bleiben?';
const ANSWER = 'Nur auf dem Desktop offen lassen.';

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

function arrange(directory: string, withHead = false): void {
	writeRulings(directory, [
		row(
			2002,
			'Sprung',
			optionLine(1, 'Der Song bleibt beim Sprung offen.', {
				question: QUESTION,
				problem: 'Der Link schließt den Song.',
				area: 'Song-Seite',
				topic: 'Sprung',
				options: OPTIONS,
				...(withHead ? { returned_on: '2026-10-27', returned_note: 'Warum?' } : {})
			})
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

function answerField(page: Page): Locator {
	return page.getByRole('textbox', { name: 'Your answer' });
}

for (const viewport of [
	{ width: 1280, height: 900 },
	{ width: 390, height: 844 }
]) {
	const phone = viewport.width === 390;
	test.describe(`${viewport.width}px Other…`, () => {
		test.use({ viewport });

		test('[ABRD-63] Other… opens the panel with focus in the field, Send waits for text, and the card stays reachable', async ({
			page
		}, testInfo) => {
			arrange(readBoardRuntime().repoDirectory);
			await open(page, phone);

			const other = page.getByRole('button', { name: 'Other…' });
			await expect(other).toHaveAttribute('aria-expanded', 'false');
			await other.click();

			await expect(other).toHaveAttribute('aria-expanded', 'true');
			await expect(answerField(page)).toBeFocused();
			await expect(answerField(page)).toHaveAttribute('placeholder', 'What should apply instead?');
			await expect(answerField(page)).toHaveAttribute('maxlength', '280');
			await expect(page.getByRole('button', { name: 'Send' })).toBeDisabled();
			await answerField(page).fill('   ');
			await expect(page.getByRole('button', { name: 'Send' })).toBeDisabled();
			await answerField(page).fill(ANSWER);
			await expect(page.getByRole('button', { name: 'Send' })).toBeEnabled();
			await page.screenshot({ path: testInfo.outputPath('panel-open.png') });

			const rowHeight = await page
				.locator('.decide-row')
				.evaluate((element) => element.getBoundingClientRect().height);
			expect(rowHeight).toBeLessThan(viewport.height * 0.5);
			await page.getByRole('heading', { name: QUESTION }).scrollIntoViewIfNeeded();
			await expect(page.getByRole('heading', { name: QUESTION })).toBeInViewport();
			expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
				viewport.width
			);
		});

		test('[ABRD-67] Send shows the Other strip, Undo posts nothing and reopens the panel with the draft', async ({
			page
		}, testInfo) => {
			arrange(readBoardRuntime().repoDirectory);
			let writes = 0;
			page.on('request', (request) => {
				if (request.method() === 'POST') writes += 1;
			});
			await open(page, phone);

			await page.getByRole('button', { name: 'Other…' }).click();
			await answerField(page).fill(ANSWER);
			await page.getByRole('button', { name: 'Send' }).click();

			const strip = page.locator('.strip');
			await expect(strip).toContainText('Other · Sprung');
			await expect(strip.getByRole('button', { name: 'Undo', exact: true })).toBeFocused();
			await expect(answerField(page)).toHaveCount(0);
			await expect(page.getByRole('button', { name: 'Other…' })).toBeDisabled();
			await page.screenshot({ path: testInfo.outputPath('strip.png') });

			await strip.getByRole('button', { name: 'Undo', exact: true }).click();
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);

			expect(writes).toBe(0);
			await expect(answerField(page)).toHaveValue(ANSWER);
			await expect(page.getByRole('button', { name: 'Other…' })).toBeEnabled();
		});

		test('[ABRD-64] after the window the answer is ruled through aco and the card moves to Decided', async ({
			page
		}) => {
			arrange(readBoardRuntime().repoDirectory);
			await open(page, phone);

			await page.getByRole('button', { name: 'Other…' }).click();
			await answerField(page).fill(` ${ANSWER} `);
			await page.getByRole('button', { name: 'Send' }).click();
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);

			await expect(page.locator('.tracks').getByTitle(QUESTION)).toHaveCount(0);
			if (phone) await page.getByRole('button', { name: '‹ Open' }).click();
			await page.getByRole('button', { name: /^Decided \d+$/ }).click();
			await decidedList(page).getByRole('button').click();
			await expectDecidedAnswer(page, `Other: „${ANSWER}“`, BOARD_ANSWER_HOW);
		});

		test('[ABRD-69] a card with its head offers Other… too', async ({ page }) => {
			arrange(readBoardRuntime().repoDirectory, true);
			await open(page, phone);

			await expect(page.getByRole('button', { name: 'Other…' })).toBeVisible();
		});
	});
}
