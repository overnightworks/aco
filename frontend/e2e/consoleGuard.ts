/**
 * Every E2E test fails on an unexpected `console.error` or uncaught page
 * error. A browser logs a refused resource -- a Content-Security-Policy
 * violation included -- as exactly that, so an empty console across a whole
 * run is this suite's own proof that the shell's policy
 * (`aco_board.server.CONTENT_SECURITY_POLICY`) holds in a real browser
 * (issue #652, #620).
 */

import { test as base, expect } from '@playwright/test';

export const test = base.extend<{ consoleGuard: undefined }>({
	consoleGuard: [
		async ({ page }, use) => {
			const messages: string[] = [];
			page.on('console', (message) => {
				if (message.type() === 'error') {
					messages.push(message.text());
				}
			});
			page.on('pageerror', (error) => {
				messages.push(error.message);
			});

			await use(undefined);

			expect(messages, 'the browser console stayed empty').toEqual([]);
		},
		{ auto: true }
	]
});

export { expect };
