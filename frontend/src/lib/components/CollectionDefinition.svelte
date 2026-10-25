<script lang="ts">
  import DetailForm from "./DetailForm.svelte";
  import type {
    CollectionEditor,
    CollectionDraft,
    RuleEditorSource,
  } from "../utils/collectionForms.svelte";
  import type { LibrarySectionRead } from "../../generated/rest/types.gen";
  import { emptySmartFilter } from "../utils/collectionBuilders";

  let {
    editor = $bindable(),
    groups,
    libraries,
  }: {
    editor: CollectionEditor | CollectionDraft;
    groups: string[];
    libraries: LibrarySectionRead[];
  } = $props();

  const groupListId = $props.id();
  let plex = $derived(editor.serverType === "plex");

  function onSourceChange(value: string) {
    if (value === "manual" || value === "builders" || value === "smart") {
      editor.sourceType = value as RuleEditorSource;
      if (value === "smart") {
        editor.kind = "smart";
        if (!editor.rule.smart_filter) {
          editor.rule.smart_filter = emptySmartFilter();
        }
      } else {
        if (editor.kind === "smart") {
          editor.kind = "regular";
        }
        if (value === "builders") {
          if (!editor.rule.builders) {
            editor.rule.builders = [];
          }
        }
      }
    }
  }
</script>

<DetailForm
  title="Collection Setup"
  description="Select the library, collection type, and core identity."
  busy={editor.busy}
>
  <div class="form-label">
    <label for={`${groupListId}-library`}>Library</label>
    <select
      id={`${groupListId}-library`}
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
  </div>

  <label class="form-label">
    Source
    <select value={editor.sourceType} onchange={(e) => onSourceChange(e.currentTarget.value)}>
      <option value="builders">Dynamic builders (MDBList, TMDB, tags, filters)</option>
      {#if plex}
        <option value="smart">Plex smart collection (live filter)</option>
      {/if}
      <option value="manual">Manual (hand-picked items)</option>
    </select>
  </label>

  <label class="form-label">
    Title
    <input required maxlength="200" bind:value={editor.title} placeholder="Collection title" />
  </label>

  <label class="form-label">
    Collection Group
    <input
      list={groupListId}
      maxlength="200"
      bind:value={editor.collectionGroup}
      placeholder="Ungrouped"
    />
    <datalist id={groupListId}>
      {#each groups as group (group)}
        <option value={group}></option>
      {/each}
    </datalist>
  </label>

  {#if editor.mediaType === "movie"}
    <label class="form-label">
      TMDB collection ID
      <input
        type="number"
        min="1"
        step="1"
        bind:value={editor.tmdbCollectionId}
        placeholder="e.g. 86311"
      />
    </label>
  {/if}
</DetailForm>
