/**
 * An item's open option lines as one card (`specs/serve.spec.md` ABRD-82 to
 * ABRD-92): the points, the card's name, the picks a post holds and the
 * confirms before them. Pure, so
 * `DecisionStore` and the components carry none of it.
 */

import type { BoardItem, CardOption, OptionLine } from '../../types';
import {
	asksToConfirm,
	confirmTitle,
	confirmVerb,
	consequenceText,
	decidedText,
	GROUP_LABEL,
	isOptionLine,
	joinedAreas,
	pointPrefix
} from './optionCard';

/** A point and the option picked for it, the point as shown when picked. */
export interface Pick {
	shown: OptionLine;
	option: CardOption;
}

/** What a modal asks before a pick or Accept all that cannot be taken back. */
export interface Confirmation {
	title: string;
	verb: string;
	lines: string[];
}

/** The points of an item's card: its open option lines, in aco's order. */
export function openPoints(item: BoardItem): OptionLine[] {
	return item.lines.filter(
		(line): line is OptionLine => isOptionLine(line) && line.ruling === null
	);
}

/** A one-point card is named by its topic, a card of points by its areas and count. */
export function cardName(points: readonly OptionLine[]): string {
	return points.length > 1
		? `${joinedAreas(points)} · ${points.length} ${GROUP_LABEL.count}`
		: points.map((point) => point.topic).join('');
}

/** A one-point card is titled by its question, a card of points by its name. */
export function cardTitle(points: readonly OptionLine[]): string {
	return points.length > 1 ? cardName(points) : points.map((point) => point.question).join('');
}

/** The place of `point` among the card's points, counted from one. */
export function pointNumber(points: readonly OptionLine[], point: OptionLine): number {
	return points.findIndex((candidate) => candidate.index === point.index) + 1;
}

/** The letter of the pick waiting for `point`, or none while it waits for none. */
export function pickedLetter(
	held: readonly Pick[],
	point: OptionLine
): CardOption['letter'] | null {
	return held.find((pick) => pick.shown.index === point.index)?.option.letter ?? null;
}

/** Accept all's picks: each point's recommended option, as shown; a point whose
 * recommendation names no option has none and stays open. */
export function recommendedPicks(points: readonly OptionLine[]): Pick[] {
	return points.flatMap((shown) =>
		shown.options
			.filter((option) => option.letter === shown.recommended)
			.map((option) => ({ shown, option }))
	);
}

function consequenceLine(points: readonly OptionLine[], pick: Pick): string {
	const consequence = consequenceText(pick.option);
	return points.length === 1
		? consequence
		: `${pointPrefix(pointNumber(points, pick.shown))}${consequence}`;
}

/** The confirm before a pick; none unless the option cannot be taken back. */
export function confirmationFor(points: readonly OptionLine[], pick: Pick): Confirmation | null {
	return asksToConfirm(pick.option)
		? {
				title: confirmTitle(pick.option),
				verb: confirmVerb(pick.option),
				lines: [consequenceLine(points, pick)]
			}
		: null;
}

/** The confirm before Accept all, listing each of the `available` points (the
 * card's points not waiting) whose recommended option cannot be taken back,
 * numbered among all the card's `points`; none when there is none. */
export function acceptAllConfirmation(
	points: readonly OptionLine[],
	available: readonly OptionLine[]
): Confirmation | null {
	const lines = recommendedPicks(available)
		.filter((pick) => asksToConfirm(pick.option))
		.map((pick) => consequenceLine(points, pick));
	return lines.length === 0
		? null
		: { title: GROUP_LABEL.acceptAllTitle, verb: GROUP_LABEL.acceptAll, lines };
}

/** The strip text of the picks waiting out the undo window. */
export function pickedText(points: readonly OptionLine[], picks: readonly Pick[]): string {
	const chosen =
		points.length > 1
			? picks.map((pick) => `${pointNumber(points, pick.shown)}${pick.option.letter}`).join(' ')
			: picks.map((pick) => decidedText(pick.option)).join('');
	return `${chosen} · ${cardName(points)}`;
}
