<script lang="ts">
  import Database from "@lucide/svelte/icons/database";
  import { createQuery } from "@tanstack/svelte-query";
  import type { Snippet } from "svelte";
  import { getCatalogItemIssueOptions } from "../../generated/rest/@tanstack/svelte-query.gen";
  import type { MediaItemRead, TmdbItemPreview } from "../../generated/rest/types.gen";
  import type { CatalogContext } from "../utils/catalogDraft";
  import { createSeasonsQuery, createServerLinks } from "../rest/queries";
  import {
    goToItemView,
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
  import { MEDIA_ICONS } from "../utils/mediaIcons";
  import { CatalogBrowsing } from "../utils/catalogBrowsing.svelte";
  import { ItemRecordActions } from "../utils/itemRecordActions.svelte";
  import { catalogStatus, hasThemeAttributes, statusTone } from "../utils/sidebarDomain";
  import CollectionBadge from "./CollectionBadge.svelte";
  import ContributeIssueLink from "./ContributeIssueLink.svelte";
  import ArtPanel from "./ArtPanel.svelte";
  import ArtCategoryTabs, { ART_TABS } from "./ArtCategoryTabs.svelte";
  import DetailRecordActions from "./DetailRecordActions.svelte";
  import DetailPanelBase from "./DetailPanelBase.svelte";
  import IdBadge from "./IdBadge.svelte";
  import ExternalLinkBadges from "./ExternalLinkBadges.svelte";
  import PasteArtButton from "./PasteArtButton.svelte";
  import UploadArtButton from "./UploadArtButton.svelte";
  import SeasonGrid from "./SeasonGrid.svelte";
  import AssetModeTabs from "./AssetModeTabs.svelte";
  import ThemePanel from "./ThemePanel.svelte";

  let {
    item = null,
    preview = null,
    catalog = null,
    members,
    emptyMessage,
    view = { mode: "art", artSubTab: "poster", drillSeasonNum: null },
  }: {
    item?: MediaItemRead | null;
    /** A TMDB title open before its first selection stores it as an item. */
    preview?: TmdbItemPreview | null;
    catalog?: CatalogContext | null;
    members?: Snippet;
    emptyMessage?: string;
    view?: ItemView;
  } = $props();

  const catalogBrowsing = new CatalogBrowsing();

  const actions = new ItemRecordActions(() => item);
  const itemIssue = createQuery(() => ({
    ...getCatalogItemIssueOptions({ path: { item_id: item?.id ?? 0 } }),
    enabled: !!item && catalogBrowsing.enabled,
  }));
  let detail = $derived(catalog?.detail);
  let catalogEntry = $derived(catalog?.entry);
  let catalogTones = $derived(catalogEntry ? catalogStatus(catalogEntry) : null);
  let subject = $derived(item ?? preview ?? catalogEntry ?? null);
  let artType = $derived(viewArtType(view));
  const seasonsQuery = createSeasonsQuery(() => item);
  const serverLinks = createServerLinks();
  // A title the server dropped has no copy there to open.
  let serverLink = $derived(
    item && !item.server_removed_at ? serverLinks.item(item.server_item_id) : null,
  );
  let seasons = $derived(seasonsQuery.data ?? []);
  let drillSeason = $derived(
    view.drillSeasonNum === null ? null : { season_num: view.drillSeasonNum },
  );
  /** Which art tabs hold something to remove: a selection, or a library title's local file. */
  // A library selection is a link or an upload; a catalog entry's is always a link.
  let savedArt = $derived(
    catalogEntry
      ? {
          poster: !!catalogEntry.poster_url,
          background: !!catalogEntry.background_url,
          seasons: (catalogEntry.seasons ?? []).some((season) => !!season.poster_url),
        }
      : {
          poster: !!(item?.poster_source || item?.poster_hash),
          background: !!(item?.background_source || item?.background_hash),
          seasons: seasons.some((season) => !!(season.poster_source || season.poster_hash)),
        },
  );

  let artStatuses = $derived(
    Object.fromEntries(
      ART_TABS.map((tab) => [
        tab.key,
        catalogTones?.[tab.key] ??
          statusTone(
            item?.[tab.statusField] ?? "missing",
            !!item && downloadState.isDownloadingType(item.id, "art", tab.artType),
          ),
      ]),
    ),
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
    detail
      ? `catalog:${detail.entry.media_type}:${detail.entry_key}`
      : item
        ? `item:${item.id}`
        : preview
          ? `tmdb:${preview.media_type}:${preview.tmdb_id}`
          : null,
  );

  function selectView(next: ItemView) {
    if (catalog) goToCatalogEntry(catalog.target, next);
    else {
      const title = item ?? preview;
      if (title) goToItemView(title, next);
    }
  }

  function clearArt(tab: ArtSubTab | "all") {
    if (!catalog)
      return tab === "all"
        ? actions.clearAllArt()
        : actions.clearArt(
            tab,
            tab === "seasons"
              ? (seasons.find((season) => season.season_num === view.drillSeasonNum)?.id ?? null)
              : null,
          );
    void catalog.draft.save(
      tab === "all"
        ? { poster_url: null, background_url: null, seasons: [] }
        : tab === "seasons"
          ? {
              seasons:
                view.drillSeasonNum === null
                  ? []
                  : (catalog.entry.seasons ?? []).filter(
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
      });
  }
</script>

<DetailPanelBase
  isEmpty={!subject}
  {subjectKey}
  recordActions={item || catalog ? recordActions : undefined}
  {backgroundUrl}
  posterHref={serverLink}
  posterLinkTitle={serverLink ? `Open in ${settingsState.media_server_name}` : null}
  emptyMessage={emptyMessage ??
    `Select a ${
      uiState.sidebarMode === "collections"
        ? "collection"
        : uiState.sidebarTab === "movie"
          ? "movie"
          : "show"
    } from the sidebar`}
  {posterUrl}
  title={subject?.title ?? ""}
>
  {#snippet emptyIcon()}
    {@const Icon =
      MEDIA_ICONS[uiState.sidebarMode === "collections" ? "collection" : uiState.sidebarTab]}
    <Icon size={64} />
  {/snippet}

  {#snippet posterIcon()}
    {@const Icon = MEDIA_ICONS[subject?.media_type ?? "collection"]}
    <Icon size={48} />
  {/snippet}

  {#snippet meta()}
    {#if subject?.year}
      <span>{subject.year}</span>
    {/if}
    {#if detail?.draft}<span class="badge badge-warning">Draft</span>{/if}
  {/snippet}

  {#snippet badges()}
    <ExternalLinkBadges {subject} mode={view.mode} {artType} season={drillSeason} />
    {#if item?.catalog_entry_key && catalogBrowsing.browsable}
      {@const entryKey = item.catalog_entry_key}
      <IdBadge
        title="Open in OvertureDB"
        icon="/brand/overturedb-logo.svg"
        alt="OvertureDB"
        onselect={() => goToCatalogEntry({ media_type: item.media_type, entry_key: entryKey }, view)}
      />
    {/if}
    {#if detail?.library_item_id || detail?.library_collection_id}
      <IdBadge
        title="Open in library"
        icon="/brand/overture-logo.svg"
        alt="Open in library"
        onselect={openLibrary}
      />
    {/if}
    {#if item?.tmdb_collection_id}
      <CollectionBadge
        tmdbId={item.tmdb_collection_id}
        libraryCollectionId={item.library_collection_id}
        catalogEnabled={catalogBrowsing.enabled}
      />
    {/if}
    <ContributeIssueLink issue={detail ? detail.draft_issue : item ? itemIssue.data : null} />
    {#if detail?.draft}<button
        class="btn btn-ghost btn-sm"
        disabled={catalog?.draft.busy}
        onclick={() => catalog?.draft.discard()}>Discard draft</button
      >{/if}
  {/snippet}

  {#snippet tabs()}
    <AssetModeTabs
      mode={view.mode}
      artStatus={catalogTones?.art ??
        statusTone(
          item?.art_status ?? "missing",
          !!item && downloadState.isDownloadingType(item.id, "art"),
        )}
      themeStatus={catalogTones?.theme ??
        statusTone(
          item?.theme_status ?? "missing",
          !!item && downloadState.isDownloadingType(item.id, "theme"),
        )}
      onart={() => selectView({ mode: "art", artSubTab: "poster", drillSeasonNum: null })}
      onthemes={() => selectView({ mode: "themes", artSubTab: "poster", drillSeasonNum: null })}
      onclearart={Object.values(savedArt).some(Boolean) ? () => clearArt("all") : null}
      oncleartheme={catalogEntry?.youtube_id_overturedb
        ? () => {
            void catalog?.draft.save({ youtube_id_overturedb: null });
          }
        : hasThemeAttributes(item) || item?.theme_file_hash
          ? () => void actions.clearTheme()
          : null}
      artBusy={!!catalog?.draft.busy || actions.clearingArt}
      themeBusy={!!catalog?.draft.busy || actions.themeBusy}
    />
  {/snippet}

  {#snippet subtabs()}
    <ArtCategoryTabs
      active={view.mode === "art" ? view.artSubTab : null}
      seasons={subject?.media_type === "show"}
      statuses={artStatuses}
      clearable={savedArt}
      clearDisabled={catalog?.draft.busy || actions.clearingArt}
      clearSeason={view.mode === "art" && view.drillSeasonNum !== null}
      onselect={(tab) => selectView({ mode: "art", artSubTab: tab, drillSeasonNum: null })}
      onclear={clearArt}
    />
  {/snippet}

  {#snippet subtabActions()}<PasteArtButton /><UploadArtButton />{/snippet}

  {#snippet content()}
    {#if view.mode === "art"}
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

{#snippet recordActions()}
  {#if item}
    <DetailRecordActions
      monitored={item.monitored}
      monitoring={actions.monitoring}
      deleting={actions.deleting}
      deleteLabel="Delete item from database"
      ontoggle={() => void actions.toggleMonitored()}
      ondelete={() => void actions.delete()}
    />
  {:else if catalog}
    <button
      type="button"
      class="tab-item"
      onclick={() => uiState.openPopupByName("database")}
      title="Open database record"
    >
      <Database size={16} />
    </button>
  {/if}
{/snippet}
