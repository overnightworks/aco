<script lang="ts">
	import type { Snippet } from 'svelte';
	import {
		cardMeta,
		chosenOption,
		decidedText,
		nextOpenOption,
		type OpenOption,
		ROW_LABEL
	} from '../app/model/optionCard';
	import type { OptionLine } from '../types';
	import CardFrame from './CardFrame.svelte';
	import CardRow from './CardRow.svelte';
	import EnlargeablePicture from './EnlargeablePicture.svelte';
	import OptionDetails from './OptionDetails.svelte';

	let {
		repo,
		item,
		line,
		children
	}: { repo: string; item: number; line: OptionLine; children?: Snippet } = $props();

	let openOption: OpenOption = $state(null);

	const chosen = $derived(chosenOption(line));
</script>

<div class="option-card">
	<CardFrame meta={cardMeta(repo, line)} title={line.question}>
		{#if chosen !== undefined}
			<CardRow label={ROW_LABEL.decided}>
				<div class="decided">
					<svg aria-hidden="true" viewBox="0 0 14 14" width="14" height="14">
						<circle cx="7" cy="7" r="6.2" fill="currentColor" />
						<path
							d="m4.3 7.2 1.9 1.9 3.5-3.9"
							fill="none"
							stroke-width="1.7"
							stroke-linecap="round"
							stroke-linejoin="round"
						/>
					</svg>
					<p>{decidedText(chosen)}</p>
					<p class="date">{line.ruled_on}</p>
				</div>
			</CardRow>
		{/if}
		<CardRow label={ROW_LABEL.problem}>
			<p>{line.problem}</p>
		</CardRow>
		<CardRow label={ROW_LABEL.today}>
			<EnlargeablePicture
				picture={line.picture}
				alt={line.caption}
				caption={line.caption}
				thumbnail
			/>
		</CardRow>
		<CardRow label={ROW_LABEL.options}>
			<ol aria-label={ROW_LABEL.options}>
				{#each line.options as option (option.letter)}
					{@const isOpen = openOption === option.letter}
					<li aria-current={option.letter === line.ruling ? 'true' : undefined}>
						<button
							type="button"
							class="disclosure"
							aria-expanded={isOpen}
							onclick={() => (openOption = nextOpenOption(openOption, option.letter))}
						>
							<span class="letter" class:chosen={option.letter === line.ruling}
								>{option.letter}</span
							>
							<span>
								<strong>{option.name}</strong>
								<span class="effect">{option.effect}</span>
							</span>
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
						</button>
						{#if isOpen}
							<OptionDetails {repo} {item} {line} {option} />
						{/if}
					</li>
				{/each}
			</ol>
		</CardRow>
		<CardRow label={ROW_LABEL.recommendation}>
			<div class="recommendation">
				<span class="letter recommended">{line.recommended}</span>
				<p>{line.reason}</p>
			</div>
		</CardRow>
		{@render children?.()}
	</CardFrame>
</div>

<style>
	p {
		margin: 0;
	}
	ol {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	li + li {
		border-top: 1px solid var(--line);
		margin-top: 8px;
	}
	.option-card button.disclosure {
		display: grid;
		grid-template-columns: 24px minmax(0, 1fr) 16px;
		column-gap: 12px;
		align-items: start;
		width: 100%;
		padding: 4px 0;
		border: 0;
		border-radius: 6px;
		background: none;
		font: inherit;
		color: inherit;
		text-align: left;
		cursor: pointer;
	}
	.option-card li + li > button.disclosure {
		padding-top: 12px;
	}
	button:hover strong {
		text-decoration: underline;
		text-underline-offset: 3px;
	}
	.chevron {
		margin-top: 3px;
		color: var(--fg-3);
		transition: transform 0.15s;
	}
	button[aria-expanded='true'] .chevron {
		transform: rotate(180deg);
	}
	li + li > button .chevron {
		margin-top: 11px;
	}
	@media (prefers-reduced-motion: reduce) {
		.chevron {
			transition: none;
		}
	}
	strong {
		display: block;
		font-weight: 600;
	}
	.effect {
		display: block;
		color: var(--fg-2);
	}
	.letter {
		display: grid;
		place-items: center;
		width: 24px;
		height: 24px;
		margin-top: -1px;
		border: 1.5px solid var(--line-strong);
		border-radius: 50%;
		font-size: 13px;
		font-weight: 700;
		line-height: 1;
		color: var(--fg-2);
	}
	.letter.recommended {
		border-color: var(--accent);
		color: var(--accent);
	}
	.letter.chosen {
		background: var(--accent);
		border-color: var(--accent);
		color: var(--accent-fg);
	}
	.recommendation {
		display: flex;
		align-items: start;
		gap: 12px;
	}
	.decided {
		display: flex;
		align-items: start;
		flex-wrap: wrap;
		gap: 4px 12px;
	}
	.decided svg {
		flex: none;
		margin-top: 4px;
		color: var(--good);
	}
	.decided path {
		stroke: var(--surface);
	}
	.date {
		color: var(--fg-2);
	}
</style>
