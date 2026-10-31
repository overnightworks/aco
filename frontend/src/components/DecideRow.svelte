<script lang="ts">
	import { tick, type ComponentProps } from 'svelte';
	import {
		acceptAllConfirmation,
		confirmationFor,
		pickedLetter,
		type Confirmation,
		type Pick
	} from '../app/model/card';
	import { STATE_LABEL } from '../app/model/boardSummary';
	import {
		CONFIRM_LABEL,
		chosenText,
		GROUP_LABEL,
		isStuck,
		pickLabel,
		ROW_LABEL
	} from '../app/model/optionCard';
	import { locksCard, type DecisionBanner } from '../app/state/decision.svelte';
	import type { OptionLine } from '../types';
	import EscapeRow from './EscapeRow.svelte';
	import RefusalBanner from './RefusalBanner.svelte';
	import StateShape from './StateShape.svelte';
	import WarnMark from './WarnMark.svelte';

	let {
		points,
		picks,
		pending,
		waiting,
		saving,
		banner,
		onPick,
		onAcceptAll,
		onReload,
		escapes
	}: {
		/** The card's points as shown now. */
		points: readonly OptionLine[];
		/** The picks shown: the held ones while the answer waits, else the live ones. */
		picks: readonly Pick[];
		pending: boolean;
		/** The answer waits in its undo window or is being saved: the picks are held. */
		waiting: boolean;
		/** The answer is being saved (ABRD-100). */
		saving: boolean;
		banner: DecisionBanner | null;
		onPick: (shown: readonly OptionLine[], pick: Pick) => void;
		onAcceptAll: (shown: readonly OptionLine[]) => void;
		onReload: () => void;
		/** The escapes (Other…, Unclear) and their panel; absent where the card offers none. */
		escapes?: Omit<ComponentProps<typeof EscapeRow>, 'points' | 'pending'>;
	} = $props();

	const titleId = $props.id();
	let dialog: HTMLDialogElement | undefined = $state();
	// The card as shown when the confirm opened: a reload under the open
	// dialog must not change what the confirmed verb posts.
	let confirming: { confirmation: Confirmation; confirmed: () => void } | null = $state(null);

	let row: HTMLDivElement | undefined = $state();
	let stuck = $state(false);

	function scrollingAncestor(element: HTMLElement): HTMLElement | null {
		for (
			let ancestor = element.parentElement;
			ancestor !== null;
			ancestor = ancestor.parentElement
		) {
			const { overflowY } = getComputedStyle(ancestor);
			if (overflowY === 'auto' || overflowY === 'scroll') return ancestor;
		}
		return null;
	}

	// The row sticks to the foot of the pane that scrolls its card; the shadow
	// shows while the card still runs on beneath it.
	$effect(() => {
		const container = row?.parentElement;
		const scroller = row ? scrollingAncestor(row) : null;
		if (!container || !scroller) return;
		const measure = () => {
			stuck = isStuck(
				container.getBoundingClientRect().bottom,
				scroller.getBoundingClientRect().bottom
			);
		};
		measure();
		scroller.addEventListener('scroll', measure, { passive: true });
		const resizes = new ResizeObserver(measure);
		resizes.observe(scroller);
		resizes.observe(container);
		return () => {
			scroller.removeEventListener('scroll', measure);
			resizes.disconnect();
		};
	});

	async function ask(confirmation: Confirmation, confirmed: () => void) {
		confirming = { confirmation, confirmed };
		await tick();
		dialog?.showModal();
	}

	/** A pick of the card, from this row or from a point's row: asks first when
	 * the option cannot be taken back. */
	export async function choose(pick: Pick) {
		const shown = points;
		const confirmation = confirmationFor(shown, pick);
		if (confirmation === null) {
			onPick(shown, pick);
			return;
		}
		await ask(confirmation, () => onPick(shown, pick));
	}

	async function acceptAll() {
		const shown = points;
		const confirmation = acceptAllConfirmation(shown);
		if (confirmation === null) {
			onAcceptAll(shown);
			return;
		}
		await ask(confirmation, () => onAcceptAll(shown));
	}

	function decideConfirmed(shown: { confirmed: () => void }) {
		dialog?.close();
		shown.confirmed();
	}
</script>

<div class="decide-row" class:stuck bind:this={row}>
	<dt>{ROW_LABEL.decide}</dt>
	<dd>
		{#if banner !== null}
			<RefusalBanner {banner} {onReload} />
		{/if}
		{#if !locksCard(banner)}
			<div class="bar">
				{#if points.length > 1}
					<button
						type="button"
						class="pick recommended wide"
						disabled={pending}
						aria-label={GROUP_LABEL.acceptAllName}
						onclick={acceptAll}
					>
						{GROUP_LABEL.acceptAll}
					</button>
					<span class="count">{chosenText(picks.length, points.length)}</span>
				{:else}
					{#each points as line (line.index)}
						{@const held = pickedLetter(picks, line)}
						<div class="picks" role="group" aria-label={ROW_LABEL.decide}>
							{#each line.options as option (option.letter)}
								<button
									type="button"
									class="pick"
									class:recommended={!waiting && option.letter === line.recommended}
									class:chosen={waiting && option.letter === held}
									disabled={pending}
									aria-pressed={waiting ? option.letter === held : undefined}
									aria-label={pickLabel(option)}
									onclick={() => choose({ shown: line, option })}
								>
									{option.letter}
								</button>
							{/each}
						</div>
					{/each}
				{/if}
				{#if saving}
					<span class="saving">
						<span aria-hidden="true"><StateShape state="saving" /></span>
						{STATE_LABEL.saving}
					</span>
				{:else if escapes !== undefined}
					<EscapeRow {points} {pending} {...escapes} />
				{/if}
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
				<h2 id={titleId}>{shown.confirmation.title}</h2>
				{#each shown.confirmation.lines as consequence (consequence)}
					<p class="cline"><WarnMark /><span>{consequence}</span></p>
				{/each}
				<div class="actions">
					<button type="button" class="confirm alt" onclick={() => dialog?.close()}>
						{CONFIRM_LABEL.cancel}
					</button>
					<button type="button" class="confirm" onclick={() => decideConfirmed(shown)}>
						{shown.confirmation.verb}
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
		border-top: 1px solid var(--line);
		background: var(--surface);
	}
	.decide-row.stuck {
		box-shadow: 0 -12px 14px -14px rgba(0, 0, 0, 0.28);
	}
	dt {
		font-size: 11px;
		line-height: 40px;
		font-weight: 650;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--fg-3);
	}
	dd {
		margin: 0;
		min-width: 0;
	}
	.bar {
		display: flex;
		flex-wrap: wrap;
		align-items: flex-start;
		gap: 8px;
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
		border: 1.5px solid var(--line-strong);
		border-radius: 8px;
		background: var(--surface);
		font-weight: 700;
	}
	.decide-row button.pick:not(.recommended):hover:enabled {
		border-color: var(--fg-2);
	}
	.decide-row button.pick:disabled:not(.chosen) {
		opacity: 0.55;
		cursor: default;
	}
	.decide-row button.pick.recommended {
		border-color: var(--accent);
		color: var(--accent);
	}
	.decide-row button.pick.chosen {
		border-color: var(--accent);
		background: var(--accent);
		color: var(--accent-fg);
	}
	.saving {
		display: inline-flex;
		gap: 6px;
		align-items: center;
		height: 40px;
		margin-left: auto;
		padding: 0 12px;
		color: var(--good);
		font-weight: 600;
	}
	.decide-row button.pick.wide {
		padding: 0 20px;
		font-weight: 600;
	}
	.count {
		align-self: center;
		font-size: 13px;
		line-height: 18px;
		color: var(--fg-3);
	}
	dialog {
		max-width: min(420px, calc(100vw - 32px));
		padding: 24px;
		border: 1px solid var(--line);
		border-radius: 12px;
		background: var(--surface);
		color: var(--fg);
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
		color: var(--fg-2);
	}
	.cline :global(svg) {
		flex: none;
		color: var(--warn);
	}
	.actions {
		display: flex;
		gap: 8px;
		justify-content: flex-end;
	}
	.decide-row button.confirm {
		height: 40px;
		padding: 0 16px;
		border: 1.5px solid var(--fg);
		border-radius: 8px;
		background: var(--fg);
		color: var(--surface);
		font-weight: 600;
	}
	.decide-row button.confirm.alt {
		border-color: var(--line-strong);
		background: none;
		color: var(--fg);
	}
	@media (max-width: 760px) {
		.count {
			display: none;
		}
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
