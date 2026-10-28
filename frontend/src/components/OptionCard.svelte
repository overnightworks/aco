<script lang="ts">
	import type { Snippet } from 'svelte';
	import { cardMeta } from '../app/model/optionCard';
	import type { OptionLine } from '../types';
	import CardFrame from './CardFrame.svelte';
	import OptionRows from './OptionRows.svelte';

	let {
		repo,
		item,
		line,
		children
	}: { repo: string; item: number; line: OptionLine; children?: Snippet } = $props();
</script>

<div class="option-card">
	<CardFrame meta={cardMeta(repo, line)} title={line.question}>
		<OptionRows {repo} {item} {line} />
		{@render children?.()}
	</CardFrame>
</div>
