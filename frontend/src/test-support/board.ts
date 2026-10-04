/**
 * Scenario builders for the board's wire types, shared by model, state, and
 * component tests. Not production code: excluded from the coverage gate in
 * `vite.config.ts`.
 */

import type { BoardItem, ExpectationLine, RepoReading } from '../types';

export function line(overrides: Partial<ExpectationLine> = {}): ExpectationLine {
	return {
		index: 1,
		text: 'Guests?',
		question: null,
		example: null,
		picture: null,
		default: null,
		ruling: null,
		ruled_on: null,
		fingerprint: 'fingerprint-1',
		...overrides
	};
}

export function item(overrides: Partial<BoardItem> = {}): BoardItem {
	return {
		number: 42,
		title: 'Share page',
		lines: [line()],
		...overrides
	};
}

export function repo(overrides: Partial<RepoReading> = {}): RepoReading {
	return {
		name: 'repo',
		error: null,
		items: [item()],
		...overrides
	};
}
