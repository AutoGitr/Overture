<script module lang="ts">
  import type {
    CollectionFiltering,
    CollectionMode,
    CollectionOrder,
    SyncMode,
  } from "../../generated/rest/types.gen";

  /** Collection policy as a collection, a group and the global defaults hold it. */
  export type PolicyData = {
    sync_mode?: SyncMode | null;
    minimum_items?: number | null;
    delete_below_minimum?: boolean | null;
    auto_match_art?: boolean | null;
    auto_match_theme?: boolean | null;
    request_missing?: boolean | null;
    member_label?: string | null;
    arr_tag?: string | null;
    collection_filtering?: CollectionFiltering | null;
    collection_mode?: CollectionMode | null;
    order_type?: CollectionOrder | null;
    visible_home?: boolean | null;
    visible_shared?: boolean | null;
    visible_library?: boolean | null;
    home_order?: number | null;
    sort_title_format?: string | null;
    summary_format?: string | null;
  };

  /**
   * Where settings are edited. Global defaults always hold a value; groups and
   * collections inherit theirs with Default, and only they name a group or
   * tag their members.
   */
  export type PolicyLevel = "global" | "group" | "collection";

  const MODES: readonly (readonly [CollectionMode, string])[] = [
    ["default", "Library default"],
    ["hide_items", "Hide items"],
    ["show_items", "Show collection and items"],
    ["hide", "Hide collection"],
  ];
  const FILTERINGS: readonly (readonly [CollectionFiltering, string])[] = [
    ["admin", "Admin's library"],
    ["user", "User's library"],
  ];
  const SYNC_MODES: readonly (readonly [SyncMode, string])[] = [
    ["sync", "Sync"],
    ["append", "Append"],
  ];
  const ON_OFF = [
    [true, "On"],
    [false, "Off"],
  ] as const;
  const SHOW_HIDE = [
    [true, "Show"],
    [false, "Hide"],
  ] as const;
  const DELETE_KEEP = [
    [true, "Delete collection"],
    [false, "Keep collection"],
  ] as const;
</script>

<script lang="ts">
  import type { Snippet } from "svelte";
  import { ORDER_LABELS, sortedOrders } from "../utils/collectionCriteria";
  import FieldRow from "./FieldRow.svelte";
  import InheritedSelect from "./InheritedSelect.svelte";

  let {
    policy,
    level,
    defaults,
    plex = false,
    orders = [],
    sortHint,
    sync = true,
    arr = null,
    memberLabels = false,
    children,
  }: {
    policy: PolicyData;
    level: PolicyLevel;
    /** What Default resolves to here, named in each Default option. */
    defaults?: PolicyData;
    /** Show the visibility choices only Plex offers. */
    plex?: boolean;
    /** The orders the server offers collections of this media type. */
    orders?: CollectionOrder[];
    sortHint?: string;
    /** Show the choices that apply when Overture syncs criteria. */
    sync?: boolean;
    /** The Arr server that takes requests and tags, when one is set up. */
    arr?: string | null;
    /** The server takes labels Overture puts on members. */
    memberLabels?: boolean;
    /** Fields placed right after Sort, under Display. */
    children?: Snippet;
  } = $props();

  const id = $props.id();
  let inherits = $derived(level !== "global");
  let sorts = $derived(sortedOrders(orders).map((order) => [order, ORDER_LABELS[order]] as const));
</script>

{#if sync}
  <h4 class="caps-label">Sync</h4>
  <InheritedSelect
    label="Sync mode"
    {inherits}
    bind:value={policy.sync_mode}
    inherited={defaults?.sync_mode}
    options={SYNC_MODES}
    hint="Sync removes members that stop matching; Append keeps them."
  />

  <FieldRow label="Minimum members" for={`${id}-minimum`}>
    <input
      id={`${id}-minimum`}
      type="number"
      min="1"
      max="100"
      required={!inherits}
      value={policy.minimum_items ?? ""}
      placeholder={inherits ? `Default (${defaults?.minimum_items ?? 1})` : ""}
      oninput={(event) =>
        (policy.minimum_items = event.currentTarget.value
          ? event.currentTarget.valueAsNumber
          : null)}
    />
  </FieldRow>

  <InheritedSelect
    label="Below minimum"
    {inherits}
    bind:value={policy.delete_below_minimum}
    inherited={defaults?.delete_below_minimum}
    options={DELETE_KEEP}
  />
  <h4 class="caps-label">Automation</h4>
  <InheritedSelect
    label="Automatic art"
    {inherits}
    bind:value={policy.auto_match_art}
    inherited={defaults?.auto_match_art}
    options={ON_OFF}
    hint="Picks art after a sync when none is chosen."
  />
  <InheritedSelect
    label="Automatic theme"
    {inherits}
    bind:value={policy.auto_match_theme}
    inherited={defaults?.auto_match_theme}
    options={ON_OFF}
    hint="Picks the OvertureDB theme after a sync when none is chosen."
  />
  {#if arr}
    <InheritedSelect
      label="Request missing"
      {inherits}
      bind:value={policy.request_missing}
      inherited={defaults?.request_missing}
      options={ON_OFF}
      hint={`After a sync, asks ${arr} for list titles the library lacks.`}
    />
  {/if}
  {#if inherits && memberLabels}
    <div class="form-label">
      <label for={`${id}-member-label`}>Member label</label>
      <input
        id={`${id}-member-label`}
        maxlength="200"
        value={policy.member_label ?? ""}
        placeholder={defaults?.member_label || "None"}
        oninput={(event) => (policy.member_label = event.currentTarget.value || null)}
      />
      <span class="hint"
        >Members get this server label and others lose it. Text or &#123;title&#125; and
        &#123;group&#125;.</span
      >
    </div>
  {/if}
  {#if inherits && arr}
    <div class="form-label">
      <label for={`${id}-arr-tag`}>{arr} tag</label>
      <input
        id={`${id}-arr-tag`}
        maxlength="200"
        value={policy.arr_tag ?? ""}
        placeholder={defaults?.arr_tag || "None"}
        oninput={(event) => (policy.arr_tag = event.currentTarget.value || null)}
      />
      <span class="hint"
        >Members get this {arr} tag and others lose it. Text or &#123;title&#125; and &#123;group&#125;.</span
      >
    </div>
  {/if}
{/if}

<h4 class="caps-label">Display</h4>
<InheritedSelect
  label="Sort"
  {inherits}
  bind:value={policy.order_type}
  inherited={defaults?.order_type}
  options={sorts}
  hint={sortHint}
/>
{@render children?.()}
{#if plex}
  <InheritedSelect
    label="Collection mode"
    {inherits}
    bind:value={policy.collection_mode}
    inherited={defaults?.collection_mode}
    options={MODES}
  />
  <InheritedSelect
    label="Collection filtering"
    {inherits}
    bind:value={policy.collection_filtering}
    inherited={defaults?.collection_filtering}
    options={FILTERINGS}
    hint="User's library makes per-user smart collections such as Unplayed."
  />
  <InheritedSelect
    label="Library recommended"
    {inherits}
    bind:value={policy.visible_library}
    inherited={defaults?.visible_library}
    options={SHOW_HIDE}
  />
  <InheritedSelect
    label="Home"
    {inherits}
    bind:value={policy.visible_home}
    inherited={defaults?.visible_home}
    options={SHOW_HIDE}
  />
  <InheritedSelect
    label="Shared users' home"
    {inherits}
    bind:value={policy.visible_shared}
    inherited={defaults?.visible_shared}
    options={SHOW_HIDE}
  />
  {#if inherits && sync}
    <FieldRow
      label="Home order"
      for={`${id}-home-order`}
      hint="Promoted rows with a lower number come first."
    >
      <input
        id={`${id}-home-order`}
        type="number"
        min="1"
        max="999"
        value={policy.home_order ?? ""}
        placeholder={defaults?.home_order ? `Default (${defaults.home_order})` : "Unordered"}
        oninput={(event) =>
          (policy.home_order = event.currentTarget.value
            ? event.currentTarget.valueAsNumber
            : null)}
      />
    </FieldRow>
  {/if}
{/if}

<h4 class="caps-label">Titles</h4>
<div class="form-label">
  <label for={`${id}-sort-title`}>Sort title</label>
  <input
    id={`${id}-sort-title`}
    maxlength="400"
    value={policy.sort_title_format ?? ""}
    placeholder={defaults?.sort_title_format || (inherits ? "Default" : "The server's")}
    oninput={(event) => (policy.sort_title_format = event.currentTarget.value || null)}
  />
  <span class="hint"
    >Text or a template with &#123;title&#125; and &#123;group&#125;, such as 01_&#123;title&#125;.</span
  >
</div>
<div class="form-label">
  <label for={`${id}-summary`}>Summary</label>
  <textarea
    id={`${id}-summary`}
    maxlength="20000"
    rows="3"
    value={policy.summary_format ?? ""}
    placeholder={defaults?.summary_format || (inherits ? "Default" : "The server's")}
    oninput={(event) => (policy.summary_format = event.currentTarget.value || null)}></textarea>
  <span class="hint"
    >Text or a template with &#123;title&#125;, &#123;group&#125;, &#123;start_date&#125;,
    &#123;end_date&#125;, &#123;summary&#125; (the server's) and &#123;source_summary&#125; (the
    first list's description or person's biography).</span
  >
</div>

<style>
  h4 {
    margin: 0;
  }
</style>
