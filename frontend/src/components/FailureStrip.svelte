<script lang="ts">
	import WarnMark from './WarnMark.svelte';

	let { name, message }: { name: string; message: string } = $props();
</script>

<div class="failure">
	<span class="head"><WarnMark />Not saved: {name}</span>
	<span class="why">{message}</span>
</div>

<style>
	.failure {
		display: grid;
		gap: 2px;
		width: 100%;
		max-width: var(--frame-width);
		margin-inline: auto;
		padding: 10px 16px;
		border: 1px solid color-mix(in srgb, var(--warn) 30%, var(--line));
		border-radius: 12px;
		background: var(--warn-soft);
		color: var(--fg);
	}
	.head {
		font-weight: 600;
		color: var(--warn);
	}
	.why {
		color: var(--fg-2);
	}
</style>
