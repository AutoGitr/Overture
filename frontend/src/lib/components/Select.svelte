<script module lang="ts">
  /** How long typed letters keep adding to one search, as a native select's do. */
  const TYPEAHEAD_RESET_MS = 500;
</script>

<script lang="ts" generics="T extends string | number | boolean | null = string">
  import ChevronDown from "@lucide/svelte/icons/chevron-down";
  import type { SelectOption } from "../utils/selectOptions";
  import Listbox, { type ListboxItem } from "./Listbox.svelte";

  let {
    value = $bindable(),
    options,
    id,
    label,
    placeholder = "",
    disabled = false,
    compact = false,
  }: {
    /** The chosen option's value; one no option holds, such as `null` for none yet, shows `placeholder`. */
    value?: T | null;
    options: readonly SelectOption<T>[];
    id?: string;
    /** Names the control when no external `<label for>` points to `id`. */
    label?: string;
    placeholder?: string;
    disabled?: boolean;
    compact?: boolean;
  } = $props();

  const listId = $props.id();
  let root: HTMLDivElement | undefined = $state();
  let button: HTMLButtonElement | undefined = $state();
  let open = $state(false);
  let active = $state(-1);
  let typed = "";
  let typedTimer: ReturnType<typeof setTimeout> | undefined;

  /** Open with no options yet, the list appears as they arrive. */
  let showing = $derived(open && options.length > 0);
  let selectedIndex = $derived(options.findIndex((option) => option.value === value));
  /** Options can change while the list is open; the highlight stays within them. */
  let activeIndex = $derived(active < options.length ? active : -1);
  let items = $derived<ListboxItem[]>(
    options.map((option, index) => ({
      key: String(option.value),
      label: option.label,
      detail: option.detail,
      selected: index === selectedIndex,
      disabled: option.disabled,
      group: option.group,
    })),
  );

  /** The first enabled option from `from` on, wrapping, that `matches` accepts. */
  function nextEnabled(
    from: number,
    step: 1 | -1,
    matches: (option: SelectOption<T>) => boolean = () => true,
  ): number {
    const count = options.length;
    for (let offset = 0; offset < count; offset++) {
      const index = (((from + offset * step) % count) + count) % count;
      const option = options[index];
      if (option && !option.disabled && matches(option)) return index;
    }
    return -1;
  }

  function show(step: 1 | -1 = 1) {
    if (button?.matches(":disabled")) return;
    open = true;
    active =
      selectedIndex >= 0 && !options[selectedIndex]?.disabled
        ? selectedIndex
        : nextEnabled(step === 1 ? 0 : options.length - 1, step);
  }

  function choose(index: number) {
    const option = options[index];
    if (!option || option.disabled) return;
    open = false;
    // A function binding may decline the value, so the shown one is re-read.
    if (option.value !== value) value = option.value;
  }

  function move(step: 1 | -1) {
    if (open) active = nextEnabled(activeIndex + step, step);
    else show(step);
  }

  /** Highlights the next option whose label starts with what was just typed. */
  function typeahead(key: string) {
    clearTimeout(typedTimer);
    typedTimer = setTimeout(() => (typed = ""), TYPEAHEAD_RESET_MS);
    typed += key.toLocaleLowerCase();
    // Pressing one letter again steps through the options it starts.
    const repeated = [...typed].every((letter) => letter === typed[0]);
    const prefix = repeated ? typed.charAt(0) : typed;
    if (!open) show();
    const from = repeated ? activeIndex + 1 : Math.max(activeIndex, 0);
    const found = nextEnabled(from, 1, (option) =>
      option.label.toLocaleLowerCase().startsWith(prefix),
    );
    if (found >= 0) active = found;
  }

  /** Answers a key that moves through, picks from or closes the list; false for any other. */
  function answer(key: string): boolean {
    switch (key) {
      case "ArrowDown":
      case "ArrowUp":
        move(key === "ArrowDown" ? 1 : -1);
        return true;
      case "Home":
      case "End":
        if (!open) return false;
        active = key === "Home" ? nextEnabled(0, 1) : nextEnabled(options.length - 1, -1);
        return true;
      case "Enter":
      case " ":
        // A space continues a typed search; Enter on a closed list is the button's own.
        if (key === " " ? !!typed : !open) return false;
        if (!open) show();
        else if (activeIndex >= 0) choose(activeIndex);
        else open = false;
        return true;
      case "Escape":
        if (!open) return false;
        open = false;
        return true;
    }
    return false;
  }

  function onkeydown(event: KeyboardEvent) {
    if (event.key === "Tab") {
      open = false;
    } else if (answer(event.key)) {
      event.preventDefault();
      // Escape closes the list, not the popup it sits in.
      if (event.key === "Escape") event.stopPropagation();
    } else if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
      event.preventDefault();
      typeahead(event.key);
    }
  }
</script>

<svelte:document
  onpointerdown={(event) => {
    if (open && event.target instanceof Node && !root?.contains(event.target)) open = false;
  }}
/>

<div class={["combobox", { compact }]} bind:this={root}>
  <button
    type="button"
    role="combobox"
    class="trigger"
    bind:this={button}
    {id}
    {disabled}
    aria-label={label}
    aria-haspopup="listbox"
    aria-expanded={open}
    aria-controls={showing ? listId : undefined}
    aria-activedescendant={showing && activeIndex >= 0 ? `${listId}-${activeIndex}` : undefined}
    onclick={() => (open ? (open = false) : show())}
    {onkeydown}
  >
    <span class={["truncate", { placeholder: selectedIndex < 0 }]}
      >{options[selectedIndex]?.label ?? placeholder}</span
    >
    <ChevronDown size={14} class="chevron" />
  </button>
  {#if showing}
    <Listbox
      id={listId}
      label={label ? `${label} options` : "Options"}
      {items}
      active={activeIndex}
      anchor={button}
      onchoose={choose}
      onclose={() => (open = false)}
    />
  {/if}
</div>

<style>
  .combobox {
    position: relative;
    min-width: 0;
  }

  .trigger {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
    width: 100%;
    min-height: var(--control-height);
    padding: var(--space-2) var(--space-3);
    background-color: var(--field-bg);
    border: var(--border-muted);
    border-radius: var(--radius-sm);
    box-shadow: var(--shadow-sm);
    font-size: var(--text-sm);
    color: var(--text-primary);
    text-align: left;

    &:hover:not(:disabled, :focus-visible, [aria-expanded="true"]) {
      border-color: var(--border-hover);
    }

    &:focus-visible,
    &[aria-expanded="true"] {
      outline: none;
      border-color: var(--accent);
      box-shadow: var(--focus-ring);
    }

    &:disabled {
      opacity: 0.55;
      cursor: not-allowed;
    }
  }

  .compact .trigger {
    padding-block: var(--space-1);
    padding-inline: var(--space-2);
  }

  .placeholder {
    color: var(--text-tertiary);
  }

  .trigger :global(.chevron) {
    flex-shrink: 0;
    color: var(--text-tertiary);
  }
</style>
