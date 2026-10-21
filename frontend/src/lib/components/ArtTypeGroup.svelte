<script lang="ts">
  import type { Snippet } from "svelte";

  let {
    label,
    note = null,
    disabled = false,
    children,
  }: {
    label?: string;
    /** Why the group is unavailable, shown beside its label. */
    note?: string | null;
    disabled?: boolean;
    children: Snippet;
  } = $props();
</script>

<div class={["group", { disabled }]}>
  {#if label}
    <div class="label">
      {label}
      {#if note}
        <span class="note">- {note}</span>
      {/if}
    </div>
  {/if}
  <div class="filter-options">
    {@render children()}
  </div>
</div>

<style>
  .group {
    margin-top: var(--space-3);
    margin-bottom: var(--space-3);
  }

  .disabled {
    opacity: 0.45;
  }

  .label {
    font-size: var(--text-xs);
    font-weight: 600;
    color: var(--text-tertiary);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: var(--space-2);
  }

  .note {
    font-weight: 400;
    text-transform: none;
    letter-spacing: 0;
  }
</style>
