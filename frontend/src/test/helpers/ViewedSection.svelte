<script lang="ts">
  import type { ComponentProps } from "svelte";
  import DetailSection from "../../lib/components/DetailSection.svelte";
  import { setSectionView } from "../../lib/stores/sectionState.svelte";

  /** A section in the named view, as a view root provides it. */
  let { view, ...props }: ComponentProps<typeof DetailSection> & { view: string } = $props();
  setSectionView(view);
</script>

<DetailSection {...props} />
