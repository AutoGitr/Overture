<script lang="ts">
  import type { CollectionEditor } from "../utils/collectionForms.svelte";
  import type { MediaItemRead, TmdbItemResult } from "../../generated/rest/types.gen";
  import { goToCatalogEntry, goToItem } from "../router/routes";
  import { itemArtDisplayUrl, remotePosterUrl } from "../utils/artDisplay";
  import PosterCard from "./PosterCard.svelte";
  import ImageGrid from "./ImageGrid.svelte";

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
  let available = $derived(
    libraryItems.filter(
      (item) =>
        item.library_id === editor?.collection.library_id &&
        item.server_item_id &&
        !item.server_removed_at &&
        !members.some((member) => "id" in member && member.id === item.id) &&
        item.title.toLowerCase().includes(search.toLowerCase()),
    ),
  );

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
    <div class="options-col">
      <label class="form-label"
        >Add item <input type="search" placeholder="Search library" bind:value={search} /></label
      >
      {#if search}
        {#each available.slice(0, 20) as item (item.id)}<button
            class="btn btn-ghost"
            disabled={editor.busy}
            onclick={() => void editor?.addMember(item.id)}
            >Add {item.title} {item.year ? `(${item.year})` : ""}</button
          >{/each}
        {#if !available.length}<p class="text-muted">No matching library items.</p>{/if}
      {/if}
      <label class="form-label"
        >Sort members
        <select
          value={editor.collection.order_type}
          disabled={editor.busy}
          onchange={(event) => {
            const order = event.currentTarget.value;
            if (order === "release" || order === "alpha" || order === "custom")
              void editor?.setMembers(
                editor.collection.members.map((member) => member.id),
                order,
              );
          }}
        >
          <option value="release">Release date</option><option value="alpha">Alphabetical</option
          >{#if editor.collection.server_type === "plex"}<option value="custom">Custom</option>{/if}
        </select>
      </label>
      <ol class="member-list">
        {#each editor.collection.members as member, index (member.id)}
          <li class="member-row">
            {#if editor.collection.server_type === "plex"}
              <button
                class="btn btn-ghost"
                draggable={!editor.busy}
                aria-label={`Drag ${member.title} to reorder`}
                disabled={editor.busy}
                ondragstart={() => (dragging = member.id)}
                ondragend={() => (dragging = null)}
                ondragover={(event) => event.preventDefault()}
                ondrop={(event) => {
                  event.preventDefault();
                  if (dragging !== null && dragging !== member.id)
                    void editor?.moveMember(dragging, member.id);
                  dragging = null;
                }}>::</button
              >
              <button
                class="btn btn-ghost"
                aria-label={`Move ${member.title} up`}
                disabled={editor.busy || index === 0}
                onclick={() => {
                  const previous = editor?.collection.members[index - 1];
                  if (previous) void editor?.moveMember(member.id, previous.id);
                }}>Up</button
              >
            {/if}
            <button class="btn btn-ghost member-title" onclick={() => open(member)}
              ><img
                class="member-poster"
                src={itemArtDisplayUrl(member, "poster") ?? undefined}
                alt=""
              />{member.title}
              {member.year ? `(${member.year})` : ""}</button
            >
            <button
              class="btn btn-ghost"
              disabled={editor.busy}
              aria-label={`Remove ${member.title} from collection`}
              onclick={() => void editor?.removeMember(member.id)}>Remove</button
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
