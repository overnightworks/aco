<script lang="ts">
	import { tick, type ComponentProps } from 'svelte';
	import {
		acceptAllConfirmation,
		confirmationFor,
		pickedLetter,
		recommendedPicks,
		type Confirmation,
		type Pick
	} from '../app/model/card';
	import { STATE_LABEL } from '../app/model/boardSummary';
	import {
		CONFIRM_LABEL,
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
		held,
		blocked,
		saving,
		banner,
		onPick,
		onAcceptAll,
		onReload,
		escapes
	}: {
		/** The card's points as shown now. */
		points: readonly OptionLine[];
		/** The picks of the answers waiting in their undo window or being saved. */
		held: readonly Pick[];
		/** The points whose controls are disabled: waiting, or the card is reading again. */
		blocked: ReadonlySet<number>;
		/** A point of the card is being saved (ABRD-100). */
		saving: boolean;
		banner: DecisionBanner | null;
		onPick: (shown: readonly OptionLine[], pick: Pick) => void;
		onAcceptAll: (shown: readonly OptionLine[]) => void;
		onReload: () => void;
		/** The escapes the row offers (Unclear on a card of points, Other… and Unclear on a
		 * one-point card) and their panel; absent where the card offers none. */
		escapes?: Omit<ComponentProps<typeof EscapeRow>, 'points' | 'pending' | 'number'>;
	} = $props();

	/** The points a post of the whole row covers: those not waiting. */
	const open = $derived(points.filter((point) => !blocked.has(point.index)));
	const allWaiting = $derived(open.length === 0);
	/** Accept all needs a point with a recommendation that names an option. */
	const nothingToAccept = $derived(recommendedPicks(open).length === 0);

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
		const confirmation = acceptAllConfirmation(shown, open);
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
						disabled={nothingToAccept}
						aria-label={GROUP_LABEL.acceptAllName}
						onclick={acceptAll}
					>
						{GROUP_LABEL.acceptAll}
					</button>
				{:else}
					{#each points as line (line.index)}
						{@const picked = pickedLetter(held, line)}
						{@const waits = blocked.has(line.index)}
						<div class="picks" role="group" aria-label={ROW_LABEL.decide}>
							{#each line.options as option (option.letter)}
								<button
									type="button"
									class="pick"
									class:recommended={!waits && option.letter === line.recommended}
									class:chosen={option.letter === picked}
									disabled={waits}
									aria-pressed={waits ? option.letter === picked : undefined}
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
				{/if}
				{#if escapes !== undefined}
					<EscapeRow {points} pending={allWaiting} {...escapes} />
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
		padding: 16px 0 10px;
		border-top: 1px solid var(--line);
		background: var(--surface);
	}
	.decide-row.stuck {
		box-shadow: 0 -12px 14px -14px var(--shade);
	}
	dt {
		font-family: var(--font-display);
		font-size: 12.5px;
		line-height: 44px;
		font-weight: 400;
		letter-spacing: 0.12em;
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
		min-width: 52px;
		height: 44px;
		padding: 0 12px;
		border: 1.5px solid var(--line-strong);
		border-radius: 10px;
		background: var(--surface);
		font-family: var(--font-display);
		font-size: 18px;
		font-weight: 700;
		transition:
			background-color 0.12s,
			border-color 0.12s,
			color 0.12s;
	}
	@media (prefers-reduced-motion: reduce) {
		.decide-row button.pick {
			transition: none;
		}
	}
	.decide-row button.pick:not(.recommended):hover:enabled {
		border-color: var(--fg-2);
	}
	.decide-row button.pick.recommended {
		border-width: 2px;
		border-color: var(--accent);
		background: var(--accent-soft);
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
		height: 44px;
		margin-left: auto;
		padding: 0 12px;
		color: var(--good);
		font-weight: 600;
	}
	.decide-row button.pick.wide {
		padding: 0 20px;
		font-size: 15px;
		font-weight: 400;
		letter-spacing: 0.08em;
		text-transform: uppercase;
	}
	dialog {
		max-width: min(420px, calc(100vw - 32px));
		padding: 26px 26px 22px;
		border: 1px solid var(--line);
		border-radius: 16px;
		background: var(--surface);
		box-shadow: var(--dialog-shadow);
		color: var(--fg);
	}
	dialog::backdrop {
		background: var(--scrim);
		backdrop-filter: blur(3px);
	}
	dialog h2 {
		margin: 0 0 12px;
		font-size: 19px;
		line-height: 26px;
		font-weight: 600;
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
		height: 44px;
		padding: 0 20px;
		border: 1.5px solid var(--fg);
		border-radius: 10px;
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
		.decide-row {
			grid-template-columns: minmax(0, 1fr);
			padding-top: 12px;
		}
		dt {
			line-height: 18px;
			padding-bottom: 8px;
		}
	}
</style>
