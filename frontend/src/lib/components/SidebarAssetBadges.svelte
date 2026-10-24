<script lang="ts">
  import Image from "@lucide/svelte/icons/image";
  import Music from "@lucide/svelte/icons/music";
  import type { StatusTone } from "../utils/sidebarDomain";
  let {
    title,
    artStatus = "danger",
    themeStatus = "danger",
    hideTheme = false,
    onart,
    onthemes,
  }: {
    title: string;
    artStatus?: StatusTone | null;
    themeStatus?: StatusTone | null;
    hideTheme?: boolean;
    onart: () => void | Promise<void>;
    onthemes: () => void | Promise<void>;
  } = $props();
</script>

<div class="item-badges">
  <button
    type="button"
    class="item-badge"
    aria-label={`Open art for ${title}`}
    title="Art"
    data-status={artStatus ?? "danger"}
    onclick={onart}><Image size={18} /></button
  >
  {#if !hideTheme}
    <button
      type="button"
      class="item-badge"
      aria-label={`Open themes for ${title}`}
      title="Theme Music"
      data-status={themeStatus ?? "danger"}
      onclick={onthemes}><Music size={18} /></button
    >
  {/if}
</div>

<style>
  .item-badges {
    position: relative;
    z-index: 2;
    display: flex;
    flex-shrink: 0;
    flex-direction: column;
    gap: var(--space-1);
  }
  .item-badge {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 32px;
    color: var(--tone, var(--text-tertiary));
    background: var(--bg-primary);
    border: 1.5px solid var(--tone, var(--text-tertiary));
    border-radius: var(--radius-sm);
    cursor: pointer;
  }
  .item-badge:hover {
    background: oklch(from var(--tone, var(--text-tertiary)) l c h / 0.18);
  }
  .item-badge:focus-visible {
    outline: 2px solid var(--tone, var(--text-tertiary));
    outline-offset: 1px;
  }
</style>
