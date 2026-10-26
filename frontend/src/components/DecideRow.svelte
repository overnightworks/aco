<script lang="ts">
	import { tick } from 'svelte';
	import {
		asksToConfirm,
		CONFIRM_LABEL,
		confirmTitle,
		confirmVerb,
		consequenceText,
		pickLabel,
		ROW_LABEL
	} from '../app/model/optionCard';
	import { locksCard, type DecisionBanner } from '../app/state/decision.svelte';
	import type { CardOption, OptionLine } from '../types';
	import RefusalBanner from './RefusalBanner.svelte';
	import WarnMark from './WarnMark.svelte';

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
		onDecide: (line: OptionLine, option: CardOption) => void;
		onReload: () => void;
	} = $props();

	const titleId = $props.id();
	let dialog: HTMLDialogElement | undefined = $state();
	// The card as shown when the confirm opened: a reload under the open
	// dialog must not change what `Decide <X>` posts.
	let confirming: { line: OptionLine; option: CardOption } | null = $state(null);

	async function pick(option: CardOption) {
		if (!asksToConfirm(option)) {
			onDecide(line, option);
			return;
		}
		confirming = { line, option };
		await tick();
		dialog?.showModal();
	}

	function decideConfirmed(shown: { line: OptionLine; option: CardOption }) {
		dialog?.close();
		onDecide(shown.line, shown.option);
	}
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
						onclick={() => pick(option)}
					>
						{option.letter}
					</button>
				{/each}
			</div>
		{/if}
		<dialog
			bind:this={dialog}
			aria-labelledby={titleId}
			onclose={() => {
				confirming = null;
			}}
		>
			{#if confirming !== null}
				{@const shown = confirming}
				<h2 id={titleId}>{confirmTitle(shown.option)}</h2>
				<p class="cline"><WarnMark /><span>{consequenceText(shown.option)}</span></p>
				<div class="actions">
					<button type="button" class="confirm alt" onclick={() => dialog?.close()}>
						{CONFIRM_LABEL.cancel}
					</button>
					<button type="button" class="confirm" onclick={() => decideConfirmed(shown)}>
						{confirmVerb(shown.option)}
					</button>
				</div>
			{/if}
		</dialog>
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
	dialog {
		max-width: min(420px, calc(100vw - 32px));
		padding: 24px;
		border: 1px solid var(--oc-line);
		border-radius: 12px;
		background: var(--oc-surface);
		color: var(--oc-fg);
	}
	dialog::backdrop {
		background: rgba(10, 8, 14, 0.45);
	}
	dialog h2 {
		margin: 0 0 8px;
		font-size: 15px;
		line-height: 22px;
	}
	.cline {
		display: flex;
		gap: 8px;
		align-items: baseline;
		margin: 0 0 16px;
		color: var(--oc-fg-2);
	}
	.cline :global(svg) {
		flex: none;
		color: var(--oc-warn);
	}
	.actions {
		display: flex;
		gap: 8px;
		justify-content: flex-end;
	}
	.decide-row button.confirm {
		height: 40px;
		padding: 0 16px;
		border: 1.5px solid var(--oc-fg);
		border-radius: 8px;
		background: var(--oc-fg);
		color: var(--oc-surface);
		font-weight: 600;
	}
	.decide-row button.confirm.alt {
		border-color: var(--oc-line-strong);
		background: none;
		color: var(--oc-fg);
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
