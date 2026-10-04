import { defineConfig, devices } from '@playwright/test';

/**
 * No `webServer` here: the app itself is ephemeral
 * (`frontend/e2e/global-setup.ts` starts the real board server, which
 * answers both the SPA and its API from one port -- no dev server, no
 * proxy). A single worker keeps every spec driving that one shared server
 * sequentially.
 */
export default defineConfig({
	testDir: './e2e',
	timeout: 30_000,
	fullyParallel: false,
	workers: 1,
	retries: 0,
	reporter: [['list']],
	globalSetup: './e2e/global-setup.ts',
	use: {
		trace: 'retain-on-failure'
	},
	projects: [
		{
			name: 'desktop',
			use: { ...devices['Desktop Chrome'], viewport: { width: 1280, height: 800 } }
		}
	]
});
