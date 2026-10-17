<script lang="ts" generics="Props extends Record<string, any>">
  import { QueryClientProvider } from "@tanstack/svelte-query";
  import type { Component } from "svelte";
  import { queryClient } from "../../lib/rest/queryClient";

  let { component: Rendered, props }: { component: Component<Props>; props: Props } = $props();
</script>

<QueryClientProvider client={queryClient}>
  <Rendered {...props} />
</QueryClientProvider>
