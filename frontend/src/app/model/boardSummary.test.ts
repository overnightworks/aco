import { describe, expect, test } from 'vitest';
import { item, line, repo } from '../../test-support/board';
import { isBoardEmpty, lineStatusText, totalLineCount } from './boardSummary';

describe('totalLineCount / isBoardEmpty', () => {
	test('counts every line across every item and repo', () => {
		const repos = [
			repo({ items: [item({ lines: [line(), line({ index: 2 })] })] }),
			repo({ name: 'other', items: [item({ number: 7, lines: [line()] })] })
		];

		expect(totalLineCount(repos)).toBe(3);
		expect(isBoardEmpty(repos)).toBe(false);
	});

	test('a repo with no items counts as empty', () => {
		const repos = [repo({ items: [] })];

		expect(totalLineCount(repos)).toBe(0);
		expect(isBoardEmpty(repos)).toBe(true);
	});

	test('no repos at all counts as empty', () => {
		expect(isBoardEmpty([])).toBe(true);
	});
});

describe('lineStatusText', () => {
	test.each([
		[line({ ruling: 'yes', ruled_on: '2026-10-01' }), 'Ja · 2026-10-01'],
		[line({ ruling: 'no', ruled_on: '2026-10-02' }), 'Nein · 2026-10-02'],
		[line({ ruling: 'later', ruled_on: '2026-10-03' }), 'Später · 2026-10-03'],
		[line({ ruling: 'yes', ruled_on: null }), 'Ja · '],
		[line({ ruling: null, default: 'yes' }), 'Empfohlen: Ja'],
		[line({ ruling: null, default: null }), 'Offen']
	])('%o -> %s', (candidate, expected) => {
		expect(lineStatusText(candidate)).toBe(expected);
	});
});
