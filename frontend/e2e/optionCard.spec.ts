import type { Locator, Page } from '@playwright/test';
import { expect, test } from './consoleGuard';
import {
	line,
	optionLine,
	row,
	writeRulings,
	type OptionRulingLine,
	type RulingOption
} from './rulingsFixture';
import { readBoardRuntime } from './runtime';

// One shared board server backs every test in this file (see
// global-setup.ts); each test overwrites the whole of rulings.json.
test.describe.configure({ mode: 'serial' });

// The fake board's one repository label (`aco_board_fixtures.DEFAULT_LABEL`).
const REPOSITORY = 'repo';

const SONG_QUESTION = 'Soll dein Song beim Sprung zum Ursprungs-Take offen bleiben?';
const SONG_CONTRACT =
	'Ja ändert die bisherige Vorgabe in Regel 10 für normalen Klick und Enter: Der vorbereitete Plan nutzt den vorhandenen App-Verlauf, öffnet den Ursprungs-Take und scrollt dorthin; URL sowie Zurück/Vorwärts bleiben erhalten.';

const TODAY_PICTURE =
	'<svg xmlns="http://www.w3.org/2000/svg" width="420" height="140" viewBox="0 0 420 140">' +
	'<rect x="1" y="1" width="198" height="138" rx="10" fill="#fff" stroke="#cdc8d5" stroke-width="1.5"/>' +
	'<text x="22" y="26" font-size="11" font-family="sans-serif" fill="#18151f">Mein Song · Take 11</text>' +
	'<rect x="12" y="42" width="176" height="86" rx="8" fill="#fbf0de" stroke="#99570c" stroke-dasharray="5 3"/>' +
	'<text x="100" y="90" font-size="11" text-anchor="middle" font-family="sans-serif" fill="#99570c">Klick auf den Ursprungs-Link</text>' +
	'<text x="215" y="76" font-size="18" font-family="sans-serif" fill="#6e6779">→</text>' +
	'<rect x="230" y="1" width="188" height="138" rx="10" fill="#fff" stroke="#cdc8d5" stroke-width="1.5"/>' +
	'<text x="324" y="76" font-size="11" text-anchor="middle" font-family="sans-serif" fill="#99570c">✗ Song ist weg</text>' +
	'</svg>';

function resultPicture(label: string): string {
	return (
		'<svg xmlns="http://www.w3.org/2000/svg" width="200" height="60" viewBox="0 0 200 60">' +
		`<rect x="1" y="1" width="198" height="58" rx="8" fill="#e4f2ea" stroke="#1c7350"/><text x="100" y="35" font-size="11" text-anchor="middle" font-family="sans-serif" fill="#18151f">${label}</text></svg>`
	);
}

const SONG_OPTIONS: RulingOption[] = [
	{
		letter: 'A',
		name: 'Song bleibt offen',
		effect: 'Die App springt selbst: v5 klappt auf, Take 7 ist markiert.',
		picture: resultPicture('Song offen'),
		notice: 'Du bleibst in deinem Song; „Zurück“ führt zur Ansicht davor.',
		cost: 'Mehr Navigationscode in Songmaker, abgesichert durch 16 Browserfälle.',
		undo: 'reversible',
		undo_how: 'eine neue Entscheidung kann es wieder ändern.',
		contract: SONG_CONTRACT
	},
	{
		letter: 'B',
		name: 'Browser-Sprung bleibt',
		effect: 'Der Browser springt weiter selbst; der Song geht weiter verloren.',
		same_as_today: true,
		notice: 'Du klickst den Link: Wie heute bleibt nur die Bibliothek.',
		cost: 'Der Fehler bleibt, bis jemand eine andere Lösung findet.',
		undo: 'reversible',
		undo_how: 'es wird nichts gebaut; neu entscheiden geht jederzeit.',
		contract: 'Nein: Die native Vorgabe bleibt bindend.'
	}
];

function songCard(index: number, overrides: Partial<OptionRulingLine> = {}): OptionRulingLine {
	return optionLine(index, 'Der Song bleibt beim Sprung zum Ursprungs-Take offen.', {
		question: SONG_QUESTION,
		problem: 'Klickst du den Link zum Ursprungs-Take, ist dein geöffneter Song weg.',
		picture: TODAY_PICTURE,
		caption: 'Der Browser springt selbst – dabei geht der Song verloren.',
		decision_kind: 'product',
		area: 'Song-Seite',
		topic: 'Sprung zum Ursprungs-Take',
		recommended: 'A',
		reason: 'Behebt den Verlust; Strg- und Mittelklick bleiben normale Browser-Links.',
		options: SONG_OPTIONS,
		...overrides
	});
}

const FOUR_OPTIONS: RulingOption[] = ['A', 'B', 'C', 'D'].map((letter, position) => ({
	letter,
	name: `Weg ${letter}`,
	effect: `Wirkung von Weg ${letter}.`,
	picture: resultPicture(`Weg ${letter}`),
	...(letter === 'A' ? { caption: 'So sieht Weg A aus.' } : {}),
	notice: 'Du merkst es.',
	cost: 'Aufwand.',
	undo: position === 3 ? 'final' : 'reversible',
	undo_how: position === 3 ? 'nie' : 'jederzeit',
	contract: `Vertrag ${letter}.`
}));

function arrange(directory: string): void {
	writeRulings(directory, [
		row(
			1843,
			'Sprung zum Ursprungs-Take',
			songCard(1),
			optionLine(2, 'Eine Datenfrage mit einem endgültigen Weg.', {
				question: 'Welcher Weg für die Altdaten?',
				problem: 'Die Altdaten passen nicht mehr.',
				decision_kind: 'data_risk',
				area: 'Bibliothek',
				recommended: 'B',
				reason: 'Weg B ist der sichere.',
				options: FOUR_OPTIONS
			}),
			line(3, 'Gäste dürfen am Gespräch teilnehmen.', {
				question: 'Gäste einladen?',
				default: 'yes'
			})
		),
		row(
			1850,
			'Schon entschieden',
			songCard(1, { ruling: 'A', ruled_on: '2026-10-26', question: 'Song offen lassen?' })
		)
	]);
}

/** An option's disclosure; the Decide pick of the same option carries the name too. */
function disclosureOf(card: Locator, name: RegExp): Locator {
	return card.locator('button[aria-expanded]').filter({ hasText: name });
}

async function openFromList(page: Page, question: string, phone: boolean): Promise<void> {
	await page.getByRole('button', { name: new RegExp(question.replace('?', '\\?')) }).click();
	if (phone) await expect(page.locator('.question-pane')).toBeVisible();
}

for (const viewport of [
	{ width: 1280, height: 900 },
	{ width: 390, height: 844 }
]) {
	const phone = viewport.width === 390;
	test.describe(`${viewport.width}px option card`, () => {
		test.use({ viewport });

		test('an open option line shows the whole card, every option closed, and offers the Decide picks', async ({
			page
		}, testInfo) => {
			const { appUrl, token, repoDirectory } = readBoardRuntime();
			arrange(repoDirectory);
			await page.goto(`${appUrl}#t=${token}`);
			await openFromList(page, SONG_QUESTION, phone);

			const card = page.locator('.option-card');
			await expect(card.locator('.meta')).toHaveText(
				new RegExp(`^\\s*${REPOSITORY} › Song-Seite\\s*·\\s*Product\\s*·\\s*reversible\\s*$`)
			);
			await expect(card.getByRole('heading', { name: SONG_QUESTION, exact: true })).toBeVisible();
			await expect(card.getByRole('term')).toHaveText([
				'Problem',
				'Today',
				'Options',
				'Recommendation',
				'Decide'
			]);
			await expect(
				card.getByText('Klickst du den Link zum Ursprungs-Take, ist dein geöffneter Song weg.')
			).toBeVisible();
			const today = card.getByRole('img', {
				name: 'Der Browser springt selbst – dabei geht der Song verloren.'
			});
			await expect(today).toHaveAttribute('src', /^data:image\/svg\+xml;base64,/);
			await expect(
				card.getByText('Der Browser springt selbst – dabei geht der Song verloren.', {
					exact: true
				})
			).toBeVisible();
			const options = card.getByRole('listitem');
			await expect(options).toHaveCount(2);
			await expect(options.nth(0)).toContainText('A');
			await expect(options.nth(0)).toContainText('Song bleibt offen');
			await expect(options.nth(0)).toContainText(
				'Die App springt selbst: v5 klappt auf, Take 7 ist markiert.'
			);
			await expect(options.nth(1)).toContainText('B');
			await expect(options.nth(1)).toContainText('Browser-Sprung bleibt');
			await expect(card).toContainText('Behebt den Verlust; Strg- und Mittelklick');
			await expect(card.getByText('Decided')).toHaveCount(0);

			await expect(page.getByRole('button', { name: 'Ja', exact: true })).toHaveCount(0);
			await expect(page.getByRole('button', { name: 'Nein', exact: true })).toHaveCount(0);
			await expect(page.getByRole('button', { name: 'Später', exact: true })).toHaveCount(0);
			await expect(page.getByText('Notiz', { exact: true })).toHaveCount(0);
			await expect(card.getByRole('group', { name: 'Decide' }).getByRole('button')).toHaveCount(2);
			await expect(card.getByRole('button', { name: 'Enlarge picture' })).toHaveCount(1);
			const disclosures = card.locator('button[aria-expanded]');
			await expect(disclosures).toHaveCount(2);
			await expect(disclosures.nth(0)).toHaveAttribute('aria-expanded', 'false');
			await expect(disclosures.nth(1)).toHaveAttribute('aria-expanded', 'false');

			await page.screenshot({ path: testInfo.outputPath('song-card.png') });
			await page.evaluate(() => {
				document.body.style.filter = 'blur(4px) grayscale(1)';
			});
			await page.screenshot({ path: testInfo.outputPath('song-card-shapes.png') });
			await page.evaluate(() => {
				document.body.style.filter = '';
			});
			await expect
				.poll(() => page.evaluate(() => document.documentElement.scrollWidth))
				.toBeLessThanOrEqual(viewport.width);
		});

		test('a card with a final option says final in its meta line', async ({ page }, testInfo) => {
			const { appUrl, token, repoDirectory } = readBoardRuntime();
			arrange(repoDirectory);
			await page.goto(`${appUrl}#t=${token}`);
			await openFromList(page, 'Welcher Weg für die Altdaten?', phone);

			const card = page.locator('.option-card');
			await expect(card.locator('.meta')).toContainText('Data & risk');
			await expect(card.locator('.meta .final')).toHaveText('final');
			await expect(card.locator('.meta')).not.toContainText('reversible');
			await expect(card.getByRole('listitem')).toHaveCount(4);
			await expect(card.getByRole('listitem').nth(3)).toContainText('Weg D');
			await page.screenshot({ path: testInfo.outputPath('final-card.png') });
		});

		test('each option opens its rows, one at a time, and folds the contract behind Show', async ({
			page
		}, testInfo) => {
			const { appUrl, token, repoDirectory } = readBoardRuntime();
			arrange(repoDirectory);
			await page.goto(`${appUrl}#t=${token}`);
			await openFromList(page, SONG_QUESTION, phone);

			const card = page.locator('.option-card');
			const first = disclosureOf(card, /Song bleibt offen/);
			const second = disclosureOf(card, /Browser-Sprung bleibt/);
			await first.click();
			await expect(first).toHaveAttribute('aria-expanded', 'true');
			await expect(first).toHaveCSS('border-top-width', '0px');
			await expect(first).toHaveCSS('background-color', 'rgba(0, 0, 0, 0)');
			await expect(card.locator('summary')).toHaveCSS('padding-top', '0px');
			await expect(card.getByRole('term')).toHaveText([
				'Problem',
				'Today',
				'Options',
				'Result',
				'You notice',
				'Cost',
				'Undo',
				'Contract',
				'Recommendation',
				'Decide'
			]);
			const result = card.getByRole('img', {
				name: 'A · Song bleibt offen: Die App springt selbst: v5 klappt auf, Take 7 ist markiert.'
			});
			await expect(result).toHaveAttribute('src', /^data:image\/svg\+xml;base64,/);
			await expect(card.getByText(SONG_OPTIONS[0]?.notice ?? '')).toBeVisible();
			await expect(card.getByText(SONG_OPTIONS[0]?.cost ?? '')).toBeVisible();
			await expect(card.locator('.details dd').nth(3)).toHaveText(
				'reversible — eine neue Entscheidung kann es wieder ändern.'
			);

			const source = card.getByText(`${REPOSITORY} · Item 1843 · Line 1`);
			await expect(card.getByText(SONG_CONTRACT)).toBeHidden();
			await expect(source).toBeHidden();
			await card.getByText('Show', { exact: true }).click();
			await expect(card.getByText(SONG_CONTRACT)).toBeVisible();
			await expect(
				card.getByText('Der Song bleibt beim Sprung zum Ursprungs-Take offen.', { exact: true })
			).toBeVisible();
			await expect(source).toBeVisible();
			await page.screenshot({ path: testInfo.outputPath('song-card-open.png') });
			await page.evaluate(() => {
				document.body.style.filter = 'blur(4px) grayscale(1)';
			});
			await page.screenshot({ path: testInfo.outputPath('song-card-open-shapes.png') });
			await page.evaluate(() => {
				document.body.style.filter = '';
			});

			await second.click();
			await expect(first).toHaveAttribute('aria-expanded', 'false');
			await expect(second).toHaveAttribute('aria-expanded', 'true');
			await expect(card.locator('.details dd').first()).toHaveText('= TODAY');
			await expect(card.getByRole('img')).toHaveCount(1);
			await second.click();
			await expect(second).toHaveAttribute('aria-expanded', 'false');
			await expect(card.locator('.details')).toHaveCount(0);
			await expect(card.getByRole('img')).toHaveCount(1);
		});

		test('the disclosures work from the keyboard', async ({ page }) => {
			const { appUrl, token, repoDirectory } = readBoardRuntime();
			arrange(repoDirectory);
			await page.goto(`${appUrl}#t=${token}`);
			await openFromList(page, SONG_QUESTION, phone);

			const card = page.locator('.option-card');
			const first = disclosureOf(card, /Song bleibt offen/);
			const second = disclosureOf(card, /Browser-Sprung bleibt/);
			await first.focus();
			await page.keyboard.press('Enter');
			await expect(first).toHaveAttribute('aria-expanded', 'true');
			await page.keyboard.press('Tab');
			await expect(
				card.locator('.details').getByRole('button', { name: 'Enlarge picture' })
			).toBeFocused();
			await page.keyboard.press('Tab');
			await expect(card.locator('summary')).toBeFocused();
			await page.keyboard.press('Enter');
			await expect(card.getByText(SONG_CONTRACT)).toBeVisible();
			await page.keyboard.press('Tab');
			await expect(second).toBeFocused();
			await page.keyboard.press('Space');
			await expect(second).toHaveAttribute('aria-expanded', 'true');
			await expect(first).toHaveAttribute('aria-expanded', 'false');
		});

		test('a final option shows its warn mark beside the word, and a caption sits below its picture', async ({
			page
		}, testInfo) => {
			const { appUrl, token, repoDirectory } = readBoardRuntime();
			arrange(repoDirectory);
			await page.goto(`${appUrl}#t=${token}`);
			await openFromList(page, 'Welcher Weg für die Altdaten?', phone);

			const card = page.locator('.option-card');
			await disclosureOf(card, /Weg D/).click();
			const undo = card.locator('.details dd').nth(3);
			await expect(undo).toHaveText('final — nie');
			await expect(undo.locator('b')).toHaveCSS('color', 'rgb(153, 87, 12)');
			await expect(undo.locator('b svg[aria-hidden="true"]')).toBeVisible();
			await page.screenshot({ path: testInfo.outputPath('final-open.png') });

			await disclosureOf(card, /Weg A/).click();
			const picture = card.locator('.details').getByRole('img');
			const caption = card.getByText('So sieht Weg A aus.', { exact: true });
			await expect(caption).toBeVisible();
			const pictureBox = await picture.boundingBox();
			const captionBox = await caption.boundingBox();
			expect(pictureBox?.y ?? 0).toBeLessThan(captionBox?.y ?? 0);
		});

		test('selecting another card shows it with every option closed', async ({ page }) => {
			const { appUrl, token, repoDirectory } = readBoardRuntime();
			arrange(repoDirectory);
			await page.goto(`${appUrl}#t=${token}`);
			await openFromList(page, SONG_QUESTION, phone);
			await page
				.locator('.option-card button[aria-expanded]')
				.filter({ hasText: /Song bleibt offen/ })
				.click();
			await expect(page.locator('.option-card .details')).toHaveCount(1);

			if (phone) await page.getByRole('button', { name: '← Liste' }).click();
			await openFromList(page, 'Welcher Weg für die Altdaten?', phone);

			const disclosures = page.locator('.option-card button[aria-expanded]');
			await expect(disclosures).toHaveCount(4);
			for (let position = 0; position < 4; position += 1) {
				await expect(disclosures.nth(position)).toHaveAttribute('aria-expanded', 'false');
			}
			await expect(page.locator('.option-card .details')).toHaveCount(0);
		});

		test('the detail labels stand in the label column, or above their values on a phone', async ({
			page
		}) => {
			const { appUrl, token, repoDirectory } = readBoardRuntime();
			arrange(repoDirectory);
			await page.goto(`${appUrl}#t=${token}`);
			await openFromList(page, SONG_QUESTION, phone);

			const card = page.locator('.option-card');
			const first = disclosureOf(card, /Song bleibt offen/);
			await first.click();
			const labels = card.locator('.details dt');
			await expect(labels).toHaveCount(5);
			if (phone) {
				for (let position = 0; position < 5; position += 1) {
					const label = await labels.nth(position).boundingBox();
					const value = await card.locator('.details dd').nth(position).boundingBox();
					expect((label?.y ?? 0) + (label?.height ?? 0)).toBeLessThanOrEqual(value?.y ?? 0);
				}
			} else {
				const label = await labels.first().boundingBox();
				const head = await first.boundingBox();
				expect((label?.x ?? 0) + (label?.width ?? 0)).toBeLessThanOrEqual(head?.x ?? 0);
			}
			expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
				viewport.width
			);
		});

		test('a yes/no line keeps Ja, Nein, Später and its note beside option cards', async ({
			page
		}) => {
			const { appUrl, token, repoDirectory } = readBoardRuntime();
			arrange(repoDirectory);
			await page.goto(`${appUrl}#t=${token}`);
			await openFromList(page, 'Gäste einladen?', phone);

			const choices = page.getByRole('group', { name: 'Entscheidung' });
			for (const name of ['Ja', 'Nein', 'Später']) {
				await expect(choices.getByRole('button', { name })).toBeVisible();
			}
			await expect(page.getByText('Notiz', { exact: true })).toBeVisible();
			await expect(page.locator('.option-card')).toHaveCount(0);
		});

		test('a ruled option line leaves the list and Verlauf shows its letter, name, date and contract', async ({
			page
		}, testInfo) => {
			const { appUrl, token, repoDirectory } = readBoardRuntime();
			arrange(repoDirectory);
			await page.goto(`${appUrl}#t=${token}`);
			await expect(page.locator('.tracks').getByText('Song offen lassen?')).toHaveCount(0);
			await expect(page.locator('.tracks')).toContainText('Empfohlen: A');
			await expect(page.locator('.tracks')).toContainText('Empfohlen: B');

			await page.getByRole('button', { name: 'Verlauf', exact: true }).click();
			const history = page.getByRole('region', { name: 'Verlauf' });
			const entry = history.locator('summary');
			await expect(entry).toHaveCount(1);
			await expect(entry).toContainText('Song offen lassen?');
			await expect(entry).toContainText('A · Song bleibt offen');
			await expect(entry).toContainText('2026-10-26');
			await expect(history.getByText(SONG_CONTRACT)).toBeHidden();
			await entry.press('Enter');
			await expect(history.getByText(SONG_CONTRACT)).toBeVisible();
			await expect(
				history.getByText('Der Song bleibt beim Sprung zum Ursprungs-Take offen.')
			).toBeVisible();
			await expect(history.getByRole('button')).toHaveCount(0);
			await page.screenshot({ path: testInfo.outputPath('history-option.png') });
		});

		if (phone) {
			test('on a phone each label stands above its value without sideways scrolling', async ({
				page
			}) => {
				const { appUrl, token, repoDirectory } = readBoardRuntime();
				arrange(repoDirectory);
				await page.goto(`${appUrl}#t=${token}`);
				await openFromList(page, SONG_QUESTION, phone);

				const rows = page.locator('.option-card .row');
				await expect(rows).toHaveCount(4);
				for (let position = 0; position < 4; position += 1) {
					const label = await rows.nth(position).locator('dt').boundingBox();
					const value = await rows.nth(position).locator('dd').boundingBox();
					expect(label, 'label is rendered').not.toBeNull();
					expect(value, 'value is rendered').not.toBeNull();
					expect((label?.y ?? 0) + (label?.height ?? 0)).toBeLessThanOrEqual(value?.y ?? 0);
				}
				expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
					390
				);
			});
		}
	});
}
