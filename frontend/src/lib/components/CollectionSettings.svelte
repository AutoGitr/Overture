<script lang="ts">
  import {
    CollectionDraft,
    formPolicy,
    type CollectionEditor,
  } from "../utils/collectionForms.svelte";
  import CollectionPolicyFields from "./CollectionPolicyFields.svelte";
  import DetailForm from "./DetailForm.svelte";
  import FieldRow from "./FieldRow.svelte";

  let { editor }: { editor: CollectionEditor | CollectionDraft } = $props();

  const identityId = $props.id();
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
  disabled={!editor.libraryId}
>
  <CollectionPolicyFields
    {policy}
    level="collection"
    defaults={editor.defaults.data}
    plex={capabilities?.visibility ?? false}
    orders={editor.orders}
    sortHint={editor.smart
      ? "Plex sorts smart collections itself."
      : "Custom keeps the order of the first list the criteria use."}
    sync={!editor.smart}
    arr={capabilities?.arr ? (editor.mediaType === "movie" ? "Radarr" : "Sonarr") : null}
    memberLabels={capabilities?.member_labels ?? false}
  >
    <FieldRow
      label="Limit"
      for={`${identityId}-limit`}
      hint={linked
        ? "A collection in several libraries keeps every member."
        : "Keeps the first members in the chosen sort."}
    >
      <input
        id={`${identityId}-limit`}
        type="number"
        min="1"
        max="10000"
        placeholder="All matches"
        disabled={editor.generated || linked}
        value={editor.rule.limit ?? ""}
        oninput={(event) =>
          (editor.rule.limit = event.currentTarget.value
            ? event.currentTarget.valueAsNumber
            : null)}
      />
    </FieldRow>
  </CollectionPolicyFields>
  {#if editor.mediaType === "movie"}
    <FieldRow
      label="TMDB collection ID"
      for={identityId}
      hint="Used for art and themes; Content decides the members."
    >
      <input
        id={identityId}
        type="number"
        min="1"
        step="1"
        bind:value={editor.tmdbCollectionId}
        placeholder="e.g. 86311"
      />
    </FieldRow>
  {/if}
</DetailForm>
