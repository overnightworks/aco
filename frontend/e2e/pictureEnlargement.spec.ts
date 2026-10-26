import type { Locator, Page } from '@playwright/test';
import { expect, test } from './consoleGuard';
import { optionLine, row, writeRulings, type RulingOption } from './rulingsFixture';
import { readBoardRuntime } from './runtime';

// One shared board server backs every test in this file (see
// global-setup.ts); each test overwrites the whole of rulings.json.
test.describe.configure({ mode: 'serial' });

interface Box {
	x: number;
	y: number;
	width: number;
	height: number;
}

const QUESTION = 'Soll das Bild groß zu sehen sein?';
const TODAY_CAPTION = 'Heute ist das Bild klein.';
const A_CAPTION = 'So sieht Weg A aus.';
const B_NAME = 'Weg B';
const B_EFFECT = 'Wirkung von Weg B.';

function picture(label: string, width: number, height: number): string {
	return (
		`<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">` +
		`<rect x="1" y="1" width="${width - 2}" height="${height - 2}" rx="10" fill="#fff" stroke="#cdc8d5" stroke-width="1.5"/>` +
		`<text x="${width / 2}" y="${height / 2}" font-size="14" text-anchor="middle" font-family="sans-serif" fill="#18151f">${label}</text></svg>`
	);
}

function option(letter: string, name: string, effect: string, caption?: string): RulingOption {
	return {
		letter,
		name,
		effect,
		picture: picture(`Ergebnis ${letter}`, 360, 120),
		...(caption === undefined ? {} : { caption }),
		notice: 'Du merkst es.',
		cost: 'Aufwand.',
		undo: 'reversible',
		undo_how: 'jederzeit',
		contract: `Vertrag ${letter}.`
	};
}

function arrange(directory: string): void {
	writeRulings(directory, [
		row(
			1900,
			'Bild vergrößern',
			optionLine(1, 'Das Bild lässt sich vergrößern.', {
				question: QUESTION,
				picture: picture('Heute', 420, 140),
				caption: TODAY_CAPTION,
				options: [
					option('A', 'Weg A', 'Wirkung von Weg A.', A_CAPTION),
					option('B', B_NAME, B_EFFECT)
				]
			})
		)
	]);
}

async function openCard(page: Page, phone: boolean): Promise<Locator> {
	const { appUrl, token, repoDirectory } = readBoardRuntime();
	arrange(repoDirectory);
	await page.goto(`${appUrl}#t=${token}`);
	await page.locator('.tracks').getByTitle(QUESTION).click();
	if (phone) await expect(page.locator('.question-pane')).toBeVisible();
	return page.locator('.option-card');
}

async function boxOf(locator: Locator): Promise<Box> {
	const box = await locator.boundingBox();
	if (box === null) throw new Error('the element has no box');
	return box;
}

async function renderedWidth(image: Locator): Promise<number> {
	return (await boxOf(image)).width;
}

async function captureShapes(page: Page, path: string): Promise<void> {
	await page.evaluate(() => {
		document.body.style.filter = 'blur(4px) grayscale(1)';
	});
	await page.screenshot({ path });
	await page.evaluate(() => {
		document.body.style.filter = '';
	});
}

for (const viewport of [
	{ width: 1280, height: 900 },
	{ width: 390, height: 844 }
]) {
	const phone = viewport.width === 390;
	test.describe(`${viewport.width}px picture enlargement`, () => {
		test.use({ viewport });

		test('TODAY opens in a dialog with its caption, and Close or Esc returns focus to it', async ({
			page
		}, testInfo) => {
			const card = await openCard(page, phone);
			const todayButton = card.getByRole('button', { name: 'Enlarge picture' });
			await expect(todayButton).toHaveCount(1);
			const todayImage = todayButton.getByRole('img', { name: TODAY_CAPTION });
			await expect(todayImage).toHaveAttribute('src', /^data:image\/svg\+xml;base64,/);
			await expect(card.getByRole('img')).toHaveCount(1);
			await page.screenshot({ path: testInfo.outputPath('card.png') });
			await captureShapes(page, testInfo.outputPath('card-shapes.png'));

			await todayButton.click();
			const dialog = page.getByRole('dialog', { name: 'Picture at full width' });
			await expect(dialog).toBeVisible();
			await expect(dialog).toHaveJSProperty('open', true);
			expect(await dialog.evaluate((element) => element.matches(':modal'))).toBe(true);
			const dialogImage = dialog.getByRole('img', { name: TODAY_CAPTION });
			await expect(dialogImage).toHaveAttribute(
				'src',
				(await todayImage.getAttribute('src')) ?? ''
			);
			await expect(dialog.getByText(TODAY_CAPTION, { exact: true })).toBeVisible();
			expect(await dialog.evaluate((element) => element.contains(document.activeElement))).toBe(
				true
			);
			await expect
				.poll(() => page.evaluate(() => document.documentElement.scrollWidth))
				.toBeLessThanOrEqual(viewport.width);
			await page.screenshot({ path: testInfo.outputPath('today-dialog.png') });

			const thumbnailWidth = await renderedWidth(todayImage);
			expect(await renderedWidth(dialogImage)).toBeGreaterThan(phone ? thumbnailWidth : 0);
			if (!phone) {
				const cardWidth = (await card.boundingBox())?.width ?? Infinity;
				expect(await renderedWidth(dialogImage)).toBeGreaterThanOrEqual(Math.min(420, cardWidth));
			}

			await dialog.getByRole('button', { name: 'Close' }).click();
			await expect(dialog).toBeHidden();
			await expect(todayButton).toBeFocused();
			await expect(card.getByRole('img')).toHaveCount(1);

			await todayButton.click();
			await expect(dialog).toBeVisible();
			await page.keyboard.press('Escape');
			await expect(dialog).toBeHidden();
			await expect(todayButton).toBeFocused();
		});

		test('a RESULT picture opens with its caption, or the fallback caption, and Esc returns focus', async ({
			page
		}, testInfo) => {
			const card = await openCard(page, phone);
			const dialog = page.getByRole('dialog', { name: 'Picture at full width' });

			await card.locator('button[aria-expanded]').filter({ hasText: /Weg A/ }).click();
			const resultButton = card
				.locator('.details')
				.getByRole('button', { name: 'Enlarge picture' });
			const resultImage = resultButton.getByRole('img', { name: A_CAPTION });
			await resultButton.click();
			await expect(dialog).toBeVisible();
			await expect(dialog.getByRole('img', { name: A_CAPTION })).toHaveAttribute(
				'src',
				(await resultImage.getAttribute('src')) ?? ''
			);
			await expect(dialog.getByText(A_CAPTION, { exact: true })).toBeVisible();
			await page.screenshot({ path: testInfo.outputPath('result-dialog.png') });
			await page.keyboard.press('Escape');
			await expect(dialog).toBeHidden();
			await expect(resultButton).toBeFocused();

			await card.locator('button[aria-expanded]').filter({ hasText: /Weg B/ }).click();
			await card.locator('.details').getByRole('button', { name: 'Enlarge picture' }).click();
			await expect(dialog.getByText(`B · ${B_NAME}: ${B_EFFECT}`, { exact: true })).toBeVisible();
			await page.keyboard.press('Escape');
			await expect(dialog).toBeHidden();
		});

		test('TODAY is a framed half-size thumbnail with the enlarge mark on a phone only', async ({
			page
		}) => {
			const card = await openCard(page, phone);
			const todayButton = card.getByRole('button', { name: 'Enlarge picture' });
			const todayImage = todayButton.getByRole('img');
			const mark = todayButton.locator('svg[aria-hidden="true"]');

			if (phone) {
				expect(Math.abs((await renderedWidth(todayImage)) - 210)).toBeLessThanOrEqual(2);
				await expect(todayButton).toHaveCSS('border-top-style', 'solid');
				// 1 px border + 6 px padding on each side, as rendered at half size.
				const buttonBox = await boxOf(todayButton);
				expect(
					Math.abs(buttonBox.width - (await renderedWidth(todayImage)) - 7)
				).toBeLessThanOrEqual(1);
				await expect(mark).toBeVisible();
				const markBox = await boxOf(mark);
				expect(markBox.x + markBox.width).toBeLessThanOrEqual(buttonBox.x + buttonBox.width);
				expect(markBox.y + markBox.height).toBeLessThanOrEqual(buttonBox.y + buttonBox.height);
				expect(markBox.x).toBeGreaterThan(buttonBox.x + buttonBox.width / 2);
				expect(markBox.y).toBeGreaterThan(buttonBox.y + buttonBox.height / 2);
			} else {
				expect(Math.abs((await renderedWidth(todayImage)) - 420)).toBeLessThanOrEqual(2);
				await expect(todayButton).toHaveCSS('border-top-style', 'none');
				await expect(mark).toBeHidden();
			}
			const caption = card.getByText(TODAY_CAPTION, { exact: true });
			const buttonBox = await boxOf(todayButton);
			expect(buttonBox.y + buttonBox.height).toBeLessThanOrEqual((await boxOf(caption)).y + 1);
		});
	});
}
