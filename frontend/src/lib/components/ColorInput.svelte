<script lang="ts">
  import { normalizeHexColor } from "../utils/appearance";

  let {
    value = $bindable(),
    id,
    label,
    name,
    disabled = false,
  }: {
    value: string;
    id?: string;
    label?: string;
    name?: string;
    disabled?: boolean;
  } = $props();

  let isFocused = $state(false);
  let rawText = $state<string | null>(null);
  let initialValueOnFocus = $state("");

  let textValue = $derived(isFocused && rawText !== null ? rawText : value);
  let pickerColor = $derived(normalizeHexColor(value) ?? "#000000");

  function handlePickerInput(e: Event) {
    const target = e.target as HTMLInputElement;
    value = target.value;
  }

  function handleFocus() {
    isFocused = true;
    rawText = value;
    initialValueOnFocus = value;
  }

  function handleTextInput(e: Event) {
    const inputVal = (e.target as HTMLInputElement).value;
    rawText = inputVal;
    const normalized = normalizeHexColor(inputVal);
    if (normalized) {
      value = normalized;
    }
  }

  function handleBlur() {
    isFocused = false;
    rawText = null;
  }

  function handleKeyDown(e: KeyboardEvent) {
    if (e.key === "Enter") {
      isFocused = false;
      rawText = null;
      (e.currentTarget as HTMLInputElement).blur();
    } else if (e.key === "Escape") {
      value = initialValueOnFocus;
      isFocused = false;
      rawText = null;
      (e.currentTarget as HTMLInputElement).blur();
    }
  }
</script>

<div class="color-picker-group">
  <input
    type="color"
    class="color-input color-picker-swatch"
    value={pickerColor}
    oninput={handlePickerInput}
    aria-label={label ? `${label} picker` : "Color picker"}
    {disabled}
  />
  <input
    type="text"
    {id}
    {name}
    class="color-hex-input text-input-mono"
    value={textValue}
    onfocus={handleFocus}
    oninput={handleTextInput}
    onblur={handleBlur}
    onkeydown={handleKeyDown}
    placeholder="#000000"
    maxlength={7}
    spellcheck="false"
    autocomplete="off"
    autocorrect="off"
    autocapitalize="off"
    aria-label={label ? `${label} hex value` : "Color hex value"}
    {disabled}
  />
</div>

<style>
  .color-picker-group {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
  }

  .color-picker-swatch {
    padding: 0;
    width: 32px;
    height: 30px;
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-sm);
    background: transparent;
    cursor: pointer;
    box-sizing: border-box;
    flex-shrink: 0;
  }

  .color-picker-swatch:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 1px;
  }

  .color-picker-swatch::-webkit-color-swatch-wrapper {
    padding: 2px;
  }

  .color-picker-swatch::-webkit-color-swatch {
    border: none;
    border-radius: 2px;
  }

  .color-picker-swatch::-moz-color-swatch {
    border: none;
    border-radius: 2px;
  }

  .color-hex-input {
    width: 82px;
    padding: var(--space-1) var(--space-2);
    font-family: var(--font-mono, monospace);
    font-size: var(--text-sm);
    text-align: left;
    box-sizing: border-box;
  }
</style>
