import { describe, expect, test } from 'vitest';
import { cardOption, item, line, optionLine } from '../../test-support/board';
import type { OptionLine } from '../../types';
import {
	acceptAllConfirmation,
	cardName,
	cardTitle,
	confirmationFor,
	livePicks,
	nextOpenAfterPick,
	openPoints,
	pickedText,
	pointNumber,
	recommendedPicks,
	withPick,
	type Pick
} from './card';
import { chosenText, pointPickLabel } from './optionCard';

const optionA = cardOption({ name: 'Keep it open' });
const optionB = cardOption({ letter: 'B', name: 'As today' });
const finalB = cardOption({
	letter: 'B',
	name: 'Delete it',
	undo: 'final',
	undo_how: 'nicht rückholbar.'
});

function point(index: number, overrides: Partial<OptionLine> = {}): OptionLine {
	return optionLine({
		index,
		fingerprint: `fp-${index}`,
		question: `Question ${index}?`,
		options: [optionA, optionB],
		...overrides
	});
}

const threePoints = [point(2), point(3), point(5)];

function pick(shown: OptionLine, option = optionB): Pick {
	return { shown, option };
}

describe('openPoints', () => {
	test('[ABRD-82] an item’s open option lines are its points, in aco’s order', () => {
		const ruled = point(3, { ruling: 'A', ruled_on: '2026-10-26' });
		const members = item({ lines: [point(2), line({ index: 4 }), ruled, point(5)] });

		const indexes = openPoints(members).map((open) => open.index);

		expect(indexes).toEqual([2, 5]);
	});

	test('[ABRD-82] a line with its head is still a point', () => {
		const members = item({ lines: [point(2, { returned_on: '2026-10-27' })] });

		const indexes = openPoints(members).map((open) => open.index);

		expect(indexes).toEqual([2]);
	});
});

describe('cardName and cardTitle', () => {
	test('[ABRD-82] a one-point card is named by its topic and titled by its question', () => {
		const points = [point(2, { topic: 'Jump', question: 'Keep the song open?' })];

		expect(cardName(points)).toBe('Jump');
		expect(cardTitle(points)).toBe('Keep the song open?');
	});

	test('[ABRD-82] a card of points is named by its area and count, and titled by that name', () => {
		const points = threePoints.map((open) => ({ ...open, area: 'Song-Seite' }));

		expect(cardName(points)).toBe('Song-Seite · 3 points');
		expect(cardTitle(points)).toBe('Song-Seite · 3 points');
	});

	test('[ABRD-82] distinct areas join in point order with a slash, each once', () => {
		const points = [
			point(2, { area: 'Song-Seite' }),
			point(3, { area: 'Bibliothek' }),
			point(5, { area: 'Song-Seite' })
		];

		expect(cardName(points)).toBe('Song-Seite / Bibliothek · 3 points');
	});
});

describe('picks as shown', () => {
	test('[ABRD-91] a pick keeps the point as it was shown when picked', () => {
		const picks = withPick([], pick(threePoints[0] as OptionLine));

		expect(livePicks(picks, threePoints)).toEqual(picks);
	});

	test('[ABRD-86] picking a point again changes its letter and leaves the others', () => {
		const first = threePoints[0] as OptionLine;
		const second = threePoints[1] as OptionLine;
		const picks = withPick(withPick([pick(first, optionA)], pick(second, optionA)), pick(first));

		const letters = livePicks(picks, threePoints).map((live) => live.option.letter);

		expect(letters).toEqual(['B', 'A']);
	});

	test('live picks follow the points’ order, not the order of picking', () => {
		const first = threePoints[0] as OptionLine;
		const last = threePoints[2] as OptionLine;
		const picks = [pick(last), pick(first)];

		const indexes = livePicks(picks, threePoints).map((live) => live.shown.index);

		expect(indexes).toEqual([2, 5]);
	});

	test('[ABRD-91] a re-read drops the pick of a changed point and keeps the others', () => {
		const picks = threePoints.map((shown) => pick(shown));
		const reread = [
			threePoints[0] as OptionLine,
			point(3, { fingerprint: 'fp-new' }),
			threePoints[2] as OptionLine
		];

		const indexes = livePicks(picks, reread).map((live) => live.shown.index);

		expect(indexes).toEqual([2, 5]);
	});

	test('[ABRD-91] a re-read drops the pick of a point that is no longer open', () => {
		const picks = threePoints.map((shown) => pick(shown));
		const reread = [threePoints[0] as OptionLine, threePoints[2] as OptionLine];

		const indexes = livePicks(picks, reread).map((live) => live.shown.index);

		expect(indexes).toEqual([2, 5]);
	});

	test('[ABRD-91] a point added since shows unchosen', () => {
		const picks = threePoints.map((shown) => pick(shown));
		const reread = [...threePoints, point(7)];

		expect(livePicks(picks, reread)).toHaveLength(3);
	});
});

describe('the open point', () => {
	test.each<[string, number | null, number, number[], number | null]>([
		['the first unchosen point opens after a pick on the open point', 2, 2, [2], 3],
		['the first unchosen point skips a chosen one', 2, 2, [2, 3], 5],
		['no point opens once every point is chosen', 5, 5, [2, 3, 5], null],
		['a pick on another point leaves the open point', 5, 2, [2], 5],
		['a pick with no point open opens none', null, 2, [2], null]
	])('[ABRD-86] %s', (_name, open, picked, chosen, expected) => {
		const live = threePoints
			.filter((candidate) => chosen.includes(candidate.index))
			.map((shown) => pick(shown));
		const shown = threePoints.find((candidate) => candidate.index === picked) as OptionLine;

		expect(nextOpenAfterPick(open, threePoints, live, shown)).toBe(expected);
	});
});

describe('Accept all', () => {
	test('[ABRD-89] every point’s pick is its recommended option as shown', () => {
		const points = [point(2, { recommended: 'B' }), point(3, { recommended: 'A' })];

		const letters = recommendedPicks(points).map((recommended) => recommended.option.letter);

		expect(letters).toEqual(['B', 'A']);
		expect(recommendedPicks(points).map((recommended) => recommended.shown)).toEqual(points);
	});

	test('[ABRD-89] a point whose recommended letter names no option picks nothing', () => {
		const points = [
			point(2, { recommended: 'A' }),
			point(3, { options: [optionB], recommended: 'A' })
		];

		expect(recommendedPicks(points)).toHaveLength(1);
	});

	test('[ABRD-89] no confirm is asked when no recommended option is final', () => {
		expect(acceptAllConfirmation(threePoints)).toBeNull();
	});

	test('[ABRD-90] the confirm names each point with a final recommended option and its consequence', () => {
		const points = [
			point(2),
			point(3, { options: [optionA, finalB], recommended: 'B' }),
			point(5, { options: [optionA, finalB], recommended: 'B' }),
			point(7, { options: [optionA, finalB], recommended: 'A' })
		];

		expect(acceptAllConfirmation(points)).toEqual({
			title: 'Accept all recommendations?',
			verb: 'Accept all',
			lines: ['Point 2: Nicht rückholbar.', 'Point 3: Nicht rückholbar.']
		});
	});
});

describe('confirmationFor a pick', () => {
	test('[ABRD-46] a reversible pick asks nothing', () => {
		expect(confirmationFor(threePoints, pick(threePoints[0] as OptionLine))).toBeNull();
	});

	test('[ABRD-46] a final pick on a one-point card asks with the bare consequence', () => {
		const single = point(2, { options: [optionA, finalB] });

		expect(confirmationFor([single], pick(single, finalB))).toEqual({
			title: 'Decide B?',
			verb: 'Decide B',
			lines: ['Nicht rückholbar.']
		});
	});

	test('[ABRD-88] a final pick on a card of points names its point', () => {
		const second = point(3, { options: [optionA, finalB] });
		const points = [point(2), second, point(5)];

		expect(confirmationFor(points, pick(second, finalB))).toEqual({
			title: 'Decide B?',
			verb: 'Decide B',
			lines: ['Point 2: Nicht rückholbar.']
		});
	});
});

describe('words of a card', () => {
	test('[ABRD-86] the Decide row counts the chosen points', () => {
		expect(chosenText(1, 3)).toBe('1 of 3 chosen');
	});

	test('[ABRD-84] a point’s pick is named by the point, its letter and the option', () => {
		expect(pointPickLabel(2, optionA)).toBe('Point 2: A – Keep it open');
	});

	test('a point is numbered by its place among the points', () => {
		expect(pointNumber(threePoints, threePoints[2] as OptionLine)).toBe(3);
	});

	test('[ABRD-87] the strip of a card of points lists each point’s letter in point order and the name', () => {
		const points = threePoints.map((open) => ({ ...open, area: 'Song-Seite' }));
		const picks = [pick(points[0] as OptionLine, optionB), pick(points[1] as OptionLine, optionA)];

		expect(pickedText(points, picks)).toBe('1B 2A · Song-Seite · 3 points');
	});

	test('[ABRD-58] the strip of a one-point card names the letter, the option and the topic', () => {
		const single = point(2, { topic: 'Jump' });

		expect(pickedText([single], [pick(single, optionB)])).toBe('B — As today · Jump');
	});
});
