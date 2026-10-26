import { describe, expect, test } from 'vitest';
import { item, line, optionLine, repo } from '../../test-support/board';
import {
	cardHeading,
	cardSentence,
	findSelectedLine,
	firstOpenKey,
	historyLines,
	isBoardEmpty,
	lineStatusText,
	nextOpenAfter,
	outcomeLabel,
	pictureDataUri,
	totalLineCount
} from './boardSummary';

test('first selection follows configured order, skipping failed repos and ruled-only groups', () => {
	const repos = [
		repo({ name: 'failed', error: 'Read failed' }),
		repo({
			name: 'first',
			items: [
				item({ number: 8, lines: [line({ ruling: 'yes' })] }),
				item({ number: 2, lines: [line({ index: 3 }), line({ index: 1 })] })
			]
		}),
		repo({ name: 'last' })
	];
	expect(firstOpenKey(repos)).toBe('first:2:3');
	expect(firstOpenKey([])).toBeNull();
	expect(firstOpenKey([repo({ items: [item({ lines: [line({ ruling: 'yes' })] })] })])).toBeNull();
});

test.each(['first', 'last'] as const)(
	'history keeps missing dates last from %s input with descending dates/items/lines and stable repo ties',
	(position) => {
		const entries = [
			['a', 9, 1, null],
			['b', 2, 1, '2026-10-02'],
			['c', 3, 1, '2026-10-02'],
			['d', 3, 2, '2026-10-02'],
			['e', 3, 2, '2026-10-02'],
			['f', 99, 9, '2026-10-01']
		] as const;
		const ordered = position === 'first' ? entries : [...entries.slice(1), entries[0]];
		const repos = ordered.map(([name, number, index, ruled_on]) =>
			repo({
				name,
				items: [
					item({ number, lines: [line({ index, ruling: 'later', ruled_on }), line({ index: 10 })] })
				]
			})
		);
		const before = structuredClone(repos);
		expect(historyLines(repos).map((entry) => entry.repo)).toEqual(['d', 'e', 'c', 'b', 'f', 'a']);
		expect(repos).toEqual(before);
	}
);

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
		[line({ ruling: null, default: null }), 'Offen'],
		[optionLine({ recommended: 'B' }), 'Empfohlen: B'],
		[optionLine({ ruling: 'A', ruled_on: '2026-10-04' }), 'A · Keep the song open · 2026-10-04']
	])('%o -> %s', (candidate, expected) => {
		expect(lineStatusText(candidate)).toBe(expected);
	});
});

describe('outcomeLabel', () => {
	test.each([
		['yes', 'Ja'],
		['no', 'Nein'],
		['later', 'Später']
	] as const)('%s -> %s', (outcome, expected) => {
		expect(outcomeLabel(outcome)).toBe(expected);
	});
});

describe('cardHeading / cardSentence', () => {
	test('a distinct question becomes the heading, the sentence stays below it', () => {
		const card = line({ question: 'Guests allowed?', text: 'Guests may join the call.' });

		expect(cardHeading(card)).toBe('Guests allowed?');
		expect(cardSentence(card)).toBe('Guests may join the call.');
	});

	test('an option line is headed by its question', () => {
		const card = optionLine({ question: 'Keep the song open?' });

		expect(cardHeading(card)).toBe('Keep the song open?');
	});

	test('with no distinct question, the sentence itself is the heading, shown once', () => {
		const card = line({ question: null, text: 'Guests may join the call.' });

		expect(cardHeading(card)).toBe('Guests may join the call.');
		expect(cardSentence(card)).toBeNull();
	});
});

describe('pictureDataUri', () => {
	test('embeds the SVG as a base64 data URI, never as inline markup', () => {
		const uri = pictureDataUri('<svg>ü</svg>');

		expect(uri).toMatch(/^data:image\/svg\+xml;base64,/);
		const encoded = uri.slice(uri.indexOf(',') + 1);
		expect(Buffer.from(encoded, 'base64').toString('utf-8')).toBe('<svg>ü</svg>');
	});
});

describe('findSelectedLine', () => {
	const openLine = line({ index: 1 });
	const openItem = item({ number: 42, title: 'Share page', lines: [openLine] });
	const repos = [
		repo({ name: 'a', items: [openItem] }),
		repo({ name: 'b', error: 'down', items: [] })
	];

	test('no key selects nothing', () => {
		expect(findSelectedLine(repos, null)).toBeNull();
	});

	test('a key naming no line, or one in a failed repo, selects nothing', () => {
		expect(findSelectedLine(repos, 'a:42:9')).toBeNull();
		expect(findSelectedLine(repos, 'b:1:1')).toBeNull();
	});

	test('a key naming an open line resolves its repo, item and line', () => {
		expect(findSelectedLine(repos, 'a:42:1')).toEqual({
			repo: 'a',
			item: openItem,
			line: openLine
		});
	});

	test('a key naming an already-ruled line still resolves it, so Stage can show it read-only', () => {
		const ruledLine = line({ index: 2, ruling: 'yes', ruled_on: '2026-10-01' });
		const ruledItem = item({ number: 42, title: 'Share page', lines: [ruledLine] });
		const withRuled = [repo({ name: 'a', items: [ruledItem] })];

		expect(findSelectedLine(withRuled, 'a:42:2')).toEqual({
			repo: 'a',
			item: ruledItem,
			line: ruledLine
		});
	});
});

describe('nextOpenAfter', () => {
	const first = line({ index: 1 });
	const second = line({ index: 2 });
	const third = line({ index: 3 });
	const repos = [repo({ items: [item({ number: 42, lines: [first, second, third] })] })];

	test('moves to the next open line in board order', () => {
		expect(nextOpenAfter(repos, 'repo:42:1')).toBe('repo:42:2');
	});

	test('wraps to the first open line once the given key was the last in order', () => {
		expect(nextOpenAfter(repos, 'repo:42:3')).toBe('repo:42:1');
	});

	test('returns null once no line is open any more', () => {
		const allRuled = [
			repo({
				items: [
					item({
						number: 42,
						lines: [
							line({ index: 1, ruling: 'yes', ruled_on: '2026-10-01' }),
							line({ index: 2, ruling: 'no', ruled_on: '2026-10-01' })
						]
					})
				]
			})
		];

		expect(nextOpenAfter(allRuled, 'repo:42:1')).toBeNull();
	});

	test('skips lines belonging to a repo that failed to read', () => {
		const withAFailedRepo = [
			...repos,
			repo({ name: 'broken', error: 'down', items: [item({ number: 9, lines: [line()] })] })
		];

		expect(nextOpenAfter(withAFailedRepo, 'repo:42:1')).toBe('repo:42:2');
	});

	test('skips a line that was already ruled when picking the next one', () => {
		const withARuledMiddle = [
			repo({
				items: [
					item({
						number: 42,
						lines: [first, line({ index: 2, ruling: 'yes', ruled_on: '2026-10-01' }), third]
					})
				]
			})
		];

		expect(nextOpenAfter(withARuledMiddle, 'repo:42:1')).toBe('repo:42:3');
	});
});
