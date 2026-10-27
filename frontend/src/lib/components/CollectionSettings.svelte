<script lang="ts">
  import type {
    CollectionFiltering,
    CollectionMode,
    CollectionOrder,
    SyncMode,
  } from "../../generated/rest/types.gen";
  import type { CollectionDraft, CollectionEditor } from "../utils/collectionForms.svelte";
  import CollectionPolicyFields from "./CollectionPolicyFields.svelte";
  import DetailForm from "./DetailForm.svelte";

  let { editor }: { editor: CollectionEditor | CollectionDraft } = $props();

  const identityId = $props.id();
  let criteria = $derived(editor.content === "criteria");
  let editable = $derived(!editor.generated && editor.criteriaEditable);
  // The rule holds the sync choices and the form the display ones, which it
  // saves to the collection and to the rule alike.
  const policy = {
    get order_type() {
      return editor.orderType;
    },
    set order_type(value: CollectionOrder | null | undefined) {
      editor.orderType = value ?? null;
    },
    get collection_mode() {
      return editor.collectionMode;
    },
    set collection_mode(value: CollectionMode | null | undefined) {
      editor.collectionMode = value ?? null;
    },
    get collection_filtering() {
      return editor.collectionFiltering;
    },
    set collection_filtering(value: CollectionFiltering | null | undefined) {
      editor.collectionFiltering = value ?? null;
    },
    get visible_home() {
      return editor.visibleHome;
    },
    set visible_home(value: boolean | null | undefined) {
      editor.visibleHome = value ?? null;
    },
    get visible_shared() {
      return editor.visibleShared;
    },
    set visible_shared(value: boolean | null | undefined) {
      editor.visibleShared = value ?? null;
    },
    get visible_library() {
      return editor.visibleLibrary;
    },
    set visible_library(value: boolean | null | undefined) {
      editor.visibleLibrary = value ?? null;
    },
    get sync_mode() {
      return editor.rule.sync_mode;
    },
    set sync_mode(value: SyncMode | null | undefined) {
      editor.rule.sync_mode = value ?? null;
    },
    get minimum_items() {
      return editor.rule.minimum_items;
    },
    set minimum_items(value: number | null | undefined) {
      editor.rule.minimum_items = value ?? null;
    },
    get delete_below_minimum() {
      return editor.rule.delete_below_minimum;
    },
    set delete_below_minimum(value: boolean | null | undefined) {
      editor.rule.delete_below_minimum = value ?? null;
    },
    get auto_match_art() {
      return editor.rule.auto_match_art;
    },
    set auto_match_art(value: boolean | null | undefined) {
      editor.rule.auto_match_art = value ?? null;
    },
    get auto_match_theme() {
      return editor.rule.auto_match_theme;
    },
    set auto_match_theme(value: boolean | null | undefined) {
      editor.rule.auto_match_theme = value ?? null;
    },
  };
</script>

<DetailForm
  collapsible
  title="Settings"
  description="Sorting, syncing and how the server shows the collection."
  busy={editor.busy}
>
  <CollectionPolicyFields
    {policy}
    defaults={editor.defaults.data}
    plex={editor.capabilities.data?.visibility ?? false}
    orders={editor.orders}
    sortHint={editor.smart
      ? "Plex sorts smart collections itself."
      : criteria
        ? "Custom keeps the order of the first list the criteria use."
        : undefined}
    sync={criteria && !editor.smart}
    seasonal={false}
  >
    {#if criteria}
      <label class="form-label">
        Limit
        <input
          type="number"
          min="1"
          max="10000"
          placeholder="All matches"
          disabled={!editable}
          value={editor.rule.limit ?? ""}
          oninput={(event) =>
            (editor.rule.limit = event.currentTarget.value
              ? event.currentTarget.valueAsNumber
              : null)}
        />
        <span class="hint">Keeps the first members in the chosen sort.</span>
      </label>
    {/if}
  </CollectionPolicyFields>
  {#if editor.mediaType === "movie"}
    <div class="form-label">
      <label for={identityId}>TMDB collection ID</label>
      <input
        id={identityId}
        type="number"
        min="1"
        step="1"
        bind:value={editor.tmdbCollectionId}
        placeholder="e.g. 86311"
      />
      <span class="hint">Used for art and themes; Content decides the members.</span>
    </div>
  {/if}
  <label class="form-label">
    Sort title
    <input
      aria-label="Sort title"
      maxlength="400"
      bind:value={editor.sortTitleFormat}
      placeholder={editor.defaults.data?.sort_title_format || editor.title}
    />
    <span class="hint"
      >Text or a template with &#123;title&#125; and &#123;group&#125;. Blank inherits.</span
    >
  </label>
  <label class="form-label form-wide">
    Summary
    <textarea
      aria-label="Summary"
      maxlength="20000"
      rows="4"
      bind:value={editor.summaryFormat}
      placeholder={editor.defaults.data?.summary_format ||
        ("collection" in editor ? (editor.collection.summary ?? "") : "")}></textarea>
    <span class="hint"
      >Text or a template with &#123;title&#125;, &#123;group&#125;, &#123;start_date&#125;,
      &#123;end_date&#125; and &#123;summary&#125; (the original). Blank inherits.</span
    >
  </label>
</DetailForm>
