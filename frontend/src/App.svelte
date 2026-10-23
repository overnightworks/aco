<script lang="ts">
	import { isBoardEmpty, nextOpenAfter } from './app/model/boardSummary';
	import { BoardStore } from './app/state/board.svelte';
	import { DecisionStore } from './app/state/decision.svelte';
	import Stage from './components/Stage.svelte';
	import TrackList from './components/TrackList.svelte';
	import UndoToast from './components/UndoToast.svelte';

	let { token }: { token: string | null } = $props();

	const board = new BoardStore();
	let decisions: DecisionStore | null = $state(null);
	let selectedKey: string | null = $state(null);

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
		<div class="decide">
			<TrackList repos={board.repos} {selectedKey} onSelect={(key) => (selectedKey = key)} />
			<Stage repos={board.repos} {selectedKey} {decisions} />
		</div>
		<div class="toasts" aria-live="polite">
			{#each decisions.pendingEntries as entry (entry.key)}
				<UndoToast message={entry.message} onUndo={() => decisions?.undo(entry.key)} />
			{/each}
		</div>
	{/if}
</main>
