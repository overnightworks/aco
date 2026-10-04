import { afterEach, expect, test, vi } from 'vitest';
import {
	TOKEN_STORAGE_KEY,
	bootstrapToken,
	windowBootstrapEnvironment,
	type BootstrapEnvironment
} from './session';

function fakeEnvironment(overrides: Partial<BootstrapEnvironment> = {}): {
	env: BootstrapEnvironment;
	storage: Map<string, string>;
	replaceState: ReturnType<typeof vi.fn>;
} {
	const storage = new Map<string, string>();
	const replaceState = vi.fn();
	const env: BootstrapEnvironment = {
		hash: '',
		pathWithSearch: '/',
		storage: {
			getItem: (key) => storage.get(key) ?? null,
			setItem: (key, value) => storage.set(key, value),
			removeItem: (key) => storage.delete(key),
			clear: () => storage.clear(),
			key: () => null,
			length: 0
		},
		replaceState,
		...overrides
	};
	return { env, storage, replaceState };
}

test('a hash token is stored and the fragment is replaced before returning', () => {
	const { env, storage, replaceState } = fakeEnvironment({
		hash: '#t=secret',
		pathWithSearch: '/?view=decide'
	});

	const token = bootstrapToken(env);

	expect(token).toBe('secret');
	expect(storage.get(TOKEN_STORAGE_KEY)).toBe('secret');
	expect(replaceState).toHaveBeenCalledWith('/?view=decide');
});

test("no hash token falls back to this tab's stored token, without touching history", () => {
	const { env, replaceState } = fakeEnvironment({ hash: '' });
	env.storage.setItem(TOKEN_STORAGE_KEY, 'already-stored');

	expect(bootstrapToken(env)).toBe('already-stored');
	expect(replaceState).not.toHaveBeenCalled();
});

test('no hash token and nothing stored reads as no access', () => {
	const { env, replaceState } = fakeEnvironment({ hash: '' });

	expect(bootstrapToken(env)).toBeNull();
	expect(replaceState).not.toHaveBeenCalled();
});

test('windowBootstrapEnvironment reads a real window and clears its fragment', () => {
	window.history.replaceState(null, '', '/?x=1#t=from-window');
	window.sessionStorage.clear();

	const token = bootstrapToken(windowBootstrapEnvironment(window));

	expect(token).toBe('from-window');
	expect(window.location.hash).toBe('');
	expect(window.sessionStorage.getItem(TOKEN_STORAGE_KEY)).toBe('from-window');
});

afterEach(() => {
	window.sessionStorage.clear();
	window.history.replaceState(null, '', '/');
});
