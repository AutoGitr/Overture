<script lang="ts">
  import ChevronDown from "@lucide/svelte/icons/chevron-down";
  import { flushSync, type Snippet } from "svelte";

  let {
    title,
    open,
    ontoggle,
    description,
    heading = false,
    children,
  }: {
    title: string;
    open: boolean;
    ontoggle: (open: boolean) => void;
    /** A line under the title, inside the toggle. */
    description?: string;
    /** Whether the toggle is the heading of a section. */
    heading?: boolean;
    children: Snippet;
  } = $props();

  const id = $props.id();
</script>

<!-- The whole header row is the one toggle, so any point across it opens or
     closes the body; every collapsible view is built from this. -->
<svelte:element this={heading ? "h3" : "div"} class={["disclosure-heading", { open }]}>
  <button
    type="button"
    class="toggle"
    aria-expanded={open}
    aria-controls={`${id}-body`}
    aria-labelledby={`${id}-title`}
    aria-describedby={description ? `${id}-description` : undefined}
    onclick={() => ontoggle(!open)}
  >
    <span class="text">
      <span id={`${id}-title`} class="title">{title}</span>
      {#if description}<span id={`${id}-description`} class="description">{description}</span>{/if}
    </span>
    <ChevronDown size={16} class={["chevron", { open }]} />
  </button>
</svelte:element>
<div
  id={`${id}-body`}
  class="body"
  hidden={!open}
  oninvalidcapture={() => {
    // Native validation focuses the invalid control before Svelte's next flush.
    if (!open) flushSync(() => ontoggle(true));
  }}
>
  {@render children()}
</div>

<style>
  .disclosure-heading {
    margin: 0;
    font: inherit;
  }

  /* An open disclosure may separate its header from its body. */
  .disclosure-heading.open {
    border-bottom: var(--disclosure-divider, none);
  }

  .toggle {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    width: 100%;
    padding: var(--disclosure-padding, var(--space-2) 0);
    border: 0;
    border-radius: var(--disclosure-radius, var(--radius-sm));
    color: inherit;
    background: transparent;
    font: inherit;
    text-align: left;
    cursor: pointer;
  }

  /* Touch screens keep :hover after a tap, so only pointers that hover get it. */
  @media (hover: hover) {
    .toggle:hover {
      background: var(--disclosure-hover, transparent);
    }

    .toggle:hover .title,
    .toggle:hover :global(.chevron) {
      color: var(--text-primary);
    }
  }

  .text {
    display: flex;
    flex: 1;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }

  .title {
    font-size: var(--disclosure-title-size, var(--text-sm));
    font-weight: var(--disclosure-title-weight, 600);
    color: var(--disclosure-title-color, var(--text-primary));
    overflow-wrap: anywhere;
  }

  .description {
    font-size: var(--text-xs);
    color: var(--text-tertiary);
  }

  .toggle :global(.chevron) {
    flex-shrink: 0;
    color: var(--text-tertiary);
    transform: rotate(-90deg);
    transition: transform var(--transition-fast, 0.15s);
  }

  .toggle :global(.chevron.open) {
    transform: none;
  }

  .body {
    display: flex;
    flex-direction: column;
    gap: var(--disclosure-gap, var(--space-2));
    padding: var(--disclosure-body-padding, 0);
  }

  .body[hidden] {
    display: none;
  }
</style>
