<script lang="ts">
	import { tick } from 'svelte';
	import { NOTE_MAX_LENGTH } from '../app/model/decision';
	import { ESCAPE_LABEL } from '../app/model/optionCard';
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
		/** The card as shown when the panel opened; null while it is closed. */
		panel: OptionLine | null;
		draft: string;
		pending: boolean;
		refreshing: boolean;
		onOpen: (shown: OptionLine) => void;
		onClose: () => void;
		onDraft: (text: string) => void;
		onSend: (shown: OptionLine, text: string) => void;
	} = $props();

	let textarea: HTMLTextAreaElement | undefined = $state();

	async function toggle() {
		if (refreshing) return;
		if (panel !== null) {
			onClose();
			return;
		}
		onOpen(line);
		await tick();
		textarea?.focus();
	}

	function send(shown: OptionLine) {
		if (refreshing || pending || draft.trim() === '') return;
		onSend(shown, draft);
	}
</script>

<div class="escapes">
	<button
		type="button"
		class="quiet"
		aria-expanded={panel !== null}
		disabled={pending}
		aria-disabled={refreshing}
		onclick={toggle}
	>
		{ESCAPE_LABEL.other}
	</button>
</div>
{#if panel !== null}
	{@const shown = panel}
	<div class="panel">
		<textarea
			bind:this={textarea}
			aria-label={ESCAPE_LABEL.answer}
			placeholder={ESCAPE_LABEL.placeholder}
			maxlength={NOTE_MAX_LENGTH}
			value={draft}
			oninput={(event) => onDraft(event.currentTarget.value)}></textarea>
		<div class="acts">
			<button
				type="button"
				class="send"
				disabled={pending || draft.trim() === ''}
				aria-disabled={refreshing}
				onclick={() => send(shown)}
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
