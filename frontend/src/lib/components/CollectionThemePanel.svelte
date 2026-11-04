<script lang="ts">
  import LoaderCircle from "@lucide/svelte/icons/loader-circle";
  import type { CollectionDetail, ThemeSearchResult } from "../../generated/rest/types.gen";
  import type { CollectionActions } from "../utils/collectionActions.svelte";
  import {
    buildCollectionThemeSearchQuery,
    mergeThemeResults,
  } from "../utils/themeSearch";
  import ThemeSearch from "./ThemeSearch.svelte";

  let {
    collection: coll,
    actions,
  }: {
    collection: CollectionDetail;
    actions: CollectionActions;
  } = $props();
</script>

{#if coll.theme_unavailable}
  <p class="text-muted">{coll.theme_unavailable}</p>
{:else}
  <div class="theme-panel">
    {#if actions.activeThemeJob}
      <div class="theme-status">
        <div class="theme-status-info">
          <LoaderCircle size={16} class="animate-spin text-accent" />
          <span>Theme job running: {actions.uploadProgressLabel}</span>
        </div>
      </div>
    {/if}

    {#key coll.id}
      <ThemeSearch
        label="Search collection themes"
        initialQuery={buildCollectionThemeSearchQuery(coll.title)}
        videoIds={[
          ...new Set(
            [coll.youtube_id, coll.youtube_id_overturedb, coll.youtube_id_themerrdb].filter(
              (id): id is string => !!id,
            ),
          ),
        ]}
        present={(results: ThemeSearchResult[]) =>
          mergeThemeResults({
            item: coll,
            overtureDbId: coll.youtube_id_overturedb,
            themerrDbId: coll.youtube_id_themerrdb,
            searchResults: results,
          })}
        currentYoutubeId={coll.youtube_id}
        busyVideoId={actions.uploadingVideoId}
        busy={actions.uploading}
        onselect={(videoId) => actions.selectTheme(videoId)}
        selectLabel={(video) => {
          if (coll.youtube_id === video.id && coll.has_theme) return "Assigned";
          if (coll.youtube_id === video.id) return "Requeue";
          return "Select";
        }}
      />
    {/key}
  </div>
{/if}

<style>
  .theme-panel {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
  }

  .theme-status {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
    padding: var(--space-3) var(--space-4);
    background: var(--bg-secondary);
    border-radius: var(--radius-md);
  }

  .theme-status-info {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    min-width: 0;
    font-size: var(--text-sm);
  }

</style>
