<script lang="ts">
  import type { Snippet } from "svelte";
  import { getSectionView, sectionState } from "../stores/sectionState.svelte";
  import Disclosure from "./Disclosure.svelte";

  let {
    label,
    description,
    children,
  }: {
    label: string;
    /** What the section applies to, under its heading. */
    description?: string;
    children: Snippet;
  } = $props();

  const view = getSectionView();
  let open = $derived(sectionState.isOpen(view, label, true));
</script>

<section class="filter-section" aria-label={label}>
  <Disclosure
    heading
    title={label}
    {open}
    ontoggle={(value) => sectionState.setOpen(view, label, value)}
    {description}
    --disclosure-padding="var(--space-3) var(--popup-pad)"
    --disclosure-body-padding="0 var(--popup-pad) var(--space-3)"
    --disclosure-hover="var(--bg-hover)"
    --disclosure-radius="0"
  >
    {@render children()}
  </Disclosure>
</section>

<style>
  /* The toggle spans the column edge to edge, so the section gives up its padding. */
  .filter-section {
    --card-padding: 0;
    --segmented-margin: 0;
  }
</style>
