import { expect, test } from 'vitest';
import { repo, stepRead } from '../../test-support/board';
import { stepGroups } from './steps';

function names(groups: { name: string }[]) {
	return groups.map((group) => group.name);
}

test('ABRD-199: the repo whose first step has the newer since stands first', () => {
	const groups = stepGroups([
		repo({ name: 'older', steps: [stepRead({ since: '2026-10-01', number: 9 })] }),
		repo({ name: 'newer', steps: [stepRead({ since: '2026-11-01', number: 1 })] })
	]);

	expect(names(groups)).toEqual(['newer', 'older']);
});

test('ABRD-199: equal first dates put the higher item first', () => {
	const groups = stepGroups([
		repo({ name: 'low', steps: [stepRead({ number: 3 })] }),
		repo({ name: 'high', steps: [stepRead({ number: 8 })] })
	]);

	expect(names(groups)).toEqual(['high', 'low']);
});

test('ABRD-199: equal dates and items keep the configured order', () => {
	const groups = stepGroups([
		repo({ name: 'first', steps: [stepRead()] }),
		repo({ name: 'second', steps: [stepRead()] })
	]);

	expect(names(groups)).toEqual(['first', 'second']);
});

test('ABRD-199: a repo whose read failed stands last, whatever the others hold', () => {
	const groups = stepGroups([
		repo({ name: 'broken', error: 'down', steps: [] }),
		repo({ name: 'old', steps: [stepRead({ since: '2020-01-01' })] })
	]);

	expect(names(groups)).toEqual(['old', 'broken']);
});

test('ABRD-199: a readable repo without a step shows no group', () => {
	const groups = stepGroups([
		repo({ name: 'quiet', steps: [] }),
		repo({ name: 'busy', steps: [stepRead()] })
	]);

	expect(names(groups)).toEqual(['busy']);
});
