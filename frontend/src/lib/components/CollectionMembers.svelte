<script lang="ts">
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
    <div class="options-col">
      <label class="form-label">
        Add item
        <input type="search" placeholder="Search library" bind:value={search} />
      </label>
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
                class="btn btn-ghost"
                draggable={!editor.busy}
                aria-label={`Drag ${member.title} to reorder`}
                disabled={editor.busy}
                ondragstart={(event) => {
                  dragging = member.id;
                  event.dataTransfer?.setData("text/plain", String(member.id));
                }}
                ondragend={() => (dragging = null)}>::</button
              >
              <button
                type="button"
                class="btn btn-ghost"
                aria-label={`Move ${member.title} up`}
                disabled={editor.busy || index === 0}
                onclick={() => void editor.moveMember(member.id, index - 1)}>Up</button
              >
              <button
                type="button"
                class="btn btn-ghost"
                aria-label={`Move ${member.title} down`}
                disabled={editor.busy || index === currentMembers.length - 1}
                onclick={() => void editor.moveMember(member.id, index + 1)}>Down</button
              >
            {/if}
            <button type="button" class="btn btn-ghost member-title" onclick={() => open(member)}>
              <img
                class="member-poster"
                src={itemArtDisplayUrl(member, "poster") ?? undefined}
                alt=""
              />
              {member.title}
              {member.year ? `(${member.year})` : ""}
            </button>
            <button
              type="button"
              class="btn btn-ghost"
              disabled={editor.busy}
              aria-label={`Remove ${member.title} from collection`}
              onclick={() => void editor.removeMember(member.id)}>Remove</button
            >
          </li>
        {/each}
      </ol>
    </div>
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

<style>
  .member-list {
    list-style: none;
    padding: 0;
  }

  .member-row {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    border-bottom: var(--border-subtle);
    flex-wrap: wrap;
  }

  .member-poster {
    width: 32px;
    aspect-ratio: 2 / 3;
    object-fit: cover;
  }

  .member-title {
    flex: 1;
    min-width: 120px;
    justify-content: flex-start;
    text-align: left;
  }
</style>
