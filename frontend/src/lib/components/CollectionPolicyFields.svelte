<script lang="ts">
  import type {
    CollectionFiltering,
    CollectionMode,
    SyncMode,
  } from "../../generated/rest/types.gen";

  type PolicyData = {
    sync_mode?: SyncMode | null;
    minimum_items?: number | null;
    delete_below_minimum?: boolean | null;
    auto_match_art?: boolean | null;
    auto_match_theme?: boolean | null;
    delete_when_inactive?: boolean | null;
    collection_filtering?: CollectionFiltering | null;
    collection_mode?: CollectionMode | null;
    visible_shared?: boolean | null;
    visible_library?: boolean | null;
  };

  let {
    policy,
    prefix = "",
    plex = false,
    section = "all",
  }: {
    policy: PolicyData;
    prefix?: string;
    plex?: boolean;
    section?: "all" | "sync";
  } = $props();
</script>

<label class="form-label">
  {prefix}Sync strategy
  <select bind:value={policy.sync_mode}>
    <option value={null}>Inherit default</option>
    <option value="sync">Strict sync</option>
    <option value="append">Append, keep manual members</option>
  </select>
</label>

<label class="form-label">
  {prefix}Minimum members (blank inherits)
  <input
    type="number"
    min="1"
    max="100"
    value={policy.minimum_items ?? ""}
    oninput={(event) =>
      (policy.minimum_items = event.currentTarget.value ? event.currentTarget.valueAsNumber : null)}
  />
</label>

<label class="form-label">
  {prefix}Below minimum
  <select bind:value={policy.delete_below_minimum}>
    <option value={null}>Inherit default</option>
    <option value={true}>Delete collection</option>
    <option value={false}>Keep collection</option>
  </select>
</label>

<label class="form-label">
  {prefix}Automatic artwork
  <select bind:value={policy.auto_match_art}>
    <option value={null}>Inherit default</option>
    <option value={true}>Enabled</option>
    <option value={false}>Disabled</option>
  </select>
</label>

<label class="form-label">
  {prefix}Automatic themes
  <select bind:value={policy.auto_match_theme}>
    <option value={null}>Inherit default</option>
    <option value={true}>Enabled</option>
    <option value={false}>Disabled</option>
  </select>
</label>

{#if section === "all"}
  <label class="form-label">
    {prefix}When inactive (seasonal)
    <select bind:value={policy.delete_when_inactive}>
      <option value={null}>Inherit default</option>
      <option value={true}>Delete from media server</option>
      <option value={false}>Keep on media server</option>
    </select>
  </label>

  {#if plex}
    <label class="form-label">
      {prefix}Visibility mode
      <select bind:value={policy.collection_mode}>
        <option value={null}>Inherit global default</option>
        <option value="default">Library default</option>
        <option value="hide_items">Hide items</option>
        <option value="show_items">Show collection and items</option>
        <option value="hide">Hide collection</option>
      </select>
    </label>

    <label class="form-label">
      {prefix}Collection filtering
      <select bind:value={policy.collection_filtering}>
        <option value={null}>Inherit global default</option>
        <option value="admin">All users (admin-managed)</option>
        <option value="user">User library</option>
      </select>
    </label>

    <div class="options-col">
      <span class="hint">{prefix}Media server promotion</span>
      <label class="form-label">
        {prefix}Shared users
        <select bind:value={policy.visible_shared}>
          <option value={null}>Inherit default</option>
          <option value={true}>Promote to shared users</option>
          <option value={false}>Hide from shared users</option>
        </select>
      </label>
      <label class="form-label">
        {prefix}Library recommendations
        <select bind:value={policy.visible_library}>
          <option value={null}>Inherit default</option>
          <option value={true}>Promote in library recommended</option>
          <option value={false}>Hide from recommended</option>
        </select>
      </label>
    </div>
  {/if}
{/if}
