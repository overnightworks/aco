<script lang="ts">
	import type { Snippet } from 'svelte';
	import { cardTitle, pickedLetter, type Pick } from '../app/model/card';
	import {
		GROUP_LABEL,
		hasFinalOption,
		pointGroupLabel,
		pointPickLabel,
		pointsMeta
	} from '../app/model/optionCard';
	import type { CardOption, OptionLine } from '../types';
	import CardFrame from './CardFrame.svelte';
	import CardRow from './CardRow.svelte';
	import OptionRows from './OptionRows.svelte';
	import WarnMark from './WarnMark.svelte';

	let {
		repo,
		item,
		points,
		open,
		picks,
		locked,
		pending,
		refreshing,
		onToggle,
		onPick,
		children
	}: {
		repo: string;
		item: number;
		/** The card's points as shown now, in aco's order. */
		points: readonly OptionLine[];
		/** The line index of the one open point, if any. */
		open: number | null;
		/** The picks that still count. */
		picks: readonly Pick[];
		/** The card needs `Neu laden` before it can be decided. */
		locked: boolean;
		pending: boolean;
		refreshing: boolean;
		onToggle: (index: number) => void;
		onPick: (point: OptionLine, option: CardOption) => void;
		children?: Snippet;
	} = $props();
</script>

<div class="option-card">
	<CardFrame meta={pointsMeta(repo, points)} title={cardTitle(points)}>
		{#each points as point, position (point.index)}
			{@const number = position + 1}
			{@const isOpen = open === point.index}
			{@const picked = pickedLetter(picks, point)}
			<CardRow label={position === 0 ? GROUP_LABEL.points : ''}>
				<div class="point">
					<button
						type="button"
						class="toggle"
						aria-expanded={isOpen}
						onclick={() => onToggle(point.index)}
					>
						<span class="number">{number}</span>
						<span class="question">
							{point.question}
							{#if hasFinalOption(point)}
								<span class="final"><WarnMark /></span>
							{/if}
							<svg class="chevron" aria-hidden="true" viewBox="0 0 16 16" width="16" height="16">
								<path
									d="m4 6 4 4 4-4"
									fill="none"
									stroke="currentColor"
									stroke-width="1.7"
									stroke-linecap="round"
									stroke-linejoin="round"
								/>
							</svg>
						</span>
					</button>
					{#if !locked}
						<div class="picks" role="group" aria-label={pointGroupLabel(number)}>
							{#each point.options as option (option.letter)}
								<button
									type="button"
									class="pick"
									class:recommended={option.letter === point.recommended}
									class:chosen={option.letter === picked}
									aria-pressed={option.letter === picked}
									disabled={pending}
									aria-disabled={refreshing}
									aria-label={pointPickLabel(number, option)}
									onclick={() => {
										if (!refreshing) onPick(point, option);
									}}
								>
									{option.letter}
								</button>
							{/each}
						</div>
					{/if}
				</div>
			</CardRow>
			{#if isOpen}
				<OptionRows {repo} {item} line={point} />
			{/if}
		{/each}
		{@render children?.()}
	</CardFrame>
</div>

<style>
	.point {
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto;
		align-items: center;
		gap: 12px;
	}
	button.toggle {
		display: grid;
		grid-template-columns: 20px minmax(0, 1fr);
		column-gap: 8px;
		align-items: start;
		padding: 0;
		border: 0;
		background: none;
		font: inherit;
		color: inherit;
		text-align: left;
		cursor: pointer;
	}
	.number {
		font-weight: 700;
		color: var(--fg-3);
	}
	.question {
		font-weight: 600;
	}
	button.toggle:hover .question {
		text-decoration: underline;
		text-underline-offset: 3px;
	}
	.final {
		display: inline-flex;
		margin-left: 6px;
		color: var(--warn);
	}
	.chevron {
		display: inline-block;
		margin-left: 4px;
		vertical-align: -3px;
		color: var(--fg-3);
		transition: transform 0.15s;
	}
	button[aria-expanded='true'] .chevron {
		transform: rotate(180deg);
	}
	@media (prefers-reduced-motion: reduce) {
		.chevron {
			transition: none;
		}
	}
	.picks {
		display: flex;
		gap: 6px;
	}
	.point button.pick {
		min-width: 40px;
		height: 32px;
		padding: 0 10px;
		border: 1.5px solid var(--line-strong);
		border-radius: 8px;
		background: var(--surface);
		font-weight: 700;
	}
	.point button.pick.recommended {
		border-color: var(--accent);
		color: var(--accent);
	}
	.point button.pick.chosen {
		border-color: var(--accent);
		background: var(--accent);
		color: var(--accent-fg);
	}
	.point button.pick:not(.recommended):not(.chosen):hover:enabled:not([aria-disabled='true']) {
		border-color: var(--fg-2);
	}
	.point button.pick[aria-disabled='true'] {
		opacity: 0.55;
		cursor: default;
	}
	@media (max-width: 760px) {
		.point {
			grid-template-columns: minmax(0, 1fr);
		}
	}
</style>
