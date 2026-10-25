<script lang="ts">
  import CollectionGenerator from "./CollectionGenerator.svelte";
  import CollectionGroupSettings from "./CollectionGroupSettings.svelte";
  import DetailForm from "./DetailForm.svelte";
  import type { CollectionEditor, CollectionDraft } from "../utils/collectionForms.svelte";
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
  let plex = $derived(editor.serverType === "plex");
</script>

<DetailForm
  title="General & Server Display"
  description="Manage the collection's metadata and how it appears in your library."
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
      {#if !editor.creating && editor.libraryId && !libraries.some((library) => library.id === editor.libraryId)}<option
          value={editor.libraryId}>{editor.libraryId}</option
        >{/if}
      {#each libraries as library (library.id)}<option value={library.id}>{library.title}</option
        >{/each}
    </select>
  </div>
  <label class="form-label"
    >Title <input required maxlength="200" bind:value={editor.title} /></label
  >
  <div class="options-col">
    <label class="form-label"
      >Sort title <input maxlength="200" bind:value={editor.sortTitle} /></label
    >
    <div class="form-row">
      {#each ["!", "+", "01_"] as prefix (prefix)}<button
          type="button"
          class="btn btn-ghost btn-sm"
          onclick={() => (editor.sortTitle = prefix + (editor.sortTitle || editor.title))}
          >{prefix}</button
        >{/each}
    </div>
  </div>
  <label class="form-label"
    >Apply sort title template
    <input maxlength="200" bind:value={editor.sortTitleFormat} placeholder="+&#123;title&#125;" />
    <span class="hint">Use &#123;title&#125; and &#123;group&#125;. Applied when saving.</span>
  </label>
  <label class="form-label form-wide"
    >Summary <textarea maxlength="10000" bind:value={editor.summary}></textarea></label
  >
  <label class="form-label"
    >Collection Group
    <input
      list={groupListId}
      maxlength="200"
      bind:value={editor.collectionGroup}
      placeholder="Ungrouped"
    />
    <datalist id={groupListId}
      >{#each groups as group (group)}<option value={group}></option>{/each}</datalist
    >
  </label>
  {#if editor.mediaType === "movie" && editor.sourceType !== "tmdb"}
    <label class="form-label"
      >TMDB collection ID
      <input type="number" min="1" step="1" bind:value={editor.tmdbCollectionId} />
    </label>
  {/if}
  {#if plex}
    <label class="form-label"
      >Visibility <select bind:value={editor.collectionMode}
        ><option value={null}>Inherit group or global default</option><option value="default"
          >Library default</option
        ><option value="hide_items">Hide items</option><option value="show_items"
          >Show collection and items</option
        ><option value="hide">Hide collection</option></select
      ></label
    >
    <label class="form-row"
      ><input type="checkbox" bind:checked={editor.visibleHome} />Visible on home</label
    >
  {/if}
  <CollectionGenerator {libraries} mediaType={editor.mediaType} libraryId={editor.libraryId} />
  {#if editor.collectionGroup.trim()}
    <CollectionGroupSettings
      group={editor.collectionGroup.trim()}
      mediaType={editor.mediaType}
      serverType={editor.serverType}
    />
  {/if}
</DetailForm>
