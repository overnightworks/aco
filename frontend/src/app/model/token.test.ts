import { describe, expect, test } from 'vitest';
import { tokenFromHash } from './token';

describe('tokenFromHash', () => {
	test.each([
		['#t=abc123', 'abc123'],
		['#t=abc123&other=1', 'abc123'],
		['#other=1&t=abc123', 'abc123'],
		['', null],
		['#', null],
		['#t=', null],
		['#other=1', null]
	])('%s -> %s', (hash, expected) => {
		expect(tokenFromHash(hash)).toBe(expected);
	});
});
