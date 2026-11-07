<script lang="ts">
  import ChevronDown from "@lucide/svelte/icons/chevron-down";
  import type { Snippet } from "svelte";
  import { getSectionView, sectionState } from "../stores/sectionState.svelte";

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

  const view = getSectionView();
  const bodyId = $props.id();
  let open = $derived(sectionState.isOpen(view, label, true));
</script>

<section class="option-card filter-section" aria-label={label}>
  <div class="heading-row">
    <h3 class="form-label">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={bodyId}
        onclick={() => sectionState.setOpen(view, label, !open)}
      >
        <ChevronDown size={14} class={open ? "" : "collapsed"} />{label}
      </button>
    </h3>
    {#if open}{@render control?.()}{/if}
  </div>
  <div id={bodyId} class="body" hidden={!open}>
    {@render children()}
  </div>
</section>

<style>
  .filter-section {
    --segmented-margin: 0;
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }

  h3 {
    margin: 0;
  }

  button {
    display: flex;
    align-items: center;
    gap: var(--space-1);
    padding: 0;
    border: 0;
    color: inherit;
    background: transparent;
    font: inherit;
    cursor: pointer;
  }

  button :global(.collapsed) {
    transform: rotate(-90deg);
  }

  .body {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }

  .body[hidden] {
    display: none;
  }
</style>
