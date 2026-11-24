<script lang="ts" generics="T extends { value: string; label: string }">
  import Listbox, { type ListboxItem } from "./Listbox.svelte";

  let {
    value = $bindable(),
    options,
    id,
    strict = false,
    required = true,
    maxlength,
    placeholder,
    label,
    unlisted = "",
    describe,
  }: {
    value: string;
    /** The values to choose from, as many as the field holds; typing narrows them. */
    options: readonly T[];
    id?: string;
    /** Only a listed value can be held, as IDs people choose by name must be. */
    strict?: boolean;
    required?: boolean;
    maxlength?: number;
    placeholder?: string;
    /** Names the control when no external `<label for>` points to `id`. */
    label?: string;
    /** What a strict control shows for a value no option holds. */
    unlisted?: string;
    /** A line beside an option, such as how many titles hold it. */
    describe?: (option: T) => string;
  } = $props();

  /** Options shown at once; a library can hold thousands of values. */
  const MAX_SHOWN = 50;
  const listId = $props.id();

  let input: HTMLInputElement | undefined = $state();
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
  /** The list shows while open with values to offer. */
  let showing = $derived(open && shown.length > 0);
  let items = $derived<ListboxItem[]>(
    shown.map((option) => ({
      key: option.value,
      label: option.label,
      detail: describe?.(option) || undefined,
      selected: option.value === value,
    })),
  );

  function show() {
    open = true;
    query = "";
    active = -1;
  }

  function choose(index: number) {
    const option = shown[index];
    if (!option) return;
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
        if (open && active >= 0 && shown[active]) {
          event.preventDefault();
          choose(active);
        }
        break;
      }
      case "Escape":
        if (open) {
          event.preventDefault();
          event.stopPropagation();
          settle();
        }
        break;
    }
  }
</script>

<div class="combobox">
  <input
    bind:this={input}
    {id}
    role="combobox"
    {required}
    {maxlength}
    aria-label={label}
    aria-autocomplete="list"
    aria-expanded={open}
    aria-controls={showing ? listId : undefined}
    aria-activedescendant={showing && active >= 0 ? `${listId}-${active}` : undefined}
    placeholder={placeholder ?? (strict ? "Choose a value" : "Type or choose a value")}
    autocomplete="off"
    value={text}
    onfocus={show}
    onclick={() => open || show()}
    oninput={(event) => type(event.currentTarget.value)}
    onblur={settle}
    {onkeydown}
  />
  {#if showing}
    <Listbox
      id={listId}
      label={label ? `${label} values` : "Values"}
      {items}
      {active}
      anchor={input}
      onchoose={choose}
      onclose={settle}
    />
  {/if}
</div>

<style>
  .combobox {
    position: relative;
    min-width: 0;
  }

  input {
    width: 100%;
  }
</style>
