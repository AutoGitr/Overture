<script lang="ts">
  import { createMutation } from "@tanstack/svelte-query";
  import { adoptCollectionMutation } from "../../generated/rest/@tanstack/svelte-query.gen";
  import type { CollectionDetail } from "../../generated/rest/types.gen";
  import { storeCollectionDetail } from "../rest/cache";
  import { createNotifier } from "../stores/notificationState.svelte";
  import { UNGROUPED_GROUP } from "../../generated/settings";
  import { errorMessage } from "../utils/errors";
  import DetailForm from "./DetailForm.svelte";
  import FieldRow from "./FieldRow.svelte";
  import PendingButton from "./PendingButton.svelte";

  let { collection, groups }: { collection: CollectionDetail; groups: string[] } = $props();

  const id = $props.id();
  const request = createMutation(() => adoptCollectionMutation());
  const feedback = createNotifier();
  let group = $state(UNGROUPED_GROUP);

  async function adopt() {
    feedback.clear();
    try {
      storeCollectionDetail(
        await request.mutateAsync({
          path: { collection_id: collection.id },
          body: { group: group || null },
        }),
      );
      feedback.success(`Overture now manages ${collection.title}.`);
    } catch (error) {
      feedback.error(errorMessage(error, "Could not adopt the collection"));
    }
  }
</script>

<DetailForm
  title="Adopt"
  description="This collection was made outside Overture, so nothing here changes it until Overture adopts it."
  busy={request.isPending}
>
  <p class="hint">
    Adopting it gives it criteria that keep what it holds today; movies that all belong to one
    TMDB collection follow that collection{collection.kind === "smart"
      ? ", and the smart collection keeps its filter"
      : ""}. It can then be edited, synced and given art and a theme like any other.
  </p>
  <FieldRow label="Group" for={`${id}-group`}>
    <select id={`${id}-group`} bind:value={group}>
      {#if !groups.includes(UNGROUPED_GROUP)}<option value={UNGROUPED_GROUP}>{UNGROUPED_GROUP}</option>{/if}
      {#each groups as name (name)}<option value={name}>{name}</option>{/each}
    </select>
  </FieldRow>
  <div class="actions-row">
    <PendingButton
      type="button"
      class="btn btn-primary"
      pending={request.isPending}
      pendingLabel="Adopting..."
      onclick={() => void adopt()}>Adopt</PendingButton
    >
  </div>
</DetailForm>
