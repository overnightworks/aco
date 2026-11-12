import type { Page } from '@playwright/test';

/** The computed colour a custom property resolves to, as the browser prints it. */
export async function tokenColor(page: Page, token: string) {
	return page.evaluate((name) => {
		const probe = document.createElement('i');
		probe.style.color = `var(${name})`;
		document.body.append(probe);
		const resolved = getComputedStyle(probe).color;
		probe.remove();
		return resolved;
	}, token);
}
