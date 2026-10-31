import type { Page } from '@playwright/test';
import { expect, test } from './consoleGuard';
import { arrange, item, optionEntry, yesNoEntry, type CardOption } from './itemFixture';
import { readBoardRuntime } from './runtime';

const SONG_QUESTION = 'Soll der Song beim Sprung offen bleiben?';
const LONG_TOPIC = 'Sehr langes Thema '.repeat(12).trim();

const OPTIONS: CardOption[] = [
	{
		name: 'Song bleibt offen',
		effect: 'Die App springt selbst.',
		same_as_today: true,
		notice: 'Du bleibst im Song.',
		cost: 'Mehr Code.',
		undo: 'reversible',
		undo_how: 'jederzeit',
		contract: 'Der Song bleibt offen.'
	},
	{
		name: 'Browser-Sprung bleibt',
		effect: 'Der Browser springt weiter.',
		same_as_today: true,
		notice: 'Du klickst den Link.',
		cost: 'Der Fehler bleibt.',
		undo: 'reversible',
		undo_how: 'jederzeit',
		contract: 'Die Vorgabe bleibt.'
	}
];

function songLine(topic: string, question = SONG_QUESTION) {
	return optionEntry('Der Song bleibt beim Sprung offen.', {
		question,
		topic,
		option: OPTIONS
	});
}

/** Two items with an option card each, served as `songmaker`
 * and `quality` (the second with a very long topic) and as `webauth` with
 * nothing open; the real server only reads the first. */
async function serveThreeRepositories(page: Page): Promise<void> {
	await arrange([
		item(7, 'Sprung', songLine('Sprung')),
		item(
			8,
			'Gäste',
			optionEntry('Gäste dürfen am Gespräch teilnehmen.', {
				question: 'Gäste einladen?',
				topic: 'Gäste',
				option: OPTIONS
			})
		)
	]);
	await page.route('**/api/board', async (route) => {
		const response = await route.fetch();
		const board = await response.json();
		const [source] = board.repos;
		const longTopicItems = source.items.map((item: { lines: { topic?: string }[] }) => ({
			...item,
			lines: item.lines.map((entry) => (entry.topic ? { ...entry, topic: LONG_TOPIC } : entry))
		}));
		await route.fulfill({
			json: {
				repos: [
					{ ...source, name: 'songmaker' },
					{ ...source, name: 'quality', items: longTopicItems },
					{ ...source, name: 'webauth', items: [] }
				]
			}
		});
	});
}

async function shoot(page: Page, outputPath: (name: string) => string, name: string) {
	await page.screenshot({ path: outputPath(`${name}.png`) });
	await page.evaluate(() => {
		document.body.style.filter = 'blur(4px) grayscale(1)';
	});
	await page.screenshot({ path: outputPath(`${name}-blur-grayscale.png`) });
	await page.evaluate(() => {
		document.body.style.filter = '';
	});
}

for (const viewport of [
	{ width: 1280, height: 900 },
	{ width: 390, height: 844 }
]) {
	test.describe(`${viewport.width}px open list`, () => {
		test.use({ viewport });

		test('[ABRD-28] [ABRD-48] option card rows stand in one group per repository, each with the shape naming its state and its question as title', async ({
			page
		}, testInfo) => {
			const { appUrl, token } = readBoardRuntime();
			await serveThreeRepositories(page);
			await page.goto(`${appUrl}#t=${token}`);

			const tracks = page.locator('.tracks');
			await expect(page.getByRole('heading', { name: 'songmaker 2' })).toBeVisible();
			await expect(page.getByRole('heading', { name: 'quality 2' })).toBeVisible();
			await expect(page.getByRole('heading', { name: 'webauth' })).toHaveCount(0);
			const rows = tracks.getByRole('button');
			await expect(rows).toHaveCount(4);
			await expect(rows.nth(0)).toHaveAccessibleName('Open Sprung');
			await expect(rows.nth(0)).toHaveAttribute('title', SONG_QUESTION);
			await expect(rows.nth(0).getByRole('img', { name: 'Open' })).toBeVisible();
			await expect(page.getByText('Nothing open: webauth')).toBeVisible();

			const longRow = rows.nth(2);
			expect((await longRow.boundingBox())?.height).toBeLessThanOrEqual(40);
			expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
				viewport.width
			);
			await shoot(page, (name) => testInfo.outputPath(name), 'open-list');
		});

		test('[ABRD-29] first load selects the first row, desktop shows its card and phones the list', async ({
			page
		}) => {
			const { appUrl, token } = readBoardRuntime();
			await serveThreeRepositories(page);
			await page.goto(`${appUrl}#t=${token}`);

			const first = page.locator('.tracks').getByRole('button').first();
			await expect(first).toHaveAttribute('aria-current', 'true');
			if (viewport.width > 760) {
				await expect(page.locator('.option-card')).toBeVisible();
			} else {
				await expect(page.locator('.tracks')).toBeVisible();
				await expect(page.locator('.question-pane')).toBeHidden();
				await first.click();
				await expect(page.locator('.option-card')).toBeVisible();
			}
		});

		test('[ABRD-49] an empty board reads All decided, a failure beside an empty repository does not', async ({
			page
		}, testInfo) => {
			const { appUrl, token } = readBoardRuntime();
			await arrange([
				item(12, 'Fertig', yesNoEntry('Entschieden.', 'yes', '2026-10-03', { question: 'Fertig?' }))
			]);
			await page.goto(`${appUrl}#t=${token}`);
			await expect(page.getByText('All decided')).toBeVisible();
			await expect(page.getByText('No project is waiting for you.')).toBeVisible();
			await page.screenshot({ path: testInfo.outputPath('all-decided.png') });

			const sentence = 'Repository konnte nicht gelesen werden.';
			await page.route('**/api/board', (route) =>
				route.fulfill({
					json: {
						repos: [
							{ name: 'quiet', error: null, items: [] },
							{ name: 'broken', error: sentence, items: [] }
						]
					}
				})
			);
			await page.reload();
			await expect(page.getByRole('heading', { name: 'broken' })).toBeVisible();
			await expect(page.getByRole('alert')).toContainText(`Not read ${sentence}`);
			await expect(page.getByText('Nothing open: quiet')).toBeVisible();
			await expect(page.getByText('All decided')).toHaveCount(0);
			await page.screenshot({ path: testInfo.outputPath('failed-and-quiet.png') });
		});

		test('[ABRD-28] Tab moves from the first row to the second, Enter opens it and focuses the stage', async ({
			page
		}) => {
			const { appUrl, token } = readBoardRuntime();
			await arrange([
				item(13, 'Tastatur', songLine('Erste', 'Erste?')),
				item(14, 'Tastatur zweite', songLine('Zweite', 'Zweite?'))
			]);
			await page.goto(`${appUrl}#t=${token}`);

			const rows = page.locator('.tracks').getByRole('button');
			await rows.first().focus();
			await page.keyboard.press('Tab');
			await expect(rows.nth(1)).toBeFocused();
			await page.keyboard.press('Enter');
			await expect(page.getByRole('heading', { name: 'Zweite?', exact: true })).toBeVisible();
			await expect(page.locator('.stage')).toBeFocused();
		});
	});
}
