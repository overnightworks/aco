<script lang="ts">
	import { pictureDataUri } from '../app/model/boardSummary';
	import {
		cardMeta,
		chosenOption,
		decidedText,
		ROW_LABEL,
		UNDO_LABEL
	} from '../app/model/optionCard';
	import type { OptionLine } from '../types';

	let { repo, line }: { repo: string; line: OptionLine } = $props();

	const meta = $derived(cardMeta(repo, line));
	const chosen = $derived(chosenOption(line));
</script>

<div class="option-card">
	<p class="meta">
		<span>{meta.where}</span>
		<span class="sep" aria-hidden="true">·</span>
		<span>{meta.kind}</span>
		<span class="sep" aria-hidden="true">·</span>
		{#if meta.undo === 'final'}
			<span class="final">
				<svg aria-hidden="true" viewBox="0 0 14 14" width="12" height="12">
					<path
						d="M7 1.6 13 12.4H1z"
						fill="none"
						stroke="currentColor"
						stroke-width="1.6"
						stroke-linejoin="round"
					/>
					<path
						d="M7 5.6v3.2M7 10.4v.1"
						stroke="currentColor"
						stroke-width="1.6"
						stroke-linecap="round"
					/>
				</svg>
				{UNDO_LABEL[meta.undo]}
			</span>
		{:else}
			<span>{UNDO_LABEL[meta.undo]}</span>
		{/if}
	</p>
	<article>
		<h2>{line.question}</h2>
		<dl>
			{#if chosen !== undefined}
				<div class="row">
					<dt>{ROW_LABEL.decided}</dt>
					<dd class="decided">
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
					</dd>
				</div>
			{/if}
			<div class="row">
				<dt>{ROW_LABEL.problem}</dt>
				<dd><p>{line.problem}</p></dd>
			</div>
			<div class="row">
				<dt>{ROW_LABEL.today}</dt>
				<dd>
					<img src={pictureDataUri(line.picture)} alt={line.caption} />
					<p class="caption">{line.caption}</p>
				</dd>
			</div>
			<div class="row">
				<dt>{ROW_LABEL.options}</dt>
				<dd>
					<ol aria-label={ROW_LABEL.options}>
						{#each line.options as option (option.letter)}
							<li aria-current={option.letter === line.ruling ? 'true' : undefined}>
								<span class="letter" class:chosen={option.letter === line.ruling}
									>{option.letter}</span
								>
								<span>
									<strong>{option.name}</strong>
									<span class="effect">{option.effect}</span>
								</span>
							</li>
						{/each}
					</ol>
				</dd>
			</div>
			<div class="row">
				<dt>{ROW_LABEL.recommendation}</dt>
				<dd class="recommendation">
					<span class="letter recommended">{line.recommended}</span>
					<p>{line.reason}</p>
				</dd>
			</div>
		</dl>
	</article>
</div>

<style>
	.option-card {
		--oc-surface: #ffffff;
		--oc-line: #e5e2ea;
		--oc-line-strong: #cdc8d5;
		--oc-fg-2: #4d4758;
		--oc-fg-3: #6e6779;
		--oc-accent: #7d2459;
		--oc-accent-fg: #ffffff;
		--oc-good: #1c7350;
		--oc-warn: #99570c;
		max-width: 880px;
		margin-inline: auto;
	}
	.meta {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: 0 8px;
		margin: 0 0 8px 2px;
		font-size: 13px;
		line-height: 18px;
		color: var(--oc-fg-3);
	}
	.sep {
		opacity: 0.6;
	}
	.final {
		color: var(--oc-warn);
		font-weight: 600;
	}
	.final svg {
		vertical-align: -1px;
		margin-right: 4px;
	}
	article {
		background: var(--oc-surface);
		border: 1px solid var(--oc-line);
		border-radius: 12px;
		padding: 24px 32px 32px;
	}
	h2 {
		margin: 0 0 24px;
		font-size: 22px;
		line-height: 28px;
		font-weight: 650;
		letter-spacing: -0.01em;
	}
	dl {
		display: grid;
		row-gap: 16px;
		margin: 0;
	}
	.row {
		display: grid;
		grid-template-columns: 136px minmax(0, 1fr);
		column-gap: 24px;
		align-items: start;
	}
	dt {
		font-size: 11px;
		line-height: 22px;
		font-weight: 650;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--oc-fg-3);
	}
	dd {
		margin: 0;
		min-width: 0;
	}
	p {
		margin: 0;
	}
	img {
		display: block;
		max-width: 100%;
		height: auto;
	}
	.caption {
		margin-top: 8px;
		font-size: 13px;
		line-height: 18px;
		color: var(--oc-fg-2);
	}
	ol {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	li {
		display: grid;
		grid-template-columns: 24px minmax(0, 1fr);
		column-gap: 12px;
		align-items: start;
		padding: 4px 0;
	}
	li + li {
		border-top: 1px solid var(--oc-line);
		margin-top: 8px;
		padding-top: 12px;
	}
	strong {
		display: block;
		font-weight: 600;
	}
	.effect {
		display: block;
		color: var(--oc-fg-2);
	}
	.letter {
		display: grid;
		place-items: center;
		width: 24px;
		height: 24px;
		margin-top: -1px;
		border: 1.5px solid var(--oc-line-strong);
		border-radius: 50%;
		font-size: 13px;
		font-weight: 700;
		line-height: 1;
		color: var(--oc-fg-2);
	}
	.letter.recommended {
		border-color: var(--oc-accent);
		color: var(--oc-accent);
	}
	.letter.chosen {
		background: var(--oc-accent);
		border-color: var(--oc-accent);
		color: var(--oc-accent-fg);
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
		color: var(--oc-good);
	}
	.decided path {
		stroke: var(--oc-surface);
	}
	.date {
		color: var(--oc-fg-2);
	}
	@media (max-width: 760px) {
		article {
			padding: 16px;
		}
		h2 {
			font-size: 20px;
			line-height: 26px;
			margin-bottom: 16px;
		}
		dl {
			row-gap: 12px;
		}
		.row {
			grid-template-columns: minmax(0, 1fr);
		}
		dt {
			line-height: 16px;
		}
	}
</style>
