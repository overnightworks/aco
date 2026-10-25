<script lang="ts">
	import {
		cardHeading,
		cardSentence,
		EMPTY_HISTORY_MESSAGE,
		HISTORY_LABEL,
		historyLines,
		outcomeLabel,
		UNKNOWN_DATE_LABEL
	} from '../app/model/boardSummary';
	import { lineKey } from '../app/model/decision';
	import type { RepoReading } from '../types';
	let { repos }: { repos: RepoReading[] } = $props();
	const entries = $derived(historyLines(repos));
</script>

<section aria-label={HISTORY_LABEL}>
	{#each repos.filter((repo) => repo.error !== null) as repo (repo.name)}
		<p role="alert">{repo.name}: {repo.error}</p>
	{/each}
	{#if entries.length === 0}<p>{EMPTY_HISTORY_MESSAGE}</p>{/if}
	{#each entries as entry (lineKey(entry.repo, entry.item.number, entry.line))}
		<details>
			<summary>
				<strong>{cardHeading(entry.line)}</strong>
				<span
					>{entry.line.ruling === null ? '' : outcomeLabel(entry.line.ruling)} · {entry.line
						.ruled_on ?? UNKNOWN_DATE_LABEL}</span
				>
				<small>{entry.repo} · #{entry.item.number} · {entry.item.title}</small>
			</summary>
			{#if cardSentence(entry.line)}<p>{cardSentence(entry.line)}</p>{/if}
		</details>
	{/each}
</section>

<style>
	section {
		max-width: 960px;
		margin-inline: auto;
		padding: 24px;
	}
	details {
		background: white;
		border: 1px solid #c9c4d4;
		border-radius: 12px;
		margin-bottom: 12px;
		padding: 16px;
	}
	summary {
		cursor: pointer;
	}
	summary span,
	small {
		display: block;
		margin-top: 6px;
		color: #4d4759;
	}
	strong {
		font-size: 18px;
	}
</style>
