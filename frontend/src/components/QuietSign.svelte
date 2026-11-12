<script lang="ts">
	let { kind }: { kind: 'good' | 'warn' } = $props();
</script>

<span class="sign {kind}" aria-hidden="true">
	{#if kind === 'good'}
		<svg viewBox="0 0 24 24">
			<path
				d="m6.5 12.5 3.6 3.6 7.4-8.2"
				fill="none"
				stroke="currentColor"
				stroke-width="2.4"
				stroke-linecap="round"
				stroke-linejoin="round"
			/>
		</svg>
	{:else}
		<svg viewBox="0 0 14 14">
			<path
				d="M7 1.6 13 12.4H1z"
				fill="none"
				stroke="currentColor"
				stroke-width="1.3"
				stroke-linejoin="round"
			/>
			<path
				d="M7 5.6v3.2M7 10.4v.1"
				stroke="currentColor"
				stroke-width="1.3"
				stroke-linecap="round"
			/>
		</svg>
	{/if}
</span>

<style>
	.sign {
		display: grid;
		place-items: center;
		border-radius: 50%;
	}
	.good {
		width: 64px;
		height: 64px;
		background: var(--good-soft);
		color: var(--good);
	}
	.good svg {
		width: 34px;
		height: 34px;
	}
	.warn {
		width: 44px;
		height: 44px;
		background: var(--warn-soft);
		color: var(--warn);
	}
	.warn svg {
		width: 24px;
		height: 24px;
	}
</style>
