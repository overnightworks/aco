import { describe, expect, test } from 'vitest';
import { item, line, optionLine, repo } from '../../test-support/board';
import {
	cardHeading,
	cardSentence,
	decidedList,
	findSelection,
	selectionHeading,
	firstDecidedKey,
	firstOpenKey,
	nextOpenAfter,
	stageAfterReturned,
	openList,
	outcomeLabel,
	pictureDataUri,
	STATE_LABEL,
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

test('[ABRD-29] first selection is the option card that follows a yes/no line in the same repository', () => {
	const repos = [
		repo({
			name: 'first',
			items: [
				item({ number: 2, lines: [line({ index: 1 })] }),
				item({ number: 3, lines: [optionLine({ index: 1 })] })
			]
		})
	];

	expect(firstOpenKey(repos)).toBe('first:3:card');
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
					{ key: 'a:7:card', state: 'open', label: 'Sprung', title: 'Keep the song open?' },
					{ key: 'a:7:3', state: 'todo', label: 'Guests allowed?', title: 'Guests allowed?' },
					{ key: 'a:7:4', state: 'todo', label: 'Plain sentence.', title: 'Plain sentence.' }
				]
			}
		]);
	});

	test('[ABRD-82] the open option lines of one item are one row named by area and count, its title the same', () => {
		const { groups } = openList([
			repo({
				name: 'a',
				items: [
					item({
						number: 7,
						lines: [
							optionLine({ index: 2, area: 'Song-Seite' }),
							optionLine({ index: 3, area: 'Song-Seite' }),
							optionLine({ index: 4, area: 'Song-Seite' }),
							line({ index: 5 })
						]
					})
				]
			})
		]);

		const name = 'Song-Seite · 3 points';
		expect(groups).toEqual([
			{
				repo: 'a',
				rows: [
					{ key: 'a:7:card', state: 'open', label: name, title: name },
					{ key: 'a:7:5', state: 'todo', label: 'Guests?', title: 'Guests?' }
				]
			}
		]);
	});

	test('[ABRD-82] a ruled option line is no point of its item’s row', () => {
		const { groups } = openList([
			repo({
				name: 'a',
				items: [
					item({
						number: 7,
						lines: [
							optionLine({ index: 2, topic: 'Sprung' }),
							optionLine({ index: 3, ruling: 'A', ruled_on: '2026-10-01' })
						]
					})
				]
			})
		]);

		const [group] = groups;
		expect(group && 'rows' in group ? group.rows.map((row) => row.label) : []).toEqual(['Sprung']);
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
			'a:1:card',
			'a:2:card',
			'a:1:1',
			'a:1:3',
			'a:2:2'
		]);
	});

	test('[ABRD-61] a card with a returned line is a back row ranked after open and before todo', () => {
		const { groups } = openList([
			repo({
				name: 'a',
				items: [
					item({ number: 1, lines: [line({ index: 1 })] }),
					item({
						number: 2,
						lines: [optionLine({ index: 1, topic: 'Sprung', returned_on: '2026-10-27' })]
					}),
					item({ number: 3, lines: [optionLine({ index: 1 })] })
				]
			})
		]);

		const [group] = groups;
		expect(group && 'rows' in group ? group.rows.map((row) => row.key) : []).toEqual([
			'a:3:card',
			'a:2:card',
			'a:1:1'
		]);
		expect(group && 'rows' in group ? group.rows[1]?.state : null).toBe('back');
		expect(STATE_LABEL.back).toBe('With head');
	});

	test('[ABRD-61] a card is with its head while any of its points is', () => {
		const { groups } = openList([
			repo({
				name: 'a',
				items: [
					item({
						number: 1,
						lines: [optionLine({ index: 1 }), optionLine({ index: 2, returned_on: '2026-10-27' })]
					}),
					item({ number: 2, lines: [optionLine({ index: 1 })] })
				]
			})
		]);

		const [group] = groups;
		expect(group && 'rows' in group ? group.rows.map((row) => row.key) : []).toEqual([
			'a:2:card',
			'a:1:card'
		]);
		expect(group && 'rows' in group ? group.rows[1]?.state : null).toBe('back');
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

describe('decidedList', () => {
	function rowKeys(group: ReturnType<typeof decidedList>['groups'][number] | undefined): string[] {
		return group && 'rows' in group ? group.rows.map((row) => row.key) : [];
	}

	test('[ABRD-30] groups ruled lines per repository in configured order, a failed one as its error group and a repository with nothing ruled absent', () => {
		const { groups, quiet } = decidedList([
			repo({
				name: 'first',
				items: [
					item({ lines: [line({ ruling: 'yes', ruled_on: '2026-10-01' }), line({ index: 2 })] })
				]
			}),
			repo({ name: 'broken', error: 'down' }),
			repo({ name: 'untouched', items: [item({ lines: [line()] })] }),
			repo({
				name: 'last',
				items: [item({ lines: [optionLine({ ruling: 'A', ruled_on: '2026-10-02' })] })]
			})
		]);

		expect(groups.map((group) => group.repo)).toEqual(['first', 'broken', 'last']);
		expect(groups[1]).toEqual({ repo: 'broken', error: 'down' });
		expect(quiet).toEqual([]);
	});

	test('[ABRD-30] a row is done, keyed by its line, labelled with the option topic or the yes/no question, and titled with the question', () => {
		const { groups } = decidedList([
			repo({
				items: [
					item({
						number: 4,
						lines: [
							optionLine({
								index: 1,
								ruling: 'B',
								ruled_on: '2026-10-02',
								topic: 'Sprung',
								question: 'Keep the song open?'
							}),
							line({
								index: 2,
								ruling: 'no',
								ruled_on: '2026-10-01',
								question: 'Guests allowed?',
								text: 'Guests may join.'
							}),
							line({ index: 3, ruling: 'later', ruled_on: '2026-09-30', text: 'Dark mode?' })
						]
					})
				]
			})
		]);

		const [group] = groups;
		expect(group && 'rows' in group ? group.rows : []).toEqual([
			{ key: 'repo:4:1', state: 'done', label: 'Sprung', title: 'Keep the song open?' },
			{ key: 'repo:4:2', state: 'done', label: 'Guests allowed?', title: 'Guests allowed?' },
			{ key: 'repo:4:3', state: 'done', label: 'Dark mode?', title: 'Dark mode?' }
		]);
	});

	test('[ABRD-30] open lines are never listed', () => {
		const { groups } = decidedList([
			repo({
				items: [item({ lines: [line({ index: 1 }), optionLine({ index: 2 })] })]
			})
		]);

		expect(groups).toEqual([]);
	});

	test.each(['first', 'last'] as const)(
		'[ABRD-31] a repository lists the newest date first, then item number and line index descending, missing dates last, from %s input',
		(position) => {
			const entries = [
				[9, 1, null],
				[2, 1, '2026-10-02'],
				[3, 1, '2026-10-02'],
				[3, 2, '2026-10-02'],
				[99, 9, '2026-10-01']
			] as const;
			const ordered = position === 'first' ? entries : [...entries.slice(1), entries[0]];
			const repos = [
				repo({
					name: 'a',
					items: ordered.map(([number, index, ruled_on]) =>
						item({
							number,
							lines: [line({ index, ruling: 'later', ruled_on }), line({ index: 10 })]
						})
					)
				})
			];
			const before = structuredClone(repos);

			expect(rowKeys(decidedList(repos).groups[0])).toEqual([
				'a:3:2',
				'a:3:1',
				'a:2:1',
				'a:99:9',
				'a:9:1'
			]);
			expect(repos).toEqual(before);
		}
	);
});

describe('firstDecidedKey', () => {
	test('[ABRD-32] is the first row of the decided list', () => {
		const repos = [
			repo({ name: 'broken', error: 'down' }),
			repo({ name: 'open', items: [item({ lines: [line()] })] }),
			repo({
				name: 'ruled',
				items: [
					item({
						number: 3,
						lines: [
							line({ index: 1, ruling: 'yes', ruled_on: '2026-10-01' }),
							line({ index: 2, ruling: 'no', ruled_on: '2026-10-02' })
						]
					})
				]
			})
		];

		expect(firstDecidedKey(repos)).toBe('ruled:3:2');
	});

	test('[ABRD-32] is null with nothing ruled or only failed repositories', () => {
		expect(firstDecidedKey([])).toBeNull();
		expect(firstDecidedKey([repo({ error: 'down' })])).toBeNull();
		expect(firstDecidedKey([repo({ items: [item({ lines: [line()] })] })])).toBeNull();
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

describe('findSelection', () => {
	const openLine = line({ index: 1 });
	const optionPoint = optionLine({ index: 2 });
	const openItem = item({ number: 42, title: 'Share page', lines: [openLine, optionPoint] });
	const repos = [
		repo({ name: 'a', items: [openItem] }),
		repo({ name: 'b', error: 'down', items: [] })
	];

	test('no key selects nothing', () => {
		expect(findSelection(repos, null)).toBeNull();
	});

	test('a key naming no line, or one in a failed repo, selects nothing', () => {
		expect(findSelection(repos, 'a:42:9')).toBeNull();
		expect(findSelection(repos, 'a:43:card')).toBeNull();
		expect(findSelection(repos, 'b:1:1')).toBeNull();
	});

	test('a key naming an open yes/no line resolves its repo, item and line as a question', () => {
		expect(findSelection(repos, 'a:42:1')).toEqual({
			kind: 'question',
			repo: 'a',
			item: openItem,
			line: openLine
		});
	});

	test('[ABRD-82] a card key resolves the open option lines of its item as the card’s points', () => {
		const other = optionLine({ index: 3 });
		const grouped = item({ number: 42, lines: [optionPoint, other] });

		expect(findSelection([repo({ name: 'a', items: [grouped] })], 'a:42:card')).toEqual({
			kind: 'card',
			repo: 'a',
			item: grouped,
			points: [optionPoint, other]
		});
	});

	test('[ABRD-50] a card key selects nothing once its item has no open option line', () => {
		const ruled = item({
			number: 42,
			lines: [optionLine({ index: 2, ruling: 'A', ruled_on: '2026-10-01' }), openLine]
		});

		expect(findSelection([repo({ name: 'a', items: [ruled] })], 'a:42:card')).toBeNull();
	});

	test('an open option line is a point of its card, never selected on its own', () => {
		expect(findSelection(repos, 'a:42:2')).toBeNull();
	});

	test('a key naming an already-ruled line still resolves it, so Stage can show it read-only', () => {
		const ruledLine = optionLine({ index: 2, ruling: 'A', ruled_on: '2026-10-01' });
		const ruledItem = item({ number: 42, title: 'Share page', lines: [ruledLine] });
		const withRuled = [repo({ name: 'a', items: [ruledItem] })];

		expect(findSelection(withRuled, 'a:42:2')).toEqual({
			kind: 'decided',
			repo: 'a',
			item: ruledItem,
			line: ruledLine
		});
	});
});

describe('selectionHeading', () => {
	const members = item({ number: 42, lines: [] });

	test('[ABRD-83] a one-point card is headed by its question, a card of points by its name', () => {
		const single = optionLine({ index: 2, question: 'Keep the song open?' });
		const points = [
			optionLine({ index: 2, area: 'Song-Seite' }),
			optionLine({ index: 3, area: 'Song-Seite' })
		];

		expect(selectionHeading({ kind: 'card', repo: 'a', item: members, points: [single] })).toBe(
			'Keep the song open?'
		);
		expect(selectionHeading({ kind: 'card', repo: 'a', item: members, points })).toBe(
			'Song-Seite · 2 points'
		);
	});

	test('a line is headed by its question, else by its sentence', () => {
		const question = line({ question: 'Guests allowed?' });

		expect(selectionHeading({ kind: 'question', repo: 'a', item: members, line: question })).toBe(
			'Guests allowed?'
		);
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

	test('[ABRD-61] a card with its head comes after an open card and before a yes/no line', () => {
		const withHead = [
			repo({
				items: [
					item({ number: 1, lines: [line({ index: 1 })] }),
					item({ number: 2, lines: [optionLine({ index: 1, returned_on: '2026-10-27' })] }),
					item({ number: 3, lines: [optionLine({ index: 1 })] })
				]
			})
		];

		expect(nextOpenAfter(withHead, 'repo:3:card')).toBe('repo:2:card');
		expect(nextOpenAfter(withHead, 'repo:2:card')).toBe('repo:3:card');
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

		expect(nextOpenAfter(mixed, 'a:1:1')).toBe('b:2:card');
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

describe('stageAfterReturned', () => {
	const cards = (...members: ReturnType<typeof optionLine | typeof line>[]) => [
		repo({ items: members.map((member, number) => item({ number: number + 1, lines: [member] })) })
	];

	test('[ABRD-76] the first other open card comes next, skipping cards with their head', () => {
		const repos = cards(
			optionLine({ index: 1, returned_on: '2026-10-27' }),
			optionLine({ index: 1 }),
			optionLine({ index: 1 })
		);

		expect(stageAfterReturned(repos, 'repo:3:card')).toBe('repo:2:card');
	});

	test('[ABRD-76] with no other open card the stage stays on the card itself', () => {
		const repos = cards(
			optionLine({ index: 1, returned_on: '2026-10-27' }),
			optionLine({ index: 1, returned_on: '2026-10-27' }),
			line({ index: 1 })
		);

		expect(stageAfterReturned(repos, 'repo:2:card')).toBe('repo:2:card');
	});
});
