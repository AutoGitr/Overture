<script lang="ts">
  import type { Snippet } from "svelte";
  import DetailSection from "./DetailSection.svelte";

  let {
    title,
    description,
    busy,
    children,
    collapsible = false,
    expanded = false,
    disabled = false,
  }: {
    title: string;
    description: string;
    busy: boolean;
    /** Nothing here applies yet, such as before a library is chosen. */
    disabled?: boolean;
    children: Snippet;
    collapsible?: boolean;
    expanded?: boolean;
  } = $props();
</script>

<DetailSection {title} {description} {collapsible} {expanded} --section-padding="0">
  <fieldset disabled={busy || disabled} class={{ unavailable: disabled }}>
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
  .unavailable {
    opacity: 0.55;
  }
  /* Settings sit in a two-column grid; everything else, such as editors, lists
     and actions, spans both columns. */
  .fields {
    --field-direction: column;
    --field-align: stretch;
    --field-input-flex: 1 1 0;
    --field-segmented-width: 100%;
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    align-items: start;
    gap: var(--space-4) var(--space-6);
    padding: var(--form-padding, var(--space-4));

    @media (max-width: 640px) {
      grid-template-columns: minmax(0, 1fr);
    }
  }
  .fields > :global(:not(.field)) {
    grid-column: 1 / -1;
    min-width: 0;
  }
  .fields :global(.form-label) {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    min-width: 0;
  }
</style>
