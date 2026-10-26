<script lang="ts">
  import type { CollectionDraft, CollectionEditor } from "../utils/collectionForms.svelte";
  import DetailForm from "./DetailForm.svelte";
  let { editor }: { editor: CollectionDraft | CollectionEditor } = $props();
  let syncs = $derived(editor.content === "criteria" && editor.criteriaEditable);
</script>

<DetailForm
  collapsible
  title="Schedule"
  description={syncs
    ? "Choose how often Overture applies the criteria and when the collection is active. Seasonal dates repeat every year, including across New Year."
    : "Seasonal dates apply when you save the collection. Criteria keep a seasonal collection current."}
  busy={editor.busy}
>
  {#if syncs}
    <label class="form-label">
      Sync interval (hours)
      <input type="number" min="1" max="8760" bind:value={editor.rule.sync_interval_hours} />
    </label>
    <label class="form-row">
      <input type="checkbox" bind:checked={editor.rule.enabled} /> Enable scheduled sync
    </label>
  {/if}
  <label class="form-label">
    Active start (MM-DD)
    <input
      placeholder={editor.defaults.data?.active_start_mmdd ?? ""}
      maxlength="5"
      bind:value={editor.activeStartMmdd}
    />
    <span class="hint">Leave both dates blank for a year-round collection.</span>
  </label>
  <label class="form-label">
    Active end (MM-DD)
    <input
      placeholder={editor.defaults.data?.active_end_mmdd ?? ""}
      maxlength="5"
      bind:value={editor.activeEndMmdd}
    />
  </label>
  {#if editor.activeStartMmdd || editor.activeEndMmdd}
    <label class="form-label">
      Seasonal inactivity behavior
      <select bind:value={editor.deleteWhenInactive}>
        <option value={null}>Default</option>
        <option value={true}>Delete from media server when inactive</option>
        <option value={false}>Keep collection on media server</option>
      </select>
    </label>
  {/if}
</DetailForm>
