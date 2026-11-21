<script lang="ts">
	import { NOT_READ_LABEL } from '../app/model/boardSummary';
	import {
		answerText,
		COPIED_LABEL,
		COPY_FAILED_LABEL,
		COPY_LABEL,
		NO_STEPS_TEXT,
		stepCount,
		STEPS_REGION_LABEL
	} from '../app/model/steps';
	import type { RepoReading } from '../types';
	import type { DecisionStore } from '../app/state/decision.svelte';
	import StepAnswer from './StepAnswer.svelte';
	import WarnMark from './WarnMark.svelte';

	let {
		repos,
		decisions,
		current = null
	}: { repos: RepoReading[]; decisions: DecisionStore; current?: string | null } = $props();

	/** The step a link opened is brought into view once the view shows it. */
	function bringIntoView(node: HTMLElement, isCurrent: boolean) {
		if (isCurrent) node.scrollIntoView({ block: 'center' });
	}

	// A copy is told per step as listed: a changed card starts at Copy again.
	let copies: Record<string, string> = $state({});

	async function copy(key: string, text: string) {
		try {
			await navigator.clipboard.writeText(text);
			copies[key] = COPIED_LABEL;
		} catch {
			copies[key] = COPY_FAILED_LABEL;
		}
	}

	const failed = $derived(repos.filter((repo) => repo.error !== null));
	const empty = $derived(failed.length === 0 && stepCount(repos) === 0);
</script>

<section aria-label={STEPS_REGION_LABEL}>
	{#if empty}
		<p class="quiet">{NO_STEPS_TEXT}</p>
	{/if}
	{#each repos as repo (repo.name)}
		{#if repo.error !== null}
			<h2>{repo.name}</h2>
			<p class="bad-line" role="alert">
				<span class="mark"><WarnMark /></span>
				<b>{NOT_READ_LABEL}</b>
				<span>{repo.error}</span>
			</p>
		{:else if repo.steps.length > 0}
			<h2>{repo.name}</h2>
			{#each repo.steps as step (step.number)}
				{@const key = `${repo.name}#${step.number}`}
				{@const copyKey = `${key}:${step.fingerprint}`}
				<article
					aria-labelledby="step-{key}"
					aria-current={key === current ? 'true' : undefined}
					class:current={key === current}
					use:bringIntoView={key === current}
				>
					<h3 id="step-{key}"><span class="number">#{step.number}</span> {step.title}</h3>
					{#if step.purpose === null}
						<p>{step.step}</p>
					{:else}
						<p>{step.purpose}</p>
						<pre>{step.actions}</pre>
						<button type="button" class="copy" onclick={() => copy(copyKey, step.actions ?? '')}
							>{copies[copyKey] ?? COPY_LABEL}</button
						>
						<p><b>Expected</b> {step.expected}</p>
						<p class="answer">{answerText(step)}</p>
						<StepAnswer repo={repo.name} {step} {decisions} />
					{/if}
				</article>
			{/each}
		{/if}
	{/each}
</section>

<style>
	section {
		width: 100%;
		max-width: var(--frame-width);
		margin: 0 auto;
		padding: 0 16px 48px;
	}
	h2 {
		margin: 22px 8px 8px;
		font-size: 15px;
		font-weight: 600;
		color: var(--fg);
	}
	article {
		margin: 0 0 12px;
		padding: 14px 16px;
		border: 1px solid var(--line);
		border-radius: 12px;
		background: var(--surface);
		font-size: 14px;
		line-height: 21px;
	}
	article.current {
		border-color: var(--accent);
		box-shadow: inset 4px 0 0 var(--accent);
	}
	h3 {
		margin: 0 0 6px;
		font-size: 15px;
		font-weight: 600;
		overflow-wrap: anywhere;
	}
	.number {
		color: var(--fg-3);
	}
	p {
		margin: 6px 0;
		overflow-wrap: anywhere;
	}
	pre {
		margin: 8px 0 6px;
		padding: 10px 12px;
		border-radius: 8px;
		background: var(--surface-2);
		box-shadow: inset 0 0 0 1px var(--line);
		font-size: 13px;
		white-space: pre-wrap;
		overflow-wrap: anywhere;
	}
	.copy {
		margin-bottom: 6px;
		padding: 4px 12px;
		border: 1px solid var(--line);
		border-radius: 8px;
		background: var(--surface-2);
		color: var(--fg);
		font: inherit;
		font-size: 13px;
		cursor: pointer;
	}
	.answer {
		color: var(--fg-2);
	}
	.quiet {
		margin: 22px 8px;
		font-size: 13px;
		color: var(--fg-3);
	}
	.bad-line {
		display: grid;
		grid-template-columns: auto 1fr;
		gap: 2px 8px;
		margin: 0 0 12px;
		padding: 10px 12px;
		border: 1px solid color-mix(in srgb, var(--warn) 30%, transparent);
		border-radius: 10px;
		background: var(--warn-soft);
		font-size: 13px;
		line-height: 19px;
		color: var(--fg-2);
	}
	.bad-line > span:not(.mark) {
		grid-column: 2;
	}
	.bad-line b,
	.mark {
		color: var(--warn);
		font-weight: 600;
		white-space: nowrap;
	}
</style>
