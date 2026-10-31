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
  <label class="form-label">
    Group name
    <input maxlength="200" bind:value={actions.name} />
  </label>
  <button
    class="btn btn-secondary"
    type="button"
    disabled={!actions.name.trim() || actions.name.trim() === group}
    onclick={async () => {
      const name = await actions.rename();
      if (name) onrename(name);
    }}>Rename</button
  >
  <FieldRow label="On delete" for={`${id}-removal`}>
    <select id={`${id}-removal`} bind:value={actions.removal}>
      <option value="keep">Move its collections to Ungrouped</option>
      <option value="move" disabled={!others.length}>Move its collections to another group</option>
      <option value="overture">Remove its collections from Overture</option>
      <option value="both">Remove its collections from Overture and the server</option>
    </select>
  </FieldRow>
  {#if actions.removal === "move"}
    <FieldRow label="Move to" for={`${id}-target`}>
      <select id={`${id}-target`} bind:value={actions.target}>
        <option value="" disabled>Choose a group</option>
        {#each others as name (name)}<option value={name}>{name}</option>{/each}
      </select>
    </FieldRow>
  {/if}
  <button
    class="btn btn-danger"
    type="button"
    disabled={!!actions.blocker}
    title={actions.blocker ?? undefined}
    onclick={async () => {
      if (await actions.delete()) ondelete();
    }}>Delete group</button
  >
</DetailForm>
