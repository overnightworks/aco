<script lang="ts">
	import {
		contractTexts,
		ROW_LABEL,
		resultAltText,
		SAME_AS_TODAY_MARK,
		sourceLine,
		UNDO_LABEL,
		undoTail
	} from '../app/model/optionCard';
	import type { CardOption, OptionLine } from '../types';
	import ContractFold from './ContractFold.svelte';
	import EnlargeablePicture from './EnlargeablePicture.svelte';
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
			<EnlargeablePicture
				picture={option.picture}
				alt={resultAltText(option)}
				caption={option.caption}
			/>
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
		<ContractFold sentences={contractTexts(line, option)} source={sourceLine(repo, item, line)} />
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
		color: var(--fg-3);
	}
	dd {
		margin: 0;
		min-width: 0;
	}
	p {
		margin: 0;
	}
	.same {
		display: inline-flex;
		align-items: center;
		font-size: 13px;
		font-weight: 650;
		letter-spacing: 0.04em;
		color: var(--fg-2);
		border: 1.5px dashed var(--line-strong);
		border-radius: 6px;
		padding: 2px 10px;
	}
	b {
		font-weight: 600;
	}
	b.final {
		color: var(--warn);
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
