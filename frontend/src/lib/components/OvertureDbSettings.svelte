<script lang="ts">
  import type { AppSettingsUpdate } from "../../generated/rest/types.gen";

  let {
    draft = $bindable(),
    enabled = $bindable(),
    disabled = false,
  }: {
    draft: AppSettingsUpdate;
    /** Whether OvertureDB syncs its catalog; the app settings do not hold it. */
    enabled: boolean;
    /** The switch cannot change, such as while the catalog syncs. */
    disabled?: boolean;
  } = $props();
</script>

<div class="options-col">
  <label class="form-row justify-between">
    <span>Enable OvertureDB</span>
    <input type="checkbox" bind:checked={enabled} {disabled} />
  </label>
  <span class="hint"
    >Downloads the OvertureDB catalog each day, so its art, themes and No theme flags are on offer.</span
  >
  <label class="form-row justify-between">
    <span>Trust OvertureDB's No theme flag</span>
    <input type="checkbox" bind:checked={draft.overturedb_no_theme} disabled={!enabled} />
  </label>
  <span class="hint"
    >A title OvertureDB marks as having no theme music counts as complete, and theme runs skip
    it.</span
  >
  <label class="form-row justify-between">
    <span>Browse OvertureDB in the sidebar</span>
    <input type="checkbox" bind:checked={draft.overturedb_browse} disabled={!enabled} />
  </label>
  <span class="hint"
    >Lists the whole catalog beside your library, with filters for what each entry lacks, so gaps
    and mismatches are easy to spot. Edit an entry to save a draft, then contribute it to
    OvertureDB.</span
  >
</div>
