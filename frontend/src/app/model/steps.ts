import type { StepRead, StepRequest } from '../../types';

export const STEPS_TAB_LABEL = 'Steps';
export const STEPS_REGION_LABEL = 'Steps for you';
export const NO_STEPS_TEXT = 'No step is waiting for you.';
export const COPY_LABEL = 'Copy';
export const COPIED_LABEL = 'Copied';
export const COPY_FAILED_LABEL = 'Copy failed, try again';

const YES_OR_NO_ANSWER = 'Ja / Nein';

/** How the step asks to be answered: yes or no, or the report it names (ABRD-159). */
export function answerText(step: StepRead): string {
	return `Antwort: ${step.answer ?? YES_OR_NO_ANSWER}`;
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
