<script lang="ts">
	import { isBoardEmpty } from './app/model/boardSummary';
	import { BoardStore } from './app/state/board.svelte';
	import TrackList from './components/TrackList.svelte';

	let { token }: { token: string | null } = $props();

	const board = new BoardStore();

	$effect(() => {
		if (token === null) {
			board.setNoAccess();
		} else {
			void board.load(token);
		}
	});
</script>

<main>
	<h1>aco-board</h1>
	{#if board.status === 'no-access'}
		<p role="alert">Zugang fehlt. Starte das Board im Repo und öffne den Link, den es ausgibt.</p>
	{:else if board.status === 'loading'}
		<p role="status">Lädt…</p>
	{:else if board.status === 'unavailable'}
		<p role="alert">aco antwortet nicht. {board.error}</p>
	{:else if isBoardEmpty(board.repos)}
		<p>Nichts offen. Neue Fragen erscheinen hier nach Neuladen, sobald ein Agent eine stellt.</p>
	{:else}
		<TrackList repos={board.repos} />
	{/if}
</main>
