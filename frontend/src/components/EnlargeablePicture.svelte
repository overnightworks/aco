<script lang="ts">
	import { tick } from 'svelte';
	import { pictureDataUri } from '../app/model/boardSummary';
	import { PICTURE_LABEL } from '../app/model/optionCard';

	let {
		picture,
		alt,
		caption,
		thumbnail = false
	}: { picture: string; alt: string; caption: string | undefined; thumbnail?: boolean } = $props();

	let dialog: HTMLDialogElement | undefined = $state();
	let isOpen = $state(false);

	async function enlarge() {
		isOpen = true;
		await tick();
		dialog?.showModal();
	}
</script>

<button
	type="button"
	class="enlarge"
	class:thumbnail
	aria-label={PICTURE_LABEL.enlarge}
	onclick={enlarge}
>
	<img src={pictureDataUri(picture)} {alt} />
	{#if thumbnail}
		<svg class="mark" aria-hidden="true" viewBox="0 0 22 22" width="22" height="22">
			<path
				d="M13 4h5v5M9 18H4v-5M18 4l-6 6M4 18l6-6"
				fill="none"
				stroke="currentColor"
				stroke-width="1.6"
				stroke-linecap="round"
				stroke-linejoin="round"
			/>
		</svg>
	{/if}
</button>
{#if caption !== undefined}<p class="caption">{caption}</p>{/if}
<dialog
	bind:this={dialog}
	aria-label={PICTURE_LABEL.dialog}
	onclose={() => {
		isOpen = false;
	}}
>
	{#if isOpen}
		<div class="big">
			<img src={pictureDataUri(picture)} {alt} />
		</div>
		<p class="caption">{alt}</p>
		<div class="actions">
			<button type="button" class="close" onclick={() => dialog?.close()}>
				{PICTURE_LABEL.close}
			</button>
		</div>
	{/if}
</dialog>

<style>
	img {
		display: block;
		max-width: 100%;
		height: auto;
	}
	.caption {
		margin: 8px 0 0;
		font-size: 13px;
		line-height: 18px;
		color: var(--oc-fg-2);
	}
	button.enlarge {
		display: block;
		max-width: 100%;
		padding: 0;
		border: 0;
		border-radius: 0;
		background: none;
		text-align: left;
		cursor: zoom-in;
	}
	.mark {
		display: none;
	}
	dialog {
		max-width: calc(100vw - 32px);
		padding: 16px;
		border: 1px solid var(--oc-line);
		border-radius: 12px;
		background: var(--oc-surface);
		color: inherit;
	}
	dialog::backdrop {
		background: rgba(10, 8, 14, 0.45);
	}
	.big {
		max-height: 70vh;
		overflow: auto;
	}
	dialog .caption {
		margin: 12px 0;
	}
	.actions {
		display: flex;
		justify-content: flex-end;
	}
	button.close {
		height: 40px;
		padding: 0 16px;
		border: 1.5px solid var(--oc-line-strong);
		border-radius: 8px;
		background: none;
		font-weight: 600;
		color: inherit;
		cursor: pointer;
	}
	@media (max-width: 760px) {
		button.enlarge.thumbnail {
			position: relative;
			zoom: 0.5;
			padding: 6px;
			border: 1px solid var(--oc-line);
			border-radius: 8px;
		}
		.thumbnail .mark {
			display: block;
			position: absolute;
			right: 4px;
			bottom: 2px;
			color: var(--oc-fg-3);
		}
	}
</style>
