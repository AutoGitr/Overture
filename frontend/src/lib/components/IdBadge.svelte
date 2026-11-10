<script lang="ts">
  import type { Snippet } from "svelte";

  /** A square link to the subject elsewhere, shown by its logo or an icon. */
  let {
    href,
    title,
    icon,
    alt,
    children,
    onclick,
    onselect,
  }: {
    title: string;
  } & (
    | { icon: string; alt: string; children?: never }
    /** An icon drawn in the badge, for a place without a logo. */
    | { icon?: never; alt?: never; children: Snippet }
  ) & (
    | { href: string; onclick?: (event: MouseEvent) => void; onselect?: never }
    | { href?: never; onclick?: never; onselect: () => void }
  ) = $props();
</script>

{#snippet content()}
  {#if children}{@render children()}{:else}<img src={icon} {alt} />{/if}
{/snippet}

{#if href}
  <a
    class="id-badge"
    {href}
    target="_blank"
    rel="noopener noreferrer"
    {title}
    aria-label={children ? title : undefined}
    {onclick}
  >
    {@render content()}
  </a>
{:else}
  <button type="button" class="id-badge" {title} aria-label={title} onclick={onselect}>
    {@render content()}
  </button>
{/if}

<style>
  .id-badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 52px;
    height: 52px;
    border-radius: var(--radius-md);
    background: var(--bg-secondary);
    border: var(--border-muted);
    box-shadow: var(--shadow-sm);
    flex-shrink: 0;
    overflow: hidden;
    color: var(--text-primary);
  }

  .id-badge:hover {
    background: var(--bg-tertiary);
  }

  img {
    width: 34px;
    height: 34px;
    object-fit: contain;
    display: block;
    filter: var(--id-badge-icon-filter, none);
  }
</style>
