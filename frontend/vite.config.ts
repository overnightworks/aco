import { svelte } from '@sveltejs/vite-plugin-svelte';
import { svelteTesting } from '@testing-library/svelte/vite';
import { defineConfig } from 'vitest/config';

// The Python package serves these committed files, so every name is fixed:
// a content hash would turn each rebuild into a rename the "assets fresh"
// CI gate reports as drift.
const STATIC_DIRECTORY = '../src/aco/board/static';

// `pnpm dev` proxies the API to a board already running on its default
// loopback port; the E2E harness (frontend/e2e/global-setup.ts) overrides
// this with its own ephemeral server instead. First used with issue #643.
const DEFAULT_BOARD_API_TARGET = 'http://127.0.0.1:8765';

export default defineConfig({
	plugins: [svelte({ configFile: false }), svelteTesting()],
	base: './',
	server: {
		proxy: {
			'/api': process.env.VITE_BOARD_API_TARGET ?? DEFAULT_BOARD_API_TARGET
		}
	},
	build: {
		outDir: STATIC_DIRECTORY,
		emptyOutDir: true,
		sourcemap: false,
		rolldownOptions: {
			output: {
				entryFileNames: 'assets/index.js',
				chunkFileNames: 'assets/[name].js',
				assetFileNames: 'assets/[name][extname]'
			}
		}
	},
	test: {
		include: ['src/**/*.test.ts'],
		environment: 'jsdom',
		setupFiles: ['src/test-setup.ts'],
		coverage: {
			provider: 'v8',
			include: ['src/**/*.{ts,svelte}'],
			exclude: ['src/**/*.test.ts', 'src/**/*.d.ts', 'src/test-setup.ts', 'src/test-support/**'],
			reporter: ['text', 'lcov'],
			reportsDirectory: '../reports/frontend-coverage',
			// `.svelte` carries no logic (see app/model and app/state's own
			// docstrings, issue #368), so its owners are held to full coverage.
			thresholds: {
				'src/app/model/**': { statements: 100, branches: 100, functions: 100, lines: 100 },
				'src/app/state/**': { statements: 100, branches: 100, functions: 100, lines: 100 }
			}
		}
	}
});
