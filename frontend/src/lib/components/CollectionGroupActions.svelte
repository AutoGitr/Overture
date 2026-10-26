<script lang="ts">
  import type { MediaType } from "../../generated/rest/types.gen";
  import { CollectionGroupActions } from "../utils/collectionGroups.svelte";
  import DetailForm from "./DetailForm.svelte";

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
</script>

<DetailForm
  title="Manage group"
  description="Rename the group or choose what happens to its collections when you delete it. Media files are always kept."
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
    }}>Rename group</button
  >
  <label class="form-label">
    When deleting this group
    <select bind:value={actions.removal}>
      <option value="keep">Delete group only; keep collections</option>
      <option value="overture">Delete group and collections from Overture</option>
      <option value="server">Delete group and collections from media server</option>
      <option value="both">Delete group and collections from both</option>
    </select>
  </label>
  <button
    class="btn btn-danger"
    type="button"
    onclick={async () => {
      if (await actions.delete()) ondelete();
    }}>Delete group</button
  >
</DetailForm>
