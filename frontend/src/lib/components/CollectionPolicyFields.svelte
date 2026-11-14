<script module lang="ts">
  import type {
    ArtStyle,
    AutoArt,
    CollectionFiltering,
    CollectionMode,
    CollectionOrder,
    CollectionPosterStyle,
    SyncMode,
  } from "../../generated/rest/types.gen";
  import type { PolicyData } from "../utils/collectionForms.svelte";

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
  const AUTO_ART: readonly (readonly [AutoArt, string])[] = [
    ["off", "Off"],
    ["overturedb", "OvertureDB"],
    ["tmdb", "TMDB"],
    ["overturedb_tmdb", "OvertureDB, then TMDB"],
    ["overturedb_generate", "OvertureDB, else generate"],
    ["tmdb_generate", "TMDB, else generate"],
    ["overturedb_tmdb_generate", "OvertureDB, then TMDB, else generate"],
    ["generate", "Generate"],
  ];
  const STYLES: readonly (readonly [ArtStyle, string])[] = [
    ["dark", "Dark"],
    ["light", "Light"],
    ["accent", "Accent"],
  ];
  const OVERTUREDB_POSTERS: readonly (readonly [CollectionPosterStyle, string])[] = [
    ["individual", "Individual"],
    ["consistent", "Consistent"],
  ];
  const WANTED_NOT = [
    [true, "Wanted"],
    [false, "Not needed"],
  ] as const;
  const SHOW_HIDE = [
    [true, "Show"],
    [false, "Hide"],
  ] as const;
  const REMOVE_KEEP = [
    [true, "Remove from server"],
    [false, "Keep on server"],
  ] as const;
</script>

<script lang="ts">
  import type { Snippet } from "svelte";
  import { ORDER_LABELS, sortedOrders } from "../utils/collectionCriteria";
  import FieldRow from "./FieldRow.svelte";
  import InheritedSelect from "./InheritedSelect.svelte";

  let {
    policy = $bindable(),
    level,
    defaults,
    plex = false,
    orders = [],
    sortHint,
    sync = true,
    arr = null,
    memberLabels = false,
    filtering = true,
    children,
    requests,
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
    /** Offer per-user filtering, which only Plex smart collections apply. */
    filtering?: boolean;
    /** Fields placed right after Sort, under Display. */
    children?: Snippet;
    /** Fields placed last in the Radarr and Sonarr section. */
    requests?: Snippet;
  } = $props();

  const id = $props.id();
  let inherits = $derived(level !== "global");
  let sorts = $derived(sortedOrders(orders).map((order) => [order, ORDER_LABELS[order]] as const));
</script>

{#if sync}
  <h4 class="caps-label">Membership</h4>
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
    options={REMOVE_KEEP}
    hint="Overture keeps the collection either way, and puts it back once it is large enough."
  />
  <h4 class="caps-label">Automation</h4>
  <InheritedSelect
    label="Automatic art"
    {inherits}
    bind:value={policy.auto_art}
    inherited={defaults?.auto_art}
    options={AUTO_ART}
    hint="After a sync, fills art no one chose with the best art of the first source that has any: OvertureDB's catalog art, or TMDB's art of the franchise or a listed person. Generate makes a poster with the title and a background without."
  />
  <InheritedSelect
    label="Generated colours"
    {inherits}
    bind:value={policy.generated_style}
    inherited={defaults?.generated_style}
    options={STYLES}
    hint="The colours of art Automatic art generates, and of a group's separator."
  />
  <InheritedSelect
    label="OvertureDB posters"
    {inherits}
    bind:value={policy.overturedb_posters}
    inherited={defaults?.overturedb_posters}
    options={OVERTUREDB_POSTERS}
    hint="Individual takes a TMDB collection's own OvertureDB poster. Consistent takes the one in the layout every consistent poster shares, so collections look alike; a collection without one gets no OvertureDB poster. Posters you choose are contributed as the same kind."
  />
  <InheritedSelect
    label="Background"
    {inherits}
    bind:value={policy.backgrounds}
    inherited={defaults?.backgrounds}
    options={WANTED_NOT}
    hint="Not needed: a poster completes a collection's art, and none is filled in automatically."
  />
  <InheritedSelect
    label="Automatic theme"
    {inherits}
    bind:value={policy.auto_match_theme}
    inherited={defaults?.auto_match_theme}
    options={ON_OFF}
    hint="Picks the OvertureDB theme after a sync when none is chosen."
  />
  {#if inherits && memberLabels}
    <FieldRow
      label="Member label"
      for={`${id}-member-label`}
      hint={"Members get this server label and others lose it. Text or {title} and {group}."}
    >
      <input
        id={`${id}-member-label`}
        maxlength="200"
        value={policy.member_label ?? ""}
        placeholder={defaults?.member_label || "None"}
        oninput={(event) => (policy.member_label = event.currentTarget.value || null)}
      />
    </FieldRow>
  {/if}
  {#if arr}
    <h4 class="caps-label">{arr}</h4>
    <InheritedSelect
      label="Request missing"
      {inherits}
      bind:value={policy.request_missing}
      inherited={defaults?.request_missing}
      options={ON_OFF}
      hint={`After a sync, asks ${arr} for list titles the library lacks, and tags each title it adds overture.`}
    />
    {#if inherits}
      <FieldRow
        label={`${arr} tag`}
        for={`${id}-arr-tag`}
        hint={`Members get this ${arr} tag; other titles lose it unless a collection with the same tag holds them. Text or {title} and {group}, written as a-z, 0-9 and -; overture is Overture's own.`}
      >
        <input
          id={`${id}-arr-tag`}
          maxlength="200"
          value={policy.arr_tag ?? ""}
          placeholder={defaults?.arr_tag || "None"}
          oninput={(event) => (policy.arr_tag = event.currentTarget.value || null)}
        />
      </FieldRow>
    {/if}
    {@render requests?.()}
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
  {#if filtering}
    <InheritedSelect
      label="Collection filtering"
      {inherits}
      bind:value={policy.collection_filtering}
      inherited={defaults?.collection_filtering}
      options={FILTERINGS}
      hint="Smart collections only: User's library evaluates the filter for each user, such as Unplayed. Regular collections show everyone the same members."
    />
  {/if}
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
<FieldRow
  label="Sort title"
  for={`${id}-sort-title`}
  hint={"Text or a template with {title} and {group}, such as 01_{title}."}
>
  <input
    id={`${id}-sort-title`}
    maxlength="400"
    value={policy.sort_title_format ?? ""}
    placeholder={defaults?.sort_title_format || (inherits ? "Default" : "The server's")}
    oninput={(event) => (policy.sort_title_format = event.currentTarget.value || null)}
  />
</FieldRow>
<div class="summary-field">
  <label class="summary-label" for={`${id}-summary`}>Summary</label>
  <textarea
    id={`${id}-summary`}
    maxlength="20000"
    rows="3"
    value={policy.summary_format ?? ""}
    placeholder={defaults?.summary_format || (inherits ? "Default" : "The server's")}
    oninput={(event) => (policy.summary_format = event.currentTarget.value || null)}
  ></textarea>
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

  .summary-field {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    min-width: 0;
  }

  .summary-label {
    font-size: var(--text-sm);
    font-weight: 500;
    color: var(--text-secondary);
  }
</style>
