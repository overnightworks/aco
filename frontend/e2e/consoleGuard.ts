/**
 * Every E2E test fails if the browser logs a Content-Security-Policy
 * violation -- Chromium's own wording always names the policy, e.g.
 * "Refused to ... because it violates the following Content Security
 * Policy directive: ...". An expected failed fetch (a simulated 502, say)
 * also logs a console error, so this guard matches only the CSP wording,
 * not every error: a clean run across the whole suite is this suite's own
 * proof that the shell's policy (`aco.board.server.CONTENT_SECURITY_POLICY`)
 * holds in a real browser (issue #652, #620).
 */

import { test as base, expect } from '@playwright/test';

const CSP_VIOLATION = /content security policy/i;

export const test = base.extend<{ consoleGuard: undefined }>({
	consoleGuard: [
		async ({ page }, use) => {
			const violations: string[] = [];
			page.on('console', (message) => {
				if (message.type() === 'error' && CSP_VIOLATION.test(message.text())) {
					violations.push(message.text());
				}
			});

			await use(undefined);

			expect(violations, 'no Content-Security-Policy violation was logged').toEqual([]);
		},
		{ auto: true }
	]
});

export { expect };
