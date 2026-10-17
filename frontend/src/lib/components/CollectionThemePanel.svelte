<script lang="ts">
  import Check from "@lucide/svelte/icons/check";
  import Database from "@lucide/svelte/icons/database";
  import ExternalLink from "@lucide/svelte/icons/external-link";
  import Eye from "@lucide/svelte/icons/eye";
  import EyeOff from "@lucide/svelte/icons/eye-off";
  import Layers from "@lucide/svelte/icons/layers";
  import LoaderCircle from "@lucide/svelte/icons/loader-circle";
  import Music from "@lucide/svelte/icons/music";
  import { createMutation } from "@tanstack/svelte-query";
  import youtubeIcon from "../../assets/icons/youtube.svg";
  import { patchCollection } from "../rest/cache";
  import {
    deleteCollectionThemeMutation,
    setCollectionThemeMutation,
    setCollectionMonitoredMutation,
  } from "../../generated/rest/@tanstack/svelte-query.gen";
  import { collectionState } from "../stores/collectionState.svelte";
  import { downloadState } from "../stores/downloadState.svelte";
  import { confirmAction, createNotifier } from "../stores/notificationState.svelte";
  import { uiState } from "../stores/uiState.svelte";
  import { collectionImageUrl } from "../utils/artDisplay";
  import { errorMessage } from "../utils/errors";
  import { statusTone } from "../utils/sidebarDomain";
  import {
    buildCollectionThemeSearchQuery,
    youtubeSearchUrl,
    youtubeShortUrl,
  } from "../utils/themeSearch";
  import DetailPanelBase from "./DetailPanelBase.svelte";
  import FallbackImage from "./FallbackImage.svelte";
  import StatusTab from "./StatusTab.svelte";
  import ThemeSearch from "./ThemeSearch.svelte";

  let coll = $derived(collectionState.selectedCollection);
  const feedback = createNotifier();
  // Belongs to the collection it was chosen for, so switching never shows it.
  let pendingUpload = $state<{ collectionId: string; videoId: string } | null>(null);
  let uploadingVideoId = $derived(
    pendingUpload && pendingUpload.collectionId === coll?.id ? pendingUpload.videoId : null,
  );
  const deleteThemeRequest = createMutation(() => deleteCollectionThemeMutation());
  const setThemeRequest = createMutation(() => setCollectionThemeMutation());
  const setMonitoredRequest = createMutation(() => setCollectionMonitoredMutation());

  let collectionThemeJob = $derived(coll ? downloadState.getCollectionJob(coll.id) : null);
  let activeThemeJob = $derived.by(() => {
    const job = collectionThemeJob;
    return job?.status === "running" ? job : null;
  });
  let uploading = $derived(
    Boolean(
      uploadingVideoId ||
      setThemeRequest.isPending ||
      deleteThemeRequest.isPending ||
      activeThemeJob?.status === "running",
    ),
  );
  let uploadProgressLabel = $derived.by(() => {
    if (!activeThemeJob) return "";
    const stage = activeThemeJob.stage || "working";
    const percent = Number.isFinite(activeThemeJob.percent)
      ? ` ${Math.round(activeThemeJob.percent)}%`
      : "";
    return `${stage}${percent}`;
  });

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

  $effect(() => {
    if (coll && uploadingVideoId && coll.youtube_id === uploadingVideoId && coll.has_theme) {
      feedback.success(`Theme applied to ${coll.title}.`);
      pendingUpload = null;
    }
  });

  $effect(() => {
    // The download tracker reports the failure itself.
    if (collectionThemeJob?.status === "failed") {
      pendingUpload = null;
    }
  });

  async function selectTheme(videoId: string): Promise<boolean> {
    if (!coll || uploading) return false;
    const target = coll;
    pendingUpload = { collectionId: target.id, videoId };
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
        serverId: target.id,
        mediaType: target.media_type,
        title: target.title,
      });
      return true;
    } catch (error) {
      feedback.error(errorMessage(error, "Upload failed"));
      pendingUpload = null;
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
    pendingUpload = null;
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

{#snippet posterPlaceholder()}
  <div class="poster-placeholder">
    <Layers size={48} />
  </div>
{/snippet}

<DetailPanelBase
  isEmpty={!coll}
  subjectKey={coll?.id ?? null}
  backgroundUrl={collectionImageUrl(coll?.art_url)}
  posterHref={coll?.server_link ?? null}
  posterLinkTitle={coll?.server_link ? "Open in Plex" : null}
  summary={coll?.summary ?? null}
>
  {#snippet emptyState()}
    <div class="empty-icon">
      <Layers size={64} />
    </div>
    <p>Select a collection from the sidebar</p>
  {/snippet}

  {#snippet posterContent()}
    <!-- Named by the heading beside it, so no alt text shows while it loads. -->
    <FallbackImage
      src={collectionImageUrl(coll?.thumb_url)}
      alt=""
      loading="eager"
      fetchpriority="high"
      placeholder={posterPlaceholder}
    />
  {/snippet}

  {#snippet titleRow()}
    <div class="title-row">
      <h2 class="detail-title">{coll?.title}</h2>
      <span class="collection-meta">{coll?.child_count} items</span>
    </div>
  {/snippet}

  {#snippet badges()}
    {#if coll?.title}
      <a
        class="id-badge youtube"
        href={youtubeSearchUrl(buildCollectionThemeSearchQuery(coll.title))}
        target="_blank"
        rel="noopener"
        title="Search YouTube"><img src={youtubeIcon} alt="YouTube" /></a
      >
    {/if}
  {/snippet}

  {#snippet tabs()}
    <div class="mode-tabs tab-bar" role="tablist" aria-label="Detail modes">
      <StatusTab
        icon={Music}
        label="Themes"
        active
        status={coll && statusTone(coll.theme_status, !!activeThemeJob)}
        clearLabel="Clear theme"
        onclear={coll && coll.theme_status !== "missing" ? clearTheme : null}
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
        class="tab-item"
        class:danger={!coll?.monitored}
        onclick={handleToggleMonitored}
        title={coll?.monitored
          ? "Monitored - click to unmonitor"
          : "Unmonitored - click to monitor"}
        disabled={setMonitoredRequest.isPending}
      >
        {#if coll?.monitored}
          <Eye size={16} />
        {:else}
          <EyeOff size={16} />
        {/if}
      </button>
    </div>
  {/snippet}

  {#snippet content()}
    {#if coll?.server_type === "plex"}
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
</style>
