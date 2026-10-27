<script lang="ts">
  let {
    status,
    duration,
    title,
  }: {
    status: string;
    duration?: number | null;
    title?: string | null;
  } = $props();
</script>

<p class="theme-facts" title={title ?? undefined}>
  Theme: {status}
  {#if duration != null}<span
      >{Math.floor(duration / 60)}:{String(duration % 60).padStart(2, "0")}</span
    >{/if}
  {#if title}<span>{title}</span>{/if}
</p>

<style>
  .theme-facts {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    margin: 0;
    font-size: var(--text-sm);
    color: var(--text-secondary);
  }

  .theme-facts > span:last-child {
    max-width: 28ch;
    overflow: hidden;
    text-overflow: ellipsis;
  }
</style>
