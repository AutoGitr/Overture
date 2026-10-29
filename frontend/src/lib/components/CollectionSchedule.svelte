<script lang="ts">
  import {
    formPolicy,
    type CollectionDraft,
    type CollectionEditor,
  } from "../utils/collectionForms.svelte";
  import CollectionScheduleFields from "./CollectionScheduleFields.svelte";
  import DetailForm from "./DetailForm.svelte";

  let { editor }: { editor: CollectionDraft | CollectionEditor } = $props();
  let policy = $derived(formPolicy(editor));
</script>

<DetailForm
  collapsible
  title="Schedule"
  description="When the collection is active each year. Its group decides when it syncs."
  busy={editor.busy}
  disabled={!editor.libraryId}
>
  <CollectionScheduleFields
    {policy}
    level="collection"
    defaults={editor.defaults.data}
  />
</DetailForm>
