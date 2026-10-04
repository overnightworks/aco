import { defineConfig, devices } from '@playwright/test';

/**
 * No `webServer` here: the app and its API target are both ephemeral and
 * assigned together (`frontend/e2e/global-setup.ts` starts the fake board
 * server, then points a Vite dev server's `/api` proxy at it). A single
 * worker keeps every spec driving the one shared server sequentially.
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
