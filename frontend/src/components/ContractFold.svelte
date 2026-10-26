<script lang="ts">
	import { CONTRACT_SUMMARY } from '../app/model/optionCard';

	let { sentences, source }: { sentences: readonly string[]; source: string } = $props();
</script>

<details class="contract">
	<summary class="fold">{CONTRACT_SUMMARY}</summary>
	<div class="binding">
		{#each sentences as sentence (sentence)}
			<p>{sentence}</p>
		{/each}
		<span class="source">{source}</span>
	</div>
</details>

<style>
	p {
		margin: 0;
	}
	.contract > summary.fold {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		padding-block: 0;
		list-style: none;
		cursor: pointer;
		color: var(--fg-2);
	}
	summary::-webkit-details-marker {
		display: none;
	}
	summary::before {
		content: '';
		width: 0;
		height: 0;
		border-left: 5px solid currentColor;
		border-top: 4px solid transparent;
		border-bottom: 4px solid transparent;
	}
	details[open] summary::before {
		transform: rotate(90deg);
	}
	.binding {
		display: grid;
		gap: 8px;
		margin-top: 8px;
		padding-left: 12px;
		border-left: 2px solid var(--line-strong);
		font-size: 13px;
		line-height: 18px;
		color: var(--fg-2);
	}
	.source {
		font-family: ui-monospace, 'DejaVu Sans Mono', Menlo, Consolas, monospace;
		font-size: 12px;
		color: var(--fg-3);
	}
</style>
