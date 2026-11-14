<script lang="ts">
	import { bindingSentences, decidedAnswer, decidedMeta, howText } from '../app/model/decidedCard';
	import { cardHeading } from '../app/model/boardSummary';
	import { ROW_LABEL, sourceLine } from '../app/model/optionCard';
	import type { BoardItem, RuledLine } from '../types';
	import CardFrame from './CardFrame.svelte';
	import CardRow from './CardRow.svelte';
	import ContractFold from './ContractFold.svelte';
	import StateShape from './StateShape.svelte';

	let {
		repo,
		item,
		line,
		note = null
	}: { repo: string; item: BoardItem; line: RuledLine; note?: string | null } = $props();
</script>

<div class="decided-card">
	<CardFrame meta={decidedMeta(repo, item, line)} title={cardHeading(line)}>
		<CardRow label={ROW_LABEL.decided}>
			<div class="answer">
				<StateShape state="done" />
				<p>{decidedAnswer(line)}</p>
			</div>
		</CardRow>
		{#if note !== null}
			<CardRow label={ROW_LABEL.note}>
				<p class="note">{note}</p>
			</CardRow>
		{/if}
		<CardRow label={ROW_LABEL.how}>
			<p>{howText(line)}</p>
		</CardRow>
		<CardRow label={ROW_LABEL.contract}>
			<ContractFold
				sentences={bindingSentences(line)}
				source={sourceLine(repo, item.number, line)}
			/>
		</CardRow>
	</CardFrame>
</div>

<style>
	p {
		margin: 0;
	}
	.note {
		padding-left: 12px;
		border-left: 3px solid var(--warn);
	}
	.answer {
		display: inline-flex;
		align-items: center;
		gap: 10px;
		padding: 8px 14px 8px 12px;
		border: 1px solid color-mix(in srgb, var(--good) 25%, transparent);
		border-radius: 10px;
		background: var(--good-soft);
		font-weight: 600;
	}
	@media (min-width: 761px) {
		.answer {
			margin: -8px 0 -4px;
		}
	}
</style>
