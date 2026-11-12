<script lang="ts">
	import {
		clockTime,
		DECIDED_TAB_LABEL,
		decidedList,
		EMPTY_DECIDED_TEXT,
		EMPTY_DECIDED_TITLE,
		EMPTY_LIST_TEXT,
		EMPTY_LIST_TITLE,
		LAST_READ_LABEL,
		LIST_REGION_LABEL,
		NOT_READ_LABEL,
		openList,
		QUIET_PREFIX,
		type ListView,
		type RowList,
		type ShownRepo
	} from '../app/model/boardSummary';
	import { displayDay } from '../app/model/optionCard';
	import QuietSign from './QuietSign.svelte';
	import StateShape from './StateShape.svelte';
	import WarnMark from './WarnMark.svelte';

	let {
		repos,
		view,
		selectedKey,
		saving,
		onSelect
	}: {
		repos: ShownRepo[];
		view: ListView;
		selectedKey: string | null;
		/** Whether the card's answer is being saved. */
		saving: (key: string) => boolean;
		onSelect: (key: string) => void;
	} = $props();

	const list: RowList = $derived(view === 'open' ? openList(repos) : decidedList(repos));
	const regionLabel = $derived(view === 'open' ? LIST_REGION_LABEL : DECIDED_TAB_LABEL);
	const emptyTitle = $derived(view === 'open' ? EMPTY_LIST_TITLE : EMPTY_DECIDED_TITLE);
	const emptyText = $derived(view === 'open' ? EMPTY_LIST_TEXT : EMPTY_DECIDED_TEXT);
</script>

<section aria-label={regionLabel}>
	{#each list.groups as group (group.repo)}
		{#if group.error === null}
			<h2 class="group"><span>{group.repo}</span> <span>{group.rows.length}</span></h2>
		{:else}
			<h2 class="group bad"><span>{group.repo}</span></h2>
			<p class="bad-line" role="alert">
				<span class="mark"><WarnMark /></span>
				<b>{NOT_READ_LABEL}</b>
				<span>{group.error}</span>
				{#if group.readAt !== null}
					<span class="read-at">{LAST_READ_LABEL} {clockTime(group.readAt)}</span>
				{/if}
			</p>
		{/if}
		<ul>
			{#each group.rows as row (row.key)}
				{@const shown = saving(row.key) ? 'saving' : row.state}
				<li>
					<button
						type="button"
						class="row"
						title={row.title}
						aria-current={row.key === selectedKey}
						onclick={() => onSelect(row.key)}
					>
						<StateShape state={shown} />
						<span class="label" class:muted={shown === 'back'}>{row.label}</span>
						<span class="day">{displayDay(row.day)}</span>
					</button>
				</li>
			{/each}
		</ul>
	{/each}
	{#if list.groups.length === 0}
		<div class="empty">
			<QuietSign kind="good" />
			<div class="words"><b>{emptyTitle}</b>{emptyText}</div>
		</div>
	{:else if list.quiet.length > 0}
		<p class="quiet">{QUIET_PREFIX}{list.quiet.join(' · ')}</p>
	{/if}
</section>

<style>
	.bad-line {
		display: grid;
		grid-template-columns: auto 1fr;
		gap: 2px 8px;
		margin: 2px 16px 6px;
		padding: 10px 12px;
		border: 1px solid color-mix(in srgb, var(--warn) 30%, transparent);
		border-radius: 10px;
		background: var(--warn-soft);
		font-size: 13px;
		line-height: 19px;
		color: var(--fg-2);
	}
	.bad-line > span:not(.mark) {
		grid-column: 2;
	}
	.bad-line b,
	.mark {
		color: var(--warn);
		font-weight: 600;
		white-space: nowrap;
	}
	.read-at {
		color: var(--fg-3);
	}
	.group {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
		margin: 0;
		padding: 22px 24px 6px;
		font-size: 13px;
		font-weight: 600;
		color: var(--fg-2);
	}
	.group > span:last-child:not(:first-child) {
		font-weight: 400;
		color: var(--fg-3);
	}
	.group.bad {
		color: var(--warn);
	}
	ul {
		list-style: none;
		margin: 0;
		padding: 0 8px;
	}
	.row {
		display: flex;
		align-items: center;
		gap: 12px;
		width: 100%;
		min-height: 42px;
		padding: 9px 16px;
		border: 0;
		border-radius: 10px;
		background: none;
		text-align: left;
		transition: background-color 0.12s;
	}
	.row:hover {
		background: var(--surface-2);
	}
	.row[aria-current='true'] {
		background: var(--accent-soft);
		box-shadow: inset 3px 0 0 var(--accent);
		font-weight: 600;
	}
	@media (prefers-reduced-motion: reduce) {
		.row {
			transition: none;
		}
	}
	.label {
		flex: 1;
		min-width: 0;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.day {
		flex: none;
		font-size: 12.5px;
		color: var(--fg-3);
	}
	.muted {
		color: var(--fg-3);
	}
	.quiet {
		margin: 0;
		padding: 16px 24px 0;
		font-size: 13px;
		color: var(--fg-3);
	}
	.empty {
		display: grid;
		justify-items: center;
		gap: 14px;
		padding: 0 24px 12vh;
		text-align: center;
		font-size: 15px;
		color: var(--fg-3);
	}
	.words {
		display: grid;
		gap: 6px;
	}
	.empty b {
		font-family: var(--font-display);
		font-size: 26px;
		font-weight: 400;
		line-height: 32px;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		color: var(--fg);
	}
	@media (max-width: 760px) {
		.group {
			padding: 20px 18px 6px;
		}
		ul {
			padding: 0 6px;
		}
		.row {
			min-height: 48px;
			padding: 10px 12px;
		}
	}
</style>
