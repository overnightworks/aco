/**
 * Pure projections of a ruled line as the decided card (`specs/serve.spec.md`
 * ABRD-37/54): the one owner of the words that say what was decided, by which
 * way and when. A way that aco did not store reads `not recorded`; it is never
 * guessed. Callers pass only ruled lines, and a ruling always names an option
 * of its line (ABRD-07), so none of these projections checks for either.
 */

import type { BoardItem, CardOption, ExpectationLine, Outcome, RulingVia } from '../../types';
import { outcomeLabel } from './boardSummary';
import {
	cardMeta,
	chosenOption,
	contractTexts,
	decidedText,
	type FrameMeta,
	isOptionLine
} from './optionCard';

export const HOW_LABEL: Record<RulingVia, string> = {
	board: 'Board',
	chat: 'From chat',
	default: 'Recommendation kept – no answer'
};

export const NOT_RECORDED = 'not recorded';

const HOW_DATE_SEPARATOR = ' · ';

/** `2026-10-25` as `25.10.2026`, the picture's date. */
export function displayDate(isoDate: string): string {
	const [year, month, day] = isoDate.split('-');
	return `${day}.${month}.${year}`;
}

/** The way a line was decided, then its date when known. Only an option line
 * can carry a `via`; a yes/no line never does. */
export function howText(line: ExpectationLine): string {
	const way = isOptionLine(line) && line.via !== null ? HOW_LABEL[line.via] : NOT_RECORDED;
	return line.ruled_on === null ? way : `${way}${HOW_DATE_SEPARATOR}${displayDate(line.ruled_on)}`;
}

/** The answer the line was ruled with. */
export function decidedAnswer(line: ExpectationLine): string {
	return isOptionLine(line)
		? decidedText(chosenOption(line) as CardOption)
		: outcomeLabel(line.ruling as Outcome);
}

/** The sentences that bind the ruling. */
export function bindingSentences(line: ExpectationLine): string[] {
	return isOptionLine(line) ? contractTexts(line, chosenOption(line) as CardOption) : [line.text];
}

/** The meta line of a decided card: an option line keeps its area and kind; a
 * yes/no line has neither, so the item it belongs to stands where the area
 * would. Neither shows the undo token of an answer already given. */
export function decidedMeta(repo: string, item: BoardItem, line: ExpectationLine): FrameMeta {
	if (!isOptionLine(line)) {
		return { where: `${repo} › ${item.title}` };
	}
	const { where, kind } = cardMeta(repo, line);
	return { where, kind };
}
