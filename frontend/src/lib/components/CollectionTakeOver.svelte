<script lang="ts">
  import { createMutation } from "@tanstack/svelte-query";
  import { takeOverCollectionMutation } from "../../generated/rest/@tanstack/svelte-query.gen";
  import type { CollectionDetail } from "../../generated/rest/types.gen";
  import { storeCollectionDetail } from "../rest/cache";
  import { createNotifier } from "../stores/notificationState.svelte";
  import { settingsState } from "../stores/settingsState.svelte";
  import { errorMessage } from "../utils/errors";
  import DetailForm from "./DetailForm.svelte";
  import FieldRow from "./FieldRow.svelte";
  import PendingButton from "./PendingButton.svelte";

  let { collection, groups }: { collection: CollectionDetail; groups: string[] } = $props();

  const id = $props.id();
  const request = createMutation(() => takeOverCollectionMutation());
  const feedback = createNotifier();
  let group = $state("");
  let required = $derived(settingsState.current.collection_require_group);
  let blocker = $derived(required && !group ? "Choose a group: every collection needs one" : null);

  async function takeOver() {
    feedback.clear();
    try {
      storeCollectionDetail(
        await request.mutateAsync({
          path: { collection_id: collection.id },
          query: { media_type: collection.media_type },
          body: { group: group || null },
        }),
      );
      feedback.success(`Overture now manages ${collection.title}.`);
    } catch (error) {
      feedback.error(errorMessage(error, "Could not take the collection over"));
    }
  }
</script>

<DetailForm
  title="Take over"
  description="This collection was made outside Overture, so nothing here changes it until Overture takes it over."
  busy={request.isPending}
>
  <p class="hint">
    Taking it over gives it criteria that keep what it holds today; a Plex smart collection keeps
    its filter. It can then be edited, synced and given art and a theme like any other.
  </p>
  <FieldRow label="Group" for={`${id}-group`} hint={blocker ?? undefined}>
    <select id={`${id}-group`} bind:value={group}>
      <option value="" disabled={required}>{required ? "Choose a group" : "No group"}</option>
      {#each groups as name (name)}<option value={name}>{name}</option>{/each}
    </select>
  </FieldRow>
  <div>
    <PendingButton
      type="button"
      class="btn btn-primary"
      pending={request.isPending}
      pendingLabel="Taking over..."
      disabled={!!blocker}
      title={blocker ?? undefined}
      onclick={() => void takeOver()}>Take over</PendingButton
    >
  </div>
</DetailForm>
