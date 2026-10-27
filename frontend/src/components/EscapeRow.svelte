<script lang="ts">
	import { tick } from 'svelte';
	import { NOTE_MAX_LENGTH } from '../app/model/decision';
	import {
		ESCAPE_LABEL,
		sendsBlank,
		type EscapeKind,
		type EscapePanel
	} from '../app/model/optionCard';
	import type { OptionLine } from '../types';

	let {
		line,
		panel,
		draft,
		pending,
		refreshing,
		onOpen,
		onClose,
		onDraft,
		onSend
	}: {
		line: OptionLine;
		/** The open panel with the card as shown when it opened; null while closed. */
		panel: EscapePanel | null;
		/** The text of the open panel's kind. */
		draft: string;
		pending: boolean;
		refreshing: boolean;
		onOpen: (kind: EscapeKind, shown: OptionLine) => void;
		onClose: () => void;
		onDraft: (text: string) => void;
		onSend: (open: EscapePanel, text: string) => void;
	} = $props();

	let textarea: HTMLTextAreaElement | undefined = $state();

	// A card with its head is not sent back again (ABRD-61).
	const kinds: EscapeKind[] = $derived(
		line.returned_on === null ? ['other', 'unclear'] : ['other']
	);

	async function toggle(kind: EscapeKind) {
		if (refreshing) return;
		if (panel?.kind === kind) {
			onClose();
			return;
		}
		onOpen(kind, line);
		await tick();
		textarea?.focus();
	}

	function blocked(open: EscapePanel): boolean {
		return pending || (draft.trim() === '' && !sendsBlank(open.kind));
	}

	function send(open: EscapePanel) {
		if (refreshing || blocked(open)) return;
		onSend(open, draft);
	}
</script>

<div class="escapes">
	{#each kinds as kind (kind)}
		<button
			type="button"
			class="quiet"
			aria-expanded={panel?.kind === kind}
			disabled={pending}
			aria-disabled={refreshing}
			onclick={() => toggle(kind)}
		>
			{ESCAPE_LABEL[kind].button}
		</button>
	{/each}
</div>
{#if panel !== null && kinds.includes(panel.kind)}
	{@const open = panel}
	<div class="panel">
		<textarea
			bind:this={textarea}
			aria-label={ESCAPE_LABEL[open.kind].field}
			placeholder={ESCAPE_LABEL[open.kind].placeholder}
			maxlength={NOTE_MAX_LENGTH}
			value={draft}
			oninput={(event) => onDraft(event.currentTarget.value)}></textarea>
		<div class="acts">
			<button
				type="button"
				class="send"
				disabled={blocked(open)}
				aria-disabled={refreshing}
				onclick={() => send(open)}
			>
				{ESCAPE_LABEL.send}
			</button>
		</div>
	</div>
{/if}

<style>
	.escapes {
		display: flex;
		margin-left: auto;
	}
	.escapes button.quiet {
		height: 40px;
		padding: 0 12px;
		border: 1.5px solid transparent;
		border-radius: 8px;
		background: none;
		color: var(--fg-2);
		font-weight: 600;
	}
	.escapes button.quiet:hover:enabled:not([aria-disabled='true']),
	.escapes button.quiet[aria-expanded='true'] {
		border-color: var(--line-strong);
		color: var(--fg);
	}
	.escapes button[aria-disabled='true'],
	.acts button[aria-disabled='true'] {
		opacity: 0.55;
		cursor: default;
	}
	.panel {
		flex-basis: 100%;
		margin-top: 8px;
	}
	textarea {
		box-sizing: border-box;
		width: 100%;
		height: 72px;
		max-height: 25vh;
		padding: 8px 10px;
		border: 1.5px solid var(--line-strong);
		border-radius: 8px;
		background: var(--surface);
		color: var(--fg);
		font: inherit;
		resize: vertical;
	}
	.acts {
		display: flex;
		justify-content: flex-end;
		margin-top: 8px;
	}
	.acts button.send {
		height: 40px;
		padding: 0 16px;
		border: 1.5px solid var(--fg);
		border-radius: 8px;
		background: var(--fg);
		color: var(--surface);
		font-weight: 600;
	}
	.acts button.send:disabled {
		opacity: 0.4;
	}
</style>
