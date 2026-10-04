<script lang="ts">
	import { lineStatusText } from '../app/model/boardSummary';
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
	{#each repos as repo (repo.name)}
		{#if repo.error !== null}
			<p role="alert">{repo.name}: {repo.error}</p>
		{:else}
			{#each repo.items as item (item.number)}
				<h2>#{item.number} {item.title}</h2>
				<ul>
					{#each item.lines as line (line.index)}
						{@const key = lineKey(repo.name, item.number, line)}
						<li>
							{#if line.ruling === null}
								<button
									type="button"
									aria-current={key === selectedKey}
									onclick={() => onSelect(key)}
								>
									<span>{line.text}</span>
									<span>{lineStatusText(line)}</span>
								</button>
							{:else}
								<span>{line.text}</span>
								<span>{lineStatusText(line)}</span>
							{/if}
						</li>
					{/each}
				</ul>
			{/each}
		{/if}
	{/each}
</section>
