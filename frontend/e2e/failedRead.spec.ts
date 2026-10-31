import type { Page } from '@playwright/test';
import { expect, test } from './consoleGuard';
import { countPosts, pick, routeRepositories, servedRepository } from './decideRow';
import { arrange, item, optionEntry, storedLine, type CardOption } from './itemFixture';
import { readBoardRuntime } from './runtime';
import { clockTime } from '../src/app/model/boardSummary';
import { UNDO_SECONDS } from '../src/app/model/decision';

// One shared board server backs every test in this file (see
// global-setup.ts); each test arranges the whole board.
test.describe.configure({ mode: 'serial' });

// Just past the app's undo window; the page clock is driven, never waited.
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

const REFUSED_QUESTION = 'Refusiert?';
const NEIGHBOUR_QUESTION = 'Nachbar?';
const SENTENCE_B = 'Repository B konnte nicht gelesen werden.';
const FIRST_READ = new Date(2026, 9, 31, 9, 41);
const LATER_READ = new Date(2026, 9, 31, 10, 5);

function board(refusedChanged: boolean) {
	return [
		item(
			41,
			'Refused',
			optionEntry('Satz.', {
				question: REFUSED_QUESTION,
				option: OPTIONS,
				area: 'Seite',
				...(refusedChanged ? { problem: 'Geändert.' } : {})
			})
		),
		item(
			42,
			'Neighbour',
			optionEntry('Satz.', { question: NEIGHBOUR_QUESTION, option: OPTIONS, area: 'Seite' })
		)
	];
}

async function visit(page: Page): Promise<void> {
	const { appUrl, token } = readBoardRuntime();
	await page.clock.install();
	await page.clock.setFixedTime(FIRST_READ);
	await page.goto(`${appUrl}#t=${token}`);
}

/** A phone leaves the shown card for its list. */
async function showList(page: Page, phone: boolean): Promise<void> {
	const back = page.getByRole('button', { name: '‹ Open' });
	if (phone && (await back.isVisible())) await back.click();
}

/** Shows the card titled `question`. */
async function show(page: Page, phone: boolean, question: string, nth = 0): Promise<void> {
	await showList(page, phone);
	await page.locator('.tracks').getByTitle(question, { exact: true }).nth(nth).click();
}

/** The first card is picked, changed behind the page and refused, so its `Neu laden` shows. */
async function refuseFirstCard(page: Page, phone: boolean): Promise<void> {
	await arrange(board(false));
	await visit(page);
	await show(page, phone, REFUSED_QUESTION);
	await arrange(board(true));
	await pick(page, 'A').click();
	await page.clock.runFor(PAST_UNDO_WINDOW_MS);
	await expect(page.getByRole('button', { name: 'Neu laden' })).toBeVisible();
}

for (const viewport of [
	{ width: 1280, height: 900 },
	{ width: 390, height: 844 }
]) {
	const phone = viewport.width === 390;
	test.describe(`${viewport.width}px failed read`, () => {
		test.use({ viewport });

		test('[ABRD-101] a repository that fails on a later read keeps its cards under Not read, its sentence and its read time, and they stay decidable', async ({
			page
		}, testInfo) => {
			const served = await servedRepository();
			await routeRepositories(page, [served, 'Projekt B'], (read) =>
				read >= 1 ? { 'Projekt B': SENTENCE_B } : {}
			);
			await refuseFirstCard(page, phone);
			const posts = countPosts(page);
			await page.clock.setFixedTime(LATER_READ);

			await page.getByRole('button', { name: 'Neu laden' }).click();

			await showList(page, phone);
			const failedGroup = page.getByRole('heading', { level: 2, name: 'Projekt B' });
			await expect(failedGroup).toBeVisible();
			const alert = page.getByRole('alert').filter({ hasText: 'Not read' });
			await expect(alert).toContainText(
				`Not read ${SENTENCE_B} last read ${clockTime(FIRST_READ)}`
			);
			await expect(
				page.locator('.tracks').getByTitle(REFUSED_QUESTION, { exact: true })
			).toHaveCount(2);
			await page.screenshot({ path: testInfo.outputPath('failed-with-kept-cards.png') });

			await show(page, phone, REFUSED_QUESTION, 1);
			await pick(page, 'A').click();
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);
			await expect.poll(posts.count).toBe(1);
		});

		test('[ABRD-102] a read that fails whole keeps every card under the page sentence and its read time, and a pick stores once', async ({
			page
		}, testInfo) => {
			await refuseFirstCard(page, phone);
			await arrange(board(true), { listingFailure: 'aco unavailable' });
			await page.clock.setFixedTime(LATER_READ);

			await page.getByRole('button', { name: 'Neu laden' }).click();

			await showList(page, phone);
			await expect(page.getByRole('alert').filter({ hasText: 'Not read' })).toContainText(
				`Not read aco antwortet nicht. last read ${clockTime(FIRST_READ)}`
			);
			await expect(
				page.locator('.tracks').getByTitle(NEIGHBOUR_QUESTION, { exact: true })
			).toBeVisible();
			await page.screenshot({ path: testInfo.outputPath('failed-whole.png') });

			await arrange(board(true));
			await show(page, phone, NEIGHBOUR_QUESTION);
			await pick(page, 'A').click();
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);
			await expect.poll(() => storedLine(42, 1)).toMatchObject({ ruling: 'A', via: 'board' });
		});

		test('[ABRD-102] a first load that fails shows aco antwortet nicht. and the failure, no list', async ({
			page
		}) => {
			await arrange(board(false), { listingFailure: 'aco unavailable' });

			const { appUrl, token } = readBoardRuntime();
			await page.goto(`${appUrl}#t=${token}`);

			await expect(page.getByRole('alert')).toContainText('aco antwortet nicht. GET /api/board');
			await expect(page.getByRole('heading', { level: 2 })).toHaveCount(0);
		});
	});
}
