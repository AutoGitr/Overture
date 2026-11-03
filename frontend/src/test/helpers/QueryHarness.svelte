<script lang="ts">
  import { QueryClientProvider } from "@tanstack/svelte-query";
  import type { Snippet } from "svelte";
  import { queryClient } from "../../lib/rest/queryClient";

  let { children }: { children: Snippet } = $props();
</script>

<QueryClientProvider client={queryClient}>
  {@render children()}
</QueryClientProvider>
