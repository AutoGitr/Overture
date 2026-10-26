<script lang="ts">
  import { CollectionEditor, type CollectionDraft } from "../utils/collectionForms.svelte";
  import { ORDER_LABELS } from "../utils/collectionCriteria";
  import DetailForm from "./DetailForm.svelte";
  import CollectionPolicyFields from "./CollectionPolicyFields.svelte";
  import CriteriaEditor from "./CriteriaEditor.svelte";
  import SegmentedControl from "./SegmentedControl.svelte";

  let { editor }: { editor: CollectionEditor | CollectionDraft } = $props();

  const CONTENT = [
    ["manual", "Chosen by hand"],
    ["criteria", "Matching criteria"],
  ] as const;
  const EVALUATION = [
    ["overture", "Synced by Overture"],
    ["smart", "Plex smart collection"],
  ] as const;
  let capabilities = $derived(editor.capabilities.data);
  let editable = $derived(!editor.generated && editor.criteriaEditable);
</script>

<DetailForm
  collapsible
  expanded
  title="Content"
  description={editor.generated
    ? "The collection set of this collection's group decides its criteria. Edit the set to change them."
    : editor.content === "manual"
      ? "Members are added and ordered by hand in Members."
      : editor.smart
        ? "Plex keeps the members current and evaluates play state for each user."
        : "Overture adds the items matching the criteria and removes the rest on each sync."}
  busy={editor.busy}
>
  {#if editor instanceof CollectionEditor && !editor.generated}
    {@const form = editor}
    <div class="form-label">
      <span>Members</span>
      <SegmentedControl
        --segmented-margin="0"
        label="Members"
        options={CONTENT}
        bind:value={form.content}
      />
    </div>
  {/if}
  {#if editor.content === "criteria"}
    {#if capabilities?.smart}
      <div class="form-label">
        <span>Evaluation</span>
        <SegmentedControl
          --segmented-margin="0"
          label="Evaluation"
          options={EVALUATION}
          bind:value={
            () => (editor.rule.smart ? "smart" : "overture"),
            (value) => (editor.rule.smart = value === "smart")
          }
        />
        <span class="hint"
          >{editor.rule.smart
            ? "Live and per user, with every Plex filter. Lists and tags become Plex labels Overture keeps up to date."
            : "Uses synced metadata, so play state follows the last library sync."}</span
        >
      </div>
    {/if}
    {#if editor instanceof CollectionEditor && !editor.criteriaEditable}
      {@const form = editor}
      <div class="form-wide">
        <p class="hint">
          Plex manages this smart collection's filter. Display changes keep it; take it over to
          replace it with criteria defined here.
        </p>
        <label class="form-row">
          <input type="checkbox" bind:checked={form.manageServerFilter} />
          Replace the Plex filter with these criteria
        </label>
      </div>
    {/if}
    <fieldset class="criteria form-wide" disabled={!editable}>
      <legend class="sr-only">Criteria</legend>
      <CriteriaEditor
        group={editor.rule.criteria}
        fields={editor.fields}
        sources={capabilities?.sources ?? []}
        mediaType={editor.mediaType}
        libraryId={editor.libraryId}
        label="Criteria"
      />
    </fieldset>
    <label class="form-label">
      Sort
      <select bind:value={editor.orderType}>
        <option value={null}>Default</option>
        {#each editor.orders as order (order)}
          <option value={order}>{ORDER_LABELS[order]}</option>
        {/each}
      </select>
      <span class="hint"
        >{editor.smart
          ? "Plex sorts smart collections itself."
          : "Custom keeps the order of the first list the criteria use."}</span
      >
    </label>
    <label class="form-label">
      Limit
      <input
        type="number"
        min="1"
        max="10000"
        placeholder="All matching items"
        disabled={!editable}
        value={editor.rule.limit ?? ""}
        oninput={(event) =>
          (editor.rule.limit = event.currentTarget.value
            ? event.currentTarget.valueAsNumber
            : null)}
      />
      <span class="hint">Keep only the first items in the chosen sort.</span>
    </label>
    {#if !editor.smart}
      <CollectionPolicyFields policy={editor.rule} defaults={editor.defaults.data} section="sync" />
    {/if}
  {/if}
</DetailForm>

<style>
  .criteria {
    min-width: 0;
    margin: 0;
    padding: 0;
    border: 0;
  }
</style>
