import { describe, expect, test } from 'vitest';
import { cardOption, line, optionLine } from '../../test-support/board';
import {
	ALREADY_RULED_MESSAGE,
	cardKey,
	cardOtherRequest,
	cardPicksRequest,
	cardUnclearRequest,
	decisionRequest,
	LINE_CHANGED_MESSAGE,
	lineKey,
	noteOrNull,
	readDecisionResult
} from './decision';

describe('lineKey / decisionRequest', () => {
	test('the key binds the repo label to the item and line index', () => {
		expect(lineKey('repo', 42, line({ index: 3 }))).toBe('repo:42:3');
	});

	test('a decision carries the card fingerprint as read, never a derived one', () => {
		const card = line({ index: 3, fingerprint: 'fp-abc' });

		expect(decisionRequest('repo', 42, card, 'later', 'a note')).toEqual({
			repo: 'repo',
			item: 42,
			line: 3,
			fingerprint: 'fp-abc',
			outcome: 'later',
			note: 'a note'
		});
	});
});

describe('card requests', () => {
	const first = optionLine({ index: 4, fingerprint: 'fp-song' });
	const second = optionLine({ index: 6, fingerprint: 'fp-library' });
	const shown = [
		{ line: 4, fingerprint: 'fp-song' },
		{ line: 6, fingerprint: 'fp-library' }
	];

	test('[ABRD-77] a card key is one per item and never a line key', () => {
		expect(cardKey('repo', 42)).toBe('repo:42:card');
		expect(cardKey('repo', 42)).not.toBe(lineKey('repo', 42, first));
	});

	test('[ABRD-77] the picks name each point as it was shown with its letter, nothing else', () => {
		const request = cardPicksRequest('repo', 42, [
			{ shown: first, option: cardOption({ letter: 'B' }) },
			{ shown: second, option: cardOption({ letter: 'A' }) }
		]);

		expect(request).toEqual({
			repo: 'repo',
			item: 42,
			lines: [
				{ line: 4, fingerprint: 'fp-song', option: 'B' },
				{ line: 6, fingerprint: 'fp-library', option: 'A' }
			]
		});
	});

	test('[ABRD-92] an Other answer names every point and carries the trimmed text once', () => {
		const request = cardOtherRequest('repo', 42, [first, second], '  Only on desktop \n');

		expect(request).toEqual({ repo: 'repo', item: 42, lines: shown, other: 'Only on desktop' });
	});

	test.each([
		['  Why two options? \n', 'Why two options?'],
		['   ', null]
	])('[ABRD-75] the note %j goes as %j on every point, with no letter', (raw, note) => {
		const request = cardUnclearRequest('repo', 42, [first, second], raw);

		expect(request).toEqual({ repo: 'repo', item: 42, lines: shown, unclear: true, note });
	});
});

describe('noteOrNull', () => {
	test.each([
		['', null],
		['   ', null],
		[' hi ', 'hi']
	])('%j -> %j', (raw, expected) => {
		expect(noteOrNull(raw)).toBe(expected);
	});
});

describe('readDecisionResult', () => {
	test('a ruled result needs no message', () => {
		expect(readDecisionResult({ status: 'ruled', message: null })).toEqual({ kind: 'ruled' });
	});

	test('[ABRD-76] a returned result is read as stored, not as a refusal', () => {
		expect(readDecisionResult({ status: 'returned', message: null })).toEqual({
			kind: 'returned'
		});
	});

	test('an already-ruled result gets the board’s own operator-facing sentence', () => {
		expect(
			readDecisionResult({ status: 'already_ruled', message: 'line 1 is already ruled' })
		).toEqual({
			kind: 'already-ruled',
			message: ALREADY_RULED_MESSAGE
		});
	});

	test('a failure carrying the exact changed-line sentence reads as "changed"', () => {
		expect(readDecisionResult({ status: 'failed', message: LINE_CHANGED_MESSAGE })).toEqual({
			kind: 'changed',
			message: LINE_CHANGED_MESSAGE
		});
	});

	test('any other failure keeps its own message', () => {
		expect(readDecisionResult({ status: 'failed', message: 'aco rule failed: boom' })).toEqual({
			kind: 'failed',
			message: 'aco rule failed: boom'
		});
	});

	test('a failure with no message falls back to a German sentence', () => {
		expect(readDecisionResult({ status: 'failed', message: null })).toEqual({
			kind: 'failed',
			message: 'unbekannter Fehler'
		});
	});
});
