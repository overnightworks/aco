import { describe, expect, test } from 'vitest';
import { repo } from '../../test-support/board';
import {
	clockTime,
	isStale,
	lastReadAt,
	READING_LABEL,
	REFRESH_LABEL,
	refreshName,
	STALE_AFTER_SECONDS
} from './boardSummary';

const readAt = new Date(2026, 9, 31, 9, 41, 0);

function readRepo(name: string, moment: Date | null, error: string | null = null) {
	return { ...repo({ name, error }), readAt: moment };
}

describe('lastReadAt', () => {
	test('[ABRD-104] is the latest read time, a failed repository keeping its older one', () => {
		const later = new Date(2026, 9, 31, 9, 55);
		const repos = [
			readRepo('a', readAt),
			readRepo('b', later),
			readRepo('c', new Date(2026, 9, 31, 9, 10), 'forge down')
		];

		expect(lastReadAt(repos)).toEqual(later);
	});

	test('[ABRD-104] is null while no repository has been read', () => {
		expect(lastReadAt([readRepo('a', null)])).toBeNull();
	});
});

describe('isStale', () => {
	const repos = [readRepo('a', readAt)];
	const after = (seconds: number) => new Date(readAt.getTime() + seconds * 1000);

	test.each([
		{ seconds: STALE_AFTER_SECONDS - 1, stale: false },
		{ seconds: STALE_AFTER_SECONDS + 1, stale: true }
	])('[ABRD-103] a read $seconds s ago is stale: $stale', ({ seconds, stale }) => {
		expect(isStale(repos, after(seconds))).toBe(stale);
	});

	test('[ABRD-103] with no read yet the board is stale', () => {
		expect(isStale([readRepo('a', null)], readAt)).toBe(true);
	});
});

describe('refreshName', () => {
	test.each([
		{ reading: false, label: REFRESH_LABEL },
		{ reading: true, label: READING_LABEL }
	])('[ABRD-104] reads "$label · read HH:MM" when reading is $reading', ({ reading, label }) => {
		expect(refreshName(reading, readAt)).toBe(`${label} · read ${clockTime(readAt)}`);
	});

	test('[ABRD-104] is the bare label before any read', () => {
		expect(refreshName(false, null)).toBe(REFRESH_LABEL);
	});
});
