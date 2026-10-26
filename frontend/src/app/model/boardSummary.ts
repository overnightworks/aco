/**
 * Pure read-only projections over a `BoardResponse`, shared by `App.svelte`,
 * `TrackList.svelte` and `Stage.svelte` so none of them carries decision
 * logic of its own (SonarCloud does not analyse `.svelte`: this
 * is where the behaviour lives instead).
 */

import type { BoardItem, ExpectationLine, Outcome, RepoReading } from '../../types';
import { lineKey } from './decision';
import { isOptionLine } from './optionCard';

export const OUTCOMES: readonly Outcome[] = ['yes', 'no', 'later'];
export const LIST_LABEL = 'Liste';
export const OPEN_TAB_LABEL = 'Open';
export const DECIDED_TAB_LABEL = 'Decided';
export const LIST_REGION_LABEL = 'Decisions';
export const QUIET_PREFIX = 'Nothing open: ';
export const EMPTY_LIST_TITLE = 'All decided';
export const EMPTY_LIST_TEXT = 'No project is waiting for you.';
export const EMPTY_HISTORY_MESSAGE = 'Noch keine Entscheidungen in den offenen Board-Items.';
export const UNKNOWN_DATE_LABEL = 'Datum fehlt';
export const NO_SELECTION_MESSAGE = 'Keine Frage ausgewählt.';

const OUTCOME_LABEL: Record<Outcome, string> = {
	yes: 'Ja',
	no: 'Nein',
	later: 'Später'
};

export function outcomeLabel(outcome: Outcome): string {
	return OUTCOME_LABEL[outcome];
}

export function ruledOutcomeText(ruling: Outcome, ruledOn: string | null): string {
	return `${outcomeLabel(ruling)} · ${ruledOn ?? ''}`;
}

/** The stage's heading: the tapped question, or the line's own sentence when
 * the source names no distinct question. */
export function cardHeading(line: ExpectationLine): string {
	return line.question ?? line.text;
}

/** The stage's own sentence, shown only when a distinct question already
 * carries the heading -- never duplicated when the sentence *is* the
 * heading. */
export function cardSentence(line: ExpectationLine): string | null {
	return line.question !== null ? line.text : null;
}

/** An SVG picture as a data URI: a browser never runs script inside an
 * image, so this is the only way a line's `picture` field reaches the DOM. */
export function pictureDataUri(svg: string): string {
	const bytes = new TextEncoder().encode(svg);
	const binary = Array.from(bytes, (byte) => String.fromCodePoint(byte)).join('');
	return `data:image/svg+xml;base64,${btoa(binary)}`;
}

export interface SelectedLine {
	repo: string;
	item: BoardItem;
	line: ExpectationLine;
}

/** How a row reads at a glance: an option line is `open`; a yes/no line is
 * `todo` because its head still has to rewrite it as an option card. */
export type RowState = 'open' | 'todo';

export const STATE_LABEL: Record<RowState, string> = {
	open: 'Open',
	todo: 'Not ready · head to fill'
};

/** Lower comes first; `nextOpenAfter` and the list both order by it. */
const ROW_RANK: Record<RowState, number> = { open: 0, todo: 1 };

interface ListRow {
	key: string;
	state: RowState;
	label: string;
	/** The full question, for the row's tooltip. */
	title: string;
}

type ListGroup = { repo: string; error: string } | { repo: string; rows: ListRow[] };

export interface OpenList {
	groups: ListGroup[];
	/** Readable repositories with no open line. */
	quiet: string[];
}

function listRow(repo: string, itemNumber: number, line: ExpectationLine): ListRow {
	return {
		key: lineKey(repo, itemNumber, line),
		state: isOptionLine(line) ? 'open' : 'todo',
		label: isOptionLine(line) ? line.topic : cardHeading(line),
		title: cardHeading(line)
	};
}

function openRows(reading: RepoReading): ListRow[] {
	return reading.items
		.flatMap((item) =>
			item.lines
				.filter((line) => line.ruling === null)
				.map((line) => listRow(reading.name, item.number, line))
		)
		.sort((left, right) => ROW_RANK[left.state] - ROW_RANK[right.state]);
}

/** The open list: one group per repository that failed or has an open line,
 * its option rows before its yes/no rows, each in aco's order. */
export function openList(repos: RepoReading[]): OpenList {
	const groups: ListGroup[] = [];
	const quiet: string[] = [];
	for (const reading of repos) {
		if (reading.error !== null) {
			groups.push({ repo: reading.name, error: reading.error });
			continue;
		}
		const rows = openRows(reading);
		if (rows.length === 0) {
			quiet.push(reading.name);
		} else {
			groups.push({ repo: reading.name, rows });
		}
	}
	return { groups, quiet };
}

function listedRows(repos: RepoReading[]): ListRow[] {
	return openList(repos).groups.flatMap((group) => ('rows' in group ? group.rows : []));
}

export function firstOpenKey(repos: RepoReading[]): string | null {
	return listedRows(repos)[0]?.key ?? null;
}

export function historyLines(repos: RepoReading[]): SelectedLine[] {
	return repos
		.filter((repo) => repo.error === null)
		.flatMap((repo) =>
			repo.items.flatMap((item) =>
				item.lines
					.filter((line) => line.ruling !== null)
					.map((line) => ({ repo: repo.name, item, line }))
			)
		)
		.sort(
			(left, right) =>
				(right.line.ruled_on ?? '').localeCompare(left.line.ruled_on ?? '') ||
				right.item.number - left.item.number ||
				right.line.index - left.line.index
		);
}

/** The one line `key` (`decision.ts`'s own) names, matched regardless of its
 * ruling -- a ruled line still resolves, so `Stage.svelte` can render it
 * read-only -- or `null` once no line in `repos` carries that key at all: a
 * key for a line that has disappeared from the data reads the same as no
 * selection, rather than showing data that no longer exists. */
export function findSelectedLine(repos: RepoReading[], key: string | null): SelectedLine | null {
	if (key === null) {
		return null;
	}
	for (const repoReading of repos) {
		if (repoReading.error !== null) {
			continue;
		}
		for (const item of repoReading.items) {
			for (const line of item.lines) {
				if (lineKey(repoReading.name, item.number, line) === key) {
					return { repo: repoReading.name, item, line };
				}
			}
		}
	}
	return null;
}

/** The line the stage moves to once `key` is decided: of the other open
 * rows, the first with the best rank in list order, so an option card comes
 * before a yes/no line the head must still fill; `null` once nothing else is
 * open. */
export function nextOpenAfter(repos: RepoReading[], key: string): string | null {
	const others = listedRows(repos).filter((row) => row.key !== key);
	const bestRank = Math.min(...others.map((row) => ROW_RANK[row.state]));
	return others.find((row) => ROW_RANK[row.state] === bestRank)?.key ?? null;
}

/** What the header's two tabs count: the rows the open list shows and the
 * ruled lines the Decided view lists. */
export function tabCounts(repos: RepoReading[]): { open: number; decided: number } {
	return { open: listedRows(repos).length, decided: historyLines(repos).length };
}
