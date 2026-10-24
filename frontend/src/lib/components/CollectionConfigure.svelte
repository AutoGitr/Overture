<script lang="ts">
  import type { CollectionDetail, MediaItemRead } from "../../generated/rest/types.gen";
  import type { CollectionEditor } from "../utils/collectionForms.svelte";
  import CollectionSettings from "./CollectionSettings.svelte";
  import CollectionRulePanel from "./CollectionRulePanel.svelte";
  import CollectionMatchPanel from "./CollectionMatchPanel.svelte";
  import CollectionMembers from "./CollectionMembers.svelte";
  import DetailSection from "./DetailSection.svelte";

  let {
    collection,
    editor,
    libraryItems,
    groups,
    formId,
  }: {
    collection: CollectionDetail;
    editor: CollectionEditor;
    libraryItems: MediaItemRead[];
    groups: string[];
    formId: string;
  } = $props();
</script>

<form
  id={formId}
  aria-label="Configure collection"
  onsubmit={(event) => {
    event.preventDefault();
    void editor.save();
  }}
>
  <section id={`${formId}-general`} aria-label="General" tabindex="-1">
    <CollectionSettings {editor} {groups} />
  </section>
  <section id={`${formId}-builder`} aria-label="Builder" tabindex="-1">
    <CollectionRulePanel {editor} />
  </section>
</form>
{#if collection.media_type === "movie"}<CollectionMatchPanel {collection} />{/if}
<section id={`${formId}-members`} aria-label="Resolved members" tabindex="-1">
  <CollectionMembers members={collection.members} {editor} {libraryItems} />
</section>
<DetailSection
  title="Danger Zone"
  description="Deleting this collection preserves its underlying movies, shows and media files."
>
  <button
    type="button"
    class="btn btn-danger"
    disabled={editor.busy}
    onclick={() => void editor.delete()}>Delete collection</button
  >
</DetailSection>

<style>
  form {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
  }
  section {
    scroll-margin-block: var(--space-4);
  }
</style>
