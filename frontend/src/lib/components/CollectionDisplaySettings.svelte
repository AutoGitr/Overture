<script lang="ts">
  import CollectionGroupSettings from "./CollectionGroupSettings.svelte";
  import DetailForm from "./DetailForm.svelte";
  import type { CollectionEditor, CollectionDraft } from "../utils/collectionForms.svelte";
  import type { LibrarySectionRead } from "../../generated/rest/types.gen";

  let {
    editor = $bindable(),
    libraries = [],
  }: {
    editor: CollectionEditor | CollectionDraft;
    libraries?: LibrarySectionRead[];
  } = $props();

  let plex = $derived(editor.serverType === "plex");
</script>

<DetailForm
  title="Server Display & Scheduling"
  description="Configure sort titles, summaries, seasonal visibility windows, and media server promotion."
  busy={editor.busy}
>
  <div class="options-col">
    <label class="form-label">
      Sort title
      <input maxlength="200" bind:value={editor.sortTitle} placeholder="Sort title override" />
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
    <textarea maxlength="10000" bind:value={editor.summary} placeholder="Collection overview"
    ></textarea>
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

    <div class="options-col form-wide">
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
    gap: var(--space-4);
  }
  @media (max-width: 640px) {
    .seasonal-row {
      grid-template-columns: 1fr;
    }
  }
</style>
