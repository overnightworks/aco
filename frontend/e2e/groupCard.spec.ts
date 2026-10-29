import { readFileSync } from 'node:fs';
import path from 'node:path';
import type { Locator, Page, Response } from '@playwright/test';
import { expect, test } from './consoleGuard';
import { decidedList, expectDecidedAnswer } from './decidedView';
import {
	optionLine,
	row,
	writeRulings,
	type OptionRulingLine,
	type RulingOption,
	type RulingRow
} from './rulingsFixture';
import { readBoardRuntime } from './runtime';
import {
	ALREADY_RULED_MESSAGE,
	LINE_CHANGED_MESSAGE,
	UNDO_SECONDS
} from '../src/app/model/decision';

// One shared board server backs every test in this file (see
// global-setup.ts); each test overwrites the whole of rulings.json.
test.describe.configure({ mode: 'serial' });

// Just past the app's undo window; the page clock is driven, never waited.
const PAST_UNDO_WINDOW_MS = UNDO_SECONDS * 1000 + 500;

// The fake aco stores every board pick as `--via board` on this date.
const BOARD_PICK_HOW = 'Board · 03.10.2026';

const CARD_NAME = 'Song-Seite · 3 points';
const ANSWER = 'Nur am Desktop';
const NOTE = 'Warum drei Fragen?';

const OPTIONS: RulingOption[] = (['A', 'B'] as const).map((letter) => ({
	letter,
	name: `Weg ${letter}`,
	effect: `Wirkung von Weg ${letter}.`,
	same_as_today: true,
	notice: 'Du merkst es.',
	cost: 'Aufwand.',
	undo: 'reversible',
	undo_how: 'jederzeit',
	contract: `Vertrag ${letter}.`
}));

const FINAL_OPTIONS: RulingOption[] = [
	OPTIONS[0] as RulingOption,
	{ ...(OPTIONS[1] as RulingOption), undo: 'final', undo_how: 'nicht rückholbar.' }
];

function point(index: number, overrides: Partial<OptionRulingLine> = {}): OptionRulingLine {
	return optionLine(index, `Satz ${index}.`, {
		question: `Frage ${index}?`,
		problem: `Problem ${index}.`,
		topic: `Thema ${index}`,
		area: 'Song-Seite',
		recommended: 'A',
		options: OPTIONS,
		...overrides
	});
}

function threePoints(): OptionRulingLine[] {
	return [point(2), point(3), point(4)];
}

function arrange(directory: string, points: OptionRulingLine[] = threePoints()): void {
	writeRulings(directory, [row(7, 'Sprung', ...points), row(9, 'Gäste', point(1))]);
}

function stored(directory: string, itemNumber: number, index: number): OptionRulingLine {
	const rows = JSON.parse(
		readFileSync(path.join(directory, 'rulings.json'), 'utf-8')
	) as RulingRow[];
	const found = rows
		.find((candidate) => candidate.number === itemNumber)
		?.lines.find((candidate) => candidate.index === index);
	if (found === undefined) throw new Error(`no line ${index} in item ${itemNumber}`);
	return found as OptionRulingLine;
}

async function expectRuled(directory: string, letters: string[]): Promise<void> {
	for (const [position, letter] of letters.entries()) {
		await expect
			.poll(() => stored(directory, 7, position + 2))
			.toMatchObject({ ruling: letter, via: 'board' });
	}
}

async function send(page: Page, kind: 'other' | 'unclear'): Promise<void> {
	if (kind === 'other') {
		await page.getByRole('button', { name: 'Other…' }).click();
		await page.getByRole('textbox', { name: 'Your answer' }).fill(ANSWER);
	} else {
		await page.getByRole('button', { name: 'Unclear' }).click();
		await page.getByRole('textbox', { name: 'What is unclear? (optional)' }).fill(NOTE);
	}
	await page.getByRole('button', { name: 'Send' }).click();
}

function logPosts(page: Page): Record<string, unknown>[] {
	const bodies: Record<string, unknown>[] = [];
	page.on('request', (request) => {
		if (request.method() === 'POST') bodies.push(request.postDataJSON());
	});
	return bodies;
}

type BoardJson = { repos: { items: { lines: { index: number; fingerprint: string }[] }[] }[] };

function logBoards(page: Page): Response[] {
	const boards: Response[] = [];
	page.on('response', (response) => {
		if (response.url().endsWith('/api/board')) boards.push(response);
	});
	return boards;
}

async function fingerprintOf(
	board: Response | undefined,
	index: number
): Promise<string | undefined> {
	const read = (await board?.json()) as BoardJson | undefined;
	return read?.repos[0]?.items
		.flatMap((entry) => entry.lines)
		.find((entry) => entry.index === index)?.fingerprint;
}

async function visit(page: Page): Promise<void> {
	const { appUrl, token } = readBoardRuntime();
	await page.clock.install();
	await page.goto(`${appUrl}#t=${token}`);
}

async function showCard(page: Page, phone: boolean, title: string): Promise<void> {
	if (phone) {
		const back = page.getByRole('button', { name: '‹ Open' });
		if (await back.isVisible()) await back.click();
	}
	await page.locator('.tracks').getByTitle(title, { exact: true }).click();
	if (phone) await expect(page.locator('.question-pane')).toBeVisible();
}

async function open(page: Page, phone: boolean, title = CARD_NAME): Promise<void> {
	await visit(page);
	await showCard(page, phone, title);
}

const card = (page: Page): Locator => page.locator('.option-card');
const toggle = (page: Page, number: number): Locator =>
	card(page)
		.locator('button.toggle')
		.nth(number - 1);
const pointPicks = (page: Page, number: number): Locator =>
	page.getByRole('group', { name: `Point ${number}` });
const pick = (page: Page, number: number, letter: string): Locator =>
	page.getByRole('button', { name: new RegExp(`^Point ${number}: ${letter} –`) });
const acceptAll = (page: Page): Locator =>
	page.getByRole('button', { name: 'Accept all recommendations' });
const strip = (page: Page): Locator => page.locator('.strip');
const undo = (page: Page): Locator =>
	strip(page).getByRole('button', { name: 'Undo', exact: true });
const decideBar = (page: Page): Locator => page.locator('.decide-row .bar');

async function pickAll(page: Page, letters: string[]): Promise<void> {
	for (const [position, letter] of letters.entries())
		await pick(page, position + 1, letter).click();
}

async function shoot(page: Page, testInfo: { outputPath(name: string): string }, name: string) {
	const filter = (value: string) =>
		page.evaluate((css) => {
			document.body.style.filter = css;
		}, value);
	await page.screenshot({ path: testInfo.outputPath(`${name}.png`) });
	await filter('blur(4px) grayscale(1)');
	await page.screenshot({ path: testInfo.outputPath(`${name}-shapes.png`) });
	await filter('');
}

async function fits(page: Page, width: number): Promise<void> {
	expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
		width
	);
}

function cardPost(item: number, lines: object[], answer: object = {}): object {
	return { repo: 'repo', item, lines, ...answer };
}

for (const viewport of [
	{ width: 1280, height: 900 },
	{ width: 390, height: 844 }
]) {
	const phone = viewport.width === 390;
	test.describe(`${viewport.width}px card of points`, () => {
		test.use({ viewport });

		test('[ABRD-82] an item’s open option lines are one Open row named by area and count, beside another open row, and the tab counts rows', async ({
			page
		}, testInfo) => {
			arrange(readBoardRuntime().repoDirectory);
			await visit(page);

			const rows = page.locator('.tracks').getByRole('button');
			await expect(rows).toHaveCount(2);
			await expect(rows.nth(0)).toHaveAccessibleName(`Open ${CARD_NAME}`);
			await expect(rows.nth(0)).toHaveAttribute('title', CARD_NAME);
			await expect(rows.nth(1)).toHaveAccessibleName('Open Thema 1');
			await expect(page.getByRole('button', { name: 'Open 2', exact: true })).toBeVisible();
			await shoot(page, testInfo, 'list');
		});

		test('[ABRD-83] the card is titled by its name, carries the meta of its points, has no Problem row and offers Accept all, the count, Other… and Unclear', async ({
			page
		}, testInfo) => {
			arrange(readBoardRuntime().repoDirectory);
			await open(page, phone);

			await expect(card(page).locator('.meta')).toHaveText(
				/^\s*repo › Song-Seite\s*·\s*Product\s*·\s*reversible\s*$/
			);
			await expect(card(page).getByRole('heading', { name: CARD_NAME, exact: true })).toBeVisible();
			await expect(card(page).getByText('Problem', { exact: true })).toHaveCount(0);
			await expect(card(page).getByText('Points', { exact: true })).toHaveCount(1);
			await expect(card(page).locator('button.toggle')).toHaveText([
				/^\s*1\s+Frage 2\?/,
				/^\s*2\s+Frage 3\?/,
				/^\s*3\s+Frage 4\?/
			]);
			for (const number of [1, 2, 3]) {
				await expect(toggle(page, number)).toHaveAttribute('aria-expanded', 'false');
				await expect(pointPicks(page, number).getByRole('button')).toHaveText(['A', 'B']);
				await expect(pick(page, number, 'A')).toHaveClass(/recommended/);
				await expect(pick(page, number, 'A')).toHaveAttribute('aria-pressed', 'false');
			}
			await expect(decideBar(page).getByRole('button')).toHaveText([
				'Accept all',
				'Other…',
				'Unclear'
			]);
			await expect(acceptAll(page)).toHaveClass(/recommended/);
			await expect(decideBar(page).getByText('0 of 3 chosen')).toBeVisible({ visible: !phone });
			await shoot(page, testInfo, 'card');
			await fits(page, viewport.width);
		});

		test('[ABRD-85] one point is open at a time, with its rows and a Today that enlarges, and a phone keeps the Decide row in view', async ({
			page
		}, testInfo) => {
			arrange(readBoardRuntime().repoDirectory);
			await open(page, phone);

			await toggle(page, 1).click();
			await expect(toggle(page, 1)).toHaveAttribute('aria-expanded', 'true');
			await expect(card(page).getByText('Problem 2.')).toBeVisible();
			await expect(card(page).getByRole('term')).toHaveText([
				'Points',
				'Problem',
				'Today',
				'Options',
				'Recommendation',
				'',
				'',
				'Decide'
			]);
			await shoot(page, testInfo, 'point-open');

			await toggle(page, 2).click();
			await expect(toggle(page, 1)).toHaveAttribute('aria-expanded', 'false');
			await expect(toggle(page, 2)).toHaveAttribute('aria-expanded', 'true');
			await expect(card(page).getByText('Problem', { exact: true })).toHaveCount(1);
			await expect(card(page).getByText('Problem 3.')).toBeVisible();

			await card(page).getByRole('button', { name: 'Enlarge picture' }).click();
			const dialog = page.getByRole('dialog', { name: 'Picture at full width' });
			await expect(dialog).toBeVisible();
			await dialog.getByRole('button', { name: 'Close' }).click();
			await expect(dialog).toHaveCount(0);

			await toggle(page, 2).click();
			await expect(toggle(page, 2)).toHaveAttribute('aria-expanded', 'false');
			await expect(card(page).getByText('Problem', { exact: true })).toHaveCount(0);

			if (phone) {
				await toggle(page, 1).click();
				await expect(page.locator('.decide-row')).toHaveCSS('position', 'sticky');
				await expect(page.locator('.decide-row')).toBeInViewport();
				await expect(acceptAll(page)).toBeInViewport();
				await expect(page.getByRole('button', { name: 'Other…' })).toBeInViewport();
				await expect(page.getByRole('button', { name: 'Unclear' })).toBeInViewport();
				await fits(page, viewport.width);
			}
		});

		test('[ABRD-84] the points, their picks and Accept all are reachable by keyboard with the right state', async ({
			page
		}) => {
			arrange(readBoardRuntime().repoDirectory);
			await open(page, phone);

			await toggle(page, 1).focus();
			await page.keyboard.press('Enter');
			await expect(toggle(page, 1)).toHaveAttribute('aria-expanded', 'true');
			await page.keyboard.press('Enter');
			await expect(toggle(page, 1)).toHaveAttribute('aria-expanded', 'false');
			await page.keyboard.press('Tab');
			await expect(pick(page, 1, 'A')).toBeFocused();
			await page.keyboard.press('Tab');
			await expect(pick(page, 1, 'B')).toBeFocused();
			await page.keyboard.press('Space');
			await expect(pick(page, 1, 'B')).toHaveAttribute('aria-pressed', 'true');
			await expect(pick(page, 1, 'A')).toHaveAttribute('aria-pressed', 'false');

			await acceptAll(page).focus();
			await page.keyboard.press('Enter');
			await expect(undo(page)).toBeFocused();
		});

		test('[ABRD-86] a pick marks its point, posts nothing and opens the first unchosen point when it was the open one', async ({
			page
		}) => {
			arrange(readBoardRuntime().repoDirectory);
			const posts = logPosts(page);
			await open(page, phone);

			await toggle(page, 1).click();
			await pick(page, 1, 'B').click();

			await expect(pick(page, 1, 'B')).toHaveAttribute('aria-pressed', 'true');
			await expect(decideBar(page).getByText('1 of 3 chosen')).toBeAttached();
			await expect(toggle(page, 1)).toHaveAttribute('aria-expanded', 'false');
			await expect(toggle(page, 2)).toHaveAttribute('aria-expanded', 'true');
			await pick(page, 1, 'A').click();
			await expect(pick(page, 1, 'A')).toHaveAttribute('aria-pressed', 'true');
			await expect(pick(page, 1, 'B')).toHaveAttribute('aria-pressed', 'false');
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);
			expect(posts).toEqual([]);
		});

		test('[ABRD-87] the last pick starts one window with one strip, then one post stores every point, and Decided lists each point', async ({
			page
		}, testInfo) => {
			const { repoDirectory } = readBoardRuntime();
			arrange(repoDirectory);
			const posts = logPosts(page);
			await open(page, phone);

			await pickAll(page, ['B', 'A', 'A']);

			await expect(strip(page)).toHaveCount(1);
			await expect(strip(page)).toContainText(`Decided: 1B 2A 3A · ${CARD_NAME}`);
			await expect(undo(page)).toBeFocused();
			await shoot(page, testInfo, 'strip');
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);

			await expect
				.poll(() => posts)
				.toEqual([
					cardPost(7, [
						{ line: 2, fingerprint: expect.any(String), option: 'B' },
						{ line: 3, fingerprint: expect.any(String), option: 'A' },
						{ line: 4, fingerprint: expect.any(String), option: 'A' }
					])
				]);
			await expectRuled(repoDirectory, ['B', 'A', 'A']);
			if (!phone) await expect(page.getByRole('heading', { name: 'Frage 1?' })).toBeVisible();
			if (phone) await page.getByRole('button', { name: '‹ Open' }).click();
			await page.getByRole('button', { name: /^Decided \d+$/ }).click();
			const rows = decidedList(page).getByRole('button');
			await expect(rows).toHaveCount(3);
			await expect(rows).toContainText(['Thema 4', 'Thema 3', 'Thema 2']);
			await decidedList(page).getByTitle('Frage 2?', { exact: true }).click();
			await expectDecidedAnswer(page, 'B — Weg B', BOARD_PICK_HOW);
		});

		test('[ABRD-87] Undo inside the window posts nothing and clears the picks', async ({
			page
		}) => {
			const { repoDirectory } = readBoardRuntime();
			arrange(repoDirectory);
			const posts = logPosts(page);
			await open(page, phone);

			await pickAll(page, ['B', 'A', 'A']);
			await undo(page).click();
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);

			expect(posts).toEqual([]);
			await expect(strip(page)).toHaveCount(0);
			await expect(pointPicks(page, 1).getByRole('button', { pressed: true })).toHaveCount(0);
			await expect(decideBar(page).getByText('0 of 3 chosen')).toBeAttached();
			expect(stored(repoDirectory, 7, 2).ruling).toBeNull();
		});

		test('[ABRD-88] a final pick asks first with its point, and Cancel leaves the point unchosen', async ({
			page
		}) => {
			arrange(readBoardRuntime().repoDirectory, [
				point(2),
				point(3, { options: FINAL_OPTIONS }),
				point(4)
			]);
			const posts = logPosts(page);
			await open(page, phone);

			await pick(page, 2, 'B').click();
			const dialog = page.getByRole('dialog', { name: 'Decide B?' });
			await expect(dialog).toContainText('Point 2: Nicht rückholbar.');
			await expect(dialog.getByRole('button', { name: 'Cancel' })).toBeFocused();
			await dialog.getByRole('button', { name: 'Cancel' }).click();

			await expect(dialog).toHaveCount(0);
			await expect(pick(page, 2, 'B')).toHaveAttribute('aria-pressed', 'false');
			await expect(pick(page, 2, 'B')).toBeFocused();
			await expect(decideBar(page).getByText('0 of 3 chosen')).toBeAttached();

			await pick(page, 2, 'B').click();
			await page
				.getByRole('dialog', { name: 'Decide B?' })
				.getByRole('button', { name: 'Decide B', exact: true })
				.click();
			await expect(pick(page, 2, 'B')).toHaveAttribute('aria-pressed', 'true');
			await expect(decideBar(page).getByText('1 of 3 chosen')).toBeAttached();
			expect(posts).toEqual([]);
		});

		test('[ABRD-89] Accept all with nothing final picks each recommended letter, shows the strip and posts once', async ({
			page
		}) => {
			const { repoDirectory } = readBoardRuntime();
			arrange(repoDirectory, [point(2), point(3, { recommended: 'B' }), point(4)]);
			const posts = logPosts(page);
			await open(page, phone);
			await pick(page, 1, 'B').click();

			await acceptAll(page).click();

			await expect(page.getByRole('dialog')).toHaveCount(0);
			await expect(strip(page)).toContainText(`Decided: 1A 2B 3A · ${CARD_NAME}`);
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);
			await expect.poll(() => posts.length).toBe(1);
			await expectRuled(repoDirectory, ['A', 'B', 'A']);
		});

		test('[ABRD-90] Accept all with a final recommendation asks first, Cancel or Esc post nothing, and confirming stores the recommendations', async ({
			page
		}, testInfo) => {
			const { repoDirectory } = readBoardRuntime();
			arrange(repoDirectory, [
				point(2),
				point(3, { options: FINAL_OPTIONS, recommended: 'B' }),
				point(4)
			]);
			const posts = logPosts(page);
			await open(page, phone);
			const dialog = page.getByRole('dialog', { name: 'Accept all recommendations?' });

			await acceptAll(page).click();
			await expect(dialog).toContainText('Point 2: Nicht rückholbar.');
			await expect(dialog.getByRole('button', { name: 'Cancel' })).toBeFocused();
			await shoot(page, testInfo, 'accept-all-confirm');
			await page.keyboard.press('Escape');
			await expect(dialog).toHaveCount(0);
			await acceptAll(page).click();
			await dialog.getByRole('button', { name: 'Cancel' }).click();
			await expect(dialog).toHaveCount(0);
			await expect(strip(page)).toHaveCount(0);
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);
			expect(posts).toEqual([]);

			await acceptAll(page).click();
			await dialog.getByRole('button', { name: 'Accept all', exact: true }).click();
			await expect(strip(page)).toContainText(`Decided: 1A 2B 3A · ${CARD_NAME}`);
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);
			await expect.poll(() => posts.length).toBe(1);
			await expectRuled(repoDirectory, ['A', 'B', 'A']);
		});

		test('[ABRD-92] Other… answers the whole card with one text, after one strip', async ({
			page
		}) => {
			const { repoDirectory } = readBoardRuntime();
			arrange(repoDirectory);
			const posts = logPosts(page);
			await open(page, phone);

			await send(page, 'other');

			await expect(strip(page)).toContainText(`Decided: Other · ${CARD_NAME}`);
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);
			await expect
				.poll(() => posts)
				.toEqual([
					cardPost(
						7,
						[2, 3, 4].map((index) => ({ line: index, fingerprint: expect.any(String) })),
						{ other: ANSWER }
					)
				]);
			for (const index of [2, 3, 4]) {
				await expect
					.poll(() => stored(repoDirectory, 7, index))
					.toMatchObject({ ruling: 'other', other: ANSWER });
			}
		});

		test('[ABRD-92] Unclear sends the whole card back with its note, and the card is then with its head without Unclear', async ({
			page
		}, testInfo) => {
			const { repoDirectory } = readBoardRuntime();
			arrange(repoDirectory);
			const posts = logPosts(page);
			await open(page, phone);

			await send(page, 'unclear');

			await expect(strip(page)).toContainText(`With head: ${CARD_NAME}`);
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);
			await expect
				.poll(() => posts)
				.toEqual([
					cardPost(
						7,
						[2, 3, 4].map((index) => ({ line: index, fingerprint: expect.any(String) })),
						{ unclear: true, note: NOTE }
					)
				]);
			for (const index of [2, 3, 4]) {
				await expect.poll(() => stored(repoDirectory, 7, index).returned_on).not.toBeNull();
			}
			if (phone) await page.getByRole('button', { name: '‹ Open' }).click();
			await expect(page.locator('.tracks').getByTitle(CARD_NAME)).toHaveAccessibleName(
				`With head ${CARD_NAME}`
			);
			await showCard(page, phone, CARD_NAME);
			await expect(card(page).locator('.meta')).toContainText('with head');
			await expect(page.getByRole('button', { name: 'Unclear' })).toHaveCount(0);
			await expect(acceptAll(page)).toBeVisible();
			await shoot(page, testInfo, 'with-head');
		});

		test('[ABRD-61] points in different areas join their areas, and a card with one point with its head lists muted after the open cards and offers no Unclear', async ({
			page
		}, testInfo) => {
			const { repoDirectory } = readBoardRuntime();
			writeRulings(repoDirectory, [
				row(
					7,
					'Sprung',
					point(2),
					point(3, { area: 'Bibliothek', returned_on: '2026-10-27', returned_note: 'Warum?' })
				),
				row(8, 'Offen', point(1, { topic: 'Offen', question: 'Offene Frage?' }))
			]);
			await visit(page);

			const name = 'Song-Seite / Bibliothek · 2 points';
			const rows = page.locator('.tracks').getByRole('button');
			await expect(rows.nth(0)).toHaveAccessibleName('Open Offen');
			await expect(rows.nth(1)).toHaveAccessibleName(`With head ${name}`);
			await expect(rows.nth(1).getByRole('img', { name: 'With head' })).toBeVisible();
			await showCard(page, phone, name);
			await expect(card(page).locator('.meta')).toHaveText(
				/^\s*repo › Song-Seite \/ Bibliothek\s*·\s*Product\s*·\s*with head\s*·\s*reversible\s*$/
			);
			await expect(card(page).getByRole('heading', { name, exact: true })).toBeVisible();
			await expect(page.getByRole('button', { name: 'Unclear' })).toHaveCount(0);
			await expect(page.getByRole('button', { name: 'Other…' })).toBeVisible();
			await expect(acceptAll(page)).toBeVisible();
			await expect(pointPicks(page, 1).getByRole('button')).toHaveText(['A', 'B']);
			await shoot(page, testInfo, 'with-head-card');
			await fits(page, viewport.width);
		});

		test('[ABRD-92] Other… on a card with a point with its head stores every point and drops the sent-back marks', async ({
			page
		}) => {
			const { repoDirectory } = readBoardRuntime();
			writeRulings(repoDirectory, [
				row(7, 'Sprung', point(2), point(3, { returned_on: '2026-10-27', returned_note: 'Warum?' }))
			]);
			await open(page, phone, 'Song-Seite · 2 points');

			await send(page, 'other');
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);

			for (const index of [2, 3]) {
				await expect
					.poll(() => stored(repoDirectory, 7, index))
					.toMatchObject({ ruling: 'other', other: ANSWER, returned_on: null });
			}
		});

		test('[ABRD-36] a one-point card looks as before, has no Accept all and posts the card form with one entry', async ({
			page
		}) => {
			const { repoDirectory } = readBoardRuntime();
			writeRulings(repoDirectory, [
				row(8, 'Offen', point(1, { topic: 'Einzel', question: 'Eine Frage?' }))
			]);
			const posts = logPosts(page);
			await visit(page);

			await expect(page.locator('.tracks').getByTitle('Eine Frage?')).toHaveAccessibleName(
				'Open Einzel'
			);
			await showCard(page, phone, 'Eine Frage?');
			await expect(
				card(page).getByRole('heading', { name: 'Eine Frage?', exact: true })
			).toBeVisible();
			await expect(card(page).getByRole('term')).toHaveText([
				'Problem',
				'Today',
				'Options',
				'Recommendation',
				'Decide'
			]);
			await expect(acceptAll(page)).toHaveCount(0);
			await page
				.getByRole('group', { name: 'Decide' })
				.getByRole('button', { name: /^Decide B:/ })
				.click();
			await expect(strip(page)).toContainText('Decided: B — Weg B · Einzel');
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);

			await expect
				.poll(() => posts)
				.toEqual([cardPost(8, [{ line: 1, fingerprint: expect.any(String), option: 'B' }])]);
			await expect
				.poll(() => stored(repoDirectory, 8, 1))
				.toMatchObject({ ruling: 'B', via: 'board' });
		});

		for (const kind of ['other', 'unclear'] as const) {
			test(`[ABRD-75] ${kind} on a one-point card posts one entry`, async ({ page }) => {
				const { repoDirectory } = readBoardRuntime();
				writeRulings(repoDirectory, [row(8, 'Offen', point(1, { topic: 'Einzel' }))]);
				const posts = logPosts(page);
				await open(page, phone, 'Frage 1?');

				await send(page, kind);
				await page.clock.runFor(PAST_UNDO_WINDOW_MS);

				const entry = [{ line: 1, fingerprint: expect.any(String) }];
				await expect
					.poll(() => posts)
					.toEqual([
						cardPost(8, entry, kind === 'other' ? { other: ANSWER } : { unclear: true, note: NOTE })
					]);
				await expect
					.poll(() => stored(repoDirectory, 8, 1))
					.toMatchObject(
						kind === 'other' ? { ruling: 'other' } : { returned_on: expect.any(String) }
					);
			});
		}

		for (const how of ['the last pick', 'Accept all'] as const) {
			test(`[ABRD-91] ${how} on a card that gained a point after the page read is refused, nothing is stored, and Neu laden keeps the picks of the unchanged points`, async ({
				page
			}) => {
				const { repoDirectory } = readBoardRuntime();
				arrange(repoDirectory);
				await open(page, phone);
				arrange(repoDirectory, [...threePoints(), point(6)]);

				if (how === 'Accept all') await acceptAll(page).click();
				else await pickAll(page, ['B', 'A', 'A']);
				await page.clock.runFor(PAST_UNDO_WINDOW_MS);

				await expect(page.getByRole('alert')).toContainText(LINE_CHANGED_MESSAGE);
				await expect(pointPicks(page, 1)).toHaveCount(0);
				await expect(acceptAll(page)).toHaveCount(0);
				for (const index of [2, 3, 4, 6]) {
					expect(stored(repoDirectory, 7, index).ruling).toBeNull();
				}
				await page.getByRole('button', { name: 'Neu laden' }).click();
				await expect(
					card(page).getByRole('heading', { name: 'Song-Seite · 4 points' })
				).toBeVisible();
				await expect(card(page).locator('button.toggle')).toHaveCount(4);
				await expect(page.getByRole('button', { pressed: true })).not.toHaveCount(0);
			});
		}

		test('[ABRD-80] a point ruled from chat meanwhile is refused as already ruled and nothing else is stored', async ({
			page
		}) => {
			const { repoDirectory } = readBoardRuntime();
			arrange(repoDirectory);
			await open(page, phone);
			arrange(repoDirectory, [
				point(2),
				point(3, { ruling: 'A', ruled_on: '2026-10-26', via: 'chat' }),
				point(4)
			]);

			await pickAll(page, ['B', 'A', 'A']);
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);

			await expect(page.getByRole('alert')).toContainText(ALREADY_RULED_MESSAGE);
			expect(stored(repoDirectory, 7, 2).ruling).toBeNull();
			expect(stored(repoDirectory, 7, 4).ruling).toBeNull();
		});

		test('[ABRD-45] any other failure keeps the picks, and picking again posts again', async ({
			page
		}) => {
			const { repoDirectory } = readBoardRuntime();
			arrange(repoDirectory);
			const posts = logPosts(page);
			let failFirst = true;
			await page.route('**/api/rule', async (route) => {
				if (failFirst) {
					failFirst = false;
					await route.fulfill({
						status: 200,
						contentType: 'application/json',
						body: JSON.stringify({ status: 'failed', message: 'aco unavailable' })
					});
				} else {
					await route.continue();
				}
			});
			await open(page, phone);

			await pickAll(page, ['B', 'A', 'A']);
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);

			await expect(page.getByRole('alert')).toContainText('aco unavailable');
			await expect(page.getByRole('button', { pressed: true })).not.toHaveCount(0);
			await pick(page, 1, 'A').click();
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);

			await expect.poll(() => posts.length).toBe(2);
			await expect
				.poll(() => stored(repoDirectory, 7, 2))
				.toMatchObject({ ruling: 'A', via: 'board' });
		});

		test('[ABRD-91] a re-read after another card was decided drops a changed point’s pick, keeps the others, and the next post names the fresh point', async ({
			page
		}) => {
			const { repoDirectory } = readBoardRuntime();
			const second = row(8, 'Einzel', point(1, { topic: 'Einzel', question: 'Eine Frage?' }));
			writeRulings(repoDirectory, [row(7, 'Sprung', ...threePoints()), second]);
			const posts = logPosts(page);
			const boards = logBoards(page);
			await open(page, phone);

			await pickAll(page, ['B', 'B']);
			writeRulings(repoDirectory, [
				row(7, 'Sprung', point(2), point(3, { card_hash: 'card-hash-changed' }), point(4)),
				second
			]);
			await showCard(page, phone, 'Eine Frage?');
			await page
				.getByRole('group', { name: 'Decide' })
				.getByRole('button', { name: /^Decide A:/ })
				.click();
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);
			await showCard(page, phone, CARD_NAME);

			await expect(pick(page, 1, 'B')).toHaveAttribute('aria-pressed', 'true');
			await expect(pick(page, 2, 'B')).toHaveAttribute('aria-pressed', 'false');
			await expect(decideBar(page).getByText('1 of 3 chosen')).toBeAttached();
			const changed = await fingerprintOf(boards.at(-1), 3);
			await pickAll(page, ['B', 'B', 'A']);
			await page.clock.runFor(PAST_UNDO_WINDOW_MS);

			await expect.poll(() => posts.length).toBe(2);
			const cardPosted = posts.at(-1) as { lines: { line: number; fingerprint: string }[] };
			expect(cardPosted.lines.find((entry) => entry.line === 3)?.fingerprint).toBe(changed);
			expect(await fingerprintOf(boards[0], 3)).not.toBe(changed);
			await expectRuled(repoDirectory, ['B', 'B', 'A']);
		});
	});
}
