import type { Page } from '@playwright/test';
import { expect, test } from './consoleGuard';
import { countBoardReads, pick, routeRepositories, servedRepository } from './decideRow';
import { arrange, item, optionEntry, type CardOption } from './itemFixture';
import { readBoardRuntime } from './runtime';
import {
	READING_LABEL,
	REFRESH_LABEL,
	SELF_REFRESH_MINUTES,
	STALE_AFTER_SECONDS,
	clockTime
} from '../src/app/model/boardSummary';
import { UNDO_SECONDS } from '../src/app/model/decision';

// One shared board server backs every test in this file (see
// global-setup.ts); each test arranges the whole board.
test.describe.configure({ mode: 'serial' });

// Just past the app's undo window; the page clock is driven, never waited.
const PAST_UNDO_WINDOW_MS = UNDO_SECONDS * 1000 + 500;
const SELF_REFRESH_MS = SELF_REFRESH_MINUTES * 60_000;
const READ_AT = new Date(2026, 9, 31, 9, 41);

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

function card(question: string, problem = 'Ausgangslage.') {
	return optionEntry('Satz.', { question, option: OPTIONS, area: 'Seite', problem });
}

function refreshButton(page: Page) {
	return page.getByRole('button', { name: /^(Refresh|Reading…) · read / });
}

function row(page: Page, question: string) {
	return page.locator('.tracks').getByTitle(question, { exact: true });
}

async function visit(page: Page, { fixedTime }: { fixedTime?: Date } = {}): Promise<void> {
	const { appUrl, token } = readBoardRuntime();
	await page.clock.install();
	if (fixedTime !== undefined) await page.clock.setFixedTime(fixedTime);
	await page.goto(`${appUrl}#t=${token}`);
	await expect(refreshButton(page)).toBeVisible();
}

/** The tab is hidden or shown, as a browser reports it. */
async function setTabVisibility(page: Page, state: 'hidden' | 'visible'): Promise<void> {
	await page.evaluate((visibility) => {
		Object.defineProperty(document, 'visibilityState', { value: visibility, configurable: true });
		document.dispatchEvent(new Event('visibilitychange'));
	}, state);
}

/** A phone leaves the shown card for its list. */
async function showList(page: Page, phone: boolean): Promise<void> {
	const back = page.getByRole('button', { name: '‹ Open' });
	if (phone && (await back.isVisible())) await back.click();
}

async function show(page: Page, phone: boolean, question: string): Promise<void> {
	await showList(page, phone);
	await row(page, question).click();
}

for (const viewport of [
	{ width: 1280, height: 900 },
	{ width: 390, height: 844 }
]) {
	const phone = viewport.width === 390;
	test.describe(`${viewport.width}px refresh`, () => {
		test.use({ viewport });

		test('[ABRD-103] Refresh reads once per click, shows a card added behind the page and keeps focus', async ({
			page
		}, testInfo) => {
			await arrange([item(61, 'First', card('Erste?'))]);
			await visit(page, { fixedTime: READ_AT });
			await expect(refreshButton(page)).toHaveAccessibleName(
				`${REFRESH_LABEL} · read ${clockTime(READ_AT)}`
			);
			await arrange([item(61, 'First', card('Erste?')), item(62, 'Second', card('Zweite?'))]);
			const reads = countBoardReads(page);

			await refreshButton(page).focus();
			await refreshButton(page).click();

			await showList(page, phone);
			await expect(row(page, 'Zweite?')).toBeVisible();
			expect(reads.count()).toBe(1);
			await expect(refreshButton(page)).toBeFocused();
			await page.screenshot({ path: testInfo.outputPath('refreshed.png') });
		});

		test('[ABRD-103] Refresh brings back a repository whose read failed', async ({ page }) => {
			await arrange([item(61, 'First', card('Erste?'))]);
			const served = await servedRepository();
			await routeRepositories(page, [served, 'Projekt B'], (read) =>
				read === 1 ? { 'Projekt B': 'Repository B konnte nicht gelesen werden.' } : {}
			);
			await visit(page);
			const notRead = page.getByRole('alert').filter({ hasText: 'Not read' });

			await refreshButton(page).click();
			await showList(page, phone);
			await expect(notRead).toBeVisible();
			await refreshButton(page).click();

			await expect(notRead).toHaveCount(0);
			await expect(row(page, 'Erste?')).toHaveCount(2);
		});

		test('[ABRD-103] Refresh is the retry after a read that failed whole', async ({ page }) => {
			await arrange([item(61, 'First', card('Erste?'))]);
			await visit(page);
			await arrange([item(61, 'First', card('Erste?'))], { listingFailure: 'aco unavailable' });
			const notRead = page.getByRole('alert').filter({ hasText: 'Not read' });

			await refreshButton(page).click();
			await expect(notRead).toContainText('aco antwortet nicht.');
			await arrange([item(61, 'First', card('Erste?'))]);
			await refreshButton(page).click();

			await expect(notRead).toHaveCount(0);
		});

		test('[ABRD-105] a read leaves the card that waits as shown and its refusal lands on it', async ({
			page
		}, testInfo) => {
			await arrange([item(61, 'First', card('Erste?')), item(62, 'Second', card('Zweite?'))]);
			await visit(page);
			await show(page, phone, 'Erste?');
			await pick(page, 'A').click();
			await expect(page.locator('.strip')).toHaveCount(1);
			await arrange([item(62, 'Second', card('Zweite?', 'Geändert.'))]);

			await refreshButton(page).click();

			await expect(refreshButton(page)).toHaveAttribute('aria-busy', 'false');
			await showList(page, phone);
			await expect(row(page, 'Zweite?')).toBeVisible();
			await expect(row(page, 'Erste?')).toBeVisible();
			await expect(page.locator('.strip')).toHaveCount(1);
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);
			await row(page, 'Erste?').click();
			await expect(page.getByRole('button', { name: 'Neu laden' })).toBeVisible();
			await page.screenshot({ path: testInfo.outputPath('waiting-card.png') });
		});

		test('[ABRD-105] a refused card’s Neu laden shows its new content while another card waits', async ({
			page
		}) => {
			await arrange([item(61, 'Refused', card('Refusiert?')), item(62, 'Waits', card('Wartet?'))]);
			await visit(page);
			await show(page, phone, 'Refusiert?');
			await arrange([
				item(61, 'Refused', card('Refusiert?', 'Geändert.')),
				item(62, 'Waits', card('Wartet?'))
			]);
			await pick(page, 'A').click();
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);
			const reload = page.getByRole('button', { name: 'Neu laden' });
			await expect(reload).toBeVisible();
			await showList(page, phone);
			await row(page, 'Wartet?').click();
			await pick(page, 'A').click();
			await show(page, phone, 'Refusiert?');

			await reload.click();

			await expect(page.getByText('Geändert.')).toBeVisible();
			await expect(page.locator('.strip')).toHaveCount(1);
			await expect(pick(page, 'A')).toBeEnabled();
		});

		test('[ABRD-104] a slow read shows Reading… busy and clickable, turns the arrow and asks for one more read', async ({
			page
		}, testInfo) => {
			await arrange([item(61, 'First', card('Erste?'))]);
			await visit(page);
			let release: (() => void) | undefined;
			const held = new Promise<void>((resolve) => {
				release = resolve;
			});
			await page.route('**/api/board', async (route) => {
				await held;
				await route.continue();
			});
			const reads = countBoardReads(page);
			const button = refreshButton(page);

			try {
				await button.click();
				await expect(button).toHaveAccessibleName(new RegExp(`^${READING_LABEL} · read `));
				await expect(button).toHaveAttribute('aria-busy', 'true');
				await expect(button).toBeEnabled();
				await expect(button.locator('.arrow')).not.toHaveCSS('animation-name', 'none');
				await page.screenshot({ path: testInfo.outputPath('reading.png') });
				await page.emulateMedia({ reducedMotion: 'reduce' });
				await expect(button.locator('.arrow')).toHaveCSS('animation-name', 'none');
				await expect(button).toHaveCSS('outline-style', 'dashed');
				await button.click();
			} finally {
				release?.();
			}

			await expect(button).toHaveAttribute('aria-busy', 'false');
			await expect(button).toBeFocused();
			expect(reads.count()).toBe(2);
		});
	});
}

test.describe('timers and return to the tab', () => {
	test('[ABRD-103] returning to the tab reads only once the last read is over the stale bound', async ({
		page
	}) => {
		await arrange([item(61, 'First', card('Erste?'))]);
		await visit(page);
		const reads = countBoardReads(page);
		await setTabVisibility(page, 'hidden');

		await page.clock.runFor((STALE_AFTER_SECONDS - 5) * 1000);
		await setTabVisibility(page, 'visible');
		expect(reads.count()).toBe(0);
		await setTabVisibility(page, 'hidden');
		await page.clock.runFor(6000);
		await setTabVisibility(page, 'visible');

		await expect.poll(reads.count).toBe(1);
	});

	test('[ABRD-103] the page reads every self-refresh interval while visible, and not while hidden', async ({
		page
	}) => {
		await arrange([item(61, 'First', card('Erste?'))]);
		await visit(page);
		const reads = countBoardReads(page);

		await page.clock.runFor(SELF_REFRESH_MS - 1000);
		expect(reads.count()).toBe(0);
		await page.clock.runFor(2000);
		await expect.poll(reads.count).toBe(1);
		await setTabVisibility(page, 'hidden');
		await page.clock.runFor(SELF_REFRESH_MS * 2);

		expect(reads.count()).toBe(1);
	});
});
