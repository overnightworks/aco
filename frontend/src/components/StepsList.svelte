<script lang="ts">
	import {
		clockTime,
		LAST_READ_LABEL,
		NO_STEP_TEXT,
		noStepText,
		NOT_READ_LABEL,
		STEPS_LABEL,
		stepGroups,
		type ShownRepo
	} from '../app/model/boardSummary';
	import WarnMark from './WarnMark.svelte';

	let { repos }: { repos: ShownRepo[] } = $props();

	const groups = $derived(stepGroups(repos));
</script>

<section aria-labelledby="steps-heading">
	<h2 id="steps-heading" class="heading">{STEPS_LABEL}</h2>
	{#each groups as group (group.repo)}
		<h3 class="group" class:bad={group.error !== null}>{group.repo}</h3>
		{#if group.error !== null}
			<p class="bad-line" role="alert">
				<span class="mark"><WarnMark /></span>
				<b>{NOT_READ_LABEL}</b>
				<span>{group.error}</span>
				{#if group.readAt !== null}
					<span class="read-at">{LAST_READ_LABEL} {clockTime(group.readAt)}</span>
				{/if}
			</p>
		{/if}
		<ul>
			{#each group.steps as step (step.number)}
				<li>
					<p class="head"><span class="number">#{step.number}</span> <b>{step.title}</b></p>
					<p class="step" class:none={step.step === null}>{step.step ?? NO_STEP_TEXT}</p>
				</li>
			{/each}
		</ul>
	{/each}
	{#if groups.length === 0}
		<p class="empty">{noStepText(repos)}</p>
	{/if}
</section>

<style>
	.heading {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
		margin: 0;
		padding: 8px 24px 4px;
		font-size: 11px;
		font-weight: 650;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--fg-3);
	}
	.group {
		margin: 0;
		padding: 8px 24px 2px;
		font-size: 13px;
		font-weight: 600;
		color: var(--fg-2);
	}
	.group.bad {
		color: var(--warn);
	}
	.bad-line {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: 8px;
		margin: 0;
		padding: 0 24px 4px;
		font-size: 13px;
		color: var(--fg-2);
	}
	.bad-line b,
	.mark {
		color: var(--warn);
		font-weight: 600;
		white-space: nowrap;
	}
	.read-at {
		color: var(--fg-3);
		white-space: nowrap;
	}
	ul {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	li {
		padding: 6px 24px;
	}
	li p {
		margin: 0;
		overflow-wrap: anywhere;
	}
	.number {
		color: var(--fg-3);
	}
	.step {
		font-size: 13px;
		color: var(--fg-2);
		white-space: pre-wrap;
	}
	.step.none {
		color: var(--fg-3);
		font-style: italic;
	}
	.empty {
		margin: 0;
		padding: 4px 24px 8px;
		font-size: 13px;
		color: var(--fg-3);
	}
	@media (max-width: 760px) {
		.heading,
		.group,
		.bad-line,
		li,
		.empty {
			padding-left: 16px;
			padding-right: 16px;
		}
	}
</style>
