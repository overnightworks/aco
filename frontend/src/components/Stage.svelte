<script lang="ts">
	import {
		cardHeading,
		cardSentence,
		findSelection,
		NO_SELECTION_MESSAGE,
		pictureDataUri,
		selectionHeading
	} from '../app/model/boardSummary';
	import { cardKey, NOTE_MAX_LENGTH, lineKey, noteOrNull } from '../app/model/decision';
	import { locksCard, type DecisionStore } from '../app/state/decision.svelte';
	import type { Outcome, RepoReading } from '../types';
	import ChoiceButtons from './ChoiceButtons.svelte';
	import DecideRow from './DecideRow.svelte';
	import DecidedCard from './DecidedCard.svelte';
	import GroupCard from './GroupCard.svelte';
	import OptionCard from './OptionCard.svelte';
	import RefusalBanner from './RefusalBanner.svelte';

	let {
		repos,
		selectedKey,
		decisions,
		refreshing
	}: {
		repos: RepoReading[];
		selectedKey: string | null;
		decisions: DecisionStore;
		refreshing: boolean;
	} = $props();

	let noteText = $state('');
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
	{:else if selected.kind === 'card'}
		{@const points = selected.points}
		{@const repoName = selected.repo}
		{@const itemNumber = selected.item.number}
		{@const optionKey = cardKey(repoName, itemNumber)}
		{@const banner = decisions.banner(optionKey)}
		{@const picks = decisions.picks(optionKey, points)}
		{@const openPanel = decisions.panel(optionKey)}
		{#snippet decide()}
			<DecideRow
				bind:this={decideRow}
				{points}
				chosen={picks.length}
				pending={decisions.isPending(optionKey)}
				{refreshing}
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
					{refreshing}
					onToggle={(index) => decisions.togglePoint(optionKey, index)}
					onPick={(shown, option) => decideRow?.choose({ shown, option })}
				>
					{@render decide()}
				</GroupCard>
			{:else}
				{#each points as only (only.index)}
					<OptionCard repo={repoName} item={itemNumber} line={only}>
						{@render decide()}
					</OptionCard>
				{/each}
			{/if}
		{/key}
	{:else}
		{@const yesNoLine = selected.line}
		{@const activeKey = lineKey(selected.repo, selected.item.number, selected.line)}
		{@const banner = decisions.banner(activeKey)}
		{@const locked = locksCard(banner)}
		<article class="card">
			<p class="item">
				#{selected.item.number} · {selected.item.title} · Zeile {selected.line.index}
			</p>
			<h2 class="question">{cardHeading(selected.line)}</h2>
			{#if cardSentence(selected.line) !== null}
				<p class="sent">{cardSentence(selected.line)}</p>
			{/if}
			{#if selected.line.example !== null}
				<p class="example">{selected.line.example}</p>
			{/if}
			{#if selected.line.picture !== null}
				<img alt="Bild zur Frage" src={pictureDataUri(selected.line.picture)} />
			{/if}
			{#if banner !== null}
				<RefusalBanner {banner} onReload={() => decisions.reloadAfterBanner(activeKey)} />
			{/if}
			{#if !locked}
				<details class="note">
					<summary>Notiz</summary>
					<textarea
						bind:value={noteText}
						maxlength={NOTE_MAX_LENGTH}
						placeholder="Optional – wird als „Anmerkung: …“ an den Satz gehängt"></textarea>
				</details>
				<ChoiceButtons
					default={selected.line.default}
					disabled={decisions.isPending(activeKey) || refreshing}
					onChoose={(outcome: Outcome) => {
						if (selected === null) {
							return;
						}
						decisions.decide(
							selected.repo,
							selected.item.number,
							yesNoLine,
							outcome,
							noteOrNull(noteText)
						);
						noteText = '';
					}}
				/>
			{/if}
		</article>
	{/if}
</section>
