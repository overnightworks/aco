<script lang="ts">
	let { message, onUndo }: { message: string; onUndo: () => void } = $props();
</script>

<div class="toast" role="status">
	<span class="msg">{message}</span>
	<button type="button" onclick={onUndo}>Rückgängig</button>
</div>
