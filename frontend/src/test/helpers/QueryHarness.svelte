<script lang="ts">
  import { QueryClientProvider } from "@tanstack/svelte-query";
  import type { Snippet } from "svelte";
  import { queryClient } from "../../lib/rest/queryClient";
  import { setSectionView } from "../../lib/stores/sectionState.svelte";

  let { children }: { children: Snippet } = $props();
  // A component tested on its own stands in its own view, as the app's views do.
  setSectionView("test");
</script>

<QueryClientProvider client={queryClient}>
  {@render children()}
</QueryClientProvider>
