import '@testing-library/jest-dom/vitest';

// jsdom has no layout engine and no ResizeObserver; the sticky Decide row only needs it to exist.
globalThis.ResizeObserver = class {
	observe() {}
	unobserve() {}
	disconnect() {}
};
