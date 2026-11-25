<script lang="ts">
  import { createMutation } from "@tanstack/svelte-query";
  import { adoptCollectionMutation } from "../../generated/rest/@tanstack/svelte-query.gen";
  import type { CollectionRead } from "../../generated/rest/types.gen";
  import { storeCollectionDetail } from "../rest/cache";
  import { createNotifier } from "../stores/notificationState.svelte";
  import { TEXT_LIMITS } from "../../generated/settings";
  import { groupOptions } from "../utils/collectionGroups.svelte";
  import { errorMessage } from "../utils/errors";
  import DetailForm from "./DetailForm.svelte";
  import FieldRow from "./FieldRow.svelte";
  import PendingButton from "./PendingButton.svelte";
  import ValueCombobox from "./ValueCombobox.svelte";

  let { collection, groups }: { collection: CollectionRead; groups: string[] } = $props();

  const id = $props.id();
  const request = createMutation(() => adoptCollectionMutation());
  const feedback = createNotifier();
  /** The group it joins: every collection Overture manages belongs to one. */
  let group = $state("");

  async function adopt() {
    feedback.clear();
    try {
      storeCollectionDetail(
        await request.mutateAsync({
          path: { collection_id: collection.id },
          body: { group },
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
  <FieldRow label="Group" for={`${id}-group`} hint="A new name makes a group of it.">
    <ValueCombobox
      id={`${id}-group`}
      maxlength={TEXT_LIMITS.groupName}
      placeholder="e.g. Franchises"
      options={groupOptions(groups)}
      bind:value={group}
    />
  </FieldRow>
  <div class="actions-row">
    <PendingButton
      type="button"
      class="btn btn-primary"
      pending={request.isPending}
      pendingLabel="Adopting..."
      disabled={!group.trim()}
      title={group.trim() ? undefined : "Choose a group"}
      onclick={() => void adopt()}>Adopt</PendingButton
    >
  </div>
</DetailForm>
