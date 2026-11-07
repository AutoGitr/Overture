<script lang="ts">
  import type { MediaIcon } from "../utils/mediaIcons";
  import FallbackImage from "./FallbackImage.svelte";

  let {
    title,
    icon: Icon,
    src,
    fallbackSrc = null,
    onselect,
    meta = null,
  }: {
    title: string;
    /** Shown while the poster is missing or loading. */
    icon: MediaIcon;
    src: string | null;
    fallbackSrc?: string | null;
    onselect: () => void;
    meta?: string | null;
  } = $props();
</script>

<button class="poster-card card card-interactive" onclick={onselect}>
  <div class="poster">
    {#snippet placeholder()}<Icon size={24} />{/snippet}
    <FallbackImage {src} {fallbackSrc} alt="" {placeholder} />
  </div>
  <div class="info">
    <span class="title">{title}</span>
    {#if meta}<span class="meta">{meta}</span>{/if}
  </div>
</button>

<style>
  .poster-card {
    overflow: hidden;
    padding: 0;
    text-align: left;
  }
  .poster {
    display: flex;
    align-items: center;
    justify-content: center;
    aspect-ratio: 2 / 3;
    overflow: hidden;
    background: var(--bg-tertiary);
    color: var(--text-tertiary);
  }
  .info {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    padding: var(--space-3);
  }
  .title {
    font-size: var(--text-sm);
    font-weight: 500;
  }
  .meta {
    font-size: var(--text-xs);
    color: var(--text-tertiary);
  }
</style>
