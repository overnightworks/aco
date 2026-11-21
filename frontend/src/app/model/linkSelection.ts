/**
 * The card or step a board link names (`specs/serve.spec.md` ABRD-188 to
 * ABRD-192): read from the fragment's `c` and `s` fields, then resolved
 * against what the board holds, or told apart by why it cannot be shown.
 */

import type { RepoReading } from '../../types';
import { openPoints } from './card';
import { cardKey } from './decision';

export type LinkTarget =
	| { kind: 'card'; repo: string; item: number; line: number }
	| { kind: 'step'; repo: string; item: number };

const CARD_RULED_NOTE = 'Diese Karte ist schon entschieden.';
const CARD_GONE_NOTE = 'Diese Karte gibt es nicht mehr.';
const STEP_GONE_NOTE = 'Dieser Schritt wartet nicht mehr.';
const REPO_UNREADABLE_NOTE = 'Dieses Repo ist gerade nicht lesbar.';

export type LinkOutcome =
	| { kind: 'card'; key: string }
	| { kind: 'step'; repo: string; item: number }
	| { kind: 'note'; note: string };

const CARD_REFERENCE = /^(.+)\/(\d+)\/(\d+)$/;
const STEP_REFERENCE = /^(.+)\/(\d+)$/;

/** The target the fragment names, a card before a step; null when it names neither. */
export function linkFromHash(hash: string): LinkTarget | null {
	if (!hash.startsWith('#')) {
		return null;
	}
	const fields = new URLSearchParams(hash.slice(1));
	const card = CARD_REFERENCE.exec(fields.get('c') ?? '');
	if (card !== null) {
		const [, repo = '', item, line] = card;
		return { kind: 'card', repo, item: Number(item), line: Number(line) };
	}
	const step = STEP_REFERENCE.exec(fields.get('s') ?? '');
	if (step === null) {
		return null;
	}
	const [, repo = '', item] = step;
	return { kind: 'step', repo, item: Number(item) };
}

/** What the board does with `target`: select the card, open the step, or say why not. */
export function resolveLink(repos: readonly RepoReading[], target: LinkTarget): LinkOutcome {
	const reading = repos.find((repo) => repo.name === target.repo);
	const gone = target.kind === 'card' ? CARD_GONE_NOTE : STEP_GONE_NOTE;
	if (reading === undefined) {
		return { kind: 'note', note: gone };
	}
	if (reading.error !== null) {
		return { kind: 'note', note: REPO_UNREADABLE_NOTE };
	}
	if (target.kind === 'step') {
		return reading.steps.some((step) => step.number === target.item)
			? { kind: 'step', repo: target.repo, item: target.item }
			: { kind: 'note', note: gone };
	}
	const item = reading.items.find((candidate) => candidate.number === target.item);
	if (item === undefined) {
		return { kind: 'note', note: gone };
	}
	if (openPoints(item).some((point) => point.index === target.line)) {
		return { kind: 'card', key: cardKey(target.repo, target.item) };
	}
	const exists = item.lines.some((line) => line.index === target.line);
	return { kind: 'note', note: exists ? CARD_RULED_NOTE : gone };
}

/** The Steps view's key of a step, the one `StepsView` marks as current. */
export function stepKey(repo: string, item: number): string {
	return `${repo}#${item}`;
}
