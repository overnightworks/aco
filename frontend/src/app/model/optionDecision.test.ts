import { expect, test } from 'vitest';
import { cardOption, optionLine } from '../../test-support/board';
import { optionDecisionRequest, RELOAD_LABEL } from './decision';
import {
	asksToConfirm,
	CONFIRM_LABEL,
	confirmTitle,
	confirmVerb,
	consequenceText,
	pendingOptionText,
	pickLabel,
	ROW_LABEL
} from './optionCard';

const optionA = cardOption({ name: 'Song stays open' });
const optionB = cardOption({ letter: 'B', name: 'As today' });
const songCard = optionLine({
	index: 4,
	fingerprint: 'fp-song',
	topic: 'Jump',
	options: [optionA, optionB]
});

test('[ABRD-39] an option decision carries the line index, the card fingerprint and the letter, nothing else', () => {
	const request = optionDecisionRequest('repo', 42, songCard, optionB);

	expect(request).toEqual({
		repo: 'repo',
		item: 42,
		line: 4,
		fingerprint: 'fp-song',
		option: 'B'
	});
	expect(Object.keys(request)).not.toContain('outcome');
	expect(Object.keys(request)).not.toContain('note');
});

test('[ABRD-44] a pick is named by its letter and option name', () => {
	expect(pickLabel(optionA)).toBe('Decide A: Song stays open');
});

test('[ABRD-44] the pending text names the letter, the option and the topic', () => {
	expect(pendingOptionText(songCard, optionB)).toBe('B — As today · Jump');
});

test('[ABRD-44] the row label and the reload label have their one owner', () => {
	expect(ROW_LABEL.decide).toBe('Decide');
	expect(RELOAD_LABEL).toBe('Neu laden');
});

test('[ABRD-46] only a final option asks to be confirmed', () => {
	expect(asksToConfirm(cardOption({ undo: 'final' }))).toBe(true);
	expect(asksToConfirm(cardOption({ undo: 'reversible' }))).toBe(false);
});

test('[ABRD-46] the confirm is titled and confirmed by the letter', () => {
	expect(confirmTitle(optionB)).toBe('Decide B?');
	expect(confirmVerb(optionB)).toBe('Decide B');
	expect(CONFIRM_LABEL.cancel).toBe('Cancel');
});

test.each([
	['nicht rückholbar.', 'Nicht rückholbar.'],
	['ärgerlich, aber möglich.', 'Ärgerlich, aber möglich.'],
	['Nicht rückholbar.', 'Nicht rückholbar.']
])('[ABRD-46] the consequence line capitalises %s as a sentence', (undoHow, sentence) => {
	expect(consequenceText(cardOption({ undo_how: undoHow }))).toBe(sentence);
});
