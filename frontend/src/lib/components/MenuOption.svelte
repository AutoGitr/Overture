<script lang="ts">
  import type { Snippet } from "svelte";

  let {
    checked,
    onselect,
    children,
  }: { checked: boolean; onselect: () => void; children: Snippet } = $props();
</script>

<button
  type="button"
  class="menu-option"
  role="menuitemradio"
  aria-checked={checked}
  tabindex="-1"
  onclick={onselect}
>
  {@render children()}
</button>
