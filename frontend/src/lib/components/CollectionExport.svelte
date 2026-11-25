<script lang="ts">
  import { createMutation } from "@tanstack/svelte-query";
  import { exportCollectionPresetMutation } from "../../generated/rest/@tanstack/svelte-query.gen";
  import type { PresetExport } from "../../generated/rest/types.gen";
  import { createNotifier } from "../stores/notificationState.svelte";
  import { choosableCollections, collectionGroupNames } from "../utils/collectionGroups.svelte";
  import { errorMessage } from "../utils/errors";
  import CollectionChecklist from "./CollectionChecklist.svelte";
  import ContributeIssueLink from "./ContributeIssueLink.svelte";

  const groups = collectionGroupNames(() => true);
  const collections = choosableCollections(() => true);
  let exportGroups = $state<string[]>([]);
  let exportIds = $state<number[]>([]);
  let exported = $state.raw<PresetExport | null>(null);
  const feedback = createNotifier();
  const exportRequest = createMutation(() => exportCollectionPresetMutation());

  async function exportChosen() {
    feedback.clear();
    try {
      exported = await exportRequest.mutateAsync({
        body: {
          groups: exportGroups.length ? exportGroups : null,
          collection_ids: exportIds.length ? exportIds : null,
        },
      });
    } catch (err) {
      feedback.error(errorMessage(err, "Failed to export the collections"));
      return;
    }
    if (!exported.file) return;
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(exported.file, null, 2)], { type: "application/json" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = "overture-collections.json";
    link.click();
    // Following the link resolves the blob URL at once, so the download keeps
    // the file after the URL is revoked.
    URL.revokeObjectURL(url);
  }
</script>

<div class="export">
  <p class="hint">
    Export groups, with their sets, and collections as a file. Another install fills its
    create form from it under Presets, and you can contribute it to OvertureDB as a preset.
  </p>
  <CollectionChecklist
    groups={groups()}
    choice={{ all: false, groups: exportGroups }}
    onchange={(choice) => (exportGroups = choice.all ? groups() : choice.groups)}
    collections={collections()}
    collectionIds={exportIds}
    oncollectionschange={(ids) => (exportIds = ids)}
  />
  <button
    type="button"
    class="btn btn-primary"
    disabled={exportRequest.isPending || (!exportGroups.length && !exportIds.length)}
    onclick={exportChosen}>Export</button
  >
  {#if exported}
    {#each exported.refused ?? [] as refusal (refusal.title)}
      <p class="hint">Left out {refusal.title}: {refusal.reason}</p>
    {/each}
    {#each exported.warnings ?? [] as warning (warning)}
      <p class="hint">{warning}</p>
    {/each}
    {#if exported.file}
      <p class="contribute">
        Contribute it to OvertureDB <ContributeIssueLink issue={exported.issue} />
      </p>
    {/if}
  {/if}
</div>

<style>
  .export {
    display: grid;
    gap: var(--space-3);
  }

  .export > button {
    justify-self: start;
  }

  .contribute {
    display: flex;
    align-items: center;
    gap: var(--space-2);
  }
</style>
