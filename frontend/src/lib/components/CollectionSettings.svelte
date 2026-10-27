<script lang="ts">
  import {
    CollectionDraft,
    formPolicy,
    type CollectionEditor,
  } from "../utils/collectionForms.svelte";
  import CollectionPolicyFields from "./CollectionPolicyFields.svelte";
  import DetailForm from "./DetailForm.svelte";

  let { editor }: { editor: CollectionEditor | CollectionDraft } = $props();

  const identityId = $props.id();
  let criteria = $derived(editor.content === "criteria");
  let editable = $derived(!editor.generated && editor.criteriaEditable);
  let capabilities = $derived(editor.capabilities.data);
  /** Collections in several libraries are a set, which keeps every member. */
  let linked = $derived(editor instanceof CollectionDraft && editor.linked);
  let policy = $derived(formPolicy(editor));
</script>

<DetailForm
  collapsible
  title="Settings"
  description="Sorting, syncing and how the server shows the collection."
  busy={editor.busy}
>
  <CollectionPolicyFields
    {policy}
    level="collection"
    defaults={editor.defaults.data}
    plex={capabilities?.visibility ?? false}
    orders={editor.orders}
    sortHint={editor.smart
      ? "Plex sorts smart collections itself."
      : criteria
        ? "Custom keeps the order of the first list the criteria use."
        : undefined}
    sync={criteria && !editor.smart}
    arr={capabilities?.arr ? (editor.mediaType === "movie" ? "Radarr" : "Sonarr") : null}
    memberLabels={capabilities?.member_labels ?? false}
  >
    {#if criteria}
      <label class="form-label">
        Limit
        <input
          type="number"
          min="1"
          max="10000"
          placeholder="All matches"
          disabled={!editable || linked}
          value={editor.rule.limit ?? ""}
          oninput={(event) =>
            (editor.rule.limit = event.currentTarget.value
              ? event.currentTarget.valueAsNumber
              : null)}
        />
        <span class="hint"
          >{linked
            ? "A collection in several libraries keeps every member."
            : "Keeps the first members in the chosen sort."}</span
        >
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
</DetailForm>
