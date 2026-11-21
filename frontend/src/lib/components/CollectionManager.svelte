<script lang="ts">
  import { settingsState } from "../stores/settingsState.svelte";
  import { MEDIA_ICONS } from "../utils/mediaIcons";
  import Settings from "@lucide/svelte/icons/settings";
  import Unlink from "@lucide/svelte/icons/unlink";
  import type {
    CollectionDetail,
    MediaItemRead,
    LibrarySectionRead,
    TmdbCollectionResponse,
  } from "../../generated/rest/types.gen";
  import { createQuery } from "@tanstack/svelte-query";
  import { untrack } from "svelte";
  import { getCatalogCollectionIssueOptions } from "../../generated/rest/@tanstack/svelte-query.gen";
  import ContributeIssueLink from "./ContributeIssueLink.svelte";
  import DataStatus from "./DataStatus.svelte";
  import { CollectionDraft, CollectionEditor } from "../utils/collectionForms.svelte";
  import { CollectionActions } from "../utils/collectionActions.svelte";
  import {
    goToCatalogEntry,
    goToCollectionView,
    routedCollectionView,
    routedCollectionArtType,
  } from "../router/routes";
  import { statusTone } from "../utils/sidebarDomain";
  import { deliveryNote } from "../utils/assetDeliveries";
  import CollectionThemePanel from "./CollectionThemePanel.svelte";
  import ConfigureNavigation from "./ConfigureNavigation.svelte";
  import CollectionConfigure from "./CollectionConfigure.svelte";
  import CollectionAdopt from "./CollectionAdopt.svelte";
  import ArtSlotPanel from "./ArtSlotPanel.svelte";
  import ArtCategoryTabs from "./ArtCategoryTabs.svelte";
  import PasteArtButton from "./PasteArtButton.svelte";
  import UploadArtButton from "./UploadArtButton.svelte";
  import DetailPanelBase from "./DetailPanelBase.svelte";
  import DetailRecordActions from "./DetailRecordActions.svelte";
  import ExternalLinkBadges from "./ExternalLinkBadges.svelte";
  import IdBadge from "./IdBadge.svelte";
  import StatusTab from "./StatusTab.svelte";
  import AssetModeTabs from "./AssetModeTabs.svelte";
  import { collectionArtDisplayUrl } from "../utils/artDisplay";
  import { CatalogBrowsing } from "../utils/catalogBrowsing.svelte";
  import { createServerLinks } from "../rest/queries";
  import { setSectionView } from "../stores/sectionState.svelte";

  const serverTitle = (serverId: number) => settingsState.serverTitle(serverId);

  let {
    collection,
    libraryItems,
    groups,
    libraries,
    seed = null,
  }: {
    collection: CollectionDetail | null;
    seed?: TmdbCollectionResponse | null;
    libraryItems: MediaItemRead[];
    groups: string[];
    libraries: LibrarySectionRead[];
  } = $props();
  setSectionView("collection");
  const serverLinks = createServerLinks();
  // Copies come lead first; a withheld collection has none to open.
  let leadCopy = $derived(collection?.copies[0]);
  let serverLink = $derived(serverLinks.collection(leadCopy));

  function currentCollection(): CollectionDetail {
    if (!collection) throw new Error("The saved collection must remain mounted");
    return collection;
  }
  // The page remounts this when adopting or orphaning changes whether Overture manages it.
  const unmanaged = untrack(() => !!collection && !collection.managed);
  const editor = unmanaged
    ? null
    : untrack(() => collection)
      ? new CollectionEditor(currentCollection, () => libraries)
      : new CollectionDraft(
          () => libraries,
          () => seed,
        );
  const actions =
    editor instanceof CollectionEditor ? new CollectionActions(currentCollection) : null;
  let view = $derived(routedCollectionView());
  let artType = $derived(routedCollectionArtType());
  let managing = $derived(!!editor && (editor.creating || view === "configure"));
  const catalog = new CatalogBrowsing();
  const collectionIssue = createQuery(() => ({
    ...getCatalogCollectionIssueOptions({ path: { collection_id: collection?.id ?? 0 } }),
    enabled: !!collection?.tmdb_collection_id && catalog.enabled,
  }));
  const panelId = $props.id();
  const formId = `${panelId}-configure`;
</script>

<DetailPanelBase
  emptyMessage="Select a collection from the sidebar"
  isEmpty={false}
  subjectKey={collection ? `collection:${collection.id}` : "new-collection"}
  title={collection?.title ?? "New collection"}
  summary={collection?.summary}
  posterUrl={collectionArtDisplayUrl(collection, "poster")}
  showPoster={!!collection}
  backgroundUrl={collectionArtDisplayUrl(collection, "background")}
  posterHref={serverLink}
  posterLinkTitle={serverLink && leadCopy
    ? `Open in ${settingsState.server(leadCopy.server_id)?.title ?? "the media server"}`
    : null}
  tabs={collection && actions ? tabs : undefined}
>
  {#snippet emptyIcon()}<MEDIA_ICONS.collection size={64} />{/snippet}
  {#snippet posterIcon()}<MEDIA_ICONS.collection size={48} />{/snippet}
  {#snippet meta()}
    {#if collection}
      <span>{collection.child_count} items</span>
      {#if collection.kind === "smart"}
        <span class="badge badge-accent">Smart</span>
      {/if}
      {#if collection.generated_value !== null}
        <span class="badge badge-muted" title="Created and kept up to date by its group's set"
          >Set: {collection.collection_group}</span
        >
      {/if}
      {#if collection.withheld}
        <span class="badge badge-warning" title="Saved in Overture only">Not on server</span>
      {/if}
      {#if collection.unsynced}
        <span class="badge badge-warning" title="Saved changes the server does not have yet"
          >Unsynced</span
        >
      {/if}
    {/if}
  {/snippet}
  {#snippet badges()}
    {#if collection}
      <ExternalLinkBadges
        subject={{
          title: collection.title,
          year: null,
          media_type: "collection",
          tmdb_id: collection.tmdb_collection_id,
          tvdb_id: null,
          imdb_id: null,
        }}
        mode={view === "themes" ? "themes" : "art"}
        artType={view === "art" ? artType : "poster"}
        season={null}
      />
      {#if collection.catalog_entry_key && catalog.browsable}
        <IdBadge
          title="Open in OvertureDB"
          icon="/brand/overturedb-logo.svg"
          alt="OvertureDB"
          onselect={() => {
            if (collection.catalog_entry_key)
              goToCatalogEntry({
                media_type: "collection",
                entry_key: collection.catalog_entry_key,
              });
          }}
        />
      {/if}
      <ContributeIssueLink issue={collectionIssue.data} />
    {/if}
  {/snippet}
  {#snippet recordActions()}
    {#if collection && actions && editor instanceof CollectionEditor}
      <DetailRecordActions
        monitored={collection.monitored}
        monitoring={actions.monitoring}
        deleting={editor.busy || actions.uploading}
        deleteLabel="Delete collection"
        deleteBlocker={editor.deleteBlocker}
        ontoggle={() => void actions.toggleMonitored()}
        ondelete={() => void editor.delete()}
      >
        {#snippet beforeDelete()}
          <button
            type="button"
            class="tab-item"
            title={editor.orphanBlocker ?? "Orphan collection: stop managing it, keeping it on the server"}
            aria-label="Orphan collection"
            disabled={editor.busy || !!editor.orphanBlocker}
            onclick={() => void editor.orphan()}
          >
            <Unlink size={16} />
          </button>
        {/snippet}
      </DetailRecordActions>
    {/if}
  {/snippet}
  {#snippet subtabs()}
    {#if collection && actions}
      <ArtCategoryTabs
        active={view === "art" ? artType : null}
        statuses={{
          poster: statusTone(collection.assets.poster.status, actions.clearingArt),
          background: statusTone(collection.assets.background.status, actions.clearingArt),
        }}
        notes={{
          poster: deliveryNote(collection.assets.poster, serverTitle),
          background: deliveryNote(collection.assets.background, serverTitle),
        }}
        clearable={{
          poster: !!(collection.assets.poster.source || collection.server_poster_version),
          background: !!(collection.assets.background.source || collection.server_background_version),
        }}
        clearDisabled={actions.clearingArt}
        onclear={(tab) => {
          if (tab !== "seasons") void actions.clearArt(tab);
        }}
        onselect={(tab) => {
          if (tab === "poster" || tab === "background") goToCollectionView(collection, "art", tab);
        }}
      />
    {/if}
  {/snippet}
  {#snippet sectionLinks()}
    {#if collection && actions}<ConfigureNavigation
        {formId}
        {collection}
        configuring={managing}
      />{/if}
  {/snippet}
  {#snippet subtabActions()}{#if actions && view === "art"}<PasteArtButton /><UploadArtButton />{/if}{/snippet}
  {#snippet content()}
    {#if collection && !editor}
      <CollectionAdopt {collection} {groups} />
    {:else if managing && editor}
      {#if editor instanceof CollectionDraft && editor.request.error}<DataStatus
          label="collection creation"
          error={editor.request.error}
          loading={false}
          hasData={false}
          onretry={() => editor.save()}
        />{/if}
      <CollectionConfigure
        collection={collection ?? undefined}
        {editor}
        {libraryItems}
        {groups}
        {formId}
        {libraries}
      />
    {:else if collection && actions && view === "themes"}
      <CollectionThemePanel {collection} {actions} />
    {:else if collection}
      {#key `${collection.id}-${artType}`}
        <ArtSlotPanel
          slot={{
            kind: "collection",
            collectionId: collection.id,
            tmdbId: collection.tmdb_collection_id,
            contributedStyle: collection.contributed_style,
          }}
          {artType}
          item={null}
        />
      {/key}
    {/if}
  {/snippet}
</DetailPanelBase>

{#snippet tabs()}
  <StatusTab
    icon={Settings}
    label="Configure"
    active={managing}
    onselect={() => {
      if (collection) goToCollectionView(collection, "configure");
    }}
  />
  {#if collection && actions}<AssetModeTabs
      mode={view}
      artStatus={statusTone(collection.art_status, actions.clearingArt)}
      themeStatus={collection.theme_unavailable
        ? null
        : statusTone(collection.assets.theme.status, actions.themeBusy)}
      onart={() => goToCollectionView(collection, "art", artType)}
      onthemes={() => goToCollectionView(collection, "themes")}
      onclearart={collection.assets.poster.source ||
      collection.assets.background.source ||
      collection.server_poster_version ||
      collection.server_background_version
        ? () => void actions.clearArt("all")
        : null}
      oncleartheme={!collection.theme_unavailable && collection.assets.theme.status !== "missing"
        ? () => void actions.clearTheme()
        : null}
      artBusy={actions.clearingArt}
      themeBusy={actions.uploading}
    />{/if}
{/snippet}
