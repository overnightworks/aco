import type { OldStepRead, PasteStepRead, RepoReading, StepRead, StepRequest } from '../../types';
import { displayDate } from './optionCard';

export const STEPS_TAB_LABEL = 'Steps';
export const STEPS_REGION_LABEL = 'Steps for you';
export const NO_STEPS_TEXT = 'No step is waiting for you.';
export const COPY_LABEL = 'Copy';
export const COPIED_LABEL = 'Copied';
export const COPY_FAILED_LABEL = 'Copy failed, try again';
export const OPEN_LABEL = 'Öffnen';
export const OLD_FORM_LABEL = 'alte Form';
const WAITING_SINCE_LABEL = 'wartet seit';

const YES_OR_NO_ANSWER = 'Ja / Nein';

/** How the step asks to be answered: yes or no, or the report it names (ABRD-159). */
export function answerText(step: StepRead): string {
	return `Antwort: ${step.answer ?? YES_OR_NO_ANSWER}`;
}

/** The paste to copy, or the link to open. */
export function pasteOf(step: PasteStepRead): { command: string } | { link: string } {
	return step.paste_kind === 'link' ? { link: step.paste } : { command: step.paste };
}

/** What an old-form step stored besides its line, as plain text: purpose, actions or paste,
 * expected, those it holds. */
export function storedTexts(step: OldStepRead): string[] {
	return [step.purpose, step.actions ?? step.paste, step.expected].filter((text) => text !== null);
}

/** Written once for each step: `wartet seit 01.11.2026`. */
export function waitingSinceText(step: StepRead): string {
	return `${WAITING_SINCE_LABEL} ${displayDate(step.since)}`;
}

/** The repos the Steps view shows as groups (ABRD-199): those with a step, by their first
 * step's `since` newest first, then higher item; ties keep the configured order, and a repo
 * whose read failed stands last. Each repo's steps arrive newest first (MCP-43). */
export function stepGroups(repos: RepoReading[]): RepoReading[] {
	const failed = repos.filter((repo) => repo.error !== null);
	const withSteps = repos.filter((repo) => repo.error === null && repo.steps.length > 0);
	const newestFirst = (a: RepoReading, b: RepoReading) =>
		b.steps[0].since.localeCompare(a.steps[0].since) || b.steps[0].number - a.steps[0].number;
	return [...withSteps.sort(newestFirst), ...failed];
}

/** The steps of every repo that could be read; a repo that failed has none to count. */
export function stepCount(repos: { steps: StepRead[] }[]): number {
	return repos.reduce((sum, repo) => sum + repo.steps.length, 0);
}

export const SUCCESS_LABEL = 'Erfolgreich';
export const FAILURE_LABEL = 'Fehlgeschlagen';
export const SEND_LABEL = 'Senden';
export const NOTE_LABEL = 'Notiz';
export const REPORT_LABEL = 'Bericht';

const RESULT_LABEL: Record<StepRequest['result'], string> = {
	yes: SUCCESS_LABEL,
	no: FAILURE_LABEL,
	report: REPORT_LABEL
};

/** What the undo strip says an answer to step `number` will store: `Erfolgreich · #7`. */
export function stepStripText(result: StepRequest['result'], number: number): string {
	return `${RESULT_LABEL[result]} · #${number}`;
}
