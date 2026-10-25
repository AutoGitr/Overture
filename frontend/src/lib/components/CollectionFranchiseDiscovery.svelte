<script lang="ts">
  import type { CollectionDraft } from "../utils/collectionForms.svelte";
  import CollectionDiscoveryFields from "./CollectionDiscoveryFields.svelte";
  import CollectionPolicyFields from "./CollectionPolicyFields.svelte";
  import DetailForm from "./DetailForm.svelte";
  let { editor }: { editor: CollectionDraft } = $props();
</script>

<DetailForm
  title="Franchise Discovery"
  description="Scan the selected library and create one collection per TMDB franchise. Existing collections in this group are updated on future runs."
  busy={editor.busy}
>
  {#if editor.discovery.policy.dynamic_tmdb}
    <CollectionDiscoveryFields config={editor.discovery.policy.dynamic_tmdb} />
  {/if}
  <label class="form-label">
    Sort title template
    <input
      maxlength="200"
      bind:value={editor.discovery.policy.sort_title_format}
      placeholder="+1_&#123;title&#125;"
    />
    <span class="hint"
      >Use &#123;title&#125; and &#123;group&#125; for every discovered collection.</span
    >
  </label>
  <CollectionPolicyFields policy={editor.discovery.policy} section="sync" />
</DetailForm>
