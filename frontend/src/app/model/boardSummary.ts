/**
 * Pure read-only projections over a `BoardResponse`, shared by `App.svelte`,
 * `TrackList.svelte` and `Stage.svelte` so none of them carries decision
 * logic of its own (SonarCloud does not analyse `.svelte`: this
 * is where the behaviour lives instead).
 */

import type { BoardItem, ExpectationLine, Outcome, RepoReading } from '../../types';
import { lineKey } from './decision';
import { isOptionLine, optionStatusText } from './optionCard';

export const OUTCOMES: readonly Outcome[] = ['yes', 'no', 'later'];
export const LIST_LABEL = 'Liste';
export const DECIDE_LABEL = 'Entscheiden';
export const HISTORY_LABEL = 'Verlauf';
export const EMPTY_OPEN_MESSAGE =
	'Nichts offen. Neue Fragen erscheinen hier nach Neuladen, sobald ein Agent eine stellt.';
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

export function totalLineCount(repos: RepoReading[]): number {
	return repos.reduce(
		(sum, repo) => sum + repo.items.reduce((itemSum, item) => itemSum + item.lines.length, 0),
		0
	);
}

export function isBoardEmpty(repos: RepoReading[]): boolean {
	return totalLineCount(repos) === 0;
}

export function lineStatusText(line: ExpectationLine): string {
	if (isOptionLine(line)) {
		return optionStatusText(line);
	}
	if (line.ruling !== null) {
		return `${outcomeLabel(line.ruling)} · ${line.ruled_on ?? ''}`;
	}
	return line.default !== null ? `Empfohlen: ${outcomeLabel(line.default)}` : 'Offen';
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

export function openRepos(repos: RepoReading[]): RepoReading[] {
	return repos.map((repo) => ({
		...repo,
		items: repo.items
			.map((item) => ({
				...item,
				lines: item.lines.filter((line) => line.ruling === null)
			}))
			.filter((item) => item.lines.length > 0)
	}));
}

export function firstOpenKey(repos: RepoReading[]): string | null {
	for (const repo of openRepos(repos)) {
		if (repo.error === null) {
			const item = repo.items[0];
			if (item) return lineKey(repo.name, item.number, item.lines[0] as ExpectationLine);
		}
	}
	return null;
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

/** The next still-open line after `key`, in the same board order the list
 * shows, wrapping to the first open line when `key` was the last one, or
 * `null` once nothing is open any more. */
export function nextOpenAfter(repos: RepoReading[], key: string): string | null {
	const order: string[] = [];
	const openKeys = new Set<string>();
	for (const repoReading of repos) {
		if (repoReading.error !== null) {
			continue;
		}
		for (const item of repoReading.items) {
			for (const line of item.lines) {
				const candidateKey = lineKey(repoReading.name, item.number, line);
				order.push(candidateKey);
				if (line.ruling === null) {
					openKeys.add(candidateKey);
				}
			}
		}
	}
	const open = order.filter((candidateKey) => openKeys.has(candidateKey) && candidateKey !== key);
	const position = order.indexOf(key);
	return open.find((candidateKey) => order.indexOf(candidateKey) > position) ?? open[0] ?? null;
}
