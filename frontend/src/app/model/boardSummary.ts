/**
 * Pure read-only projections over a `BoardResponse`, shared by `App.svelte`,
 * `TrackList.svelte` and `Stage.svelte` so none of them carries decision
 * logic of its own (SonarCloud does not analyse `.svelte`: this
 * is where the behaviour lives instead).
 */

import type {
	BoardItem,
	ExpectationLine,
	OptionLine,
	Outcome,
	RepoReading,
	RuledLine
} from '../../types';
import { cardName, cardTitle, openPoints } from './card';
import { cardKey, lineKey } from './decision';
import { hasHead, isOptionLine } from './optionCard';

export const OPEN_TAB_LABEL = 'Open';
export const DECIDED_TAB_LABEL = 'Decided';
export const LIST_REGION_LABEL = 'Decisions';
export const QUIET_PREFIX = 'Nothing open: ';
export const EMPTY_LIST_TITLE = 'All decided';
export const EMPTY_LIST_TEXT = 'No project is waiting for you.';
export const EMPTY_DECIDED_TITLE = 'Nothing decided yet';
export const EMPTY_DECIDED_TEXT = 'Your decisions show here with their answer and date.';
export const NO_SELECTION_MESSAGE = 'Keine Frage ausgewählt.';

const OUTCOME_LABEL: Record<Outcome, string> = {
	yes: 'Ja',
	no: 'Nein',
	later: 'Später'
};

export function outcomeLabel(outcome: Outcome): string {
	return OUTCOME_LABEL[outcome];
}

/** Whether `line` carries a ruling; a yes/no line always does. */
function isRuled(line: ExpectationLine): line is RuledLine {
	return line.ruling !== null;
}

/** The stage's heading: the tapped question, or the line's own sentence when
 * the source names no distinct question. */
export function cardHeading(line: ExpectationLine): string {
	return line.question ?? line.text;
}

/** An SVG picture as a data URI: a browser never runs script inside an
 * image, so this is the only way a line's `picture` field reaches the DOM. */
export function pictureDataUri(svg: string): string {
	const bytes = new TextEncoder().encode(svg);
	const binary = Array.from(bytes, (byte) => String.fromCodePoint(byte)).join('');
	return `data:image/svg+xml;base64,${btoa(binary)}`;
}

interface Located {
	repo: string;
	item: BoardItem;
}

/** An item's open option lines, shown as one card (ABRD-82). */
interface CardSelection extends Located {
	kind: 'card';
	points: OptionLine[];
}

/** A ruled line, shown read-only. */
interface DecidedSelection extends Located {
	kind: 'decided';
	line: RuledLine;
}

export type Selection = CardSelection | DecidedSelection;

/** How a row reads at a glance: an option card is `open`, or `back` once the
 * operator sent one of its lines to its head, or `saving` while its answer is
 * being saved; a ruled line is `done`. */
export type RowState = OpenRowState | 'saving' | 'done';
type OpenRowState = 'open' | 'back';

/** The two tabs that list rows. */
export type ListView = 'open' | 'decided';

/** How a waiting decision's strip reads: `done` for a ruling, `back` for a card
 * on its way to its head. */
export type StripState = Extract<RowState, 'done' | 'back'>;

export const STATE_LABEL: Record<RowState, string> = {
	open: 'Open',
	back: 'With head',
	saving: 'Saving',
	done: 'Decided'
};

/** Lower comes first; `nextOpenAfter` and the open list both order by it. */
const ROW_RANK: Record<OpenRowState, number> = { open: 0, back: 1 };

interface ListRow<State extends RowState = RowState> {
	key: string;
	state: State;
	label: string;
	/** The full question, for the row's tooltip. */
	title: string;
}

type ListGroup<Row extends ListRow> =
	{ repo: string; error: string } | { repo: string; rows: Row[] };

export interface RowList<Row extends ListRow = ListRow> {
	groups: ListGroup<Row>[];
	/** Readable repositories with no row; only the open list names them. */
	quiet: string[];
}

function decidedRow(repo: string, itemNumber: number, line: ExpectationLine): ListRow<'done'> {
	return {
		key: lineKey(repo, itemNumber, line),
		state: 'done',
		label: isOptionLine(line) ? line.topic : cardHeading(line),
		title: cardHeading(line)
	};
}

function cardRow(repo: string, itemNumber: number, points: OptionLine[]): ListRow<OpenRowState> {
	return {
		key: cardKey(repo, itemNumber),
		state: hasHead(points) ? 'back' : 'open',
		label: cardName(points),
		title: cardTitle(points)
	};
}

/** An item's card row, if it has open option lines. */
function itemRows(repo: string, item: BoardItem): ListRow<OpenRowState>[] {
	const points = openPoints(item);
	return points.length > 0 ? [cardRow(repo, item.number, points)] : [];
}

function openRows(reading: RepoReading): ListRow<OpenRowState>[] {
	return reading.items
		.flatMap((item) => itemRows(reading.name, item))
		.sort((left, right) => ROW_RANK[left.state] - ROW_RANK[right.state]);
}

/** Newest date first, then item number and line index descending. */
function decidedRows(reading: RepoReading): ListRow<'done'>[] {
	return reading.items
		.flatMap((item) => item.lines.filter(isRuled).map((line) => ({ item, line })))
		.sort(
			(left, right) =>
				right.line.ruled_on.localeCompare(left.line.ruled_on) ||
				right.item.number - left.item.number ||
				right.line.index - left.line.index
		)
		.map(({ item, line }) => decidedRow(reading.name, item.number, line));
}

/** One group per repository that failed or has a row, in configured order; a
 * readable repository without one is quiet. */
function groupedRows<Row extends ListRow>(
	repos: RepoReading[],
	rowsFor: (reading: RepoReading) => Row[]
): RowList<Row> {
	const groups: ListGroup<Row>[] = [];
	const quiet: string[] = [];
	for (const reading of repos) {
		if (reading.error !== null) {
			groups.push({ repo: reading.name, error: reading.error });
			continue;
		}
		const rows = rowsFor(reading);
		if (rows.length === 0) {
			quiet.push(reading.name);
		} else {
			groups.push({ repo: reading.name, rows });
		}
	}
	return { groups, quiet };
}

/** The open list: one group per repository that failed or has an open card,
 * its cards in aco's order, those with their head after the others. */
export function openList(repos: RepoReading[]): RowList<ListRow<OpenRowState>> {
	return groupedRows(repos, openRows);
}

/** The Decided list: one group per repository that failed or has a ruled
 * line. The picture names quiet projects only on Open, so `quiet` stays
 * empty. */
export function decidedList(repos: RepoReading[]): RowList<ListRow<'done'>> {
	return { groups: groupedRows(repos, decidedRows).groups, quiet: [] };
}

function rowsOf<Row extends ListRow>(list: RowList<Row>): Row[] {
	return list.groups.flatMap((group) => ('rows' in group ? group.rows : []));
}

function listedRows(repos: RepoReading[]): ListRow<OpenRowState>[] {
	return rowsOf(openList(repos));
}

export function firstOpenKey(repos: RepoReading[]): string | null {
	return listedRows(repos)[0]?.key ?? null;
}

export function firstDecidedKey(repos: RepoReading[]): string | null {
	return rowsOf(decidedList(repos))[0]?.key ?? null;
}

function lineSelection(repo: string, item: BoardItem, line: ExpectationLine): Selection | null {
	return isRuled(line) ? { kind: 'decided', repo, item, line } : null;
}

/** What the stage shows for `key`: a card key names the open option lines of
 * its item, a line key a ruled line (shown read-only).
 * An open option line is a point of its card and never selected on its own.
 * A key whose data has disappeared reads the same as no selection. */
export function findSelection(repos: RepoReading[], key: string | null): Selection | null {
	if (key === null) {
		return null;
	}
	for (const reading of repos) {
		for (const item of reading.error === null ? reading.items : []) {
			const points = openPoints(item);
			if (points.length > 0 && cardKey(reading.name, item.number) === key) {
				return { kind: 'card', repo: reading.name, item, points };
			}
			const found = item.lines.find((line) => lineKey(reading.name, item.number, line) === key);
			if (found !== undefined) {
				return lineSelection(reading.name, item, found);
			}
		}
	}
	return null;
}

/** The stage's heading: a card's title, else the ruled line's question. */
export function selectionHeading(selection: Selection): string {
	return selection.kind === 'card' ? cardTitle(selection.points) : cardHeading(selection.line);
}

/** The card the stage moves to once `key` is decided: of the other open
 * rows, the first with the best rank in list order, so an option card comes
 * before one with its head; `null` once nothing else is open. */
export function nextOpenAfter(repos: RepoReading[], key: string): string | null {
	const others = listedRows(repos).filter((row) => row.key !== key);
	const bestRank = Math.min(...others.map((row) => ROW_RANK[row.state]));
	return others.find((row) => ROW_RANK[row.state] === bestRank)?.key ?? null;
}

/** Where the stage goes once `key` is sent back to its head: the first other
 * open row, else the card itself, which now reads `with head`. */
export function stageAfterReturned(repos: RepoReading[], key: string): string {
	return listedRows(repos).find((row) => row.key !== key && row.state === 'open')?.key ?? key;
}

/** What the header's two tabs count: the rows the open list shows and the
 * ruled lines the Decided view lists. */
export function tabCounts(repos: RepoReading[]): { open: number; decided: number } {
	return { open: listedRows(repos).length, decided: rowsOf(decidedList(repos)).length };
}
