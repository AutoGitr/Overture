<script lang="ts">
  import { untrack, type Snippet } from "svelte";
  import { CatalogBrowsing } from "../../utils/catalogBrowsing.svelte";
  import { goToLibrary, routeScope } from "../routes";

  let { children }: { children: Snippet } = $props();

  const catalog = new CatalogBrowsing();

  // Turning browsing off, or opening a catalog link while it is off, returns to the library.
  $effect(() => {
    if (catalog.loaded && !catalog.browsable) untrack(() => goToLibrary(routeScope().tab));
  });
</script>

{#if catalog.browsable}
  {@render children()}
{/if}
