<script lang="ts">
	import { bindingSentences, decidedAnswer, decidedMeta, howText } from '../app/model/decidedCard';
	import { cardHeading } from '../app/model/boardSummary';
	import { ROW_LABEL, sourceLine } from '../app/model/optionCard';
	import type { BoardItem, RuledLine } from '../types';
	import CardFrame from './CardFrame.svelte';
	import CardRow from './CardRow.svelte';
	import ContractFold from './ContractFold.svelte';
	import StateShape from './StateShape.svelte';

	let { repo, item, line }: { repo: string; item: BoardItem; line: RuledLine } = $props();
</script>

<div class="decided-card">
	<CardFrame meta={decidedMeta(repo, item, line)} title={cardHeading(line)}>
		<CardRow label={ROW_LABEL.decided}>
			<div class="answer">
				<StateShape state="done" />
				<p>{decidedAnswer(line)}</p>
			</div>
		</CardRow>
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
	.answer {
		display: flex;
		align-items: start;
		gap: 12px;
	}
	.answer :global(.shape) {
		margin-top: 4px;
	}
</style>
