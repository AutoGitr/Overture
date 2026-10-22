<script lang="ts">
  import LoaderCircle from "@lucide/svelte/icons/loader-circle";
  import PanelLeftClose from "@lucide/svelte/icons/panel-left-close";
  import PanelLeftOpen from "@lucide/svelte/icons/panel-left-open";
  import { OPERATIONS } from "../stores/operations";
  import { uiState } from "../stores/uiState.svelte";
  import HeaderMenu from "./HeaderMenu.svelte";
  import ProductBrand from "./ProductBrand.svelte";

  let { onLogout }: { onLogout: () => void } = $props();
</script>

<header class="header">
  <div class="header-left">
    <button
      type="button"
      class={["btn btn-ghost btn-icon sidebar-toggle", { active: !uiState.mobileShowDetail }]}
      onclick={() => {
        uiState.mobileShowDetail = !uiState.mobileShowDetail;
      }}
      title={uiState.mobileShowDetail ? "Show sidebar" : "Hide sidebar"}
      aria-label="Toggle sidebar"
    >
      {#if uiState.mobileShowDetail}
        <PanelLeftOpen size={18} />
      {:else}
        <PanelLeftClose size={18} />
      {/if}
    </button>
    <!-- target="_self" opts out of client-side routing: a full reload of the
         landing page, which picks up a waiting service-worker update and is the
         only way to refresh an installed PWA. -->
    <ProductBrand as="h1" size="md" href="/" target="_self" />
  </div>

  <div class="header-actions">
    {#each ["assets", "sync"] as const as tab (tab)}
      {@const operation = OPERATIONS[tab]}
      <button
        type="button"
        class={["btn btn-ghost header-action-btn", { active: operation.running }]}
        onclick={(event) => {
          // The popup gives focus back to its opener when it closes.
          event.currentTarget.focus();
          uiState.openOperations(tab);
        }}
        title={operation.label}
        aria-label={operation.label}
      >
        {#if operation.running}
          <LoaderCircle size={18} class="animate-spin" />
        {:else}
          <operation.icon size={18} />
        {/if}
        <span class="action-label">{operation.label}</span>
      </button>
    {/each}

    <HeaderMenu {onLogout} />
  </div>
</header>

<style>
  .header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    height: var(--header-height);
    padding: var(--safe-area-top) calc(var(--space-5) + var(--safe-area-right)) 0
      calc(var(--space-5) + var(--safe-area-left));
    background: oklch(from var(--bg-primary) l c h / 0.85);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    border-bottom: var(--border-subtle);
    flex-shrink: 0;
    z-index: 100;
  }

  .header-left {
    display: flex;
    align-items: center;
    gap: var(--space-2);
  }

  .header-actions {
    display: flex;
    align-items: center;
    gap: var(--space-1);
  }

  .header-action-btn {
    gap: var(--space-1);
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-sm);
    font-size: var(--text-sm);
    font-weight: 500;
    color: var(--text-secondary);
  }

  .header-action-btn:hover {
    color: var(--text-primary);
    background: var(--bg-hover);
  }

  .header-action-btn.active {
    color: var(--accent);
    background: var(--accent-muted);
  }

  .action-label {
    display: inline;
  }

  .sidebar-toggle {
    display: none;
  }

  @media (max-width: 768px), (max-height: 500px) and (pointer: coarse) {
    .header {
      padding-right: calc(var(--space-1) + var(--safe-area-right));
      padding-left: calc(var(--space-1) + var(--safe-area-left));
    }

    .header-left {
      min-width: 0;
    }

    .header-actions {
      flex-shrink: 0;
    }

    .action-label {
      display: none;
    }

    .sidebar-toggle {
      display: flex;
      color: var(--text-secondary);
    }

    .sidebar-toggle.active {
      color: var(--accent);
      background: var(--accent-muted);
    }

    .header-action-btn,
    .sidebar-toggle {
      width: 44px;
      height: 44px;
      padding: 0;
    }
  }
</style>
