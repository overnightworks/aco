import { svelte } from '@sveltejs/vite-plugin-svelte';
import { svelteTesting } from '@testing-library/svelte/vite';
import { defineConfig } from 'vitest/config';

// The Python package serves these committed files, so every name is fixed:
// a content hash would turn each rebuild into a rename the "assets fresh"
// CI gate reports as drift.
const STATIC_DIRECTORY = '../src/aco_board/static';

export default defineConfig({
	plugins: [svelte({ configFile: false }), svelteTesting()],
	base: './',
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
			exclude: ['src/**/*.test.ts', 'src/test-setup.ts'],
			reporter: ['text', 'lcov'],
			reportsDirectory: '../reports/frontend-coverage'
		}
	}
});
