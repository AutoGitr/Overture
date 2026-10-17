<script lang="ts">
  import ChartColumn from "@lucide/svelte/icons/chart-column";
  import Database from "@lucide/svelte/icons/database";
  import DatabaseBackup from "@lucide/svelte/icons/database-backup";
  import LoaderCircle from "@lucide/svelte/icons/loader-circle";
  import LogOut from "@lucide/svelte/icons/log-out";
  import Menu from "@lucide/svelte/icons/menu";
  import PanelLeftClose from "@lucide/svelte/icons/panel-left-close";
  import PanelLeftOpen from "@lucide/svelte/icons/panel-left-open";
  import Settings from "@lucide/svelte/icons/settings";
  import {
    getBackupScheduleOptions,
    getStatsOptions,
    listBackupsOptions,
  } from "../../generated/rest/@tanstack/svelte-query.gen";
  import { queryClient } from "../rest/queryClient";
  import { session } from "../auth/session.svelte";
  import { OPERATIONS } from "../stores/operations";
  import { uiState, type OperationsTab } from "../stores/uiState.svelte";
  import ProductBrand from "./ProductBrand.svelte";

  let { onLogout }: { onLogout: () => void } = $props();
  let menuOpen = $state(false);
  let menuWrapper: HTMLDivElement | null = null;
  let menuButton: HTMLButtonElement;
  const menuId = $props.id();
  /** The pointer that pressed the menu button; empty for a keyboard press. */
  let pressedWith = "";

  function closeMenu() {
    menuOpen = false;
  }

  // A mouse or pen opens the menu by hovering and closes it by leaving; a
  // click never pins it open. Touch and keyboard have no hover, so a tap or
  // Enter toggles it instead.
  function hovers(event: PointerEvent) {
    return event.pointerType !== "touch";
  }

  function pressMenuButton() {
    if (pressedWith === "mouse" || pressedWith === "pen") menuOpen = true;
    else menuOpen = !menuOpen;
    pressedWith = "";
  }

  $effect(() => {
    if (!menuOpen) return;

    function handlePointerDown(event: PointerEvent) {
      if (!menuWrapper) return;
      if (event.target instanceof Node && !menuWrapper.contains(event.target)) {
        closeMenu();
      }
    }

    function handleEscape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        closeMenu();
        menuButton.focus({ preventScroll: true });
      }
    }

    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleEscape);
    window.addEventListener("resize", closeMenu);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleEscape);
      window.removeEventListener("resize", closeMenu);
    };
  });

  function openPopup(name: Parameters<typeof uiState.openPopupByName>[0], opener = menuButton) {
    opener.focus();
    closeMenu();
    uiState.openPopupByName(name);
  }

  function openOperations(tab: OperationsTab, opener = menuButton) {
    opener.focus();
    closeMenu();
    uiState.openOperations(tab);
  }

  // A popup whose data is fetched once the pointer or focus reaches its menu
  // item opens with that data in place, instead of growing as it arrives.
  function prefetchBackup() {
    void queryClient.prefetchQuery(getBackupScheduleOptions());
    void queryClient.prefetchQuery(listBackupsOptions());
  }

  function prefetchStats() {
    void queryClient.prefetchQuery(getStatsOptions());
  }
</script>

<header class="header">
  <div class="header-left">
    <button
      type="button"
      class="btn btn-ghost btn-icon sidebar-toggle"
      class:active={!uiState.mobileShowDetail}
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
        class="btn btn-ghost header-action-btn"
        class:active={operation.running}
        onclick={(event) => openOperations(tab, event.currentTarget)}
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

    <div
      class="header-menu-wrapper"
      role="presentation"
      bind:this={menuWrapper}
      onpointerenter={(event) => {
        if (hovers(event)) menuOpen = true;
      }}
      onpointerleave={(event) => {
        if (hovers(event)) closeMenu();
      }}
      onfocusout={(event) => {
        if (!menuWrapper?.contains(event.relatedTarget as Node | null)) closeMenu();
      }}
    >
      <button
        type="button"
        class="btn btn-ghost btn-icon"
        class:active={menuOpen}
        title="Menu"
        aria-label="Open menu"
        aria-controls={menuId}
        aria-expanded={menuOpen}
        bind:this={menuButton}
        onpointerdown={(event) => (pressedWith = event.pointerType)}
        onclick={pressMenuButton}
      >
        <Menu size={18} />
      </button>

      <div id={menuId} class="menu-dropdown-container" class:open={menuOpen} inert={!menuOpen}>
        <div class="menu-dropdown">
          {#each ["renamer", "audit"] as const as tab (tab)}
            {@const operation = OPERATIONS[tab]}
            <button
              type="button"
              class="menu-item"
              class:active={operation.running}
              onclick={() => openOperations(tab)}
              title={operation.label}
            >
              {#if operation.running}
                <LoaderCircle size={18} class="animate-spin" />
              {:else}
                <operation.icon size={18} />
              {/if}
              <span class="menu-label">{operation.label}</span>
            </button>
          {/each}
          <button
            type="button"
            class="menu-item"
            onpointerenter={prefetchBackup}
            onfocus={prefetchBackup}
            onclick={() => openPopup("backup")}
          >
            <DatabaseBackup size={16} />
            <span class="menu-label">Backup</span>
          </button>
          <button type="button" class="menu-item" onclick={() => openPopup("overturedb")}>
            <Database size={16} />
            <span class="menu-label">OvertureDB</span>
          </button>
          <button
            type="button"
            class="menu-item"
            onpointerenter={prefetchStats}
            onfocus={prefetchStats}
            onclick={() => openPopup("stats")}
          >
            <ChartColumn size={16} />
            <span class="menu-label">Statistics</span>
          </button>
          <button type="button" class="menu-item" onclick={() => openPopup("settings")}>
            <Settings size={16} />
            <span class="menu-label">Settings</span>
          </button>
          {#if session.config.auth_mode !== "none"}
            <div class="menu-divider"></div>
            <button type="button" class="menu-item menu-item-danger" onclick={onLogout}>
              <LogOut size={16} />
              <span class="menu-label">Logout</span>
            </button>
          {/if}
        </div>
      </div>
    </div>
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
    background: var(--bg-primary);
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

  .header-action-btn :global(.animate-spin) {
    animation: spin 1s linear infinite;
  }

  .action-label {
    display: inline;
  }

  .header-menu-wrapper {
    position: relative;
  }

  .menu-dropdown-container {
    position: absolute;
    right: 0;
    top: 100%;
    padding-top: var(--space-2);
    z-index: 100;
    visibility: hidden;
  }

  .menu-dropdown-container.open {
    visibility: visible;
  }

  .menu-dropdown {
    background: var(--bg-elevated);
    border: var(--border-accent);
    border-radius: var(--radius-md);
    box-shadow: var(--shadow-lg);
    min-width: 180px;
    padding: var(--space-1);
  }

  .menu-item {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    width: 100%;
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-sm);
    font-size: var(--text-sm);
    color: var(--text-secondary);
  }

  .menu-item:hover {
    color: var(--text-primary);
    background: var(--bg-hover);
  }

  .menu-item.active {
    color: var(--accent);
    background: var(--accent-muted);
  }

  .menu-label {
    display: inline;
  }

  .menu-item-danger:hover {
    color: var(--danger);
    background: var(--danger-muted);
  }

  .menu-divider {
    height: 1px;
    background: var(--surface-glass-border);
    margin: var(--space-1) var(--space-2);
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
    .header-menu-wrapper > .btn,
    .sidebar-toggle {
      width: 44px;
      height: 44px;
      padding: 0;
    }

    .menu-dropdown-container {
      max-width: calc(100vw - var(--space-4) - var(--safe-area-left) - var(--safe-area-right));
    }
  }
</style>
