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

export interface RulingRow {
	number: number;
	title: string;
	lines: RulingLine[];
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

export function row(number: number, title: string, ...lines: RulingLine[]): RulingRow {
	return { number, title, lines };
}

export function writeRulings(repoDirectory: string, rows: RulingRow[]): void {
	writeFileSync(path.join(repoDirectory, 'rulings.json'), JSON.stringify(rows));
}
