import { describe, expect, test } from 'vitest';
import { item, line, optionLine, repo } from '../../test-support/board';
import {
	cardHeading,
	cardSentence,
	findSelectedLine,
	firstOpenKey,
	historyLines,
	nextOpenAfter,
	openList,
	outcomeLabel,
	pictureDataUri,
	ruledOutcomeText,
	tabCounts
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

test('[ABRD-29] first selection is the option line that follows a yes/no line in the same repository', () => {
	const repos = [
		repo({
			name: 'first',
			items: [
				item({ number: 2, lines: [line({ index: 1 })] }),
				item({ number: 3, lines: [optionLine({ index: 1 })] })
			]
		})
	];

	expect(firstOpenKey(repos)).toBe('first:3:1');
});

describe('openList', () => {
	test('[ABRD-28] groups follow configured order, a failed repository as its error group', () => {
		const { groups } = openList([
			repo({ name: 'zeta', items: [item({ number: 1, lines: [line({ index: 1 })] })] }),
			repo({ name: 'broken', error: 'aco failed', items: [] }),
			repo({ name: 'alpha', items: [item({ number: 2, lines: [line({ index: 1 })] })] })
		]);

		expect(groups.map((group) => group.repo)).toEqual(['zeta', 'broken', 'alpha']);
		expect(groups[1]).toEqual({ repo: 'broken', error: 'aco failed' });
	});

	test('[ABRD-28] a row carries its key, state, label and the full question as its title', () => {
		const { groups } = openList([
			repo({
				name: 'a',
				items: [
					item({
						number: 7,
						lines: [
							optionLine({ index: 2, topic: 'Sprung', question: 'Keep the song open?' }),
							line({ index: 3, question: 'Guests allowed?', text: 'Guests may join.' }),
							line({ index: 4, question: null, text: 'Plain sentence.' })
						]
					})
				]
			})
		]);

		expect(groups).toEqual([
			{
				repo: 'a',
				rows: [
					{ key: 'a:7:2', state: 'open', label: 'Sprung', title: 'Keep the song open?' },
					{ key: 'a:7:3', state: 'todo', label: 'Guests allowed?', title: 'Guests allowed?' },
					{ key: 'a:7:4', state: 'todo', label: 'Plain sentence.', title: 'Plain sentence.' }
				]
			}
		]);
	});

	test('[ABRD-29] option rows come before yes/no rows in one repository, each in aco order', () => {
		const { groups } = openList([
			repo({
				name: 'a',
				items: [
					item({
						number: 1,
						lines: [line({ index: 1 }), optionLine({ index: 2 }), line({ index: 3 })]
					}),
					item({ number: 2, lines: [optionLine({ index: 1 }), line({ index: 2 })] })
				]
			})
		]);

		const [group] = groups;
		expect(group && 'rows' in group ? group.rows.map((row) => row.key) : []).toEqual([
			'a:1:2',
			'a:2:1',
			'a:1:1',
			'a:1:3',
			'a:2:2'
		]);
	});

	test('[ABRD-49] readable repositories with no open line are quiet, a ruled-only one included', () => {
		const { groups, quiet } = openList([
			repo({ name: 'open', items: [item({ lines: [line()] })] }),
			repo({ name: 'empty', items: [] }),
			repo({ name: 'broken', error: 'down', items: [] }),
			repo({
				name: 'ruled',
				items: [item({ lines: [line({ ruling: 'yes', ruled_on: '2026-10-01' })] })]
			})
		]);

		expect(groups.map((group) => group.repo)).toEqual(['open', 'broken']);
		expect(quiet).toEqual(['empty', 'ruled']);
	});
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

describe('[ABRD-30] ruledOutcomeText', () => {
	test.each([
		['yes', '2026-10-01', 'Ja · 2026-10-01'],
		['no', '2026-10-02', 'Nein · 2026-10-02'],
		['later', '2026-10-03', 'Später · 2026-10-03'],
		['yes', null, 'Ja · ']
	] as const)('%s on %s -> %s', (ruling, ruledOn, expected) => {
		expect(ruledOutcomeText(ruling, ruledOn)).toBe(expected);
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

	test('[ABRD-50] among yes/no lines only, the first other open line comes next', () => {
		expect(nextOpenAfter(repos, 'repo:42:1')).toBe('repo:42:2');
	});

	test('[ABRD-50] the decided line is skipped, so from the last line the first one comes next', () => {
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

	test('[ABRD-50] an option line in a later repository wins over the next yes/no line', () => {
		const mixed = [
			repo({
				name: 'a',
				items: [item({ number: 1, lines: [line({ index: 1 }), line({ index: 2 })] })]
			}),
			repo({ name: 'b', items: [item({ number: 2, lines: [optionLine({ index: 1 })] })] })
		];

		expect(nextOpenAfter(mixed, 'a:1:1')).toBe('b:2:1');
	});

	test('[ABRD-50] with only yes/no lines left it returns the first of them', () => {
		const onlyYesNo = [
			repo({
				name: 'a',
				items: [item({ number: 1, lines: [line({ index: 1 }), line({ index: 2 })] })]
			}),
			repo({ name: 'b', items: [item({ number: 2, lines: [line({ index: 1 })] })] })
		];

		expect(nextOpenAfter(onlyYesNo, 'a:1:2')).toBe('a:1:1');
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

describe('tabCounts', () => {
	test('[ABRD-51] counts the open list rows and the ruled lines', () => {
		const repos = [
			repo({
				items: [
					item({
						number: 1,
						lines: [
							optionLine({ index: 1 }),
							line({ index: 2 }),
							line({ index: 3, ruling: 'yes', ruled_on: '2026-10-01' })
						]
					})
				]
			})
		];

		expect(tabCounts(repos)).toEqual({ open: 2, decided: 1 });
	});

	test('[ABRD-51] a failed repository adds to neither count', () => {
		const repos = [
			repo({ name: 'broken', error: 'down', items: [item({ number: 9, lines: [line()] })] })
		];

		expect(tabCounts(repos)).toEqual({ open: 0, decided: 0 });
	});

	test('[ABRD-51] an empty board counts nothing', () => {
		expect(tabCounts([])).toEqual({ open: 0, decided: 0 });
	});
});
