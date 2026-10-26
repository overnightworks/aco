<script lang="ts">
	import { tick } from 'svelte';
	import {
		LIST_LABEL,
		nextOpenAfter,
		firstOpenKey,
		OPEN_TAB_LABEL,
		DECIDED_TAB_LABEL,
		tabCounts
	} from './app/model/boardSummary';
	import { BoardStore } from './app/state/board.svelte';
	import { DecisionStore } from './app/state/decision.svelte';
	import Stage from './components/Stage.svelte';
	import TrackList from './components/TrackList.svelte';
	import UndoToast from './components/UndoToast.svelte';
	import HistoryView from './components/HistoryView.svelte';

	let { token }: { token: string | null } = $props();

	const board = new BoardStore();
	let decisions: DecisionStore | null = $state(null);
	let selectedKey: string | null = $state(null);
	let showQuestion = $state(false);
	let view: 'open' | 'decided' = $state('open');
	const counts = $derived(tabCounts(board.repos));
	let initialized = $state(false);
	let tracks: HTMLDivElement | undefined = $state();
	let question: HTMLDivElement | undefined = $state();

	function focusQuestion() {
		(question?.querySelector<HTMLElement>('.stage') ?? question)?.focus({ preventScroll: true });
	}

	async function resetQuestion(explicitSelection = false) {
		await tick();
		if (question && question.getClientRects().length > 0) {
			question.scrollTop = 0;
		}
		if (explicitSelection) focusQuestion();
		else keepFocusVisible();
	}

	async function showList() {
		showQuestion = false;
		await tick();
		(tracks?.querySelector<HTMLElement>('[aria-current="true"]') ?? tracks)?.focus({
			preventScroll: true
		});
	}

	function keepFocusVisible() {
		if (view === 'decided') return;
		const active = document.activeElement;
		if (
			active === document.body ||
			(active instanceof HTMLElement && active.getClientRects().length === 0)
		) {
			if (question && question.getClientRects().length > 0) focusQuestion();
			else tracks?.focus({ preventScroll: true });
		}
	}

	$effect(() => {
		if (board.status === 'ready' && !board.refreshing) {
			if (!initialized) {
				selectedKey = firstOpenKey(board.repos);
				initialized = true;
			}
			void tick().then(() => {
				if (document.activeElement === question) focusQuestion();
				else keepFocusVisible();
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
			void resetQuestion();
		}
	});
</script>

<svelte:window onresize={keepFocusVisible} />

<main>
	<header class="top">
		<h1 class="brand">Entscheidungs-Board</h1>
		{#if board.status === 'ready' && decisions !== null}
			<nav aria-label="Views">
				<button
					type="button"
					aria-current={view === 'open' ? 'page' : undefined}
					onclick={() => (view = 'open')}
					>{OPEN_TAB_LABEL} <span class="n">{counts.open}</span></button
				>
				<button
					type="button"
					aria-current={view === 'decided' ? 'page' : undefined}
					onclick={() => (view = 'decided')}
					>{DECIDED_TAB_LABEL} <span class="n">{counts.decided}</span></button
				>
			</nav>
		{/if}
	</header>
	{#if board.status === 'no-access'}
		<p role="alert">Zugang fehlt. Starte das Board im Repo und öffne den Link, den es ausgibt.</p>
	{:else if board.status === 'loading'}
		<p role="status">Lädt…</p>
	{:else if board.status === 'unavailable'}
		<p role="alert">aco antwortet nicht. {board.error}</p>
	{:else if decisions !== null}
		<div class="history" hidden={view !== 'decided'}><HistoryView repos={board.repos} /></div>
		<div class="decide" hidden={view !== 'open'} class:show-question={showQuestion}>
			<div class="tracks" bind:this={tracks} tabindex="-1">
				<TrackList
					repos={board.repos}
					{selectedKey}
					onSelect={(key) => {
						selectedKey = key;
						showQuestion = true;
						void resetQuestion(true);
					}}
				/>
			</div>
			<div class="question-pane" bind:this={question} tabindex="-1">
				<div class="inner">
					<button class="back" type="button" onclick={showList}>← {LIST_LABEL}</button>
					<Stage repos={board.repos} {selectedKey} {decisions} refreshing={board.refreshing} />
				</div>
			</div>
		</div>
		<div class="toasts" hidden={view !== 'open'} aria-live="polite">
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
	:global(:root) {
		--bg: #f6f5f8;
		--surface: #ffffff;
		--surface-2: #f1eff4;
		--line: #e5e2ea;
		--line-strong: #cdc8d5;
		--fg: #18151f;
		--fg-2: #4d4758;
		--fg-3: #6e6779;
		--accent: #7d2459;
		--accent-fg: #ffffff;
		--good: #1c7350;
		--warn: #99570c;
		color-scheme: light;
	}
	:global(body) {
		margin: 0;
		background: var(--bg);
		color: var(--fg);
		font:
			400 15px/22px ui-sans-serif,
			system-ui,
			-apple-system,
			'Segoe UI',
			'Noto Sans',
			sans-serif;
		font-variant-numeric: tabular-nums;
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
		outline: 2px solid var(--accent);
		outline-offset: -2px;
	}
	main {
		height: 100dvh;
		display: flex;
		flex-direction: column;
		overflow-wrap: anywhere;
	}
	.top {
		flex-shrink: 0;
		height: 56px;
		display: flex;
		align-items: center;
		gap: 16px;
		padding: 0 24px;
		background: var(--surface);
		border-bottom: 1px solid var(--line);
	}
	.brand {
		margin: 0;
		font: inherit;
		font-weight: 650;
		white-space: nowrap;
	}
	main > p {
		padding: 20px;
	}
	[hidden] {
		display: none !important;
	}
	nav {
		margin-left: auto;
		display: flex;
		align-items: center;
		gap: 4px;
	}
	nav button {
		display: flex;
		align-items: baseline;
		gap: 6px;
		padding: 6px 12px;
		border: 0;
		border-radius: 8px;
		background: none;
		font-weight: 550;
		color: var(--fg-2);
		white-space: nowrap;
	}
	nav button .n {
		font-size: 13px;
		color: var(--fg-3);
	}
	nav button[aria-current='page'] {
		background: var(--fg);
		color: var(--surface);
	}
	nav button[aria-current='page'] .n {
		color: inherit;
		opacity: 0.75;
	}
	.history {
		flex: 1;
		overflow: auto;
		min-height: 0;
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
		background: var(--surface);
		border-right: 1px solid var(--line);
		padding: 8px 0 24px;
	}
	.question-pane {
		padding: 24px 32px 0;
	}
	.inner {
		padding-bottom: 32px;
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
		.top {
			height: 52px;
			padding: 0 16px;
			gap: 8px;
		}
		.brand {
			position: absolute;
			width: 0;
			height: 0;
			overflow: hidden;
		}
		nav {
			gap: 2px;
		}
		nav button {
			padding: 6px 8px;
		}
		.decide {
			grid-template-columns: minmax(0, 1fr);
		}
		.question-pane {
			display: none;
			padding: 16px 16px 0;
		}
		.inner {
			padding-bottom: 16px;
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
