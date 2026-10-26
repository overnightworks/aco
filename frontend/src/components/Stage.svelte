<script lang="ts">
	import {
		cardHeading,
		cardSentence,
		findSelectedLine,
		NO_SELECTION_MESSAGE,
		pictureDataUri,
		ruledOutcomeText
	} from '../app/model/boardSummary';
	import { NOTE_MAX_LENGTH, lineKey, noteOrNull } from '../app/model/decision';
	import { isOptionLine } from '../app/model/optionCard';
	import { locksCard, type DecisionStore } from '../app/state/decision.svelte';
	import type { Outcome, RepoReading } from '../types';
	import ChoiceButtons from './ChoiceButtons.svelte';
	import DecideRow from './DecideRow.svelte';
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
	{:else if isOptionLine(selected.line)}
		{@const optionLine = selected.line}
		{@const repoName = selected.repo}
		{@const itemNumber = selected.item.number}
		{@const optionKey = lineKey(repoName, itemNumber, optionLine)}
		{#key optionKey}
			<OptionCard repo={repoName} item={itemNumber} line={optionLine}>
				{#if optionLine.ruling === null}
					<DecideRow
						line={optionLine}
						pending={decisions.isPending(optionKey)}
						{refreshing}
						banner={decisions.banner(optionKey)}
						onDecide={(shownLine, option) =>
							decisions.decideOption(repoName, itemNumber, shownLine, option)}
						onReload={() => decisions.reloadAfterBanner(optionKey)}
					/>
				{/if}
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
			{#if yesNoLine.ruling !== null}
				<div class="ruledbox">
					<p>{ruledOutcomeText(yesNoLine.ruling, yesNoLine.ruled_on)}</p>
					<p class="hint">Nur zum Lesen. Umentscheiden heißt: eine neue Zeile in aco.</p>
				</div>
			{:else}
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
			{/if}
		</article>
	{/if}
</section>
