/**
 * Pure read-only projections over a `BoardResponse`, shared by `App.svelte`,
 * `TrackList.svelte` and `Stage.svelte` so none of them carries decision
 * logic of its own (SonarCloud does not analyse `.svelte`, issue #368: this
 * is where the behaviour lives instead).
 */

import type { BoardItem, ExpectationLine, Outcome, RepoReading } from '../../types';
import { lineKey } from './decision';

export const OUTCOMES: readonly Outcome[] = ['yes', 'no', 'later'];

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
	if (line.ruling !== null) {
		return `${outcomeLabel(line.ruling)} · ${line.ruled_on ?? ''}`;
	}
	return line.default !== null ? `Empfohlen: ${outcomeLabel(line.default)}` : 'Offen';
}

/** The stage's heading: the tapped question, or the line's own sentence when
 * the source names no distinct question (mirrors `aco_board.page._card`). */
export function cardHeading(line: ExpectationLine): string {
	return line.question ?? line.text;
}

/** The stage's own sentence, shown only when a distinct question already
 * carries the heading -- never duplicated when the sentence *is* the
 * heading (mirrors `aco_board.page._card`). */
export function cardSentence(line: ExpectationLine): string | null {
	return line.question !== null ? line.text : null;
}

/** An SVG picture as a data URI, the same embedding `aco_board.page._picture`
 * uses: a browser never runs script inside an image, so this is the only way
 * a line's `picture` field reaches the DOM. */
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
 * `null` once nothing is open any more (picture: `mockup.html`'s own
 * `nextOpenAfter`, which `Stage`'s auto-advance after a decision mirrors). */
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
