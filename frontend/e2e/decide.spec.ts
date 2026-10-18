import type { Page } from '@playwright/test';
import { expect, test } from './consoleGuard';
import { line, row, writeRulings } from './rulingsFixture';
import { readBoardRuntime } from './runtime';
import { UNDO_SECONDS } from '../src/app/model/decision';

// One shared board server backs every test in this file (see
// global-setup.ts); each test overwrites the whole of rulings.json, so
// tests stay isolated from one another despite the shared process.
test.describe.configure({ mode: 'serial' });

// Just past the app's undo window; the page clock is driven, never waited.
const PAST_UNDO_WINDOW_MS = UNDO_SECONDS * 1000 + 500;

function choices(page: Page) {
	return page.getByRole('group', { name: 'Entscheidung' });
}

test('undoing within the 8 s window writes nothing, ever', async ({ page }) => {
	const { appUrl, token, repoDirectory } = readBoardRuntime();
	writeRulings(repoDirectory, [
		row(
			601,
			'Guests',
			line(1, 'Guests may join the call.', { question: 'Guests allowed?', default: 'yes' })
		)
	]);
	let ruleRequests = 0;
	page.on('request', (request) => {
		if (request.url().endsWith('/api/rule')) {
			ruleRequests += 1;
		}
	});

	await page.clock.install();
	await page.goto(`${appUrl}#t=${token}`);
	await page.getByRole('button', { name: /Guests may join the call\./ }).click();
	await choices(page).getByRole('button', { name: /Ja/ }).click();
	await page.getByRole('button', { name: 'Rückgängig' }).click();

	// The page clock runs past the window: the undo must have cancelled the
	// write, not merely delayed it, and no real waiting is needed to prove it.
	await page.clock.runFor(PAST_UNDO_WINDOW_MS);

	expect(ruleRequests).toBe(0);
	await expect(choices(page).getByRole('button', { name: /Ja/ })).toBeEnabled();
});

test('once the window elapses, exactly one decision is written', async ({ page }) => {
	const { appUrl, token, repoDirectory } = readBoardRuntime();
	writeRulings(repoDirectory, [
		row(
			602,
			'Hosts',
			line(1, 'Hosts may close the room.', { question: 'Hosts allowed?', default: 'no' })
		)
	]);
	let ruleRequests = 0;
	page.on('request', (request) => {
		if (request.url().endsWith('/api/rule')) {
			ruleRequests += 1;
		}
	});

	await page.clock.install();
	await page.goto(`${appUrl}#t=${token}`);
	await page.getByRole('button', { name: /Hosts may close the room\./ }).click();
	await choices(page).getByRole('button', { name: /Nein/ }).click();
	await page.clock.runFor(PAST_UNDO_WINDOW_MS);

	await expect(page.getByText('Nein · 2026-10-03')).toBeVisible();
	expect(ruleRequests).toBe(1);
	// Nothing else was open: the stage goes back to "all decided", not a stale card.
	await expect(page.getByText('Alles entschieden')).toBeVisible();
});

test('deciding moves the stage to the next open card, and the ruled one keeps no buttons', async ({
	page
}) => {
	const { appUrl, token, repoDirectory } = readBoardRuntime();
	writeRulings(repoDirectory, [
		row(
			605,
			'Access',
			line(1, 'Guests may join the call.', { question: 'Guests allowed?', default: 'yes' }),
			line(2, 'Hosts may close the room.', { question: 'Hosts allowed?', default: 'no' })
		)
	]);

	await page.goto(`${appUrl}#t=${token}`);
	await page.getByRole('button', { name: /Guests may join the call\./ }).click();
	await choices(page).getByRole('button', { name: /Ja/ }).click();

	await expect(page.getByRole('heading', { name: 'Hosts allowed?' })).toBeVisible({
		timeout: 10_000
	});
	await expect(choices(page).getByRole('button', { name: /Nein/ })).toBeVisible();

	// The just-ruled line stays visible in the list, but as read-only text.
	await expect(page.getByRole('button', { name: /Guests may join the call\./ })).not.toBeVisible();
	await expect(page.getByText('Guests may join the call.')).toBeVisible();
	await expect(page.getByText('Ja · 2026-10-03')).toBeVisible();
});

test('a question changed mid-undo refuses to save and asks for a reload', async ({ page }) => {
	const { appUrl, token, repoDirectory } = readBoardRuntime();
	writeRulings(repoDirectory, [
		row(
			603,
			'Changed line',
			line(1, 'Original sentence.', { question: 'Original question?', default: 'yes' })
		)
	]);

	await page.goto(`${appUrl}#t=${token}`);
	await page.getByRole('button', { name: /Original sentence\./ }).click();
	await choices(page).getByRole('button', { name: /Ja/ }).click();

	// An agent reformulates the line while the operator's undo window is
	// still open; the board must refuse the stale choice once it writes.
	writeRulings(repoDirectory, [
		row(
			603,
			'Changed line',
			line(1, 'A different sentence now.', { question: 'Original question?', default: 'yes' })
		)
	]);

	await expect(page.getByText('Diese Zeile hat sich geändert, bitte neu laden')).toBeVisible({
		timeout: 10_000
	});
});

test('"Später" is a real, writable outcome, recommended when it is the default', async ({
	page
}) => {
	const { appUrl, token, repoDirectory } = readBoardRuntime();
	writeRulings(repoDirectory, [
		row(
			604,
			'Deferred',
			line(1, 'This can wait a cycle.', { question: 'Deferred question?', default: 'later' })
		)
	]);

	await page.goto(`${appUrl}#t=${token}`);
	await page.getByRole('button', { name: /This can wait a cycle\./ }).click();
	const recommended = choices(page).getByRole('button', { name: /Später/ });
	await expect(recommended).toContainText('Empfohlen');
	await recommended.click();

	await expect(page.getByText('Später · 2026-10-03')).toBeVisible({ timeout: 10_000 });
});
