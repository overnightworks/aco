<script lang="ts">
	import {
		cardHeading,
		cardSentence,
		findSelectedLine,
		NO_SELECTION_MESSAGE,
		pictureDataUri
	} from '../app/model/boardSummary';
	import { NOTE_MAX_LENGTH, lineKey, noteOrNull } from '../app/model/decision';
	import { isOptionLine } from '../app/model/optionCard';
	import { locksCard, type DecisionStore } from '../app/state/decision.svelte';
	import type { Outcome, RepoReading } from '../types';
	import ChoiceButtons from './ChoiceButtons.svelte';
	import DecideRow from './DecideRow.svelte';
	import DecidedCard from './DecidedCard.svelte';
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

	const selected = $derived(findSelectedLine(repos, selectedKey));
</script>

<section
	class="stage"
	aria-live="polite"
	tabindex="-1"
	aria-label={selected === null ? NO_SELECTION_MESSAGE : cardHeading(selected.line)}
>
	{#if selected === null}
		<p>{NO_SELECTION_MESSAGE}</p>
	{:else if selected.line.ruling !== null}
		{@const ruledLine = selected.line}
		{#key lineKey(selected.repo, selected.item.number, ruledLine)}
			<DecidedCard repo={selected.repo} item={selected.item} line={ruledLine} />
		{/key}
	{:else if isOptionLine(selected.line)}
		{@const optionLine = selected.line}
		{@const repoName = selected.repo}
		{@const itemNumber = selected.item.number}
		{@const optionKey = lineKey(repoName, itemNumber, optionLine)}
		{@const openPanel = decisions.panel(optionKey)}
		{#key optionKey}
			<OptionCard repo={repoName} item={itemNumber} line={optionLine}>
				<DecideRow
					line={optionLine}
					pending={decisions.isPending(optionKey)}
					{refreshing}
					banner={decisions.banner(optionKey)}
					onDecide={(shownLine, option) =>
						decisions.decideOption(repoName, itemNumber, shownLine, option)}
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
			</OptionCard>
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
