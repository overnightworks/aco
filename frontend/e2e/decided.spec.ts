import type { Page } from '@playwright/test';
import { expect, test } from './consoleGuard';
import {
	decidedCard,
	decidedList,
	decidedRow,
	expectDecidedAnswer,
	openDecidedLine
} from './decidedView';
import {
	arrange,
	item,
	optionEntry,
	yesNoEntry,
	type CardOption,
	type OptionEntry
} from './itemFixture';
import { readBoardRuntime } from './runtime';
import { UNDO_SECONDS } from '../src/app/model/decision';

// One shared board server backs every test in this file (see
// global-setup.ts); each test arranges the whole board.
test.describe.configure({ mode: 'serial' });

const FAILED_MESSAGE = 'Repository konnte nicht gelesen werden.';
const DONE_COLOUR = 'rgb(28, 115, 80)';

function choice(name: string): CardOption {
	return {
		name,
		effect: `Wirkung von ${name}.`,
		same_as_today: true,
		notice: 'Du merkst nichts.',
		cost: 'Nichts.',
		undo: 'reversible',
		undo_how: 'jederzeit.',
		contract: `Vertrag von ${name}.`
	};
}

function sprungCard(options: CardOption[], overrides: Partial<OptionEntry>): OptionEntry {
	return optionEntry('Der Sprung bleibt offen.', {
		question: 'Sprung offen lassen?',
		topic: 'Sprung',
		option: options,
		...overrides
	});
}

/** A ruled card is exempt from the open card's word rules, so its option may carry a one-word name. */
function ruledOption(overrides: Partial<OptionEntry>): OptionEntry {
	return sprungCard([choice('Offen'), choice('Wie heute')], {
		ruling: 'A',
		ruled_on: '2026-10-02',
		...overrides
	});
}

function openOption(question: string): OptionEntry {
	return sprungCard([choice('Sprung offen'), choice('Wie heute')], { question });
}

/** Item 42: three ruled lines of both forms and one open line. */
async function arrangeMixed(): Promise<void> {
	await arrange([
		item(
			42,
			'Gäste im Gespräch',
			ruledOption({ via: 'board' }),
			yesNoEntry('Gäste dürfen über einen Link teilnehmen.', 'no', '2026-10-03', {
				question: 'Gäste einladen?'
			}),
			yesNoEntry('Die Aufzeichnung bleibt ausgeschaltet.', 'later', '2026-10-01'),
			openOption('Offene Frage?')
		)
	]);
}

const SHORT_ANSWER = 'Nur am Desktop; auf dem Handy bleibt es wie heute.';
const UNBROKEN_TOKEN = 'x'.repeat(120);
const LONG_ANSWER = `Erst am Desktop,\n„dann“ am Handy: ${'Der Sprung bleibt offen, solange das Lied läuft. '.repeat(4)}${UNBROKEN_TOKEN} Ende.`;

/** Item 50: option lines ruled the three ways, one yes/no line, then two
 * lines answered in the operator's own words. */
async function arrangeEveryWay(): Promise<void> {
	await arrange([
		item(
			50,
			'Gespräch',
			ruledOption({ question: 'Per Board?', via: 'board', ruled_on: '2026-10-25' }),
			ruledOption({ question: 'Per Chat?', ruling: 'B', via: 'chat', ruled_on: '2026-10-04' }),
			ruledOption({ question: 'Ohne Antwort?', via: 'default', ruled_on: '2026-10-26' }),
			yesNoEntry('Gäste dürfen über einen Link teilnehmen.', 'no', '2026-10-03', {
				question: 'Gäste einladen?'
			}),
			ruledOption({
				question: 'Nur Desktop?',
				ruling: 'other',
				other: SHORT_ANSWER,
				via: 'board',
				ruled_on: '2026-10-27'
			}),
			ruledOption({
				question: 'Auch Handy?',
				ruling: 'other',
				other: LONG_ANSWER,
				via: 'chat',
				ruled_on: '2026-10-27'
			})
		)
	]);
}

const OPTION_TEXT = 'Der Sprung bleibt offen.';

const EVERY_WAY = [
	{
		title: 'Per Board?',
		answer: 'A — Offen',
		how: 'Board · 25.10.2026',
		area: 'Bereich',
		binding: ['Vertrag von Offen.', OPTION_TEXT]
	},
	{
		title: 'Per Chat?',
		answer: 'B — Wie heute',
		how: 'From chat · 04.10.2026',
		area: 'Bereich',
		binding: ['Vertrag von Wie heute.', OPTION_TEXT]
	},
	{
		title: 'Ohne Antwort?',
		answer: 'A — Offen',
		how: 'Recommendation kept – no answer · 26.10.2026',
		area: 'Bereich',
		binding: ['Vertrag von Offen.', OPTION_TEXT]
	},
	{
		title: 'Gäste einladen?',
		answer: 'Nein',
		how: 'not recorded · 03.10.2026',
		area: 'Gespräch',
		binding: ['Gäste dürfen über einen Link teilnehmen.']
	},
	{
		title: 'Nur Desktop?',
		answer: `Other: „${SHORT_ANSWER}“`,
		how: 'Board · 27.10.2026',
		area: 'Bereich',
		binding: [SHORT_ANSWER]
	},
	{
		title: 'Auch Handy?',
		answer: `Other: „${LONG_ANSWER}“`,
		how: 'From chat · 27.10.2026',
		area: 'Bereich',
		binding: [LONG_ANSWER]
	}
];

async function routeRepositories(
	page: Page,
	names: string[],
	failedNames: string[] = []
): Promise<void> {
	await page.route('**/api/board', async (route) => {
		const response = await route.fetch();
		const board = await response.json();
		await route.fulfill({
			json: {
				repos: [
					...names.map((name) => ({ ...board.repos[0], name })),
					...failedNames.map((name) => ({ name, error: FAILED_MESSAGE, items: [] }))
				]
			}
		});
	});
}

async function shootWithShapes(page: Page, outputPath: (name: string) => string, name: string) {
	await page.screenshot({ path: outputPath(`${name}.png`) });
	await page.evaluate(() => {
		document.body.style.filter = 'blur(4px) grayscale(1)';
	});
	await page.screenshot({ path: outputPath(`${name}-shapes.png`) });
	await page.evaluate(() => {
		document.body.style.filter = '';
	});
}

const decidedTab = (page: Page) => page.getByRole('button', { name: /^Decided \d+$/ });
const openTab = (page: Page) => page.getByRole('button', { name: /^Open \d+$/ });

for (const viewport of [
	{ width: 1280, height: 900 },
	{ width: 390, height: 844 }
]) {
	const phone = viewport.width === 390;
	test.describe(`${viewport.width}px Decided`, () => {
		test.use({ viewport });

		test('[ABRD-30] Decided lists the ruled lines per project with the Decided shape and shows the selected card', async ({
			page
		}, testInfo) => {
			const { appUrl, token } = readBoardRuntime();
			await arrangeMixed();
			await routeRepositories(page, ['Projekt A', 'Projekt B'], ['Projekt C']);
			await page.goto(`${appUrl}#t=${token}`);
			await decidedTab(page).click();

			const list = decidedList(page);
			await expect(list.getByRole('heading', { level: 2 })).toHaveText([
				/^Projekt A\s+3$/,
				/^Projekt B\s+3$/
			]);
			await expect(list.getByRole('alert')).toHaveText(`Projekt C: ${FAILED_MESSAGE}`);
			const rows = list.getByRole('button');
			await expect(rows).toHaveCount(6);
			await expect(rows.getByRole('img', { name: 'Decided' })).toHaveCount(6);
			for (const label of ['Gäste einladen?', 'Sprung', 'Die Aufzeichnung bleibt ausgeschaltet.']) {
				await expect(list.getByText(label, { exact: true })).toHaveCount(2);
			}
			await expect(list.getByTitle('Offene Frage?')).toHaveCount(0);
			await expect(rows.first().getByRole('img', { name: 'Decided' })).toHaveCSS(
				'color',
				DONE_COLOUR
			);
			if (!phone) {
				expect((await rows.first().boundingBox())?.height).toBe(36);
				expect((await list.getByRole('heading', { level: 2 }).first().boundingBox())?.height).toBe(
					42
				);
			}
			await shootWithShapes(page, testInfo.outputPath.bind(testInfo), 'decided');
			await expect
				.poll(() => page.evaluate(() => document.documentElement.scrollWidth))
				.toBeLessThanOrEqual(viewport.width);

			const firstCard = page.getByRole('heading', { name: 'Gäste einladen?', exact: true });
			if (phone) {
				await expect(firstCard).toBeHidden();
				await rows.first().click();
			} else {
				await expect(rows.first()).toHaveAttribute('aria-current', 'true');
			}
			await expect(firstCard).toBeVisible();
			await expectDecidedAnswer(page, 'Nein', 'not recorded · 03.10.2026');
			await page.screenshot({ path: testInfo.outputPath('decided-card.png') });
			if (phone) {
				await page.getByRole('button', { name: '‹ Decided' }).click();
				await expect(firstCard).toBeHidden();
				await expect(rows.first()).toHaveAttribute('aria-current', 'true');
			}
		});

		test('[ABRD-37] [ABRD-54] [ABRD-57] the decided card says what was decided, how and when', async ({
			page
		}, testInfo) => {
			const { appUrl, token } = readBoardRuntime();
			await arrangeEveryWay();
			await page.goto(`${appUrl}#t=${token}`);
			await expect(openTab(page)).toHaveText(/^Open 0$/);
			await expect(decidedTab(page)).toHaveText(/^Decided 6$/);

			for (const [
				position,
				{ title, answer, how, area, binding: sentences }
			] of EVERY_WAY.entries()) {
				await openDecidedLine(page, title);
				const card = decidedCard(page);
				await expect(card.locator('.meta')).toContainText(`repo › ${area}`);
				await expect(card.getByRole('heading', { name: title, exact: true })).toBeVisible();
				await expect(card.getByRole('term')).toHaveText(['Decided', 'How', 'Contract']);
				await expect(
					decidedRow(card, 'Decided').getByRole('img', { name: 'Decided' })
				).toBeVisible();
				await expectDecidedAnswer(page, answer, how);
				const binding = card.locator('.binding');
				await expect(binding).toBeHidden();
				await card.getByText('Show', { exact: true }).click();
				await expect(binding).toBeVisible();
				await expect(binding.locator('p')).toHaveText(sentences);
				await expect(binding.locator('.source')).toHaveText(
					`repo · Item 50 · Line ${position + 1}`
				);
				await expect(card.getByText('Problem', { exact: true })).toHaveCount(0);
				await expect(card.getByText('Today', { exact: true })).toHaveCount(0);
				await expect(card.getByText('Options', { exact: true })).toHaveCount(0);
				await expect(card.getByText('Recommendation', { exact: true })).toHaveCount(0);
				await expect
					.poll(() => page.evaluate(() => document.documentElement.scrollWidth))
					.toBeLessThanOrEqual(viewport.width);
				await page.screenshot({
					path: testInfo.outputPath(`decided-way-${position + 1}.png`)
				});
				if (phone) await page.getByRole('button', { name: '‹ Decided' }).click();
			}
		});

		test('[ABRD-31] a repository lists the newest date first', async ({ page }) => {
			const { appUrl, token } = readBoardRuntime();
			await arrange([
				item(8, 'Alt', yesNoEntry('Zweiter Oktober?', 'yes', '2026-10-02')),
				item(7, 'Neu', yesNoEntry('Dritter Oktober?', 'no', '2026-10-03'))
			]);
			await page.goto(`${appUrl}#t=${token}`);
			await decidedTab(page).click();

			await expect(decidedList(page).getByRole('button')).toHaveCount(2);
			await expect
				.poll(() =>
					decidedList(page)
						.getByRole('button')
						.evaluateAll((buttons) => buttons.map((button) => button.getAttribute('title')))
				)
				.toEqual(['Dritter Oktober?', 'Zweiter Oktober?']);
		});

		test('[ABRD-31] with nothing ruled Decided reads Nothing decided yet', async ({
			page
		}, testInfo) => {
			const { appUrl, token } = readBoardRuntime();
			await arrange([item(9, 'Offen', openOption('Noch offen?'))]);
			await page.goto(`${appUrl}#t=${token}`);
			await decidedTab(page).click();

			await expect(page.getByText('Nothing decided yet')).toBeVisible();
			await expect(
				page.getByText('Your decisions show here with their answer and date.')
			).toBeVisible();
			await expect(page.getByText(/Nothing open/)).toBeHidden();
			await shootWithShapes(page, testInfo.outputPath.bind(testInfo), 'decided-empty');
		});

		test('[ABRD-31] a failed repository with nothing ruled shows its alert and no Nothing decided yet', async ({
			page
		}) => {
			const { appUrl, token } = readBoardRuntime();
			await page.route('**/api/board', (route) =>
				route.fulfill({
					json: {
						repos: [
							{ name: 'available', error: null, items: [] },
							{ name: 'unavailable', error: FAILED_MESSAGE, items: [] }
						]
					}
				})
			);
			await page.goto(`${appUrl}#t=${token}`);
			await decidedTab(page).click();

			await expect(decidedList(page).getByRole('alert')).toContainText('unavailable');
			await expect(page.getByText('Nothing decided yet')).toHaveCount(0);
			await expect(page.getByText(/Nothing open/)).toBeHidden();
		});

		test('[ABRD-32] Open keeps its row, list position and phone view across Decided, which starts at its first row again', async ({
			page
		}) => {
			const { appUrl, token } = readBoardRuntime();
			await arrange([
				item(
					42,
					'Gäste im Gespräch',
					openOption('Gäste einladen?'),
					yesNoEntry('Gastzugänge bleiben unverändert.', 'later', '2026-10-03', {
						question: 'Gastzugänge ändern?'
					})
				),
				item(43, 'Gesprächsende', openOption('Gespräch beenden?')),
				item(
					41,
					'Aufzeichnung',
					yesNoEntry('Die Aufzeichnung bleibt ausgeschaltet.', 'no', '2026-10-02', {
						question: 'Aufzeichnen?'
					})
				)
			]);
			await routeRepositories(
				page,
				Array.from({ length: 8 }, (_, index) => `Projekt ${index + 1}`)
			);
			let writes = 0;
			page.on('request', (request) => {
				if (request.method() === 'POST') writes += 1;
			});
			await page.goto(`${appUrl}#t=${token}`);
			const tracks = page.locator('.tracks').first();
			const last = tracks.getByRole('button').last();
			await last.scrollIntoViewIfNeeded();
			const position = await tracks.evaluate((element) => element.scrollTop);
			await last.click();
			await expect(
				page.getByRole('heading', { name: 'Gespräch beenden?', exact: true })
			).toBeVisible();

			if (phone) await page.getByRole('button', { name: '‹ Open' }).click();
			await decidedTab(page).click();
			const rows = decidedList(page).getByRole('button');
			await expect(rows).toHaveCount(16);
			await expect(rows.first()).toHaveAttribute('aria-current', 'true');
			await expect(decidedList(page).getByRole('heading', { level: 2 }).first()).toHaveText(
				/^Projekt 1\s+2$/
			);
			await rows.last().click();
			await expect(page.getByRole('heading', { name: 'Aufzeichnen?', exact: true })).toBeVisible();
			if (phone) await page.getByRole('button', { name: '‹ Decided' }).click();
			await expect(rows.last()).toHaveAttribute('aria-current', 'true');
			await openTab(page).click();
			if (!phone) {
				await expect(
					page.getByRole('heading', { name: 'Gespräch beenden?', exact: true })
				).toBeVisible();
			}
			await expect(last).toHaveAttribute('aria-current', 'true');
			await expect.poll(() => tracks.evaluate((element) => element.scrollTop)).toBe(position);

			await decidedTab(page).click();
			await expect(rows.first()).toHaveAttribute('aria-current', 'true');
			await expect(rows.last()).toHaveAttribute('aria-current', 'false');
			await expect(page.getByText('Keine Frage ausgewählt.')).toBeHidden();
			if (phone) {
				await expect(page.getByRole('button', { name: '‹ Decided' })).toBeHidden();
			}
			expect(writes).toBe(0);
		});

		test('[ABRD-33] a pick waiting out its undo window is not in Decided, and once stored it is', async ({
			page
		}) => {
			const { appUrl, token } = readBoardRuntime();
			await arrange([item(60, 'Eine Frage', openOption('Gäste zulassen?'))]);
			await page.clock.install();
			await page.goto(`${appUrl}#t=${token}`);
			await page.locator('.tracks').getByTitle('Gäste zulassen?', { exact: true }).click();
			await page
				.getByRole('group', { name: 'Decide' })
				.getByRole('button', { name: /^Decide A:/ })
				.click();
			if (phone) await page.getByRole('button', { name: '‹ Open' }).click();
			await decidedTab(page).click();
			await expect(page.getByText('Nothing decided yet')).toBeVisible();
			await page.clock.runFor(UNDO_SECONDS * 1000 + 500);

			await expect(decidedList(page).getByTitle('Gäste zulassen?', { exact: true })).toBeVisible();
			await expect(decidedTab(page)).toBeFocused();
			await openTab(page).click();
			await expect(page.getByText('All decided')).toBeVisible();
		});
	});
}
