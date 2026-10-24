<script lang="ts">
  import Check from "@lucide/svelte/icons/check";
  import ExternalLink from "@lucide/svelte/icons/external-link";
  import LoaderCircle from "@lucide/svelte/icons/loader-circle";
  import type { CollectionDetail, ThemeSearchResult } from "../../generated/rest/types.gen";
  import type { CollectionActions } from "../utils/collectionActions.svelte";
  import {
    buildCollectionThemeSearchQuery,
    mergeThemeResults,
    youtubeShortUrl,
  } from "../utils/themeSearch";
  import ThemeSearch from "./ThemeSearch.svelte";

  let {
    collection: coll,
    actions,
    searchInputId,
  }: {
    collection: CollectionDetail;
    actions: CollectionActions;
    searchInputId?: string;
  } = $props();
</script>

{#if coll.theme_unavailable}
  <p class="text-muted">{coll.theme_unavailable}</p>
{:else}
  <div class="theme-panel">
    {#if coll.theme_status !== "missing"}
      <div class="theme-status">
        <div class="theme-status-info">
          <Check size={16} class="text-success" />
          {#if coll.youtube_id}
            <span>Source: </span>
            <a
              href={youtubeShortUrl(coll.youtube_id)}
              target="_blank"
              rel="noopener"
              class="theme-link"
            >
              youtu.be/{coll.youtube_id}
              <ExternalLink size={11} />
            </a>
          {:else}
            <span class="text-muted">Theme assigned</span>
          {/if}
        </div>
      </div>
    {/if}

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
        inputId={searchInputId}
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
    background: var(--success-muted);
    border: 1px solid oklch(from var(--success) l c h / 0.15);
    border-radius: var(--radius-md);
  }

  .theme-status-info {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    min-width: 0;
    font-size: var(--text-sm);
  }

  .theme-link {
    display: inline-flex;
    align-items: center;
    gap: 3px;
    min-width: 0;
    color: var(--accent);
    font-family: var(--font-mono);
    font-size: var(--text-xs);
  }
</style>
