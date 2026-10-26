import { describe, expect, test } from 'vitest';
import { cardOption, line, optionLine } from '../../test-support/board';
import type { CardOption, DecisionKind } from '../../types';
import {
	cardMeta,
	chosenOption,
	decidedText,
	isOptionLine,
	KIND_LABEL,
	optionStatusText,
	UNDO_LABEL,
	verdictLabel
} from './optionCard';

describe('cardMeta', () => {
	test('names repository and area, the kind, and reversible when no option is final', () => {
		const meta = cardMeta('songmaker', optionLine({ area: 'Song page', decision_kind: 'money' }));

		expect(meta).toEqual({ where: 'songmaker › Song page', kind: 'Money', undo: 'reversible' });
	});

	test('names final as soon as one option is final', () => {
		const card = optionLine({
			options: [cardOption(), cardOption({ letter: 'B', name: 'Delete it', undo: 'final' })]
		});

		expect(cardMeta('songmaker', card).undo).toBe('final');
		expect(UNDO_LABEL[cardMeta('songmaker', card).undo]).toBe('final');
	});

	test.each<[DecisionKind, string]>([
		['product', 'Product'],
		['technical', 'Technical'],
		['data_risk', 'Data & risk'],
		['money', 'Money'],
		['access', 'Access'],
		['wording', 'Wording'],
		['release', 'Release']
	])('labels the %s kind %s', (kind, label) => {
		expect(KIND_LABEL[kind]).toBe(label);
		expect(cardMeta('repo', optionLine({ decision_kind: kind })).kind).toBe(label);
	});
});

describe('the chosen option', () => {
	const ruled = optionLine({
		ruling: 'B',
		ruled_on: '2026-10-26',
		options: [cardOption(), cardOption({ letter: 'B', name: 'As today' })]
	});

	test('is the option whose letter the ruling names', () => {
		const chosen = chosenOption(ruled) as CardOption;

		expect(chosen.name).toBe('As today');
		expect(verdictLabel(chosen)).toBe('B · As today');
		expect(decidedText(chosen)).toBe('B — As today');
	});

	test('does not exist while the line is open', () => {
		expect(chosenOption(optionLine())).toBeUndefined();
	});
});

describe('optionStatusText', () => {
	test('recommends the letter on an open line', () => {
		expect(optionStatusText(optionLine({ recommended: 'C' }))).toBe('Empfohlen: C');
	});

	test('gives letter, name and date on a ruled line', () => {
		const ruled = optionLine({ ruling: 'A', ruled_on: '2026-10-26' });

		expect(optionStatusText(ruled)).toBe('A · Keep the song open · 2026-10-26');
	});

	test('leaves the date empty when the ruling carries none', () => {
		expect(optionStatusText(optionLine({ ruling: 'A', ruled_on: null }))).toBe(
			'A · Keep the song open · '
		);
	});
});

test('only a line carrying form options is an option line', () => {
	expect(isOptionLine(optionLine())).toBe(true);
	expect(isOptionLine(line())).toBe(false);
});
