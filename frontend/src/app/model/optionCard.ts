/**
 * Pure projections over an option line (`specs/serve.spec.md` ABRD-36/37):
 * the one vocabulary owner for every string on the option card, so
 * `OptionCard.svelte` and the list and Verlauf views carry no wording of
 * their own. The row labels are the ruled English words of the decision
 * card (#13 line 12); the rest of the page keeps its German.
 */

import type { CardOption, DecisionKind, ExpectationLine, OptionLine, Undo } from '../../types';

export const ROW_LABEL = {
	problem: 'Problem',
	today: 'Today',
	options: 'Options',
	recommendation: 'Recommendation',
	decided: 'Decided'
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

/** `A · name` -- the verdict Verlauf and the list show instead of a yes/no
 * outcome. */
export function verdictLabel(option: CardOption): string {
	return `${option.letter} · ${option.name}`;
}

/** The ruled card's Decided row. */
export function decidedText(option: CardOption): string {
	return `${option.letter} — ${option.name}`;
}

/** The list's status text: the recommended letter while open, the verdict
 * and its date once ruled. */
export function optionStatusText(line: OptionLine): string {
	const chosen = chosenOption(line);
	if (chosen === undefined) {
		return `Empfohlen: ${line.recommended}`;
	}
	return `${verdictLabel(chosen)} · ${line.ruled_on ?? ''}`;
}
