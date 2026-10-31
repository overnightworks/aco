import { describe, expect, test } from 'vitest';
import { item, line, optionLine, repo } from '../../test-support/board';
import {
	cardHeading,
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

test('first selection follows configured order, skipping unread repos and ruled-only groups', () => {
	const repos = [
		repo({ name: 'failed', error: 'Read failed', items: [] }),
		repo({
			name: 'first',
			items: [
				item({ number: 8, lines: [line({ ruling: 'yes' })] }),
				item({ number: 5, lines: [optionLine({ index: 3 })] }),
				item({ number: 2, lines: [optionLine({ index: 1 })] })
			]
		}),
		repo({ name: 'last', items: [item({ lines: [optionLine()] })] })
	];
	expect(firstOpenKey(repos)).toBe('first:5:card');
	expect(firstOpenKey([])).toBeNull();
	expect(firstOpenKey([repo({ items: [item({ lines: [line({ ruling: 'yes' })] })] })])).toBeNull();
});

describe('openList', () => {
	test('[ABRD-101] groups follow configured order, a failed repository without cards as a group with its sentence', () => {
		const { groups } = openList([
			repo({ name: 'zeta', items: [item({ number: 1, lines: [optionLine({ index: 1 })] })] }),
			repo({ name: 'broken', error: 'aco failed', items: [] }),
			repo({ name: 'alpha', items: [item({ number: 2, lines: [optionLine({ index: 1 })] })] })
		]);

		expect(groups.map((group) => group.repo)).toEqual(['zeta', 'broken', 'alpha']);
		expect(groups[1]).toEqual({ repo: 'broken', error: 'aco failed', readAt: null, rows: [] });
	});

	test('[ABRD-28] a row carries its key, state, label and the full question as its title', () => {
		const { groups } = openList([
			repo({
				name: 'a',
				items: [
					item({
						number: 7,
						lines: [optionLine({ index: 2, topic: 'Sprung', question: 'Keep the song open?' })]
					}),
					item({
						number: 8,
						lines: [optionLine({ index: 3, topic: 'Gäste', question: 'Guests allowed?' })]
					})
				]
			})
		]);

		expect(groups).toEqual([
			{
				repo: 'a',
				error: null,
				readAt: null,
				rows: [
					{ key: 'a:7:card', state: 'open', label: 'Sprung', title: 'Keep the song open?' },
					{ key: 'a:8:card', state: 'open', label: 'Gäste', title: 'Guests allowed?' }
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
							optionLine({ index: 4, area: 'Song-Seite' })
						]
					}),
					item({
						number: 8,
						lines: [optionLine({ index: 5, topic: 'Gäste', question: 'Guests allowed?' })]
					})
				]
			})
		]);

		const name = 'Song-Seite · 3 points';
		expect(groups).toEqual([
			{
				repo: 'a',
				error: null,
				readAt: null,
				rows: [
					{ key: 'a:7:card', state: 'open', label: name, title: name },
					{ key: 'a:8:card', state: 'open', label: 'Gäste', title: 'Guests allowed?' }
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

	test('[ABRD-61] a card with a returned line is a back row ranked after open', () => {
		const { groups } = openList([
			repo({
				name: 'a',
				items: [
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
			'a:2:card'
		]);
		expect(group?.rows[1]?.state).toBe('back');
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
		expect(group?.rows[1]?.state).toBe('back');
	});

	test('[ABRD-49] readable repositories with no open line are quiet, a ruled-only one included', () => {
		const { groups, quiet } = openList([
			repo({ name: 'open', items: [item({ lines: [optionLine()] })] }),
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

describe('openList with a failed repository', () => {
	test('[ABRD-101] a failed repository is one group with sentence, time and kept rows; one without cards a group with its sentence; a quiet one stays under Nothing open', () => {
		const readAt = new Date(2026, 9, 31, 9, 41);
		const { groups, quiet } = openList([
			{
				...repo({
					name: 'kept',
					error: 'down',
					items: [item({ number: 7, lines: [optionLine()] })]
				}),
				readAt
			},
			repo({ name: 'never', error: 'gh failed', items: [] }),
			repo({ name: 'a', items: [] })
		]);

		expect(
			groups.map(({ repo: name, error, readAt: at, rows }) => [name, error, at, rows.length])
		).toEqual([
			['kept', 'down', readAt, 1],
			['never', 'gh failed', null, 0]
		]);
		expect(quiet).toEqual(['a']);
	});
});

describe('decidedList', () => {
	function rowKeys(group: ReturnType<typeof decidedList>['groups'][number] | undefined): string[] {
		return group?.rows.map((row) => row.key) ?? [];
	}

	test('[ABRD-30] groups ruled lines per repository in configured order, a failed one as a group with its kept rows and a repository with nothing ruled absent', () => {
		const { groups, quiet } = decidedList([
			repo({
				name: 'first',
				items: [
					item({
						lines: [line({ ruling: 'yes', ruled_on: '2026-10-01' }), optionLine({ index: 2 })]
					})
				]
			}),
			repo({
				name: 'broken',
				error: 'down',
				items: [item({ lines: [optionLine({ ruling: 'A', ruled_on: '2026-10-01' })] })]
			}),
			repo({ name: 'untouched', items: [item({ lines: [optionLine()] })] }),
			repo({
				name: 'last',
				items: [item({ lines: [optionLine({ ruling: 'A', ruled_on: '2026-10-02' })] })]
			})
		]);

		expect(groups.map((group) => group.repo)).toEqual(['first', 'broken', 'last']);
		expect(groups[1]?.error).toBe('down');
		expect(rowKeys(groups[1])).toEqual(['broken:42:1']);
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
				items: [
					item({ number: 1, lines: [optionLine({ index: 2 })] }),
					item({ number: 2, lines: [optionLine({ index: 3, returned_on: '2026-10-27' })] })
				]
			})
		]);

		expect(groups).toEqual([]);
	});

	test.each(['first', 'last'] as const)(
		'[ABRD-31] a repository lists the newest date first, then item number and line index descending, from %s input',
		(position) => {
			const entries = [
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
							lines: [line({ index, ruling: 'later', ruled_on }), optionLine({ index: 10 })]
						})
					)
				})
			];
			const before = structuredClone(repos);

			expect(rowKeys(decidedList(repos).groups[0])).toEqual(['a:3:2', 'a:3:1', 'a:2:1', 'a:99:9']);
			expect(repos).toEqual(before);
		}
	);
});

describe('firstDecidedKey', () => {
	test('[ABRD-32] is the first row of the decided list', () => {
		const repos = [
			repo({ name: 'broken', error: 'down', items: [] }),
			repo({ name: 'open', items: [item({ lines: [optionLine()] })] }),
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
		expect(firstDecidedKey([repo({ error: 'down', items: [] })])).toBeNull();
		expect(firstDecidedKey([repo({ items: [item({ lines: [optionLine()] })] })])).toBeNull();
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

describe('cardHeading', () => {
	test('a distinct question becomes the heading', () => {
		const card = line({
			question: 'Guests allowed?',
			text: 'Guests may join the call.',
			ruling: 'yes',
			ruled_on: '2026-10-01'
		});

		expect(cardHeading(card)).toBe('Guests allowed?');
	});

	test('an option line is headed by its question', () => {
		const card = optionLine({ question: 'Keep the song open?' });

		expect(cardHeading(card)).toBe('Keep the song open?');
	});

	test('with no distinct question, the sentence itself is the heading', () => {
		const card = line({
			text: 'Guests may join the call.',
			ruling: 'yes',
			ruled_on: '2026-10-01'
		});

		expect(cardHeading(card)).toBe('Guests may join the call.');
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
	const optionPoint = optionLine({ index: 2 });
	const repos = [
		repo({ name: 'a', items: [item({ number: 42, title: 'Share page', lines: [optionPoint] })] }),
		repo({ name: 'b', error: 'down', items: [] })
	];

	test('no key selects nothing', () => {
		expect(findSelection(repos, null)).toBeNull();
	});

	test('a key naming no line, or one in a failed repo without cards, selects nothing', () => {
		expect(findSelection(repos, 'a:42:9')).toBeNull();
		expect(findSelection(repos, 'a:43:card')).toBeNull();
		expect(findSelection(repos, 'b:1:1')).toBeNull();
	});

	test('[ABRD-101] a card key resolves a card a failed repo kept', () => {
		const kept = item({ number: 7, lines: [optionPoint] });

		expect(
			findSelection([repo({ name: 'c', error: 'down', items: [kept] })], 'c:7:card')
		).toMatchObject({ kind: 'card', repo: 'c', item: kept });
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
			lines: [
				optionLine({ index: 2, ruling: 'A', ruled_on: '2026-10-01' }),
				line({ index: 1, ruling: 'no', ruled_on: '2026-10-01' })
			]
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

	test('a ruled line is headed by its question, else by its sentence', () => {
		const ruled = line({ question: 'Guests allowed?' });

		expect(selectionHeading({ kind: 'decided', repo: 'a', item: members, line: ruled })).toBe(
			'Guests allowed?'
		);
	});
});

describe('nextOpenAfter', () => {
	const cardRepos = [
		repo({
			items: [1, 2, 3].map((number) => item({ number, lines: [optionLine({ index: 1 })] }))
		})
	];

	test('[ABRD-50] the decided card is skipped, so from the last card the first one comes next', () => {
		expect(nextOpenAfter(cardRepos, 'repo:3:card')).toBe('repo:1:card');
	});

	test('[ABRD-61] a card with its head comes after an open card', () => {
		const withHead = [
			repo({
				items: [
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

	test('[ABRD-101] lands on the kept card of a failed repo when it is the next open one', () => {
		const withAKeptCard = [
			repo({ items: [item({ number: 1, lines: [optionLine()] })] }),
			repo({ name: 'broken', error: 'down', items: [item({ number: 9, lines: [optionLine()] })] })
		];

		expect(nextOpenAfter(withAKeptCard, 'repo:1:card')).toBe('broken:9:card');
	});

	test('skips a line that was already ruled when picking the next one', () => {
		const withARuledMiddle = [
			repo({
				items: [
					item({ number: 1, lines: [optionLine({ index: 1 })] }),
					item({ number: 2, lines: [line({ index: 1, ruling: 'yes', ruled_on: '2026-10-01' })] }),
					item({ number: 3, lines: [optionLine({ index: 1 })] })
				]
			})
		];

		expect(nextOpenAfter(withARuledMiddle, 'repo:1:card')).toBe('repo:3:card');
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
							line({ index: 3, ruling: 'yes', ruled_on: '2026-10-01' })
						]
					}),
					item({ number: 2, lines: [optionLine({ index: 1 })] })
				]
			})
		];

		expect(tabCounts(repos)).toEqual({ open: 2, decided: 1 });
	});

	test('[ABRD-51] a failed repository without cards adds to neither count', () => {
		const repos = [repo({ name: 'broken', error: 'down', items: [] })];

		expect(tabCounts(repos)).toEqual({ open: 0, decided: 0 });
	});

	test('[ABRD-101] a failed repository counts the cards it kept', () => {
		const repos = [
			repo({ name: 'broken', error: 'down', items: [item({ number: 9, lines: [optionLine()] })] })
		];

		expect(tabCounts(repos)).toEqual({ open: 1, decided: 0 });
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
			line({ index: 1, ruling: 'yes', ruled_on: '2026-10-01' })
		);

		expect(stageAfterReturned(repos, 'repo:2:card')).toBe('repo:2:card');
	});
});
