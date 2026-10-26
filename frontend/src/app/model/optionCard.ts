/**
 * Pure projections over an option line (`specs/serve.spec.md` ABRD-36/37):
 * the one vocabulary owner for every string on the option card, so
 * `OptionCard.svelte` and the list and Decided views carry no wording of
 * their own. The row labels are the ruled English words of the decision
 * card (#13 line 12); the rest of the page keeps its German.
 */

import type { CardOption, DecisionKind, ExpectationLine, OptionLine, Undo } from '../../types';

export const ROW_LABEL = {
	problem: 'Problem',
	today: 'Today',
	options: 'Options',
	recommendation: 'Recommendation',
	decide: 'Decide',
	decided: 'Decided',
	result: 'Result',
	notice: 'You notice',
	cost: 'Cost',
	undo: 'Undo',
	contract: 'Contract'
} as const;

/** The words of a card picture and its enlargement dialog. */
export const PICTURE_LABEL = {
	enlarge: 'Enlarge picture',
	dialog: 'Picture at full width',
	close: 'Close'
} as const;

export const KIND_LABEL: Record<DecisionKind, string> = {
	product: 'Product',
	technical: 'Technical',
	data_risk: 'Data & risk',
	money: 'Money',
	access: 'Access',
	wording: 'Wording',
	release: 'Release'
};

export const UNDO_LABEL: Record<Undo, string> = {
	reversible: 'reversible',
	final: 'final'
};

/** A yes/no line carries no `form` at all (ABRD-34). */
export function isOptionLine(line: ExpectationLine): line is OptionLine {
	return 'form' in line;
}

export interface CardMeta {
	where: string;
	kind: string;
	undo: Undo;
}

/** The meta line above the card: where the decision lives, what kind it is,
 * and whether any answer cannot be taken back. */
export function cardMeta(repo: string, line: OptionLine): CardMeta {
	return {
		where: `${repo} › ${line.area}`,
		kind: KIND_LABEL[line.decision_kind],
		undo: line.options.some((option) => option.undo === 'final') ? 'final' : 'reversible'
	};
}

/** The option a ruled line chose; `undefined` while the line is open. */
export function chosenOption(line: OptionLine): CardOption | undefined {
	return line.options.find((option) => option.letter === line.ruling);
}

/** `A · name` -- the verdict Decided and the list show instead of a yes/no
 * outcome. */
export function verdictLabel(option: CardOption): string {
	return `${option.letter} · ${option.name}`;
}

/** The ruled card's Decided row. */
export function decidedText(option: CardOption): string {
	return `${option.letter} — ${option.name}`;
}

/** A pick's accessible name; the pick itself shows only the letter. */
export function pickLabel(option: CardOption): string {
	return `${ROW_LABEL.decide} ${option.letter}: ${option.name}`;
}

/** The words of the confirm before a pick that cannot be taken back. */
export const CONFIRM_LABEL = {
	cancel: 'Cancel'
} as const;

/** Only a pick that cannot be taken back asks first (#13 line 12). */
export function asksToConfirm(option: CardOption): boolean {
	return option.undo === 'final';
}

export function confirmTitle(option: CardOption): string {
	return `${confirmVerb(option)}?`;
}

export function confirmVerb(option: CardOption): string {
	return `${ROW_LABEL.decide} ${option.letter}`;
}

/** The one consequence line: the Undo sentence, standing alone. */
export function consequenceText(option: CardOption): string {
	return option.undo_how.charAt(0).toUpperCase() + option.undo_how.slice(1);
}

/** The toast text of a pick waiting out the undo window. */
export function pendingOptionText(line: OptionLine, option: CardOption): string {
	return `${decidedText(option)} · ${line.topic}`;
}

export const SAME_AS_TODAY_MARK = '= TODAY';
export const CONTRACT_SUMMARY = 'Show';
export const UNDO_SEPARATOR = ' — ';

/** The letter of the one option that is open on a card, or none. */
export type OpenOption = CardOption['letter'] | null;

/** Activating an option opens it and closes any other; activating the open
 * one closes it. */
export function nextOpenOption(open: OpenOption, letter: CardOption['letter']): OpenOption {
	return open === letter ? null : letter;
}

/** An option's RESULT alt text: its caption, else the picture's own
 * fallback `A · name: effect`. */
export function resultAltText(option: CardOption): string {
	const caption = 'caption' in option ? option.caption : undefined;
	return caption ?? `${verdictLabel(option)}: ${option.effect}`;
}

/** The Undo row's tail after the bold word. */
export function undoTail(option: CardOption): string {
	return `${UNDO_SEPARATOR}${option.undo_how}`;
}

/** Where the binding sentences stand: repository, item and line. */
export function sourceLine(repo: string, item: number, line: OptionLine): string {
	return `${repo} · Item ${item} · Line ${line.index}`;
}

/** The sentences that bind an option: its contract, then the line's text
 * unless it only repeats the contract. */
export function contractTexts(line: OptionLine, option: CardOption): string[] {
	return line.text === option.contract ? [option.contract] : [option.contract, line.text];
}

/** Whether the Decide row floats over content: its sticky container runs on
 * more than a pixel beyond the bottom of the pane that scrolls it. */
export function isStuck(containerBottom: number, viewBottom: number): boolean {
	return containerBottom > viewBottom + 1;
}
