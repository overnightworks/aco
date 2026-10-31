import type { Locator, Page } from '@playwright/test';
import { expect, test } from './consoleGuard';
import { countPosts, pick } from './decideRow';
import {
	arrange,
	item,
	optionEntry,
	storedLine,
	type CardOption,
	type Item,
	type OptionEntry
} from './itemFixture';
import { readBoardRuntime } from './runtime';
import { LINE_CHANGED_MESSAGE, UNDO_SECONDS } from '../src/app/model/decision';

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

function card(question: string, overrides: Partial<OptionEntry> = {}): OptionEntry {
	return optionEntry('Satz.', { question, option: OPTIONS, area: 'Seite', ...overrides });
}

const POINTS_NAME = 'Seite · 3 points';

function points(): OptionEntry[] {
	return [1, 2, 3].map((number) => card(`Punkt ${number}?`, { topic: `Thema ${number}` }));
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

async function visit(page: Page): Promise<void> {
	const { appUrl, token } = readBoardRuntime();
	await page.clock.install();
	await page.goto(`${appUrl}#t=${token}`);
}

/** Holds every request matching `pattern` until `release` is called. */
function holdRequests(page: Page, pattern: string): { release(): void; ready: Promise<void> } {
	let release: () => void = () => {};
	const held = new Promise<void>((resolve) => {
		release = resolve;
	});
	const ready = page.route(pattern, async (route) => {
		await held;
		await route.continue();
	});
	return { release, ready };
}

const opacityOf = (letter: Locator): Promise<number> =>
	letter.evaluate((element) => Number(getComputedStyle(element).opacity));

/** The page reads `before`, aco then holds `after`, and a pick on the card `question` is refused as changed. */
async function refuse(
	page: Page,
	phone: boolean,
	question: string,
	{ before, after }: { before: Item[]; after: Item[] }
): Promise<void> {
	await arrange(before);
	await visit(page);
	await show(page, phone, question);
	await arrange(after);
	await pick(page, 'A').click();
	await page.clock.runFor(PAST_UNDO_WINDOW_MS);
	await expect(page.getByRole('button', { name: 'Neu laden' })).toBeVisible();
}

/** The refused card, a changed or unchanged copy of it, and the cards `others`. */
function boardWith(changed: boolean, ...others: Item[]): Item[] {
	return [
		item(41, 'Refused', card('Refusiert?', changed ? { problem: 'Geändert.' } : {})),
		...others
	];
}

for (const viewport of [
	{ width: 1280, height: 900 },
	{ width: 390, height: 844 }
]) {
	const phone = viewport.width === 390;
	test.describe(`${viewport.width}px saving`, () => {
		test.use({ viewport });

		test('[ABRD-99] a pick marks its letter from the click, at full strength beside a dimmed other', async ({
			page
		}) => {
			await arrange([item(11, 'Window', card('Fenster?'))]);
			await visit(page);
			await show(page, phone, 'Fenster?');

			await pick(page, 'A').click();

			await expect(pick(page, 'A')).toHaveAttribute('aria-pressed', 'true');
			await expect(pick(page, 'B')).toHaveAttribute('aria-pressed', 'false');
			await expect(pick(page, 'B')).toBeDisabled();
			expect(await opacityOf(pick(page, 'A'))).toBeGreaterThan(await opacityOf(pick(page, 'B')));
		});

		test('[ABRD-100] a slow POST turns the row, the meta and the Decide row to Saving, and reduced motion stops the turn', async ({
			page
		}) => {
			await arrange([item(21, 'Slow', card('Langsam?'))]);
			await visit(page);
			await show(page, phone, 'Langsam?');
			const post = holdRequests(page, '**/api/rule');
			await post.ready;
			try {
				await pick(page, 'A').click();
				const posted = page.waitForRequest('**/api/rule');
				await page.clock.runFor(PAST_UNDO_WINDOW_MS);
				await posted;

				await expect(page.locator('.meta').getByText('saving', { exact: true })).toBeVisible();
				await expect(pick(page, 'A')).toHaveAttribute('aria-pressed', 'true');
				await expect(pick(page, 'A')).toBeDisabled();
				await expect(pick(page, 'B')).toBeDisabled();
				await expect(
					page.locator('.decide-row').getByText('Saving', { exact: true })
				).toBeVisible();
				await expect(page.getByRole('button', { name: 'Other…' })).toHaveCount(0);

				if (phone) await page.getByRole('button', { name: '‹ Open' }).click();
				const turning = listRow(page, 'Langsam?')
					.getByRole('img', { name: 'Saving' })
					.locator('svg');
				await expect(turning).toBeVisible();
				await expect(turning).not.toHaveCSS('animation-name', 'none');
				await page.emulateMedia({ reducedMotion: 'reduce' });
				await expect(turning).toHaveCSS('animation-name', 'none');
			} finally {
				post.release();
			}
		});

		test('[ABRD-100] a card of points keeps its picks held, locks Accept all, shows Saving, opens a point and ends in Decided', async ({
			page
		}) => {
			await arrange([item(31, 'Points', ...points())]);
			await visit(page);
			await show(page, phone, POINTS_NAME);
			const post = holdRequests(page, '**/api/rule');
			await post.ready;
			try {
				for (const number of [1, 2, 3]) {
					await page.getByRole('button', { name: new RegExp(`^Point ${number}: A –`) }).click();
				}
				const posted = page.waitForRequest('**/api/rule');
				await page.clock.runFor(PAST_UNDO_WINDOW_MS);
				await posted;

				const held = page.getByRole('button', { pressed: true, name: /^Point \d: A –/ });
				await expect(held).toHaveCount(3);
				for (const letter of await held.all()) await expect(letter).toBeDisabled();
				await expect(
					page.getByRole('button', { name: 'Accept all recommendations' })
				).toBeDisabled();
				await expect(
					page.locator('.decide-row').getByText('Saving', { exact: true })
				).toBeVisible();
				await expect(page.getByRole('button', { name: 'Other…' })).toHaveCount(0);
				await expect(page.getByRole('button', { name: 'Unclear' })).toHaveCount(0);
				const toggle = page.locator('button.toggle').first();
				await toggle.click();
				await expect(toggle).toHaveAttribute('aria-expanded', 'true');
			} finally {
				post.release();
			}
			await expect(page.getByRole('button', { name: /^Decided 3$/ })).toBeVisible();
			await expect.poll(() => storedLine(31, 1)).toMatchObject({ ruling: 'A', via: 'board' });
		});
		test('[ABRD-97] a Neu laden read held while another card saves keeps its Saving and its letter, and every other click counts', async ({
			page
		}) => {
			const others = [
				item(42, 'Saving', card('Speichert?')),
				item(43, 'Pick', card('Pick?')),
				item(44, 'Other', card('Anderes?'))
			];
			await refuse(page, phone, 'Refusiert?', {
				before: boardWith(false, ...others),
				after: boardWith(true, ...others)
			});
			const posts = countPosts(page);
			await show(page, phone, 'Speichert?');
			await pick(page, 'A').click();
			await show(page, phone, 'Refusiert?');
			const read = holdRequests(page, '**/api/board');
			const post = holdRequests(page, '**/api/rule');
			await Promise.all([read.ready, post.ready]);
			try {
				const reading = page.waitForRequest('**/api/board');
				await page.getByRole('button', { name: 'Neu laden' }).click();
				await reading;
				const posted = page.waitForRequest('**/api/rule');
				await page.clock.runFor(PAST_UNDO_WINDOW_MS);
				await posted;

				await show(page, phone, 'Pick?');
				await pick(page, 'B').click();
				await show(page, phone, 'Anderes?');
				await page.getByRole('button', { name: 'Other…' }).click();
				await page.getByRole('textbox').fill('Nur am Desktop.');
				await page.getByRole('button', { name: 'Send' }).click();
				await expect(page.locator('.strip')).toHaveCount(2);

				const answered = page.waitForResponse('**/api/board');
				read.release();
				await answered;
				await show(page, phone, 'Speichert?');
				await expect(pick(page, 'A')).toHaveAttribute('aria-pressed', 'true');
				await expect(
					page.locator('.decide-row').getByText('Saving', { exact: true })
				).toBeVisible();
			} finally {
				read.release();
				post.release();
			}
			await expect.poll(() => storedLine(42, 1)).toMatchObject({ ruling: 'A', via: 'board' });
			await expect(page.getByRole('button', { name: /^Decided 1$/ })).toBeVisible();
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);
			await expect.poll(() => storedLine(43, 1)).toMatchObject({ ruling: 'B', via: 'board' });
			await expect
				.poll(() => storedLine(44, 1))
				.toMatchObject({ ruling: 'other', other: 'Nur am Desktop.' });
			expect(posts.count()).toBe(3);
		});

		test('[ABRD-97] a pick made during a held read on a card the read changes ends in the changed banner, storing nothing', async ({
			page
		}) => {
			const watched = item(42, 'Watched', card('Beobachtet?'));
			await refuse(page, phone, 'Refusiert?', {
				before: boardWith(false, watched),
				after: boardWith(true, watched)
			});
			const read = holdRequests(page, '**/api/board');
			await read.ready;
			try {
				const reading = page.waitForRequest('**/api/board');
				await page.getByRole('button', { name: 'Neu laden' }).click();
				await reading;
				await show(page, phone, 'Beobachtet?');
				await pick(page, 'A').click();
				await arrange([
					...boardWith(true),
					item(42, 'Watched', card('Beobachtet?', { problem: 'Neu geschrieben.' }))
				]);
				const answered = page.waitForResponse('**/api/board');
				read.release();
				await answered;
			} finally {
				read.release();
			}
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);

			await expect(page.getByText(LINE_CHANGED_MESSAGE)).toBeVisible();
			expect((await storedLine(42, 1)).ruling).toBeNull();
		});

		test('[ABRD-45] the refused card’s own Neu laden read locks that card alone until it answers', async ({
			page
		}) => {
			const neighbour = item(42, 'Neighbour', card('Nachbar?'));
			await refuse(page, phone, 'Refusiert?', {
				before: boardWith(false, neighbour),
				after: boardWith(true, neighbour)
			});
			const read = holdRequests(page, '**/api/board');
			await read.ready;
			try {
				const reading = page.waitForRequest('**/api/board');
				await page.getByRole('button', { name: 'Neu laden' }).click();
				await reading;

				await expect(pick(page, 'A')).toBeDisabled();
				await expect(pick(page, 'B')).toBeDisabled();
				await expect(page.getByRole('button', { name: 'Other…' })).toBeDisabled();
				await show(page, phone, 'Nachbar?');
				await pick(page, 'A').click();
				await expect(page.locator('.strip')).toHaveCount(1);

				const answered = page.waitForResponse('**/api/board');
				read.release();
				await answered;
			} finally {
				read.release();
			}
			await show(page, phone, 'Refusiert?');
			await expect(pick(page, 'A')).toBeEnabled();
			await expect(page.getByRole('button', { name: 'Other…' })).toBeEnabled();
		});
	});
}
