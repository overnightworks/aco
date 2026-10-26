import { expect, test } from 'vitest';
import { cardOption, optionLine } from '../../test-support/board';
import { optionDecisionRequest, RELOAD_LABEL } from './decision';
import { pendingOptionText, pickLabel, ROW_LABEL } from './optionCard';

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
