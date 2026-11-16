import { expect, test } from 'vitest';
import { barShares, progressFigure, remainingFigure } from './progress';
import type { WorkRange } from '../../types';

test.each([
	[{ closed: 7, landed: 0, planned: 48, open: 31, uncut: 10, percent: 14 }, '7/48 · 14 %'],
	[{ closed: 5, landed: 5, planned: 5, open: 0, uncut: 0, percent: 100 }, '5/5 · 100 %'],
	[{ closed: 0, landed: 0, planned: 0, open: 0, uncut: 0, percent: null }, '0/0']
])('[ABRD-131] %j reads %s', (counts, figure) => {
	expect(progressFigure(counts)).toBe(figure);
});

test('[ABRD-135] a bar splits its closed share into landed and other closes', () => {
	const shares = barShares({
		closed: 6,
		landed: 2,
		planned: 8,
		open: 2,
		uncut: 0,
		percent: 75
	});

	expect(shares).toEqual({ landed: 25, otherClosed: 50 });
});

function range(lowSeconds: number, highSeconds: number, samples = 31): WorkRange {
	return {
		error: null,
		low_seconds: lowSeconds,
		high_seconds: highSeconds,
		samples,
		classes: [{ size: null, lanes: 5, basis: 'pooled', samples }]
	};
}

test.each([
	[
		5,
		range(3 * 3600, 7 * 3600),
		'5 lanes left · about 3 to 7 h agent work · from 31 finished items'
	],
	[1, range(1900, 2400, 1), '1 lane left · under 1 h agent work · from 1 finished item'],
	[2, range(600, 9000), '2 lanes left · under 1 to 3 h agent work · from 31 finished items'],
	[2, range(7500, 8100), '2 lanes left · about 2 h agent work · from 31 finished items'],
	[3, { error: 'not enough lane records yet' }, '3 lanes left · not enough lane records yet'],
	[1, { error: 'lane records unreadable' }, '1 lane left · lane records unreadable']
])('[ABRD-146] %i lanes with %j read %s', (lanes, estimate, figure) => {
	expect(remainingFigure(lanes, estimate)).toBe(figure);
});

test('[ABRD-140] a container with no estimate has no remaining figure', () => {
	expect(remainingFigure(0, null)).toBeNull();
});
