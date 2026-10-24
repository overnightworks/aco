<script lang="ts">
	import {
		cardHeading,
		cardSentence,
		findSelectedLine,
		lineStatusText,
		NO_SELECTION_MESSAGE,
		pictureDataUri
	} from '../app/model/boardSummary';
	import { NOTE_MAX_LENGTH, lineKey, noteOrNull } from '../app/model/decision';
	import type { DecisionStore } from '../app/state/decision.svelte';
	import type { Outcome, RepoReading } from '../types';
	import ChoiceButtons from './ChoiceButtons.svelte';

	let {
		repos,
		selectedKey,
		decisions
	}: { repos: RepoReading[]; selectedKey: string | null; decisions: DecisionStore } = $props();

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
	{:else}
		{@const activeKey = lineKey(selected.repo, selected.item.number, selected.line)}
		{@const ruled = selected.line.ruling !== null}
		{@const banner = decisions.banner(activeKey)}
		{@const locked = banner !== null && banner.kind !== 'failed'}
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
			{#if ruled}
				<div class="ruledbox">
					<p>{lineStatusText(selected.line)}</p>
					<p class="hint">Nur zum Lesen. Umentscheiden heißt: eine neue Zeile in aco.</p>
				</div>
			{:else}
				{#if banner !== null}
					<p role="alert" class="banner">{banner.message}</p>
					{#if locked}
						<button type="button" onclick={() => decisions.reloadAfterBanner(activeKey)}>
							Neu laden
						</button>
					{/if}
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
						disabled={decisions.isPending(activeKey)}
						onChoose={(outcome: Outcome) => {
							if (selected === null) {
								return;
							}
							decisions.decide(
								selected.repo,
								selected.item.number,
								selected.line,
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
