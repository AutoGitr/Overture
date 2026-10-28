<script lang="ts">
  import type { CatalogEntryRow } from "../../generated/rest/types.gen";
  import { confirmAction, createNotifier } from "../stores/notificationState.svelte";
  import { discardDrafts } from "../utils/catalogDrafts";
  import { errorMessage } from "../utils/errors";

  /** Operations on the catalog entries the filters and search match. */
  let { entries }: { entries: CatalogEntryRow[] } = $props();

  let drafted = $derived(entries.filter((entry) => entry.has_draft));
  let busy = $state(false);
  const feedback = createNotifier();

  async function discard() {
    if (busy || !drafted.length) return;
    const confirmed = await confirmAction({
      title: `Discard ${drafted.length} drafts?`,
      message: "The local changes to these catalog entries are removed. OvertureDB is unchanged.",
      confirmLabel: "Discard drafts",
      destructive: true,
    });
    if (!confirmed) return;
    busy = true;
    feedback.clear();
    try {
      feedback.success(`Discarded ${await discardDrafts(drafted)} drafts.`);
    } catch (error) {
      feedback.error(errorMessage(error, "Could not discard the drafts"));
    } finally {
      busy = false;
    }
  }
</script>

<section class="option-card" aria-label="Bulk operations">
  <h3 class="form-label">Bulk operations</h3>
  <p class="hint">For the {entries.length} entries the filters and search match.</p>
  <button
    type="button"
    class="btn btn-danger btn-sm"
    disabled={busy || !drafted.length}
    onclick={() => void discard()}>Discard drafts ({drafted.length})</button
  >
</section>
