import { expect, test } from './consoleGuard';
import { line, optionLine, row, writeRulings, type RulingOption } from './rulingsFixture';
import { readBoardRuntime } from './runtime';

// One shared board server backs every test in this file (see
// global-setup.ts); each test overwrites the whole of rulings.json.
test.describe.configure({ mode: 'serial' });

const OPTIONS: RulingOption[] = [
	{
		letter: 'A',
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
		letter: 'B',
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

for (const viewport of [
	{ width: 1280, height: 900 },
	{ width: 390, height: 844 }
]) {
	test.describe(`${viewport.width}px with head`, () => {
		test.use({ viewport });

		test('[ABRD-65] a returned line lists muted with the With head shape after the open ones, and its card says with head and offers Decide', async ({
			page
		}, testInfo) => {
			const { appUrl, token, repoDirectory } = readBoardRuntime();
			writeRulings(repoDirectory, [
				row(
					7,
					'Sprung',
					line(1, 'Gäste dürfen teilnehmen.', { question: 'Gäste einladen?' }),
					optionLine(2, 'Der Song bleibt offen.', {
						topic: 'Zurückgegeben',
						question: 'Soll der Song offen bleiben?',
						options: OPTIONS,
						returned_on: '2026-10-27',
						returned_note: 'Welcher Sprung ist gemeint?'
					}),
					optionLine(3, 'Der Link bleibt ein Link.', {
						topic: 'Offen',
						question: 'Soll der Link ein Link bleiben?',
						options: OPTIONS
					})
				)
			]);
			await page.goto(`${appUrl}#t=${token}`);

			const rows = page.locator('.tracks').getByRole('button');
			await expect(rows).toHaveCount(3);
			await expect(rows.nth(0)).toHaveAccessibleName('Open Offen');
			await expect(rows.nth(1)).toHaveAccessibleName('With head Zurückgegeben');
			await expect(rows.nth(2)).toHaveAccessibleName('Not ready · head to fill Gäste einladen?');
			await expect(rows.nth(1).getByRole('img', { name: 'With head' })).toBeVisible();
			const labelColour = (label: string) =>
				rows
					.getByText(label, { exact: true })
					.evaluate((element) => getComputedStyle(element).color);
			expect(await labelColour('Zurückgegeben')).not.toBe(await labelColour('Offen'));
			await page.screenshot({ path: testInfo.outputPath('with-head-list.png') });

			await rows.nth(1).click();
			const card = page.locator('.option-card');
			await expect(card.locator('.meta')).toHaveText(
				/^\s*repo › Bereich\s*·\s*Product\s*·\s*with head\s*·\s*reversible\s*$/
			);
			await expect(card.getByRole('group', { name: 'Decide' }).getByRole('button')).toHaveCount(2);
			await page.screenshot({ path: testInfo.outputPath('with-head-card.png') });
		});
	});
}
