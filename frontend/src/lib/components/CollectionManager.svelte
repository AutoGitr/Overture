<script lang="ts">
  import Layers from "@lucide/svelte/icons/layers";
  import { SERVER_DISPLAY_NAMES } from "../../generated/settings";
  import { uiState } from "../stores/uiState.svelte";
  import type { CollectionDetail, MediaItemRead } from "../../generated/rest/types.gen";
  import { CollectionEditor } from "../utils/collectionForms.svelte";
  import {
    goToCollectionView,
    routedCollectionView,
    routedCollectionArtType,
    type CollectionView,
  } from "../router/routes";
  import CollectionThemePanel from "./CollectionThemePanel.svelte";
  import CollectionMembers from "./CollectionMembers.svelte";
  import CollectionSettingsDrawer from "./CollectionSettingsDrawer.svelte";
  import CollectionRulePanel from "./CollectionRulePanel.svelte";
  import ArtSlotPanel from "./ArtSlotPanel.svelte";
  import DetailPanelBase from "./DetailPanelBase.svelte";
  import CollectionMatchPanel from "./CollectionMatchPanel.svelte";
  import ExternalLinkBadges from "./ExternalLinkBadges.svelte";
  import IdBadge from "./IdBadge.svelte";
  import { collectionImageUrl } from "../utils/artDisplay";
  import { goToCatalogEntry } from "../router/routes";
  let {
    collection,
    libraryItems,
  }: { collection: CollectionDetail; libraryItems: MediaItemRead[] } = $props();
  const editor = new CollectionEditor(() => collection);
  let view = $derived(routedCollectionView());
  const tabs: { view: CollectionView; title: string }[] = [
    { view: "members", title: "Members" },
    { view: "art", title: "Art" },
    { view: "themes", title: "Themes" },
    { view: "rule", title: "Rule / Sync" },
    { view: "settings", title: "Settings" },
  ];
</script>

<div class="collection-manager">
  <nav aria-label="Collection views" class="collection-tabs">
    {#each tabs as { view: tab, title } (tab)}
      <button
        class={["btn btn-ghost", { active: view === tab }]}
        aria-current={view === tab ? "page" : undefined}
        onclick={() => goToCollectionView(collection, tab)}
        >{title}{#if tab === "themes" && collection.server_type === "emby"}<span
            class="badge badge-muted">Unsupported</span
          >{/if}</button
      >
    {/each}
  </nav>
  {#if view === "themes"}<CollectionThemePanel {collection} showMembers={false} />
  {:else}
    <DetailPanelBase
      emptyMessage="Select a collection from the sidebar"
      isEmpty={false}
      subjectKey={collection.id}
      title={collection.title}
      summary={collection.summary}
      posterUrl={collectionImageUrl(collection.thumb_url)}
      backgroundUrl={collectionImageUrl(collection.art_url)}
      posterHref={collection.server_link}
      posterLinkTitle={collection.server_link
        ? `Open in ${SERVER_DISPLAY_NAMES[collection.server_type]}`
        : null}
    >
      {#snippet emptyIcon()}<Layers size={64} />{/snippet}
      {#snippet posterIcon()}<Layers size={48} />{/snippet}
      {#snippet tabs()}<button class="tab-item" onclick={() => uiState.openPopupByName("database")}
          >Database</button
        >{/snippet}
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
          mode="art"
          artType="poster"
          season={null}
        />
        {#if collection.catalog_entry_key}<IdBadge
            title="Open in OvertureDB"
            icon="/favicon.svg"
            alt="OvertureDB"
            onselect={() => {
              if (collection.catalog_entry_key)
                goToCatalogEntry({
                  media_type: "collection",
                  entry_key: collection.catalog_entry_key,
                });
            }}
          />{/if}
      {/snippet}
      {#snippet content()}
        {#if collection.media_type === "movie"}<CollectionMatchPanel {collection} />{/if}
        {#if view === "members"}<CollectionMembers
            members={collection.members}
            {editor}
            {libraryItems}
          />
        {:else if view === "settings"}<CollectionSettingsDrawer {editor} />
        {:else if view === "rule"}<CollectionRulePanel {editor} />
        {:else}
          <div class="form-row">
            <button class="btn" onclick={() => goToCollectionView(collection, "art", "poster")}
              >Poster</button
            >
            <button class="btn" onclick={() => goToCollectionView(collection, "art", "background")}
              >Background</button
            >
          </div>
          {#key `${collection.id}-${routedCollectionArtType()}`}
            <ArtSlotPanel
              slot={{
                kind: "collection",
                collectionId: collection.id,
                mediaType: collection.media_type,
              }}
              artType={routedCollectionArtType() === "background" ? "background" : "poster"}
              item={null}
            />
          {/key}
        {/if}
      {/snippet}
    </DetailPanelBase>
  {/if}
</div>

<style>
  .collection-manager {
    display: flex;
    flex-direction: column;
    min-width: 0;
    flex: 1;
    overflow: auto;
  }
  .collection-tabs {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
    padding: var(--space-3);
    border-bottom: var(--border-subtle);
  }
</style>
