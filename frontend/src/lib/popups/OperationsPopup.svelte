<script lang="ts">
  import type { Snippet } from "svelte";
  import PopupShell from "../components/PopupShell.svelte";
  import PopupTabs from "../components/PopupTabs.svelte";
  import AssetsTab from "../components/operations/AssetsTab.svelte";
  import RenamerTab from "../components/operations/RenamerTab.svelte";
  import ServerAuditTab from "../components/operations/ServerAuditTab.svelte";
  import SyncTab from "../components/operations/SyncTab.svelte";
  import { availableOperations, OPERATIONS } from "../stores/operations";
  import { settingsState } from "../stores/settingsState.svelte";
  import { uiState, type OperationsTab } from "../stores/uiState.svelte";

  const PANELS = {
    assets: AssetsTab,
    sync: SyncTab,
    renamer: RenamerTab,
    audit: ServerAuditTab,
  } as const satisfies Record<OperationsTab, unknown>;

  let operationTabs = $derived(availableOperations(!settingsState.standalone));
  let activeTab = $derived(
    operationTabs.includes(uiState.operationsTab) ? uiState.operationsTab : "assets",
  );
  let active = $derived(OPERATIONS[activeTab]);
  let footers = $state<Partial<Record<OperationsTab, Snippet>>>({});
</script>

<PopupShell title="Operations" size="wide" onclose={() => uiState.closePopup()}>
  {#snippet icon()}
    <active.icon size={18} />
  {/snippet}

  {#snippet tabs()}
    <PopupTabs
      tabs={operationTabs.map((id) => ({ id, ...OPERATIONS[id] }))}
      active={activeTab}
      label="Operation modes"
      idPrefix="operations"
      onselect={(tab) => (uiState.operationsTab = tab)}
    />
  {/snippet}

  {#snippet about()}
    {active.about}
    Work keeps running when this window is closed.
  {/snippet}

  {#each operationTabs as tab (tab)}
    {@const Panel = PANELS[tab]}
    <div
      class="tab-panel"
      hidden={activeTab !== tab}
      role="tabpanel"
      id="operations-panel-{tab}"
      aria-labelledby="operations-tab-{tab}"
    >
      <Panel isActive={activeTab === tab} onfooterchange={(footer) => (footers[tab] = footer)} />
    </div>
  {/each}

  {#snippet footer()}
    {@const activeFooter = footers[activeTab]}
    {#if activeFooter}
      {@render activeFooter()}
    {/if}
  {/snippet}
</PopupShell>

<style>
  /* Rows for every run shown, which subgrid into it; it gives way to the
     body's height down to their lists' least heights. */
  .tab-panel:not([hidden]) {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    align-content: start;
    row-gap: 0;
    min-height: 0;
  }
</style>
