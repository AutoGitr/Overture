<script lang="ts">
  import { QueryClientProvider, type QueryClient } from "@tanstack/svelte-query";
  import type { MediaItemRead } from "../../generated/rest/types.gen";
  import Sidebar from "../../lib/components/Sidebar.svelte";

  let {
    client,
    loading = false,
    movies = [],
    totalMovies = 0,
    totalShows = 0,
    shows = [],
  }: {
    client: QueryClient;
    loading?: boolean;
    movies?: MediaItemRead[];
    totalMovies?: number;
    totalShows?: number;
    shows?: MediaItemRead[];
  } = $props();
</script>

<QueryClientProvider {client}>
  <Sidebar {loading} {movies} {totalMovies} {totalShows} {shows} />
</QueryClientProvider>
