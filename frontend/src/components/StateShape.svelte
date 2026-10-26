<script lang="ts">
	import { STATE_LABEL, type RowState } from '../app/model/boardSummary';

	let { state }: { state: RowState } = $props();

	const label = $derived(STATE_LABEL[state]);
</script>

<span class="shape {state}" role="img" aria-label={label} title={label}>
	<svg viewBox="0 0 14 14" width="14" height="14" aria-hidden="true">
		<circle
			cx="7"
			cy="7"
			r="5.6"
			fill="none"
			stroke="currentColor"
			stroke-width="1.6"
			stroke-dasharray={state === 'todo' ? '2.4 2.2' : undefined}
		/>
	</svg>
</span>

<style>
	.shape {
		display: inline-flex;
		flex: none;
		color: var(--fg-2);
	}
	.todo {
		color: var(--fg-3);
	}
	svg {
		display: block;
	}
</style>
