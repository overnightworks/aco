import type { ProgressCounts } from '../../types';

export const PROGRESS_TAB_LABEL = 'Progress';
export const PROGRESS_REGION_LABEL = 'Progress per repository';
export const LANDED_COUNT_LABEL = 'Landed';
export const OPEN_COUNT_LABEL = 'Open';
export const UNCUT_COUNT_LABEL = 'Uncut';
export const WAITING_COUNT_LABEL = 'Waiting';
export const PROGRESS_UNKNOWN_LABEL = 'Progress unknown';
export const NO_CONTAINERS_TEXT = 'No container is open.';
export const NOTHING_PLANNED_TEXT = 'Nothing planned';

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
