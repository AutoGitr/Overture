<script lang="ts">
  import type { Snippet } from "svelte";
  import { getSectionView, sectionState } from "../stores/sectionState.svelte";
  import Disclosure from "./Disclosure.svelte";

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
  let open = $derived(sectionState.isOpen(view, title, expanded));
</script>

<section class="detail-section" aria-label={title}>
  {#if collapsible}
    <Disclosure
      heading
      {title}
      {description}
      {open}
      ontoggle={(value) => sectionState.setOpen(view, title, value)}
      --disclosure-padding="var(--section-header-padding, var(--space-3) var(--space-4))"
      --disclosure-body-padding="var(--section-padding, var(--space-4))"
      --disclosure-hover="var(--bg-hover)"
      --disclosure-radius="0"
      --disclosure-title-size="var(--text-lg)"
      --disclosure-gap="var(--space-3)"
      --disclosure-divider="var(--section-header-border, var(--border-subtle))"
    >
      {@render children()}
    </Disclosure>
  {:else}
    <header>
      <h3 class="title">{title}</h3>
      <p class="description">{description}</p>
    </header>
    <div class="section-body">
      {@render children()}
    </div>
  {/if}
</section>

<style>
  /* The accent rule along the top parts sections however they are framed; a
     border, unlike an inset shadow, stays above the header's hover fill. */
  .detail-section {
    border: var(--section-border, var(--border-subtle));
    border-top: 2px solid var(--section-accent, var(--accent));
    border-radius: var(--section-radius, var(--radius-lg));
    background: var(--section-background, var(--bg-secondary));
    overflow: hidden;
  }

  header {
    border-bottom: var(--section-header-border, var(--border-subtle));
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: var(--section-header-padding, var(--space-3) var(--space-4));
  }

  .title {
    margin: 0;
    font-size: var(--text-lg);
    font-weight: 600;
  }

  .description {
    margin: 0;
    font-size: var(--text-xs);
    color: var(--text-tertiary);
  }

  .section-body {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
    padding: var(--section-padding, var(--space-4));
  }
</style>
