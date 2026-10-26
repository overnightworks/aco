<script lang="ts">
	import {
		EMPTY_LIST_TEXT,
		EMPTY_LIST_TITLE,
		LIST_REGION_LABEL,
		openList,
		QUIET_PREFIX
	} from '../app/model/boardSummary';
	import type { RepoReading } from '../types';
	import StateShape from './StateShape.svelte';

	let {
		repos,
		selectedKey,
		onSelect
	}: { repos: RepoReading[]; selectedKey: string | null; onSelect: (key: string) => void } =
		$props();

	const list = $derived(openList(repos));
</script>

<section aria-label={LIST_REGION_LABEL}>
	{#each list.groups as group (group.repo)}
		{#if 'error' in group}
			<p role="alert">{group.repo}: {group.error}</p>
		{:else}
			<h2 class="group"><span>{group.repo}</span> <span>{group.rows.length}</span></h2>
			<ul>
				{#each group.rows as row (row.key)}
					<li>
						<button
							type="button"
							class="row"
							title={row.title}
							aria-current={row.key === selectedKey}
							onclick={() => onSelect(row.key)}
						>
							<StateShape state={row.state} />
							<span class="label" class:muted={row.state === 'todo'}>{row.label}</span>
						</button>
					</li>
				{/each}
			</ul>
		{/if}
	{/each}
	{#if list.groups.length === 0}
		<div class="empty"><b>{EMPTY_LIST_TITLE}</b>{EMPTY_LIST_TEXT}</div>
	{:else if list.quiet.length > 0}
		<p class="quiet">{QUIET_PREFIX}{list.quiet.join(' · ')}</p>
	{/if}
</section>

<style>
	[role='alert'] {
		margin: 0;
		padding: 16px 24px 0;
	}
	.group {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
		margin: 0;
		padding: 16px 24px 4px;
		font-size: 11px;
		font-weight: 650;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: #6e6779;
	}
	ul {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	.row {
		display: flex;
		align-items: center;
		gap: 12px;
		width: 100%;
		min-height: 36px;
		padding: 7px 24px;
		border: 0;
		background: none;
		text-align: left;
	}
	.row:hover,
	.row[aria-current='true'] {
		background: #f1eff4;
	}
	.row[aria-current='true'] {
		font-weight: 600;
	}
	.label {
		flex: 1;
		min-width: 0;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.muted {
		color: #6e6779;
	}
	.quiet {
		margin: 0;
		padding: 16px 24px 0;
		font-size: 13px;
		color: #6e6779;
	}
	.empty {
		padding: 32px 24px;
		color: #4d4758;
	}
	.empty b {
		display: block;
		margin-bottom: 4px;
		color: #18151f;
	}
	@media (max-width: 760px) {
		.group,
		.row {
			padding-left: 16px;
			padding-right: 16px;
		}
	}
</style>
