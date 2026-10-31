<script lang="ts">
	import { findSelection, NO_SELECTION_MESSAGE, selectionHeading } from '../app/model/boardSummary';
	import { cardKey, lineKey } from '../app/model/decision';
	import { locksCard, type DecisionStore } from '../app/state/decision.svelte';
	import type { RepoReading } from '../types';
	import DecideRow from './DecideRow.svelte';
	import DecidedCard from './DecidedCard.svelte';
	import GroupCard from './GroupCard.svelte';
	import OptionCard from './OptionCard.svelte';

	let {
		repos,
		selectedKey,
		decisions
	}: {
		repos: RepoReading[];
		selectedKey: string | null;
		decisions: DecisionStore;
	} = $props();

	let decideRow: DecideRow | undefined = $state();

	const selected = $derived(findSelection(repos, selectedKey));
</script>

<section
	class="stage"
	aria-live="polite"
	tabindex="-1"
	aria-label={selected === null ? NO_SELECTION_MESSAGE : selectionHeading(selected)}
>
	{#if selected === null}
		<p>{NO_SELECTION_MESSAGE}</p>
	{:else if selected.kind === 'decided'}
		{@const ruledLine = selected.line}
		{#key lineKey(selected.repo, selected.item.number, ruledLine)}
			<DecidedCard repo={selected.repo} item={selected.item} line={ruledLine} />
		{/key}
	{:else}
		{@const points = selected.points}
		{@const repoName = selected.repo}
		{@const itemNumber = selected.item.number}
		{@const optionKey = cardKey(repoName, itemNumber)}
		{@const banner = decisions.banner(optionKey)}
		{@const held = decisions.held(optionKey)}
		{@const picks = held ?? decisions.picks(optionKey, points)}
		{@const saving = decisions.isSaving(optionKey)}
		{@const openPanel = decisions.panel(optionKey)}
		{#snippet decide()}
			<DecideRow
				bind:this={decideRow}
				{points}
				{picks}
				pending={decisions.isPending(optionKey)}
				waiting={held !== null}
				{saving}
				{banner}
				onPick={(shown, pick) => decisions.choose(repoName, itemNumber, shown, pick)}
				onAcceptAll={(shown) => decisions.acceptAll(repoName, itemNumber, shown)}
				onReload={() => decisions.reloadAfterBanner(optionKey)}
				escapes={{
					panel: openPanel,
					draft: openPanel === null ? '' : decisions.draft(optionKey, openPanel.kind),
					onOpen: (kind, shown) => decisions.openPanel(optionKey, { kind, shown }),
					onClose: () => decisions.closePanel(optionKey),
					onDraft: (text) => {
						if (openPanel !== null) decisions.setDraft(optionKey, openPanel.kind, text);
					},
					onSend: ({ kind, shown }, text) =>
						kind === 'other'
							? decisions.decideOther(repoName, itemNumber, shown, text)
							: decisions.decideUnclear(repoName, itemNumber, shown, text)
				}}
			/>
		{/snippet}
		{#key optionKey}
			{#if points.length > 1}
				<GroupCard
					repo={repoName}
					item={itemNumber}
					{points}
					open={decisions.openPoint(optionKey)}
					{picks}
					locked={locksCard(banner)}
					pending={decisions.isPending(optionKey)}
					waiting={held !== null}
					{saving}
					onToggle={(index) => decisions.togglePoint(optionKey, index)}
					onPick={(shown, option) => decideRow?.choose({ shown, option })}
				>
					{@render decide()}
				</GroupCard>
			{:else}
				{#each points as only (only.index)}
					<OptionCard repo={repoName} item={itemNumber} line={only} {saving}>
						{@render decide()}
					</OptionCard>
				{/each}
			{/if}
		{/key}
	{/if}
</section>
