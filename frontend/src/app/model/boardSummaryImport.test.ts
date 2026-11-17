import { expect, test } from 'vitest';

test('the board summary module loads first without an undefined label table', async () => {
	await expect(import('./boardSummary')).resolves.toBeDefined();
});
