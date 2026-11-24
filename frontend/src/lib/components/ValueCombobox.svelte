<script lang="ts">
  import type { CollectionFieldValue } from "../../generated/rest/types.gen";

  let {
    value = $bindable(),
    options,
    strict,
    label,
    unlisted,
    describe,
  }: {
    value: string;
    /** The values to choose from, as many as the field holds; typing narrows them. */
    options: readonly CollectionFieldValue[];
    /** Only a listed value can be held, as IDs people choose by name must be. */
    strict: boolean;
    /** Names the control for assistive technology. */
    label: string;
    /** What a strict control shows for a value no option holds. */
    unlisted: string;
    /** A line beside an option, such as how many titles hold it. */
    describe: (option: CollectionFieldValue) => string;
  } = $props();

  /** Options shown at once; a library can hold thousands of values. */
  const MAX_SHOWN = 50;
  const listId = $props.id();

  let listed = $derived(options.find((option) => option.value === value));
  /** What the input shows: the held value by name, or as typed. */
  let text = $derived(listed?.label ?? (strict ? unlisted : value));
  /** What was typed since the list opened; nothing lists every option. */
  let query = $state("");
  let open = $state(false);
  let active = $state(-1);
  let shown = $derived.by(() => {
    const folded = query.trim().toLocaleLowerCase();
    const matching = folded
      ? options.filter((option) => option.label.toLocaleLowerCase().includes(folded))
      : options;
    return matching.slice(0, MAX_SHOWN);
  });

  function show() {
    open = true;
    query = "";
    active = -1;
  }

  function choose(option: CollectionFieldValue) {
    value = option.value;
    open = false;
  }

  function type(typed: string) {
    text = typed;
    query = typed;
    open = true;
    active = -1;
    if (!strict) value = typed;
  }

  /** A strict control takes what was typed only when it names an option. */
  function settle() {
    open = false;
    if (!strict) return;
    const folded = text.trim().toLocaleLowerCase();
    const named = options.find((option) => option.label.toLocaleLowerCase() === folded);
    if (named) value = named.value;
    text = listed?.label ?? unlisted;
  }

  function onkeydown(event: KeyboardEvent) {
    switch (event.key) {
      case "ArrowDown":
      case "ArrowUp": {
        event.preventDefault();
        if (!open) show();
        const step = event.key === "ArrowDown" ? 1 : -1;
        active = shown.length ? (active + step + shown.length) % shown.length : -1;
        break;
      }
      case "Enter": {
        const option = shown[active];
        if (open && option) {
          event.preventDefault();
          choose(option);
        }
        break;
      }
      case "Escape":
        if (open) {
          event.preventDefault();
          settle();
        }
        break;
    }
  }
</script>

<div class="combobox">
  <input
    role="combobox"
    required
    aria-label={label}
    aria-autocomplete="list"
    aria-expanded={open}
    aria-controls={listId}
    aria-activedescendant={open && active >= 0 ? `${listId}-${active}` : undefined}
    placeholder={strict ? "Choose a value" : "Type or choose a value"}
    autocomplete="off"
    value={text}
    onfocus={show}
    onclick={() => open || show()}
    oninput={(event) => type(event.currentTarget.value)}
    onblur={settle}
    {onkeydown}
  />
  {#if open && shown.length}
    <ul id={listId} role="listbox" aria-label={`${label} values`}>
      {#each shown as option, index (option.value)}
        <!-- The input keeps focus and the keyboard; a press chooses before it blurs. -->
        <li
          id={`${listId}-${index}`}
          role="option"
          aria-selected={option.value === value}
          class:active={index === active}
          onpointerdown={(event) => {
            event.preventDefault();
            choose(option);
          }}
        >
          <span>{option.label}</span>
          {#if describe(option)}<span class="detail">{describe(option)}</span>{/if}
        </li>
      {/each}
    </ul>
  {/if}
</div>

<style>
  .combobox {
    position: relative;
    min-width: 0;
  }

  ul {
    position: absolute;
    inset-inline: 0;
    top: calc(100% + 2px);
    z-index: var(--z-menu);
    max-height: 16rem;
    margin: 0;
    padding: var(--space-1) 0;
    overflow-y: auto;
    list-style: none;
    background: var(--bg-elevated);
    border: var(--border-subtle);
    border-radius: var(--radius-md);
    box-shadow: var(--shadow-md);
  }

  li {
    display: flex;
    justify-content: space-between;
    gap: var(--space-2);
    padding: var(--space-1) var(--space-3);
    font-size: var(--text-sm);
    cursor: pointer;

    &:hover,
    &.active {
      background: var(--bg-hover);
    }

    &[aria-selected="true"] {
      color: var(--accent-text);
    }
  }

  .detail {
    flex-shrink: 0;
    color: var(--text-tertiary);
  }
</style>
