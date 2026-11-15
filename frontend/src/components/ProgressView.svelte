<script lang="ts">
	import {
		NO_CONTAINERS_TEXT,
		OPEN_COUNT_LABEL,
		PROGRESS_REGION_LABEL,
		PROGRESS_UNKNOWN_LABEL,
		progressFigure,
		UNCUT_COUNT_LABEL,
		WAITING_COUNT_LABEL
	} from '../app/model/progress';
	import { NOT_READ_LABEL } from '../app/model/boardSummary';
	import type { ProgressCounts, RepoReading } from '../types';
	import WarnMark from './WarnMark.svelte';

	let { repos }: { repos: RepoReading[] } = $props();
</script>

{#snippet bar(counts: ProgressCounts, label: string)}
	<div
		class="bar"
		class:done={counts.percent === 100}
		role="progressbar"
		aria-label={label}
		aria-valuemin={0}
		aria-valuemax={counts.planned}
		aria-valuenow={counts.closed}
		aria-valuetext={progressFigure(counts)}
	>
		<span style:width="{counts.percent ?? 0}%"></span>
	</div>
{/snippet}

<section aria-label={PROGRESS_REGION_LABEL}>
	{#each repos as repo (repo.name)}
		{@const progress = repo.progress}
		<article class="repo">
			{#if repo.error !== null || progress === null}
				<h2><span>{repo.name}</span></h2>
				<p class="bad-line" role="alert">
					<span class="mark"><WarnMark /></span>
					<b>{NOT_READ_LABEL}</b>
					<span>{repo.error}</span>
				</p>
			{:else if progress.error !== null}
				<h2><span>{repo.name}</span></h2>
				<p class="bad-line" role="alert">
					<span class="mark"><WarnMark /></span>
					<b>{PROGRESS_UNKNOWN_LABEL}</b>
					<span>{progress.error}</span>
				</p>
			{:else}
				<h2>
					<span>{repo.name}</span>
					<span class="figure">{progressFigure(progress)}</span>
				</h2>
				{@render bar(progress, repo.name)}
				<ul class="counts">
					<li>{OPEN_COUNT_LABEL} <b>{progress.open}</b></li>
					<li>{UNCUT_COUNT_LABEL} <b>{progress.uncut}</b></li>
					<li class:waiting={progress.waiting > 0}>
						{WAITING_COUNT_LABEL} <b>{progress.waiting}</b>
					</li>
				</ul>
				{#if progress.containers.length === 0}
					<p class="quiet">{NO_CONTAINERS_TEXT}</p>
				{:else}
					<ul class="containers">
						{#each progress.containers as container (container.number)}
							<li>
								<div class="line">
									<span class="title" title={container.title}>
										<span class="number">#{container.number}</span>
										{container.title}
									</span>
									<span class="figure">{progressFigure(container)}</span>
								</div>
								{@render bar(container, container.title)}
							</li>
						{/each}
					</ul>
				{/if}
			{/if}
		</article>
	{/each}
</section>

<style>
	section {
		width: 100%;
		max-width: var(--frame-width);
		margin: 0 auto;
		padding: 0 16px 48px;
	}
	.repo {
		padding: 22px 8px 6px;
	}
	h2 {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
		gap: 12px;
		margin: 0 0 8px;
		font-size: 15px;
		font-weight: 600;
		color: var(--fg);
	}
	.figure {
		flex: none;
		font-weight: 400;
		font-size: 13px;
		color: var(--fg-2);
		font-variant-numeric: tabular-nums;
	}
	.bar {
		height: 8px;
		border-radius: 4px;
		background: var(--surface-2);
		box-shadow: inset 0 0 0 1px var(--line);
		overflow: hidden;
	}
	.bar span {
		display: block;
		height: 100%;
		background: var(--accent);
	}
	.bar.done span {
		background: var(--good);
	}
	.counts {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		list-style: none;
		margin: 10px 0 0;
		padding: 0;
		font-size: 13px;
		color: var(--fg-2);
	}
	.counts li {
		padding: 2px 10px;
		border-radius: 999px;
		background: var(--surface-2);
	}
	.counts li.waiting {
		background: var(--warn-soft);
		color: var(--warn);
	}
	.containers {
		display: grid;
		gap: 14px;
		list-style: none;
		margin: 16px 0 0;
		padding: 0;
	}
	.line {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
		gap: 12px;
		margin-bottom: 4px;
		font-size: 14px;
	}
	.title {
		min-width: 0;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.number {
		color: var(--fg-3);
	}
	.quiet {
		margin: 12px 0 0;
		font-size: 13px;
		color: var(--fg-3);
	}
	.bad-line {
		display: grid;
		grid-template-columns: auto 1fr;
		gap: 2px 8px;
		margin: 0;
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
</style>
