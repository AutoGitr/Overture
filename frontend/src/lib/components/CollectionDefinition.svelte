<script lang="ts">
  import { uiState } from "../stores/uiState.svelte";
  import DetailForm from "./DetailForm.svelte";
  import {
    CollectionDraft,
    selectCollectionSource,
    type CollectionEditor,
  } from "../utils/collectionForms.svelte";
  import type { LibrarySectionRead } from "../../generated/rest/types.gen";

  let {
    editor,
    groups,
    libraries,
  }: {
    editor: CollectionEditor | CollectionDraft;
    groups: string[];
    libraries: LibrarySectionRead[];
  } = $props();

  const groupListId = $props.id();
  let discovering = $derived(editor instanceof CollectionDraft && editor.discovering);
</script>

<DetailForm
  title="Collection Setup"
  description="Choose where the collection lives and how its members are selected, then give it a name and optional group."
  busy={editor.busy}
>
  <label class="form-label">
    Library
    <select
      required
      value={editor.libraryId}
      disabled={!editor.creating}
      onchange={(event) => {
        if (editor.creating) editor.selectLibrary(event.currentTarget.value);
      }}
    >
      <option value="">Select a library</option>
      {#if !editor.creating && editor.libraryId && !libraries.some((library) => library.id === editor.libraryId)}
        <option value={editor.libraryId}>{editor.libraryId}</option>
      {/if}
      {#each libraries as library (library.id)}
        <option value={library.id}>{library.title}</option>
      {/each}
    </select>
  </label>

  <div class="form-label">
    <label for={`${groupListId}-source`}>Source</label>
    <select
      id={`${groupListId}-source`}
      value={editor.sourceType}
      onchange={(event) => {
        const source = event.currentTarget.value;
        if (source === "builders" || source === "smart" || source === "discovery")
          selectCollectionSource(editor, source);
      }}
    >
      {#if !editor.creating && editor.sourceType === "unmanaged"}
        <option value="unmanaged" disabled>Unmanaged server collection</option>
      {/if}
      <option value="builders">Dynamic sources</option>
      {#if editor.serverType === "plex"}<option value="smart">Plex smart filter</option>{/if}
      {#if editor instanceof CollectionDraft && editor.mediaType === "movie"}
        <option value="discovery">Discover TMDB franchises</option>
      {/if}
    </select>
    <span class="hint"
      >{discovering
        ? "Create a collection for each matching franchise in this library."
        : editor.sourceType === "smart"
          ? "Plex updates members as they match your filters."
          : "Combine lists, TMDB IDs, people, tags, and library filters."}</span
    >
  </div>

  <label class="form-label">
    Title
    {#if discovering}
      <input disabled value="" placeholder="From TMDB franchise names" />
    {:else}
      <input required maxlength="200" bind:value={editor.title} placeholder="Collection title" />
    {/if}
  </label>

  <div class="form-label">
    <label for={`${groupListId}-group`}>Collection Group</label>
    <select
      id={`${groupListId}-group`}
      value={groups.includes(editor.collectionGroup)
        ? editor.collectionGroup
        : editor.collectionGroup
          ? "__new__"
          : ""}
      onchange={(event) => {
        editor.collectionGroup =
          event.currentTarget.value === "__new__" ? "New group" : event.currentTarget.value;
      }}
    >
      <option value="" disabled={discovering}>No group</option>
      {#each groups as group (group)}<option value={group}>{group}</option>{/each}
      <option value="__new__">Create new group...</option>
    </select>
    {#if editor.collectionGroup && !groups.includes(editor.collectionGroup)}
      <label for={`${groupListId}-new-group`}>New group name</label>
      <input
        id={`${groupListId}-new-group`}
        required
        maxlength="200"
        bind:value={editor.collectionGroup}
      />
    {/if}
    <span class="hint">Group defaults apply unless this collection has an explicit override.</span>
    <button
      type="button"
      class="btn btn-ghost btn-sm"
      onclick={() => uiState.openCollectionGroups(editor.collectionGroup)}>Manage groups</button
    >
  </div>
</DetailForm>
