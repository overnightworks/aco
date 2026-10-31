<script lang="ts">
	import type { Snippet } from 'svelte';
	import { type FrameMeta, META_LABEL, UNDO_LABEL } from '../app/model/optionCard';
	import WarnMark from './WarnMark.svelte';

	let { meta, title, children }: { meta: FrameMeta; title: string; children: Snippet } = $props();

	interface Token {
		text: string;
		final: boolean;
	}

	// The picture's order: kind, with head, saving, then the undo token.
	const tokens: Token[] = $derived([
		...(meta.kind !== undefined ? [{ text: meta.kind, final: false }] : []),
		...(meta.withHead ? [{ text: META_LABEL.withHead, final: false }] : []),
		...(meta.saving ? [{ text: META_LABEL.saving, final: false }] : []),
		...(meta.undo !== undefined
			? [{ text: UNDO_LABEL[meta.undo], final: meta.undo === 'final' }]
			: [])
	]);
</script>

<div class="frame">
	<p class="meta">
		<span class="where">{meta.where}</span>
		{#if tokens.length > 0}
			<span class="sep lead" aria-hidden="true">·</span>
			<span class="props">
				{#each tokens as token, position (token.text)}
					{#if position > 0}
						<span class="sep" aria-hidden="true">·</span>
					{/if}
					{#if token.final}
						<span class="final">
							<WarnMark />{token.text}
						</span>
					{:else}
						<span>{token.text}</span>
					{/if}
				{/each}
			</span>
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
		max-width: var(--frame-width);
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
	.props {
		display: inline-flex;
		flex-wrap: wrap;
		gap: 0 8px;
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
		.meta {
			display: block;
			margin-bottom: 12px;
		}
		.where,
		.props {
			display: flex;
		}
		.lead {
			display: none;
		}
		article {
			padding: 0;
			border: 0;
			border-radius: 0;
			background: none;
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
