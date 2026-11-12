<script lang="ts">
	import type { Snippet } from 'svelte';

	let { label, children }: { label: string; children: Snippet } = $props();
</script>

<div class="row">
	<dt>{label}</dt>
	<dd>{@render children()}</dd>
</div>

<style>
	.row {
		display: grid;
		grid-template-columns: var(--oc-label-width) minmax(0, 1fr);
		column-gap: var(--oc-column-gap);
		align-items: start;
	}
	dt {
		font-family: var(--font-display);
		font-size: 12.5px;
		line-height: 23px;
		font-weight: 400;
		letter-spacing: 0.12em;
		text-transform: uppercase;
		color: var(--fg-3);
	}
	dd {
		margin: 0;
		min-width: 0;
	}
	@media (max-width: 760px) {
		.row {
			grid-template-columns: minmax(0, 1fr);
		}
		dt {
			line-height: 16px;
		}
	}
</style>
