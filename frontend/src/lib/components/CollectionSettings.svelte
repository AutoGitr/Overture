<script lang="ts">
  import CollectionGroupSettings from "./CollectionGroupSettings.svelte";
  import DetailForm from "./DetailForm.svelte";
  import type { CollectionEditor, CollectionDraft } from "../utils/collectionForms.svelte";
  import type { LibrarySectionRead } from "../../generated/rest/types.gen";

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
</script>

<DetailForm
  title="General & Server Display"
  description="Manage the collection's metadata, active seasonal windows, and how it appears in your library."
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
    Title
    <input required maxlength="200" bind:value={editor.title} />
  </label>

  <div class="options-col">
    <label class="form-label">
      Sort title
      <input maxlength="200" bind:value={editor.sortTitle} />
    </label>
    <div class="form-row">
      {#each ["!", "+", "01_"] as prefix (prefix)}
        <button
          type="button"
          class="btn btn-ghost btn-sm"
          onclick={() => (editor.sortTitle = prefix + (editor.sortTitle || editor.title))}
        >
          {prefix}
        </button>
      {/each}
    </div>
  </div>

  <label class="form-label">
    Apply sort title template
    <input maxlength="200" bind:value={editor.sortTitleFormat} placeholder="+&#123;title&#125;" />
    <span class="hint">Use &#123;title&#125; and &#123;group&#125;. Applied when saving.</span>
  </label>

  <label class="form-label form-wide">
    Summary
    <textarea maxlength="10000" bind:value={editor.summary}></textarea>
  </label>

  <label class="form-label">
    Summary template
    <input
      maxlength="500"
      bind:value={editor.summaryFormat}
      placeholder="&#123;title&#125; - &#123;summary&#125;"
    />
    <span class="hint">
      Tokens: &#123;title&#125;, &#123;group&#125;, &#123;start_date&#125;, &#123;end_date&#125;,
      &#123;summary&#125;.
    </span>
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

  {#if editor.mediaType === "movie" && editor.sourceType !== "tmdb"}
    <label class="form-label">
      TMDB collection ID
      <input type="number" min="1" step="1" bind:value={editor.tmdbCollectionId} />
    </label>
  {/if}

  <div class="seasonal-row">
    <label class="form-label">
      Active start (MM-DD)
      <input placeholder="12-15" maxlength="5" bind:value={editor.activeStartMmdd} />
    </label>
    <label class="form-label">
      Active end (MM-DD)
      <input placeholder="01-05" maxlength="5" bind:value={editor.activeEndMmdd} />
    </label>
  </div>

  {#if editor.activeStartMmdd && editor.activeEndMmdd}
    <label class="form-label">
      Seasonal inactivity behavior
      <select bind:value={editor.deleteWhenInactive}>
        <option value={null}>Inherit default</option>
        <option value={true}>Delete from media server when inactive</option>
        <option value={false}>Keep collection on media server</option>
      </select>
    </label>
  {/if}

  {#if plex}
    <label class="form-label">
      Visibility
      <select bind:value={editor.collectionMode}>
        <option value={null}>Inherit group or global default</option>
        <option value="default">Library default</option>
        <option value="hide_items">Hide items</option>
        <option value="show_items">Show collection and items</option>
        <option value="hide">Hide collection</option>
      </select>
    </label>

    <label class="form-label">
      Collection filtering
      <select bind:value={editor.collectionFiltering}>
        <option value={null}>Inherit default</option>
        <option value="admin">All users (admin-managed)</option>
        <option value="user">User library</option>
      </select>
    </label>

    <div class="options-col">
      <span class="hint">Media server home and promotion</span>
      <label class="form-row">
        <input type="checkbox" bind:checked={editor.visibleHome} />
        Visible on home
      </label>
      <label class="form-row">
        <input type="checkbox" bind:checked={editor.visibleShared} />
        Visible to shared users
      </label>
      <label class="form-row">
        <input type="checkbox" bind:checked={editor.visibleLibrary} />
        Visible in library recommended
      </label>
    </div>
  {/if}

  {#if editor.collectionGroup.trim()}
    <CollectionGroupSettings
      group={editor.collectionGroup.trim()}
      mediaType={editor.mediaType}
      serverType={editor.serverType}
      {libraries}
    />
  {/if}
</DetailForm>

<style>
  .seasonal-row {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--space-3, 0.75rem);
  }
</style>
