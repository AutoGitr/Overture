<script lang="ts">
  import FolderPen from "@lucide/svelte/icons/folder-pen";
  import LoaderCircle from "@lucide/svelte/icons/loader-circle";
  import RefreshCw from "@lucide/svelte/icons/refresh-cw";
  import { createMutation } from "@tanstack/svelte-query";
  import { onMount, type Snippet } from "svelte";
  import type { ServerAsset } from "../../../generated/rest/types.gen";
  import { SERVER_ASSETS } from "../../../generated/settings";
  import {
    renameAssetsMutation,
    startScanMutation,
    stopScanMutation,
  } from "../../../generated/rest/@tanstack/svelte-query.gen";
  import ArtTypeFiltersCard from "../ArtTypeFiltersCard.svelte";
  import AssetRenamerResultsPanel from "../AssetRenamerResultsPanel.svelte";
  import FolderScopeCard from "../FolderScopeCard.svelte";
  import PendingButton from "../PendingButton.svelte";
  import JobFooter from "./JobFooter.svelte";
  import { assetManagerState } from "../../stores/assetManagerState.svelte";
  import { libraryGate } from "../../stores/libraryGate.svelte";
  import { createNotifier } from "../../stores/notificationState.svelte";
  import { assetRenameRequests } from "../../utils/assetRenamerPopup";
  import { assetsInScope } from "../../utils/artTypes";
  import { errorMessage } from "../../utils/errors";
  import { createFolderScope } from "../../utils/folderScope.svelte";
  import { createClearResults } from "../../utils/jobSnapshots";
  import { persistedState } from "../../utils/persistedState.svelte";
  import { toggleSelectedValue } from "../../utils/popupSelection";

  let {
    isActive = false,
    onfooterchange,
  }: {
    isActive?: boolean;
    onfooterchange?: (footer: Snippet) => void;
  } = $props();

  const scope = createFolderScope("assetPopup", () => isActive);
  const config = persistedState("assetPopup", {
    artTypes: [...SERVER_ASSETS],
  });
  /** The chosen types the scope has files for. */
  let artTypes = $derived(
    assetsInScope(config.artTypes, { hasSelection: scope.hasSelection, hasShows: scope.hasShows }),
  );
  let canScan = $derived(artTypes.length > 0 && scope.hasSelection && scope.ready);

  const feedback = createNotifier();
  const startScanRequest = createMutation(() => startScanMutation());
  const stopScanRequest = createMutation(() => stopScanMutation());
  const renameRequest = createMutation(() => renameAssetsMutation());
  const clearResults = createClearResults(() => ["asset_scan"], feedback);
  /** Results show exactly while a run exists, never ahead of the server's answer. */
  let hasResults = $derived(assetManagerState.hasRun);
  let stopping = $derived(stopScanRequest.isPending || assetManagerState.stopping);
  let selectedIssues = $derived(assetManagerState.running ? [] : assetManagerState.selectedItems);

  onMount(() => {
    onfooterchange?.(renamerFooter);
  });

  function toggleArtType(type: ServerAsset) {
    config.artTypes = toggleSelectedValue(config.artTypes, type);
  }

  async function startScan() {
    if (!canScan || libraryGate.itemsBlocked) return;
    config.save();
    feedback.clear();
    try {
      await startScanRequest.mutateAsync({ body: { art_types: artTypes, ...scope.request() } });
      assetManagerState.markStartAccepted();
    } catch (err) {
      feedback.error(errorMessage(err, "Asset scan failed"));
    }
  }

  async function stopScan() {
    feedback.clear();
    try {
      await stopScanRequest.mutateAsync({});
      assetManagerState.markStopRequested();
    } catch (error) {
      feedback.error(errorMessage(error, "Could not stop the scan. Please retry."));
    }
  }

  async function renameSelected() {
    if (!selectedIssues.length) return;
    if (!assetManagerState.finished_at) {
      feedback.warning("Wait for the asset scan to finish before renaming files.");
      return;
    }
    feedback.clear();
    try {
      const { results } = await renameRequest.mutateAsync({
        body: {
          renames: assetRenameRequests(selectedIssues),
          snapshot_finished_at: assetManagerState.finished_at,
        },
      });
      assetManagerState.applyRenameResults(results);
    } catch (err) {
      feedback.error(errorMessage(err, "Rename failed"));
    }
  }
</script>

{#if !hasResults}
  <FolderScopeCard {scope} />
  <ArtTypeFiltersCard
    {artTypes}
    hasSelectedFolders={scope.hasSelection}
    hasShowFolders={scope.hasShows}
    themeChecked={artTypes.includes("theme")}
    ontoggletype={toggleArtType}
    ontoggletheme={() => toggleArtType("theme")}
  />
{:else}
  <AssetRenamerResultsPanel />
{/if}

{#snippet renamerFooter()}
  <JobFooter
    {hasResults}
    running={assetManagerState.running}
    blocked={libraryGate.itemsBlocked}
    {stopping}
    onstop={stopScan}
    clear={clearResults}
  >
    {#snippet start()}
      <PendingButton
        class="btn btn-primary"
        onclick={startScan}
        disabled={!canScan || !!libraryGate.itemsBlocked}
        pending={startScanRequest.isPending}
        pendingLabel="Starting..."
      >
        <FolderPen size={15} />
        Scan
      </PendingButton>
    {/snippet}
    {#snippet finished()}
      {#if assetManagerState.items.length > 0}
        <PendingButton
          class="btn btn-primary"
          onclick={renameSelected}
          disabled={selectedIssues.length === 0}
          pending={renameRequest.isPending}
        >
          {#if renameRequest.isPending}
            <LoaderCircle size={15} class="animate-spin" />
          {:else}
            <RefreshCw size={15} />
          {/if}
          Rename {selectedIssues.length} File{selectedIssues.length !== 1 ? "s" : ""}
        </PendingButton>
      {/if}
    {/snippet}
  </JobFooter>
{/snippet}
