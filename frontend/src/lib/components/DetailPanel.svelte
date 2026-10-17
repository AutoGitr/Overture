<script lang="ts">
  import Clapperboard from "@lucide/svelte/icons/clapperboard";
  import Database from "@lucide/svelte/icons/database";
  import Eye from "@lucide/svelte/icons/eye";
  import EyeOff from "@lucide/svelte/icons/eye-off";
  import Image from "@lucide/svelte/icons/image";
  import Layers from "@lucide/svelte/icons/layers";
  import MonitorPlay from "@lucide/svelte/icons/monitor-play";
  import MountainSnow from "@lucide/svelte/icons/mountain-snow";
  import Music from "@lucide/svelte/icons/music";
  import Trash from "@lucide/svelte/icons/trash";
  import { createMutation, createQuery } from "@tanstack/svelte-query";
  import githubIcon from "../../assets/icons/github.svg";
  import type { ArtType, MediaItemRead, SeasonRead } from "../../generated/rest/types.gen";
  import { invalidateSeasons, refreshItem, upsertLibraryItem } from "../rest/cache";
  import { createSeasonsQuery } from "../rest/queries";
  import {
    clearAllArtMutation,
    clearArtMutation,
    clearThemeMutation,
    deleteItemMutation,
    getPublicDatasetRecordOptions,
    setMonitoredMutation,
  } from "../../generated/rest/@tanstack/svelte-query.gen";
  import { goToItemArt, goToItemThemes, goToLibrary } from "../router/routes";
  import { artPreviewState } from "../stores/artPreviewState.svelte";
  import { downloadState } from "../stores/downloadState.svelte";
  import { confirmAction, createNotifier } from "../stores/notificationState.svelte";
  import { publicDatasetState } from "../stores/publicDatasetState.svelte";
  import { selectedState } from "../stores/selectedState.svelte";
  import { settingsState } from "../stores/settingsState.svelte";
  import { uiState } from "../stores/uiState.svelte";
  import { itemArtDisplayUrl, remotePosterUrl } from "../utils/artDisplay";
  import { errorMessage } from "../utils/errors";
  import {
    buildContributionIssueUrl,
    hasContributionValues,
    selectionMatchesPublicDataset,
  } from "../utils/publicDataset";
  import { hasThemeAttributes, statusTone } from "../utils/sidebarDomain";
  import ArtPanel from "./ArtPanel.svelte";
  import DetailPanelBase from "./DetailPanelBase.svelte";
  import ExternalLinkBadges from "./ExternalLinkBadges.svelte";
  import PasteArtButton from "./PasteArtButton.svelte";
  import SeasonGrid from "./SeasonGrid.svelte";
  import StatusTab from "./StatusTab.svelte";
  import ThemePanel from "./ThemePanel.svelte";
  import DataStatus from "./DataStatus.svelte";
  import FallbackImage from "./FallbackImage.svelte";

  type ArtSubTab = typeof selectedState.artSubTab;

  function checkArtForSubTab(item: MediaItemRead | null, seasons: SeasonRead[], tab: string) {
    if (!item) return false;
    if (tab === "poster") return !!item.poster_url;
    if (tab === "background") return !!item.background_url;
    if (tab === "seasons") return seasons.some((season) => !!season.poster_url);
    return false;
  }

  function hasArtForSubTab(tab: string) {
    return checkArtForSubTab(item, seasons, tab);
  }

  function hasAnyArt(item: MediaItemRead | null) {
    if (!item) return false;
    if (item.poster_url || item.background_url) return true;
    if (item.media_type === "show") {
      if (seasons.some((season) => !!season.poster_url)) return true;
    }
    return false;
  }

  const feedback = createNotifier();
  let item = $derived(selectedState.item);
  // A TMDB title shows like an item; only a stored item has records to manage.
  let subject = $derived(selectedState.subject);
  let artType = $derived(selectedState.currentArtType);
  const seasonsQuery = createSeasonsQuery(() => item);
  let seasons = $derived(seasonsQuery.data ?? []);
  let drillSeason = $derived(
    selectedState.drillSeasonNum === null ? null : { season_num: selectedState.drillSeasonNum },
  );
  const publicDatasetRecordQuery = createQuery(() => ({
    ...getPublicDatasetRecordOptions({ path: { item_id: item?.id ?? 0 } }),
    enabled: publicDatasetState.enabled && !!item?.id,
  }));
  let publicDatasetRecord = $derived(
    publicDatasetRecordQuery.data?.found ? publicDatasetRecordQuery.data : null,
  );
  let publicDatasetRecordLoaded = $derived(
    !publicDatasetState.enabled || !item?.id || publicDatasetRecordQuery.isSuccess,
  );
  const clearAllArtRequest = createMutation(() => clearAllArtMutation());
  const clearArtRequest = createMutation(() => clearArtMutation());
  const clearThemeRequest = createMutation(() => clearThemeMutation());
  let clearingArt = $derived(clearArtRequest.isPending || clearAllArtRequest.isPending);
  let themeJobs = $derived(
    item ? downloadState.getJobsForItem(item.id).filter((job) => job.job_type === "theme") : [],
  );
  let themeBusy = $derived(
    clearThemeRequest.isPending || themeJobs.some((job) => job.status === "running"),
  );
  const setMonitoredRequest = createMutation(() => setMonitoredMutation());

  let repoUrl = $derived(publicDatasetState.status?.repo_url ?? "");
  let contributionUrl = $derived(
    item && repoUrl ? buildContributionIssueUrl(repoUrl, item, seasons) : "",
  );
  let contributionMatchesOvertureDb = $derived(
    selectionMatchesPublicDataset(item, seasons, publicDatasetRecord),
  );
  let showContributionLink = $derived(
    !!contributionUrl &&
      hasContributionValues(item, seasons) &&
      publicDatasetRecordLoaded &&
      !contributionMatchesOvertureDb,
  );

  function openContributionIssue(event: MouseEvent) {
    event.preventDefault();
    window.open(contributionUrl, "_blank", "noopener,noreferrer");
  }

  // -- Art helpers ----------------------------------------------------------
  async function clearArtForSubTab(tab: ArtSubTab) {
    if (!item || clearingArt) return;
    const targetItem = item;
    const confirmed = await confirmAction({
      title: `Forget the saved ${tab} selection?`,
      message: "Local artwork files are kept.",
      confirmLabel: "Forget",
      destructive: true,
    });
    if (!confirmed) return;
    feedback.clear();
    try {
      if (tab === "seasons") {
        // Without a season, every season's poster is forgotten at once.
        await clearArtRequest.mutateAsync({
          path: { item_id: targetItem.id, art_type: "season_poster" },
        });
        await Promise.all([refreshItem(targetItem.id), invalidateSeasons(targetItem.id)]);
      } else {
        await clearArtRequest.mutateAsync({ path: { item_id: targetItem.id, art_type: tab } });
        await refreshItem(targetItem.id);
      }
    } catch (err) {
      feedback.error(errorMessage(err, "Clear art failed"));
    }
  }

  async function clearAllArt() {
    if (!item || clearingArt) return;
    const targetItem = item;
    const confirmed = await confirmAction({
      title: "Forget every saved artwork selection?",
      message: "Local artwork files are kept.",
      confirmLabel: "Forget all",
      destructive: true,
    });
    if (!confirmed) return;
    feedback.clear();
    try {
      await clearAllArtRequest.mutateAsync({ path: { item_id: targetItem.id } });
      await Promise.all([refreshItem(targetItem.id), invalidateSeasons(targetItem.id)]);
    } catch (err) {
      feedback.error(errorMessage(err, "Clear all art failed"));
    }
  }

  async function clearTheme() {
    if (!item || themeBusy) return;
    const targetItem = item;
    const confirmed = await confirmAction({
      title: "Forget the saved theme selection?",
      message: "The local theme file is kept.",
      confirmLabel: "Forget",
      destructive: true,
    });
    if (!confirmed) return;
    feedback.clear();
    try {
      await clearThemeRequest.mutateAsync({ path: { item_id: targetItem.id } });
      await refreshItem(targetItem.id);
    } catch (err) {
      feedback.error(errorMessage(err, "Clear theme failed"));
    }
  }

  async function handleToggleMonitored() {
    if (!item) return;
    feedback.clear();
    try {
      const { monitored } = await setMonitoredRequest.mutateAsync({
        path: { item_id: item.id },
        body: { monitored: !item.monitored },
      });
      upsertLibraryItem({ ...item, monitored });
    } catch (err) {
      feedback.error(errorMessage(err, "Toggle monitored failed"));
    }
  }

  const deleteItemRequest = createMutation(() => deleteItemMutation());

  async function handleDeleteItem() {
    if (!item) return;
    const targetItem = item;
    const confirmed = await confirmAction({
      title: `Remove ${targetItem.title ?? "this item"} from Overture?`,
      message:
        "Its saved record will be removed. Local files and the media server item are kept, so it may return after a sync.",
      confirmLabel: "Remove",
      destructive: true,
    });
    if (!confirmed) return;
    feedback.clear();
    try {
      const deletedItemType = targetItem.media_type;
      await deleteItemRequest.mutateAsync({ path: { item_id: targetItem.id } });
      goToLibrary(deletedItemType);
    } catch (err) {
      feedback.error(errorMessage(err, "Delete item failed"));
    }
  }

  // -- Art sub-tab config ---------------------------------------------------
  const subTabConfig: {
    key: ArtSubTab;
    label: string;
    icon: typeof Image;
    artType: ArtType;
    statusField: "poster_status" | "background_status" | "season_posters_status";
    showOnly?: boolean;
  }[] = [
    {
      key: "poster",
      label: "Poster",
      icon: Image,
      artType: "poster",
      statusField: "poster_status",
    },
    {
      key: "background",
      label: "Background",
      icon: MountainSnow,
      artType: "background",
      statusField: "background_status",
    },
    {
      key: "seasons",
      label: "Seasons",
      icon: Layers,
      artType: "season_poster",
      statusField: "season_posters_status",
      showOnly: true,
    },
  ];
  let visibleSubTabs = $derived(
    subTabConfig.filter((t) => {
      if (t.showOnly && subject?.media_type !== "show") return false;
      return true;
    }),
  );

  // A choice being fetched shows its preview until the item shows the file.
  let backgroundUrl = $derived(
    item
      ? (artPreviewState.previewFor(item, "background") ?? itemArtDisplayUrl(item, "background"))
      : (selectedState.preview?.background_url ?? null),
  );
  let posterUrl = $derived(
    item
      ? (artPreviewState.previewFor(item, "poster") ?? itemArtDisplayUrl(item, "poster"))
      : selectedState.preview
        ? remotePosterUrl(selectedState.preview)
        : null,
  );
  let subjectKey = $derived(
    item
      ? `item:${item.id}`
      : selectedState.preview
        ? `tmdb:${selectedState.preview.media_type}:${selectedState.preview.tmdb_id}`
        : null,
  );

  function selectArtSubTab(tab: ArtSubTab) {
    if (subject) goToItemArt(subject, tab);
  }
</script>

{#snippet posterPlaceholder()}
  <div class="poster-placeholder">
    {#if subject?.media_type === "movie"}
      <Clapperboard size={48} />
    {:else}
      <Layers size={48} />
    {/if}
  </div>
{/snippet}

<DetailPanelBase
  isEmpty={!subject}
  {subjectKey}
  {backgroundUrl}
  posterHref={item?.server_link ?? null}
  posterLinkTitle={item?.server_link ? `Open in ${settingsState.media_server_name}` : null}
>
  {#snippet emptyState()}
    <div class="empty-icon">
      {#if uiState.sidebarTab === "movie"}
        <Clapperboard size={64} />
      {:else}
        <MonitorPlay size={64} />
      {/if}
    </div>
    <p>
      Select a {uiState.sidebarTab === "movie" ? "movie" : "show"} from the sidebar
    </p>
  {/snippet}

  {#snippet posterContent()}
    <!-- An image that fails to load (a file gone from disk) shows the placeholder.
         The title is the heading beside it, so the image has no alt text for a
         browser to draw in its place while it loads. -->
    <FallbackImage
      src={posterUrl}
      alt=""
      loading="eager"
      fetchpriority="high"
      placeholder={posterPlaceholder}
    />
  {/snippet}

  {#snippet titleRow()}
    <div class="title-row">
      <h2 class="detail-title">{subject?.title}</h2>
      {#if subject?.year}
        <span class="detail-year">{subject.year}</span>
      {/if}
    </div>
  {/snippet}

  {#snippet badges()}
    <ExternalLinkBadges {subject} mode={selectedState.mode} {artType} season={drillSeason} />
    {#if showContributionLink}
      <a
        class="id-badge github"
        href={contributionUrl}
        target="_blank"
        rel="noopener noreferrer"
        title="Contribute to OvertureDB"
        onclick={openContributionIssue}
      >
        <img src={githubIcon} alt="GitHub" />
      </a>
    {/if}
  {/snippet}

  {#snippet tabs()}
    <div class="mode-tabs tab-bar" role="tablist" aria-label="Detail modes">
      <StatusTab
        icon={Image}
        label="Art"
        active={selectedState.mode === "art"}
        status={item &&
          statusTone(item.art_status, downloadState.isDownloadingType(item.id, "art"))}
        onselect={() => selectArtSubTab("poster")}
        clearLabel="Clear all art"
        onclear={hasAnyArt(item) ? clearAllArt : null}
        clearDisabled={clearingArt}
      />
      <StatusTab
        icon={Music}
        label="Themes"
        active={selectedState.mode === "themes"}
        status={item &&
          statusTone(item.theme_status, downloadState.isDownloadingType(item.id, "theme"))}
        onselect={() => {
          if (subject) goToItemThemes(subject);
        }}
        clearLabel="Clear theme"
        onclear={hasThemeAttributes(item) ? clearTheme : null}
        clearDisabled={themeBusy}
      />
      <!-- A TMDB title has no record until its first selection stores it. -->
      {#if item}
        <button
          class="tab-item"
          onclick={() => uiState.openPopupByName("database")}
          title="Open Database Record"
        >
          <Database size={16} /><span>Database</span>
        </button>
        <button
          class="tab-item"
          class:danger={!item.monitored}
          onclick={handleToggleMonitored}
          title={item.monitored
            ? "Monitored - click to unmonitor"
            : "Unmonitored - click to monitor"}
          disabled={setMonitoredRequest.isPending}
        >
          {#if item.monitored}
            <Eye size={16} />
          {:else}
            <EyeOff size={16} />
          {/if}
        </button>
        <button
          class="tab-item danger"
          onclick={handleDeleteItem}
          title="Delete Item from Database"
          disabled={deleteItemRequest.isPending}
        >
          <Trash size={16} />
        </button>
      {/if}
    </div>
  {/snippet}

  {#snippet subtabs()}
    <div class="art-subtabs tab-bar" role="tablist" aria-label="Art categories">
      {#each visibleSubTabs as tab (tab.key)}
        <StatusTab
          icon={tab.icon}
          label={tab.label}
          active={selectedState.mode === "art" && selectedState.artSubTab === tab.key}
          status={item &&
            statusTone(
              item[tab.statusField],
              downloadState.isDownloadingType(item.id, "art", tab.artType),
            )}
          onselect={() => selectArtSubTab(tab.key)}
          clearLabel="Clear {tab.label.toLowerCase()}"
          onclear={hasArtForSubTab(tab.key) ? () => clearArtForSubTab(tab.key) : null}
          clearDisabled={clearingArt}
        />
      {/each}
    </div>
    <PasteArtButton />
  {/snippet}

  {#snippet content()}
    {#if publicDatasetState.enabled && item}
      <DataStatus
        label="OvertureDB record"
        error={publicDatasetRecordQuery.error}
        hasData={publicDatasetRecordQuery.data !== undefined}
        loading={publicDatasetRecordQuery.isFetching}
        onretry={() => publicDatasetRecordQuery.refetch()}
      />
    {/if}
    {#if selectedState.mode === "art"}
      {#if selectedState.artSubTab === "seasons" && selectedState.drillSeasonNum === null}
        <SeasonGrid />
      {:else}
        <ArtPanel />
      {/if}
    {:else if selectedState.mode === "themes"}
      {#key subjectKey}
        <ThemePanel />
      {/key}
    {/if}
  {/snippet}
</DetailPanelBase>
