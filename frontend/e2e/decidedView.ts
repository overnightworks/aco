import type { Locator, Page } from '@playwright/test';

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
