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
  let preset = $derived(
    editor instanceof CollectionDraft && (editor.generating || editor.discovering),
  );
</script>

<DetailForm
  collapsible
  expanded
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

  {#if editor instanceof CollectionDraft}
    <div class="form-label">
      <label for={`${groupListId}-type`}>Type</label>
      <select
        id={`${groupListId}-type`}
        value={preset ? "preset" : "custom"}
        onchange={(event) =>
          selectCollectionSource(
            editor,
            event.currentTarget.value === "preset" ? "preset" : "builders",
          )}
      >
        <option value="custom">Custom</option>
        <option value="preset">Preset</option>
      </select>
    </div>
  {/if}

  {#if preset && editor instanceof CollectionDraft}
    <div class="form-label">
      <label for={`${groupListId}-preset`}>Preset</label>
      <select
        id={`${groupListId}-preset`}
        value={discovering ? "discovery" : editor.preset}
        onchange={(event) => {
          const value = event.currentTarget.value;
          if (value === "discovery") selectCollectionSource(editor, "discovery");
          else if (value === "decades" || value === "years" || value === "genres") {
            editor.preset = value;
            selectCollectionSource(editor, "preset");
          }
        }}
      >
        <option value="decades">Decades</option>
        <option value="years">Years</option>
        <option value="genres">Genres</option>
        {#if editor.mediaType === "movie"}<option value="discovery">TMDB franchises</option>{/if}
      </select>
      <span class="hint"
        >Create a set of collections, each with editable sources and its own schedule.</span
      >
    </div>
  {:else}
    <div class="form-label">
      <label for={`${groupListId}-source`}>Source</label>
      <select
        id={`${groupListId}-source`}
        value={editor.sourceType}
        onchange={(event) => {
          const source = event.currentTarget.value;
          if (source === "builders" || source === "smart") selectCollectionSource(editor, source);
        }}
      >
        {#if !editor.creating && editor.sourceType === "unmanaged"}
          <option value="unmanaged" disabled>Unmanaged server collection</option>
        {/if}
        <option value="builders">Dynamic sources</option>
        {#if editor.serverType === "plex"}<option value="smart">Plex smart filter</option>{/if}
      </select>
      <span class="hint"
        >{discovering
          ? "Create a collection for each matching franchise in this library."
          : editor.sourceType === "smart"
            ? "Plex updates members as they match your filters."
            : "Combine lists, TMDB IDs, people, tags, and library filters."}</span
      >
    </div>
  {/if}

  <label class="form-label">
    Title
    {#if preset}
      <input
        disabled
        value=""
        placeholder={discovering ? "From TMDB franchise names" : "From selected preset values"}
      />
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
      onclick={() =>
        uiState.openCollectionGroups(editor.collectionGroup, (name, replacement) => {
          if (editor.collectionGroup === name) editor.collectionGroup = replacement;
        })}>Manage groups</button
    >
  </div>
</DetailForm>
