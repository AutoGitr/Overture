<script lang="ts">
  import Check from "@lucide/svelte/icons/check";
  import Database from "@lucide/svelte/icons/database";
  import ExternalLink from "@lucide/svelte/icons/external-link";
  import Eye from "@lucide/svelte/icons/eye";
  import EyeOff from "@lucide/svelte/icons/eye-off";
  import Layers from "@lucide/svelte/icons/layers";
  import LoaderCircle from "@lucide/svelte/icons/loader-circle";
  import Music from "@lucide/svelte/icons/music";
  import { createMutation, createQuery } from "@tanstack/svelte-query";
  import type { CollectionDetail, ThemeSearchResult } from "../../generated/rest/types.gen";
  import githubIcon from "../../assets/icons/github.svg";
  import { patchCollection } from "../rest/cache";
  import {
    deleteCollectionThemeMutation,
    setCollectionThemeMutation,
    setCollectionMonitoredMutation,
    getPublicDatasetStatusOptions,
  } from "../../generated/rest/@tanstack/svelte-query.gen";
  import { downloadStageLabel, downloadState } from "../stores/downloadState.svelte";
  import { confirmAction, createNotifier } from "../stores/notificationState.svelte";
  import { settingsState } from "../stores/settingsState.svelte";
  import { goToCatalogEntry } from "../router/routes";
  import ExternalLinkBadges from "./ExternalLinkBadges.svelte";
  import CollectionMatchPanel from "./CollectionMatchPanel.svelte";
  import CollectionMembers from "./CollectionMembers.svelte";
  import { uiState } from "../stores/uiState.svelte";
  import { collectionImageUrl } from "../utils/artDisplay";
  import { errorMessage } from "../utils/errors";
  import { statusTone } from "../utils/sidebarDomain";
  import { buildContributionIssueUrl } from "../utils/publicDataset";
  import {
    buildCollectionThemeSearchQuery,
    mergeThemeResults,
    youtubeShortUrl,
  } from "../utils/themeSearch";
  import DetailPanelBase from "./DetailPanelBase.svelte";
  import IdBadge from "./IdBadge.svelte";
  import StatusTab from "./StatusTab.svelte";
  import ThemeSearch from "./ThemeSearch.svelte";

  let { collection: coll }: { collection: CollectionDetail | null } = $props();
  const feedback = createNotifier();
  const deleteThemeRequest = createMutation(() => deleteCollectionThemeMutation());
  const setThemeRequest = createMutation(() => setCollectionThemeMutation());
  const setMonitoredRequest = createMutation(() => setCollectionMonitoredMutation());
  const datasetQuery = createQuery(() => ({
    ...getPublicDatasetStatusOptions(),
    enabled: !!coll?.tmdb_collection_id,
  }));
  let contributionUrl = $derived.by(() => {
    if (
      !coll?.tmdb_collection_id ||
      !coll.youtube_id ||
      !datasetQuery.data?.repo_url ||
      coll.youtube_id === coll.youtube_id_overturedb ||
      coll.youtube_id === coll.youtube_id_themerrdb
    )
      return null;
    return buildContributionIssueUrl(datasetQuery.data.repo_url, {
      media_type: "collection",
      title: coll.title,
      tmdb_id: coll.tmdb_collection_id,
      tvdb_id: null,
      imdb_id: null,
      year: null,
      poster_url: null,
      background_url: null,
      seasons: null,
      youtube_id_overturedb: coll.youtube_id,
      youtube_id_themerrdb: null,
    });
  });

  let collectionThemeJob = $derived(coll ? downloadState.getCollectionJob(coll.id) : null);
  let activeThemeJob = $derived(
    collectionThemeJob?.status === "running" ? collectionThemeJob : null,
  );
  /** A chosen theme is on its way until its download ends. */
  let applying = $derived(
    setThemeRequest.isPending || !!activeThemeJob || collectionThemeJob?.status === "pending",
  );
  // Belongs to the collection it was chosen for, so switching never shows it.
  let chosen = $state<{ collectionId: number; videoId: string } | null>(null);
  let uploadingVideoId = $derived(
    applying && chosen && chosen.collectionId === coll?.id ? chosen.videoId : null,
  );
  let uploading = $derived(applying || deleteThemeRequest.isPending);
  let uploadProgressLabel = $derived(activeThemeJob ? downloadStageLabel(activeThemeJob) : "");

  async function handleToggleMonitored() {
    if (!coll) return;
    const target = coll;
    feedback.clear();
    try {
      const { monitored } = await setMonitoredRequest.mutateAsync({
        path: { collection_id: target.id },
        query: { media_type: target.media_type },
        body: { monitored: !target.monitored },
      });
      patchCollection(target.id, { monitored });
    } catch (error) {
      feedback.error(errorMessage(error, "Toggle monitored failed"));
    }
  }

  async function selectTheme(videoId: string): Promise<boolean> {
    if (!coll || uploading) return false;
    const target = coll;
    chosen = { collectionId: target.id, videoId };
    feedback.clear();
    try {
      const enqueueResult = await setThemeRequest.mutateAsync({
        body: {
          media_type: target.media_type,
          youtube_id: videoId,
        },
        path: { collection_id: target.id },
      });
      downloadState.trackQueuedCollectionJob({
        jobId: enqueueResult.job_id,
        collectionId: target.id,
        title: target.title,
      });
      return true;
    } catch (error) {
      feedback.error(errorMessage(error, "Upload failed"));
      return false;
    }
  }

  async function clearTheme() {
    if (!coll || uploading) return;
    const target = coll;
    const confirmed = await confirmAction({
      title: "Remove the collection theme?",
      message: `The theme is removed from ${target.title} on the media server.`,
      confirmLabel: "Remove",
      destructive: true,
    });
    if (!confirmed) return;
    feedback.clear();
    try {
      const cleared = await deleteThemeRequest.mutateAsync({
        path: { collection_id: target.id },
        query: { media_type: target.media_type },
      });
      patchCollection(target.id, {
        has_theme: cleared.has_theme,
        youtube_id: null,
        youtube_title: null,
        youtube_duration: null,
        theme_status: cleared.theme_status,
      });
    } catch (error) {
      feedback.error(errorMessage(error, "Clear failed"));
    }
  }
</script>

<DetailPanelBase
  isEmpty={!coll}
  subjectKey={coll?.id ?? null}
  backgroundUrl={collectionImageUrl(coll?.art_url)}
  posterHref={coll?.server_link ?? null}
  posterLinkTitle={coll?.server_link ? `Open in ${settingsState.media_server_name}` : null}
  summary={coll?.summary ?? null}
  emptyMessage="Select a collection from the sidebar"
  posterUrl={collectionImageUrl(coll?.thumb_url)}
  title={coll?.title ?? ""}
>
  {#snippet emptyIcon()}
    <Layers size={64} />
  {/snippet}

  {#snippet posterIcon()}
    <Layers size={48} />
  {/snippet}

  {#snippet meta()}
    <span class="collection-meta">{coll?.child_count} items</span>
  {/snippet}

  {#snippet badges()}
    {#if coll}
      <ExternalLinkBadges
        subject={{
          title: coll.title,
          year: null,
          media_type: "collection",
          tmdb_id: coll.tmdb_collection_id,
          tvdb_id: null,
          imdb_id: null,
        }}
        mode="themes"
        artType="poster"
        season={null}
      />
      {#if coll.catalog_entry_key}<IdBadge
          title="Open in OvertureDB"
          icon="/favicon.svg"
          alt="OvertureDB"
          onselect={() => {
            if (coll?.catalog_entry_key)
              goToCatalogEntry({
                media_type: "collection",
                entry_key: coll.catalog_entry_key,
              });
          }}
        />{/if}
    {/if}
    {#if contributionUrl}<IdBadge
        href={contributionUrl}
        title="Contribute to OvertureDB"
        icon={githubIcon}
        alt="GitHub"
      />{/if}
  {/snippet}

  {#snippet tabs()}
    <StatusTab
      icon={Music}
      label="Themes"
      active
      status={coll && statusTone(coll.theme_status, !!activeThemeJob)}
      clearLabel="Clear theme"
      onclear={coll && !coll.theme_unavailable && coll.theme_status !== "missing"
        ? clearTheme
        : null}
      clearDisabled={uploading}
    />
    <button
      class="tab-item"
      onclick={() => uiState.openPopupByName("database")}
      title="Open Database Record"
    >
      <Database size={16} /><span>Database</span>
    </button>
    <button
      class={["tab-item", { danger: !coll?.monitored }]}
      onclick={handleToggleMonitored}
      title={coll?.monitored ? "Monitored - click to unmonitor" : "Unmonitored - click to monitor"}
      disabled={setMonitoredRequest.isPending}
    >
      {#if coll?.monitored}
        <Eye size={16} />
      {:else}
        <EyeOff size={16} />
      {/if}
    </button>
  {/snippet}

  {#snippet content()}
    {#if coll}
      {#if coll.media_type === "movie"}<CollectionMatchPanel collection={coll} />{/if}
      {#if coll.theme_unavailable}<p class="text-muted">{coll.theme_unavailable}</p>{/if}
    {/if}
    {#if coll && !coll.theme_unavailable}
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

        {#if activeThemeJob}
          <div class="theme-status">
            <div class="theme-status-info">
              <LoaderCircle size={16} class="animate-spin text-accent" />
              <span>Theme job running: {uploadProgressLabel}</span>
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
                overtureDbId: coll?.youtube_id_overturedb,
                themerrDbId: coll?.youtube_id_themerrdb,
                searchResults: results,
              })}
            currentYoutubeId={coll.youtube_id}
            busyVideoId={uploadingVideoId}
            busy={uploading}
            onselect={selectTheme}
            selectLabel={(video) => {
              if (coll?.youtube_id === video.id && coll.has_theme) return "Assigned";
              if (coll?.youtube_id === video.id) return "Requeue";
              return "Select";
            }}
          />
        {/key}
      </div>
    {/if}
    {#if coll}<CollectionMembers members={coll.members} />{/if}
  {/snippet}
</DetailPanelBase>

<style>
  .collection-meta {
    color: var(--text-tertiary);
    font-size: var(--text-lg);
    font-family: var(--font-mono);
  }

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
