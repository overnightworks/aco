/**
 * Scenario builders for the board's wire types, shared by model, state, and
 * component tests. Not production code: excluded from the coverage gate in
 * `vite.config.ts`.
 */

import type {
	BoardItem,
	CardOption,
	OptionLine,
	RepoReading,
	RuledOptionLine,
	YesNoLine
} from '../types';

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
		asked_on: '2026-10-20',
		card_hash: 'sha256:card-now',
		stored_card_hash: null,
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
		returned_on: null,
		returned_note: null,
		fingerprint: 'fingerprint-option',
		...overrides
	};
}

/** An option line ruled on a date by a way, as aco always stores one (BODY-86). */
export function ruledOptionLine(overrides: Partial<RuledOptionLine> = {}): RuledOptionLine {
	const shown = optionLine(overrides);
	return {
		...shown,
		ruling: overrides.ruling ?? 'A',
		ruled_on: overrides.ruled_on ?? '2026-10-25',
		via: overrides.via ?? 'board',
		stored_card_hash: overrides.stored_card_hash ?? shown.card_hash
	};
}

/** A ruled yes/no line, dated as aco always stores one (BODY-32; ABRD-34). */
export function line(overrides: Partial<YesNoLine> = {}): YesNoLine {
	return {
		index: 1,
		text: 'Guests?',
		ruling: 'yes',
		ruled_on: '2026-10-01',
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
