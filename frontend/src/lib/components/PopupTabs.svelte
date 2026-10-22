<script lang="ts" generics="T extends string">
  import type Image from "@lucide/svelte/icons/image";
  import LoaderCircle from "@lucide/svelte/icons/loader-circle";

  let {
    tabs,
    active,
    label,
    idPrefix,
    onselect,
  }: {
    tabs: readonly { id: T; label: string; icon: typeof Image; running?: boolean }[];
    active: T;
    /** Names the tab list for assistive technology. */
    label: string;
    /** Prefixes the ids of each tab and the panel it controls. */
    idPrefix: string;
    onselect: (tab: T) => void;
  } = $props();
</script>

<!-- Rendered in a popup's header under its title, so the tabs never scroll
     away with the body. -->
<div class="popup-tabs" role="tablist" aria-label={label}>
  {#each tabs as tab (tab.id)}
    <button
      type="button"
      id="{idPrefix}-tab-{tab.id}"
      class={["popup-tab", { active: active === tab.id }]}
      onclick={() => onselect(tab.id)}
      role="tab"
      aria-selected={active === tab.id}
      aria-controls="{idPrefix}-panel-{tab.id}"
    >
      <tab.icon size={15} />
      <span class="tab-label">{tab.label}</span>
      {#if tab.running}
        <span class="tab-badge" title="Running">
          <LoaderCircle size={13} class="animate-spin text-accent" />
        </span>
      {/if}
    </button>
  {/each}
</div>

<style>
  .popup-tabs {
    flex: 1 1 auto;
    min-width: 0;
    display: flex;
    gap: var(--space-1);
    padding: var(--space-1);
    background: var(--bg-secondary);
    border: var(--border-subtle);
    border-radius: var(--radius-md);
    container-type: inline-size;
  }

  .popup-tab {
    flex: 1 1 0;
    min-width: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-3);
    border: none;
    border-radius: var(--radius-sm);
    background: transparent;
    color: var(--text-secondary);
    font-size: var(--text-sm);
    font-weight: 500;
    white-space: nowrap;
    cursor: pointer;
  }

  .popup-tab:hover {
    color: var(--text-primary);
    background: var(--bg-hover);
  }

  .popup-tab.active {
    color: var(--accent);
    background: var(--accent-muted);
    box-shadow:
      inset 0 0 0 1px var(--accent-border),
      0 0 14px var(--accent-glow);
    font-weight: 600;
  }

  .tab-label {
    overflow: hidden;
    text-overflow: ellipsis;
  }

  /* Too narrow for every label: the other tabs keep only their icons, and
     their names for assistive technology. */
  @container (max-width: 34rem) {
    .popup-tab:not(.active) .tab-label {
      position: absolute;
      width: 1px;
      height: 1px;
      overflow: hidden;
      clip-path: inset(50%);
      white-space: nowrap;
    }

    .popup-tab.active {
      flex-grow: 3;
    }
  }

  .tab-badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
  }
</style>
