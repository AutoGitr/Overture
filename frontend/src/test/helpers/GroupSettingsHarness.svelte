<script lang="ts">
  import type { ComponentProps, Snippet } from "svelte";
  import CollectionGroupSettings from "../../lib/components/CollectionGroupSettings.svelte";

  /** The settings with the footer actions they hand to their popup. */
  let props: ComponentProps<typeof CollectionGroupSettings> = $props();
  let footer = $state<Snippet | null>(null);
</script>

<CollectionGroupSettings {...props} onfooterchange={(actions) => (footer = actions)} />
{#if footer}{@render footer()}{/if}
