<script lang="ts">
	import { STATE_LABEL, type StripState } from '../app/model/boardSummary';
	import StateShape from './StateShape.svelte';

	let { message, kind, onUndo }: { message: string; kind: StripState; onUndo: () => void } =
		$props();

	let undo: HTMLButtonElement | undefined = $state();

	// A strip mounts when a pick starts its undo window, so this is focus after a
	// pick: the pressed pick is disabled by now and Undo is the one action left.
	$effect(() => {
		undo?.focus();
	});
</script>

<div class="strip" class:back={kind === 'back'}>
	<StateShape state={kind} />
	<span class="tx">{STATE_LABEL[kind]}: {message}</span>
	<button type="button" class="undo" bind:this={undo} onclick={onUndo}>Undo</button>
</div>

<style>
	.strip {
		display: flex;
		align-items: center;
		gap: 12px;
		width: 100%;
		max-width: var(--frame-width);
		margin-inline: auto;
		padding: 8px 8px 8px 16px;
		border-radius: 10px;
		background: var(--good-soft);
		color: var(--fg);
	}
	.strip.back {
		background: var(--surface-2);
	}
	.tx {
		flex: 1;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.undo {
		flex: none;
		height: 40px;
		padding: 0 12px;
		border: 0;
		border-radius: 8px;
		background: none;
		color: var(--fg-2);
		font-weight: 500;
	}
	.undo:hover {
		background: var(--surface-2);
		color: var(--fg);
	}
</style>
