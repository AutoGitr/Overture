<script lang="ts">
  import LoaderCircle from "@lucide/svelte/icons/loader-circle";
  import { createMutation, createQuery } from "@tanstack/svelte-query";
  import {
    getPublicDatasetSourcesOptions,
    getPublicDatasetStatusOptions,
    getTmdbPublicDatasetSourcesOptions,
    selectThemeMutation,
    selectTmdbThemeMutation,
  } from "../../generated/rest/@tanstack/svelte-query.gen";
  import type {
    MediaItemRead,
    ThemeSearchResult,
    TmdbItemPreview,
  } from "../../generated/rest/types.gen";
  import { upsertLibraryItem } from "../rest/cache";
  import { downloadStageLabel, downloadState } from "../stores/downloadState.svelte";
  import { createNotifier } from "../stores/notificationState.svelte";
  import { settingsState } from "../stores/settingsState.svelte";
  import type { CatalogContext } from "../utils/catalogDraft";
  import { errorMessage } from "../utils/errors";
  import { beginAutoAdvance, handleThemeSelectionAdvance } from "../utils/autoAdvance";
  import {
    buildCollectionThemeSearchQuery,
    buildThemeSearchQuery,
    mergeThemeResults,
  } from "../utils/themeSearch";
  import { openPersistedItem } from "../utils/tmdbItems";
  import DataStatus from "./DataStatus.svelte";
  import ThemeSearch from "./ThemeSearch.svelte";

  let {
    item = null,
    preview = null,
    catalog = null,
    searchInputId,
  }: {
    item?: MediaItemRead | null;
    searchInputId?: string;
    catalog?: CatalogContext | null;
    /** A TMDB title not yet stored: its first theme selection stores it. */
    preview?: TmdbItemPreview | null;
  } = $props();

  const datasetQuery = createQuery(() => getPublicDatasetStatusOptions());
  let datasetEnabled = $derived(datasetQuery.data?.enabled ?? false);
  let catalogEntry = $derived(catalog?.entry);
  let subject = $derived(item ?? preview ?? catalogEntry);
  const provenanceLabels = {
    download: "Source recorded when downloaded",
    embedded_id: "Recovered from an embedded YouTube ID",
    source_url: "Recovered from an embedded YouTube source URL",
    metadata_url: "Recovered from a YouTube link in file metadata",
    selection: "Selected in Overture; downloads once the item has a local folder",
  };

  const feedback = createNotifier();
  let downloadingId = $state<string | null>(null);
  const selectThemeRequest = createMutation(() => selectThemeMutation());
  const selectTmdbThemeRequest = createMutation(() => selectTmdbThemeMutation());

  // Active downloads for this item
  let activeDownloads = $derived(
    item ? downloadState.getJobsForItem(item.id).filter((job) => job.job_type === "theme") : [],
  );
  let themeBusy = $derived(
    downloadingId !== null || activeDownloads.some((job) => job.status === "running"),
  );
  // Keyed on the item, so responses stay with the item they were requested for.
  const itemSourcesQuery = createQuery(() => ({
    ...getPublicDatasetSourcesOptions({ path: { item_id: item?.id ?? 0 } }),
    enabled: !!item && !catalog && datasetEnabled,
  }));
  const tmdbSourcesQuery = createQuery(() => ({
    ...getTmdbPublicDatasetSourcesOptions({
      path: { media_type: preview?.media_type ?? "movie", tmdb_id: preview?.tmdb_id ?? 0 },
    }),
    enabled: !!preview && !catalog && datasetEnabled,
  }));
  let publicSourcesQuery = $derived(preview ? tmdbSourcesQuery : itemSourcesQuery);
  let datasetSource = $derived(
    catalogEntry ?? (datasetEnabled ? publicSourcesQuery.data?.item : null),
  );
  // The themes shown whatever is searched for: the current one and the dataset's.
  let candidateVideoIds = $derived([
    ...new Set(
      [
        item?.youtube_id,
        catalog?.detail.entry.youtube_id_overturedb,
        datasetSource?.youtube_id_overturedb,
        datasetSource?.youtube_id_themerrdb,
      ]
        .map((id) => id?.trim())
        .filter((id): id is string => Boolean(id)),
    ),
  ]);
  let subjectKey = $derived(
    catalog
      ? `catalog-${catalog.detail.entry.media_type}-${catalog.detail.entry_key}`
      : item
        ? `item-${item.id}`
        : preview
          ? `tmdb-${preview.media_type}-${preview.tmdb_id}`
          : null,
  );

  /** The subject's current and dataset themes first, then the videos found. */
  function presentResults(results: ThemeSearchResult[]) {
    return mergeThemeResults({
      item: catalogEntry
        ? {
            title: catalogEntry.title,
            youtube_id: catalogEntry.youtube_id_overturedb,
            youtube_title: null,
            youtube_duration: null,
          }
        : item,
      overtureDbId: datasetSource?.youtube_id_overturedb,
      themerrDbId: datasetSource?.youtube_id_themerrdb,
      searchResults: results,
    });
  }

  async function selectTheme(youtubeId: string): Promise<boolean> {
    if (catalog) return catalog.draft.save({ youtube_id_overturedb: youtubeId });
    if (themeBusy) return false;
    if (preview) return selectTmdbTheme(preview.media_type, preview.tmdb_id, youtubeId);
    if (!item) return false;
    const targetItem = item;
    const advanceContext = beginAutoAdvance();
    downloadingId = youtubeId;
    feedback.clear();
    try {
      const result = await selectThemeRequest.mutateAsync({
        path: { item_id: targetItem.id },
        body: { youtube_id: youtubeId },
      });
      // An item without a local folder records the choice and downloads nothing.
      if (result.selection.job_id) {
        downloadState.trackQueuedItemJob({
          jobId: result.selection.job_id,
          mediaItemId: targetItem.id,
          jobType: "theme",
        });
      }
      upsertLibraryItem(result.item);
      handleThemeSelectionAdvance(result.item, advanceContext);
      return true;
    } catch (err) {
      feedback.error(errorMessage(err, "Download failed"));
      return false;
    } finally {
      downloadingId = null;
    }
  }

  /** Store a TMDB title with its first theme, then show the item it became. */
  async function selectTmdbTheme(
    mediaType: "movie" | "show",
    tmdbId: number,
    youtubeId: string,
  ): Promise<boolean> {
    const advanceContext = beginAutoAdvance();
    downloadingId = youtubeId;
    feedback.clear();
    try {
      const result = await selectTmdbThemeRequest.mutateAsync({
        body: { youtube_id: youtubeId },
        path: { media_type: mediaType, tmdb_id: tmdbId },
      });
      await openPersistedItem(result.item, { theme: true }, advanceContext);
      return true;
    } catch (err) {
      feedback.error(errorMessage(err, "Selection failed"));
      return false;
    } finally {
      downloadingId = null;
    }
  }
</script>

<div class="theme-panel">
  {#if datasetEnabled && !catalog}
    <DataStatus
      label="OvertureDB theme"
      error={publicSourcesQuery.error}
      loading={publicSourcesQuery.isFetching}
      hasData={publicSourcesQuery.data !== undefined}
      onretry={() => publicSourcesQuery.refetch()}
    />
  {/if}

  <!-- Active Downloads -->
  {#each activeDownloads as job (job.job_id)}
    <div class={["download-progress-box", { error: job.status === "failed" }]}>
      <div class="download-progress-label">
        {#if job.status === "running"}
          <LoaderCircle size={14} class="animate-spin" />
        {/if}
        <span>{downloadStageLabel(job)}</span>
      </div>
      <div class="progress-bar progress-bar-sm">
        <div class="progress-bar-fill" style="width:{job.percent}%"></div>
      </div>
    </div>
  {/each}

  {#if item?.youtube_id && item.youtube_id_source}
    <p class="text-muted">{provenanceLabels[item.youtube_id_source]}</p>
  {/if}

  {#if subject}
    {#key subjectKey}
      <ThemeSearch
        label="Search themes"
        inputId={searchInputId}
        initialQuery={catalogEntry?.media_type === "collection"
          ? buildCollectionThemeSearchQuery(subject.title)
          : buildThemeSearchQuery(
              { title: subject.title, year: subject.year ?? null },
              settingsState.current.theme_search_format,
            )}
        videoIds={candidateVideoIds}
        present={presentResults}
        currentYoutubeId={catalogEntry?.youtube_id_overturedb ?? item?.youtube_id ?? null}
        busyVideoId={downloadingId}
        busy={themeBusy || (catalog?.draft.busy ?? false)}
        onselect={selectTheme}
      />
    {/key}
  {/if}
</div>

<style>
  .theme-panel {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
  }

  .download-progress-box {
    padding: var(--space-3);
    border-radius: var(--radius-md);
    border-left: 3px solid var(--accent);
    background: var(--bg-secondary);
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }

  .download-progress-box.error {
    border-left-color: var(--danger);
  }

  .download-progress-label {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    font-size: var(--text-sm);
    color: var(--text-secondary);
  }
</style>
