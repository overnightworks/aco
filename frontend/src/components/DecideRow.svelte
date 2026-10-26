<script lang="ts">
	import { pickLabel, ROW_LABEL } from '../app/model/optionCard';
	import { locksCard, type DecisionBanner } from '../app/state/decision.svelte';
	import type { CardOption, OptionLine } from '../types';
	import RefusalBanner from './RefusalBanner.svelte';

	let {
		line,
		pending,
		banner,
		onDecide,
		onReload
	}: {
		line: OptionLine;
		pending: boolean;
		banner: DecisionBanner | null;
		onDecide: (option: CardOption) => void;
		onReload: () => void;
	} = $props();
</script>

<div class="decide-row">
	<dt>{ROW_LABEL.decide}</dt>
	<dd>
		{#if banner !== null}
			<RefusalBanner {banner} {onReload} />
		{/if}
		{#if !locksCard(banner)}
			<div class="picks" role="group" aria-label={ROW_LABEL.decide}>
				{#each line.options as option (option.letter)}
					<button
						type="button"
						class="pick"
						class:recommended={option.letter === line.recommended}
						disabled={pending}
						aria-label={pickLabel(option)}
						onclick={() => onDecide(option)}
					>
						{option.letter}
					</button>
				{/each}
			</div>
		{/if}
	</dd>
</div>

<style>
	.decide-row {
		display: grid;
		grid-template-columns: var(--oc-label-width) minmax(0, 1fr);
		column-gap: var(--oc-column-gap);
		align-items: start;
		position: sticky;
		bottom: 0;
		z-index: 2;
		margin-top: 4px;
		padding: 16px 0 8px;
		border-top: 1px solid var(--oc-line);
		background: var(--oc-surface);
	}
	dt {
		font-size: 11px;
		line-height: 40px;
		font-weight: 650;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--oc-fg-3);
	}
	dd {
		margin: 0;
		min-width: 0;
	}
	.picks {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
	}
	.decide-row button.pick {
		min-width: 48px;
		height: 40px;
		padding: 0 12px;
		border: 1.5px solid var(--oc-line-strong);
		border-radius: 8px;
		background: var(--oc-surface);
		font-weight: 700;
	}
	.decide-row button.pick:not(.recommended):hover:enabled {
		border-color: var(--oc-fg-2);
	}
	.decide-row button.pick.recommended {
		border-color: var(--oc-accent);
		color: var(--oc-accent);
	}
	@media (max-width: 760px) {
		.decide-row {
			grid-template-columns: minmax(0, 1fr);
			padding-top: 12px;
		}
		dt {
			line-height: 16px;
			padding-bottom: 4px;
		}
	}
</style>
