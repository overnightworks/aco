<script lang="ts">
	import { findSelection, NO_SELECTION_MESSAGE, selectionHeading } from '../app/model/boardSummary';
	import { cardKey, lineKey, pointKey } from '../app/model/decision';
	import { escapeKinds, type EscapeKind, type EscapePanel } from '../app/model/optionCard';
	import { locksCard, type DecisionStore } from '../app/state/decision.svelte';
	import type { OptionLine, RepoReading } from '../types';
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

	/** The points whose controls are disabled: those waiting, all while the card reads again. */
	function blockedPoints(card: string, points: readonly OptionLine[]): ReadonlySet<number> {
		return decisions.isReading(card)
			? new Set(points.map((point) => point.index))
			: decisions.waitingIndexes(card);
	}

	/** The escapes of `shown` points: Other has its panel and draft under its point,
	 * Unclear under the card; one panel is open at a time per row. */
	function escapesFor(
		repo: string,
		item: number,
		shown: readonly OptionLine[],
		kinds: readonly EscapeKind[]
	) {
		const card = cardKey(repo, item);
		const [answered] = shown;
		const keyOf = (kind: EscapeKind) =>
			kind === 'other' && answered !== undefined ? pointKey(repo, item, answered.index) : card;
		const panel = kinds.map((kind) => decisions.panel(keyOf(kind))).find((open) => open !== null);
		return {
			kinds,
			panel: panel ?? null,
			draft: panel === undefined ? '' : decisions.draft(keyOf(panel.kind), panel.kind),
			onOpen: (kind: EscapeKind, snapshot: readonly OptionLine[]) => {
				for (const other of kinds) decisions.closePanel(keyOf(other));
				decisions.openPanel(keyOf(kind), { kind, shown: snapshot });
			},
			onClose: () => {
				for (const kind of kinds) decisions.closePanel(keyOf(kind));
			},
			onDraft: (text: string) => {
				if (panel !== undefined) decisions.setDraft(keyOf(panel.kind), panel.kind, text);
			},
			onSend: ({ kind, shown: snapshot }: EscapePanel, text: string) => {
				const [point] = snapshot;
				if (kind === 'unclear') decisions.decideUnclear(repo, item, snapshot, text);
				else if (point !== undefined) decisions.decideOther(repo, item, point, text);
			}
		};
	}
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
			<DecidedCard
				repo={selected.repo}
				item={selected.item}
				line={ruledLine}
				note={decisions.note(cardKey(selected.repo, selected.item.number))}
			/>
		{/key}
	{:else}
		{@const points = selected.points}
		{@const repoName = selected.repo}
		{@const itemNumber = selected.item.number}
		{@const optionKey = cardKey(repoName, itemNumber)}
		{@const banner = decisions.banner(optionKey)}
		{@const held = decisions.held(optionKey) ?? []}
		{@const blocked = blockedPoints(optionKey, points)}
		{@const saving = decisions.isSaving(optionKey)}
		{#snippet decide()}
			<DecideRow
				bind:this={decideRow}
				{points}
				{held}
				{blocked}
				{saving}
				{banner}
				onPick={(shown, pick) => decisions.choose(repoName, itemNumber, shown, pick)}
				onAcceptAll={(shown) => decisions.acceptAll(repoName, itemNumber, shown)}
				onReload={() => decisions.reloadAfterBanner(optionKey)}
				escapes={escapesFor(repoName, itemNumber, points, escapeKinds(points, points.length === 1))}
			/>
		{/snippet}
		{#key optionKey}
			{#if points.length > 1}
				<GroupCard
					repo={repoName}
					item={itemNumber}
					{points}
					open={decisions.openPoint(optionKey)}
					{held}
					locked={locksCard(banner)}
					{blocked}
					{saving}
					escapes={(point) => escapesFor(repoName, itemNumber, [point], ['other'])}
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
