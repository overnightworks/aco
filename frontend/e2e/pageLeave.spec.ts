import type { Locator, Page } from '@playwright/test';
import { expect, test } from './consoleGuard';
import { pick } from './decideRow';
import {
	arrange,
	item,
	optionEntry,
	storedLine,
	type CardOption,
	type OptionEntry
} from './itemFixture';
import { readBoardRuntime } from './runtime';
import { UNDO_SECONDS } from '../src/app/model/decision';

// One shared board server backs every test in this file (see
// global-setup.ts); each test arranges the whole board.
test.describe.configure({ mode: 'serial' });

const PAST_UNDO_WINDOW_MS = UNDO_SECONDS * 1000 + 500;

const OPTIONS: CardOption[] = (['A', 'B'] as const).map((letter) => ({
	name: `Weg ${letter}`,
	effect: `Wirkung ${letter}.`,
	same_as_today: true,
	notice: 'Merkbar.',
	cost: 'Aufwand.',
	undo: 'reversible',
	undo_how: 'jederzeit',
	contract: `Vertrag ${letter}.`
}));

function card(question: string, topic: string): OptionEntry {
	return optionEntry('Satz.', { question, topic, option: OPTIONS, area: 'Seite' });
}

function listRow(page: Page, question: string): Locator {
	return page.locator('.tracks').getByTitle(question, { exact: true });
}

/** Shows the card titled `question`; a phone returns to its list first. */
async function show(page: Page, phone: boolean, question: string): Promise<void> {
	const back = page.getByRole('button', { name: '‹ Open' });
	if (phone && (await back.isVisible())) await back.click();
	await listRow(page, question).click();
}

/** Opens the board with a frozen page clock, so the undo window never ends on its own. */
async function visit(page: Page): Promise<void> {
	const { appUrl, token } = readBoardRuntime();
	await page.clock.install();
	await page.goto(`${appUrl}#t=${token}`);
}

for (const viewport of [
	{ width: 1280, height: 900 },
	{ width: 390, height: 844 }
]) {
	const phone = viewport.width === 390;
	test.describe(`${viewport.width}px page leave`, () => {
		test.use({ viewport });

		test('[ABRD-152] leaving the page inside the undo window stores the decision', async ({
			page
		}) => {
			await arrange([item(61, 'Leave', card('Verlassen?', 'Weg'))]);
			await visit(page);
			await show(page, phone, 'Verlassen?');
			await pick(page, 'B').click();
			await expect(page.locator('.strip')).toContainText('Saves shortly: B');

			await page.goto('about:blank');

			await expect.poll(() => storedLine(61, 1)).toMatchObject({ ruling: 'B', via: 'board' });
		});

		test('[ABRD-152] closing the page inside the undo window stores the decision', async ({
			page
		}) => {
			await arrange([item(62, 'Close', card('Schliessen?', 'Zu'))]);
			await visit(page);
			await show(page, phone, 'Schliessen?');
			await pick(page, 'A').click();
			await expect(page.locator('.strip')).toContainText('Saves shortly: A');

			await page.close({ runBeforeUnload: true });

			await expect.poll(() => storedLine(62, 1)).toMatchObject({ ruling: 'A', via: 'board' });
		});

		test('[ABRD-152] hiding the page inside the undo window stores the decision and keeps the page', async ({
			page
		}) => {
			await arrange([item(63, 'Hide', card('Verstecken?', 'Weg'))]);
			await visit(page);
			await show(page, phone, 'Verstecken?');
			await pick(page, 'A').click();

			await page.evaluate(() => {
				Object.defineProperty(document, 'visibilityState', {
					configurable: true,
					get: () => 'hidden'
				});
				document.dispatchEvent(new Event('visibilitychange'));
			});

			await expect.poll(() => storedLine(63, 1)).toMatchObject({ ruling: 'A', via: 'board' });
		});

		test('[ABRD-152] a card nothing was chosen on is never stored by leaving', async ({ page }) => {
			await arrange([item(64, 'Idle', card('Unberuehrt?', 'Nichts'))]);
			await visit(page);
			await show(page, phone, 'Unberuehrt?');

			await page.goto('about:blank');

			expect(await storedLine(64, 1)).toMatchObject({ ruling: null });
		});

		test('[ABRD-153] a failed post on a card left behind keeps a strip naming it until the card is shown', async ({
			page
		}) => {
			await arrange([
				item(65, 'First', card('Erste?', 'Erstes')),
				item(66, 'Second', card('Zweite?', 'Zweites'))
			]);
			await visit(page);
			await show(page, phone, 'Erste?');
			await page.route('**/api/rule', (route) => route.abort());
			await pick(page, 'A').click();
			await show(page, phone, 'Zweite?');
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);

			const failure = page.locator('.strips').getByText('Not saved: Erstes');
			await expect(failure).toBeVisible();

			await show(page, phone, 'Erste?');

			await expect(failure).toHaveCount(0);
			await expect(page.getByText('Das Board ist nicht erreichbar.')).toBeVisible();
		});

		test('[ABRD-153] a failed post on a card hidden by the back button keeps a strip naming it until the card is shown', async ({
			page
		}) => {
			test.skip(!phone, 'the back button exists only on the phone');
			await arrange([item(67, 'Only', card('Einzige?', 'Einziges'))]);
			await visit(page);
			await show(page, phone, 'Einzige?');
			await page.route('**/api/rule', (route) => route.abort());
			await pick(page, 'A').click();
			await page.getByRole('button', { name: '‹ Open' }).click();
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);

			const failure = page.locator('.strips').getByText('Not saved: Einziges');
			await expect(failure).toBeVisible();

			await listRow(page, 'Einzige?').click();

			await expect(failure).toHaveCount(0);
		});
	});
}
