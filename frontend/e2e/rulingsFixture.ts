/**
 * Builds and writes the fake `aco`'s own `rulings.json`
 * (`tests/aco_board/aco_board_fixtures.py`'s `_FAKE_ACO` reads this file
 * directly), the wire shape `aco rulings --json` answers with
 * (`specs/rulings.spec.md` RUL-10). A spec rewrites it mid-test to simulate
 * an agent editing a line while the operator is deciding it.
 */

import { writeFileSync } from 'node:fs';
import path from 'node:path';

type RulingOutcome = 'yes' | 'no' | 'later';

export interface RulingLine {
	index: number;
	text: string;
	question: string | null;
	example: string | null;
	picture: string | null;
	default: RulingOutcome | null;
	ruling: RulingOutcome | null;
	ruled_on: string | null;
}

export interface RulingOption {
	letter: string;
	name: string;
	effect: string;
	picture?: string;
	same_as_today?: true;
	caption?: string;
	notice: string;
	cost: string;
	undo: 'reversible' | 'final';
	undo_how: string;
	contract: string;
}

/** An option line as `aco rulings --json` writes it (`specs/rulings.spec.md`
 * RUL-13/14); `default` and `stored_card_hash` are always null here, which
 * the board's adapter never reads. */
export interface OptionRulingLine {
	index: number;
	form: 'options';
	text: string;
	question: string;
	problem: string;
	picture: string;
	caption: string;
	decision_kind: string;
	area: string;
	topic: string;
	recommended: string;
	reason: string;
	options: RulingOption[];
	ruling: string | null;
	ruled_on: string | null;
	card_hash: string;
	stored_card_hash: string | null;
	default: null;
}

export interface RulingRow {
	number: number;
	title: string;
	lines: (RulingLine | OptionRulingLine)[];
}

export function line(index: number, text: string, overrides: Partial<RulingLine> = {}): RulingLine {
	return {
		index,
		text,
		question: null,
		example: null,
		picture: null,
		default: null,
		ruling: null,
		ruled_on: null,
		...overrides
	};
}

export function optionLine(
	index: number,
	text: string,
	overrides: Partial<OptionRulingLine> = {}
): OptionRulingLine {
	return {
		index,
		form: 'options',
		text,
		question: 'Frage?',
		problem: 'Ein Problem.',
		picture: '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="60"/>',
		caption: 'Heute',
		decision_kind: 'product',
		area: 'Bereich',
		topic: 'Thema',
		recommended: 'A',
		reason: 'Ein Grund.',
		options: [],
		ruling: null,
		ruled_on: null,
		card_hash: `card-hash-${index}`,
		stored_card_hash: null,
		default: null,
		...overrides
	};
}

export function row(
	number: number,
	title: string,
	...lines: (RulingLine | OptionRulingLine)[]
): RulingRow {
	return { number, title, lines };
}

export function writeRulings(repoDirectory: string, rows: RulingRow[]): void {
	writeFileSync(path.join(repoDirectory, 'rulings.json'), JSON.stringify(rows));
}
