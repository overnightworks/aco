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
		SELF_REFRESH_MINUTES,
		isStale,
		lastReadAt,
		tabCounts
	} from './app/model/boardSummary';
	import { BoardStore } from './app/state/board.svelte';
	import { cardKey } from './app/model/decision';
	import { DecisionStore } from './app/state/decision.svelte';
	import QuietSign from './components/QuietSign.svelte';
	import RefreshButton from './components/RefreshButton.svelte';
	import Stage from './components/Stage.svelte';
	import TrackList from './components/TrackList.svelte';
	import UndoStrip from './components/UndoStrip.svelte';

	let { token }: { token: string | null } = $props();

	let decisions: DecisionStore | null = $state(null);
	const board = new BoardStore(
		(repo, item) => (decisions?.held(cardKey(repo, item.number)) ?? null) !== null
	);
	let selectedKey: string | null = $state(null);
	let showQuestion = $state(false);
	let decidedKey: string | null = $state(null);
	let showDecidedCard = $state(false);
	let view: ListView = $state('open');
	const counts = $derived(tabCounts(board.repos));
	const hasViews = $derived(board.status === 'ready' && decisions !== null);
	const cardView = $derived(view === 'open' ? showQuestion : view === 'decided' && showDecidedCard);
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
		if (view !== 'open') return;
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

	// The page also reads when the tab comes back to a stale reading and on its
	// timer, never while hidden; both go away with the token.
	$effect(() => {
		if (token === null) return;
		const readIfVisible = (onlyStale: boolean) => {
			if (document.visibilityState !== 'visible') return;
			if (onlyStale && !isStale(board.repos, new Date())) return;
			void board.load(token);
		};
		const onVisibility = () => readIfVisible(true);
		document.addEventListener('visibilitychange', onVisibility);
		const timer = setInterval(() => readIfVisible(false), SELF_REFRESH_MINUTES * 60_000);
		return () => {
			document.removeEventListener('visibilitychange', onVisibility);
			clearInterval(timer);
		};
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
	<header class="top" class:card-view={cardView} class:bare={!hasViews}>
		<h1 class="brand">Entscheidungs-Board</h1>
		{#if hasViews}
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
					>{OPEN_TAB_LABEL}
					<span class="n waiting" class:zero={counts.open === 0}>{counts.open}</span></button
				>
				<button
					type="button"
					aria-current={view === 'decided' ? 'page' : undefined}
					onclick={openDecided}>{DECIDED_TAB_LABEL} <span class="n">{counts.decided}</span></button
				>
			</nav>
			{#if token !== null}
				{@const readToken = token}
				<RefreshButton
					reading={board.reading}
					readAt={lastReadAt(board.repos)}
					onRefresh={() => void board.load(readToken)}
				/>
			{/if}
		{/if}
	</header>
	{#if board.status === 'no-access'}
		<p role="alert">
			<QuietSign kind="warn" />Zugang fehlt. Starte das Board im Repo und öffne den Link, den es
			ausgibt.
		</p>
	{:else if board.status === 'loading'}
		<p role="status">Lädt…</p>
	{:else if board.status === 'unavailable'}
		<p role="alert"><QuietSign kind="warn" />{SERVER_SILENT_SENTENCE} {board.error}</p>
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
		--accent-soft: #f7ecf2;
		--accent-fg: #ffffff;
		--good: #1c7350;
		--good-soft: #e4f2ea;
		--warn: #99570c;
		--warn-soft: #fdf3e2;
		--scrim: rgba(10, 8, 14, 0.45);
		--shade: rgba(0, 0, 0, 0.28);
		--shadow: 0 1px 2px rgba(20, 20, 30, 0.04), 0 6px 20px rgba(20, 20, 30, 0.05);
		--font-display: 'Oswald', Impact, sans-serif;
		--font-body: 'Open Sans', Arial, sans-serif;
		--frame-width: 880px;
		color-scheme: light dark;
	}
	@media (prefers-color-scheme: dark) {
		:global(:root) {
			--bg: #0d0d0d;
			--surface: #161618;
			--surface-2: #212125;
			--line: #2b2b30;
			--line-strong: #4a4a52;
			--fg: #e8e8ea;
			--fg-2: #babac0;
			--fg-3: #8e8e96;
			--accent: #e892c4;
			--accent-soft: #33192a;
			--accent-fg: #1c0b15;
			--good: #5cc05c;
			--good-soft: #17301a;
			--warn: #f0a030;
			--warn-soft: #2a1f10;
			--scrim: rgba(0, 0, 0, 0.65);
			--shade: rgba(0, 0, 0, 0.6);
			--shadow: none;
		}
	}
	:global(body) {
		margin: 0;
		background: var(--bg);
		color: var(--fg);
		font: 400 15px/23px var(--font-body);
		-webkit-font-smoothing: antialiased;
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
	/* A pane takes focus by script (tabindex -1) so keyboard flow and screen readers
	   continue there; a ring around the whole pane marks nothing to act on. */
	:global([tabindex='-1']:focus-visible) {
		outline: none;
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
		gap: 20px;
		padding: 0 24px;
		background: var(--surface);
		border-bottom: 1px solid var(--line);
	}
	.brand {
		margin: 0;
		font: inherit;
		font-family: var(--font-display);
		font-size: 19px;
		font-weight: 400;
		letter-spacing: 0.12em;
		text-transform: uppercase;
		white-space: nowrap;
	}
	main > p {
		align-self: center;
		display: grid;
		justify-items: center;
		gap: 14px;
		max-width: 420px;
		margin: 18vh 16px 0;
		padding: 0;
		text-align: center;
		color: var(--fg-2);
	}
	main > p[role='status']::before {
		content: '';
		width: 30px;
		height: 30px;
		border-radius: 50%;
		border: 3px solid var(--line);
		border-top-color: var(--accent);
		animation: turn 0.9s linear infinite;
	}
	main > p[role='alert'] {
		padding: 28px 28px 24px;
		border: 1px solid color-mix(in srgb, var(--warn) 30%, var(--line));
		border-radius: 16px;
		background: var(--surface);
		box-shadow: var(--shadow);
		font-size: 15px;
		color: var(--fg);
	}
	@keyframes turn {
		to {
			transform: rotate(360deg);
		}
	}
	@media (prefers-reduced-motion: reduce) {
		main > p[role='status']::before {
			animation: none;
		}
	}
	[hidden] {
		display: none !important;
	}
	nav {
		margin-left: auto;
		display: flex;
		align-items: center;
		gap: 6px;
	}
	nav button {
		display: flex;
		align-items: center;
		gap: 8px;
		height: 38px;
		padding: 0 8px 0 14px;
		border: 0;
		border-radius: 999px;
		background: none;
		font-family: var(--font-display);
		font-size: 15px;
		font-weight: 400;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--fg-2);
		white-space: nowrap;
		transition:
			background-color 0.15s,
			color 0.15s;
	}
	nav button:hover {
		background: var(--surface-2);
		color: var(--fg);
	}
	nav button[aria-current='page'] {
		background: var(--fg);
		color: var(--surface);
	}
	nav button .n {
		min-width: 24px;
		height: 24px;
		padding: 0 7px;
		border-radius: 999px;
		background: var(--surface-2);
		font-family: var(--font-body);
		font-size: 12.5px;
		font-weight: 600;
		line-height: 24px;
		letter-spacing: 0;
		text-align: center;
		text-transform: none;
		color: var(--fg-2);
	}
	nav button[aria-current='page'] .n {
		background: color-mix(in srgb, var(--surface) 18%, transparent);
		color: var(--surface);
	}
	nav button .n.waiting:not(.zero) {
		background: var(--accent);
		color: var(--accent-fg);
	}
	@media (prefers-reduced-motion: reduce) {
		nav button {
			transition: none;
		}
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
		padding: 6px 0 32px;
	}
	/* Nothing to show: the list's calm state fills the page instead of a column
	   beside an empty stage. */
	.split:has(:global(.empty)) {
		grid-template-columns: minmax(0, 1fr);
	}
	.split:has(:global(.empty)) .question-pane {
		display: none;
	}
	.split:has(:global(.empty)) .tracks {
		grid-column: 1;
		grid-row: 2;
		display: grid;
		place-items: center;
		border-right: 0;
		background: var(--bg);
	}
	.split:has(:global(.empty)) .strips {
		grid-column: 1;
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
		border: 1px solid var(--line-strong);
		border-radius: 12px;
		resize: vertical;
	}
	.question-pane :global(button) {
		padding: 10px 18px;
		border: 1px solid var(--line-strong);
		border-radius: 12px;
		background: var(--surface);
	}
	.question-pane :global(button:disabled:not(.chosen)) {
		opacity: 0.55;
		cursor: default;
	}
	.question-pane :global(.banner) {
		padding: 16px;
		border: 1px dashed var(--line-strong);
		border-radius: 12px;
		background: var(--surface-2);
	}
	.top > :global(.refresh) {
		flex-shrink: 0;
	}
	.back {
		display: none;
	}
	@media (max-width: 760px) {
		.top {
			height: auto;
			min-height: 52px;
			flex-wrap: wrap;
			align-content: center;
			padding: 0 12px;
			gap: 0 8px;
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
		.bare .brand {
			position: static;
			width: auto;
			height: auto;
			margin: 0 0 0 4px;
			overflow: visible;
			clip-path: none;
			font-size: 17px;
		}
		.card-view .back {
			display: inline-flex;
			padding: 6px 8px 6px 0;
			border: 0;
			background: none;
			color: var(--fg);
			font-family: var(--font-display);
			font-weight: 400;
			letter-spacing: 0.08em;
			text-transform: uppercase;
			white-space: nowrap;
		}
		.card-view nav {
			display: none;
		}
		.top > :global(.refresh) {
			margin-left: auto;
		}
		nav {
			margin-left: 0;
			flex-wrap: wrap;
			gap: 4px;
		}
		.tracks {
			grid-row: 2;
			border-right: 0;
		}
		nav button {
			padding: 0 6px 0 12px;
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
