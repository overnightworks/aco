import { describe, expect, test } from 'vitest';
import { cardOption, item, line, optionLine, ruledOptionLine } from '../../test-support/board';
import type { Outcome, RulingVia } from '../../types';
import {
	bindingSentences,
	decidedAnswer,
	decidedMeta,
	displayDate,
	HOW_LABEL,
	howText,
	NOT_RECORDED
} from './decidedCard';

function ruledOption(via: RulingVia) {
	return ruledOptionLine({ ruling: 'B', ruled_on: '2026-10-25', via });
}

describe('howText', () => {
	test.each<[string, RulingVia, string]>([
		['[ABRD-54] board', 'board', 'Board · 25.10.2026'],
		['[ABRD-54] chat', 'chat', 'From chat · 25.10.2026'],
		['[ABRD-54] default', 'default', 'Recommendation kept – no answer · 25.10.2026']
	])('%s reads its stored way and the date', (_name, via, expected) => {
		expect(howText(ruledOption(via))).toBe(expected);
		expect(HOW_LABEL[via]).toBe(expected.split(' · ')[0]);
	});

	test('[ABRD-54] a yes/no line reads not recorded and the date', () => {
		expect(howText(line({ ruling: 'no', ruled_on: '2026-10-25' }))).toBe(
			`${NOT_RECORDED} · 25.10.2026`
		);
	});
});

describe('displayDate', () => {
	test('[ABRD-54] writes an ISO date as day, month and year', () => {
		expect(displayDate('2026-10-05')).toBe('05.10.2026');
	});
});

describe('decidedAnswer', () => {
	test('[ABRD-37] names the chosen option by letter and name', () => {
		expect(decidedAnswer(ruledOption('board'))).toBe('B — As today');
	});

	test.each<[Outcome, string]>([
		['yes', 'Ja'],
		['no', 'Nein'],
		['later', 'Später']
	])('[ABRD-37] a yes/no line ruled %s reads %s', (ruling, expected) => {
		expect(decidedAnswer(line({ ruling }))).toBe(expected);
	});

	test('[ABRD-57] an option line ruled other reads Other and its answer in quotes', () => {
		const ruled = optionLine({ ruling: 'other', other: 'Nur am Desktop.', via: 'chat' });

		expect(decidedAnswer(ruled)).toBe('Other: „Nur am Desktop.“');
	});
});

describe('bindingSentences', () => {
	test.each([
		[
			'[ABRD-37] the contract, then the line sentence',
			'Rule 10.',
			['The browser keeps jumping.', 'Rule 10.']
		],
		[
			'[ABRD-37] the contract alone when the line only repeats it',
			'The browser keeps jumping.',
			['The browser keeps jumping.']
		]
	])('an option line binds %s', (_name, text, expected) => {
		const ruled = optionLine({
			text,
			ruling: 'B',
			options: [
				cardOption(),
				cardOption({ letter: 'B', name: 'As today', contract: 'The browser keeps jumping.' })
			]
		});

		expect(bindingSentences(ruled)).toEqual(expected);
	});

	test('[ABRD-57] an option line ruled other binds its answer alone', () => {
		const ruled = optionLine({ text: 'Rule 10.', ruling: 'other', other: 'Nur am Desktop.' });

		expect(bindingSentences(ruled)).toEqual(['Nur am Desktop.']);
	});

	test('[ABRD-37] a yes/no line binds its own sentence', () => {
		expect(bindingSentences(line({ text: 'Guests may join the call.', ruling: 'yes' }))).toEqual([
			'Guests may join the call.'
		]);
	});
});

describe('decidedMeta', () => {
	test('[ABRD-37] an option line names repository, area and kind without the undo token', () => {
		const meta = decidedMeta('songmaker', item(), optionLine({ area: 'Song page' }));

		expect(meta).toEqual({ where: 'songmaker › Song page', kind: 'Product' });
	});

	test('[ABRD-37] a yes/no line names the repository and the item title alone', () => {
		const meta = decidedMeta('songmaker', item({ title: 'Share page' }), line());

		expect(meta).toEqual({ where: 'songmaker › Share page' });
	});
});
