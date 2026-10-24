<script lang="ts">
  import Layers from "@lucide/svelte/icons/layers";
  import Image from "@lucide/svelte/icons/image";
  import Music from "@lucide/svelte/icons/music";
  import Settings from "@lucide/svelte/icons/settings";
  import githubIcon from "../../assets/icons/github.svg";
  import { SERVER_DISPLAY_NAMES } from "../../generated/settings";
  import type { CollectionDetail, MediaItemRead } from "../../generated/rest/types.gen";
  import { CollectionEditor } from "../utils/collectionForms.svelte";
  import { CollectionActions } from "../utils/collectionActions.svelte";
  import {
    goToCatalogEntry,
    goToCollectionView,
    routedCollectionView,
    routedCollectionArtType,
  } from "../router/routes";
  import { statusTone } from "../utils/sidebarDomain";
  import CollectionThemePanel from "./CollectionThemePanel.svelte";
  import CollectionConfigure from "./CollectionConfigure.svelte";
  import ThemeStatus from "./ThemeStatus.svelte";
  import ThemeActions from "./ThemeActions.svelte";
  import ArtSlotPanel from "./ArtSlotPanel.svelte";
  import ArtCategoryTabs from "./ArtCategoryTabs.svelte";
  import PasteArtButton from "./PasteArtButton.svelte";
  import DetailPanelBase from "./DetailPanelBase.svelte";
  import DetailRecordActions from "./DetailRecordActions.svelte";
  import ExternalLinkBadges from "./ExternalLinkBadges.svelte";
  import IdBadge from "./IdBadge.svelte";
  import StatusTab from "./StatusTab.svelte";
  import { collectionImageUrl } from "../utils/artDisplay";

  let {
    collection,
    libraryItems,
    groups,
  }: { collection: CollectionDetail; libraryItems: MediaItemRead[]; groups: string[] } = $props();

  const editor = new CollectionEditor(() => collection);
  const actions = new CollectionActions(() => collection);
  let view = $derived(routedCollectionView());
  let artType = $derived(routedCollectionArtType());
  let managing = $derived(view === "configure");
  const panelId = $props.id();
  const formId = `${panelId}-configure`;
  const themeInputId = `${panelId}-theme-search`;
</script>

<DetailPanelBase
  emptyMessage="Select a collection from the sidebar"
  isEmpty={false}
  subjectKey={`collection:${collection.id}`}
  title={collection.title}
  summary={collection.summary}
  posterUrl={collectionImageUrl(collection.thumb_url)}
  backgroundUrl={collectionImageUrl(collection.art_url)}
  posterHref={collection.server_link}
  posterLinkTitle={collection.server_link
    ? `Open in ${SERVER_DISPLAY_NAMES[collection.server_type]}`
    : null}
  subtabLabel={managing
    ? "Configure navigation"
    : view === "themes"
      ? "Theme status"
      : "Art categories"}
  subtabRole={view === "art" ? "tablist" : "group"}
>
  {#snippet emptyIcon()}<Layers size={64} />{/snippet}
  {#snippet posterIcon()}<Layers size={48} />{/snippet}
  {#snippet meta()}<span>{collection.child_count} items</span>{/snippet}
  {#snippet badges()}
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
    {#if collection.catalog_entry_key}
      <IdBadge
        title="Open in OvertureDB"
        icon="/favicon.svg"
        alt="OvertureDB"
        onselect={() => {
          if (collection.catalog_entry_key)
            goToCatalogEntry({ media_type: "collection", entry_key: collection.catalog_entry_key });
        }}
      />
    {/if}
    {#if actions.contributionUrl}
      <IdBadge
        href={actions.contributionUrl}
        title="Contribute to OvertureDB"
        icon={githubIcon}
        alt="GitHub"
      />
    {/if}
  {/snippet}
  {#snippet tabs()}
    <StatusTab
      icon={Settings}
      label="Configure"
      active={managing}
      onselect={() => goToCollectionView(collection, "configure")}
    />
    <StatusTab
      icon={Image}
      label="Art"
      active={view === "art"}
      onselect={() => goToCollectionView(collection, "art", artType)}
    />
    <StatusTab
      icon={Music}
      label="Themes"
      active={view === "themes"}
      status={collection.theme_unavailable
        ? null
        : statusTone(collection.theme_status, actions.themeBusy)}
      onselect={() => goToCollectionView(collection, "themes")}
    />
  {/snippet}
  {#snippet recordActions()}
    <DetailRecordActions
      monitored={collection.monitored}
      monitoring={actions.monitoring}
      deleting={editor.busy || actions.uploading}
      deleteLabel="Delete collection"
      ontoggle={() => void actions.toggleMonitored()}
      ondelete={() => void editor.delete()}
    />
  {/snippet}
  {#snippet subtabs()}
    {#if managing}
      <span class="text-muted">Jump:</span>
      {#each ["General", "Builder", "Members"] as section (section)}
        <a class="tab-item" href={`#${formId}-${section.toLowerCase()}`}>{section}</a>
      {/each}
    {:else if view === "themes"}
      <ThemeStatus
        status={collection.theme_status}
        duration={collection.theme_duration}
        title={collection.youtube_title}
        unavailable={collection.theme_unavailable}
      />
    {:else}
      <ArtCategoryTabs
        active={artType}
        onselect={(tab) => {
          if (tab === "poster" || tab === "background") goToCollectionView(collection, "art", tab);
        }}
      />
    {/if}
  {/snippet}
  {#snippet subtabActions()}
    {#if managing}
      <button class="tab-item" type="submit" form={formId} disabled={editor.busy}
        >Save Changes</button
      >
      <button
        class="tab-item"
        type="button"
        disabled={editor.busy || !collection.rule}
        onclick={() => void editor.sync()}>Sync Now</button
      >
    {:else if view === "art"}<PasteArtButton />
    {:else}
      <ThemeActions
        inputId={themeInputId}
        disabled={!!collection.theme_unavailable || actions.uploading}
        clearDisabled={collection.theme_status === "missing"}
        onclear={() => void actions.clearTheme()}
      />
    {/if}
  {/snippet}
  {#snippet content()}
    {#if managing}
      <CollectionConfigure {collection} {editor} {libraryItems} {groups} {formId} />
    {:else if view === "themes"}
      <CollectionThemePanel {collection} {actions} searchInputId={themeInputId} />
    {:else}
      {#key `${collection.id}-${artType}`}
        <ArtSlotPanel
          slot={{
            kind: "collection",
            collectionId: collection.id,
            mediaType: collection.media_type,
          }}
          {artType}
          item={null}
        />
      {/key}
    {/if}
  {/snippet}
</DetailPanelBase>
