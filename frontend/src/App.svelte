<script lang="ts">
	import { tick } from 'svelte';
	import { isBoardEmpty, LIST_LABEL, nextOpenAfter } from './app/model/boardSummary';
	import { BoardStore } from './app/state/board.svelte';
	import { DecisionStore } from './app/state/decision.svelte';
	import Stage from './components/Stage.svelte';
	import TrackList from './components/TrackList.svelte';
	import UndoToast from './components/UndoToast.svelte';

	let { token }: { token: string | null } = $props();

	const board = new BoardStore();
	let decisions: DecisionStore | null = $state(null);
	let selectedKey: string | null = $state(null);
	let showQuestion = $state(false);
	let tracks: HTMLDivElement | undefined = $state();
	let question: HTMLDivElement | undefined = $state();

	function focusQuestion() {
		question?.querySelector<HTMLElement>('.stage')?.focus({ preventScroll: true });
	}

	async function showList() {
		showQuestion = false;
		await tick();
		(tracks?.querySelector<HTMLElement>('[aria-current="true"]') ?? tracks)?.focus({
			preventScroll: true
		});
	}

	function keepFocusVisible() {
		const active = document.activeElement;
		if (
			active === document.body ||
			(active instanceof HTMLElement && active.getClientRects().length === 0)
		) {
			if (showQuestion) focusQuestion();
			else tracks?.focus({ preventScroll: true });
		}
	}

	$effect(() => {
		// A newly selected or automatically advanced question begins at its heading.
		void selectedKey;
		if (showQuestion) {
			void tick().then(() => {
				if (question) question.scrollTop = 0;
				focusQuestion();
			});
		}
	});

	$effect(() => {
		if (token === null) {
			board.setNoAccess();
			decisions = null;
		} else {
			void board.load(token);
			decisions = new DecisionStore(token, () => board.load(token));
		}
	});

	// Once a decision this tab made lands and the board re-reads from it, the
	// stage leaves the now-ruled card for the next open one -- but only while
	// it is still the card shown, never yanking the operator off a different
	// card they moved to in the meantime (picture: `nextOpenAfter`).
	$effect(() => {
		if (decisions !== null && decisions.justRuled !== null && decisions.justRuled === selectedKey) {
			selectedKey = nextOpenAfter(board.repos, decisions.justRuled);
		}
	});
</script>

<svelte:window onresize={keepFocusVisible} />

<main>
	<h1>aco</h1>
	{#if board.status === 'no-access'}
		<p role="alert">Zugang fehlt. Starte das Board im Repo und öffne den Link, den es ausgibt.</p>
	{:else if board.status === 'loading'}
		<p role="status">Lädt…</p>
	{:else if board.status === 'unavailable'}
		<p role="alert">aco antwortet nicht. {board.error}</p>
	{:else if isBoardEmpty(board.repos)}
		<p>Nichts offen. Neue Fragen erscheinen hier nach Neuladen, sobald ein Agent eine stellt.</p>
	{:else if decisions !== null}
		<div class="decide" class:show-question={showQuestion}>
			<div class="tracks" bind:this={tracks} tabindex="-1">
				<TrackList
					repos={board.repos}
					{selectedKey}
					onSelect={(key) => {
						selectedKey = key;
						showQuestion = true;
					}}
				/>
			</div>
			<div class="question-pane" bind:this={question}>
				<button class="back" type="button" onclick={showList}>← {LIST_LABEL}</button>
				<Stage repos={board.repos} {selectedKey} {decisions} />
			</div>
		</div>
		<div class="toasts" aria-live="polite">
			{#each decisions.pendingEntries as entry (entry.key)}
				<UndoToast message={entry.message} onUndo={() => decisions?.undo(entry.key)} />
			{/each}
		</div>
	{/if}
</main>

<style>
	:global(*) {
		box-sizing: border-box;
	}
	:global(body) {
		margin: 0;
		background: #f3f2f6;
		color: #17141f;
		font:
			15px/1.5 ui-sans-serif,
			system-ui,
			-apple-system,
			'Segoe UI',
			sans-serif;
	}
	:global(button),
	:global(textarea) {
		font: inherit;
		color: inherit;
	}
	:global(button) {
		cursor: pointer;
	}
	:global(:focus-visible) {
		outline: 2px solid #8a2a63;
		outline-offset: -2px;
	}
	main {
		height: 100dvh;
		display: flex;
		flex-direction: column;
		overflow-wrap: anywhere;
	}
	h1 {
		margin: 0;
		padding: 14px 20px;
		background: white;
		border-bottom: 1px solid #e1dee8;
		font-size: 17px;
	}
	main > p {
		padding: 20px;
	}
	.decide {
		display: grid;
		grid-template-columns: 320px minmax(0, 1fr);
		flex: 1;
		min-height: 0;
	}
	.tracks,
	.question-pane {
		overflow: auto;
		min-width: 0;
	}
	.tracks {
		background: white;
		border-right: 1px solid #e1dee8;
		padding: 16px 0 32px;
	}
	.tracks :global(h2) {
		margin: 0;
		padding: 12px 20px 6px;
		font-size: 13px;
	}
	.tracks :global(ul) {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	.tracks :global(li > span) {
		display: block;
		padding: 4px 20px;
		color: #4d4759;
	}
	.tracks :global(button) {
		display: flex;
		flex-direction: column;
		gap: 4px;
		width: 100%;
		text-align: left;
		padding: 11px 20px;
		border: 0;
		border-left: 3px solid transparent;
		background: transparent;
		overflow-wrap: anywhere;
	}
	.tracks :global(button:hover) {
		background: #eceaf1;
	}
	.tracks :global(button[aria-current='true']) {
		border-left-color: #8a2a63;
		background: #f6e8f0;
	}
	.tracks :global(button span:last-child) {
		font-size: 12px;
		color: #4d4759;
	}
	.question-pane {
		padding: 28px clamp(16px, 3vw, 44px) 56px;
	}
	.question-pane :global(.card) {
		max-width: 900px;
		margin-inline: auto;
	}
	.question-pane :global(.item) {
		color: #4d4759;
		font-size: 13px;
		margin-top: 0;
	}
	.question-pane :global(.question) {
		font-size: clamp(26px, 3vw, 38px);
		line-height: 1.12;
		margin: 0 0 22px;
	}
	.question-pane :global(.sent) {
		font-size: 17px;
	}
	.question-pane :global(.example) {
		border-left: 2px solid #c9c4d4;
		padding-left: 14px;
		color: #4d4759;
		white-space: pre-wrap;
	}
	.question-pane :global(img) {
		display: block;
		max-width: 100%;
		height: auto;
	}
	.question-pane :global(.note) {
		margin-block: 24px;
	}
	.question-pane :global(summary) {
		cursor: pointer;
		padding-block: 8px;
	}
	.question-pane :global(textarea) {
		display: block;
		width: 100%;
		max-width: 100%;
		min-height: 100px;
		padding: 12px;
		border: 1px solid #c9c4d4;
		border-radius: 12px;
		resize: vertical;
	}
	.question-pane :global(.choices) {
		display: flex;
		flex-wrap: wrap;
		gap: 12px;
		margin-top: 24px;
	}
	.question-pane :global(button),
	.toasts :global(button) {
		padding: 10px 18px;
		border: 1px solid #c9c4d4;
		border-radius: 12px;
		background: white;
	}
	.question-pane :global(.choices button) {
		flex: 1;
		min-width: 80px;
		display: flex;
		flex-direction: column;
		justify-content: center;
		align-items: center;
		font-weight: 600;
	}
	.question-pane :global(.choices button:has(.rec-tag)) {
		border: 2px solid #8a2a63;
	}
	.question-pane :global(.rec-tag) {
		font-size: 11px;
		color: #8a2a63;
	}
	.question-pane :global(button:disabled) {
		opacity: 0.55;
		cursor: default;
	}
	.question-pane :global(.banner),
	.question-pane :global(.ruledbox) {
		padding: 16px;
		border: 1px dashed #c9c4d4;
		border-radius: 12px;
		background: #eceaf1;
	}
	.back {
		display: none;
	}
	.toasts {
		flex-shrink: 0;
		max-height: 35dvh;
		overflow: auto;
	}
	.toasts :global(.toast) {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 12px;
		padding: 12px 20px;
		background: #17141f;
		color: white;
		border-top: 1px solid #4d4759;
	}
	.toasts :global(.msg) {
		flex: 1;
		min-width: 0;
	}
	.toasts :global(button) {
		color: #17141f;
		flex-shrink: 0;
	}
	@media (max-width: 760px) {
		.decide {
			grid-template-columns: minmax(0, 1fr);
		}
		.question-pane {
			display: none;
			padding: 16px 16px 32px;
		}
		.show-question .tracks {
			display: none;
		}
		.show-question .question-pane {
			display: block;
		}
		.back {
			display: inline-block;
			margin-bottom: 20px;
		}
	}
</style>
