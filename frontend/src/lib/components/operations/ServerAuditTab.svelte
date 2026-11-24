<script lang="ts">
  import { countOf } from "../../utils/plural";
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
  import Checklist from "../Checklist.svelte";
  import FolderScopeCard from "../FolderScopeCard.svelte";
  import PendingButton from "../PendingButton.svelte";
  import JobFooter from "./JobFooter.svelte";
  import ServerAuditResultsPanel from "../ServerAuditResultsPanel.svelte";
  import { confirmAction } from "../../stores/notificationState.svelte";
  import { serverAuditFixState } from "../../stores/serverAuditFixState.svelte";
  import { serverAuditState } from "../../stores/serverAuditState.svelte";
  import { settingsState } from "../../stores/settingsState.svelte";
  import { assetsInScope } from "../../utils/artTypes";
  import { errorMessage } from "../../utils/errors";
  import { createFolderScope } from "../../utils/folderScope.svelte";
  import { OperationRun } from "../../utils/operationRun.svelte";
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
    checkCollections: false,
  });
  let checkCollections = $derived(
    settingsState.current.collections_supported && config.checkCollections,
  );
  let collectionArtTypes = $derived(
    config.artTypes.filter((type) => (ITEM_ART_TYPES as readonly string[]).includes(type)),
  );
  /** The chosen art types the scope has files for. */
  let artTypes = $derived(
    assetsInScope(config.artTypes, { hasSelection: scope.hasSelection, hasShows: scope.hasShows }),
  );
  let checkThemes = $derived((scope.hasSelection || checkCollections) && config.checkThemes);
  let fixing = $derived(serverAuditFixState.running);
  const run = new OperationRun("audit", {
    blocker: () => {
      if (!scope.ready) return "Loading the folders...";
      if (!scope.hasSelection && !checkCollections)
        return "Choose a folder, the sidebar's titles or collections";
      const checks =
        (scope.hasSelection && (artTypes.length > 0 || checkThemes)) ||
        (checkCollections && (collectionArtTypes.length > 0 || checkThemes));
      return checks ? null : "Choose an art type or themes";
    },
    results: () => ["server_audit"],
    stopping: () => (fixing ? serverAuditFixState.stopping : serverAuditState.stopping),
  });
  const { feedback } = run;
  const startAuditRequest = createMutation(() => startServerAuditMutation());
  const stopAuditRequest = createMutation(() => stopServerAuditMutation());
  const fixRequest = createMutation(() => fixAuditFindingsMutation());
  const stopFixRequest = createMutation(() => stopAuditFixMutation());

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

  function startAudit() {
    return run.start(async () => {
      config.save();
      await startAuditRequest.mutateAsync({
        body: {
          art_types: [...new Set([...artTypes, ...(checkCollections ? collectionArtTypes : [])])],
          check_themes: checkThemes,
          check_collections: checkCollections,
          ...scope.request(),
        },
      });
      serverAuditState.markStartAccepted();
    }, "Server audit failed");
  }

  /** Stop the fix while one runs, else the audit. */
  function stop() {
    return fixing
      ? run.stop(async () => {
          await stopFixRequest.mutateAsync({});
          serverAuditFixState.markStopRequested();
        }, "Could not stop the fix. Please retry.")
      : run.stop(async () => {
          await stopAuditRequest.mutateAsync({});
          serverAuditState.markStopRequested();
        }, "Could not stop the audit. Please retry.");
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
    const itemThemes = themes.filter((result) => result.item_id != null);
    if (itemThemes.length) {
      const confirmed = await confirmAction({
        title: `Delete ${countOf(itemThemes.length, "server theme")}?`,
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
          // A row naming no server, such as a missing local file, has nothing there to fix.
          targets: art.flatMap((result) =>
            result.art_type === "theme" || result.server_id == null
              ? []
              : [
                  {
                    art_type: result.art_type,
                    item_id: result.item_id,
                    collection_id: result.collection_id,
                    season_id: result.season_id,
                    server_id: result.server_id,
                  },
                ],
          ),
          themes: themes.flatMap((result) =>
            (result.item_id != null || result.collection_id != null) && result.server_id != null
              ? [
                  {
                    item_id: result.item_id,
                    collection_id: result.collection_id,
                    server_id: result.server_id,
                    server_item_id: result.server_item_id || "",
                    theme_id: result.theme_id,
                  },
                ]
              : [],
          ),
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
</script>

{#if !run.hasResults}
  <CardColumn>
    <FolderScopeCard {scope} collections={settingsState.current.collections_supported ? collectionScope : undefined} />
    <ArtTypeFiltersCard
      artTypes={scope.hasSelection ? artTypes : collectionArtTypes}
      hasSelectedFolders={scope.hasSelection || checkCollections}
      hasShowFolders={scope.hasSelection && scope.hasShows}
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

{#snippet collectionScope()}
  <Checklist
    label="Collections"
    groups={[]}
    allSelected={config.checkCollections}
    ontoggle={() => {}}
    ontoggleall={(checked) => (config.checkCollections = checked)}
    notice={collectionHint}
  />
{/snippet}

{#snippet collectionHint()}
  <span class="hint"
    >Compares the posters, backgrounds and themes Overture holds for collections with what the
    server shows and plays.</span
  >
{/snippet}

{#snippet auditFooter()}
  <JobFooter {run} onstop={stop}>
    {#snippet start()}
      <PendingButton
        class="btn btn-primary"
        onclick={startAudit}
        title={run.blocked ?? undefined}
        disabled={!!run.blocked}
        pending={run.starting}
        pendingLabel="Starting..."
      >
        <ShieldCheck size={15} />
        Audit server
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
          title={selectedCount ? undefined : "Select the items to refresh"}
          disabled={selectedCount === 0}
          pending={fixRequest.isPending}
        >
          {#if fixRequest.isPending}
            <LoaderCircle size={15} class="animate-spin" />
          {:else}
            <RefreshCw size={15} />
          {/if}
          Refresh {countOf(selectedCount, "Item")}
        </PendingButton>
      {/if}
    {/snippet}
  </JobFooter>
{/snippet}
