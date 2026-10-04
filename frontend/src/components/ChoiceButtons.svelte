<script lang="ts">
	import { OUTCOMES, outcomeLabel } from '../app/model/boardSummary';
	import type { Outcome } from '../types';

	let {
		default: recommended,
		disabled,
		onChoose
	}: {
		default: Outcome | null;
		disabled: boolean;
		onChoose: (outcome: Outcome) => void;
	} = $props();
</script>

<div class="choices" role="group" aria-label="Entscheidung">
	{#each OUTCOMES as outcome (outcome)}
		<button type="button" {disabled} onclick={() => onChoose(outcome)}>
			{#if outcome === recommended}
				<span class="rec-tag">Empfohlen</span>
			{/if}
			{outcomeLabel(outcome)}
		</button>
	{/each}
</div>
