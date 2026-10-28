<script lang="ts">
  import type { Snippet } from "svelte";

  let {
    label,
    control,
    children,
  }: {
    label: string;
    /** A control beside the heading, such as which artwork the section tests. */
    control?: Snippet;
    children: Snippet;
  } = $props();
</script>

<section class="option-card filter-section" aria-label={label}>
  <div class="heading-row">
    <h3 class="form-label">{label}</h3>
    {@render control?.()}
  </div>
  {@render children()}
</section>

<style>
  .filter-section {
    --segmented-margin: 0;
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }

  .heading-row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
  }

  h3 {
    margin: 0;
  }
</style>
