<script lang="ts">
  /** A square link to the subject on another site, shown by its logo. */
  let {
    href,
    title,
    icon,
    alt,
    onclick,
    onselect,
  }: {
    title: string;
    icon: string;
    alt: string;
  } & (
    | { href: string; onclick?: (event: MouseEvent) => void; onselect?: never }
    | { href?: never; onclick?: never; onselect: () => void }
  ) = $props();
</script>

{#if href}
  <a class="id-badge" {href} target="_blank" rel="noopener noreferrer" {title} {onclick}>
    <img src={icon} {alt} />
  </a>
{:else}
  <button type="button" class="id-badge" {title} aria-label={title} onclick={onselect}>
    <img src={icon} {alt} />
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
  }

  .id-badge:hover {
    background: var(--bg-tertiary);
  }

  img {
    width: 34px;
    height: 34px;
    object-fit: contain;
    display: block;
  }
</style>
