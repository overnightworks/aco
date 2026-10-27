import { expect, type Locator, type Page } from '@playwright/test';

/** The Decided list; the Open block stays mounted but hidden beside it. */
export function decidedList(page: Page): Locator {
	return page.getByRole('region', { name: 'Decided', exact: true });
}

/** Opens the Decided tab and taps the row titled `title`, whose card then
 * stands in the pane (a phone shows the list until a row is tapped). */
export async function openDecidedLine(page: Page, title: string): Promise<void> {
	await page.getByRole('button', { name: /^Decided \d+$/ }).click();
	await decidedList(page).getByTitle(title, { exact: true }).click();
}

/** The decided card the stage shows for a ruled line. */
export function decidedCard(page: Page): Locator {
	return page.locator('.decided-card');
}

/** The value of one of the decided card's labelled rows. */
export function decidedRow(card: Locator, label: 'Decided' | 'How' | 'Contract'): Locator {
	return card.getByText(label, { exact: true }).locator('xpath=..').locator('dd');
}

/** The decided card says what was decided and how. */
export async function expectDecidedAnswer(page: Page, answer: string, how: string): Promise<void> {
	const card = decidedCard(page);
	await expect(decidedRow(card, 'Decided')).toHaveText(answer);
	await expect(decidedRow(card, 'How')).toHaveText(how);
}
