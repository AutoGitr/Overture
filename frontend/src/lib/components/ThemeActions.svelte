<script lang="ts">
  import Search from "@lucide/svelte/icons/search";
  import Trash from "@lucide/svelte/icons/trash";
  let {
    inputId,
    disabled = false,
    clearDisabled,
    onclear,
  }: {
    inputId: string;
    disabled?: boolean;
    clearDisabled: boolean;
    onclear: () => void;
  } = $props();
</script>

<button
  type="button"
  class="tab-item"
  {disabled}
  onclick={() => document.getElementById(inputId)?.focus()}
>
  <Search size={16} /><span>Search YouTube</span>
</button>
<button
  type="button"
  class="tab-item"
  aria-label="Clear theme selection"
  disabled={disabled || clearDisabled}
  onclick={onclear}
>
  <Trash size={16} /><span>Clear</span>
</button>
