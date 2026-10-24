<script lang="ts">
  import X from "@lucide/svelte/icons/x";
  import type { StatusTone } from "../utils/sidebarDomain";

  let {
    icon: Icon,
    label,
    active = false,
    status = null,
    onselect,
    clearLabel = `Clear ${label.toLowerCase()}`,
    onclear = null,
    clearDisabled = false,
  }: {
    /** Any Lucide icon. */
    icon: typeof X;
    label: string;
    active?: boolean;
    /** The section's asset status, in the sidebar's tones; null shows none. */
    status?: StatusTone | null;
    /** Opens the section; without it the tab only names the panel shown. */
    onselect?: () => void;
    clearLabel?: string;
    /** Forgets the section's selections; null while there is nothing to forget. */
    onclear?: (() => void) | null;
    clearDisabled?: boolean;
  } = $props();
</script>

<!-- The icon carries the status. With something to forget it is its own
     button, a cross on hover; otherwise it belongs to the label. Both forms
     are the same width, so the tab never moves. -->
<div class={["tab-item status-tab", { active }]} role="presentation">
  {#if onclear}
    <button
      type="button"
      class="status-tab-clear"
      title={clearLabel}
      aria-label={clearLabel}
      disabled={clearDisabled}
      onclick={onclear}
    >
      <Icon size={16} class="status-icon" data-status={status} />
      <X size={16} class="clear-icon" />
    </button>
    {@render name(false)}
  {:else}
    {@render name(true)}
  {/if}
</div>

{#snippet name(withIcon: boolean)}
  {#snippet content()}
    {#if withIcon}
      <Icon size={16} class="status-icon" data-status={status} />
    {/if}
    <span>{label}</span>
  {/snippet}
  {#if onselect}
    <button
      type="button"
      class="status-tab-label"
      role="tab"
      aria-selected={active}
      tabindex={active ? 0 : -1}
      onclick={onselect}
    >
      {@render content()}
    </button>
  {:else}
    <span class="status-tab-label" role="tab" aria-selected={active}>
      {@render content()}
    </span>
  {/if}
{/snippet}

<style>
  .status-tab {
    align-items: stretch;
    gap: 0;
    padding: 0;
  }

  .status-tab-clear,
  .status-tab-label {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: 0 var(--space-3);
  }

  /* Split, the halves keep the label's own icon-to-text gap between them. */
  .status-tab-clear {
    padding-right: var(--space-1);
  }

  .status-tab-clear + .status-tab-label {
    padding-left: var(--space-1);
  }

  .status-tab :global(.status-icon) {
    color: var(--tone, currentColor);
  }

  .status-tab-clear :global(.clear-icon) {
    display: none;
    color: var(--danger);
  }

  .status-tab-clear:hover:not(:disabled) :global(.status-icon) {
    display: none;
  }

  .status-tab-clear:hover:not(:disabled) :global(.clear-icon) {
    display: block;
  }

  .status-tab-clear:disabled {
    cursor: not-allowed;
  }

  span.status-tab-label {
    cursor: default;
  }
</style>
