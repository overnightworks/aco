<script lang="ts">
	import { RELOAD_LABEL } from '../app/model/decision';
	import { locksCard, type DecisionBanner } from '../app/state/decision.svelte';

	let { banner, onReload }: { banner: DecisionBanner; onReload: () => void } = $props();
</script>

<p role="alert" class="banner">{banner.message}</p>
{#if locksCard(banner)}
	<button type="button" onclick={onReload}>
		{RELOAD_LABEL}
	</button>
{/if}
