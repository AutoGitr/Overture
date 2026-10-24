<script lang="ts">
  import type { Snippet } from "svelte";
  import DetailSection from "./DetailSection.svelte";

  let {
    title,
    description,
    busy,
    onsubmit,
    children,
    actions,
  }: {
    title: string;
    description: string;
    busy: boolean;
    onsubmit: () => void;
    children: Snippet;
    actions: Snippet;
  } = $props();
</script>

<form
  class="detail-form"
  aria-label={title}
  onsubmit={(event) => {
    event.preventDefault();
    onsubmit();
  }}
>
  <DetailSection {title} {description} --section-padding="0">
    <fieldset disabled={busy}>
      <legend class="sr-only">{title}</legend>
      <div class="fields">{@render children()}</div>
      <footer>{@render actions()}</footer>
    </fieldset>
  </DetailSection>
</form>

<style>
  .detail-form {
    min-width: 0;
  }
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
  footer {
    display: flex;
    flex-wrap: wrap;
    justify-content: flex-end;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-3) var(--space-4);
    border-top: var(--border-subtle);
  }
</style>
