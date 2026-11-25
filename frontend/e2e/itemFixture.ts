/**
 * Arranges the work items the board's real `aco` reads, through the control
 * endpoint `tests/support/e2e_server.py` serves beside the board. An entry
 * carries the body grammar's own keys (`specs/body-block.spec.md`): aco renders
 * the item body, computes every card hash and refuses an entry its grammar
 * refuses, so a spec arranges only bodies aco itself would read. A line's
 * index is its position among its item's entries.
 */

import type { Page } from '@playwright/test';
import { readBoardRuntime } from './runtime';

type Outcome = 'yes' | 'no' | 'later';

export interface CardOption {
	name: string;
	effect: string;
	picture?: string;
	same_as_today?: true;
	caption?: string;
	notice: string;
	cost: string;
	undo: 'reversible' | 'final';
	undo_how: string;
	contract: string;
}

/** An option line; a state key left out is undecided, never null. */
export interface OptionEntry {
	text: string;
	asked_on?: string;
	ruling?: string;
	ruled_on?: string;
	via?: 'board' | 'chat' | 'default';
	other?: string;
	returned_on?: string;
	returned_note?: string;
	question: string;
	problem: string;
	picture?: string;
	caption?: string;
	decision_kind: string;
	area: string;
	topic: string;
	recommended: string;
	reason: string;
	option: CardOption[];
}

/** A ruled yes/no line, the history an item may still carry. */
export interface YesNoEntry {
	text: string;
	ruling: Outcome;
	ruled_on: string;
	question?: string;
	example?: string;
	picture?: string;
}

interface WithdrawnEntry {
	text: string;
	withdrawn_on: string;
}

type Entry = OptionEntry | YesNoEntry | WithdrawnEntry;

/** A container's sub-issues by number, the list its counts derive from. */
export interface ContainerChildren {
	closed: number[];
	open: number[];
}

export interface Item {
	number: number;
	title: string;
	entries: Entry[];
	/** Set once the item is a container. */
	container?: ContainerChildren;
	/** The item this one is a child of. */
	parent?: number;
	/** Whether the item waits on the operator. */
	waiting?: true;
	/** The step table of an item that waits on the operator; it waits without `waiting`. */
	step?: StepTable | OldStepTable;
}

/** The first arranged item's open cards are asked on this day, each later one a day before. */
const NEWEST_ASKED_ON = new Date('2026-10-02T00:00:00Z');
const DAY_MS = 24 * 60 * 60 * 1000;

export function optionEntry(text: string, overrides: Partial<OptionEntry> = {}): OptionEntry {
	return {
		text,
		question: 'Frage?',
		problem: 'Ein Problem.',
		picture: '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="60"/>',
		caption: 'Heute',
		decision_kind: 'product',
		area: 'Bereich',
		topic: 'Thema',
		recommended: 'A',
		reason: 'Ein Grund.',
		option: [],
		...overrides
	};
}

export function withdrawnEntry(text: string, withdrawnOn: string): WithdrawnEntry {
	return { text, withdrawn_on: withdrawnOn };
}

export function yesNoEntry(
	text: string,
	ruling: Outcome,
	ruledOn: string,
	overrides: Partial<YesNoEntry> = {}
): YesNoEntry {
	return { text, ruling, ruled_on: ruledOn, ...overrides };
}

export function item(number: number, title: string, ...entries: Entry[]): Item {
	return { number, title, entries };
}

function isOpenOptionEntry(entry: Entry): entry is OptionEntry {
	return 'option' in entry && !('ruling' in entry);
}

/** RUL-03 lists items with an open card newest `asked_on` first, so dating
 * each item's undated open cards a day older than the item before it lists
 * the items in the order a spec arranges them. */
function dated(items: Item[]): Item[] {
	return items.map((arranged, position) => {
		const askedOn = new Date(NEWEST_ASKED_ON.getTime() - position * DAY_MS)
			.toISOString()
			.slice(0, 10);
		return {
			...arranged,
			entries: arranged.entries.map((entry) =>
				isOpenOptionEntry(entry) && entry.asked_on === undefined
					? { ...entry, asked_on: askedOn }
					: entry
			)
		};
	});
}

/** A finished item the state ref's lane records hold: its issue, the seconds its lane took and,
 * when its record states them, its fix rounds. */
export interface FinishedItem {
	issue: number;
	wall_seconds: number;
	fix_rounds?: number;
}

/** The board holds exactly `items` from now on; `listingFailure` makes every
 * listing fail with that message until the next arrangement, `landed` are
 * the items a trunk commit's trailer names as landed, and `laneRecords` the
 * finished items the state ref holds (none by default). */
export async function arrange(
	items: Item[],
	{
		listingFailure,
		landed,
		laneRecords
	}: { listingFailure?: string; landed?: number[]; laneRecords?: FinishedItem[] } = {}
): Promise<void> {
	const response = await fetch(`${readBoardRuntime().controlUrl}/board`, {
		method: 'PUT',
		body: JSON.stringify({
			items: dated(items),
			landed: landed ?? [],
			lane_records: laneRecords ?? [],
			listing_failure: listingFailure ?? null
		})
	});
	if (!response.ok) {
		throw new Error(`aco refuses the arrangement: ${await response.text()}`);
	}
}

/** Line `index` of item `number` as aco stores it, in aco's own line JSON. */
export async function storedLine(number: number, index: number): Promise<Record<string, unknown>> {
	const response = await fetch(`${readBoardRuntime().controlUrl}/items/${number}/lines`);
	const lines = (await response.json()) as Record<string, unknown>[];
	return lines[index - 1];
}

/** The `now` text of item `number` as aco stores it. */
export async function storedNow(number: number): Promise<string> {
	const response = await fetch(`${readBoardRuntime().controlUrl}/items/${number}/now`);
	return (await response.json()) as string;
}

/** A container with these sub-issues, no card of its own. */
export function container(
	number: number,
	title: string,
	children: Partial<ContainerChildren>,
	overrides: Partial<Item> = {}
): Item {
	return {
		number,
		title,
		entries: [],
		container: { closed: [], open: [], ...children },
		...overrides
	};
}

interface StepTable {
	purpose: string;
	paste: string;
	expected: string;
}

interface OldStepTable {
	purpose: string;
	actions: string;
	expected: string;
	answer?: string;
}

/** One repository as `GET /api/board` lists it with nothing to show: `overrides` names what the
 * scenario changes, a failed read through `error`. */
export function repoReading(
	name: string,
	overrides: Partial<{ error: string | null; steps: unknown[] }> = {}
) {
	return { name, error: null, items: [], progress: null, steps: [], ...overrides };
}

/** A step table in the paste form the way an item stores it; `overrides` names what the
 * scenario changes. */
export function stepTable(overrides: Partial<StepTable> = {}): StepTable {
	return {
		purpose: 'Release the build.',
		paste: 'make release',
		expected: 'The page shows green.',
		...overrides
	};
}

/** A step table stored with `actions`, the older form. */
export function oldStepTable(overrides: Partial<OldStepTable> = {}): OldStepTable {
	return {
		purpose: 'Release the build.',
		actions: 'open https://example.test/run\nclick Run',
		expected: 'The page shows green.',
		...overrides
	};
}

/** Opens the board and its Steps view. */
export async function openSteps(page: Page): Promise<void> {
	const { appUrl, token } = readBoardRuntime();
	await page.goto(`${appUrl}#t=${token}`);
	await page
		.getByRole('navigation', { name: 'Views' })
		.getByRole('button', { name: /^Steps/ })
		.click();
}
