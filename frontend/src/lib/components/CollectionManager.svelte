<script lang="ts">
  import { settingsState } from "../stores/settingsState.svelte";
  import { MEDIA_ICONS } from "../utils/mediaIcons";
  import Settings from "@lucide/svelte/icons/settings";
  import Unlink from "@lucide/svelte/icons/unlink";
  import Download from "@lucide/svelte/icons/download";
  import type {
    CollectionDetail,
    CollectionRead,
    MediaItemRead,
    LibrarySectionRead,
    TmdbCollectionResponse,
  } from "../../generated/rest/types.gen";
  import { createQuery } from "@tanstack/svelte-query";
  import { untrack } from "svelte";
  import { getCatalogCollectionIssueOptions } from "../../generated/rest/@tanstack/svelte-query.gen";
  import ContributeIssueLink from "./ContributeIssueLink.svelte";
  import DataStatus from "./DataStatus.svelte";
  import { CollectionDraft } from "../utils/collectionDraft.svelte";
  import { CollectionEditor } from "../utils/collectionEditor.svelte";
  import { CollectionActions } from "../utils/collectionActions.svelte";
  import { CollectionExport } from "../utils/collectionExport.svelte";
  import {
    goToCatalogEntry,
    goToCollectionView,
    groupHref,
    routedCollectionView,
    routedCollectionArtType,
  } from "../router/routes";
  import { statusTone } from "../utils/sidebarShared";
  import { deliveryNote, holdsSomething } from "../utils/assetDeliveries";
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
  import { configureSections, setSectionView } from "../stores/sectionState.svelte";

  const serverTitle = (serverId: number) => settingsState.serverTitle(serverId);

  let {
    collection,
    detail,
    libraryItems,
    groups,
    libraries,
    seed = null,
  }: {
    /** The collection shown, null while creating one; the sidebar's row until `detail` loads. */
    collection: CollectionRead | null;
    /** Its rule, members and themes, null while they load. */
    detail: CollectionDetail | null;
    seed?: TmdbCollectionResponse | null;
    libraryItems: MediaItemRead[];
    groups: string[];
    libraries: LibrarySectionRead[];
  } = $props();
  setSectionView(configureSections());
  const serverLinks = createServerLinks();
  // Copies come lead first; a withheld collection has none to open.
  let leadCopy = $derived(collection?.copies[0]);
  let serverLink = $derived(serverLinks.collection(leadCopy));

  function current(): CollectionRead {
    if (!collection) throw new Error("The saved collection must remain mounted");
    return collection;
  }
  // The page remounts this when adopting or orphaning changes whether Overture manages it.
  const unmanaged = untrack(() => !!collection && !collection.managed);
  const editor = unmanaged
    ? null
    : untrack(() => collection)
      ? new CollectionEditor(current, () => detail, () => libraries)
      : new CollectionDraft(
          () => libraries,
          () => seed,
        );
  const actions =
    editor instanceof CollectionEditor ? new CollectionActions(current) : null;
  const exporter = new CollectionExport();
  let view = $derived(routedCollectionView());
  let artType = $derived(routedCollectionArtType());
  let managing = $derived(!!editor && (editor.creating || view === "configure"));
  /** Until its details say which servers keep its theme, the configured servers decide. */
  let themeUnavailable = $derived(
    detail ? detail.theme_unavailable : settingsState.current.collection_themes_unavailable,
  );
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
      {#if collection.generated_value !== null && collection.collection_group}
        <a
          class="badge badge-muted set-link"
          href={groupHref(collection.collection_group)}
          title="Created and kept up to date by its group's set; open the group"
          >Set: {collection.collection_group}</a
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
      {#if detail?.catalog_entry_key && catalog.browsable}
        <IdBadge
          title="Open in OvertureDB"
          icon="/brand/overturedb-logo.svg"
          alt="OvertureDB"
          onselect={() => {
            if (detail.catalog_entry_key)
              goToCatalogEntry({
                media_type: "collection",
                entry_key: detail.catalog_entry_key,
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
            title="Export the collection as a file"
            aria-label="Export collection"
            disabled={exporter.busy}
            onclick={() => void exporter.run({ collection_ids: [collection.id] }, collection.title)}
          >
            <Download size={16} />
          </button>
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
    {#if detail && actions}<ConfigureNavigation
        {formId}
        configuring={managing}
        onopen={(target) => goToCollectionView(detail, "configure", "poster", target)}
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
      {#if editor instanceof CollectionDraft || detail}
        <CollectionConfigure
          collection={detail ?? undefined}
          {editor}
          {libraryItems}
          {groups}
          {formId}
          {libraries}
        />
      {/if}
    {:else if detail && actions && view === "themes"}
      <CollectionThemePanel collection={detail} {actions} />
    {:else if collection && view === "art"}
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
      themeStatus={themeUnavailable
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
      oncleartheme={!themeUnavailable && holdsSomething(collection.assets.theme)
        ? () => void actions.clearTheme()
        : null}
      artBusy={actions.clearingArt}
      themeBusy={actions.uploading}
    />{/if}
{/snippet}

<style>
  .set-link:hover {
    color: var(--accent-hover);
  }
</style>
