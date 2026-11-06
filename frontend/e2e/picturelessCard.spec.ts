import { arrange, item, optionEntry, type CardOption } from './itemFixture';
import { expect, test } from './consoleGuard';
import { readBoardRuntime } from './runtime';

// One shared board server backs every test in this file (see global-setup.ts).
test.describe.configure({ mode: 'serial' });

const QUESTION = 'Soll die Karte ohne Bilder auskommen?';

function resultlessOption(name: string): CardOption {
	return {
		name,
		effect: `Wirkung von ${name}.`,
		notice: 'Du merkst es.',
		cost: 'Aufwand.',
		undo: 'reversible',
		undo_how: 'jederzeit',
		contract: `Vertrag ${name}.`
	};
}

for (const viewport of [
	{ width: 1280, height: 900 },
	{ width: 390, height: 844 }
]) {
	test.describe(`${viewport.width}px card without pictures`, () => {
		test.use({ viewport });

		test('a card without pictures shows no Today row and an option shows its effect alone', async ({
			page
		}) => {
			const { appUrl, token } = readBoardRuntime();
			await arrange([
				item(
					1900,
					'Karte ohne Bilder',
					optionEntry('Die Karte kommt ohne Bilder aus.', {
						question: QUESTION,
						picture: undefined,
						caption: undefined,
						option: [resultlessOption('Weg eins'), resultlessOption('Weg zwei')]
					})
				)
			]);
			await page.goto(`${appUrl}#t=${token}`);
			await page.locator('.tracks').getByTitle(QUESTION).click();
			if (viewport.width === 390) await expect(page.locator('.question-pane')).toBeVisible();

			const card = page.locator('.option-card');
			await expect(card.getByRole('heading', { name: QUESTION, exact: true })).toBeVisible();
			await expect(card.getByRole('term')).toHaveText([
				'Problem',
				'Options',
				'Recommendation',
				'Decide'
			]);
			await expect(card.getByRole('img')).toHaveCount(0);
			await expect(card.getByRole('button', { name: 'Enlarge picture' })).toHaveCount(0);

			const first = card.locator('button[aria-expanded]').filter({ hasText: /Weg eins/ });
			await expect(first).toContainText('Wirkung von Weg eins.');
			await first.click();
			await expect(first).toHaveAttribute('aria-expanded', 'true');
			await expect(card.getByText('Result', { exact: true })).toHaveCount(0);
			await expect(card.getByText('You notice', { exact: true })).toBeVisible();
			await expect
				.poll(() => page.evaluate(() => document.documentElement.scrollWidth))
				.toBeLessThanOrEqual(viewport.width);
		});
	});
}
