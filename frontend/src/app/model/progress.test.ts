import { expect, test } from 'vitest';
import { progressFigure } from './progress';

test.each([
	[{ closed: 7, planned: 48, open: 31, uncut: 10, percent: 14 }, '7/48 · 14 %'],
	[{ closed: 5, planned: 5, open: 0, uncut: 0, percent: 100 }, '5/5 · 100 %'],
	[{ closed: 0, planned: 0, open: 0, uncut: 0, percent: null }, '0/0']
])('[ABRD-131] %j reads %s', (counts, figure) => {
	expect(progressFigure(counts)).toBe(figure);
});
