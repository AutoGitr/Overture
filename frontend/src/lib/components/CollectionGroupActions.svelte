<script lang="ts">
  import { createQuery } from "@tanstack/svelte-query";
  import { listCollectionGroupsOptions } from "../../generated/rest/@tanstack/svelte-query.gen";
  import type { MediaType } from "../../generated/rest/types.gen";

  import { CollectionGroupActions } from "../utils/collectionGroups.svelte";
  import DetailForm from "./DetailForm.svelte";
  import FieldRow from "./FieldRow.svelte";

  let {
    group,
    mediaType,
    onrename,
    ondelete,
  }: {
    group: string;
    mediaType: MediaType;
    onrename: (name: string) => void;
    ondelete: () => void;
  } = $props();
  const actions = new CollectionGroupActions(
    () => group,
    () => mediaType,
    () => others,
  );
  const groups = createQuery(() =>
    listCollectionGroupsOptions({ query: { media_type: mediaType } }),
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
  <div class="form-row">
    <button
      class="btn btn-secondary"
      type="button"
      disabled={!actions.name.trim() || actions.name.trim() === group}
      onclick={async () => {
        const name = await actions.rename();
        if (name) onrename(name);
      }}>Rename</button
    >
    <button
      class="btn btn-danger"
      type="button"
      onclick={async () => {
        if (await actions.delete()) ondelete();
      }}>Delete group</button
    >
  </div>
</DetailForm>
