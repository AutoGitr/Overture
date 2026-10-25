<script lang="ts">
  import { CollectionDraft, type CollectionEditor } from "../utils/collectionForms.svelte";
  import DetailForm from "./DetailForm.svelte";
  let { editor }: { editor: CollectionDraft | CollectionEditor } = $props();
  let discovery = $derived(
    editor instanceof CollectionDraft && editor.discovering ? editor.discovery : null,
  );
</script>

<DetailForm
  title="Schedule"
  description={discovery
    ? "Choose how often Overture discovers and updates franchise collections."
    : editor.sourceType === "manual"
      ? "Seasonal dates apply when you save this collection. Choose a dynamic source in Setup for automatic seasonal updates."
      : "Choose when Overture syncs sources and when this collection is active. Seasonal dates repeat every year, including across New Year."}
  busy={editor.busy}
>
  {#if discovery}
    <label class="form-label">
      Sync interval (hours)
      <input type="number" min="1" max="8760" bind:value={discovery.policy.sync_interval_hours} />
    </label>
    <label class="form-row">
      <input type="checkbox" bind:checked={discovery.policy.sync_enabled} /> Enable scheduled sync
    </label>
  {:else}
    {#if editor.sourceType !== "manual" && editor.smartFilterEditable}
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
      <input placeholder="12-15" maxlength="5" bind:value={editor.activeStartMmdd} />
      <span class="hint">Leave both dates blank for a year-round collection.</span>
    </label>
    <label class="form-label">
      Active end (MM-DD)
      <input placeholder="01-05" maxlength="5" bind:value={editor.activeEndMmdd} />
    </label>
    {#if editor.activeStartMmdd || editor.activeEndMmdd}
      <label class="form-label">
        Seasonal inactivity behavior
        <select bind:value={editor.deleteWhenInactive}>
          <option value={null}>Inherit default</option>
          <option value={true}>Delete from media server when inactive</option>
          <option value={false}>Keep collection on media server</option>
        </select>
      </label>
    {/if}
  {/if}
</DetailForm>
