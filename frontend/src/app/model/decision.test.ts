import { describe, expect, test } from 'vitest';
import { line, optionLine } from '../../test-support/board';
import {
	ALREADY_RULED_MESSAGE,
	decisionRequest,
	LINE_CHANGED_MESSAGE,
	lineKey,
	noteOrNull,
	otherDecisionRequest,
	readDecisionResult,
	unclearDecisionRequest
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

describe('otherDecisionRequest', () => {
	test('[ABRD-64] an Other answer carries the trimmed text and the card fingerprint, no letter or note', () => {
		const request = otherDecisionRequest(
			'repo',
			42,
			optionLine({ index: 4, fingerprint: 'fp-song' }),
			'  Only on desktop \n'
		);

		expect(request).toEqual({
			repo: 'repo',
			item: 42,
			line: 4,
			fingerprint: 'fp-song',
			other: 'Only on desktop'
		});
	});
});

describe('unclearDecisionRequest', () => {
	test.each([
		['  Why two options? \n', 'Why two options?'],
		['   ', null]
	])('[ABRD-75] the note %j goes as %j, with the card fingerprint and no letter', (raw, note) => {
		const request = unclearDecisionRequest(
			'repo',
			42,
			optionLine({ index: 4, fingerprint: 'fp-song' }),
			raw
		);

		expect(request).toEqual({
			repo: 'repo',
			item: 42,
			line: 4,
			fingerprint: 'fp-song',
			unclear: true,
			note
		});
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
