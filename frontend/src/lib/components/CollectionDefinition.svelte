<script lang="ts">
  import DetailForm from "./DetailForm.svelte";
  import SegmentedControl from "./SegmentedControl.svelte";
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
  {#if editor instanceof CollectionDraft && editor.mediaType === "movie"}
    <div class="form-wide">
      <SegmentedControl
        label="Collection scope"
        options={[
          ["single", "One collection"],
          ["multiple", "Discover franchises"],
        ]}
        bind:value={editor.creationScope}
        --segmented-margin="0"
      />
    </div>
  {/if}

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
    {#if discovering}
      <select id={`${groupListId}-source`} disabled><option>TMDB franchises</option></select>
      <span class="hint">Create a collection for each matching franchise in this library.</span>
    {:else}
      <select
        id={`${groupListId}-source`}
        value={editor.sourceType}
        onchange={(event) => {
          const source = event.currentTarget.value;
          if (source === "manual" || source === "builders" || source === "smart") {
            selectCollectionSource(editor, source);
          }
        }}
      >
        <option value="manual">Manual selection</option>
        <option value="builders">Dynamic sources</option>
        {#if editor.serverType === "plex"}
          <option value="smart">Plex smart filter</option>
        {/if}
      </select>
      <span class="hint">
        {editor.sourceType === "manual"
          ? "Pick items from your library."
          : editor.sourceType === "smart"
            ? "Plex updates members as they match your filters."
            : "Combine TMDB, MDBList, tags, and library filters."}
      </span>
    {/if}
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
    <input
      id={`${groupListId}-group`}
      list={groupListId}
      maxlength="200"
      required={discovering}
      bind:value={editor.collectionGroup}
      placeholder={discovering ? "e.g. Franchises" : "Ungrouped"}
    />
    <span class="hint"
      >{discovering
        ? "All discovered collections share this group and its defaults."
        : "Choose an existing group or type a new name."}</span
    >
    <datalist id={groupListId}>
      {#each groups as group (group)}<option value={group}></option>{/each}
    </datalist>
  </div>
</DetailForm>
