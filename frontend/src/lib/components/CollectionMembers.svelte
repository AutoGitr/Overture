<script lang="ts">
  import ArrowUp from "@lucide/svelte/icons/arrow-up";
  import ArrowDown from "@lucide/svelte/icons/arrow-down";
  import GripVertical from "@lucide/svelte/icons/grip-vertical";
  import X from "@lucide/svelte/icons/x";
  import Film from "@lucide/svelte/icons/film";
  import DetailSection from "./DetailSection.svelte";
  import FallbackImage from "./FallbackImage.svelte";
  import type { MediaItemRead, TmdbItemResult } from "../../generated/rest/types.gen";
  import { goToCatalogEntry, goToItem } from "../router/routes";
  import { itemArtDisplayUrl, remotePosterUrl } from "../utils/artDisplay";
  import type { CollectionEditor } from "../utils/collectionForms.svelte";
  import ImageGrid from "./ImageGrid.svelte";
  import PosterCard from "./PosterCard.svelte";

  let {
    members,
    catalog = false,
    editor,
    libraryItems = [],
  }: {
    members: (MediaItemRead | TmdbItemResult)[];
    catalog?: boolean;
    editor?: CollectionEditor;
    libraryItems?: MediaItemRead[];
  } = $props();

  let search = $state("");
  let dragging = $state<number | null>(null);

  let memberIdSet = $derived<ReadonlySet<number>>(
    new Set(editor?.collection.members.map((member) => member.id) ?? []),
  );

  let available = $derived.by(() => {
    const query = search.trim().toLowerCase();
    if (!query || !editor) return [];

    return libraryItems.filter(
      (item) =>
        item.library_id === editor.collection.library_id &&
        item.server_item_id &&
        !item.server_removed_at &&
        !memberIdSet.has(item.id) &&
        item.title.toLowerCase().includes(query),
    );
  });

  function open(member: MediaItemRead | TmdbItemResult) {
    if (catalog && "catalog_entry_key" in member && member.catalog_entry_key) {
      goToCatalogEntry({ media_type: member.media_type, entry_key: member.catalog_entry_key });
      return;
    }
    const id = "id" in member ? member.id : member.existing_item_id;
    if (id) void goToItem({ id, title: member.title, media_type: member.media_type });
    else if (member.tmdb_id)
      void goToItem({
        tmdb_id: member.tmdb_id,
        title: member.title,
        media_type: member.media_type,
      });
  }
</script>

<section aria-label="Collection members">
  {#if editor}
    {@const currentMembers = editor.collection.members}
    <DetailSection
      title="Members"
      description={editor.collection.server_type === "plex"
        ? "Add library items, choose an order, or drag members into place."
        : "Add or remove library items and choose their display order."}
    >
      <div class="member-toolbar">
        <label class="form-label">
          Add item
          <input type="search" placeholder="Search library" bind:value={search} />
        </label>
        <label class="form-label">
          Sort members
          <select
            value={editor.collection.order_type}
            disabled={editor.busy}
            onchange={(event) => {
              const order = event.currentTarget.value;
              if (order === "release" || order === "alpha" || order === "custom")
                void editor.setMembers(
                  currentMembers.map((member) => member.id),
                  order,
                );
            }}
          >
            <option value="release">Release date</option>
            <option value="alpha">Alphabetical</option>
            {#if editor.collection.server_type === "plex"}
              <option value="custom">Custom</option>
            {/if}
          </select>
        </label>
      </div>
      {#if search.trim()}
        {#each available.slice(0, 20) as item (item.id)}
          <button
            type="button"
            class="btn btn-ghost"
            disabled={editor.busy}
            onclick={() => void editor.addMember(item.id)}
          >
            Add {item.title}
            {item.year ? `(${item.year})` : ""}
          </button>
        {/each}
        {#if !available.length}<p class="text-muted">No matching library items.</p>{/if}
      {/if}

      {#if currentMembers.length}
        <ol class="member-list">
          {#each currentMembers as member, index (member.id)}
            <li
              class="member-row"
              ondragover={(event) => {
                if (editor.collection.server_type === "plex") event.preventDefault();
              }}
              ondrop={(event) => {
                if (editor.collection.server_type !== "plex") return;
                event.preventDefault();
                if (dragging !== null && dragging !== member.id) {
                  void editor.moveMember(dragging, index);
                }
                dragging = null;
              }}
            >
              {#if editor.collection.server_type === "plex"}
                <button
                  type="button"
                  class="btn btn-ghost btn-icon drag-handle"
                  draggable={!editor.busy}
                  aria-label={`Drag ${member.title} to reorder`}
                  disabled={editor.busy}
                  ondragstart={(event) => {
                    dragging = member.id;
                    if (event.dataTransfer) {
                      event.dataTransfer.effectAllowed = "move";
                      event.dataTransfer.setData("text/plain", String(member.id));
                    }
                  }}
                  ondragend={() => (dragging = null)}><GripVertical size={16} /></button
                >
              {/if}
              <button type="button" class="btn btn-ghost member-title" onclick={() => open(member)}>
                <span class="member-poster"
                  ><FallbackImage
                    src={itemArtDisplayUrl(member, "poster")}
                    alt=""
                    placeholder={memberPlaceholder}
                  /></span
                >
                <span class="member-name">
                  {member.title}
                  {member.year ? `(${member.year})` : ""}
                </span>
              </button>
              <div class="member-actions">
                {#if editor.collection.server_type === "plex"}
                  <button
                    type="button"
                    class="btn btn-ghost btn-icon"
                    aria-label={`Move ${member.title} up`}
                    disabled={editor.busy || index === 0}
                    onclick={() => void editor.moveMember(member.id, index - 1)}
                    ><ArrowUp size={16} /></button
                  >
                  <button
                    type="button"
                    class="btn btn-ghost btn-icon"
                    aria-label={`Move ${member.title} down`}
                    disabled={editor.busy || index === currentMembers.length - 1}
                    onclick={() => void editor.moveMember(member.id, index + 1)}
                    ><ArrowDown size={16} /></button
                  >
                {/if}
                <button
                  type="button"
                  class="btn btn-ghost btn-icon"
                  disabled={editor.busy}
                  aria-label={`Remove ${member.title} from collection`}
                  onclick={() => void editor.removeMember(member.id)}><X size={16} /></button
                >
              </div>
            </li>
          {/each}
        </ol>
      {:else}<p class="text-muted">No members yet. Search your library to add an item.</p>{/if}
    </DetailSection>
  {:else}
    <ImageGrid title="Members" count={members.length}>
      {#if members.length === 0}<p class="text-muted">No members found.</p>{/if}
      {#each members as member ("id" in member ? member.id : member.tmdb_id)}
        <PosterCard
          title={`${member.title}${member.year ? ` (${member.year})` : ""}`}
          src={"id" in member ? itemArtDisplayUrl(member, "poster") : remotePosterUrl(member)}
          onselect={() => open(member)}
          meta={"id" in member || member.existing_item_id ? "In library" : null}
        />
      {/each}
    </ImageGrid>
  {/if}
</section>

{#snippet memberPlaceholder()}<Film size={16} />{/snippet}

<style>
  .member-toolbar {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(100%, 240px), 1fr));
    gap: var(--space-4);
  }
  .member-toolbar .form-label {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    min-width: 0;
  }
  .member-list {
    list-style: none;
    padding: 0;
    margin: var(--space-4) 0 0;
  }
  .member-row {
    display: flex;
    align-items: center;
    gap: var(--space-1);
    padding: var(--space-2) 0;
    border-bottom: var(--border-subtle);
  }
  .member-row:last-child {
    border-bottom: 0;
  }
  .drag-handle {
    cursor: grab;
    flex-shrink: 0;
  }
  .member-poster {
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    width: 32px;
    aspect-ratio: 2 / 3;
    border-radius: var(--radius-sm);
    overflow: hidden;
    background: var(--bg-tertiary);
  }
  .member-title {
    flex: 1;
    min-width: 0;
    justify-content: flex-start;
    text-align: left;
  }
  .member-name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .member-actions {
    display: flex;
    flex-shrink: 0;
  }
</style>
