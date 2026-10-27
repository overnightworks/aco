/**
 * Scenario builders for the board's wire types, shared by model, state, and
 * component tests. Not production code: excluded from the coverage gate in
 * `vite.config.ts`.
 */

import type { BoardItem, CardOption, OptionLine, RepoReading, YesNoLine } from '../types';

export const PICTURE = '<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4"/>';

export function cardOption(overrides: Partial<CardOption> = {}): CardOption {
	return {
		letter: 'A',
		name: 'Keep the song open',
		effect: 'The app jumps itself.',
		picture: PICTURE,
		notice: 'You stay in your song.',
		cost: 'More code.',
		undo: 'reversible',
		undo_how: 'Any time.',
		contract: 'The song stays open.',
		...overrides
	} as CardOption;
}

/** An option that leaves the TODAY picture as it is: it carries no
 * `picture` (`cardOption()` always does). */
export function sameAsTodayOption(overrides: Partial<CardOption> = {}): CardOption {
	const fields: Record<string, unknown> = { ...cardOption(), same_as_today: true, ...overrides };
	delete fields.picture;
	return fields as unknown as CardOption;
}

export function optionLine(overrides: Partial<OptionLine> = {}): OptionLine {
	return {
		index: 1,
		form: 'options',
		text: 'The song stays open on the jump.',
		question: 'Keep the song open?',
		problem: 'The jump closes your song.',
		picture: PICTURE,
		caption: 'Today the song is lost.',
		decision_kind: 'product',
		area: 'Song page',
		topic: 'Jump',
		recommended: 'A',
		reason: 'Ends the loss.',
		options: [
			cardOption(),
			cardOption({
				letter: 'B',
				name: 'As today',
				effect: 'The browser jumps.',
				contract: 'The browser keeps jumping.'
			})
		],
		ruling: null,
		ruled_on: null,
		via: null,
		other: null,
		fingerprint: 'fingerprint-option',
		...overrides
	};
}

export function line(overrides: Partial<YesNoLine> = {}): YesNoLine {
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
