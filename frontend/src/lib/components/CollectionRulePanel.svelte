<script lang="ts">
  import CollectionPolicyFields from "./CollectionPolicyFields.svelte";
  import DetailForm from "./DetailForm.svelte";
  import type { CollectionEditor, CollectionDraft } from "../utils/collectionForms.svelte";
  let { editor }: { editor: CollectionEditor | CollectionDraft } = $props();
  let filters = $derived(editor.rule.filters ?? {});
</script>

<DetailForm
  title="Builder & Dynamic Rules Engine"
  description="Build this collection from an external list or library filters, then keep it in sync."
  busy={editor.busy}
>
  <label class="form-label"
    >Source <select bind:value={editor.sourceType}
      ><option value="manual">Manual</option><option value="mdblist">MDBList</option
      >{#if editor.mediaType === "movie"}<option value="tmdb">TMDB franchise</option>{/if}<option
        value="filter">Library filter</option
      ></select
    ></label
  >
  {#if editor.sourceType !== "manual"}
    {#if editor.sourceType === "filter"}
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
        >{editor.sourceType === "mdblist" ? "MDBList list URL or ID" : "TMDB franchise ID"}<input
          required
          bind:value={editor.rule.source_identifier}
        /></label
      >
    {/if}
    <CollectionPolicyFields policy={editor.rule} />
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
    {#if editor.existingRule}
      <div class="form-wide options-col">
        <p class="hint">Last run: {editor.existingRule.last_synced_at ?? "Never"}</p>
        {#if editor.existingRule.last_error}<p role="alert" class="text-danger">
            {editor.existingRule.last_error}
          </p>{/if}
      </div>
    {/if}
  {/if}
</DetailForm>
