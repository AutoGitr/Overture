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
  import { createQuery } from "@tanstack/svelte-query";
  import type { Snippet } from "svelte";
  import { SvelteMap } from "svelte/reactivity";
  import githubIcon from "../../assets/icons/github.svg";
  import type {
    ArtType,
    CatalogEntryDetail,
    MediaItemRead,
    TmdbItemPreview,
  } from "../../generated/rest/types.gen";
  import { CatalogDraft } from "../utils/catalogDraft";
  import { createSeasonsQuery } from "../rest/queries";
  import {
    getPublicDatasetRecordOptions,
    getPublicDatasetStatusOptions,
    getTmdbItemOptions,
  } from "../../generated/rest/@tanstack/svelte-query.gen";
  import {
    goToItemArt,
    goToItemThemes,
    goToCatalogEntry,
    goToCollection,
    goToItem,
    viewArtType,
    type ArtSubTab,
    type ItemView,
  } from "../router/routes";
  import { artPreviewState } from "../stores/artPreviewState.svelte";
  import { downloadState } from "../stores/downloadState.svelte";
  import { settingsState } from "../stores/settingsState.svelte";
  import { uiState } from "../stores/uiState.svelte";
  import { itemArtDisplayUrl, remotePosterUrl } from "../utils/artDisplay";
  import { ItemRecordActions } from "../utils/itemRecordActions.svelte";
  import {
    buildContributionIssueUrl,
    hasContributionValues,
    selectionMatchesPublicDataset,
  } from "../utils/publicDataset";
  import { catalogStatus, hasThemeAttributes, statusTone } from "../utils/sidebarDomain";
  import CollectionBadge from "./CollectionBadge.svelte";
  import ArtPanel from "./ArtPanel.svelte";
  import DetailPanelBase from "./DetailPanelBase.svelte";
  import IdBadge from "./IdBadge.svelte";
  import ExternalLinkBadges from "./ExternalLinkBadges.svelte";
  import PasteArtButton from "./PasteArtButton.svelte";
  import SeasonGrid from "./SeasonGrid.svelte";
  import StatusTab from "./StatusTab.svelte";
  import ThemePanel from "./ThemePanel.svelte";
  import DataStatus from "./DataStatus.svelte";

  let {
    item = null,
    preview = null,
    detail = null,
    members,
    view = { mode: "art", artSubTab: "poster", drillSeasonNum: null },
  }: {
    item?: MediaItemRead | null;
    /** A TMDB title open before its first selection stores it as an item. */
    preview?: TmdbItemPreview | null;
    detail?: CatalogEntryDetail | null;
    members?: Snippet;
    view?: ItemView;
  } = $props();

  const datasetQuery = createQuery(() => getPublicDatasetStatusOptions());
  let datasetEnabled = $derived(datasetQuery.data?.enabled ?? false);

  const actions = new ItemRecordActions(() => item);
  // A TMDB title shows like an item; only a stored item has records to manage.
  let catalogEntry = $derived(detail?.draft ?? detail?.entry);
  let catalogTones = $derived(catalogEntry ? catalogStatus(catalogEntry) : null);
  let catalogTarget = $derived(
    detail ? { media_type: detail.entry.media_type, entry_key: detail.entry_key } : null,
  );
  const draft = new CatalogDraft(() => catalogTarget);
  const catalogTmdbQuery = createQuery(() => ({
    ...getTmdbItemOptions({ path: { media_type: "show", tmdb_id: catalogEntry?.tmdb_id ?? 0 } }),
    enabled:
      catalogEntry?.media_type === "show" &&
      !!catalogEntry.tmdb_id &&
      settingsState.current.tmdb_configured &&
      view.mode === "art" &&
      view.artSubTab === "seasons",
  }));
  let catalogSeasons = $derived.by(() => {
    const merged = new SvelteMap(
      (catalogTmdbQuery.data?.seasons ?? []).map((season) => [season.season_num, season]),
    );
    for (const season of catalogEntry?.seasons ?? []) {
      merged.set(season.season_num, {
        ...merged.get(season.season_num),
        season_num: season.season_num,
        title: `Season ${season.season_num}`,
        poster_url: season.poster_url,
        poster_preview_url: null,
      });
    }
    return [...merged.values()].sort((a, b) => a.season_num - b.season_num);
  });
  let catalog = $derived(detail ? { detail, draft, seasons: catalogSeasons } : null);
  let subject = $derived(item ?? preview ?? catalogEntry ?? null);
  let artType = $derived(viewArtType(view));
  const seasonsQuery = createSeasonsQuery(() => item);
  let seasons = $derived(seasonsQuery.data ?? []);
  let drillSeason = $derived(
    view.drillSeasonNum === null ? null : { season_num: view.drillSeasonNum },
  );
  const publicDatasetRecordQuery = createQuery(() => ({
    ...getPublicDatasetRecordOptions({ path: { item_id: item?.id ?? 0 } }),
    enabled: datasetEnabled && !!item?.id,
  }));
  let publicDatasetRecord = $derived(
    publicDatasetRecordQuery.data?.found ? publicDatasetRecordQuery.data : null,
  );
  let publicDatasetRecordLoaded = $derived(
    !datasetEnabled || !item?.id || publicDatasetRecordQuery.isSuccess,
  );
  /** Which art tabs hold a saved selection to forget. */
  let savedArt = $derived({
    poster: !!(catalogEntry ?? item)?.poster_url,
    background: !!(catalogEntry ?? item)?.background_url,
    seasons: (catalogEntry?.seasons ?? seasons).some((season) => !!season.poster_url),
  });

  let repoUrl = $derived(datasetQuery.data?.repo_url ?? "");
  let contributionUrl = $derived.by(() => {
    const selection = catalogEntry ?? item;
    return repoUrl && selection ? buildContributionIssueUrl(repoUrl, selection, seasons) : "";
  });
  let contributionMatchesOvertureDb = $derived(
    selectionMatchesPublicDataset(item, seasons, publicDatasetRecord),
  );
  let showContributionLink = $derived(
    !!contributionUrl &&
      (detail
        ? !!detail.draft
        : hasContributionValues(item, seasons) &&
          publicDatasetRecordLoaded &&
          !contributionMatchesOvertureDb),
  );

  function openContributionIssue(event: MouseEvent) {
    event.preventDefault();
    window.open(contributionUrl, "_blank", "noopener,noreferrer");
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
      : (catalogEntry?.background_url ?? preview?.background_url ?? null),
  );
  let posterUrl = $derived(
    item
      ? (artPreviewState.previewFor(item, "poster") ?? itemArtDisplayUrl(item, "poster"))
      : catalogEntry
        ? catalogEntry.poster_url
        : preview
          ? remotePosterUrl(preview)
          : null,
  );
  let subjectKey = $derived(
    catalogTarget
      ? `catalog:${catalogTarget.media_type}:${catalogTarget.entry_key}`
      : item
        ? `item:${item.id}`
        : preview
          ? `tmdb:${preview.media_type}:${preview.tmdb_id}`
          : null,
  );

  function selectArtSubTab(tab: ArtSubTab) {
    if (catalogTarget)
      goToCatalogEntry(catalogTarget, { mode: "art", artSubTab: tab, drillSeasonNum: null });
    else {
      const title = item ?? preview;
      if (title) goToItemArt(title, tab);
    }
  }

  function clearArt(tab: ArtSubTab | "all") {
    if (!catalogEntry)
      return tab === "all"
        ? actions.clearAllArt()
        : actions.clearArt(
            tab,
            tab === "seasons"
              ? (seasons.find((season) => season.season_num === view.drillSeasonNum)?.id ?? null)
              : null,
          );
    void draft.save(
      tab === "all"
        ? { poster_url: null, background_url: null, seasons: [] }
        : tab === "seasons"
          ? {
              seasons:
                view.drillSeasonNum === null
                  ? []
                  : (catalogEntry.seasons ?? []).filter(
                      (season) => season.season_num !== view.drillSeasonNum,
                    ),
            }
          : tab === "poster"
            ? { poster_url: null }
            : { background_url: null },
    );
  }

  function openLibrary() {
    if (!detail || !catalogEntry) return;
    if (detail.library_item_id && catalogEntry.media_type !== "collection")
      void goToItem({
        id: detail.library_item_id,
        title: catalogEntry.title,
        media_type: catalogEntry.media_type,
      });
    else if (detail.library_collection_id)
      goToCollection({
        id: detail.library_collection_id,
        title: catalogEntry.title,
        media_type: "movie",
      });
  }
</script>

<DetailPanelBase
  isEmpty={!subject}
  {subjectKey}
  {backgroundUrl}
  posterHref={item?.server_link ?? null}
  posterLinkTitle={item?.server_link ? `Open in ${settingsState.media_server_name}` : null}
  emptyMessage="Select a {uiState.sidebarTab === 'movie' ? 'movie' : 'show'} from the sidebar"
  {posterUrl}
  title={subject?.title ?? ""}
>
  {#snippet emptyIcon()}
    {#if uiState.sidebarTab === "movie"}
      <Clapperboard size={64} />
    {:else}
      <MonitorPlay size={64} />
    {/if}
  {/snippet}

  {#snippet posterIcon()}
    {#if subject?.media_type === "movie"}
      <Clapperboard size={48} />
    {:else}
      <Layers size={48} />
    {/if}
  {/snippet}

  {#snippet meta()}
    {#if subject?.year}
      <span class="detail-year">{subject.year}</span>
    {/if}
    {#if detail?.draft}<span class="badge badge-warning">Draft</span>{/if}
  {/snippet}

  {#snippet badges()}
    <ExternalLinkBadges {subject} mode={view.mode} {artType} season={drillSeason} />
    {#if detail?.library_item_id || detail?.library_collection_id}
      <IdBadge
        title="Open in library"
        icon="/favicon.svg"
        alt="Open in library"
        onselect={openLibrary}
      />
    {/if}
    {#if detail?.draft}<button
        class="btn btn-ghost btn-sm"
        disabled={draft.busy}
        onclick={() => draft.discard()}>Discard draft</button
      >{/if}
    {#if item?.tmdb_collection_id}<CollectionBadge
        tmdbId={item.tmdb_collection_id}
        libraryCollectionId={item.library_collection_id}
        {datasetEnabled}
      />{/if}
    {#if showContributionLink}
      <IdBadge
        href={contributionUrl}
        title="Contribute to OvertureDB"
        icon={githubIcon}
        alt="GitHub"
        onclick={openContributionIssue}
      />
    {/if}
  {/snippet}

  {#snippet tabs()}
    <StatusTab
      icon={Image}
      label="Art"
      active={view.mode === "art"}
      status={catalogTones?.art ??
        (item && statusTone(item.art_status, downloadState.isDownloadingType(item.id, "art")))}
      onselect={() => selectArtSubTab("poster")}
      clearLabel="Clear all art"
      onclear={Object.values(savedArt).some(Boolean) ? () => clearArt("all") : null}
      clearDisabled={draft.busy || actions.clearingArt}
    />
    <StatusTab
      icon={Music}
      label="Themes"
      active={view.mode === "themes"}
      status={catalogTones?.theme ??
        (item && statusTone(item.theme_status, downloadState.isDownloadingType(item.id, "theme")))}
      onselect={() => {
        if (catalogTarget)
          goToCatalogEntry(catalogTarget, {
            mode: "themes",
            artSubTab: "poster",
            drillSeasonNum: null,
          });
        else {
          const title = item ?? preview;
          if (title) goToItemThemes(title);
        }
      }}
      clearLabel="Clear theme"
      onclear={catalogEntry
        ? catalogEntry.youtube_id_overturedb
          ? () => {
              void draft.save({ youtube_id_overturedb: null });
            }
          : null
        : hasThemeAttributes(item)
          ? () => actions.clearTheme()
          : null}
      clearDisabled={draft.busy || actions.themeBusy}
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
        class={["tab-item", { danger: !item.monitored }]}
        onclick={() => actions.toggleMonitored()}
        title={item.monitored ? "Monitored - click to unmonitor" : "Unmonitored - click to monitor"}
        disabled={actions.monitoring}
      >
        {#if item.monitored}
          <Eye size={16} />
        {:else}
          <EyeOff size={16} />
        {/if}
      </button>
      <button
        class="tab-item danger"
        onclick={() => actions.delete()}
        title="Delete Item from Database"
        disabled={actions.deleting}
      >
        <Trash size={16} />
      </button>
    {/if}
  {/snippet}

  {#snippet subtabs()}
    {#each visibleSubTabs as tab (tab.key)}
      <StatusTab
        icon={tab.icon}
        label={tab.label}
        active={view.mode === "art" && view.artSubTab === tab.key}
        status={catalogTones?.[tab.key] ??
          (item &&
            statusTone(
              item[tab.statusField],
              downloadState.isDownloadingType(item.id, "art", tab.artType),
            ))}
        onselect={() => selectArtSubTab(tab.key)}
        clearLabel={tab.key === "seasons" && view.drillSeasonNum !== null
          ? "Clear season poster"
          : `Clear ${tab.label.toLowerCase()}`}
        onclear={savedArt[tab.key] ? () => clearArt(tab.key) : null}
        clearDisabled={draft.busy || actions.clearingArt}
      />
    {/each}
  {/snippet}

  {#snippet subtabActions()}
    <PasteArtButton />
  {/snippet}

  {#snippet content()}
    {#if datasetEnabled && item}
      <DataStatus
        label="OvertureDB record"
        error={publicDatasetRecordQuery.error}
        hasData={publicDatasetRecordQuery.data !== undefined}
        loading={publicDatasetRecordQuery.isFetching}
        onretry={() => publicDatasetRecordQuery.refetch()}
      />
    {/if}
    {#if view.mode === "art"}
      {#if catalog && view.artSubTab === "seasons"}
        <DataStatus
          label="TMDB seasons"
          error={catalogTmdbQuery.error}
          loading={catalogTmdbQuery.isFetching}
          hasData={catalogTmdbQuery.data !== undefined}
          onretry={() => catalogTmdbQuery.refetch()}
        />
      {/if}
      {#if view.artSubTab === "seasons" && view.drillSeasonNum === null}
        <SeasonGrid {item} {preview} {catalog} />
      {:else}
        <ArtPanel {item} {preview} {catalog} {artType} drillSeasonNum={view.drillSeasonNum} />
      {/if}
    {:else}
      {#key subjectKey}
        <ThemePanel {item} {preview} {catalog} />
      {/key}
    {/if}
    {#if members}{@render members()}{/if}
  {/snippet}
</DetailPanelBase>

<style>
  .detail-year {
    font-size: var(--text-lg);
    font-family: var(--font-mono);
  }
</style>
