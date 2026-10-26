<script lang="ts">
	import type { Snippet } from 'svelte';
	import { type FrameMeta, UNDO_LABEL } from '../app/model/optionCard';
	import WarnMark from './WarnMark.svelte';

	let { meta, title, children }: { meta: FrameMeta; title: string; children: Snippet } = $props();
</script>

<div class="frame">
	<p class="meta">
		<span>{meta.where}</span>
		{#if meta.kind !== undefined}
			<span class="sep" aria-hidden="true">·</span>
			<span>{meta.kind}</span>
		{/if}
		{#if meta.undo !== undefined}
			<span class="sep" aria-hidden="true">·</span>
			{#if meta.undo === 'final'}
				<span class="final">
					<WarnMark />{UNDO_LABEL[meta.undo]}
				</span>
			{:else}
				<span>{UNDO_LABEL[meta.undo]}</span>
			{/if}
		{/if}
	</p>
	<article>
		<h2>{title}</h2>
		<dl>
			{@render children()}
		</dl>
	</article>
</div>

<style>
	.frame {
		--oc-label-width: 136px;
		--oc-column-gap: 24px;
		max-width: 880px;
		margin-inline: auto;
	}
	.meta {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: 0 8px;
		margin: 0 0 8px 2px;
		font-size: 13px;
		line-height: 18px;
		color: var(--fg-3);
	}
	.sep {
		opacity: 0.6;
	}
	.final {
		color: var(--warn);
		font-weight: 600;
	}
	article {
		background: var(--surface);
		border: 1px solid var(--line);
		border-radius: 12px;
		padding: 24px 32px 32px;
	}
	h2 {
		margin: 0 0 24px;
		font-size: 22px;
		line-height: 28px;
		font-weight: 650;
		letter-spacing: -0.01em;
	}
	dl {
		display: grid;
		row-gap: 16px;
		margin: 0;
	}
	@media (max-width: 760px) {
		article {
			padding: 16px;
		}
		h2 {
			font-size: 20px;
			line-height: 26px;
			margin-bottom: 16px;
		}
		dl {
			row-gap: 12px;
		}
	}
</style>
