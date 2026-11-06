<script lang="ts">
  import { createQuery } from "@tanstack/svelte-query";
  import {
    listCollectionGroupsOptions,
    listCollectionsOptions,
  } from "../../generated/rest/@tanstack/svelte-query.gen";

  import { CollectionGroupActions } from "../utils/collectionGroups.svelte";
  import DetailForm from "./DetailForm.svelte";
  import FieldRow from "./FieldRow.svelte";
  import PendingButton from "./PendingButton.svelte";

  let {
    group,
    onrename,
    ondelete,
  }: {
    group: string;
    onrename: (name: string) => void;
    ondelete: () => void;
  } = $props();
  const actions = new CollectionGroupActions(
    () => group,
    () => others,
    () => members,
  );
  const groups = createQuery(() => listCollectionGroupsOptions());
  const collections = createQuery(() => listCollectionsOptions());
  let members = $derived(
    collections.data?.filter((row) => row.managed && row.collection_group === group).length ??
      null,
  );
  const id = $props.id();
  let others = $derived((groups.data ?? []).filter((name) => name !== group));
</script>

<DetailForm
  title="Rename or delete"
  description="Media files are always kept."
  busy={actions.busy}
  collapsible
>
  <FieldRow label="Group name" for={`${id}-name`}>
    <input id={`${id}-name`} maxlength="200" bind:value={actions.name} />
  </FieldRow>
  <div class="actions-row">
    <PendingButton
      class="btn btn-danger actions-start"
      pending={actions.deleting}
      pendingLabel="Deleting..."
      onclick={async () => {
        if (await actions.delete()) ondelete();
      }}>Delete group</PendingButton
    >
    <button
      class="btn btn-secondary"
      type="button"
      disabled={!actions.name.trim() || actions.name.trim() === group}
      onclick={async () => {
        const name = await actions.rename();
        if (name) onrename(name);
      }}>Rename</button
    >
  </div>
</DetailForm>
