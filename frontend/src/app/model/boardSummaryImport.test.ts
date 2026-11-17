import { expect, test } from 'vitest';

test('the board summary module loads first without an undefined label table', async () => {
	await expect(
		import('/home/felix-hummert/git/aco-worktrees/issue-908-board-saves-on-page-leave/frontend/src/app/model/boardSummary')
	).resolves.toBeDefined();
});
