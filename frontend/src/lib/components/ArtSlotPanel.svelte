<script lang="ts">
  import Check from "@lucide/svelte/icons/check";
  import CircleAlert from "@lucide/svelte/icons/circle-alert";
  import LoaderCircle from "@lucide/svelte/icons/loader-circle";
  import X from "@lucide/svelte/icons/x";
  import { createMutation, createQuery } from "@tanstack/svelte-query";
  import { onMount } from "svelte";
  import {
    getArtSourcesOptions,
    getTmdbArtSourcesOptions,
    matchArtMutation,
    saveArtMutation,
    saveTmdbArtMutation,
  } from "../../generated/rest/@tanstack/svelte-query.gen";
  import type { ArtCandidate, ArtType } from "../../generated/rest/types.gen";
  import { invalidateSeasons, refreshItem } from "../rest/cache";
  import { artPasteState, type ArtPasteTarget } from "../stores/artPasteState.svelte";
  import { artPreviewState } from "../stores/artPreviewState.svelte";
  import { downloadState } from "../stores/downloadState.svelte";
  import { createNotifier } from "../stores/notificationState.svelte";
  import { selectedState } from "../stores/selectedState.svelte";
  import { settingsState } from "../stores/settingsState.svelte";
  import { beginAutoAdvance, handleArtworkSelectionAdvance } from "../utils/autoAdvance";
  import { errorMessage } from "../utils/errors";
  import {
    DEFAULT_MATCH_THRESHOLD,
    MAX_MATCH_THRESHOLD,
    MIN_MATCH_THRESHOLD,
    clampMatchThreshold,
    matchStatusLine,
  } from "../utils/matchStatus";
  import { parseArtUrl } from "../utils/artUrls";
  import { readJson, writeJson } from "../utils/storage";
  import { openPersistedItem, type ArtSlotTarget } from "../utils/tmdbItems";
  import ArtSourceSection from "./ArtSourceSection.svelte";
  import DataStatus from "./DataStatus.svelte";

  let {
    slot,
    artType,
  }: {
    slot: ArtSlotTarget;
    artType: ArtType;
  } = $props();

  type ArtSelection = Pick<ArtCandidate, "url"> & Partial<Pick<ArtCandidate, "width" | "height">>;

  const thresholdId = $props.id();
  // A TMDB title has no files or server to match against; matching needs a stored item.
  let canMatch = $derived(slot.kind === "item");

  const itemSourcesQuery = createQuery(() => ({
    ...getArtSourcesOptions({
      path: { item_id: slot.kind === "item" ? slot.itemId : 0, art_type: artType },
      query: { season_id: slot.kind === "item" ? slot.seasonId : null },
    }),
    enabled: slot.kind === "item",
  }));
  const tmdbSourcesQuery = createQuery(() => ({
    ...getTmdbArtSourcesOptions({
      path: {
        media_type: slot.kind === "tmdb" ? slot.mediaType : "movie",
        tmdb_id: slot.kind === "tmdb" ? slot.tmdbId : 0,
        art_type: artType,
      },
      query: { season_num: slot.kind === "tmdb" ? slot.seasonNum : null },
    }),
    enabled: slot.kind === "tmdb",
  }));
  let sourcesQuery = $derived(slot.kind === "item" ? itemSourcesQuery : tmdbSourcesQuery);
  let sources = $derived(sourcesQuery.data?.sources ?? null);
  // Typed/pasted URL entry, shown when the clipboard cannot be read directly.
  let manualEntry = $state(false);
  let customUrl = $state("");

  let matchResults = $state<ArtCandidate[] | null>(null);
  let matchLoading = $state(false);
  let matchRan = $state(false);
  let threshold = $state(
    clampMatchThreshold(readJson("artPanel_threshold", DEFAULT_MATCH_THRESHOLD)),
  );
  let matchStatus = $state("");
  let matchSettled = $state(false);

  let saving = $state(false);
  const matchArtRequest = createMutation(() => matchArtMutation());
  const saveArtRequest = createMutation(() => saveArtMutation());
  const saveTmdbArtRequest = createMutation(() => saveTmdbArtMutation());

  let autoMatch = $derived(canMatch && settingsState.current.auto_match_art);
  // An automatic match shows as running from the start, rather than first
  // asking for a match it is about to run itself.
  let matchPending = $derived(matchLoading || (autoMatch && !matchRan && !sourcesQuery.isError));
  let autoMatched = false;
  $effect(() => {
    if (!autoMatch || !sourcesQuery.data || autoMatched) return;
    autoMatched = true;
    void runMatch();
  });

  async function runMatch() {
    if (matchLoading || slot.kind !== "item") return;
    const matchThreshold = clampMatchThreshold(threshold);
    threshold = matchThreshold;
    matchLoading = true;
    matchRan = true;
    matchResults = null;
    matchStatus = "";
    matchSettled = false;
    writeJson("artPanel_threshold", matchThreshold);

    try {
      const result = await matchArtRequest.mutateAsync({
        path: { item_id: slot.itemId, art_type: artType },
        query: { season_id: slot.seasonId, threshold: matchThreshold },
      });
      matchResults = result.matches || [];

      ({ text: matchStatus, settled: matchSettled } = matchStatusLine(result, matchThreshold));
    } catch (err) {
      matchStatus = `Error - ${errorMessage(err, "unknown error")}`;
    } finally {
      matchLoading = false;
    }
  }

  const feedback = createNotifier();

  /**
   * Save a choice. A candidate from the grid passes the image the grid shows,
   * which the detail page then shows until the server has fetched the file.
   */
  async function saveArt(art: ArtSelection, previewUrl: string | null = null) {
    if (saving) return false;
    if (!art.url) {
      feedback.warning("No art URL selected");
      return false;
    }
    const body = { height: art.height ?? null, url: art.url, width: art.width ?? null };
    saving = true;
    feedback.clear();
    if (slot.kind === "tmdb") {
      const advanceContext = beginAutoAdvance();
      // The first selection stores the title; the view then follows the item.
      try {
        const result = await saveTmdbArtRequest.mutateAsync({
          body,
          path: { media_type: slot.mediaType, tmdb_id: slot.tmdbId, art_type: artType },
          query: { season_num: slot.seasonNum },
        });
        await openPersistedItem(
          result.item,
          { artType, seasonNum: slot.seasonNum },
          advanceContext,
        );
        return true;
      } catch (err) {
        feedback.error(errorMessage(err, "Save failed"));
        return false;
      } finally {
        saving = false;
      }
    }
    const target = { mediaItemId: slot.itemId, artType, seasonId: slot.seasonId };
    const advanceContext = beginAutoAdvance();
    // The art the detail page shows now; a preview stands in for exactly that.
    const shownItem = selectedState.item;
    const detailArtType = artType === "poster" || artType === "background" ? artType : null;
    try {
      const result = await saveArtRequest.mutateAsync({
        body,
        path: { item_id: target.mediaItemId, art_type: artType },
        query: { season_id: target.seasonId },
      });
      // Only once the server has accepted the choice.
      if (previewUrl && detailArtType && shownItem?.id === target.mediaItemId) {
        artPreviewState.show(shownItem, detailArtType, previewUrl, result.job_id ?? null);
      }
      // An item without a local folder records the choice and downloads nothing.
      if (result.job_id) {
        downloadState.trackQueuedItemJob({ jobId: result.job_id, jobType: "art", ...target });
      }
      const updatedItem = await refreshItem(target.mediaItemId);
      // Nothing to download: the item already shows its choice.
      if (!result.job_id && detailArtType) {
        artPreviewState.clear(target.mediaItemId, detailArtType);
      }
      if (target.artType === "season_poster") await invalidateSeasons(target.mediaItemId);
      await handleArtworkSelectionAdvance({
        item: updatedItem,
        artType: target.artType,
        seasonId: target.seasonId,
        context: advanceContext,
      });
      return true;
    } catch (err) {
      feedback.error(errorMessage(err, "Save failed"));
      return false;
    } finally {
      saving = false;
    }
  }

  async function saveUrlText(text: string) {
    const url = parseArtUrl(text);
    if (!url) {
      feedback.warning("That is not an image URL");
      return false;
    }
    return saveArt({ url });
  }

  async function saveCustomUrl() {
    if (await saveUrlText(customUrl)) {
      customUrl = "";
      manualEntry = false;
    }
  }

  // navigator.clipboard only exists in secure contexts (HTTPS or localhost),
  // and reading can be refused; both fall back to a paste-able input.
  async function pasteFromClipboard() {
    let text: string;
    try {
      text = await navigator.clipboard.readText();
    } catch {
      manualEntry = true;
      return;
    }
    await saveUrlText(text);
  }

  // The header's "Paste URL & save as ..." button saves into whichever slot is shown.
  const pasteTarget: ArtPasteTarget = {
    get label() {
      return artType.replace("_", " ");
    },
    get busy() {
      return saving;
    },
    paste: pasteFromClipboard,
  };
  onMount(() => {
    artPasteState.target = pasteTarget;
    return () => {
      if (artPasteState.target === pasteTarget) artPasteState.target = null;
    };
  });

  // Ctrl/Cmd+V anywhere on the art tab saves a pasted URL, which also works
  // over plain HTTP where the clipboard API is unavailable.
  function handleDocumentPaste(event: ClipboardEvent) {
    if (saving || manualEntry) return;
    const target = event.target;
    if (target instanceof Element && target.closest("input, textarea, [contenteditable], dialog")) {
      return;
    }
    const url = parseArtUrl(event.clipboardData?.getData("text") ?? "");
    if (!url) return;
    event.preventDefault();
    void saveArt({ url });
  }
</script>

<svelte:document onpaste={handleDocumentPaste} />

<div class="art-slot">
  <div class="match-bar">
    <div class="match-status">
      {#if !canMatch && !saving}
        <span class="text-muted">Choose artwork to add this title</span>
      {:else if saving}
        <LoaderCircle size={14} class="animate-spin" />
        <span class="text-muted">Saving selected art...</span>
      {:else if matchPending}
        <LoaderCircle size={14} class="animate-spin" />
        <span class="text-muted">Matching...</span>
      {:else if matchRan && matchStatus}
        {#if matchSettled}
          <Check size={14} class="text-success" />
        {:else if matchResults !== null}
          <CircleAlert size={14} class="text-warning" />
        {/if}
        <span>{matchStatus}</span>
      {:else}
        <span class="text-muted">Run match to find candidates</span>
      {/if}
    </div>

    {#if manualEntry}
      <form
        class="url-entry"
        onsubmit={(event) => {
          event.preventDefault();
          void saveCustomUrl();
        }}
      >
        <input
          type="url"
          class="url-entry-input"
          placeholder="Paste image URL..."
          aria-label="Image URL"
          bind:value={customUrl}
          onkeydown={(event) => {
            if (event.key === "Escape") manualEntry = false;
          }}
          {@attach (node) => node.focus()}
        />
        <button
          type="submit"
          class="btn btn-secondary btn-sm"
          disabled={saving || !customUrl.trim()}
        >
          Save
        </button>
        <button
          type="button"
          class="btn btn-ghost btn-icon btn-sm"
          aria-label="Cancel URL entry"
          title="Cancel"
          onclick={() => {
            manualEntry = false;
          }}
        >
          <X size={14} />
        </button>
      </form>
    {/if}

    {#if canMatch}
      <div class="match-controls">
        <div
          class="match-threshold"
          title={`Maximum perceptual hash distance (${MIN_MATCH_THRESHOLD}-${MAX_MATCH_THRESHOLD}). Lower is stricter.`}
        >
          <label for="{thresholdId}-threshold" class="threshold-label">Distance &le;</label>
          <input
            id="{thresholdId}-threshold"
            type="number"
            class="threshold-input"
            min={MIN_MATCH_THRESHOLD}
            max={MAX_MATCH_THRESHOLD}
            step="1"
            bind:value={threshold}
            onchange={() => {
              threshold = clampMatchThreshold(threshold);
              writeJson("artPanel_threshold", threshold);
            }}
          />
        </div>
        <button
          class="btn btn-primary btn-sm"
          onclick={() => runMatch()}
          disabled={saving || matchPending}
        >
          Match {artType.replace("_", " ")}
        </button>
      </div>
    {/if}
  </div>

  {#if matchResults && matchResults.length > 0}
    <ArtSourceSection
      title="MATCHED"
      arts={matchResults}
      {artType}
      disabled={saving}
      onselect={saveArt}
      paged={false}
      matched
    />
  {/if}

  <DataStatus
    label="art sources"
    error={sourcesQuery.error}
    loading={sourcesQuery.isFetching}
    hasData={sourcesQuery.data !== undefined}
    onretry={() => sourcesQuery.refetch()}
  />
  {#if sources}
    {#if sourcesQuery.isSuccess && Object.values(sources).every((arts) => arts.length === 0)}
      <p class="text-muted">No art sources found.</p>
    {/if}
    {#each Object.entries(sources) as [sourceKey, arts] (sourceKey)}
      {#if arts.length > 0}
        <ArtSourceSection
          title={sourceKey.toUpperCase()}
          {arts}
          {artType}
          disabled={saving}
          onselect={saveArt}
          showSource={sourceKey !== "tmdb"}
        />
      {/if}
    {/each}
  {/if}
</div>

<style>
  .art-slot {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
  }

  .match-bar {
    display: flex;
    align-items: center;
    gap: var(--space-2) var(--space-3);
    flex-wrap: wrap;
    padding: var(--space-2) var(--space-2) var(--space-2) var(--space-3);
    background: var(--bg-secondary);
    border: var(--border-subtle);
    border-radius: var(--radius-md);
  }

  .url-entry {
    display: flex;
    align-items: center;
    gap: var(--space-1);
    flex: 1 1 260px;
    min-width: 0;
  }

  .url-entry-input {
    flex: 1;
    min-width: 0;
    padding: var(--space-1) var(--space-2);
    font-size: var(--text-sm);
  }

  .match-status {
    flex: 1 1 auto;
    min-width: 0;
    display: flex;
    align-items: center;
    gap: var(--space-2);
    font-size: var(--text-sm);
    color: var(--text-secondary);
  }

  .match-status :global(.animate-spin) {
    animation: spin 1s linear infinite;
  }

  .match-controls {
    display: flex;
    align-items: center;
    gap: var(--space-3);
  }

  .match-threshold {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    font-size: var(--text-sm);
    color: var(--text-secondary);
  }

  .threshold-label {
    font-size: var(--text-sm);
    font-weight: 500;
    color: var(--text-secondary);
    user-select: none;
    cursor: pointer;
    white-space: nowrap;
  }

  .threshold-input {
    width: 38px;
    padding: var(--space-1) var(--space-1);
    text-align: center;
    font-family: var(--font-mono);
    font-size: var(--text-sm);
    font-weight: 500;
    color: var(--text-primary);
    background: var(--bg-tertiary);
    border: var(--border-subtle);
    border-radius: var(--radius-sm);
    outline: none;
    -moz-appearance: textfield;
    appearance: textfield;
  }

  .threshold-input::-webkit-inner-spin-button,
  .threshold-input::-webkit-outer-spin-button {
    -webkit-appearance: none;
    margin: 0;
  }

  .threshold-input:hover {
    border-color: var(--border-hover);
  }

  .threshold-input:focus {
    border-color: var(--accent);
    box-shadow: 0 0 0 2px var(--accent-muted);
  }
</style>
