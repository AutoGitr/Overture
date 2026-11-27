<script lang="ts">
  import { QueryClientProvider } from "@tanstack/svelte-query";
  import type { Snippet } from "svelte";
  import { queryClient } from "../../lib/rest/queryClient";
  import { SectionView, setSectionView } from "../../lib/stores/sectionState.svelte";

  let { children }: { children: Snippet } = $props();
  // A component tested on its own stands in a view of its own, its sections open.
  setSectionView(new SectionView(() => true));
</script>

<QueryClientProvider client={queryClient}>
  {@render children()}
</QueryClientProvider>
