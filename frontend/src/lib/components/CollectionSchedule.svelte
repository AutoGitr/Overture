<script lang="ts">
  import type { CollectionDraft } from "../utils/collectionDraft.svelte";
  import type { CollectionEditor } from "../utils/collectionEditor.svelte";
  import { formPolicy } from "../utils/collectionFormShared.svelte";
  import CollectionScheduleFields from "./CollectionScheduleFields.svelte";
  import DetailForm from "./DetailForm.svelte";

  let { editor }: { editor: CollectionDraft | CollectionEditor } = $props();
  let policy = $derived(formPolicy(editor));
</script>

<DetailForm
  collapsible
  title="Active dates"
  description="When the collection is on the server each year."
  busy={editor.busy}
  disabled={!editor.libraryIds.length}
>
  <CollectionScheduleFields
    bind:policy
    level="collection"
    defaults={editor.defaults.data}
  />
</DetailForm>
