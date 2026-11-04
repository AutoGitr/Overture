<script lang="ts">
  import { flushSync, type Snippet } from "svelte";
  import ChevronDown from "@lucide/svelte/icons/chevron-down";
  import { getSectionView, sectionState } from "../stores/sectionState.svelte";
  let {
    title,
    description,
    children,
    collapsible = false,
    expanded = false,
  }: {
    title: string;
    description: string;
    children: Snippet;
    collapsible?: boolean;
    /** Whether it starts open, until the user opens or closes it. */
    expanded?: boolean;
  } = $props();
  const view = getSectionView();
  // The store owns the choice, so neither a remount nor a new default undoes it.
  let open = $derived(!collapsible || sectionState.isOpen(view, title, expanded));
  const bodyId = $props.id();

  function setOpen(value: boolean) {
    sectionState.setOpen(view, title, value);
  }
</script>

<section class="detail-section" aria-label={title}>
  <header>
    <h3 class="section-heading">
      {#if collapsible}
        <button
          type="button"
          aria-expanded={open}
          aria-controls={bodyId}
          onclick={() => setOpen(!open)}
        >
          {title}<ChevronDown size={18} class={open ? "expanded" : ""} />
        </button>
      {:else}{title}{/if}
    </h3>
    <p class="text-muted">{description}</p>
  </header>
  <div
    id={bodyId}
    class="section-body"
    hidden={!open}
    oninvalidcapture={() => {
      // Native validation focuses the invalid control before Svelte's next flush.
      if (!open) flushSync(() => setOpen(true));
    }}
  >
    {@render children()}
  </div>
</section>

<style>
  .detail-section {
    border: var(--section-border, var(--border-subtle));
    border-bottom: var(--section-divider, var(--border-subtle));
    border-radius: var(--section-radius, var(--radius-lg));
    background: var(--section-background, var(--bg-secondary));
    overflow: hidden;
  }
  header {
    padding: var(--section-header-padding, var(--space-4));
    border-bottom: var(--section-header-border, var(--border-subtle));
  }
  h3 {
    margin-bottom: var(--space-2);
  }
  h3 button {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
    width: 100%;
    padding: 0;
    border: 0;
    color: inherit;
    background: transparent;
    font: inherit;
    text-align: left;
    cursor: pointer;
  }
  h3 button :global(.expanded) {
    transform: rotate(180deg);
  }
  p {
    margin: 0;
    font-size: var(--text-sm);
  }
  .section-body {
    padding: var(--section-padding, var(--space-4));
  }
</style>
