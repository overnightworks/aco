import type { ClosedChild, NoWorkRange, ProgressCounts, WorkRange } from '../../types';

export const PROGRESS_TAB_LABEL = 'Progress';
export const PROGRESS_REGION_LABEL = 'Progress per repository';
export const LANDED_COUNT_LABEL = 'Landed';
export const OTHER_CLOSED_COUNT_LABEL = 'Closed otherwise';
export const OPEN_COUNT_LABEL = 'Open';
export const UNCUT_COUNT_LABEL = 'Uncut';
export const WAITING_COUNT_LABEL = 'Waiting';
export const PROGRESS_UNKNOWN_LABEL = 'Progress unknown';
export const NO_CONTAINERS_TEXT = 'No container is open.';
export const NOTHING_PLANNED_TEXT = 'Nothing planned';
export const CLOSED_CHILDREN_LABEL = 'Closed children';

/** The figure beside a bar: closed over planned, and the whole percent once
 * something is planned, as in `7/48 · 14 %` (ABRD-131). */
export function progressFigure({ closed, planned, percent }: ProgressCounts): string {
	return percent === null ? `${closed}/${planned}` : `${closed}/${planned} · ${percent} %`;
}

/** The two filled parts of a bar as a share of its width: the landed children,
 * and the children closed another way (ABRD-135); the caller draws no bar
 * while nothing is planned. */
export function barShares({ closed, landed, planned }: ProgressCounts): {
	landed: number;
	otherClosed: number;
} {
	return { landed: (100 * landed) / planned, otherClosed: (100 * (closed - landed)) / planned };
}

const SECONDS_PER_HOUR = 3600;

function plural(count: number, noun: string): string {
	return `${count} ${noun}${count === 1 ? '' : 's'}`;
}

function hoursOf({ low_seconds, high_seconds }: WorkRange): string {
	if (high_seconds < SECONDS_PER_HOUR) return 'under 1 h';
	const high = Math.round(high_seconds / SECONDS_PER_HOUR);
	const low = Math.round(low_seconds / SECONDS_PER_HOUR);
	if (low === high) return `about ${high} h`;
	return low < 1 ? `under 1 to ${high} h` : `about ${low} to ${high} h`;
}

/** The agent work left in a container, never a date (ABRD-146): its lanes left and the range
 * in whole hours with the finished items it is measured from, or the sentence of why there is
 * no range; `null` while no lane is left. */
export function remainingFigure(
	lanesLeft: number,
	estimate: WorkRange | NoWorkRange | null
): string | null {
	if (estimate === null) return null;
	const lanes = `${plural(lanesLeft, 'lane')} left`;
	if (estimate.error !== null) return `${lanes} · ${estimate.error}`;
	return `${lanes} · ${hoursOf(estimate)} agent work · from ${plural(estimate.samples, 'finished item')}`;
}

const SECONDS_PER_MINUTE = 60;

function laneTime(seconds: number | null): string {
	if (seconds === null) return 'time unknown';
	if (seconds < SECONDS_PER_HOUR) return `${Math.round(seconds / SECONDS_PER_MINUTE)} min`;
	return `${Number((seconds / SECONDS_PER_HOUR).toFixed(1))} h`;
}

/** A closed child as its title and what its lanes took, or `no record` when no lane record
 * names it (ABRD-151). */
export function closedChildFigure(child: ClosedChild): string {
	const name = `#${child.number} ${child.title}`;
	if (!child.recorded) return `${name} · no record`;
	const rounds =
		child.fix_rounds === null ? 'fix rounds unknown' : plural(child.fix_rounds, 'fix round');
	return `${name} · ${laneTime(child.wall_seconds)} · ${rounds}`;
}
