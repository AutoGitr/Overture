<script lang="ts">
  import { createMutation, createQuery } from "@tanstack/svelte-query";
  import { onMount } from "svelte";
  import {
    getArtSourcesOptions,
    getCollectionArtSourcesOptions,
    saveCollectionArtMutation,
    matchCollectionArtMutation,
    getTmdbArtSourcesOptions,
    matchArtMutation,
    saveArtMutation,
    saveTmdbArtMutation,
    uploadArtMutation,
  } from "../../generated/rest/@tanstack/svelte-query.gen";
  import type {
    ArtCandidate,
    ArtType,
    MediaItemRead,
    SaveArtRequest,
  } from "../../generated/rest/types.gen";
  import { invalidateSeasons, upsertLibraryItem } from "../rest/cache";
  import { artPasteState, type ArtPasteTarget } from "../stores/artPasteState.svelte";
  import { artPreviewState } from "../stores/artPreviewState.svelte";
  import { downloadState } from "../stores/downloadState.svelte";
  import { createNotifier } from "../stores/notificationState.svelte";
  import { settingsState } from "../stores/settingsState.svelte";
  import { ArtMatch } from "../utils/artMatch.svelte";
  import { parseArtUrl } from "../utils/artUrls";
  import { beginAutoAdvance, handleArtworkSelectionAdvance } from "../utils/autoAdvance";
  import {
    beginRecordAdvance,
    catalogKey,
    catalogPageRecord,
    collectionKey,
    handleRecordSelectionAdvance,
    type RecordSlot,
  } from "../utils/recordAdvance";
  import { errorMessage } from "../utils/errors";
  import {
    openPersistedItem,
    type ArtSlotTarget,
    type CollectionArtTarget,
  } from "../utils/tmdbItems";
  import ArtMatchBar from "./ArtMatchBar.svelte";
  import ArtCard from "./ArtCard.svelte";
  import ImageGrid from "./ImageGrid.svelte";
  import { candidateImageUrl } from "../utils/artDisplay";
  import ArtUrlEntry from "./ArtUrlEntry.svelte";
  import DataStatus from "./DataStatus.svelte";

  let {
    slot,
    artType,
    item,
  }: {
    slot: ArtSlotTarget | CollectionArtTarget;
    artType: ArtType;
    /** The stored item the detail view shows. */
    item: MediaItemRead | null;
  } = $props();

  // A TMDB title has no files or server to match against; matching needs a stored item.
  let canMatch = $derived(
    slot.kind === "item" || (slot.kind === "collection" && slot.tmdbId !== null),
  );
  let tmdbTarget = $derived(
    slot.kind === "catalog"
      ? slot.catalog.entry
      : slot.kind === "tmdb"
        ? { media_type: slot.mediaType, tmdb_id: slot.tmdbId }
        : null,
  );

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
        media_type: tmdbTarget?.media_type ?? "movie",
        tmdb_id: tmdbTarget?.tmdb_id ?? 0,
        art_type: artType,
      },
      query: {
        season_num: slot.kind === "tmdb" || slot.kind === "catalog" ? slot.seasonNum : null,
      },
    }),
    enabled:
      slot.kind === "tmdb" ||
      (slot.kind === "catalog" && !!tmdbTarget?.tmdb_id && settingsState.current.tmdb_configured),
  }));
  const collectionSourcesQuery = createQuery(() => ({
    ...getCollectionArtSourcesOptions({
      path: {
        collection_id: slot.kind === "collection" ? slot.collectionId : 0,
        art_type: artType,
      },
    }),
    enabled: slot.kind === "collection" && slot.tmdbId !== null,
  }));
  let sourcesQuery = $derived(
    slot.kind === "collection"
      ? collectionSourcesQuery
      : slot.kind === "item"
        ? itemSourcesQuery
        : tmdbSourcesQuery,
  );
  let sources = $derived.by(() => {
    const available = sourcesQuery.data?.sources;
    if (slot.kind !== "catalog") return available ?? null;
    const entry = slot.catalog.detail.entry;
    const url =
      artType === "season_poster"
        ? entry?.seasons?.find((season) => season.season_num === slot.seasonNum)?.poster_url
        : artType === "background"
          ? entry?.background_url
          : entry?.poster_url;
    const original: ArtCandidate[] =
      url && slot.catalog.detail.draft
        ? [
            {
              url,
              art_type: artType,
              source: "overturedb",
              width: null,
              height: null,
              hamming: null,
              iso_639_1: null,
              perfect_match: null,
              preview_url: null,
              title: null,
            },
          ]
        : [];
    return { tmdb: available?.tmdb ?? [], overturedb: original };
  });
  // Typed/pasted URL entry, shown when the clipboard cannot be read directly.
  let manualEntry = $state(false);

  let saving = $state(false);
  const uploadRequest = createMutation(() => uploadArtMutation());
  const matchArtRequest = createMutation(() => matchArtMutation());
  const saveArtRequest = createMutation(() => saveArtMutation());
  const saveTmdbArtRequest = createMutation(() => saveTmdbArtMutation());
  const saveCollectionRequest = createMutation(() => saveCollectionArtMutation());
  const matchCollectionRequest = createMutation(() => matchCollectionArtMutation());
  const match = new ArtMatch((args) =>
    slot.kind === "collection"
      ? matchCollectionRequest.mutateAsync({
          path: { collection_id: slot.collectionId, art_type: artType },
          query: { threshold: args.query.threshold },
        })
      : matchArtRequest.mutateAsync(args),
  );

  function runMatch() {
    if (slot.kind === "item") void match.run(slot.itemId, artType, slot.seasonId);
    else if (slot.kind === "collection") void match.run(slot.collectionId, artType, null);
  }

  let autoMatch = $derived(canMatch && settingsState.current.auto_match_art);
  // An automatic match shows as running from the start, rather than first
  // asking for a match it is about to run itself.
  let matchPending = $derived(match.loading || (autoMatch && !match.ran && !sourcesQuery.isError));
  // The slot's sources arrive from outside the component; matching starts once they have.
  let autoMatched = false;
  $effect(() => {
    if (!autoMatch || !sourcesQuery.data || autoMatched) return;
    autoMatched = true;
    runMatch();
  });

  const feedback = createNotifier();

  /**
   * Save a choice. A candidate from the grid passes the image the grid shows,
   * which the detail page then shows until the server has fetched the file.
   */
  async function saveArt(body: SaveArtRequest, previewUrl: string | null = null) {
    if (saving || (slot.kind === "catalog" && slot.catalog.draft.busy)) return false;
    saving = true;
    feedback.clear();
    if (slot.kind === "collection") {
      const advanceContext = beginRecordAdvance();
      try {
        await saveCollectionRequest.mutateAsync({
          body,
          path: { collection_id: slot.collectionId, art_type: artType },
        });
        if (artType === "poster" || artType === "background")
          handleRecordSelectionAdvance(collectionKey(slot.collectionId), artType, advanceContext);
        return true;
      } catch (error) {
        feedback.error(errorMessage(error, "Artwork upload failed"));
        return false;
      } finally {
        saving = false;
      }
    }
    if (slot.kind === "catalog") {
      const catalog = slot.catalog;
      // OvertureDB stores public links only, so it offers no upload.
      const url = body.url;
      if (!url) return false;
      const advanceContext = beginRecordAdvance();
      try {
        let saved: boolean;
        let current: RecordSlot;
        if (artType === "season_poster") {
          const entry = catalog.entry;
          if (slot.seasonNum === null) return false;
          const seasonNum = slot.seasonNum;
          const seasons = [
            ...(entry.seasons ?? []).filter((season) => season.season_num !== seasonNum),
            { season_num: seasonNum, poster_url: url },
          ].sort((a, b) => a.season_num - b.season_num);
          saved = await catalog.draft.save({ seasons });
          current = `season:${seasonNum}`;
        } else {
          saved = await catalog.draft.save(
            artType === "background" ? { background_url: url } : { poster_url: url },
          );
          current = artType === "background" ? "background" : "poster";
        }
        if (saved)
          handleRecordSelectionAdvance(
            catalogKey(catalog.target),
            current,
            advanceContext,
            catalogPageRecord(catalog),
          );
        return saved;
      } finally {
        saving = false;
      }
    }
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
    const shownItem = item;
    const detailArtType = artType === "poster" || artType === "background" ? artType : null;
    try {
      const result = await saveArtRequest.mutateAsync({
        body,
        path: { item_id: target.mediaItemId, art_type: artType },
        query: { season_id: target.seasonId },
      });
      // Only once the server has accepted the choice.
      if (previewUrl && detailArtType && shownItem?.id === target.mediaItemId) {
        artPreviewState.show(shownItem, detailArtType, previewUrl, result.selection.job_id ?? null);
      }
      // An item without a local folder records the choice and downloads nothing.
      if (result.selection.job_id) {
        downloadState.trackQueuedItemJob({
          jobId: result.selection.job_id,
          jobType: "art",
          ...target,
        });
      }
      upsertLibraryItem(result.item);
      // Nothing to download: the item already shows its choice.
      if (!result.selection.job_id && detailArtType) {
        artPreviewState.clear(target.mediaItemId, detailArtType);
      }
      if (target.artType === "season_poster") await invalidateSeasons(target.mediaItemId);
      await handleArtworkSelectionAdvance({
        item: result.item,
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

  async function uploadFile(file: File) {
    if (saving) return;
    saving = true;
    feedback.clear();
    let uploaded;
    try {
      uploaded = await uploadRequest.mutateAsync({ body: file });
    } catch (err) {
      feedback.error(errorMessage(err, "Upload failed"));
      return;
    } finally {
      saving = false;
    }
    await saveArt(uploaded);
  }

  async function saveCustomUrl(text: string) {
    if (await saveUrlText(text)) manualEntry = false;
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
    get upload() {
      return slot.kind === "catalog" ? null : uploadFile;
    },
  };
  onMount(() => {
    artPasteState.target = pasteTarget;
    return () => {
      if (artPasteState.target === pasteTarget) artPasteState.target = null;
    };
  });

  // Ctrl/Cmd+V anywhere on the art tab saves a pasted image or URL, which also
  // works over plain HTTP where the clipboard API is unavailable.
  function handleDocumentPaste(event: ClipboardEvent) {
    if (saving || manualEntry) return;
    const target = event.target;
    if (target instanceof Element && target.closest("input, textarea, [contenteditable], dialog")) {
      return;
    }
    const image = [...(event.clipboardData?.files ?? [])].find((file) =>
      ["image/jpeg", "image/png"].includes(file.type),
    );
    if (image && pasteTarget.upload) {
      event.preventDefault();
      void pasteTarget.upload(image);
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
  <ArtMatchBar {match} {artType} {canMatch} {saving} pending={matchPending} onmatch={runMatch}>
    {#snippet entry()}
      {#if manualEntry}
        <ArtUrlEntry
          {saving}
          onsave={(text) => void saveCustomUrl(text)}
          oncancel={() => (manualEntry = false)}
        />
      {/if}
    {/snippet}
  </ArtMatchBar>

  {#if match.results && match.results.length > 0}
    {@render source("MATCHED", match.results, true)}
  {/if}

  <DataStatus
    label="art sources"
    error={sourcesQuery.error}
    loading={sourcesQuery.isFetching}
    hasData={sourcesQuery.data !== undefined}
    onretry={() => sourcesQuery.refetch()}
  />
  {#if slot.kind === "collection" && slot.tmdbId === null}
    <p class="text-muted">
      Set a TMDB collection ID to browse artwork candidates, or paste custom artwork.
    </p>
  {/if}
  {#if sources}
    {#if sourcesQuery.isSuccess && Object.values(sources).every((arts) => arts.length === 0)}
      <p class="text-muted">No art sources found.</p>
    {/if}
    {#each Object.entries(sources) as [sourceKey, arts] (sourceKey)}
      {#if arts.length > 0}
        {@render source(sourceKey.toUpperCase(), arts, false, sourceKey !== "tmdb")}
      {/if}
    {/each}
  {/if}
</div>

{#snippet source(title: string, arts: ArtCandidate[], matched = false, showSource = false)}
  <ImageGrid {title} count={arts.length} {matched} {artType}>
    {#each arts as art (art.url)}
      <ArtCard
        {art}
        disabled={saving}
        {showSource}
        onSelect={(art) =>
          saveArt({ url: art.url, width: art.width, height: art.height }, candidateImageUrl(art))}
      />
    {/each}
  </ImageGrid>
{/snippet}

<style>
  .art-slot {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
  }
</style>
