<script lang="ts">
	import {
		cardHeading,
		cardSentence,
		EMPTY_HISTORY_MESSAGE,
		DECIDED_TAB_LABEL,
		historyLines,
		outcomeLabel,
		UNKNOWN_DATE_LABEL
	} from '../app/model/boardSummary';
	import { lineKey } from '../app/model/decision';
	import { chosenOption, contractTexts, isOptionLine, verdictLabel } from '../app/model/optionCard';
	import type { RepoReading } from '../types';
	let { repos }: { repos: RepoReading[] } = $props();
	const entries = $derived(historyLines(repos));
</script>

<section aria-label={DECIDED_TAB_LABEL}>
	{#each repos.filter((repo) => repo.error !== null) as repo (repo.name)}
		<p role="alert">{repo.name}: {repo.error}</p>
	{/each}
	{#if entries.length === 0}<p>{EMPTY_HISTORY_MESSAGE}</p>{/if}
	{#each entries as entry (lineKey(entry.repo, entry.item.number, entry.line))}
		{@const sentence = cardSentence(entry.line)}
		{@const chosen = isOptionLine(entry.line) ? chosenOption(entry.line) : undefined}
		{#snippet heading()}
			<strong>{cardHeading(entry.line)}</strong>
			<span class="metadata">
				{#if chosen !== undefined}
					<span class="verdict chosen">
						<svg
							aria-hidden="true"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="2"
							stroke-linecap="round"
							stroke-linejoin="round"
						>
							<path d="M5 12l5 5 9-10" />
						</svg>
						{verdictLabel(chosen)}
					</span>
				{:else if !isOptionLine(entry.line) && entry.line.ruling !== null}
					<span class="verdict {entry.line.ruling}">
						<svg
							aria-hidden="true"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="2"
							stroke-linecap="round"
							stroke-linejoin="round"
						>
							{#if entry.line.ruling === 'yes'}
								<path d="M5 12l5 5 9-10" />
							{:else if entry.line.ruling === 'no'}
								<path d="M6 6l12 12M18 6L6 18" />
							{:else}
								<circle cx="12" cy="12" r="8" /><path d="M12 8v4l3 2" />
							{/if}
						</svg>
						{outcomeLabel(entry.line.ruling)}
					</span>
				{/if}
				<span>· {entry.line.ruled_on ?? UNKNOWN_DATE_LABEL}</span>
			</span>
			<small>{entry.repo} · #{entry.item.number} · {entry.item.title}</small>
		{/snippet}
		{#if sentence !== null}
			<details>
				<summary>{@render heading()}</summary>
				{#if chosen !== undefined && isOptionLine(entry.line)}
					{#each contractTexts(entry.line, chosen) as bindingSentence (bindingSentence)}
						<p>{bindingSentence}</p>
					{/each}
				{:else}
					<p>{sentence}</p>
				{/if}
			</details>
		{:else}
			<article>{@render heading()}</article>
		{/if}
	{/each}
</section>

<style>
	section {
		max-width: 960px;
		margin-inline: auto;
		padding: 24px;
	}
	details,
	article {
		background: white;
		border: 1px solid #c9c4d4;
		border-radius: 12px;
		margin-bottom: 12px;
		padding: 16px;
	}
	summary {
		cursor: pointer;
	}
	.metadata,
	small {
		display: block;
		margin-top: 6px;
		color: #4d4759;
	}
	.metadata {
		display: flex;
		align-items: center;
		gap: 6px;
		flex-wrap: wrap;
	}
	.verdict {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		font-size: 12px;
		font-weight: 600;
		padding: 2px 9px;
		border-radius: 999px;
		white-space: nowrap;
	}
	.verdict svg {
		width: 12px;
		height: 12px;
	}
	.verdict.yes {
		background: #e2f2ea;
		color: #1f7a52;
	}
	.verdict.no {
		background: #fbe7e7;
		color: #c42f2f;
	}
	.verdict.chosen {
		background: #f6e9f1;
		color: #7d2459;
	}
	.verdict.later {
		background: #f8eeda;
		color: #9a6514;
	}
	strong {
		font-size: 18px;
	}
</style>
