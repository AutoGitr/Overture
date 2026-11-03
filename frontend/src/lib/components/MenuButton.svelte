<script lang="ts">
  import type { Snippet } from "svelte";

  let {
    label,
    title,
    menuLabel,
    active = false,
    attached = false,
    align = "left",
    resetKey,
    trigger,
    menu,
  }: {
    label: string;
    title: string;
    menuLabel: string;
    /** Highlights the button while it holds a non-default choice. */
    active?: boolean;
    /** The button sits at the start of a field rather than standing alone. */
    attached?: boolean;
    align?: "left" | "right";
    /** The menu closes when this changes, such as when navigation changes the section. */
    resetKey: string;
    trigger: Snippet;
    /** The menu's items; `close` refocuses the button when asked to. */
    menu: Snippet<[close: (refocus: boolean) => void]>;
  } = $props();

  const menuId = $props.id();
  const MENU_KEYS = ["ArrowDown", "ArrowUp", "Home", "End"];

  let root: HTMLElement;
  let button: HTMLButtonElement;
  let openFor = $state<string | null>(null);
  let open = $derived(openFor === resetKey);

  function close(refocus: boolean) {
    openFor = null;
    if (refocus) button.focus({ preventScroll: true });
  }

  /** Moves focus into the menu as it opens, onto its checked item. */
  function focusCheckedItem(element: HTMLElement) {
    element.querySelector<HTMLElement>('[aria-checked="true"]')?.focus({ preventScroll: true });
  }

  function onButtonKeydown(event: KeyboardEvent) {
    if (MENU_KEYS.includes(event.key)) {
      event.preventDefault();
      openFor = resetKey;
    }
  }

  function onMenuKeydown(event: KeyboardEvent & { currentTarget: HTMLElement }) {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      close(true);
    } else if (event.key === "Tab") {
      close(false);
    } else if (MENU_KEYS.includes(event.key)) {
      event.preventDefault();
      const items = [
        ...event.currentTarget.querySelectorAll<HTMLElement>('[role="menuitemradio"]'),
      ];
      const index = items.findIndex((item) => item === document.activeElement);
      const next =
        event.key === "Home"
          ? 0
          : event.key === "End"
            ? items.length - 1
            : (index + (event.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
      items[next]?.focus({ preventScroll: true });
    }
  }
</script>

<svelte:window
  onclick={(event) => {
    if (open && event.target instanceof Node && !root.contains(event.target)) close(false);
  }}
/>

<div class="picker" bind:this={root}>
  <button
    type="button"
    class={["trigger", { active, attached }]}
    bind:this={button}
    aria-label={label}
    aria-haspopup="menu"
    aria-controls="{menuId}-menu"
    aria-expanded={open}
    {title}
    onclick={() => (openFor = open ? null : resetKey)}
    onkeydown={onButtonKeydown}
  >
    {@render trigger()}
  </button>

  {#if open}
    <div
      id="{menuId}-menu"
      class={["menu", align]}
      role="menu"
      aria-label={menuLabel}
      tabindex="-1"
      onkeydown={onMenuKeydown}
      {@attach focusCheckedItem}
    >
      {@render menu(close)}
    </div>
  {/if}
</div>

<style>
  .picker {
    position: relative;
    flex-shrink: 0;
  }

  .trigger {
    display: flex;
    align-items: center;
    gap: 3px;
    padding: var(--space-2);
    background: transparent;
    border: var(--border-subtle);
    border-radius: var(--radius-sm);
    color: var(--text-tertiary);
    cursor: pointer;
    font-size: var(--text-xs);
    white-space: nowrap;
  }

  .trigger:hover,
  .trigger.active {
    color: var(--accent);
    background: var(--accent-muted);
    border-color: var(--accent);
  }

  .trigger.attached {
    border: none;
    border-right: var(--border-subtle);
    border-radius: var(--radius-sm) 0 0 var(--radius-sm);
  }

  .trigger.attached:hover {
    color: var(--text-primary);
    background: var(--bg-hover);
  }

  .trigger.attached.active {
    color: var(--accent);
    background: var(--accent-muted);
    border-right: var(--border-subtle);
  }

  .menu {
    position: absolute;
    top: calc(100% + 4px);
    z-index: 200;
    background: var(--bg-secondary);
    border: var(--border-accent);
    border-radius: var(--radius-sm);
    box-shadow: var(--shadow-md);
    min-width: 110px;
    max-height: 80dvh;
    overflow-x: hidden;
    overflow-y: auto;
    overscroll-behavior: contain;
    white-space: nowrap;
  }

  .left {
    left: 0;
  }

  .right {
    right: 0;
  }
</style>
