import type { Locator, Page } from '@playwright/test';
import { expect, test } from './consoleGuard';
import { readBoardRuntime } from './runtime';
import { tokenColor } from './tokens';
import { item, line, optionLine, repo } from '../src/test-support/board';

const RULED_ONLY = {
	repos: [
		repo({
			name: 'Songmaker-App',
			items: [
				item({
					number: 42,
					title: 'Song-Seite',
					lines: [
						line({ index: 3, text: 'Gespräch beenden?', ruling: 'yes', ruled_on: '2026-10-01' })
					]
				})
			]
		})
	]
};

const KEPT_QUESTION = 'Soll der Song beim Sprung offen bleiben?';
const NOT_READ_SENTENCE = 'Repository konnte nicht gelesen werden.';
const WITH_KEPT_CARD = {
	repos: [
		repo({
			name: 'Projekt B',
			items: [
				item({ number: 7, title: 'Sprung', lines: [optionLine({ question: KEPT_QUESTION })] })
			]
		})
	]
};
const NOT_READ = { repos: [repo({ name: 'Projekt B', error: NOT_READ_SENTENCE, items: [] })] };

async function visit(page: Page, board: object | null = null) {
	const { appUrl, token } = readBoardRuntime();
	if (board !== null) await page.route('**/api/board', (route) => route.fulfill({ json: board }));
	await page.goto(`${appUrl}#t=${token}`);
}

/** The middle of the box's width, which a centred state shares with the page. */
async function centreX(locator: Locator) {
	const box = await locator.boundingBox();
	return box === null ? NaN : box.x + box.width / 2;
}

for (const viewport of [
	{ width: 1280, height: 900 },
	{ width: 390, height: 844 }
]) {
	for (const scheme of ['light', 'dark'] as const) {
		test.describe(`${viewport.width}px quiet states, device set to ${scheme}`, () => {
			test.use({ viewport, colorScheme: scheme });

			test('[ABRD-127] nothing waiting shows one centred state with its sign and both sentences, no stage beside it', async ({
				page
			}, testInfo) => {
				await visit(page, RULED_ONLY);

				const calm = page.locator('.tracks .empty');
				await expect(calm.getByText('All decided')).toBeVisible();
				await expect(calm.getByText('No project is waiting for you.')).toBeVisible();
				await expect(calm.locator('svg')).toBeVisible();
				await expect(page.locator('.question-pane')).toBeHidden();
				const tracks = await page.locator('.tracks').boundingBox();
				expect(tracks?.width).toBeGreaterThanOrEqual(viewport.width - 1);
				expect(Math.abs((await centreX(calm)) - viewport.width / 2)).toBeLessThan(2);
				await page.screenshot({ path: testInfo.outputPath('nothing-waits.png') });
				await expect(calm.locator('.sign')).toHaveCSS(
					'background-color',
					await tokenColor(page, '--good-soft')
				);
			});

			test('[ABRD-127] loading shows a turning ring in the middle, and a still one under reduced motion', async ({
				page
			}) => {
				let finish: (() => void) | undefined;
				const held = new Promise<void>((resolve) => {
					finish = resolve;
				});
				await page.route('**/api/board', async (route) => {
					await held;
					await route.fulfill({ json: RULED_ONLY });
				});
				await visit(page);

				const status = page.getByRole('status');
				await expect(status).toHaveText('Lädt…');
				expect(Math.abs((await centreX(status)) - viewport.width / 2)).toBeLessThan(2);
				const ring = (name: 'animationName' | 'borderTopColor') =>
					status.evaluate(
						(element, property) => getComputedStyle(element, '::before')[property],
						name
					);
				expect(await ring('borderTopColor')).toBe(await tokenColor(page, '--accent'));
				expect(await ring('animationName')).not.toBe('none');

				await page.emulateMedia({ reducedMotion: 'reduce' });
				expect(await ring('animationName')).toBe('none');
				finish?.();
			});

			test('[ABRD-127] no access shows a centred card with the warning sign and its sentence', async ({
				page
			}, testInfo) => {
				await page.goto(readBoardRuntime().appUrl);

				const card = page.getByRole('alert');
				await expect(card).toHaveText(
					'Zugang fehlt. Starte das Board im Repo und öffne den Link, den es ausgibt.'
				);
				await expect(card.locator('svg')).toBeVisible();
				await expect(card).toHaveCSS('background-color', await tokenColor(page, '--surface'));
				await expect(card).toHaveCSS('border-top-left-radius', '16px');
				await page.screenshot({ path: testInfo.outputPath('no-access.png') });
				expect(Math.abs((await centreX(card)) - viewport.width / 2)).toBeLessThan(2);
			});

			test('[ABRD-127] an unanswered board shows the same card with the warning sign and its sentence', async ({
				page
			}) => {
				const { appUrl, token } = readBoardRuntime();
				await page.route('**/api/board', (route) =>
					route.fulfill({ status: 503, body: 'Unavailable' })
				);
				await page.goto(`${appUrl}#t=${token}`);

				const card = page.getByRole('alert');
				await expect(card).toContainText('aco antwortet nicht.');
				await expect(card.locator('svg')).toBeVisible();
				await expect(card).toHaveCSS('border-top-left-radius', '16px');
				expect(Math.abs((await centreX(card)) - viewport.width / 2)).toBeLessThan(2);
			});

			test('[ABRD-101] a repository not read is one warning box with the mark, its sentence and its last read, above the cards it kept', async ({
				page
			}, testInfo) => {
				let reads = 0;
				await page.route('**/api/board', (route) =>
					route.fulfill({ json: reads++ === 0 ? WITH_KEPT_CARD : NOT_READ })
				);
				await visit(page);
				await expect(page.locator('.tracks').getByTitle(KEPT_QUESTION)).toBeVisible();

				await page.getByRole('button', { name: /^Refresh/ }).click();

				const box = page.locator('.tracks').getByRole('alert');
				await expect(box).toHaveText(
					new RegExp(`^\\s*Not read\\s+${NOT_READ_SENTENCE}\\s+last read \\d\\d:\\d\\d\\s*$`)
				);
				await expect(box).toHaveCSS('background-color', await tokenColor(page, '--warn-soft'));
				await page.screenshot({ path: testInfo.outputPath('not-read.png') });
				const around = await box.boundingBox();
				const mark = await box.locator('svg').boundingBox();
				const kept = await page.locator('.tracks').getByTitle(KEPT_QUESTION).boundingBox();
				expect(mark?.x).toBeGreaterThanOrEqual(around?.x ?? Infinity);
				expect((mark?.y ?? 0) + (mark?.height ?? 0)).toBeLessThanOrEqual(
					(around?.y ?? 0) + (around?.height ?? 0)
				);
				expect((around?.y ?? 0) + (around?.height ?? 0)).toBeLessThanOrEqual(kept?.y ?? 0);
			});
		});
	}
}
