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
		saving,
		children
	}: {
		repo: string;
		item: number;
		line: OptionLine;
		/** The card's answer is being saved (ABRD-100). */
		saving: boolean;
		children?: Snippet;
	} = $props();
</script>

<div class="option-card">
	<CardFrame
		meta={{ ...cardMeta(repo, line), ...(saving && { saving: true as const }) }}
		title={line.question}
	>
		<OptionRows {repo} {item} {line} />
		{@render children?.()}
	</CardFrame>
</div>
