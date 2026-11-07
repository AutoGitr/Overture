<script lang="ts">
  import ArrowUp from "@lucide/svelte/icons/arrow-up";
  import ArrowDown from "@lucide/svelte/icons/arrow-down";
  import GripVertical from "@lucide/svelte/icons/grip-vertical";
  import X from "@lucide/svelte/icons/x";
  import Film from "@lucide/svelte/icons/film";
  import DetailSection from "./DetailSection.svelte";
  import FallbackImage from "./FallbackImage.svelte";
  import type {
    LibrarySectionRead,
    MediaItemRead,
    TmdbItemResult,
  } from "../../generated/rest/types.gen";
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
    libraries = [],
  }: {
    members: (MediaItemRead | TmdbItemResult)[];
    catalog?: boolean;
    editor?: CollectionEditor;
    libraryItems?: MediaItemRead[];
    libraries?: LibrarySectionRead[];
  } = $props();

  let smart = $derived(editor?.collection.kind === "smart");
  let orderable = $derived(!smart && editor?.collection.server_type === "plex");
  let memberGroups = $derived.by(() => {
    if (!editor) return [];
    const collection = editor.collection;
    const ids = [
      ...new Set([
        ...collection.library_ids,
        ...collection.members.map((member) => member.library_id ?? ""),
      ]),
    ];
    return ids
      .map((id) => ({
        id,
        title: libraries.find((library) => library.id === id)?.title ?? id,
        members: collection.members.filter((member) => (member.library_id ?? "") === id),
      }))
      .filter((group) => group.members.length > 0);
  });

  // Plex orders each library's copy of a collection on its own.
  function moveWithin(group: MediaItemRead[], index: number, target: number) {
    const member = group[index];
    const neighbour = group[target];
    if (!editor || !member || !neighbour) return;
    void editor.moveMember(member.id, editor.collection.members.indexOf(neighbour));
  }
  let available = $derived(editor?.availableMembers(libraryItems) ?? []);

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
      collapsible
      title="Members"
      description={smart
        ? "Plex decides the members and their order from the smart filter."
        : editor.collection.server_type === "plex"
          ? "Add, remove or drag members into place. The next sync sends them."
          : "Add or remove members. The next sync sends them."}
    >
      <span class="badge badge-muted" aria-label="Resolved member count"
        >{editor.collection.child_count} members</span
      >
      {#if editor.manualMembersAllowed}
        <label class="form-label add-member">
          Add item
          <input
            type="search"
            placeholder="Search library"
            bind:value={editor.memberSearch}
            disabled={editor.busy}
          />
        </label>
      {/if}
      {#if editor.manualMembersAllowed && editor.memberSearch.trim()}
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
        {#each memberGroups as group (group.id)}
          <section class="member-group" aria-label={`${group.title} members`}>
            {#if memberGroups.length > 1 || editor.collection.library_ids.length > 1}
              <h4 class="form-label">{group.title}</h4>
            {/if}
            <ol class="member-list">
              {#each group.members as member, index (member.id)}
                <li
                  class="member-row"
                  ondragover={(event) => {
                    if (orderable) event.preventDefault();
                  }}
                  ondrop={(event) => {
                    if (!orderable) return;
                    event.preventDefault();
                    const from = group.members.findIndex(
                      (entry) => entry.id === editor.draggingMemberId,
                    );
                    if (from !== -1 && from !== index) moveWithin(group.members, from, index);
                    editor.draggingMemberId = null;
                  }}
                >
                  {#if orderable}
                    <button
                      type="button"
                      class="btn btn-ghost btn-icon drag-handle"
                      draggable={!editor.busy}
                      aria-label={`Drag ${member.title} to reorder`}
                      disabled={editor.busy}
                      ondragstart={(event) => {
                        editor.draggingMemberId = member.id;
                        if (event.dataTransfer) {
                          event.dataTransfer.effectAllowed = "move";
                          event.dataTransfer.setData("text/plain", String(member.id));
                        }
                      }}
                      ondragend={() => (editor.draggingMemberId = null)}
                      ><GripVertical size={16} /></button
                    >
                  {/if}
                  <button
                    type="button"
                    class="btn btn-ghost member-title"
                    onclick={() => open(member)}
                  >
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
                    {#if orderable}
                      <button
                        type="button"
                        class="btn btn-ghost btn-icon"
                        aria-label={`Move ${member.title} up`}
                        disabled={editor.busy || index === 0}
                        onclick={() => moveWithin(group.members, index, index - 1)}
                        ><ArrowUp size={16} /></button
                      >
                      <button
                        type="button"
                        class="btn btn-ghost btn-icon"
                        aria-label={`Move ${member.title} down`}
                        disabled={editor.busy || index === group.members.length - 1}
                        onclick={() => moveWithin(group.members, index, index + 1)}
                        ><ArrowDown size={16} /></button
                      >
                    {/if}
                    {#if editor.manualMembersAllowed}<button
                        type="button"
                        class="btn btn-ghost btn-icon"
                        disabled={editor.busy}
                        aria-label={`Remove ${member.title} from collection`}
                        onclick={() => void editor.removeMember(member.id)}
                        ><X size={16} /></button
                      >{/if}
                  </div>
                </li>
              {/each}
            </ol>
          </section>
        {/each}
      {:else}<p class="text-muted">
          {smart
            ? "No items currently match the smart filter."
            : editor.manualMembersAllowed
              ? "No members yet. Search your library to add an item."
              : "No members yet. Sync the saved sources to populate this collection."}
        </p>{/if}
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
  .add-member {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    min-width: 0;
  }
  .member-group {
    margin-top: var(--space-4);
  }
  .member-group h4 {
    margin: 0 0 var(--space-1);
  }
  .member-list {
    list-style: none;
    padding: 0;
    margin: 0;
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
