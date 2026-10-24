<script lang="ts">
  import Folder from "@lucide/svelte/icons/folder";
  let {
    title,
    count,
    style,
    onselect,
  }: { title: string; count: number; style: string; onselect: () => void } = $props();
</script>

<button
  type="button"
  class="group-row"
  {style}
  aria-label={`Open group ${title}`}
  onclick={onselect}
>
  <Folder size={26} /><span><strong>{title}</strong><small>{count} collections</small></span>
</button>

<style>
  .group-row {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    padding: var(--space-3);
    width: 100%;
    text-align: left;
    border-radius: var(--radius-sm);
  }
  .group-row:hover {
    background: var(--bg-hover);
  }
  span {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    min-width: 0;
  }
  strong {
    font-size: var(--text-sm);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  small {
    color: var(--text-tertiary);
  }
</style>
