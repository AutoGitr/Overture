<script lang="ts">
  import { flushSync, type Snippet } from "svelte";
  import ChevronDown from "@lucide/svelte/icons/chevron-down";
  let {
    title,
    description,
    children,
    collapsible = false,
    expanded = false,
    ontoggle,
  }: {
    title: string;
    description: string;
    children: Snippet;
    collapsible?: boolean;
    expanded?: boolean;
    /** Opening or closing a collapsible section. */
    ontoggle?: (open: boolean) => void;
  } = $props();
  // Memoised, so only a change of the value itself overrides what the user chose:
  // an expression such as `!!form.generator` re-runs on every edit of its source.
  let initiallyOpen = $derived(expanded);
  let open = $derived(initiallyOpen);
  const bodyId = $props.id();
</script>

<section class="detail-section" aria-label={title}>
  <header>
    <h3 class="section-heading">
      {#if collapsible}
        <button
          type="button"
          aria-expanded={open}
          aria-controls={bodyId}
          onclick={() => {
            open = !open;
            ontoggle?.(open);
          }}
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
    hidden={collapsible && !open}
    oninvalidcapture={() => {
      // Native validation focuses the invalid control before Svelte's next flush.
      flushSync(() => {
        open = true;
      });
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
