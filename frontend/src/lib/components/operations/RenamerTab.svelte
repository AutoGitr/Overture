<script lang="ts">
  import { countOf } from "../../utils/plural";
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
  import CardColumn from "../CardColumn.svelte";
  import FolderScopeCard from "../FolderScopeCard.svelte";
  import PendingButton from "../PendingButton.svelte";
  import JobFooter from "./JobFooter.svelte";
  import { assetManagerState } from "../../stores/assetManagerState.svelte";
  import { assetRenameRequests } from "../../utils/assetRenamerPopup";
  import { assetsInScope } from "../../utils/artTypes";
  import { errorMessage } from "../../utils/errors";
  import { createFolderScope } from "../../utils/folderScope.svelte";
  import { OperationRun } from "../../utils/operationRun.svelte";
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
  const run = new OperationRun("renamer", {
    blocker: () =>
      !scope.ready
        ? "Loading the folders..."
        : !scope.hasSelection
          ? "Choose a folder or the sidebar's titles"
          : !artTypes.length
            ? "Choose an asset type"
            : null,
    results: () => ["asset_scan"],
    stopping: () => assetManagerState.stopping,
  });
  const { feedback } = run;
  const startScanRequest = createMutation(() => startScanMutation());
  const stopScanRequest = createMutation(() => stopScanMutation());
  const renameRequest = createMutation(() => renameAssetsMutation());
  let selectedIssues = $derived(assetManagerState.running ? [] : assetManagerState.selectedItems);

  onMount(() => {
    onfooterchange?.(renamerFooter);
  });

  function toggleArtType(type: ServerAsset) {
    config.artTypes = toggleSelectedValue(config.artTypes, type);
  }

  function startScan() {
    return run.start(async () => {
      config.save();
      await startScanRequest.mutateAsync({ body: { art_types: artTypes, ...scope.request() } });
      assetManagerState.markStartAccepted();
    }, "Asset scan failed");
  }

  function stopScan() {
    return run.stop(async () => {
      await stopScanRequest.mutateAsync({});
      assetManagerState.markStopRequested();
    }, "Could not stop the scan. Please retry.");
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

{#if !run.hasResults}
  <CardColumn>
    <FolderScopeCard {scope} />
    <ArtTypeFiltersCard
      {artTypes}
      hasSelectedFolders={scope.hasSelection}
      hasShowFolders={scope.hasShows}
      themeChecked={artTypes.includes("theme")}
      ontoggletype={toggleArtType}
      ontoggletheme={() => toggleArtType("theme")}
    />
  </CardColumn>
{:else}
  <AssetRenamerResultsPanel />
{/if}

{#snippet renamerFooter()}
  <JobFooter {run} onstop={stopScan}>
    {#snippet start()}
      <PendingButton
        class="btn btn-primary"
        onclick={startScan}
        title={run.blocked ?? undefined}
        disabled={!!run.blocked}
        pending={run.starting}
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
          title={selectedIssues.length ? undefined : "Select the files to rename"}
          disabled={selectedIssues.length === 0}
          pending={renameRequest.isPending}
        >
          {#if renameRequest.isPending}
            <LoaderCircle size={15} class="animate-spin" />
          {:else}
            <RefreshCw size={15} />
          {/if}
          Rename {countOf(selectedIssues.length, "File")}
        </PendingButton>
      {/if}
    {/snippet}
  </JobFooter>
{/snippet}
