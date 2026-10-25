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
        <option value={null}>Inherit group or global default</option>
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
  <label class="form-label">
    Sort title
    <input
      aria-label="Sort title"
      maxlength="400"
      bind:value={editor.sortTitleFormat}
      placeholder="Inherit group or global default"
    />
    <span class="hint"
      >Plain text or a template: &#123;title&#125;, &#123;group&#125;. Blank inherits the group or
      global default.</span
    >
  </label>
  <label class="form-label form-wide">
    Summary
    <textarea
      aria-label="Summary"
      maxlength="20000"
      rows="4"
      bind:value={editor.summaryFormat}
      placeholder="Inherit group or global default"></textarea>
    <span class="hint"
      >Plain text or a template: &#123;title&#125;, &#123;group&#125;, &#123;start_date&#125;,
      &#123;end_date&#125;, &#123;summary&#125; (the original summary).</span
    >
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
      <label class="form-label">
        Visible on home
        <select bind:value={editor.visibleHome}>
          <option value={null}>Inherit group or global default</option>
          <option value={true}>true</option>
          <option value={false}>false</option>
        </select>
      </label>
      <label class="form-label">
        Visible to shared users
        <select bind:value={editor.visibleShared}>
          <option value={null}>Inherit group or global default</option>
          <option value={true}>true</option>
          <option value={false}>false</option>
        </select>
      </label>
      <label class="form-label">
        Visible in library recommended
        <select bind:value={editor.visibleLibrary}>
          <option value={null}>Inherit group or global default</option>
          <option value={true}>true</option>
          <option value={false}>false</option>
        </select>
      </label>
    </div>
  {/if}
</DetailForm>
