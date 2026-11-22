<script lang="ts">
  import type { Snippet } from "svelte";

  let {
    checked,
    indeterminate = false,
    noun,
    disabled = false,
    ontoggle,
    children,
  }: {
    /** Whether every option is chosen, so the control offers to clear them. */
    checked: boolean;
    /** Some options, not all, are chosen. */
    indeterminate?: boolean;
    /** Names the options for assistive technology, such as "libraries". */
    noun: string;
    disabled?: boolean;
    ontoggle: (checked: boolean) => void;
    /** What the control shows in place of "Select all" or "Deselect all". */
    children?: Snippet;
  } = $props();
</script>

<label class="checkbox-group">
  <input
    type="checkbox"
    {checked}
    {indeterminate}
    {disabled}
    aria-label="{checked ? 'Deselect' : 'Select'} all {noun}"
    onchange={(event) => ontoggle(event.currentTarget.checked)}
  />
  {#if children}
    {@render children()}
  {:else}
    <span aria-hidden="true">{checked ? "Deselect all" : "Select all"}</span>
  {/if}
</label>
