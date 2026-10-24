<script lang="ts">
  import Layers from "@lucide/svelte/icons/layers";
  import Image from "@lucide/svelte/icons/image";
  import Music from "@lucide/svelte/icons/music";
  import Users from "@lucide/svelte/icons/users";
  import RefreshCw from "@lucide/svelte/icons/refresh-cw";
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
  import CollectionMembers from "./CollectionMembers.svelte";
  import CollectionSettings from "./CollectionSettings.svelte";
  import CollectionRulePanel from "./CollectionRulePanel.svelte";
  import ArtSlotPanel from "./ArtSlotPanel.svelte";
  import ArtCategoryTabs from "./ArtCategoryTabs.svelte";
  import PasteArtButton from "./PasteArtButton.svelte";
  import DetailPanelBase from "./DetailPanelBase.svelte";
  import DetailRecordActions from "./DetailRecordActions.svelte";
  import CollectionMatchPanel from "./CollectionMatchPanel.svelte";
  import ExternalLinkBadges from "./ExternalLinkBadges.svelte";
  import IdBadge from "./IdBadge.svelte";
  import StatusTab from "./StatusTab.svelte";
  import { collectionImageUrl } from "../utils/artDisplay";

  let {
    collection,
    libraryItems,
  }: { collection: CollectionDetail; libraryItems: MediaItemRead[] } = $props();

  const editor = new CollectionEditor(() => collection);
  const actions = new CollectionActions(() => collection);
  let view = $derived(routedCollectionView());
  let artType = $derived(routedCollectionArtType());
  let managing = $derived(view === "members" || view === "rule" || view === "settings");
  const managementTabs = [
    { key: "members", label: "Members", icon: Users },
    { key: "rule", label: "Rule / Sync", icon: RefreshCw },
    { key: "settings", label: "Settings", icon: Settings },
  ] as const;
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
  subtabLabel={managing ? "Collection sections" : "Art categories"}
  showSubtabs={view !== "themes"}
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
      icon={Layers}
      label="Collection"
      active={managing}
      onselect={() => goToCollectionView(collection, "members")}
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
      clearLabel="Clear theme"
      onclear={!collection.theme_unavailable && collection.theme_status !== "missing"
        ? () => void actions.clearTheme()
        : null}
      clearDisabled={actions.uploading}
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
      {#each managementTabs as tab (tab.key)}
        <StatusTab
          icon={tab.icon}
          label={tab.label}
          active={view === tab.key}
          onselect={() => goToCollectionView(collection, tab.key)}
        />
      {/each}
    {:else}
      <ArtCategoryTabs
        active={artType}
        onselect={(tab) => {
          if (tab === "poster" || tab === "background") goToCollectionView(collection, "art", tab);
        }}
      />
    {/if}
  {/snippet}
  {#snippet subtabActions()}{#if view === "art"}<PasteArtButton />{/if}{/snippet}
  {#snippet content()}
    {#if view === "members"}
      <CollectionMembers members={collection.members} {editor} {libraryItems} />
    {:else if view === "settings"}
      <CollectionSettings {editor} />
      {#if collection.media_type === "movie"}<CollectionMatchPanel {collection} />{/if}
    {:else if view === "rule"}
      <CollectionRulePanel {editor} />
    {:else if view === "themes"}
      <CollectionThemePanel {collection} {actions} />
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
