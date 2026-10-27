<script lang="ts">
  import {
    formPolicy,
    type CollectionDraft,
    type CollectionEditor,
  } from "../utils/collectionForms.svelte";
  import CollectionScheduleFields from "./CollectionScheduleFields.svelte";
  import DetailForm from "./DetailForm.svelte";

  let { editor }: { editor: CollectionDraft | CollectionEditor } = $props();
  let syncs = $derived(editor.content === "criteria" && editor.criteriaEditable);
  let policy = $derived(formPolicy(editor));
</script>

<DetailForm
  collapsible
  title="Schedule"
  description={syncs
    ? "When the criteria sync, and when the collection is active each year."
    : "When the collection is active each year."}
  busy={editor.busy}
>
  <CollectionScheduleFields
    {policy}
    level="collection"
    defaults={editor.defaults.data}
    sync={syncs}
  />
</DetailForm>
