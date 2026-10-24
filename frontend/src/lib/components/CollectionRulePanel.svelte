<script lang="ts">
  import type { CollectionEditor } from "../utils/collectionForms.svelte";
  let { editor }: { editor: CollectionEditor } = $props();
  let filters = $derived(editor.rule.filters ?? {});
</script>

<form
  class="options-col"
  onsubmit={(event) => {
    event.preventDefault();
    void editor.saveRule();
  }}
>
  <fieldset class="options-col" disabled={editor.busy}>
    <legend>Dynamic membership</legend>
    <label class="form-label"
      >Source <select bind:value={editor.rule.source_type}
        ><option value="mdblist">MDBList</option
        >{#if editor.collection.media_type === "movie"}<option value="tmdb">TMDB franchise</option
          >{/if}<option value="filter">Library filter</option></select
      ></label
    >
    {#if editor.rule.source_type === "filter"}
      <label class="form-label"
        >Decade <input
          type="number"
          min="1800"
          max="3000"
          step="10"
          value={filters.decade ?? ""}
          oninput={(event) =>
            (editor.rule.filters = {
              ...filters,
              decade: event.currentTarget.value ? event.currentTarget.valueAsNumber : null,
            })}
        /></label
      >
      <label class="form-label"
        >Studio <input
          value={filters.studio ?? ""}
          oninput={(event) =>
            (editor.rule.filters = { ...filters, studio: event.currentTarget.value || null })}
        /></label
      >
      <label class="form-label"
        >Genre <input
          value={filters.genre ?? ""}
          oninput={(event) =>
            (editor.rule.filters = { ...filters, genre: event.currentTarget.value || null })}
        /></label
      >
    {:else}
      <label class="form-label"
        >{editor.rule.source_type === "mdblist"
          ? "MDBList list URL or ID"
          : "TMDB collection ID"}<input
          required
          bind:value={editor.rule.source_identifier}
        /></label
      >
    {/if}
    <label class="form-label"
      >Sync strategy <select bind:value={editor.rule.sync_mode}
        ><option value={null}>Inherit global default</option><option value="sync"
          >Strict sync</option
        ><option value="append">Append, keep manual members</option></select
      ></label
    >
    <label class="form-label"
      >Minimum members (blank inherits)<input
        type="number"
        min="1"
        max="100"
        value={editor.rule.minimum_items ?? ""}
        oninput={(event) =>
          (editor.rule.minimum_items = event.currentTarget.value
            ? event.currentTarget.valueAsNumber
            : null)}
      /></label
    >
    <label class="form-label"
      >Below minimum <select bind:value={editor.rule.delete_below_minimum}
        ><option value={null}>Inherit global default</option><option value={false}
          >Keep collection</option
        ><option value={true}>Delete collection</option></select
      ></label
    >
    <label class="form-label"
      >Sync interval (hours)<input
        type="number"
        min="1"
        max="8760"
        required
        bind:value={editor.rule.sync_interval_hours}
      /></label
    >
    <label class="form-row"
      ><input type="checkbox" bind:checked={editor.rule.enabled} />Enable scheduled sync</label
    >
    <button class="btn btn-primary" type="submit">Save rule</button>
  </fieldset>
</form>
{#if editor.collection.rule}
  <p class="text-muted">Last run: {editor.collection.rule.last_synced_at ?? "Never"}</p>
  {#if editor.collection.rule.last_error}<p role="alert">
      {editor.collection.rule.last_error}
    </p>{/if}
  <div class="form-row">
    <button class="btn" disabled={editor.busy} onclick={() => void editor.sync()}>Sync now</button
    ><button class="btn btn-ghost" disabled={editor.busy} onclick={() => void editor.removeRule()}
      >Remove rule</button
    >
  </div>
{/if}
