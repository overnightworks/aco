import type { Locator, Page } from '@playwright/test';
import { expect, test } from './consoleGuard';
import { arrange, item, optionEntry, type CardOption } from './itemFixture';
import { decidedCard, decidedRow, openDecidedLine } from './decidedView';
import { picks } from './decideRow';
import { readBoardRuntime } from './runtime';
import { tokenColor } from './tokens';
import { UNDO_SECONDS } from '../src/app/model/decision';

// One shared board server backs every test in this file (see
// global-setup.ts); each test arranges the whole board.
test.describe.configure({ mode: 'serial' });

const SINGLE_QUESTION = 'Soll der Song beim Sprung offen bleiben?';
const GROUP_TITLE = 'Song-Seite · 2 points';

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

async function arrangeCards(): Promise<void> {
	await arrange([
		item(
			3101,
			'Sprung',
			optionEntry('Der Song bleibt offen.', {
				question: SINGLE_QUESTION,
				topic: 'Sprung',
				area: 'Song-Seite',
				recommended: 'A',
				reason: 'Behebt den Verlust.',
				option: OPTIONS
			})
		),
		item(
			3102,
			'Gäste',
			...[1, 2].map((number) =>
				optionEntry(`Satz ${number}.`, {
					question: `Frage ${number}?`,
					topic: `Thema ${number}`,
					area: 'Song-Seite',
					recommended: 'A',
					option: OPTIONS
				})
			)
		)
	]);
}

async function open(page: Page, title: string): Promise<void> {
	const { appUrl, token } = readBoardRuntime();
	await page.clock.install();
	await page.goto(`${appUrl}#t=${token}`);
	await page.locator('.tracks').getByTitle(title).click();
}

async function style(locator: Locator, property: string): Promise<string> {
	return locator.evaluate(
		(element, name) => getComputedStyle(element).getPropertyValue(name),
		property
	);
}

for (const viewport of [
	{ width: 1280, height: 800 },
	{ width: 390, height: 844 }
]) {
	const phone = viewport.width === 390;
	test.describe(`${viewport.width}px decision card finish`, () => {
		test.use({ viewport });

		test('an unfolded option holds all its details in one inset panel', async ({ page }) => {
			await arrangeCards();
			await open(page, SINGLE_QUESTION);

			await page.locator('.option-card button.disclosure').first().click();

			const panel = page.locator('.option-card .details');
			await expect(panel).toHaveCSS('background-color', await tokenColor(page, '--surface-2'));
			await expect(panel).toHaveCSS('border-top-left-radius', '12px');
			const frame = await panel.boundingBox();
			for (const detail of await panel.locator('dt, dd').all()) {
				const box = await detail.boundingBox();
				expect(box?.x).toBeGreaterThanOrEqual(frame?.x ?? Infinity);
				expect((box?.x ?? 0) + (box?.width ?? 0)).toBeLessThanOrEqual(
					(frame?.x ?? 0) + (frame?.width ?? 0)
				);
				expect((box?.y ?? 0) + (box?.height ?? 0)).toBeLessThanOrEqual(
					(frame?.y ?? 0) + (frame?.height ?? 0)
				);
			}
		});

		test('the picks carry their letters in the display font, the recommended one on a light accent ground and the chosen one filled', async ({
			page
		}) => {
			await arrangeCards();
			await open(page, SINGLE_QUESTION);
			const recommended = picks(page).getByRole('button', { name: /^Decide A:/ });
			const other = picks(page).getByRole('button', { name: /^Decide B:/ });

			expect(await style(recommended, 'font-family')).toContain('Oswald');
			await expect(recommended).toHaveCSS(
				'background-color',
				await tokenColor(page, '--accent-soft')
			);
			await expect(other).toHaveCSS('background-color', await tokenColor(page, '--surface'));

			await other.click();

			await expect(other).toHaveCSS('background-color', await tokenColor(page, '--accent'));
		});

		if (phone) {
			test('a multi-point card puts each question’s picks under it', async ({ page }) => {
				await arrangeCards();
				await open(page, GROUP_TITLE);

				const question = page.locator('.option-card button.toggle').first();
				const group = page.getByRole('group', { name: 'Point 1' });

				const asked = await question.boundingBox();
				const picked = await group.getByRole('button').first().boundingBox();
				expect(picked?.y).toBeGreaterThanOrEqual((asked?.y ?? 0) + (asked?.height ?? 0));
				expect(picked?.x).toBeGreaterThan(asked?.x ?? Infinity);
			});
		} else {
			test('the recommendation stands fully visible above the decide bar', async ({ page }) => {
				await arrangeCards();
				await open(page, SINGLE_QUESTION);

				const row = page.locator('.recommendation');
				const bar = await page.locator('.decide-row').boundingBox();
				const shown = await row.boundingBox();

				await expect(row).toBeInViewport({ ratio: 1 });
				expect((shown?.y ?? 0) + (shown?.height ?? 0)).toBeLessThanOrEqual(bar?.y ?? 0);
				await expect(row).toHaveCSS('background-color', await tokenColor(page, '--accent-soft'));
				await expect(row.locator('.letter')).toHaveCSS(
					'background-color',
					await tokenColor(page, '--accent')
				);
				await expect(row.locator('.letter')).toHaveCSS('border-top-left-radius', '50%');
			});
		}

		test('[ABRD-58] the undo strip drains over the window, stands still under reduced motion and undo is a button', async ({
			page
		}) => {
			await arrangeCards();
			await open(page, SINGLE_QUESTION);
			await picks(page)
				.getByRole('button', { name: /^Decide B:/ })
				.click();

			const drain = page.locator('.strip .drain');
			await expect(drain).not.toHaveCSS('animation-name', 'none');
			await expect(drain).toHaveCSS('animation-duration', `${UNDO_SECONDS}s`);
			await expect(page.locator('.strip').getByRole('button', { name: 'Undo' })).toHaveCSS(
				'background-color',
				await tokenColor(page, '--surface')
			);

			await page.emulateMedia({ reducedMotion: 'reduce' });

			await expect(drain).toHaveCSS('animation-name', 'none');
		});

		test('the history stands the decided answer in a success panel', async ({ page }) => {
			await arrangeCards();
			await open(page, SINGLE_QUESTION);
			await picks(page)
				.getByRole('button', { name: /^Decide B:/ })
				.click();
			await page.clock.runFor(UNDO_SECONDS * 1000 + 500);
			if (phone) await page.getByRole('button', { name: '‹ Open' }).click();

			await openDecidedLine(page, SINGLE_QUESTION);

			const answer = decidedRow(decidedCard(page), 'Decided').locator('.answer');
			await expect(answer).toHaveCSS('background-color', await tokenColor(page, '--good-soft'));
			await expect(answer).toContainText('B — Weg B');
		});
	});
}
