<script lang="ts">
	import { pictureDataUri } from '../app/model/boardSummary';
	import {
		CONTRACT_SUMMARY,
		contractTexts,
		ROW_LABEL,
		resultAltText,
		SAME_AS_TODAY_MARK,
		sourceLine,
		UNDO_LABEL,
		undoTail
	} from '../app/model/optionCard';
	import type { CardOption, OptionLine } from '../types';
	import WarnMark from './WarnMark.svelte';

	let {
		repo,
		item,
		line,
		option
	}: { repo: string; item: number; line: OptionLine; option: CardOption } = $props();
</script>

<dl class="details">
	<dt>{ROW_LABEL.result}</dt>
	<dd>
		{#if 'picture' in option}
			<img src={pictureDataUri(option.picture)} alt={resultAltText(option)} />
			{#if option.caption !== undefined}<p class="caption">{option.caption}</p>{/if}
		{:else}
			<span class="same">{SAME_AS_TODAY_MARK}</span>
		{/if}
	</dd>
	<dt>{ROW_LABEL.notice}</dt>
	<dd><p>{option.notice}</p></dd>
	<dt>{ROW_LABEL.cost}</dt>
	<dd><p>{option.cost}</p></dd>
	<dt>{ROW_LABEL.undo}</dt>
	<dd>
		<p>
			<b class:final={option.undo === 'final'}
				>{#if option.undo === 'final'}<WarnMark />{/if}{UNDO_LABEL[option.undo]}</b
			>{undoTail(option)}
		</p>
	</dd>
	<dt>{ROW_LABEL.contract}</dt>
	<dd>
		<details>
			<summary class="fold">{CONTRACT_SUMMARY}</summary>
			<div class="binding">
				{#each contractTexts(line, option) as sentence (sentence)}
					<p>{sentence}</p>
				{/each}
				<span class="source">{sourceLine(repo, item, line)}</span>
			</div>
		</details>
	</dd>
</dl>

<style>
	.details {
		display: grid;
		grid-template-columns: var(--oc-label-width) minmax(0, 1fr);
		column-gap: var(--oc-column-gap);
		row-gap: 12px;
		align-items: start;
		margin: 12px 0 0 calc(-1 * (var(--oc-label-width) + var(--oc-column-gap)));
	}
	dt {
		padding-left: 12px;
		font-size: 11px;
		line-height: 22px;
		font-weight: 550;
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
	.same {
		display: inline-flex;
		align-items: center;
		font-size: 13px;
		font-weight: 650;
		letter-spacing: 0.04em;
		color: var(--oc-fg-2);
		border: 1.5px dashed var(--oc-line-strong);
		border-radius: 6px;
		padding: 2px 10px;
	}
	b {
		font-weight: 600;
	}
	b.final {
		color: var(--oc-warn);
	}
	.details summary.fold {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		padding-block: 0;
		list-style: none;
		cursor: pointer;
		color: var(--oc-fg-2);
	}
	summary::-webkit-details-marker {
		display: none;
	}
	summary::before {
		content: '';
		width: 0;
		height: 0;
		border-left: 5px solid currentColor;
		border-top: 4px solid transparent;
		border-bottom: 4px solid transparent;
	}
	details[open] summary::before {
		transform: rotate(90deg);
	}
	.binding {
		display: grid;
		gap: 8px;
		margin-top: 8px;
		padding-left: 12px;
		border-left: 2px solid var(--oc-line-strong);
		font-size: 13px;
		line-height: 18px;
		color: var(--oc-fg-2);
	}
	.source {
		font-family: ui-monospace, 'DejaVu Sans Mono', Menlo, Consolas, monospace;
		font-size: 12px;
		color: var(--oc-fg-3);
	}
	@media (max-width: 760px) {
		.details {
			grid-template-columns: minmax(0, 1fr);
			row-gap: 0;
			margin-left: 0;
		}
		dt {
			padding-left: 0;
			line-height: 16px;
		}
		dd {
			margin-bottom: 12px;
		}
	}
</style>
