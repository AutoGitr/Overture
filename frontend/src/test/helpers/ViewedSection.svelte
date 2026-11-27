<script lang="ts">
  import { untrack, type ComponentProps } from "svelte";
  import DetailSection from "../../lib/components/DetailSection.svelte";
  import { setSectionView, type SectionView } from "../../lib/stores/sectionState.svelte";

  /** A section in the given view, as a view root provides it. */
  let { view, ...props }: ComponentProps<typeof DetailSection> & { view: SectionView } = $props();
  // A view root provides its view once, as it mounts.
  setSectionView(untrack(() => view));
</script>

<DetailSection {...props} />
