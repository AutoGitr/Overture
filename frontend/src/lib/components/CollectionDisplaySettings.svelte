<script lang="ts">
  import DetailForm from "./DetailForm.svelte";
  import type { CollectionEditor, CollectionDraft } from "../utils/collectionForms.svelte";

  let {
    editor,
  }: {
    editor: CollectionEditor | CollectionDraft;
  } = $props();

  const identityId = $props.id();
  let plex = $derived(editor.serverType === "plex");
</script>

<DetailForm
  title="Display"
  description="Set the summary, library ordering, and media server visibility."
  busy={editor.busy}
>
  {#if editor.sourceType !== "smart"}
    <label class="form-label">
      Member order
      <select bind:value={editor.orderType}>
        <option value="release">Release date</option>
        <option value="alpha">Alphabetical</option>
        {#if plex}<option value="custom">Source / custom order</option>{/if}
      </select>
    </label>
  {/if}
  {#if editor.mediaType === "movie"}
    <div class="form-label">
      <label for={identityId}>TMDB collection ID</label>
      <input
        id={identityId}
        type="number"
        min="1"
        step="1"
        bind:value={editor.tmdbCollectionId}
        placeholder="e.g. 86311"
      />
      <span class="hint"
        >Optional franchise identity for artwork and themes. Membership is configured above.</span
      >
    </div>
  {/if}
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
</DetailForm>
