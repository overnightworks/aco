<script lang="ts">
	import QuietSign from './QuietSign.svelte';

	let { note }: { note: string } = $props();
</script>

<div class="note" role="status"><QuietSign kind="warn" />{note}</div>

<style>
	.note {
		display: flex;
		align-items: center;
		gap: 8px;
		width: 100%;
		max-width: var(--frame-width);
		margin: 0 auto 12px;
		padding: 10px 16px;
		border-radius: 10px;
		background: var(--warn-soft);
		color: var(--fg);
		font-size: 14px;
	}
</style>
