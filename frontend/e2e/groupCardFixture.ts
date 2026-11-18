import type { Locator, Page, Response } from '@playwright/test';
import { expect } from './consoleGuard';
import {
	arrange,
	item,
	optionEntry,
	storedLine,
	withdrawnEntry,
	type CardOption,
	type Item,
	type OptionEntry
} from './itemFixture';
import { readBoardRuntime } from './runtime';
import { UNDO_SECONDS } from '../src/app/model/decision';

export const PAST_UNDO_WINDOW_MS = UNDO_SECONDS * 1000 + 500;

// aco rules every board pick `via board` on `board_forge.RULING_DAY`.
export const BOARD_PICK_HOW = 'Board · 03.10.2026';

export const CARD_NAME = 'Song-Seite · 3 points';
export const ANSWER = 'Nur am Desktop';
export const NOTE = 'Warum drei Fragen?';

const OPTIONS: CardOption[] = (['A', 'B'] as const).map((letter) => ({
	name: `Weg ${letter}`,
	effect: `Wirkung von Weg ${letter}.`,
	same_as_today: true,
	notice: 'Du merkst es.',
	cost: 'Aufwand.',
	undo: 'reversible',
	undo_how: 'jederzeit',
	contract: `Vertrag ${letter}.`
}));

export const FINAL_OPTIONS: CardOption[] = [
	OPTIONS[0] as CardOption,
	{ ...(OPTIONS[1] as CardOption), undo: 'final', undo_how: 'nicht rückholbar.' }
];

/** A point named after `index`, the block position it is arranged at. */
export function point(index: number, overrides: Partial<OptionEntry> = {}): OptionEntry {
	return optionEntry(`Satz ${index}.`, {
		question: `Frage ${index}?`,
		problem: `Problem ${index}.`,
		topic: `Thema ${index}`,
		area: 'Song-Seite',
		recommended: 'A',
		option: OPTIONS,
		...overrides
	});
}

/** A withdrawn line the board hides, holding a block position before or between points. */
export function withdrawn(): Item['entries'][number] {
	return withdrawnEntry('Ein zurückgezogener Punkt.', '2026-10-01');
}

export function threePoints(): OptionEntry[] {
	return [point(2), point(3), point(4)];
}

/** Item 7, its line 1 withdrawn, so its points keep the indexes from 2 on. */
export function sprung(...points: Item['entries']): Item {
	return item(7, 'Sprung', withdrawn(), ...points);
}

export async function arrangeCards(points: Item['entries'] = threePoints()): Promise<void> {
	await arrange([sprung(...points), item(9, 'Gäste', point(1))]);
}

export async function expectRuled(letters: string[]): Promise<void> {
	for (const [position, letter] of letters.entries()) {
		await expect
			.poll(() => storedLine(7, position + 2))
			.toMatchObject({ ruling: letter, via: 'board' });
	}
}

/** Sends an answer for the card: Unclear, Other… at the point numbered `point`, or Other… on a one-point card. */
export async function send(page: Page, kind: 'other' | 'unclear', point?: number): Promise<void> {
	if (kind === 'other') {
		const scope = point === undefined ? '' : `Point ${point}: `;
		await page.getByRole('button', { name: `${scope}Other…`, exact: true }).click();
		await page.getByRole('textbox', { name: `${scope}Your answer`, exact: true }).fill(ANSWER);
	} else {
		await page.getByRole('button', { name: 'Unclear' }).click();
		await page.getByRole('textbox', { name: 'What is unclear? (optional)' }).fill(NOTE);
	}
	await page.getByRole('button', { name: 'Send' }).click();
}

export function logPosts(page: Page): Record<string, unknown>[] {
	const bodies: Record<string, unknown>[] = [];
	page.on('request', (request) => {
		if (request.method() === 'POST') bodies.push(request.postDataJSON());
	});
	return bodies;
}

type BoardJson = {
	repos: { items: { lines: { index: number; fingerprint: string }[] }[] }[];
};

export function logBoards(page: Page): Response[] {
	const boards: Response[] = [];
	page.on('response', (response) => {
		if (response.url().endsWith('/api/board')) boards.push(response);
	});
	return boards;
}

export async function fingerprintOf(
	board: Response | undefined,
	index: number
): Promise<string | undefined> {
	const read = (await board?.json()) as BoardJson | undefined;
	return read?.repos[0]?.items
		.flatMap((entry) => entry.lines)
		.find((entry) => entry.index === index)?.fingerprint;
}

export async function visit(page: Page): Promise<void> {
	const { appUrl, token } = readBoardRuntime();
	await page.clock.install();
	await page.goto(`${appUrl}#t=${token}`);
}

export async function showCard(page: Page, phone: boolean, title: string): Promise<void> {
	if (phone) {
		const back = page.getByRole('button', { name: '‹ Open' });
		if (await back.isVisible()) await back.click();
	}
	await page.locator('.tracks').getByTitle(title, { exact: true }).click();
	if (phone) await expect(page.locator('.question-pane')).toBeVisible();
}

export async function open(page: Page, phone: boolean, title = CARD_NAME): Promise<void> {
	await visit(page);
	await showCard(page, phone, title);
}

export const card = (page: Page): Locator => page.locator('.option-card');
export const toggle = (page: Page, number: number): Locator =>
	card(page)
		.locator('button.toggle')
		.nth(number - 1);
export const pointPicks = (page: Page, number: number): Locator =>
	page.getByRole('group', { name: `Point ${number}` });
export const pick = (page: Page, number: number, letter: string): Locator =>
	page.getByRole('button', { name: new RegExp(`^Point ${number}: ${letter} –`) });
export const acceptAll = (page: Page): Locator =>
	page.getByRole('button', { name: 'Accept all recommendations' });
export const strip = (page: Page): Locator => page.locator('.strip');
export const undo = (page: Page): Locator =>
	strip(page).getByRole('button', { name: 'Undo', exact: true });
export const otherAt = (page: Page, number: number): Locator =>
	page.getByRole('button', { name: `Point ${number}: Other…`, exact: true });
export const picks = (page: Page): Locator => page.getByRole('group', { name: 'Decide' });
export const decideBar = (page: Page): Locator => page.locator('.decide-row .bar');

export async function shoot(
	page: Page,
	testInfo: { outputPath(name: string): string },
	name: string
) {
	const filter = (value: string) =>
		page.evaluate((css) => {
			document.body.style.filter = css;
		}, value);
	await page.screenshot({ path: testInfo.outputPath(`${name}.png`) });
	await filter('blur(4px) grayscale(1)');
	await page.screenshot({ path: testInfo.outputPath(`${name}-shapes.png`) });
	await filter('');
}

export async function fits(page: Page, width: number): Promise<void> {
	expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
		width
	);
}

export function cardPost(item: number, lines: object[], answer: object = {}): object {
	return { repo: readBoardRuntime().repository, item, lines, ...answer };
}
