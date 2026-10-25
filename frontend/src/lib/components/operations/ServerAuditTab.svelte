<script lang="ts">
  import LoaderCircle from "@lucide/svelte/icons/loader-circle";
  import RefreshCw from "@lucide/svelte/icons/refresh-cw";
  import ShieldCheck from "@lucide/svelte/icons/shield-check";
  import { createMutation } from "@tanstack/svelte-query";
  import { onMount, type Snippet } from "svelte";
  import type { ArtType } from "../../../generated/rest/types.gen";
  import { ITEM_ART_TYPES, SEASON_ART_TYPES } from "../../../generated/settings";
  import {
    fixAuditFindingsMutation,
    startServerAuditMutation,
    stopAuditFixMutation,
    stopServerAuditMutation,
  } from "../../../generated/rest/@tanstack/svelte-query.gen";
  import ArtTypeFiltersCard from "../ArtTypeFiltersCard.svelte";
  import CardColumn from "../CardColumn.svelte";
  import FolderScopeCard from "../FolderScopeCard.svelte";
  import PendingButton from "../PendingButton.svelte";
  import EmptyCollectionsCard from "./EmptyCollectionsCard.svelte";
  import JobFooter from "./JobFooter.svelte";
  import ServerAuditResultsPanel from "../ServerAuditResultsPanel.svelte";
  import { libraryGate } from "../../stores/libraryGate.svelte";
  import { confirmAction, createNotifier } from "../../stores/notificationState.svelte";
  import { serverAuditFixState } from "../../stores/serverAuditFixState.svelte";
  import { serverAuditState } from "../../stores/serverAuditState.svelte";
  import { assetsInScope } from "../../utils/artTypes";
  import { errorMessage } from "../../utils/errors";
  import { createFolderScope } from "../../utils/folderScope.svelte";
  import { createClearResults } from "../../utils/jobSnapshots";
  import { persistedState } from "../../utils/persistedState.svelte";
  import { toggleSelectedValue } from "../../utils/popupSelection";
  import {
    auditRowKey,
    selectedArtAuditResults,
    selectedThemeAuditResults,
  } from "../../utils/serverAuditPopup";

  let {
    isActive = false,
    onfooterchange,
  }: {
    isActive?: boolean;
    onfooterchange?: (footer: Snippet) => void;
  } = $props();

  const scope = createFolderScope("serverAudit", () => isActive);
  const config = persistedState("serverAudit", {
    artTypes: [...ITEM_ART_TYPES, ...SEASON_ART_TYPES],
    checkThemes: true,
  });
  /** The chosen art types the scope has files for. */
  let artTypes = $derived(
    assetsInScope(config.artTypes, { hasSelection: scope.hasSelection, hasShows: scope.hasShows }),
  );
  let checkThemes = $derived(scope.hasSelection && config.checkThemes);
  let canAudit = $derived(
    (artTypes.length > 0 || checkThemes) && scope.hasSelection && scope.ready,
  );

  const feedback = createNotifier();
  const startAuditRequest = createMutation(() => startServerAuditMutation());
  const stopAuditRequest = createMutation(() => stopServerAuditMutation());
  const fixRequest = createMutation(() => fixAuditFindingsMutation());
  const stopFixRequest = createMutation(() => stopAuditFixMutation());
  const clearResults = createClearResults(() => ["server_audit"], feedback);
  /** Results show exactly while a run exists, never ahead of the server's answer. */
  let hasResults = $derived(serverAuditState.hasRun);
  let stopping = $derived(stopAuditRequest.isPending || serverAuditState.stopping);
  let fixing = $derived(serverAuditFixState.running);
  let stoppingFix = $derived(stopFixRequest.isPending || serverAuditFixState.stopping);

  let actionsLocked = $derived(serverAuditState.running || fixing);
  let selectedArtResults = $derived(
    actionsLocked ? [] : selectedArtAuditResults(serverAuditState.selectedItems),
  );
  let selectedThemeResults = $derived(
    actionsLocked ? [] : selectedThemeAuditResults(serverAuditState.selectedItems),
  );
  let selectedCount = $derived(selectedArtResults.length + selectedThemeResults.length);

  onMount(() => {
    onfooterchange?.(auditFooter);
  });

  function toggleArtType(type: ArtType) {
    config.artTypes = toggleSelectedValue(config.artTypes, type);
  }

  async function startAudit() {
    if (!canAudit || libraryGate.blocked("audit")) return;
    config.save();
    feedback.clear();
    try {
      await startAuditRequest.mutateAsync({
        body: { art_types: artTypes, check_themes: checkThemes, ...scope.request() },
      });
      serverAuditState.markStartAccepted();
    } catch (err) {
      feedback.error(errorMessage(err, "Server audit failed"));
    }
  }

  async function stopAudit() {
    feedback.clear();
    try {
      await stopAuditRequest.mutateAsync({});
      serverAuditState.markStopRequested();
    } catch (error) {
      feedback.error(errorMessage(error, "Could not stop the audit. Please retry."));
    }
  }

  /**
   * Fix the selected rows in one background run: images are refreshed, and
   * themes have their server theme deleted first. Their earlier outcome is
   * cleared and they wait on the server until the job marks each verified or
   * failed.
   */
  async function fixSelected() {
    if (!selectedCount) return;
    const snapshot = serverAuditState.finished_at;
    if (!snapshot) {
      feedback.warning("Wait for the audit to finish before refreshing items.");
      return;
    }
    const art = selectedArtResults;
    const themes = selectedThemeResults;
    if (themes.length) {
      const confirmed = await confirmAction({
        title: `Delete ${themes.length} server theme${themes.length === 1 ? "" : "s"}?`,
        message:
          "The server then reloads each theme from your local file. Jellyfin and Emby may also delete the file behind the server's theme.",
        confirmLabel: "Delete",
        destructive: true,
      });
      if (!confirmed) return;
    }
    const keys = new Set([...art, ...themes].map(auditRowKey));
    serverAuditFixState.markSubmitted([...keys]);
    serverAuditState.clearRefreshErrors(keys);
    feedback.clear();
    try {
      const { status } = await fixRequest.mutateAsync({
        body: {
          snapshot_finished_at: snapshot,
          targets: art.flatMap((result) =>
            result.art_type === "theme"
              ? []
              : [
                  {
                    art_type: result.art_type,
                    item_id: result.item_id,
                    season_id: result.season_id,
                  },
                ],
          ),
          themes: themes.map((result) => ({
            item_id: result.item_id,
            server_item_id: result.server_item_id || "",
            theme_id: result.theme_id,
          })),
        },
      });
      if (status === "already_running") {
        serverAuditFixState.markSubmitted([]);
        feedback.warning("Wait for the current fix to finish.");
      } else {
        serverAuditFixState.markStartAccepted();
      }
    } catch (err) {
      serverAuditFixState.markSubmitted([]);
      feedback.error(errorMessage(err, "Refresh failed"));
    }
  }

  async function stopFix() {
    feedback.clear();
    try {
      await stopFixRequest.mutateAsync({});
      serverAuditFixState.markStopRequested();
    } catch (error) {
      feedback.error(errorMessage(error, "Could not stop the fix. Please retry."));
    }
  }
</script>

{#if !hasResults}
  <CardColumn>
    <EmptyCollectionsCard {isActive} />
    <FolderScopeCard {scope} />
    <ArtTypeFiltersCard
      {artTypes}
      hasSelectedFolders={scope.hasSelection}
      hasShowFolders={scope.hasShows}
      themeChecked={checkThemes}
      ontoggletype={toggleArtType}
      ontoggletheme={(value) => (config.checkThemes = value)}
    />
  </CardColumn>
{:else}
  <ServerAuditResultsPanel
    selectedArtCount={selectedArtResults.length}
    selectedThemeCount={selectedThemeResults.length}
  />
{/if}

{#snippet auditFooter()}
  <JobFooter
    {hasResults}
    running={serverAuditState.running || fixing}
    blocked={libraryGate.blocked("audit")}
    stopping={fixing ? stoppingFix : stopping}
    onstop={fixing ? stopFix : stopAudit}
    clear={clearResults}
  >
    {#snippet start()}
      <PendingButton
        class="btn btn-primary"
        onclick={startAudit}
        disabled={!canAudit || !!libraryGate.blocked("audit")}
        pending={startAuditRequest.isPending}
        pendingLabel="Starting..."
      >
        <ShieldCheck size={15} />
        Audit Server
      </PendingButton>
    {/snippet}
    {#snippet runningNote()}
      {#if fixing}
        <span class="popup-footer-note" role="status">
          {serverAuditFixState.planning
            ? "Fixing on the server..."
            : `Checking the server: ${serverAuditFixState.done}/${serverAuditFixState.total} settled`}
        </span>
      {/if}
    {/snippet}
    {#snippet finished()}
      {#if serverAuditState.items.length > 0}
        <PendingButton
          class="btn btn-primary"
          onclick={fixSelected}
          disabled={selectedCount === 0}
          pending={fixRequest.isPending}
        >
          {#if fixRequest.isPending}
            <LoaderCircle size={15} class="animate-spin" />
          {:else}
            <RefreshCw size={15} />
          {/if}
          Refresh {selectedCount}
          {selectedCount === 1 ? "Item" : "Items"}
        </PendingButton>
      {/if}
    {/snippet}
  </JobFooter>
{/snippet}
