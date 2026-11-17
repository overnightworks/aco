<script lang="ts">
	import { tick } from 'svelte';
	import { NOTE_MAX_LENGTH } from '../app/model/decision';
	import {
		ESCAPE_LABEL,
		pointPrefix,
		sendsBlank,
		type EscapeKind,
		type EscapePanel
	} from '../app/model/optionCard';
	import type { OptionLine } from '../types';

	let {
		points,
		kinds,
		number = null,
		panel,
		draft,
		pending,
		onOpen,
		onClose,
		onDraft,
		onSend
	}: {
		/** The points the escapes answer, as shown now. */
		points: readonly OptionLine[];
		/** The escapes on offer, in order. */
		kinds: readonly EscapeKind[];
		/** The place of the one point the escapes answer, when the row stands at a point. */
		number?: number | null;
		/** The open panel with the card as shown when it opened; null while closed. */
		panel: EscapePanel | null;
		/** The text of the open panel's kind. */
		draft: string;
		pending: boolean;
		onOpen: (kind: EscapeKind, shown: readonly OptionLine[]) => void;
		onClose: () => void;
		onDraft: (text: string) => void;
		onSend: (open: EscapePanel, text: string) => void;
	} = $props();

	let textarea: HTMLTextAreaElement | undefined = $state();

	/** A row at a point names the point in its accessible names. */
	function named(text: string): string {
		return number === null ? text : `${pointPrefix(number)}${text}`;
	}

	async function toggle(kind: EscapeKind) {
		if (panel?.kind === kind) {
			onClose();
			return;
		}
		onOpen(kind, points);
		await tick();
		textarea?.focus();
	}

	function blocked(open: EscapePanel): boolean {
		return pending || (draft.trim() === '' && !sendsBlank(open.kind));
	}

	function send(open: EscapePanel) {
		if (blocked(open)) return;
		onSend(open, draft);
	}
</script>

<div class="escapes">
	{#each kinds as kind (kind)}
		<button
			type="button"
			class="quiet"
			aria-expanded={panel?.kind === kind}
			aria-label={number === null ? undefined : named(ESCAPE_LABEL[kind].button)}
			disabled={pending}
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
			aria-label={named(ESCAPE_LABEL[open.kind].field)}
			placeholder={ESCAPE_LABEL[open.kind].placeholder}
			maxlength={NOTE_MAX_LENGTH}
			value={draft}
			oninput={(event) => onDraft(event.currentTarget.value)}></textarea>
		<div class="acts">
			<button type="button" class="send" disabled={blocked(open)} onclick={() => send(open)}>
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
		height: 44px;
		padding: 0 12px;
		border: 1.5px solid transparent;
		border-radius: 10px;
		background: none;
		color: var(--fg-2);
		font-weight: 600;
	}
	.escapes button.quiet:hover:enabled,
	.escapes button.quiet[aria-expanded='true'] {
		border-color: var(--line-strong);
		color: var(--fg);
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
