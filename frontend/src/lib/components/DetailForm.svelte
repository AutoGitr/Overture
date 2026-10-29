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
  /* One setting per row, its label beside its control, like every form. */
  .fields {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
    padding: var(--form-padding, var(--space-4));
  }
  .fields :global(.form-label) {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    min-width: 0;
  }
</style>
