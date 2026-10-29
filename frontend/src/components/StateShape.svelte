<script lang="ts">
	import { STATE_LABEL, type RowState } from '../app/model/boardSummary';

	let { state }: { state: RowState } = $props();

	const label = $derived(STATE_LABEL[state]);
</script>

<span class="shape {state}" role="img" aria-label={label} title={label}>
	<svg viewBox="0 0 14 14" width="14" height="14" aria-hidden="true">
		{#if state === 'done'}
			<circle cx="7" cy="7" r="6.2" fill="currentColor" />
			<path
				d="m4.3 7.2 1.9 1.9 3.5-3.9"
				fill="none"
				stroke="var(--surface)"
				stroke-width="1.7"
				stroke-linecap="round"
				stroke-linejoin="round"
			/>
		{:else}
			<circle cx="7" cy="7" r="5.6" fill="none" stroke="currentColor" stroke-width="1.6" />
			{#if state === 'back'}
				<path
					d="M8.6 4.6 6.2 7l2.4 2.4"
					fill="none"
					stroke="currentColor"
					stroke-width="1.6"
					stroke-linecap="round"
					stroke-linejoin="round"
				/>
			{/if}
		{/if}
	</svg>
</span>

<style>
	.shape {
		display: inline-flex;
		flex: none;
		color: var(--fg-2);
	}
	.back {
		color: var(--fg-3);
	}
	.done {
		color: var(--good);
	}
	svg {
		display: block;
	}
</style>
