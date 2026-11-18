<script lang="ts">
	import { NOTE_MAX_LENGTH, stepKey } from '../app/model/decision';
	import {
		FAILURE_LABEL,
		NOTE_LABEL,
		REPORT_LABEL,
		SEND_LABEL,
		SUCCESS_LABEL
	} from '../app/model/steps';
	import type { DecisionStore } from '../app/state/decision.svelte';
	import type { StepRead } from '../types';
	import RefusalBanner from './RefusalBanner.svelte';
	import UndoStrip from './UndoStrip.svelte';

	let { repo, step, decisions }: { repo: string; step: StepRead; decisions: DecisionStore } =
		$props();

	const key = $derived(stepKey(repo, step.number));
	const pending = $derived(decisions.pendingStep(key));
	const busy = $derived(pending !== null || decisions.isSaving(key));
	const banner = $derived(decisions.banner(key));
	const asksReport = $derived(step.answer !== null);

	let report = $state('');
	let note = $state('');
	let failing = $state(false);
</script>

{#if pending !== null}
	<UndoStrip
		message={pending.message}
		kind={pending.state}
		onUndo={() => decisions.undo(pending.key)}
	/>
{:else}
	{#if banner !== null}
		<RefusalBanner {banner} onReload={() => void decisions.reloadAfterBanner(key)} />
	{/if}
	<div class="answer-row">
		{#if asksReport}
			<label>
				{REPORT_LABEL}
				<textarea bind:value={report} maxlength={NOTE_MAX_LENGTH} rows="2" disabled={busy}
				></textarea>
			</label>
			<button
				type="button"
				class="primary"
				disabled={busy || report.trim() === ''}
				onclick={() => decisions.answerStep(repo, step, 'report', report)}>{SEND_LABEL}</button
			>
		{:else}
			<button
				type="button"
				class="primary"
				disabled={busy}
				onclick={() => decisions.answerStep(repo, step, 'yes', '')}>{SUCCESS_LABEL}</button
			>
		{/if}
		<button
			type="button"
			aria-expanded={failing}
			disabled={busy}
			onclick={() => (failing = !failing)}>{FAILURE_LABEL}</button
		>
	</div>
	{#if failing}
		<div class="answer-row">
			<label>
				{NOTE_LABEL}
				<textarea bind:value={note} maxlength={NOTE_MAX_LENGTH} rows="2" disabled={busy}></textarea>
			</label>
			<button
				type="button"
				disabled={busy || note.trim() === ''}
				onclick={() => decisions.answerStep(repo, step, 'no', note)}>{SEND_LABEL}</button
			>
		</div>
	{/if}
{/if}

<style>
	.answer-row {
		display: flex;
		flex-wrap: wrap;
		align-items: end;
		gap: 8px;
		margin: 8px 0 0;
	}
	label {
		display: grid;
		flex: 1 1 100%;
		gap: 4px;
		font-size: 13px;
		color: var(--fg-2);
	}
	textarea {
		padding: 8px 10px;
		border: 1px solid var(--line);
		border-radius: 8px;
		background: var(--surface);
		color: var(--fg);
		font: inherit;
		resize: vertical;
	}
	button {
		padding: 6px 14px;
		border: 1px solid var(--line);
		border-radius: 8px;
		background: var(--surface-2);
		color: var(--fg);
		font: inherit;
		font-size: 13px;
		cursor: pointer;
	}
	button.primary {
		border-color: color-mix(in srgb, var(--good) 40%, var(--line));
		background: var(--good-soft);
		font-weight: 600;
	}
	button:disabled {
		opacity: 0.5;
		cursor: default;
	}
</style>
