<script lang="ts">
	import { STATE_LABEL, type StripState } from '../app/model/boardSummary';
	import { UNDO_SECONDS } from '../app/model/decision';
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

<div class="strip" class:back={kind === 'back'} style:--undo-seconds="{UNDO_SECONDS}s">
	<StateShape state={kind} />
	<span class="tx">{STATE_LABEL[kind]}: {message}</span>
	<button type="button" class="undo" bind:this={undo} onclick={onUndo}>Undo</button>
	<span class="drain" aria-hidden="true"></span>
</div>

<style>
	.strip {
		position: relative;
		overflow: hidden;
		display: flex;
		align-items: center;
		gap: 12px;
		width: 100%;
		max-width: var(--frame-width);
		margin-inline: auto;
		padding: 10px 10px 10px 16px;
		border: 1px solid color-mix(in srgb, var(--good) 28%, transparent);
		border-radius: 12px;
		background: var(--good-soft);
		color: var(--fg);
		font-weight: 600;
	}
	.strip.back {
		border-color: var(--line-strong);
		background: var(--surface-2);
	}
	.tx {
		flex: 1;
		min-width: 0;
	}
	.undo {
		flex: none;
		height: 40px;
		padding: 0 18px;
		border: 1.5px solid color-mix(in srgb, var(--good) 45%, var(--line-strong));
		border-radius: 10px;
		background: var(--surface);
		color: var(--fg);
		font-weight: 600;
	}
	.undo:hover {
		border-color: var(--fg-2);
	}
	.drain {
		position: absolute;
		inset: auto 0 0;
		height: 3px;
		background: var(--good);
		transform-origin: left center;
		animation: drain var(--undo-seconds) linear forwards;
	}
	.back .drain {
		background: var(--fg-3);
	}
	@keyframes drain {
		from {
			transform: scaleX(1);
		}
		to {
			transform: scaleX(0);
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.drain {
			animation: none;
		}
	}
	@media (max-width: 760px) {
		.tx {
			line-height: 20px;
		}
	}
</style>
