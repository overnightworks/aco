<script lang="ts">
	import { cardHeading, lineStatusText, openRepos } from '../app/model/boardSummary';
	import { lineKey } from '../app/model/decision';
	import type { RepoReading } from '../types';

	let {
		repos,
		selectedKey,
		onSelect
	}: { repos: RepoReading[]; selectedKey: string | null; onSelect: (key: string) => void } =
		$props();
</script>

<section aria-label="Zeilen je Item">
	{#each openRepos(repos) as repo (repo.name)}
		{#if repo.error !== null}
			<p role="alert">{repo.name}: {repo.error}</p>
		{:else}
			{#each repo.items as item (item.number)}
				<h2>{item.title} <small>{repo.name} · #{item.number}</small></h2>
				<ul>
					{#each item.lines as line (line.index)}
						{@const key = lineKey(repo.name, item.number, line)}
						<li>
							<button
								type="button"
								aria-current={key === selectedKey}
								onclick={() => onSelect(key)}
							>
								<span>{cardHeading(line)}</span>
								<span>{lineStatusText(line)}</span>
							</button>
						</li>
					{/each}
				</ul>
			{/each}
		{/if}
	{/each}
</section>
