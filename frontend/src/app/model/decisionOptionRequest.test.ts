import { expect, test } from 'vitest';
import { cardOption } from '../../test-support/board';
import { RELOAD_LABEL } from './decision';
import {
	asksToConfirm,
	CONFIRM_LABEL,
	confirmTitle,
	confirmVerb,
	consequenceText,
	pickLabel,
	ROW_LABEL
} from './optionCard';

const optionA = cardOption({ name: 'Song stays open' });
const optionB = cardOption({ letter: 'B', name: 'As today' });

test('[ABRD-44] a pick is named by its letter and option name', () => {
	expect(pickLabel(optionA)).toBe('Decide A: Song stays open');
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
