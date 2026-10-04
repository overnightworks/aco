/**
 * Pure read-only projections over a `BoardResponse`, shared by `App.svelte`
 * and `TrackList.svelte` so neither carries decision logic of its own
 * (SonarCloud does not analyse `.svelte`, issue #368: this is where the
 * behaviour lives instead).
 */

import type { ExpectationLine, Outcome, RepoReading } from '../../types';

const OUTCOME_LABEL: Record<Outcome, string> = {
	yes: 'Ja',
	no: 'Nein',
	later: 'Später'
};

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
		return `${OUTCOME_LABEL[line.ruling]} · ${line.ruled_on ?? ''}`;
	}
	return line.default !== null ? `Empfohlen: ${OUTCOME_LABEL[line.default]}` : 'Offen';
}
