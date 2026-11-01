<script lang="ts">
	import { clockTime, refreshLabel, refreshName } from '../app/model/boardSummary';

	let {
		reading,
		readAt,
		onRefresh
	}: { reading: boolean; readAt: Date | null; onRefresh: () => void } = $props();

	const name = $derived(refreshName(reading, readAt));
</script>

<!-- aria-busy, never disabled: focus stays on the button and a click asks for one more read. -->
<button
	type="button"
	class="refresh"
	aria-busy={reading}
	aria-label={name}
	title={name}
	onclick={onRefresh}
>
	<span class="arrow" aria-hidden="true">
		<svg viewBox="0 0 16 16" width="15" height="15">
			<path
				d="M13 8a5 5 0 1 1-1.5-3.6"
				fill="none"
				stroke="currentColor"
				stroke-width="1.5"
				stroke-linecap="round"
			/>
			<path
				d="M12 1.8v3h-3"
				fill="none"
				stroke="currentColor"
				stroke-width="1.5"
				stroke-linecap="round"
				stroke-linejoin="round"
			/>
		</svg>
	</span>
	<span class="label">{refreshLabel(reading)}</span>
	{#if readAt !== null}<span class="at">{clockTime(readAt)}</span>{/if}
</button>

<style>
	.refresh {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		height: 32px;
		padding: 0 8px;
		border: 0;
		border-radius: 8px;
		background: none;
		color: var(--fg-2);
		font-size: 13px;
		font-weight: 550;
		white-space: nowrap;
	}
	.refresh:hover {
		background: var(--surface-2);
		color: var(--fg);
	}
	.refresh[aria-busy='true'] {
		cursor: progress;
	}
	.arrow {
		display: inline-flex;
	}
	.refresh[aria-busy='true'] .arrow {
		animation: turn 1s linear infinite;
		transform-origin: 50% 50%;
	}
	.at {
		color: var(--fg-3);
		font-weight: 450;
	}
	@keyframes turn {
		to {
			transform: rotate(360deg);
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.refresh[aria-busy='true'] .arrow {
			animation: none;
		}
	}
	@media (max-width: 760px) {
		.refresh {
			padding: 0 4px;
			gap: 2px;
		}
		.label {
			display: none;
		}
	}
</style>
