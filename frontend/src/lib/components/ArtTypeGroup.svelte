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

<!-- Its options in a row after its label; it sits in a row of groups. -->
<div class={["group", { disabled }]}>
  {#if label}
    <span class="caps-label">
      {label}
      {#if note}
        <span class="note">- {note}</span>
      {/if}
    </span>
  {/if}
  {@render children()}
</div>

<style>
  .group {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2) var(--space-4);
  }

  .disabled {
    opacity: 0.45;
  }

  .note {
    font-weight: 400;
    text-transform: none;
    letter-spacing: 0;
  }
</style>
