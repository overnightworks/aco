<script lang="ts">
	import { lineStatusText } from '../app/model/boardSummary';
	import type { RepoReading } from '../types';

	let { repos }: { repos: RepoReading[] } = $props();
</script>

<section aria-label="Zeilen je Item">
	{#each repos as repo (repo.name)}
		{#if repo.error !== null}
			<p role="alert">{repo.name}: {repo.error}</p>
		{:else}
			{#each repo.items as item (item.number)}
				<h2>#{item.number} {item.title}</h2>
				<ul>
					{#each item.lines as line (line.index)}
						<li>
							<span>{line.text}</span>
							<span>{lineStatusText(line)}</span>
						</li>
					{/each}
				</ul>
			{/each}
		{/if}
	{/each}
</section>
