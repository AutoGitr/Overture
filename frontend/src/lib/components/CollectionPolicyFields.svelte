<script lang="ts">
  import type { Snippet } from "svelte";
  import { ORDER_LABELS, sortedOrders } from "../utils/collectionCriteria";
  import type {
    CollectionFiltering,
    CollectionMode,
    CollectionOrder,
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
    order_type?: CollectionOrder | null;
    visible_home?: boolean | null;
    visible_shared?: boolean | null;
    visible_library?: boolean | null;
  };

  /**
   * The policy a collection and a group share, with the same labels in both.
   * Every choice can stay at Default to inherit.
   */
  let {
    policy,
    plex = false,
    orders = [],
    sortHint,
    sync = true,
    seasonal = true,
    defaults,
    children,
  }: {
    policy: PolicyData;
    /** Show the visibility choices only Plex offers. */
    plex?: boolean;
    /** The orders the server offers collections of this media type. */
    orders?: CollectionOrder[];
    sortHint?: string;
    /** Show the choices that apply when Overture syncs criteria. */
    sync?: boolean;
    /** Show what happens outside the active dates. */
    seasonal?: boolean;
    defaults?: PolicyData;
    /** Fields placed right after Sort. */
    children?: Snippet;
  } = $props();
</script>

<label class="form-label">
  Sort
  <select aria-label="Sort" bind:value={policy.order_type}>
    <option value={null}>Default</option>
    {#each sortedOrders(orders) as order (order)}
      <option value={order}>{ORDER_LABELS[order]}</option>
    {/each}
  </select>
  {#if sortHint}<span class="hint">{sortHint}</span>{/if}
</label>

{@render children?.()}

{#if sync}
  <label class="form-label">
    Sync mode
    <select aria-label="Sync mode" bind:value={policy.sync_mode}>
      <option value={null}>Default</option>
      <option value="sync">Sync</option>
      <option value="append">Append</option>
    </select>
    <span class="hint">Sync removes members that stop matching; Append keeps them.</span>
  </label>

  <label class="form-label">
    Minimum members
    <input
      type="number"
      min="1"
      max="100"
      value={policy.minimum_items ?? ""}
      placeholder={String(defaults?.minimum_items ?? "")}
      oninput={(event) =>
        (policy.minimum_items = event.currentTarget.value
          ? event.currentTarget.valueAsNumber
          : null)}
    />
  </label>

  <label class="form-label">
    Below minimum
    <select bind:value={policy.delete_below_minimum}>
      <option value={null}>Default</option>
      <option value={true}>Delete collection</option>
      <option value={false}>Keep collection</option>
    </select>
  </label>

  <label class="form-label">
    Automatic art
    <select bind:value={policy.auto_match_art}>
      <option value={null}>Default</option>
      <option value={true}>On</option>
      <option value={false}>Off</option>
    </select>
  </label>

  <label class="form-label">
    Automatic theme
    <select bind:value={policy.auto_match_theme}>
      <option value={null}>Default</option>
      <option value={true}>On</option>
      <option value={false}>Off</option>
    </select>
  </label>
{/if}

{#if seasonal}
  <label class="form-label">
    When inactive
    <select bind:value={policy.delete_when_inactive}>
      <option value={null}>Default</option>
      <option value={true}>Remove from server</option>
      <option value={false}>Keep on server</option>
    </select>
  </label>
{/if}

{#if plex}
  <label class="form-label">
    Collection mode
    <select bind:value={policy.collection_mode}>
      <option value={null}>Default</option>
      <option value="default">Library default</option>
      <option value="hide_items">Hide items</option>
      <option value="show_items">Show collection and items</option>
      <option value="hide">Hide collection</option>
    </select>
  </label>

  <label class="form-label">
    Collection filtering
    <select bind:value={policy.collection_filtering}>
      <option value={null}>Default</option>
      <option value="admin">Admin's library</option>
      <option value="user">User's library</option>
    </select>
  </label>

  <label class="form-label">
    Library recommended
    <select bind:value={policy.visible_library}>
      <option value={null}>Default</option>
      <option value={true}>Show</option>
      <option value={false}>Hide</option>
    </select>
  </label>
  <label class="form-label">
    Home
    <select bind:value={policy.visible_home}>
      <option value={null}>Default</option>
      <option value={true}>Show</option>
      <option value={false}>Hide</option>
    </select>
  </label>
  <label class="form-label">
    Shared users' home
    <select bind:value={policy.visible_shared}>
      <option value={null}>Default</option>
      <option value={true}>Show</option>
      <option value={false}>Hide</option>
    </select>
  </label>
{/if}
