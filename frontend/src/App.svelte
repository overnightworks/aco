<script lang="ts">
	import { tick } from 'svelte';
	import {
		nextOpenAfter,
		stageAfterReturned,
		firstDecidedKey,
		firstOpenKey,
		type ListView,
		OPEN_TAB_LABEL,
		SERVER_SILENT_SENTENCE,
		DECIDED_TAB_LABEL,
		tabCounts
	} from './app/model/boardSummary';
	import { BoardStore } from './app/state/board.svelte';
	import { DecisionStore } from './app/state/decision.svelte';
	import Stage from './components/Stage.svelte';
	import TrackList from './components/TrackList.svelte';
	import UndoStrip from './components/UndoStrip.svelte';

	let { token }: { token: string | null } = $props();

	const board = new BoardStore();
	let decisions: DecisionStore | null = $state(null);
	let selectedKey: string | null = $state(null);
	let showQuestion = $state(false);
	let decidedKey: string | null = $state(null);
	let showDecidedCard = $state(false);
	let view: ListView = $state('open');
	const counts = $derived(tabCounts(board.repos));
	const cardView = $derived(view === 'open' ? showQuestion : showDecidedCard);
	let initialized = $state(false);
	let tracks: HTMLDivElement | undefined = $state();
	let question: HTMLDivElement | undefined = $state();
	let decidedTracks: HTMLDivElement | undefined = $state();
	let decidedQuestion: HTMLDivElement | undefined = $state();

	function focusQuestion(pane: HTMLDivElement | undefined) {
		(pane?.querySelector<HTMLElement>('.stage') ?? pane)?.focus({ preventScroll: true });
	}

	async function resetQuestion(pane: HTMLDivElement | undefined, explicitSelection = false) {
		await tick();
		if (pane && pane.getClientRects().length > 0) {
			pane.scrollTop = 0;
		}
		if (explicitSelection) focusQuestion(pane);
		else keepFocusVisible();
	}

	async function showList(list: HTMLDivElement | undefined) {
		await tick();
		(list?.querySelector<HTMLElement>('[aria-current="true"]') ?? list)?.focus({
			preventScroll: true
		});
	}

	function leaveCard() {
		if (view === 'open') {
			showQuestion = false;
			void showList(tracks);
		} else {
			showDecidedCard = false;
			void showList(decidedTracks);
		}
	}

	function openDecided() {
		decidedKey = firstDecidedKey(board.repos);
		showDecidedCard = false;
		view = 'decided';
	}

	async function undo(key: string) {
		decisions?.undo(key);
		await tick();
		keepFocusVisible();
	}

	function keepFocusVisible() {
		if (view === 'decided') return;
		const active = document.activeElement;
		if (
			active === document.body ||
			(active instanceof HTMLElement && active.getClientRects().length === 0)
		) {
			if (question && question.getClientRects().length > 0) focusQuestion(question);
			else tracks?.focus({ preventScroll: true });
		}
	}

	$effect(() => {
		// Also after a stored answer is applied in place: its card may leave the list.
		void board.repos;
		if (board.status === 'ready') {
			if (!initialized) {
				selectedKey = firstOpenKey(board.repos);
				initialized = true;
			}
			void tick().then(() => {
				if (document.activeElement === question) focusQuestion(question);
				else keepFocusVisible();
			});
		}
	});

	// A strip that leaves takes a focused Undo with it, whether its post ruled,
	// was refused or failed; the applied answer only covers the ruled case.
	$effect(() => {
		void decisions?.pendingEntries;
		void tick().then(keepFocusVisible);
	});

	$effect(() => {
		decisions?.reconcilePicks(board.repos);
	});

	$effect(() => {
		if (token === null) {
			board.setNoAccess();
			decisions = null;
		} else {
			void board.load(token);
			decisions = new DecisionStore(token, {
				reload: () => board.load(token),
				applyItem: (repo, item) => board.applyItem(repo, item)
			});
		}
	});

	// Once a decision this tab made lands and its item is applied, the
	// stage leaves the now-ruled card for the next open one -- but only while
	// it is still the card shown, never yanking the operator off a different
	// card they moved to in the meantime (picture: `nextOpenAfter`).
	$effect(() => {
		if (decisions !== null && decisions.justRuled !== null && decisions.justRuled === selectedKey) {
			selectedKey = nextOpenAfter(board.repos, decisions.justRuled);
			void resetQuestion(question);
		}
	});

	// A card this tab sent back to its head stays on the stage unless another
	// card is open; the report is taken once, so selecting it again later never
	// moves the stage.
	$effect(() => {
		const returned = decisions?.justReturned ?? null;
		if (decisions !== null && returned !== null) {
			if (returned === selectedKey) {
				selectedKey = stageAfterReturned(board.repos, returned);
				void resetQuestion(question);
			}
			decisions.acknowledgeReturned();
		}
	});
</script>

<svelte:window onresize={keepFocusVisible} />

<main>
	<header class="top" class:card-view={cardView}>
		<h1 class="brand">Entscheidungs-Board</h1>
		{#if board.status === 'ready' && decisions !== null}
			{#if cardView}
				<button type="button" class="back" onclick={leaveCard}
					>‹ {view === 'open' ? OPEN_TAB_LABEL : DECIDED_TAB_LABEL}</button
				>
			{/if}
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
					onclick={openDecided}>{DECIDED_TAB_LABEL} <span class="n">{counts.decided}</span></button
				>
			</nav>
		{/if}
	</header>
	{#if board.status === 'no-access'}
		<p role="alert">Zugang fehlt. Starte das Board im Repo und öffne den Link, den es ausgibt.</p>
	{:else if board.status === 'loading'}
		<p role="status">Lädt…</p>
	{:else if board.status === 'unavailable'}
		<p role="alert">{SERVER_SILENT_SENTENCE} {board.error}</p>
	{:else if decisions !== null}
		{@const store = decisions}
		<div class="split" hidden={view !== 'open'} class:show-question={showQuestion}>
			<div class="tracks" bind:this={tracks} tabindex="-1">
				<TrackList
					repos={board.repos}
					view="open"
					{selectedKey}
					saving={(key) => store.isSaving(key)}
					onSelect={(key) => {
						selectedKey = key;
						showQuestion = true;
						void resetQuestion(question, true);
					}}
				/>
			</div>
			<div class="strips" aria-live="polite">
				{#each decisions.pendingEntries as entry (entry.key)}
					<UndoStrip message={entry.message} kind={entry.state} onUndo={() => undo(entry.key)} />
				{/each}
			</div>
			<div class="question-pane" bind:this={question} tabindex="-1">
				<div class="inner">
					<Stage repos={board.repos} {selectedKey} {decisions} />
				</div>
			</div>
		</div>
		{#if view === 'decided'}
			<div class="split" class:show-question={showDecidedCard}>
				<div class="tracks" bind:this={decidedTracks} tabindex="-1">
					<TrackList
						repos={board.repos}
						view="decided"
						selectedKey={decidedKey}
						saving={(key) => store.isSaving(key)}
						onSelect={(key) => {
							decidedKey = key;
							showDecidedCard = true;
							void resetQuestion(decidedQuestion, true);
						}}
					/>
				</div>
				<div class="question-pane" bind:this={decidedQuestion} tabindex="-1">
					<div class="inner">
						<Stage repos={board.repos} selectedKey={decidedKey} {decisions} />
					</div>
				</div>
			</div>
		{/if}
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
		--good-soft: #e4f2ea;
		--warn: #99570c;
		--frame-width: 880px;
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
	.split {
		display: grid;
		grid-template-columns: 320px minmax(0, 1fr);
		grid-template-rows: auto minmax(0, 1fr);
		flex: 1;
		min-height: 0;
	}
	.tracks,
	.question-pane {
		overflow: auto;
		min-width: 0;
	}
	.tracks {
		grid-column: 1;
		grid-row: 1 / span 2;
		background: var(--surface);
		border-right: 1px solid var(--line);
		padding: 8px 0 24px;
	}
	.strips {
		grid-column: 2;
		grid-row: 1;
		display: grid;
		grid-template-columns: minmax(0, 1fr);
		gap: 8px;
		min-width: 0;
		max-height: 35dvh;
		overflow: auto;
	}
	.strips:has(:global(.strip)) {
		padding: 24px 32px 16px;
	}
	.question-pane {
		grid-column: 2;
		grid-row: 2;
		padding: 24px 32px 0;
	}
	.strips:has(:global(.strip)) + .question-pane {
		padding-top: 0;
	}
	.inner {
		padding-bottom: 32px;
	}
	.question-pane :global(img) {
		display: block;
		max-width: 100%;
		height: auto;
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
	.question-pane :global(button) {
		padding: 10px 18px;
		border: 1px solid #c9c4d4;
		border-radius: 12px;
		background: white;
	}
	.question-pane :global(button:disabled:not(.chosen)) {
		opacity: 0.55;
		cursor: default;
	}
	.question-pane :global(.banner) {
		padding: 16px;
		border: 1px dashed #c9c4d4;
		border-radius: 12px;
		background: #eceaf1;
	}
	.back {
		display: none;
	}
	@media (max-width: 760px) {
		.top {
			height: 52px;
			padding: 0 16px;
			gap: 8px;
		}
		.brand {
			position: absolute;
			width: 1px;
			height: 1px;
			margin: -1px;
			padding: 0;
			border: 0;
			overflow: hidden;
			clip-path: inset(50%);
			white-space: nowrap;
		}
		.card-view .back {
			display: inline-flex;
			padding: 6px 8px 6px 0;
			border: 0;
			background: none;
			color: var(--fg);
			font-weight: 600;
			white-space: nowrap;
		}
		.card-view nav {
			display: none;
		}
		nav {
			gap: 2px;
		}
		.tracks {
			grid-row: 2;
			border-right: 0;
		}
		nav button {
			padding: 6px 8px;
		}
		.split {
			grid-template-columns: minmax(0, 1fr);
		}
		.tracks,
		.strips,
		.question-pane {
			grid-column: 1;
		}
		.strips {
			background: var(--surface);
		}
		.strips:has(:global(.strip)) {
			padding: 12px 16px 16px;
		}
		.question-pane {
			display: none;
			padding: 12px 16px 0;
			background: var(--surface);
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
	}
</style>
