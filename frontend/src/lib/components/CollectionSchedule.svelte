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
    ? "How often the criteria sync, and when the collection is active each year."
    : "When the collection is active each year."}
  busy={editor.busy}
>
  {#if syncs}
    <label class="form-label">
      Sync interval (hours)
      <input type="number" min="1" max="8760" bind:value={editor.rule.sync_interval_hours} />
    </label>
    <label class="form-row">
      <input type="checkbox" bind:checked={editor.rule.enabled} /> Scheduled sync
    </label>
  {/if}
  <label class="form-label">
    Active from (MM-DD)
    <input
      placeholder={editor.defaults.data?.active_start_mmdd ?? ""}
      maxlength="5"
      bind:value={editor.activeStartMmdd}
    />
    <span class="hint">Blank for all year. A range can cross New Year.</span>
  </label>
  <label class="form-label">
    Active until (MM-DD)
    <input
      placeholder={editor.defaults.data?.active_end_mmdd ?? ""}
      maxlength="5"
      bind:value={editor.activeEndMmdd}
    />
  </label>
  {#if editor.activeStartMmdd || editor.activeEndMmdd}
    <label class="form-label">
      When inactive
      <select bind:value={editor.deleteWhenInactive}>
        <option value={null}>Default</option>
        <option value={true}>Remove from server</option>
        <option value={false}>Keep on server</option>
      </select>
    </label>
  {/if}
</DetailForm>
