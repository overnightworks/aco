import { describe, expect, test } from 'vitest';
import { cardOption, line, optionLine } from '../../test-support/board';
import type { CardOption, DecisionKind } from '../../types';
import {
	cardMeta,
	chosenOption,
	CONTRACT_SUMMARY,
	contractTexts,
	decidedText,
	isOptionLine,
	isStuck,
	KIND_LABEL,
	nextOpenOption,
	type OpenOption,
	resultAltText,
	ROW_LABEL,
	SAME_AS_TODAY_MARK,
	sourceLine,
	UNDO_LABEL,
	UNDO_SEPARATOR,
	undoTail,
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

test('only a line carrying form options is an option line', () => {
	expect(isOptionLine(optionLine())).toBe(true);
	expect(isOptionLine(line())).toBe(false);
});

describe('the detail rows of an option', () => {
	test('are labelled with the ruled words of the decision card', () => {
		expect([
			ROW_LABEL.result,
			ROW_LABEL.notice,
			ROW_LABEL.cost,
			ROW_LABEL.undo,
			ROW_LABEL.contract
		]).toEqual(['Result', 'You notice', 'Cost', 'Undo', 'Contract']);
		expect([SAME_AS_TODAY_MARK, CONTRACT_SUMMARY, UNDO_SEPARATOR]).toEqual([
			'= TODAY',
			'Show',
			' — '
		]);
	});

	test('give the picture the caption as alt text, or letter, name and effect without one', () => {
		const captioned = cardOption({ caption: 'The song stays.' }) as CardOption;

		expect(resultAltText(captioned)).toBe('The song stays.');
		expect(resultAltText(cardOption())).toBe('A · Keep the song open: The app jumps itself.');
	});

	test('read the undo word, the separator and how to undo', () => {
		const option = cardOption({ undo: 'final', undo_how: 'nie' });

		expect(undoTail(option)).toBe(' — nie');
	});

	test('name the source as repository, item and line', () => {
		expect(sourceLine('songmaker', 1843, optionLine({ index: 1 }))).toBe(
			'songmaker · Item 1843 · Line 1'
		);
	});

	test('[ABRD-37] name the source of a yes/no line the same way', () => {
		expect(sourceLine('songmaker', 42, line({ index: 3 }))).toBe('songmaker · Item 42 · Line 3');
	});

	test.each([
		[
			'the line text differs from the contract',
			'The song stays.',
			'Rule 10.',
			['The song stays.', 'Rule 10.']
		],
		['the line text equals the contract', 'Rule 10.', 'Rule 10.', ['Rule 10.']]
	])('bind both sentences when %s', (_name, contract, text, expected) => {
		const texts = contractTexts(optionLine({ text }), cardOption({ contract }));

		expect(texts).toEqual(expected);
	});
});

describe('nextOpenOption', () => {
	test.each<[string, OpenOption, CardOption['letter'], OpenOption]>([
		['opens a closed option', null, 'A', 'A'],
		['switches from one option to another', 'A', 'B', 'B'],
		['closes the open option', 'B', 'B', null]
	])('%s', (_name, open, letter, expected) => {
		expect(nextOpenOption(open, letter)).toBe(expected);
	});
});

describe('isStuck', () => {
	test.each<[string, number, boolean]>([
		['the card runs on 2 px below the view', 102, true],
		['the card ends 1 px below the view', 101, false],
		['the card ends level with the view', 100, false],
		['the card ends above the view', 90, false]
	])('[ABRD-52] %s', (_name, containerBottom, expected) => {
		expect(isStuck(containerBottom, 100)).toBe(expected);
	});
});
