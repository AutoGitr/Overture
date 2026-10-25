<script lang="ts">
  import type { CollectionGroupPolicyInput } from "../../generated/rest/types.gen";
  let {
    policy,
    prefix = "",
    plex = false,
  }: {
    policy: Pick<
      CollectionGroupPolicyInput,
      "sync_mode" | "minimum_items" | "delete_below_minimum" | "auto_match_art" | "auto_match_theme"
    > &
      Partial<Pick<CollectionGroupPolicyInput, "collection_mode">>;
    prefix?: string;
    plex?: boolean;
  } = $props();
  const flags = [
    ["delete_below_minimum", "Below minimum", "Delete collection", "Keep collection"],
    ["auto_match_art", "Automatic artwork", "Enabled", "Disabled"],
    ["auto_match_theme", "Automatic themes", "Enabled", "Disabled"],
  ] as const;
</script>

<label class="form-label"
  >{prefix}Sync strategy
  <select bind:value={policy.sync_mode}>
    <option value={null}>Inherit default</option>
    <option value="sync">Strict sync</option>
    <option value="append">Append, keep manual members</option>
  </select>
</label>
<label class="form-label"
  >{prefix}Minimum members (blank inherits)
  <input
    type="number"
    min="1"
    max="100"
    value={policy.minimum_items ?? ""}
    oninput={(event) =>
      (policy.minimum_items = event.currentTarget.value ? event.currentTarget.valueAsNumber : null)}
  />
</label>
{#each flags as [key, label, yes, no] (key)}
  <label class="form-label"
    >{prefix}{label}
    <select bind:value={policy[key]}>
      <option value={null}>Inherit default</option>
      <option value={true}>{yes}</option>
      <option value={false}>{no}</option>
    </select>
  </label>
{/each}
{#if plex}
  <label class="form-label"
    >{prefix}Visibility
    <select bind:value={policy.collection_mode}>
      <option value={null}>Inherit global default</option>
      <option value="default">Library default</option>
      <option value="hide_items">Hide items</option>
      <option value="show_items">Show collection and items</option>
      <option value="hide">Hide collection</option>
    </select>
  </label>
{/if}
