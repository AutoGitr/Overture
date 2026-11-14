<script lang="ts">
  import { untrack, type ComponentProps } from "svelte";
  import DetailSection from "../../lib/components/DetailSection.svelte";
  import { setSectionView } from "../../lib/stores/sectionState.svelte";

  /** A section in the named view, as a view root provides it. */
  let { view, ...props }: ComponentProps<typeof DetailSection> & { view: string } = $props();
  // A view root names its view once, as it mounts.
  setSectionView(untrack(() => view));
</script>

<DetailSection {...props} />
