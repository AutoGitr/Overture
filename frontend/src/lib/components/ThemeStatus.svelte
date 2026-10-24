<script lang="ts">
  let {
    status,
    duration,
    title,
    unavailable,
  }: {
    status: string;
    duration?: number | null;
    title?: string | null;
    unavailable?: string | null;
  } = $props();
</script>

<span class="theme-facts" title={unavailable ?? title ?? undefined}>
  {unavailable ? "Themes unsupported" : `Theme: ${status}`}
  {#if !unavailable && duration != null}<span
      >{Math.floor(duration / 60)}:{String(duration % 60).padStart(2, "0")}</span
    >{/if}
  {#if !unavailable && title}<span>{title}</span>{/if}
</span>

<style>
  .theme-facts {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    padding: 0 var(--space-3);
    font-size: var(--text-sm);
    color: var(--text-secondary);
  }

  .theme-facts > span:last-child {
    max-width: 28ch;
    overflow: hidden;
    text-overflow: ellipsis;
  }
</style>
