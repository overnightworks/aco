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
	how: 'How',
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

/** What the frame's meta line shows; a card without a kind or an undo token
 * leaves it out. */
export interface FrameMeta {
	where: string;
	kind?: string;
	/** The line was sent back to its head (ABRD-61). */
	withHead?: true;
	undo?: Undo;
}

export interface CardMeta extends FrameMeta {
	kind: string;
	undo: Undo;
}

/** The meta line above the card: where the decision lives, what kind it is,
 * and whether any answer cannot be taken back. */
export function cardMeta(repo: string, line: OptionLine): CardMeta {
	return {
		where: `${repo} › ${line.area}`,
		kind: KIND_LABEL[line.decision_kind],
		...(line.returned_on !== null && { withHead: true as const }),
		undo: line.options.some((option) => option.undo === 'final') ? 'final' : 'reversible'
	};
}

/** The option a ruled line chose; `undefined` while the line is open. */
export function chosenOption(line: OptionLine): CardOption | undefined {
	return line.options.find((option) => option.letter === line.ruling);
}

/** `A · name` -- an option named by its letter, as the RESULT picture's
 * fallback alt text reads it. */
export function verdictLabel(option: CardOption): string {
	return `${option.letter} · ${option.name}`;
}

/** The Decided row of a ruled line. */
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

/** The strip text of a pick waiting out the undo window. */
export function pendingOptionText(line: OptionLine, option: CardOption): string {
	return `${decidedText(option)} · ${line.topic}`;
}

export type EscapeKind = 'other' | 'unclear';

/** The escape row's open panel: its kind, and the card as shown when it opened
 * -- the card `Send` posts. */
export interface EscapePanel {
	kind: EscapeKind;
	shown: OptionLine;
}

export const ESCAPE_LABEL = {
	send: 'Send',
	other: { button: 'Other…', field: 'Your answer', placeholder: 'What should apply instead?' },
	unclear: {
		button: 'Unclear',
		field: 'What is unclear? (optional)',
		placeholder: 'Optional: what is unclear?'
	}
} as const;

/** Unclear sends the card back with or without a note; Other needs its answer. */
export function sendsBlank(kind: EscapeKind): boolean {
	return kind === 'unclear';
}

/** The strip text of an Other answer waiting out the undo window. */
export function pendingOtherText(line: OptionLine): string {
	return `Other · ${line.topic}`;
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
export function sourceLine(repo: string, item: number, line: ExpectationLine): string {
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
