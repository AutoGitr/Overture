<script lang="ts">
  import type { Snippet } from "svelte";
  import DetailSection from "./DetailSection.svelte";

  let {
    title,
    description,
    busy,
    children,
  }: {
    title: string;
    description: string;
    busy: boolean;
    children: Snippet;
  } = $props();
</script>

<DetailSection {title} {description} --section-padding="0">
  <fieldset disabled={busy}>
    <legend class="sr-only">{title}</legend>
    <div class="fields">{@render children()}</div>
  </fieldset>
</DetailSection>

<style>
  fieldset {
    margin: 0;
    padding: 0;
    border: 0;
    min-width: 0;
  }
  .fields {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(100%, 320px), 1fr));
    align-items: start;
    gap: var(--space-4);
    padding: var(--space-4);
  }
  .fields :global(.form-label) {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    min-width: 0;
  }
  .fields :global(.form-wide) {
    grid-column: 1 / -1;
  }
</style>
